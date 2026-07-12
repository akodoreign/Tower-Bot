"""
maps.py - battle map selection for mission modules.

Mission maps now come from battle_maps_library and battle_map_area_memory.
This module keeps the old public API shape, but it no longer calls A1111 or
attempts on-the-spot image generation.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.image_ref import LOCATION_DENOISE
from src.log import logger
from src.mission_builder.vtt_renderer import write_grid_sidecar

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "generated_modules"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower().strip()).strip("_")[:50]


def _detect_district(text: str) -> str:
    text_lower = str(text or "").lower()
    district_keywords = {
        "markets_infinite": ["market", "bazaar", "vendor", "stall", "cobbleway", "neon row"],
        "shantytown_heights": ["shanty", "slum", "warren"],
        "collapsed_plaza": ["collapsed", "ruin", "debris"],
        "guild_spires": ["guild", "spire", "tower", "academy", "headquarters"],
        "sanctum_quarter": ["temple", "shrine", "sanctum", "church", "holy", "divine"],
        "grand_forum": ["forum", "plaza", "fountain", "civic", "library"],
        "outer_wall": ["wall", "gate", "fortification", "guard", "watchtower"],
        "the_fringe": ["cave", "cavern", "underground", "tunnel", "subterranean"],
        "archive_row": ["archive", "library", "records", "study"],
        "scrapworks": ["scrap", "factory", "machine", "industrial"],
        "ironworks": ["ironworks", "forge", "foundry"],
        "night_pits": ["arena", "pit", "gladiator", "combat ring"],
    }
    for district, keywords in district_keywords.items():
        if any(kw in text_lower for kw in keywords):
            return district
    return ""


def _detect_scene_type(text: str) -> str:
    text_lower = str(text or "").lower()
    if any(w in text_lower for w in ("boss", "leader", "final", "climax", "lair")):
        return "boss"
    if any(w in text_lower for w in ("ambush", "trap", "surprise", "hidden")):
        return "ambush"
    if any(w in text_lower for w in ("chase", "pursuit", "flee", "escape")):
        return "chase"
    if any(w in text_lower for w in ("investigate", "search", "clue", "evidence")):
        return "investigation"
    if any(w in text_lower for w in ("talk", "negotiate", "meet", "social", "conversation")):
        return "social"
    return "combat"


def extract_map_scenes(module_data: dict, mission_type: str = "") -> List[Dict]:
    """Extract likely map-worthy scenes from module data."""
    mission_type = mission_type or module_data.get("metadata", {}).get("mission_type", "")
    raw_content = module_data.get("raw_content", "")
    sections = module_data.get("sections", {}) or {}
    content = "\n\n".join(str(v or "") for v in sections.values()) or raw_content
    if not content:
        return []

    pattern = re.compile(
        r"(?:#{1,4}\s+|\*{1,2}\s*)(?:Scene|Investigation\s+Lead|Lead)\s*\d+\s*[:\-]\s*([^\n\*]{2,80})\*{0,2}\s*\n(.*?)(?=(?:#{1,4}\s+|\*{1,2}\s*(?:Scene|Lead|Investigation|Act|Chapter|Battlefield|Location|Enemy|Reward|Resolution))|\Z)",
        re.DOTALL | re.IGNORECASE,
    )

    scenes: List[Dict] = []
    for idx, match in enumerate(pattern.finditer(content), start=1):
        location = match.group(1).strip().rstrip("*").strip()
        description = match.group(2).strip()[:900]
        combined = f"{location} {description}"
        scenes.append(
            {
                "scene_id": f"scene_{idx}_{_slugify(location) or 'map'}",
                "scene_name": location,
                "location": location,
                "description": description,
                "district": _detect_district(combined),
                "scene_type": _detect_scene_type(combined),
                "mission_type": mission_type,
                "act": 4 if any(w in combined.lower() for w in ("final", "boss", "climax")) else 2,
            }
        )
    if not scenes:
        excerpt = content[:120].replace("\n", " ")
        logger.info(
            f"extract_map_scenes: no scenes matched (content {len(content)} chars, "
            f"mission_type={mission_type!r}, excerpt={excerpt!r})"
        )
    return scenes[:8]


def build_map_prompt(scene: Dict, strategy: str = "legacy") -> Tuple[str, str]:
    """Deprecated compatibility hook. Map prompts are no longer generated."""
    return "", ""


async def generate_vtt_map(
    scene: Dict,
    ref_bytes: Optional[bytes] = None,
    denoise: float = LOCATION_DENOISE,
) -> Optional[bytes]:
    """Deprecated: mission maps now come from battle_maps_library, not A1111."""
    logger.info("Mission map generation is disabled; use battle_maps_library selection instead.")
    return None


async def generate_module_maps(
    module_data: dict,
    output_subdir: Optional[str] = None,
    max_maps: int = 5,
) -> List[Path]:
    """Copy matching library maps for extracted module scenes."""
    scenes = extract_map_scenes(module_data)
    if not scenes:
        logger.info("No map scenes found in module")
        return []
    scenes = scenes[:max_maps]

    if output_subdir:
        maps_dir = OUTPUT_DIR / output_subdir / "maps"
    else:
        maps_dir = OUTPUT_DIR / _slugify(module_data.get("title", "unknown")) / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)

    generated_paths: List[Path] = []
    for scene in scenes:
        location = scene.get("location", "unknown")
        map_path = maps_dir / f"{scene.get('scene_id', 'map')}.png"
        try:
            from src.battle_map_library import copy_library_map_for_mission

            picked = copy_library_map_for_mission(
                {
                    "title": module_data.get("title", ""),
                    "faction": module_data.get("metadata", {}).get("faction", ""),
                },
                map_path,
                mission_type=scene.get("mission_type", ""),
                location_name=location,
                district=scene.get("district", ""),
                description=scene.get("description", ""),
            )
            if picked:
                write_grid_sidecar(picked, scene)
                generated_paths.append(picked)
                logger.info(f"Reused library map: {picked}")
            else:
                logger.info(f"No library map found for {location}; skipping")
        except Exception as e:
            logger.warning(f"Library map lookup failed for {location}: {e}")
        await asyncio.sleep(1)
    return generated_paths


async def post_maps_to_channel(
    client,
    map_paths: List[Path],
    module_data: dict,
    retry_count: int = 2,
    channel=None,
) -> bool:
    """Post selected map files to the configured Discord channel."""
    import os
    import discord

    if not map_paths:
        logger.warning("No map paths provided to post")
        return False
    for path in map_paths:
        if not path.exists():
            logger.error(f"Map file missing: {path}")
            return False

    channel_id = getattr(channel, "id", None)
    if channel is None:
        channel_id = int(os.getenv("MODULE_OUTPUT_CHANNEL_ID", "0")) or int(os.getenv("MAPS_CHANNEL_ID", "0"))
        if not channel_id:
            logger.warning("No module output channel configured")
            return False
        channel = client.get_channel(channel_id)
        if not channel:
            logger.warning(f"Module output channel {channel_id} cannot be accessed by bot")
            return False
        channel_id = channel.id

    title = module_data.get("title", "Unknown Mission")
    embed = discord.Embed(
        title=f"VTT Maps: {title}",
        description=f"Selected {len(map_paths)} tactical battlemaps from the map library.",
        color=discord.Color.dark_teal(),
        timestamp=datetime.now(),
    )

    for attempt in range(1, retry_count + 1):
        try:
            files = [discord.File(str(path), filename=path.name) for path in map_paths[:10]]
            await channel.send(embed=embed, files=files)
            logger.info(f"Posted {len(files)} maps to channel {channel_id} for: {title}")
            return True
        except discord.HTTPException as e:
            if attempt < retry_count and e.status in [429, 503, 500]:
                await asyncio.sleep(2 ** attempt)
                continue
            logger.error(f"Discord HTTP error posting maps: {e.status} {e.message}")
            return False
        except Exception as e:
            logger.error(f"Failed to post maps: {e}")
            if attempt < retry_count:
                await asyncio.sleep(1)
            else:
                return False
    return False


__all__ = [
    "extract_map_scenes",
    "generate_vtt_map",
    "generate_module_maps",
    "post_maps_to_channel",
    "build_map_prompt",
]
