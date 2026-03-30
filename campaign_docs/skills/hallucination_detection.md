# Skill: Hallucination Detection for Mission Generation
**Keywords:** hallucination, error, mistake, invented, fake, wrong, incorrect, validation, lore, canon
**Category:** validation
**Version:** 1
**Source:** seed

## Purpose
This skill teaches the self-learning system HOW to detect hallucinations in generated mission content. A hallucination is any generated content that contradicts established campaign lore, invents nonexistent entities, or contains factual/mechanical errors.

**CRITICAL:** Hallucination detection is the highest priority quality check. A plausible-sounding hallucination is MORE dangerous than an obvious error because DMs may not catch it.

---

## HALLUCINATION CATEGORIES

### Category 1: Invented Factions (CRITICAL)
**What it is:** References to factions that don't exist in the Undercity.

**Canonical Factions (ONLY these exist):**
- Iron Fang Consortium
- Argent Blades
- Wardens of Ash
- Serpent Choir
- Obsidian Lotus
- Glass Sigil
- Patchwork Saints
- Adventurers Guild
- Guild of Ashen Scrolls
- Tower Authority / FTA
- Wizards Tower
- Brother Thane's Cult / The Returned

**Common Hallucinations:**
- "Culinary Council" — DOES NOT EXIST
- "Hollow Waiter" — DOES NOT EXIST
- "Shadow Guild" — DOES NOT EXIST
- "Merchant's Alliance" — DOES NOT EXIST
- Any faction name not in the canonical list

**Detection Method:**
1. Extract all faction names from generated text
2. Compare against canonical list
3. Flag any that don't match (fuzzy match to catch variants)

### Category 2: Wrong NPC Names (HIGH)
**What it is:** NPCs that don't exist in npc_roster.json, or name inconsistencies within a document.

**Types:**
- **Invented NPCs** — Names that don't exist in the roster
- **Name Drift** — Same character called different names in different sections
- **Title Confusion** — "Commander Veridia" in narrative, "Captain Veridia" in stat block
- **Ghost NPCs** — Referenced but never introduced

**Detection Method:**
1. Extract all NPC names from generated text
2. Check each against npc_roster.json
3. Check for internal consistency (same name used throughout)
4. Flag mismatches between narrative and stat blocks

**Common Patterns:**
- Boss named "Serrik" in story, "Vander" in stat block
- NPC "introduced" in Act 3 but never actually described
- Quest-giver name changes mid-document

### Category 3: Location Errors (HIGH)
**What it is:** Places that don't exist in city_gazetteer.json or are placed in wrong districts.

**Canonical Districts:**
- Markets Infinite
- Grand Forum
- Guild Spires
- Sanctum Quarter
- The Warrens
- Outer Wall

**Common Hallucinations:**
- "The Sunken Quarter" — DOES NOT EXIST
- "Merchant's Row" — might be confusing with Markets Infinite
- Locations placed in wrong districts
- Underground areas accessed from impossible locations

**Detection Method:**
1. Extract location names from generated text
2. Check against city_gazetteer.json
3. Verify district assignments are correct
4. Flag unfamiliar location names

### Category 4: Rift Lore Violations (CRITICAL)
**What it is:** Rifts appearing where they cannot exist.

**Rift Rules:**
- Rifts ONLY appear in: The Warrens, Outer Wall
- Rifts NEVER appear in: Markets Infinite, Grand Forum, Guild Spires, Sanctum Quarter
- Rifts are RARE, alarming emergencies — not routine
- Rift missions should be serious multi-week contracts

**Common Hallucinations:**
- "A Rift opened in the Grand Forum" — IMPOSSIBLE
- "The routine Rift patrol in Markets Infinite" — IMPOSSIBLE
- "Small Rift in the Guild Spires basement" — IMPOSSIBLE
- Treating Rifts as common, mundane events

**Detection Method:**
1. Search for "Rift" mentions in generated text
2. Check associated locations
3. Flag if Rift + forbidden district combination found

### Category 5: Mechanical Errors (MEDIUM)
**What it is:** Stat blocks, DCs, or rewards that don't make sense.

**Types:**
- **Impossible Stats:** AC 25 on a CR 4 creature, 200 HP on a minion
- **Wrong DCs:** DC 5 for a "nearly impossible" check, DC 30 for "simple"
- **Broken Math:** Attack bonus doesn't match ability scores
- **Missing Stats:** Creature has no HP listed, attack has no damage
- **Reward Imbalance:** 10 Kharma for epic quest, 5000 EC for local job

**DC Guidelines:**
- Easy: DC 10
- Medium: DC 13-14
- Hard: DC 16-17
- Very Hard: DC 20+
- Nearly Impossible: DC 25+

**Reward Guidelines:**
- Local/Patrol: 50-100 EC, 20-50 Kharma
- Standard/Escort: 100-200 EC, 50-150 Kharma
- Major/Dungeon: 200-400 EC, 150-500 Kharma
- Epic/Divine: 500+ EC, 500-2000 Kharma

### Category 6: Structural Failures (MEDIUM)
**What it is:** Format violations that indicate the generator didn't follow instructions.

**Types:**
- **READ ALOUD blocks** — Should be "Scene Description" instead
- **Missing Stat Blocks** — Enemies referenced but no stats provided
- **Wrong Section Order** — Acts out of sequence
- **Placeholder Text** — "Insert description here", "TBD", "[TODO]"
- **Meta-Commentary** — "As requested, here is...", "I hope this helps"

**Detection Method:**
1. Search for forbidden patterns (READ ALOUD, placeholders)
2. Check that all enemies have stat blocks
3. Verify act structure is correct
4. Flag any LLM-style preambles

---

## DETECTION PROCESS

### Phase 1: Entity Extraction
Extract all named entities from the generated content:
- Faction names
- NPC names
- Location names
- Creature/enemy names

### Phase 2: Cross-Reference
Compare extracted entities against canonical sources:
- `campaign_docs/npc_roster.json` — for NPCs
- `campaign_docs/city_gazetteer.json` — for locations
- Hardcoded faction list — for factions
- `campaign_docs/rift_state.json` — for Rift rules

### Phase 3: Internal Consistency
Check that the document is consistent with itself:
- Same NPC name used throughout
- Stat blocks match narrative descriptions
- Rewards match tier/difficulty claims
- Timeline makes sense

### Phase 4: Pattern Matching
Search for known bad patterns:
- "READ ALOUD" (forbidden)
- Rift + wrong district
- Invented faction names
- Placeholder text

---

## OUTPUT FORMAT

When hallucinations are detected, output in this format:

```
HALLUCINATION DETECTED: [Category]
Location: [Where in the document]
Problem: [What's wrong]
Evidence: [The offending text]
Correction: [What it should be, or "REMOVE"]
Severity: CRITICAL / HIGH / MEDIUM / LOW
```

### Severity Levels:
- **CRITICAL:** Breaks campaign lore, confuses players, must fix
- **HIGH:** Significant error, should fix before use
- **MEDIUM:** Quality issue, fix if time allows
- **LOW:** Minor inconsistency, cosmetic

---

## KNOWN FALSE POSITIVES

Some things that LOOK like hallucinations but aren't:
- New NPCs created FOR this mission (not in roster yet) — check if they're clearly new
- Variant faction names ("FTA" = "Tower Authority")
- Informal location references ("the market" = "Markets Infinite")
- Generic creature types ("guard", "thug") — don't need roster entries

When uncertain, flag as "POSSIBLE HALLUCINATION — NEEDS HUMAN REVIEW" rather than making a definitive call.

---

## INTEGRATION

This skill is used by `_detect_hallucinations()` in `self_learning.py` to:
1. Scan recent mission_memory.json entries
2. Scan generated module files
3. Build a correction list
4. Feed corrections back into future generation prompts
