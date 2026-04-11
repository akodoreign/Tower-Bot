# Bug Fix Session — 2026-04-10

## Session Goal
Fix two priority bugs:
1. ⚔️ emoji reaction on mission bulletin not triggering mission build/post
2. NPC lifecycle stopping after generating 1 new NPC instead of processing the full roster

---

## Bug 1: NPC Lifecycle — Only Generating 1 NPC, Ignoring 119 DB Entries

### Root Cause (two-part)
**Part A — DB: 115 of 119 NPCs had NULL data_json**

Queried MySQL:
```
NPCs total: 119 | null data_json: 115
```

The `npcs` table schema stores detailed NPC data in a `JSON` column called `data_json`. MySQL returns `None` (Python) for NULL JSON columns. The `_load_npcs()` function in `src/npc_lifecycle.py` did:
```python
npc_data = row.get("data_json", {})   # returns None for NULL, not {}
# ...
npc = { **npc_data, ... }              # CRASH: **None → TypeError
```

The exception was caught at the function level, causing the ENTIRE load to return `[]`. Since all 119 NPCs had their first row NULL, the function immediately failed.

**Part B — Seed fallback blocked**

After the load failure, `run_daily_lifecycle()` tries `_seed_from_txt()`. But `npc_roster.txt` has "Auto-generated" in its header (it's bot-generated), so `_seed_from_txt()` returns `[]` by design. Result: lifecycle runs with an empty roster, generates 1 new NPC, done.

### Fixes Applied

**Fix A — Code: `src/npc_lifecycle.py` `_load_npcs()`**
```python
# Before:
npc_data = row.get("data_json", {})
if isinstance(npc_data, str):
    npc_data = json.loads(npc_data) if npc_data else {}

# After:
npc_data = row.get("data_json") or {}
if isinstance(npc_data, str):
    try:
        npc_data = json.loads(npc_data) if npc_data else {}
    except json.JSONDecodeError:
        npc_data = {}
elif not isinstance(npc_data, dict):
    npc_data = {}
```
This survives NULL, empty string, and malformed JSON in data_json.

**Fix B — DB Migration: populate NULL data_json from DB columns**

Ran one-time migration using system Python + mysql.connector (not in venv):
- Fetched all 115 rows with `data_json IS NULL`
- Built minimal JSON from DB columns: name, faction, role, location, status, description
- Merged `appearance_json` if present
- Updated each row
- Verified: 0 NULL rows remaining

### Expected Result
Next lifecycle run will load all 119 NPCs successfully and run events on 1-3 of them as intended.

---

## Bug 2: ⚔️ Reaction Not Triggering Mission Claim

### Root Cause (two-part)

**Part A — CONFIRMED BUG: `message_id` stored as VARCHAR, compared as int**

MySQL schema: `missions.message_id` is `VARCHAR(50)`.
This means `row.get("message_id")` returns a Python **string** like `'1479164846208585861'`.

But Discord's `payload.message_id` and `reaction.message.id` are Python **ints**.

The lookup in `handle_reaction_claim()`:
```python
mission_index = next(
    (i for i, m in enumerate(missions) if m.get("message_id") == message_id),
    None
)
```
Compares `'1479164846208585861'` == `1479164846208585861` → **False every time**.
`mission_index` is always `None`, function returns immediately, nothing happens.

**Part B — DEFENSIVE FIX: emoji variation selector**

`EMOJI_CLAIM = "⚔️"` = `\u2694\ufe0f`. Discord sometimes strips the variation selector `\ufe0f` from returned payloads. Added normalization to both sides before comparing.

### Fixes Applied

**Fix A — `src/mission_board.py` `_load_missions()`**
```python
# Before:
"message_id": row.get("message_id") or mission_data.get("message_id"),

# After:
_raw_mid = row.get("message_id") or mission_data.get("message_id")
try:
    _msg_id = int(_raw_mid) if _raw_mid is not None else None
except (ValueError, TypeError):
    _msg_id = _raw_mid
mission = { ..., "message_id": _msg_id }
```

**Fix B — `src/cogs/missions.py` emoji check**
```python
# Before:
if str(payload.emoji) != EMOJI_CLAIM:

# After:
_emoji_str = str(payload.emoji).replace('\ufe0f', '')
_claim_str = EMOJI_CLAIM.replace('\ufe0f', '')
if _emoji_str != _claim_str:
```

### Expected Result
Clicking ⚔️ on a mission bulletin will now:
1. Match the message_id correctly (int comparison works)
2. Match the emoji correctly (variation-selector-stripped comparison)
3. Proceed to `handle_reaction_claim()` → post claim notice, queue module generation, DM the game master

---

## Files Changed
| File | Change |
|------|--------|
| `src/npc_lifecycle.py` | `_load_npcs()`: defensive NULL/non-dict guard on data_json |
| `src/mission_board.py` | `_load_missions()`: cast message_id to int after DB load |
| `src/cogs/missions.py` | `on_raw_reaction_add`: strip `\ufe0f` before emoji compare |
| DB: `npcs` table | One-time migration: populated data_json for 115 NULL rows |

## Remaining Bugs (debug_log.md)
- BUG-002: `generate_bulletin() returned None` fires every cycle — still active
- BUG-004: Mistral prompt agent returning prose — still active
- BUG-005: Bulletin validation failures — still active
- BUG-006/007: Fact-check/editor agents empty output — still active

## Next Session
1. Verify ⚔️ reaction + full mission claim flow works after restart
2. Verify NPC lifecycle loads 119 NPCs correctly
3. Work through remaining BUG-002/005 bulletin generation failures
