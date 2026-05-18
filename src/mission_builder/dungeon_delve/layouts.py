"""
dungeon_delve/layouts.py — Dungeon layout patterns and room positioning.

Provides predefined dungeon layouts that define:
- Number of rooms
- Room positions on a grid
- Connections between rooms
- Room type assignments

Exported:
    LAYOUTS: Dict of layout name → layout definition
    generate_layout(party_level: int) -> DungeonLayout
    DungeonLayout dataclass
    RoomPosition dataclass
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class RoomPosition:
    """A single room in the dungeon layout."""
    room_id: str          # Unique identifier (e.g., "room_1")
    grid_x: int           # 0-based column position
    grid_y: int           # 0-based row position
    room_type: str        # entry, corridor, chamber, lair, vault, shrine, workshop, prison, flooded, boss
    exits: List[str] = field(default_factory=list)  # ["north", "south", "east", "west"]
    
    def __post_init__(self):
        if not self.exits:
            self.exits = []


@dataclass
class DungeonLayout:
    """Complete dungeon layout with all room positions."""
    name: str                         # Layout pattern name
    rooms: List[RoomPosition]         # All rooms in order
    grid_width: int                   # Number of columns
    grid_height: int                  # Number of rows
    aesthetic: str = "ruined"         # Visual style override
    
    def get_canvas_size(self, tile_size: int = 512, padding: int = 64) -> Tuple[int, int]:
        """Calculate the final composite map dimensions."""
        width = self.grid_width * tile_size + padding * 2
        height = self.grid_height * tile_size + padding * 2 + 100  # Extra for legend
        return width, height
    
    def get_room_by_id(self, room_id: str) -> Optional[RoomPosition]:
        """Find a room by its ID."""
        for room in self.rooms:
            if room.room_id == room_id:
                return room
        return None
    
    def get_entry_room(self) -> Optional[RoomPosition]:
        """Get the entry room (always room_1)."""
        return self.get_room_by_id("room_1")
    
    def get_boss_room(self) -> Optional[RoomPosition]:
        """Get the boss room (last room)."""
        return self.rooms[-1] if self.rooms else None


# ---------------------------------------------------------------------------
# Room Type Weights by Position
# ---------------------------------------------------------------------------

# Room types for middle rooms (not entry or boss)
MIDDLE_ROOM_TYPES = [
    ("corridor", 15),    # Common connector
    ("chamber", 25),     # Generic room
    ("lair", 10),        # Monster den
    ("vault", 8),        # Treasure
    ("shrine", 8),       # Religious
    ("workshop", 6),     # Crafting
    ("prison", 8),       # Cells
    ("flooded", 5),      # Hazard
]

def _pick_room_type(exclude: Optional[List[str]] = None) -> str:
    """Pick a random room type using weighted selection."""
    exclude = exclude or []
    options = [(t, w) for t, w in MIDDLE_ROOM_TYPES if t not in exclude]
    if not options:
        return "chamber"
    
    total = sum(w for _, w in options)
    roll = random.randint(1, total)
    cumulative = 0
    for room_type, weight in options:
        cumulative += weight
        if roll <= cumulative:
            return room_type
    return "chamber"


# ---------------------------------------------------------------------------
# Layout Templates
# ---------------------------------------------------------------------------

def _linear_4() -> DungeonLayout:
    """4-room linear dungeon: Entry → Chamber → Chamber → Boss"""
    return DungeonLayout(
        name="linear_4",
        grid_width=4,
        grid_height=1,
        rooms=[
            RoomPosition("room_1", 0, 0, "entry", ["east"]),
            RoomPosition("room_2", 1, 0, _pick_room_type(), ["west", "east"]),
            RoomPosition("room_3", 2, 0, _pick_room_type(["corridor"]), ["west", "east"]),
            RoomPosition("room_4", 3, 0, "boss", ["west"]),
        ],
    )


def _linear_5() -> DungeonLayout:
    """5-room linear dungeon"""
    return DungeonLayout(
        name="linear_5",
        grid_width=5,
        grid_height=1,
        rooms=[
            RoomPosition("room_1", 0, 0, "entry", ["east"]),
            RoomPosition("room_2", 1, 0, "corridor", ["west", "east"]),
            RoomPosition("room_3", 2, 0, _pick_room_type(), ["west", "east"]),
            RoomPosition("room_4", 3, 0, _pick_room_type(["corridor"]), ["west", "east"]),
            RoomPosition("room_5", 4, 0, "boss", ["west"]),
        ],
    )


def _branching_5() -> DungeonLayout:
    """5-room T-shaped layout with branch"""
    return DungeonLayout(
        name="branching_5",
        grid_width=4,
        grid_height=3,
        rooms=[
            RoomPosition("room_1", 0, 1, "entry", ["east"]),
            RoomPosition("room_2", 1, 1, "corridor", ["west", "east", "north"]),
            RoomPosition("room_3", 1, 0, _pick_room_type(), ["south"]),  # Branch north
            RoomPosition("room_4", 2, 1, _pick_room_type(["corridor"]), ["west", "east"]),
            RoomPosition("room_5", 3, 1, "boss", ["west"]),
        ],
    )


def _branching_6() -> DungeonLayout:
    """6-room layout with two branches"""
    return DungeonLayout(
        name="branching_6",
        grid_width=4,
        grid_height=3,
        rooms=[
            RoomPosition("room_1", 0, 1, "entry", ["east"]),
            RoomPosition("room_2", 1, 1, "corridor", ["west", "east", "north", "south"]),
            RoomPosition("room_3", 1, 0, _pick_room_type(), ["south"]),  # Branch north
            RoomPosition("room_4", 1, 2, _pick_room_type(), ["north"]),  # Branch south
            RoomPosition("room_5", 2, 1, _pick_room_type(["corridor"]), ["west", "east"]),
            RoomPosition("room_6", 3, 1, "boss", ["west"]),
        ],
    )


def _loop_6() -> DungeonLayout:
    """6-room loop layout"""
    return DungeonLayout(
        name="loop_6",
        grid_width=3,
        grid_height=2,
        rooms=[
            RoomPosition("room_1", 0, 0, "entry", ["east", "south"]),
            RoomPosition("room_2", 1, 0, _pick_room_type(), ["west", "east"]),
            RoomPosition("room_3", 2, 0, _pick_room_type(), ["west", "south"]),
            RoomPosition("room_4", 0, 1, _pick_room_type(), ["north", "east"]),
            RoomPosition("room_5", 1, 1, _pick_room_type(["corridor"]), ["west", "east"]),
            RoomPosition("room_6", 2, 1, "boss", ["west", "north"]),
        ],
    )


def _complex_7() -> DungeonLayout:
    """7-room complex layout with multiple paths"""
    return DungeonLayout(
        name="complex_7",
        grid_width=4,
        grid_height=3,
        rooms=[
            RoomPosition("room_1", 0, 1, "entry", ["east"]),
            RoomPosition("room_2", 1, 1, "corridor", ["west", "north", "south", "east"]),
            RoomPosition("room_3", 1, 0, _pick_room_type(), ["south", "east"]),
            RoomPosition("room_4", 1, 2, _pick_room_type(), ["north"]),
            RoomPosition("room_5", 2, 0, _pick_room_type(), ["west", "south"]),
            RoomPosition("room_6", 2, 1, _pick_room_type(["corridor"]), ["west", "north", "east"]),
            RoomPosition("room_7", 3, 1, "boss", ["west"]),
        ],
    )


def _complex_8() -> DungeonLayout:
    """8-room complex layout — maximum complexity"""
    return DungeonLayout(
        name="complex_8",
        grid_width=4,
        grid_height=3,
        rooms=[
            RoomPosition("room_1", 0, 1, "entry", ["east"]),
            RoomPosition("room_2", 1, 1, "corridor", ["west", "north", "south", "east"]),
            RoomPosition("room_3", 1, 0, _pick_room_type(), ["south", "east"]),
            RoomPosition("room_4", 1, 2, _pick_room_type(), ["north", "east"]),
            RoomPosition("room_5", 2, 0, _pick_room_type(), ["west", "south"]),
            RoomPosition("room_6", 2, 1, _pick_room_type(["corridor"]), ["west", "north", "south", "east"]),
            RoomPosition("room_7", 2, 2, _pick_room_type(), ["west", "north"]),
            RoomPosition("room_8", 3, 1, "boss", ["west"]),
        ],
    )


# ---------------------------------------------------------------------------
# Layout Selection
# ---------------------------------------------------------------------------

# Layouts organized by room count
LAYOUTS_BY_SIZE: Dict[int, List] = {
    4: [_linear_4],
    5: [_linear_5, _branching_5],
    6: [_branching_6, _loop_6],
    7: [_complex_7],
    8: [_complex_8],
}


def get_room_count_for_level(party_level: int) -> int:
    """Determine room count based on party level."""
    if party_level <= 4:
        return random.choice([4, 5])
    elif party_level <= 8:
        return random.choice([5, 6])
    elif party_level <= 12:
        return random.choice([6, 7])
    else:
        return random.choice([7, 8])


def generate_layout(party_level: int, preferred_size: Optional[int] = None) -> DungeonLayout:
    """
    Generate a dungeon layout appropriate for the party level.
    
    Args:
        party_level: Average party level (1-20)
        preferred_size: Optional specific room count (4-8)
    
    Returns:
        A DungeonLayout with randomly assigned room types
    """
    if preferred_size and preferred_size in LAYOUTS_BY_SIZE:
        room_count = preferred_size
    else:
        room_count = get_room_count_for_level(party_level)
    
    # Get layout generators for this size
    generators = LAYOUTS_BY_SIZE.get(room_count, [_linear_5])
    
    # Pick and generate a random layout
    generator = random.choice(generators)
    return generator()


# ---------------------------------------------------------------------------
# Dungeon Aesthetics (from gazetteer locations)
# ---------------------------------------------------------------------------

LOCATION_AESTHETICS: Dict[str, str] = {
    # Named dungeons
    "old prison": "prison",
    "sunken temple": "temple",
    "artificer's folly": "arcane",
    "merchant vaults": "ruined",
    "warden tombs": "temple",
    "rift laboratories": "arcane",
    "drowned coliseum": "flooded",
    "thane's labyrinth": "temple",
    
    # Monster lairs
    "rat king's warren": "sewer",
    "slime pits": "natural",
    "spider galleries": "natural",
    "goblin warrens": "natural",
    "carrion caves": "natural",
    "troll depths": "natural",
    "wyvern roost": "volcanic",
    "mimic alley": "ruined",
    
    # Sewer sections
    "forum sewers": "sewer",
    "sanctum drains": "sewer",
    "market underdrain": "sewer",
    "industrial outflow": "sewer",
    "sewer grid 7": "arcane",
    "deep sewers": "sewer",
}


def get_aesthetic_for_location(location_name: str) -> str:
    """Get the visual aesthetic for a dungeon location."""
    name_lower = location_name.lower()
    for key, aesthetic in LOCATION_AESTHETICS.items():
        if key in name_lower:
            return aesthetic
    return "ruined"  # Default


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "RoomPosition",
    "DungeonLayout",
    "generate_layout",
    "get_room_count_for_level",
    "get_aesthetic_for_location",
    "LOCATION_AESTHETICS",
]
