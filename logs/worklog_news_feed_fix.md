# News Feed Bug Fix Worklog

**Created:** 2026-04-04
**Status:** IN PROGRESS
**Issue:** Three bugs in news_feed.py output

## Problem Summary

1. **LLM Reasoning Leaking** — Editor notes like "Formatting adjustments:", "- Tone/Style:", etc. appearing in Discord posts
2. **EC References Persisting** — "47 EC", "150 EC" appearing despite existing filters
3. **Truncated Bulletins** — Incomplete stories like "The vendor demands." being posted

## Fix Strategy

Create a new `src/bulletin_cleaner.py` module with:
- `strip_llm_reasoning()` — Aggressively remove editor commentary
- `filter_ec_references()` — Stronger EC pattern filtering
- `validate_bulletin()` — Reject truncated/malformed content
- `clean_bulletin()` — Convenience wrapper

Then integrate into news_feed.py.

---

## Steps

### Step 1: Create bulletin_cleaner.py module ✅ COMPLETE
- [x] Write the new module with all cleaning functions
- [x] Include comprehensive patterns for LLM reasoning
- [x] Include stronger EC filtering
- [x] Include minimum content validation

**File:** `src/bulletin_cleaner.py` (13,615 bytes)

### Step 2: Add import to news_feed.py ✅ COMPLETE
- [x] Add import statement for bulletin_cleaner functions

**Import added at line 82:** `from src.bulletin_cleaner import clean_bulletin, validate_bulletin, strip_llm_reasoning, filter_ec_references`

### Step 3: Update _edit_bulletin function ✅ COMPLETE
- [x] Simplify the editor prompt (less likely to trigger explanatory output)
- [x] Replace manual stripping with clean_bulletin()
- [x] Add validation check

**Changes made:**
- Simplified editor prompt to just "Fix any errors...OUTPUT THE CORRECTED BULLETIN ONLY"
- Added `edited = clean_bulletin(edited)` after Ollama response
- Added `is_valid, reason = validate_bulletin(edited)` with fallback to original draft

### Step 4: Update generate_bulletin function
- [ ] Add filter_ec_references() call
- [ ] Add validation before returning

### Step 5: Update generate_bulletin_draft function
- [ ] Add validation before returning

### Step 6: Verify file integrity
- [ ] Check news_feed.py for syntax errors
- [ ] Verify imports work

---

## Progress Log

