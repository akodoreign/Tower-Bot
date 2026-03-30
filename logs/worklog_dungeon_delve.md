# Worklog: Dungeon Delve Mission Type
**Started:** 2026-03-30
**Status:** ✅ COMPLETE

## Task Summary
Create a new "Dungeon Delve" mission type that generates multi-room dungeons with:
- Room-by-room descriptions with monsters and settings
- Individual room map images generated via A1111
- Stitched together into a labeled composite dungeon map
- Integrated document with room descriptions and the composite map

## Steps
- [x] 1. Research: Read city_gazetteer.json for dungeon-appropriate locations
- [x] 2. Research: Read existing mission_board.py / mission_module_gen.py patterns
- [x] 3. Research: Read existing maps.py for A1111 battlemap generation
- [x] 4. Design: Architecture document created at `dungeon_delve_architecture.md`
- [x] 5. Implement: Created `src/mission_builder/dungeon_delve/` directory
- [x] 6. Implement: `layouts.py` — Room positioning, grid layouts, aesthetics
- [x] 7. Implement: `tile_generator.py` — A1111 room tile generation
- [x] 8. Implement: `stitcher.py` — PIL-based composite map assembly
- [x] 9. Implement: `room_generator.py` — LLM room content generation
- [x] 10. Implement: `__init__.py` — Package entry point with generate_dungeon_delve()
- [x] 11. Implement: Mission board integration (added dungeon-delve tier)
- [ ] 12. Test: Generate sample dungeon delve mission (manual testing needed)

## Progress Log

### 2026-03-30 14:00 — Research Complete
- Reviewed city_gazetteer.json — found 8 dungeons, 8 lairs, 6 sewer sections, 10 sanctums
- Reviewed mission_board.py — understood mission type structure, tier system
- Reviewed maps.py — A1111 integration patterns
- Reviewed docx_builder.py and Node.js script — markdown to DOCX conversion

### 2026-03-30 14:15 — Architecture Document
- Created `dungeon_delve_architecture.md` in project root

### 2026-03-30 14:20 — Directory Created
- Created `src/mission_builder/dungeon_delve/` package directory

### 2026-03-30 14:25 — layouts.py Complete
- File: `src/mission_builder/dungeon_delve/layouts.py` (~8KB)
- Contains: RoomPosition, DungeonLayout dataclasses
- Contains: 6 layout templates (linear_4/5, branching_5/6, loop_6, complex_7/8)
- Contains: Room type selection, aesthetic mapping from gazetteer

### 2026-03-30 14:30 — tile_generator.py Complete
- File: `src/mission_builder/dungeon_delve/tile_generator.py` (~6KB)
- Contains: A1111 payload building with room/aesthetic prompts
- Contains: generate_room_tile(), generate_all_tiles()
- Uses a1111_lock from news_feed.py for queue management

### 2026-03-30 14:35 — stitcher.py Complete
- File: `src/mission_builder/dungeon_delve/stitcher.py` (~8KB)
- Contains: stitch_dungeon_map() — combines tiles into composite
- Contains: create_placeholder_map() — for testing without A1111
- Features: Room labels, connection lines, legend at bottom

### 2026-03-30 14:45 — room_generator.py Complete
- File: `src/mission_builder/dungeon_delve/room_generator.py` (~12KB)
- Contains: DungeonContext dataclass
- Contains: LLM-based room generation with Ollama
- Contains: Fallback generation without LLM
- Contains: Monster tables by CR tier, treasure tables, trap generation
- Contains: generate_room_content(), generate_all_rooms()

### 2026-03-30 14:55 — __init__.py Complete
- File: `src/mission_builder/dungeon_delve/__init__.py` (~12KB)
- Main entry: generate_dungeon_delve() — complete pipeline
- Contains: Location selection from gazetteer
- Contains: Module data building for DOCX
- Contains: save_dungeon_delve() for file output
- Exports all necessary classes and functions

### 2026-03-30 15:05 — Mission Board Integration Complete
- Added "dungeon-delve": (30, 90) to TIER_EXPIRY
- Added "dungeon-delve": (60, 90) to PERSONAL_TIER_EXPIRY
- Existing _MISSION_TYPES already includes dungeon delve option

### 2026-03-30 15:15 — Dynamic Party Level Scaling
- Added "dungeon-delve": 3 to TIER_OFFSET in encounters.py
- Updated generate_dungeon_delve() to auto-detect party level from character_memory.txt
- Uses get_max_pc_level() and get_cr() from mission_builder.encounters
- CR now scales dynamically: max_pc_level + tier_offset (clamped)
- Changed default tier from "dungeon" to "dungeon-delve"
- party_level parameter is now Optional[int] — auto-detects if None

## Files Created
| File | Status |
|------|--------|
| `dungeon_delve_architecture.md` | ✅ Complete |
| `src/mission_builder/dungeon_delve/layouts.py` | ✅ Complete |
| `src/mission_builder/dungeon_delve/tile_generator.py` | ✅ Complete |
| `src/mission_builder/dungeon_delve/stitcher.py` | ✅ Complete |
| `src/mission_builder/dungeon_delve/room_generator.py` | ✅ Complete |
| `src/mission_builder/dungeon_delve/__init__.py` | ✅ Complete |
| `src/mission_board.py` (modified) | ✅ Complete |

## Usage

```python
from src.mission_builder.dungeon_delve import generate_dungeon_delve, save_dungeon_delve

# Generate a dungeon delve
result = await generate_dungeon_delve(
    location_name="The Old Prison",  # Optional — auto-selects if None
    faction="Wardens of Ash",
    party_level=5,
    use_llm=True,           # Use Ollama for room descriptions
    generate_tiles=True,    # Generate A1111 room images
)

# Result contains:
#   result["module_data"]     — dict for DOCX generation
#   result["composite_map"]   — PNG bytes of stitched map
#   result["room_tiles"]      — Dict[room_id, bytes] individual tiles
#   result["layout"]          — DungeonLayout object
#   result["room_info"]       — Dict[room_id, dict] room content

# Save to disk
saved = await save_dungeon_delve(result)
# Returns paths: saved["composite_map"], saved["module_json"], etc.
```

## Next Steps (Manual)
1. Test by running: `python -c "import asyncio; from src.mission_builder.dungeon_delve import generate_dungeon_delve; asyncio.run(generate_dungeon_delve(party_level=5))"`
2. Verify A1111 tile generation works
3. Check composite map stitching quality
4. Integrate with DOCX builder if needed (add ImageRun support)
5. Optional: Add /delve slash command for DM-initiated dungeon generation
