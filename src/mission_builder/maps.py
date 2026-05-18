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
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

import httpx

from src.image_ref import (
    get_location_ref,
    save_location_ref,
    to_img2img_payload,
    LOCATION_DENOISE,
)
from src.log import logger
from src.mission_builder.vtt_renderer import (
    A1111_COOLDOWN_SECONDS,
    ALLOW_AI_TEXTURE,
    decode_useful_a1111_image,
    render_vtt_battlemap,
    STRICT_VTT,
    stylize_pretty_battlemap,
    wait_for_a1111_idle,
    write_grid_sidecar,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")
A1111_TIMEOUT = 600.0  # 10 minutes per map
A1111_MODEL_SWAP_COOLDOWN = float(os.getenv("A1111_MAP_MODEL_SWAP_COOLDOWN", "180"))
A1111_MAP_MAX_ROUNDS = int(os.getenv("A1111_MAP_MAX_ROUNDS", "1"))

# VTT Map dimensions — standard grid-friendly sizes
MAP_WIDTH = 1024
MAP_HEIGHT = 1024

# Map generation settings — Flux.1 [dev] compatible
MAP_STEPS = 20
MAP_CFG = 1.0
MAP_SAMPLER = "Euler"

# Three-LoRA system: dungeon / interior building / town exterior
_LORA_TOWN     = os.getenv("A1111_MAP_LORA_TOWN",     "EnvyFluxVillageMap01")
_LORA_DUNGEON  = os.getenv("A1111_MAP_LORA_DUNGEON",  "EnvyFluxDungeonMap01")
_LORA_INTERIOR = os.getenv("A1111_MAP_LORA_INTERIOR", "")   # set when interior LoRA is installed
_LORA_WEIGHT   = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
_TRIGGERS_TOWN     = os.getenv("A1111_MAP_TOWN_TRIGGERS",     "detailed, map, village")
_TRIGGERS_DUNGEON  = os.getenv("A1111_MAP_DUNGEON_TRIGGERS",  "detailed, map, dungeon")
_TRIGGERS_INTERIOR = os.getenv("A1111_MAP_INTERIOR_TRIGGERS", "detailed, map, interior, floor plan")
_MAPCRAFT_ENABLED = os.getenv("A1111_MAPCRAFT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
_MAPCRAFT_TRIGGER = os.getenv("A1111_MAPCRAFT_TRIGGER", "mapcraft.").strip()
_MAPCRAFT_FLUX_LORA = os.getenv("A1111_MAPCRAFT_FLUX_LORA", "mapcraft_flux_v2").strip()
_MAPCRAFT_SDXL_LORA = os.getenv("A1111_MAPCRAFT_SDXL_LORA", "mapcraft_sdxl_v1").strip()
_MAPCRAFT_FLUX_CHECKPOINT = os.getenv("A1111_MAPCRAFT_FLUX_CHECKPOINT", os.getenv("A1111_FLUX_CHECKPOINT", "flux1-dev-fp8.safetensors")).strip()
_MAPCRAFT_SDXL_CHECKPOINT = os.getenv("A1111_MAPCRAFT_SDXL_CHECKPOINT", os.getenv("A1111_MAP_CHECKPOINT", "")).strip()

# Keywords that indicate a building interior (heist/infiltration/sabotage/investigation)
_INTERIOR_KEYWORDS = {
    "floor plan", "building", "office", "vault", "corridor", "server room",
    "infiltrat", "heist", "interior", "storey", "multi-storey", "crawlspace",
    "service corridor", "freight elevator", "sabotag", "ventilation",
}


def _lora_for_style(style: str):
    """Return (lora_tag, trigger_words) for the correct map type.

    Priority:
      1. dungeon  — underground rooms, stone walls, infestation zones
      2. interior — building floor plans (heist, infiltration, sabotage)
      3. town     — outdoor/street/exterior (everything else)
    Falls back to town if the interior LoRA is not configured yet.
    """
    style_low = style.lower()
    if "dungeon" in style_low:
        return f"<lora:{_LORA_DUNGEON}:{_LORA_WEIGHT}>", _TRIGGERS_DUNGEON
    if _LORA_INTERIOR and any(kw in style_low for kw in _INTERIOR_KEYWORDS):
        return f"<lora:{_LORA_INTERIOR}:{_LORA_WEIGHT}>", _TRIGGERS_INTERIOR
    return f"<lora:{_LORA_TOWN}:{_LORA_WEIGHT}>", _TRIGGERS_TOWN


def _is_flux_checkpoint(name: str) -> bool:
    return "flux" in (name or "").lower()


async def _current_a1111_checkpoint() -> str:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{A1111_URL}/sdapi/v1/options")
            resp.raise_for_status()
            return str(resp.json().get("sd_model_checkpoint") or "").strip()
    except Exception:
        return ""


def _mapcraft_override(strategy: str) -> dict:
    override: dict = {}
    if strategy == "flux" and _MAPCRAFT_FLUX_CHECKPOINT:
        override["sd_model_checkpoint"] = _MAPCRAFT_FLUX_CHECKPOINT
    elif strategy == "sdxl":
        ckpt = _MAPCRAFT_SDXL_CHECKPOINT
        if ckpt:
            override["sd_model_checkpoint"] = ckpt
    elif strategy == "legacy":
        ckpt = os.getenv("A1111_MAP_CHECKPOINT", "").strip()
        if ckpt:
            override["sd_model_checkpoint"] = ckpt
    return override

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "generated_modules"

# ---------------------------------------------------------------------------
# Undercity battlemap style prompts
# ---------------------------------------------------------------------------

# Base style — no environment assumption, that comes from mission/scene type
_BASE_STYLE = (
    "grid-ready, high contrast, clear edges, flat lighting from above, "
    "orthographic view, detailed floor textures, clear walls and boundaries, "
    "high fantasy cyberpunk fusion, wealth-stratified technology, "
    "ancient stone beside neon-lit facades, arcane runes beside circuit panels"
)

# Negative prompt — kept minimal; Flux largely ignores negative prompts
_NEGATIVE = "characters, people, isometric, perspective, watermark, text"

# ---------------------------------------------------------------------------
# Mission-type map styles — what kind of environment the LoRA should draw
# ---------------------------------------------------------------------------

_MISSION_TYPE_STYLES: Dict[str, str] = {
    # Infiltration / sabotage — multi-level building interior
    "infiltration": (
        "multi-storey building floor plan, "
        "service corridors, ventilation crawlspace, freight elevator shaft, "
        "security guard post, locked server room, stairwell, utility pipes along walls"
    ),
    "sabotage": (
        "industrial facility floor plan, "
        "heavy machinery on floor, gantry walkways, control room with consoles, "
        "pressure valve cluster, generator room, maintenance crawlspace, emergency exits"
    ),
    # Escort / courier — city street and urban exterior
    "escort": (
        "wide cobblestone city street, "
        "building facades flanking both sides, market stalls at kerb, alley entrances, "
        "chokepoint bridge or underpass, sewer grate covers, lamp posts at corners"
    ),
    "courier": (
        "urban street and plaza, "
        "exchange point at plaza centre, narrow alleys for escape, market stalls, "
        "canal edge with boat dock, building entrances"
    ),
    # Battle / assault — open combat ground
    "battle": (
        "wide open urban battle ground, "
        "barricades and rubble piles for cover, collapsed wall sections, "
        "flanking alleyways both sides, elevated platform or catwalk, debris scatter"
    ),
    "assault": (
        "fortified compound exterior, "
        "main gate with guardhouse, perimeter wall sections with gaps, "
        "courtyard with fountain, secondary flank entrance, watch tower footprint"
    ),
    # Defense / siege — holdout position
    "defense": (
        "defensive holdout position, "
        "chokepoint gateway, reinforced barricade line with firing positions, "
        "killzone open ground, fallback alcove, breach point in wall"
    ),
    "siege": (
        "fortified interior under siege, "
        "main hall with barricaded doors, breach hole in exterior wall, "
        "defensive line of overturned furniture, last-stand room, window firing positions"
    ),
    # Heist — vault and secure facility
    "heist": (
        "secure facility floor plan, "
        "vault room at back with heavy door, guard station, "
        "service corridor bypass, lobby with reception desk, air-duct entry in ceiling"
    ),
    "retrieval": (
        "storage vault floor plan, "
        "locked cages along walls, central evidence table, "
        "guard post at entrance, records room with shelves, secondary locked door"
    ),
    # Bounty / assassination — contained pursuit space
    "bounty": (
        "flat rooftop with chimney stacks, "
        "skybridge connecting buildings, fire escape ladder head, water tower, "
        "maintenance shack, drop-off edges with low walls"
    ),
    "assassination": (
        "private dining room or meeting chamber, "
        "hidden alcove behind tapestry, servant entrance at back, "
        "window with external ledge, central table obstacle, emergency exit behind panel"
    ),
    # Investigation — searchable interior
    "investigation": (
        "office or study floor plan, "
        "desk and bookshelves, searchable cabinets, hidden floor hatch, "
        "secondary room behind false wall, evidence scatter on surfaces"
    ),
    # Rift / arcane — dungeon supernatural environment
    "rift": (
        "dungeon arcane rift chamber, "
        "glowing fissure crack across floor, warped stone tiles, collapsed pillars, "
        "ritual circle remnants, containment rune circles, unstable floor sections"
    ),
    # Ambush — prepared trap
    "ambush": (
        "narrow ambush alley, "
        "constricted passage with blind corner, hiding positions in doorways, "
        "barrel and crate barricade mid-alley, multiple exit routes"
    ),
    # Gather — outdoor collection point
    "gather": (
        "open market or park area, "
        "collection point with vendor stalls, paths between areas, "
        "scatter objects, benches, crates, multiple entry routes"
    ),
    # Infestation — dungeon interior
    "infestation": (
        "dungeon underground room, "
        "stone walls, torch bracket niches, pit trap cover, debris scatter, "
        "multiple corridor exits, pillars for cover"
    ),
    # Exploration — open survey area
    "exploration": (
        "open survey area, "
        "winding paths, gate markers, unstable terrain sections, survey stakes, "
        "mixed ground types, exit routes marked"
    ),
    # Train / transit
    "train": (
        "fantasy train car interior, "
        "rows of seats along both walls, narrow central aisle, windows each side, "
        "luggage racks above, connecting doors at each end, cargo compartment"
    ),
}

# District-specific aesthetics — wealth determines tech level visible in the environment
_DISTRICT_STYLES: Dict[str, str] = {
    # Wealthy / high-tech districts
    "guild_spires":     "polished glass floors, hover-platform landing pads, guild hologram banners, arcane lighting strips, clean sightlines, maglev freight rails",
    "grand_forum":      "wide civic plaza, luminescent fountain, statue plinths with rune-etched bases, public announcement screens, formal symmetry, tram stop",
    "noble_estate":     "marble tile floors, automated servant alcoves, chandelier with arcane crystal core, private hover-dock, ornate furniture as cover",
    # Mid-tier districts — mixed old and new
    "markets_infinite": "cobblestone with embedded light rails, merchant hover-carts beside wooden stalls, awnings over neon signs, lantern-and-LED mix, crates and barrels",
    "sanctum_quarter":  "religious floor motifs, carved stone archways with power conduit runs alongside, altar stonework, incense brazier beside air recycler",
    "outer_wall":       "heavy fortification stone, guard-post with both crossbow slits and camera mounts, gatehouse arch, patrol drone dock, crenellation footprints",
    "warehouse":        "loading-bay floor markings, forklift tracks beside hand-cart ruts, pallet stacks, support column grid, cargo crane rail overhead",
    "tavern":           "wooden plank flooring over older stone, bar counter with tap handles and arcane keg, hearth beside a humming heat coil, cellar hatch",
    # Poor / low-tech districts
    "warrens":          "crumbling walls with salvaged scrap patches, exposed pipe bundles, dim flickering bulbs beside torch brackets, debris scatter, wagon wheel ruts",
    "arena":            "sand pit with blood stains, tiered audience tiers of stone and scrap metal, entry gate archways, weapon rack alcoves, jury-rigged lighting rigs",
    # Underground / no-tech zones
    "underground":      "rough cave walls, stalactite drops, underground water channel, bioluminescent moss patches, rope bridge anchor points",
    "sewer":            "brick tunnel walls, central water channel, iron grate covers, pipe clusters, damp stone, maintenance walkway, access ladder",
}

# Scene-type tactical overlays (secondary detail, layered last)
_SCENE_FEATURES: Dict[str, str] = {
    "combat":        "tactical cover positions, elevation variation, chokepoint corridor",
    "investigation": "searchable object clutter, hidden compartment hints, evidence on surfaces",
    "social":        "conversation seating cluster, open floor space, ambient furnishing",
    "chase":         "long sight-line corridor, jump-gap obstacle, multiple branching escape paths",
    "ambush":        "concealment alcoves, high-ground position, blind-corner approach",
    "boss":          "large dramatic centrepiece, lair environmental hazard, wide fighting arena",
    "wave":          "staged defensive lines, fallback room, breach point, kill zone open ground",
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


def extract_map_scenes(module_data: dict, mission_type: str = "") -> List[Dict]:
    """
    Extract scenes that need battlemaps from module data.

    Handles LLM output variance — matches both markdown heading formats:
      ### Lead 1: Location Name
      **Lead 1: Location Name**
      ### Scene 4: Location Name
      **Scene 4: Location Name**

    Returns list of dicts with:
    - scene_id: unique identifier
    - scene_name: human readable name
    - location: location name/description
    - description: full scene description
    - district: detected district for styling
    - scene_type: combat/investigation/social/etc
    - mission_type: passed through for map style selection
    - act: which act this is from
    """
    mission_type = mission_type or module_data.get("metadata", {}).get("mission_type", "")
    scenes = []

    raw_content = module_data.get("raw_content", "")
    sections    = module_data.get("sections", {})

    # Fallback: if sections is empty use raw_content for both halves
    if not sections:
        logger.warning("🗺️ No sections found in module_data; attempting raw_content parse")
        sections = {"acts_1_2": raw_content, "acts_3_4": raw_content}

    acts_1_2 = sections.get("acts_1_2", "")
    acts_3_4 = sections.get("acts_3_4", "")

    if not acts_1_2 and not acts_3_4:
        logger.warning("🗺️ Both acts_1_2 and acts_3_4 are empty — no content to extract from")

    # ── Scene/Lead extraction from Acts 1-2 ──────────────────────────────
    # Match: ### Lead N: Name  OR  **Lead N: Name**  (and Scene/Investigation Lead variants)
    # Boundary lookahead stops at the next heading of any kind.
    _HEADING_PAT = r"(?:#{1,4}\s+|\*{1,2}\s*)"
    _SCENE_KWORD = r"(?:Scene|Investigation\s+Lead|Lead)"
    _BOUNDARY    = r"(?=(?:#{1,4}|\*{1,2}\s*(?:Scene|Lead|Investigation|Act|Chapter|Battlefield|Location|Enemy|Reward|Resolution))|\Z)"

    scene_pattern = re.compile(
        _HEADING_PAT
        + _SCENE_KWORD
        + r"\s*\d+\s*[:\-]\s*"        # number + separator
        + r"([^\n\*\[]{2,80}?)"        # captured location name (non-greedy)
        + r"\s*\*{0,2}\s*\n"           # optional closing ** + newline
        + r"(.*?)"                      # scene body
        + _BOUNDARY,
        re.DOTALL | re.IGNORECASE,
    )

    for match in re.finditer(scene_pattern, acts_1_2):
        location_name = match.group(1).strip().rstrip("*").strip()
        if not location_name:
            continue
        scene_text = match.group(2).strip()

        # Pull explicit Setting/Description block if present
        desc_m = re.search(
            r"\*{0,2}(?:Setting|Scene Description)\*{0,2}[:\s]*(.*?)(?=\*{0,2}(?:[A-Z][^a-z]|\Z))",
            scene_text, re.DOTALL | re.IGNORECASE
        )
        description = desc_m.group(1).strip() if desc_m else scene_text[:500]

        scenes.append({
            "scene_id":    f"act2_lead_{_slugify(location_name)}",
            "scene_name":  f"Lead: {location_name}",
            "location":    location_name,
            "description": description,
            "district":    _detect_district(scene_text),
            "scene_type":  _detect_scene_type(scene_text),
            "mission_type": mission_type,
            "act":         2,
        })

    # ── Confrontation scene from Acts 3-4 ────────────────────────────────
    # Tries several header formats; falls back to the whole Act 4 block.
    confrontation_text  = None
    confrontation_loc   = None

    # 1) "### Location: Name"  or  "**Location: Name**"  or same with Battlefield
    conf_loc_match = re.search(
        r"(?:#{1,4}\s*|\*{1,2}\s*)(?:Location|Battlefield)(?:\s+Description)?[:\s]*([^\n\*]{0,80}?)\s*\*{0,2}\s*\n(.*?)(?=#{1,4}|\*{1,2}\s*(?:Enemy|Non-Combat|Reward)|\Z)",
        acts_3_4, re.DOTALL | re.IGNORECASE
    )
    if conf_loc_match:
        raw_loc = conf_loc_match.group(1).strip().rstrip("*").strip()
        # If LLM left the location name blank (e.g. just "### Battlefield Description")
        confrontation_loc  = raw_loc or module_data.get("metadata", {}).get("primary_location", "The Confrontation Site")
        confrontation_text = conf_loc_match.group(2).strip()

    # 2) Fallback: entire Act 4 block
    if not confrontation_text:
        act4_match = re.search(
            r"(?:#{1,4}\s*|\*{1,2}\s*)Act\s*4[:\s]*([^\n\*]*?)\*{0,2}\s*\n(.*?)(?=#{1,4}|\Z)",
            acts_3_4, re.DOTALL | re.IGNORECASE
        )
        if act4_match:
            confrontation_text = act4_match.group(2).strip()
            confrontation_loc  = module_data.get("metadata", {}).get("primary_location", "Final Confrontation")

    # 3) Last resort: just use whatever is in acts_3_4
    if not confrontation_text and acts_3_4.strip():
        confrontation_text = acts_3_4.strip()
        confrontation_loc  = module_data.get("metadata", {}).get("primary_location", "Final Confrontation")

    if confrontation_text and confrontation_loc:
        desc_m = re.search(
            r"\*{0,2}(?:Setting|Scene Description|Battlefield)\*{0,2}[:\s]*(.*?)(?=\*{0,2}[A-Z]|\Z)",
            confrontation_text, re.DOTALL | re.IGNORECASE
        )
        description = desc_m.group(1).strip() if desc_m else confrontation_text[:500]

        scenes.append({
            "scene_id":    f"act4_confrontation_{_slugify(confrontation_loc)}",
            "scene_name":  f"Confrontation: {confrontation_loc}",
            "location":    confrontation_loc,
            "description": description,
            "district":    _detect_district(confrontation_text),
            "scene_type":  "boss",
            "mission_type": mission_type,
            "act":         4,
        })

    logger.info(f"🗺️ Extracted {len(scenes)} map scenes from module")
    if not scenes:
        sample = (acts_1_2 or acts_3_4)[:200].replace("\n", " ")
        logger.warning(f"🗺️ CRITICAL: No scenes extracted. Check module format or sections structure. Raw sample: {sample}...")
    return scenes


# ---------------------------------------------------------------------------
# Map prompt building
# ---------------------------------------------------------------------------

def _mission_type_style(mission_type: str, scene_name: str, description: str) -> str:
    """
    Pick the best mission-type map style.
    Checks mission_type first, then falls back to keywords in scene name/description.
    """
    mtype = (mission_type or "").lower()
    combined = f"{mtype} {scene_name} {description}".lower()

    # Direct mission-type match — most reliable
    for key in _MISSION_TYPE_STYLES:
        if key in mtype:
            return _MISSION_TYPE_STYLES[key]

    # Keyword fallback from scene content
    keyword_map = [
        (["infiltrat", "sneak", "stealth entry", "vent", "crawl", "elevator"],  "infiltration"),
        (["sabotag", "disabl", "destroy", "factory", "machinery", "generator"], "sabotage"),
        (["escort", "protect", "bodyguard", "convoy"],                          "escort"),
        (["courier", "delivery", "handoff", "exchange", "package"],             "courier"),
        (["battle", "assault", "raid", "open combat", "warband"],               "battle"),
        (["defense", "defend", "siege", "holdout", "hold the line"],            "defense"),
        (["heist", "vault", "laser", "security system"],                        "heist"),
        (["retrieval", "recover", "locked room", "evidence locker"],            "retrieval"),
        (["bounty", "hunt", "rooftop", "pursuit"],                              "bounty"),
        (["assassin", "ambush kill", "private room", "target"],                 "assassination"),
        (["invest", "search", "clue", "evidence", "study", "office"],          "investigation"),
        (["rift", "arcane", "magical anomaly", "containment"],                  "rift"),
        (["ambush", "trap", "alley", "narrow"],                                 "ambush"),
    ]
    for keywords, style_key in keyword_map:
        if any(kw in combined for kw in keywords):
            return _MISSION_TYPE_STYLES[style_key]

    # Final fallback — generic urban combat
    return "urban street combat area, building facades flanking, cover positions, chokepoint"


def build_map_prompt(scene: Dict, strategy: str = "legacy") -> Tuple[str, str]:
    """
    Build the SD prompt and negative prompt for a battlemap.

    Order: LoRA tag → environment trigger (Town/Interior/Dungeon + Table Map) →
           location description → district tint → tactical details → quality modifiers.
    The LoRA trigger MUST be the first content token after the LoRA tag.
    """
    location     = scene.get("location", "unknown location")
    description  = scene.get("description", "")
    district     = scene.get("district", "warrens")
    scene_type   = scene.get("scene_type", "combat")
    mission_type = scene.get("mission_type", "")
    scene_name   = scene.get("scene_name", "")

    # 1. Environment description (used to pick the right LoRA)
    mission_style = _mission_type_style(mission_type, scene_name, description)

    # 2. Pick correct Flux LoRA + activation triggers based on dungeon vs town
    lora_tag, triggers = _lora_for_style(mission_style)
    if _MAPCRAFT_ENABLED and strategy in {"flux", "sdxl"}:
        lora_name = _MAPCRAFT_FLUX_LORA if strategy == "flux" else _MAPCRAFT_SDXL_LORA
        lora_tag = f"<lora:{lora_name}:{_LORA_WEIGHT}>" if lora_name else ""
        triggers = _MAPCRAFT_TRIGGER

    # 3. District aesthetic
    district_style = _DISTRICT_STYLES.get(district, "")

    # 4. Scene tactical overlay
    tactical_key = "wave" if any(
        w in (mission_type or "").lower() for w in ("battle", "defense", "defend", "siege", "assault")
    ) else scene_type
    scene_features = _SCENE_FEATURES.get(tactical_key, _SCENE_FEATURES["combat"])

    # LoRA tag → triggers → environment description → quality modifiers
    prompt_parts = [
        lora_tag,
        triggers,               # ← Flux activation tokens first
        mission_style,          # ← environment description
    ]
    if _MAPCRAFT_ENABLED and strategy in {"flux", "sdxl"}:
        prompt_parts = [
            lora_tag,
            triggers,
            f"A top-down view of {mission_style}.",
        ]

    if location and location.lower() not in ("unknown location", ""):
        prompt_parts.append(location)
    if description and len(description) > 20:
        prompt_parts.append(description[:180])
    if district_style:
        prompt_parts.append(district_style)
    prompt_parts.append(scene_features)
    if _MAPCRAFT_ENABLED and strategy in {"flux", "sdxl"}:
        prompt_parts.append("clear 5 foot square grid, orthographic VTT battlemap, readable tactical layout, no people, no tokens")
    prompt_parts.append(_BASE_STYLE)  # ← quality modifiers last

    # Pull strong visual nouns from description
    if description and len(description) > 20:
        visual_words = []
        for word in description.split():
            w = word.lower().strip(".,!?;:")
            if w in {"stone", "wood", "metal", "water", "fire", "dark", "light",
                     "broken", "ruined", "ornate", "ancient", "blood", "shadow",
                     "narrow", "wide", "tall", "low", "open", "closed", "hidden"}:
                visual_words.append(w)
        if visual_words:
            prompt_parts.append(", ".join(dict.fromkeys(visual_words))[:80])

    return ", ".join(p for p in prompt_parts if p), _NEGATIVE


# ---------------------------------------------------------------------------
# A1111 generation
# ---------------------------------------------------------------------------

_loras_refreshed = False


async def _check_a1111_available() -> bool:
    """Check if A1111 is running and responsive."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{A1111_URL}/sdapi/v1/sd-models")
            return resp.status_code == 200
    except Exception:
        return False


async def _ensure_loras_refreshed() -> None:
    """Tell A1111 to rescan its LoRA folder. Called once per process lifetime."""
    global _loras_refreshed
    if _loras_refreshed:
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{A1111_URL}/sdapi/v1/refresh-loras")
            if resp.status_code == 200:
                logger.info("🗺️ A1111 LoRA list refreshed")
            else:
                logger.warning(f"🗺️ LoRA refresh returned {resp.status_code}")
    except Exception as e:
        logger.warning(f"🗺️ LoRA refresh failed (non-fatal): {e}")
    _loras_refreshed = True


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
    if STRICT_VTT and not ALLOW_AI_TEXTURE:
        logger.info("Strict VTT mode active; rendering tactical map without direct A1111 texture for: %s", scene["scene_name"])
        return render_vtt_battlemap(context=scene)

    if not await _check_a1111_available():
        logger.warning("🗺️ A1111 not available for map generation")
        return render_vtt_battlemap(context=scene)

    await _ensure_loras_refreshed()

    strategies = ["legacy"]
    if _MAPCRAFT_ENABLED:
        strategies = ["flux", "sdxl", "legacy"]
    
    logger.info(f"🗺️ Generating map for: {scene['scene_name']}")
    
    # Build base payload
    payload = {
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
        from src.news_feed import a1111_lock
        from src.resource_cop import wait_for_a1111_turn

        decision = await wait_for_a1111_turn("mission_map", model_hint=str(scene.get("scene_name", "")))
        if not decision.run_now:
            logger.info("🗺️ A1111 stayed busy for mission map; using deterministic VTT fallback: %s", decision.reason)
            return render_vtt_battlemap(context=scene)
        
        async with a1111_lock:
            images = []
            decoded_image = None
            used_prompt = ""
            async with httpx.AsyncClient(timeout=A1111_TIMEOUT) as client:
                for idx, strategy in enumerate(strategies, start=1):
                    positive, negative = build_map_prompt(scene, strategy)
                    attempt = {**payload, "prompt": positive, "negative_prompt": negative}
                    override = _mapcraft_override(strategy)
                    if override:
                        attempt["override_settings"] = override
                        attempt["override_settings_restore_afterwards"] = True
                    logger.info(f"🗺️ Trying {strategy} map strategy for: {scene['scene_name']}")
                    logger.debug(f"🗺️ Prompt: {positive[:200]}...")
                    await asyncio.to_thread(
                        wait_for_a1111_idle,
                        cooldown=max(A1111_COOLDOWN_SECONDS, A1111_MODEL_SWAP_COOLDOWN if idx > 1 else 0),
                    )
                    try:
                        resp = await client.post(f"{A1111_URL}{endpoint}", json=attempt)
                        resp.raise_for_status()
                        images = resp.json().get("images", [])
                        await asyncio.to_thread(wait_for_a1111_idle, cooldown=max(A1111_COOLDOWN_SECONDS, 45))
                        if images:
                            decoded_image = decode_useful_a1111_image(images[0])
                            if not decoded_image:
                                logger.warning(f"🗺️ {strategy} map strategy returned a blank/invalid image for: {scene['scene_name']}")
                                images = []
                                continue
                            used_prompt = positive
                            break
                    except Exception as exc:
                        logger.warning(f"🗺️ {strategy} map strategy failed: {exc}")
                        await asyncio.to_thread(wait_for_a1111_idle, cooldown=max(A1111_COOLDOWN_SECONDS, A1111_MODEL_SWAP_COOLDOWN))
        
        if not decoded_image:
            logger.warning("A1111 returned no useful map image for %s; using deterministic VTT fallback", scene["scene_name"])
            return render_vtt_battlemap(context=scene)
        
        img_bytes = render_vtt_battlemap(
            context={**scene, "prompt": used_prompt},
            ai_png=decoded_image,
        )
        
        logger.info(f"🗺️ Map generated: {len(img_bytes):,} bytes")
        return img_bytes
        
    except Exception as e:
        logger.error(f"🗺️ Map generation failed: {e}")
        return render_vtt_battlemap(context=scene)


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
            write_grid_sidecar(map_path, scene)
            pretty_path = await asyncio.to_thread(stylize_pretty_battlemap, map_path, scene, True)
            generated_paths.append(map_path)
            logger.info(f"🗺️ Saved map: {map_path}")

            # Save a visual reference separately from the authoritative VTT map.
            ref_meta = {
                "district":    scene.get("district", "unknown"),
                "scene_type":  scene.get("scene_type", "combat"),
                "scene_name":  scene.get("scene_name", ""),
                "module_title": module_data.get("title", ""),
                "map_file":    str(map_path.resolve()),
            }
            ref_source_path = pretty_path if pretty_path and pretty_path.exists() else map_path
            ref_meta["visual_ref_file"] = str(ref_source_path.resolve())
            save_location_ref(location, ref_source_path.read_bytes(), metadata=ref_meta)
            logger.info(f"🗺️ Updated reference for: {location} (district={ref_meta['district']})")
        
        # Small delay between generations
        await asyncio.sleep(2)
    
    logger.info(f"🗺️ Generated {len(generated_paths)} maps for module")
    return generated_paths


async def post_maps_to_channel(
    client,
    map_paths: List[Path],
    module_data: dict,
    retry_count: int = 2,
    channel=None,
) -> bool:
    """
    Post generated maps to the module output channel with retry logic.

    Posts to the same channel as the DOCX (MODULE_OUTPUT_CHANNEL_ID).
    Pass channel directly to skip the lookup.

    Args:
        client: Discord client
        map_paths: List of paths to map files
        module_data: Module data for context
        retry_count: Number of retries on transient failures
        channel: Optional pre-resolved discord.TextChannel (skips env lookup)

    Returns:
        True if posted successfully, False otherwise
    """
    import discord

    if not map_paths:
        logger.warning("🗺️ No map paths provided to post")
        return False

    # Validate all map files exist before attempting post
    for p in map_paths:
        if not p.exists():
            logger.error(f"🗺️ Map file missing: {p}")
            return False

    # Use provided channel, or resolve from MODULE_OUTPUT_CHANNEL_ID
    channel_id = getattr(channel, "id", None)
    if channel is None:
        channel_id = int(os.getenv("MODULE_OUTPUT_CHANNEL_ID", "0")) or int(os.getenv("MAPS_CHANNEL_ID", "0"))
        if not channel_id:
            logger.warning("🗺️ No module output channel configured (MODULE_OUTPUT_CHANNEL_ID)")
            return False
        channel = client.get_channel(channel_id)
        if not channel:
            logger.warning(f"🗺️ Module output channel {channel_id} cannot be accessed by bot")
            return False
        channel_id = channel.id

    # Verify bot has send permissions
    try:
        perms = channel.permissions_for(channel.guild.me) if hasattr(channel, 'guild') and channel.guild else None
        if perms and not perms.send_messages:
            logger.error(f"🗺️ Bot lacks send_messages permission in maps channel {channel_id}")
            return False
        if perms and not perms.attach_files:
            logger.error(f"🗺️ Bot lacks attach_files permission in maps channel {channel_id}")
            return False
    except Exception as e:
        logger.warning(f"🗺️ Could not verify permissions: {e} — proceeding anyway")
    
    title = module_data.get("title", "Unknown Mission")
    
    embed = discord.Embed(
        title=f"🗺️ VTT Maps: {title}",
        description=f"Generated {len(map_paths)} tactical battlemaps for this mission.\n"
                    f"*1024x1024px, optimized for D&D Beyond VTT*",
        color=discord.Color.dark_teal(),
        timestamp=datetime.now(),
    )
    
    # Retry loop for transient failures
    for attempt in range(1, retry_count + 1):
        try:
            files = [
                discord.File(str(p), filename=p.name)
                for p in map_paths[:10]  # Discord limit
            ]
            await channel.send(embed=embed, files=files)
            logger.info(f"✅ Posted {len(files)} maps to channel {channel_id} for: {title}")
            return True
        except discord.HTTPException as e:
            if attempt < retry_count and e.status in [429, 503, 500]:  # Retry on rate limit or server error
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(f"🗺️ HTTP {e.status} from Discord (attempt {attempt}/{retry_count}), waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(f"🗺️ Discord HTTP error (final): {e.status} {e.message}")
                return False
        except Exception as e:
            logger.error(f"🗺️ Failed to post maps (attempt {attempt}/{retry_count}): {e}")
            if attempt < retry_count:
                await asyncio.sleep(1)
            else:
                return False
    
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
