"""
rescue_pipeline.py - Rescue mission modules.

Rescue is about getting someone or something out alive, whole, witnessed, or
properly recovered. It supports active rescues and slower aftermath
cleanup-and-rescue scenes. Aftermath rescue is emotional, usually over days,
and should not involve combat except verbal/social conflict.

Exported:
    build_rescue_module(mission: dict, out_dir: Path) -> Path
    is_rescue_mission(mission_type: str) -> bool
"""

from __future__ import annotations

import os
import re
import json
import random
import asyncio
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

import httpx

from src.log import logger
from src.mission_builder.html_renderer import _faction_color, _page
from src.mission_builder.cr_scaling import mission_cr, party_strength as _party_strength
from src.mission_builder.monster_roster import logical_enemy_roster_for_mission

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "generated_modules"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")

_RESCUE_KEYWORDS = {
    "rescue", "extract", "save", "evacuate", "recover survivor", "hostage",
    "missing person", "medical extraction", "pullout", "prison break",
}


def is_rescue_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _RESCUE_KEYWORDS)


SUBTYPES = {
    "captive_extraction": {"mode": "active", "label": "Captive Extraction"},
    "hostage_negotiation": {"mode": "active", "label": "Hostage Negotiation"},
    "disaster_area": {"mode": "active", "label": "Disaster Area Rescue"},
    "cleanup_rescue": {"mode": "aftermath", "label": "Cleanup-and-Rescue"},
    "medical_extraction": {"mode": "active", "label": "Medical Extraction"},
    "prison_break": {"mode": "active", "label": "Prison Break"},
    "cursed_ritual": {"mode": "active", "label": "Cursed / Ritual Rescue"},
    "battlefield_pullout": {"mode": "active", "label": "Battlefield Pullout"},
    "missing_person": {"mode": "aftermath", "label": "Missing-Person Recovery"},
}

_RESCUE_DUNGEON_SUBTYPES = {"captive_extraction", "prison_break", "cursed_ritual"}

TARGET_TYPES = [
    "individual NPC/person",
    "group of civilians",
    "adventuring party",
    "missing child/family",
    "animal/familiar/mount",
    "sentient construct",
    "body/remains",
    "trapped spirit/memory/soul",
]

CONDITION_TRACK = [
    ("Safe for now", "Target can wait briefly without getting worse."),
    ("At risk", "Delay, failed checks, or hazards will worsen the situation."),
    ("Injured / damaged", "Target needs help, calming, repair, or treatment."),
    ("Critical", "Immediate action is required."),
    ("Lost / dead / unrecoverable", "Mission becomes recovery, grief, or consequences."),
]

REPORTER_TRACK = [
    ("Respectful distance", "Reporters keep back and may help broadcast missing-person details."),
    ("Circling", "Questions begin shaping the public story."),
    ("Intrusive", "Families, survivors, or the party are pressed at bad moments."),
    ("Exploitative headline", "TNN or rivals frame the scene for drama."),
    ("Public backlash", "Coverage creates faction/public consequences."),
]

AFTERMATH_SCENES = [
    "locate missing people",
    "identify remains",
    "comfort families",
    "clear safe paths",
    "negotiate with officials or factions",
    "recover keepsakes",
    "document what happened",
    "resolve survivor guilt or witness accounts",
    "decide who gets limited help first",
    "handle TNN questions",
    "protect families from cameras",
    "correct a false official statement",
]

ACTIVE_TIMERS = [
    "6 rounds before the target is moved or the structure shifts",
    "10 minutes before guards relocate the target",
    "1 hour before the medical/ritual condition degrades",
    "before shift change",
    "before the next collapse/fire surge/rift pulse",
]

NEWS_ANGLES = [
    "survivors pulled from danger",
    "families demand answers",
    "questions raised over delayed response",
    "heroes or opportunists?",
    "sponsor claims credit",
    "opponent blamed for preventable suffering",
    "official denial contradicted by witness interview",
]


def _db_rows(query: str, params: tuple = ()) -> List[Dict]:
    try:
        from src.db_api import raw_query
        return raw_query(query, params) or []
    except Exception as e:
        logger.warning(f"[RESCUE] DB read failed: {e}")
        return []


def _json_col(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return default
    return default


GENERIC_PLAN_MARKERS = {
    "trapped civilians",
    "missing family",
    "injured courier",
    "generic rescue",
    "needs extraction",
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
    terms = []
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9'’.-]*(?:\s+[A-Z][A-Za-z0-9'’.-]*){0,4}\b", text):
        term = match.group(0).strip()
        if term.lower() not in {"mission", "rescue", "standard", "posted"} and term not in terms:
            terms.append(term)
    stakes = re.findall(r"[^.!?\n]*(?:rescue|extract|save|hostage|captive|missing|injured|evacuate|ritual|timer|family|survivor|condition)[^.!?\n]*", text, flags=re.I)
    return {"full_text": text[:1800], "canon_terms": terms[:14], "stakes": [s.strip() for s in stakes[:6] if s.strip()]}


def _specificity_score(plan: Dict[str, Any], context: Dict[str, Any]) -> int:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    score = 0
    for term in context.get("canon_terms", []):
        if term.lower() in blob:
            score += 2
    for stake in context.get("stakes", []):
        words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", stake)[:4]]
        if words and any(w in blob for w in words):
            score += 1
    return score


def _is_generic_plan(plan: Dict[str, Any], context: Dict[str, Any]) -> bool:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    has_context = bool(context.get("canon_terms") or context.get("stakes"))
    score = _specificity_score(plan, context)
    if has_context and score >= 3:
        # Anchored in mission canon -- markers alone cannot reject it. The
        # fallback fields merged into partial LLM plans contain some of our own
        # markers, so a marker hit on an anchored plan is self-poisoning, not
        # a signal the plan is generic.
        return False
    return (has_context and score < 3) or any(marker in blob for marker in GENERIC_PLAN_MARKERS)


def _party_strength() -> Dict[str, Any]:
    rows = _db_rows("SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC")
    pcs = []
    for row in rows:
        snap = _json_col(row.get("snapshot_json"), {})
        if not isinstance(snap, dict):
            continue
        level = int(snap.get("total_level") or 0)
        if level <= 0:
            continue
        pcs.append({"name": snap.get("name") or row.get("char_name"), "level": level, "max_hp": int(snap.get("max_hp") or 0)})
    levels = [p["level"] for p in pcs] or [5]
    return {"party_size": len(pcs) or 4, "avg_level": round(sum(levels) / len(levels), 1), "max_level": max(levels), "pcs": pcs}


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    return f"Live party read: {strength['party_size']} PCs, average level {strength['avg_level']}, max level {strength['max_level']}."


def _factions() -> List[Dict]:
    rows = _db_rows("SELECT faction_name, reputation_score, tier, leader, location_name, description FROM faction_reputation ORDER BY faction_name")
    return rows or [{"faction_name": "Adventurers Guild"}, {"faction_name": "Tower Authority"}, {"faction_name": "Patchwork Saints"}]


def _canon(name: str, factions: List[Dict]) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    for row in factions:
        fname = row.get("faction_name") or ""
        if low == fname.lower() or low in fname.lower() or fname.lower() in low:
            return fname
    return raw


def _resolve_roles(mission: dict) -> Dict[str, str]:
    factions = _factions()
    sponsor = _canon(mission.get("faction") or mission.get("sponsor_faction") or "", factions)
    if not sponsor:
        sponsor = random.choice([f["faction_name"] for f in factions if f.get("faction_name")])
    obstacle = _canon(mission.get("opposing_faction") or mission.get("blocking_faction") or "", factions)
    if not obstacle:
        choices = [f["faction_name"] for f in factions if f.get("faction_name") and f["faction_name"] != sponsor]
        obstacle = random.choice(choices or ["Unknown Threat"])
    return {"sponsor": sponsor, "obstacle": obstacle}


def _pick_subtype(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    if any(k in text for k in ("cleanup", "aftermath", "families", "remains", "reporter")):
        return "cleanup_rescue"
    if "missing" in text:
        return "missing_person"
    if "hostage" in text:
        return "hostage_negotiation"
    if any(k in text for k in ("prison", "jail", "cell")):
        return "prison_break"
    if any(k in text for k in ("ritual", "cursed", "soul", "spirit")):
        return "cursed_ritual"
    if any(k in text for k in ("fire", "collapse", "rift", "flood", "disaster")):
        return "disaster_area"
    return random.choice(list(SUBTYPES.keys()))


def _pick_target(subtype: str, roles: Dict[str, str]) -> Dict[str, str]:
    if subtype in ("missing_person", "cleanup_rescue"):
        rows = _db_rows("SELECT person_name, last_seen_location, status FROM missing_persons WHERE status <> 'found' ORDER BY RAND() LIMIT 1")
        if rows:
            r = rows[0]
            return {"name": r.get("person_name"), "type": "missing person", "detail": f"last seen: {r.get('last_seen_location')}; status: {r.get('status')}"}
    if subtype in ("captive_extraction", "medical_extraction", "hostage_negotiation", "cursed_ritual"):
        rows = _db_rows(
            "SELECT name, faction, role, location, status FROM npcs WHERE status IN ('alive','injured','undead','doppelganger') ORDER BY RAND() LIMIT 1"
        )
        if rows:
            r = rows[0]
            return {"name": r.get("name"), "type": "NPC/person", "detail": f"{r.get('role') or 'unknown role'}; faction: {r.get('faction')}; location: {r.get('location')}"}
    if subtype == "battlefield_pullout":
        rows = _db_rows("SELECT party_name, profile_json, members_json FROM party_profiles WHERE status='active' ORDER BY RAND() LIMIT 1")
        if rows:
            r = rows[0]
            profile = _json_col(r.get("profile_json"), {}) or _json_col(r.get("members_json"), {})
            members = profile.get("members") if isinstance(profile, dict) else []
            return {"name": r.get("party_name"), "type": "adventuring party", "detail": f"{len(members or [])} members reported pinned or missing"}
    if subtype in ("cleanup_rescue", "cursed_ritual"):
        rows = _db_rows("SELECT npc_name, died_at, resurrect_at, status FROM resurrection_queue WHERE status='pending' ORDER BY RAND() LIMIT 1")
        if rows:
            r = rows[0]
            return {"name": r.get("npc_name"), "type": "body/remains/spirit", "detail": f"resurrection queue status: {r.get('status')}"}
    return {"name": random.choice(["trapped civilians", "a missing family", "an injured courier", "a sentient construct", "a bound memory-soul"]), "type": random.choice(TARGET_TYPES), "detail": "generated fallback target"}


def _pick_location(subtype: str, target: Dict[str, str]) -> Dict[str, Any]:
    if target.get("detail") and "last seen:" in target["detail"]:
        loc = target["detail"].split("last seen:", 1)[-1].split(";", 1)[0].strip()
        rows = _db_rows("SELECT district, place_type, name, type_tag, description, wealth_level FROM gazetteer_places WHERE name LIKE %s OR description LIKE %s ORDER BY RAND() LIMIT 1", (f"%{loc}%", f"%{loc}%"))
        if rows:
            return rows[0]
    tags = ["clinic", "shrine", "warehouse", "warrens", "checkpoint", "tower", "market", "park", "mall", "archive"]
    where = " OR ".join(["LOWER(name) LIKE %s OR LOWER(description) LIKE %s"] * len(tags))
    params = []
    for tag in tags:
        params.extend([f"%{tag}%", f"%{tag}%"])
    rows = _db_rows(f"SELECT district, place_type, name, type_tag, description, wealth_level FROM gazetteer_places WHERE {where} ORDER BY RAND() LIMIT 1", tuple(params))
    if not rows:
        rows = _db_rows("SELECT district, place_type, name, type_tag, description, wealth_level FROM gazetteer_places ORDER BY RAND() LIMIT 1")
    return rows[0] if rows else {"district": "Outer Wall", "name": "an unstable rescue site", "description": "A dangerous place where someone needs help now."}


def _mode(subtype: str) -> str:
    return SUBTYPES[subtype]["mode"]


def _needs_map(subtype: str) -> bool:
    return True  # all rescue subtypes get a map — active gets combat map, aftermath gets site map


_RESCUE_MAP_TYPE: dict = {
    "captive_extraction":   "dungeon",
    "prison_break":         "dungeon",
    "cursed_ritual":        "dungeon",
    "hostage_negotiation":  "interior",
    "medical_extraction":   "interior",
    "disaster_area":        "exterior",
    "battlefield_pullout":  "exterior",
    "cleanup_rescue":       "street",
    "missing_person":       "interior",
}


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


async def _ollama(prompt: str, tokens: int = 1200) -> str:
    payload = {"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False, "options": {"temperature": 0.85, "num_predict": tokens, "num_ctx": _fit_ctx(prompt, tokens)}}
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("rescue_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[RESCUE] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[RESCUE] Ollama error: {e}")
        return ""


def _parse_json(raw: str) -> Optional[dict]:
    raw = re.sub(r"[“”]", '"', raw or "")
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


def _db_captor_stat_block(mission: dict, fallback_name: str) -> Optional[Dict[str, Any]]:
    rows = logical_enemy_roster_for_mission(
        mission,
        count=1,
        prefer_faction_roles=True,
        prefer_void=any(w in str(mission).lower() for w in ("void", "rift", "corrupt")),
    )
    if not rows:
        return None
    m = rows[0]
    abilities = []
    if m.get("actions"):
        abilities.extend([p.strip() for p in str(m["actions"]).split("\n\n") if p.strip()][:2])
    if m.get("traits"):
        abilities.append(str(m["traits"]).split("\n\n")[0])
    return {
        "name": m.get("name") or fallback_name,
        "cr": str(m.get("cr") or "2"),
        "hp": int(m.get("hp") or 45),
        "ac": int(m.get("ac") or 14),
        "abilities": abilities or ["Multiattack", "Alert - can't be surprised"],
        "special": m.get("notes") or "DB-backed captor; re-skin faction markings to the active obstacle.",
    }


def _fallback_plan(mode: str, roles: Dict[str, str], target: Dict[str, str], location: Dict[str, Any], mission: Optional[dict] = None) -> Dict[str, Any]:
    mission_context = _mission_context(mission or {})
    canon = ", ".join(mission_context.get("canon_terms", [])[:6]) or target["name"]
    _stakes = mission_context.get("stakes") or [f"{target['name']} must come out alive, whole, witnessed, or properly recovered"]
    stake = _stakes[0]
    if mode == "aftermath":
        return {
            "briefing": f"{roles['sponsor']} needs help finding answers around {location.get('name')} for {canon}. This is not a fight; it is grief, paperwork, families, and the truth.",
            "timer": "over the next few days, before public attention moves on",
            "target_state": f"{target['name']} is in aftermath status; the table needs dignity, identification, family answers, and proof.",
            "rescue_clock": ["families wait for news", "official story hardens", "TNN turns grief into spectacle", f"stake escalates: {stake}"],
            "extraction_standard": "Success means the right person/body/spirit/story is located, witnessed, and handed to the right people with dignity.",
            "captor_or_pressure": roles["obstacle"],
            "scenes": random.sample(AFTERMATH_SCENES, 6),
            "hazards_or_pressures": ["families need answers", "TNN presses for a dramatic angle", "officials withhold details", "limited help must be prioritized"],
            "survivor_quote": "I just need someone to say they looked.",
            "family_quote": "Do not let them become a number.",
            "official_quote": "The situation is under review.",
            "tnn_question": "Did the city fail these people before you ever arrived?",
            "news_memory_seed": f"Rescue crews and adventurers searched {location.get('name')} for {target['name']}, while families and TNN demanded answers.",
            "debrief": "Payment depends on dignity, answers, and who the party protected from the cameras.",
            "scene_skill_checks": [
                {"scene": "locate missing", "skill": "Investigation or Survival (DC 13)", "consequence": "lose a day — public story hardens"},
                {"scene": "comfort families", "skill": "Persuasion or Insight (DC 12)", "consequence": "family goes to TNN instead"},
                {"scene": "clear officials", "skill": "Persuasion or Intimidation (DC 14)", "consequence": "access denied — slower route needed"},
            ],
            "captor_stat_block": {
                "name": "None (aftermath mode)",
                "cr": "—",
                "hp": 0,
                "ac": 0,
                "abilities": [],
                "special": "No active combatant. Conflict in aftermath mode is social and bureaucratic.",
            },
        }
    db_captor = _db_captor_stat_block(mission or {}, roles["obstacle"])
    return {
        "briefing": f"{target['name']} needs extraction from {location.get('name')}. Preserve mission-specific stakes around {canon}; move now, get them out, and do not let the situation degrade.",
        "timer": random.choice(ACTIVE_TIMERS),
        "target_state": f"{target['name']} starts vulnerable: {target.get('detail')}. Delay worsens condition or leverage.",
        "rescue_clock": ["target is located", "condition worsens or captor reacts", "route or bargain narrows", f"stake escalates: {stake}"],
        "extraction_standard": "Success requires target stabilized, route secured, witnesses or sponsor handoff confirmed, and condition recorded.",
        "captor_or_pressure": roles["obstacle"],
        "scenes": ["approach", "locate target", "clear immediate obstacle", "stabilize target", "extract", "public/TNN pressure", "handoff"],
        "hazards_or_pressures": ["unstable route", "target condition worsens", "blocking faction interference", "overhead coverage", "panicked witnesses"],
        "survivor_quote": "I heard someone coming and made myself stay awake.",
        "family_quote": "Bring them back. I do not care what it costs.",
        "official_quote": "We had teams moving as fast as procedure allowed.",
        "tnn_question": "Are you rescuers, or are you cleaning up someone else's negligence?",
        "news_memory_seed": f"{target['name']} was pulled from danger at {location.get('name')} under {roles['sponsor']} sponsorship.",
        "debrief": "Pay and reputation depend on condition, speed, and how public the rescue became.",
        "scene_skill_checks": [
            {"scene": "approach",        "skill": "Stealth (DC 14)",         "consequence": "guards alerted, timer reduced by 1 stage"},
            {"scene": "locate target",   "skill": "Perception or Investigation (DC 13)", "consequence": "lose 2 rounds — target condition worsens"},
            {"scene": "clear obstacle",  "skill": "Athletics or Persuasion (DC 15)", "consequence": "obstacle blocks extraction route"},
            {"scene": "stabilize",       "skill": "Medicine (DC 12)",         "consequence": "target degrades one condition step"},
            {"scene": "extract",         "skill": "Athletics or Deception (DC 14)", "consequence": "pursuit triggered or route closes"},
        ],
        "captor_stat_block": db_captor or {
            "name": roles["obstacle"],
            "cr": "2",
            "hp": 45,
            "ac": 14,
            "abilities": ["Multiattack (2 strikes)", "Alert — can't be surprised"],
            "special": "Falls back to guard the target if the party disables or flanks the patrol.",
        },
    }


def _normalize_plan(data: Optional[dict], mode: str, roles: Dict[str, str], target: Dict[str, str], location: Dict[str, Any], mission: dict) -> Dict[str, Any]:
    fallback = _fallback_plan(mode, roles, target, location, mission)
    if not isinstance(data, dict):
        return fallback
    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    for key in ("scenes", "hazards_or_pressures"):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    for key in ("rescue_clock",):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    if _is_generic_plan(plan, _mission_context(mission)):
        logger.warning("[RESCUE] Rejected generic plan; using mission-specific fallback")
        return fallback
    return plan


async def _generate_plan(mission: dict, subtype: str, roles: Dict[str, str], target: Dict[str, str], location: Dict[str, Any], strength: Dict[str, Any]) -> Dict[str, Any]:
    mode = _mode(subtype)
    mission_context = _mission_context(mission)
    prompt = f"""Write a D&D rescue mission module plan.

Subtype: {SUBTYPES[subtype]['label']}
Mode: {mode}
Mission canon that must be preserved: {mission_context}
Sponsor: {roles['sponsor']}
Obstacle/blocking faction: {roles['obstacle']}
Target: {target['name']} ({target['type']})
Target detail: {target['detail']}
Location: {location.get('name')} in {location.get('district')}
Live party: {strength['party_size']} PCs, avg level {strength['avg_level']}, max {strength['max_level']}

Rules:
- Active rescue may have immediate danger and tactical pressure.
- Cleanup-and-rescue / aftermath is emotional over days, not an active combat zone, and should not involve combat except verbal/social conflict.
- Rescue bulletins should feel urgent, expire within one day, and be high Kharma / low EC.
- Include TNN/reporters/interviews as appropriate.

Return JSON only:
{{
  "briefing": "2-3 paragraphs from the contact",
  "timer": "active countdown or aftermath timeframe",
  "target_state": "exact condition, leverage, wound, ritual status, or aftermath status of the rescued target",
  "rescue_clock": ["4 escalating rescue clock beats"],
  "extraction_standard": "what proves the rescue is complete",
  "captor_or_pressure": "who/what can stop or exploit the extraction",
  "scenes": ["5-8 scene beats"],
  "hazards_or_pressures": ["3-5 hazards, social pressures, or obstacles"],
  "survivor_quote": "short quote",
  "family_quote": "short quote",
  "official_quote": "short quote",
  "tnn_question": "intrusive or useful TNN question",
  "news_memory_seed": "1-2 sentence news-cycle memory candidate",
  "debrief": "how debrief changes by result",
  "scene_skill_checks": [
    {{"scene": "scene name", "skill": "Skill (DC XX)", "consequence": "what happens on failure"}}
  ],
  "captor_stat_block": {{
    "name": "captor/threat name",
    "cr": "challenge rating",
    "hp": 0,
    "ac": 0,
    "abilities": ["key combat ability 1", "key combat ability 2"],
    "special": "what makes this threat unique in a rescue context"
  }}
}}"""
    data = None
    for attempt in range(3):
        data = _parse_json(await _ollama(prompt))
        if data:
            break
        logger.warning(f"[RESCUE] LLM returned no usable plan (attempt {attempt + 1}/3) for '{mission.get('title', 'Rescue')}'")
        await asyncio.sleep(2)
    if not data:
        logger.warning("[RESCUE] LLM unavailable after retries; using mission-faithful fallback")
    return _normalize_plan(data, mode, roles, target, location, mission)


async def _generate_map(subtype: str, location: Dict[str, Any], out_dir: Path) -> Optional[Path]:
    out = out_dir / "rescue_map.png"
    from src.battle_map_library import copy_library_map_for_mission
    map_type = _RESCUE_MAP_TYPE.get(subtype, "")
    return copy_library_map_for_mission(
        {"faction": location.get("faction", "")},
        out,
        mission_type="rescue",
        location_name=location.get("name", ""),
        district=location.get("district", ""),
        description=f"{subtype} {location.get('description', '')}",
        map_type=map_type,
    )

def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _card(title: str, body: str, color: str) -> str:
    return f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;padding:14px 18px;margin:14px 0;background:#fff;"><h2 style="margin:0 0 8px;color:{color};">{title}</h2>{body}</div>'


def _table(rows: List[tuple]) -> str:
    body = "".join(f'<tr><td style="padding:6px 8px;font-weight:bold;">{_e(a)}</td><td style="padding:6px 8px;">{_e(b)}</td></tr>' for a, b in rows)
    return f'<table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody>{body}</tbody></table>'


def _map_html(path: Optional[Path], out_dir: Path, fc: str, dm: bool) -> str:
    points = [("T", "target", 52, 42, "#7b1e1e"), ("H", "hazard", 35, 55, "#b8923a"), ("E", "extraction exit", 82, 78, "#2a6a2a"), ("C", "coverage / crowd", 20, 22, "#3a6898")]
    if not path or not path.exists():
        return "<ul>" + "".join(f"<li><strong>{_e(a)}</strong> - {_e(b)}</li>" for a, b, *_ in points) + "</ul>"
    rel = path.relative_to(out_dir)
    markers = ""
    if dm:
        for label, name, x, y, color in points:
            markers += f'<div title="{_e(name)}" style="position:absolute;left:{x}%;top:{y}%;transform:translate(-50%,-50%);width:30px;height:30px;border-radius:50%;background:{color};color:white;font-weight:bold;display:flex;align-items:center;justify-content:center;border:2px solid white;box-shadow:0 1px 5px #000;">{label}</div>'
    title = "DM Reference Map - target, hazards, extraction, coverage" if dm else "Player Map - active rescue site"
    return f'<div style="margin:16px 0;"><div style="font-weight:bold;margin-bottom:6px;color:{("#7b1e1e" if dm else fc)};">{title}</div><div style="position:relative;display:inline-block;max-width:100%;"><img src="{rel}" style="max-width:100%;border:3px solid {("#7b1e1e" if dm else fc)};border-radius:8px;" alt="Rescue Map">{markers}</div></div>'


def render_rescue_module(mission: dict, subtype: str, roles: Dict[str, str], target: Dict[str, str], location: Dict[str, Any], plan: Dict[str, Any], strength: Dict[str, Any], map_path: Optional[Path], out_dir: Path) -> str:
    title = mission.get("title", "Rescue")
    fc = _faction_color(roles["sponsor"])
    mode = _mode(subtype)
    scenes = "".join(f"<li>{_e(s)}</li>" for s in plan.get("scenes", []))
    pressures = "".join(f"<li>{_e(s)}</li>" for s in plan.get("hazards_or_pressures", []))
    map_section = ""
    if _needs_map(subtype):
        map_section = _card("Active Rescue Map", _map_html(map_path, out_dir, fc, False) + _map_html(map_path, out_dir, fc, True), fc)
    else:
        map_section = _card("Aftermath Scene Mode", "<p>No tactical map generated; do not spend compute on a non-active area. Run this through scenes, interviews, families, officials, and TNN pressure.</p>", fc)
    body = ""
    body += _card("Briefing", f'<div style="white-space:pre-line;font-style:italic;">{_e(plan["briefing"])}</div>', fc)
    body += _card("Urgency / Bulletin Note", "<p>Rescue bulletins should expire within one day. Reward profile: high Kharma, low EC.</p>", "#7b1e1e")
    body += _card("Live Party Scaling", f'<p>{_e(_party_scaling_note(strength))} Condition pressure and active rescue difficulty use this read.</p>', "#3a6898")
    body += _card("Target", _table([("Subtype", SUBTYPES[subtype]["label"]), ("Mode", mode), ("Target", target["name"]), ("Type", target["type"]), ("Detail", target["detail"]), ("Location", f"{location.get('name')} - {location.get('district')}"), ("Timer / timeframe", plan["timer"])]), "#8a5a1f")
    body += _card("Rescue Standard", _table([("Target State", plan.get("target_state", "")), ("Captor / Pressure", plan.get("captor_or_pressure", "")), ("Complete When", plan.get("extraction_standard", ""))]) + "<h3>Rescue Clock</h3><ul>" + "".join(f"<li>{_e(x)}</li>" for x in plan.get("rescue_clock", [])) + "</ul>", "#2a6a2a")
    body += _card("Condition Track", _table(CONDITION_TRACK), "#7b1e1e")
    body += _card("Scenes", f"<ol>{scenes}</ol><h3>Hazards / Pressures</h3><ul>{pressures}</ul>", "#555")
    if plan.get("scene_skill_checks"):
        sc_rows = [
            (c.get("scene", ""),
             f"{c.get('skill', '')} | "
             f"Setup: {c.get('setup') or 'Attempt the check to clear this beat of the rescue.'} | "
             f"On Success: {c.get('success') or 'the beat goes clean -- the team keeps the clock and moves on.'} | "
             f"On Failure: {c.get('consequence', '')}")
            for c in plan["scene_skill_checks"]
        ]
        body += _card("Scene Skill Checks", _table(sc_rows), "#3a6898")
    cstat = plan.get("captor_stat_block") or {}
    if cstat and cstat.get("name") and cstat.get("cr") != "—":
        abilities_html = "<ul>" + "".join(f"<li>{_e(a)}</li>" for a in (cstat.get("abilities") or [])) + "</ul>"
        body += _card(
            f"Captor / Threat Stat Block — {_e(cstat.get('name', ''))}",
            _table([("CR", cstat.get("cr", "")), ("HP", str(cstat.get("hp", ""))), ("AC", str(cstat.get("ac", "")))]) + "<h4>Abilities</h4>" + abilities_html + f"<p><strong>Special:</strong> {_e(cstat.get('special', ''))}</p>",
            "#7b1e1e",
        )
    body += map_section
    body += _card("Reporter / TNN Pressure", _table(REPORTER_TRACK) + f'<p><strong>TNN question:</strong> {_e(plan["tnn_question"])}</p>', "#3a6898")
    body += _card("Interviews", _table([("Survivor", plan["survivor_quote"]), ("Family", plan["family_quote"]), ("Official / faction", plan["official_quote"]), ("Party response", '<textarea rows="2" style="width:100%;font-family:inherit;"></textarea>')]), "#555")
    body += _card("News Cycle Seed", f'<p>{_e(plan["news_memory_seed"])}</p><p><strong>Angle options:</strong> {_e(", ".join(random.sample(NEWS_ANGLES, 3)))}</p>', "#8a5a1f")
    body += _card("Debrief", f'<p>{_e(plan["debrief"])}</p><p><strong>Condition result:</strong> <select><option>Safe for now</option><option>At risk</option><option>Injured / damaged</option><option>Critical</option><option>Lost / dead / unrecoverable</option></select></p><p><strong>Reporter pressure:</strong> <select><option>Respectful distance</option><option>Circling</option><option>Intrusive</option><option>Exploitative headline</option><option>Public backlash</option></select></p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Debrief notes..."></textarea>', "#2a6a2a")
    from src.treasure import loot_card as _loot_card
    body += _loot_card(mission)
    return _page(title, body, roles["sponsor"], mission_id=mission.get("id"))


def render_rescue_session(mission: dict, subtype: str, roles: Dict[str, str], target: Dict[str, str], plan: Dict[str, Any], strength: Dict[str, Any], map_path: Optional[Path], out_dir: Path) -> str:
    title = mission.get("title", "Rescue")
    fc = _faction_color(roles["sponsor"])
    scenes = "".join(f'<li><input type="checkbox"> {_e(s)}</li>' for s in plan.get("scenes", []))
    body = f'<h1 style="color:{fc};">{_e(title)}</h1>'
    body += _card("Target", f'<p><strong>{_e(target["name"])}</strong> - {_e(target["type"])}</p><p>{_e(plan["timer"])}</p><p>{_e(_party_scaling_note(strength))}</p>', fc)
    if _needs_map(subtype):
        body += _card("Map", _map_html(map_path, out_dir, fc, False), fc)
    body += _card("Scenes", f"<ol>{scenes}</ol>", "#555")
    body += _card("Condition / TNN", '<p><strong>Condition:</strong> <select><option>Safe for now</option><option>At risk</option><option>Injured / damaged</option><option>Critical</option><option>Lost / dead / unrecoverable</option></select></p><p><strong>TNN pressure:</strong> <select><option>Respectful distance</option><option>Circling</option><option>Intrusive</option><option>Exploitative headline</option><option>Public backlash</option></select></p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Session/interview notes..."></textarea>', "#7b1e1e")
    return _page(title, body, roles["sponsor"], mission_id=mission.get("id"))


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


async def build_rescue_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Rescue")
    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    strength = _party_strength()
    roles = _resolve_roles(mission)
    subtype = _pick_subtype(mission)
    target = _pick_target(subtype, roles)
    location = _pick_location(subtype, target)
    plan = await _generate_plan(mission, subtype, roles, target, location, strength)

    logger.info(f"[RESCUE] Building {title!r} | subtype={subtype} | mode={_mode(subtype)} | target={target['name']}")

    map_path = None
    try:
        map_path = await _generate_map(subtype, location, out_dir)
    except Exception as _mpe:
        logger.warning(f"[RESCUE] Map generation failed: {_mpe}")

    from src.mission_builder.mimir_module import create_module as _mc, enrich_monsters as _me, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd, enrich_mission_loot as _mel
    _mimir_id = await _mc(mission, mission_type="rescue")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Rescue Map")
    # Captor forces from the DB roster -> real stat blocks in Mimir/DDB.
    # Aftermath-mode rescues have no active combatant, so those skip enrichment.
    _c_enemies = []
    if _mode(subtype) != "aftermath":
        try:
            from src.mission_builder.monster_roster import mission_enemy_entry as _mee
            _rows = logical_enemy_roster_for_mission(
                mission, count=2, prefer_faction_roles=True,
                prefer_void=any(w in str(mission).lower() for w in ("void", "rift", "corrupt")),
            )
            _c_enemies = [_mee(m, count=1, notes=f"Captor force holding {target['name']}") for m in _rows or []]
        except Exception as _mre:
            logger.warning(f"[RESCUE] Captor enrichment skipped: {_mre}")
    _enriched = await _me(_mimir_id or "", _c_enemies) if _c_enemies else []
    module_html = render_rescue_module(mission, subtype, roles, target, location, plan, strength, map_path, out_dir)
    _loot_rewards = await _mel(_mimir_id or "", mission)
    module_html += _ms(_enriched, _loot_rewards, _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")
    session_html = render_rescue_session(mission, subtype, roles, target, plan, strength, map_path, out_dir)
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    dm_md = (
        f"## Rescue DM Guide\n"
        f"### Situation\n"
        f"- Sponsor: {roles['sponsor']}\n"
        f"- Subtype: {SUBTYPES[subtype]['label']}\n"
        f"- Mode: {_mode(subtype)}\n"
        f"- Target: {target['name']} ({target['type']})\n"
        f"- Timer / timeframe: {plan.get('timer', '')}\n\n"
        f"### Scenes\n"
        + "\n".join(f"- {s}" for s in plan.get("scenes", []))
        + "\n\n### Hazards / Pressures\n"
        + "\n".join(f"- {p}" for p in plan.get("hazards_or_pressures", []))
        + f"\n\n### TNN / News\n- Question: {plan.get('tnn_question', '')}\n- Seed: {plan.get('news_memory_seed', '')}\n\n"
        f"### Live Scaling\n{_party_scaling_note(strength)}"
    )
    players_md = (
        f"## Player Brief\n{plan.get('briefing', '')}\n\n"
        f"### Known Rescue Need\n"
        f"- Target: {target['name']}\n"
        f"- Location: {location.get('name')} - {location.get('district')}\n"
        f"- Timeframe: {plan.get('timer', '')}\n"
        f"- These jobs should feel urgent, high Kharma, and low EC.\n"
    )
    chart_md = (
        f"## Rescue Chart Pack\n"
        f"### Condition Track\n"
        + "\n".join(f"| {a} | {b} |" for a, b in CONDITION_TRACK)
        + "\n\n### Reporter Track\n"
        + "\n".join(f"| {a} | {b} |" for a, b in REPORTER_TRACK)
        + "\n\n### Interviews\n"
        f"- Survivor: {plan.get('survivor_quote', '')}\n"
        f"- Family: {plan.get('family_quote', '')}\n"
        f"- Official/faction: {plan.get('official_quote', '')}\n"
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, roles["sponsor"], dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, roles["sponsor"], players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, roles["sponsor"], chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",   "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",        "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Condition Track", "type": "custom",      "content": chart_md},
        ])
    maps_name = write_maps_page(out_dir, title, roles["sponsor"], [map_path] if map_path else [])
    box_components = component_links(has_maps=bool(maps_name))

    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title,
            faction=roles["sponsor"],
            tier=mission.get("tier", "standard"),
            cr=mission_cr(mission),
            player_name=mission.get("player_name", "") or "Open",
            chapters=[],
            components=box_components,
            chart_pack=None,
            map_count=1 if map_path else 0,
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as e:
        logger.warning(f"[RESCUE] index.html failed: {e}")
        index_path = out_dir / "module.html"

    try:
        from src.mission_builder.mission_db import write_module_slug_for_mission
        write_module_slug_for_mission(mission, out_dir.name, log_prefix="RESCUE")
    except Exception as e:
        logger.warning(f"[RESCUE] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    return index_path
