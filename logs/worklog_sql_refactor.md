# SQL Refactor Worklog
**Created:** 2026-04-09
**Operation:** Migrate Tower Bot from file-based storage to MySQL
**Status:** IN_PROGRESS — Phase 4 (Testing & Additional Refactors)

## Credentials (unchanged)
- **MySQL Bot User:** `Claude` / `WXdCPJmeDfaQALaktzF6!`
- **MySQL Root:** `root` / `qT9bDq7V84fnLWjCP2HW1!`
- **Database:** `tower_bot`

---

## PHASE STATUS SUMMARY

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 0: Setup | ✅ COMPLETE | mysql-connector installed, scripts created |
| Phase 1: Database | ✅ COMPLETE | 23 tables created, db_api.py (17KB) |
| Phase 2: Migration | ✅ COMPLETE | 749 records migrated |
| Phase 3: Refactor | ✅ COMPLETE | 16/16 files done (1 skipped intentionally) |
| Phase 4: Testing | 🔄 IN PROGRESS | Bug fixes + additional features |

---

## PHASE 3: CODE REFACTOR — FINAL STATUS

### ✅ COMPLETED FILES (15)

| File | Status | Key Changes |
|------|--------|-------------|
| `faction_reputation.py` | ✅ | Uses `get_faction_reputation()`, `set_faction_reputation()` |
| `bounty_board.py` | ✅ | Uses `db.insert()`, `raw_query()` for bounties table; added `_save_bounties()` wrapper |
| `dome_weather.py` | ✅ | Uses `get_weather_state()`, `update_weather_state()` |
| `ec_exchange.py` | ✅ | Uses `get_economy_state()`, `update_economy_state()` |
| `missing_persons.py` | ✅ | Uses `raw_query()`, `db.insert()` for missing_persons table |
| `arena_season.py` | ✅ | Uses `raw_query()`, `db.insert()` for arena_seasons table |
| `faction_calendar.py` | ✅ | Uses `raw_query()`, `db.insert()` for faction_events table |
| `character_profiles.py` | ✅ | Uses `_get_player_by_discord_id()`, stores in profile_json |
| `image_ref.py` | ⏭️ SKIPPED | Binary PNG storage — file-based approach appropriate |
| `party_profiles.py` | ✅ | Uses `raw_query()`, `db.insert()` for party_profiles table |
| `player_listings.py` | ✅ | Uses `raw_query()`, `db.insert()` for towerbay_auctions table |
| `npc_lifecycle.py` | ✅ | Uses `npcs` + `lifecycle_daily_events` tables |
| `npc_appearance.py` | ✅ | Uses `npc_appearances` table |
| `tower_economy.py` | ✅ | Uses `towerbay_auctions`, `tia_market`, `global_state` tables |
| `mission_board.py` | ✅ | Uses `missions`, `global_state` tables (mission_types, personal_tracker, used_parties) |
| `news_feed.py` | ✅ | Uses `rift_state`, `news_memory`, `global_state` tables |

### 📁 FILES INTENTIONALLY KEPT FILE-BASED

These are DM reference files that are manually maintained:

| File | Reads From | Reason |
|------|------------|--------|
| `_load_characters()` | `character_memory.txt` | Manual DM character reference |
| `_load_party_list()` | `adventurer_parties.txt` | Manual party list |
| `npc_lookup.py` | `npc_roster.json`, `npc_graveyard.json` | NPC lookup for /draw, /chat — will work if JSON files exist |
| `self_learning.py` | Various JSON files | Analysis reads — works if JSON files exist |

---

## REFACTORING PATTERN ESTABLISHED

When refactoring each file, follow this pattern:

### 1. Remove JSON imports
```python
# REMOVE these:
import json
from pathlib import Path
DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
SOME_FILE = DOCS_DIR / "filename.json"
```

### 2. Add db_api imports
```python
# ADD these (pick what you need):
from src.db_api import (
    # Generic query functions
    raw_query,
    raw_execute,
    db,  # For db.insert(), db.update(), etc.
    
    # Specific table functions (if they exist)
    get_weather_state, update_weather_state,
    get_economy_state, update_economy_state,
    get_faction_reputation, set_faction_reputation, get_all_faction_reputations,
    get_npc, get_all_npcs, add_npc, update_npc,
    get_mission, get_active_missions, create_mission,
    get_recent_news, add_news_entry,
    # etc.
)
```

### 3. Replace _load/_save functions
```python
# OLD:
def _load() -> dict:
    if not FILE.exists(): return {}
    return json.loads(FILE.read_text())

def _save(data: dict) -> None:
    FILE.write_text(json.dumps(data, indent=2))

# NEW:
def _load() -> dict:
    try:
        result = raw_query("SELECT * FROM table_name ...")
        # or use specific function like get_weather_state()
        return result[0] if result else {}
    except Exception as e:
        logger.error(f"Load error: {e}")
        return {}

def _save(data: dict) -> None:
    try:
        # Use raw_execute for UPDATE, or db.insert for new records
        raw_execute("UPDATE table_name SET ...", (params,))
        # or update_weather_state(data)
    except Exception as e:
        logger.error(f"Save error: {e}")
```

---

## db_api.py KEY FUNCTIONS REFERENCE

```python
# Connection
db = TowerBotDB()  # Singleton, auto-connects

# Raw queries
raw_query(sql, params=None)     # SELECT → List[Dict]
raw_execute(sql, params=None)   # INSERT/UPDATE/DELETE → affected rows

# NPCs (npcs table)
get_npc(name) → dict | None
get_all_npcs() → List[dict]
get_npcs_by_faction(faction) → List[dict]
get_living_npcs() → List[dict]
add_npc(data: dict) → int (new id)
update_npc(name, data: dict) → bool
kill_npc(name) → bool

# Missions (missions table)
get_mission(mission_id) → dict | None
get_active_missions() → List[dict]
create_mission(data: dict) → int (new id)
claim_mission(mission_id, player) → bool
complete_mission(mission_id) → bool
expire_mission(mission_id) → bool

# News (news_entries table)
get_recent_news(limit=20) → List[dict]
add_news_entry(headline, body, category, news_type) → int
get_news_memory(limit=50) → str  # Formatted for LLM context

# State tables
get_weather_state() → dict | None
update_weather_state(data: dict) → bool
get_economy_state() → dict | None
update_economy_state(data: dict) → bool
get_rift_state() → dict | None
update_rift_state(data: dict) → bool

# Faction reputation
get_faction_reputation(faction_name) → dict | None
get_all_faction_reputations() → List[dict]
set_faction_reputation(faction_name, score, tier) → bool

# Bounties
get_active_bounties() → List[dict]
add_bounty(title, target_type, target_name, reward_ec) → int
claim_bounty(bounty_id, claimed_by) → bool
complete_bounty(bounty_id) → bool

# Player/Party
get_player_character(name) → dict | None
save_player_character(name, data: dict) → bool
get_party_profile(party_name) → dict | None
save_party_profile(party_name, data: dict) → bool

# Images
get_image_ref(ref_type, name) → str | None
save_image_ref(ref_type, name, path) → bool
```

---

## DATABASE SCHEMA QUICK REFERENCE

Key tables and their primary columns:

| Table | Key Columns |
|-------|-------------|
| npcs | id, name, faction, role, location, status, data_json |
| missions | id, title, faction, tier, status, reward_ec, claimed_by |
| news_entries | id, headline, body, category, news_type, created_at |
| bounties | id, title, target_name, reward_ec, status, claimed_by |
| weather_state | id, current_weather, temperature, effects_json |
| economy_state | id, ec_to_kharma_rate, trend |
| rift_state | id, rift_level, effects_json |
| faction_reputation | id, faction_name, reputation_score, tier |
| arena_seasons | id, season_number, champion_name, state_json |
| missing_persons | id, name, last_seen_location, status, reported_at |
| npc_appearances | id, npc_name, appearance_json |
| party_profiles | id, party_name, profile_json |
| tia_market | id, sector, value |
| towerbay_auctions | id, item_name, current_bid |

---

## RESUME INSTRUCTIONS

When resuming in ~4 hours:

1. **Read this worklog** to get context
2. **Continue with remaining files** in this order:
   - `faction_calendar.py` (12KB) — straightforward
   - `character_profiles.py` (5KB) — small
   - `image_ref.py` (5KB) — small
   - `party_profiles.py` (19KB) — medium
   - `player_listings.py` (19KB) — medium
   - `npc_lifecycle.py` (35KB) — large but critical
   - `npc_appearance.py` (31KB) — large
   - `tower_economy.py` (33KB) — large
   - `mission_board.py` (62KB) — CRITICAL, largest priority
   - `news_feed.py` (115KB) — CRITICAL, most complex
   
3. **After all files refactored:**
   - Create a test script to verify each module works
   - Test the bot locally with a few commands
   - Backup the original JSON files before deleting

4. **Potential issues to watch for:**
   - Some db_api functions may need additions (check if function exists before using)
   - JSON fields (like data_json, state_json) need json.loads/dumps handling
   - Datetime fields need proper formatting

---

## SESSION LOG

### 2026-04-09 Session 1
- **Phase 0-1:** Setup complete
- **Phase 2:** Migration complete (749 records)
- **Phase 3:** Started
  - Refactored: faction_reputation.py, bounty_board.py, dome_weather.py, ec_exchange.py, missing_persons.py, arena_season.py
  - **6/16 files complete (37.5%)**
- **Session ended:** User break, resuming in ~4 hours

### 2026-04-09 Session 2
- **Phase 3:** Continued
  - Refactored: faction_calendar.py, character_profiles.py, party_profiles.py, player_listings.py
  - Skipped: image_ref.py (binary PNG storage, not JSON)
  - **11/16 files complete (68.75%)**
- **Remaining:** npc_lifecycle.py, npc_appearance.py, tower_economy.py, mission_board.py, news_feed.py

### 2026-04-09 Session 3 (Current)
- **Phase 3:** COMPLETED
  - Completed refactor of all remaining files:
    - `npc_lifecycle.py` → `npcs` + `lifecycle_daily_events` tables
    - `npc_appearance.py` → `npc_appearances` table
    - `tower_economy.py` → `towerbay_auctions`, `tia_market`, `global_state`
    - `mission_board.py` → `missions`, `global_state` (mission_types, personal_tracker, used_parties)
    - `news_feed.py` → `rift_state`, `news_memory`, `global_state` (cadence, news_types)
  - **16/16 files complete (100%)**

- **Phase 4:** Started — Bug Fixes & Additional Features
  - ❌ **Import Error:** `aclient.py` importing `_save_bounties` from `bounty_board.py` which was removed
    - ✅ **FIXED:** Added `_save_bounties()` compatibility wrapper to `bounty_board.py`
  - ❌ **Schema Mismatch:** `bounties` table missing `message_id`, `body` columns
    - Created `alter_bounties_table.sql` for adding columns (run manually)
    - Updated `_save_bounty()` to only use existing columns for now

- **Files Intentionally File-Based:**
  - `_load_characters()` → `character_memory.txt` (DM reference)
  - `_load_party_list()` → `adventurer_parties.txt` (manual list)
  - `npc_lookup.py` → `npc_roster.json` (NPC lookup for /draw, /chat)
  - `self_learning.py` → reads JSON for analysis (works if files exist)

- **Next Steps (In Progress):**
  1. ✅ Add DB access for story image generation (more context than just news_memory)
  2. ✅ Add DB access for character tracking (`character_monitor.py`)
  3. Run `alter_add_character_snapshots.sql` to create table
  4. Test bot startup and verify all features work

### Completed This Session:

**1. Story Image Generation — Enhanced DB Context**
- Added to `db_api.py`:
  - `get_story_context(limit_news, limit_npcs, limit_missions)` — comprehensive context from multiple tables
  - `format_story_context_for_prompt(context, max_chars)` — formats for LLM prompts
- Updated `news_feed.py` `_build_image_prompt()`:
  - Fetches comprehensive story context from DB (news, NPCs, missions, rifts, weather, economy)
  - Logs context availability
  - Uses DB NPCs when none found in bulletin text

**2. Character Monitor — Database-Backed Snapshots**
- Created `alter_add_character_snapshots.sql` (run to create table)
- Added to `db_api.py`:
  - `get_character_snapshot(char_id)` / `save_character_snapshot()` / `get_previous_snapshot()` / `cleanup_old_snapshots()`
- Updated `character_monitor.py`:
  - Replaced file-based JSON snapshots with DB storage
  - Keeps last 5 snapshots per character for history
  - Still updates `character_memory.txt` for Oracle context

**SQL Scripts to Run:**
```bash
mysql -u Claude -p tower_bot < alter_add_character_snapshots.sql
mysql -u Claude -p tower_bot < alter_bounties_table.sql  # if not already done
```

---

## QUICK TEST COMMAND

After resuming, verify the refactored modules work:

```powershell
cd C:\Users\akodoreign\Desktop\chatGPT-discord-bot
python -c "
from src.faction_reputation import get_all_reputations
from src.dome_weather import format_weather_bulletin
from src.ec_exchange import get_rate
from src.arena_season import format_standings_bulletin

print('Factions:', len(get_all_reputations()))
print('EC Rate:', get_rate())
print('Weather OK:', 'DOME' in format_weather_bulletin())
print('Arena OK:', 'STANDINGS' in format_standings_bulletin())
print('All 4 refactored modules working!')
"
```
