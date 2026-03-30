"""
dungeon_delve/tile_generator.py — A1111 tile generation for dungeon rooms.

Generates consistent-style 512x512 top-down room tiles for stitching
into a composite dungeon map.

Exported:
    generate_room_tile(room, aesthetic, seed) -> bytes
    generate_all_tiles(layout, aesthetic) -> Dict[str, bytes]
"""

from __future__ import annotations

import os
import base64
import asyncio
import logging
from typing import Dict, List, Optional

import httpx

from .layouts import RoomPosition, DungeonLayout

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")
A1111_TIMEOUT = 300.0  # 5 minutes per tile

# Tile dimensions — 512x512 for faster generation, will be stitched
TILE_WIDTH = 512
TILE_HEIGHT = 512

# Generation settings
TILE_STEPS = 25
TILE_CFG = 7.0
TILE_SAMPLER = "DPM++ 2M Karras"

# Checkpoint — use photorealistic for battlemaps
TILE_MODEL = os.getenv("A1111_MODEL", "juggernautXL_version6Rundiffusion.safetensors")

# ---------------------------------------------------------------------------
# Prompt Components
# ---------------------------------------------------------------------------

_BASE_STYLE = """top-down tactical dungeon room, D&D battlemap tile, dark fantasy,
orthographic view, grid-ready, clear floor texture, defined walls,
single room interior, torch lighting, high contrast edges,
fantasy RPG style, detailed ground texture"""

_NEGATIVE = """3d render, perspective, isometric, character, people, monsters,
miniatures, tokens, grid lines, numbers, text, watermark, signature,
multiple rooms, outdoor, sky, sun, bright daylight, blurry, low quality,
photo, realistic photograph, UI elements, borders, frames, white background"""

# Room type specific prompts
ROOM_PROMPTS: Dict[str, str] = {
    "entry": "stone archway entrance, heavy iron door, guard alcoves, flickering wall torches, welcome mat area",
    "corridor": "narrow stone passage, wall sconces, checkered floor tiles, connecting hallway, long room",
    "chamber": "large open room, support pillars, scattered debris, stone floor, crates and barrels",
    "lair": "creature nest, bones and refuse, organic matter, territorial marks, sleeping area",
    "vault": "treasure room, locked chests, pedestals, reinforced door, valuable items visible",
    "shrine": "altar centerpiece, religious symbols, candles, offering bowls, prayer mats",
    "workshop": "workbenches, tools on walls, arcane circles, unfinished projects, forge",
    "prison": "iron bar cells, chains on walls, straw beds, suffering marks, jailer station",
    "flooded": "water covering floor, partially submerged, wet stone, algae patches, dripping ceiling",
    "boss": "large dramatic chamber, raised platform, impressive throne or altar, arena-like, dramatic",
}

# Aesthetic overlays based on dungeon location
AESTHETIC_PROMPTS: Dict[str, str] = {
    "prison": "iron bars, stone blocks, rusted metal, cold damp atmosphere, oppressive",
    "temple": "religious architecture, divine symbols, cracked mosaics, sacred geometry",
    "arcane": "magical residue, glowing runes, strange apparatus, crystalline formations, ley lines",
    "sewer": "brick tunnels, water channels, grates and pipes, industrial decay, slime",
    "natural": "cave walls, stalactites and stalagmites, uneven floor, natural stone, moss",
    "ruined": "collapsed sections, debris piles, overgrown vines, ancient decay, crumbling",
    "volcanic": "obsidian floor, lava glow at edges, heat shimmer, sulfur deposits, red lighting",
    "flooded": "standing water, submerged objects, wet reflections, aquatic plants",
}

# Exit direction hints
EXIT_HINTS: Dict[str, str] = {
    "north": "open passage at top edge",
    "south": "open passage at bottom edge",
    "east": "open passage at right edge",
    "west": "open passage at left edge",
}


# ---------------------------------------------------------------------------
# Prompt Building
# ---------------------------------------------------------------------------

def build_tile_prompt(room: RoomPosition, aesthetic: str = "ruined") -> tuple[str, str]:
    """
    Build the SD prompt for a room tile.
    
    Args:
        room: Room position with type and exits
        aesthetic: Visual style from dungeon location
    
    Returns:
        (positive_prompt, negative_prompt)
    """
    # Get room-specific and aesthetic prompts
    room_prompt = ROOM_PROMPTS.get(room.room_type, ROOM_PROMPTS["chamber"])
    aesthetic_prompt = AESTHETIC_PROMPTS.get(aesthetic, AESTHETIC_PROMPTS["ruined"])
    
    # Build exit hints
    exit_hints = [EXIT_HINTS[d] for d in room.exits if d in EXIT_HINTS]
    exit_str = ", ".join(exit_hints) if exit_hints else "enclosed room"
    
    # Combine
    positive = f"{_BASE_STYLE}, {room_prompt}, {aesthetic_prompt}, {exit_str}"
    
    return positive, _NEGATIVE


# ---------------------------------------------------------------------------
# A1111 Generation
# ---------------------------------------------------------------------------

async def _check_a1111_available() -> bool:
    """Check if A1111 is running and responsive."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{A1111_URL}/sdapi/v1/sd-models")
            return resp.status_code == 200
    except Exception:
        return False


async def generate_room_tile(
    room: RoomPosition,
    aesthetic: str = "ruined",
    seed: int = -1,
) -> Optional[bytes]:
    """
    Generate a single room tile using A1111.
    
    Args:
        room: Room position with type and exits
        aesthetic: Visual style from dungeon location
        seed: Random seed (-1 for random, or fixed for consistency)
    
    Returns:
        PNG image bytes, or None on failure
    """
    if not await _check_a1111_available():
        logger.warning("🗺️ A1111 not available for tile generation")
        return None
    
    positive, negative = build_tile_prompt(room, aesthetic)
    
    logger.info(f"🗺️ Generating tile for {room.room_id} ({room.room_type})")
    logger.debug(f"🗺️ Prompt: {positive[:150]}...")
    
    payload = {
        "prompt": positive,
        "negative_prompt": negative,
        "width": TILE_WIDTH,
        "height": TILE_HEIGHT,
        "steps": TILE_STEPS,
        "cfg_scale": TILE_CFG,
        "sampler_name": TILE_SAMPLER,
        "seed": seed,
    }
    
    try:
        # Import the A1111 lock from news_feed to respect queue
        from src.news_feed import a1111_lock, _a1111_lock
        
        if _a1111_lock.locked():
            logger.info(f"🗺️ A1111 busy, waiting for lock...")
        
        async with a1111_lock:
            async with httpx.AsyncClient(timeout=A1111_TIMEOUT) as client:
                resp = await client.post(
                    f"{A1111_URL}/sdapi/v1/txt2img",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        
        images = data.get("images", [])
        if not images:
            logger.error(f"🗺️ A1111 returned no images for {room.room_id}")
            return None
        
        # Decode first image
        img_b64 = images[0]
        img_bytes = base64.b64decode(img_b64)
        
        # Get the seed that was used (for reproducibility)
        info = data.get("info", "")
        if "Seed:" in str(info):
            try:
                import json
                info_dict = json.loads(info) if isinstance(info, str) else info
                used_seed = info_dict.get("seed", seed)
                logger.debug(f"🗺️ Tile {room.room_id} generated with seed {used_seed}")
            except Exception:
                pass
        
        logger.info(f"🗺️ Tile generated for {room.room_id}: {len(img_bytes):,} bytes")
        return img_bytes
        
    except httpx.TimeoutException:
        logger.error(f"🗺️ Tile generation timed out for {room.room_id}")
        return None
    except Exception as e:
        logger.error(f"🗺️ Tile generation failed for {room.room_id}: {e}")
        return None


async def generate_all_tiles(
    layout: DungeonLayout,
    aesthetic: str = "ruined",
    base_seed: int = -1,
    delay_between: float = 2.0,
) -> Dict[str, bytes]:
    """
    Generate tiles for all rooms in a dungeon layout.
    
    Args:
        layout: The dungeon layout with all room positions
        aesthetic: Visual style for the dungeon
        base_seed: Base seed for consistency (-1 for random per tile)
        delay_between: Seconds to wait between generations
    
    Returns:
        Dict mapping room_id → PNG bytes
    """
    tiles: Dict[str, bytes] = {}
    
    logger.info(f"🗺️ Generating {len(layout.rooms)} tiles for dungeon ({layout.name})")
    
    for i, room in enumerate(layout.rooms):
        # Calculate seed for this room (for consistency if base_seed provided)
        if base_seed >= 0:
            room_seed = base_seed + i
        else:
            room_seed = -1
        
        tile_bytes = await generate_room_tile(room, aesthetic, room_seed)
        
        if tile_bytes:
            tiles[room.room_id] = tile_bytes
        else:
            logger.warning(f"🗺️ Failed to generate tile for {room.room_id}")
        
        # Delay between generations (except after last)
        if i < len(layout.rooms) - 1:
            await asyncio.sleep(delay_between)
    
    logger.info(f"🗺️ Generated {len(tiles)}/{len(layout.rooms)} tiles")
    return tiles


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "generate_room_tile",
    "generate_all_tiles",
    "build_tile_prompt",
    "ROOM_PROMPTS",
    "AESTHETIC_PROMPTS",
]
