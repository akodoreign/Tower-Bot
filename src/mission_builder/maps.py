"""
maps.py — VTT battlemap generation for mission modules.

Generates top-down tactical battlemaps for each combat/exploration scene
in a mission module using A1111/Stable Diffusion.

Uses image_ref.py for iterative improvement — each generated map is saved
as a location reference, so future maps of the same location improve over time.

Directory layout:
  generated_modules/[module_name]/
    maps/
      act2_lead1_[location_slug].png
      act4_confrontation_[location_slug].png
      ...

Exported:
    extract_map_scenes(module_data) -> list of scene dicts
    generate_vtt_map(scene, ref_bytes=None) -> bytes (PNG)
    generate_module_maps(module_data) -> list of paths
"""

from __future__ import annotations

import os
import re
import json
import base64
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Tuple

import httpx

from src.image_ref import (
    get_location_ref,
    save_location_ref,
    to_img2img_payload,
    LOCATION_DENOISE,
)
from src.log import logger

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")
A1111_TIMEOUT = 600.0  # 10 minutes per map

# VTT Map dimensions — standard grid-friendly sizes
MAP_WIDTH = 1024
MAP_HEIGHT = 1024

# Map generation settings
MAP_STEPS = 30
MAP_CFG = 7.5
MAP_SAMPLER = "DPM++ 2M Karras"

# Checkpoint for maps — use the photorealistic model for battlemaps
MAP_MODEL = os.getenv("A1111_MODEL", "juggernautXL_version6Rundiffusion.safetensors")

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "generated_modules"

# ---------------------------------------------------------------------------
# Undercity battlemap style prompts
# ---------------------------------------------------------------------------

# Base style applied to all maps
_BASE_STYLE = """top-down tactical battlemap, D&D VTT map, grid-ready, 
dungeon map style, dark fantasy, high contrast, clear edges, 
flat lighting from above, no perspective distortion, orthographic view,
detailed floor textures, clear walls and boundaries"""

# Negative prompt to avoid
_NEGATIVE = """3d render, perspective, isometric, character, people, monsters,
side view, angle, sky, clouds, sun, horizon, blurry, low quality,
realistic photo, photograph, watermark, signature, text, UI elements,
miniatures, tokens, grid overlay, numbers, letters"""

# District-specific aesthetics
_DISTRICT_STYLES: Dict[str, str] = {
    "markets_infinite": "cobblestone streets, market stalls, crates and barrels, awnings, vendor booths, lantern light, cramped alleyways",
    "warrens": "ruined buildings, debris piles, makeshift shelters, cracked stone, exposed pipes, dim lighting, dangerous terrain, collapsed walls",
    "guild_spires": "polished stone floors, ornate pillars, guild banners, clean architecture, magic lighting, elegant design",
    "sanctum_quarter": "temple architecture, religious symbols, altar spaces, ceremonial chambers, divine light, incense braziers",
    "grand_forum": "open plaza, fountain features, statue pedestals, wide streets, civic architecture, public squares",
    "outer_wall": "fortifications, guard towers, heavy stone, murder holes, defensive positions, patrol routes, gatehouse",
    "underground": "cave systems, rough stone, stalactites, underground river, natural formations, dim bioluminescence",
    "sewer": "brick tunnels, water channels, walkways, grates, pipes, damp stone, refuse piles",
    "warehouse": "wooden crates, shelving units, loading areas, support columns, storage containers, industrial space",
    "tavern": "wooden floor, bar counter, tables and chairs, fireplace, kitchen area, storage room, stairs",
    "noble_estate": "marble floors, ornate furniture, paintings, chandeliers, formal gardens, hedge maze",
    "arena": "sand pit, spectator stands, gladiator gates, weapon racks, blood stains, dramatic lighting",
}

# Scene type specific features
_SCENE_FEATURES: Dict[str, str] = {
    "combat": "clear tactical positions, cover objects, elevation changes, chokepoints",
    "investigation": "clutter and details, searchable objects, hiding spots, evidence markers",
    "social": "conversation areas, seating arrangements, ambient details",
    "chase": "long corridors, obstacles, multiple paths, escape routes",
    "ambush": "hiding spots, high ground, shadows, surprise positions",
    "boss": "large central area, dramatic centerpiece, lair features, environmental hazards",
}


# ---------------------------------------------------------------------------
# Scene extraction from module data
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower().strip()).strip("_")[:50]


def _detect_district(text: str) -> str:
    """Detect which district a scene is in based on text content."""
    text_lower = text.lower()
    
    district_keywords = {
        "markets_infinite": ["market", "bazaar", "vendor", "stall", "cobbleway", "neon row"],
        "warrens": ["warren", "collapsed", "ruin", "shanty", "slum", "debris"],
        "guild_spires": ["guild", "spire", "tower", "academy", "headquarters"],
        "sanctum_quarter": ["temple", "shrine", "sanctum", "church", "holy", "divine"],
        "grand_forum": ["forum", "plaza", "fountain", "civic", "library"],
        "outer_wall": ["wall", "gate", "fortification", "guard", "watchtower"],
        "underground": ["cave", "cavern", "underground", "tunnel", "subterranean"],
        "sewer": ["sewer", "drain", "pipe", "waste", "runoff"],
        "warehouse": ["warehouse", "storage", "crate", "dock", "loading"],
        "tavern": ["tavern", "inn", "bar", "soot", "cinder", "pub"],
        "arena": ["arena", "pit", "gladiator", "combat ring"],
    }
    
    for district, keywords in district_keywords.items():
        if any(kw in text_lower for kw in keywords):
            return district
    
    return "warrens"  # Default to Warrens aesthetic


def _detect_scene_type(text: str) -> str:
    """Detect the type of scene for tactical feature selection."""
    text_lower = text.lower()
    
    if any(w in text_lower for w in ["boss", "leader", "final", "climax", "lair"]):
        return "boss"
    if any(w in text_lower for w in ["ambush", "trap", "surprise", "hidden"]):
        return "ambush"
    if any(w in text_lower for w in ["chase", "pursuit", "flee", "escape"]):
        return "chase"
    if any(w in text_lower for w in ["investigate", "search", "clue", "evidence"]):
        return "investigation"
    if any(w in text_lower for w in ["talk", "negotiate", "meet", "social", "conversation"]):
        return "social"
    
    return "combat"  # Default


def extract_map_scenes(module_data: dict) -> List[Dict]:
    """
    Extract scenes that need battlemaps from module data.
    
    Returns list of dicts with:
    - scene_id: unique identifier
    - scene_name: human readable name
    - location: location name/description
    - description: full scene description
    - district: detected district for styling
    - scene_type: combat/investigation/social/etc
    - act: which act this is from
    """
    scenes = []
    
    raw_content = module_data.get("raw_content", "")
    sections = module_data.get("sections", {})
    
    # Parse Act 2 leads (investigation locations)
    acts_1_2 = sections.get("acts_1_2", "")
    lead_pattern = r"###\s*Lead\s*\d+:\s*([^\n]+)\n(.*?)(?=###|##|$)"
    
    for match in re.finditer(lead_pattern, acts_1_2, re.DOTALL | re.IGNORECASE):
        location_name = match.group(1).strip()
        scene_text = match.group(2).strip()
        
        # Extract scene description if present
        desc_match = re.search(r"\*\*Scene Description\*\*[:\s]*(.*?)(?=\*\*|$)", scene_text, re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else scene_text[:500]
        
        scenes.append({
            "scene_id": f"act2_lead_{_slugify(location_name)}",
            "scene_name": f"Lead: {location_name}",
            "location": location_name,
            "description": description,
            "district": _detect_district(scene_text),
            "scene_type": _detect_scene_type(scene_text),
            "act": 2,
        })
    
    # Parse Act 4 confrontation (main battle)
    acts_3_4 = sections.get("acts_3_4", "")
    
    # Look for battlefield section
    battlefield_match = re.search(
        r"###\s*Battlefield:\s*([^\n]+)\n(.*?)(?=###|##|$)",
        acts_3_4, re.DOTALL | re.IGNORECASE
    )
    
    if battlefield_match:
        location_name = battlefield_match.group(1).strip()
        scene_text = battlefield_match.group(2).strip()
        
        desc_match = re.search(r"\*\*Scene Description\*\*[:\s]*(.*?)(?=\*\*|$)", scene_text, re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else scene_text[:500]
        
        scenes.append({
            "scene_id": f"act4_confrontation_{_slugify(location_name)}",
            "scene_name": f"Confrontation: {location_name}",
            "location": location_name,
            "description": description,
            "district": _detect_district(scene_text),
            "scene_type": "boss",  # Act 4 is always the boss fight
            "act": 4,
        })
    else:
        # Fallback: look for Act 4 header
        act4_match = re.search(
            r"##\s*Act\s*4[:\s]*([^\n]*)\n(.*?)(?=##|$)",
            acts_3_4, re.DOTALL | re.IGNORECASE
        )
        if act4_match:
            scene_text = act4_match.group(2).strip()
            scenes.append({
                "scene_id": "act4_confrontation",
                "scene_name": "Final Confrontation",
                "location": module_data.get("metadata", {}).get("primary_location", "Unknown"),
                "description": scene_text[:500],
                "district": _detect_district(scene_text),
                "scene_type": "boss",
                "act": 4,
            })
    
    logger.info(f"🗺️ Extracted {len(scenes)} map scenes from module")
    return scenes


# ---------------------------------------------------------------------------
# Map prompt building
# ---------------------------------------------------------------------------

def build_map_prompt(scene: Dict) -> Tuple[str, str]:
    """
    Build the SD prompt and negative prompt for a battlemap.
    
    Returns (positive_prompt, negative_prompt)
    """
    location = scene.get("location", "unknown location")
    description = scene.get("description", "")
    district = scene.get("district", "warrens")
    scene_type = scene.get("scene_type", "combat")
    
    # Get district and scene type styles
    district_style = _DISTRICT_STYLES.get(district, _DISTRICT_STYLES["warrens"])
    scene_features = _SCENE_FEATURES.get(scene_type, _SCENE_FEATURES["combat"])
    
    # Build prompt
    prompt_parts = [
        _BASE_STYLE,
        f"location: {location}",
        district_style,
        scene_features,
    ]
    
    # Add description details if meaningful
    if description and len(description) > 20:
        # Extract key visual elements from description
        visual_words = []
        for word in description.split():
            word_clean = word.lower().strip(".,!?;:")
            if word_clean in ["stone", "wood", "metal", "water", "fire", "dark", "light",
                             "broken", "ruined", "ornate", "ancient", "blood", "shadow"]:
                visual_words.append(word_clean)
        if visual_words:
            prompt_parts.append(", ".join(visual_words[:5]))
    
    positive = ", ".join(prompt_parts)
    
    return positive, _NEGATIVE


# ---------------------------------------------------------------------------
# A1111 generation
# ---------------------------------------------------------------------------

async def _check_a1111_available() -> bool:
    """Check if A1111 is running and responsive."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{A1111_URL}/sdapi/v1/sd-models")
            return resp.status_code == 200
    except Exception:
        return False


async def generate_vtt_map(
    scene: Dict,
    ref_bytes: Optional[bytes] = None,
    denoise: float = LOCATION_DENOISE,
) -> Optional[bytes]:
    """
    Generate a VTT battlemap for a scene.
    
    Args:
        scene: Scene dict from extract_map_scenes()
        ref_bytes: Optional reference image for img2img
        denoise: Denoising strength for img2img (0.0-1.0)
    
    Returns:
        PNG image bytes, or None on failure
    """
    if not await _check_a1111_available():
        logger.warning("🗺️ A1111 not available for map generation")
        return None
    
    positive, negative = build_map_prompt(scene)
    
    logger.info(f"🗺️ Generating map for: {scene['scene_name']}")
    logger.debug(f"🗺️ Prompt: {positive[:200]}...")
    
    # Build base payload
    payload = {
        "prompt": positive,
        "negative_prompt": negative,
        "width": MAP_WIDTH,
        "height": MAP_HEIGHT,
        "steps": MAP_STEPS,
        "cfg_scale": MAP_CFG,
        "sampler_name": MAP_SAMPLER,
        "seed": -1,  # Random seed
    }
    
    # Use img2img if we have a reference
    endpoint = "/sdapi/v1/txt2img"
    if ref_bytes:
        payload = to_img2img_payload(payload, ref_bytes, denoise)
        endpoint = "/sdapi/v1/img2img"
        logger.info(f"🗺️ Using reference image (denoise={denoise})")
    
    try:
        # Import the lock from news_feed to respect A1111 queue
        from src.news_feed import a1111_lock, _a1111_lock
        
        if _a1111_lock.locked():
            logger.info("🗺️ A1111 busy, waiting for lock...")
        
        async with a1111_lock:
            async with httpx.AsyncClient(timeout=A1111_TIMEOUT) as client:
                resp = await client.post(f"{A1111_URL}{endpoint}", json=payload)
                resp.raise_for_status()
                data = resp.json()
        
        images = data.get("images", [])
        if not images:
            logger.error("🗺️ A1111 returned no images")
            return None
        
        # Decode first image
        img_b64 = images[0]
        img_bytes = base64.b64decode(img_b64)
        
        logger.info(f"🗺️ Map generated: {len(img_bytes):,} bytes")
        return img_bytes
        
    except Exception as e:
        logger.error(f"🗺️ Map generation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Full module map generation
# ---------------------------------------------------------------------------

async def generate_module_maps(
    module_data: dict,
    output_subdir: Optional[str] = None,
    max_maps: int = 5,
) -> List[Path]:
    """
    Generate VTT maps for all combat/exploration scenes in a module.
    
    Uses image_ref.py to check for existing location references and
    saves newly generated maps as references for future use.
    
    Args:
        module_data: The full module data dict
        output_subdir: Subdirectory under generated_modules/ for maps
        max_maps: Maximum number of maps to generate (avoid runaway)
    
    Returns:
        List of paths to generated map files
    """
    scenes = extract_map_scenes(module_data)
    
    if not scenes:
        logger.info("🗺️ No map scenes found in module")
        return []
    
    # Limit to max_maps
    if len(scenes) > max_maps:
        logger.info(f"🗺️ Limiting to {max_maps} maps (found {len(scenes)} scenes)")
        # Prioritize: Act 4 boss fight first, then Act 2 leads
        scenes = sorted(scenes, key=lambda s: (s["act"] != 4, s["act"]))[:max_maps]
    
    # Create output directory
    if output_subdir:
        maps_dir = OUTPUT_DIR / output_subdir / "maps"
    else:
        title = module_data.get("title", "unknown")
        safe_title = _slugify(title)
        maps_dir = OUTPUT_DIR / safe_title / "maps"
    
    maps_dir.mkdir(parents=True, exist_ok=True)
    
    generated_paths = []
    
    for scene in scenes:
        location = scene.get("location", "unknown")
        scene_id = scene.get("scene_id", "map")
        
        # Check for existing reference
        ref_bytes = get_location_ref(location)
        if ref_bytes:
            logger.info(f"🗺️ Found reference for {location}")
        
        # Generate map
        map_bytes = await generate_vtt_map(scene, ref_bytes=ref_bytes)
        
        if map_bytes:
            # Save to output directory
            map_path = maps_dir / f"{scene_id}.png"
            map_path.write_bytes(map_bytes)
            generated_paths.append(map_path)
            logger.info(f"🗺️ Saved map: {map_path}")
            
            # Save as location reference for future iterations
            save_location_ref(location, map_bytes)
            logger.info(f"🗺️ Updated reference for: {location}")
        
        # Small delay between generations
        await asyncio.sleep(2)
    
    logger.info(f"🗺️ Generated {len(generated_paths)} maps for module")
    return generated_paths


async def post_maps_to_channel(
    client,
    map_paths: List[Path],
    module_data: dict,
) -> bool:
    """
    Post generated maps to the maps channel.
    
    Args:
        client: Discord client
        map_paths: List of paths to map files
        module_data: Module data for context
    
    Returns:
        True if posted successfully
    """
    import discord
    
    channel_id = int(os.getenv("MAPS_CHANNEL_ID", "0"))
    if not channel_id:
        # Fall back to module output channel
        channel_id = int(os.getenv("MODULE_OUTPUT_CHANNEL_ID", "0"))
    
    if not channel_id:
        logger.warning("🗺️ No maps channel configured")
        return False
    
    channel = client.get_channel(channel_id)
    if not channel:
        logger.warning(f"🗺️ Maps channel {channel_id} not found")
        return False
    
    title = module_data.get("title", "Unknown Mission")
    
    embed = discord.Embed(
        title=f"🗺️ VTT Maps: {title}",
        description=f"Generated {len(map_paths)} tactical battlemaps for this mission.\n"
                    f"*1024x1024px, optimized for D&D Beyond VTT*",
        color=discord.Color.dark_teal(),
    )
    
    try:
        files = [
            discord.File(str(p), filename=p.name)
            for p in map_paths[:10]  # Discord limit
        ]
        await channel.send(embed=embed, files=files)
        logger.info(f"🗺️ Posted {len(files)} maps to channel")
        return True
    except Exception as e:
        logger.error(f"🗺️ Failed to post maps: {e}")
        return False


# ---------------------------------------------------------------------------
# Convenience exports
# ---------------------------------------------------------------------------

__all__ = [
    "extract_map_scenes",
    "generate_vtt_map",
    "generate_module_maps",
    "post_maps_to_channel",
    "build_map_prompt",
]
