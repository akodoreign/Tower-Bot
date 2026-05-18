"""
dungeon_delve/docx_formatter.py — Format dungeon delve data for DOCX generation.

Converts dungeon layout + room content into the structure expected
by the Node.js DOCX builder script.

Exported:
    format_dungeon_delve_module(dungeon_data) -> dict
    build_room_markdown(room_content, room_number) -> str
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .layouts import DungeonLayout, RoomPosition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Markdown Formatting
# ---------------------------------------------------------------------------

def _format_creature_table(creatures: List[dict]) -> str:
    """Format creature list as a markdown table."""
    if not creatures:
        return ""
    
    lines = [
        "| Creature | Count | CR | HP | Notes |",
        "|----------|-------|----|----|-------|",
    ]
    
    for creature in creatures:
        name = creature.get("name", "Unknown")
        count = creature.get("count", 1)
        cr = creature.get("cr", "1")
        hp = creature.get("hp", "?")
        notes = creature.get("notes", "")
        lines.append(f"| {name} | {count} | {cr} | {hp} | {notes} |")
    
    return "\n".join(lines)


def _format_features_list(features: List[str]) -> str:
    """Format features as a bullet list."""
    if not features:
        return "- No notable features"
    return "\n".join(f"- {f}" for f in features)


def build_room_markdown(
    room: RoomPosition,
    content: dict,
    room_number: int,
) -> str:
    """
    Build markdown for a single room.
    
    Args:
        room: Room position data
        content: Generated room content
        room_number: 1-based room number
    
    Returns:
        Markdown string for the room section
    """
    name = content.get("name", f"Room {room_number}")
    room_type = room.room_type.title()
    read_aloud = content.get("read_aloud", "You enter a dark chamber.")
    features = content.get("features", [])
    encounter = content.get("encounter")
    treasure = content.get("treasure")
    traps = content.get("traps")
    secrets = content.get("secrets")
    exits = ", ".join(e.title() for e in room.exits) if room.exits else "None"
    
    # Build sections
    sections = []
    
    # Header
    sections.append(f"### Room {room_number}: {name}")
    sections.append(f"**Type:** {room_type} | **Exits:** {exits}")
    sections.append("")
    
    # Read-aloud box (using > for blockquote style)
    sections.append("> " + read_aloud.replace("\n", "\n> "))
    sections.append("")
    
    # Features
    sections.append("**Features:**")
    sections.append(_format_features_list(features))
    sections.append("")
    
    # Encounter
    if encounter:
        sections.append("**Encounter:**")
        desc = encounter.get("description", "Hostile creatures")
        sections.append(f"*{desc}*")
        sections.append("")
        
        creatures = encounter.get("creatures", [])
        if creatures:
            sections.append(_format_creature_table(creatures))
            sections.append("")
        
        # Tactical notes
        if any(c.get("notes") for c in creatures):
            sections.append("**Tactics:**")
            for c in creatures:
                if c.get("notes"):
                    sections.append(f"- **{c['name']}:** {c['notes']}")
            sections.append("")
    
    # Treasure
    if treasure:
        sections.append(f"**Treasure:** {treasure}")
        sections.append("")
    
    # Traps
    if traps:
        sections.append(f"**Traps/Hazards:** {traps}")
        sections.append("")
    
    # Secrets
    if secrets:
        sections.append(f"**Secrets:** {secrets}")
        sections.append("")
    
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Module Formatting
# ---------------------------------------------------------------------------

def format_dungeon_delve_module(
    dungeon_name: str,
    dungeon_lore: str,
    location_name: str,
    district: str,
    layout: DungeonLayout,
    room_content: Dict[str, dict],
    faction: str,
    tier: str,
    cr: int,
    party_level: int,
    reward: str,
    composite_map_path: Optional[Path] = None,
    player_name: str = "Unclaimed",
) -> dict:
    """
    Format a complete dungeon delve module for the DOCX builder.
    
    Args:
        dungeon_name: Title of the dungeon/mission
        dungeon_lore: Backstory and history
        location_name: Gazetteer location name
        district: City district
        layout: Dungeon layout with room positions
        room_content: Dict mapping room_id → content dict
        faction: Associated faction
        tier: Mission tier (dungeon-delve, epic, etc.)
        cr: Challenge rating
        party_level: Target party level
        reward: Reward string
        composite_map_path: Path to the composite map image
        player_name: Claiming player name
    
    Returns:
        Dict formatted for build_module_docx.js
    """
    total_rooms = len(layout.rooms)
    encounter_count = sum(
        1 for room_id, content in room_content.items()
        if content.get("encounter")
    )
    
    # Estimate runtime: 15-25 minutes per room with encounters
    min_runtime = encounter_count * 15 + (total_rooms - encounter_count) * 10
    max_runtime = encounter_count * 25 + (total_rooms - encounter_count) * 15
    
    # Build overview section
    overview = f"""## Mission Overview

**Dungeon:** {location_name}
**District:** {district}
**Faction:** {faction}

### Background

{dungeon_lore}

### Mission Parameters

| Parameter | Value |
|-----------|-------|
| Total Rooms | {total_rooms} |
| Encounter Count | {encounter_count} |
| Challenge Rating | CR {cr} |
| Party Level | {party_level} |
| Estimated Runtime | {min_runtime}-{max_runtime} minutes |

### Dungeon Map

*See the composite dungeon map attached to this module. Each room is numbered and corresponds to the room descriptions below.*

### How to Use This Module

1. **Prepare:** Read through all room descriptions before the session
2. **Entry:** Start at Room 1 (the dungeon entrance)
3. **Exploration:** Let players choose their path based on exits
4. **Pacing:** Not every room needs combat—use non-combat rooms for breathing space
5. **Finale:** Room {total_rooms} is the boss encounter—build toward it
"""
    
    # Build room sections (split into two halves for acts_1_2 and acts_3_4)
    all_room_md = []
    for i, room in enumerate(layout.rooms):
        room_number = i + 1
        content = room_content.get(room.room_id, {})
        room_md = build_room_markdown(room, content, room_number)
        all_room_md.append(room_md)
    
    # Split rooms between acts_1_2 and acts_3_4
    midpoint = (total_rooms + 1) // 2
    
    acts_1_2 = "## Dungeon Rooms (Part 1)\n\n" + "\n---\n\n".join(all_room_md[:midpoint])
    acts_3_4 = "## Dungeon Rooms (Part 2)\n\n" + "\n---\n\n".join(all_room_md[midpoint:])
    
    # Build completion section
    act_5_rewards = f"""## Mission Completion

### Victory Conditions

The mission is complete when the party has:

1. **Explored the dungeon** — Visited at least {total_rooms - 1} rooms
2. **Defeated the boss** — Overcome or bypassed the encounter in Room {total_rooms}
3. **Achieved their objective** — Based on faction goals

### Rewards

**Primary Reward:** {reward}

**Bonus Objectives:**
- Full exploration (all {total_rooms} rooms): +10% EC bonus
- No party deaths: +100 Kharma
- Recovered all treasure: Faction reputation bonus

### Aftermath

After clearing the dungeon:
- The {faction} considers this a successful contract
- The location may be claimed or sealed by the faction
- Future missions may reference this dungeon's state
- Any rescued NPCs provide information or future hooks

### DM Notes

- Room {total_rooms} is designed as the climactic encounter
- Adjust encounter difficulty based on party resources when they arrive
- The dungeon aesthetic is "{layout.aesthetic}" — maintain this atmosphere
- Players who retreat and rest may find the dungeon has reset or reinforced
"""
    
    # Assemble final structure
    return {
        "title": dungeon_name,
        "faction": faction,
        "tier": tier,
        "cr": cr,
        "player_level": party_level,
        "player_name": player_name,
        "reward": reward,
        "generated_at": datetime.now().isoformat(),
        "sections": {
            "overview": overview,
            "acts_1_2": acts_1_2,
            "acts_3_4": acts_3_4,
            "act_5_rewards": act_5_rewards,
        },
        "raw_content": f"{overview}\n\n{acts_1_2}\n\n{acts_3_4}\n\n{act_5_rewards}",
        "metadata": {
            "type": "dungeon_delve",
            "location": location_name,
            "district": district,
            "room_count": total_rooms,
            "encounter_count": encounter_count,
            "aesthetic": layout.aesthetic,
            "layout_name": layout.name,
        },
        "dungeon_map": str(composite_map_path) if composite_map_path else None,
    }


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "format_dungeon_delve_module",
    "build_room_markdown",
]
