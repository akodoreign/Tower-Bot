"""
puzzle_pipeline.py - Standalone hard puzzle mission modules.

Puzzle missions are about solving a difficult, long-standing problem. They are
not investigation mysteries and not generic puzzle rooms inside another job.
The mission exists because the puzzle itself is the work: a sealed shrine,
ancient ruin, arcane mechanism, graffiti-art sequence, cipher, logic lock, or
other hard-to-crack system.

No map generation by default. Maps slow this mission type down unless a
physical/spatial mechanism truly needs one.

Exported:
    build_puzzle_module(mission: dict, out_dir: Path) -> Path
    is_puzzle_mission(mission_type: str) -> bool
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

_PUZZLE_KEYWORDS = {
    "puzzle", "cipher", "decode", "riddle", "logic", "mechanism",
    "arcane lock", "sealed shrine", "sealed door", "sealed vault",
    "graffiti puzzle", "mural puzzle", "pattern", "sequence",
    "trial", "worthiness", "restore the mechanism", "solve",
}


def is_puzzle_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _PUZZLE_KEYWORDS)


PRIMARY_SPONSORS = [
    "Wizards Tower",
    "Guild of Ashen Scrolls",
    "Adventurers Guild",
    "Glass Sigil",
    "Serpent Choir",
    "Brother Thane's Cult",
]

PUZZLE_TYPES = {
    "symbol_pattern": "symbols / pattern matching",
    "lore_history": "lore / history reconstruction",
    "physical_mechanism": "physical mechanism",
    "art_puzzle": "art, graffiti, mural, song, performance, sculpture, or stained glass",
    "logic_sequence": "logic, order, category, contradiction, or rule deduction",
    "moral_choice": "moral / choice puzzle",
    "language_cipher": "language, cipher, acrostic, or dead script",
    "arcane_system": "arcane lock, ward, circuit, ritual, or broken magical system",
    "divine_trial": "shrine, god, omen, faith, or worthiness trial",
    "rift_memory": "rift, memory, soul, resurrection, or impossible time puzzle",
}

OBJECTIVES = [
    "open something sealed",
    "decode a message / mural / graffiti trail / cipher",
    "restore a broken system or magical circuit",
    "choose the correct sequence, offering, door, or arrangement",
    "prove worthiness to a shrine, god, faction, or old maker",
    "disable a ward, curse, trap system, or lockdown",
    "reassemble a scattered art piece or city-spanning sign",
    "recover a buried truth without turning it into a mystery investigation",
    "translate rules from a dead context into the present city",
]

GENERIC_PLAN_MARKERS = [
    "source culture",
    "not the most obvious visible order",
    "repeated mark is a separator",
    "missing symbol marks the start",
    "stubborn pattern of marks",
    "arcane lock, ward, circuit, ritual, or broken magical system built around",
]

SOLVE_METHODS = [
    "player thinking",
    "skill checks",
    "hybrid logic + checks",
    "multi-path solution",
    "brute force / tools / magic if appropriate",
    "research-first solution",
    "calendar / staged reveal solution",
]

RESEARCH_SITES = [
    "library",
    "archive",
    "temple",
    "faction records room",
    "old map collection",
    "art collection",
    "witness memory",
    "public monument",
    "graffiti wall",
    "private scholar's notes",
    "sealed civic ledger",
]

PROGRESS_STAGES = [
    ("First Shape", "The party identifies what kind of puzzle it is and what is missing."),
    ("Rule Found", "The party confirms one real rule and one tempting false reading."),
    ("Research Breakthrough", "Research connects the puzzle to a person, place, god, faction, or historical event."),
    ("Working Theory", "The party can attempt a meaningful solution without guessing."),
    ("Final Unlock", "The puzzle opens, decodes, restores, disables, or reveals its buried truth."),
]

WRONG_OUTCOMES = [
    "harmless negative information",
    "wasted hours or days while the world moves",
    "puzzle shifts, resets, or locks one route",
    "trap, curse, damage, summon, or magical backlash",
    "public or scholarly embarrassment",
    "old truth, scandal, or buried history comes to light",
    "rival solver gains a step",
    "sponsor loses patience or sends another reviewer",
]

WORLD_MOVES = [
    "a rival group makes progress",
    "a faction applies pressure",
    "weather, access, or witnesses change",
    "new symbols become visible",
    "another faction changes the site",
    "TNN buries a small science item in a 5am segment",
    "the sponsor's scholars argue and slow the party down",
    "a key research room closes for a day",
    "the puzzle reveals a new layer after rest or time",
]

DEBRIEF_TYPES = [
    "scholar review",
    "public recognition",
    "private handoff",
    "embarrassed sponsor",
    "dangerous reveal",
    "faction prestige scene",
    "Tower peer scrutiny of the party's wizard",
]

LIGHT_SKIRMISHES = [
    "rival scholar crew shoves ahead in a records room",
    "Glass Sigil aides try to distract a Wizards Tower reviewer",
    "a competing faction grabs the wrong clue and runs",
    "a duel of nonlethal cantrips breaks out over priority",
    "rivals block access long enough to buy research time",
    "security removes everyone after a public argument",
]

REWARD_PROFILES = {
    "Wizards Tower": "high EC, strong recognition, low-to-moderate Kharma; much harder because Tower scholars already failed",
    "Glass Sigil": "high EC, quiet prestige, low Kharma; much harder because Sigil experts need deniable outside minds",
    "Guild of Ashen Scrolls": "moderate EC, strong scholarly recognition, archive access, faction standing",
    "Adventurers Guild": "standard EC, public recognition, future contract trust",
    "Serpent Choir": "mixed EC/Kharma, omen access, spiritual consequence",
    "Brother Thane's Cult": "modest EC, intense faith recognition, uncomfortable reverence",
}


def _db_rows(query: str, params: tuple = ()) -> List[Dict]:
    try:
        from src.db_api import raw_query
        return raw_query(query, params) or []
    except Exception as e:
        logger.warning(f"[PUZZLE] DB read failed: {e}")
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
    snap_rows = _db_rows("SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC")
    profile_rows = _db_rows("SELECT name, class_name, species, player_name, profile_json FROM player_characters")
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
                    label = str(sk).replace("_", " ").title()
                    top_skills.append((label, int(mod)))
                    skill_counts[label] = skill_counts.get(label, 0) + 1
        pcs.append({
            "name": name,
            "level": level,
            "class": profile.get("class_name") or snap.get("class") or "",
            "top_skills": sorted(top_skills, key=lambda x: x[1], reverse=True)[:5],
        })
    levels = [p["level"] for p in pcs] or [5]
    return {
        "party_size": len(pcs) or 4,
        "avg_level": round(sum(levels) / len(levels), 1),
        "max_level": max(levels),
        "pcs": pcs,
        "puzzle_level": max(levels) + 4,
        "party_top_skills": sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:8],
    }


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    skills = ", ".join(f"{name} x{count}" for name, count in strength.get("party_top_skills", [])[:5])
    skill_note = f" Visible party strengths: {skills}." if skills else ""
    return f"Live party read: {strength['party_size']} PCs, avg level {strength['avg_level']}, max level {strength['max_level']}; puzzle pressure can scale to party +4 ({strength['puzzle_level']}).{skill_note}"


def _factions() -> List[Dict]:
    rows = _db_rows("SELECT faction_name, reputation_score, tier, description FROM faction_reputation ORDER BY faction_name")
    return rows or [{"faction_name": "Wizards Tower"}, {"faction_name": "Guild of Ashen Scrolls"}, {"faction_name": "Adventurers Guild"}]


def _canon(name: str, factions: List[Dict]) -> str:
    raw = (name or "").strip()
    low = raw.lower()
    for row in factions:
        fname = row.get("faction_name") or ""
        if low and (low == fname.lower() or low in fname.lower() or fname.lower() in low):
            return fname
    return raw


def _resolve_sponsor(mission: dict) -> str:
    factions = _factions()
    sponsor = _canon(mission.get("faction") or "", factions)
    if sponsor:
        return sponsor
    weighted = []
    available = [f.get("faction_name") for f in factions if f.get("faction_name")]
    for name in available:
        weighted.extend([name] * (4 if name in PRIMARY_SPONSORS else 1))
    return random.choice(weighted or PRIMARY_SPONSORS)


def _pick_puzzle_type(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    if any(k in text for k in ("graffiti", "mural", "song", "art", "stained")):
        return "art_puzzle"
    if any(k in text for k in ("god", "shrine", "divine", "omen", "faith")):
        return "divine_trial"
    if any(k in text for k in ("cipher", "language", "decode", "script")):
        return "language_cipher"
    if any(k in text for k in ("mechanism", "lever", "statue", "tile")):
        return "physical_mechanism"
    if any(k in text for k in ("rift", "memory", "soul", "resurrection")):
        return "rift_memory"
    if any(k in text for k in ("arcane", "ward", "lock", "ritual")):
        return "arcane_system"
    if any(k in text for k in ("logic", "sequence", "order")):
        return "logic_sequence"
    return random.choice(list(PUZZLE_TYPES.keys()))


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
    contact = mission.get("contact") or data.get("contact") or "the sponsor's contact"
    personal_for = mission.get("personal_for") or data.get("personal_for") or ""
    opposing = mission.get("opposing_faction") or data.get("opposing_faction") or ""
    reward = mission.get("reward") or data.get("reward") or ""
    title = mission.get("title") or data.get("title") or "the puzzle"

    phrases = []
    for match in re.findall(r"\*([^*\n]{3,80})\*", text):
        phrases.append(match.strip())
    for match in re.findall(r"\b[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){0,4}\b", text):
        clean = match.strip(" -*")
        if clean.lower() not in {"type", "tier", "expires", "reward", "opposes", "contact", "gm notes"}:
            phrases.append(clean)
    lower = text.lower()
    stakes = []
    for needle in ("dome", "rogue arcane engine", "stolen relic", "weaponized", "cover up", "trap", "former ally", "breach", "rift", "betrayal"):
        if needle in lower:
            stakes.append(needle)

    seen = set()
    canon_terms = []
    for phrase in [title, contact, personal_for, opposing, *phrases]:
        phrase = str(phrase or "").strip()
        if phrase and phrase.lower() not in seen:
            seen.add(phrase.lower())
            canon_terms.append(phrase)

    return {
        "title": title,
        "contact": contact,
        "personal_for": personal_for,
        "opposing_faction": opposing,
        "reward": reward,
        "text": text,
        "canon_terms": canon_terms[:12],
        "stakes": stakes[:8],
    }


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
    marker_hits = sum(1 for marker in GENERIC_PLAN_MARKERS if marker in haystack)
    return marker_hits >= 2 or _specificity_score(plan, context) < 3


def _canon_seed(puzzle_type: str, sponsor: str) -> Dict[str, List[str]]:
    seeds = {"places": [], "people": [], "history": [], "weird": [], "faith": []}
    seeds["places"].extend(_sample_text(
        _db_rows("SELECT name, district, place_type, description FROM gazetteer_places ORDER BY RAND() LIMIT 8"),
        ["name", "district", "place_type", "description"], 5,
    ))
    seeds["people"].extend(_sample_text(
        _db_rows("SELECT name, faction, role, location FROM npcs ORDER BY RAND() LIMIT 6"),
        ["name", "faction", "role", "location"], 4,
    ))
    seeds["history"].extend(_sample_text(
        _db_rows("SELECT facts FROM news_memory ORDER BY id DESC LIMIT 8"),
        ["facts"], 4,
    ))
    seeds["history"].extend(_sample_text(
        _db_rows("SELECT mission_title, result, key_decisions, loose_threads, notable_moments FROM mission_outcomes ORDER BY id DESC LIMIT 5"),
        ["mission_title", "result", "key_decisions", "loose_threads", "notable_moments"], 3,
    ))
    seeds["faith"].extend(_sample_text(
        _db_rows("SELECT name, domain, alignment, notes FROM gods ORDER BY RAND() LIMIT 5"),
        ["name", "domain", "alignment", "notes"], 3,
    ))
    seeds["weird"].extend(_sample_text(
        _db_rows("SELECT active, intensity, location, effects_json FROM rift_state LIMIT 2"),
        ["active", "intensity", "location", "effects_json"], 2,
    ))
    seeds["weird"].extend(_sample_text(
        _db_rows("SELECT npc_name, died_at, resurrect_at, status FROM resurrection_queue ORDER BY id DESC LIMIT 4"),
        ["npc_name", "died_at", "resurrect_at", "status"], 3,
    ))
    if not seeds["places"]:
        seeds["places"].append(f"{sponsor} has a sealed site that no one can solve.")
    return seeds


def _sample_text(rows: List[Dict], keys: List[str], limit: int) -> List[str]:
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


def _pick_research_routes(puzzle_type: str, seeds: Dict[str, List[str]], strength: Dict[str, Any]) -> List[Dict[str, str]]:
    skills = [name for name, _count in strength.get("party_top_skills", [])]
    default_skills = ["Investigation", "Arcana", "History", "Religion", "Insight", "Perception"]
    skill_pool = list(dict.fromkeys(skills + default_skills))
    routes = []
    site_pool = RESEARCH_SITES[:]
    random.shuffle(site_pool)
    for idx, site in enumerate(site_pool[:5]):
        skill = skill_pool[idx % len(skill_pool)]
        routes.append({
            "site": site,
            "skill": skill,
            "time": random.choice(["2 hours", "half a day", "one day", "one long evening"]),
            "clue": random.choice([
                "confirms one real rule",
                "reveals the source culture",
                "connects a symbol to a faction or god",
                "finds an old failed attempt",
                "shows what a wrong answer costs",
                "reveals when the next stage appears",
            ]),
        })
    return routes


def _calendar_stages() -> List[str]:
    return [
        "Day 1: first inspection and research split.",
        random.choice([
            "Day 2: new symbol, graffiti layer, moon/weather angle, or archival contradiction appears.",
            "Day 2: rival scholars arrive and try to claim priority.",
            "Day 2: a research site opens after a favor, fee, or faction call.",
        ]),
        random.choice([
            "Day 3: working theory can be tested.",
            "Day 3: a wrong attempt reveals the buried truth behind the puzzle.",
            "Day 3: sponsor review pressures the party to show progress.",
        ]),
        "Final stage: solve, open, decode, restore, disable, or reveal the puzzle's truth.",
    ]


async def _ollama(prompt: str, system: str = "", tokens: int = 2200) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.78, "num_predict": tokens},
    }
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("puzzle_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[PUZZLE] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=220.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[PUZZLE] Ollama error: {e}")
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


async def _generate_plan(
    mission: dict,
    sponsor: str,
    puzzle_type: str,
    seeds: Dict[str, List[str]],
    research_routes: List[Dict[str, str]],
    strength: Dict[str, Any],
) -> Dict[str, Any]:
    objective = random.choice(OBJECTIVES)
    methods = random.sample(SOLVE_METHODS, 4)
    reward_profile = REWARD_PROFILES.get(sponsor, "recognition, faction standing, more EC than Kharma, and access to what the puzzle protects")
    context = _mission_context(mission)
    prompt = f"""Write a standalone D&D puzzle mission module plan.

Mission: {mission.get('title', 'Puzzle Mission')}
Mission notes: {(mission.get('body') or mission.get('description') or '')[:450]}
Sponsor: {sponsor}
Puzzle type: {puzzle_type} - {PUZZLE_TYPES[puzzle_type]}
Objective: {objective}
Solve methods: {methods}
Reward profile: {reward_profile}
Live party: {strength['party_size']} PCs, avg level {strength['avg_level']}, max {strength['max_level']}
DB canon seeds: {json.dumps(seeds, ensure_ascii=False)[:3200]}
Research routes: {json.dumps(research_routes, ensure_ascii=False)}
Mission-specific canon terms that MUST appear in the module: {json.dumps(context['canon_terms'], ensure_ascii=False)}
Mission-specific stakes that MUST be honored: {json.dumps(context['stakes'], ensure_ascii=False)}
Full mission text for context: {context['text'][:1800]}

Rules:
- This is a standalone hard puzzle mission, not an investigation mystery.
- Do not replace the mission with a generic puzzle shell. Keep the named PC/NPC, contact, relic/object, site, sponsor scandal, rival, and consequence from the mission text.
- Avoid gotcha riddles. No cheap wording traps.
- The answer must be supported by fair clues, research, symbols, site observation, lore, faction/god/history context, or clear pattern logic.
- The answer key must be concrete enough that a DM can run it without inventing the relic, clue sequence, culprit/rival, or final operation at the table.
- No map by default.
- Puzzle can take days; world keeps turning.
- Some stages may reveal themselves over days.
- Research in key locations reveals clues and costs time.
- DM section must include full answer key, exact solution, clue meanings, step-by-step solve path, alternate solutions, and unstick notes.
- Light skirmishes are possible only as nonlethal rival pressure; combat is not the core solution.

Return JSON only:
{{
  "briefing": "2-3 paragraphs from the sponsor/contact",
  "surface_description": "what the party sees at first, without solution",
  "puzzle_name": "short name",
  "mission_specific_stakes": "named PC/NPC/object/site/consequence summary",
  "objective": "specific objective",
  "core_puzzle": "what the puzzle is",
  "answer_key": "full answer for DM",
  "exact_solution_steps": ["specific input/action 1", "specific input/action 2", "specific final action"],
  "clue_ladder": [
    {{"clue": "concrete clue", "where": "where found", "means": "what it proves", "failure_cost": "what happens on failure"}}
  ],
  "clue_meanings": ["5-8 clue meanings"],
  "solve_path": ["phase 1", "phase 2", "phase 3", "final unlock"],
  "alternate_solutions": ["3-5 valid alternate approaches"],
  "unstick_notes": ["4-6 ways for DM to keep progress moving"],
  "wrong_attempts": ["4-6 wrong or partial attempt consequences"],
  "world_moves": ["4-6 ways the world moves while they research"],
  "debrief": "scholar review / recognition / handoff scene",
  "news_angle": "usually boring 5am science segment unless huge"
}}"""
    data = _parse_json(await _ollama(prompt))
    return _normalize_plan(data, mission, sponsor, puzzle_type, objective)


def _fallback_plan(mission: dict, sponsor: str, puzzle_type: str, objective: str) -> Dict[str, Any]:
    context = _mission_context(mission)
    title = context["title"]
    contact = context["contact"]
    personal = context["personal_for"] or "the party"
    terms = context["canon_terms"]
    stakes = context["stakes"]
    object_name = next((t for t in terms if "oath" in t.lower() or "relic" in t.lower()), title)
    engine = "rogue arcane engine" if "rogue arcane engine" in stakes else "unstable arcane engine"
    site = "The Warrens' Undercroft" if "Warrens" in " ".join(terms) else "the sponsor's sealed worksite"
    consequence = "a breach in the Dome" if "dome" in stakes or "breach" in stakes else "a public magical disaster"
    return {
        "briefing": f"{contact} hires {personal} and the crew because {sponsor} cannot solve the lock around {object_name} without exposing its own cover-up. The job is not to smash a door; it is to restore the failed control sequence before {engine} turns a stolen relic into {consequence}.\n\nThe sponsor wants the truth contained, the relic recovered, and any former ally involved in the trap identified quietly. Every hour spent guessing gives rival handlers more time to weaponize the system.",
        "surface_description": f"At {site}, {object_name} sits behind a fractured oath-circuit: Iron Fang tally marks, a warforged-compatible command socket, and a missing oath phrase burned out of the sequence. The ward hums in pulses that match an engine cycle rather than a door lock.",
        "puzzle_name": f"{title} Oath-Circuit",
        "mission_specific_stakes": f"{personal} is tied to {object_name}; {contact} wants {sponsor}'s breach buried; the wrong solve feeds {engine} toward {consequence}.",
        "objective": objective,
        "core_puzzle": f"A broken arcane oath-circuit around {object_name}; the visible Iron Fang order is bait, while the true sequence is betrayal -> custody -> restoration -> release.",
        "answer_key": f"The party must restore the missing oath phrase, route the engine pulse through the warforged-compatible socket, then speak or inscribe the original custody oath in reverse witness order. The final action is to ground {object_name} before the engine reaches its fourth pulse; doing it in the visible Iron Fang order arms the trap.",
        "exact_solution_steps": [
            f"Identify the burned-out oath phrase connected to {object_name}.",
            "Separate the visible Iron Fang tally order from the true witness order.",
            "Route or mimic the warforged-compatible socket so the circuit accepts a living/construct witness.",
            "Input the custody oath in reverse witness order: betrayal, custody, restoration, release.",
            f"Ground {object_name} before the fourth engine pulse to prevent {consequence}.",
        ],
        "clue_ladder": [
            {"clue": "Soot around the missing phrase curls inward, not outward.", "where": site, "means": "The phrase was removed by the circuit itself after a betrayal, not chiseled out later.", "failure_cost": "The next engine pulse advances while the party chases a vandal theory."},
            {"clue": "The warforged socket is polished by use and sized for a palm, not a key.", "where": "control plinth", "means": f"{personal} or another construct-linked witness can safely bridge the circuit.", "failure_cost": "A metal tool works briefly, then heats and marks the user."},
            {"clue": "An old failed attempt used the visible Iron Fang tally order and scorched the release rune.", "where": "records or old map collection", "means": "The visible order is a false reading.", "failure_cost": "A rival repeats the same wrong attempt and locks one research route for a day."},
            {"clue": "Veyra's briefing avoids naming who first broke the custody oath.", "where": "interview with the contact", "means": "The cover-up is part of the solution sequence.", "failure_cost": "The sponsor grows defensive and adds a watcher."},
        ],
        "clue_meanings": [
            "The missing oath phrase marks the start, not the end.",
            "Iron Fang tally order is bait left by the trap-maker.",
            "The warforged socket means witness identity matters.",
            "Engine pulses are a countdown and a metronome.",
            "The former ally's failed order proves what not to do.",
        ],
        "solve_path": [
            f"Inspect {site} and identify the oath-circuit as a custody ward around {object_name}.",
            "Research the failed Iron Fang attempt and prove the visible order is false.",
            "Interview the contact or rival witness to recover the missing oath phrase.",
            "Test the warforged/construct-compatible bridge with safeguards.",
            f"Input the reverse witness order and ground {object_name} before the fourth pulse.",
        ],
        "alternate_solutions": [
            "Research-first solve through records and failed attempt notes.",
            "Arcana plus tool proficiency to simulate the warforged socket safely.",
            "Social solve: pressure the contact into revealing the missing oath phrase.",
            "Divination or object reading to confirm the witness order, still requiring the physical grounding step.",
        ],
        "unstick_notes": [
            "Let a failed visible-order attempt prove the bait without destroying the relic.",
            "Have the engine pulse visibly advance when the party stalls.",
            "Let the contact accidentally say one word of the missing oath phrase.",
            "A rival makes a useful wrong attempt that reveals the false order.",
            "Any careful theory can be tested on a harmless side rune first.",
        ],
        "wrong_attempts": random.sample(WRONG_OUTCOMES, 5),
        "world_moves": random.sample(WORLD_MOVES, 5),
        "debrief": f"{sponsor} reviews whether the party recovered {object_name}, kept the breach quiet, and exposed the former ally trap without public scandal.",
        "news_angle": f"A quiet technical item unless {consequence} becomes visible or {sponsor}'s cover-up leaks.",
    }


def _normalize_plan(data: Optional[dict], mission: dict, sponsor: str, puzzle_type: str, objective: str) -> Dict[str, Any]:
    fallback = _fallback_plan(mission, sponsor, puzzle_type, objective)
    if not isinstance(data, dict):
        return fallback
    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    for key in (
        "exact_solution_steps",
        "clue_ladder",
        "clue_meanings",
        "solve_path",
        "alternate_solutions",
        "unstick_notes",
        "wrong_attempts",
        "world_moves",
    ):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    if _is_generic_plan(plan, _mission_context(mission)):
        logger.warning("[PUZZLE] Generated plan was too generic; using mission-specific fallback")
        return fallback
    return plan


def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _card(title: str, body: str, color: str) -> str:
    return f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;padding:14px 18px;margin:14px 0;background:#fff;"><h2 style="margin:0 0 8px;color:{color};">{_e(title)}</h2>{body}</div>'


def _table(rows: List[tuple]) -> str:
    body = "".join(f'<tr><td style="padding:6px 8px;font-weight:bold;vertical-align:top;width:28%;">{_e(a)}</td><td style="padding:6px 8px;vertical-align:top;">{_e(b)}</td></tr>' for a, b in rows)
    return f'<table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody>{body}</tbody></table>'


def _ul(items: List[Any]) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _checks(items: List[Any]) -> str:
    return "<ul>" + "".join(f"<li><input type='checkbox'> {_e(i)}</li>" for i in items) + "</ul>"


def _progress_track() -> str:
    rows = [(stage, desc) for stage, desc in PROGRESS_STAGES]
    checks = "".join(f"<p><input type='checkbox'> <strong>{_e(stage)}</strong> - {_e(desc)}</p>" for stage, desc in rows)
    return checks


def _research_table(routes: List[Dict[str, str]]) -> str:
    rows = [(r["site"], f'{r["skill"]}; {r["time"]}; clue: {r["clue"]}') for r in routes]
    return _table(rows)


def _puzzle_board() -> str:
    fields = [
        "Observed symbols / pieces",
        "Confirmed rules",
        "False rules",
        "Research leads",
        "Wrong attempts",
        "Theories",
        "Calendar / staged reveals",
        "Rival progress",
        "Final answer",
        "Consequences revealed",
    ]
    html = "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;'>"
    for field in fields:
        html += f"<div style='border:1px solid #ddd;border-radius:6px;padding:8px;background:#fafafa;'><strong>{_e(field)}</strong><textarea rows='3' style='width:100%;font-family:inherit;margin-top:6px;'></textarea></div>"
    html += "</div>"
    return html


def _clue_ladder(items: List[Any]) -> str:
    rows = []
    for item in items:
        if isinstance(item, dict):
            rows.append((
                item.get("clue", ""),
                f"{item.get('where', '')} | Means: {item.get('means', '')} | Cost: {item.get('failure_cost', '')}",
            ))
        else:
            rows.append(("Clue", str(item)))
    return _table(rows)


def render_puzzle_module(mission: dict, sponsor: str, puzzle_type: str, plan: Dict[str, Any], research_routes: List[Dict[str, str]], strength: Dict[str, Any], calendar: List[str]) -> str:
    title = mission.get("title", "Puzzle")
    fc = _faction_color(sponsor)
    reward_profile = REWARD_PROFILES.get(sponsor, "recognition, faction standing, and more EC than Kharma")
    body = ""
    body += _card("Briefing", f'<div style="white-space:pre-line;font-style:italic;">{_e(plan["briefing"])}</div>', fc)
    body += _card("Puzzle Frame", _table([
        ("Puzzle", plan.get("puzzle_name", title)),
        ("Type", f"{puzzle_type} - {PUZZLE_TYPES[puzzle_type]}"),
        ("Sponsor", sponsor),
        ("Objective", plan.get("objective", "")),
        ("Surface description", plan.get("surface_description", "")),
        ("Reward profile", reward_profile),
    ]), "#8a5a1f")
    body += _card("Mission-Specific Stakes", f"<p>{_e(plan.get('mission_specific_stakes', ''))}</p>", "#7b1e1e")
    body += _card("Live Party Scaling", f"<p>{_e(_party_scaling_note(strength))}</p>", "#3a6898")
    body += _card("No Map By Default", "<p>No map generated. Run this through clues, research, symbols, staged discoveries, and the puzzle board. Add a map only for a genuinely spatial/physical puzzle.</p>", "#7b1e1e")
    body += _card("Research Routes", _research_table(research_routes) + "<p>Research can take meaningful time; the world continues moving while the party researches.</p>", "#3a6898")
    body += _card("Progress / Breakthrough Track", _progress_track(), "#2a6a2a")
    body += _card("Calendar Stages", _checks(calendar), "#8a5a1f")
    body += _card("Puzzle Board", _puzzle_board(), "#555")
    body += _card("DM Answer Key", _table([
        ("Core puzzle", plan.get("core_puzzle", "")),
        ("Exact answer", plan.get("answer_key", "")),
    ]) + "<h3>Exact Solution Steps</h3>" + _ul(plan.get("exact_solution_steps", [])) + "<h3>Clue Ladder</h3>" + _clue_ladder(plan.get("clue_ladder", [])) + "<h3>Clue Meanings</h3>" + _ul(plan.get("clue_meanings", [])) + "<h3>Solve Path</h3>" + _ul(plan.get("solve_path", [])), "#7b1e1e")
    body += _card("Alternate Solutions / Unstick Notes", "<h3>Alternate Solutions</h3>" + _ul(plan.get("alternate_solutions", [])) + "<h3>DM Unstick Notes</h3>" + _ul(plan.get("unstick_notes", [])), "#3a6898")
    body += _card("Wrong Attempts And World Movement", "<h3>Wrong / Partial Attempts</h3>" + _ul(plan.get("wrong_attempts", [])) + "<h3>World Keeps Turning</h3>" + _ul(plan.get("world_moves", [])), "#8a5a1f")
    body += _card("Rival Pressure / Light Skirmishes", _ul(random.sample(LIGHT_SKIRMISHES, 3)) + "<p>Skirmishes should be nonlethal pressure: delay, distract, steal credit, or get ahead. Combat is not the solve method.</p>", "#555")
    body += _card("Debrief / Scholar Review", f'<p>{_e(plan.get("debrief", ""))}</p><p><strong>Debrief modes:</strong> {_e(", ".join(DEBRIEF_TYPES))}</p><p><strong>News:</strong> {_e(plan.get("news_angle", ""))}</p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Scholar review notes..."></textarea>', "#2a6a2a")
    return _page(title, body, sponsor)


def render_puzzle_session(mission: dict, sponsor: str, puzzle_type: str, plan: Dict[str, Any], research_routes: List[Dict[str, str]], strength: Dict[str, Any], calendar: List[str]) -> str:
    title = mission.get("title", "Puzzle")
    fc = _faction_color(sponsor)
    body = f'<h1 style="color:{fc};">{_e(title)}</h1>'
    body += _card("Puzzle", _table([
        ("Sponsor", sponsor),
        ("Type", PUZZLE_TYPES[puzzle_type]),
        ("Objective", plan.get("objective", "")),
        ("Stakes", plan.get("mission_specific_stakes", "")),
        ("Party", _party_scaling_note(strength)),
    ]), fc)
    body += _card("Research", _research_table(research_routes), "#3a6898")
    body += _card("Progress", _progress_track(), "#2a6a2a")
    body += _card("Calendar", _checks(calendar), "#8a5a1f")
    body += _card("Puzzle Board", _puzzle_board(), "#555")
    body += _card("DM Key Snapshot", _table([("Answer", plan.get("answer_key", "")), ("Steps", "; ".join(plan.get("exact_solution_steps", [])[:4])), ("Unstick", "; ".join(plan.get("unstick_notes", [])[:3]))]), "#7b1e1e")
    return _page(title, body, sponsor)


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


async def build_puzzle_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Puzzle")
    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    sponsor = _resolve_sponsor(mission)
    puzzle_type = _pick_puzzle_type(mission)
    strength = _party_strength()
    seeds = _canon_seed(puzzle_type, sponsor)
    research_routes = _pick_research_routes(puzzle_type, seeds, strength)
    calendar = _calendar_stages()

    logger.info(f"[PUZZLE] Building {title!r} | sponsor={sponsor} | type={puzzle_type}")

    plan = await _generate_plan(mission, sponsor, puzzle_type, seeds, research_routes, strength)

    from src.mission_builder.mimir_module import create_module as _mc, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="puzzle")
    module_html = render_puzzle_module(mission, sponsor, puzzle_type, plan, research_routes, strength, calendar)
    module_html += _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")
    session_html = render_puzzle_session(mission, sponsor, puzzle_type, plan, research_routes, strength, calendar)
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component
    dm_md = (
        f"## Puzzle DM Guide\n"
        f"### Mission-Specific Stakes\n"
        f"{plan.get('mission_specific_stakes', '')}\n\n"
        f"### Core Puzzle\n"
        f"- Name: {plan.get('puzzle_name', title)}\n"
        f"- Type: {PUZZLE_TYPES[puzzle_type]}\n"
        f"- Objective: {plan.get('objective', '')}\n"
        f"- Core puzzle: {plan.get('core_puzzle', '')}\n"
        f"- Exact answer: {plan.get('answer_key', '')}\n\n"
        f"### Exact Solution Steps\n"
        + "\n".join(f"- {c}" for c in plan.get("exact_solution_steps", []))
        + "\n\n### Clue Ladder\n"
        + "\n".join(
            f"- {c.get('clue', c) if isinstance(c, dict) else c}: "
            f"{c.get('where', '') if isinstance(c, dict) else ''} "
            f"{c.get('means', '') if isinstance(c, dict) else ''}"
            for c in plan.get("clue_ladder", [])
        )
        + "\n\n"
        f"### Clue Meanings\n"
        + "\n".join(f"- {c}" for c in plan.get("clue_meanings", []))
        + "\n\n### Solve Path\n"
        + "\n".join(f"- {s}" for s in plan.get("solve_path", []))
        + "\n\n### Alternate Solutions\n"
        + "\n".join(f"- {s}" for s in plan.get("alternate_solutions", []))
        + "\n\n### Unstick Notes\n"
        + "\n".join(f"- {s}" for s in plan.get("unstick_notes", []))
        + "\n\n### Wrong Attempts / World Movement\n"
        + "\n".join(f"- {s}" for s in plan.get("wrong_attempts", []))
        + "\n"
        + "\n".join(f"- {s}" for s in plan.get("world_moves", []))
    )
    players_md = (
        f"## Player Puzzle Guide\n"
        f"### Public Frame\n"
        f"- Sponsor: {sponsor}\n"
        f"- Puzzle type: {PUZZLE_TYPES[puzzle_type]}\n"
        f"- Surface description: {plan.get('surface_description', '')}\n"
        f"- Objective: {plan.get('objective', '')}\n\n"
        f"### Stakes\n"
        f"{plan.get('mission_specific_stakes', '')}\n\n"
        f"### Research Routes\n"
        + "\n".join(f"- {r.get('site')}: {r.get('clue')} ({r.get('skill')}, {r.get('time')})" for r in research_routes)
        + "\n\nResearch can take time. The world keeps turning, but there is no gotcha timer unless the fiction creates one."
    )
    chart_md = (
        f"## Puzzle Chart Pack\n"
        f"### Exact Solution Steps\n"
        + "\n".join(f"- {s}" for s in plan.get("exact_solution_steps", []))
        + "\n\n### Clue Ladder\n"
        + "\n".join(
            f"- {c.get('clue', c) if isinstance(c, dict) else c}: "
            f"{c.get('where', '') if isinstance(c, dict) else ''} "
            f"{c.get('means', '') if isinstance(c, dict) else ''}"
            for c in plan.get("clue_ladder", [])
        )
        + "\n\n"
        f"### Progress Stages\n"
        + "\n".join(f"- {stage}: {desc}" for stage, desc in PROGRESS_STAGES)
        + "\n\n### Research Sites\n"
        + "\n".join(f"- {site}" for site in RESEARCH_SITES)
        + "\n\n### Solve Methods\n"
        + "\n".join(f"- {s}" for s in SOLVE_METHODS)
        + "\n\n### Scholar Review / Debrief Types\n"
        + "\n".join(f"- {s}" for s in DEBRIEF_TYPES)
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, sponsor, dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, sponsor, players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, sponsor, chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief", "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",      "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Clue Guide",    "type": "custom",      "content": chart_md},
        ])
    box_components = component_links(has_maps=False)

    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title,
            faction=sponsor,
            tier=mission.get("tier", "standard"),
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
        logger.warning(f"[PUZZLE] index.html failed: {e}")
        index_path = out_dir / "module.html"

    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as e:
        logger.warning(f"[PUZZLE] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[PUZZLE] Complete: {title!r} -> {out_dir.name}")
    return index_path
