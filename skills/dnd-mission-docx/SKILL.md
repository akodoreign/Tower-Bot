---
name: dnd-mission-docx
description: "Use this skill whenever the user wants to generate D&D mission documents, mission briefs, campaign handouts, or any tabletop RPG content as Word (.docx) files. Triggers include: 'mission document', 'mission brief', 'mission handout', 'campaign doc', 'mission to docx', 'printable mission', 'player handout', 'session prep doc', or any request to turn mission board data into a formatted document. Also use when generating DM-facing mission prep documents, faction briefings, NPC dossiers, or session summaries as Word files. This skill knows the Tower of Last Chance campaign data format and the docx-js tooling. Always use alongside the core 'docx' skill for document creation mechanics."
---

# D&D Mission Document Generator

Generate professional, printable D&D mission documents from the Tower of Last Chance campaign data.

## IMPORTANT: Always read the docx SKILL.md first
Before creating any document, read `/mnt/skills/public/docx/SKILL.md` for the docx-js setup, validation, and formatting reference. This skill provides the D&D-specific content structure and data mapping — the docx skill provides the creation mechanics.

## Mission Data Source

Mission data lives in `campaign_docs/mission_memory.json` — a JSON array of mission objects:

```json
{
  "title": "The Serpent's Ledger",
  "faction": "Serpent Choir",
  "tier": "investigation",
  "body": "Full mission posting text...",
  "posted_at": "2026-03-18T12:00:00",
  "expires_at": "2026-04-17T12:00:00",
  "claimed": false,
  "resolved": false,
  "completed": false,
  "failed": false,
  "player_claimer": null,
  "npc_claimed": false,
  "npc_party": null,
  "personal_for": null,
  "message_id": 123456789
}
```

### Tier Hierarchy
`local` → `patrol` → `escort` → `standard` → `investigation` → `rift` → `dungeon` → `major` → `inter-guild` → `high-stakes` → `epic` → `divine` → `tower`

### Faction List
Iron Fang Consortium, Argent Blades, Wardens of Ash, Serpent Choir, Obsidian Lotus, Glass Sigil, Patchwork Saints, Adventurers' Guild, Guild of Ashen Scrolls, Tower Authority, Independent, Brother Thane's Cult

## Document Types

### 1. Mission Brief (Player-Facing)
Single-page handout suitable for printing and giving to players at the table.

**Structure:**
- **Header**: Faction crest area + "MISSION BRIEF" title + tier badge
- **Contract Title**: Bold, centered
- **Issuing Faction**: With brief faction description
- **Objective**: 2-3 sentences — what the players need to do
- **Location**: Where in the Undercity
- **Known Threats**: What to expect (without spoilers)
- **Compensation**: EC reward + any Kharma bonus
- **Time Limit**: Days remaining before contract expires
- **Special Conditions**: Any faction-specific rules or restrictions
- **Footer**: "Filed with the Adventurers' Guild — Tower of Last Chance"

**Style**: Dark parchment feel — use dark brown/sepia headers, faction-colored accents, serif fonts. Think aged contract document, not modern corporate memo.

### 2. DM Mission Prep (DM-Facing)
Multi-page document with full encounter details, NPC stat references, loot tables.

**Structure:**
- **Page 1 — Overview**: Same as player brief but with DM notes column
- **Page 2 — Encounter Map**: Location description, entry points, hazards, environmental details
- **Page 3 — NPCs**: Relevant NPCs with motivations, combat notes, roleplay hooks
- **Page 4 — Complications & Twists**: What could go wrong, faction politics, hidden agendas
- **Page 5 — Rewards & Consequences**: Detailed loot, rep changes, story consequences for success/failure
- **Appendix**: Relevant stat blocks, DC tables, random encounter tables

### 3. Faction Dossier
2-page faction briefing suitable for player handout when they gain faction standing.

**Structure:**
- **Page 1**: Faction name, motto, leadership, territory, public reputation
- **Page 2**: Known operations, allies/enemies, current tensions, what they want from adventurers

### 4. Session Summary
Post-session document capturing what happened for campaign continuity.

**Structure:**
- **Header**: Session number, date, characters present
- **Events**: Chronological summary
- **Decisions Made**: Key choices and their immediate consequences
- **Loose Threads**: Unresolved plot hooks
- **XP/Rewards**: What was earned
- **Next Session Hooks**: What's coming

## Formatting Conventions

### Faction Color Palette (use for headers and accents)
```
Iron Fang Consortium: #8B4513 (saddle brown)
Argent Blades:        #C0C0C0 (silver)
Wardens of Ash:       #A0522D (sienna)
Serpent Choir:        #DAA520 (goldenrod)
Obsidian Lotus:       #4B0082 (indigo)
Glass Sigil:          #4682B4 (steel blue)
Patchwork Saints:     #F5F5DC (beige) with #8B0000 (dark red) text
Adventurers' Guild:   #228B22 (forest green)
Ashen Scrolls:        #D2B48C (tan)
Tower Authority:      #2F4F4F (dark slate gray)
Independent:          #696969 (dim gray)
Brother Thane's Cult: #800000 (maroon)
```

### Typography
- **Title**: 18pt, bold, faction color
- **Section headers**: 14pt, bold, dark gray
- **Body text**: 11pt, regular, black
- **Flavor text/quotes**: 11pt, italic, dark gray
- **Footer**: 9pt, gray

### Page Setup
- US Letter (8.5" × 11")
- 1" margins all sides
- Single column for briefs, two-column option for DM prep

## Generating from Mission Board Data

### Reading the data:
```python
import json
from pathlib import Path
DOCS = Path("campaign_docs")
missions = json.loads((DOCS / "mission_memory.json").read_text(encoding="utf-8"))
```

### Filtering active missions:
```python
active = [m for m in missions if not m.get("resolved")]
unclaimed = [m for m in active if not m.get("claimed") and not m.get("npc_claimed")]
player_claimed = [m for m in active if m.get("claimed") and not m.get("resolved")]
```

### Enriching with NPC data:
```python
# Load NPC roster for faction NPCs relevant to the mission
roster = json.loads((DOCS / "npc_roster.json").read_text(encoding="utf-8"))
faction_npcs = [n for n in roster if n.get("faction") == mission["faction"]]

# Load faction rep for context
rep = json.loads((DOCS / "faction_reputation.json").read_text(encoding="utf-8"))
```

### Using Ollama to expand mission body into full document:
When the mission body from the board is terse (2-4 lines), use Ollama to expand it into full document sections. Prompt Ollama with the mission data + relevant campaign context and ask it to generate the specific section content (encounter details, NPC motivations, complications, etc).

## Batch Operations

For session prep, the DM may want to generate briefs for ALL unclaimed missions, or ALL missions claimed by a specific player. Support batch generation into a single multi-page document with page breaks between missions.
