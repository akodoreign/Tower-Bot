# Worklog: Swap Mistral → qwen3-8b-slim:latest
**Started:** 2026-04-04 
**Status:** IN PROGRESS
**Model:** `qwen3-8b-slim:latest`

## Task Summary
Replace all remaining "mistral" model references with `qwen3-8b-slim:latest` across the codebase.

## Categories

### SKIP (Backups - historical, don't touch)
- `backups\*` - all backup files ✓ SKIPPED

### CRITICAL (Active Source Code)
- [x] 1. `src\news_feed.py` - FIXED via script
- [x] 2. `src\aclient.py` - FIXED via script
- [x] 3. `src\mission_compiler.py` - FIXED via script
- [x] 4. `src\npc_appearance.py` - FIXED via script
- [x] 5. `src\npc_lifecycle.py` - FIXED via script
- [x] 6. `src\party_profiles.py` - FIXED via script
- [x] 7. `src\self_learning.py` - FIXED via script
- [x] 8. `src\skills.py` - FIXED (docstring only)
- [x] 9. `src\tower_economy.py` - FIXED via script
- [x] 10. `src\cogs\economy.py` - FIXED via script
- [x] 11. `src\agents\kimi_agent.py` - FIXED (docstring only)
- [x] 12. `src\mission_builder\dungeon_delve\room_generator.py` - FIXED via script
- [x] 13. `src\mission_builder\image_integration.py` - FIXED via script

### DOCUMENTATION (Update for accuracy)
- [x] 14. `skills\tower-bot\SKILL.md` - lines 64, 279 - FIXED
- [x] 15. `src\agents\AGENTS.md` - lines 61-73 - FIXED
- [x] 16. `src\mission_builder\README.md` - lines 227, 233, 377, 470 - FIXED
- [x] 17. `campaign_docs\skills\module_quality.md` - line 206 - FIXED

### NEW ISSUE DISCOVERED
- [ ] 18. Context window overflow causing truncation
  - qwen3-8b-slim:latest has 8k context window
  - News feed prompts are ~4000-6000 tokens (world lore + roster + bulletins + instructions)
  - Fact-check and editor prompts add more context
  - Result: model returns empty/truncated responses
  - **FIX NEEDED:** Reduce prompt sizes in `news_feed.py` for:
    - `_build_prompt()` - main bulletin generation
    - `_fact_check_bulletin()` - validation pass
    - `_edit_bulletin()` - editor pass
    - `_prompt_agent()` - image prompt generation

## Progress Log

### 2026-04-04 - Session Start
- Created worklog
- Ran fix_mistral_to_qwen.py script - fixed 11 files
- Fixed `src\skills.py` docstring manually
- Fixed `src\agents\kimi_agent.py` docstrings manually
- Fixed all 4 documentation files

### 2026-04-04 - Post-swap testing
- Model swap complete but bulletins failing:
  - "Fact-check: result too short, using original"
  - "Editor output invalid (empty) — using original draft"
  - "Bulletin failed validation (too few lines (1))"
- Root cause: prompt sizes exceed qwen3-8b-slim context capacity
- Next: Trim prompts to fit 8k context

## Checkpoint Data
Model swap files completed: 17/17 ✓
Post-swap issue: Context overflow causing truncation
Next step: Reduce prompt sizes in news_feed.py
