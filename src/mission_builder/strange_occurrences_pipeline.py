"""
strange_occurrences_pipeline.py - Standalone pipeline for weird civic cases.

Strange Occurrences are not generic investigations. They are cases where the
city has to decide what kind of wrong happened: returned dead, ghosts,
revenants, doppelgangers, memory bleed, Tower errors, omens, and entities that
look like monsters until someone listens.

The coroner's office is usually involved because the dead staying properly dead
is their job, but sketchy guilds and frightened factions can occasionally open
the file. Payment depends on the resolution: if the ghost convinces the party
they are protecting their family, the party may choose closure over contract pay.

No map generation by default. This pipeline uses scenes, records, witnesses,
ritual handling, moral outcomes, and evidence boards.

Exported:
    build_strange_occurrences_module(mission: dict, out_dir: Path) -> Path
    is_strange_occurrences_mission(mission_type: str) -> bool
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

KEYWORDS = {
    "strange occurrence", "strange occurrences", "weird occurrence", "occurrence",
    "returned dead", "returning dead", "revenant", "ghost", "haunting",
    "doppelganger", "doppleganger", "impostor", "imposter", "duplicate",
    "walking corpse", "wrong grave", "graveyard", "coroner", "morgue",
    "memory bleed", "tower glitch", "reality error", "omen",
}


def is_strange_occurrences_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in KEYWORDS)


OCCURRENCE_TYPES = {
    "returned_dead": "returned dead, revenants, ghosts, wrong burials, and dead people walking home",
    "doppelganger": "doppelganger / impostor event with no automatic villain flag",
    "haunting": "haunting, memory bleed, grief echo, replayed violence, or impossible witness",
    "tower_error": "Tower glitch, reality error, record desync, duplicated room, or yesterday leaking into today",
    "misread_entity": "frightening omen or entity that may be protective, contractual, divine, or misunderstood",
    "mixed_weird": "several strange signs tangled together: grave records, copies, ghosts, memory, and faction pressure",
}

FIRST_JOB_MODES = [
    "investigate first",
    "contain first",
    "resolve first",
    "protect the occurrence before anyone understands it",
    "calm witnesses while checking the records",
    "prove whether the dead / copy / omen is actually dangerous",
]

STRUCTURES = [
    "Report -> Scene -> Truth -> Resolution",
    "Report -> Coroner Record -> Witness Web -> Moral Choice",
    "Scene -> Panic Control -> Evidence Board -> Restorative Ending",
    "Records -> Grave / Identity Check -> Faction Interference -> Judgment",
    "Public Rumor -> TNN Heat -> Private Truth -> Consequence",
    "Occurrence Contact -> Listening Scene -> Hidden Culprit -> Closure",
]

DEAD_MORAL_CENTERS = [
    "put them properly back to rest",
    "find who disturbed, raised, moved, copied, or exploited them",
    "decide whether they deserve legal or moral room to stay",
    "protect a family from a returned dead who is actually guarding them",
    "restore the death record before the city forgets the right person",
]

DOPPELGANGER_ROLES = [
    "predator using a borrowed life",
    "refugee copying someone to survive",
    "tool of a faction, curse, blackmailer, or handler",
    "identity tragedy with inherited memories, debts, love, or guilt",
    "confused survivor who thinks the copied life is also theirs",
    "spy who would rather defect than keep replacing people",
]

EVIDENCE_LANES = [
    ("Body / Form", "Medicine, Arcana, Religion", "what the body, ghost, copy, or entity actually is"),
    ("Witness", "Insight, Persuasion, Intimidation", "what people saw, misread, omitted, or emotionally need to be true"),
    ("Records", "Investigation, History, Religion", "death certificates, grave ledgers, permits, name changes, custody records"),
    ("Location", "Perception, Survival, Arcana", "where the weirdness repeats, leaks, anchors, or avoids"),
    ("Motive", "Insight, History, Deception", "who benefits if the party chooses the obvious answer"),
    ("Faction Link", "History, Religion, Persuasion", "who wants it sealed, exploited, protected, interpreted, or buried"),
    ("Supernatural Trace", "Arcana, Religion, Nature", "residue, oath, soul echo, divine mark, rift shimmer, Tower error"),
]

FAIL_FORWARD = [
    "The party misses the clean clue but a frightened witness blurts out the emotional truth.",
    "A record search fails, but the wrong ledger reveals a different contradiction.",
    "The occurrence flees instead of fighting, leaving behind proof of what it feared.",
    "TNN gets a bad version of the story, raising pressure but surfacing a new witness.",
    "A faction files a complaint, which proves they were watching too closely.",
    "The coroner locks the file for an hour; a clerk quietly gives the party the missing page.",
    "A ritual fails gently: no closure yet, but the name, grave, or copied memory reacts.",
]

RESOLUTION_OPTIONS = [
    "proper burial / reburial / grave correction",
    "protect the ghost, revenant, or copy from being treated as a monster",
    "expose who raised, copied, bound, moved, or exploited the occurrence",
    "restore civic records so the right person is remembered",
    "public explanation with TNN managed carefully",
    "private coroner report and quiet family closure",
    "faction handoff with safeguards",
    "nonlethal containment until a better answer is found",
    "let the occurrence leave if it is not harming anyone",
    "destroy or banish only if it is a real threat and other paths failed",
]

OUTCOME_RULES = [
    ("Contract Clean", "The party resolves the stated job without betraying the truth. Full EC, reputation, possible Kharma."),
    ("Moral Override", "The truth changes the contract. The party may get no pay but earns Kharma, family trust, or coroner respect."),
    ("Protected Weird", "The occurrence was a person, victim, or guardian. Sponsor may be angry; vulnerable people remember."),
    ("Culprit Exposed", "The occurrence was a symptom. Pay comes from proof, not violence."),
    ("Public Scandal", "TNN or witnesses force the truth public. Factions react sharply."),
    ("Paperwork Victory", "The dead, copy, or family gets legal status, burial correction, or record restoration."),
    ("Bad Ending", "The party kills or exposes the wrong target. Rep loss, haunting residue, formal complaint, or watcher assigned."),
]

CORONER_CONTACTS = [
    "Deputy Coroner Ilyra Voss",
    "Grave Registrar Pellan Mourne",
    "Morgue Clerk Sella Tane",
    "Cemetery Warden Hask Orrel",
    "Death Registry Auditor Nima Vale",
    "Night Coroner Brannic Holt",
]

SKETCHY_SPONSORS = [
    "Obsidian Lotus",
    "Iron Fang Consortium",
    "Glass Sigil",
    "Serpent Choir",
    "Brother Thane's Cult",
]

INTERESTED_PARTY_GOALS = {
    "Wardens of Ash": "protect civilians and keep the scene from becoming a riot",
    "Patchwork Saints": "protect families, refugees, and people being treated like monsters",
    "Glass Sigil": "catalogue the impossible and claim record access before panic contaminates testimony",
    "Wizards Tower": "test whether the phenomenon obeys known arcane laws",
    "Obsidian Lotus": "identify who benefits from the uncertainty and move quietly",
    "Iron Fang Consortium": "secure liability, salvage, insurance, or ownership angles",
    "Serpent Choir": "interpret whether the dead, copy, or omen is bound by contract",
    "Tower Authority": "decide legal continuity, identity status, and public safety authority",
    "Guild of Ashen Scrolls": "preserve names, histories, and contradictory records",
    "Argent Blades": "offer visible protection and maybe escalate if something threatens witnesses",
}


def _db_rows(query: str, params: tuple = ()) -> List[Dict]:
    try:
        from src.db_api import raw_query
        return raw_query(query, params) or []
    except Exception as e:
        logger.warning(f"[STRANGE] DB read failed: {e}")
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
    "strange occurrence",
    "weird civic case",
    "the occurrence",
    "generic case",
    "file that would not stay closed",
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
        if term.lower() not in {"mission", "strange occurrence", "standard", "posted"} and term not in terms:
            terms.append(term)
    weird = re.findall(r"\b(?:ghost|revenant|dead|doppelganger|impostor|duplicate|memory|omen|grave|coroner|record|haunting|tower|glitch)\b", text, flags=re.I)
    stakes = re.findall(r"[^.!?\n]*(?:dead|ghost|copy|duplicate|memory|record|grave|family|truth|protect|culprit|contract|moral|person)[^.!?\n]*", text, flags=re.I)
    return {
        "full_text": text[:1800],
        "canon_terms": terms[:14],
        "weird_markers": sorted({w.lower() for w in weird})[:8],
        "stakes": [s.strip() for s in stakes[:6] if s.strip()],
    }


def _specificity_score(plan: Dict[str, Any], context: Dict[str, Any]) -> int:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    score = 0
    for term in context.get("canon_terms", []):
        if term.lower() in blob:
            score += 2
    for marker in context.get("weird_markers", []):
        if marker.lower() in blob:
            score += 1
    for stake in context.get("stakes", []):
        words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", stake)[:4]]
        if words and any(w in blob for w in words):
            score += 1
    return score


def _is_generic_plan(plan: Dict[str, Any], context: Dict[str, Any]) -> bool:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    has_context = bool(context.get("canon_terms") or context.get("weird_markers") or context.get("stakes"))
    return (has_context and _specificity_score(plan, context) < 3) or any(marker in blob for marker in GENERIC_PLAN_MARKERS)


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
    pcs = []
    skill_counts: Dict[str, int] = {}
    levels = []
    for row in snap_rows:
        snap = _json_col(row.get("snapshot_json"), {})
        if not isinstance(snap, dict):
            continue
        name = snap.get("name") or row.get("char_name") or "Unknown PC"
        level = snap.get("level") or snap.get("total_level") or snap.get("character_level") or 5
        try:
            level = int(level)
        except Exception:
            level = 5
        levels.append(level)
        skills = _find_skill_map(snap)
        for skill, value in skills.items():
            try:
                if int(value) >= 4:
                    skill_counts[str(skill).lower()] = skill_counts.get(str(skill).lower(), 0) + 1
            except Exception:
                pass
        pcs.append({"name": name, "level": level})
    avg = sum(levels) / len(levels) if levels else 5
    return {
        "pcs": pcs,
        "party_size": len(pcs) or 4,
        "avg_level": round(avg, 1),
        "high_skills": sorted(skill_counts, key=skill_counts.get, reverse=True)[:8],
    }


def _dc_profile(tier: str, strength: Dict[str, Any]) -> Dict[str, int]:
    avg = int(float(strength.get("avg_level", 5)))
    base = 11 + min(7, avg // 2)
    tier_mod = {"local": -2, "standard": 0, "investigation": 1, "major": 2, "high-stakes": 3, "epic": 4}.get((tier or "standard").lower(), 0)
    return {
        "basic": max(10, base + tier_mod),
        "hard": max(13, base + tier_mod + 3),
        "occult": max(12, base + tier_mod + 2),
        "social": max(11, base + tier_mod + 1),
        "records": max(11, base + tier_mod),
    }


def _pick_type(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("type", "mission_type", "title", "description", "body")).lower()
    if any(k in text for k in ("doppel", "dopple", "impost", "duplicate", "copy")):
        return "doppelganger"
    if any(k in text for k in ("ghost", "haunt", "memory")):
        return "haunting"
    if any(k in text for k in ("dead", "revenant", "grave", "corpse", "morgue", "coroner")):
        return "returned_dead"
    if any(k in text for k in ("tower", "glitch", "record", "yesterday", "reality")):
        return "tower_error"
    return random.choice(list(OCCURRENCE_TYPES))


def _pick_sponsor(mission: dict, occurrence_type: str) -> Dict[str, str]:
    sponsor = mission.get("faction") or ""
    roll = random.random()
    if sponsor and sponsor != "Independent":
        source = sponsor
    elif occurrence_type in ("returned_dead", "haunting") and roll < 0.65:
        source = "Coroner's Office"
    elif roll < 0.12:
        source = random.choice(SKETCHY_SPONSORS)
    else:
        source = random.choice(["Coroner's Office", "Tower Authority", "Patchwork Saints", "Wardens of Ash", "Guild of Ashen Scrolls"])
    contact = random.choice(CORONER_CONTACTS) if source == "Coroner's Office" else mission.get("npc_giver") or f"{source} case contact"
    return {"sponsor": source, "contact": contact}


def _pick_locations(occurrence_type: str) -> List[Dict[str, Any]]:
    tags = ["morgue", "grave", "cemetery", "temple", "market", "district", "warrens"]
    if occurrence_type == "doppelganger":
        tags = ["market", "guild", "tavern", "safehouse", "district", "forum"]
    elif occurrence_type == "tower_error":
        tags = ["archive", "tower", "forum", "district", "street"]
    clause = " OR ".join(["LOWER(name) LIKE %s OR LOWER(type_tag) LIKE %s OR LOWER(description) LIKE %s"] * len(tags))
    params: List[str] = []
    for tag in tags:
        params.extend([f"%{tag}%", f"%{tag}%", f"%{tag}%"])
    rows = _db_rows(
        f"SELECT district, place_type, name, type_tag, description, extra_json FROM gazetteer_places WHERE {clause} ORDER BY RAND() LIMIT 5",
        tuple(params),
    )
    if rows:
        return rows
    return [
        {"district": "Grand Forum", "name": "Death Registry annex", "description": "A quiet civic office where grief becomes paperwork."},
        {"district": "Sanctum Quarter", "name": "Old cemetery row", "description": "Rows of names, fresh candles, and one grave whose soil is wrong."},
        {"district": "The Warrens", "name": "Rain-slick alley shrine", "description": "A place locals use when official gods feel too far away."},
    ]


def _interested_parties(sponsor: str, occurrence_type: str) -> List[Dict[str, str]]:
    pool = list(INTERESTED_PARTY_GOALS)
    random.shuffle(pool)
    selected = []
    for faction in pool:
        if faction == sponsor:
            continue
        selected.append({"faction": faction, "goal": INTERESTED_PARTY_GOALS[faction]})
        if len(selected) >= 5:
            break
    if occurrence_type == "doppelganger":
        selected.append({"faction": "Obsidian Lotus", "goal": "determine whether the copy is an asset, refugee, or liability"})
    if occurrence_type in ("returned_dead", "haunting"):
        selected.append({"faction": "Serpent Choir", "goal": "argue whether the dead are bound, wronged, or under contract"})
    return selected[:6]


async def _ollama(prompt: str, tokens: int = 2600) -> str:
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("strange_occurrence_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[STRANGE] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=240.0) as c:
            r = await c.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.88, "num_predict": tokens},
                },
            )
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"[STRANGE] Ollama unavailable: {e}")
        return ""


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


async def _generate_plan(
    mission: dict,
    occurrence_type: str,
    sponsor: Dict[str, str],
    locations: List[Dict[str, Any]],
    parties: List[Dict[str, str]],
    dcs: Dict[str, int],
    strength: Dict[str, Any],
) -> Dict[str, Any]:
    mission_context = _mission_context(mission)
    prompt = f"""Create a D&D Strange Occurrences mission module as JSON only.
This is not a generic investigation. The core is weird civic / moral uncertainty:
returned dead, ghosts, revenants, doppelgangers, hauntings, Tower glitches,
records that no longer agree, and entities that may not be evil.

Mission: {mission.get('title', 'Strange Occurrence')}
Mission canon that must be preserved: {mission_context}
Occurrence type: {occurrence_type} - {OCCURRENCE_TYPES[occurrence_type]}
Sponsor/contact: {sponsor}
Locations from DB: {locations}
Interested parties: {parties}
Party strength: {strength}
DCs: {dcs}

Design rules:
- Default mode is random mix: investigate / contain / resolve / protect / calm witnesses.
- Coroner's office or death records should matter unless the case is clearly doppelganger-only.
- Use clue ladder + evidence board + contradictions + skill-check reveals.
- No gotcha dead ends. Include fail-forward clues.
- Combat may happen by occurrence type, but never default murder mode.
- Always include peaceful / restorative / nonlethal / expose-real-culprit paths.
- Payment depends on resolution. If the ghost/copy/returned dead is right, the party may lose contract pay but gain Kharma, respect, or truth.

Return JSON object with:
case_title, public_report, first_scene, true_situation, moral_question,
structure, occurrence_behavior, uncanny_rule, explanation_ladder[5 strings], culprit_or_cause, contradictions[6],
evidence_ladder[7 objects: lane, skill, dc, clue, if_failed],
witnesses[6 objects: name, role, what_they_say, what_they_hide],
dialogue[24 strings],
coroner_records[5 strings],
faction_pressure[6 strings],
resolution_paths[8 objects: choice, result, pay, kharma, faction_reaction],
combat_or_hazard_options[5 strings],
tnn_angle, follow_up, news_seed.
JSON only."""
    data = _parse_json(await _ollama(prompt))
    return _normalize_plan(data, mission, occurrence_type, sponsor, locations, parties, dcs)


def _fallback_plan(occurrence_type: str, sponsor: Dict[str, str], locations: List[Dict[str, Any]], parties: List[Dict[str, str]], dcs: Dict[str, int], mission: Optional[dict] = None) -> Dict[str, Any]:
    loc = locations[0] if locations else {"name": "Death Registry annex", "district": "Grand Forum"}
    mission_context = _mission_context(mission or {})
    title = (mission or {}).get("title", "Strange Occurrence")
    canon = ", ".join(mission_context.get("canon_terms", [])[:6]) or title
    stake = (mission_context.get("stakes") or [f"{canon} forces the city to decide whether the weirdness is a threat, victim, witness, or person"])[0]
    behavior = random.choice(DOPPELGANGER_ROLES if occurrence_type == "doppelganger" else DEAD_MORAL_CENTERS)
    return {
        "case_title": f"{title}: The Case That Would Not Stay Closed",
        "public_report": f"{sponsor['contact']} reports a strange occurrence near {loc.get('name')} tied to {canon}: witnesses disagree on what kind of wrong happened.",
        "first_scene": f"{loc.get('name')} in {loc.get('district')} feels ordinary until the records, witnesses, and body language stop agreeing.",
        "true_situation": f"The occurrence is not automatically evil. Its current behavior is best described as: {behavior}.",
        "moral_question": "Does the party complete the contract as written, or change the outcome after learning who is actually being protected?",
        "structure": random.choice(STRUCTURES),
        "occurrence_behavior": behavior,
        "uncanny_rule": f"The weirdness follows one playable rule: it reacts whenever someone denies the mission-specific truth around {canon}.",
        "explanation_ladder": ["obvious monster story", "record contradiction", "witness contradiction", f"mission stake surfaces: {stake}", "truth shows whether the occurrence is threat, victim, witness, or protector"],
        "culprit_or_cause": "A hidden actor disturbed the records and let fear turn a vulnerable occurrence into a monster story.",
        "contradictions": [
            "The death certificate time is one hour before the last confirmed conversation.",
            "The grave soil is fresh but the burial ledger says it was never opened.",
            "A witness recognizes a voice but not the face using it.",
            "The supposed monster avoided children and the elderly.",
            "The coroner's seal appears on a document no coroner signed.",
            "The occurrence remembers a private kindness nobody else recorded.",
        ],
        "evidence_ladder": [
            {"lane": lane, "skill": skills, "dc": dcs["basic"], "clue": clue, "if_failed": random.choice(FAIL_FORWARD)}
            for lane, skills, clue in EVIDENCE_LANES
        ],
        "witnesses": [
            {"name": "gravekeeper", "role": "first reporter", "what_they_say": "The dead came back wrong.", "what_they_hide": "They spoke to it before calling anyone."},
            {"name": "family member", "role": "protected person", "what_they_say": "Please do not hurt them.", "what_they_hide": "They asked the occurrence to stay nearby."},
            {"name": "coroner clerk", "role": "record witness", "what_they_say": "The paperwork changed after filing.", "what_they_hide": "They copied the original before it changed."},
            {"name": "TNN stringer", "role": "public pressure", "what_they_say": "The public deserves answers.", "what_they_hide": "They already have footage."},
            {"name": "faction observer", "role": "interested party", "what_they_say": "This is a public safety matter.", "what_they_hide": "Their faction wants custody."},
            {"name": "the occurrence", "role": "possible victim", "what_they_say": "I am not what they think.", "what_they_hide": "They know who caused this."},
        ],
        "dialogue": [
            "Coroner: My job is simple. The dead stay accounted for. This file is no longer simple.",
            "Ghost: I stood at the door because the child still wakes up screaming.",
            "Doppelganger: I borrowed a face. I did not borrow the knife.",
            "Family member: If you put them down, look me in the eye first.",
            "Clerk: Records do not change themselves. Usually.",
            "TNN: Is the city safe from its own dead?",
            "Warden: Nonlethal first unless it proves otherwise.",
            "Serpent Choir agent: A revenant may be an oath, not a crime.",
            "Glass Sigil aide: We need custody before panic ruins the evidence.",
            "Patchwork Saint: Weird does not mean disposable.",
        ],
        "coroner_records": [
            "death certificate with mismatched time",
            "grave ledger with one line overwritten",
            "body intake tag that names two different people",
            "family claim form never processed",
            "sealed note from the night coroner",
        ],
        "faction_pressure": [f"{p['faction']}: {p['goal']}" for p in parties],
        "resolution_paths": [
            {"choice": label, "result": desc, "pay": pay, "kharma": kharma, "faction_reaction": reaction}
            for label, desc, pay, kharma, reaction in [
                ("Complete Contract", "Resolve exactly what the sponsor asked.", "Full EC if morally defensible.", "Low to moderate.", "Sponsor approves."),
                ("Moral Override", "Protect the occurrence after proving it is not the threat.", "Often no EC.", "High.", "Sponsor may be angry; families remember."),
                ("Expose Culprit", "Shift the case from monster problem to responsible actor.", "Full or bonus EC.", "Moderate.", "Guilty faction retaliates."),
                ("Proper Rest", "Return the dead to grave, name, family, or ritual closure.", "Modest EC.", "High.", "Coroner and families approve."),
                ("Legal Status", "Argue the copy/returned person has standing.", "Uncertain.", "Moderate.", "Tower Authority gets involved."),
                ("Public Reveal", "Let TNN carry the truth.", "Variable.", "Variable.", "Public pressure explodes."),
            ]
        ],
        "combat_or_hazard_options": [
            "The occurrence flees through witnesses; restraint matters more than damage.",
            "A corpse-body lashes out when someone lies near it.",
            "A doppelganger handler tries to silence the copy.",
            "A ghost replay knocks everyone prone but avoids lethal harm.",
            "A faction agent escalates and forces a nonlethal standoff.",
        ],
        "tnn_angle": "TNN loves the drama: are the dead citizens, threats, or paperwork failures?",
        "follow_up": random.choice(["Investigation", "Rescue", "Negotiation", "Discovery", "Puzzle", "Defense"]),
        "news_seed": "A strange civic case involving death records, identity, and faction custody has left the city arguing over what counts as a person.",
    }


def _normalize_plan(
    data: Optional[Dict[str, Any]],
    mission: dict,
    occurrence_type: str,
    sponsor: Dict[str, str],
    locations: List[Dict[str, Any]],
    parties: List[Dict[str, str]],
    dcs: Dict[str, int],
) -> Dict[str, Any]:
    fallback = _fallback_plan(occurrence_type, sponsor, locations, parties, dcs, mission)
    if not isinstance(data, dict):
        return fallback
    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    for key in (
        "contradictions",
        "dialogue",
        "coroner_records",
        "faction_pressure",
        "combat_or_hazard_options",
        "explanation_ladder",
    ):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    for key in ("evidence_ladder", "witnesses", "resolution_paths"):
        value = plan.get(key)
        if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
            plan[key] = fallback[key]
    if _is_generic_plan(plan, _mission_context(mission)):
        logger.warning("[STRANGE] Rejected generic plan; using mission-specific fallback")
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


def _evidence_table(rows: List[Dict[str, Any]]) -> str:
    body = "".join(
        f"<tr><td>{_e(r.get('lane'))}</td><td>{_e(r.get('skill'))} DC {_e(r.get('dc'))}</td><td>{_e(r.get('clue'))}</td><td>{_e(r.get('if_failed'))}</td></tr>"
        for r in rows
    )
    return "<table><tr><th>Lane</th><th>Skill</th><th>Clue</th><th>Fail Forward</th></tr>" + body + "</table>"


def _witness_table(rows: List[Dict[str, Any]]) -> str:
    body = "".join(
        f"<tr><td>{_e(r.get('name'))}</td><td>{_e(r.get('role'))}</td><td>{_e(r.get('what_they_say'))}</td><td>{_e(r.get('what_they_hide'))}</td></tr>"
        for r in rows
    )
    return "<table><tr><th>Witness</th><th>Role</th><th>Says</th><th>Hides</th></tr>" + body + "</table>"


def _resolution_table(rows: List[Dict[str, Any]]) -> str:
    body = "".join(
        f"<tr><td>{_e(r.get('choice'))}</td><td>{_e(r.get('result'))}</td><td>{_e(r.get('pay'))}</td><td>{_e(r.get('kharma'))}</td><td>{_e(r.get('faction_reaction'))}</td></tr>"
        for r in rows
    )
    return "<table><tr><th>Choice</th><th>Result</th><th>Pay</th><th>Kharma</th><th>Reaction</th></tr>" + body + "</table>"


def render_module(mission: dict, occurrence_type: str, sponsor: Dict[str, str], locations: List[Dict[str, Any]], parties: List[Dict[str, str]], plan: Dict[str, Any], dcs: Dict[str, int], strength: Dict[str, Any]) -> str:
    title = mission.get("title") or plan.get("case_title") or "Strange Occurrence"
    faction = sponsor["sponsor"]
    fc = _faction_color(faction)
    loc_rows = [(l.get("name"), f"{l.get('district', '')} - {l.get('description', '')}") for l in locations]
    body = ""
    body += _card("Case File", _table([
        ("Type", f"{occurrence_type} - {OCCURRENCE_TYPES[occurrence_type]}"),
        ("Sponsor", faction),
        ("Contact", sponsor["contact"]),
        ("Structure", plan.get("structure", "")),
        ("Party", f"{strength['party_size']} PCs, average level {strength['avg_level']}; strong skills: {', '.join(strength.get('high_skills', [])) or 'unknown'}"),
    ]), fc)
    body += _card("Public Report", f"<p>{_e(plan.get('public_report'))}</p><p><strong>First scene:</strong> {_e(plan.get('first_scene'))}</p>", "#8a5a1f")
    body += _card("Truth / Moral Question", f"<p><strong>Truth:</strong> {_e(plan.get('true_situation'))}</p><p><strong>Question:</strong> {_e(plan.get('moral_question'))}</p><p><strong>Cause:</strong> {_e(plan.get('culprit_or_cause'))}</p>", "#7b1e1e")
    body += _card("Uncanny Rule", f"<p>{_e(plan.get('uncanny_rule'))}</p><h3>Explanation Ladder</h3>{_ul(plan.get('explanation_ladder', []))}", "#2a6a2a")
    body += _card("Locations", _table(loc_rows), "#555")
    body += _card("Contradictions", _ul(plan.get("contradictions", [])), "#3a6898")
    body += _card("Evidence Ladder", _evidence_table(plan.get("evidence_ladder", [])), "#3a6898")
    body += _card("Witness Web", _witness_table(plan.get("witnesses", [])), "#8a5a1f")
    body += _card("Coroner Records", _ul(plan.get("coroner_records", [])), "#555")
    body += _card("Faction Pressure", _ul(plan.get("faction_pressure", [f"{p['faction']}: {p['goal']}" for p in parties])), "#7b1e1e")
    body += _card("Dialogue Bank", _ul(plan.get("dialogue", [])), "#555")
    body += _card("Combat / Hazard Options", _ul(plan.get("combat_or_hazard_options", [])), "#c85320")
    body += _card("Resolution Determines Pay", _resolution_table(plan.get("resolution_paths", [])), "#2a6a2a")
    body += _card("TNN / Follow-Up", _table([("TNN angle", plan.get("tnn_angle", "")), ("News seed", plan.get("news_seed", "")), ("Follow-up", plan.get("follow_up", ""))]), "#3a6898")
    return _page(title, body, faction)


def render_session(mission: dict, sponsor: Dict[str, str], plan: Dict[str, Any]) -> str:
    title = mission.get("title") or plan.get("case_title") or "Strange Occurrence"
    faction = sponsor["sponsor"]
    fc = _faction_color(faction)
    body = f'<h1 style="color:{fc};">{_e(title)}</h1>'
    body += _card("Live Case State", _table([
        ("Sponsor", faction),
        ("Contact", sponsor["contact"]),
        ("Current theory", "<textarea rows='2' style='width:100%;font-family:inherit;'></textarea>"),
        ("Moral read", "<select><option>Threat</option><option>Victim</option><option>Guardian</option><option>Witness</option><option>Tool of someone else</option><option>Unknown</option></select>"),
    ]), fc)
    body += _card("Evidence Checklist", "".join(f"<p><input type='checkbox'> {_e(e.get('lane'))}: {_e(e.get('clue'))}</p>" for e in plan.get("evidence_ladder", [])), "#3a6898")
    body += _card("Witnesses", "".join(f"<p><input type='checkbox'> {_e(w.get('name'))} - {_e(w.get('role'))}</p>" for w in plan.get("witnesses", [])), "#8a5a1f")
    body += _card("Resolution", "<p><strong>Chosen ending:</strong> <select><option>Contract Clean</option><option>Moral Override</option><option>Protected Weird</option><option>Culprit Exposed</option><option>Proper Rest</option><option>Public Scandal</option><option>Bad Ending</option></select></p><p><strong>Pay earned?</strong> <select><option>Full</option><option>Partial</option><option>No EC, Kharma/standing only</option><option>No reward, fallout</option></select></p><textarea rows='4' style='width:100%;font-family:inherit;' placeholder='What did the party decide and who is angry?'></textarea>", "#2a6a2a")
    return _page(title, body, faction)


def _guides(plan: Dict[str, Any], occurrence_type: str, sponsor: Dict[str, str], parties: List[Dict[str, str]], dcs: Dict[str, int]) -> Dict[str, str]:
    dm = (
        "## Strange Occurrence DM Guide\n"
        f"### Type\n{occurrence_type}: {OCCURRENCE_TYPES[occurrence_type]}\n\n"
        f"### True Situation\n{plan.get('true_situation')}\n\n"
        f"### Moral Question\n{plan.get('moral_question')}\n\n"
        f"### Culprit / Cause\n{plan.get('culprit_or_cause')}\n\n"
        "### Contradictions\n" + "\n".join(f"- {x}" for x in plan.get("contradictions", [])) + "\n\n"
        "### Dialogue Bank\n" + "\n".join(f"- {x}" for x in plan.get("dialogue", [])) + "\n\n"
        "### Resolution Rule\nPayment depends on what the party proves and chooses. If the contract is morally wrong after the truth comes out, no-pay / high-Kharma closure is valid."
    )
    players = (
        "## Strange Occurrence Player Guide\n"
        f"### Public Report\n{plan.get('public_report')}\n\n"
        f"### First Scene\n{plan.get('first_scene')}\n\n"
        f"### Sponsor\n{sponsor['contact']} / {sponsor['sponsor']}\n\n"
        "### Known Lanes\n"
        + "\n".join(f"- {lane}: {skills}" for lane, skills, _ in EVIDENCE_LANES)
        + "\n\nWeird does not automatically mean evil. Listen before you decide."
    )
    chart = (
        "## Strange Occurrence Chart Pack\n"
        "### DCs\n" + "\n".join(f"- {k}: {v}" for k, v in dcs.items()) + "\n\n"
        "### Evidence Lanes\n" + "\n".join(f"- {e.get('lane')}: {e.get('skill')} DC {e.get('dc')} - {e.get('clue')}" for e in plan.get("evidence_ladder", [])) + "\n\n"
        "### Interested Parties\n" + "\n".join(f"- {p['faction']}: {p['goal']}" for p in parties) + "\n\n"
        "### Outcome Rules\n" + "\n".join(f"- {name}: {desc}" for name, desc in OUTCOME_RULES)
    )
    return {"dm": dm, "players": players, "chart": chart}


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


async def build_strange_occurrences_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Strange Occurrence")
    if out_dir is None:
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    strength = _party_strength()
    dcs = _dc_profile(mission.get("tier", "standard"), strength)
    occurrence_type = _pick_type(mission)
    sponsor = _pick_sponsor(mission, occurrence_type)
    locations = _pick_locations(occurrence_type)
    parties = _interested_parties(sponsor["sponsor"], occurrence_type)

    logger.info(f"[STRANGE] Building {title!r} | type={occurrence_type} | sponsor={sponsor['sponsor']}")

    plan = await _generate_plan(mission, occurrence_type, sponsor, locations, parties, dcs, strength)

    from src.mission_builder.mimir_module import create_module as _mc, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="strange_occurrence")
    _html = render_module(mission, occurrence_type, sponsor, locations, parties, plan, dcs, strength) + _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(_html, encoding="utf-8")
    (out_dir / "session.html").write_text(render_session(mission, sponsor, plan), encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component
    guides = _guides(plan, occurrence_type, sponsor, parties, dcs)
    write_component(out_dir, "dm_guide", "DM Guide", title, sponsor["sponsor"], guides["dm"])
    write_component(out_dir, "players_guide", "Players Guide", title, sponsor["sponsor"], guides["players"])
    write_component(out_dir, "chart_pack", "Chart Pack", title, sponsor["sponsor"], guides["chart"])
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",    "type": "description", "content": guides["players"]},
            {"title": f"{title} — DM Notes",         "type": "dm_notes",    "content": guides["dm"]},
            {"title": f"{title} — Evidence & Witness","type": "custom",      "content": guides["chart"]},
        ])

    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title,
            faction=sponsor["sponsor"],
            tier=mission.get("tier", "standard"),
            cr=mission.get("cr", max(1, int(float(strength["avg_level"])))),
            player_name=mission.get("player_name", "") or "Open",
            chapters=[],
            components=component_links(has_maps=False),
            chart_pack=None,
            map_count=0,
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as e:
        logger.warning(f"[STRANGE] index.html failed: {e}")
        index_path = out_dir / "module.html"

    try:
        from src.db_api import raw_execute
        raw_execute("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as e:
        logger.warning(f"[STRANGE] Could not write module_slug: {e}")

    with zipfile.ZipFile(out_dir.parent / f"{out_dir.name}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))
    return index_path
