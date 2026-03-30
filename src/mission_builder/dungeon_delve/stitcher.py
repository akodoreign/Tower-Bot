"""
dungeon_delve/stitcher.py — PIL-based map stitching for dungeon tiles.

Combines individual room tiles into a composite dungeon map with:
- Room number labels
- Connection indicators between rooms
- Legend at bottom
- Dark fantasy styling

Exported:
    stitch_dungeon_map(layout, room_tiles, room_info) -> bytes
    add_room_labels(image, layout, room_info) -> Image
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .layouts import DungeonLayout, RoomPosition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Default tile size (can be overridden)
DEFAULT_TILE_SIZE = 512

# Padding around the dungeon map
DEFAULT_PADDING = 64

# Colors
COLOR_BACKGROUND = (30, 30, 35, 255)       # Dark charcoal
COLOR_LABEL_BG = (255, 255, 255, 230)      # White with slight transparency
COLOR_LABEL_TEXT = (20, 20, 20, 255)       # Near black
COLOR_CONNECTION = (180, 160, 120, 255)    # Tan/parchment
COLOR_LEGEND_TEXT = (220, 220, 210, 255)   # Off-white
COLOR_ENCOUNTER_ICON = (200, 50, 50, 255)  # Red for combat

# Font settings
LABEL_FONT_SIZE = 28
LEGEND_FONT_SIZE = 18
LABEL_CIRCLE_RADIUS = 18

# Legend area
LEGEND_HEIGHT = 120
LEGEND_COLUMNS = 2


# ---------------------------------------------------------------------------
# Font Loading
# ---------------------------------------------------------------------------

def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Load a font, falling back to default if needed."""
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    
    # Fallback to default
    try:
        return ImageFont.load_default()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Connection Drawing
# ---------------------------------------------------------------------------

def _draw_connections(
    draw: ImageDraw.Draw,
    layout: DungeonLayout,
    tile_size: int,
    padding: int,
):
    """Draw connection indicators between rooms."""
    for room in layout.rooms:
        # Calculate room center
        cx = padding + room.grid_x * tile_size + tile_size // 2
        cy = padding + room.grid_y * tile_size + tile_size // 2
        
        # Draw lines toward exits
        line_length = tile_size // 3
        line_width = 4
        
        for exit_dir in room.exits:
            if exit_dir == "north":
                end = (cx, cy - line_length)
            elif exit_dir == "south":
                end = (cx, cy + line_length)
            elif exit_dir == "east":
                end = (cx + line_length, cy)
            elif exit_dir == "west":
                end = (cx - line_length, cy)
            else:
                continue
            
            # Draw dashed connection line
            draw.line(
                [(cx, cy), end],
                fill=COLOR_CONNECTION,
                width=line_width,
            )


def _draw_room_label(
    draw: ImageDraw.Draw,
    x: int,
    y: int,
    room_num: str,
    font: ImageFont.FreeTypeFont,
    has_encounter: bool = False,
):
    """Draw a circled room number label."""
    # Draw white circle background
    draw.ellipse(
        [
            x - LABEL_CIRCLE_RADIUS,
            y - LABEL_CIRCLE_RADIUS,
            x + LABEL_CIRCLE_RADIUS,
            y + LABEL_CIRCLE_RADIUS,
        ],
        fill=COLOR_LABEL_BG,
        outline=(60, 60, 60, 255),
        width=2,
    )
    
    # Draw room number centered
    if font:
        # Get text bounding box for centering
        bbox = draw.textbbox((0, 0), room_num, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = x - text_width // 2
        text_y = y - text_height // 2 - 2  # Slight adjustment for visual centering
        draw.text((text_x, text_y), room_num, fill=COLOR_LABEL_TEXT, font=font)
    else:
        draw.text((x, y), room_num, fill=COLOR_LABEL_TEXT, anchor="mm")
    
    # Draw encounter indicator (small red dot) if combat room
    if has_encounter:
        indicator_x = x + LABEL_CIRCLE_RADIUS - 4
        indicator_y = y - LABEL_CIRCLE_RADIUS + 4
        draw.ellipse(
            [indicator_x - 5, indicator_y - 5, indicator_x + 5, indicator_y + 5],
            fill=COLOR_ENCOUNTER_ICON,
        )


def _draw_legend(
    draw: ImageDraw.Draw,
    canvas_width: int,
    legend_y: int,
    layout: DungeonLayout,
    room_info: Dict[str, dict],
    font: ImageFont.FreeTypeFont,
):
    """Draw the room legend at the bottom of the map."""
    # Title
    title_font = _get_font(LEGEND_FONT_SIZE + 4)
    if title_font:
        draw.text(
            (DEFAULT_PADDING, legend_y),
            "Room Key:",
            fill=COLOR_LEGEND_TEXT,
            font=title_font,
        )
    
    # Calculate column layout
    col_width = (canvas_width - DEFAULT_PADDING * 2) // LEGEND_COLUMNS
    start_y = legend_y + 30
    line_height = 22
    
    for i, room in enumerate(layout.rooms):
        col = i % LEGEND_COLUMNS
        row = i // LEGEND_COLUMNS
        
        x = DEFAULT_PADDING + col * col_width
        y = start_y + row * line_height
        
        # Get room info
        info = room_info.get(room.room_id, {})
        room_num = room.room_id.split("_")[-1]
        room_name = info.get("name", f"{room.room_type.title()} {room_num}")
        has_encounter = bool(info.get("encounter"))
        
        # Format: "1. Entry Chamber ⚔" or just "1. Entry Chamber"
        encounter_mark = " ⚔" if has_encounter else ""
        text = f"{room_num}. {room_name}{encounter_mark}"
        
        if font:
            draw.text((x, y), text, fill=COLOR_LEGEND_TEXT, font=font)
        else:
            draw.text((x, y), text, fill=COLOR_LEGEND_TEXT)


# ---------------------------------------------------------------------------
# Main Stitching Function
# ---------------------------------------------------------------------------

def stitch_dungeon_map(
    layout: DungeonLayout,
    room_tiles: Dict[str, bytes],
    room_info: Optional[Dict[str, dict]] = None,
    tile_size: int = DEFAULT_TILE_SIZE,
    padding: int = DEFAULT_PADDING,
) -> bytes:
    """
    Stitch individual room tiles into a composite dungeon map.
    
    Args:
        layout: DungeonLayout with room positions
        room_tiles: Dict mapping room_id → PNG bytes
        room_info: Dict mapping room_id → {name, encounter, treasure, etc.}
        tile_size: Size of each tile in pixels
        padding: Padding around the map
    
    Returns:
        PNG image bytes of the composite map
    """
    if room_info is None:
        room_info = {}
    
    # Calculate canvas size
    canvas_width = layout.grid_width * tile_size + padding * 2
    canvas_height = layout.grid_height * tile_size + padding * 2 + LEGEND_HEIGHT
    
    logger.info(f"🗺️ Stitching {len(room_tiles)} tiles into {canvas_width}x{canvas_height} map")
    
    # Create canvas with dark background
    canvas = Image.new("RGBA", (canvas_width, canvas_height), COLOR_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    
    # Load fonts
    label_font = _get_font(LABEL_FONT_SIZE)
    legend_font = _get_font(LEGEND_FONT_SIZE)
    
    # Place each room tile
    tiles_placed = 0
    for room in layout.rooms:
        if room.room_id not in room_tiles:
            logger.warning(f"🗺️ Missing tile for {room.room_id}")
            continue
        
        # Calculate position
        x = padding + room.grid_x * tile_size
        y = padding + room.grid_y * tile_size
        
        try:
            # Load tile image
            tile_bytes = room_tiles[room.room_id]
            tile_img = Image.open(io.BytesIO(tile_bytes))
            
            # Resize if needed
            if tile_img.size != (tile_size, tile_size):
                tile_img = tile_img.resize((tile_size, tile_size), Image.LANCZOS)
            
            # Convert to RGBA if needed
            if tile_img.mode != "RGBA":
                tile_img = tile_img.convert("RGBA")
            
            # Paste onto canvas
            canvas.paste(tile_img, (x, y))
            tiles_placed += 1
            
        except Exception as e:
            logger.error(f"🗺️ Failed to paste tile {room.room_id}: {e}")
            continue
    
    # Draw connection lines (before labels so labels appear on top)
    _draw_connections(draw, layout, tile_size, padding)
    
    # Draw room labels
    for room in layout.rooms:
        x = padding + room.grid_x * tile_size + 30  # Offset from corner
        y = padding + room.grid_y * tile_size + 30
        
        room_num = room.room_id.split("_")[-1]
        info = room_info.get(room.room_id, {})
        has_encounter = bool(info.get("encounter"))
        
        _draw_room_label(draw, x, y, room_num, label_font, has_encounter)
    
    # Draw legend
    legend_y = padding + layout.grid_height * tile_size + 20
    _draw_legend(draw, canvas_width, legend_y, layout, room_info, legend_font)
    
    logger.info(f"🗺️ Stitched {tiles_placed} tiles with {len(layout.rooms)} labels")
    
    # Convert to bytes
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


def create_placeholder_map(
    layout: DungeonLayout,
    room_info: Optional[Dict[str, dict]] = None,
    tile_size: int = DEFAULT_TILE_SIZE,
    padding: int = DEFAULT_PADDING,
) -> bytes:
    """
    Create a placeholder map with empty room outlines (no A1111).
    
    Useful for testing layout or when A1111 is unavailable.
    
    Args:
        layout: DungeonLayout with room positions
        room_info: Dict mapping room_id → {name, encounter, etc.}
        tile_size: Size of each room in pixels
        padding: Padding around the map
    
    Returns:
        PNG image bytes of the placeholder map
    """
    if room_info is None:
        room_info = {}
    
    # Calculate canvas size
    canvas_width = layout.grid_width * tile_size + padding * 2
    canvas_height = layout.grid_height * tile_size + padding * 2 + LEGEND_HEIGHT
    
    # Create canvas
    canvas = Image.new("RGBA", (canvas_width, canvas_height), COLOR_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    
    # Load fonts
    label_font = _get_font(LABEL_FONT_SIZE)
    type_font = _get_font(14)
    legend_font = _get_font(LEGEND_FONT_SIZE)
    
    # Draw placeholder rooms
    for room in layout.rooms:
        x = padding + room.grid_x * tile_size
        y = padding + room.grid_y * tile_size
        
        # Draw room outline
        draw.rectangle(
            [x + 5, y + 5, x + tile_size - 5, y + tile_size - 5],
            fill=(50, 50, 55, 255),
            outline=(100, 100, 100, 255),
            width=2,
        )
        
        # Draw room type label in center
        if type_font:
            type_text = room.room_type.upper()
            bbox = draw.textbbox((0, 0), type_text, font=type_font)
            text_width = bbox[2] - bbox[0]
            text_x = x + (tile_size - text_width) // 2
            text_y = y + tile_size // 2
            draw.text(
                (text_x, text_y),
                type_text,
                fill=(120, 120, 120, 255),
                font=type_font,
            )
    
    # Draw connections
    _draw_connections(draw, layout, tile_size, padding)
    
    # Draw room labels
    for room in layout.rooms:
        label_x = padding + room.grid_x * tile_size + 30
        label_y = padding + room.grid_y * tile_size + 30
        
        room_num = room.room_id.split("_")[-1]
        info = room_info.get(room.room_id, {})
        has_encounter = bool(info.get("encounter"))
        
        _draw_room_label(draw, label_x, label_y, room_num, label_font, has_encounter)
    
    # Draw legend
    legend_y = padding + layout.grid_height * tile_size + 20
    _draw_legend(draw, canvas_width, legend_y, layout, room_info, legend_font)
    
    # Convert to bytes
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "stitch_dungeon_map",
    "create_placeholder_map",
]
