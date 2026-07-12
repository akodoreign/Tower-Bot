"""
negotiation_pipeline.py - standalone pipeline for Negotiation / Mediation missions.

Negotiation is not about pushing the table to "your side." The objective is to
land the deal as close to 0 as possible on a -10 / 0 / +10 balance marker:
everyone gives up something, nobody is happy, everyone accepts.

Exported:
    build_negotiation_module(mission: dict, out_dir: Path) -> Path
    is_negotiation_mission(mission_type: str) -> bool
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

_NEGOTIATION_KEYWORDS = {
    "negotiation", "negotiate", "mediation", "mediate", "diplomacy",
    "diplomatic", "ceasefire", "agreement", "accord", "treaty",
    "broker", "arbitration", "apology", "hearing", "summit",
    "political intrigue", "political deal", "faction politics", "inter-faction",
}


def is_negotiation_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _NEGOTIATION_KEYWORDS)


FALLBACK_FACTIONS = [
    "Iron Fang Consortium", "Argent Blades", "Wardens of Ash", "Serpent Choir",
    "Obsidian Lotus", "Glass Sigil", "Patchwork Saints", "Adventurers Guild",
    "Guild of Ashen Scrolls", "Tower Authority", "Brother Thane's Cult", "Wizards Tower",
]

SITUATIONS: List[Dict[str, str]] = [
    {"name": "Border Gate Ultimatum", "frame": "two groups claim the same checkpoint", "failure": "assault"},
    {"name": "Hostage Who Won't Leave", "frame": "a captive says the captors are protecting them", "failure": "rescue"},
    {"name": "Relic Extradition Hearing", "frame": "several factions have plausible claims to one relic", "failure": "heist"},
    {"name": "Refugee Corridor", "frame": "safe passage exposes a vulnerable flank", "failure": "defense"},
    {"name": "Construct Witness Rights", "frame": "a sentient construct will testify only if recognized", "failure": "investigation"},
    {"name": "Wounded Commander's Terms", "frame": "a commander will surrender under difficult conditions", "failure": "assault"},
    {"name": "Trial By Proxy", "frame": "the party represents someone in a faction tribunal", "failure": "political"},
    {"name": "Prisoner Exchange", "frame": "both sides accuse the other of hiding extra prisoners", "failure": "rescue"},
    {"name": "Contaminated Aid Shipment", "frame": "medicine may also carry surveillance", "failure": "investigation"},
    {"name": "Sacred Ground Standoff", "frame": "priests, guards, protesters, and families all occupy a holy site", "failure": "defense"},
    {"name": "Mine Collapse Blame Game", "frame": "rescue is delayed by labor and management blame", "failure": "rescue"},
    {"name": "Diplomat With A Knife", "frame": "an envoy privately wants the agreement to fail", "failure": "investigation"},
    {"name": "False Flag Apology", "frame": "one side may apologize for something it did not do", "failure": "assault"},
    {"name": "Child Monarch Clause", "frame": "a young heir must approve a treaty they do not understand", "failure": "political"},
    {"name": "Clone Continuity Case", "frame": "a duplicate claims the legal rights of the original", "failure": "investigation"},
    {"name": "Quarantine Vote", "frame": "sealing a ward saves many and condemns some", "failure": "rescue"},
    {"name": "Memory Ownership Case", "frame": "stolen memories may be property, testimony, or contraband", "failure": "heist"},
    {"name": "Ritual Noise Complaint", "frame": "a legal ritual is hurting neighbors", "failure": "sabotage"},
    {"name": "Mercenary Strike", "frame": "fighters refuse to defend until back pay is honored", "failure": "defense"},
    {"name": "Water Rights Crisis", "frame": "one purifier cannot serve both neighborhoods fully", "failure": "rescue"},
    {"name": "Museum Repatriation Summit", "frame": "a museum display has descendants, scholars, and thieves at odds", "failure": "heist"},
    {"name": "No-Fly Zone Dispute", "frame": "rescue craft, reporters, and scouts all need the same airspace", "failure": "rescue"},
    {"name": "Duel Replacement", "frame": "an injured champion creates an honor crisis", "failure": "battle"},
    {"name": "Witness Protection Bargain", "frame": "a witness wants their whole family relocated", "failure": "investigation"},
    {"name": "Tower Authority Injunction", "frame": "procedure freezes a site while the clock keeps moving", "failure": "rescue"},
    {"name": "Cult Defector Accord", "frame": "a defector wants protection and partial religious autonomy", "failure": "rescue"},
    {"name": "Trade Embargo Spiral", "frame": "tariffs are turning into food shortage and street anger", "failure": "defense"},
    {"name": "Salvage Rights Fight", "frame": "a crash site contains cargo, bodies, black boxes, and sacred remains", "failure": "investigation"},
    {"name": "Accidental Occupation", "frame": "temporary security has become permanent control", "failure": "assault"},
    {"name": "Wedding Treaty", "frame": "a symbolic alliance has one objector with a valid reason", "failure": "political"},
    {"name": "Weapon Seeking Asylum", "frame": "a sentient weapon defects from its owner", "failure": "heist"},
    {"name": "Reporter Access Fight", "frame": "TNN demands access while families demand privacy", "failure": "investigation"},
    {"name": "Bounty Cancellation", "frame": "a bounty target is now politically inconvenient to kill", "failure": "ambush"},
    {"name": "Funeral Procession Route", "frame": "a funeral must cross enemy-aligned territory", "failure": "defense"},
    {"name": "Illegal Miracle", "frame": "forbidden magic saved lives and now someone must answer for it", "failure": "investigation"},
    {"name": "Train Car Lock-In", "frame": "rival delegations are trapped on a halted train", "failure": "rescue"},
    {"name": "Dead God Cargo", "frame": "a legal shipment terrifies everyone asked to unload it", "failure": "infestation"},
    {"name": "Siege That Hasn't Started", "frame": "both armies prepare while diplomats insist peace remains possible", "failure": "assault"},
    {"name": "Third Party At The Table", "frame": "the smallest faction has the actual leverage", "failure": "political"},
    {"name": "Public Apology Script", "frame": "one wrong word in the apology may start violence", "failure": "assault"},
    {"name": "Arena Champion Walkout", "frame": "a fighter refuses a match and half the district has money on it", "failure": "battle"},
    {"name": "Shared Commander Problem", "frame": "two factions claim command over one mixed defense force", "failure": "defense"},
    {"name": "Unmarked Grave Disclosure", "frame": "bodies under a worksite could destabilize a district", "failure": "investigation"},
    {"name": "Spell Patent War", "frame": "scholars failed to settle ownership of a dangerous formula", "failure": "puzzle"},
    {"name": "Sanctuary Breach", "frame": "punishing the violator may end neutrality forever", "failure": "assault"},
    {"name": "Mutiny Mediation", "frame": "a crew refuses orders, but the mission still matters", "failure": "rescue"},
    {"name": "Conditional Surrender", "frame": "an enemy will yield only if a hated NPC is removed", "failure": "assault"},
    {"name": "Debt Forgiveness Riot", "frame": "forgiving debts saves lives and breaks contracts", "failure": "defense"},
    {"name": "Monster With Terms", "frame": "a dangerous entity offers peace for territory or recognition", "failure": "defense"},
    {"name": "Peace Conference Assassination Rumor", "frame": "no attack has happened, but everyone believes one is coming", "failure": "investigation"},
]

RESEARCH_LANES = [
    ("Legal precedent", "History or Investigation", "treaties, contracts, jurisdiction, sanctuary rules"),
    ("Personal leverage", "Insight or Persuasion", "debts, grudges, old favors, family ties"),
    ("Historical truth", "History or Religion", "buried crimes, old ownership, broken promises"),
    ("Practical constraint", "Investigation or Survival", "food, water, routes, money, troop movement, medicine"),
    ("Public optics", "Performance or Insight", "TNN angle, neighborhood mood, apology language"),
    ("Economic pressure", "Investigation or Persuasion", "who pays, who loses, who can absorb the hit"),
    ("Ritual requirement", "Religion or Arcana", "doctrine, omen, formal rite, taboo wording"),
    ("Witness chain", "Perception or Persuasion", "who saw what and who can safely say it"),
    ("Prior mission outcome", "History or Insight", "old board work, favors owed, unresolved fallout"),
    ("Character-specific leverage", "Relevant PC skill", "party class, fame, faction standing, or personal contact"),
]

FACTION_STYLE = {
    "Obsidian Lotus": "respects subtlety, deniability, and lies that leave no fingerprints",
    "Glass Sigil": "respects polished presentation, leverage, and impossible-to-prove claims",
    "Iron Fang Consortium": "respects enforceable contracts, payment logic, and risk allocation",
    "Wardens of Ash": "respects protecting the weak, discipline, and honorable restraint",
    "Patchwork Saints": "respects community protection and practical kindness over paperwork",
    "Tower Authority": "respects procedure, official record, permits, and chain of custody",
    "Wizards Tower": "respects scholarship, proof, peer review, and technical precision",
    "Serpent Choir": "respects omen logic, divine obligation, and ritual framing",
    "Brother Thane's Cult": "respects faith continuity, sacrifice, and signs of Thane's will",
    "Argent Blades": "respects spectacle, courage, personal challenge, and a great fight",
    "Adventurers Guild": "respects party competence, precedent, and fair contract terms",
    "Guild of Ashen Scrolls": "respects archive truth, fate records, and exact wording",
}

OUTCOME_BANDS = [
    (-10, -6, "Side A over-wins", "Side B rejects, retaliates, or spawns a follow-up mission."),
    (-5, -3, "Rough success for Side A", "Agreement holds, but resentment and fallout remain."),
    (-2, 2, "Total success", "Both sides accept the pain. The deal is durable."),
    (0, 0, "Perfect negotiation", "Nobody is happy, everyone signs."),
    (3, 5, "Rough success for Side B", "Agreement holds, but resentment and fallout remain."),
    (6, 10, "Side B over-wins", "Side A rejects, retaliates, or spawns a follow-up mission."),
]

FAVOR_COSTS = [
    "time pressure advances",
    "the party owes a future favor",
    "TNN notices the backchannel",
    "a source is exposed",
    "one faction grows jealous",
    "the other side prepares a counterargument",
    "the private negotiation becomes public",
    "the favor-giver demands credit",
    "the faction records the debt formally",
    "a bad-faith actor learns what the party is doing",
]

ESCALATIONS = [
    "security scuffle in the hall",
    "assassination scare that may be staged",
    "protester rushes the table",
    "ritual challenge",
    "arena duel proposal",
    "public humiliation demand",
    "bodyguard posture check",
    "breaking a symbolic object",
    "threat of formal complaint",
    "TNN ambush interview",
]

APOLOGY_MODES = [
    "regular written apology with carefully negotiated wording",
    "public spoken apology before neutral witnesses",
    "formal ritual apology with symbolic restitution",
    "humiliating but effective over-the-top apology spectacle",
    "Gintama-style escalation: bows, tears, props, over-commitment, accidental sincerity, and everyone too exhausted to keep fighting",
]


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


def _db_rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        from src.db_api import raw_query
        return raw_query(sql, params) or []
    except Exception as e:
        logger.debug(f"[NEGOTIATION] DB read skipped: {e}")
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


def _canonical_factions() -> List[str]:
    rows = _db_rows("SELECT faction_name FROM faction_reputation ORDER BY faction_name")
    names = [r.get("faction_name") for r in rows if r.get("faction_name")]
    return names or list(FALLBACK_FACTIONS)


def _canon_name(name: str, factions: List[str]) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    for fname in factions:
        if low == fname.lower() or low in fname.lower() or fname.lower() in low:
            return fname
    return raw


def _pick_other_faction(primary: str, factions: List[str]) -> str:
    pool = [f for f in factions if f.lower() != (primary or "").lower()]
    return random.choice(pool or FALLBACK_FACTIONS)


def _resolve_sides(mission: dict) -> Dict[str, str]:
    factions = _canonical_factions()
    side_a = _canon_name(mission.get("faction") or mission.get("hiring_faction") or "", factions)
    if not side_a:
        side_a = random.choice(factions)
    side_b = _canon_name(
        mission.get("opposing_faction") or mission.get("target_faction") or mission.get("other_faction") or "",
        factions,
    )
    if not side_b:
        side_b = _pick_other_faction(side_a, factions)
    sponsor = side_a
    return {"sponsor": sponsor, "side_a": side_a, "side_b": side_b}


def _party_strength() -> Dict[str, Any]:
    pcs = []
    rows = _db_rows(
        "SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC"
    )
    for row in rows:
        snap = _json_col(row.get("snapshot_json"), {})
        if not isinstance(snap, dict):
            continue
        level = int(snap.get("total_level") or 0)
        if level <= 0:
            continue
        pcs.append({
            "name": snap.get("name") or row.get("char_name"),
            "level": level,
            "classes": snap.get("classes") or {},
            "skills": snap.get("skills") or {},
            "max_hp": int(snap.get("max_hp") or 0),
        })
    if not pcs:
        rows = _db_rows("SELECT name, class_name, species, profile_json FROM player_characters ORDER BY name")
        for row in rows:
            profile = _json_col(row.get("profile_json"), {})
            text = f"{row.get('class_name', '')} {profile}"
            nums = [int(n) for n in re.findall(r"\b(\d{1,2})\b", text)]
            pcs.append({
                "name": row.get("name"),
                "level": max(nums) if nums else 5,
                "classes": row.get("class_name") or "",
                "skills": profile.get("skills") or "",
                "max_hp": 0,
            })
    levels = [p["level"] for p in pcs] or [5]
    return {"party_size": len(pcs) or 4, "avg_level": round(sum(levels) / len(levels), 1), "max_level": max(levels), "pcs": pcs}


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    return f"Live party read: {strength['party_size']} PCs, average level {strength['avg_level']}, max level {strength['max_level']}."


def _dc_profile(tier: str, strength: Dict[str, Any]) -> Dict[str, int]:
    tier_bump = {"local": 0, "patrol": 0, "escort": 1, "standard": 1, "investigation": 1, "major": 2, "inter-guild": 3, "high-stakes": 4, "epic": 5, "divine": 5, "tower": 5}
    base = 11 + tier_bump.get((tier or "standard").lower(), 1) + max(0, int(strength["avg_level"]) - 4) // 3
    return {"easy": base, "standard": base + 2, "hard": base + 5, "severe": base + 8}


def _start_marker(tier: str) -> int:
    spread = {"local": 4, "patrol": 4, "escort": 5, "standard": 6, "investigation": 6, "major": 8, "inter-guild": 9, "high-stakes": 10, "epic": 10, "divine": 10, "tower": 10}.get((tier or "standard").lower(), 6)
    return random.randint(-spread, spread)


def _marker_reason(marker: int, side_a: str, side_b: str) -> str:
    if marker < -6:
        return f"{side_a} begins with overwhelming leverage; {side_b} feels cornered."
    if marker < -2:
        return f"{side_a} has the better opening position, but overplaying it may break the room."
    if marker <= 2:
        return "The room begins close to balanced; one bad argument can still tilt it."
    if marker <= 6:
        return f"{side_b} has the better opening position, but needs face-saving terms."
    return f"{side_b} begins with overwhelming leverage; {side_a} feels cornered."


def _extract_canon_terms(mission: dict) -> tuple[list[str], list[str]]:
    """Extract named NPCs/places and stakes phrases from mission body for prompt injection."""
    body = mission.get("body") or mission.get("description") or ""
    title = mission.get("title", "")
    combined = f"{title} {body}"
    names = list(dict.fromkeys(re.findall(r"\b([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){1,2})\b", combined)))[:8]
    stake_keywords = ("purge", "expos", "silence", "ruin", "destroy", "collapse", "seize", "arrest", "execute")
    stakes = [s.strip() for s in re.split(r"[.!;]", body) if any(kw in s.lower() for kw in stake_keywords)][:4]
    return names, stakes


GENERIC_NEGOTIATION_MARKERS = [
    "wants a fair deal",
    "seeks reasonable terms",
    "come to an understanding",
    "general settlement",
]


def _is_generic_negotiation_plan(
    plan: Optional[Dict[str, Any]],
    canon_names: Optional[List[str]] = None,
) -> bool:
    if not isinstance(plan, dict):
        return True

    check_text = " ".join(
        str(v) for k in ("what_happened", "current_state", "side_a_wants", "side_b_wants") for v in [plan.get(k, "")]
    ).lower()
    hits = sum(1 for m in GENERIC_NEGOTIATION_MARKERS if m in check_text)

    # Positive check: plan contains mission-specific named entities → not generic
    if canon_names:
        plan_blob = json.dumps(plan, ensure_ascii=False).lower()
        name_hits = sum(1 for name in canon_names if len(name) > 3 and name.lower() in plan_blob)
        if name_hits >= 2:
            return False

    has_specifics = any(len(str(plan.get(k, ""))) > 40 for k in ("side_a_wants", "side_b_wants", "what_happened"))
    return hits >= 3 or (hits >= 2 and not has_specifics)


def _pick_situation(mission: dict) -> Dict[str, str]:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    for sit in SITUATIONS:
        if any(word in text for word in sit["name"].lower().split()[:2]):
            return sit
    if "apolog" in text:
        return next(s for s in SITUATIONS if s["name"] == "Public Apology Script")
    return random.choice(SITUATIONS)


def _pick_location() -> Dict[str, str]:
    rows = _db_rows(
        "SELECT district, place_type, name, type_tag, description, wealth_level FROM gazetteer_places "
        "WHERE LOWER(type_tag) LIKE %s OR LOWER(description) LIKE %s OR LOWER(place_type) LIKE %s "
        "ORDER BY RAND() LIMIT 1",
        ("%hall%", "%meeting%", "%forum%"),
    )
    if not rows:
        rows = _db_rows("SELECT district, place_type, name, type_tag, description, wealth_level FROM gazetteer_places ORDER BY RAND() LIMIT 1")
    return rows[0] if rows else {"district": "Grand Forum", "name": "a neutral meeting chamber", "description": "A formal room with too many witnesses and not enough exits."}


def _npc_pool(side_a: str, side_b: str, limit: int = 8) -> List[Dict[str, str]]:
    rows = _db_rows(
        "SELECT name, faction, role, location, description FROM npcs WHERE faction LIKE %s OR faction LIKE %s ORDER BY RAND() LIMIT %s",
        (f"%{side_a}%", f"%{side_b}%", limit),
    )
    return rows or []


def _canon_seed(roles: Dict[str, str]) -> Dict[str, Any]:
    npcs = _npc_pool(roles["side_a"], roles["side_b"])
    outcomes = _db_rows(
        "SELECT mission_title, faction, opposing_faction, result, key_decisions, loose_threads, notable_moments "
        "FROM mission_outcomes "
        "WHERE faction LIKE %s OR faction LIKE %s OR opposing_faction LIKE %s OR opposing_faction LIKE %s "
        "ORDER BY completed_at DESC LIMIT 5",
        (f"%{roles['side_a']}%", f"%{roles['side_b']}%", f"%{roles['side_a']}%", f"%{roles['side_b']}%"),
    )
    news = _db_rows(
        "SELECT headline, body, category FROM news_entries ORDER BY posted_at DESC LIMIT 5"
    )
    return {"npcs": npcs, "outcomes": outcomes, "news": news}


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


async def _ollama(prompt: str, tokens: int = 4000) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.82, "num_predict": tokens, "think": True, "num_ctx": _fit_ctx(prompt, tokens)},
    }
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("negotiation_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[NEGOTIATION] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=240.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            text = r.json()["message"]["content"].strip()
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return text
    except Exception as e:
        logger.warning(f"[NEGOTIATION] Ollama unavailable: {e}")
        return ""


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


async def _generate_plan(
    mission: dict,
    roles: Dict[str, str],
    situation: Dict[str, str],
    location: Dict[str, str],
    marker: int,
    dcs: Dict[str, int],
    strength: Dict[str, Any],
    seeds: Dict[str, Any],
) -> Dict[str, Any]:
    canon_names, stakes = _extract_canon_terms(mission)
    canon_note = (f"Mission canon — use these names in delegate names and dialogue: {', '.join(canon_names)}" if canon_names else "")
    stakes_note = (f"Mission stakes — reference these in red lines and success/failure terms: {'; '.join(stakes)}" if stakes else "")

    npc_names = ", ".join(f"{n.get('name')} ({n.get('faction')}, {n.get('role')})" for n in seeds.get("npcs", [])[:8])
    outcome_bits = []
    for outcome in seeds.get("outcomes", [])[:4]:
        title = outcome.get("mission_title") or "recent mission"
        result = outcome.get("result") or ""
        details = outcome.get("key_decisions") or outcome.get("loose_threads") or outcome.get("notable_moments") or ""
        outcome_bits.append(" - ".join(str(part) for part in (title, result, details) if part))
    outcome_notes = "; ".join(outcome_bits)
    news_notes = "; ".join(str(n.get("headline") or "") for n in seeds.get("news", [])[:4])
    prompt = f"""Build a D&D negotiation mission plan as JSON only.

Mission: {mission.get('title', 'Negotiation')}
Situation: {situation['name']} - {situation['frame']}
Side A: {roles['side_a']} ({FACTION_STYLE.get(roles['side_a'], 'pragmatic faction interests')})
Side B: {roles['side_b']} ({FACTION_STYLE.get(roles['side_b'], 'pragmatic faction interests')})
Location: {location.get('name')} in {location.get('district')} - {location.get('description', '')}
Starting marker: {marker} on -10/0/+10 where 0 is perfect.
DCs: {dcs}
Live party: {_party_scaling_note(strength)}
DB NPCs: {npc_names}
Recent outcomes: {outcome_notes}
Recent news: {news_notes}
Mission notes: {(mission.get('body') or mission.get('description') or '')[:600]}
{canon_note}
{stakes_note}

Generate:
- what_happened: brief public history (reference mission canon if present)
- current_state: where negotiation stands now
- side_a_delegate and side_b_delegate with specific names and titles (use mission canon names if provided)
- side_a_wants and side_b_wants: specific concessions tied to THIS dispute, not generic phrases
- side_a_red_lines and side_b_red_lines: DM-only, each with format "if [specific topic is raised] → [specific reaction/consequence]"
- marker_start_reason
- scene_anchor: 2-3 sentences — the physical room, who else is present, ambient tension when party enters
- research: 8 items, each with lane, place, check, dc, result, marker_effect, risk
- dialogue: at least 20 DM lines referencing the actual dispute and names (not generic filler)
- outside_favors: 6 possible favors with source, ask, cost, marker_effect
- escalations: 4 possible escalation scenes
- apology_mode: one normal or over-the-top apology option
- debrief: how sponsor reacts
- success_terms: what a -2..+2 deal looks like for THIS dispute
- rough_terms_a and rough_terms_b
- failure_spawn: one of assault, defense, rescue, investigation, sabotage, heist, ambush, battle, political

Keep player-facing material surface-level. Dialogue can include secrets because it is for DM side.
Return JSON object only."""
    data = None
    for attempt in range(3):
        raw = await _ollama(prompt)
        data = _parse_json(raw)
        if data:
            break
        logger.warning(f"[NEGOTIATION] LLM returned no usable plan (attempt {attempt + 1}/3)")
        await asyncio.sleep(2)
    if _is_generic_negotiation_plan(data, canon_names=canon_names):
        logger.info("[NEGOTIATION] Plan too generic — using fallback")
        return _normalize_plan(None, mission, roles, situation, marker, dcs)
    return _normalize_plan(data, mission, roles, situation, marker, dcs)


def _fallback_plan(mission: dict, roles: Dict[str, str], situation: Dict[str, str], marker: int, dcs: Dict[str, int]) -> Dict[str, Any]:
    a, b = roles["side_a"], roles["side_b"]
    research = []
    for lane, skill, detail in random.sample(RESEARCH_LANES, 8):
        shift = random.choice([-2, -1, 1, 2])
        research.append({
            "lane": lane, "place": "appropriate DB-canon contact or archive", "check": skill,
            "dc": dcs["standard"], "result": detail, "marker_effect": shift,
            "risk": random.choice(FAVOR_COSTS),
        })
    dialogue = [
        f"{a}: We are not here to be educated. We are here because {b} crossed a line.",
        f"{b}: If {a} wanted peace, they would not have arrived with terms already written.",
        "Neutral clerk: For the record, nobody has agreed to the word 'fault.'",
        "TNN stringer: Is either side willing to say who is responsible on camera?",
        f"{a}: Give us something we can take back without looking weak.",
        f"{b}: Give us something our people can accept without spitting.",
        "Mediator line: That is a victory speech, not a settlement offer.",
        "Mediator line: If everyone hates this equally, we may finally be close.",
        "Pressure line: Say that again, but as a concession instead of an accusation.",
        "Apology line: We can apologize for the harm without confessing to the whole charge.",
        "Counter line: Money solves the damage, not the insult.",
        "Counter line: Public truth solves the insult, not the damage.",
        "Outside favor line: We can recess for one hour and bring in a witness.",
        "Outside favor line: If we call TNN, the room changes forever.",
        "Failure line: If this table breaks, tomorrow's board will not say negotiation.",
        "Argent Blades line: If words fail, name a champion and make it worth watching.",
        "Wardens line: The weak do not become bargaining chips.",
        "Lotus line: A useful lie is only ugly when it leaves fingerprints.",
        "Iron Fang line: Put it in writing or stop pretending it exists.",
        "Saints line: People first. Then pride.",
    ]
    return {
        "what_happened": f"{situation['frame'].capitalize()} pulled {a} and {b} into the same room.",
        "current_state": "Both sides are still seated, but neither trusts the first offer.",
        "scene_anchor": "A neutral room cleared for the occasion. Both delegations sit across a long table, faction colours visible but not ostentatious. A clerk near the door holds an unsealed summary of proceedings. The air smells of cold tea and held grudges.",
        "side_a_delegate": f"{a} delegate",
        "side_b_delegate": f"{b} delegate",
        "side_a_wants": ["public face-saving", "material compensation", "enforceable limits"],
        "side_b_wants": ["private apology", "safe passage", "no admission of total fault"],
        "side_a_red_lines": ["being seen as weak", "unlimited liability"],
        "side_b_red_lines": ["public humiliation", "losing operational access"],
        "marker_start_reason": _marker_reason(marker, a, b),
        "research": research,
        "dialogue": dialogue,
        "outside_favors": [
            {"source": "NPC witness", "ask": "confirm one narrow fact", "cost": "source exposure", "marker_effect": -1},
            {"source": "TNN", "ask": "delay or soften coverage", "cost": "public attention later", "marker_effect": 1},
            {"source": "faction elder", "ask": "authorize a concession", "cost": "future debt", "marker_effect": -2},
            {"source": "Wizards Tower expert", "ask": "technical ruling", "cost": "scholar review", "marker_effect": 2},
            {"source": "Tower Authority clerk", "ask": "procedural precedent", "cost": "official record", "marker_effect": -1},
            {"source": "party reputation", "ask": "trust us to enforce it", "cost": "personal accountability", "marker_effect": 1},
        ],
        "escalations": random.sample(ESCALATIONS, 4),
        "apology_mode": random.choice(APOLOGY_MODES),
        "debrief": "The sponsor evaluates not whether they got everything, but whether the agreement survives tomorrow.",
        "success_terms": "Both sides give up something visible, both can explain the pain to their people, and neither gets a victory speech.",
        "rough_terms_a": f"{a} gets the stronger clause; {b} signs while planning future leverage.",
        "rough_terms_b": f"{b} gets the stronger clause; {a} signs while planning future leverage.",
        "failure_spawn": situation["failure"],
    }


def _normalize_plan(
    data: Optional[Dict[str, Any]],
    mission: dict,
    roles: Dict[str, str],
    situation: Dict[str, str],
    marker: int,
    dcs: Dict[str, int],
) -> Dict[str, Any]:
    fallback = _fallback_plan(mission, roles, situation, marker, dcs)
    if not isinstance(data, dict):
        return fallback

    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    for key in (
        "side_a_wants",
        "side_b_wants",
        "side_a_red_lines",
        "side_b_red_lines",
        "dialogue",
        "escalations",
    ):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]

    for key in ("research", "outside_favors"):
        value = plan.get(key)
        if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
            plan[key] = fallback[key]

    # Strip literal "None" / "null" strings from scalar fields — LLM sometimes echoes these
    _NONE_STRINGS = {"none", "null", "n/a", ""}
    for key in ("side_a_delegate", "side_b_delegate", "what_happened", "current_state",
                "marker_start_reason", "scene_anchor", "apology_mode", "debrief",
                "success_terms", "rough_terms_a", "rough_terms_b", "failure_spawn"):
        val = plan.get(key)
        if isinstance(val, str) and val.strip().lower() in _NONE_STRINGS:
            plan[key] = fallback.get(key, "")

    return plan


def _e(value: Any) -> str:
    import html
    return html.escape(str(value or ""))


def _card(title: str, body: str, color: str = "#3a6898") -> str:
    return (
        f'<div style="border-left:4px solid {color};padding:12px 16px;margin:14px 0;'
        f'background:#fafafa;border-radius:0 6px 6px 0;">'
        f'<h2 style="margin:0 0 8px;color:{color};">{_e(title)}</h2>{body}</div>'
    )


def _ul(items: List[Any]) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _table(rows: List[tuple]) -> str:
    return "<table style='width:100%;border-collapse:collapse;'>" + "".join(
        f"<tr><td style='padding:6px 10px;font-weight:bold;border-bottom:1px solid #ddd;'>{_e(a)}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #ddd;'>{_e(b)}</td></tr>"
        for a, b in rows
    ) + "</table>"


def _marker_html(marker: int) -> str:
    cells = []
    for n in range(-10, 11):
        bg = "#fff"
        if n == 0:
            bg = "#dff0d8"
        elif -2 <= n <= 2:
            bg = "#edf7ed"
        elif -5 <= n <= 5:
            bg = "#fff5d8"
        else:
            bg = "#f8dddd"
        border = "3px solid #111" if n == marker else "1px solid #aaa"
        cells.append(
            f"<td style='padding:6px;text-align:center;background:{bg};border:{border};font-weight:{'bold' if n == marker else 'normal'};'>{n}</td>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:12px;'><tr>"
        + "".join(cells)
        + "</tr></table>"
        "<p><strong>Goal:</strong> land as close to 0 as possible. Perfect negotiation means nobody is happy and everyone accepts.</p>"
    )


def _research_table(research: List[Dict[str, Any]]) -> str:
    rows = ""
    for r in research:
        setup = r.get("setup") or f"Work the {r.get('lane', 'lane')} at {r.get('place', 'the location')} with {r.get('check', 'the relevant skill')} to dig up leverage before the table."
        rows += (
            "<tr>"
            f"<td>{_e(r.get('lane'))}</td><td>{_e(r.get('place'))}</td><td>{_e(r.get('check'))} DC {_e(r.get('dc'))}</td>"
            f"<td>{_e(setup)}</td>"
            f"<td>{_e(r.get('result'))}</td><td>{_e(r.get('marker_effect'))}</td><td>{_e(r.get('risk'))}</td>"
            "</tr>"
        )
    return (
        "<table><tr><th>Lane</th><th>Where</th><th>Check</th><th>Setup</th>"
        "<th>On Success (Find)</th><th>Marker</th><th>On Failure (Risk)</th></tr>"
        + rows + "</table>"
    )


def _dialogue_html(dialogue: List[str]) -> str:
    return "<ol>" + "".join(f"<li style='margin:6px 0;'>{_e(line)}</li>" for line in dialogue) + "</ol>"


def render_negotiation_module(mission: dict, roles: Dict[str, str], situation: Dict[str, str], location: Dict[str, str], plan: Dict[str, Any], marker: int, dcs: Dict[str, int], strength: Dict[str, Any]) -> str:
    title = mission.get("title", "Negotiation")
    fc = _faction_color(roles["sponsor"])
    body = ""
    body += _card("What Happened", f"<p>{_e(plan.get('what_happened'))}</p><p><strong>Situation:</strong> {_e(situation['name'])} - {_e(situation['frame'])}</p>", fc)
    body += _card("Negotiation Table", _table([
        ("Side A", roles["side_a"]),
        ("Side A delegate", plan.get("side_a_delegate", "")),
        ("Side B", roles["side_b"]),
        ("Side B delegate", plan.get("side_b_delegate", "")),
        ("Location", f"{location.get('name')} - {location.get('district')}"),
        ("Current state", plan.get("current_state", "")),
        ("Party scaling", _party_scaling_note(strength)),
    ]), "#8a5a1f")
    body += _card("Balance Marker", _marker_html(marker) + f"<p>{_e(plan.get('marker_start_reason') or _marker_reason(marker, roles['side_a'], roles['side_b']))}</p>", "#7b1e1e")
    body += _card("Concessions Wanted", "<h3>Side A Wants</h3>" + _ul(plan.get("side_a_wants", [])) + "<h3>Side B Wants</h3>" + _ul(plan.get("side_b_wants", [])), "#3a6898")
    body += _card("Research Packet", _research_table(plan.get("research", [])), "#2a6a2a")
    body += _card("DM Red Lines", "<h3>Side A Hidden Red Lines</h3>" + _ul(plan.get("side_a_red_lines", [])) + "<h3>Side B Hidden Red Lines</h3>" + _ul(plan.get("side_b_red_lines", [])), "#7b1e1e")
    body += _card("Lots Of Dialogue", _dialogue_html(plan.get("dialogue", [])), "#555")
    favors = plan.get("outside_favors", [])
    body += _card("Outside Favors", _research_table([
        {"lane": f.get("source"), "place": f.get("ask"), "check": "favor", "dc": dcs["standard"], "result": f.get("cost"), "marker_effect": f.get("marker_effect"), "risk": f.get("cost")}
        for f in favors
    ]), "#8a5a1f")
    body += _card("Escalations", _ul(plan.get("escalations", [])) + f"<p><strong>Apology mode:</strong> {_e(plan.get('apology_mode'))}</p>", "#7b1e1e")
    body += _card("Outcome / Debrief", _table([
        ("Total success (-2 to +2)", plan.get("success_terms", "")),
        ("Rough Side A success", plan.get("rough_terms_a", "")),
        ("Rough Side B success", plan.get("rough_terms_b", "")),
        ("Failure spawns", plan.get("failure_spawn", situation["failure"])),
        ("Debrief", plan.get("debrief", "")),
    ]), "#2a6a2a")
    from src.treasure import loot_card as _loot_card
    body += _loot_card(mission)
    return _page(title, body, roles["sponsor"], mission_id=mission.get("id"))


def render_negotiation_session(mission: dict, roles: Dict[str, str], plan: Dict[str, Any], marker: int, dcs: Dict[str, int]) -> str:
    title = mission.get("title", "Negotiation")
    fc = _faction_color(roles["sponsor"])
    body = f"<h1 style='color:{fc};'>{_e(title)}</h1>"
    body += _card("Current Room", _table([
        ("Side A", roles["side_a"]),
        ("Side B", roles["side_b"]),
        ("Marker start", marker),
        ("Current marker", "<input type='number' min='-10' max='10' style='width:60px;'>"),
        ("Target", "0 = agreement"),
    ]), fc)
    body += _card("Concessions", "<h3>Side A Wants</h3>" + _ul(plan.get("side_a_wants", [])) + "<h3>Side B Wants</h3>" + _ul(plan.get("side_b_wants", [])), "#3a6898")

    # Research lane checklist — one checkbox per lane
    research = plan.get("research", [])
    if research:
        lane_checks = "".join(
            f'<label style="display:flex;align-items:flex-start;gap:8px;padding:5px 0;border-bottom:1px solid #eee;">'
            f'<input type="checkbox" style="margin-top:3px;flex-shrink:0;">'
            f'<span><strong>{_e(r.get("lane","Lane"))}</strong> — {_e(r.get("check","Check"))} DC {_e(r.get("dc","?"))} '
            f'<em style="color:#555;">({_e(r.get("place",""))})</em>'
            f'<br><span style="font-size:12px;color:#2a6a2a;">Find: {_e(r.get("result",""))}</span>'
            f'<span style="font-size:12px;color:#7b1e1e;margin-left:12px;">Marker: {_e(r.get("marker_effect",""))}</span>'
            f'</span></label>'
            for r in research
        )
        body += _card("Research Lanes", lane_checks, "#2a6a2a")
    else:
        body += _card("Research / Favor Tracker", "<textarea rows='5' style='width:100%;font-family:inherit;'></textarea>", "#2a6a2a")

    # Escalation checklist
    escalations = plan.get("escalations", [])
    if escalations:
        esc_checks = "".join(
            f'<label style="display:flex;align-items:center;gap:8px;padding:4px 0;">'
            f'<input type="checkbox"> <span>{_e(e)}</span></label>'
            for e in escalations
        )
        body += _card("Escalation Triggers", esc_checks, "#7b1e1e")

    body += _card("Skill DCs", _table([("Easy", dcs["easy"]), ("Standard", dcs["standard"]), ("Hard", dcs["hard"]), ("Severe", dcs["severe"])]), "#8a5a1f")
    body += _card("Result", (
        "<p><strong>Final marker:</strong> <input type='number' min='-10' max='10' style='width:60px;'></p>"
        "<p><label style='display:flex;align-items:center;gap:8px;'><input type='checkbox'> Agreement signed</label></p>"
        "<p><label style='display:flex;align-items:center;gap:8px;'><input type='checkbox'> Failure spawned follow-up</label></p>"
        "<p><label style='display:flex;align-items:center;gap:8px;'><input type='checkbox'> Escalation triggered</label></p>"
        "<p><strong>Follow-up type:</strong> <input type='text' style='width:200px;'></p>"
        "<textarea rows='4' style='width:100%;font-family:inherit;margin-top:8px;'>Debrief notes...</textarea>"
    ), "#7b1e1e")
    return _page(title, body, roles["sponsor"], mission_id=mission.get("id"))


def _dm_guide_md(title: str, roles: Dict[str, str], situation: Dict[str, str], plan: Dict[str, Any], marker: int, dcs: Dict[str, int], strength: Dict[str, Any]) -> str:
    return (
        f"## Negotiation DM Guide\n"
        f"### The Situation\n{plan.get('what_happened', '')}\n\n"
        f"### Balance Marker\nStart: {marker}. Goal: 0.\n\n"
        f"| Band | Result |\n|---|---|\n"
        + "\n".join(f"| {lo} to {hi} | {label}: {effect} |" for lo, hi, label, effect in OUTCOME_BANDS)
        + f"\n\n### Hidden Red Lines\n"
        f"Side A ({roles['side_a']}):\n" + "\n".join(f"- {x}" for x in plan.get("side_a_red_lines", []))
        + f"\n\nSide B ({roles['side_b']}):\n" + "\n".join(f"- {x}" for x in plan.get("side_b_red_lines", []))
        + f"\n\n### Dialogue Bank\n" + "\n".join(f"- {line}" for line in plan.get("dialogue", []))
        + f"\n\n### Escalations\n" + "\n".join(f"- {x}" for x in plan.get("escalations", []))
        + f"\n\n### Failure Spawn\nIf the table breaks, seed a {plan.get('failure_spawn', situation['failure'])} mission.\n\n"
        f"### Difficulty\n{_party_scaling_note(strength)} DCs: easy {dcs['easy']}, standard {dcs['standard']}, hard {dcs['hard']}, severe {dcs['severe']}."
    )


def _players_guide_md(roles: Dict[str, str], situation: Dict[str, str], location: Dict[str, str], plan: Dict[str, Any]) -> str:
    return (
        f"## Negotiation Player Guide\n"
        f"### What Happened\n{plan.get('what_happened', '')}\n\n"
        f"### Who Is At The Table\n"
        f"- {roles['side_a']}: {plan.get('side_a_delegate', '')}\n"
        f"- {roles['side_b']}: {plan.get('side_b_delegate', '')}\n\n"
        f"### Where Negotiations Stand\n{plan.get('current_state', '')}\n\n"
        f"### Location\n{location.get('name')} in {location.get('district')}.\n\n"
        f"### Concessions Each Side Wants\n"
        f"{roles['side_a']} wants:\n" + "\n".join(f"- {x}" for x in plan.get("side_a_wants", []))
        + f"\n\n{roles['side_b']} wants:\n" + "\n".join(f"- {x}" for x in plan.get("side_b_wants", []))
        + "\n\nThe goal is not to make one side happy. The goal is a deal both sides can survive."
    )


def _chart_pack_md(plan: Dict[str, Any], dcs: Dict[str, int], marker: int) -> str:
    return (
        f"## Negotiation Chart Pack\n"
        f"### Marker\nStart at {marker}. Move toward 0 for balanced concessions. Move away from 0 when one side gets too much.\n\n"
        f"### Skill DCs\n| Difficulty | DC |\n|---|---|\n"
        + "\n".join(f"| {k.title()} | {v} |" for k, v in dcs.items())
        + "\n\n### Research Lanes\n| Lane | Check | What It Finds |\n|---|---|---|\n"
        + "\n".join(f"| {lane} | {skill} | {detail} |" for lane, skill, detail in RESEARCH_LANES)
        + "\n\n### Generated Research\n| Lane | Result | Marker | Risk |\n|---|---|---|---|\n"
        + "\n".join(f"| {r.get('lane') or '—'} | {r.get('result') or '—'} | {r.get('marker_effect') or '—'} | {r.get('risk') or '—'} |" for r in plan.get("research", []))
        + "\n\n### Outside Favor Costs\n" + "\n".join(f"- {c}" for c in FAVOR_COSTS)
    )


async def build_negotiation_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Negotiation")
    tier = mission.get("tier", "standard")
    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    roles = _resolve_sides(mission)
    strength = _party_strength()
    dcs = _dc_profile(tier, strength)
    marker = _start_marker(tier)
    situation = _pick_situation(mission)
    location = _pick_location()
    seeds = _canon_seed(roles)

    logger.info(f"[NEGOTIATION] Building {title!r} | {roles['side_a']} vs {roles['side_b']} | marker={marker}")

    plan = await _generate_plan(mission, roles, situation, location, marker, dcs, strength, seeds)

    from src.mission_builder.mimir_module import create_module as _mc, render_mimir_section as _ms, push_documents as _mpd, enrich_mission_loot as _mel
    _mimir_id = await _mc(mission, mission_type="negotiation")
    module_html = render_negotiation_module(mission, roles, situation, location, plan, marker, dcs, strength)
    _loot_rewards = await _mel(_mimir_id or "", mission)
    module_html += _ms([], _loot_rewards, _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")
    session_html = render_negotiation_session(mission, roles, plan, marker, dcs)
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component
    _neg_dm     = _dm_guide_md(title, roles, situation, plan, marker, dcs, strength)
    _neg_players = _players_guide_md(roles, situation, location, plan)
    _neg_chart   = _chart_pack_md(plan, dcs, marker)
    write_component(out_dir, "dm_guide", "DM Guide", title, roles["sponsor"], _neg_dm)
    write_component(out_dir, "players_guide", "Players Guide", title, roles["sponsor"], _neg_players)
    write_component(out_dir, "chart_pack", "Chart Pack", title, roles["sponsor"], _neg_chart)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",         "type": "description", "content": _neg_players},
            {"title": f"{title} — DM Notes",              "type": "dm_notes",    "content": _neg_dm},
            {"title": f"{title} — Leverage & Concessions","type": "custom",      "content": _neg_chart},
        ])
    # Pull a venue/meeting-room map from the library
    _neg_maps: list = []
    try:
        from src.battle_map_library import copy_library_map_for_mission
        from src.mission_builder.html_renderer import render_maps_page
        _neg_lib = copy_library_map_for_mission(
            mission, out_dir / "maps" / "venue.png",
            mission_type="negotiation", map_type="interior",
            district=location.get("district", "") if isinstance(location, dict) else "",
        )
        if _neg_lib:
            _neg_maps = [_neg_lib]
            (out_dir / "maps.html").write_text(
                render_maps_page(title, roles["sponsor"], _neg_maps, "{}"), encoding="utf-8"
            )
    except Exception as _neg_me:
        logger.warning(f"[NEGOTIATION] Library map failed: {_neg_me}")

    box_components = component_links(has_maps=bool(_neg_maps))
    if _neg_maps:
        box_components.append(("maps", "maps.html"))

    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title,
            faction=roles["sponsor"],
            tier=tier,
            cr=mission_cr(mission),
            player_name=mission.get("player_name", "") or "Open",
            chapters=[],
            components=box_components,
            chart_pack=None,
            map_count=0,
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as e:
        logger.warning(f"[NEGOTIATION] index.html failed: {e}")
        index_path = out_dir / "module.html"

    try:
        from src.mission_builder.mission_db import write_module_slug_for_mission
        write_module_slug_for_mission(mission, out_dir.name, log_prefix="NEGOTIATION")
    except Exception as e:
        logger.warning(f"[NEGOTIATION] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[NEGOTIATION] Complete: {title!r} -> {out_dir.name}")
    return index_path
