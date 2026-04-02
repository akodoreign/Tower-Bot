"""
image_generator.py — Battle map and encounter image generation for missions.

Handles:
  1. Individual tile generation via A1111 Stable Diffusion
  2. Dungeon map stitching (combining tiles into composite maps)
  3. Image asset metadata for mission JSON
  4. Integration with image_ref.py for iterative refinement

Architecture:
  - generate_battle_map_tiles(): Generate isometric/top-down tiles for rooms
  - stitch_dungeon_map(): Combine tiles into composite 2D dungeon map
  - generate_encounter_images(): Full image pipeline for encounters
  - save_mission_images(): Store all images and update mission module metadata

Supports both text2img (new) and img2img (referencing previous generations).

Exports:
    generate_battle_map_tiles()           — Generate individual room tiles
    stitch_dungeon_map()                  — Stitch tiles into composite map
    generate_encounter_images()           — Generate all images for encounters
    get_image_asset()                     — Create ImageAsset metadata dict
    save_mission_images()                 — Store images and update mission JSON
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any
from PIL import Image
import io
import httpx

from src.log import logger
from src.image_ref import get_npc_ref, save_npc_ref
from .schemas import ImageAsset, MissionModule, DungeonRoom

# Configuration
A1111_URL = "http://127.0.0.1:7860"
MISSION_IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "generated_modules" / "images"
MISSION_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Tile generation defaults
DEFAULT_TILE_WIDTH = 256
DEFAULT_TILE_HEIGHT = 256
DEFAULT_SAMPLER = "Euler"
DEFAULT_STEPS = 20
DEFAULT_CFG = 7.0
DEFAULT_SEED = -1

# Dungeon map stitching defaults
TILES_PER_ROW = 4
GAP_BETWEEN_TILES = 2


@dataclass
class TileGenerationParams:
    """Parameters for a single tile generation request."""
    prompt: str
    negative_prompt: str = "blurry, distorted, low quality"
    seed: int = DEFAULT_SEED
    width: int = DEFAULT_TILE_WIDTH
    height: int = DEFAULT_TILE_HEIGHT
    sampler: str = DEFAULT_SAMPLER
    cfg_scale: float = DEFAULT_CFG
    steps: int = DEFAULT_STEPS
    use_reference: bool = False
    reference_base64: Optional[str] = None
    denoise_strength: float = 0.75


@dataclass
class ImageAssetMetadata:
    """Metadata for tracking generated images."""
    filename: str
    type: str  # "battle_map", "location", "creature", "item", "npc_portrait"
    size: tuple[int, int]  # (width, height)
    seed: int
    prompt: str
    model: str = "Stable Diffusion"


async def generate_single_tile(params: TileGenerationParams) -> Optional[Image.Image]:
    """
    Generate a single battle map tile using A1111 API.

    Args:
        params: TileGenerationParams with prompt and settings

    Returns:
        PIL Image object, or None if generation fails
    """
    try:
        if params.use_reference and params.reference_base64:
            # Use img2img for consistency with reference
            payload = {
                "init_images": [params.reference_base64],
                "prompt": params.prompt,
                "negative_prompt": params.negative_prompt,
                "denoising_strength": params.denoise_strength,
                "steps": params.steps,
                "cfg_scale": params.cfg_scale,
                "sampler_name": params.sampler,
                "seed": params.seed,
                "width": params.width,
                "height": params.height,
                "batch_size": 1,
            }
            endpoint = f"{A1111_URL}/sdapi/v1/img2img"
        else:
            # Use txt2img for new generation
            payload = {
                "prompt": params.prompt,
                "negative_prompt": params.negative_prompt,
                "steps": params.steps,
                "cfg_scale": params.cfg_scale,
                "sampler_name": params.sampler,
                "seed": params.seed,
                "width": params.width,
                "height": params.height,
                "batch_size": 1,
            }
            endpoint = f"{A1111_URL}/sdapi/v1/txt2img"

        async with httpx.AsyncClient(timeout=60.0) as client:
            logger.debug(f"Generating tile via A1111: {params.prompt[:50]}...")
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()

            data = await response.json()
            if "images" not in data or not data["images"]:
                logger.error(f"A1111 returned no images")
                return None

            # Decode first image
            img_base64 = data["images"][0]
            img_bytes = base64.b64decode(img_base64)
            img = Image.open(io.BytesIO(img_bytes))

            logger.info(f"✓ Generated tile: {img.size}")
            return img

    except httpx.ConnectError:
        logger.error(f"❌ Could not connect to A1111 at {A1111_URL}")
        logger.error("   Make sure A1111 is running with --api flag")
        return None
    except Exception as e:
        logger.error(f"❌ Tile generation failed: {e}")
        return None


async def generate_dungeon_tiles_for_rooms(
    rooms: List[DungeonRoom],
    style: str = "dark dungeon"
) -> Dict[str, Optional[Image.Image]]:
    """
    Generate tiles for all dungeon rooms in parallel.

    Args:
        rooms: List of DungeonRoom objects
        style: Visual style descriptor ("dark dungeon", "cave", "crypt", etc.)

    Returns:
        Dict mapping room names to generated PIL Images
    """
    tiles = {}

    # Create tile generation tasks
    tasks = []
    room_map = {}

    for room in rooms:
        room_name = room.get("name", "Unknown Room")
        room_description = room.get("description", "a dungeon room")

        # Craft tile prompt emphasizing battle map aesthetic
        prompt = (
            f"Isometric top-down D&D battle grid, {style}, "
            f"{room_name}: {room_description}, "
            f"256x256, grid lines, detailed terrain, tabletop RPG style, "
            f"high quality, clear lighting, minimal text"
        )

        params = TileGenerationParams(
            prompt=prompt,
            negative_prompt="blurry, realistic, 3D cartoon, side view, portrait",
        )

        task = generate_single_tile(params)
        tasks.append(task)
        room_map[len(tasks) - 1] = room_name

    # Execute all tile generations in parallel
    logger.info(f"Generating {len(rooms)} dungeon room tiles...")
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Map results back to room names
    for idx, result in enumerate(results):
        room_name = room_map[idx]
        if isinstance(result, Exception):
            logger.warning(f"Failed to generate tile for {room_name}: {result}")
            tiles[room_name] = None
        else:
            tiles[room_name] = result

    return tiles


async def stitch_dungeon_map(
    tiles: Dict[str, Image.Image],
    layout: Optional[List[List[str]]] = None
) -> Optional[Image.Image]:
    """
    Stitch individual room tiles into a composite dungeon map.

    Args:
        tiles: Dict mapping room names to PIL Images
        layout: 2D list specifying tile arrangement (default: auto-arrange)
                E.g., [["entrance", "hallway"], ["boss_room", "treasure"]]

    Returns:
        Composite PIL Image or None if stitching fails
    """
    if not tiles:
        logger.warning("No tiles to stitch")
        return None

    # Auto-layout if not provided
    if layout is None:
        room_names = list(tiles.keys())
        layout = []
        for i in range(0, len(room_names), TILES_PER_ROW):
            layout.append(room_names[i : i + TILES_PER_ROW])

    try:
        # Calculate composite map dimensions
        tile_w, tile_h = DEFAULT_TILE_WIDTH, DEFAULT_TILE_HEIGHT
        cols = len(layout[0]) if layout else 1
        rows = len(layout)

        composite_w = cols * tile_w + (cols - 1) * GAP_BETWEEN_TILES
        composite_h = rows * tile_h + (rows - 1) * GAP_BETWEEN_TILES

        # Create composite image (white background)
        composite = Image.new("RGB", (composite_w, composite_h), color=(255, 255, 255))

        # Paste tiles
        for row_idx, row in enumerate(layout):
            for col_idx, room_name in enumerate(row):
                if room_name not in tiles or tiles[room_name] is None:
                    logger.warning(f"Tile for {room_name} not found, skipping")
                    continue

                x = col_idx * (tile_w + GAP_BETWEEN_TILES)
                y = row_idx * (tile_h + GAP_BETWEEN_TILES)

                tile_img = tiles[room_name]
                composite.paste(tile_img, (x, y))

        logger.info(f"✓ Stitched composite dungeon map: {composite.size}")
        return composite

    except Exception as e:
        logger.error(f"❌ Stitching failed: {e}")
        return None


def get_image_asset(
    filename: str,
    type: str,
    size: Optional[tuple[int, int]] = None,
    seed: int = DEFAULT_SEED,
    prompt: str = ""
) -> ImageAsset:
    """
    Create an ImageAsset metadata dict for mission JSON.

    Args:
        filename: Relative path to image file (e.g., "missions/battle_map_001.png")
        type: "battle_map", "location", "creature", "item", or "npc_portrait"
        size: (width, height) tuple
        seed: Generation seed (for reproducibility)
        prompt: Generation prompt (for reference)

    Returns:
        ImageAsset typed dict
    """
    return ImageAsset(
        filename=filename,
        type=type,
        size=size or (DEFAULT_TILE_WIDTH, DEFAULT_TILE_HEIGHT),
        seed=seed,
        prompt=prompt[:100] if prompt else "",
    )


async def generate_encounter_images(
    encounter_id: str,
    encounter_data: Dict[str, Any],
    dungeon_rooms: Optional[List[DungeonRoom]] = None,
    style: str = "dark dungeon"
) -> Dict[str, Any]:
    """
    Generate all images for an encounter (battle maps, creature art, etc.).

    Args:
        encounter_id: Unique encounter identifier
        encounter_data: Encounter dict from mission JSON
        dungeon_rooms: Optional list of DungeonRoom objects
        style: Visual style for generation

    Returns:
        Dict with generated images and metadata updates for encounter_data
    """
    images_to_save = {}
    encounter_update = {}

    # Generate battle map tiles if dungeon rooms provided
    if dungeon_rooms:
        logger.info(f"[{encounter_id}] Generating dungeon tiles...")
        tiles = await generate_dungeon_tiles_for_rooms(dungeon_rooms, style)

        # Stitch composite map
        if tiles:
            logger.info(f"[{encounter_id}] Stitching composite map...")
            composite = await stitch_dungeon_map(tiles)

            if composite:
                # Save composite map
                map_filename = f"encounter_{encounter_id}_composite_map.png"
                images_to_save[map_filename] = composite
                encounter_update["composite_map"] = get_image_asset(
                    filename=f"missions/{map_filename}",
                    type="battle_map",
                    size=composite.size,
                )

            # Save individual tiles
            for room_name, tile_img in tiles.items():
                if tile_img:
                    tile_filename = f"encounter_{encounter_id}_room_{room_name}.png"
                    images_to_save[tile_filename] = tile_img
                    # Could store individual tile references if needed

    return {
        "images_to_save": images_to_save,
        "encounter_update": encounter_update,
    }


async def save_mission_images(
    mission_title: str,
    images: Dict[str, Image.Image],
    mission_module: Optional[MissionModule] = None
) -> tuple[Dict[str, str], Optional[MissionModule]]:
    """
    Save generated images to disk and update mission JSON.

    Args:
        mission_title: Mission title for directory naming
        images: Dict mapping filenames to PIL Images
        mission_module: Optional mission module to update with image references

    Returns:
        Tuple of (saved_paths_dict, updated_mission_module)
    """
    saved_paths = {}

    # Create mission-specific image directory
    mission_slug = mission_title.lower().replace(" ", "_")[:30]
    mission_image_dir = MISSION_IMAGES_DIR / mission_slug
    mission_image_dir.mkdir(parents=True, exist_ok=True)

    # Save each image
    for filename, img in images.items():
        try:
            filepath = mission_image_dir / filename
            img.save(filepath, "PNG", quality=95)
            
            # Store relative path for JSON
            rel_path = filepath.relative_to(MISSION_IMAGES_DIR)
            saved_paths[filename] = str(rel_path)
            logger.info(f"✓ Saved: {rel_path}")

        except Exception as e:
            logger.error(f"❌ Failed to save {filename}: {e}")

    # Update mission module with image references (if provided)
    if mission_module:
        try:
            # Add images list if not present
            if "images" not in mission_module:
                mission_module["images"] = []

            # Add new image assets
            for filename, rel_path in saved_paths.items():
                image_asset = get_image_asset(
                    filename=rel_path,
                    type="battle_map" if "composite" in filename else "encounter_tile"
                )
                mission_module["images"].append(image_asset)

            logger.info(f"✓ Updated mission module with {len(saved_paths)} images")

        except Exception as e:
            logger.error(f"❌ Failed to update mission module: {e}")

    return saved_paths, mission_module


# ============================================================================
# Helper: Prompt engineering for different image types
# ============================================================================

def craft_battle_map_prompt(room: DungeonRoom, style: str = "dark dungeon") -> str:
    """Craft an optimized prompt for battle map tile generation."""
    name = room.get("name", "Room")
    desc = room.get("description", "")
    hazards = room.get("hazards", [])
    terrain = " ".join(hazards[:2]) if hazards else "default"

    return (
        f"D&D battle map tile, top-down isometric view, {style}, "
        f"{name}: {desc}, terrain {terrain}, "
        f"256x256, grid lines visible, tabletop game aesthetic, high quality, "
        f"clear lighting, minimal text, no speech bubbles"
    )


def craft_creature_prompt(creature_name: str, creature_type: str) -> str:
    """Craft an optimized prompt for creature/monster art."""
    return (
        f"D&D fantasy art, {creature_type} creature '{creature_name}', "
        f"portrait style, mid-shot, D&D 5e style, high quality, "
        f"intricate details, professional fantasy illustration"
    )


def craft_location_prompt(location_name: str, location_desc: str) -> str:
    """Craft an optimized prompt for location/scene art."""
    return (
        f"Fantasy isometric scene, location '{location_name}': {location_desc}, "
        f"tabletop RPG style, detailed environment, tavern interior, "
        f"high quality, clear lighting, strategic positioning visible"
    )
