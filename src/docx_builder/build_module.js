/**
 * build_module.js — Converts a JSON payload into a formatted D&D mission module .docx
 *
 * Usage: node build_module.js payload.json
 *
 * Enhanced for multi-pass generation: handles large content sections,
 * multi-line read-aloud blocks, NPC dialogue, and dense stat blocks.
 *
 * Requires: npm install docx (run once in this directory)
 */

const fs = require("fs");
const path = require("path");

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle,
  WidthType, ShadingType, PageBreak, LevelFormat, TabStopType, TabStopPosition,
} = require("docx");

// ---------------------------------------------------------------------------
// Read payload
// ---------------------------------------------------------------------------

const payloadPath = process.argv[2];
if (!payloadPath) {
  console.error("Usage: node build_module.js <payload.json>");
  process.exit(1);
}

let payload;
try {
  payload = JSON.parse(fs.readFileSync(payloadPath, "utf-8"));
} catch (e) {
  console.error(`Failed to read payload: ${e.message}`);
  process.exit(1);
}

const {
  title, faction, tier, cr, runtime, player_name, personal_for,
  reward, faction_color, sections, output_path,
} = payload;

const factionColor = (faction_color || "696969").replace(/^#/, "").slice(0, 6);

/**
 * Lighten a 6-digit hex color toward white by a factor (0 = original, 1 = white).
 * Returns a valid 6-digit hex string.
 */
function lightenColor(hex, factor) {
  hex = hex.replace(/^#/, "").slice(0, 6);
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  const lr = Math.round(r + (255 - r) * factor).toString(16).padStart(2, "0");
  const lg = Math.round(g + (255 - g) * factor).toString(16).padStart(2, "0");
  const lb = Math.round(b + (255 - b) * factor).toString(16).padStart(2, "0");
  return (lr + lg + lb).toUpperCase();
}

// ---------------------------------------------------------------------------
// Markdown → docx paragraph conversion (enhanced)
// ---------------------------------------------------------------------------

/**
 * Detect if a line is purely italic (read-aloud block).
 * Handles: *text*, _text_, and multi-line blocks that start/end with *
 */
function isReadAloud(trimmed) {
  return (trimmed.startsWith("*") && trimmed.endsWith("*") && !trimmed.startsWith("**"))
      || (trimmed.startsWith("_") && trimmed.endsWith("_") && !trimmed.startsWith("__"));
}

/**
 * Strip outer italic markers from read-aloud text.
 */
function stripItalicMarkers(text) {
  if ((text.startsWith("*") && text.endsWith("*")) || (text.startsWith("_") && text.endsWith("_"))) {
    return text.slice(1, -1).trim();
  }
  return text;
}

/**
 * Create a styled read-aloud box paragraph.
 * Parchment background, indented, italic, with a left border.
 */
function makeReadAloudParagraph(text) {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    indent: { left: 480, right: 480 },
    shading: { fill: "F5EFE0", type: ShadingType.CLEAR },
    border: {
      left: { style: BorderStyle.SINGLE, size: 6, color: factionColor, space: 8 },
    },
    children: parseInlineFormatting(text, true),
  });
}

/**
 * Create a "Read Aloud" label paragraph.
 */
function makeReadAloudLabel() {
  return new Paragraph({
    spacing: { before: 200, after: 40 },
    indent: { left: 480 },
    children: [new TextRun({
      text: "📖 READ ALOUD:",
      font: "Georgia", size: 18, bold: true, color: factionColor, italics: true,
    })],
  });
}

/**
 * Create a DM Notes box paragraph with grey background.
 */
function makeDMNoteParagraph(text) {
  return new Paragraph({
    spacing: { before: 80, after: 80 },
    indent: { left: 480, right: 480 },
    shading: { fill: "EAEAEA", type: ShadingType.CLEAR },
    border: {
      left: { style: BorderStyle.SINGLE, size: 6, color: "888888", space: 8 },
    },
    children: parseInlineFormatting(text, false),
  });
}

/**
 * Convert markdown text into an array of docx Paragraph objects.
 */
function markdownToDocx(text) {
  if (!text) return [new Paragraph({ children: [new TextRun({ text: "(No content generated)", italics: true, color: "999999", font: "Georgia", size: 22 })] })];

  const lines = text.split("\n");
  const paragraphs = [];
  let inDMNotes = false;
  let readAloudBuffer = []; // accumulate multi-line read-aloud

  function flushReadAloud() {
    if (readAloudBuffer.length === 0) return;
    paragraphs.push(makeReadAloudLabel());
    const combined = readAloudBuffer.join(" ");
    paragraphs.push(makeReadAloudParagraph(combined));
    readAloudBuffer = [];
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      // Blank line flushes any accumulated read-aloud
      flushReadAloud();
      continue;
    }

    // Track DM Notes sections
    if (trimmed.match(/^#{2,4}\s*DM\s*Notes/i)) {
      flushReadAloud();
      inDMNotes = true;
      paragraphs.push(new Paragraph({
        heading: HeadingLevel.HEADING_3,
        spacing: { before: 300, after: 120 },
        shading: { fill: "EAEAEA", type: ShadingType.CLEAR },
        children: [new TextRun({ text: trimmed.replace(/^#{2,4}\s*/, ""), bold: true, font: "Georgia", size: 24, color: "555555" })],
      }));
      continue;
    }

    // Exit DM Notes on next heading
    if (inDMNotes && trimmed.match(/^#{2,3}\s/) && !trimmed.match(/DM\s*Notes/i)) {
      inDMNotes = false;
    }

    // ## Heading 2
    if (trimmed.startsWith("## ")) {
      flushReadAloud();
      inDMNotes = false;
      paragraphs.push(new Paragraph({
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 360, after: 180 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 1, color: factionColor } },
        children: [new TextRun({ text: trimmed.slice(3).trim(), bold: true, font: "Georgia", size: 30, color: factionColor })],
      }));
      continue;
    }

    // ### Heading 3
    if (trimmed.startsWith("### ")) {
      flushReadAloud();
      paragraphs.push(new Paragraph({
        heading: HeadingLevel.HEADING_3,
        spacing: { before: 280, after: 140 },
        children: [new TextRun({ text: trimmed.slice(4).trim(), bold: true, font: "Georgia", size: 26, color: "333333" })],
      }));
      continue;
    }

    // #### Heading 4
    if (trimmed.startsWith("#### ")) {
      flushReadAloud();
      paragraphs.push(new Paragraph({
        spacing: { before: 220, after: 100 },
        children: [new TextRun({ text: trimmed.slice(5).trim(), bold: true, font: "Georgia", size: 23, color: "444444" })],
      }));
      continue;
    }

    // Horizontal rule
    if (trimmed === "---" || trimmed === "***" || trimmed === "___") {
      flushReadAloud();
      paragraphs.push(new Paragraph({
        spacing: { before: 120, after: 120 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" } },
        children: [],
      }));
      continue;
    }

    // Read-aloud text (italic full lines)
    if (isReadAloud(trimmed)) {
      readAloudBuffer.push(stripItalicMarkers(trimmed));
      continue;
    } else {
      flushReadAloud();
    }

    // Bullet list item (- text or * text, but not bold **)
    if ((trimmed.startsWith("- ") || (trimmed.startsWith("* ") && !trimmed.startsWith("**")))) {
      const bulletText = trimmed.startsWith("- ") ? trimmed.slice(2).trim() : trimmed.slice(2).trim();
      if (inDMNotes) {
        paragraphs.push(new Paragraph({
          numbering: { reference: "bullets", level: 0 },
          spacing: { after: 60 },
          shading: { fill: "EAEAEA", type: ShadingType.CLEAR },
          children: parseInlineFormatting(bulletText, false),
        }));
      } else {
        paragraphs.push(new Paragraph({
          numbering: { reference: "bullets", level: 0 },
          spacing: { after: 80 },
          children: parseInlineFormatting(bulletText, false),
        }));
      }
      continue;
    }

    // Sub-bullet (  - text or   * text)
    if (trimmed.match(/^\s{2,}-\s/) || trimmed.match(/^\s{2,}\*\s/)) {
      const subText = trimmed.replace(/^\s+[-*]\s+/, "");
      paragraphs.push(new Paragraph({
        numbering: { reference: "subbullets", level: 0 },
        spacing: { after: 60 },
        children: parseInlineFormatting(subText, false),
      }));
      continue;
    }

    // Numbered list item (1. text)
    const numMatch = trimmed.match(/^(\d+)\.\s+(.+)/);
    if (numMatch) {
      paragraphs.push(new Paragraph({
        numbering: { reference: "numbers", level: 0 },
        spacing: { after: 80 },
        children: parseInlineFormatting(numMatch[2].trim(), false),
      }));
      continue;
    }

    // Table row (| col1 | col2 |)
    if (trimmed.startsWith("|")) {
      const tableLines = [trimmed];
      while (i + 1 < lines.length && lines[i + 1].trim().startsWith("|")) {
        i++;
        tableLines.push(lines[i].trim());
      }
      const tableObj = parseMarkdownTable(tableLines);
      if (tableObj) paragraphs.push(tableObj);
      continue;
    }

    // Dialogue lines (text in quotes — style with special formatting)
    const dialogueMatch = trimmed.match(/^"(.+)"$/);

    // DM notes content
    if (inDMNotes) {
      paragraphs.push(makeDMNoteParagraph(trimmed));
      continue;
    }

    // Normal paragraph
    paragraphs.push(new Paragraph({
      spacing: { after: 120 },
      children: parseInlineFormatting(trimmed, false),
    }));
  }

  // Flush any remaining read-aloud
  flushReadAloud();

  return paragraphs;
}

/**
 * Parse inline markdown formatting: ***bold italic***, **bold**, *italic*, `code`
 * isReadAloud: if true, everything is italic by default.
 */
function parseInlineFormatting(text, isReadAloud) {
  const runs = [];
  // Extended regex to handle code backticks too
  const regex = /(`([^`]+)`|\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|\*(.+?)\*|([^`*]+))/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (match[2]) {
      // `code`
      runs.push(new TextRun({ text: match[2], font: "Consolas", size: 20, color: "8B4513",
        shading: { fill: "F0F0F0", type: ShadingType.CLEAR } }));
    } else if (match[3]) {
      // ***bold italic***
      runs.push(new TextRun({ text: match[3], bold: true, italics: true, font: "Georgia", size: 22,
        color: isReadAloud ? "444444" : undefined }));
    } else if (match[4]) {
      // **bold**
      runs.push(new TextRun({ text: match[4], bold: true, font: "Georgia", size: 22,
        color: isReadAloud ? "444444" : undefined, italics: isReadAloud }));
    } else if (match[5]) {
      // *italic*
      runs.push(new TextRun({ text: match[5], italics: true, font: "Georgia", size: 22,
        color: isReadAloud ? "444444" : "555555" }));
    } else if (match[6]) {
      // plain text
      runs.push(new TextRun({ text: match[6], font: "Georgia", size: 22,
        italics: isReadAloud, color: isReadAloud ? "444444" : undefined }));
    }
  }
  return runs.length ? runs : [new TextRun({ text, font: "Georgia", size: 22,
    italics: isReadAloud, color: isReadAloud ? "444444" : undefined })];
}

/**
 * Parse markdown table lines into a docx Table object.
 */
function parseMarkdownTable(lines) {
  const dataLines = lines.filter(l => !l.match(/^\|[\s\-:|]+\|$/));
  if (dataLines.length === 0) return null;

  const parseRow = (line) =>
    line.split("|").filter(cell => cell.trim() !== "").map(cell => cell.trim());

  const allRows = dataLines.map(parseRow);
  if (allRows.length === 0) return null;

  const colCount = Math.max(...allRows.map(r => r.length));
  const colWidth = Math.floor(9360 / colCount);
  const border = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
  const borders = { top: border, bottom: border, left: border, right: border };

  const tableRows = allRows.map((row, rowIdx) =>
    new TableRow({
      children: Array.from({ length: colCount }, (_, colIdx) => {
        const cellText = row[colIdx] || "";
        const isHeader = rowIdx === 0;
        return new TableCell({
          borders,
          width: { size: colWidth, type: WidthType.DXA },
          shading: isHeader
            ? { fill: lightenColor(factionColor, 0.85), type: ShadingType.CLEAR }  // light faction tint
            : (rowIdx % 2 === 0 ? { fill: "F8F6F0", type: ShadingType.CLEAR } : undefined), // zebra stripe
          margins: { top: 40, bottom: 40, left: 100, right: 100 },
          children: [new Paragraph({
            children: parseInlineFormatting(cellText, false).map(run => {
              // Override size for table cells
              if (run.root && run.root[1]) {
                // Just create a new TextRun with smaller size
              }
              return run;
            }),
          })],
        });
      }),
    })
  );

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: Array(colCount).fill(colWidth),
    rows: tableRows,
  });
}

// ---------------------------------------------------------------------------
// Build the document
// ---------------------------------------------------------------------------

const doc = new Document({
  styles: {
    default: {
      document: { run: { font: "Georgia", size: 22 } },
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Georgia", color: factionColor },
        paragraph: { spacing: { before: 360, after: 240 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, font: "Georgia", color: factionColor },
        paragraph: { spacing: { before: 360, after: 180 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Georgia", color: "333333" },
        paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 2 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2022",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
      {
        reference: "subbullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u25E6",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 360 } } },
        }],
      },
      {
        reference: "numbers",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
    ],
  },
  sections: [
    // ── Cover Page ──
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 2880, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      children: [
        new Paragraph({ spacing: { after: 800 }, children: [] }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 200 },
          children: [new TextRun({ text: faction.toUpperCase(), font: "Georgia", size: 28, bold: true, color: factionColor })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [new TextRun({ text: "— presents —", font: "Georgia", size: 20, italics: true, color: "888888" })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 300 },
          border: {
            top: { style: BorderStyle.SINGLE, size: 2, color: factionColor },
            bottom: { style: BorderStyle.SINGLE, size: 2, color: factionColor },
          },
          children: [new TextRun({ text: title, font: "Georgia", size: 56, bold: true, color: factionColor })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 200 },
          children: [new TextRun({
            text: `A D&D 5e 2024 Mission Module`,
            font: "Georgia", size: 24, color: "555555",
          })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [new TextRun({
            text: `Tier: ${tier.toUpperCase()}  •  Challenge Rating: ${cr}  •  Runtime: ${runtime}`,
            font: "Georgia", size: 20, color: "777777",
          })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [new TextRun({
            text: `Reward: ${reward}`,
            font: "Georgia", size: 20, color: "777777",
          })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 400 },
          children: [new TextRun({
            text: `Contract claimed by: ${player_name}${personal_for ? ` (${personal_for})` : ""}`,
            font: "Georgia", size: 24, bold: true, color: "333333",
          })],
        }),
        new Paragraph({ spacing: { after: 200 }, children: [] }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({
            text: "TOWER OF LAST CHANCE",
            font: "Georgia", size: 22, bold: true, color: "AAAAAA",
          })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({
            text: `Generated: ${new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })}`,
            font: "Georgia", size: 18, color: "BBBBBB",
          })],
        }),
      ],
    },

    // ── Main Content ──
    {
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
            children: [
              new TextRun({ text: title, font: "Georgia", size: 16, italics: true, color: "999999" }),
              new TextRun({ text: `  •  ${faction}`, font: "Georgia", size: 16, color: "BBBBBB" }),
            ],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({
              text: "Tower of Last Chance — D&D 5e 2024 — CONFIDENTIAL DM MATERIAL",
              font: "Georgia", size: 14, color: "BBBBBB",
            })],
          })],
        }),
      },
      children: [
        // Mission info header
        new Paragraph({
          spacing: { after: 80 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: factionColor } },
          children: [new TextRun({ text: title, bold: true, font: "Georgia", size: 28, color: factionColor })],
        }),
        new Paragraph({
          spacing: { after: 60 },
          children: [new TextRun({
            text: `${faction}  •  Tier: ${tier.toUpperCase()}  •  CR ${cr}  •  ${runtime}`,
            font: "Georgia", size: 20, color: "666666"
          })],
        }),
        new Paragraph({
          spacing: { after: 60 },
          children: [new TextRun({ text: `Reward: ${reward}`, font: "Georgia", size: 20, color: "666666" })],
        }),
        new Paragraph({
          spacing: { after: 240 },
          children: [new TextRun({
            text: `Claimed by: ${player_name}${personal_for ? ` (personal contract for ${personal_for})` : ""}`,
            font: "Georgia", size: 20, bold: true
          })],
        }),

        // Sections with page breaks between major acts
        ...markdownToDocx(sections.overview),
        new Paragraph({ children: [new PageBreak()] }),

        ...markdownToDocx(sections.act1),
        new Paragraph({ children: [new PageBreak()] }),

        ...markdownToDocx(sections.act2),
        new Paragraph({ children: [new PageBreak()] }),

        ...markdownToDocx(sections.act3),
        new Paragraph({ children: [new PageBreak()] }),

        ...markdownToDocx(sections.act4),
        new Paragraph({ children: [new PageBreak()] }),

        // Appendix header
        new Paragraph({
          heading: HeadingLevel.HEADING_1,
          spacing: { before: 360, after: 240 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 3, color: factionColor } },
          children: [new TextRun({ text: "APPENDICES", bold: true, font: "Georgia", size: 36, color: factionColor })],
        }),
        ...markdownToDocx(sections.appendix),
      ],
    },
  ],
});

// ---------------------------------------------------------------------------
// Write the file
// ---------------------------------------------------------------------------

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(output_path, buffer);
  console.log(`OK: ${output_path} (${Math.round(buffer.length / 1024)}KB)`);
}).catch(err => {
  console.error(`Packer error: ${err.message}`);
  process.exit(1);
});
