# Self-Learning Module Quality Trainer — Worklog
Created: 2026-04-03T15:00:00Z

## Status: COMPLETED ✅

## Recent Addition: Discord Patch Approval UI

Added `/patches` command that:
1. Reads pending patches from `skills/module-quality/PATCHES.md`
2. DMs you an interactive review interface with buttons
3. Approve ✅ / Reject ❌ / Skip ⏭️ each patch
4. Updates PATCHES.md with your decision

## Objective
Create an autonomous self-learning system that:
1. Generates a test mission during the 1-4 AM learning cycle
2. Compares its output against extracted professional D&D module PDFs
3. Identifies quality gaps using AICriticAgent
4. Generates prompt improvement patches
5. Logs all learning for DM review
6. Does NOT affect production systems (isolated sandbox)

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   SELF-LEARNING QUALITY LOOP                     │
│                      (Runs 1-4 AM nightly)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌───────────────┐    ┌─────────────────┐   │
│  │ 1. Generate  │───▶│ 2. Compare to │───▶│ 3. Identify     │   │
│  │ Test Mission │    │ Training PDFs │    │ Quality Gaps    │   │
│  └──────────────┘    └───────────────┘    └────────┬────────┘   │
│                                                     │            │
│  ┌──────────────┐    ┌───────────────┐    ┌────────▼────────┐   │
│  │ 6. Log to    │◀───│ 5. Save       │◀───│ 4. Generate     │   │
│  │ Journal      │    │ Patches       │    │ Prompt Patches  │   │
│  └──────────────┘    └───────────────┘    └─────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

ISOLATION:
- Test output → logs/learning/test_modules/ (NOT generated_modules/)
- No Discord posting
- No mission_memory.json updates
- No faction reputation changes
```

## Steps — ALL COMPLETED ✅

- [x] **Step 1**: Create directory structure for learning outputs
- [x] **Step 2**: Create ModuleQualityTrainer class (main orchestrator)
  - Created: `src/module_quality_trainer.py`
  - Functions: `study_module_quality()`, `_generate_test_mission()`, `_compare_to_reference()`
- [x] **Step 3**: Integrate into self_learning.py
  - Added import and study entry to `run_learning_session()`
- [x] **Step 4**: Create patches file and test script
  - Created: `skills/module-quality/PATCHES.md`
  - Created: `scripts/test_module_quality_training.py`
- [x] **Step 5**: Update worklog with completion status

## Files Created

| File | Purpose |
|------|---------|
| `src/module_quality_trainer.py` | Main training module (450+ lines) |
| `src/patch_approval.py` | Discord `/patches` command + approval UI |
| `scripts/test_module_quality_training.py` | Manual test script |
| `skills/module-quality/PATCHES.md` | Pending patches for DM review |

## Files Modified

| File | Change |
|------|--------|
| `src/self_learning.py` | Added import and study entry for module_quality_training |
| `src/bot.py` | Added `src.patch_approval` to COG_MODULES |

## Output Locations

| Output | Location |
|--------|----------|
| Test modules (JSON) | `logs/learning/test_modules/` |
| Quality journal | `logs/learning/quality_journal.jsonl` |
| Prompt patches | `skills/module-quality/PATCHES.md` |
| Learned skill | `campaign_docs/skills/learned_module_quality_report_*.md` |

## How It Works

### 1. Test Mission Generation (Sandbox Mode)
- Randomly selects faction, tier, mission type
- Generates all 5 sections (overview, act_1, act_2, act_3, rewards)
- Uses anti-pattern enforcement from module-quality skill
- Output saved to `logs/learning/test_modules/` NOT production directories
- Marked with `is_learning_test: true` in metadata

### 2. Reference Material Loading
- Reads from `campaign_docs/TrainingPDFS/extracted/`
- Uses PDFs that extracted well: Can_We_Keep_Him, Respect_your_elderly, Oni Mother, Castle Amber
- Extracts middle pages (actual adventure content, not credits)

### 3. Quality Comparison
- AI critic scores 8 criteria (1-10 each):
  - SPECIFICITY, SENSORY_DETAIL, NPC_QUALITY, ENCOUNTER_DESIGN
  - READ_ALOUD, ANTI_PATTERNS, FORMAT, PLAYABILITY
- Identifies top 3 quality gaps with specific examples
- Generates 3 prompt patches to fix the gaps

### 4. Patch Generation
- Patches saved to `skills/module-quality/PATCHES.md`
- Marked as PENDING — requires DM approval
- NOT auto-applied to production prompts
- DM marks each as: ✅ APPROVED, ❌ REJECTED, or 🔄 MODIFIED

### 5. Learning Journal
- Each session logged to `logs/learning/quality_journal.jsonl`
- Tracks: timestamp, mission title, scores, gaps, patches count
- Enables trend analysis over time

## Manual Testing

Run the training manually without waiting for 1-4 AM:

```powershell
cd C:\Users\akodoreign\Desktop\chatGPT-discord-bot
python scripts\test_module_quality_training.py
```

## Integration with Nightly Learning

The training runs automatically during the 1-4 AM learning window as part of `run_learning_session()`:

```python
studies = [
    ...
    ("module_quality_training", study_module_quality, "module_quality_report"),
    ...
]
```

Position: After world_state assessment, before news_memory study.

## Key Design Decisions

### Isolation
- Test missions go to `logs/learning/` NOT `generated_modules/`
- No Discord client used = no posting
- Metadata includes `is_learning_test: true`

### DM Control
- Patches require explicit DM approval
- Journal provides transparency into learning process
- Test modules saved for inspection

### Iterative Improvement
- Each session builds on previous learnings
- Quality journal enables trend tracking
- Patches accumulate for batch review

## Last Checkpoint
Step: COMPLETE
Time: 2026-04-03T16:00:00Z
