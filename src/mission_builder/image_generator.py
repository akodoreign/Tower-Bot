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
import inspect
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any
from PIL import Image
import io
import httpx

from src.log import logger
from src.image_ref import get_npc_ref, save_npc_ref


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
from .schemas import ImageAsset, MissionModule, DungeonRoom

# Configuration
A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")
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
        from src.resource_cop import wait_for_a1111_turn
        decision = await wait_for_a1111_turn(
            "image_generator_tile",
            max_wait_seconds=60,
        )
        if not decision.run_now:
            logger.info(f"image_generator: A1111 deferred tile generation: {decision.reason}")
            return None

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
            await _maybe_await(response.raise_for_status())

            data = await _maybe_await(response.json())
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


# ---------------------------------------------------------------------------
# Single-cell location map — no stitching, uses DD_Table_RPG LoRA
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ASCII grid → init_image renderer
# ---------------------------------------------------------------------------

# Character → RGB color mapping for grid rendering
_GRID_COLORS: dict[str, tuple[int, int, int]] = {
    "#":  (55,  55,  65),   # stone wall
    "█":  (40,  40,  50),   # solid wall
    "|":  (55,  55,  65),   # vertical wall
    "-":  (55,  55,  65),   # horizontal wall
    "+":  (130, 120, 110),  # pillar / crossroads
    ".":  (200, 185, 158),  # floor / path
    " ":  (18,  18,  22),   # void / outside
    "~":  (75,  125, 175),  # water
    "W":  (75,  125, 175),  # water (alt)
    "T":  (38,  88,  38),   # tree
    "G":  (95,  155, 75),   # grass
    "R":  (165, 130, 90),   # road / cobblestone
    "D":  (125, 88,  55),   # door
    "S":  (155, 75,  175),  # stairs
    ">":  (155, 75,  175),  # stairs down
    "<":  (155, 75,  175),  # stairs up
    "o":  (215, 175, 55),   # light / torch
    "X":  (175, 45,  45),   # trap / hazard
    "^":  (75,  95,  75),   # high terrain / mountain
    "=":  (145, 115, 78),   # bridge
    "C":  (200, 185, 158),  # chamber (same as floor)
    "V":  (120, 90,  50),   # vent / crawlspace
    "v":  (120, 90,  50),   # vent / crawlspace (lowercase)
}
_GRID_DEFAULT = (100, 95, 88)  # fallback for unknown chars


def render_ascii_grid_to_png(ascii_grid: str, cell_size: int = 24) -> bytes:
    """
    Render an ASCII grid string to a PNG image (bytes).

    Each character becomes a cell_size × cell_size colored square.
    Rows are split on newlines; all rows padded to the same width.
    """
    lines = ascii_grid.splitlines()
    if not lines:
        lines = [" "]
    # Pad all rows to the same width
    max_w = max(len(line) for line in lines)
    rows = [line.ljust(max_w) for line in lines]

    img_w = max_w * cell_size
    img_h = len(rows) * cell_size
    img = Image.new("RGB", (img_w, img_h), color=(18, 18, 22))

    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    for row_idx, row in enumerate(rows):
        for col_idx, ch in enumerate(row):
            color = _GRID_COLORS.get(ch, _GRID_DEFAULT)
            x0 = col_idx * cell_size
            y0 = row_idx * cell_size
            draw.rectangle([x0, y0, x0 + cell_size - 1, y0 + cell_size - 1], fill=color)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def generate_location_map(
    location_name: str,
    map_prompt: str,
    map_type: str = "interior",
    size: int = 768,
    ascii_grid: Optional[str] = None,
    init_image_bytes: Optional[bytes] = None,
    update_denoising: float = 0.42,
) -> Optional[bytes]:
    """
    Generate a single top-down battle map for a mission location.

    Priority order for init image:
      1. init_image_bytes — existing map from DB (lowest denoising: adds to it)
      2. ascii_grid       — rendered schematic layout (medium denoising: styles it)
      3. txt2img          — generate from scratch

    Args:
        location_name:    Human-readable name (for logging)
        map_prompt:       A1111 prompt describing the map contents
        map_type:         "interior", "dungeon", "outdoor", "village", "cave"
        size:             Square image size (512 or 768 recommended)
        ascii_grid:       Optional ASCII layout string (# walls, . floor, ~ water, etc.)
        init_image_bytes: Optional existing map PNG bytes to paint over (very low denoising)
        update_denoising: Denoising strength for init_image_bytes mode (default 0.42)
    """
    a1111_url   = os.getenv("A1111_URL", "http://127.0.0.1:7860")
    lora_name   = os.getenv("A1111_MAP_LORA", "DD_Table_RPG")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.85"))

    _type_prefix = {
        # Original types
        "dungeon":              "top-down dungeon map, stone walls, torch-lit rooms, grid overlay,",
        "interior":             "top-down floor plan, interior room layout, furniture and cover objects visible, grid overlay,",
        "outdoor":              "top-down outdoor map, terrain features, paths, foliage, grid overlay,",
        "village":              "top-down village map, buildings, roads, wells, market stalls, grid overlay,",
        "cave":                 "top-down cave map, natural rock walls, winding passages, underground pools, grid overlay,",
        "vent_tunnels":         "top-down building cross-section, ventilation shafts and crawlspaces as narrow passages inside walls, main rooms visible, grid overlay,",
        # Mission-type-specific map environments
        "multi_level_building": (
            "top-down multi-storey building interior, floors shown as layered rooms, "
            "service ladders between levels, freight elevator shaft with open cage, "
            "ventilation crawlspace corridors, security guard post, maintenance corridors, "
            "utility conduit runs along walls, rooftop access hatch, stairwell shaft, grid overlay,"
        ),
        "city_street":          (
            "top-down city street map, wide cobblestone road centre, building facades as solid border, "
            "side alley branching off mid-block, market stalls and awnings along kerb, "
            "choke-point underpass or bridge, lantern posts at corners, sewer grate access, "
            "crates and barrels as street-level cover, grid overlay,"
        ),
        "urban_combat":         (
            "top-down urban combat zone, wide central clearing, rubble pile barricades, "
            "collapsed wall section creating breach, flanking alley on each side, "
            "elevated catwalk or balcony, blown-out doorways, scattered debris cover, grid overlay,"
        ),
        "fortified_interior":   (
            "top-down fortified holdout, barricade line with sandbag firing positions, "
            "choke-point corridor leading to killzone, fallback chamber at the rear, "
            "breach hole in exterior wall showing outside ground, overlook balcony, "
            "supply cache alcove, collapsed ceiling rubble, grid overlay,"
        ),
        "vault_interior":       (
            "top-down secure facility interior, heavy vault door at the far end, "
            "guard station with desk and sight-line corridor, laser-grid floor section, "
            "air-duct entry point in ceiling shown as ceiling hatch, "
            "server or display room, service corridor bypass route, "
            "lobby with reception desk, grid overlay,"
        ),
        "rooftop":              (
            "top-down rooftop chase map, flat tar or stone roof surface, "
            "chimney stacks as cover obstacles, skybridge to adjacent building, "
            "rooftop garden or antenna cluster, fire-escape ladder head, "
            "water tower, maintenance shack, low parapet walls at edges, "
            "drop-off point with short ledge, grid overlay,"
        ),
        "private_interior":     (
            "top-down private room interior, meeting or dining table as centrepiece obstacle, "
            "hidden alcove behind tapestry or panel, servant entrance at the back wall, "
            "window with external ledge, bodyguard standing positions, "
            "locked secondary exit, decorative columns as cover, grid overlay,"
        ),
        "alley":                (
            "top-down narrow alley ambush map, constricted passage with blind corner, "
            "doorway alcoves as hiding spots, overhead catwalk position, "
            "barrel and crate barricade mid-alley, dumpster cover, "
            "multiple exit routes at both ends, grid overlay,"
        ),
        "sewer":                (
            "top-down sewer tunnel map, brick tunnel walls with arched ceiling implied, "
            "central water channel running through, iron grate covers, "
            "maintenance walkway along one side, ladder access points, junction room, "
            "pipe clusters as cover, grid overlay,"
        ),
        "arcane_chamber":       (
            "top-down arcane ritual chamber, glowing rift fissure crack across floor centre, "
            "warped stone tiles around rift, containment rune circles, "
            "collapsed pillar cover, floating debris fragments as obstacles, "
            "unstable floor sections near rift edges, altar or containment device, grid overlay,"
        ),
    }.get(map_type, "top-down battle map, grid overlay,")

    full_prompt = (
        f"{_type_prefix} {map_prompt}, "
        f"tabletop RPG battle map, D&D VTT style, top-down view, "
        f"high fantasy cyberpunk fusion, wealth-stratified technology, "
        f"ancient stone beside neon and circuit panels, arcane runes on machine surfaces, "
        f"poor districts show wagons and cobblestone, rich districts show hovercars and glass towers, "
        f"magic and machine coexist, detailed, clean lines, <lora:{lora_name}:{lora_weight}>"
    )
    negative = (
        "isometric, perspective, 3D, portrait, characters, people, text, "
        "watermark, blurry, low quality, photorealistic faces"
    )

    def _to_b64(png_bytes: bytes) -> str:
        img = Image.open(io.BytesIO(png_bytes)).resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    try:
        from src.resource_cop import wait_for_a1111_turn
        decision = await wait_for_a1111_turn(
            "location_map_generator",
            max_wait_seconds=60,
        )
        if not decision.run_now:
            logger.info(f"🗺️ A1111 deferred map generation for {location_name}: {decision.reason}")
            return None

        timeout = float(os.getenv("A1111_MAP_TIMEOUT", "900"))
        async with httpx.AsyncClient(timeout=timeout) as http:
            if init_image_bytes:
                # Existing map from DB — paint new story details on top with low denoising
                payload = {
                    "prompt":             full_prompt,
                    "negative_prompt":    negative,
                    "init_images":        [_to_b64(init_image_bytes)],
                    "denoising_strength": update_denoising,
                    "steps":              28,
                    "cfg_scale":          7.5,
                    "width":              size,
                    "height":             size,
                    "sampler_name":       "DPM++ 2M SDE Karras",
                    "seed":               -1,
                    "batch_size":         1,
                    "n_iter":             1,
                }
                endpoint = f"{a1111_url}/sdapi/v1/img2img"
                logger.info(f"🗺️ Updating existing map: {location_name} (denoising={update_denoising})")

            elif ascii_grid and ascii_grid.strip():
                # ASCII schematic — render to pixel grid and style with LoRA
                grid_png = render_ascii_grid_to_png(ascii_grid.strip())
                payload = {
                    "prompt":             full_prompt,
                    "negative_prompt":    negative,
                    "init_images":        [_to_b64(grid_png)],
                    "denoising_strength": 0.65,
                    "steps":              30,
                    "cfg_scale":          7.5,
                    "width":              size,
                    "height":             size,
                    "sampler_name":       "DPM++ 2M SDE Karras",
                    "seed":               -1,
                    "batch_size":         1,
                    "n_iter":             1,
                }
                endpoint = f"{a1111_url}/sdapi/v1/img2img"
                logger.info(f"🗺️ Grid-guided map: {location_name}")

            else:
                # No reference — pure txt2img
                payload = {
                    "prompt":          full_prompt,
                    "negative_prompt": negative,
                    "steps":           28,
                    "cfg_scale":       7.0,
                    "width":           size,
                    "height":          size,
                    "sampler_name":    "DPM++ 2M SDE Karras",
                    "seed":            -1,
                    "batch_size":      1,
                    "n_iter":          1,
                }
                endpoint = f"{a1111_url}/sdapi/v1/txt2img"

            resp = await http.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("images"):
                img_bytes = base64.b64decode(data["images"][0])
                logger.info(f"🗺️ Map generated: {location_name} ({len(img_bytes)//1024}KB)")
                return img_bytes
    except Exception as e:
        logger.warning(f"🗺️ Map generation failed for {location_name}: {e}")
    return None
