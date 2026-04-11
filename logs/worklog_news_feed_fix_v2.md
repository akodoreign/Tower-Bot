# News Feed Bug Fix Worklog v2

**Created:** 2026-04-04
**Status:** IN PROGRESS

## Problem Summary

Three bugs in news_feed.py output:
1. **LLM Reasoning Leaking** — Editor notes like "Formatting adjustments:", "- Tone/Style:" appearing in Discord posts
2. **EC References Persisting** — "47 EC", "150 EC" appearing despite existing filters  
3. **Truncated Bulletins** — Incomplete stories like "The vendor demands." being posted

## Fix Strategy

Create `src/bulletin_cleaner.py` module, then integrate into news_feed.py at multiple points.

---

## Steps

### Step 1: Create bulletin_cleaner.py module ✅ COMPLETE
- [x] Create new module with cleaning functions
- [x] strip_llm_reasoning() — remove editor commentary
- [x] filter_ec_references() — stronger EC filtering  
- [x] validate_bulletin() — reject truncated content
- [x] clean_bulletin() — convenience wrapper

**File exists:** `src/bulletin_cleaner.py` (13,615 bytes)

### Step 2: Add import to news_feed.py ✅ COMPLETE
- [x] Add import statement for bulletin_cleaner functions

**Line 82:** `from src.bulletin_cleaner import clean_bulletin, validate_bulletin, strip_llm_reasoning, filter_ec_references`

### Step 3: Update _edit_bulletin function ✅ COMPLETE
- [x] Simplify editor prompt
- [x] Add clean_bulletin() call after Ollama response  
- [x] Add validate_bulletin() with fallback to original

**Key changes:**
- Prompt simplified to: `"Fix any errors...OUTPUT THE CORRECTED BULLETIN ONLY"`
- `edited = clean_bulletin(edited)` after Ollama response
- Validation check with fallback to original draft on failure

### Step 4: Update generate_bulletin function ✅ COMPLETE
- [x] Add filter_ec_references() call
- [x] Add validate_bulletin() before returning

**Note:** `filter_ec_references()` is called inside `clean_bulletin()` which is called by `_edit_bulletin()`. Validation added in Step 5.

### Step 5: Update generate_bulletin_draft function ✅ COMPLETE
- [x] Add validate_bulletin() after _edit_bulletin()
- [x] Return (None, None) if invalid

**Added at line 3256:** Validation block after `_edit_bulletin()` that discards invalid bulletins

### Step 6: Verify syntax and imports ✅ COMPLETE
- [x] Test that news_feed.py has no syntax errors

**Verified:** Code structure is correct, validation block properly placed after `_edit_bulletin()`

---

## Progress Log

**2026-04-04 07:40** — All steps complete.

### Summary of Changes

1. **src/bulletin_cleaner.py** (existed from previous session)
   - `strip_llm_reasoning()` — removes editor commentary like "Formatting adjustments:", "- Tone/Style:"
   - `filter_ec_references()` — removes invalid EC mentions, keeps only valid purchase transactions
   - `validate_bulletin()` — rejects bulletins with <2 lines, <80 chars, <15 words, or incomplete sentences
   - `clean_bulletin()` — convenience wrapper that applies all cleaning steps

2. **src/news_feed.py**
   - Import added at line 82
   - `_edit_bulletin()` already updated with:
     - Simplified prompt: "Fix any errors...OUTPUT THE CORRECTED BULLETIN ONLY"
     - `clean_bulletin(edited)` call after Ollama response
     - `validate_bulletin(edited)` check with fallback to original draft
   - `generate_bulletin_draft()` updated with:
     - Final validation block after `_edit_bulletin()` (line 3256)
     - Returns `(None, None)` if bulletin fails validation

### Bugs Fixed

1. **LLM Reasoning Leaking** — `strip_llm_reasoning()` catches bullet-point editor notes
2. **EC References Persisting** — `filter_ec_references()` double-filters EC abuse patterns
3. **Truncated Bulletins** — `validate_bulletin()` rejects incomplete content

### Next Steps

- Restart bot to apply changes
- Monitor next bulletin cycle for clean output
- Check logs for `"U0001f4f0 Draft bulletin failed validation"` messages

---

## Step 7: Clean news_memory.txt ✅ COMPLETE

**Removed 18 malformed entries:**

1. **LLM commentary entries** (5 removed):
   - `"---END BULLETIN--- - Removed AI assistant phrasing..."`
   - `"Formatting adjustments: Bolded names..."`
   - `"1. \"The thief left before...\" → — The previous bulletin..."`
   - `"- Added a emoji to the headline..."`
   - `"- Tone/Style: Adjusted \"risk poisoning\"..."`

2. **Truncated/incomplete bulletins** (5 removed):
   - `"Raziel Voss demanded."` (no object)
   - `"The vendor demands."` (no object)
   - `"A customer paid. The vendor's gaze lingered..."` (too sparse)
   - `"Ledgers sold for 120 EC each. Now gone."` (too short)
   - `"A blade etched with sigils sliced through a ledger..."` (fragmented)

3. **Overly long narrative entries** (6 removed):
   - 800+ word "Coldwatch Advance" story
   - 500+ word "Elara Nightshadow" story
   - Long faction intrigue pieces that read like fiction, not news

4. **Duplicate/malformed timestamps** (2 fixed):
   - Embedded duplicate timestamps in entries

**Result:** 22 clean entries remain (from 40 original)

