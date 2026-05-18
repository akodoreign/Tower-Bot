"""
first_contact_pipeline.py - standalone pipeline for Tower Contact missions.

First Contact covers newly recycled/generated people, races, societies, world
fragments, refugees, scouts, or communities that have never seen the Tower.
"""

from __future__ import annotations

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

KEYWORDS = {"first contact", "first-contact", "contact", "new arrivals", "new people", "new race", "tower contact", "refugees", "unknown race"}


def is_first_contact_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in KEYWORDS)


CONTACT_TYPES = {
    "stranded_community": "a small community recycled into the Tower with homes, customs, and panic intact",
    "scout_party": "armed scouts from a world that thinks the Tower is an invasion",
    "refugees": "frightened survivors who need shelter and explanation",
    "envoys": "diplomats or ritual representatives trying to understand where they are",
    "children_or_civilians": "noncombatants who need protection before politics",
    "nonhuman_people": "a species/race with unfamiliar senses, language, body rules, or taboos",
}

PANIC_STATES = [
    ("Calm curiosity", "They are scared, but listening."),
    ("Fearful confusion", "They follow gestures but misunderstand motives."),
    ("Protective clustering", "They hide children, elders, sacred items, or leaders."),
    ("Defensive posture", "They expect violence and prepare for it."),
    ("Panic break", "They flee, attack, or trigger a cultural emergency response."),
]

TOWER_PRIMER = [
    "The Tower and Dome are real and visible civic facts, not mythology.",
    "Factions are not nations, but they behave like powers.",
    "Adventurers are recognized workers who take posted missions.",
    "EC is money; many new arrivals will not know how to use it.",
    "Kharma is faith/social energy and often matters more for protection work.",
    "TNN and public attention can help or exploit them.",
    "Warrens, Outer Wall, and rift zones are dangerous until proven otherwise.",
    "A contract is not always a trap, but they should read who benefits.",
]

FOLLOW_UPS = ["Negotiation", "Rescue", "Escort", "Defense", "Investigation", "Exploration", "Discovery"]


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


def _db_rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        from src.db_api import raw_query
        return raw_query(sql, params) or []
    except Exception as e:
        logger.debug(f"[FIRST_CONTACT] DB read skipped: {e}")
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
    "new arrivals",
    "unknown group",
    "strange people",
    "generic first contact",
    "unfamiliar culture",
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
        if term.lower() not in {"mission", "first contact", "standard", "posted"} and term not in terms:
            terms.append(term)
    stakes = re.findall(r"[^.!?\n]*(?:refugee|new|contact|language|taboo|custom|shelter|panic|protect|exploit|trust|faction)[^.!?\n]*", text, flags=re.I)
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
    return (has_context and _specificity_score(plan, context) < 3) or any(marker in blob for marker in GENERIC_PLAN_MARKERS)


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
    return {"communicate": base + 2, "calm": base + 3, "protect": base + 2, "teach": base + 1, "custom": base + 4}


def _pick_type(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    for key in CONTACT_TYPES:
        if any(part in text for part in key.split("_")):
            return key
    return random.choice(list(CONTACT_TYPES))


def _pick_location() -> Dict[str, Any]:
    rows = _db_rows("SELECT district, place_type, name, type_tag, description, extra_json FROM gazetteer_places ORDER BY id DESC LIMIT 12")
    return random.choice(rows) if rows else {"district": "The Warrens", "name": "a newly generated street", "description": "A place that did not exist on yesterday's map."}


def _rift_fuel() -> List[Dict[str, Any]]:
    try:
        from src.news_feed import get_rift_mission_fuel
        return get_rift_mission_fuel(limit=5)
    except Exception:
        return []


async def _ollama(prompt: str, tokens: int = 2600) -> str:
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("first_contact_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[FIRST_CONTACT] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=240.0) as c:
            r = await c.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False, "options": {"temperature": 0.88, "num_predict": tokens}})
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"[FIRST_CONTACT] Ollama unavailable: {e}")
        return ""


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


async def _generate_plan(mission: dict, ctype: str, location: Dict[str, Any], dcs: Dict[str, int], strength: Dict[str, Any], rift_fuel: List[Dict[str, Any]]) -> Dict[str, Any]:
    mission_context = _mission_context(mission)
    prompt = f"""Create a D&D First Contact / Tower Contact mission as JSON only.
Mission: {mission.get('title', 'First Contact')}
Mission canon that must be preserved: {mission_context}
Contact type: {ctype} - {CONTACT_TYPES[ctype]}
Location from DB: {location}
Rift mission fuel from news cycle: {rift_fuel[:3]}
Party: {_party_note(strength)}
DCs: {dcs}

Include:
- briefing
- contact_identity: the exact people/community/entity being contacted, using mission canon
- contact_protocol: 5 ordered steps for safe first contact
- misunderstanding_ladder: 5 ways the first meeting can go wrong without becoming murder mode
- first_sight: 8 vivid visual/imaging descriptions
- who_they_are
- immediate_needs
- fears
- taboos
- translation_tracker: 5 stages
- panic_meter: 5 stages
- dialogue: 24 lines across first words, confusion, fear, teaching EC/Kharma, customs, faction warning, and trust
- tower_primer: what must be explained about EC, Kharma, factions, missions, Dome, TNN
- faction_risks: how factions might exploit/protect them
- protection_options
- follow_up
- news_seed
Use the named NPCs, places, factions, communities, and stakes from Mission canon. Do not replace them with generic arrival scaffolding.
Return JSON object only."""
    data = _parse_json(await _ollama(prompt))
    return _normalize_plan(data, mission, ctype)


def _fallback_plan(mission: dict, ctype: str) -> Dict[str, Any]:
    mission_context = _mission_context(mission)
    title = mission.get("title", "First Contact")
    canon = ", ".join(mission_context.get("canon_terms", [])[:6]) or title
    _stakes = mission_context.get("stakes") or [f"{canon} needs a safe first conversation before factions define them as an asset or threat"]
    stake = _stakes[0]
    return {
        "briefing": f"{canon} has reached a first-contact moment. The job is to keep the meeting safe, protect consent, and stop the first public story from becoming exploitation.",
        "contact_identity": f"The contact subject is mission-specific: {canon}.",
        "contact_protocol": ["hands visible and weapons low", "ask permission before approaching vulnerable people", "exchange names before offers", "explain the Tower in plain words", "secure a quiet shelter before faction claims begin"],
        "misunderstanding_ladder": ["gesture is read as a threat", "translation invents a false promise", "a camera turns fear into public panic", "a faction agent speaks over the contact subject", f"the core stake escalates: {stake}"],
        "first_sight": ["They stand under the Dome like it is a second moon.", "Their children count exits before learning names.", "Their clothes smell like rain from a sky that is not here.", "Their leader keeps touching the ground to make sure it remains ground."],
        "who_they_are": CONTACT_TYPES[ctype],
        "immediate_needs": ["safety", "water", "translation", "privacy", "proof the party is not captors"],
        "fears": ["being sold", "being trapped", "losing their dead", "unknown gods", "TNN cameras"],
        "taboos": ["do not touch face markings", "do not count children aloud", "do not name the lost world casually"],
        "translation_tracker": ["gesture exchange", "shared nouns", "danger words", "trust phrases", "contract language"],
        "panic_meter": [s for s, _ in PANIC_STATES],
        "dialogue": ["New arrival: Is this a prison or a sky?", "Child: Why is your sun broken?", "Party line: EC is money. Kharma is harder to explain.", "Elder: Your factions sound like hungry houses.", "TNN: Can we get a statement?", "Warden: No cameras near the children."],
        "tower_primer": TOWER_PRIMER,
        "faction_risks": ["Glass Sigil wants records", "Iron Fang wants contract rights", "Wardens want safety", "Saints want shelter", "Lotus wants deniability"],
        "protection_options": ["quiet shelter", "faction sponsor", "public sanctuary", "escort to safe district", "formal negotiation"],
        "follow_up": random.choice(FOLLOW_UPS),
        "news_seed": "New arrivals from a recycled world fragment have forced questions about protection, economy, and first contact protocols.",
    }


def _normalize_plan(data: Optional[Dict[str, Any]], mission: dict, ctype: str) -> Dict[str, Any]:
    fallback = _fallback_plan(mission, ctype)
    if not isinstance(data, dict):
        return fallback
    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    for key in (
        "first_sight",
        "immediate_needs",
        "fears",
        "taboos",
        "translation_tracker",
        "panic_meter",
        "dialogue",
        "tower_primer",
        "faction_risks",
        "protection_options",
    ):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    for key in ("contact_protocol", "misunderstanding_ladder"):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    if _is_generic_plan(plan, _mission_context(mission)):
        logger.warning("[FIRST_CONTACT] Rejected generic plan; using mission-specific fallback")
        return fallback
    return plan


def _e(v: Any) -> str:
    import html
    return html.escape(str(v or ""))


def _card(title: str, body: str, color: str = "#3a6898") -> str:
    return f'<div style="border-left:4px solid {color};padding:12px 16px;margin:14px 0;background:#fafafa;border-radius:0 6px 6px 0;"><h2 style="margin:0 0 8px;color:{color};">{_e(title)}</h2>{body}</div>'


def _ul(items: List[Any]) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _table(rows: List[tuple]) -> str:
    return "<table>" + "".join(f"<tr><td><strong>{_e(a)}</strong></td><td>{_e(b)}</td></tr>" for a, b in rows) + "</table>"


def render_module(mission: dict, ctype: str, location: Dict[str, Any], plan: Dict[str, Any], dcs: Dict[str, int], strength: Dict[str, Any]) -> str:
    title = mission.get("title", "First Contact")
    faction = mission.get("faction", "Patchwork Saints")
    fc = _faction_color(faction)
    body = ""
    body += _card("Briefing", f"<p>{_e(plan.get('briefing'))}</p><p>{_e(_party_note(strength))}</p>", fc)
    body += _card("Where Contact Happens", f"<p><strong>{_e(location.get('name'))}</strong> - {_e(location.get('district'))}</p><p>{_e(location.get('description'))}</p>", "#8a5a1f")
    body += _card("Contact Protocol", f"<p><strong>{_e(plan.get('contact_identity'))}</strong></p><h3>Protocol</h3>{_ul(plan.get('contact_protocol', []))}<h3>Misunderstanding Ladder</h3>{_ul(plan.get('misunderstanding_ladder', []))}", "#2a6a2a")
    body += _card("First Sight Imagery", _ul(plan.get("first_sight", [])), "#555")
    body += _card("Who They Are", f"<p>{_e(plan.get('who_they_are'))}</p>", "#3a6898")
    body += _card("Needs, Fears, Taboos", "<h3>Needs</h3>" + _ul(plan.get("immediate_needs", [])) + "<h3>Fears</h3>" + _ul(plan.get("fears", [])) + "<h3>Taboos</h3>" + _ul(plan.get("taboos", [])), "#7b1e1e")
    body += _card("Translation / Panic", "<h3>Translation</h3>" + _ul(plan.get("translation_tracker", [])) + "<h3>Panic Meter</h3>" + _ul(plan.get("panic_meter", [])), "#2a6a2a")
    body += _card("Lots Of Dialogue", _ul(plan.get("dialogue", [])), "#555")
    body += _card("Teach The Tower", _ul(plan.get("tower_primer", TOWER_PRIMER)), "#8a5a1f")
    body += _card("Faction Risks / Protection", "<h3>Risks</h3>" + _ul(plan.get("faction_risks", [])) + "<h3>Protection Options</h3>" + _ul(plan.get("protection_options", [])) + f"<p><strong>Follow-up:</strong> {_e(plan.get('follow_up'))}</p>", "#3a6898")
    return _page(title, body, faction)


def render_session(mission: dict, plan: Dict[str, Any], dcs: Dict[str, int]) -> str:
    title = mission.get("title", "First Contact")
    faction = mission.get("faction", "Patchwork Saints")
    body = f"<h1>{_e(title)}</h1>"
    body += _card("Translation", "".join(f"<p><input type='checkbox'> {_e(s)}</p>" for s in plan.get("translation_tracker", [])), "#2a6a2a")
    body += _card("Panic / Trust", "<p><strong>Panic:</strong> <select>" + "".join(f"<option>{_e(s)}</option>" for s in plan.get("panic_meter", [])) + "</select></p><p><strong>Trust established:</strong> <input type='checkbox'></p>", "#7b1e1e")
    body += _card("Teaching Notes", "<textarea rows='7' style='width:100%;font-family:inherit;' placeholder='EC, Kharma, factions, missions, Dome, TNN, customs...'></textarea>", "#8a5a1f")
    return _page(title, body, faction)


def _guides(plan: Dict[str, Any], dcs: Dict[str, int]) -> Dict[str, str]:
    return {
        "dm": "## First Contact DM Guide\n### Dialogue Bank\n" + "\n".join(f"- {x}" for x in plan.get("dialogue", [])) + "\n\n### Taboos\n" + "\n".join(f"- {x}" for x in plan.get("taboos", [])) + f"\n\n### News Seed\n{plan.get('news_seed')}",
        "players": f"## First Contact Player Guide\n### What Happened\n{plan.get('briefing')}\n\n### Immediate Needs\n" + "\n".join(f"- {x}" for x in plan.get("immediate_needs", [])) + "\n\n### What Must Be Explained\n" + "\n".join(f"- {x}" for x in plan.get("tower_primer", TOWER_PRIMER)),
        "chart": "## First Contact Chart Pack\n### DCs\n" + "\n".join(f"- {k}: {v}" for k, v in dcs.items()) + "\n\n### Panic States\n" + "\n".join(f"- {a}: {b}" for a, b in PANIC_STATES) + "\n\n### Tower Primer\n" + "\n".join(f"- {x}" for x in TOWER_PRIMER),
    }


async def build_first_contact_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "First Contact")
    faction = mission.get("faction", "Patchwork Saints")
    tier = mission.get("tier", "standard")
    if out_dir is None:
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    strength = _party_strength()
    dcs = _dc_profile(tier, strength)
    ctype = _pick_type(mission)
    location = _pick_location()
    plan = await _generate_plan(mission, ctype, location, dcs, strength, _rift_fuel())
    from src.mission_builder.mimir_module import create_module as _mc, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="first_contact")
    _html = render_module(mission, ctype, location, plan, dcs, strength) + _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(_html, encoding="utf-8")
    (out_dir / "session.html").write_text(render_session(mission, plan, dcs), encoding="utf-8")
    from src.mission_builder.boxset_utils import component_links, write_component
    guide = _guides(plan, dcs)
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, guide["dm"])
    write_component(out_dir, "players_guide", "Players Guide", title, faction, guide["players"])
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, guide["chart"])
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",         "type": "description", "content": guide["players"]},
            {"title": f"{title} — DM Notes",              "type": "dm_notes",    "content": guide["dm"]},
            {"title": f"{title} — Translation & Panic",   "type": "custom",      "content": guide["chart"]},
        ])
    from src.mission_builder.html_renderer import render_index
    index_html = render_index(title, faction, tier, mission_cr(mission), mission.get("player_name", "") or "Open", [], component_links(False), None, 0)
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    try:
        from src.db_api import raw_execute
        raw_execute("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as e:
        logger.warning(f"[FIRST_CONTACT] Could not write module_slug: {e}")
    with zipfile.ZipFile(out_dir.parent / f"{out_dir.name}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))
    return index_path
