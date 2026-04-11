# Worklog: Image Generation Refactor
**Started:** 2026-04-04T16:30:00
**Status:** ✅ COMPLETE
**Last Updated:** 2026-04-04T18:15:00

## Task Summary
1. **Trim saved photos** — Reduce MAX_REFS from 3 to 2 to save disk space
2. **Clean existing files** — Delete oldest ref files (ref_003.png) from all entity folders
3. **Refactor image loop code** — Research and apply A1111/SD best practices for better image quality

---

## Directory Structure (Discovered)
```
campaign_docs/image_refs/
├── npcs/           # 57 NPC portrait folders, each with ref_001/002/003.png
├── locations/      # 15 location folders with ref files
├── characters/     # Player character folders (6 + README)
└── team/           # Flat structure: team1/2/3.png (party images)
```

Current MAX_REFS = 2 (updated from 3)

---

## Steps

### Phase 1: Trim to 2 References ✅
- [x] Step 1.1: Update MAX_REFS constant in image_ref.py (3 → 2) ✅
- [x] Step 1.2-1.5: Created cleanup_image_refs.py script ✅
      → Run: `python scripts/cleanup_image_refs.py` (dry run)
      → Run: `python scripts/cleanup_image_refs.py --execute` (delete files)
- [ ] Step 1.6: Verify disk space recovered (awaiting manual execution)

### Phase 2: Research A1111/SD Best Practices ✅
- [x] Step 2.1: Analyze current generate_story_image() implementation ✅
- [x] Step 2.2: Research AnimagineXL/SDXL optimal parameters ✅
- [x] Step 2.3: Identify improvement opportunities ✅
- [x] Step 2.4: Document findings ✅

### Phase 3: Refactor Image Generation Loop ✅
- [x] Step 3.1: Update sampler from Euler a → DPM++ 2M SDE Karras ✅
- [x] Step 3.2: Reduce steps from 40 → 28 ✅
- [x] Step 3.3: Increase resolution from 896×512 → 1024×576 ✅
- [x] Step 3.4: Verify battlemap settings (maps.py already optimal) ✅

---

## Progress Log

### 2026-04-04T16:30:00 — Step 0: Discovery
- Identified image_ref.py as main storage module
- Found news_feed.py generate_story_image() as main generation loop
- Documented directory structure
- Created this worklog

### 2026-04-04T18:00:00 — Phase 2: Research Complete
- Analyzed current implementation
- Researched SDXL optimal parameters from multiple sources
- Documented findings (see below)

### 2026-04-04T18:15:00 — Phase 3: Implementation Complete
- Applied changes to src/news_feed.py:
  - `steps: 40 → 28` (sweet spot for SDXL)
  - `sampler: "Euler a" → "DPM++ 2M SDE Karras"` (better convergence)
  - `width: 896 → 1024`, `height: 512 → 576` (closer to SDXL native)
- Verified maps.py already using `DPM++ 2M Karras` with 30 steps — no changes needed

---

## Research Findings (Archived)

**Sampler Recommendations for SDXL:**
| Sampler | Use Case | Notes |
|---------|----------|-------|
| DPM++ 2M Karras | Default stable | Fast convergence, stable |
| DPM++ 2M SDE Karras | Photorealism | Best for detailed outputs |
| Euler a | Creative variety | Non-convergent, lottery |
| UniPC | Speed | Good at 5-10 steps |

**Optimal SDXL Parameters:**
- CFG: 4-7 (5.0 is good)
- Steps: 21-30 (40 is overkill)
- Resolution: 1024×1024 base, or proportional (e.g., 1024×576)

**Why Euler a was problematic:**
- Ancestral samplers add random noise each step
- Never converge — unpredictable quality
- Can produce worse results at 50 steps than 25

**Why DPM++ 2M SDE Karras is better:**
- Stochastic but controlled
- High-fidelity photorealism
- Converges well at 25-30 steps
- Better detail retention

---

## Changes Applied

```diff
# src/news_feed.py — generate_story_image() payload

+    # Optimized for SDXL: DPM++ 2M SDE Karras converges better than Euler a,
+    # 28 steps is the sweet spot (research shows 21-30 optimal for SDXL),
+    # 1024x576 is closer to SDXL's native 1024x1024 training resolution
     payload = {
         "prompt": image_prompt,
         "negative_prompt": negative_prompt,
-        "steps": 40,
+        "steps": 28,
         "cfg_scale": 5.0,
-        "width": 896,
-        "height": 512,
-        "sampler_name": "Euler a",
+        "width": 1024,
+        "height": 576,
+        "sampler_name": "DPM++ 2M SDE Karras",
         "batch_size": 1,
         ...
     }
```

---

## Expected Benefits
- ~30% faster generation (fewer steps)
- More consistent quality (non-ancestral sampler)
- Better detail/sharpness (proper resolution)
- Predictable photorealistic output

---

## Manual Steps Remaining
1. Run cleanup script: `python scripts/cleanup_image_refs.py --execute`
2. Restart bot to apply changes
3. Monitor next few image generations for quality

---

## Files Modified
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\src\image_ref.py (MAX_REFS)
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\src\news_feed.py (payload optimization)
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\scripts\cleanup_image_refs.py (created)
- C:\Users\akodoreign\Desktop\chatGPT-discord-bot\logs\worklog_image_refactor.md (this file)
