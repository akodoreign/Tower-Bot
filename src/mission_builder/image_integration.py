"""
image_integration.py — Integration layer linking mission generation with image creation.

Provides end-to-end functions for generating missions with full visual assets.

Exports:
    generate_mission_with_images()    — Generate mission JSON + battle map tiles
    generate_mission_with_images_async() — Async version
    generate_complete_mission()       — Full mission with all images saved
    update_mission_with_images()      — Add images to existing mission JSON
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.log import logger
from .schemas import MissionModule, DungeonRoom
from .json_generator import generate_module_json
from .image_generator import (
    generate_dungeon_tiles_for_rooms,
    stitch_dungeon_map,
    save_mission_images,
    get_image_asset,
)
from .api import generate_mission_async, get_mission_output_path


async def generate_mission_with_images(
    title: str,
    faction: str,
    tier: str,
    body: str,
    player_name: str = "Party",
    include_images: bool = True,
    image_style: str = "dark dungeon",
    model_name: str = "qwen3-8b-slim:latest",
) -> tuple[Optional[MissionModule], Optional[Dict[str, str]]]:
    """
    Generate a complete mission with images integrated.

    Args:
        title: Mission title
        faction: Faction issuing the mission
        tier: Mission difficulty (e.g., "low-stakes", "high-stakes")
        body: Mission briefing/description
        player_name: Name of player/party
        include_images: Whether to generate battle maps and assets
        image_style: Visual style for image generation
        model_name: LLM model to use

    Returns:
        Tuple of (mission_module, image_paths_dict) where image_paths_dict 
        contains relative paths to saved images
    """
    logger.info(f"[{title}] Generating mission with images...")

    # Step 1: Generate mission JSON
    logger.info(f"[{title}] Step 1/3: Generating mission content...")
    mission_module = await generate_mission_async(
        title=title,
        faction=faction,
        tier=tier,
        body=body,
        player_name=player_name,
        model_name=model_name,
    )

    if not mission_module:
        logger.error(f"[{title}] Mission generation failed")
        return None, None

    # Step 2: Generate images if requested
    images_dict = {}
    if include_images:
        logger.info(f"[{title}] Step 2/3: Generating images...")

        # Extract dungeon rooms from mission if available
        dungeon_rooms = extract_dungeon_rooms_from_mission(mission_module)

        if dungeon_rooms:
            logger.info(f"[{title}] Found {len(dungeon_rooms)} rooms, generating tiles...")

            # Generate tiles
            tiles = await generate_dungeon_tiles_for_rooms(dungeon_rooms, style=image_style)

            # Stitch composite map
            if tiles:
                composite = await stitch_dungeon_map(tiles)
                if composite:
                    images_dict["battle_map"] = composite

                    # Also include individual tiles for reference
                    for room_name, tile_img in tiles.items():
                        if tile_img:
                            images_dict[f"room_{room_name}"] = tile_img
        else:
            logger.warning(f"[{title}] No dungeon rooms found, skipping image generation")

    # Step 3: Save images and update mission
    logger.info(f"[{title}] Step 3/3: Saving mission with images...")
    saved_paths, updated_module = await save_mission_images(
        mission_title=title,
        images=images_dict,
        mission_module=mission_module,
    )

    logger.info(f"✓ Mission complete: {title}")
    logger.info(f"  - Content: {len(json.dumps(updated_module))} bytes")
    logger.info(f"  - Images: {len(saved_paths)} files")

    return updated_module, saved_paths


def generate_mission_with_images_sync(
    title: str,
    faction: str,
    tier: str,
    body: str,
    player_name: str = "Party",
    include_images: bool = True,
    image_style: str = "dark dungeon",
    model_name: str = "qwen3-8b-slim:latest",
) -> tuple[Optional[MissionModule], Optional[Dict[str, str]]]:
    """
    Synchronous wrapper for generate_mission_with_images().

    Runs async function in a managed event loop.
    """
    try:
        loop = asyncio.get_running_loop()
        # If we're already in an async context, return the coroutine
        return generate_mission_with_images(
            title=title,
            faction=faction,
            tier=tier,
            body=body,
            player_name=player_name,
            include_images=include_images,
            image_style=image_style,
            model_name=model_name,
        )
    except RuntimeError:
        # No event loop, create one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                generate_mission_with_images(
                    title=title,
                    faction=faction,
                    tier=tier,
                    body=body,
                    player_name=player_name,
                    include_images=include_images,
                    image_style=image_style,
                    model_name=model_name,
                )
            )
        finally:
            loop.close()


async def generate_complete_mission(
    title: str,
    faction: str,
    tier: str,
    body: str,
    player_name: str = "Party",
    output_dir: Optional[Path] = None,
    image_style: str = "dark dungeon",
) -> Optional[tuple[Path, Path]]:
    """
    Generate complete mission (JSON + images) and save to disk.

    Args:
        title: Mission title
        faction: Faction
        tier: Difficulty tier
        body: Mission description
        player_name: Player/party name
        output_dir: Optional custom output directory
        image_style: Visual style for images

    Returns:
        Tuple of (mission_json_path, mission_dir_path) or None if generation fails
    """
    # Generate mission with images
    mission_module, image_paths = await generate_mission_with_images(
        title=title,
        faction=faction,
        tier=tier,
        body=body,
        player_name=player_name,
        include_images=True,
        image_style=image_style,
    )

    if not mission_module:
        return None

    # Determine output paths
    mission_output_path = get_mission_output_path(title)

    # Create mission directory
    mission_dir = mission_output_path.parent
    mission_dir.mkdir(parents=True, exist_ok=True)

    # Save mission JSON
    with open(mission_output_path, "w", encoding="utf-8") as f:
        json.dump(mission_module, f, indent=2)

    logger.info(f"✓ Mission saved: {mission_output_path}")
    logger.info(f"✓ Images: {mission_dir / 'images'}")

    return mission_output_path, mission_dir


async def update_mission_with_images(
    mission_file: Path,
    include_dungeon_images: bool = True,
    image_style: str = "dark dungeon",
) -> Optional[MissionModule]:
    """
    Load existing mission JSON and add generated images to it.

    Args:
        mission_file: Path to mission JSON file
        include_dungeon_images: Whether to generate dungeon map images
        image_style: Visual style

    Returns:
        Updated mission module with images, or None if loading fails
    """
    try:
        # Load mission JSON
        with open(mission_file, "r", encoding="utf-8") as f:
            mission_module: MissionModule = json.load(f)

        mission_title = mission_module.get("title", "Untitled Mission")
        logger.info(f"[{mission_title}] Loading mission for image generation...")

        # Extract and generate images
        images_dict = {}

        if include_dungeon_images:
            dungeon_rooms = extract_dungeon_rooms_from_mission(mission_module)
            if dungeon_rooms:
                logger.info(f"[{mission_title}] Generating {len(dungeon_rooms)} dungeon tiles...")

                tiles = await generate_dungeon_tiles_for_rooms(
                    dungeon_rooms, style=image_style
                )

                if tiles:
                    composite = await stitch_dungeon_map(tiles)
                    if composite:
                        images_dict["battle_map"] = composite
                        images_dict.update(
                            {f"room_{name}": img for name, img in tiles.items() if img}
                        )

        # Save images and update mission
        if images_dict:
            saved_paths, updated = await save_mission_images(
                mission_title=mission_title,
                images=images_dict,
                mission_module=mission_module,
            )

            # Write updated mission JSON
            with open(mission_file, "w", encoding="utf-8") as f:
                json.dump(updated, f, indent=2)

            logger.info(f"✓ Mission updated with {len(saved_paths)} images")
            return updated

        logger.warning(f"[{mission_title}] No images generated")
        return mission_module

    except Exception as e:
        logger.error(f"❌ Failed to update mission: {e}")
        return None


def extract_dungeon_rooms_from_mission(mission_module: MissionModule) -> List[DungeonRoom]:
    """
    Extract all dungeon rooms from mission encounters.

    Args:
        mission_module: Parsed mission JSON

    Returns:
        List of DungeonRoom objects
    """
    rooms: List[DungeonRoom] = []

    try:
        acts = mission_module.get("acts", [])
        for act in acts:
            encounters = act.get("encounters", [])
            for encounter in encounters:
                dungeon = encounter.get("dungeon_delve")
                if dungeon:
                    encounter_rooms = dungeon.get("rooms", [])
                    rooms.extend(encounter_rooms)

    except Exception as e:
        logger.warning(f"Could not extract dungeon rooms: {e}")

    return rooms


# ============================================================================
# Example usage and documentation
# ============================================================================

def example_usage():
    """Example of using the image integration API."""
    mission_title = "The Silent Vault"
    faction = "Glass Sigil"

    # ASYNC VERSION (preferred):
    # mission, images = await generate_mission_with_images(
    #     title=mission_title,
    #     faction=faction,
    #     tier="high-stakes",
    #     body="Your faction needs you to recover a lost artifact...",
    #     player_name="Party of Shadows",
    #     include_images=True,
    #     image_style="gothic crypt"
    # )

    # SYNC VERSION (for synchronous code):
    # mission, images = generate_mission_with_images_sync(
    #     title=mission_title,
    #     faction=faction,
    #     tier="high-stakes",
    #     body="Your faction needs you to recover a lost artifact...",
    # )
    # if mission:
    #     print(f"Generated: {mission_title}")
    #     print(f"Images: {list(images.keys())}")

    # COMPLETE MISSION WITH IMAGES TO DISK:
    # paths = await generate_complete_mission(
    #     title=mission_title,
    #     faction=faction,
    #     tier="high-stakes",
    #     body="Your faction needs you to recover a lost artifact...",
    # )
    # if paths:
    #     json_path, mission_dir = paths
    #     print(f"Mission JSON: {json_path}")
    #     print(f"Mission directory: {mission_dir}")

    pass
