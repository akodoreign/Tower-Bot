"""
src/area_generator.py — District area profile generator.

Pulls rich DB context for each Undercity district and uses ProAuthorAgent to
generate a living world profile (atmosphere, secrets, threats, hooks, map prompt).
Profiles persist in the `area_profiles` table; overview maps in `image_refs`
(entity_type='area_map') so they're never duplicated.

The mission builder reads area profiles to ground new missions in existing lore
rather than inventing the district from scratch each time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.db_api import raw_query, raw_execute

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table bootstrap
# ---------------------------------------------------------------------------

def _ensure_table() -> None:
    raw_execute(
        "CREATE TABLE IF NOT EXISTS area_profiles ("
        "  id INT AUTO_INCREMENT PRIMARY KEY,"
        "  district VARCHAR(200) NOT NULL UNIQUE,"
        "  profile_json JSON,"
        "  generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        ")"
    )


# ---------------------------------------------------------------------------
# Map type inference
# ---------------------------------------------------------------------------

_MAP_TYPE_HINTS: dict[str, str] = {
    "floating bazaar":      "outdoor",
    "night pits":           "dungeon",
    "cult corners":         "dungeon",
    "collapsed plaza":      "outdoor",
    "archive row":          "interior",
    "ironworks":            "interior",
    "scrapworks":           "outdoor",
    "cobbleway market":     "outdoor",
    "markets infinite":     "outdoor",
    "duskhollow":           "outdoor",
    "the fringe":           "outdoor",
    "shantytown heights":   "outdoor",
    "ember ward":           "outdoor",
    "outer wall":           "outdoor",
    "ashfall terraces":     "outdoor",
    "the reliquary":        "interior",
    "sanctum quarter":      "interior",
    "academy heights":      "outdoor",
    "guild spires":         "outdoor",
    "grand forum":          "outdoor",
    "temple row":           "outdoor",
    "neon row":             "outdoor",
    "diplomats row":        "outdoor",
    "hearthstone district": "outdoor",
    "artisan quarter":      "outdoor",
    "coppergate":           "outdoor",
    "tower of last chance": "outdoor",
}


def _infer_map_type(district: str) -> str:
    return _MAP_TYPE_HINTS.get(district.lower(), "outdoor")


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------

def _gather_district_context(district: str) -> dict:
    """Pull all relevant DB data for a district into a context dict."""
    ctx: dict = {"district": district}

    # Named places
    places = raw_query(
        "SELECT place_type, name, type_tag, description, extra_json"
        " FROM gazetteer_places WHERE district = %s ORDER BY place_type, name",
        (district,),
    ) or []
    ctx["places"] = [
        {
            "name": p["name"],
            "place_type": p["place_type"],
            "tag": p["type_tag"] or "",
            "description": (p["description"] or "")[:200],
            "extra": json.loads(p["extra_json"]) if p["extra_json"] else {},
        }
        for p in places
    ]

    # NPCs whose location text mentions this district
    npc_rows = raw_query(
        "SELECT name, npc_faction, data_json FROM npcs"
        " WHERE status IN ('alive','injured','undead','doppelganger')"
        " AND data_json->'$.location' LIKE %s",
        (f"%{district}%",),
    ) or []
    ctx["npcs"] = []
    for nr in npc_rows:
        dj = json.loads(nr["data_json"]) if nr.get("data_json") else {}
        ctx["npcs"].append({
            "name": nr["name"],
            "faction": nr.get("npc_faction") or dj.get("faction", ""),
            "role": dj.get("role", ""),
            "motivation": dj.get("motivation", "")[:120],
            "location_note": (dj.get("location", ""))[:150],
        })

    # Recent news mentioning this district
    news_rows = raw_query(
        "SELECT headline, body FROM news_entries"
        " WHERE headline LIKE %s OR body LIKE %s"
        " ORDER BY posted_at DESC LIMIT 6",
        (f"%{district}%", f"%{district}%"),
    ) or []
    ctx["recent_news"] = [
        {"headline": n["headline"], "excerpt": (n["body"] or "")[:200]}
        for n in news_rows
    ]

    # Active + recently completed missions touching this district
    mission_rows = raw_query(
        "SELECT title, tier, faction, mission_json FROM missions"
        " WHERE (mission_json->'$.location' LIKE %s OR title LIKE %s)"
        "   AND status IN ('active','claimed','completed')"
        " ORDER BY created_at DESC LIMIT 5",
        (f"%{district}%", f"%{district}%"),
    ) or []
    ctx["missions"] = []
    for mr in mission_rows:
        mj = json.loads(mr["mission_json"]) if mr.get("mission_json") else {}
        ctx["missions"].append({
            "title": mr["title"],
            "type": mj.get("type", ""),
            "tier": mr.get("tier", ""),
            "faction": mr.get("faction", ""),
            "synopsis": mj.get("synopsis", mj.get("description", ""))[:200],
        })

    # Faction presence in this district
    faction_names = list({n["faction"] for n in ctx["npcs"] if n["faction"]})
    faction_rows = raw_query(
        "SELECT faction_name, tier, reputation_score FROM faction_reputation"
        " WHERE faction_name IN ({})".format(
            ",".join(["%s"] * len(faction_names))
        ),
        tuple(faction_names),
    ) if faction_names else []
    ctx["factions"] = [
        {"name": f["faction_name"], "tier": f["tier"], "score": f["reputation_score"]}
        for f in (faction_rows or [])
    ]

    # Check for existing area map in image_refs
    map_row = raw_query(
        "SELECT image_path FROM image_refs WHERE entity_type='area_map' AND entity_name=%s LIMIT 1",
        (district,),
    )
    ctx["existing_map"] = map_row[0]["image_path"] if map_row else None

    return ctx


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_area_prompt(ctx: dict) -> str:
    district = ctx["district"]

    places_block = ""
    for p in ctx["places"]:
        line = f"  - {p['name']} ({p['place_type']}"
        if p["tag"]:
            line += f", {p['tag']}"
        line += ")"
        if p["description"]:
            line += f": {p['description']}"
        places_block += line + "\n"

    npcs_block = ""
    for n in ctx["npcs"]:
        npcs_block += f"  - {n['name']} [{n['faction']}]: {n['location_note']}\n"

    news_block = ""
    for i, ne in enumerate(ctx["recent_news"], 1):
        news_block += f"  {i}. {ne['headline']}\n"
        if ne["excerpt"]:
            news_block += f"     {ne['excerpt'][:160]}\n"

    missions_block = ""
    for m in ctx["missions"]:
        missions_block += f"  - [{m['type']} / {m['tier']}] {m['title']}"
        if m["faction"]:
            missions_block += f" (faction: {m['faction']})"
        missions_block += "\n"
        if m["synopsis"]:
            missions_block += f"    {m['synopsis'][:160]}\n"

    factions_block = ""
    for f in ctx["factions"]:
        factions_block += f"  - {f['name']} ({f['tier']}, score {f['score']})\n"

    return f"""You are a master world-builder for a dark fantasy D&D 5e campaign set in an enormous domed city called the Undercity — billions of people, artificial sky, a massive Tower at the center, real weather under the dome. This is NOT underground tunnels. It is a living city with markets, politics, crime, wonder, and horror layered on top of each other.

You are writing the definitive area profile for the **{district}** district. Use all the data below as ground truth — this is what already exists in the world. Your job is to synthesize it into a vivid, usable profile.

═══════════════════════════════════
NAMED LOCATIONS IN {district.upper()}
═══════════════════════════════════
{places_block or '  (none catalogued)'}

═══════════════════════════════════
KNOWN NPCS OPERATING HERE
═══════════════════════════════════
{npcs_block or '  (none on record)'}

═══════════════════════════════════
FACTION PRESENCE
═══════════════════════════════════
{factions_block or '  (none confirmed)'}

═══════════════════════════════════
RECENT NEWS TOUCHING THIS DISTRICT
═══════════════════════════════════
{news_block or '  (no recent events)'}

═══════════════════════════════════
MISSIONS SET HERE (RECENT)
═══════════════════════════════════
{missions_block or '  (none on record)'}

═══════════════════════════════════
YOUR OUTPUT
═══════════════════════════════════
Write a living area profile in this EXACT JSON format (no markdown fences, no extra keys):

{{
  "atmosphere": "2-4 sentence description of what it FEELS like to be here — sensory details, time-of-day character, the undercurrent of tension or wonder",
  "character": "1-2 sentences on who lives/works here and why — the social fabric",
  "key_features": ["feature 1", "feature 2", "feature 3", "feature 4"],
  "hidden_secrets": ["secret that players could discover", "a second secret", "optional third"],
  "active_threats": ["ongoing threat or tension", "a second one"],
  "dm_hooks": ["adventure hook idea", "second hook", "third hook"],
  "sub_locations": [
    {{
      "name": "area name (dungeon, sewer, hidden room, rooftop, alley, etc.)",
      "type": "dungeon|interior|outdoor|cave",
      "description": "1 sentence",
      "sd_prompt": "50-70 word A1111 top-down map prompt, terrain only, no people",
      "ascii_grid": "16-20 col × 10-14 row ASCII layout using: # wall, . floor, ~ water, T tree, D door, S stairs, o light, + pillar, G grass, R road, ^ high terrain, = bridge, X hazard"
    }}
  ],
  "overview_map_type": "{_infer_map_type(district)}",
  "overview_sd_prompt": "60-80 word A1111 top-down district overview map prompt — streets, building silhouettes, key landmarks visible, no people, dark fantasy city",
  "overview_ascii_grid": "20-26 col × 14-18 row ASCII district overview layout, same key as above"
}}

Rules:
- Every field must be present
- sub_locations: 2-4 entries (can be sewers, basements, rooftops, hidden chambers, back alleys — areas that would need their own map)
- sd_prompts and ascii_grids describe only terrain/architecture/layout — never characters or people
- ascii_grid rows are joined with \\n inside the JSON string
- Secrets and hooks should feel grounded in the data above, not generic
- DO NOT invent named NPCs that weren't listed above
"""


# ---------------------------------------------------------------------------
# Profile parser
# ---------------------------------------------------------------------------

def _parse_profile(raw: str) -> Optional[dict]:
    text = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    # Strip any leading/trailing prose
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        return json.loads(text[start:end])
    except Exception as e:
        logger.warning(f"[AreaGen] JSON parse failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------

async def generate_area_profile(district: str, force: bool = False) -> Optional[dict]:
    """
    Generate and save an area profile for one district.
    Returns the profile dict, or None on failure.
    Skips generation if profile already exists and force=False.
    """
    _ensure_table()

    if not force:
        existing = raw_query(
            "SELECT profile_json FROM area_profiles WHERE district = %s",
            (district,),
        )
        if existing and existing[0]["profile_json"]:
            return json.loads(existing[0]["profile_json"]) if isinstance(existing[0]["profile_json"], str) else existing[0]["profile_json"]

    ctx = _gather_district_context(district)
    prompt = _build_area_prompt(ctx)

    profile: Optional[dict] = None
    try:
        from src.ollama_queue import call_ollama
        _model = __import__("os").getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
        _resp = await call_ollama(
            payload={
                "model": _model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "num_predict": 8192,   # think:True burns tokens — need room for full JSON
                    "num_ctx": int(__import__("os").getenv("OLLAMA_AGENT_CTX", "16384")),
                    "think": True,
                    "temperature": 0.75,
                },
            },
            timeout=300.0,
            caller=f"area_gen_{district[:20]}",
            force=True,
        )
        _content = ""
        if isinstance(_resp, dict):
            _msg = _resp.get("message", {})
            _content = (_msg.get("content", "") if isinstance(_msg, dict) else "").strip()
        if _content:
            profile = _parse_profile(_content)
        if not _content:
            logger.error(f"[AreaGen] {district}: empty response from Ollama (check think/num_predict)")
            return None
        if not profile:
            logger.warning(
                f"[AreaGen] {district}: response received ({len(_content)} chars) but JSON parse failed. "
                f"Preview: {_content[:300]!r}"
            )
            return None
    except Exception as e:
        logger.error(f"[AreaGen] Generation error for {district}: {type(e).__name__}: {e}", exc_info=True)
        return None

    # Save text profile to area_profiles
    raw_execute(
        "INSERT INTO area_profiles (district, profile_json)"
        " VALUES (%s, %s)"
        " ON DUPLICATE KEY UPDATE profile_json = VALUES(profile_json), updated_at = NOW()",
        (district, json.dumps(profile)),
    )

    # Generate overview map if one doesn't exist yet
    if not ctx["existing_map"]:
        try:
            from src.mission_builder.image_generator import generate_location_map
            from src.news_feed import a1111_lock
            from src.resource_cop import wait_for_a1111_turn

            map_type   = profile.get("overview_map_type", _infer_map_type(district))
            map_prompt = profile.get("overview_sd_prompt", "")
            map_grid   = profile.get("overview_ascii_grid", "")
            if map_prompt:
                maps_dir = Path(__file__).resolve().parent.parent / "generated_modules" / "maps"
                maps_dir.mkdir(parents=True, exist_ok=True)
                safe_name = re.sub(r"[^\w\s-]", "", district).strip().replace(" ", "_")[:60]
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")

                decision = await wait_for_a1111_turn("area_profile_map", max_wait_seconds=60)
                if not decision.run_now:
                    logger.info(f"[AreaGen] A1111 busy; deferring overview map for {district}: {decision.reason}")
                    img_bytes = None
                else:
                    async with a1111_lock:
                        img_bytes = await generate_location_map(
                            district, map_prompt, map_type, size=768, ascii_grid=map_grid
                        )

                if img_bytes:
                    map_path = maps_dir / f"area_{safe_name}_{ts}.png"
                    map_path.write_bytes(img_bytes)
                    raw_execute(
                        "INSERT INTO image_refs (entity_type, entity_name, image_path, metadata_json)"
                        " VALUES ('area_map', %s, %s, %s)"
                        " ON DUPLICATE KEY UPDATE image_path = VALUES(image_path),"
                        " ref_count = ref_count + 1, updated_at = NOW()",
                        (district, str(map_path), json.dumps({"map_type": map_type, "district": district})),
                    )
                    logger.info(f"[AreaGen] Overview map saved for {district}: {map_path.name}")
        except Exception as me:
            logger.warning(f"[AreaGen] Map generation failed for {district}: {me}")

    # Also register sub-location maps in image_refs as 'location_map' for future mission reuse
    for sub in profile.get("sub_locations", []):
        sname = sub.get("name", "")
        if not sname:
            continue
        existing_sub = raw_query(
            "SELECT id FROM image_refs WHERE entity_type='location_map' AND entity_name=%s LIMIT 1",
            (sname,),
        )
        if not existing_sub:
            # Register with empty path — will be generated on demand by mission pipeline
            raw_execute(
                "INSERT IGNORE INTO image_refs (entity_type, entity_name, metadata_json)"
                " VALUES ('location_map', %s, %s)",
                (sname, json.dumps({
                    "district": district,
                    "type": sub.get("type", "interior"),
                    "prompt": sub.get("sd_prompt", "")[:400],
                })),
            )

    logger.info(f"[AreaGen] Profile complete for: {district}")
    return profile


# ---------------------------------------------------------------------------
# Bulk runner
# ---------------------------------------------------------------------------

async def generate_all_area_profiles(
    force: bool = False,
    progress_callback=None,
) -> dict:
    """
    Generate profiles for all known districts.
    progress_callback(district, done, total) called after each completes.
    Returns stats dict.
    """
    _ensure_table()

    districts = [
        r["district"]
        for r in (raw_query("SELECT DISTINCT district FROM gazetteer_places ORDER BY district") or [])
    ]
    total = len(districts)
    done = skipped = failed = 0

    for district in districts:
        # Check skip before hitting the LLM
        if not force:
            ex = raw_query("SELECT id FROM area_profiles WHERE district=%s", (district,))
            if ex:
                skipped += 1
                if progress_callback:
                    await progress_callback(district, done + skipped, total, status="skipped")
                continue

        try:
            profile = await generate_area_profile(district, force=force)
            if profile:
                done += 1
                if progress_callback:
                    await progress_callback(district, done + skipped, total, status="done")
            else:
                failed += 1
                if progress_callback:
                    await progress_callback(district, done + skipped, total, status="failed")
        except Exception as e:
            logger.error(f"[AreaGen] Error on {district}: {e}")
            failed += 1

        # Brief pause between districts to avoid hammering Ollama+A1111 together
        await asyncio.sleep(2)

    return {"total": total, "done": done, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# Query helper for mission builder
# ---------------------------------------------------------------------------

def get_area_profile(district: str) -> Optional[dict]:
    """
    Return the stored profile dict for a district, or None if not generated yet.
    Synchronous — safe to call from sync or async code.
    """
    try:
        rows = raw_query(
            "SELECT profile_json FROM area_profiles WHERE district = %s LIMIT 1",
            (district,),
        )
    except Exception:
        return None
    if not rows or not rows[0]["profile_json"]:
        return None
    pj = rows[0]["profile_json"]
    return json.loads(pj) if isinstance(pj, str) else pj


def get_all_district_names() -> list[str]:
    """Return all district names that have area profiles."""
    try:
        rows = raw_query("SELECT district FROM area_profiles ORDER BY district") or []
        return [r["district"] for r in rows]
    except Exception:
        return []


def get_area_map_path(district: str) -> Optional[str]:
    """Return the file path of the overview map for a district, or None."""
    rows = raw_query(
        "SELECT image_path FROM image_refs"
        " WHERE entity_type IN ('area_map','location_map') AND entity_name=%s LIMIT 1",
        (district,),
    )
    return rows[0]["image_path"] if rows else None
