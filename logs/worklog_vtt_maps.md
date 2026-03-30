# Worklog: VTT Map Generation Pipeline
**Started:** 2026-03-29 02:45 UTC
**Status:** ✅ COMPLETE

## Task Summary
Add automatic VTT battlemap generation to the mission module pipeline:
1. After a mission module DOCX is generated
2. Extract location scenes from the module
3. Generate top-down VTT-compatible battlemaps using A1111
4. Use image_ref.py system to keep references for iterative improvement
5. Attach/link maps to the mission or post to a maps channel

## Steps
- [x] 1. Read mission_builder architecture (docx_builder.py, __init__.py)
- [x] 2. Read image_ref.py to understand the reference system
- [x] 3. Design map generation module (src/mission_builder/maps.py)
- [x] 4. Create VTT map prompts/styles for Undercity aesthetic
- [x] 5. Wire map generation into module pipeline
- [x] 6. Update post_module_to_channel to include maps
- [x] 7. Update worklog and tower-bot skill

## Files Created/Modified

### New File
| File | Purpose |
|------|---------|
| `src/mission_builder/maps.py` | VTT battlemap generation module (~350 lines) |

### Modified Files
| File | Changes |
|------|---------|
| `src/mission_builder/__init__.py` | Added map imports, integrated into generate_module(), updated post_module_to_channel() |

## How It Works

### Automatic Pipeline
When `generate_module()` is called:
1. Module DOCX is generated (existing behavior)
2. **NEW:** `generate_module_maps()` is called automatically
3. Extracts scenes from module (Act 2 leads + Act 4 confrontation)
4. For each scene:
   - Checks `image_ref.py` for existing location reference
   - Builds SD prompt with district + scene type aesthetics
   - Generates 1024x1024 top-down battlemap via A1111
   - Uses img2img if reference exists (iterative improvement)
   - Saves generated map as new reference for future
5. Maps saved to `generated_modules/[module_name]/maps/`
6. When posted to Discord, maps are attached alongside DOCX

### Iterative Improvement via image_ref.py
```
Mission 1 uses "Collapsed Plaza":
  → No reference exists → txt2img generates map
  → Map saved as reference: campaign_docs/image_refs/locations/collapsed_plaza/ref_001.png

Mission 2 uses "Collapsed Plaza":
  → Reference found! → img2img with denoise=0.50
  → Result is more consistent, builds on previous
  → New map saved as ref_001.png, old becomes ref_002.png

Mission 3 uses "Collapsed Plaza":
  → Even better reference available
  → Maps get progressively more consistent and refined
```

### District Aesthetics
Each district has unique visual style:
- **Markets Infinite**: cobblestone, market stalls, lantern light
- **Warrens**: ruins, debris, makeshift shelters, dangerous terrain
- **Guild Spires**: polished stone, ornate pillars, guild banners
- **Sanctum Quarter**: temple architecture, religious symbols
- **Grand Forum**: open plaza, fountains, civic architecture
- **Outer Wall**: fortifications, guard towers, defensive positions

### Scene Type Features
- **Boss**: large central area, dramatic centerpiece, lair features
- **Combat**: clear tactical positions, cover objects, chokepoints
- **Investigation**: clutter, searchable objects, hiding spots
- **Ambush**: hiding spots, high ground, shadows
- **Chase**: long corridors, obstacles, escape routes

## Technical Details

### Map Specifications
- Size: 1024x1024px (grid-friendly)
- Format: PNG
- Style: Top-down orthographic (VTT-ready)
- Steps: 30
- CFG: 7.5
- Sampler: DPM++ 2M Karras

### Scene Extraction
Parses module markdown for:
- `### Lead [N]: [Location]` in Acts 1-2
- `### Battlefield: [Location]` in Act 4
- Falls back to Act 4 section if no explicit battlefield

### Limits
- Max 4 maps per module (prevents runaway)
- Prioritizes Act 4 boss fight, then Act 2 leads
- Respects A1111 lock (waits if busy)

## Environment Variables
```
A1111_URL          — Stable Diffusion WebUI URL (default: http://127.0.0.1:7860)
A1111_MODEL        — Checkpoint for maps (uses photorealistic)
MAPS_CHANNEL_ID    — Optional separate channel for maps (falls back to MODULE_OUTPUT_CHANNEL_ID)
```

## Progress Log
### 2026-03-29 02:45 UTC
- Started task
- Read existing architecture

### 2026-03-29 03:00 UTC
- Created maps.py with full implementation
- Wired into mission_builder pipeline
- Updated post_module_to_channel for map attachments

### 2026-03-29 03:15 UTC
- Task complete!
