"""
exploration_pipeline.py - standalone pipeline for unmapped / shifted places.

Exploration covers Warrens sectors, rift-collapsed replacement zones, shifted
sewers, forgotten areas, gate entrances/exits, and Tower-generated terrain.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from src.log import logger
from src.mission_builder.html_renderer import _faction_color, _page
from src.mission_builder.cr_scaling import mission_cr, party_strength as _party_strength

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "generated_modules"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")

KEYWORDS = {"exploration", "explore", "survey", "map", "remap", "gate", "sewer", "warrens", "forgotten", "unmapped",
            "rift clearance", "rift clear", "rift survey", "rift zone", "rift seal"}


def is_exploration_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in KEYWORDS)


SUBTYPES = {
    "rift_replaced_zone": "Town Exterior Objects Table Map, rift zone, warped terrain replacement, alien ground, floating debris, unstable floor sections, strange light sources, survey stakes",
    "shifted_sewers": "Dungeon Interior Objects Table Map, sewer tunnels, underground passages, water channels, iron grates, maintenance walkways, damp stone, pipe bundles, shifted layout",
    "gate_marking": "Town Exterior Objects Table Map, gate entrance zone, archway threshold, guard post, open plaza, transit point, survey markers",
    "forgotten_area": "Dungeon Interior Objects Table Map, forgotten sealed chamber, abandoned rooms, dust and debris scatter, hidden passages, collapsed sections, old architecture",
    "warrens_sector": "Town Exterior Objects Table Map, warrens district, cramped streets, makeshift structures, debris scatter, narrow lanes, low shanty buildings",
    "new_generated_area": "Town Exterior Objects Table Map, newly surfaced area, mixed terrain, exploration route markers, open unknown ground, survey waypoints",
}

DELIVERABLES = [
    "usable route map",
    "hazard and stability report",
    "gate/exit markers",
    "survivor/resource/threat notes",
    "safe-route recommendation",
    "what the Tower replaced and what remains",
    "future mission seeds",
]

HAZARDS = [
    "floor repeats every ninety feet unless someone marks it with living blood",
    "sewer current now runs uphill and pulls loose objects toward a new gate",
    "collapsed street opens into a sunlit field no one under the Dome has seen before",
    "sound arrives late, making shouted warnings unreliable",
    "old doors open into new rooms, but only once",
    "gravity tilts three degrees near the replacement seam",
    "forgotten signage changes language when ignored",
    "air tastes like rain and hot iron",
    "a stable path exists only while someone keeps line of sight on the entrance",
    "mapped chalk marks are copied onto walls the party has not visited yet",
]

FOLLOW_UPS = ["Discovery", "First Contact", "Infestation", "Puzzle", "Rescue", "Defense", "Rift", "Investigation"]


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


def _db_rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        from src.db_api import raw_query
        return raw_query(sql, params) or []
    except Exception as e:
        logger.debug(f"[EXPLORATION] DB read skipped: {e}")
        return []


def _json_col(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return fallback
    return value


GENERIC_PLAN_MARKERS = {
    "unmapped replacement block",
    "old maps no longer match",
    "generic exploration",
    "survey zone",
}


def _mission_text(mission: dict) -> str:
    parts: List[str] = []
    for key in ("title", "type", "mission_type", "tier", "faction", "npc_giver", "body", "description", "private_notes"):
        value = mission.get(key)
        if value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def _mission_context(mission: dict) -> Dict[str, Any]:
    text = _mission_text(mission)
    # Metadata values (faction="Unknown", tier="standard", type="Exploration", ...)
    # must never be treated as story canon — otherwise placeholders like
    # "Unknown", "Type", "Tier" leak into briefing/endpoint prose.
    meta_values = {
        str(mission.get(k, "")).strip().lower()
        for k in ("type", "mission_type", "tier", "faction", "status", "difficulty")
        if mission.get(k)
    }
    stop = {"mission", "exploration", "standard", "posted", "unknown", "type",
            "tier", "patrol", "local", "major", "faction", "difficulty", "reward"} | meta_values
    terms = []
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9'’.-]*(?:\s+[A-Z][A-Za-z0-9'’.-]*){0,4}\b", text):
        term = match.group(0).strip()
        if term.lower() not in stop and term not in terms:
            terms.append(term)
    places = re.findall(r"\b(?:gate|sewer|warrens|district|route|map|tower|rift|collapse|sector|street|chamber|ruin)\b", text, flags=re.I)
    stakes = re.findall(r"[^.!?\n]*(?:explore|survey|map|route|hazard|gate|rift|collapse|missing|discover|safe|unmapped)[^.!?\n]*", text, flags=re.I)
    return {"full_text": text[:1800], "canon_terms": terms[:14], "places": sorted({p.lower() for p in places})[:8], "stakes": [s.strip() for s in stakes[:6] if s.strip()]}


def _specificity_score(plan: Dict[str, Any], context: Dict[str, Any]) -> int:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    score = 0
    for term in context.get("canon_terms", []):
        if term.lower() in blob:
            score += 2
    for place in context.get("places", []):
        if place.lower() in blob:
            score += 1
    for stake in context.get("stakes", []):
        words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", stake)[:4]]
        if words and any(w in blob for w in words):
            score += 1
    return score


def _is_generic_plan(plan: Dict[str, Any], context: Dict[str, Any]) -> bool:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    has_context = bool(context.get("canon_terms") or context.get("places") or context.get("stakes"))
    score = _specificity_score(plan, context)
    if has_context and score >= 3:
        # Anchored in mission canon -- markers alone cannot reject it. The
        # fallback fields merged into partial LLM plans contain some of our own
        # markers, so a marker hit on an anchored plan is self-poisoning, not
        # a signal the plan is generic.
        return False
    return (has_context and score < 3) or any(marker in blob for marker in GENERIC_PLAN_MARKERS)


def _is_historical_place(row: Dict[str, Any]) -> bool:
    extra = _json_col(row.get("extra_json"), {})
    if not isinstance(extra, dict):
        return False
    status = str(extra.get("status") or "").lower()
    return bool(extra.get("historical")) or status in {"historical", "rift_collapsed", "replaced", "retired"}


def mark_area_historical(place_id: int, replaced_by: str, reason: str = "rift collapse replacement") -> None:
    """Mark a gazetteer place as historical so future active pickers skip it."""
    try:
        from src.db_api import raw_execute
        payload = {
            "historical": True,
            "status": "rift_collapsed",
            "replaced_by": replaced_by,
            "collapse_reason": reason,
            "replaced_at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        raw_execute("UPDATE gazetteer_places SET extra_json=%s WHERE id=%s", (json.dumps(payload), place_id))
    except Exception as e:
        logger.warning(f"[EXPLORATION] Could not mark place historical: {e}")


def _party_strength() -> Dict[str, Any]:
    pcs = []
    rows = _db_rows("SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC")
    for row in rows:
        snap = _json_col(row.get("snapshot_json"), {})
        if isinstance(snap, dict) and int(snap.get("total_level") or 0) > 0:
            pcs.append({"name": snap.get("name") or row.get("char_name"), "level": int(snap.get("total_level") or 0), "skills": snap.get("skills") or {}, "classes": snap.get("classes") or {}})
    levels = [p["level"] for p in pcs] or [5]
    return {"party_size": len(pcs) or 4, "avg_level": round(sum(levels) / len(levels), 1), "max_level": max(levels), "pcs": pcs}


def _party_note(strength: Dict[str, Any]) -> str:
    return f"Live party read: {strength['party_size']} PCs, average level {strength['avg_level']}, max level {strength['max_level']}."


def _dc_profile(tier: str, strength: Dict[str, Any]) -> Dict[str, int]:
    bump = {"local": 0, "patrol": 0, "standard": 1, "escort": 1, "investigation": 1, "major": 2, "inter-guild": 3, "high-stakes": 4, "epic": 5, "divine": 5, "tower": 5}.get((tier or "standard").lower(), 1)
    base = 11 + bump + max(0, int(strength["avg_level"]) - 5) // 3
    return {"navigation": base + 2, "hazard": base + 3, "stability": base + 4, "lore": base + 2}


def _pick_subtype(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    for key in SUBTYPES:
        if any(part in text for part in key.split("_")):
            return key
    if "sewer" in text:
        return "shifted_sewers"
    if "gate" in text:
        return "gate_marking"
    if "rift" in text or "collapse" in text:
        return "rift_replaced_zone"
    return random.choice(list(SUBTYPES))


def _pick_area(subtype: str) -> Dict[str, Any]:
    if subtype == "new_generated_area":
        rows = _db_rows("SELECT district, place_type, name, type_tag, description, extra_json FROM gazetteer_places ORDER BY id DESC LIMIT 10")
    else:
        tags = ["warrens", "sewer", "gate", "ruin", "tunnel", "market", "outer wall", "collapse"]
        clause = " OR ".join(["LOWER(name) LIKE %s OR LOWER(type_tag) LIKE %s OR LOWER(description) LIKE %s"] * len(tags))
        params = []
        for tag in tags:
            params.extend([f"%{tag}%", f"%{tag}%", f"%{tag}%"])
        rows = _db_rows(f"SELECT district, place_type, name, type_tag, description, extra_json FROM gazetteer_places WHERE {clause} ORDER BY RAND() LIMIT 10", tuple(params))
    rows = [r for r in rows if not _is_historical_place(r)]
    if rows:
        return random.choice(rows)
    return {"district": "The Warrens", "place_type": "shifted zone", "name": "an unmapped replacement block", "type_tag": "rift collapse", "description": "A place where the old city stops matching any map."}


def _active_rift_seed() -> List[Dict[str, Any]]:
    try:
        from src.news_feed import get_rift_mission_fuel
        return get_rift_mission_fuel(limit=5)
    except Exception:
        rows = _db_rows("SELECT effects_json FROM rift_state ORDER BY id DESC LIMIT 1")
        if not rows:
            return []
        data = _json_col(rows[0].get("effects_json"), {})
        return data.get("rifts", []) if isinstance(data, dict) else []


def _fit_ctx(prompt: str, reply_tokens: int) -> int:
    """Size the Ollama context window to the prompt + planned reply. With no
    num_ctx set, Ollama uses a small default and silently truncates either the
    oversized prompt or the long reply (yielding empty/unparseable output ->
    generic fallback). Only raises; capped at 32k. Local to this pipeline by the
    no-shared-helpers rule."""
    needed = len(prompt) // 4 + reply_tokens + 768
    for cand in (8192, 12288, 16384, 24576, 32768):
        if cand >= needed:
            return cand
    return 32768


async def _ollama(prompt: str, tokens: int = 2200) -> str:
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("exploration_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[EXPLORATION] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=220.0) as c:
            r = await c.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False, "options": {"temperature": 0.86, "num_predict": tokens, "num_ctx": _fit_ctx(prompt, tokens)}})
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"[EXPLORATION] Ollama unavailable: {e}")
        return ""


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


def _fallback_plan(subtype: str, area: Dict[str, Any], dcs: Dict[str, int], mission: Optional[dict] = None) -> Dict[str, Any]:
    mission_context = _mission_context(mission or {})
    title = (mission or {}).get("title", "Exploration")
    canon = ", ".join(mission_context.get("canon_terms", [])[:6]) or title
    _stakes = mission_context.get("stakes") or [f"{area.get('name')} must be mapped well enough to make future movement safe"]
    stake = _stakes[0]
    # Build 6 DISTINCT survey points so the fallback is not six identical boxes.
    # HAZARDS has 10 entries; sample without replacement for non-colliding "change" text.
    _changes = random.sample(HAZARDS, min(6, len(HAZARDS)))
    while len(_changes) < 6:
        _changes.append(random.choice(HAZARDS))
    _point_names = ["The Chalk Gate", "The Sunken Crossing", "The Folded Stair",
                    "The Quiet Stalls", "The Replaced Yard", "The Last Marker"]
    _reads = [
        f"The first stretch of {area.get('name')} looks ordinary until you notice the walls do not line up with the floor.",
        "Water pools where it should drain, and your own reflection lags a half-second behind you.",
        "The passage narrows, then opens into a space far larger than the building outside should hold.",
        "Stalls stand abandoned mid-trade, goods still laid out, the dust on them undisturbed.",
        "The ground here is new - too clean, too even, as though it was set down only yesterday.",
        "You can see the exit marker ahead, but the route toward it keeps quietly rearranging.",
    ]
    _checks = ["Survival", "Perception", "Investigation", "Survival", "Perception", "Survival"]
    _dm = [
        "A chalk mark from a previous survey team is visible on a DC 12 Perception check.",
        "The reflection lag is a stability artifact; a failed Stability save here disorients for 1 round.",
        "The oversized space loops back on itself; mapping it correctly needs the navigation check.",
        "Anything taken from the stalls is gone from the map on the next visit - log it as a hazard.",
        "This patch is a Tower replacement; the seam is the safest documented anchor point.",
        "The shifting route is the complication trigger if the party has not hit one already.",
    ]
    _setups = [
        "Mark the spot, sketch the anomaly, and note how the geometry is wrong before moving on.",
        "Trace the water and your own reflection to time the lag before you commit to the footing.",
        "Pace the oversized space and chalk a true line through it so it can be mapped.",
        "Catalogue the abandoned stalls without lifting anything that might vanish from the record.",
        "Find the seam of the replacement patch and stake it as the safe anchor.",
        "Read the rearranging route and fix the exit line in chalk before it shifts again.",
    ]
    _successes = [
        "The anomaly is logged cleanly; the safe line through here holds for the rest of the team.",
        "You time the lag and cross sure-footed; the stability artifact is now a known, mapped hazard.",
        "The true path through the loop is charted; the next point comes easier (-2 to its DC).",
        "The stalls are catalogued and flagged; nothing the party needs goes missing.",
        "The seam is staked as a reliable anchor; the route back is now dependable.",
        "The exit line is fixed and marked; the party can leave clean whenever they choose.",
    ]
    route_log = [
        {"point": _point_names[i], "change": _changes[i], "read_aloud": _reads[i],
         "dm_notes": _dm[i], "check": _checks[i], "dc": dcs["navigation"],
         "setup": _setups[i], "success": _successes[i],
         "failure": "The route becomes unstable. Navigation DC increases by 2 for subsequent points."}
        for i in range(6)
    ]
    return {
        "briefing": f"Map {area.get('name')} in {area.get('district')} while preserving the mission-specific stake around {canon}. The old maps no longer match what stands there.",
        "endpoint_revelation": f"The route ends by proving what changed in {area.get('name')} since the last survey - the safe path, the live hazards, and what the Tower replaced - not just by walking six points.",
        "route_decisions": ["mark the safest entry", "choose loud speed or careful survey", "decide which hazard to document first", "protect the exit line", f"resolve the stake: {stake}"],
        "return_standard": "The job is complete when the party can explain the safe route, active hazards, what was discovered, and what follow-up mission is unlocked.",
        "setup": f"Contact NPC waits at the entrance to {area.get('name')} with survey stakes and chalk. Brief the party on the DC profile and give each member one survey stake. The first hazard is visible from the entry point.",
        "win_conditions": "SUCCESS: All 6 survey points documented and party exits. PARTIAL: 3-5 points documented. FAILURE: Fewer than 3 points or party cannot exit.",
        "opening_scene": f"The entrance to {area.get('name')} looms ahead. The chalk dust on the floor has been disturbed by something moving in the dark. A warden in a travel-stained cloak marks an X on the doorframe and turns to face you.",
        "scenes": [
            {"name": "Survey Phase", "trigger": "Party enters the area", "read_aloud": "The survey zone stretches before you - twisted geometry, wrong light, and the smell of something replaced.", "dm_notes": "Remind players that chalk marks are their best tool. Encourage creative approaches.", "mechanics": f"Survival DC {dcs['navigation']} per survey point. Hazard check DC {dcs['hazard']} if players rush.", "outcome": "Leads to Complication when midpoint is crossed."},
            {"name": "Complication", "trigger": "After survey point 3 or if players trigger a hazard", "read_aloud": "The route behind you looks different. Either the chalk marks have moved, or you have.", "dm_notes": "Introduce the most dramatic hazard now. One PC should face a real consequence.", "mechanics": f"Stability DC {dcs['stability']} to avoid disorientation. Navigation DC {dcs['navigation']} to reorient.", "outcome": "Successful parties continue to Extraction. Failed parties must backtrack."},
            {"name": "Extraction", "trigger": "All survey points attempted or 4 hours elapsed", "read_aloud": "The entrance is visible - but something has changed since you came through it.", "dm_notes": "Add one final pressure: a watcher, a shifting floor, or a timer. Make the exit feel earned.", "mechanics": f"Navigation DC {dcs['navigation']} to exit cleanly. On failure, 1 hour lost or 1d6 damage.", "outcome": "Party delivers survey data. Follow-up mission unlocks."},
        ],
        "imagery": random.sample(HAZARDS, min(8, len(HAZARDS))),
        "route_log": route_log,
        "hazards": random.sample(HAZARDS, min(5, len(HAZARDS))),
        "deliverables": list(DELIVERABLES),
        "discoveries": ["new resource vein", "sealed gate", "survivor sign", "impossible weather pocket", "trace of a recycled world"],
        "dialogue": ["Warden: Mark exits first. Curiosity second.", "Scout: My chalk marks came back before I did.", "Local: That street used to end at a bakery.", "TNN: Is it true people are living in there?", "Survivor: The sky was wrong, but it was sky.", "Contact: Don't trust anything that isn't nailed down.", "Lookout: It's quiet. Too quiet.", "Runner: The last crew didn't come back with everything."],
        "news_seed": f"Survey crews report a replacement zone in {area.get('district')} after suspected Tower recycling.",
        "follow_up": random.choice(FOLLOW_UPS),
    }


def _list_field(value: Any, fallback: List[Any]) -> List[Any]:
    if isinstance(value, list):
        items = [item for item in value if item not in (None, "")]
        return items or fallback
    if isinstance(value, str):
        items = [part.strip(" -\t") for part in re.split(r"[\n;]+", value) if part.strip(" -\t")]
        return items or fallback
    return fallback


def _structured_list(value: Any, fallback: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return fallback
    normalized: List[Dict[str, Any]] = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            return fallback
        base = dict(fallback[i]) if i < len(fallback) else {}
        base.update({k: v for k, v in item.items() if v not in (None, "", [])})
        normalized.append(base)
    return normalized or fallback


def _normalize_plan(data: Optional[Dict[str, Any]], subtype: str, area: Dict[str, Any], dcs: Dict[str, int], mission: Optional[dict] = None) -> Dict[str, Any]:
    fallback = _fallback_plan(subtype, area, dcs, mission)
    if not isinstance(data, dict):
        return fallback

    plan = dict(fallback)
    for key, value in data.items():
        if value not in (None, "", []):
            plan[key] = value

    for key in ("briefing", "setup", "win_conditions", "opening_scene", "news_seed", "follow_up", "endpoint_revelation", "return_standard"):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            plan[key] = fallback[key]

    for key in ("imagery", "hazards", "deliverables", "discoveries", "dialogue", "route_decisions"):
        plan[key] = _list_field(plan.get(key), fallback[key])

    plan["scenes"] = _structured_list(plan.get("scenes"), fallback["scenes"])
    plan["route_log"] = _structured_list(plan.get("route_log"), fallback["route_log"])
    if mission and _is_generic_plan(plan, _mission_context(mission)):
        logger.warning("[EXPLORATION] Rejected generic plan; using mission-specific fallback")
        return fallback
    return plan


async def _generate_plan(mission: dict, subtype: str, area: Dict[str, Any], strength: Dict[str, Any], dcs: Dict[str, int], rifts: List[Dict[str, Any]]) -> Dict[str, Any]:
    mission_context = _mission_context(mission)
    prompt = f"""Create a D&D 5e 2024 Exploration mission plan as JSON only.
Mission: {mission.get('title', 'Exploration')}
Mission canon that must be preserved: {mission_context}
Subtype: {subtype} — {SUBTYPES[subtype]}
Area: {area.get('name')} in {area.get('district')} — {area.get('description','')}
Active rifts: {rifts[:2]}
Party: {_party_note(strength)}
DCs: navigation {dcs['navigation']}, hazard {dcs['hazard']}, stability {dcs['stability']}, lore {dcs['lore']}

Return a JSON object with these EXACT keys:

"briefing": one paragraph player hook (2-3 sentences)
"endpoint_revelation": what the exploration proves/finds at the endpoint; it must use mission canon
"route_decisions": array of 5 meaningful route/survey decisions the players make
"return_standard": what proves the survey is complete and useful
"setup": DM pre-session instructions — who the contact NPC is, where they wait, what gear is given, what marks/hazards are already visible before the party enters. 3-4 sentences.
"win_conditions": explicit success/partial/failure criteria in plain language. e.g. 'SUCCESS: all 6 points documented, party exits. PARTIAL: 3-5 points, some hazards mapped. FAILURE: fewer than 3 points or party cannot exit.'
"opening_scene": 3 sentences of vivid read-aloud text describing the moment the party arrives at the survey area entrance.
"scenes": array of 3 scene objects (Survey, Complication, Extraction), each with:
  "name": scene title
  "trigger": what causes the scene (e.g. 'after survey point 3' or 'if alarm is raised')
  "read_aloud": 2-3 sentence description the DM reads aloud when the scene begins
  "dm_notes": 2-3 sentences of DM-only tactical context
  "mechanics": relevant skill checks, DCs, timing pressure in this scene
  "outcome": where this leads
"imagery": array of 8 vivid 1-sentence environmental details
"route_log": array of 6 survey point objects, each with:
  "point": short location name (e.g. 'The Chalk Gate', 'The Sunken Crossing')
  "change": 1 sentence describing what is different or wrong here
  "read_aloud": 2-3 sentence read-aloud the DM uses when players arrive
  "dm_notes": 1-2 sentences DM-only context (what is really happening, hidden clue, or tactical note)
  "check": skill name (e.g. 'Survival', 'Investigation', 'Perception')
  "dc": DC number ({dcs['navigation']})
  "setup": 1 sentence describing what attempting the check looks like in the fiction here
  "success": 1 sentence describing what the DM narrates on a successful check (a concrete gain)
  "failure": 1 sentence describing what happens on a failed check
"hazards": array of 5 hazard strings
"deliverables": array of 6-8 survey deliverables
"discoveries": array of 5 possible findings
"dialogue": array of 8 short NPC lines with speaker prefix (e.g. 'Warden: Mark exits first.')
"news_seed": short public bulletin after the mission
"follow_up": one follow-up mission type string
Return JSON object only. No markdown, no explanation."""
    data = None
    for attempt in range(3):
        data = _parse_json(await _ollama(prompt, tokens=3200))
        if data:
            break
        logger.warning(f"[EXPLORATION] LLM returned no usable plan (attempt {attempt + 1}/3) for '{mission.get('title', 'Exploration')}'")
        await asyncio.sleep(2)
    if not data:
        logger.warning("[EXPLORATION] LLM unavailable after retries; using mission-faithful fallback")
    return _normalize_plan(data, subtype, area, dcs, mission)
    if False:
        return {
        "briefing": f"Map {area.get('name')} in {area.get('district')}. The old maps no longer match what stands there.",
        "setup": f"Contact NPC waits at the entrance to {area.get('name')} with survey stakes and chalk. Brief the party on the DC profile and give each member one survey stake. The first hazard is visible from the entry point.",
        "win_conditions": f"SUCCESS: All 6 survey points documented and party exits. PARTIAL: 3-5 points documented. FAILURE: Fewer than 3 points or party cannot exit.",
        "opening_scene": f"The entrance to {area.get('name')} looms ahead. The chalk dust on the floor has been disturbed by something moving in the dark. A warden in a travel-stained cloak marks an X on the doorframe and turns to face you.",
        "scenes": [
            {"name": "Survey Phase", "trigger": "Party enters the area", "read_aloud": "The survey zone stretches before you — twisted geometry, wrong light, and the smell of something replaced.", "dm_notes": "Remind players that chalk marks are their best tool. Encourage creative approaches.", "mechanics": f"Survival DC {dcs['navigation']} per survey point. Hazard check DC {dcs['hazard']} if players rush.", "outcome": "Leads to Complication when midpoint is crossed."},
            {"name": "Complication", "trigger": "After survey point 3 or if players trigger a hazard", "read_aloud": "The route behind you looks different. Either the chalk marks have moved, or you have.", "dm_notes": "Introduce the most dramatic hazard now. One PC should face a real consequence.", "mechanics": f"Stability DC {dcs['stability']} to avoid disorientation. Navigation DC {dcs['navigation']} to reorient.", "outcome": "Successful parties continue to Extraction. Failed parties must backtrack."},
            {"name": "Extraction", "trigger": "All survey points attempted or 4 hours elapsed", "read_aloud": "The entrance is visible — but something has changed since you came through it.", "dm_notes": "Add one final pressure: a watcher, a shifting floor, or a timer. Make the exit feel earned.", "mechanics": f"Navigation DC {dcs['navigation']} to exit cleanly. On failure, 1 hour lost or 1d6 damage.", "outcome": "Party delivers survey data. Follow-up mission unlocks."},
        ],
        "imagery": random.sample(HAZARDS, min(8, len(HAZARDS))),
        "route_log": [{"point": f"Survey Point {i}", "change": random.choice(HAZARDS), "read_aloud": f"The ground here feels wrong underfoot. Something about this section of {area.get('name')} refuses to stay still.", "dm_notes": "Hidden: a chalk mark from a previous survey team is visible on DC 12 Perception.", "check": "Survival", "dc": dcs["navigation"], "failure": "The route becomes unstable. Navigation DC increases by 2 for subsequent points."} for i in range(1, 7)],
        "hazards": random.sample(HAZARDS, min(5, len(HAZARDS))),
        "deliverables": DELIVERABLES,
        "discoveries": ["new resource vein", "sealed gate", "survivor sign", "impossible weather pocket", "trace of a recycled world"],
        "dialogue": ["Warden: Mark exits first. Curiosity second.", "Scout: My chalk marks came back before I did.", "Local: That street used to end at a bakery.", "TNN: Is it true people are living in there?", "Survivor: The sky was wrong, but it was sky.", "Contact: Don't trust anything that isn't nailed down.", "Lookout: It's quiet. Too quiet.", "Runner: The last crew didn't come back with everything."],
        "news_seed": f"Survey crews report a replacement zone in {area.get('district')} after suspected Tower recycling.",
        "follow_up": random.choice(FOLLOW_UPS),
    }


async def _generate_map(subtype: str, area: Dict[str, Any], out_dir: Path) -> Optional[Path]:
    path = out_dir / "exploration_map.png"
    from src.battle_map_library import copy_library_map_for_mission
    return copy_library_map_for_mission(
        {"faction": area.get("faction", "")},
        path,
        mission_type="exploration",
        location_name=area.get("name", ""),
        district=area.get("district", ""),
        description=f"{subtype} {area.get('description', '')}",
    )

def _e(v: Any) -> str:
    import html
    return html.escape(str(v or ""))


def _card(title: str, body: str, color: str = "#3a6898") -> str:
    return f'<div style="border-left:4px solid {color};padding:12px 16px;margin:14px 0;background:#fafafa;border-radius:0 6px 6px 0;"><h2 style="margin:0 0 8px;color:{color};">{_e(title)}</h2>{body}</div>'


def _ul(items: List[Any]) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _route_table(points: List[Dict[str, Any]]) -> str:
    return "<table><tr><th>Point</th><th>Change</th><th>Check</th><th>Failure</th></tr>" + "".join(f"<tr><td>{_e(p.get('point'))}</td><td>{_e(p.get('change'))}</td><td>{_e(p.get('check'))} DC {_e(p.get('dc'))}</td><td>{_e(p.get('failure'))}</td></tr>" for p in points) + "</table>"


def render_module(mission: dict, subtype: str, area: Dict[str, Any], plan: Dict[str, Any], strength: Dict[str, Any], dcs: Dict[str, int], map_path: Optional[Path], out_dir: Path) -> str:
    title   = mission.get("title", "Exploration")
    faction = mission.get("faction", "Adventurers Guild")
    tier    = (mission.get("tier") or "standard").upper()
    fc      = _faction_color(faction)

    # ── Cover ────────────────────────────────────────────────────────────────
    cover = (
        f'<div class="cover">'
        f'<div class="faction-label">{_e(faction)} &nbsp;·&nbsp; {tier}</div>'
        f'<div class="ornament">⬥ ⬥ ⬥</div>'
        f'<h1>{_e(title)}</h1>'
        f'<div class="subtitle">Exploration — {_e(area.get("district",""))} / {_e(subtype.replace("_"," ").title())}</div>'
        f'<div class="meta-block">'
        f'Party: {_e(_party_note(strength))}<br>'
        f'DCs: Nav {dcs["navigation"]} &nbsp;·&nbsp; Hazard {dcs["hazard"]} &nbsp;·&nbsp; Stability {dcs["stability"]} &nbsp;·&nbsp; Lore {dcs["lore"]}'
        f'</div></div>'
    )

    # ── Quick Reference card ─────────────────────────────────────────────────
    win = _e(str(plan.get("win_conditions") or "Document all survey points and exit safely."))
    quick_ref = (
        '<div style="background:#fffbe6;border:2px solid #b8923a;border-radius:8px;'
        'padding:20px 24px;margin:24px 56px;font-family:Arial,sans-serif;font-size:14px;">'
        '<div style="font-weight:bold;color:#8a5a1f;letter-spacing:3px;text-transform:uppercase;'
        'font-size:11px;margin-bottom:14px;">⚡ Quick Reference — Exploration</div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px 28px;">'
        f'<div><strong>LOCATION</strong><br>{_e(area.get("name","?"))} — {_e(area.get("district","?"))}</div>'
        f'<div><strong>FACTION</strong><br>{_e(faction)}</div>'
        f'<div><strong>PARTY</strong><br>{strength["party_size"]} PCs · avg Lv {strength["avg_level"]} · max Lv {strength["max_level"]}</div>'
        f'<div><strong>KEY DCs</strong><br>Navigation {dcs["navigation"]} · Hazard {dcs["hazard"]} · Stability {dcs["stability"]}</div>'
        f'<div style="grid-column:1/-1;"><strong>WIN CONDITIONS</strong><br><span style="color:#2a6a2a;">{win}</span></div>'
        '</div></div>'
    )

    # ── Before You Run (DM-only setup box) ──────────────────────────────────
    setup_text = _e(str(plan.get("setup") or f"Contact NPC waits at the entrance to {area.get('name','the area')}. Provide survey stakes. Brief party on DC profile."))
    setup_block = (
        '<div class="page-body">'
        '<div class="gm-note" style="margin-top:28px;">'
        '<span class="gm-label">🗂️ Before You Run — DM Setup</span>'
        f'{setup_text}'
        '</div>'
    )
    endpoint_block = (
        '<div class="gm-note" style="margin-top:18px;">'
        '<span class="gm-label">Endpoint & Return Standard</span>'
        f'<p><strong>Endpoint revelation:</strong> {_e(plan.get("endpoint_revelation", ""))}</p>'
        f'<p><strong>Return standard:</strong> {_e(plan.get("return_standard", ""))}</p>'
        '<h3>Route Decisions</h3>'
        + "".join(f'<p>☐ {_e(x)}</p>' for x in plan.get("route_decisions", []))
        + '</div>'
    )

    # ── Map with numbered survey-point overlays ──────────────────────────────
    route_log = plan.get("route_log") or []
    if map_path:
        # Fixed positions for up to 6 survey markers — spread across the map
        _positions = [(18,78),(38,52),(55,38),(70,62),(84,35),(48,72)]
        markers = "".join(
            f'<div title="{_e(p.get("point",""))}" style="position:absolute;left:{pos[0]}%;top:{pos[1]}%;'
            f'transform:translate(-50%,-50%);width:30px;height:30px;border-radius:50%;background:#7b1e1e;'
            f'color:white;font-weight:bold;font-size:13px;display:flex;align-items:center;justify-content:center;'
            f'border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,.5);font-family:Arial,sans-serif;">{i+1}</div>'
            for i, (p, pos) in enumerate(zip(route_log[:6], _positions))
        )
        markers += (
            '<div title="Entry point" style="position:absolute;left:9%;top:91%;transform:translate(-50%,-50%);'
            'width:30px;height:30px;border-radius:50%;background:#3a6898;color:white;font-weight:bold;'
            'font-size:11px;display:flex;align-items:center;justify-content:center;border:2px solid white;'
            'box-shadow:0 2px 6px rgba(0,0,0,.5);font-family:Arial,sans-serif;">S</div>'
            '<div title="Extraction" style="position:absolute;left:89%;top:9%;transform:translate(-50%,-50%);'
            'width:30px;height:30px;border-radius:50%;background:#2a6a2a;color:white;font-weight:bold;'
            'font-size:11px;display:flex;align-items:center;justify-content:center;border:2px solid white;'
            'box-shadow:0 2px 6px rgba(0,0,0,.5);font-family:Arial,sans-serif;">X</div>'
        )
        legend = (
            '<div style="margin-top:10px;font-family:Arial,sans-serif;font-size:12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;">'
            '<span style="background:#3a6898;color:white;padding:2px 8px;border-radius:3px;font-weight:bold;">S</span> Start &nbsp;'
            '<span style="background:#7b1e1e;color:white;padding:2px 8px;border-radius:3px;font-weight:bold;">1–6</span> Survey Points &nbsp;'
            '<span style="background:#2a6a2a;color:white;padding:2px 8px;border-radius:3px;font-weight:bold;">X</span> Extraction'
            '</div>'
        )
        map_src = map_path.relative_to(out_dir).as_posix()
        map_section = (
            f'<h2>Survey Map — {_e(area.get("name",""))}</h2>'
            '<div style="position:relative;display:inline-block;max-width:100%;width:100%;">'
            f'<img src="{map_src}" style="max-width:100%;border:3px solid {fc};border-radius:8px;display:block;" alt="Exploration Map">'
            f'{markers}</div>{legend}'
        )
    else:
        map_section = "<h2>Survey Map</h2><p><em>No map generated.</em></p>"

    # ── Opening scene ────────────────────────────────────────────────────────
    opening_ra   = _e(str(plan.get("opening_scene") or plan.get("briefing") or ""))
    opening_dn   = _e(str(plan.get("setup") or "Brief the party and hand out survey equipment."))
    opening_html = (
        '<div class="chapter-header"><div class="ch-label">Scene 1 — Entry</div>'
        f'<h2>Arrival at {_e(area.get("name",""))}</h2></div>'
        f'<div class="read-aloud"><span class="ra-label">Read Aloud</span>{opening_ra}</div>'
        f'<div class="dm-note"><span class="dm-label">DM Note — Setup</span>{opening_dn}</div>'
    )

    # ── Scene flow cards (Survey / Complication / Extraction) ────────────────
    scenes_html = ""
    for i, sc in enumerate(plan.get("scenes") or [], 2):
        n    = _e(sc.get("name") or f"Scene {i}")
        trig = _e(sc.get("trigger") or "")
        ra   = _e(sc.get("read_aloud") or "")
        dn   = _e(sc.get("dm_notes") or "")
        mech = _e(sc.get("mechanics") or "")
        out  = _e(sc.get("outcome") or "")
        scenes_html += (
            f'<div class="chapter-header" style="margin-top:36px;"><div class="ch-label">Scene {i}</div><h2>{n}</h2></div>'
            + (f'<p style="background:#f0f4f8;border-left:4px solid #3a6898;padding:8px 14px;margin:8px 0;font-style:italic;font-size:13px;font-family:Arial,sans-serif;border-radius:0 5px 5px 0;color:#3a4a5a;"><strong>Trigger:</strong> {trig}</p>' if trig else "")
            + (f'<div class="read-aloud"><span class="ra-label">Read Aloud</span>{ra}</div>' if ra else "")
            + (f'<div class="dm-note"><span class="dm-label">DM Note</span>{dn}</div>' if dn else "")
            + (f'<div class="gm-note"><span class="gm-label">⚙️ Mechanics</span>{mech}</div>' if mech else "")
            + (f'<p style="font-style:italic;color:#555;font-size:14px;margin-top:8px;"><strong>Leads to:</strong> {out}</p>' if out else "")
        )

    # ── Survey point cards ───────────────────────────────────────────────────
    point_cards = ""
    if route_log:
        point_cards = (
            '<div class="chapter-header" style="margin-top:36px;"><div class="ch-label">Survey Phase</div>'
            '<h2>Survey Points</h2></div>'
            '<p>Survey points may be approached in any order. Each requires a check to document accurately. '
            'Tick the checkbox when a point is recorded.</p>'
        )
        for i, pt in enumerate(route_log[:6], 1):
            pname  = _e(pt.get("point") or f"Survey Point {i}")
            change = _e(pt.get("change") or "")
            ra     = _e(pt.get("read_aloud") or pt.get("change") or "")
            dn     = _e(pt.get("dm_notes") or "")
            skill  = _e(pt.get("check") or "Survival")
            dc     = _e(str(pt.get("dc") or dcs["navigation"]))
            fail   = _e(pt.get("failure") or "The route becomes unstable.")
            setup  = _e(pt.get("setup") or f"Document the change here with a {pt.get('check') or 'Survival'} check before moving on.")
            succ   = _e(pt.get("success") or "Logged cleanly; the safe route holds and the next point comes easier.")
            point_cards += (
                f'<div style="border:1px solid #7b1e1e;border-left:5px solid #7b1e1e;border-radius:6px;'
                f'padding:16px 20px;margin:20px 0;background:#fdf8f0;page-break-inside:avoid;">'
                f'<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:10px;'
                f'border-bottom:1px solid #e8d8a0;padding-bottom:8px;">'
                f'<span style="background:#7b1e1e;color:white;width:28px;height:28px;border-radius:50%;'
                f'display:inline-flex;align-items:center;justify-content:center;font-weight:bold;font-size:13px;'
                f'flex-shrink:0;font-family:Arial,sans-serif;">{i}</span>'
                f'<span style="font-size:17px;font-weight:700;font-family:Georgia,serif;">{pname}</span>'
                f'<span style="margin-left:auto;font-family:Arial,sans-serif;font-size:11px;background:#3a6898;'
                f'color:white;padding:2px 9px;border-radius:3px;font-weight:bold;">DC {dc}</span></div>'
                f'<div style="margin-bottom:10px;">'
                f'<div style="font-family:Arial,sans-serif;font-size:9px;font-weight:700;letter-spacing:.12em;'
                f'text-transform:uppercase;color:rgba(26,22,18,.4);margin-bottom:3px;">What Changed</div>'
                f'<div style="font-size:14px;line-height:1.6;">{change}</div></div>'
                f'<div class="read-aloud" style="padding:8px 12px;margin:8px 0;font-size:14px;">'
                f'<span class="ra-label">Read Aloud</span>{ra}</div>'
                + (f'<div class="dm-note" style="font-size:13px;padding:8px 12px;margin:6px 0;">'
                   f'<span class="dm-label">DM Note</span>{dn}</div>' if dn else "")
                + f'<div style="margin-top:10px;font-size:13px;color:#3a2d1a;">'
                f'<span style="font-family:Arial,sans-serif;font-size:9px;font-weight:700;letter-spacing:.1em;'
                f'text-transform:uppercase;color:#8a5a1f;">Setup</span><br>{setup}</div>'
                + f'<div style="display:flex;gap:20px;flex-wrap:wrap;margin-top:10px;font-size:13px;">'
                f'<div style="min-width:90px;"><span style="font-family:Arial,sans-serif;font-size:9px;font-weight:700;'
                f'letter-spacing:.1em;text-transform:uppercase;color:#7b1e1e;">Check</span><br>'
                f'{skill} DC {dc}</div>'
                f'<div style="flex:1;min-width:160px;"><span style="font-family:Arial,sans-serif;font-size:9px;font-weight:700;'
                f'letter-spacing:.1em;text-transform:uppercase;color:#2a6a2a;">On Success</span><br>'
                f'{succ}</div>'
                f'<div style="flex:1;min-width:160px;"><span style="font-family:Arial,sans-serif;font-size:9px;font-weight:700;'
                f'letter-spacing:.1em;text-transform:uppercase;color:#7b1e1e;">On Failure</span><br>'
                f'{fail}</div></div>'
                f'<label style="display:block;margin-top:10px;font-family:Arial,sans-serif;font-size:12px;color:#666;">'
                f'<input type="checkbox" style="margin-right:6px;"> Documented</label>'
                f'</div>'
            )

    # ── Hazards ──────────────────────────────────────────────────────────────
    hazards      = plan.get("hazards") or []
    hazards_html = (
        '<h2>Active Hazards</h2>'
        '<p>These may appear at any survey point. Introduce 1-2 per session based on party pace.</p>'
        + "".join(
            f'<div style="background:#fef4f4;border-left:4px solid #c55555;border-radius:0 5px 5px 0;'
            f'padding:8px 12px;margin:7px 0;font-size:14px;">⚠️ {_e(h)}</div>'
            for h in hazards
        )
    )

    # ── Discoveries + Deliverables ────────────────────────────────────────────
    discoveries  = plan.get("discoveries") or []
    deliverables = plan.get("deliverables") or DELIVERABLES
    follow_up    = plan.get("follow_up") or ""
    reward_html  = (
        '<h2>Deliverables</h2>'
        '<p>The party must submit these to complete the mission.</p>'
        + "".join(f'<p>☐ {_e(d)}</p>' for d in deliverables)
        + '<h2>Discoveries &amp; Future Seeds</h2>'
        + "".join(f'<p>• {_e(d)}</p>' for d in discoveries)
        + (f'<p style="margin-top:10px;"><strong>Follow-up mission:</strong> {_e(follow_up)}</p>' if follow_up else "")
    )

    # ── Dialogue ─────────────────────────────────────────────────────────────
    dialogue     = plan.get("dialogue") or []
    dialogue_html = (
        '<h2>NPC Lines &amp; Witness Dialog</h2>'
        '<p>Use when players talk to locals, survivors, or faction observers.</p>'
        + "".join(
            f'<p style="border-bottom:1px dotted #d0c8b0;padding:6px 0;font-style:italic;">&ldquo;{_e(line)}&rdquo;</p>'
            for line in dialogue
        )
    )

    # ── Assemble body ────────────────────────────────────────────────────────
    body = (
        cover
        + quick_ref
        + setup_block
        + endpoint_block
        + map_section
        + opening_html
        + scenes_html
        + point_cards
        + hazards_html
        + reward_html
        + dialogue_html
        + "</div>"   # close .page-body
    )
    from src.treasure import loot_card as _loot_card
    body += _loot_card(mission)
    return _page(title, body, faction)


def render_session(mission: dict, plan: Dict[str, Any], dcs: Dict[str, int]) -> str:
    title = mission.get("title", "Exploration")
    faction = mission.get("faction", "Adventurers Guild")
    body = f"<h1>{_e(title)}</h1>"
    body += _card("Route Checklist", "".join(f"<p><input type='checkbox'> {_e(p.get('point'))} - {_e(p.get('change'))}</p>" for p in plan.get("route_log", [])), "#3a6898")
    body += _card("DCs", f"<p>Navigation DC {dcs['navigation']} | Hazard DC {dcs['hazard']} | Stability DC {dcs['stability']} | Lore DC {dcs['lore']}</p>", "#8a5a1f")
    body += _card("Survey Record", "<textarea rows='8' style='width:100%;font-family:inherit;' placeholder='Routes, gates, hazards, discoveries, future missions...'></textarea>", "#2a6a2a")
    return _page(title, body, faction)


def _md_guides(mission: dict, subtype: str, area: Dict[str, Any], plan: Dict[str, Any], strength: Dict[str, Any], dcs: Dict[str, int]) -> Dict[str, str]:
    return {
        "dm": f"## Exploration DM Guide\n### Area\n{area.get('name')} - {area.get('district')}\n\n### Imagery\n" + "\n".join(f"- {x}" for x in plan.get("imagery", [])) + "\n\n### Hazards\n" + "\n".join(f"- {x}" for x in plan.get("hazards", [])) + f"\n\n### Follow-Up\n{plan.get('follow_up')}\n\n### News Seed\n{plan.get('news_seed')}",
        "players": f"## Exploration Player Guide\n### What Happened\n{plan.get('briefing')}\n\n### Survey Target\n{area.get('name')} in {area.get('district')}\n\n### Deliverables\n" + "\n".join(f"- {x}" for x in plan.get("deliverables", DELIVERABLES)),
        "chart": f"## Exploration Chart Pack\n### DCs\n| Type | DC |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in dcs.items()) + "\n\n### Route Log\n" + "\n".join(f"- {p.get('point')}: {p.get('change')} ({p.get('check')} DC {p.get('dc')})" for p in plan.get("route_log", [])),
    }


async def build_exploration_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Exploration")
    faction = mission.get("faction", "Adventurers Guild")
    tier = mission.get("tier", "standard")
    if out_dir is None:
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    strength = _party_strength()
    dcs      = _dc_profile(tier, strength)
    subtype  = _pick_subtype(mission)
    area     = _pick_area(subtype)
    rifts    = _active_rift_seed()

    # --- Council or single-pass generation ---
    from src.mission_builder.module_council import generate_with_council, ENABLED as COUNCIL_ON
    plan = None
    if COUNCIL_ON:
        logger.info(f"[EXPLORATION] Using 4-pass council for {title!r}")
        fallback_briefing = f"Map {area.get('name')} in {area.get('district')}."
        plan = await generate_with_council(
            mission_title = title,
            subtype       = subtype,
            area          = area,
            strength      = strength,
            dcs           = dcs,
            rifts         = rifts,
            faction       = faction,
            briefing      = mission.get("body") or fallback_briefing,
        )
        if not plan:
            logger.warning("[EXPLORATION] Council returned nothing — falling back to single-pass")
    if not plan:
        plan = await _generate_plan(mission, subtype, area, strength, dcs, rifts)
    else:
        plan = _normalize_plan(plan, subtype, area, dcs, mission)
    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        map_path = await _generate_map(subtype, area, out_dir)
    from src.mission_builder.mimir_module import create_module as _mc, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd, enrich_mission_loot as _mel
    _mimir_id = await _mc(mission, mission_type="exploration")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Exploration Map")
    _html = render_module(mission, subtype, area, plan, strength, dcs, map_path, out_dir)
    _loot_rewards = await _mel(_mimir_id or "", mission)
    _html += _ms([], _loot_rewards, _mimir_id or "")
    (out_dir / "module.html").write_text(_html, encoding="utf-8")
    (out_dir / "session.html").write_text(render_session(mission, plan, dcs), encoding="utf-8")
    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    guides = _md_guides(mission, subtype, area, plan, strength, dcs)
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, guides["dm"])
    write_component(out_dir, "players_guide", "Players Guide", title, faction, guides["players"])
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, guides["chart"])
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",    "type": "description", "content": guides["players"]},
            {"title": f"{title} — DM Notes",         "type": "dm_notes",    "content": guides["dm"]},
            {"title": f"{title} — Discovery Tables", "type": "custom",      "content": guides["chart"]},
        ])
    maps_name = write_maps_page(out_dir, title, faction, [map_path] if map_path else [])
    components = component_links(has_maps=bool(maps_name))
    from src.mission_builder.html_renderer import render_index
    index_html = render_index(title, faction, tier, mission_cr(mission), mission.get("player_name", "") or "Open", [], components, None, 1 if map_path else 0)
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    try:
        from src.mission_builder.mission_db import write_module_slug_for_mission
        write_module_slug_for_mission(mission, out_dir.name, log_prefix="EXPLORATION")
    except Exception as e:
        logger.warning(f"[EXPLORATION] Could not write module_slug: {e}")
    with zipfile.ZipFile(out_dir.parent / f"{out_dir.name}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))
    return index_path
