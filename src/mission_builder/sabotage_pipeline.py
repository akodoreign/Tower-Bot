"""
sabotage_pipeline.py - Pipeline for Sabotage mission modules.

Sabotage is about making a target fail at the moment that matters. The job may
be a clean item swap in a museum, a facility break, a supply disruption, or an
arcane/system compromise. DB/API canon is preferred for targets, factions,
detectors, places, recent history, gods, and economic targets.

Exported:
    build_sabotage_module(mission: dict, out_dir: Path) -> Path
    is_sabotage_mission(mission_type: str) -> bool
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


_SABOTAGE_KEYWORDS = {
    "sabotage", "disable", "disrupt", "destroy the", "rig the", "poison",
    "jam", "collapse", "swap", "substitute", "replace", "tamper",
}


def is_sabotage_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _SABOTAGE_KEYWORDS)


SUBTYPES = {
    "item_swap": {
        "label": "Item Swap",
        "resolution": "Fixed sequence: access, bypass protection, swap item, reset display, escape, survive trigger timing.",
        "map_prompt": "Interior Table Map, museum archive gallery vault room, display cases, public viewing area, back rooms, security routes, exits, objects",
    },
    "facility": {
        "label": "Facility Sabotage",
        "resolution": "Hybrid: access phase, sabotage phase, escape phase.",
        "map_prompt": "Interior and Exterior Table Map, facility floorplan, public area, maintenance access, machinery, control room, guard route, exits, objects",
    },
    "route_supply": {
        "label": "Route / Supply Sabotage",
        "resolution": "Progress track: 4 successes before 3 failures, then escape.",
        "map_prompt": "Town Exterior Table Map, dock warehouse checkpoint bridge supply route, loading lanes, cover, witnesses, choke points, objects",
    },
    "arcane_system": {
        "label": "Arcane / System Sabotage",
        "resolution": "Fixed or hybrid sequence: identify anchors, bypass wards, alter system, stabilize evidence, escape.",
        "map_prompt": "Dungeon Interior Table Map, ritual chamber relay room magical archive memory vault, ward nodes, unstable zones, anchors, objects",
    },
}

FACTION_FLAVOR = {
    "Glass Sigil": "flawless forgery, legal/social damage, blackmail, deniable leverage",
    "Obsidian Lotus": "tracker copy, memory substitution, silent delayed reveal, counter-surveillance",
    "Patchwork Saints": "rough but emotionally convincing fake, protection of locals, destruction of harmful assets",
    "Tower Authority": "evidence-chain manipulation, official seals, paperwork sabotage, formal complaints",
    "Wizards Tower": "unstable arcane substitute, ward failure, containment weirdness",
    "Iron Fang Consortium": "market pressure, supply disruption, auction manipulation, profit damage",
    "Argent Blades": "professional disabling work, mercenary deniability, intimidation aftermath",
    "Wardens of Ash": "defensive infrastructure, gate controls, disciplined non-civilian targets",
    "Serpent Choir": "ritual substitutions, doctrinal traps, symbolic reversals",
    "Brother Thane's Cult": "death-coded substitutions, resurrection hooks, faith pressure",
    "Guild of Ashen Scrolls": "archive edits, relic swaps, provenance manipulation, scholarly cover",
    "Adventurers Guild": "contract record tampering, party reputation pressure, official job-board fallout",
}

FAKE_SOURCES = [
    "hiring faction provides the fake",
    "party must acquire or build the fake before insertion",
    "fake is generated as part of the mission",
    "fake source depends on faction and target",
]

FAKE_TYPES = [
    "imperfect copy",
    "museum-grade replica",
    "cursed replacement",
    "tracker copy",
    "inert decoy",
    "altered evidence",
    "false relic",
    "swapped contract",
    "ritual component substitute",
    "memory vial duplicate",
]

DETECTION_PRESSURES = [
    "guards / patrols",
    "display case locks",
    "magical wards",
    "weight or size mismatch",
    "curator / archivist inspection",
    "crowd visibility",
    "time limit",
    "fake quality",
    "unstable or dangerous target item",
    "paperwork or chain-of-custody check",
]

TRIGGER_TIMES = [
    "immediate",
    "later that night",
    "next business day",
    "during public unveiling",
    "during ritual activation",
    "during delivery or inspection",
    "after a set number of rounds or minutes",
]

OUTCOMES = [
    ("Clean success", "Sabotage works at trigger, party escapes, low/no heat."),
    ("Success with suspicion", "Sabotage works, but someone knows it was tampered with."),
    ("Partial disruption", "Target is damaged or delayed, but not fully sabotaged."),
    ("Loud failure", "Party is exposed before completing the job."),
    ("Catastrophic failure", "Rare: target triggers early, explodes, summons, corrupts, burns evidence, or kills someone."),
]

HEAT_STATES = [
    ("Unseen", "No one can tie the sabotage to the party."),
    ("Suspected", "Clues exist, but no proof."),
    ("Exposed", "A detector, guard, or witness identifies the party."),
    ("Wanted", "Formal complaint, legal heat, retaliation, or assigned watcher/assassin."),
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
        logger.warning(f"[SABOTAGE] DB read failed: {e}")
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
    rows = _db_rows("SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC")
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


def _canonical_factions() -> List[Dict]:
    rows = _db_rows(
        "SELECT faction_name, reputation_score, tier, leader, location_name, description, motto "
        "FROM faction_reputation ORDER BY faction_name"
    )
    if rows:
        return rows
    return [{"faction_name": f} for f in FALLBACK_FACTIONS]


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
    owner = _canon_name(mission.get("target_faction") or mission.get("owner_faction") or mission.get("opposing_faction") or "", factions) or _pick_faction(factions, [hiring])
    security = _canon_name(mission.get("security_faction") or mission.get("guarding_faction") or owner, factions) or owner
    blamed = _canon_name(mission.get("blamed_faction") or "", factions)
    if not blamed and random.random() < 0.35:
        blamed = _pick_faction(factions, [hiring, owner, security])
    return {"hiring": hiring, "owner": owner, "security": security, "blamed": blamed}


def _pick_subtype(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    if any(k in text for k in ("swap", "replace", "substitute", "museum", "gallery", "archive", "relic")):
        return "item_swap"
    if any(k in text for k in ("ritual", "ward", "relay", "rift", "memory", "arcane")):
        return "arcane_system"
    if any(k in text for k in ("supply", "shipment", "dock", "bridge", "route", "market", "auction")):
        return "route_supply"
    return random.choice(list(SUBTYPES.keys()))


def _pick_place(subtype: str) -> Dict[str, Any]:
    if subtype == "item_swap":
        tags = ["museum", "gallery", "archive", "vault", "reliquary", "library", "shrine"]
    elif subtype == "facility":
        tags = ["warehouse", "facility", "forge", "station", "clinic", "office", "workshop"]
    elif subtype == "route_supply":
        tags = ["dock", "market", "bridge", "checkpoint", "warehouse", "shop", "mall"]
    else:
        tags = ["shrine", "archive", "tower", "ritual", "temple", "library", "sanctum"]
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
    return {"district": "Markets Infinite", "name": "an unnamed target site", "type_tag": "facility", "description": "A useful target with too many ways in and not enough ways out.", "wealth_level": 5}


def _pick_detector(roles: Dict[str, str], subtype: str) -> Dict[str, str]:
    rows = _db_rows(
        "SELECT name, faction, role, location, status FROM npcs "
        "WHERE status IN ('alive','injured','undead','doppelganger') "
        "AND (faction LIKE %s OR role LIKE %s OR role LIKE %s OR role LIKE %s) "
        "ORDER BY RAND() LIMIT 1",
        (f"%{roles['security']}%", "%curator%", "%inspector%", "%archivist%"),
    )
    if rows:
        r = rows[0]
        return {"name": r.get("name") or "unnamed detector", "role": r.get("role") or "site staff", "faction": r.get("faction") or roles["security"]}
    fallback = {
        "item_swap": ("Curator on duty", "curator / display inspector"),
        "facility": ("Maintenance foreman", "engineer / site handler"),
        "route_supply": ("Dock foreman", "handler / checkpoint watcher"),
        "arcane_system": ("Ward technician", "wizard technician / ritual observer"),
    }[subtype]
    return {"name": fallback[0], "role": fallback[1], "faction": roles["security"]}


def _economic_target() -> Optional[Dict[str, Any]]:
    rows = _db_rows("SELECT item_name, seller_name, current_bid, status, auction_json FROM towerbay_auctions WHERE status='active' ORDER BY RAND() LIMIT 1")
    if rows:
        r = rows[0]
        return {"kind": "auction", "name": r.get("item_name"), "detail": f"seller: {r.get('seller_name')}, current bid: {r.get('current_bid')}"}
    rows = _db_rows("SELECT sector, value, trend FROM tia_market ORDER BY RAND() LIMIT 1")
    if rows:
        r = rows[0]
        return {"kind": "market sector", "name": r.get("sector"), "detail": f"value: {r.get('value')}, trend: {r.get('trend')}"}
    return None


def _divine_target() -> Optional[Dict[str, Any]]:
    rows = _db_rows("SELECT name, domain, god_type, alliance, alignment FROM gods ORDER BY RAND() LIMIT 1")
    if rows:
        r = rows[0]
        return {"kind": "divine asset", "name": r.get("name"), "detail": f"domain: {r.get('domain')}, alliance: {r.get('alliance')}"}
    return None


def _continuity_seed() -> str:
    rows = _db_rows("SELECT facts FROM news_memory ORDER BY created_at DESC LIMIT 3")
    facts = [str(r.get("facts") or "").strip() for r in rows if r.get("facts")]
    if facts:
        return random.choice(facts)[:300]
    rows = _db_rows("SELECT mission_title, key_decisions, loose_threads, notable_moments FROM mission_outcomes ORDER BY created_at DESC LIMIT 3")
    if rows:
        r = random.choice(rows)
        return " / ".join(str(r.get(k) or "") for k in ("mission_title", "key_decisions", "loose_threads", "notable_moments"))[:300]
    return ""


def _target_seed(mission: dict, subtype: str, place: Dict[str, Any], roles: Dict[str, str]) -> Dict[str, Any]:
    econ = _economic_target() if subtype == "route_supply" and random.random() < 0.5 else None
    divine = _divine_target() if subtype == "arcane_system" and random.random() < 0.35 else None
    if econ:
        target_name = econ["name"]
        target_detail = econ["detail"]
    elif divine:
        target_name = divine["name"]
        target_detail = divine["detail"]
    else:
        target_name = mission.get("target_name") or place.get("name") or "target asset"
        target_detail = place.get("description") or ""
    return {
        "name": target_name,
        "detail": target_detail,
        "subtype": subtype,
        "fake_source": random.choice(FAKE_SOURCES),
        "fake_type": random.choice(FAKE_TYPES) if subtype == "item_swap" or random.random() < 0.35 else "",
        "pressures": random.sample(DETECTION_PRESSURES, random.randint(3, 5)),
        "trigger": random.choice(TRIGGER_TIMES),
        "continuity": _continuity_seed(),
    }


async def _ollama(prompt: str, tokens: int = 1000) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.85, "num_predict": tokens},
    }
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("sabotage_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[SABOTAGE] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[SABOTAGE] Ollama error: {e}")
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


def _fallback_plan(roles: Dict[str, str], target: Dict[str, Any], place: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "briefing": f"{roles['hiring']} wants {target['name']} sabotaged at {place.get('name')}. It only matters if the failure survives until {target['trigger']}.",
        "objective": f"Make {target['name']} fail at {target['trigger']}.",
        "bonus": "Keep the party anonymous and frame no civilians.",
        "steps": ["Reach the target", "Bypass the first protection", "Apply the sabotage", "Reset the scene", "Escape", "Survive the trigger timing"],
        "immediate_effect": f"{target['name']} appears normal until the sabotage triggers.",
        "ripple_effect": f"{roles['owner']} loses time, leverage, or face when the failure is revealed.",
        "catastrophic_failure": "The target fails early and publicly, raising heat immediately.",
        "debrief": "Debrief varies by heat; clean work pays best.",
    }


def _normalize_plan(data: Optional[dict], roles: Dict[str, str], target: Dict[str, Any], place: Dict[str, Any]) -> Dict[str, Any]:
    fallback = _fallback_plan(roles, target, place)
    if not isinstance(data, dict):
        return fallback
    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    steps = plan.get("steps")
    if isinstance(steps, str):
        items = [part.strip(" -") for part in re.split(r"[\n;]", steps) if part.strip(" -")]
        plan["steps"] = items or fallback["steps"]
    elif not isinstance(steps, list) or not steps:
        plan["steps"] = fallback["steps"]
    return plan


async def _generate_plan(mission: dict, subtype: str, roles: Dict[str, str], target: Dict[str, Any], place: Dict[str, Any], detector: Dict[str, str], strength: Dict[str, Any]) -> Dict[str, Any]:
    prompt = f"""Write a D&D sabotage mission plan.

Subtype: {SUBTYPES[subtype]['label']}
Hiring faction: {roles['hiring']}
Target owner: {roles['owner']}
Security faction: {roles['security']}
Faction flavor: {FACTION_FLAVOR.get(roles['hiring'], 'practical sabotage')}
Target: {target['name']}
Target detail: {target['detail']}
Place: {place.get('name')} in {place.get('district')}
Fake source: {target.get('fake_source')}
Fake type: {target.get('fake_type') or 'not required'}
Detection pressures: {', '.join(target['pressures'])}
Trigger timing: {target['trigger']}
Likely detector: {detector['name']} - {detector['role']}
Live party: {strength['party_size']} PCs, avg level {strength['avg_level']}, max {strength['max_level']}
Continuity seed: {target.get('continuity') or 'none'}

Return JSON only:
{{
  "briefing": "2-3 paragraphs from the hiring contact",
  "objective": "specific primary objective",
  "bonus": "optional bonus objective",
  "steps": ["4-6 table-ready steps or progress beats"],
  "immediate_effect": "what happens at the target site when it works",
  "ripple_effect": "who gets hurt, embarrassed, protected, delayed, or empowered later",
  "catastrophic_failure": "rare but possible failure event",
  "debrief": "where/how debrief happens and how heat changes it"
}}"""
    data = _parse_json(await _ollama(prompt, tokens=1200))
    return _normalize_plan(data, roles, target, place)


def _map_plan(subtype: str) -> Dict[str, Any]:
    base = SUBTYPES[subtype]
    points = [
        {"label": "T", "name": "Target point", "x": 52, "y": 45, "color": "#7b1e1e"},
        {"label": "P", "name": "Patrol route", "x": 32, "y": 35, "color": "#b8923a"},
        {"label": "W", "name": "Ward/security", "x": 65, "y": 28, "color": "#3a6898"},
        {"label": "E", "name": "Escape exit", "x": 18, "y": 82, "color": "#2a6a2a"},
    ]
    return {"prompt": base["map_prompt"], "points": points}


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
            logger.info(f"[SABOTAGE] A1111 not ready (attempt {attempt}/10) — waiting 30s…")
            await asyncio.sleep(30)
    logger.warning("[SABOTAGE] A1111 unavailable after 10 attempts")
    return False


async def _generate_map(subtype: str, place: Dict[str, Any], roles: Dict[str, str], out_dir: Path) -> Optional[Path]:
    out = out_dir / "sabotage_map.png"
    import re
    plan = _map_plan(subtype)
    _raw_style = plan["prompt"]
    is_dungeon = "dungeon" in _raw_style.lower()
    _style = re.sub(r'(?:Big |Small )?(?:[\w]+ )*?Table Map[, ]+', '', _raw_style, count=1, flags=re.IGNORECASE).strip(', ')
    lora_name = os.getenv("A1111_MAP_LORA_DUNGEON" if is_dungeon else "A1111_MAP_LORA_TOWN",
                           "EnvyFluxDungeonMap01" if is_dungeon else "EnvyFluxFantasyTownMap01")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    triggers = os.getenv("A1111_MAP_DUNGEON_TRIGGERS" if is_dungeon else "A1111_MAP_TOWN_TRIGGERS",
                          "detailed, map, dungeon" if is_dungeon else "detailed, map, village")
    positive = ", ".join([
        f"<lora:{lora_name}:{lora_weight}>",
        triggers,
        _style,
        "clean tactical layout, obvious access points, patrol space, target area, escape exits",
        f"location: {place.get('name')} in {place.get('district')}",
        f"security faction flavor: {roles['security']}",
        "high fantasy cyberpunk fusion",
    ])
    negative = "characters, people, isometric, perspective, watermark, text"
    payload = {
        "prompt": positive,
        "negative_prompt": negative,
        "width": 1024,
        "height": 1024,
        "steps": 20,
        "cfg_scale": 1.0,
        "sampler_name": "Euler",
        "seed": -1,
    }
    _map_ckpt = os.getenv("A1111_MAP_CHECKPOINT", "")
    if _map_ckpt:
        override: dict = {"sd_model_checkpoint": _map_ckpt}
        payload["override_settings"] = override
        payload["override_settings_restore_afterwards"] = True
    from src.news_feed import a1111_lock
    from src.mission_builder.vtt_renderer import save_vtt_battlemap
    _map_ctx = {"title": place.get("name"), "location": place, "prompt": positive, "kind": "sabotage interior facility"}
    for map_attempt in range(1, 11):
        try:
            from src.resource_cop import wait_for_a1111_turn
            decision = await wait_for_a1111_turn("sabotage_map", max_wait_seconds=60)
            if not decision.run_now:
                logger.info(f"[SABOTAGE] A1111 deferred by resource cop: {decision.reason}")
                save_vtt_battlemap(out, None, context=_map_ctx)
                return out
            async with a1111_lock:
                async with httpx.AsyncClient(timeout=600.0) as c:
                    r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                    r.raise_for_status()
                    images = r.json().get("images", [])
            if not images:
                raise RuntimeError("A1111 returned no images")
            save_vtt_battlemap(out, images[0], context=_map_ctx)
            return out
        except Exception as e:
            backoff = min(30 * map_attempt, 120)
            logger.warning(f"[SABOTAGE] Map generation attempt {map_attempt}/10 failed: {e} — retrying in {backoff}s…")
            if map_attempt < 10:
                await asyncio.sleep(backoff)
    logger.error("[SABOTAGE] Map generation failed after 10 attempts — using deterministic fallback")
    save_vtt_battlemap(out, None, context=_map_ctx)
    return out


def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _card(title: str, body: str, color: str) -> str:
    return f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;padding:14px 18px;margin:14px 0;background:#fff;"><h2 style="margin:0 0 8px;color:{color};">{title}</h2>{body}</div>'


def _map_html(map_path: Optional[Path], subtype: str, out_dir: Path, fc: str, dm: bool) -> str:
    plan = _map_plan(subtype)
    if not map_path or not map_path.exists():
        points = "".join(f'<li><strong>{_e(p["label"])}</strong> - {_e(p["name"])}</li>' for p in plan["points"])
        return f'<div style="background:#f5f5f5;padding:12px;border-radius:6px;"><strong>{_e(SUBTYPES[subtype]["label"])}</strong><ul>{points}</ul></div>'
    rel = map_path.relative_to(out_dir)
    markers = ""
    if dm:
        for p in plan["points"]:
            markers += (
                f'<div title="{_e(p["name"])}" style="position:absolute;left:{p["x"]}%;top:{p["y"]}%;'
                f'transform:translate(-50%,-50%);width:30px;height:30px;border-radius:50%;background:{p["color"]};'
                f'color:white;font-weight:bold;display:flex;align-items:center;justify-content:center;'
                f'border:2px solid white;box-shadow:0 1px 5px #000;">{_e(p["label"])}</div>'
            )
    label = "DM Reference Map - target, patrols, wards, escape" if dm else "Player Map - clean view"
    return (
        f'<div style="margin:16px 0;"><div style="font-weight:bold;margin-bottom:6px;color:{("#7b1e1e" if dm else fc)};">{label}</div>'
        f'<div style="position:relative;display:inline-block;max-width:100%;">'
        f'<img src="{rel}" style="max-width:100%;border:3px solid {("#7b1e1e" if dm else fc)};border-radius:8px;" alt="Sabotage Map">{markers}</div></div>'
    )


def _table(rows: List[tuple]) -> str:
    body = "".join(f'<tr><td style="padding:6px 8px;font-weight:bold;">{_e(a)}</td><td style="padding:6px 8px;">{_e(b)}</td></tr>' for a, b in rows)
    return f'<table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody>{body}</tbody></table>'


def render_sabotage_module(
    mission: dict,
    subtype: str,
    roles: Dict[str, str],
    target: Dict[str, Any],
    place: Dict[str, Any],
    detector: Dict[str, str],
    plan: Dict[str, Any],
    strength: Dict[str, Any],
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title = mission.get("title", "Sabotage")
    fc = _faction_color(roles["hiring"])
    steps = "".join(f'<li>{_e(s)}</li>' for s in plan.get("steps", []))
    pressures = "".join(f'<li>{_e(p)}</li>' for p in target["pressures"])
    outcomes = _table(OUTCOMES)
    heat = _table(HEAT_STATES)
    body = ""
    body += _card("Briefing", f'<div style="white-space:pre-line;font-style:italic;">{_e(plan["briefing"])}</div>', fc)
    body += _card("Live Party Scaling", f'<p>{_e(_party_scaling_note(strength))} DCs, detector pressure, and CR defaults are tuned from this read.</p>', "#3a6898")
    body += _card("Faction Roles", _table([
        ("Hiring", roles["hiring"]),
        ("Target owner/source", roles["owner"]),
        ("Security", roles["security"]),
        ("Possible blamed faction", roles.get("blamed") or "None"),
        ("Hiring flavor", FACTION_FLAVOR.get(roles["hiring"], "practical sabotage")),
    ]), "#555")
    body += _card("Target And Trigger", _table([
        ("Subtype", SUBTYPES[subtype]["label"]),
        ("Target", target["name"]),
        ("Location", f"{place.get('name')} - {place.get('district')}"),
        ("Fake source", target.get("fake_source")),
        ("Fake type", target.get("fake_type") or "None"),
        ("Trigger timing", target["trigger"]),
        ("Likely detector", f"{detector['name']} - {detector['role']} ({detector['faction']})"),
    ]) + f'<h3>Detection Pressures</h3><ul>{pressures}</ul>', "#7b1e1e")
    body += _card("Resolution", f'<p><strong>{_e(SUBTYPES[subtype]["resolution"])}</strong></p><ol>{steps}</ol><p><strong>Objective:</strong> {_e(plan["objective"])}</p><p><strong>Bonus:</strong> {_e(plan["bonus"])}</p>', "#8a5a1f")
    body += _card("Maps", _map_html(map_path, subtype, out_dir, fc, dm=False) + _map_html(map_path, subtype, out_dir, fc, dm=True), fc)
    body += _card("Outcome Ladder", outcomes, "#555")
    body += _card("Heat / Anonymity", heat, "#7b1e1e")
    body += _card("Consequences", f'<p><strong>Immediate:</strong> {_e(plan["immediate_effect"])}</p><p><strong>Ripple:</strong> {_e(plan["ripple_effect"])}</p><p><strong>Catastrophic failure:</strong> {_e(plan["catastrophic_failure"])}</p>', "#3a6898")
    body += _card("Debrief", f'<p>{_e(plan["debrief"])}</p><p><strong>Trigger result:</strong> <select><option>Works at trigger</option><option>Discovered before trigger</option><option>Partial disruption</option><option>Loud failure</option><option>Catastrophic failure</option></select></p><p><strong>Heat:</strong> <select><option>Unseen</option><option>Suspected</option><option>Exposed</option><option>Wanted</option></select></p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Debrief notes..."></textarea>', "#2a6a2a")
    return _page(title, body, roles["hiring"])


def render_sabotage_session(mission: dict, subtype: str, roles: Dict[str, str], target: Dict[str, Any], plan: Dict[str, Any], strength: Dict[str, Any], map_path: Optional[Path], out_dir: Path) -> str:
    title = mission.get("title", "Sabotage")
    fc = _faction_color(roles["hiring"])
    steps = "".join(f'<li><input type="checkbox"> {_e(s)}</li>' for s in plan.get("steps", []))
    body = f'<h1 style="color:{fc};">{_e(title)}</h1>'
    body += _card("Objective", f'<p><strong>{_e(plan["objective"])}</strong></p><p>Trigger: {_e(target["trigger"])}</p><p>{_e(_party_scaling_note(strength))}</p>', fc)
    body += _card("Map", _map_html(map_path, subtype, out_dir, fc, dm=False), fc)
    body += _card("Steps", f'<ol>{steps}</ol>', "#8a5a1f")
    body += _card("Result", '<p><strong>Trigger result:</strong> <select><option>Works</option><option>Discovered early</option><option>Partial</option><option>Failed</option><option>Catastrophic</option></select></p><p><strong>Escaped:</strong> <input type="checkbox"></p><p><strong>Anonymous:</strong> <input type="checkbox"></p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Notes..."></textarea>', "#2a6a2a")
    return _page(title, body, roles["hiring"])


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


async def build_sabotage_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Sabotage")
    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    strength = _party_strength()
    roles = _resolve_roles(mission)
    subtype = _pick_subtype(mission)
    place = _pick_place(subtype)
    target = _target_seed(mission, subtype, place, roles)
    detector = _pick_detector(roles, subtype)

    logger.info(f"[SABOTAGE] Building {title!r} | subtype={subtype} | hiring={roles['hiring']} | target={target['name']}")

    plan = await _generate_plan(mission, subtype, roles, target, place, detector, strength)

    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            map_path = await _generate_map(subtype, place, roles, out_dir)
        else:
            logger.warning("[SABOTAGE] A1111 not available - skipping map")

    from src.mission_builder.mimir_module import create_module as _mc, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="sabotage")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Sabotage Map")
    module_html = render_sabotage_module(mission, subtype, roles, target, place, detector, plan, strength, map_path, out_dir)
    module_html += _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")

    session_html = render_sabotage_session(mission, subtype, roles, target, plan, strength, map_path, out_dir)
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    dm_md = (
        f"## Sabotage DM Guide\n"
        f"### Operation\n"
        f"- Hiring faction: {roles['hiring']}\n"
        f"- Target owner: {roles['owner']}\n"
        f"- Security faction: {roles['security']}\n"
        f"- Subtype: {SUBTYPES[subtype]['label']}\n"
        f"- Target: {target['name']}\n"
        f"- Trigger timing: {target['trigger']}\n"
        f"- Detector: {detector['name']} - {detector['role']} ({detector['faction']})\n\n"
        f"### Objective\n{plan.get('objective', '')}\n\n"
        f"### Steps\n"
        + "\n".join(f"- {s}" for s in plan.get("steps", []))
        + f"\n\n### Consequences\n- Immediate: {plan.get('immediate_effect', '')}\n- Ripple: {plan.get('ripple_effect', '')}\n- Catastrophic: {plan.get('catastrophic_failure', '')}\n"
        f"\n### Live Scaling\n{_party_scaling_note(strength)}"
    )
    players_md = (
        f"## Player Brief\n{plan.get('briefing', '')}\n\n"
        f"### Known Objective\n"
        f"- Target: {target['name']}\n"
        f"- Trigger: {target['trigger']}\n"
        f"- Bonus: {plan.get('bonus', '')}\n\n"
        f"Stay anonymous if possible. Getting caught can irk factions, trigger complaints, or assign watchers."
    )
    chart_md = (
        f"## Sabotage Chart Pack\n"
        f"### Detection Pressures\n"
        + "\n".join(f"- {p}" for p in DETECTION_PRESSURES)
        + "\n\n### Outcome Ladder\n"
        + "\n".join(f"| {a} | {b} |" for a, b in OUTCOMES)
        + "\n\n### Heat States\n"
        + "\n".join(f"| {a} | {b} |" for a, b in HEAT_STATES)
        + f"\n\n### Resolution Style\n{SUBTYPES[subtype]['resolution']}"
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, roles["hiring"], dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, roles["hiring"], players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, roles["hiring"], chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",       "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",            "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Detection & Outcomes","type": "custom",      "content": chart_md},
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
        logger.warning(f"[SABOTAGE] index.html failed: {e}")
        index_path = out_dir / "module.html"

    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as e:
        logger.warning(f"[SABOTAGE] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[SABOTAGE] Complete: {title!r} -> {out_dir.name}")
    return index_path
