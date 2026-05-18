"""
infestation_layout.py — Pure-Python ASCII dungeon layout generator for infestation missions.

No LLM involved — deterministic room placement with clear connector marking.
Outputs both a human-readable ASCII map and a structured room graph.

Infestation subtypes and room counts:
  sewer    → 6-10  rooms  (linear/branching, all on one level)
  basement → 6-12  rooms  (grid-like, functional, may have stairs)
  lair     → 8-15  rooms  (organic branching, irregular)
  dungeon  → 10-20 rooms  (complex, multi-level, elevators possible)

ASCII conventions:
  +---+  room border
  | Rn|  room number inside
  ---D-- door between rooms (horizontal)
  | D |  door between rooms (vertical)
  S      stairs connector (down from here)
  ^      stairs connector (up from here)
  [E]    elevator shaft connector
  ===    locked/heavy door
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOM_COUNTS = {
    "sewer":    (6,  10),
    "basement": (6,  12),
    "lair":     (8,  15),
    "dungeon":  (10, 20),
}

ROOM_W = 9   # character width of each room box (including borders)
ROOM_H = 5   # character height of each room box (including borders)
GAP_H  = 3   # horizontal gap between rooms (connector space)
GAP_V  = 3   # vertical gap between rooms (connector space)


# ---------------------------------------------------------------------------
# Room types per subtype
# ---------------------------------------------------------------------------

ROOM_TYPES: Dict[str, List[str]] = {
    "sewer": [
        "entry shaft", "main channel", "junction", "overflow chamber",
        "pump room", "collapsed section", "cistern", "filtration room",
        "maintenance crawl", "waste pit",
    ],
    "basement": [
        "loading bay", "boiler room", "storage vault", "maintenance corridor",
        "freezer room", "office (ruined)", "electrical room", "utility junction",
        "sub-basement stairwell", "derelict lab", "water main room", "coal chute",
    ],
    "lair": [
        "cave entrance", "feeding ground", "egg chamber", "bone pile",
        "watering hole", "narrow passage", "fungal grove", "mud pit",
        "territorial marker room", "ambush alcove", "trophy cavern",
        "primary nest", "den core", "breeding chamber", "alpha's lair",
    ],
    "dungeon": [
        "guard post", "cell block", "torture chamber", "shrine",
        "armoury", "kitchen (ruined)", "warden's office", "well room",
        "summoning circle", "hidden vault", "portcullis room", "pit trap room",
        "trophy hall", "collapsed corridor", "flooded cell", "throne room",
        "ritual chamber", "archive", "secret passage entrance", "inner sanctum",
    ],
}

CONNECTOR_TYPES: Dict[str, List[str]] = {
    "sewer":    ["door", "door", "door", "door", "locked"],
    "basement": ["door", "door", "door", "stairs", "locked"],
    "lair":     ["door", "door", "door", "door", "door"],
    "dungeon":  ["door", "door", "stairs", "stairs", "elevator", "locked"],
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class InfestationRoom:
    room_id: int
    room_type: str
    grid_x: int
    grid_y: int
    is_entry: bool = False
    is_boss: bool = False
    connections: List[Tuple[int, str]] = field(default_factory=list)  # [(room_id, connector_type)]
    monster_density: str = "normal"   # empty / light / normal / heavy / boss


@dataclass
class InfestationLayout:
    subtype: str           # sewer / basement / lair / dungeon
    rooms: List[InfestationRoom]
    grid_w: int
    grid_h: int
    ascii_map: str = ""    # rendered ASCII, filled by render_ascii()
    room_sequence: List[int] = field(default_factory=list)  # depth-first traversal order


# ---------------------------------------------------------------------------
# Layout generation
# ---------------------------------------------------------------------------

def _weighted_connector(subtype: str) -> str:
    pool = CONNECTOR_TYPES.get(subtype, ["door"])
    weights = {"door": 5, "stairs": 2, "elevator": 1, "locked": 2}
    weighted = []
    for c in pool:
        weighted.extend([c] * weights.get(c, 1))
    return random.choice(weighted)


def generate_layout(subtype: str, room_count: Optional[int] = None) -> InfestationLayout:
    """
    Generate a room graph for the given infestation subtype.
    Room positions are placed on a grid using a depth-first expansion
    so the layout looks organic rather than perfectly square.
    """
    lo, hi = ROOM_COUNTS.get(subtype, (8, 12))
    n = room_count or random.randint(lo, hi)
    type_pool = ROOM_TYPES.get(subtype, ROOM_TYPES["lair"])

    # --- Place rooms on a grid via DFS expansion ---
    occupied: Set[Tuple[int, int]] = set()
    rooms: List[InfestationRoom] = []
    room_by_pos: Dict[Tuple[int, int], InfestationRoom] = {}

    DIRECTIONS = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    def _place(gx: int, gy: int, room_id: int, parent_id: Optional[int], connector: str):
        rtype = random.choice(type_pool)
        room = InfestationRoom(
            room_id=room_id,
            room_type=rtype,
            grid_x=gx,
            grid_y=gy,
            is_entry=(room_id == 1),
            monster_density="light" if room_id == 1 else "normal",
        )
        rooms.append(room)
        occupied.add((gx, gy))
        room_by_pos[(gx, gy)] = room

        if parent_id is not None:
            parent = next(r for r in rooms if r.room_id == parent_id)
            parent.connections.append((room_id, connector))
            room.connections.append((parent_id, connector))

    _place(0, 0, 1, None, "")

    stack = [rooms[0]]
    next_id = 2

    while next_id <= n and stack:
        current = stack[-1]
        random.shuffle(DIRECTIONS)
        placed = False
        for dx, dy in DIRECTIONS:
            nx, ny = current.grid_x + dx, current.grid_y + dy
            if (nx, ny) not in occupied:
                conn = _weighted_connector(subtype)
                _place(nx, ny, next_id, current.room_id, conn)
                stack.append(rooms[next_id - 1])
                next_id += 1
                placed = True
                break
        if not placed:
            stack.pop()
            if stack:
                # Backtrack — try to branch from a random already-placed room
                stack = [random.choice(rooms[:-1])]

    # Add a few extra cross-connections to make loops (optional, chance-based)
    for room in rooms:
        for dx, dy in DIRECTIONS:
            neighbour = room_by_pos.get((room.grid_x + dx, room.grid_y + dy))
            if neighbour and neighbour.room_id != room.room_id:
                already = any(c[0] == neighbour.room_id for c in room.connections)
                if not already and random.random() < 0.15:
                    conn = _weighted_connector(subtype)
                    room.connections.append((neighbour.room_id, conn))
                    neighbour.connections.append((room.room_id, conn))

    # Designate boss room — deepest room from entry by BFS
    from collections import deque
    dist: Dict[int, int] = {1: 0}
    q = deque([rooms[0]])
    while q:
        cur = q.popleft()
        for (nid, _) in cur.connections:
            if nid not in dist:
                dist[nid] = dist[cur.room_id] + 1
                q.append(next(r for r in rooms if r.room_id == nid))

    farthest_id = max(dist, key=lambda rid: dist[rid])
    boss_room = next(r for r in rooms if r.room_id == farthest_id)
    boss_room.is_boss = True
    boss_room.monster_density = "boss"
    boss_room.room_type = {
        "sewer": "primary overflow nest",
        "basement": "sub-basement core",
        "lair": "alpha's lair",
        "dungeon": "inner sanctum",
    }.get(subtype, "boss chamber")

    # Mark a few rooms as heavy / empty
    for room in rooms:
        if room.is_boss or room.is_entry:
            continue
        r = random.random()
        if r < 0.10:
            room.monster_density = "empty"
        elif r < 0.30:
            room.monster_density = "light"
        elif r < 0.75:
            room.monster_density = "normal"
        else:
            room.monster_density = "heavy"

    # Compute BFS order for sequence
    sequence = list(dist.keys())
    sequence.sort(key=lambda rid: dist[rid])

    # Grid bounds
    min_x = min(r.grid_x for r in rooms)
    min_y = min(r.grid_y for r in rooms)
    for room in rooms:
        room.grid_x -= min_x
        room.grid_y -= min_y
    grid_w = max(r.grid_x for r in rooms) + 1
    grid_h = max(r.grid_y for r in rooms) + 1

    layout = InfestationLayout(
        subtype=subtype,
        rooms=rooms,
        grid_w=grid_w,
        grid_h=grid_h,
        room_sequence=sequence,
    )
    layout.ascii_map = render_ascii(layout)
    return layout


# ---------------------------------------------------------------------------
# ASCII renderer
# ---------------------------------------------------------------------------

CONNECTOR_CHARS = {
    "door":     ("D", "D"),   # (horizontal char, vertical char)
    "stairs":   ("S", "S"),
    "elevator": ("E", "E"),
    "locked":   ("=", "X"),
}


def render_ascii(layout: InfestationLayout) -> str:
    """
    Render the room graph as ASCII art on a character canvas.

    Canvas cell size:
      Each room occupies (ROOM_W + GAP_H) cols × (ROOM_H + GAP_V) rows on the canvas.
    """
    cw = ROOM_W + GAP_H   # canvas columns per grid cell
    ch = ROOM_H + GAP_V   # canvas rows per grid cell

    canvas_cols = layout.grid_w * cw + GAP_H
    canvas_rows = layout.grid_h * ch + GAP_V

    # Initialise blank canvas
    grid = [[" " for _ in range(canvas_cols)] for _ in range(canvas_rows)]

    def _set(row: int, col: int, ch: str):
        if 0 <= row < canvas_rows and 0 <= col < canvas_cols:
            grid[row][col] = ch

    def _room_origin(gx: int, gy: int) -> Tuple[int, int]:
        """Top-left character position of a room box."""
        return gy * ch + GAP_V, gx * cw + GAP_H

    # Draw rooms
    by_id: Dict[int, InfestationRoom] = {r.room_id: r for r in layout.rooms}

    for room in layout.rooms:
        row0, col0 = _room_origin(room.grid_x, room.grid_y)

        # Top/bottom border
        for c in range(ROOM_W):
            _set(row0, col0 + c, "+" if c in (0, ROOM_W - 1) else "-")
            _set(row0 + ROOM_H - 1, col0 + c, "+" if c in (0, ROOM_W - 1) else "-")

        # Side borders
        for r in range(1, ROOM_H - 1):
            _set(row0 + r, col0, "|")
            _set(row0 + r, col0 + ROOM_W - 1, "|")

        # Room label — centred on middle row
        label_row = row0 + ROOM_H // 2
        markers = []
        if room.is_entry:
            markers.append("IN")
        if room.is_boss:
            markers.append("BOSS")
        num_str = f"R{room.room_id:02d}"
        tag_str = f"[{','.join(markers)}]" if markers else ""
        inner_str = f"{num_str}{tag_str}"
        inner_w = ROOM_W - 2
        inner_str = inner_str[:inner_w].center(inner_w)
        for i, ch_char in enumerate(inner_str):
            _set(label_row, col0 + 1 + i, ch_char)

        # Density hint on row above/below label
        density_map = {"empty": ".", "light": "~", "normal": "*", "heavy": "**", "boss": "!!"}
        density_str = density_map.get(room.monster_density, "*")
        density_str = density_str[:inner_w].center(inner_w)
        for i, ch_char in enumerate(density_str):
            _set(label_row + 1, col0 + 1 + i, ch_char)

    # Draw connectors
    drawn_pairs: Set[Tuple[int, int]] = set()
    for room in layout.rooms:
        row0, col0 = _room_origin(room.grid_x, room.grid_y)
        for (nid, conn_type) in room.connections:
            pair = tuple(sorted((room.room_id, nid)))
            if pair in drawn_pairs:
                continue
            drawn_pairs.add(pair)

            neighbour = by_id[nid]
            nrow0, ncol0 = _room_origin(neighbour.grid_x, neighbour.grid_y)
            hchar, vchar = CONNECTOR_CHARS.get(conn_type, ("D", "D"))

            dx = neighbour.grid_x - room.grid_x
            dy = neighbour.grid_y - room.grid_y

            if dx == 1:   # neighbour is to the right
                mid_col = col0 + ROOM_W   # gap starts here
                mid_row = row0 + ROOM_H // 2
                gap_str = f"-{hchar}-"
                for i, c in enumerate(gap_str):
                    _set(mid_row, mid_col + i, c)

            elif dx == -1:  # neighbour is to the left
                mid_col = ncol0 + ROOM_W
                mid_row = row0 + ROOM_H // 2
                gap_str = f"-{hchar}-"
                for i, c in enumerate(gap_str):
                    _set(mid_row, mid_col + i, c)

            elif dy == 1:   # neighbour is below
                mid_row = row0 + ROOM_H   # gap starts here
                mid_col = col0 + ROOM_W // 2
                for i in range(GAP_V):
                    ch_char = vchar if i == GAP_V // 2 else "|"
                    _set(mid_row + i, mid_col, ch_char)

            elif dy == -1:  # neighbour is above
                mid_row = nrow0 + ROOM_H
                mid_col = col0 + ROOM_W // 2
                for i in range(GAP_V):
                    ch_char = vchar if i == GAP_V // 2 else "|"
                    _set(mid_row + i, mid_col, ch_char)

    # Assemble
    lines = ["".join(row).rstrip() for row in grid]
    # Trim leading/trailing blank lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    # Legend
    legend = [
        "",
        "LEGEND: R##=Room  [IN]=Entry  [BOSS]=Boss  D=Door  S=Stairs  E=Elevator  ==Locked",
        "DENSITY: .=Empty  ~=Light  *=Normal  **=Heavy  !!=Boss spawn",
    ]
    return "\n".join(lines + legend)


# ---------------------------------------------------------------------------
# Text summary for Ollama context
# ---------------------------------------------------------------------------

def layout_summary(layout: InfestationLayout) -> str:
    """One-line summary of each room for use in Ollama prompts."""
    lines = [f"Infestation layout — {layout.subtype.upper()} — {len(layout.rooms)} rooms"]
    by_id = {r.room_id: r for r in layout.rooms}
    for rid in layout.room_sequence:
        room = by_id[rid]
        conns = ", ".join(f"R{c[0]:02d}({c[1]})" for c in room.connections)
        flags = []
        if room.is_entry: flags.append("ENTRY")
        if room.is_boss:  flags.append("BOSS")
        tag = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"  R{rid:02d}{tag}: {room.room_type} | density={room.monster_density} | connects to: {conns or 'none'}")
    return "\n".join(lines)
