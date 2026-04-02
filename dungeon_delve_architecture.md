# Dungeon Delve Architecture Document
## Tower of Last Chance — Multi-Room Dungeon Mission Type

**Version:** 1.0
**Date:** 2026-03-30
**Authors:** D&D Expert, Python Expert, A1111 Expert

---

## 1. Overview

The Dungeon Delve is a new mission type that generates procedural multi-room dungeons using the Undercity's existing locations from `city_gazetteer.json`. Unlike standard missions (which have investigation leads → confrontation), Dungeon Delves are **room-by-room exploration** with:

- **4-8 connected rooms** forming a logical dungeon
- **Individual 512×512 room tiles** generated via A1111
- **Stitched composite map** with room labels and connections
- **DOCX document** with room-by-room descriptions, encounters, and the composite map

---

## 2. Dungeon Structure Design (D&D Expert)

### 2.1 Room Types

Each dungeon contains rooms selected from these archetypes:

| Room Type | Purpose | Features | Encounter Chance |
|-----------|---------|----------|------------------|
| **Entry** | Dungeon entrance | Guard post, traps, warning signs | 50% |
| **Corridor** | Connects rooms | Narrow passages, patrol routes | 30% |
| **Chamber** | General room | Columns, debris, varied purposes | 60% |
| **Lair** | Monster den | Nests, loot, environmental hazards | 100% |
| **Vault** | Treasure room | Locked, trapped, valuable contents | 80% |
| **Shrine** | Religious space | Altar, ritual items, undead/divine | 70% |
| **Workshop** | Crafting area | Tools, materials, constructs | 50% |
| **Prison** | Cells/holding | Cages, chains, captives/undead | 60% |
| **Flooded** | Water hazard | Partial/full flood, aquatic enemies | 80% |
| **Boss** | Final encounter | Large space, dramatic features | 100% |

### 2.2 Room Generation Rules

1. **Entry room is always first** — establishes the dungeon entrance
2. **Boss room is always last** — climactic encounter
3. **Rooms must connect logically** — no floating disconnected rooms
4. **2-4 encounters per dungeon** — not every room has combat
5. **Treasure scales with CR** — higher CR = better loot
6. **Environmental variety** — mix room types for interest

### 2.3 Dungeon Layouts (Grid Patterns)

Dungeons use predefined layouts that define room positions on a grid:

```
LINEAR (4-6 rooms):
[E]→[C]→[C]→[B]

BRANCHING (5-7 rooms):
    [C]
     ↑
[E]→[C]→[C]→[B]
     ↓
    [C]

LOOP (6-8 rooms):
[E]→[C]→[C]
 ↓       ↓
[C]←[C]←[B]

COMPLEX (7-8 rooms):
    [C]→[C]
     ↑   ↓
[E]→[C]→[C]→[B]
     ↓
    [C]
```

### 2.4 Encounter Building (CR-scaled)

Based on party level from `character_memory.txt`:

| Party Level | Dungeon CR | Minion CR | Boss CR | Rooms |
|-------------|------------|-----------|---------|-------|
| 1-4 | 2-4 | 1/4-1 | 2-4 | 4-5 |
| 5-8 | 5-8 | 1-3 | 5-8 | 5-6 |
| 9-12 | 9-12 | 3-5 | 9-12 | 6-7 |
| 13-16 | 13-16 | 5-8 | 13-16 | 7-8 |
| 17-20 | 17-20 | 8-12 | 17-20 | 7-8 |

### 2.5 Location Selection

Dungeons are selected from `city_gazetteer.json` categories:

1. **Named Dungeons** (canonical multi-level sites)
2. **Monster Lairs** (creature-specific encounters)
3. **Sewer Sections** (urban underground)
4. **Faction Sanctums** (if mission involves that faction)

Selection factors:
- Danger level matches party CR
- District aesthetic influences room style
- History/lore creates narrative hooks

---

## 3. Room Tile Generation (A1111 Expert)

### 3.1 Tile Specifications

| Property | Value | Notes |
|----------|-------|-------|
| Dimensions | 512×512 | Grid-friendly, fast generation |
| Style | Top-down tactical | VTT-ready |
| Borders | Edge-aware | North/South/East/West exit indicators |
| Labels | None in image | Labels added during stitching |

### 3.2 A1111 Payload Structure

```python
TILE_PAYLOAD = {
    "prompt": "{base_style}, {room_type}, {dungeon_aesthetic}, {room_features}",
    "negative_prompt": "{standard_negatives}",
    "width": 512,
    "height": 512,
    "steps": 25,
    "cfg_scale": 7.0,
    "sampler_name": "DPM++ 2M Karras",
    "seed": -1,  # Random, but save for consistency
}
```

### 3.3 Room Type Prompts

Base style (all rooms):
```
top-down tactical dungeon room, D&D battlemap tile, dark fantasy, 
orthographic view, grid-ready, clear floor texture, defined walls, 
single room interior, torch lighting, high contrast edges
```

Room-specific additions:
```python
ROOM_PROMPTS = {
    "entry": "stone archway entrance, heavy door, guard alcoves, flickering torches",
    "corridor": "narrow stone passage, wall sconces, floor tiles, connecting hallway",
    "chamber": "large open room, support pillars, scattered debris, stone floor",
    "lair": "creature nest, bones and refuse, organic matter, territorial marks",
    "vault": "treasure room, locked chests, pedestals, iron door, trap indicators",
    "shrine": "altar centerpiece, religious symbols, candles, offering bowls",
    "workshop": "workbenches, tools, arcane circles, unfinished projects",
    "prison": "iron bars, cells, chains on walls, suffering marks",
    "flooded": "water covering floor, partially submerged, wet stone, algae",
    "boss": "large dramatic chamber, raised platform, impressive centerpiece, arena-like",
}
```

### 3.4 Dungeon Aesthetic Overlays

Based on gazetteer location:
```python
DUNGEON_AESTHETICS = {
    "prison": "iron bars, stone blocks, rusted metal, cold damp atmosphere",
    "temple": "religious architecture, broken altar, divine symbols, cracked mosaics",
    "arcane": "magical residue, glowing runes, strange apparatus, crystalline formations",
    "sewer": "brick tunnels, water channels, grates, industrial decay",
    "natural": "cave walls, stalactites, uneven floor, natural stone",
    "ruined": "collapsed sections, debris, overgrown, ancient decay",
    "volcanic": "obsidian, lava glow, heat shimmer, sulfur deposits",
}
```

### 3.5 Exit Indicators

Rooms have exits (passages to adjacent rooms). The tile prompt includes exit hints:
```python
def add_exit_hints(base_prompt: str, exits: List[str]) -> str:
    hints = []
    if "north" in exits:
        hints.append("open passage at top edge")
    if "south" in exits:
        hints.append("open passage at bottom edge")
    if "east" in exits:
        hints.append("open passage at right edge")
    if "west" in exits:
        hints.append("open passage at left edge")
    return f"{base_prompt}, {', '.join(hints)}"
```

### 3.6 Negative Prompt

```
3d render, perspective, isometric, character, people, monsters,
miniatures, tokens, grid lines, numbers, text, watermark, signature,
multiple rooms, outdoor, sky, sun, bright daylight, blurry, low quality,
photo, realistic photograph, UI elements, borders, frames
```

---

## 4. Image Stitching Pipeline (Python Expert)

### 4.1 Dependencies

```python
from PIL import Image, ImageDraw, ImageFont
import asyncio
from pathlib import Path
from typing import List, Dict, Tuple, Optional
```

### 4.2 Grid Layout System

```python
@dataclass
class RoomPosition:
    room_id: str
    grid_x: int  # 0-based column
    grid_y: int  # 0-based row
    room_type: str
    exits: List[str]  # ["north", "east", etc.]
    
@dataclass
class DungeonLayout:
    rooms: List[RoomPosition]
    grid_width: int   # Number of columns
    grid_height: int  # Number of rows
    
    def get_canvas_size(self, tile_size: int = 512, padding: int = 64) -> Tuple[int, int]:
        width = self.grid_width * tile_size + padding * 2
        height = self.grid_height * tile_size + padding * 2 + 100  # Extra for legend
        return width, height
```

### 4.3 Stitching Algorithm

```python
async def stitch_dungeon_map(
    layout: DungeonLayout,
    room_tiles: Dict[str, bytes],  # room_id → PNG bytes
    room_info: Dict[str, dict],    # room_id → {name, description, monsters}
    tile_size: int = 512,
    padding: int = 64,
) -> bytes:
    """
    Stitch individual room tiles into a composite dungeon map.
    
    Returns PNG bytes of the composite map.
    """
    canvas_w, canvas_h = layout.get_canvas_size(tile_size, padding)
    
    # Create canvas with dark background
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (30, 30, 35, 255))
    draw = ImageDraw.Draw(canvas)
    
    # Place each room tile
    for room in layout.rooms:
        if room.room_id not in room_tiles:
            continue
            
        # Calculate position
        x = padding + room.grid_x * tile_size
        y = padding + room.grid_y * tile_size
        
        # Load and paste tile
        tile_img = Image.open(io.BytesIO(room_tiles[room.room_id]))
        tile_img = tile_img.resize((tile_size, tile_size), Image.LANCZOS)
        canvas.paste(tile_img, (x, y))
        
        # Draw room label
        label_x = x + 20
        label_y = y + 20
        room_num = room.room_id.split("_")[-1]
        
        # White circle background
        draw.ellipse([label_x-15, label_y-15, label_x+15, label_y+15], 
                    fill="white", outline="black")
        draw.text((label_x, label_y), room_num, fill="black", anchor="mm")
    
    # Convert to bytes
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
```

---

## 5. File Structure

```
src/
  mission_builder/
    dungeon_delve/
      __init__.py           # Main entry point
      room_generator.py     # Room content generation (LLM)
      layout_generator.py   # Grid layout selection
      tile_generator.py     # A1111 room tile generation
      stitcher.py           # PIL-based map stitching
      docx_formatter.py     # DOCX structure formatting
    maps.py                 # (existing) - extend for tiles
    docx_builder.py         # (existing) - extend for images
```

---

## 6. Next Steps

1. Create `src/mission_builder/dungeon_delve/` package
2. Implement `layout_generator.py` — Layout selection and room positioning
3. Implement `room_generator.py` — LLM-based room content generation
4. Implement `tile_generator.py` — A1111 tile generation with room prompts
5. Implement `stitcher.py` — PIL-based composite map creation
6. Implement `docx_formatter.py` — Dungeon delve DOCX structure
7. Extend `build_module_docx.js` — Image embedding support
8. Add to mission board — New dungeon-delve mission type
9. Test end-to-end — Generate sample dungeon
