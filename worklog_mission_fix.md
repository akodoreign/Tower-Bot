# Mission Module Generator Fix — Worklog
Started: 2026-03-28 07:45
Last Updated: 2026-03-28 08:15

## Objective
Fix mission module generator to:
1. Not use player Discord names as NPCs
2. Use correct faction leader names from NPC roster
3. Ensure faction leaders have proper NPC entries
4. Clean up READ ALOUD blocks

## Completed Steps

### Step 1: Fixed `__init__.py` corruption ✅
- File was corrupted by bad regex edit
- Rewrote entire file from scratch (~26KB clean)
- Added `_post_process_module_text()` function
- Strengthened system prompt against READ ALOUD
- Added post-processing to all generated sections

### Step 2: Updated `tower-bot/SKILL.md` ✅
- Added "Safe File Editing — CRITICAL" section
- Documented when edit_file is safe vs dangerous
- Added recovery pattern

### Step 3: Reviewed npcs.py module ✅
- `get_relevant_npcs(faction)` returns NPCs from faction + some random others
- `format_quest_giver_guidance(faction)` uses first faction NPC as quest giver
- No explicit faction leader lookup - just picks first NPC found
- ISSUE: If faction leader isn't in roster, module won't use correct names

### Step 4: Analyzed npc_roster.json ✅
Total NPCs: 70

**FACTION LEADERS FOUND:**
- ✅ Captain Havel Korin (Wardens of Ash) — Captain, Commander of Outer Wall
- ✅ Yaulderna Silverstreak (Wizards Tower) — Archmage, Head of Tower

**FACTION LEADERS MISSING:**
- ❌ Serrik Dhal (Iron Fang Consortium)
- ❌ Lady Cerys Valemont (Argent Blades)
- ❌ High Apostle Yzura (Serpent Choir)
- ❌ The Widow (Obsidian Lotus)
- ❌ Senior Archivist Pell (Glass Sigil)
- ❌ Mari Fen (Adventurers' Guild)
- ❌ Eir Velan (Guild of Ashen Scrolls)
- ❌ Director Myra Kess (Tower Authority/FTA)
- ❌ Brother Thane (Brother Thane's Cult)

### Step 5: Created faction leader NPCs ✅
- Created `campaign_docs/faction_leaders_to_add.json` with 9 faction leader entries
- Created `scripts/merge_faction_leaders.py` for future use
- Each leader has full NPC data (appearance, motivation, secret, relationships, oracle_notes)

### Step 6: Updated npcs.py with leader prioritization ✅
- Added `FACTION_LEADERS` dict with canonical leader names
- Added `LEADER_RANKS` list for rank-based identification
- Added `get_faction_leader(faction)` function
- Added `get_faction_leader_name(faction)` function with fallback
- Modified `get_relevant_npcs()` to always include leader first
- Modified `format_quest_giver_guidance()` to prioritize leaders
- Modified `build_npc_prompt_block()` to include leader name

### Step 7: Merge faction leaders into roster ⬜ IN PROGRESS
- Need to append 9 new leaders to npc_roster.json
- Create backup first
- Cannot run Python scripts directly — will manually merge

## Files Modified
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\src\mission_builder\__init__.py ✅
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills\tower-bot\SKILL.md ✅
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\src\mission_builder\npcs.py ✅ (rewritten)
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\campaign_docs\faction_leaders_to_add.json ✅ (created)
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\scripts\merge_faction_leaders.py ✅ (created)

## Files To Modify
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\campaign_docs\npc_roster.json ⬜ (merge leaders)

## Resume Instructions
If disconnected, read this worklog and continue from Step 7:
1. Read npc_roster.json (full file)
2. Read faction_leaders_to_add.json
3. Merge them (append leaders to roster)
4. Write merged result to npc_roster.json
5. Update worklog to Step 8 (testing)
