"""
dungeon_delve — Multi-room dungeon generation for Tower of Last Chance.

This package generates complete dungeon delve missions with:
- Procedural room layouts (4-8 connected rooms)
- LLM-generated room descriptions and encounters
- A1111-generated room tiles (512x512 each)
- Stitched composite dungeon maps with labels
- DOCX module integration

Usage:
    from src.mission_builder.dungeon_delve import generate_dungeon_delve
    
    # Party level auto-detected from character_memory.txt
    result = await generate_dungeon_delve(
        location_name="The Old Prison",  # Optional — auto-selects if None
        faction="Wardens of Ash",
    )
    
    # Or override with explicit level:
    result = await generate_dungeon_delve(party_level=8)
    
    # result contains:
    #   - module_data: Dict for DOCX generation
    #   - composite_map: bytes (PNG)
    #   - room_tiles: Dict[room_id, bytes]

Exported:
    generate_dungeon_delve() — Main entry point
    DungeonLayout, RoomPosition — Layout dataclasses
    DungeonContext — Context for generation
"""

from __future__ import annotations

import os
import json
import random
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from .layouts import (
    DungeonLayout,
    RoomPosition,
    generate_layout,
    get_aesthetic_for_location,
    LOCATION_AESTHETICS,
)
from .room_generator import (
    DungeonContext,
    generate_all_rooms,
)
from .tile_generator import (
    generate_all_tiles,
)
from .stitcher import (
    stitch_dungeon_map,
    create_placeholder_map,
)

# Import dynamic CR/level detection from parent mission_builder
from src.mission_builder.encounters import get_max_pc_level, get_cr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DOCS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "campaign_docs"
GAZETTEER_FILE = DOCS_DIR / "city_gazetteer.json"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "generated_modules"


# ---------------------------------------------------------------------------
# Location Selection
# ---------------------------------------------------------------------------

def _load_gazetteer() -> Dict:
    """Load the city gazetteer."""
    if not GAZETTEER_FILE.exists():
        logger.warning("🏰 Gazetteer not found, using fallback locations")
        return {}
    
    try:
        return json.loads(GAZETTEER_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"🏰 Failed to load gazetteer: {e}")
        return {}


def get_dungeon_locations() -> List[Dict]:
    """Get all dungeon-appropriate locations from the gazetteer."""
    gazetteer = _load_gazetteer()
    locations = []
    
    # Get named dungeons
    dungeons = gazetteer.get("underground_network", {}).get("dungeons", {}).get("locations", [])
    for d in dungeons:
        locations.append({
            "name": d.get("name", "Unknown"),
            "type": "dungeon",
            "district": d.get("district", "Unknown"),
            "description": d.get("description", ""),
            "history": d.get("history", ""),
            "danger_level": d.get("danger_level", "high"),
            "levels": d.get("levels", 3),
        })
    
    # Get lairs
    lairs = gazetteer.get("underground_network", {}).get("lairs", {}).get("locations", [])
    for lair in lairs:
        locations.append({
            "name": lair.get("name", "Unknown"),
            "type": "lair",
            "district": lair.get("district", "Unknown"),
            "description": lair.get("description", ""),
            "inhabitants": lair.get("inhabitants", "Unknown creatures"),
            "danger_level": lair.get("danger_level", "high"),
        })
    
    # Get sewer sections
    sewers = gazetteer.get("underground_network", {}).get("sewers", {}).get("major_sections", [])
    for sewer in sewers:
        if sewer.get("danger_level", "low") in ("moderate", "high", "extreme"):
            locations.append({
                "name": sewer.get("name", "Unknown"),
                "type": "sewer",
                "ring": sewer.get("ring", "varies"),
                "description": sewer.get("description", ""),
                "danger_level": sewer.get("danger_level", "moderate"),
                "sub_locations": sewer.get("locations", []),
            })
    
    return locations


def select_dungeon_location(
    party_level: int,
    preferred_type: Optional[str] = None,
) -> Dict:
    """
    Select an appropriate dungeon location for the party level.
    
    Args:
        party_level: Average party level
        preferred_type: Optional preferred type (dungeon, lair, sewer)
    
    Returns:
        Location dict from gazetteer
    """
    locations = get_dungeon_locations()
    
    if not locations:
        # Fallback
        return {
            "name": "Forgotten Catacombs",
            "type": "dungeon",
            "district": "Eastern Warrens",
            "description": "Ancient burial chambers beneath the city.",
            "danger_level": "high",
        }
    
    # Filter by type if specified
    if preferred_type:
        type_locations = [loc for loc in locations if loc.get("type") == preferred_type]
        if type_locations:
            locations = type_locations
    
    # Filter by danger level based on party level
    if party_level <= 4:
        danger_filter = ["low", "moderate"]
    elif party_level <= 8:
        danger_filter = ["moderate", "high"]
    elif party_level <= 12:
        danger_filter = ["high", "extreme"]
    else:
        danger_filter = ["extreme", "high"]
    
    level_appropriate = [
        loc for loc in locations
        if loc.get("danger_level", "high") in danger_filter
    ]
    
    if level_appropriate:
        return random.choice(level_appropriate)
    
    return random.choice(locations)


# ---------------------------------------------------------------------------
# Main Generation Function
# ---------------------------------------------------------------------------

async def generate_dungeon_delve(
    location_name: Optional[str] = None,
    faction: str = "Independent",
    party_level: Optional[int] = None,
    tier: str = "dungeon-delve",
    use_llm: bool = True,
    generate_tiles: bool = True,
    player_name: str = "Unclaimed",
    reward: str = "500 EC + 100 Kharma",
) -> Dict[str, Any]:
    """
    Generate a complete dungeon delve mission.
    
    Args:
        location_name: Optional specific location name (auto-selects if None)
        faction: Sponsoring faction
        party_level: Average party level (auto-detected from character_memory.txt if None)
        tier: Mission tier (for mission board, defaults to "dungeon-delve")
        use_llm: Whether to use LLM for room descriptions
        generate_tiles: Whether to generate A1111 room tiles
        player_name: Name of claiming player/party
        reward: Reward string
    
    Returns:
        Dict containing:
            - module_data: Complete module data for DOCX
            - composite_map: PNG bytes of stitched map
            - room_tiles: Dict[room_id, bytes] of individual tiles
            - layout: DungeonLayout used
            - room_info: Dict[room_id, dict] of room content
    """
    # Dynamic party level detection — same as other mission types
    if party_level is None:
        party_level = get_max_pc_level()
        if party_level <= 0:
            party_level = 5  # Fallback default
            logger.warning("🏰 Could not detect party level from character_memory.txt, using default level 5")
        else:
            logger.info(f"🏰 Auto-detected party level: {party_level}")
    
    # Dynamic CR calculation based on party level and tier
    cr_target = get_cr(tier)
    
    logger.info(f"🏰 Starting dungeon delve generation for level {party_level} party (CR {cr_target})")
    
    # Select or validate location
    if location_name:
        location = {
            "name": location_name,
            "type": "dungeon",
            "description": f"A dangerous location known as {location_name}",
            "danger_level": "high",
        }
    else:
        location = select_dungeon_location(party_level)
        location_name = location.get("name", "Unknown Dungeon")
    
    logger.info(f"🏰 Selected location: {location_name}")
    
    # Get aesthetic for this location
    aesthetic = get_aesthetic_for_location(location_name)
    logger.info(f"🏰 Using aesthetic: {aesthetic}")
    
    # Generate layout
    layout = generate_layout(party_level)
    layout.aesthetic = aesthetic
    logger.info(f"🏰 Generated layout: {layout.name} with {len(layout.rooms)} rooms")
    
    # Create context
    context = DungeonContext(
        dungeon_name=location_name,
        location_description=location.get("description", "A dangerous underground location"),
        faction=faction,
        aesthetic=aesthetic,
        party_level=party_level,
        cr_target=cr_target,
        history=location.get("history", ""),
        objective=f"Clear {location_name} of threats and recover any artifacts",
    )
    
    # Generate room content
    logger.info(f"🏰 Generating room content (LLM={use_llm})...")
    room_info = await generate_all_rooms(layout, context, use_llm=use_llm)
    
    # Generate tiles
    room_tiles: Dict[str, bytes] = {}
    if generate_tiles:
        logger.info(f"🏰 Generating {len(layout.rooms)} room tiles via A1111...")
        room_tiles = await generate_all_tiles(layout, aesthetic)
        logger.info(f"🏰 Generated {len(room_tiles)} tiles")
    
    # Create composite map
    if room_tiles:
        logger.info(f"🏰 Stitching composite map...")
        composite_map = stitch_dungeon_map(layout, room_tiles, room_info)
    else:
        logger.info(f"🏰 Creating placeholder map (no tiles)...")
        composite_map = create_placeholder_map(layout, room_info)
    
    # Build module data for DOCX
    module_data = _build_module_data(
        location_name=location_name,
        location=location,
        layout=layout,
        room_info=room_info,
        context=context,
        faction=faction,
        tier=tier,
        player_name=player_name,
        reward=reward,
    )
    
    logger.info(f"🏰 Dungeon delve generation complete: {location_name}")
    
    return {
        "module_data": module_data,
        "composite_map": composite_map,
        "room_tiles": room_tiles,
        "layout": layout,
        "room_info": room_info,
        "location": location,
        "context": context,
    }


def _build_module_data(
    location_name: str,
    location: Dict,
    layout: DungeonLayout,
    room_info: Dict[str, Dict],
    context: DungeonContext,
    faction: str,
    tier: str,
    player_name: str,
    reward: str,
) -> Dict:
    """Build module data structure for DOCX generation."""
    
    # Count encounters
    encounter_count = sum(1 for r in room_info.values() if r.get("encounter"))
    
    # Build overview section
    overview = f"""## Dungeon Overview

**Location:** {location_name}
**District:** {location.get('district', 'Unknown')}
**Danger Level:** {location.get('danger_level', 'High').title()}

{location.get('description', 'A dangerous underground location.')}

{location.get('history', '')}

### Mission Parameters

- **Total Rooms:** {len(layout.rooms)}
- **Expected Encounters:** {encounter_count}
- **Estimated Runtime:** {len(layout.rooms) * 15}-{len(layout.rooms) * 25} minutes
- **Target CR:** {context.cr_target}

### Objective

{context.objective}

### Dungeon Map

*See the attached composite dungeon map for room layout and connections.*
"""

    # Build room-by-room sections
    rooms_part1 = []
    rooms_part2 = []
    
    for i, room in enumerate(layout.rooms):
        info = room_info.get(room.room_id, {})
        room_md = _format_room_markdown(i + 1, room, info)
        
        if i < len(layout.rooms) // 2:
            rooms_part1.append(room_md)
        else:
            rooms_part2.append(room_md)
    
    acts_1_2 = "## Dungeon Rooms (Part 1)\n\n" + "\n---\n".join(rooms_part1)
    acts_3_4 = "## Dungeon Rooms (Part 2)\n\n" + "\n---\n".join(rooms_part2)
    
    # Build rewards section
    act_5_rewards = f"""## Completion & Rewards

### Victory Conditions

The dungeon delve is complete when:
- The party has explored at least {len(layout.rooms) - 2} rooms
- The boss encounter in Room {len(layout.rooms)} has been defeated or bypassed
- The objective has been achieved

### Rewards

**Primary Reward:** {reward}

### Aftermath

With {location_name} cleared, the sponsoring faction ({faction}) will be grateful. This may improve the party's standing with {faction} and open future opportunities.

### Experience Points

Award XP based on encounters defeated and challenges overcome. For a party of appropriate level, this dungeon should provide approximately {encounter_count * 200}-{encounter_count * 400} XP total.
"""
    
    return {
        "title": f"Dungeon Delve: {location_name}",
        "faction": faction,
        "tier": tier,
        "cr": context.cr_target,
        "player_level": context.party_level,
        "player_name": player_name,
        "reward": reward,
        "generated_at": datetime.now().isoformat(),
        "sections": {
            "overview": overview,
            "acts_1_2": acts_1_2,
            "acts_3_4": acts_3_4,
            "act_5_rewards": act_5_rewards,
        },
        "dungeon_type": "delve",
        "room_count": len(layout.rooms),
        "encounter_count": encounter_count,
    }


def _format_room_markdown(room_num: int, room: RoomPosition, info: Dict) -> str:
    """Format a single room as markdown."""
    name = info.get("name", f"{room.room_type.title()} {room_num}")
    room_type = info.get("type", room.room_type)
    read_aloud = info.get("read_aloud", "You enter a dark chamber.")
    features = info.get("features", [])
    
    md = f"""### Room {room_num}: {name}

**Room Type:** {room_type.title()}

> {read_aloud}

**Features:**
"""
    for feature in features:
        md += f"- {feature}\n"
    
    # Encounter
    encounter = info.get("encounter")
    if encounter:
        md += f"\n**Encounter:** {encounter.get('description', 'Monsters')}\n\n"
        md += "| Creature | Count | CR | HP | Notes |\n"
        md += "|----------|-------|----|----|-------|\n"
        for creature in encounter.get("creatures", []):
            md += f"| {creature['name']} | {creature['count']} | {creature['cr']} | {creature['hp']} | {creature.get('notes', '')} |\n"
    
    # Treasure
    treasure = info.get("treasure")
    if treasure:
        md += f"\n**Treasure:** {treasure}\n"
    
    # Traps
    traps = info.get("traps")
    if traps:
        md += f"\n**Traps/Hazards:** {traps}\n"
    
    # DM Notes
    dm_notes = info.get("dm_notes")
    if dm_notes:
        md += f"\n*DM Notes: {dm_notes}*\n"
    
    return md


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

async def save_dungeon_delve(
    result: Dict[str, Any],
    output_dir: Optional[Path] = None,
) -> Dict[str, Path]:
    """
    Save dungeon delve outputs to files.
    
    Args:
        result: Result dict from generate_dungeon_delve()
        output_dir: Output directory (defaults to generated_modules/)
    
    Returns:
        Dict of saved file paths
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    
    # Create subdirectory for this dungeon
    location_name = result["module_data"]["title"].replace("Dungeon Delve: ", "")
    safe_name = "".join(c for c in location_name if c.isalnum() or c in " -_").strip()
    safe_name = safe_name.replace(" ", "_")[:50]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    dungeon_dir = output_dir / f"{safe_name}_{timestamp}"
    dungeon_dir.mkdir(parents=True, exist_ok=True)
    
    saved_files = {}
    
    # Save composite map
    map_path = dungeon_dir / "composite_map.png"
    map_path.write_bytes(result["composite_map"])
    saved_files["composite_map"] = map_path
    
    # Save individual tiles
    tiles_dir = dungeon_dir / "tiles"
    tiles_dir.mkdir(exist_ok=True)
    for room_id, tile_bytes in result.get("room_tiles", {}).items():
        tile_path = tiles_dir / f"{room_id}.png"
        tile_path.write_bytes(tile_bytes)
        saved_files[room_id] = tile_path
    
    # Save module data JSON
    json_path = dungeon_dir / "module_data.json"
    json_path.write_text(json.dumps(result["module_data"], indent=2), encoding="utf-8")
    saved_files["module_json"] = json_path
    
    # Save room info JSON
    room_info_path = dungeon_dir / "room_info.json"
    room_info_path.write_text(json.dumps(result["room_info"], indent=2), encoding="utf-8")
    saved_files["room_info"] = room_info_path
    
    logger.info(f"🏰 Saved dungeon delve to: {dungeon_dir}")
    
    return saved_files


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    # Main function
    "generate_dungeon_delve",
    "save_dungeon_delve",
    
    # Location helpers
    "get_dungeon_locations",
    "select_dungeon_location",
    
    # Layout classes
    "DungeonLayout",
    "RoomPosition",
    "generate_layout",
    
    # Context
    "DungeonContext",
    
    # Level/CR helpers (re-exported from encounters.py)
    "get_max_pc_level",
    "get_cr",
    
    # Sub-modules (for direct access if needed)
    "layouts",
    "room_generator",
    "tile_generator",
    "stitcher",
]
