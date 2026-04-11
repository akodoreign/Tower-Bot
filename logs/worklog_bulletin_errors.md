# Worklog: Bulletin Generation Errors Fix
**Started:** 2026-04-04T18:30:00
**Status:** ✅ COMPLETE

## Error Analysis

### Error 1: Discord Interaction Already Acknowledged (40060)
```
400 Bad Request (error code: 40060): Interaction has already been acknowledged.
```
**Location:** `src/bot.py` → `on_interaction()` handler
**Root Cause:** The error handler tried to send a response even when the interaction was already handled or timed out.

### Error 2: Bulletin Too Short / Truncated
```
Editor output invalid (too few lines (1)) — using original draft
Bulletin failed validation (too few lines (1)) — discarding: Grok Vey's crate arrived sealed at Dock 7. Sera Kael cut the lock with a blade from her belt. Inside...
```
**Location:** `src/news_feed.py` → `_edit_bulletin()` / `generate_bulletin()`
**Root Cause:** Ollama returned truncated responses ending mid-sentence ("Inside...").

---

## Fixes Applied

### Fix 1: Discord Interaction Handler (bot.py)
**File:** `src/bot.py`
**Changes:**
- Added specific exception handling for `discord.errors.NotFound` (expired interactions)
- Added specific handling for `discord.errors.HTTPException` with error code 40060
- Wrapped fallback response in try/except to prevent secondary errors
- Changed ERROR to DEBUG level for expected/harmless cases

```python
except discord.errors.NotFound:
    # Interaction expired (>15 minutes old) — silently ignore
    logger.debug("📰 Bulletin expansion: interaction expired")
except discord.errors.HTTPException as e:
    # 40060 = already acknowledged — silently ignore
    if e.code == 40060:
        logger.debug("📰 Bulletin expansion: interaction already acknowledged")
    else:
        logger.warning(f"📰 Bulletin expansion HTTP error: {e}")
```

### Fix 2: Truncation Detection (bulletin_cleaner.py)
**File:** `src/bulletin_cleaner.py`
**Changes:**
- Added `is_truncated()` function to detect mid-generation cutoffs
- Detects: `...` endings, trailing commas/semicolons/colons, incomplete words (and, the, to, etc.)
- Checks for missing sentence-ending punctuation
- Integrated truncation check into `validate_bulletin()` — returns "truncated" reason

```python
def is_truncated(text: str) -> bool:
    """Check if text appears to be truncated mid-generation."""
    # Checks for ..., trailing punctuation, incomplete last word, missing sentence ending
```

---

## Files Modified

1. **`src/bot.py`** — Improved Discord interaction error handling
2. **`src/bulletin_cleaner.py`** — Added truncation detection, improved validation

---

## Testing Notes

After bot restart:
- Discord 40060 errors should now log at DEBUG level (not ERROR)
- Truncated bulletins will be caught with reason "truncated" instead of "too few lines"
- Both fixes are non-breaking and backward compatible

---

## Completion

**Completed:** 2026-04-04T18:55:00
**Next Steps:** Restart bot to apply changes. Monitor logs for improved error reporting.
