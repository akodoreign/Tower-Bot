#!/usr/bin/env node
/**
 * build_module_docx.js — Builds a D&D 5e mission module .docx from JSON data.
 *
 * Usage: node build_module_docx.js <input.json> <output.docx>
 *
 * The JSON file contains all the generated text content.
 * This script converts it into a professional D&D module document.
 */

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageBreak, LevelFormat, TabStopType, TabStopPosition,
} = require("docx");

// ---------------------------------------------------------------------------
// Faction colors
// ---------------------------------------------------------------------------

const FACTION_COLORS = {
  "iron fang consortium": "8B4513",
  "argent blades":        "808080",
  "wardens of ash":       "A0522D",
  "serpent choir":        "DAA520",
  "obsidian lotus":       "4B0082",
  "glass sigil":          "4682B4",
  "patchwork saints":     "8B0000",
  "adventurers' guild":   "228B22",
  "adventurers guild":    "228B22",
  "guild of ashen scrolls": "D2B48C",
  "ashen scrolls":        "D2B48C",
  "tower authority":      "2F4F4F",
  "independent":          "696969",
  "brother thane's cult": "800000",
  "brother thane":        "800000",
};

function getFactionColor(faction) {
  const key = (faction || "").toLowerCase();
  for (const [k, v] of Object.entries(FACTION_COLORS)) {
    if (key.includes(k)) return v;
  }
  return "333333";
}

// ---------------------------------------------------------------------------
// Markdown → docx paragraph converter
// ---------------------------------------------------------------------------

/**
 * Parse inline markdown (bold, italic, bold-italic) into TextRun array.
 */
function parseInline(text) {
  const runs = [];
  // Match ***bold italic***, **bold**, *italic*, and plain text
  const regex = /(\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|\*(.+?)\*|([^*]+))/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (match[2]) {
      runs.push(new TextRun({ text: match[2], bold: true, italics: true }));
    } else if (match[3]) {
      runs.push(new TextRun({ text: match[3], bold: true }));
    } else if (match[4]) {
      runs.push(new TextRun({ text: match[4], italics: true }));
    } else if (match[5]) {
      runs.push(new TextRun({ text: match[5] }));
    }
  }
  return runs.length ? runs : [new TextRun(text)];
}

/**
 * Render a stat block (multiple lines) as a parchment-colored scroll box.
 * Triggered by lines prefixed with ">> " in the markdown.
 */
function renderStatBlock(lines, factionColor) {
  const PARCHMENT = "FDF5E6";
  const BORDER_COLOR = "C8A86B";
  const paras = [];
  const nonEmpty = lines.filter(l => l.trim());
  if (nonEmpty.length === 0) return paras;

  nonEmpty.forEach((line, i) => {
    const isFirst = i === 0;
    const isLast  = i === nonEmpty.length - 1;
    const trimLine = line.trim();

    const B = (size) => ({ style: BorderStyle.SINGLE, size, color: BORDER_COLOR });
    const border = {
      left:  B(8),
      right: B(8),
      ...(isFirst ? { top:    B(6) } : {}),
      ...(isLast  ? { bottom: B(6) } : {}),
    };

    // Section separator inside stat block (--- or ───)
    if (/^[-─═]{3,}$/.test(trimLine)) {
      paras.push(new Paragraph({
        indent: { left: 360, right: 360 },
        spacing: { before: 30, after: 30 },
        border,
        shading: { type: ShadingType.CLEAR, fill: PARCHMENT },
        children: [new TextRun({ text: "──────────────────", color: "D4A96A", size: 18 })],
        alignment: AlignmentType.CENTER,
      }));
      return;
    }

    // Bold header lines (e.g. ACTIONS, TRAITS)
    const isHeader = /^\*\*(ACTIONS|BONUS ACTIONS|REACTIONS|LEGENDARY|TRAITS|FEATURES|LOOT)\**/.test(trimLine);
    paras.push(new Paragraph({
      indent: { left: 360, right: 360 },
      spacing: { before: isFirst ? 160 : (isHeader ? 60 : 20), after: isLast ? 160 : 20 },
      border,
      shading: { type: ShadingType.CLEAR, fill: PARCHMENT },
      children: parseInline(trimLine),
    }));
  });

  return paras;
}

/**
 * Convert a markdown text block into an array of docx Paragraph objects.
 */
function markdownToParagraphs(md, bulletRef, numberRef, factionColor) {
  if (!md) return [new Paragraph({ children: [new TextRun("(Content not generated)")] })];

  const lines = md.split("\n");
  const paragraphs = [];
  let tableRows = [];
  let statBlockLines = [];

  const flushStatBlock = () => {
    if (statBlockLines.length > 0) {
      paragraphs.push(...renderStatBlock(statBlockLines, factionColor));
      statBlockLines = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Stat block line — accumulate
    if (trimmed.startsWith(">> ")) {
      statBlockLines.push(trimmed.slice(3));
      continue;
    }

    // Non->> line — flush any pending stat block
    flushStatBlock();

    // Skip empty lines
    if (!trimmed) continue;

    // Table row
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      // Skip separator rows like |---|---|
      if (/^\|[\s\-:|]+\|$/.test(trimmed)) continue;

      const cells = trimmed.split("|").filter(c => c.trim()).map(c => c.trim());
      tableRows.push(cells);

      // Check if next line is NOT a table row → flush the table
      const nextLine = (lines[i + 1] || "").trim();
      if (!nextLine.startsWith("|")) {
        if (tableRows.length > 0) {
          paragraphs.push(buildTable(tableRows));
          paragraphs.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
          tableRows = [];
        }
      }
      continue;
    }

    // Flush any pending table
    if (tableRows.length > 0) {
      paragraphs.push(buildTable(tableRows));
      paragraphs.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
      tableRows = [];
    }

    // Heading 2: ## Title
    if (trimmed.startsWith("## ")) {
      paragraphs.push(new Paragraph({
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 300, after: 150 },
        children: [new TextRun({
          text: trimmed.replace(/^##\s+/, ""),
          color: factionColor,
        })],
      }));
      continue;
    }

    // Heading 3: ### Title
    if (trimmed.startsWith("### ")) {
      paragraphs.push(new Paragraph({
        heading: HeadingLevel.HEADING_3,
        spacing: { before: 240, after: 120 },
        children: [new TextRun({
          text: trimmed.replace(/^###\s+/, ""),
          color: "444444",
        })],
      }));
      continue;
    }

    // Heading 4: #### Title
    if (trimmed.startsWith("#### ")) {
      paragraphs.push(new Paragraph({
        spacing: { before: 180, after: 100 },
        children: [new TextRun({
          text: trimmed.replace(/^####\s+/, ""),
          bold: true,
          size: 24,
          color: "555555",
        })],
      }));
      continue;
    }

    // Bullet point: - text or * text
    if (/^[-*]\s+/.test(trimmed)) {
      const content = trimmed.replace(/^[-*]\s+/, "");
      paragraphs.push(new Paragraph({
        numbering: { reference: bulletRef, level: 0 },
        spacing: { after: 60 },
        children: parseInline(content),
      }));
      continue;
    }

    // Numbered list: 1. text
    if (/^\d+\.\s+/.test(trimmed)) {
      const content = trimmed.replace(/^\d+\.\s+/, "");
      paragraphs.push(new Paragraph({
        numbering: { reference: numberRef, level: 0 },
        spacing: { after: 60 },
        children: parseInline(content),
      }));
      continue;
    }

    // SIDEBAR box — right-float table (sidebar in right 40%, spacer left 60%)
    if (trimmed.startsWith("> SIDEBAR:") || trimmed.startsWith(">SIDEBAR:")) {
      const content = trimmed.replace(/^>?\s*SIDEBAR:\s*/i, "");
      const SB_WIDTH = 3600;  // ~38% of 9360 page width
      const SP_WIDTH = 5400;  // spacer
      const sideB = (sz) => ({ style: BorderStyle.SINGLE, size: sz, color: factionColor });
      const noneB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };

      const headerPara = new Paragraph({
        spacing: { before: 80, after: 60 },
        children: [new TextRun({
          text: "◆ SIDEBAR",
          bold: true,
          size: 18,
          color: factionColor,
          font: "Arial",
        })],
        shading: { type: ShadingType.CLEAR, fill: "EEF4FB" },
      });
      const contentPara = new Paragraph({
        spacing: { before: 0, after: 80 },
        children: parseInline(content),
        shading: { type: ShadingType.CLEAR, fill: "EEF4FB" },
      });

      const sidebarCell = new TableCell({
        width: { size: SB_WIDTH, type: WidthType.DXA },
        borders: {
          top:    sideB(4), bottom: sideB(4),
          left:   sideB(8), right:  sideB(4),
        },
        shading: { type: ShadingType.CLEAR, fill: "EEF4FB" },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [headerPara, contentPara],
      });
      const spacerCell = new TableCell({
        width: { size: SP_WIDTH, type: WidthType.DXA },
        borders: { top: noneB, bottom: noneB, left: noneB, right: noneB },
        children: [new Paragraph({ children: [] })],
      });
      paragraphs.push(new Table({
        width: { size: 9360, type: WidthType.DXA },
        rows: [new TableRow({ children: [spacerCell, sidebarCell] })],
      }));
      paragraphs.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
      continue;
    }

    // SNIPPET box — in-world story flavor (journal entry, rumor, notice)
    if (trimmed.startsWith("> SNIPPET:") || trimmed.startsWith(">SNIPPET:")) {
      const content = trimmed.replace(/^>?\s*SNIPPET:\s*/i, "");
      paragraphs.push(new Paragraph({
        indent: { left: 720, right: 720 },
        spacing: { before: 160, after: 60 },
        children: [new TextRun({
          text: "— — — — — — — — — —",
          color: "AAAAAA",
          size: 16,
          font: "Georgia",
        })],
        alignment: AlignmentType.CENTER,
      }));
      paragraphs.push(new Paragraph({
        indent: { left: 720, right: 720 },
        spacing: { before: 0, after: 0 },
        children: [new TextRun({
          text: content,
          italics: true,
          color: "444444",
          font: "Georgia",
          size: 21,
        })],
      }));
      paragraphs.push(new Paragraph({
        indent: { left: 720, right: 720 },
        spacing: { before: 60, after: 160 },
        children: [new TextRun({
          text: "— — — — — — — — — —",
          color: "AAAAAA",
          size: 16,
          font: "Georgia",
        })],
        alignment: AlignmentType.CENTER,
      }));
      continue;
    }

    // Read-aloud / flavor blockquote (starts with > )
    if (trimmed.startsWith("> ")) {
      const content = trimmed.replace(/^>\s*/, "");
      paragraphs.push(new Paragraph({
        indent: { left: 720, right: 720 },
        spacing: { before: 120, after: 120 },
        children: [new TextRun({
          text: content,
          italics: true,
          color: "333333",
          font: "Georgia",
        })],
        border: {
          left: { style: BorderStyle.SINGLE, size: 6, color: factionColor, space: 10 },
        },
        shading: { type: ShadingType.CLEAR, fill: "F5F0E8" },
      }));
      continue;
    }

    // Regular paragraph
    paragraphs.push(new Paragraph({
      spacing: { after: 120 },
      children: parseInline(trimmed),
    }));
  }

  // Flush any remaining stat block
  flushStatBlock();

  // Flush final table if any
  if (tableRows.length > 0) {
    paragraphs.push(buildTable(tableRows));
  }

  return paragraphs;
}

/**
 * Build a docx Table from parsed rows.
 */
function buildTable(rows) {
  if (rows.length === 0) return new Paragraph({ children: [] });

  const numCols = Math.max(...rows.map(r => r.length));
  const tableWidth = 9360; // US Letter content width
  const colWidth = Math.floor(tableWidth / numCols);

  const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
  const borders = { top: border, bottom: border, left: border, right: border };

  const docxRows = rows.map((row, rowIdx) => {
    const cells = [];
    for (let c = 0; c < numCols; c++) {
      const cellText = row[c] || "";
      const isHeader = rowIdx === 0;
      cells.push(new TableCell({
        borders,
        width: { size: colWidth, type: WidthType.DXA },
        shading: isHeader
          ? { fill: "D5E8F0", type: ShadingType.CLEAR }
          : { fill: "FFFFFF", type: ShadingType.CLEAR },
        margins: { top: 60, bottom: 60, left: 100, right: 100 },
        children: [new Paragraph({
          children: [new TextRun({
            text: cellText,
            bold: isHeader,
            size: 20,
          })],
        })],
      }));
    }
    return new TableRow({ children: cells });
  });

  return new Table({
    width: { size: tableWidth, type: WidthType.DXA },
    columnWidths: Array(numCols).fill(colWidth),
    rows: docxRows,
  });
}

// ---------------------------------------------------------------------------
// Document builder
// ---------------------------------------------------------------------------

function buildDocument(data) {
  // Null-safety: ensure all required fields have defaults
  const faction = data.faction || "Independent";
  const tier = data.tier || "Unknown";
  const title = data.title || "Untitled Mission";
  const cr = data.cr !== undefined ? data.cr : (data.metadata && data.metadata.cr !== undefined ? data.metadata.cr : "?");
  const playerLevel = data.player_level || (data.metadata && data.metadata.party_level) || "?";
  const playerCount = data.player_count || (data.metadata && data.metadata.player_count) || "4–6";
  const playerName = data.player_name || "Unclaimed";
  const reward = data.reward || "TBD";
  const generatedAt = data.generated_at || new Date().toISOString();

  const factionColor = getFactionColor(faction);
  const bulletRef = "moduleBullets";
  const numberRef = "moduleNumbers";

  // Cover page
  const coverPage = [
    new Paragraph({ spacing: { before: 3000 }, children: [] }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
      children: [new TextRun({
        text: faction.toUpperCase(),
        size: 28,
        color: factionColor,
        font: "Arial",
        bold: true,
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 100 },
      children: [new TextRun({
        text: "━━━━━━━━━━━━━━━━━━━━━━",
        color: factionColor,
        size: 20,
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 400 },
      children: [new TextRun({
        text: title,
        size: 48,
        bold: true,
        color: "222222",
        font: "Georgia",
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 100 },
      children: [new TextRun({
        text: `Tier: ${tier.toUpperCase()}  |  CR: ${cr}  |  Level: ${playerLevel}  |  Party: ${playerCount} Players`,
        size: 24,
        color: "555555",
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 100 },
      children: [new TextRun({
        text: `Estimated Runtime: ~4–5 Hours`,
        size: 22,
        color: "777777",
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
      children: [new TextRun({
        text: "━━━━━━━━━━━━━━━━━━━━━━",
        color: factionColor,
        size: 20,
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
      children: [new TextRun({
        text: `Claimed by: ${playerName}`,
        size: 26,
        italics: true,
        color: "444444",
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 100 },
      children: [new TextRun({
        text: `Reward: ${reward}`,
        size: 22,
        color: "666666",
      })],
    }),
    new Paragraph({ spacing: { before: 2000 }, children: [] }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: "D&D 5e 2024 Compatible  •  Tower of Last Chance Campaign",
        size: 18,
        color: "999999",
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: `Generated: ${new Date(generatedAt).toLocaleDateString()}`,
        size: 18,
        color: "AAAAAA",
      })],
    }),
    new Paragraph({ children: [new PageBreak()] }),
  ];

  // Content sections
  const s = data.sections || {};
  const overviewParas = markdownToParagraphs(s.overview       || s.acts_1_2 || "", bulletRef, numberRef, factionColor);
  const ch1Paras      = markdownToParagraphs(s.chapter_1      || s.acts_1_2 || "", bulletRef, numberRef, factionColor);
  const ch2Paras      = markdownToParagraphs(s.chapter_2      || s.acts_3_4 || "", bulletRef, numberRef, factionColor);
  const ch3Paras      = markdownToParagraphs(s.chapter_3      || "",               bulletRef, numberRef, factionColor);
  const ch4Paras      = markdownToParagraphs(s.chapter_4      || s.act_5_rewards || "", bulletRef, numberRef, factionColor);
  const ch5Paras      = markdownToParagraphs(s.chapter_5      || "",               bulletRef, numberRef, factionColor);

  // Section dividers
  const divider = () => new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 300, after: 300 },
    children: [new TextRun({ text: "━━━━━━━━━━", color: factionColor, size: 18 })],
  });

  // Build content: overview (DM spine) + 5 chapters
  const chapterSections = [ch1Paras, ch2Paras, ch3Paras, ch4Paras, ch5Paras].filter(p => p.length > 0);
  const allChildren = [
    ...coverPage,
    ...overviewParas,
    divider(),
    new Paragraph({ children: [new PageBreak()] }),
    ...chapterSections.flatMap((paras, i) => [
      ...paras,
      ...(i < chapterSections.length - 1 ? [divider(), new Paragraph({ children: [new PageBreak()] })] : []),
    ]),
  ];

  return new Document({
    styles: {
      default: {
        document: { run: { font: "Arial", size: 22 } },
      },
      paragraphStyles: [
        {
          id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal",
          quickFormat: true,
          run: { size: 36, bold: true, font: "Georgia", color: "222222" },
          paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 },
        },
        {
          id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal",
          quickFormat: true,
          run: { size: 30, bold: true, font: "Georgia" },
          paragraph: { spacing: { before: 300, after: 150 }, outlineLevel: 1 },
        },
        {
          id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal",
          quickFormat: true,
          run: { size: 26, bold: true, font: "Arial" },
          paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 2 },
        },
      ],
    },
    numbering: {
      config: [
        {
          reference: bulletRef,
          levels: [{
            level: 0, format: LevelFormat.BULLET, text: "\u2022",
            alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } },
          }],
        },
        {
          reference: numberRef,
          levels: [{
            level: 0, format: LevelFormat.DECIMAL, text: "%1.",
            alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } },
          }],
        },
      ],
    },
    sections: [{
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            alignment: AlignmentType.RIGHT,
            children: [new TextRun({
              text: `${title} — ${faction}`,
              size: 16,
              color: "999999",
              italics: true,
            })],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({
              text: "Tower of Last Chance — D&D 5e 2024",
              size: 16,
              color: "AAAAAA",
            })],
          })],
        }),
      },
      children: allChildren,
    }],
  });
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const [jsonPath, docxPath] = process.argv.slice(2);
  if (!jsonPath || !docxPath) {
    console.error("Usage: node build_module_docx.js <input.json> <output.docx>");
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));
  const doc = buildDocument(data);
  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(docxPath, buffer);
  console.log(`OK: ${docxPath} (${buffer.length} bytes)`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
