"""
seed_battle_maps.py — DEPRECATED AI-generation path for VTT battle maps.

IMPORTANT: This script manages the OLD `battle_maps` DB table (AI-generated maps,
one slot per district+map_type). Production mission pipelines now use
`battle_maps_library` (downloaded r/battlemaps images) via src/battle_map_library.py.

Do NOT update this script expecting it to affect module map delivery.
Use scripts/download_battlemaps.py + scripts/analyze_battle_maps.py for the live path.

Legacy: For each district generates three standard map types:
  street     — outdoor street / plaza encounter (always)
  sewer      — underground tunnel / drainage encounter (always)
  <interior> — district-appropriate interior type (office, guild, temple, etc.)

Tracked in DB table `battle_maps` (NOT `battle_maps_library`).
DDB VTT upload is stubbed.

Usage:
  python scripts/seed_battle_maps.py                         # all pending maps
  python scripts/seed_battle_maps.py --dry-run               # list pending only
  python scripts/seed_battle_maps.py --district "Scrapworks" # one district
  python scripts/seed_battle_maps.py --types sewer,street    # specific types
  python scripts/seed_battle_maps.py --batch 10              # max 10 per run
  python scripts/seed_battle_maps.py --upload-only           # re-run DDB upload
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx

from src.log import logger

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

A1111_URL     = os.getenv("A1111_URL", "http://127.0.0.1:7860")
A1111_TIMEOUT = 300.0

MAP_WIDTH  = 1024
MAP_HEIGHT = 1024

# SDXL settings — Flux is non-functional on this A1111 build (returns blank images)
MAP_STEPS   = 35
MAP_CFG     = 4.0
MAP_SAMPLER = "DPM++ 2M Karras"

# mapcraft_sdxl_v1 + RealVisXL: confirmed working in diagnostic tests
MAP_LORA       = "<lora:mapcraft_sdxl_v1:0.85>"
MAP_TRIGGER    = "mapcraft."
MAP_CHECKPOINT = os.getenv("A1111_BATTLEMAP_CHECKPOINT", "RealVisXL_V4.0.safetensors")

GAZETTEER_PATH = ROOT / "campaign_docs" / "city_gazetteer.json"
BATTLE_MAPS_DIR = ROOT / "campaign_docs" / "battle_maps"
BATTLE_MAPS_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = ROOT / "logs" / "battle_maps.log"

# ---------------------------------------------------------------------------
# DB table
# ---------------------------------------------------------------------------

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS battle_maps (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    district        VARCHAR(120) NOT NULL,
    district_slug   VARCHAR(80)  NOT NULL,
    map_type        VARCHAR(40)  NOT NULL,
    file_path       VARCHAR(600),
    sd_prompt       TEXT,
    generated_at    DATETIME,
    ddb_asset_id    VARCHAR(120),
    ddb_asset_url   VARCHAR(500),
    uploaded_at     DATETIME,
    created_at      DATETIME DEFAULT NOW(),
    UNIQUE KEY uq_map (district_slug(60), map_type(30))
)
"""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Map type catalogue — prompts per environment type
# ---------------------------------------------------------------------------

_NEG = (
    "characters, people, tokens, miniatures, isometric, side view, perspective distortion, "
    "3d render, sky background, blurry, low quality, watermark, signature, text overlay, "
    "aerial photograph, AI artifacts, smeared texture, dreamlike distortion"
)

# Environment details with lighting and atmosphere baked in.
# These feed directly into Flux prompts — descriptive prose works better than keyword lists.
_ENV_DETAILS: dict[str, str] = {
    "street": (
        "Cobblestone street flanked by building facades, wide enough for open combat. "
        "Amber gas lanterns on iron posts cast warm overlapping pools of light. "
        "Market stalls and bollards as cover, drainage gutters along kerbs, "
        "a branching alley mouth mid-block, manhole covers in the road. "
        "Long soft shadows from building overhangs."
    ),
    "plaza": (
        "Wide stone plaza with a central monument or fountain as focal cover. "
        "Bright diffuse overhead light (dome glow) with crisp short shadows. "
        "Radiating paved paths, stone benches and planters at edges, "
        "low walls and carved pillars framing the space, "
        "stairs rising to building entrances on multiple sides."
    ),
    "sewer": (
        "Brick-vaulted sewer tunnel, two narrow stone walkways flanking a central water channel. "
        "Dim wall-bracket lanterns spaced far apart, orange flame reflections shimmering on black water. "
        "Iron grates, mossy dripping walls, pipe junctions overhead, "
        "support pillars casting long shadows, ambush alcoves cut into the brick. "
        "Deep darkness beyond the lit sections."
    ),
    "office": (
        "Open-plan office floor, rows of desks partitioned by low dividers as cover. "
        "Neon strip lights along ceiling edges cast blue-white light, "
        "individual desk panels glow with arcane holographic blue. "
        "Filing cabinets and server racks block sightlines, "
        "a glass-walled conference room at one end, "
        "circuit-panel wall insets, multiple doorways."
    ),
    "guild": (
        "Guild hall, central heavy oak meeting table as dominant obstacle. "
        "Warm overhead iron-and-crystal chandeliers casting golden light. "
        "Notice boards and trophy cases on walls, weapon racks in a training alcove, "
        "administrative desks as partial cover, wide double doors at entrance, "
        "staircase in corner, open central combat floor."
    ),
    "temple": (
        "Sacred hall, central altar on a raised dais radiating soft divine golden light. "
        "Stone pews in rows as cover, incense braziers at corners trailing smoke, "
        "prayer alcoves cut into thick walls, a sacred fountain glowing faintly blue, "
        "processional aisle running full length, flanking stone columns, "
        "candlelit side chapels in deep amber shadow."
    ),
    "archive": (
        "Scroll archive, tall shelving units forming a labyrinth of narrow reading aisles. "
        "Bright overhead arcane reading lamps on every aisle, warm amber desk lamps at tables, "
        "one restricted vault alcove behind a heavy iron door in near-darkness. "
        "Card catalogue cabinets, a winding iron staircase, overhead balcony railing visible."
    ),
    "library": (
        "Grand library, tall dark-wood bookshelves in parallel rows creating corridors. "
        "Warm fireplace light from a reading nook, afternoon light from high clerestory windows, "
        "individual reading lamp glow at central tables. "
        "Winding staircases between levels, open atrium at center with balcony rail, "
        "archive alcoves in deep shadow at edges."
    ),
    "tavern": (
        "Tavern common room, worn wooden plank floor, bar counter along one wall. "
        "Golden hearth firelight dominates — orange glow pools across the floor. "
        "Round tables and stools scattered as terrain, overhead iron lanterns, "
        "candles on each table, kitchen alcove behind bar, storage barrels stacked, "
        "small stage platform, booth seating along side walls."
    ),
    "inn": (
        "Inn floor plan, reception desk at entrance under a bright lantern. "
        "Warm hearth light in the common room fading to dim corridor lighting. "
        "Private room doors along corridor, staircase in corner, "
        "storage closets as terrain breaks, furniture clusters for tactical cover."
    ),
    "arena": (
        "Fighting arena, oval sand pit as the open combat floor. "
        "Bright arc-lamp or magical spotlight illumination from above, "
        "dramatic deep shadows beneath tiered stone spectator stands. "
        "Sand shows scuff marks and old blood stains. "
        "Gladiator entrance gates at opposite ends, weapon racks along outer wall, "
        "low barrier railing at the pit edge."
    ),
    "workshop": (
        "Crafting workshop, central workbench islands dominate the floor. "
        "Harsh industrial overhead lights plus individual work lamp pools on each bench. "
        "Tools on pegboard walls, a press or lathe at far end casting machine shadow, "
        "material bins as terrain, loading dock with bright exterior spill at one end. "
        "Machinery blocks sightlines down the central aisle."
    ),
    "forge": (
        "Forge room, the central forge and anvil glow intense orange-red. "
        "Heat-light from the forge fire illuminates everything — deep crimson on close surfaces, "
        "fading to amber and shadow at the walls. "
        "Cooling troughs flank the forge, coal bins and bellows at sides, "
        "tool racks on stone walls, elevated catwalk above, "
        "heavy chimney column rising from center. Metal stock piles as difficult terrain."
    ),
    "warehouse": (
        "Warehouse storage floor, massive crate stacks and tall shelving form terrain walls. "
        "Harsh industrial overhead strip lights, deep shadow corridors between stacks. "
        "Loading dock at one end bright with exterior light, "
        "support columns at regular intervals, forklift path marks worn into floor, "
        "mezzanine storage level with railing above."
    ),
    "barracks": (
        "Military barracks, bunk beds in rows as terrain blocks. "
        "Efficient overhead lighting, brighter over the central training mat. "
        "Weapon racks and armor stands between beds, officer desk at far end, "
        "mess table in one corner, armory alcove behind locked door, "
        "guard post with lantern at entrance."
    ),
    "prison": (
        "Cell block, cells in rows with heavy iron bars casting striped shadows. "
        "Harsh overhead lights in the central guard corridor, "
        "deep shadow inside each locked cell. "
        "Central guard station with lantern, interrogation room at one end under a bright hanging light, "
        "armory closet, thick stone walls defining all spaces."
    ),
    "alley": (
        "Narrow urban alley, one distant lantern at the entrance casting long shadows. "
        "Irregular cobblestones, recessed doorways as cover, crates and barrels stacked against walls, "
        "drainage gutter running down center, dead-end alcove at far side, "
        "salvaged pipe structures overhead. Deep ambient darkness."
    ),
    "bazaar": (
        "Open bazaar, vendor tent canopy frames casting coloured shadow patches. "
        "Warm afternoon light between stalls, lanterns beginning to glow for evening. "
        "Central statue or fountain as landmark cover, winding paths between stalls, "
        "scattered goods as difficult terrain, tent poles as obstacles, "
        "crates and barrels at stall backs."
    ),
    "market": (
        "Market street, stall frames on both sides forming a covered lane. "
        "Warm daylight filtering through awnings — striped amber and shadow patterns. "
        "Crates and display tables as cover, central open haggling space, "
        "cart-rut tracks worn in cobblestones, alley entrance mid-street, "
        "lamp posts at corners just beginning to flicker on."
    ),
    "rooftop": (
        "Flat rooftop surface under open dome-sky ambient light, no shadows from above. "
        "Chimney stacks as solid cover, water tower as major central obstacle, "
        "skylights as dangerous floor hazards, ventilation housings scattered, "
        "parapet edge with crenellations, rope bridge to adjacent roof, "
        "stairwell door access at one corner."
    ),
    "cave": (
        "Natural cave, organic rough stone walls with no right angles. "
        "Bioluminescent mushroom clusters cast blue-green pools of light. "
        "A crack in the ceiling lets in one pale shaft of dome-light. "
        "Deep darkness beyond the lit radius. Stalactite columns, underground pool, "
        "rope bridge over a chasm, rubble piles blocking shortcuts."
    ),
    "cistern": (
        "Underground cistern, large stone pillars rising from black water. "
        "Wall torches reflect orange on the water surface, pillars casting long shadows. "
        "Narrow stone walkways along edges and between pillars, pump mechanisms, "
        "overflow channels, iron access ladders, arched ceiling above."
    ),
    "manor": (
        "Manor interior, grand entry hall with split staircase under a chandelier. "
        "Warm chandelier light in formal rooms, fireplace glow in parlor and study, "
        "dim servant corridors. Long dining table as obstacle, "
        "parlor furniture clusters, bookshelves in study, multiple interior doors."
    ),
    "ruin": (
        "Collapsed ruins, pale dome-light shafts through collapsed ceiling sections. "
        "Dust motes visible in the light beams. No artificial light — just ambient glow. "
        "Massive rubble piles blocking paths, broken columns and partial walls as terrain, "
        "exposed foundations, scattered debris, improvised scavenger lean-tos in alcoves."
    ),
    "onsen": (
        "Hot spring bath house, large steaming mineral pool as the central impassable terrain. "
        "Warm amber paper-lantern light filtered through rising steam. "
        "Stone pool edges as walkways, mineral water glowing faint turquoise. "
        "Private bathing alcoves along walls, wooden changing screens as partial cover, "
        "low stone benches, drainage channels in floor, attendant desk near entrance."
    ),
}

# ---------------------------------------------------------------------------
# District → map type assignments
# ---------------------------------------------------------------------------

# Every district always gets these two types
UNIVERSAL_TYPES = ["street", "sewer"]

# Primary interior per district (slug → type from _ENV_DETAILS keys)
DISTRICT_INTERIOR: dict[str, str] = {
    "grand_forum":           "office",
    "guild_spires":          "guild",
    "archive_row":           "archive",
    "diplomats_row":         "office",
    "sanctum_quarter":       "temple",
    "temple_row":            "temple",
    "academy_heights":       "library",
    "cobbleway_market":      "market",
    "floating_bazaar":       "bazaar",
    "neon_row":              "tavern",
    "night_pits":            "arena",
    "scrapworks":            "workshop",
    "artisan_quarter":       "workshop",
    "markets_infinite":      "warehouse",
    "hearthstone_district":  "inn",
    "ember_ward":            "warehouse",
    "outer_wall":            "barracks",
    "ironworks":             "forge",
    "the_warrens":           "alley",
    # Districts added 2026-05-20
    "the_reliquary":         "archive",
    "cult_corners":          "temple",
    "coppergate":            "market",
    "ashfall_terraces":      "cave",
    "duskhollow":            "tavern",
    "collapsed_plaza":       "ruin",
    "the_fringe":            "cave",
}

# Additional optional extras per district (slug → extra type list)
DISTRICT_EXTRAS: dict[str, list[str]] = {
    "scrapworks":       ["rooftop", "warehouse"],
    "ironworks":        ["warehouse"],
    "night_pits":       ["prison"],
    "the_warrens":      ["rooftop"],
    "sanctum_quarter":  ["cistern"],
    "guild_spires":     ["rooftop"],
    "cobbleway_market": ["warehouse"],
    "floating_bazaar":  ["alley"],
    "archive_row":      ["cistern"],
    "outer_wall":       ["prison"],
    # Districts added 2026-05-20
    "the_reliquary":    ["cistern"],
    "cult_corners":     ["alley"],
    "coppergate":       ["tavern"],
    "ashfall_terraces": ["forge", "onsen"],
    "duskhollow":       ["alley"],
    "collapsed_plaza":  ["cave"],
    "shantytown_heights": ["rooftop"],
    "the_fringe":       ["alley"],
}

# Warren-type districts get cave/sewer/alley instead of the normal street+interior set.
# The Warrens are several distinct districts, not one.
WARREN_TYPES = ["sewer", "cave", "alley"]
WARREN_DISTRICTS = {"shantytown_heights"}

# District-level visual context injections (from area_map_generator.py)
_DISTRICT_CONTEXT: dict[str, str] = {
    "Grand Forum":          "civic architecture, formal paving stone, administrative grandeur",
    "Guild Spires":         "guild tower base, professional district, guild insignia carved into walls",
    "Archive Row":          "vaulted document storage, scroll vault aesthetics, scholar atmosphere",
    "Diplomats Row":        "formal neutral-ground aesthetics, secure meeting spaces, marble trim",
    "Sanctum Quarter":      "sacred geometry floor patterns, divine architecture, protective ward carvings",
    "Temple Row":           "multiple shrine entries, holy water fonts, divine iconography",
    "Academy Heights":      "scholarly campus aesthetic, experiment apparatus, academic trim",
    "Cobbleway Market":     "dense merchant stalls, cobblestone worn smooth, haggling atmosphere",
    "Floating Bazaar":      "canal-adjacent market, platform structures, floating trade post",
    "Neon Row":             "entertainment district, bright alchemical signage positions, crowd flow",
    "Night Pits":           "fighting pit aesthetic, underground entertainment, rough crowd barriers",
    "Scrapworks":           "salvage yard parts, mechanical detritus, industrial patina",
    "Artisan Quarter":      "craftwork guild studios, display windows, maker aesthetic",
    "Markets Infinite":     "endless layered market, maze-like commercial density",
    "Hearthstone District": "residential warmth, community space, worn household aesthetic",
    "Ember Ward":           "working class industrial proximity, soot staining, hard use",
    "Outer Wall":           "defensive fortification, patrol routes, checkpoint architecture",
    "Ironworks":            "heavy industrial, smelting residue, factory floor aesthetic",
    "The Warrens":          "improvised salvaged structures, survival space, tight corridors",
    "The Reliquary":        "sacred vault aesthetic, heavy ward carvings on walls, secure storage atmosphere",
    "Cult Corners":         "cult meeting hall iconography, minor faith shrines, Brother Thane's influence",
    "Coppergate":           "aspiring merchant district, copper coin motifs, small business storefronts",
    "Ashfall Terraces":     "volcanic slope construction, warm amber glow, ash-stained surfaces, lava tube access, Steeping Quarter mineral bath houses",
    "Duskhollow":           "perpetual shadow, dim lanterns, night market atmosphere, those who avoid light",
    "Shantytown Heights":   "vertical patchwork slum construction, rope bridges between levels, salvaged materials",
    "Collapsed Plaza":      "rift disaster aftermath, rubble and ruin, scavenger territory, dangerous instability",
    "The Fringe":           "last permanent habitation, frontier atmosphere, monitoring station aesthetic, unknown beyond",
}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower().strip()).strip("_")[:60]


def map_types_for_district(district_name: str) -> list[str]:
    """Return the full list of map types to generate for a district."""
    slug = _slugify(district_name)

    # Warren-type districts (slums, improvised structures) get cave-focused set
    if slug in WARREN_DISTRICTS:
        return list(dict.fromkeys(WARREN_TYPES + DISTRICT_EXTRAS.get(slug, [])))

    types = list(UNIVERSAL_TYPES)  # street, sewer

    interior = DISTRICT_INTERIOR.get(slug, "office")
    if interior not in types:
        types.append(interior)

    for extra in DISTRICT_EXTRAS.get(slug, []):
        if extra not in types:
            types.append(extra)

    return types


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_battle_map_prompt(district_name: str, map_type: str) -> tuple[str, str]:
    env_detail = _ENV_DETAILS.get(map_type, _ENV_DETAILS["street"])
    dist_ctx   = _DISTRICT_CONTEXT.get(district_name, "")

    prompt = (
        f"{MAP_LORA}, {MAP_TRIGGER} "
        "Illustrated top-down VTT battlemap, painted tabletop RPG map art style, "
        "rich detail, clearly readable from above. "
        f"{map_type.title()} location in the {district_name} district, "
        "fantasy cyberpunk underground city beneath a dome. "
        f"{env_detail} "
    )
    if dist_ctx:
        prompt += f"{dist_ctx}. "
    prompt += (
        "Thick walls clearly define all spaces. "
        "Every prop identifiable from above — chairs, barrels, desks, columns. "
        "Empty of all characters and tokens. Grid-compatible flat overhead view."
    )
    return prompt, _NEG


# ---------------------------------------------------------------------------
# Gazetteer loader + job collector
# ---------------------------------------------------------------------------

def _load_gazetteer() -> dict:
    try:
        return json.loads(GAZETTEER_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"[ERROR] Gazetteer load failed: {exc}")
        return {}


def collect_map_jobs(gaz: dict, district_filter: str = "", type_filter: list[str] | None = None) -> list[dict]:
    """
    Returns list of {district, district_slug, map_type, file_path, needs_generation}
    for every (district × map_type) combination.
    """
    jobs = []
    districts: dict = gaz.get("districts", {})

    for dist_name, dist_data in districts.items():
        if district_filter and district_filter.lower() not in dist_name.lower():
            continue
        slug = _slugify(dist_name)
        types = map_types_for_district(dist_name)
        if type_filter:
            types = [t for t in types if t in type_filter]

        for mtype in types:
            out_dir  = BATTLE_MAPS_DIR / slug
            out_path = out_dir / f"{mtype}.png"
            jobs.append({
                "district":      dist_name,
                "district_slug": slug,
                "map_type":      mtype,
                "file_path":     str(out_path),
                "exists":        out_path.exists(),
            })

    return jobs


# ---------------------------------------------------------------------------
# A1111 generation
# ---------------------------------------------------------------------------

async def _a1111_alive() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{A1111_URL}/sdapi/v1/sd-models")
            return r.status_code == 200
    except Exception:
        return False


async def _ensure_checkpoint() -> bool:
    """Pre-load MAP_CHECKPOINT if it isn't already active. Returns True when ready."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{A1111_URL}/sdapi/v1/options")
            current = r.json().get("sd_model_checkpoint", "")
        base = MAP_CHECKPOINT.split(".")[0].lower()
        if base in current.lower():
            log(f"  Checkpoint already loaded: {current}")
            return True
        log(f"  Loading checkpoint: {MAP_CHECKPOINT} (currently: {current}) ...")
        async with httpx.AsyncClient(timeout=300.0) as c:
            await c.post(f"{A1111_URL}/sdapi/v1/options",
                         json={"sd_model_checkpoint": MAP_CHECKPOINT})
        for _ in range(60):
            await asyncio.sleep(3)
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{A1111_URL}/sdapi/v1/options")
                loaded = r.json().get("sd_model_checkpoint", "")
                if base in loaded.lower():
                    log(f"  Checkpoint ready: {loaded}")
                    return True
        log(f"  WARNING: checkpoint swap timed out — proceeding anyway")
        return True
    except Exception as e:
        log(f"  ERROR ensuring checkpoint: {e}")
        return False


async def _flush_a1111_vram() -> bool:
    """Unload then reload the checkpoint to flush VRAM after an OOM crash.
    Returns True if A1111 comes back healthy."""
    log("  [VRAM] Unloading checkpoint to flush VRAM...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            await c.post(f"{A1111_URL}/sdapi/v1/unload-checkpoint")
    except Exception as e:
        log(f"  [VRAM] Unload failed (non-fatal): {e}")

    log("  [VRAM] Waiting 30s for VRAM to clear...")
    await asyncio.sleep(30)

    log("  [VRAM] Reloading checkpoint...")
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            await c.post(f"{A1111_URL}/sdapi/v1/reload-checkpoint")
    except Exception as e:
        log(f"  [VRAM] Reload failed: {e}")
        return False

    log("  [VRAM] Waiting 60s for model to be hot...")
    await asyncio.sleep(60)

    alive = await _a1111_alive()
    log(f"  [VRAM] A1111 {'responsive' if alive else 'still unresponsive'} after reload")
    return alive


async def _generate_map_image(prompt: str, neg: str) -> Optional[bytes]:
    payload = {
        "prompt":          prompt,
        "negative_prompt": neg,
        "width":           MAP_WIDTH,
        "height":          MAP_HEIGHT,
        "steps":           MAP_STEPS,
        "cfg_scale":       MAP_CFG,
        "sampler_name":    MAP_SAMPLER,
        "seed":            -1,
        "n_iter":          1,
        "batch_size":      1,
    }
    try:
        async with httpx.AsyncClient(timeout=A1111_TIMEOUT) as c:
            r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
            r.raise_for_status()
            images = r.json().get("images", [])
            if not images:
                return None
            return base64.b64decode(images[0])
    except Exception as exc:
        log(f"  [A1111] Error: {exc}")
        return None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_init() -> None:
    try:
        from src.db_api import raw_execute
        raw_execute(CREATE_TABLE)
    except Exception as exc:
        log(f"[DB] Init failed: {exc}")


def _db_mark_generated(district: str, district_slug: str, map_type: str, file_path: str, prompt: str) -> None:
    try:
        from src.db_api import raw_execute
        raw_execute(
            """INSERT INTO battle_maps (district, district_slug, map_type, file_path, sd_prompt, generated_at)
               VALUES (%s, %s, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE district=%s, file_path=%s, sd_prompt=%s, generated_at=NOW()""",
            (district, district_slug, map_type, file_path, prompt, district, file_path, prompt),
        )
    except Exception as exc:
        log(f"  [DB] Write failed: {exc}")


def _db_mark_uploaded(district_slug: str, map_type: str, asset_id: str, asset_url: str) -> None:
    try:
        from src.db_api import raw_execute
        raw_execute(
            """UPDATE battle_maps SET ddb_asset_id=%s, ddb_asset_url=%s, uploaded_at=NOW()
               WHERE district_slug=%s AND map_type=%s""",
            (asset_id, asset_url, district_slug, map_type),
        )
    except Exception as exc:
        log(f"  [DB] Upload mark failed: {exc}")


def _db_get_generated() -> list[dict]:
    """Return AI-generated maps not yet uploaded."""
    try:
        from src.db_api import raw_query
        return raw_query(
            "SELECT * FROM battle_maps WHERE file_path IS NOT NULL AND uploaded_at IS NULL ORDER BY district_slug, map_type"
        ) or []
    except Exception as exc:
        log(f"[DB] Query failed: {exc}")
        return []


def _db_get_library_pending() -> list[dict]:
    """Return downloaded library maps not yet uploaded to VTT."""
    try:
        from src.db_api import raw_query
        return raw_query(
            "SELECT id, file_path, map_type, reddit_score, reddit_title "
            "FROM battle_maps_library "
            "WHERE file_path IS NOT NULL AND vtt_uploaded_at IS NULL "
            "ORDER BY id"
        ) or []
    except Exception as exc:
        log(f"[DB] Library query failed: {exc}")
        return []


def _db_mark_library_uploaded(map_id: int, vtt_name: str, asset_id: str, asset_url: str) -> None:
    try:
        from src.db_api import raw_execute
        raw_execute(
            "UPDATE battle_maps_library SET vtt_asset_name=%s, vtt_asset_id=%s, vtt_asset_url=%s, vtt_uploaded_at=NOW() WHERE id=%s",
            (vtt_name, asset_id, asset_url, map_id),
        )
    except Exception as exc:
        log(f"  [DB] Library upload mark failed: {exc}")


def _db_upsert_district(district: str, district_slug: str) -> None:
    """Ensure district name is stored (for human-readable logs)."""
    try:
        from src.db_api import raw_execute
        raw_execute(
            "INSERT IGNORE INTO battle_maps (district, district_slug, map_type) VALUES (%s,%s,'__init__')"
            " ON DUPLICATE KEY UPDATE district=%s",
            (district, district_slug, district),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# DDB VTT upload
# ---------------------------------------------------------------------------

_DDB_GAME_ID     = os.getenv("DDB_GAME_ID", "6923222")
_DDB_USER_ID     = "123889713"
_DDB_COBALT_URL  = "https://auth-service.dndbeyond.com/v1/cobalt-token"
_DDB_GAME_URL    = f"https://www.dndbeyond.com/games/{_DDB_GAME_ID}"
_DDB_S3_BUCKET   = "h7ktnb-dndbeyond-feywild-maps-temp-live"
_DDB_S3_URL      = f"https://{_DDB_S3_BUCKET}.s3.amazonaws.com/"
# Next.js Server Action hash for map upload — update if DDB redeploys and uploads break
# Confirmed via CDP probe 2026-05-20: body [true,"6923222",123889713] → this hash → presigned S3 fields
_DDB_ACTION_HASH = "70be8a5bf79ce7e9f33c3fca47aad1a3688b174bbe"

_DDB_BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Origin":     "https://www.dndbeyond.com",
    "Referer":    f"https://www.dndbeyond.com/games/{_DDB_GAME_ID}",
}


def _ddb_session() -> str:
    return os.getenv("DDB_COBALT_SESSION", "")


async def _get_cobalt_token() -> str:
    """Fetch a fresh cobalt JWT (5 min TTL) using the long-lived CobaltSession cookie."""
    session = _ddb_session()
    if not session:
        log("  [DDB] DDB_COBALT_SESSION not set in .env")
        return ""
    try:
        async with httpx.AsyncClient(
            headers={**_DDB_BROWSER_UA, "Cookie": f"CobaltSession={session}"},
            timeout=15.0, follow_redirects=True,
        ) as c:
            r = await c.get(_DDB_COBALT_URL)
            r.raise_for_status()
            data = r.json()
            return data.get("token") or data.get("cobaltToken") or r.cookies.get("cobalt-token", "")
    except Exception as e:
        log(f"  [DDB] cobalt-token failed: {e}")
        return ""


async def _get_action_hash() -> str:
    """
    Fetch the current Server Action hash from the DDB games page JS bundle.
    The hash changes on every DDB deployment. Falls back to the hardcoded value.
    """
    try:
        async with httpx.AsyncClient(headers=_DDB_BROWSER_UA, timeout=15.0, follow_redirects=True) as c:
            r = await c.get(_DDB_GAME_URL)
            text = r.text
        import re as _re
        # Next.js embeds action IDs as 40-char hex strings in the RSC payload
        matches = _re.findall(r'"([0-9a-f]{40})"', text)
        # The upload action hash appears near "upload" or "map" context
        for i, m in enumerate(matches):
            ctx = text[text.find(m)-100:text.find(m)+50]
            if any(w in ctx.lower() for w in ["upload", "map", "presign"]):
                log(f"  [DDB] Found action hash: {m}")
                return m
        # Fall back to stored hash
        return _DDB_ACTION_HASH
    except Exception:
        return _DDB_ACTION_HASH


async def _get_presigned_fields(cobalt_token: str) -> Optional[dict]:
    """Call the DDB Server Action to get presigned S3 upload fields."""
    from urllib.parse import quote
    session = _ddb_session()
    cookies = f"CobaltSession={session}; cobalt-token={cobalt_token}"
    payload = f'[true,"{_DDB_GAME_ID}",{_DDB_USER_ID}]'

    # URL-encode the router state tree exactly as the browser sends it
    rstate_raw = (
        f'["",{{"children":[["campaignId","{_DDB_GAME_ID}","d",null],'
        f'{{"children":["__PAGE__",{{}},null,null,0]}},'
        f'null,null,0]}},null,null,16]'
    )
    rstate = quote(rstate_raw, safe="")

    action_hash = await _get_action_hash()

    try:
        async with httpx.AsyncClient(
            headers={
                **_DDB_BROWSER_UA,
                "Content-Type":           "text/plain;charset=UTF-8",
                "Accept":                 "text/x-component",
                "next-action":            action_hash,
                "next-router-state-tree": rstate,
                "Cookie":                 cookies,
            },
            timeout=30.0, follow_redirects=True,
        ) as c:
            r = await c.post(_DDB_GAME_URL, content=payload.encode())
            if r.status_code != 200:
                log(f"  [DDB] Server Action returned {r.status_code}: {r.text[:300]}")
                return None

        import re as _re
        # Find the presigned S3 fields object in the RSC wire response
        match = _re.search(r'\{[^{}]*"bucket"\s*:\s*"[^"]+"[^{}]*\}', r.text, _re.DOTALL)
        if not match:
            log(f"  [DDB] presigned fields not in response (hash={action_hash[:8]}..., {len(r.text)} bytes)")
            log(f"  [DDB] Response sample: {r.text[:400]}")
            return None
        return json.loads(match.group())
    except Exception as e:
        log(f"  [DDB] presigned fields failed: {e}")
        return None


async def _s3_post_upload(map_path: Path, vtt_name: str, fields: dict) -> bool:
    """POST the image to S3 with the presigned form fields."""
    ct = "image/jpeg" if map_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    form = {
        "Content-Type":          ct,
        "bucket":                fields.get("bucket", _DDB_S3_BUCKET),
        "X-Amz-Algorithm":       fields.get("X-Amz-Algorithm", fields.get("algorithm", "")),
        "X-Amz-Credential":      fields.get("X-Amz-Credential", fields.get("credential", "")),
        "X-Amz-Date":            fields.get("X-Amz-Date", fields.get("date", "")),
        "X-Amz-Security-Token":  fields.get("X-Amz-Security-Token", fields.get("security_token", "")),
        "key":                   fields.get("key", ""),
        "Policy":                fields.get("Policy", fields.get("policy", "")),
        "X-Amz-Signature":       fields.get("X-Amz-Signature", fields.get("signature", "")),
    }
    form = {k: v for k, v in form.items() if v}
    safe_name = vtt_name.replace(" ", "_").replace("#", "No") + map_path.suffix
    try:
        img = map_path.read_bytes()
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(_DDB_S3_URL, data=form, files={"file": (safe_name, img, ct)})
            if r.status_code in {200, 204}:
                return True
            log(f"  [DDB] S3 returned {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        log(f"  [DDB] S3 POST failed: {e}")
        return False


async def _upload_to_ddb_vtt(map_path: Path, vtt_name: str) -> Optional[str]:
    """
    Upload a map to DDB VTT, naming it vtt_name (e.g. "Map #42").

    Flow:
      1. Fetch fresh cobalt token via DDB_COBALT_SESSION cookie
      2. POST /games/{id} Server Action → presigned S3 form fields
      3. POST to S3 with presigned fields + file

    Requires DDB_COBALT_SESSION in .env (long-lived, ~6 months).
    _DDB_ACTION_HASH may need updating if DDB redeploys.
    """
    cobalt = await _get_cobalt_token()
    if not cobalt:
        return None
    fields = await _get_presigned_fields(cobalt)
    if not fields:
        return None
    s3_key = fields.get("key", "")
    if not await _s3_post_upload(map_path, vtt_name, fields):
        return None
    asset_url = f"https://h7ktnb-dndbeyond-feywild-maps-live.s3.us-east-1.amazonaws.com/user/{_DDB_USER_ID}/maps/{s3_key}"
    log(f"  [DDB] OK '{vtt_name}' key={s3_key}")
    return asset_url


# ---------------------------------------------------------------------------
# Main passes
# ---------------------------------------------------------------------------

async def run_generation_pass(
    gaz: dict,
    district_filter: str = "",
    type_filter: list[str] | None = None,
    batch: int | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Generate missing battle maps. Returns (ok, fail)."""
    jobs = collect_map_jobs(gaz, district_filter, type_filter)
    pending = [j for j in jobs if not j["exists"]]

    log(f"\n{'='*60}")
    mode = "DRY RUN - " if dry_run else ""
    total_j = len(jobs)
    log(f"  {mode}Battle Map Generation  ({len(pending)} pending of {total_j} total)")
    log(f"{'='*60}")

    if not pending:
        log("  All maps already generated.")
        return 0, 0

    if batch:
        pending = pending[:batch]
        log(f"  Batch limit: {batch} maps")

    if dry_run:
        for j in pending:
            log(f"  WOULD GENERATE: {j['district']} / {j['map_type']}")
        return len(pending), 0

    if not await _a1111_alive():
        log("[ERROR] A1111 is not running — cannot generate maps")
        return 0, len(pending)

    await _ensure_checkpoint()

    VRAM_FLUSH_EVERY = 10   # flush VRAM every N successful maps
    MAX_CONSECUTIVE_FAILS = 5
    ok = fail = consecutive_fails = 0
    for i, j in enumerate(pending, 1):
        district = j["district"]
        slug     = j["district_slug"]
        mtype    = j["map_type"]
        out_path = Path(j["file_path"])
        log(f"[{i:03d}/{len(pending)}] {district} / {mtype}")

        prompt, neg = build_battle_map_prompt(district, mtype)
        log(f"  Prompt: {prompt[:120]}…")

        img_bytes = await _generate_map_image(prompt, neg)
        if not img_bytes:
            log(f"  FAIL: no image returned")
            fail += 1
            consecutive_fails += 1
            if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                log(f"  ABORT: {consecutive_fails} consecutive failures — A1111 appears crashed. Restart it and re-run.")
                break
            await asyncio.sleep(2)
            continue

        consecutive_fails = 0
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img_bytes)
        kb = len(img_bytes) // 1024
        log(f"  OK ({kb}KB) -> {out_path.relative_to(ROOT)}")

        _db_mark_generated(district, slug, mtype, str(out_path), prompt)
        ok += 1

        if ok % VRAM_FLUSH_EVERY == 0:
            log(f"  [VRAM] {ok} maps done — flushing VRAM before continuing...")
            await _flush_a1111_vram()

        await asyncio.sleep(2)

    log(f"\nGeneration done: {ok} OK, {fail} failed.")
    return ok, fail


async def run_upload_pass(
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Upload pending downloaded maps to DDB VTT, named "Map #ID".

    Maps are in: campaign_docs/battle_maps/_downloaded/<type>/
    VTT name format: Map #42
    """
    pending = _db_get_library_pending()

    log(f"\n{'='*60}")
    mode = "DRY RUN - " if dry_run else ""
    log(f"  {mode}DDB VTT Upload  ({len(pending)} pending)")
    log(f"  Location: campaign_docs/battle_maps/_downloaded/<type>/")
    log(f"{'='*60}")

    if not pending:
        log("  No maps pending upload.")
        return 0, 0

    ok = fail = 0
    for i, row in enumerate(pending, 1):
        map_id   = row["id"]
        vtt_name = f"Map #{map_id}"
        path     = Path(row["file_path"])
        mtype    = row["map_type"]
        score    = row.get("reddit_score", 0)
        log(f"[{i:04d}/{len(pending)}] {vtt_name}  [{mtype}]  score={score}  {path.name}")

        if dry_run:
            log(f"  DRY RUN: would upload as '{vtt_name}'")
            ok += 1
            continue

        if not path.exists():
            log(f"  SKIP: file missing at {path}")
            fail += 1
            continue

        asset_url = await _upload_to_ddb_vtt(path, vtt_name)
        if asset_url:
            _db_mark_library_uploaded(map_id, vtt_name, "", asset_url)
            log(f"  OK -> {asset_url}")
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(1)

    log(f"\nUpload done: {ok} OK, {fail} failed.")
    return ok, fail


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def print_status(gaz: dict) -> None:
    jobs = collect_map_jobs(gaz)
    by_district: dict[str, dict] = {}
    for j in jobs:
        d = j["district"]
        if d not in by_district:
            by_district[d] = {"total": 0, "done": 0}
        by_district[d]["total"] += 1
        if j["exists"]:
            by_district[d]["done"] += 1

    total = sum(v["total"] for v in by_district.values())
    done  = sum(v["done"]  for v in by_district.values())
    log(f"\n  Battle Map Status: {done}/{total} generated\n")

    for district, counts in sorted(by_district.items()):
        bar = "#" * counts["done"] + "." * (counts["total"] - counts["done"])
        log(f"  {district:<28} {counts['done']:2}/{counts['total']:2}  {bar}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate and track reusable VTT battle maps for gazetteer districts."
    )
    p.add_argument("--dry-run",      action="store_true", help="List pending work without generating.")
    p.add_argument("--district",     default="",          help="Filter to a specific district (partial match).")
    p.add_argument("--types",        default="",          help="Comma-separated map types to generate (e.g. sewer,street).")
    p.add_argument("--batch",        type=int, default=0, help="Max maps to generate per run.")
    p.add_argument("--upload-only",  action="store_true", help="Skip generation; only run DDB VTT upload pass.")
    p.add_argument("--status",       action="store_true", help="Print status table and exit.")
    return p.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    type_filter = [t.strip() for t in args.types.split(",") if t.strip()] or None
    batch = args.batch or None

    _db_init()
    gaz = _load_gazetteer()
    if not gaz:
        log("[ERROR] Could not load gazetteer — aborting")
        return

    if args.status:
        print_status(gaz)
        return

    if not args.upload_only:
        await run_generation_pass(
            gaz,
            district_filter=args.district,
            type_filter=type_filter,
            batch=batch,
            dry_run=args.dry_run,
        )

    await run_upload_pass(dry_run=args.dry_run)

    log("\nAll done.")


if __name__ == "__main__":
    asyncio.run(main())
