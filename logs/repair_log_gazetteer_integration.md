# Gazetteer Integration — news_feed.py

**Date:** 2026-03-26
**Goal:** Wire city_gazetteer.json into news generator and fact-checker

## Plan

1. [x] Create this log file
2. [ ] Find `_fact_check_bulletin` function — add gazetteer location loading
3. [ ] Find `_build_prompt` function — add city districts section  
4. [ ] Find `_WORLD_LORE` — add `{LIVE_CITY_DISTRICTS}` placeholder
5. [ ] Create `_build_city_districts_block()` helper function
6. [ ] Update fact-checker system prompt to validate locations
7. [ ] Test import works

## Step Status

### STEP 2: Locate _fact_check_bulletin
**Status:** DONE
**Line range:** ~line 2200+
**Finding:** Function exists, calls `_load_gazetteer_locations()` but only gets basic lists

### STEP 3: Locate _build_prompt  
**Status:** DONE  
**Line range:** ~line 1900+
**Finding:** Only replaces `{LIVE_ROSTER_NPCS}`, NOT `{LIVE_CITY_DISTRICTS}` - BUG!

### STEP 4: Locate _WORLD_LORE
**Status:** DONE
**Line range:** ~line 700
**Finding:** Has `{LIVE_CITY_DISTRICTS}` placeholder but it NEVER gets replaced - stays as literal text!

### STEP 5: Create _build_city_districts_block()
**Status:** IN PROGRESS

### STEP 6: Fix _build_prompt() to call city districts builder
**Status:** PENDING

### STEP 7: Update _fact_check_bulletin() with full gazetteer context
**Status:** PENDING

---

## Code Changes Log

(Will be updated as changes are made)

