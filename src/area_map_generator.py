"""
area_map_generator.py — Overnight overhead area map generation from the city gazetteer.

Runs as part of the 3am-4am learning window. Reads the city gazetteer, finds every
district and sub_area that doesn't yet have an overhead PNG, and generates them in
small batches using A1111 + DD_Table_RPG LoRA.

Maps are written to Webpage/area_maps/<district_slug>/<area_slug>.png
and served by Flask via /area-maps/<path>.

Exported:
    generate_area_map_batch(batch_size)  — async, generates up to N missing maps
    list_area_maps()                     — sync, returns dict[district_slug → list of map paths]
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

from src.log import logger

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

A1111_URL     = os.getenv("A1111_URL", "http://127.0.0.1:7860")
A1111_TIMEOUT = 600.0

# Overhead area map dimensions — slightly wider for street-level views
MAP_WIDTH  = 1024
MAP_HEIGHT = 1024

MAP_STEPS   = 35        # more passes for cleaner area maps
MAP_CFG     = 7.0
MAP_SAMPLER = "DPM++ 2M Karras"
MAP_LORA    = "<lora:DD_Table_RPG:0.85>"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AREA_MAPS_DIR  = PROJECT_ROOT / "Webpage" / "area_maps"

# ---------------------------------------------------------------------------
# Prompt library — overhead area styles by environment keyword
# ---------------------------------------------------------------------------

# Outdoor/city areas — streets, markets, plazas, districts
_BASE_STYLE_TOWN = (
    "town map, top-down city map, DnD fantasy city map, overhead view, bird's eye view, "
    "DD_Table_RPG style, high detail, clean linework, flat orthographic perspective, "
    "no perspective distortion, detailed ground textures, vibrant environment art"
)
# Interior/floor-plan areas — taverns, guilds, dungeons, sewers, vaults
_BASE_STYLE_INTERIOR = (
    "top-down floor plan, interior map, dungeon map, room layout, bird's eye view, "
    "DD_Table_RPG style, high detail, clean linework, flat orthographic perspective, "
    "no perspective distortion, detailed floor textures, furniture and features visible"
)

# Which style keys count as interiors
_INTERIOR_STYLES = {
    "sewer", "cistern", "vault", "laboratory", "infirmary", "prison", "barracks",
    "forge", "workshop", "archive", "library", "guild", "temple", "shrine",
    "arena", "tavern", "inn", "manor", "noble", "tower", "warehouse",
    "underground", "cave", "office",
}

_NEGATIVE = (
    "3d render, isometric, side view, character, people, monsters, portrait, "
    "sky background, clouds, horizon line, blurry, low quality, watermark, "
    "signature, text overlay, UI elements, grid numbers, tokens, miniatures, "
    "aerial photograph, satellite image, realistic photo"
)

_AREA_STYLES: Dict[str, str] = {
    # Underground city districts
    "market":        "market stalls, cobblestone street, merchant carts, awnings, crates and barrels, lanterns, dense crowd flow paths, narrow alleys",
    "bazaar":        "open market, vendor tents, central fountain, trading post, colorful fabrics, scattered goods, winding paths",
    "sewer":         "brick tunnels, water channels, stone walkways, iron grates, pipes and drains, damp mossy walls, maintenance catwalks",
    "underground":   "rough stone cavern, stalactites on edges, underground river, bioluminescent pools, natural rock columns, carved paths",
    "tavern":        "wooden floor planks, central bar counter, round tables and chairs, fireplace hearth, kitchen alcove, staircase, storage barrels",
    "inn":           "reception desk, common room, hearth, guest room doors along corridor, stable area, luggage storage",
    "guild":         "guild hall interior, meeting table, notice board with papers, trophy displays, training area, administrative desks",
    "temple":        "central altar with offering bowls, stone pews, incense braziers, prayer alcoves, sacred fountain, vaulted ceiling pattern",
    "shrine":        "small sacred space, votive candles, offering shelf, kneeling mat, divine symbol carved into floor",
    "office":        "rows of writing desks, filing cabinets, central meeting table, bookshelves along walls, clerk stations, open floor plan",
    "library":       "tall bookshelves in rows, reading tables, card catalogue, winding staircases between levels, archive alcoves",
    "archive":       "packed shelving, scroll tubes, document boxes, narrow aisles, researcher tables, climate-controlled vaults",
    "workshop":      "workbench stations, tools hung on walls, forge or press at center, material bins, project tables, machinery",
    "forge":         "central forge with anvil, cooling troughs, tool racks, coal bins, bellows, metal stock piles",
    "warehouse":     "large storage crates, tall shelving units, loading dock, support columns, forklift paths, inventory staging area",
    "dock":          "canal-side loading area, tied boats, crane mechanism, cargo nets, bollards, warehouse doors",
    "prison":        "cell blocks in rows, guard station, exercise yard, interrogation room, armory alcove",
    "barracks":      "bunk beds in rows, weapon racks, armor stands, training mat, officer desk, mess table",
    "arena":         "central sand pit with blood stains, tiered spectator stands, gladiator entrance gates, weapon racks, medical alcove",
    "plaza":         "wide open stone plaza, central monument or fountain, radiating paths, benches, decorative planters",
    "garden":        "cultivated bioluminescent plant beds, winding garden paths, stone benches, trellis structures, central water feature",
    "park":          "open grass clearing, mature trees at edges, walking paths, rest areas, small pond",
    "noble":         "marble floors, ornate furniture clusters, chandelier position, formal sitting areas, servant passages",
    "manor":         "grand entry hall, split staircase, dining room, parlor, study, servants quarters at rear",
    "tower":         "circular floor plan, spiral staircase well at center, radial room layout, arcane apparatus, observation windows",
    "ruin":          "collapsed walls, rubble piles, partial flooring, exposed foundations, overgrown reclamation, debris scatter",
    "slum":          "tightly packed shanties, improvised structures, shared courtyard, laundry lines, refuse areas, narrow irregular paths",
    "gate":          "fortified gatehouse, portcullis mechanism, guard stations, flanking towers, approach road, inspection area",
    "alley":         "narrow passage, dumpster alcoves, fire escapes, doorways, drainage gutters, dead end alcove",
    "crossroads":    "four-way street intersection, center marker, street vendor positions, signpost, flow of foot traffic implied",
    "street":        "cobblestone road, sidewalk areas, building facades along edges, lamp posts, manhole covers, vendor stalls",
    "canal":         "water channel with stone banks, pedestrian bridges, moored gondolas, waterside buildings, steps to water level",
    "cave":          "organic cave walls, stalactite fields, underground pool, rope bridges, luminescent mushroom clusters",
    "cistern":       "large water storage chamber, support pillars in water, walkway along edges, pump mechanisms, overflow channels",
    "vault":         "reinforced door at entry, safety deposit rows, counting tables, armored teller stations, guard post",
    "laboratory":    "experiment tables, reagent shelves, distillation apparatus, specimen jars, chalkboard wall, safety containment zone",
    "infirmary":     "patient bed rows, supply cabinet, operating table, washbasin stations, quarantine alcove",
    "rooftop":       "flat roof surface, chimneys, skylights, water tower, rope bridges to adjacent roofs, parapet edge",
}

# District-level context injections
_DISTRICT_CONTEXT: Dict[str, str] = {
    "Grand Forum":       "civic plaza, administrative architecture, formal paving, political space",
    "Guild Spires":      "guild tower base, professional district, guild insignia markings",
    "Archive Row":       "document storage, scroll vaults, scholar traffic patterns",
    "Diplomats Row":     "formal facades, neutral ground markers, secure meeting spaces",
    "Sanctum Quarter":   "sacred geometry in floor, divine architecture, protective wards",
    "Temple Row":        "multiple shrine entries, processional path, holy water fonts",
    "Academy Heights":   "scholarly campus, lecture halls, study gardens, experimental plots",
    "Cobbleway Market":  "dense market stalls, cobblestone, merchant carts, haggling spaces",
    "Floating Bazaar":   "platform structures, canal-adjacent, floating market stalls",
    "Neon Row":          "entertainment district, bright signage positions, crowd flow",
    "Night Pits":        "fighting pits, betting areas, underground entertainment",
    "Scrapworks":        "salvage yards, mechanical detritus, industrial aesthetic",
    "Artisan Quarter":   "craftwork studios, display windows, guild mark stations",
    "Markets Infinite":  "endless market, layered stall rows, maze-like alley grid",
    "Hearthstone District": "residential streets, housing blocks, community spaces",
    "Ember Ward":        "working class housing, communal kitchens, industrial proximity",
    "Outer Wall":        "defensive fortification, patrol routes, checkpoint positions",
    "Ironworks":         "heavy industry, smelting areas, factory floor plans",
    "The Warrens":       "improvised structures, salvaged materials, survival spaces",
}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower().strip()).strip("_")[:50]


def _detect_area_style(name: str, description: str) -> str:
    """Pick the best style tag from name + description keywords."""
    text = (name + " " + description).lower()
    # Check in priority order — more specific first
    for key in [
        "sewer", "cistern", "vault", "laboratory", "infirmary", "prison", "barracks",
        "forge", "workshop", "archive", "library", "guild", "temple", "shrine",
        "arena", "tavern", "inn", "manor", "noble", "tower", "rooftop",
        "warehouse", "dock", "alley", "canal", "crossroads", "street",
        "underground", "cave", "cavern", "ruin", "slum", "gate",
        "bazaar", "market", "plaza", "garden", "park", "office",
    ]:
        if key in text:
            return key
    return "street"


# ---------------------------------------------------------------------------
# Gazetteer loader — collects all areas to map
# ---------------------------------------------------------------------------

def _load_gazetteer() -> dict:
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT content_json FROM gazetteer LIMIT 1") or []
        if rows and rows[0].get("content_json"):
            cj = rows[0]["content_json"]
            return json.loads(cj) if isinstance(cj, str) else cj
    except Exception as e:
        logger.error(f"🗺️ area_map: gazetteer DB load failed: {e}")
    return {}


def collect_areas_to_map(gaz: dict) -> List[Dict]:
    """
    Returns a flat list of areas that should get overhead maps.
    Each entry: {district, area_name, description, file_path, slug_district, slug_area}
    Covers districts (one wide-view each) and every sub_area within them.
    """
    areas = []
    districts: dict = gaz.get("districts", {})

    for dist_name, dist_data in districts.items():
        slug_d = _slugify(dist_name)
        dist_desc = dist_data.get("description", "")

        # One overview map per district
        areas.append({
            "district":      dist_name,
            "area_name":     dist_name,
            "description":   dist_desc,
            "slug_district": slug_d,
            "slug_area":     "overview",
            "is_overview":   True,
        })

        # One map per sub_area
        for sub in dist_data.get("sub_areas", []):
            sub_name = sub.get("name", "")
            if not sub_name:
                continue
            # sub_areas sometimes have a nested list under "locations"
            sub_desc = sub.get("description", "") or ", ".join(sub.get("locations", []))
            areas.append({
                "district":      dist_name,
                "area_name":     sub_name,
                "description":   sub_desc,
                "slug_district": slug_d,
                "slug_area":     _slugify(sub_name),
                "is_overview":   False,
            })

    return areas


def list_area_maps() -> Dict[str, List[Dict]]:
    """Return {district_slug: [{area_slug, url, area_name}, ...]} for all existing PNGs."""
    result: Dict[str, List[Dict]] = {}
    if not AREA_MAPS_DIR.exists():
        return result
    for dist_dir in sorted(AREA_MAPS_DIR.iterdir()):
        if not dist_dir.is_dir():
            continue
        slug_d = dist_dir.name
        maps = []
        for png in sorted(dist_dir.glob("*.png")):
            maps.append({
                "area_slug": png.stem,
                "url":       f"/area-maps/{slug_d}/{png.name}",
                "area_name": png.stem.replace("_", " ").title(),
            })
        if maps:
            result[slug_d] = maps
    return result


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_area_prompt(area: Dict) -> Tuple[str, str]:
    dist_name  = area["district"]
    area_name  = area["area_name"]
    desc       = area.get("description", "")
    is_overview = area.get("is_overview", False)

    style_key    = _detect_area_style(area_name, desc)
    area_style   = _AREA_STYLES.get(style_key, _AREA_STYLES["street"])
    dist_context = _DISTRICT_CONTEXT.get(dist_name, "")

    base_style = _BASE_STYLE_INTERIOR if style_key in _INTERIOR_STYLES else _BASE_STYLE_TOWN
    scope = "wide district overview, neighbourhood-scale, multiple buildings" if is_overview else f"location: {area_name}"

    parts = [
        MAP_LORA,
        base_style,
        scope,
        area_style,
    ]
    if dist_context:
        parts.append(dist_context)

    # Pull strong visual nouns from the description
    if desc:
        visual_nouns = []
        for word in re.findall(r"\b[a-z]{4,}\b", desc.lower()):
            if word in {
                "stone", "wood", "metal", "water", "fire", "shadow", "light",
                "ancient", "ruined", "ornate", "carved", "arched", "vaulted",
                "narrow", "wide", "grand", "cramped", "dark", "bright",
                "cobblestone", "marble", "brick", "iron", "crystal",
            }:
                visual_nouns.append(word)
        if visual_nouns:
            parts.append(", ".join(dict.fromkeys(visual_nouns))[:80])

    return ", ".join(parts), _NEGATIVE


# ---------------------------------------------------------------------------
# A1111 call
# ---------------------------------------------------------------------------

async def _check_a1111() -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{A1111_URL}/sdapi/v1/sd-models")
            return r.status_code == 200
    except Exception:
        return False


async def _generate_one(area: Dict) -> Optional[Path]:
    """Generate a single area map and save it. Returns the path or None."""
    out_dir  = AREA_MAPS_DIR / area["slug_district"]
    out_path = out_dir / f"{area['slug_area']}.png"

    if out_path.exists():
        return None   # already done

    positive, negative = build_area_prompt(area)

    payload = {
        "prompt":          positive,
        "negative_prompt": negative,
        "width":           MAP_WIDTH,
        "height":          MAP_HEIGHT,
        "steps":           MAP_STEPS,
        "cfg_scale":       MAP_CFG,
        "sampler_name":    MAP_SAMPLER,
        "seed":            -1,
    }

    try:
        from src.resource_cop import wait_for_a1111_turn
        from src.news_feed import a1111_lock, _a1111_lock
        if _a1111_lock.locked():
            logger.info(f"🗺️ area_map: A1111 busy, waiting (area={area['area_name']})…")
        decision = await wait_for_a1111_turn("area_map", max_wait_seconds=60)
        if not decision.run_now:
            logger.info(f"area_map: A1111 busy, deferring {area['area_name']}: {decision.reason}")
            return None

        async with a1111_lock:
            async with httpx.AsyncClient(timeout=A1111_TIMEOUT) as client:
                resp = await client.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                resp.raise_for_status()
                data = resp.json()
    except Exception as e:
        logger.error(f"🗺️ area_map: A1111 request failed for {area['area_name']}: {e}")
        return None

    images = data.get("images", [])
    if not images:
        logger.error(f"🗺️ area_map: no images returned for {area['area_name']}")
        return None

    try:
        img_bytes = base64.b64decode(images[0])
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img_bytes)
        logger.info(f"🗺️ area_map: saved {out_path.relative_to(PROJECT_ROOT)} ({len(img_bytes):,} bytes)")
        return out_path
    except Exception as e:
        logger.error(f"🗺️ area_map: save failed for {area['area_name']}: {e}")
        return None


# ---------------------------------------------------------------------------
# Public batch entry point
# ---------------------------------------------------------------------------

async def generate_area_map_batch(batch_size: int = 4) -> int:
    """
    Generate up to batch_size overhead maps for areas that don't have one yet.
    Works through the gazetteer in order (overviews first, then sub-areas).
    Returns the count of maps successfully generated.
    """
    if not await _check_a1111():
        logger.warning("🗺️ area_map: A1111 unavailable — skipping batch")
        return 0

    gaz = _load_gazetteer()
    if not gaz:
        return 0

    all_areas  = collect_areas_to_map(gaz)
    missing    = [a for a in all_areas if not (AREA_MAPS_DIR / a["slug_district"] / f"{a['slug_area']}.png").exists()]
    batch      = missing[:batch_size]

    if not batch:
        logger.info("🗺️ area_map: all gazetteer areas already have maps")
        return 0

    logger.info(f"🗺️ area_map: generating {len(batch)} maps ({len(missing)} total missing)")
    generated = 0

    for area in batch:
        result = await _generate_one(area)
        if result:
            generated += 1
        # Brief pause between generations so VRAM can settle
        await asyncio.sleep(2)

    logger.info(f"🗺️ area_map: batch complete — {generated}/{len(batch)} maps generated")
    return generated
