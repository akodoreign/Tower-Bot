"""
src/area_places.py — LLM-driven sub-area generation for Undercity districts.

Pulls existing places + area profile from DB, feeds them to ProAuthorAgent,
and inserts new named locations (taverns, shops, sightseeing, hidden spots,
guild halls, clinics, etc.) into gazetteer_places via raw_execute.

DB is authoritative — all reads/writes go through db_api.
Tower of Last Chance is excluded from generation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from src.db_api import raw_query, raw_execute

logger = logging.getLogger(__name__)

BANNED_DISTRICTS = {"Tower of Last Chance"}

# place_type enum values that exist in gazetteer_places
_PLACE_TYPE_MAP = {
    "tavern":        "small_shop",
    "inn":           "small_shop",
    "pub":           "small_shop",
    "bar":           "small_shop",
    "shop":          "small_shop",
    "service":       "small_shop",
    "clinic":        "small_shop",
    "apothecary":    "small_shop",
    "bakery":        "small_shop",
    "smithy":        "small_shop",
    "guild":         "place_of_interest",
    "landmark":      "place_of_interest",
    "attraction":    "place_of_interest",
    "sightseeing":   "place_of_interest",
    "shrine":        "place_of_interest",
    "monument":      "place_of_interest",
    "theater":       "place_of_interest",
    "arena":         "place_of_interest",
    "office":        "place_of_interest",
    "hideout":       "place_of_interest",
    "plaza":         "park",
    "garden":        "park",
    "square":        "park",
    "park":          "park",
    "courtyard":     "park",
    "market":        "mall",
    "bazaar":        "mall",
    "exchange":      "mall",
    "arcade":        "mall",
}

def _infer_place_type(type_tag: str) -> str:
    return _PLACE_TYPE_MAP.get(type_tag.lower(), "place_of_interest")


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _get_district_meta(district: str) -> dict:
    """Pull ring, danger_level, faction_presence from gazetteer table."""
    rows = raw_query("SELECT content_json FROM gazetteer LIMIT 1")
    if not rows:
        return {}
    gaz = rows[0]["content_json"]
    if isinstance(gaz, str):
        gaz = json.loads(gaz)
    return gaz.get("districts", {}).get(district, {})


def _get_existing_names(district: str) -> set[str]:
    """All currently known place names in this district (for dedup)."""
    rows = raw_query(
        "SELECT name FROM gazetteer_places WHERE district = %s",
        (district,),
    ) or []
    return {r["name"].lower() for r in rows}


def _get_area_profile(district: str) -> Optional[dict]:
    try:
        rows = raw_query(
            "SELECT profile_json FROM area_profiles WHERE district = %s LIMIT 1",
            (district,),
        )
        if not rows or not rows[0]["profile_json"]:
            return None
        pj = rows[0]["profile_json"]
        return json.loads(pj) if isinstance(pj, str) else pj
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_places_prompt(district: str, count: int) -> str:
    meta    = _get_district_meta(district)
    profile = _get_area_profile(district)
    existing = _get_existing_names(district)

    ring        = meta.get("ring", "?")
    danger      = meta.get("danger_level", "moderate")
    desc        = meta.get("description", "")[:300]
    factions    = meta.get("faction_presence", [])
    faction_str = ", ".join(factions) if factions else "independent"

    existing_block = ""
    if existing:
        sample = sorted(list(existing))[:20]
        existing_block = (
            "\nALREADY EXISTS — do NOT create places with these names:\n"
            + "\n".join(f"  - {n}" for n in sample)
            + ("\n  (and more…)" if len(existing) > 20 else "")
        )

    atm_block = ""
    if profile:
        atm  = profile.get("atmosphere", "")[:250]
        char = profile.get("character", "")[:150]
        if atm:
            atm_block = f"\nDISTRICT FEEL:\n{atm}\n{char}"

    return f"""You are a master world-builder for a dark fantasy D&D 5e campaign set in the Undercity — a massive sealed city under a dome, billions of people, real weather, layered social strata. This is NOT underground. It is a living city.

You are generating new named locations for the **{district}** district.

DISTRICT DATA:
  Ring: {ring}
  Danger level: {danger}
  Description: {desc}
  Faction presence: {faction_str}
{atm_block}
{existing_block}

Generate exactly {count} NEW named locations. Be creative and specific — invent names, quirks, and DM-useful details. Mix the mundane with the strange. Allowed types:

  tavern, inn, pub — drinking/lodging establishments
  shop, bakery, smithy, clinic, apothecary, service — small businesses
  guild, theater, arena, shrine, monument, office — places of interest
  hideout, attraction, sightseeing — unusual or notable spots
  plaza, garden, square, courtyard — open spaces
  market, bazaar, arcade, exchange — commercial areas

Output ONLY valid JSON array (no markdown fences):
[
  {{
    "name": "The Salted Hook",
    "type_tag": "tavern",
    "description": "A narrow taphouse known for its eel stew and the chalk wall where regulars leave coded messages for Patchwork Saints runners.",
    "notable_features": ["chalk message wall", "trap door to smuggler's passage"],
    "dnd_relevance": "DC 13 Insight reveals the chalk code; Patchwork Saints contacts can be made here",
    "price_tier": "cheap"
  }},
  ...
]

Rules:
- Every entry needs name, type_tag, description (2 sentences max), notable_features (list), dnd_relevance (1 sentence)
- price_tier (cheap/moderate/expensive/exclusive) only required for commercial places — omit for parks/plazas/monuments
- Names must be specific and evocative — no generic "The Tavern" or "The Shop"
- Do NOT invent named NPCs not already in the world — reference faction types instead ("a Patchwork Saints runner", "an Iron Fang enforcer")
- Descriptions should feel grounded: smells, sounds, specific details
"""


# ---------------------------------------------------------------------------
# Parser + DB insertion
# ---------------------------------------------------------------------------

def _parse_places(raw: str) -> list[dict]:
    text = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start = text.find("[")
    end   = text.rfind("]") + 1
    if start == -1 or end == 0:
        return []
    try:
        items = json.loads(text[start:end])
        return [i for i in items if i.get("name") and i.get("type_tag")]
    except Exception as e:
        logger.warning(f"[AreaPlaces] JSON parse failed: {e}")
        return []


def _insert_places(district: str, places: list[dict]) -> int:
    inserted = 0
    for p in places:
        name     = p.get("name", "").strip()
        type_tag = p.get("type_tag", "attraction").lower()
        desc     = p.get("description", "")[:500]
        place_type = _infer_place_type(type_tag)

        extra = {}
        for k in ("notable_features", "dnd_relevance", "price_tier"):
            if k in p:
                extra[k] = p[k]

        try:
            raw_execute(
                "INSERT IGNORE INTO gazetteer_places"
                " (district, place_type, name, type_tag, description, extra_json)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    district,
                    place_type,
                    name,
                    type_tag,
                    desc,
                    json.dumps(extra) if extra else None,
                ),
            )
            inserted += 1
        except Exception as e:
            logger.warning(f"[AreaPlaces] Insert failed for '{name}': {e}")
    return inserted


# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------

async def generate_places_for_district(
    district: str,
    count: int = 7,
    force: bool = False,
) -> int:
    """
    Generate and insert `count` new sub-areas for a district.
    Returns number of rows actually inserted.
    """
    if district in BANNED_DISTRICTS:
        logger.info(f"[AreaPlaces] Skipping banned district: {district}")
        return 0

    if not force:
        # Skip if district already has a lot of AI-generated places
        existing = raw_query(
            "SELECT COUNT(*) as cnt FROM gazetteer_places WHERE district = %s",
            (district,),
        )
        existing_cnt = existing[0]["cnt"] if existing else 0
        if existing_cnt >= 20:
            logger.info(f"[AreaPlaces] {district} already has {existing_cnt} places — skipping")
            return 0

    prompt = _build_places_prompt(district, count)

    try:
        import os as _os
        from src.ollama_queue import call_ollama
        _model = _os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
        _resp = await call_ollama(
            payload={
                "model": _model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "num_predict": 2048,
                    "num_ctx": int(_os.getenv("OLLAMA_AGENT_CTX", "12288")),
                    "think": True,
                    "temperature": 0.8,
                },
            },
            timeout=300.0,
            caller=f"area_places_{district[:20]}",
            force=True,
        )
        _content = ""
        if isinstance(_resp, dict):
            _msg = _resp.get("message", {})
            _content = (_msg.get("content", "") if isinstance(_msg, dict) else "").strip()
        if not _content:
            logger.warning(f"[AreaPlaces] No content for {district}")
            return 0
        places = _parse_places(_content)
        if not places:
            logger.warning(f"[AreaPlaces] Parsed 0 places for {district}. Preview: {_content[:200]!r}")
            return 0
        inserted = _insert_places(district, places)
        logger.info(f"[AreaPlaces] {district}: inserted {inserted}/{len(places)} places")
        return inserted
    except Exception as e:
        logger.error(f"[AreaPlaces] Error for {district}: {e}", exc_info=True)
        return 0


async def generate_all_new_areas(
    count_per_district: int = 7,
    force: bool = False,
    progress_callback=None,
) -> dict:
    """
    Run place generation across all districts (except banned ones).
    Returns stats dict.
    """
    district_rows = raw_query(
        "SELECT DISTINCT district FROM gazetteer_places ORDER BY district"
    ) or []
    # Also include districts known only from the gazetteer JSON
    try:
        gaz_rows = raw_query("SELECT content_json FROM gazetteer LIMIT 1")
        if gaz_rows:
            gaz = gaz_rows[0]["content_json"]
            if isinstance(gaz, str):
                gaz = json.loads(gaz)
            for dn in gaz.get("districts", {}).keys():
                if dn not in BANNED_DISTRICTS:
                    if not any(r["district"] == dn for r in district_rows):
                        district_rows.append({"district": dn})
    except Exception:
        pass

    districts = [r["district"] for r in district_rows if r["district"] not in BANNED_DISTRICTS]
    total = len(districts)
    total_inserted = 0
    skipped = 0
    failed  = 0

    for district in districts:
        n = await generate_places_for_district(district, count=count_per_district, force=force)
        if n == 0:
            skipped += 1
        elif n < 0:
            failed += 1
        else:
            total_inserted += n

        if progress_callback:
            await progress_callback(district, total_inserted, total)

        await asyncio.sleep(1)

    return {
        "total_districts": total,
        "total_inserted": total_inserted,
        "skipped": skipped,
        "failed": failed,
    }
