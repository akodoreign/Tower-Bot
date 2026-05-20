"""
discovery_pipeline.py - standalone pipeline for strange objects, anomalies,
signals, impossible materials, living phenomena, and newly revealed truths.
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

KEYWORDS = {"discovery", "discover", "anomaly", "phenomenon", "artifact", "unknown", "signal", "specimen", "contain"}


def is_discovery_mission(mission_type: str) -> bool:
    return any(k in (mission_type or "").lower() for k in KEYWORDS)


DISCOVERY_TYPES = {
    "object": "a strange object, relic, sample, or impossible material",
    "phenomenon": "a field effect, signal, weather, echo, or repeating event",
    "biology": "unknown life, tissue, spores, eggs, symbiont, or specimen",
    "machine": "a mechanism, tower-grown device, gate component, or living tool",
    "memory": "a memory structure, recorded life, soul-vial echo, or copied experience",
    "truth": "evidence that changes what people believe about a place, faction, or world",
}

HANDLING_STATES = [
    "Stable while observed",
    "Leaks heat, light, sound, memory, or emotion",
    "Reacts to spellcasting",
    "Reacts to Kharma or prayer",
    "Changes when lied to",
    "Appears inert but is listening",
    "Wants to be returned",
    "Cannot cross running water or copper",
    "Duplicates small objects nearby",
    "Attracts faction attention within hours",
]

FACTION_CUSTODY = [
    "Wizards Tower wants testing rights",
    "Glass Sigil wants archive custody and secrecy",
    "Obsidian Lotus wants it hidden, moved, or memory-wiped",
    "Iron Fang wants enforceable ownership and transport insurance",
    "Wardens of Ash want public safety first",
    "Patchwork Saints want locals protected before scholars arrive",
    "Serpent Choir wants ritual interpretation",
    "Tower Authority wants chain of custody",
]

FOLLOW_UPS = ["Puzzle", "Investigation", "Negotiation", "Heist", "Infestation", "Rescue", "Exploration", "Defense"]


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


def _db_rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        from src.db_api import raw_query
        return raw_query(sql, params) or []
    except Exception as e:
        logger.debug(f"[DISCOVERY] DB read skipped: {e}")
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
    "strange discovery",
    "unknown object",
    "mysterious phenomenon",
    "something unusual",
    "generic discovery",
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
        if term.lower() not in {"mission", "discovery", "standard", "posted"} and term not in terms:
            terms.append(term)
    objects = re.findall(r"\b(?:relic|artifact|signal|specimen|engine|ledger|shard|sample|record|device|gate|memory|vial|core)\b", text, flags=re.I)
    stakes = re.findall(r"[^.!?\n]*(?:breach|collapse|stolen|missing|corrupt|danger|custody|public|panic|cover-up|proof|truth)[^.!?\n]*", text, flags=re.I)
    return {
        "full_text": text[:1800],
        "canon_terms": terms[:14],
        "objects": sorted({o.lower() for o in objects})[:8],
        "stakes": [s.strip() for s in stakes[:6] if s.strip()],
    }


def _specificity_score(plan: Dict[str, Any], context: Dict[str, Any]) -> int:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    score = 0
    for term in context.get("canon_terms", []):
        if term.lower() in blob:
            score += 2
    for obj in context.get("objects", []):
        if obj.lower() in blob:
            score += 1
    for stake in context.get("stakes", []):
        words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", stake)[:4]]
        if words and any(w in blob for w in words):
            score += 1
    return score


def _is_generic_plan(plan: Dict[str, Any], context: Dict[str, Any]) -> bool:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    has_context = bool(context.get("canon_terms") or context.get("objects") or context.get("stakes"))
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
    base = 12 + bump + max(0, int(strength["avg_level"]) - 5) // 3
    return {"identify": base + 2, "contain": base + 3, "transport": base + 4, "implication": base + 2}


def _pick_type(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    for key in DISCOVERY_TYPES:
        if key in text:
            return key
    if "signal" in text:
        return "phenomenon"
    if "memory" in text or "soul" in text:
        return "memory"
    return random.choice(list(DISCOVERY_TYPES))


def _pick_context() -> Dict[str, Any]:
    rows = _db_rows("SELECT district, place_type, name, type_tag, description, extra_json FROM gazetteer_places ORDER BY RAND() LIMIT 1")
    return rows[0] if rows else {"district": "Grand Forum", "name": "a secured examination room", "description": "A quiet room filled with people trying not to touch the wrong thing."}


def _rift_fuel() -> List[Dict[str, Any]]:
    try:
        from src.news_feed import get_rift_mission_fuel
        return get_rift_mission_fuel(limit=5)
    except Exception:
        return []


async def _ollama(prompt: str, tokens: int = 2200) -> str:
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("discovery_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[DISCOVERY] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=220.0) as c:
            r = await c.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False, "options": {"temperature": 0.85, "num_predict": tokens}})
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"[DISCOVERY] Ollama unavailable: {e}")
        return ""


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


async def _generate_plan(mission: dict, dtype: str, context: Dict[str, Any], dcs: Dict[str, int], strength: Dict[str, Any], rift_fuel: List[Dict[str, Any]]) -> Dict[str, Any]:
    mission_context = _mission_context(mission)
    prompt = f"""Create a D&D Discovery mission plan as JSON only.
Mission: {mission.get('title', 'Discovery')}
Mission canon that must be preserved: {mission_context}
Discovery type: {dtype} - {DISCOVERY_TYPES[dtype]}
Context from DB: {context}
Rift mission fuel from news cycle: {rift_fuel[:3]}
Party: {_party_note(strength)}
DCs: {dcs}

Include:
- briefing
- opening_read_aloud: 2-3 sentences the DM reads aloud when the party first encounters the discovery — sensory, immediate, specific to the mission
- actual_discovery: the exact mission-specific thing/truth found
- proof_standard: what proves it is real and not rumor
- changed_world_state: what changes after the party reports it
- surface_description
- first_imagery: 8 vivid descriptions
- identification_steps: 5 steps with skill, dc, success, failure
- containment_rules: 5 rules
- handling_states: 5 handling quirks
- implication_tree: 6 implications or truths
- faction_claims: 5 custody claims
- dialogue: 14 lines from scholars, witnesses, faction agents, and frightened locals
- fate_options: destroy/preserve/hide/return/publish/bargain style options
- news_seed
- follow_up
Use the named NPCs, objects, places, factions, and stakes from Mission canon. Do not replace them with generic discovery scaffolding.
Return JSON object only."""
    data = _parse_json(await _ollama(prompt))
    return _normalize_plan(data, mission, dtype, context, dcs)


def _fallback_plan(mission: dict, dtype: str, context: Dict[str, Any], dcs: Dict[str, int]) -> Dict[str, Any]:
    mission_context = _mission_context(mission)
    title = mission.get("title", "Discovery")
    canon = ", ".join(mission_context.get("canon_terms", [])[:6]) or title
    object_hint = ", ".join(mission_context.get("objects", [])[:3]) or DISCOVERY_TYPES[dtype]
    _stakes = mission_context.get("stakes") or [f"custody and public truth around {title}"]
    stake = _stakes[0]
    return {
        "briefing": f"Identify what {title} really revealed, preserve evidence tied to {canon}, and contain the consequences before rumor or misuse spreads.",
        "opening_read_aloud": f"Something is wrong with the air near {context.get('name', 'the site')} — the wrong kind of quiet, the wrong kind of light. You push forward and see it: {object_hint or DISCOVERY_TYPES[dtype]}, sitting in the open as if it has been waiting.",
        "actual_discovery": f"The party finds mission-specific proof involving {object_hint}; it is tied to {canon}.",
        "proof_standard": f"Success requires two independent signs: physical handling proof from {context.get('name')} and testimony or records tying the find to {canon}.",
        "changed_world_state": f"Once reported, {stake}",
        "surface_description": f"The discovery was found near {context.get('name')} and nobody agrees whether it is safe, legal, alive, or politically explosive.",
        "first_imagery": random.sample(HANDLING_STATES, 8),
        "identification_steps": [{"step": f"Test {i}", "skill": "Arcana, Investigation, Religion, or Nature", "dc": dcs["identify"], "success": "narrows classification", "failure": "triggers a handling quirk"} for i in range(1, 6)],
        "containment_rules": ["do not expose to direct spellcasting", "keep witness count low", "assign one handler", "record every change", "do not let rival factions take custody"],
        "handling_states": random.sample(HANDLING_STATES, 5),
        "implication_tree": ["it belongs to a recycled world", "it may be alive", "it proves a faction lied", "it can seed a puzzle", "it is useful and dangerous", "public panic is possible"],
        "faction_claims": random.sample(FACTION_CUSTODY, 5),
        "dialogue": ["Scholar: That is not inert. It is being polite.", "Witness: It hummed when I lied.", "Warden: Can it hurt civilians today?", "Archivist: Custody is not ownership.", "Local: If it came from my street, why can't I see it?"],
        "fate_options": ["destroy", "preserve", "hide", "return", "publish", "bargain"],
        "news_seed": "A strange discovery has triggered faction custody arguments and public safety questions.",
        "follow_up": random.choice(FOLLOW_UPS),
    }


def _normalize_plan(data: Optional[Dict[str, Any]], mission: dict, dtype: str, context: Dict[str, Any], dcs: Dict[str, int]) -> Dict[str, Any]:
    fallback = _fallback_plan(mission, dtype, context, dcs)
    if not isinstance(data, dict):
        return fallback
    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    for key in (
        "first_imagery",
        "containment_rules",
        "handling_states",
        "implication_tree",
        "faction_claims",
        "dialogue",
        "fate_options",
    ):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    steps = plan.get("identification_steps")
    if not isinstance(steps, list) or not steps or not all(isinstance(item, dict) for item in steps):
        plan["identification_steps"] = fallback["identification_steps"]
    if _is_generic_plan(plan, _mission_context(mission)):
        logger.warning("[DISCOVERY] Rejected generic plan; using mission-specific fallback")
        return fallback
    return plan


def _e(v: Any) -> str:
    import html
    return html.escape(str(v or ""))


def _card(title: str, body: str, color: str = "#3a6898") -> str:
    return f'<div style="border-left:4px solid {color};padding:12px 16px;margin:14px 0;background:#fafafa;border-radius:0 6px 6px 0;"><h2 style="margin:0 0 8px;color:{color};">{_e(title)}</h2>{body}</div>'


def _ul(items: List[Any]) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _step_table(steps: List[Dict[str, Any]]) -> str:
    return "<table><tr><th>Step</th><th>Skill</th><th>Success</th><th>Failure</th></tr>" + "".join(f"<tr><td>{_e(s.get('step'))}</td><td>{_e(s.get('skill'))} DC {_e(s.get('dc'))}</td><td>{_e(s.get('success'))}</td><td>{_e(s.get('failure'))}</td></tr>" for s in steps) + "</table>"


def render_module(mission: dict, dtype: str, context: Dict[str, Any], plan: Dict[str, Any], dcs: Dict[str, int], strength: Dict[str, Any]) -> str:
    title = mission.get("title", "Discovery")
    faction = mission.get("faction", "Wizards Tower")
    fc = _faction_color(faction)
    body = ""
    body += _card("Briefing", f"<p>{_e(plan.get('briefing'))}</p><p>{_e(_party_note(strength))}</p>", fc)
    if plan.get("opening_read_aloud"):
        body += _card("Read Aloud — First Encounter", f'<div style="font-style:italic;color:#333;">{_e(plan["opening_read_aloud"])}</div>', "#8a5a1f")
    body += _card("Actual Discovery", f"<p><strong>Discovery:</strong> {_e(plan.get('actual_discovery'))}</p><p><strong>Proof:</strong> {_e(plan.get('proof_standard'))}</p><p><strong>Changed World-State:</strong> {_e(plan.get('changed_world_state'))}</p>", "#2a6a2a")
    body += _card("Surface Description", f"<p>{_e(plan.get('surface_description'))}</p><p><strong>Context:</strong> {_e(context.get('name'))} - {_e(context.get('district'))}</p>", "#8a5a1f")
    body += _card("Imagery", _ul(plan.get("first_imagery", [])), "#555")
    body += _card("Identification Logic", _step_table(plan.get("identification_steps", [])), "#3a6898")
    body += _card("Containment Sheet", _ul(plan.get("containment_rules", [])) + "<h3>Handling States</h3>" + _ul(plan.get("handling_states", [])), "#7b1e1e")
    body += _card("Implication Tree", _ul(plan.get("implication_tree", [])), "#2a6a2a")
    body += _card("Faction Custody Claims", _ul(plan.get("faction_claims", [])), "#8a5a1f")
    body += _card("Dialogue", _ul(plan.get("dialogue", [])), "#555")
    body += _card("Fate Options", _ul(plan.get("fate_options", [])) + f"<p><strong>Follow-up:</strong> {_e(plan.get('follow_up'))}</p>", "#2a6a2a")
    return _page(title, body, faction)


def render_session(mission: dict, plan: Dict[str, Any], dcs: Dict[str, int]) -> str:
    title = mission.get("title", "Discovery")
    faction = mission.get("faction", "Wizards Tower")
    body = f"<h1>{_e(title)}</h1>"
    body += _card("Identification", "".join(f"<p><input type='checkbox'> {_e(s.get('step'))} - {_e(s.get('skill'))} DC {_e(s.get('dc'))}</p>" for s in plan.get("identification_steps", [])), "#3a6898")
    body += _card("Containment", "<textarea rows='5' style='width:100%;font-family:inherit;' placeholder='Containment actions, handling breaches, custody...'></textarea>", "#7b1e1e")
    body += _card("Final Fate", "<select><option>Destroy</option><option>Preserve</option><option>Hide</option><option>Return</option><option>Publish</option><option>Bargain</option></select>", "#2a6a2a")
    return _page(title, body, faction)


def _guides(dtype: str, context: Dict[str, Any], plan: Dict[str, Any], dcs: Dict[str, int]) -> Dict[str, str]:
    return {
        "dm": f"## Discovery DM Guide\n### Truth / Implications\n" + "\n".join(f"- {x}" for x in plan.get("implication_tree", [])) + "\n\n### Dialogue\n" + "\n".join(f"- {x}" for x in plan.get("dialogue", [])) + f"\n\n### News Seed\n{plan.get('news_seed')}",
        "players": f"## Discovery Player Guide\n### What Happened\n{plan.get('briefing')}\n\n### What Is Visible\n{plan.get('surface_description')}\n\n### Known Context\n{context.get('name')} in {context.get('district')}.",
        "chart": f"## Discovery Chart Pack\n### DCs\n" + "\n".join(f"- {k}: {v}" for k, v in dcs.items()) + "\n\n### Containment Rules\n" + "\n".join(f"- {x}" for x in plan.get("containment_rules", [])) + "\n\n### Custody Claims\n" + "\n".join(f"- {x}" for x in plan.get("faction_claims", [])),
    }


async def build_discovery_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Discovery")
    faction = mission.get("faction", "Wizards Tower")
    tier = mission.get("tier", "standard")
    if out_dir is None:
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    strength = _party_strength()
    dcs = _dc_profile(tier, strength)
    dtype = _pick_type(mission)
    context = _pick_context()
    plan = await _generate_plan(mission, dtype, context, dcs, strength, _rift_fuel())
    from src.mission_builder.mimir_module import create_module as _mc, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="discovery")
    _html = render_module(mission, dtype, context, plan, dcs, strength) + _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(_html, encoding="utf-8")
    (out_dir / "session.html").write_text(render_session(mission, plan, dcs), encoding="utf-8")
    from src.mission_builder.boxset_utils import component_links, write_component
    guide = _guides(dtype, context, plan, dcs)
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, guide["dm"])
    write_component(out_dir, "players_guide", "Players Guide", title, faction, guide["players"])
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, guide["chart"])
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",       "type": "description", "content": guide["players"]},
            {"title": f"{title} — DM Notes",            "type": "dm_notes",    "content": guide["dm"]},
            {"title": f"{title} — Factions & Fates",    "type": "custom",      "content": guide["chart"]},
        ])
    from src.mission_builder.html_renderer import render_index
    index_html = render_index(title, faction, tier, mission_cr(mission), mission.get("player_name", "") or "Open", [], component_links(False), None, 0)
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    try:
        from src.db_api import raw_execute
        raw_execute("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as e:
        logger.warning(f"[DISCOVERY] Could not write module_slug: {e}")
    with zipfile.ZipFile(out_dir.parent / f"{out_dir.name}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))
    return index_path
