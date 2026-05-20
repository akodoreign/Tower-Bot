"""
infiltration_pipeline.py - Social infiltration mission modules.

Infiltration is about playing a part: getting friendly, blending in, earning
access, extracting an item/person/information, then leaving before the cover
falls apart. It is RP-first. Maps are optional and only generated when the job
has an item room, secure objective room, or facility layout that benefits from
tactical positioning.

Exported:
    build_infiltration_module(mission: dict, out_dir: Path) -> Path
    is_infiltration_mission(mission_type: str) -> bool
"""

from __future__ import annotations

import os
import re
import json
import base64
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

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "generated_modules"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")


_INFILTRATION_KEYWORDS = {
    "infiltration", "infiltrate", "undercover", "blend in", "social entry",
    "impersonate", "get inside", "restricted access", "plant a listener",
    "observe meeting", "copy records", "extract information",
}


def is_infiltration_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _INFILTRATION_KEYWORDS)


OBJECTIVES = [
    "extract an item",
    "extract information",
    "extract a person",
    "plant an item, listener, or false record",
    "observe a meeting",
    "befriend or influence an NPC",
    "verify a rumor",
    "map the inside for a future job",
    "alter access permissions or credentials",
    "identify a traitor or mole",
    "swap a guest list",
    "acquire a signature or seal",
    "gain blackmail material",
    "test security response",
    "deliver a secret message",
    "poison or bless an object discreetly",
    "open a door or gate for later",
    "copy an artifact, sketch, map, or ledger",
    "learn patrol or staff routines",
    "introduce a false witness or source",
    "recover memory, vision, or testimony",
    "confirm whether a target is alive",
]

COVER_OPTIONS = [
    ("Visiting inspectors", ["Investigation", "Persuasion", "Insight"]),
    ("Hired contractors", ["Performance", "Investigation", "tool proficiency"]),
    ("Rival bidders", ["Deception", "Persuasion", "History"]),
    ("Minor nobles or donors", ["Performance", "Persuasion", "Insight"]),
    ("Courier crew", ["Deception", "Sleight of Hand", "Investigation"]),
    ("Shrine volunteers", ["Religion", "Persuasion", "Insight"]),
    ("Archive researchers", ["History", "Arcana", "Investigation"]),
    ("Repair team", ["Arcana", "Investigation", "tool proficiency"]),
    ("Security consultants", ["Insight", "Investigation", "Intimidation"]),
    ("Catering or event staff", ["Performance", "Stealth", "Persuasion"]),
    ("Guild clerks", ["History", "Deception", "Investigation"]),
    ("Entertainers or performers", ["Performance", "Persuasion", "Acrobatics"]),
]

SOCIAL_ROLES = [
    "gatekeeper",
    "host/contact",
    "suspicious observer",
    "useful friend",
    "target NPC",
    "wildcard",
    "bored guard",
    "overworked clerk",
    "ambitious assistant",
    "drunk noble / guest",
    "servant who sees everything",
    "rival infiltrator",
    "undercover Authority observer",
    "faction loyalist",
    "blackmailed staffer",
    "gossip source",
    "security consultant",
    "event performer",
    "courier with wrong paperwork",
    "priest / scholar / curator",
    "jealous rival",
    "someone who recognizes a PC",
    "someone who thinks they recognize a PC",
    "staff member looking for help",
    "NPC having a private crisis",
]

SCENE_POOL = [
    "entry / check-in",
    "first impression",
    "mingle / gossip",
    "credentials inspection",
    "host introduction",
    "favor exchange",
    "private conversation",
    "distraction opportunity",
    "staff-only access",
    "suspicious test",
    "mistaken identity",
    "rival infiltrator contact",
    "overheard secret",
    "service corridor",
    "social game / toast / ritual etiquette",
    "objective access",
    "evidence handling",
    "hidden witness",
    "sudden schedule change",
    "alarm near-miss",
    "exit interview",
    "clean exit / messy exit",
]

ALERT_TRACK = [
    ("Clear", "Cover holds. NPCs treat the party as expected guests or staff."),
    ("Curious", "Someone noticed a mismatch and asks light questions."),
    ("Suspicious", "Staff quietly checks the party's story."),
    ("Searching", "Security actively looks for the party or the missing thing."),
    ("Lockdown", "Exits close; formal questioning, chase, or combat becomes likely."),
]

ALERT_CONSEQUENCES = [
    "someone asks sharper questions",
    "staff member shadows them",
    "host withholds access",
    "target NPC moves rooms",
    "credentials are sent for verification",
    "someone checks their story against a ledger",
    "rival NPC tries to expose them",
    "guards appear but do not attack yet",
    "private invitation is withdrawn",
    "servants stop talking freely",
    "a door that was open gets locked",
]

PC_ROLES = [
    ("face / speaker", ["Persuasion", "Deception", "Performance", "Insight"]),
    ("document handler", ["Investigation", "History", "Sleight of Hand"]),
    ("lookout", ["Perception", "Insight", "Stealth"]),
    ("social floater", ["Insight", "Persuasion", "Performance"]),
    ("technical specialist", ["Arcana", "Investigation", "tool", "Artificer", "Wizard"]),
    ("magical cover", ["Arcana", "Religion", "Sorcerer", "Wizard", "Cleric"]),
    ("distraction", ["Performance", "Athletics", "Acrobatics"]),
    ("extraction lead", ["Athletics", "Stealth", "Intimidation"]),
    ("emergency muscle", ["Fighter", "Barbarian", "Paladin", "Athletics"]),
]

FALLBACK_FACTIONS = [
    "Iron Fang Consortium", "Argent Blades", "Wardens of Ash", "Serpent Choir",
    "Obsidian Lotus", "Glass Sigil", "Patchwork Saints", "Adventurers Guild",
    "Guild of Ashen Scrolls", "Tower Authority", "Brother Thane's Cult", "Wizards Tower",
]


def _db_rows(query: str, params: tuple = ()) -> List[Dict]:
    try:
        from src.db_api import raw_query
        return raw_query(query, params) or []
    except Exception as e:
        logger.warning(f"[INFILTRATION] DB read failed: {e}")
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


def _party_strength() -> Dict[str, Any]:
    pcs = []
    snap_rows = _db_rows("SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC")
    profiles = {
        r.get("name"): r for r in _db_rows(
            "SELECT name, class_name, profile_json, raw_block FROM player_characters ORDER BY updated_at DESC"
        )
    }
    for row in snap_rows:
        snap = _json_col(row.get("snapshot_json"), {})
        if not isinstance(snap, dict):
            continue
        name = snap.get("name") or row.get("char_name")
        level = int(snap.get("total_level") or 0)
        if level <= 0:
            continue
        prof_row = profiles.get(name, {})
        profile = _json_col(prof_row.get("profile_json"), {})
        skills = str((profile or {}).get("NOTABLE_SKILLS") or "")
        class_text = str((profile or {}).get("CLASS") or prof_row.get("class_name") or snap.get("classes") or "")
        pcs.append({
            "name": name,
            "level": level,
            "classes": class_text,
            "skills": skills,
            "max_hp": int(snap.get("max_hp") or 0),
        })
    levels = [p["level"] for p in pcs] or [5]
    return {"party_size": len(pcs) or 4, "avg_level": round(sum(levels) / len(levels), 1), "max_level": max(levels), "pcs": pcs}


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    return f"Live party read: {strength['party_size']} PCs, average level {strength['avg_level']}, max level {strength['max_level']}."


def _suggest_pc_roles(strength: Dict[str, Any]) -> List[Dict[str, str]]:
    suggestions = []
    used = set()
    for role, keys in PC_ROLES:
        best = None
        best_score = -1
        for pc in strength.get("pcs", []):
            if pc["name"] in used:
                continue
            blob = f"{pc.get('classes','')} {pc.get('skills','')}".lower()
            score = sum(1 for k in keys if k.lower() in blob)
            if score > best_score:
                best, best_score = pc, score
        if best:
            used.add(best["name"])
            suggestions.append({"role": role, "pc": best["name"], "why": best.get("skills") or best.get("classes") or "best available fit"})
        if len(suggestions) >= min(strength["party_size"], 7):
            break
    return suggestions


def _canonical_factions() -> List[Dict]:
    rows = _db_rows("SELECT faction_name, reputation_score, tier, leader, location_name, description FROM faction_reputation ORDER BY faction_name")
    return rows or [{"faction_name": f} for f in FALLBACK_FACTIONS]


def _canon_name(name: str, factions: List[Dict]) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    for row in factions:
        fname = row.get("faction_name") or ""
        if low == fname.lower() or low in fname.lower() or fname.lower() in low:
            return fname
    return raw


def _pick_faction(factions: List[Dict], avoid: List[str]) -> str:
    avoid_lows = {a.lower() for a in avoid if a}
    names = [r.get("faction_name") for r in factions if r.get("faction_name") and r.get("faction_name").lower() not in avoid_lows]
    return random.choice(names or FALLBACK_FACTIONS)


def _resolve_roles(mission: dict) -> Dict[str, str]:
    factions = _canonical_factions()
    hiring = _canon_name(mission.get("faction") or mission.get("hiring_faction") or "", factions) or _pick_faction(factions, [])
    site = _canon_name(mission.get("site_faction") or mission.get("opposing_faction") or mission.get("owner_faction") or "", factions) or _pick_faction(factions, [hiring])
    return {"hiring": hiring, "site": site}


def _pick_location(needs_map: bool) -> Dict[str, Any]:
    if needs_map:
        tags = ["archive", "gallery", "vault", "museum", "office", "library", "shrine", "warehouse", "facility"]
    else:
        tags = ["hall", "market", "forum", "guild", "shrine", "shop", "library", "mall", "park"]
    where = " OR ".join(["LOWER(name) LIKE %s OR LOWER(type_tag) LIKE %s OR LOWER(description) LIKE %s"] * len(tags))
    params = []
    for tag in tags:
        params.extend([f"%{tag}%", f"%{tag}%", f"%{tag}%"])
    rows = _db_rows(
        f"SELECT district, place_type, name, type_tag, description, wealth_level FROM gazetteer_places WHERE {where} ORDER BY RAND() LIMIT 1",
        tuple(params),
    )
    if not rows:
        rows = _db_rows("SELECT district, place_type, name, type_tag, description, wealth_level FROM gazetteer_places ORDER BY RAND() LIMIT 1")
    if rows:
        return rows[0]
    return {"district": "Grand Forum", "name": "a public faction venue", "type_tag": "social venue", "description": "A place where access matters more than swords.", "wealth_level": 5}


def _needs_map(mission: dict, objective: str) -> bool:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    if any(k in text for k in ("item room", "secure room", "vault", "archive room", "facility", "relic", "display case")):
        return True
    return any(k in objective for k in ("item", "plant", "copy an artifact", "open a door", "alter access"))


def _pick_objectives(mission: dict) -> Dict[str, str]:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "body", "description")).lower()
    primary = ""
    for obj in OBJECTIVES:
        if any(w in text for w in obj.split()[:3]):
            primary = obj
            break
    if not primary:
        primary = random.choice(OBJECTIVES)
    secondary = random.choice([o for o in OBJECTIVES if o != primary])
    return {"primary": primary, "secondary": secondary}


def _npcs_for_site(site_faction: str, limit: int = 12) -> List[Dict]:
    rows = _db_rows(
        "SELECT name, faction, role, location, status, data_json FROM npcs "
        "WHERE status IN ('alive','injured','undead','doppelganger') "
        "AND faction LIKE %s ORDER BY RAND() LIMIT %s",
        (f"%{site_faction}%", limit),
    )
    if not rows:
        rows = _db_rows(
            "SELECT name, faction, role, location, status, data_json FROM npcs "
            "WHERE status IN ('alive','injured','undead','doppelganger') ORDER BY RAND() LIMIT %s",
            (limit,),
        )
    return rows


def _social_cast(site_faction: str) -> List[Dict[str, str]]:
    npcs = _npcs_for_site(site_faction, 12)
    roles = list(SOCIAL_ROLES)
    random.shuffle(roles)
    cast = []
    for i, role in enumerate(roles[:8]):
        npc = npcs[i % len(npcs)] if npcs else {}
        cast.append({
            "role": role,
            "name": npc.get("name") or role.title(),
            "faction": npc.get("faction") or site_faction,
            "note": npc.get("role") or npc.get("location") or "generated social pressure point",
            "attitude": random.choice(["friendly if respected", "bored", "guarded", "curious", "lonely", "ambitious", "suspicious"]),
        })
    return cast


def _cover_options(roles: Dict[str, str]) -> List[Dict[str, Any]]:
    options = random.sample(COVER_OPTIONS, 4)
    fixed = random.choice([True, False])
    covers = []
    for name, skills in options:
        covers.append({
            "name": name,
            "skills": skills,
            "provided": fixed and len(covers) == 0,
            "note": "provided by hiring faction" if fixed and len(covers) == 0 else "party may choose this cover if they can sell it",
        })
    return covers


def _scene_sequence(objective: str, needs_map: bool) -> List[str]:
    must = ["entry / check-in", "mingle / gossip", "suspicious test", "objective access", "exit interview"]
    extras = random.sample([s for s in SCENE_POOL if s not in must], 4 if needs_map else 5)
    seq = [must[0], extras[0], must[1], extras[1], must[2], extras[2], must[3], extras[-1], must[4]]
    return seq


async def _ollama(prompt: str, tokens: int = 1200) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.85, "num_predict": tokens},
    }
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("infiltration_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[INFILTRATION] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[INFILTRATION] Ollama error: {e}")
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


async def _generate_briefing(mission: dict, roles: Dict[str, str], objectives: Dict[str, str], location: Dict[str, Any], covers: List[Dict[str, Any]]) -> Dict[str, Any]:
    prompt = f"""Write a D&D social infiltration mission.

Hiring faction: {roles['hiring']}
Site faction: {roles['site']}
Location: {location.get('name')} in {location.get('district')}
Primary objective: {objectives['primary']}
Secondary objective: {objectives['secondary']}
Cover options: {', '.join(c['name'] for c in covers)}
Mission notes: {(mission.get('body') or mission.get('description') or '')[:400]}

Tone: roleplay-first. The party gets friendly, plays a part, earns access, extracts what they need, and leaves.

Return JSON only:
{{
  "briefing": "2-3 paragraphs from the hiring contact",
  "site_description": "2 sentences about the social space",
  "opening_read_aloud": "2-3 sentences, present tense, sensory — what the party sees, hears, and smells the first moment they enter the venue or social space",
  "win_condition": "what success means",
  "failure_note": "what failure looks like before lockdown",
  "debrief": "where/how the debrief happens"
}}"""
    data = _parse_json(await _ollama(prompt))
    if data:
        return data
    return {
        "briefing": f"{roles['hiring']} needs the party inside {location.get('name')} under a believable cover. Get friendly, get access, complete the objective, and leave before {roles['site']} realizes the story does not add up.",
        "site_description": location.get("description") or "A public-facing site with private rooms behind a polite social mask.",
        "opening_read_aloud": f"The entrance to {location.get('name')} opens onto a space that is louder and busier than you expected. {roles['site']} faces are everywhere — and none of them know you yet.",
        "win_condition": f"Complete: {objectives['primary']}; bonus: {objectives['secondary']}.",
        "failure_note": "Failure starts as social suspicion before it becomes lockdown.",
        "debrief": "Debrief depends on alert level and whether the party kept the cover intact.",
    }


async def _check_a1111() -> bool:
    for attempt in range(1, 11):
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{A1111_URL}/sdapi/v1/progress")
                if r.status_code == 200:
                    return True
        except Exception:
            pass
        if attempt < 10:
            logger.info(f"[INFILTRATE] A1111 not ready (attempt {attempt}/10) — waiting 30s…")
            await asyncio.sleep(30)
    logger.warning("[INFILTRATE] A1111 unavailable after 10 attempts")
    return False


async def _generate_map(location: Dict[str, Any], roles: Dict[str, str], out_dir: Path) -> Optional[Path]:
    out = out_dir / "infiltration_map.png"
    # Infiltration is always a building interior — use town LoRA (buildings are in town maps)
    lora_name = os.getenv("A1111_MAP_LORA_TOWN", "EnvyFluxFantasyTownMap01")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    triggers = os.getenv("A1111_MAP_TOWN_TRIGGERS", "detailed, map, village")
    positive = ", ".join([
        f"<lora:{lora_name}:{lora_weight}>",
        triggers,
        "social venue with secure objective room, exterior approach, entry desk, public mingling area, staff corridor, host office, service exit",
        f"location: {location.get('name')} in {location.get('district')}",
        f"site faction flavor: {roles['site']}",
        "high fantasy cyberpunk fusion",
    ])
    negative = "characters, people, isometric, perspective, watermark, text"
    payload = {"prompt": positive, "negative_prompt": negative, "width": 1024, "height": 1024, "steps": 20, "cfg_scale": 1.0, "sampler_name": "Euler", "seed": -1}
    _map_ckpt = os.getenv("A1111_MAP_CHECKPOINT", "")
    if _map_ckpt:
        override: dict = {"sd_model_checkpoint": _map_ckpt}
        payload["override_settings"] = override
        payload["override_settings_restore_afterwards"] = True
    from src.news_feed import a1111_lock
    from src.mission_builder.vtt_renderer import save_vtt_battlemap
    _map_context = {"title": location.get("name"), "location": location, "prompt": positive, "kind": "infiltration interior"}
    images = None
    for map_attempt in range(1, 11):
        try:
            from src.resource_cop import wait_for_a1111_turn
            decision = await wait_for_a1111_turn("infiltration_map", max_wait_seconds=60)
            if not decision.run_now:
                logger.info(f"[INFILTRATE] A1111 deferred by resource cop: {decision.reason}")
                save_vtt_battlemap(out, None, context=_map_context)
                return out
            async with a1111_lock:
                async with httpx.AsyncClient(timeout=600.0) as c:
                    r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                    r.raise_for_status()
                    images = r.json().get("images", [])
            if not images:
                raise RuntimeError("A1111 returned no images")
            break
        except Exception as e:
            logger.warning(f"[INFILTRATE] Map generation attempt {map_attempt}/10 failed: {e}")
            if map_attempt < 10:
                wait = min(30 * map_attempt, 120)
                logger.info(f"[INFILTRATE] Retrying map in {wait}s…")
                await asyncio.sleep(wait)
    if images:
        save_vtt_battlemap(out, images[0], context=_map_context)
    else:
        logger.error("[INFILTRATE] Map generation failed after 10 attempts — using deterministic fallback")
        save_vtt_battlemap(out, None, context=_map_context)
    return out


def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _card(title: str, body: str, color: str) -> str:
    return f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;padding:14px 18px;margin:14px 0;background:#fff;"><h2 style="margin:0 0 8px;color:{color};">{title}</h2>{body}</div>'


def _table(rows: List[tuple]) -> str:
    body = "".join(f'<tr><td style="padding:6px 8px;font-weight:bold;">{_e(a)}</td><td style="padding:6px 8px;">{_e(b)}</td></tr>' for a, b in rows)
    return f'<table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody>{body}</tbody></table>'


def _map_html(map_path: Optional[Path], out_dir: Path, fc: str, dm: bool) -> str:
    points = [
        ("E", "entry/check-in", 18, 82, "#3a6898"),
        ("P", "public/social area", 42, 58, "#b8923a"),
        ("S", "staff-only route", 70, 62, "#8a5a1f"),
        ("O", "secure objective room", 62, 30, "#7b1e1e"),
        ("X", "service exit", 84, 18, "#2a6a2a"),
    ]
    if not map_path or not map_path.exists():
        return "<ul>" + "".join(f"<li><strong>{_e(a)}</strong> - {_e(b)}</li>" for a, b, *_ in points) + "</ul>"
    rel = map_path.relative_to(out_dir)
    markers = ""
    if dm:
        for label, name, x, y, color in points:
            markers += f'<div title="{_e(name)}" style="position:absolute;left:{x}%;top:{y}%;transform:translate(-50%,-50%);width:30px;height:30px;border-radius:50%;background:{color};color:white;font-weight:bold;display:flex;align-items:center;justify-content:center;border:2px solid white;box-shadow:0 1px 5px #000;">{label}</div>'
    title = "DM Reference Map - security zones and objective" if dm else "Player Map - clean social layout"
    return f'<div style="margin:16px 0;"><div style="font-weight:bold;margin-bottom:6px;color:{("#7b1e1e" if dm else fc)};">{title}</div><div style="position:relative;display:inline-block;max-width:100%;"><img src="{rel}" style="max-width:100%;border:3px solid {("#7b1e1e" if dm else fc)};border-radius:8px;" alt="Infiltration Map">{markers}</div></div>'


def render_infiltration_module(
    mission: dict,
    roles: Dict[str, str],
    objectives: Dict[str, str],
    location: Dict[str, Any],
    briefing: Dict[str, Any],
    covers: List[Dict[str, Any]],
    cast: List[Dict[str, str]],
    scenes: List[str],
    pc_roles: List[Dict[str, str]],
    strength: Dict[str, Any],
    needs_map: bool,
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title = mission.get("title", "Infiltration")
    fc = _faction_color(roles["hiring"])
    cover_html = "".join(
        f'<div style="padding:8px 10px;margin:6px 0;background:#fafafa;border-left:3px solid {fc};"><strong>{_e(c["name"])}</strong>'
        f'{" <em>(provided)</em>" if c.get("provided") else ""}<br><span style="font-size:13px;">Skills: {_e(", ".join(c["skills"]))}. {_e(c["note"])}</span></div>'
        for c in covers
    )
    cast_rows = [(f'{c["role"]}: {c["name"]}', f'{c["attitude"]}; {c["note"]} ({c["faction"]})') for c in cast]
    scene_rows = [(str(i + 1), s) for i, s in enumerate(scenes)]
    pc_rows = [(r["role"], f'{r["pc"]} - {r["why"]}') for r in pc_roles]
    alert_rows = ALERT_TRACK
    consequences = "".join(f"<li>{_e(c)}</li>" for c in ALERT_CONSEQUENCES)
    map_section = _card("Map / Social Zones", _map_html(map_path, out_dir, fc, False) + _map_html(map_path, out_dir, fc, True), fc) if needs_map else _card("Social Zones", _table([
        ("Entrance / check-in", "prove the cover identity"),
        ("Public mingling area", "gossip, favors, first impressions"),
        ("Private conversation spot", "earn access without making a scene"),
        ("Staff corridor", "riskier movement and sharper questions"),
        ("Host office / objective area", "where the real extraction happens"),
        ("Exit route", "leave clean or under suspicion"),
    ]), fc)
    body = ""
    body += _card("Briefing", f'<div style="white-space:pre-line;font-style:italic;">{_e(briefing["briefing"])}</div><p>{_e(briefing["site_description"])}</p>', fc)
    body += _card("Live Party Scaling", f'<p>{_e(_party_scaling_note(strength))} Cover pressure, alert severity, and suggested PC roles use this read.</p>', "#3a6898")
    body += _card("Objective", _table([
        ("Primary", objectives["primary"]),
        ("Secondary", objectives["secondary"]),
        ("Win condition", briefing["win_condition"]),
        ("Failure before lockdown", briefing["failure_note"]),
    ]), "#7b1e1e")
    body += _card("Cover Options", cover_html, "#8a5a1f")
    body += _card("Suggested PC Roles", _table(pc_rows), "#3a6898")
    body += _card("Social Cast", _table(cast_rows), "#555")
    body += _card("Scene Sequence", _table(scene_rows), "#8a5a1f")
    body += _card("Alert Track", _table(alert_rows) + f"<h3>Consequences</h3><ul>{consequences}</ul>", "#7b1e1e")
    body += map_section
    body += _card("Debrief", f'<p>{_e(briefing["debrief"])}</p><p><strong>Alert result:</strong> <select><option>Clear</option><option>Curious</option><option>Suspicious</option><option>Searching</option><option>Lockdown</option></select></p><p><strong>Cover maintained:</strong> <input type="checkbox"></p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Debrief notes..."></textarea>', "#2a6a2a")
    return _page(title, body, roles["hiring"])


def render_infiltration_session(mission: dict, roles: Dict[str, str], objectives: Dict[str, str], scenes: List[str], covers: List[Dict[str, Any]], strength: Dict[str, Any], needs_map: bool, map_path: Optional[Path], out_dir: Path) -> str:
    title = mission.get("title", "Infiltration")
    fc = _faction_color(roles["hiring"])
    scene_list = "".join(f'<li><input type="checkbox"> {_e(s)}</li>' for s in scenes)
    cover_list = "".join(f'<li>{_e(c["name"])} - {_e(", ".join(c["skills"]))}</li>' for c in covers)
    body = f'<h1 style="color:{fc};">{_e(title)}</h1>'
    body += _card("Objective", f'<p><strong>Primary:</strong> {_e(objectives["primary"])}</p><p><strong>Secondary:</strong> {_e(objectives["secondary"])}</p><p>{_e(_party_scaling_note(strength))}</p>', fc)
    body += _card("Cover", f'<ul>{cover_list}</ul>', "#8a5a1f")
    if needs_map:
        body += _card("Map", _map_html(map_path, out_dir, fc, False), fc)
    body += _card("Scenes", f'<ol>{scene_list}</ol>', "#555")
    body += _card("Alert / Exit", '<p><strong>Alert:</strong> <select><option>Clear</option><option>Curious</option><option>Suspicious</option><option>Searching</option><option>Lockdown</option></select></p><p><strong>Exited clean:</strong> <input type="checkbox"></p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Notes..."></textarea>', "#7b1e1e")
    return _page(title, body, roles["hiring"])


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


async def build_infiltration_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Infiltration")
    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    strength = _party_strength()
    roles = _resolve_roles(mission)
    objectives = _pick_objectives(mission)
    needs_map = _needs_map(mission, objectives["primary"])
    location = _pick_location(needs_map)
    covers = _cover_options(roles)
    cast = _social_cast(roles["site"])
    scenes = _scene_sequence(objectives["primary"], needs_map)
    pc_roles = _suggest_pc_roles(strength)

    logger.info(f"[INFILTRATION] Building {title!r} | hiring={roles['hiring']} site={roles['site']} | map={needs_map}")

    briefing = await _generate_briefing(mission, roles, objectives, location, covers)

    map_path = None
    if needs_map and str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            map_path = await _generate_map(location, roles, out_dir)
        else:
            logger.warning("[INFILTRATION] A1111 not available - skipping map")

    from src.mission_builder.mimir_module import create_module as _mc, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="infiltration")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Infiltration Map")
    module_html = render_infiltration_module(
        mission, roles, objectives, location, briefing, covers, cast, scenes,
        pc_roles, strength, needs_map, map_path, out_dir,
    )
    module_html += _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")

    session_html = render_infiltration_session(
        mission, roles, objectives, scenes, covers, strength, needs_map, map_path, out_dir,
    )
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    dm_md = (
        f"## Infiltration DM Guide\n"
        f"### Social Operation\n"
        f"- Hiring faction: {roles['hiring']}\n"
        f"- Site faction: {roles['site']}\n"
        f"- Location: {location.get('name')} - {location.get('district')}\n"
        f"- Primary: {objectives['primary']}\n"
        f"- Secondary: {objectives['secondary']}\n\n"
        f"### Briefing Truth\n{briefing.get('briefing', briefing.get('contact_speech', ''))}\n\n"
        f"### Social Cast\n"
        + "\n".join(f"- {c.get('name')}: {c.get('role')} / {c.get('attitude')} / {c.get('note')}" for c in cast)
        + "\n\n### Scene Sequence\n"
        + "\n".join(f"- {s}" for s in scenes)
        + f"\n\n### Live Scaling\n{_party_scaling_note(strength)}"
    )
    players_md = (
        f"## Player Brief\n{briefing.get('briefing', briefing.get('contact_speech', ''))}\n\n"
        f"### Objectives\n"
        f"- Primary: {objectives['primary']}\n"
        f"- Secondary: {objectives['secondary']}\n\n"
        f"### Covers\n"
        + "\n".join(f"- {c['name']}: {', '.join(c['skills'])}" for c in covers)
        + "\n\nPlay the part, get friendly, extract what matters, and leave before the cover collapses."
    )
    chart_md = (
        f"## Infiltration Chart Pack\n"
        f"### Alert Track\n"
        + "\n".join(f"| {a} | {b} |" for a, b in ALERT_TRACK)
        + "\n\n### Alert Consequences\n"
        + "\n".join(f"- {c}" for c in ALERT_CONSEQUENCES)
        + "\n\n### Suggested PC Roles\n"
        + "\n".join(f"| {r.get('role')} | {r.get('pc')} | {r.get('why')} |" for r in pc_roles)
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, roles["hiring"], dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, roles["hiring"], players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, roles["hiring"], chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",   "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",        "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Alert Track",     "type": "custom",      "content": chart_md},
        ])
    maps_name = write_maps_page(out_dir, title, roles["hiring"], [map_path] if map_path else [])
    box_components = component_links(has_maps=bool(maps_name))

    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title,
            faction=roles["hiring"],
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
        logger.warning(f"[INFILTRATION] index.html failed: {e}")
        index_path = out_dir / "module.html"

    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as e:
        logger.warning(f"[INFILTRATION] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[INFILTRATION] Complete: {title!r} -> {out_dir.name}")
    return index_path
