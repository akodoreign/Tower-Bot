"""
investigation_pipeline.py - Investigation mission modules.

Investigation is a multi-day, skill-driven mission type. The party follows
leads in any order, builds an evidence board, interviews witnesses, tests
theories, and resolves the case through proof instead of a tactical map.

No map generation here. Use strong location / room descriptions, witness
behavior, clue quality, and changing public pressure.

Exported:
    build_investigation_module(mission: dict, out_dir: Path) -> Path
    is_investigation_mission(mission_type: str) -> bool
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

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "generated_modules"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")


_INVESTIGATION_KEYWORDS = {
    "investigation", "investigate", "mystery", "case", "missing person",
    "murder", "suspicious death", "theft", "stolen", "corruption",
    "blackmail", "fraud", "forgery", "cover-up", "cover up", "cult activity",
    "strange illness", "curse", "false accusation", "witness protection",
    "arson", "illegal auction", "identity swap", "impersonation",
    "memory tampering", "divine omen", "doppelganger", "fake adventurer",
    "disappearance of evidence", "unexplained resurrection", "cursed object",
}


def is_investigation_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _INVESTIGATION_KEYWORDS)


CASE_TYPES = [
    "missing person",
    "murder / suspicious death",
    "theft / missing item",
    "corruption / blackmail",
    "monster or rift incident",
    "faction conspiracy",
    "fraud / forged records",
    "cult activity",
    "strange illness or curse",
    "false accusation",
    "witness protection",
    "aftermath truth-finding",
    "arson",
    "sabotage aftermath",
    "illegal auction / market fraud",
    "identity swap / impersonation",
    "memory tampering",
    "divine omen / shrine incident",
    "doppelganger or replaced NPC",
    "fake adventurer party",
    "official cover-up",
    "disappearance of evidence",
    "unexplained resurrection",
    "cursed object trail",
]

TONES = [
    "noir",
    "Scooby-Doo antics",
    "occult",
    "procedural",
    "urban weird",
    "comic red herring",
    "surreal civic bureaucracy",
    "melancholy aftermath",
    "faction paranoia",
]

SCOOBY_ANTICS = [
    "wrong doors in a back hallway",
    "suspicious janitor energy",
    "chase through storage rooms",
    "bad disguise that still fools one witness",
    "fake monster / real monster ambiguity",
    "absurd clue that is still useful",
    "split-up consequence",
    "witness tells the truth badly",
    "suspect is guilty of a completely unrelated thing",
    "dramatic unmasking",
    "culprit tries to flee during the reveal",
    "false supernatural masking mundane crime",
    "mundane explanation masking something genuinely weird",
]

LEAD_PATHS = [
    {
        "key": "scene",
        "label": "Scene Work",
        "skills": ["Investigation", "Perception", "Survival", "Arcana", "Medicine"],
        "focus": "physical clues, room logic, residue, footprints, timing, contamination",
    },
    {
        "key": "people",
        "label": "Witnesses And Suspects",
        "skills": ["Insight", "Persuasion", "Intimidation", "Deception", "Performance"],
        "focus": "interviews, alibis, tells, omissions, social pressure, gossip",
    },
    {
        "key": "records",
        "label": "Records And Paper Trail",
        "skills": ["Investigation", "History", "Arcana", "Religion", "Sleight of Hand"],
        "focus": "ledgers, permits, auction records, old notices, erased names, forged entries",
    },
    {
        "key": "faction",
        "label": "Faction Pressure",
        "skills": ["Insight", "History", "Persuasion", "Intimidation", "Religion"],
        "focus": "who benefits, who wants quiet, who wants scandal, reputational motive",
    },
    {
        "key": "strange",
        "label": "The Weird Angle",
        "skills": ["Arcana", "Religion", "Nature", "Medicine", "Investigation"],
        "focus": "rift residue, omens, curses, impossible memories, soul or resurrection weirdness",
    },
    {
        "key": "media",
        "label": "TNN / Rumor Mill",
        "skills": ["Persuasion", "Deception", "Insight", "Performance", "Investigation"],
        "focus": "leaks, interviews, bad headline pressure, recorded contradiction, baiting a culprit",
    },
]

FAILURE_COSTS = [
    "time is lost and the case moves into the next day",
    "a suspect learns the party is asking the right questions",
    "a witness clams up until approached differently",
    "evidence is contaminated but not destroyed",
    "the party gets a true clue attached to a misleading interpretation",
    "a faction files a formal complaint",
    "TNN frames the party as reckless investigators",
    "a rival investigator starts following the same lead",
    "the culprit moves one piece of evidence",
    "the party is accused of snooping",
    "a witness tells the truth in the most confusing way possible",
    "an unrelated secret creates social debt",
    "occult backlash causes a bad dream or omen during long rest",
]

RESOLUTIONS = [
    "name the culprit or cause",
    "present evidence to the sponsor",
    "clear an innocent suspect",
    "confront the culprit",
    "prevent the next incident",
    "expose a cover-up",
    "quietly bury the truth to protect someone",
    "leak the proof to TNN",
    "hand evidence to Tower Authority",
    "bargain with the culprit",
    "prove supernatural cause",
    "prove fake supernatural cause",
    "discover the victim staged it",
    "discover the culprit was coerced",
    "unlock a follow-up rescue, sabotage, bounty, or assault",
]

LONG_REST_REVELATIONS = [
    "A PC dreams the same room from the wrong angle and realizes a witness described something they could not have seen.",
    "During watch, someone remembers a smell, hymn, tool mark, or phrase that links two unrelated leads.",
    "A copied note changes meaning after sleep because the party remembers the missing punctuation or emblem placement.",
    "A divine, rift, or memory echo shows one image: a hand, a doorway, a mask, a bell, or an old wound.",
    "A witness sends a late-night message: they lied earlier, but only about why they were present.",
    "An exhausted PC realizes the obvious suspect had the wrong motive and the right alibi.",
    "A long-rest nightmare reveals that the fake supernatural clue is hiding a mundane mechanical trick.",
    "A quiet morning rumor contradicts the official timeline by one impossible hour.",
]

GENERIC_INVESTIGATION_MARKERS = [
    "rumor, fear, and faction pressure decide the answer",
    "protecting a secret, debt, reputation, or faction leverage",
    "at least two witnesses are hiding unrelated secrets",
    "street version blames",
    "solve a public mystery",
]


def _default_clue_check(item: Any, idx: int) -> Dict[str, Any]:
    text = json.dumps(item, ensure_ascii=False).lower() if isinstance(item, dict) else str(item).lower()
    source = str(item.get("source", "")).lower() if isinstance(item, dict) else ""
    if any(term in text or term in source for term in ("record", "ledger", "paper", "archive", "seal", "permit")):
        skill = "Investigation"
    elif any(term in text or term in source for term in ("witness", "interview", "alibi", "testimony", "social")):
        skill = "Insight"
    elif any(term in text or term in source for term in ("scene", "footprint", "physical", "blood", "residue")):
        skill = "Perception"
    elif any(term in text or term in source for term in ("ritual", "rift", "magic", "curse", "omen")):
        skill = "Arcana"
    else:
        skill = "Investigation"
    return {"skill": skill, "dc": 13 + (idx % 3)}


def _normalize_clue_web(items: List[Any], fallback: List[Any]) -> List[Dict[str, Any]]:
    source_items = items if isinstance(items, list) and items else fallback
    normalized = []
    for idx, item in enumerate(source_items):
        defaults = _default_clue_check(item, idx)
        if isinstance(item, dict):
            entry = dict(item)
            entry.setdefault("clue", "")
            entry.setdefault("source", "")
            entry.setdefault("proves", "")
            entry.setdefault("unlocks", "")
        else:
            entry = {"clue": str(item), "source": "", "proves": "", "unlocks": ""}
        entry["skill"] = entry.get("skill") or entry.get("check_skill") or defaults["skill"]
        raw_dc = entry.get("dc") or entry.get("DC") or entry.get("check_dc") or defaults["dc"]
        try:
            entry["dc"] = int(raw_dc)
        except (TypeError, ValueError):
            entry["dc"] = defaults["dc"]
        entry["dc"] = max(10, min(22, entry["dc"]))
        normalized.append(entry)
    return normalized


def _mission_text(mission: dict) -> str:
    parts = []
    for key in ("title", "body", "description", "private_notes", "public_text", "story_text", "contact", "personal_for", "opposing_faction"):
        val = mission.get(key)
        if val not in (None, ""):
            parts.append(str(val))
    raw_json = mission.get("mission_json")
    data = _json_col(raw_json, {}) if raw_json else {}
    if isinstance(data, dict):
        for key in ("body", "private_notes", "public_text", "story_text", "contact", "personal_for", "opposing_faction", "reward"):
            val = data.get(key)
            if val not in (None, ""):
                parts.append(str(val))
    return "\n".join(parts)


def _mission_context(mission: dict) -> Dict[str, Any]:
    text = _mission_text(mission)
    raw_json = mission.get("mission_json")
    data = _json_col(raw_json, {}) if raw_json else {}
    if not isinstance(data, dict):
        data = {}
    terms = []
    for key in ("title", "contact", "personal_for", "opposing_faction"):
        val = mission.get(key) or data.get(key)
        if val:
            terms.append(str(val))
    for match in re.findall(r"\*([^*\n]{3,80})\*", text):
        terms.append(match.strip())
    for match in re.findall(r"\b[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){0,4}\b", text):
        if match.lower() not in {"type", "tier", "expires", "reward", "opposes", "contact", "gm notes"}:
            terms.append(match.strip())
    lower = text.lower()
    stakes = [s for s in ("betrayal", "cover up", "stolen", "relic", "weaponized", "trap", "former ally", "dome", "breach", "false accusation", "missing", "murder") if s in lower]
    seen = set()
    canon_terms = []
    for term in terms:
        term = term.strip(" -*")
        if term and term.lower() not in seen:
            seen.add(term.lower())
            canon_terms.append(term)
    return {"text": text, "canon_terms": canon_terms[:12], "stakes": stakes[:8]}


def _specificity_score(plan: Dict[str, Any], context: Dict[str, Any]) -> int:
    haystack = json.dumps(plan, ensure_ascii=False).lower()
    score = 0
    for term in context.get("canon_terms", [])[:8]:
        bits = [b for b in re.split(r"\s+", str(term).lower()) if len(b) > 3]
        if bits and any(bit in haystack for bit in bits):
            score += 1
    for stake in context.get("stakes", []):
        if stake.lower() in haystack:
            score += 1
    return score


def _is_generic_plan(plan: Dict[str, Any], context: Dict[str, Any]) -> bool:
    haystack = json.dumps(plan, ensure_ascii=False).lower()
    marker_hits = sum(1 for marker in GENERIC_INVESTIGATION_MARKERS if marker in haystack)
    return marker_hits >= 2 or _specificity_score(plan, context) < 3


def _db_rows(query: str, params: tuple = ()) -> List[Dict]:
    try:
        from src.db_api import raw_query
        return raw_query(query, params) or []
    except Exception as e:
        logger.warning(f"[INVESTIGATION] DB read failed: {e}")
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


def _find_skill_map(data: Any) -> Dict[str, Any]:
    if isinstance(data, dict):
        for key in ("skills", "skill_mods", "skill_modifiers", "proficiencies"):
            val = data.get(key)
            if isinstance(val, dict):
                return val
        for val in data.values():
            found = _find_skill_map(val)
            if found:
                return found
    if isinstance(data, list):
        for val in data:
            found = _find_skill_map(val)
            if found:
                return found
    return {}


def _party_strength() -> Dict[str, Any]:
    snap_rows = _db_rows(
        "SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC"
    )
    profile_rows = _db_rows(
        "SELECT name, class_name, species, player_name, profile_json FROM player_characters"
    )
    profiles = {str(r.get("name") or "").lower(): r for r in profile_rows}
    pcs = []
    skill_counts: Dict[str, int] = {}

    for row in snap_rows:
        snap = _json_col(row.get("snapshot_json"), {})
        if not isinstance(snap, dict):
            continue
        name = snap.get("name") or row.get("char_name") or "Unknown PC"
        level = int(snap.get("total_level") or snap.get("level") or 0)
        if level <= 0:
            continue
        profile = profiles.get(str(name).lower()) or {}
        profile_json = _json_col(profile.get("profile_json"), {})
        skills = _find_skill_map(profile_json)
        top_skills = []
        if isinstance(skills, dict):
            for sk, val in skills.items():
                mod = val.get("modifier") if isinstance(val, dict) else val
                if isinstance(mod, (int, float)) and mod >= 3:
                    top_skills.append((str(sk).replace("_", " ").title(), int(mod)))
                    skill_counts[str(sk).replace("_", " ").title()] = skill_counts.get(str(sk).replace("_", " ").title(), 0) + 1
        top_skills = sorted(top_skills, key=lambda x: x[1], reverse=True)[:5]
        pcs.append({
            "name": name,
            "level": level,
            "class": profile.get("class_name") or snap.get("class") or "",
            "top_skills": top_skills,
        })

    levels = [p["level"] for p in pcs] or [5]
    party_top = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:8]
    return {
        "party_size": len(pcs) or 4,
        "avg_level": round(sum(levels) / len(levels), 1),
        "max_level": max(levels),
        "pcs": pcs,
        "investigation_level": max(levels) + 4,
        "party_top_skills": party_top,
    }


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    skills = ", ".join(f"{name} x{count}" for name, count in strength.get("party_top_skills", [])[:5])
    skill_note = f" Strong visible skills: {skills}." if skills else ""
    return (
        f"Live party read: {strength['party_size']} PCs, average level {strength['avg_level']}, "
        f"max level {strength['max_level']}; case pressure can assume party +4 levels "
        f"(investigation level {strength['investigation_level']}).{skill_note}"
    )


def _factions() -> List[Dict]:
    rows = _db_rows(
        "SELECT faction_name, reputation_score, tier FROM faction_reputation ORDER BY faction_name"
    )
    return rows or [
        {"faction_name": "Adventurers Guild", "tier": "Liked", "reputation_score": 0},
        {"faction_name": "Tower Authority", "tier": "Neutral", "reputation_score": 0},
        {"faction_name": "Patchwork Saints", "tier": "Neutral", "reputation_score": 0},
    ]


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
    pressure = _canon(mission.get("opposing_faction") or mission.get("pressure_faction") or "", factions)
    if not pressure:
        choices = [f["faction_name"] for f in factions if f.get("faction_name") and f["faction_name"] != sponsor]
        pressure = random.choice(choices or ["Unknown Pressure"])
    return {"sponsor": sponsor, "pressure": pressure}


def _pick_case_type(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    for case_type in CASE_TYPES:
        if any(piece.strip() and piece.strip() in text for piece in case_type.replace("/", " ").split()):
            if case_type.split()[0] in text or case_type.replace(" / ", " ") in text:
                return case_type
    if "missing" in text:
        return "missing person"
    if "murder" in text or "death" in text:
        return "murder / suspicious death"
    if "auction" in text or "market" in text:
        return "illegal auction / market fraud"
    if "memory" in text:
        return "memory tampering"
    if "doppelganger" in text or "replace" in text:
        return "doppelganger or replaced NPC"
    return random.choice(CASE_TYPES)


def _pick_tones() -> Dict[str, str]:
    primary = random.choice(TONES)
    secondary = random.choice([t for t in TONES if t != primary])
    wildcard = random.choice(SCOOBY_ANTICS)
    return {"primary": primary, "secondary": secondary, "wildcard": wildcard}


def _sample_text(rows: List[Dict], keys: List[str], limit: int = 4) -> List[str]:
    out = []
    for row in rows[:limit]:
        parts = []
        for key in keys:
            val = row.get(key)
            if val not in (None, ""):
                parts.append(str(val))
        if parts:
            out.append(" - ".join(parts))
    return out


def _case_seed(case_type: str, roles: Dict[str, str]) -> Dict[str, Any]:
    seeds: Dict[str, Any] = {"canon": [], "entities": [], "weird": []}

    seeds["canon"].extend(_sample_text(
        _db_rows("SELECT facts FROM news_memory ORDER BY id DESC LIMIT 8"),
        ["facts"],
        4,
    ))
    seeds["canon"].extend(_sample_text(
        _db_rows("SELECT mission_title, result, key_decisions, loose_threads, notable_moments FROM mission_outcomes ORDER BY id DESC LIMIT 6"),
        ["mission_title", "result", "key_decisions", "loose_threads", "notable_moments"],
        3,
    ))

    if "missing" in case_type:
        seeds["entities"].extend(_sample_text(
            _db_rows("SELECT person_name, last_seen_location, status FROM missing_persons ORDER BY reported_at DESC LIMIT 5"),
            ["person_name", "last_seen_location", "status"],
            3,
        ))
    if "auction" in case_type or "market" in case_type or "fraud" in case_type:
        seeds["entities"].extend(_sample_text(
            _db_rows("SELECT item_name, seller_name, current_bid, status FROM towerbay_auctions ORDER BY id DESC LIMIT 5"),
            ["item_name", "seller_name", "current_bid", "status"],
            3,
        ))
        seeds["entities"].extend(_sample_text(
            _db_rows("SELECT sector, value, trend, state_json FROM tia_market ORDER BY id DESC LIMIT 5"),
            ["sector", "value", "trend", "state_json"],
            3,
        ))
    if "fake adventurer" in case_type:
        seeds["entities"].extend(_sample_text(
            _db_rows("SELECT party_name, members_json, reputation, status FROM party_profiles ORDER BY RAND() LIMIT 4"),
            ["party_name", "reputation", "status"],
            3,
        ))

    seeds["entities"].extend(_sample_text(
        _db_rows("SELECT name, faction, role, location FROM npcs ORDER BY RAND() LIMIT 8"),
        ["name", "faction", "role", "location"],
        5,
    ))
    seeds["entities"].extend(_sample_text(
        _db_rows("SELECT name, district, place_type, description FROM gazetteer_places ORDER BY RAND() LIMIT 8"),
        ["name", "district", "place_type", "description"],
        5,
    ))
    seeds["weird"].extend(_sample_text(
        _db_rows("SELECT active, intensity, location, effects_json FROM rift_state LIMIT 2"),
        ["active", "intensity", "location", "effects_json"],
        2,
    ))
    seeds["weird"].extend(_sample_text(
        _db_rows("SELECT npc_name, died_at, resurrect_at, status FROM resurrection_queue ORDER BY id DESC LIMIT 4"),
        ["npc_name", "died_at", "resurrect_at", "status"],
        3,
    ))
    seeds["weird"].extend(_sample_text(
        _db_rows("SELECT name, domain, alignment FROM gods ORDER BY RAND() LIMIT 4"),
        ["name", "domain", "alignment"],
        3,
    ))

    if not seeds["entities"]:
        seeds["entities"].append(f"{roles['sponsor']} asks the party to solve a public mystery before the story hardens.")
    return seeds


def _pick_locations(case_type: str) -> List[Dict[str, str]]:
    rows = _db_rows("SELECT name, district, place_type, description FROM gazetteer_places ORDER BY RAND() LIMIT 7")
    locations = []
    for row in rows[:5]:
        locations.append({
            "name": row.get("name") or "Unnamed Scene",
            "district": row.get("district") or "Unknown District",
            "type": row.get("place_type") or "location",
            "description": row.get("description") or "A location with too many witnesses and not enough certainty.",
        })
    while len(locations) < 5:
        locations.append(random.choice([
            {"name": "The First Scene", "district": "case site", "type": "scene", "description": "The original room, street, shrine, or office where the story began."},
            {"name": "Back Room", "district": "nearby", "type": "room", "description": "A cramped secondary room with a forgotten exit, loose records, and one thing out of place."},
            {"name": "Witness Corner", "district": "public", "type": "street", "description": "A place where people saw enough to be useful and too little to be reliable."},
            {"name": "Records Desk", "district": "civic", "type": "office", "description": "A desk full of forms, seals, omissions, and someone who hates being asked twice."},
            {"name": "Quiet Shrine", "district": "old city", "type": "shrine", "description": "A place where rumor, guilt, and prayer overlap."},
        ]))
    return locations[:5]


def _pick_suspects(roles: Dict[str, str]) -> List[Dict[str, str]]:
    rows = _db_rows("SELECT name, faction, role, location, description FROM npcs ORDER BY RAND() LIMIT 8")
    roles_pool = [
        "actual culprit or proximate cause",
        "obvious suspect",
        "sympathetic liar",
        "comic red herring",
        "dangerous unrelated secret",
        "witness who saw part of it",
        "good-reason hider",
        "faction pressure source",
    ]
    suspects = []
    for idx, row in enumerate(rows[:6]):
        suspects.append({
            "name": row.get("name") or f"Suspect {idx + 1}",
            "faction": row.get("faction") or (roles["pressure"] if idx % 2 else roles["sponsor"]),
            "role": row.get("role") or roles_pool[idx % len(roles_pool)],
            "location": row.get("location") or "unknown",
            "case_role": roles_pool[idx % len(roles_pool)],
            "note": row.get("description") or "Has a reason to be in the story and a reason to avoid telling all of it.",
        })
    while len(suspects) < 6:
        idx = len(suspects)
        suspects.append({
            "name": f"Unlisted Suspect {idx + 1}",
            "faction": roles["pressure"] if idx % 2 else roles["sponsor"],
            "role": "local",
            "location": "case area",
            "case_role": roles_pool[idx % len(roles_pool)],
            "note": "A fallback suspect generated because the DB did not provide enough usable NPCs.",
        })
    return suspects


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


async def _ollama(prompt: str, system: str = "", tokens: int = 1800) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.82, "num_predict": tokens, "num_ctx": _fit_ctx(system + prompt, tokens)},
    }
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("investigation_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[INVESTIGATION] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[INVESTIGATION] Ollama error: {e}")
        return ""


def _clean_json(raw: str) -> str:
    raw = raw.replace("\x5c\x27", "\x27")
    raw = raw.replace("\u2018", "'").replace("\u2019", "'")
    raw = raw.replace("\u201c", '"').replace("\u201d", '"')
    raw = raw.replace("\u2013", "-").replace("\u2014", "-")
    cleaned, in_string = [], False
    for i, ch in enumerate(raw):
        if ch == '"' and (i == 0 or raw[i - 1] != "\\"):
            in_string = not in_string
            cleaned.append(ch)
        elif in_string and ord(ch) in (10, 13):
            cleaned.append(" ")
        else:
            cleaned.append(ch)
    return "".join(cleaned)


def _parse_json(raw: str) -> Optional[dict]:
    for attempt in (raw, _clean_json(raw or "")):
        m = re.search(r"\{[\s\S]*\}", attempt)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return None


def _fallback_plan(mission: dict, case_type: str, roles: Dict[str, str], tones: Dict[str, str], locations: List[Dict[str, str]], suspects: List[Dict[str, str]]) -> Dict[str, Any]:
    culprit = suspects[0]
    context = _mission_context(mission)
    title = mission.get("title") or f"{case_type.title()} Investigation"
    anchor = context["canon_terms"][0] if context.get("canon_terms") else title
    stake = ", ".join(context.get("stakes", [])[:4]) or "reputation, leverage, and public trust"
    return {
        "case_title": title,
        "briefing": f"{roles['sponsor']} needs the party to solve {anchor} before {stake} hardens into the official story. The contact gives the party enough public facts to begin, but the useful truth is buried in witness omissions, records, and one scene detail that does not match the rumor.",
        "truth": f"{culprit['name']} is tied to the real cause behind {anchor}; the public version is wrong because it mistakes a cover story for motive.",
        "public_story": f"The street version blames {roles['pressure']} and keeps changing every few hours around {anchor}.",
        "timeline": [
            "Day 1 morning: briefing and first scene.",
            "Day 1 afternoon: first interviews and records.",
            "Day 1 night: first contradiction becomes obvious.",
            "Day 2: faction pressure, second interviews, and weird angle.",
            "Day 3: final theory, confrontation, or public reveal.",
        ],
        "culprit_or_cause": culprit["name"],
        "motive": f"Protecting {stake} while keeping {roles['sponsor']} or {roles['pressure']} from owning the scandal.",
        "twist": f"{tones['wildcard']} complicates the clean explanation.",
        "long_rest_revelation": random.choice(LONG_REST_REVELATIONS) if random.random() < 0.25 else "None expected; the case can still move through ordinary deduction.",
        "resolution": random.sample(RESOLUTIONS, 5),
        "clue_web": [
            {"clue": f"A witness uses the wrong name for {anchor}.", "source": "first interview", "skill": "Insight", "dc": 13, "proves": "They learned the story secondhand or were coached.", "unlocks": "records lead"},
            {"clue": f"A record connected to {anchor} has one altered date or seal.", "source": "paper trail", "skill": "Investigation", "dc": 14, "proves": "The official timeline is engineered.", "unlocks": "pressure faction lead"},
            {"clue": f"A physical detail at the scene contradicts the public story.", "source": "scene work", "skill": "Perception", "dc": 15, "proves": "The case cannot be solved from testimony alone.", "unlocks": "final theory"},
        ],
        "scene_secrets": [
            f"The first scene contains one detail that only matters after the party hears {culprit['name']}'s alibi.",
            "One witness is lying about why they were present, not about what they saw.",
            f"{roles['pressure']} benefits from the rumor but may not be the true culprit.",
        ],
        "accusation_standard": "The party should be able to name the culprit/cause, prove motive, explain the false public story, and cite at least three independent clues before the final reveal.",
        "witness_list": [
            {
                "name": culprit["name"],
                "what_they_say_publicly": f"Nothing unusual happened around {anchor}.",
                "what_they_know": f"They were present when the incident occurred and saw something that contradicts the public story.",
                "dc_to_get_truth": 14,
                "how_to_break": "Catch them in a contradiction or appeal to their conscience.",
            },
            {
                "name": suspects[1]["name"] if len(suspects) > 1 else "A second witness",
                "what_they_say_publicly": "I only heard about it afterward.",
                "what_they_know": "They were actually present but covered for a faction contact.",
                "dc_to_get_truth": 15,
                "how_to_break": "Present the physical evidence that contradicts their alibi.",
            },
        ],
    }


def _normalize_plan(
    data: Optional[dict],
    mission: dict,
    case_type: str,
    roles: Dict[str, str],
    tones: Dict[str, str],
    locations: List[Dict[str, str]],
    suspects: List[Dict[str, str]],
) -> Dict[str, Any]:
    fallback = _fallback_plan(mission, case_type, roles, tones, locations, suspects)
    if not isinstance(data, dict):
        return fallback

    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    for key in ("timeline", "resolution", "clue_web", "scene_secrets"):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    plan["clue_web"] = _normalize_clue_web(plan.get("clue_web", []), fallback["clue_web"])
    plan.setdefault("long_rest_revelation", "None expected.")
    plan.setdefault("accusation_standard", fallback["accusation_standard"])

    # Strip literal "None"/"null" strings from scalar fields
    _NONE_STRINGS = {"none", "null", "n/a", ""}
    for key in ("public_story", "true_story", "culprit_name", "culprit_motive",
                "accusation_standard", "long_rest_revelation", "debrief"):
        val = plan.get(key)
        if isinstance(val, str) and val.strip().lower() in _NONE_STRINGS:
            plan[key] = fallback.get(key, "")

    if _is_generic_plan(plan, _mission_context(mission)):
        logger.warning("[INVESTIGATION] Generated plan was too generic; using mission-specific fallback")
        return fallback
    return plan


_INCIDENT_BELLS = [
    "first bell", "second bell", "third bell", "fourth bell",
    "midday bell", "evening bell", "late bell", "midnight bell",
]

_DAY_SLOTS = [
    ("Early morning", "first bell to second bell"),
    ("Mid-morning",   "second bell to third bell"),
    ("Late morning",  "third bell to midday"),
    ("Early afternoon","midday to second afternoon bell"),
    ("Late afternoon", "second to fourth afternoon bell"),
    ("Evening",        "evening bell to late bell"),
    ("Night",          "late bell to midnight"),
]

_TRUTH_LEVELS = {
    "actual culprit or proximate cause": ["HALF-TRUTH", "LIE", "HALF-TRUTH", "LIE", "HALF-TRUTH", "HALF-TRUTH"],
    "obvious suspect":     ["TRUTH", "TRUTH", "LIE", "TRUTH", "TRUTH", "HALF-TRUTH"],
    "sympathetic liar":    ["TRUTH", "LIE", "TRUTH", "TRUTH", "LIE", "TRUTH"],
    "comic red herring":   ["TRUTH", "TRUTH", "TRUTH", "TRUTH", "TRUTH", "TRUTH"],
    "dangerous unrelated secret": ["TRUTH", "HALF-TRUTH", "TRUTH", "LIE", "TRUTH", "TRUTH"],
    "witness who saw part of it": ["TRUTH", "TRUTH", "TRUTH", "TRUTH", "TRUTH", "HALF-TRUTH"],
    "good-reason hider":   ["TRUTH", "TRUTH", "LIE", "TRUTH", "TRUTH", "TRUTH"],
    "faction pressure source": ["HALF-TRUTH", "TRUTH", "HALF-TRUTH", "TRUTH", "LIE", "TRUTH"],
}


async def _generate_suspect_timelines(
    suspects: List[Dict[str, str]],
    plan: Dict[str, Any],
    mission: dict,
    incident_time: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Generate a 6-entry witness timeline for each suspect.

    Each entry: time, claim (what they say), voice (verbatim in their words),
    dm_truth (TRUTH/HALF-TRUTH/LIE + DM note), verifiable (bool).

    The culprit's entries deliberately mix half-truths with lies.
    One entry per suspect is always the incident time specifically.
    """
    culprit_name = (plan.get("culprit_or_cause") or "").lower()
    timelines: Dict[str, List[Dict[str, Any]]] = {}

    # Pull some real locations for alibi variety
    alibi_places: List[str] = []
    try:
        rows = _db_rows(
            "SELECT name, district FROM gazetteer_places ORDER BY RAND() LIMIT 12"
        )
        alibi_places = [f"{r['name']} ({r['district']})" for r in rows if r.get("name")]
    except Exception:
        pass
    if not alibi_places:
        alibi_places = ["the market", "their district", "a contact's location", "their usual haunt"]

    for suspect in suspects:
        name      = suspect.get("name", "Unknown")
        faction   = suspect.get("faction", "Independent")
        role      = suspect.get("role", "")
        case_role = suspect.get("case_role", "witness who saw part of it")
        is_culprit = culprit_name and name.lower() == culprit_name

        # Get NPC voice from DB if available
        npc_quote = ""
        npc_motivation = ""
        try:
            npc_rows = _db_rows(
                "SELECT quote, motivation, oracle_notes FROM npcs WHERE LOWER(name) = LOWER(%s) LIMIT 1",
                (name,),
            )
            if npc_rows:
                npc_quote      = npc_rows[0].get("quote") or ""
                npc_motivation = npc_rows[0].get("motivation") or ""
        except Exception:
            pass

        truth_pattern = _TRUTH_LEVELS.get(case_role, ["TRUTH"] * 6)

        # Build the 6 time slots — one is always the incident time
        slots = list(_DAY_SLOTS)
        # Replace one slot with the incident moment
        incident_slot_idx = 2  # default: late morning
        for i, (label, _) in enumerate(slots):
            if any(bell in label.lower() for bell in incident_time.lower().split()):
                incident_slot_idx = i
                break
        slots[incident_slot_idx] = (f"At the incident ({incident_time})", "the exact moment")

        prompt = f"""You are writing interrogation-style witness timelines for a D&D investigation module.

Suspect: {name}
Faction: {faction}
Role in case: {case_role}
{'THIS IS THE ACTUAL CULPRIT.' if is_culprit else ''}
{'Voice sample: ' + npc_quote if npc_quote else ''}
{'Motivation: ' + npc_motivation[:120] if npc_motivation else ''}
Incident time: {incident_time}
Case: {mission.get('title', 'Investigation')}
Case type: {plan.get('case_title', '')}
Truth: {plan.get('truth', '')[:200]}
Culprit or cause: {plan.get('culprit_or_cause', 'unknown')}

Generate a day-of timeline with EXACTLY 6 entries. The entries cover the day the incident happened.
One entry MUST be for the incident time exactly: "{incident_time}".

{'CULPRIT RULES: Mix half-truths with lies so they sound credible. The culprit was present or nearby at the incident time but claims otherwise. Verifiable details (real places, real people) are mixed with false claims to make the story hard to pick apart.' if is_culprit else f'TRUTH PATTERN for this character (entry 1-6): {" / ".join(truth_pattern)} — follow this strictly.'}

Return a JSON array of exactly 6 objects:
[
  {{
    "time": "period label (e.g. Early morning)",
    "claim": "what {name} claims they were doing — one sentence",
    "voice": "their exact words as spoken to investigators — 1-2 sentences in their own voice, specific and character-consistent",
    "dm_truth": "TRUTH / HALF-TRUTH / LIE — followed by a colon and a short DM note explaining the real situation",
    "verifiable": true or false
  }}
]

Available real locations for alibis: {', '.join(alibi_places[:6])}
The entry for "{incident_time}" must always have verifiable=false for the culprit.
Output only the JSON array. No preamble."""

        raw = await _ollama(prompt, tokens=2000)
        entries: List[Dict[str, Any]] = []

        # Parse JSON array
        if raw:
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            m = re.search(r"\[[\s\S]*\]", raw)
            if m:
                try:
                    parsed = json.loads(m.group())
                    if isinstance(parsed, list):
                        entries = parsed[:6]
                except Exception:
                    pass

        # Fallback if LLM failed
        if len(entries) < 6:
            for i, (slot_label, slot_range) in enumerate(slots[len(entries):6]):
                truth = truth_pattern[len(entries) + i] if len(entries) + i < len(truth_pattern) else "TRUTH"
                is_incident = slot_label.startswith("At the incident")
                place = random.choice(alibi_places)
                entries.append({
                    "time": slot_label,
                    "claim": f"Was at {place}" if not is_incident else f"Was not near the incident — can provide no information about {incident_time}",
                    "voice": npc_quote or f"I keep my own schedule. You can ask around.",
                    "dm_truth": f"{truth}: DM-generated fallback — verify against case facts",
                    "verifiable": not is_incident and truth == "TRUTH",
                })

        timelines[name] = entries
        logger.info(f"[INVESTIGATION] Timeline generated for {name} ({case_role}, {'culprit' if is_culprit else 'suspect'})")

    return timelines


async def _generate_plan(
    mission: dict,
    case_type: str,
    roles: Dict[str, str],
    tones: Dict[str, str],
    seeds: Dict[str, Any],
    locations: List[Dict[str, str]],
    suspects: List[Dict[str, str]],
    strength: Dict[str, Any],
) -> Dict[str, Any]:
    context = _mission_context(mission)
    prompt = f"""Write a D&D investigation mission module plan.

Mission: {mission.get('title', 'Investigation')}
Mission notes: {(mission.get('body') or mission.get('description') or '')[:400]}
Case type: {case_type}
Sponsor faction: {roles['sponsor']}
Pressure/opposition faction: {roles['pressure']}
Tone: primary={tones['primary']}; secondary={tones['secondary']}; wildcard={tones['wildcard']}
Live party: {strength['party_size']} PCs, avg level {strength['avg_level']}, max {strength['max_level']}
DB canon seeds: {json.dumps(seeds, ensure_ascii=False)[:3000]}
Locations: {json.dumps(locations, ensure_ascii=False)[:1600]}
Suspects: {json.dumps(suspects, ensure_ascii=False)[:1800]}
Mission-specific canon terms that MUST appear in the module: {json.dumps(context['canon_terms'], ensure_ascii=False)}
Mission-specific stakes that MUST be honored: {json.dumps(context['stakes'], ensure_ascii=False)}
Full mission text for context: {context['text'][:1800]}

Rules:
- This investigation usually spans several in-world days.
- Do not replace the case with a generic mystery shell. Preserve the named PC/NPC, contact, object/relic/victim, site, faction scandal, rival, and consequence from the mission text.
- No map. Use rooms/areas/descriptions, witnesses, evidence, and social pressure.
- Skill checks are king; every lead must fail forward.
- Every lead needs a concrete clue, where it is found, what it proves, what it unlocks, and what failure costs.
- The final accusation must be evidence-based, not just "name the culprit."
- Include rare long-rest revelation only if it adds drama; otherwise say "None expected."
- Include Scooby-Doo antics without making the mystery stupid.
- TNN/media pressure can matter but should not replace clue work.

Return JSON only:
{{
  "case_title": "short title",
  "briefing": "2-3 paragraphs from the contact",
  "truth": "what actually happened",
  "public_story": "what people think happened",
  "timeline": ["5-7 day/time beats, usually over 2-4 days"],
  "culprit_or_cause": "name or cause",
  "motive": "why it happened",
  "twist": "reveal, false mask, or complication",
  "long_rest_revelation": "rare dream/memory/revelation during long rest or None expected",
  "clue_web": [
    {{"clue": "specific clue", "source": "where/who gives it", "skill": "Investigation", "dc": 14, "proves": "what it proves", "unlocks": "next lead"}}
  ],
  "scene_secrets": ["3-6 secrets attached to specific rooms/witnesses/records"],
  "witness_list": [
    {{"name": "witness name", "what_they_say_publicly": "what they tell anyone who asks", "what_they_know": "what they actually know and are hiding", "dc_to_get_truth": 14, "how_to_break": "what pressure or approach makes them talk"}}
  ],
  "accusation_standard": "what proof the party needs before the final reveal",
  "resolution": ["5-7 valid resolution paths"]
}}"""
    data = _parse_json(await _ollama(prompt))
    return _normalize_plan(data, mission, case_type, roles, tones, locations, suspects)


def _build_leads(case_type: str, locations: List[Dict[str, str]], suspects: List[Dict[str, str]], strength: Dict[str, Any]) -> List[Dict[str, Any]]:
    leads = []
    chosen = random.sample(LEAD_PATHS, min(5, len(LEAD_PATHS)))
    dc_base = max(12, min(18, 10 + int(strength.get("avg_level", 5))))
    for idx, path in enumerate(chosen):
        loc = locations[idx % len(locations)]
        suspect = suspects[idx % len(suspects)]
        skills = path["skills"][:]
        random.shuffle(skills)
        primary_skills = skills[:3]
        leads.append({
            "label": path["label"],
            "location": loc,
            "person": suspect,
            "focus": path["focus"],
            "skills": primary_skills,
            "dc": dc_base + (idx % 3),
            "fail_forward": f"Even on failure, they learn one usable fact about {suspect['name']} or {loc['name']}, but {random.choice(FAILURE_COSTS)}.",
            "success": f"They confirm a contradiction tied to {path['focus']} and unlock another approach to {suspect['case_role']}.",
            "high_success": f"They get the clue cleanly, avoid the cost, and spot why the obvious reading is incomplete.",
            "wrong_read": random.choice([
                "The clue points at the right person for the wrong reason.",
                "The clue is true, but the timeline interpretation is backward.",
                "The suspect is lying, but not about the central crime.",
                "The supernatural explanation is attractive and premature.",
                "The mundane explanation is attractive and incomplete.",
            ]),
            "unlocks": random.sample([p["label"] for p in LEAD_PATHS if p["label"] != path["label"]], 2),
        })
    return leads


def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _card(title: str, body: str, color: str) -> str:
    return (
        f'<div style="border:1px solid {color};border-left:4px solid {color};'
        f'border-radius:6px;padding:14px 18px;margin:14px 0;background:#fff;">'
        f'<h2 style="margin:0 0 8px;color:{color};">{_e(title)}</h2>{body}</div>'
    )


def _table(rows: List[tuple]) -> str:
    body = "".join(
        f'<tr><td style="padding:6px 8px;font-weight:bold;vertical-align:top;width:28%;">{_e(a)}</td>'
        f'<td style="padding:6px 8px;vertical-align:top;">{_e(b)}</td></tr>'
        for a, b in rows
    )
    return f'<table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody>{body}</tbody></table>'


def _list(items: List[Any], ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{_e(i)}</li>" for i in items) + f"</{tag}>"


def _lead_card(lead: Dict[str, Any], idx: int, color: str) -> str:
    skills = ", ".join(f"{s} DC {lead['dc']}" for s in lead["skills"])
    loc = lead["location"]
    person = lead["person"]
    body = _table([
        ("Where", f"{loc['name']} ({loc['district']}) - {loc['description']}"),
        ("Who", f"{person['name']} - {person['case_role']} - {person['note']}"),
        ("Skill routes", skills),
        ("Fail-forward", lead["fail_forward"]),
        ("Success", lead["success"]),
        ("High success", lead["high_success"]),
        ("Wrong read", lead["wrong_read"]),
        ("Unlocks", ", ".join(lead["unlocks"])),
    ])
    body += f'<p><input type="checkbox"> Lead checked &nbsp; <input type="checkbox"> Clue confirmed &nbsp; <input type="checkbox"> Cost triggered</p>'
    return _card(f"Lead {idx} - {lead['label']}", body, color)


def _suspect_board(suspects: List[Dict[str, str]]) -> str:
    rows = ""
    for s in suspects:
        rows += (
            "<tr>"
            f"<td style='padding:6px 8px;font-weight:bold;'>{_e(s['name'])}</td>"
            f"<td style='padding:6px 8px;'>{_e(s['faction'])}</td>"
            f"<td style='padding:6px 8px;'>{_e(s['case_role'])}</td>"
            f"<td style='padding:6px 8px;'><input type='checkbox'> motive "
            f"<input type='checkbox'> alibi <input type='checkbox'> contradiction</td>"
            "</tr>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
        "<thead><tr style='background:#eee;'><th style='text-align:left;padding:6px 8px;'>Name</th>"
        "<th style='text-align:left;padding:6px 8px;'>Faction</th>"
        "<th style='text-align:left;padding:6px 8px;'>Role</th>"
        "<th style='text-align:left;padding:6px 8px;'>Board</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _evidence_board() -> str:
    sections = [
        "Confirmed clues",
        "Suspects",
        "Motives",
        "Alibis",
        "Contradictions",
        "Open questions",
        "Weird maybe-unrelated notes",
        "Red herrings",
        "Witness reliability",
        "Evidence quality",
        "Faction pressure",
        "Timeline",
        "Locations visited",
        "People still to interview",
        "Final theory",
        "Accusation target",
        "Confidence level",
        "Consequences if wrong",
    ]
    html = "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;'>"
    for sec in sections:
        html += (
            "<div style='border:1px solid #ddd;border-radius:6px;padding:8px;background:#fafafa;'>"
            f"<strong>{_e(sec)}</strong><br>"
            "<textarea rows='3' style='width:100%;font-family:inherit;margin-top:6px;'></textarea>"
            "</div>"
        )
    html += "</div>"
    return html


def _clue_web(items: List[Any]) -> str:
    rows = []
    for item in items:
        if isinstance(item, dict):
            skill = item.get("skill", "Investigation")
            check = ""
            if item.get("skill") or item.get("dc"):
                check = f"Check: {skill} DC {item.get('dc', '')} | "
            proves  = item.get("proves", "")
            setup   = item.get("setup") or f"Work the {skill} angle on this lead and read what it gives up."
            success = item.get("success") or proves or "the clue is confirmed and the next lead opens up."
            failure = item.get("failure") or "a misread sends the party to the wrong interpretation -- the clue still surfaces, but late or skewed."
            rows.append((
                item.get("clue", ""),
                f"{check}Source: {item.get('source', '')} | Unlocks: {item.get('unlocks', '')} | "
                f"Setup: {setup} | On Success: {success} | On Failure: {failure}",
            ))
        else:
            rows.append(("Clue", str(item)))
    return _table(rows)


def _security_detail(
    mission: dict,
    roles: Dict[str, str],
    locations: List[Dict[str, str]],
    suspects: List[Dict[str, str]],
    strength: Dict[str, Any],
) -> Dict[str, Any]:
    """Investigation-only security/recon layer for future stealth jobs."""
    avg = int(strength.get("avg_level", 5))
    dc_base = max(13, min(20, 11 + avg))
    primary_location = locations[0] if locations else {"name": "the case site", "district": "unknown"}
    primary_suspect = suspects[0] if suspects else {"name": roles.get("pressure", "the pressure faction")}
    host = roles.get("pressure") or mission.get("opposing_faction") or roles.get("sponsor", "")
    district = primary_location.get("district", "")
    failed_recon = None
    try:
        rows = _db_rows(
            "SELECT * FROM recon_dossiers WHERE outcome = 'failure' "
            "AND (host_faction = %s OR district = %s) "
            "ORDER BY created_at DESC LIMIT 1",
            (host, district),
        )
        failed_recon = rows[0] if rows else None
    except Exception:
        failed_recon = None

    heightened = bool(failed_recon)
    heat_note = (
        "Heightened security: a previous infiltration failed here or against this faction. "
        "Guards are looking for social covers, forged papers, and repeated casing behavior."
        if heightened else
        "Normal security posture: suspicious but not yet in lockdown. Careful investigation can still become clean recon."
    )
    target_name = primary_suspect.get("name") or host or "the mark"
    site_name = primary_location.get("name") or "the site"
    return {
        "site": site_name,
        "district": district,
        "host_faction": host,
        "heightened": heightened,
        "heat_note": heat_note,
        "failed_recon_id": failed_recon.get("id") if failed_recon else None,
        "layers": [
            f"Public layer: clerks, neighbors, mourners, or staff at {site_name} notice repeated questions.",
            f"Private layer: {host or 'the pressure faction'} controls keys, guest lists, back rooms, or witness access.",
            f"Evidence layer: a record, route, or routine around {target_name} can be converted into follow-up recon.",
            "Response layer: if the party is identified, future infiltration, heist, or assassination starts one heat step higher.",
        ],
        "checks": [
            {"route": "Infiltration setup", "check": "Insight or Deception", "dc": dc_base, "finds": "which cover identity would survive first contact"},
            {"route": "Heist setup", "check": "Investigation or Perception", "dc": dc_base + 1, "finds": "where the valuable record, object, or leverage is actually kept"},
            {"route": "Assassination setup", "check": "Insight or Survival", "dc": dc_base + 1, "finds": "the mark's routine, escort habit, or safest surveillance angle"},
        ],
        "followups": [
            "A clean investigation can seed an infiltration with a believable cover.",
            "Recovered floor/routine evidence can seed a heist with a known security layer.",
            "A proven suspect routine can seed an assassination with surveillance already done.",
        ],
    }


def _security_detail_html(detail: Dict[str, Any]) -> str:
    check_rows = "".join(
        f'<tr><td style="padding:6px 8px;font-weight:bold;">{_e(c.get("route"))}</td>'
        f'<td style="padding:6px 8px;">{_e(c.get("check"))} DC {int(c.get("dc", 14))}</td>'
        f'<td style="padding:6px 8px;">{_e(c.get("finds"))}</td></tr>'
        for c in detail.get("checks", [])
    )
    failed = (
        f'<p style="font-size:12px;color:#7b1e1e;"><strong>Failed recon link:</strong> dossier #{int(detail.get("failed_recon_id"))}</p>'
        if detail.get("failed_recon_id") else ""
    )
    return (
        f'<p><strong>Site:</strong> {_e(detail.get("site"))} ({_e(detail.get("district"))})<br>'
        f'<strong>Security holder:</strong> {_e(detail.get("host_faction"))}<br>'
        f'<strong>Posture:</strong> {_e(detail.get("heat_note"))}</p>'
        f'{failed}'
        f'<h4 style="margin:10px 0 4px;">Layers To Investigate</h4>'
        f'{_list(detail.get("layers", []))}'
        f'<h4 style="margin:10px 0 4px;">Recon Checks For Follow-up Jobs</h4>'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        f'<thead><tr style="background:#eee;"><th style="padding:6px 8px;text-align:left;">Follow-up</th>'
        f'<th style="padding:6px 8px;text-align:left;">Check</th>'
        f'<th style="padding:6px 8px;text-align:left;">Intel Found</th></tr></thead>'
        f'<tbody>{check_rows}</tbody></table>'
        f'<h4 style="margin:10px 0 4px;">Butterfly Effects</h4>'
        f'{_list(detail.get("followups", []))}'
    )


def _render_suspect_timeline(name: str, entries: List[Dict[str, Any]]) -> str:
    """Render one suspect's day-of timeline as a DM reference table."""
    if not entries:
        return "<p><em>No timeline generated.</em></p>"

    _TRUTH_COLORS = {
        "TRUTH":      ("#2a6a2a", "✓"),
        "HALF-TRUTH": ("#8a5a1f", "~"),
        "LIE":        ("#7b1e1e", "✗"),
    }

    rows = ""
    for entry in entries:
        dm_truth_raw = entry.get("dm_truth", "TRUTH: unverified")
        truth_tag    = "TRUTH"
        for tag in ("HALF-TRUTH", "LIE", "TRUTH"):
            if dm_truth_raw.upper().startswith(tag):
                truth_tag = tag
                break
        color, symbol = _TRUTH_COLORS.get(truth_tag, ("#555", "?"))
        dm_note = dm_truth_raw.split(":", 1)[1].strip() if ":" in dm_truth_raw else dm_truth_raw

        verifiable = entry.get("verifiable", False)
        ver_badge  = '<span style="font-size:10px;background:#3a6898;color:#fff;border-radius:3px;padding:1px 5px;margin-left:6px;">verifiable</span>' if verifiable else ""

        rows += (
            f'<tr style="border-bottom:1px solid #e8dcc8;">'
            f'<td style="padding:6px 8px;font-weight:600;white-space:nowrap;font-size:12px;">{_e(entry.get("time",""))}</td>'
            f'<td style="padding:6px 8px;font-size:13px;">{_e(entry.get("claim",""))}{ver_badge}</td>'
            f'<td style="padding:6px 8px;font-style:italic;font-size:13px;color:#333;">"{_e(entry.get("voice",""))}"</td>'
            f'<td style="padding:6px 8px;font-size:11px;color:{color};white-space:nowrap;font-weight:bold;">'
            f'{symbol} {truth_tag}</td>'
            f'<td style="padding:6px 8px;font-size:11px;color:{color};">{_e(dm_note)}</td>'
            f'</tr>'
        )

    return (
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        f'<thead><tr style="background:#2a2218;color:#e8dcc8;">'
        f'<th style="padding:6px 8px;text-align:left;white-space:nowrap;">Time</th>'
        f'<th style="padding:6px 8px;text-align:left;">What they claim</th>'
        f'<th style="padding:6px 8px;text-align:left;">Their words</th>'
        f'<th style="padding:6px 8px;text-align:left;">DM truth</th>'
        f'<th style="padding:6px 8px;text-align:left;">DM note</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
    )


def render_investigation_module(
    mission: dict,
    case_type: str,
    roles: Dict[str, str],
    tones: Dict[str, str],
    plan: Dict[str, Any],
    locations: List[Dict[str, str]],
    suspects: List[Dict[str, str]],
    leads: List[Dict[str, Any]],
    strength: Dict[str, Any],
    security_detail: Optional[Dict[str, Any]] = None,
    suspect_timelines: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> str:
    title = mission.get("title") or plan.get("case_title") or "Investigation"
    fc = _faction_color(roles["sponsor"])
    body = ""
    context = _mission_context(mission)
    if len(context.get("canon_terms", [])) < 3:
        body += _card("DM WARNING — Thin Mission Body", "<p style='color:#ffcc00;'><strong>This mission body contained fewer than 3 named entities or canon terms. Clue anchors, suspect names, and scene details may be generic. Enrich before running cold.</strong></p>", "#7b1e1e")
    body += _card("Briefing", f'<div style="white-space:pre-line;font-style:italic;">{_e(plan["briefing"])}</div>', fc)
    body += _card("Case Frame", _table([
        ("Type", case_type),
        ("Sponsor", roles["sponsor"]),
        ("Pressure faction", roles["pressure"]),
        ("Tone", f"{tones['primary']} + {tones['secondary']} + {tones['wildcard']}"),
        ("Public story", plan.get("public_story", "")),
        ("Truth", plan.get("truth", "")),
        ("Culprit / cause", plan.get("culprit_or_cause", "")),
        ("Motive", plan.get("motive", "")),
        ("Twist", plan.get("twist", "")),
    ]), "#8a5a1f")
    body += _card("Live Party Scaling", f"<p>{_e(_party_scaling_note(strength))}</p>", "#3a6898")
    if security_detail:
        body += _card("Security Detail - Follow-up Recon", _security_detail_html(security_detail), "#7b1e1e")
    body += _card("Multi-Day Timeline", _list(plan.get("timeline", []), ordered=True), "#555")
    body += _card("Core Clue Web", _clue_web(plan.get("clue_web", [])), "#2a6a2a")
    body += _card("Scene Secrets", _list(plan.get("scene_secrets", []), ordered=False), "#8a5a1f")
    if plan.get("witness_list"):
        witness_rows = []
        for w in plan["witness_list"]:
            witness_rows.append((
                w.get("name", "?"),
                f"Public: {w.get('what_they_say_publicly', '')} | Knows: {w.get('what_they_know', '')} | DC {w.get('dc_to_get_truth', 14)} to truth | Break: {w.get('how_to_break', '')}",
            ))
        body += _card("Witness List", _table(witness_rows), "#8a5a1f")
    body += _card("Long-Rest Revelation", f"<p>{_e(plan.get('long_rest_revelation', 'None expected.'))}</p><p><strong>Use rarely:</strong> only when the table needs a late-night connection, omen, remembered detail, or witness message.</p>", "#3a6898")
    body += _card("No Tactical Map", "<p>No map generated. Run this through area and room descriptions: who is present, what feels off, what changes after the party leaves, what gets missed if they rush, and sensory details that can become evidence.</p>", "#7b1e1e")
    body += _card("Suspect Board", _suspect_board(suspects), "#555")
    if suspect_timelines:
        for s in suspects:
            s_name = s.get("name", "")
            timeline = suspect_timelines.get(s_name)
            if timeline:
                case_role = s.get("case_role", s.get("role", "witness"))
                is_culprit = "culprit" in case_role.lower() or "cause" in case_role.lower()
                tl_color = "#7b1e1e" if is_culprit else "#3a6898"
                body += _card(
                    f"Witness Timeline — {s_name} ({case_role})",
                    _render_suspect_timeline(s_name, timeline),
                    tl_color,
                )
    for i, lead in enumerate(leads, 1):
        body += _lead_card(lead, i, fc if i % 2 else "#8a5a1f")
    body += _card("Evidence Board", _evidence_board(), "#555")
    body += _card("Accusation Standard", f"<p>{_e(plan.get('accusation_standard', 'Name the culprit/cause and cite three independent clues before the reveal.'))}</p>", "#7b1e1e")
    body += _card("Resolution Paths", _list(plan.get("resolution", RESOLUTIONS), ordered=False), "#2a6a2a")
    body += _card("TNN / Public Pressure", _table([
        ("Quiet", "No coverage yet; witnesses are easier to talk to."),
        ("Rumor", "People repeat a simple version that may be wrong."),
        ("TNN interest", "A reporter asks pointed questions and may accidentally capture a clue."),
        ("Bad headline", "Faction pressure rises; a formal complaint or watcher may appear."),
        ("Public reveal", "The final accusation becomes part of the city story, for good or ill."),
    ]), "#3a6898")
    from src.treasure import loot_card as _loot_card
    body += _loot_card(mission)
    return _page(title, body, roles["sponsor"])


def render_investigation_session(
    mission: dict,
    case_type: str,
    roles: Dict[str, str],
    plan: Dict[str, Any],
    suspects: List[Dict[str, str]],
    leads: List[Dict[str, Any]],
    strength: Dict[str, Any],
    security_detail: Optional[Dict[str, Any]] = None,
    suspect_timelines: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> str:
    title = mission.get("title") or plan.get("case_title") or "Investigation"
    fc = _faction_color(roles["sponsor"])
    lead_checks = "".join(
        f"<li><input type='checkbox'> {_e(lead['label'])} - {_e(', '.join(lead['skills']))}</li>"
        for lead in leads
    )
    suspect_checks = "".join(
        f"<li><input type='checkbox'> {_e(s['name'])} - {_e(s['case_role'])}</li>"
        for s in suspects
    )
    body = f'<h1 style="color:{fc};">{_e(title)}</h1>'
    body += _card("Case", _table([
        ("Type", case_type),
        ("Sponsor", roles["sponsor"]),
        ("Pressure", roles["pressure"]),
        ("Public story", plan.get("public_story", "")),
        ("Accusation standard", plan.get("accusation_standard", "")),
        ("Long-rest revelation", plan.get("long_rest_revelation", "None expected.")),
        ("Party", _party_scaling_note(strength)),
    ]), fc)
    body += _card("Core Clue Web", _clue_web(plan.get("clue_web", [])), "#2a6a2a")
    if security_detail:
        body += _card("Security Detail", _security_detail_html(security_detail), "#7b1e1e")
    body += _card("Leads", f"<ul>{lead_checks}</ul>", "#8a5a1f")
    body += _card("Suspects", f"<ul>{suspect_checks}</ul>", "#555")
    if suspect_timelines:
        for s in suspects:
            s_name = s.get("name", "")
            timeline = suspect_timelines.get(s_name)
            if timeline:
                case_role = s.get("case_role", s.get("role", "witness"))
                is_culprit = "culprit" in case_role.lower() or "cause" in case_role.lower()
                body += _card(
                    f"Witness Timeline — {s_name}",
                    _render_suspect_timeline(s_name, timeline),
                    "#7b1e1e" if is_culprit else "#3a6898",
                )
    body += _card("Evidence Board", _evidence_board(), "#555")
    body += _card("Resolution", '<p><strong>Final theory:</strong></p><textarea rows="3" style="width:100%;font-family:inherit;"></textarea><p><strong>Accusation / reveal:</strong> <select><option>Private sponsor report</option><option>Public accusation</option><option>TNN leak</option><option>Tower Authority handoff</option><option>Quiet bargain</option><option>Protective cover-up</option></select></p>', "#2a6a2a")
    return _page(title, body, roles["sponsor"])


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


async def build_investigation_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Investigation")
    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    strength = _party_strength()
    roles = _resolve_roles(mission)
    case_type = _pick_case_type(mission)
    tones = _pick_tones()
    seeds = _case_seed(case_type, roles)
    locations = _pick_locations(case_type)
    suspects = _pick_suspects(roles)

    plan_task = asyncio.create_task(_generate_plan(mission, case_type, roles, tones, seeds, locations, suspects, strength))
    leads = _build_leads(case_type, locations, suspects, strength)
    plan = await plan_task
    security_detail = _security_detail(mission, roles, locations, suspects, strength)

    # Determine incident time from plan or fall back to a canonical bell
    _incident_time = plan.get("incident_time") or "third bell"
    for _tl_entry in plan.get("timeline", []):
        if isinstance(_tl_entry, str) and any(b in _tl_entry.lower() for b in ("bell", "morning", "midday", "evening", "night")):
            _words = _tl_entry.split()
            _incident_time = " ".join(_words[:4]) if len(_words) >= 2 else _incident_time
            break

    # Generate per-suspect timelines (one LLM call per suspect)
    suspect_timelines: Dict[str, List[Dict[str, Any]]] = {}
    try:
        suspect_timelines = await _generate_suspect_timelines(suspects, plan, mission, _incident_time)
        logger.info(f"[INVESTIGATION] Witness timelines generated for {len(suspect_timelines)} suspects")
    except Exception as _te:
        logger.warning(f"[INVESTIGATION] Timeline generation failed: {_te}")

    logger.info(f"[INVESTIGATION] Building {title!r} | case={case_type} | sponsor={roles['sponsor']}")

    from src.mission_builder.mimir_module import create_module as _mc, render_mimir_section as _ms, push_documents as _mpd, enrich_mission_loot as _mel
    _mimir_id = await _mc(mission, mission_type="investigation")
    module_html = render_investigation_module(mission, case_type, roles, tones, plan, locations, suspects, leads, strength,
                                              security_detail=security_detail,
                                              suspect_timelines=suspect_timelines)
    _loot_rewards = await _mel(_mimir_id or "", mission)
    module_html += _ms([], _loot_rewards, _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")
    session_html = render_investigation_session(mission, case_type, roles, plan, suspects, leads, strength,
                                               security_detail=security_detail,
                                               suspect_timelines=suspect_timelines)
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component
    dm_md = (
        f"## Investigation DM Guide\n"
        f"### Truth Layer\n"
        f"- Public story: {plan.get('public_story', '')}\n"
        f"- Truth: {plan.get('truth', '')}\n"
        f"- Culprit/cause: {plan.get('culprit_or_cause', '')}\n"
        f"- Motive: {plan.get('motive', '')}\n"
        f"- Twist: {plan.get('twist', '')}\n"
        f"- Long-rest revelation: {plan.get('long_rest_revelation', '')}\n\n"
        f"### Accusation Standard\n"
        f"{plan.get('accusation_standard', '')}\n\n"
        f"### Security Detail / Follow-up Recon\n"
        f"- Site: {security_detail.get('site')} ({security_detail.get('district')})\n"
        f"- Security holder: {security_detail.get('host_faction')}\n"
        f"- Posture: {security_detail.get('heat_note')}\n"
        + "\n".join(
            f"- {c.get('route')}: {c.get('check')} DC {c.get('dc')} -> {c.get('finds')}"
            for c in security_detail.get("checks", [])
        )
        + "\n\n"
        f"### Core Clue Web\n"
        + "\n".join(
            f"- {c.get('clue', c) if isinstance(c, dict) else c}: "
            f"{c.get('source', '') if isinstance(c, dict) else ''} "
            f"{c.get('proves', '') if isinstance(c, dict) else ''}"
            for c in plan.get("clue_web", [])
        )
        + "\n\n### Scene Secrets\n"
        + "\n".join(f"- {s}" for s in plan.get("scene_secrets", []))
        + "\n\n"
        f"### Timeline\n"
        + "\n".join(f"- {s}" for s in plan.get("timeline", []))
        + "\n\n### Suspects\n"
        + "\n".join(f"- {s.get('name')}: {s.get('case_role')} / secret: {s.get('note', '')}" for s in suspects)
        + "\n\n### Leads\n"
        + "\n".join(f"- {lead.get('label')}: {lead.get('focus', '')} ({', '.join(lead.get('skills', []))})" for lead in leads)
    )
    players_md = (
        f"## Player Case Guide\n"
        f"### Public Case\n"
        f"- Sponsor: {roles['sponsor']}\n"
        f"- Case type: {case_type}\n"
        f"- Public story: {plan.get('public_story', '')}\n\n"
        f"### What Counts As Proof\n"
        f"{plan.get('accusation_standard', '')}\n\n"
        f"### Known Leads\n"
        + "\n".join(f"- {lead.get('label')}: {lead.get('focus', lead.get('label', 'Investigate this lead.'))}" for lead in leads)
        + "\n\n### Security Awareness\n"
        + f"{security_detail.get('heat_note')}\n"
        + "\n\nUse skills, interviews, area descriptions, and evidence board notes. No tactical map is expected."
    )
    chart_md = (
        f"## Investigation Chart Pack\n"
        f"### Case Tones\n- {tones['primary']}\n- {tones['secondary']}\n- {tones['wildcard']}\n\n"
        f"### Core Clue Web\n"
        + "\n".join(
            f"- {c.get('clue', c) if isinstance(c, dict) else c}: "
            f"{c.get('source', '') if isinstance(c, dict) else ''} "
            f"{c.get('proves', '') if isinstance(c, dict) else ''}"
            for c in plan.get("clue_web", [])
        )
        + "\n\n### Scene Secrets\n"
        + "\n".join(f"- {s}" for s in plan.get("scene_secrets", []))
        + "\n\n"
        f"### Failure Costs\n"
        + "\n".join(f"- {s}" for s in FAILURE_COSTS)
        + "\n\n### Security Detail Checks\n"
        + "\n".join(
            f"- {c.get('route')}: {c.get('check')} DC {c.get('dc')} -> {c.get('finds')}"
            for c in security_detail.get("checks", [])
        )
        + "\n\n### Resolution Options\n"
        + "\n".join(f"- {s}" for s in plan.get("resolution", RESOLUTIONS))
        + "\n\n### TNN / Public Pressure\n"
        f"- Quiet\n- Rumor\n- TNN interest\n- Bad headline\n- Public reveal\n"
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, roles["sponsor"], dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, roles["sponsor"], players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, roles["sponsor"], chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",      "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",           "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Evidence & Resolution","type": "custom",    "content": chart_md},
        ])
    # NPC knowledge cards for all named suspects + witnesses
    try:
        from src.mission_builder.npc_knowledge_cards import build_npc_cards_html
        from src.mission_builder.html_renderer import render_component as _rc
        suspect_names = [s.get("name","") for s in plan.get("suspects", suspects) if s.get("name")]
        extra_names   = [roles.get("sponsor",""), mission.get("npc_giver","")]
        cards_html = build_npc_cards_html([], mission, extra_names=suspect_names + extra_names)
        if cards_html:
            _npc_page = _rc("NPC Reference", title, "", roles["sponsor"]).replace("</body>", cards_html + "</body>")
            (out_dir / "npcs.html").write_text(_npc_page, encoding="utf-8")
    except Exception as _npc_e:
        logger.warning(f"[INVESTIGATION] NPC cards failed: {_npc_e}")

    # Pull a crime-scene or meeting-place map from the library
    _inv_maps: list = []
    try:
        from src.battle_map_library import copy_library_map_for_mission
        from src.mission_builder.html_renderer import render_maps_page
        _district = (locations[0].get("district", "") if locations else "")
        _lib = copy_library_map_for_mission(mission, out_dir / "maps" / "scene.png",
                                            mission_type="investigation", map_type="interior", district=_district)
        if _lib:
            _inv_maps = [_lib]
            (out_dir / "maps.html").write_text(
                render_maps_page(title, roles["sponsor"], _inv_maps, "{}"), encoding="utf-8"
            )
    except Exception as _me:
        logger.warning(f"[INVESTIGATION] Library map failed: {_me}")

    box_components = component_links(has_maps=bool(_inv_maps))
    if _inv_maps:
        box_components.append(("maps", "maps.html"))

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
            map_count=len(_inv_maps),
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as e:
        logger.warning(f"[INVESTIGATION] index.html failed: {e}")
        index_path = out_dir / "module.html"

    try:
        from src.mission_builder.mission_db import write_module_slug_for_mission
        write_module_slug_for_mission(mission, out_dir.name, log_prefix="INVESTIGATION")
    except Exception as e:
        logger.warning(f"[INVESTIGATION] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    return index_path
