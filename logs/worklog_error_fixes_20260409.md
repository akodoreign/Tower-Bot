# Worklog: Bot Error Fixes (2026-04-09)

## Summary
Systematic fix for errors identified in `bot_stderr.log`.

---

## Errors Identified

### 1. ❌ Database Schema - Missing Columns

| Table | Missing Column | Purpose |
|-------|----------------|---------|
| `npcs` | `data_json` | Stores full NPC JSON data |
| `towerbay_auctions` | `auction_json` | Stores full auction item data |
| `tia_market` | `sector_name`, `value_json`, `state_json` | Expected by tower_economy.py |
| `arena_seasons` | `champion_name` | Current champion tracking |
| `faction_events` | `emoji` | Event emoji display |

**Status**: 🔧 FIXING

---

### 2. ❌ NPC Lifecycle KeyError: 'history'

**Location**: `src/npc_lifecycle.py` lines 593, 746
**Cause**: NPCs loaded from DB via `_load_npcs()` don't have `history` key initialized
**Error**: `KeyError: 'history'`

**Fix**: Ensure `history` is always initialized as empty list when loading NPCs

**Status**: 🔧 FIXING

---

### 3. ❌ TIA Division by Zero

**Location**: `src/tower_economy.py` line 924
**Cause**: `format_tia_bulletin()` divides by `len(all_vals)` when sectors dict is empty
**Error**: `ZeroDivisionError: division by zero`

**Fix**: Add guard for empty sectors before division

**Status**: 🔧 FIXING

---

### 4. ⚠️ Rift State Save Error

**Message**: `Could not save rift state: Python type list cannot be converted`
**Cause**: Lists being passed directly to MySQL instead of JSON-serialized
**Note**: Not a hard error (printed to console, not logged as ERROR)

**Fix**: Ensure all list/dict values are JSON-serialized before DB operations

**Status**: 🔧 FIXING

---

## Fix Progress

| # | Issue | Status |
|---|-------|--------|
| 1 | DB Schema migration | ⬜ RUN `python migrate_add_columns.py` |
| 2 | NPC history init | ✅ DONE - Added to `_load_npcs()` |
| 3 | TIA div/zero guard | ✅ DONE - Guard added to `format_tia_bulletin()` |
| 4 | Rift state JSON | ✅ DONE - Fixed `update_rift_state()` |

---

## Step-by-Step Fixes

### Step 1: Create Database Migration Script
Create SQL migration to add missing columns.

### Step 2: Fix NPC History Initialization
Modify `_load_npcs()` in `npc_lifecycle.py` to ensure history is always a list.

### Step 3: Fix TIA Division by Zero
Add guard in `format_tia_bulletin()` for empty sectors.

### Step 4: Fix Rift State Serialization
Ensure `update_rift_state()` properly serializes all values.

---

## Notes
- Bot will need restart after fixes are applied
- Database migration should be run first
- Test each fix individually before moving to next
