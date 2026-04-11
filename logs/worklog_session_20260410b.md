# Session Worklog — 2026-04-10 (Session B)

## Session Goals
1. Fix news bulletins not posting to Discord (carry-over from Session A)
2. Move everything possible to MySQL, remove file-based JSON reads
3. Create `bot_commands` table so the bot can self-reference its own API

---

## Work Completed

### 1. Fixed `news_feed.py` Single-Line Bulletin Bug (BUG-005)

**Problem:** Previous session's Python patch inserted regex patterns with literal embedded newlines (`\n` in `r"..."` strings), causing a `SyntaxError`. The `generate_bulletin()` function crashed silently.

**Fix:** Re-wrote the normalisation block using clean single-line regex patterns:
- Case A: `r"(\*\*[^*]{3,}\*\*)\s+"` — matches proper `**Headline** Body` and injects `\n`
- Case B: `r"(\*\*.{20,80}?)\s+(The |A |An |...)"` — dangling bold opener
- Case C: `r"(?<=[.!?])\s+(?=[A-Z*])"` — sentence boundary split fallback

All 7 changed files passed `py_compile` after this fix.

---

### 2. Fixed `mission_compiler.py` Map Generation (BUG-008)

**Problem:** Line ~697 called `generate_vtt_map(scene_description=..., location_type=..., output_subdir=...)` — kwargs don't match the actual signature `generate_vtt_map(scene: Dict, ref_bytes=None, denoise=float)`.

**Fix:** Replaced with `generate_module_maps(module_data, output_subdir=safe_title, max_maps=4)` which handles scene extraction, generation, and file saving internally.

---

### 3. Migrated `FactCheckerMixin` to MySQL (`src/agents/news_agents.py`)

Both `get_npc_roster()` and `get_npc_graveyard()` now query MySQL directly:
- `get_npc_roster()`: `SELECT ... FROM npcs WHERE status IN ('alive','injured')`
- `get_npc_graveyard()`: `SELECT ... FROM npcs WHERE status = 'dead'`
- Both fall back to JSON file if DB unavailable
- Results cached in `_cache` dict per session

---

### 4. Migrated 12 Dead NPCs into MySQL (`npcs` table)

`campaign_docs/npc_graveyard.json` had 12 dead NPCs that were never in MySQL. One-time migration via `scripts/populate_bot_commands.py` (adjacent script), inserted all 12 with `status='dead'` and parsed `moved_to_graveyard_at` into new `deceased_at` column.

DB now has: 119 alive/injured + 12 dead = 131 total NPCs.

---

### 5. Created `bot_commands` Table + Populated 30 Commands

New MySQL table: `tower_bot.bot_commands`
```sql
CREATE TABLE bot_commands (
    id INT AUTO_INCREMENT PRIMARY KEY,
    command_name VARCHAR(100) UNIQUE,
    description TEXT,
    source_file VARCHAR(255),
    source_function VARCHAR(255),
    cog_name VARCHAR(100),
    dm_only TINYINT(1),
    parameters JSON,
    notes TEXT,
    created_at DATETIME,
    updated_at DATETIME ON UPDATE CURRENT_TIMESTAMP
)
```
30 commands inserted covering all cogs: chat, image, missions, bot.py inline commands.
Maintained by `scripts/populate_bot_commands.py`.

---

### 6. Fixed `npc_lifecycle._rebuild_txt()` to Also Write `npc_roster.json`

`_rebuild_txt()` wrote `npc_roster.txt` but not `npc_roster.json`. Any code still reading the JSON file got stale data. Added 5-line block to write `npc_roster.json` from the same in-memory list after the txt write.

---

### 7. Migrated `npc_consequence.py` Entirely to MySQL

All 4 file I/O function pairs replaced:

| Function | Was | Now |
|---|---|---|
| `_load_roster()` | `npc_roster.json` read | `SELECT FROM npcs WHERE status IN ('alive','injured')` |
| `_save_roster()` | `json.dumps` to file | `_save_npc()` per NPC + `_rebuild_txt()` |
| `_load_graveyard()` | `npc_graveyard.json` read | `SELECT FROM npcs WHERE status = 'dead'` |
| `_save_graveyard()` | `json.dumps` to file | `_save_npc()` per NPC (status already 'dead') |
| `_load_resurrection_queue()` | `resurrection_queue.json` | `SELECT FROM resurrection_queue WHERE status='pending'` |
| `_save_resurrection_queue()` | `json.dumps` to file | UPSERT into `resurrection_queue` table |

All functions have JSON file fallback if DB unavailable.

---

### 8. Migrated `self_learning.py` JSON Reads to MySQL

Added two helpers at module level:
- `_load_missions_from_db(limit)` — queries `missions` table, normalises `outcome` field from `status` column
- `_load_faction_rep_from_db()` — calls `get_all_faction_reputations()` → dict keyed by faction name

Updated 6 async study functions to use DB first, file fallback second:
- `_study_mission_patterns()` — missions from DB
- `_study_npc_roster()` — NPCs from DB
- `_study_faction_reputation()` — faction_reputation table
- `_study_failure_logs()` — missions from DB
- `_study_world_state()` — missions + faction_rep from DB
- `_study_mission_quality()` — missions from DB; `generated_mission_types` from global_state
- `_study_mission_type_variety()` — missions + types from DB

---

### 9. Migrated `mission_compiler.py` and `mission_builder/__init__.py`

**`mission_compiler.py`** context-gathering:
- NPC roster: now queries `SELECT name,faction,role,location,status FROM npcs WHERE status='alive'`
- Faction info: now calls `get_all_faction_reputations()`

**`mission_builder/__init__.py`** prompt-building:
- `faction_reputation.json` → `get_all_faction_reputations()` with file fallback
- `rift_state.json` → `get_rift_state()` with file fallback (reads `effects_json.rifts`)

---

## MySQL Schema Changes

| Change | Table | Detail |
|---|---|---|
| Added column | `npcs` | `deceased_at DATETIME DEFAULT NULL` |
| New table | `bot_commands` | 30 rows inserted |
| Migrated data | `npcs` | 12 dead NPCs inserted (status='dead') |

---

## Files Changed

| File | Change |
|---|---|
| `src/news_feed.py` | Fixed corrupted regex in single-line normalisation block |
| `src/mission_compiler.py` | Fixed `generate_vtt_map` kwargs; migrated NPC/faction reads to MySQL |
| `src/mission_builder/__init__.py` | Migrated faction_rep + rift_state reads to MySQL |
| `src/agents/news_agents.py` | `get_npc_roster()` + `get_npc_graveyard()` now query MySQL |
| `src/npc_consequence.py` | All 4 I/O function pairs migrated to MySQL |
| `src/npc_lifecycle.py` | `_rebuild_txt()` now also writes `npc_roster.json` |
| `src/self_learning.py` | 7 study functions migrated from JSON files to MySQL |
| `scripts/populate_bot_commands.py` | NEW — one-time script, can re-run to refresh commands table |
| `logs/debug_log.md` | Updated — BUG-005, BUG-008 marked fixed; investigation queue updated |

---

## Remaining JSON Files Still in Use

These still have file-based reads but are lower priority or rarely touched:

| File | Used By | Note |
|---|---|---|
| `npc_roster.json` | `npc_lookup.py`, legacy fallbacks | Written by `_rebuild_txt()` now — stays in sync |
| `npc_graveyard.json` | Legacy fallbacks only | Data now in MySQL; file kept for emergency restore |
| `faction_reputation.json` | Fallback only | Data in MySQL; file kept for emergency restore |
| `adventurer_parties.txt` | `mission_board.py` `_load_party_list()` | Text format, not JSON — low priority |
| `character_memory.txt` | `self_learning.py`, `mission_board.py` | Text/RAG format — needs separate DB design |
| `news_memory.txt` | `news_feed.py` | Text/RAG format — separate design needed |
| `weekly_archive.py` `_archive_missions()` | Archive only, reads missions table via `raw_query` | Already uses DB for source; file write is archival |

---

## Next Session

1. **Restart the bot and verify bulletins post** — the critical validation: does `generate_bulletin()` now produce ≥2 lines that pass `validate_bulletin()`?
2. **Test ⚔️ reaction** — does clicking the crossed-swords emoji on a mission now trigger `handle_reaction_claim()`?
3. **Verify NPC lifecycle** — does it now process 131 NPCs instead of 1?
4. **Watch BUG-006 / BUG-007** — fact-check and editor agents still returning empty output; consider disabling them or adding a simpler prompt
5. **`character_memory.txt` and `news_memory.txt`** — design a proper DB schema if these need MySQL (both are multi-entry text logs; `news_memory` is already partially in `news_entries` table)
