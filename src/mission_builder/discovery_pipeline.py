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
    "ledger": "a ledger: the recorded history and trapped essence of a place the Tower recycled (anything from a single well to an entire star system)",
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

# Mission-card scaffolding words that must never be mined as "canon" and leaked
# into prose (they come from the "Type: ... | Difficulty: ... | Expires: ..." line).
_LABEL_STOPWORDS = {
    "mission", "discovery", "standard", "posted", "type", "difficulty",
    "expires", "tbd", "reward", "opposes", "none", "gm", "notes", "ec",
    "kharma", "status", "tier", "contact", "giver", "faction",
    "the", "she", "he", "they", "it", "complication",
}

# Read-aloud framing per discovery sub-type: documents/records read as a job
# briefing (neutral), physical anomalies read as a containment scene.
_READ_ALOUD_HINT = {
    "ledger": "discovery", "truth": "discovery", "memory": "discovery",
    "object": "contain", "phenomenon": "contain", "biology": "contain", "machine": "contain",
}

# Object-class descriptor banks so a document discovery is not described with
# living-anomaly boilerplate (and vice versa). Keyed by DISCOVERY_TYPES.
IMAGERY_BY_TYPE = {
    "ledger": [
        "Pages that map every corner of {subject} in patient detail",
        "Dates kept in a calendar no one runs anymore",
        "The names of the last people who lived in {subject}",
        "A final entry broken off in the middle of a word",
        "Ink that holds a faint warmth, as if {subject} still remembers being alive",
        "Directions to places that no longer exist",
        "Margins where loss is recorded as carefully as fact",
        "The weight of {subject} somehow pressed into the binding",
    ],
    "truth": [
        "Pages dense with coded entries and crossed-out names",
        "A cipher that resists a casual read",
        "Margins annotated in a second, nervous hand",
        "Dates that line up with events the city was told never happened",
        "Columns totaling sums no honest trade would move",
        "Wax, ash, or blood pressed into the binding",
        "One name repeated, scratched out, then written again",
        "Routes and drop points sketched across the endpapers",
    ],
    "object": [
        "Surface too smooth where it should be worn",
        "Weight that does not match its size",
        "A seam that was never meant to be opened",
        "Marks of a maker no one can name",
        "Warmth or cold that does not fade",
        "A finish that drinks the light around it",
        "Damage that healed instead of staying broken",
        "A guild mark from a workshop that burned down years ago",
    ],
    "phenomenon": [
        "An effect that holds steady only while watched",
        "A sound that arrives a moment before its source",
        "Air that bends, hums, or refuses to settle",
        "A pattern that repeats on a clock no one set",
        "Instruments that disagree with each other",
        "A boundary you can feel but not see",
        "Light that lags behind the thing casting it",
        "A cold spot that follows the loudest voice",
    ],
    "biology": [
        "Tissue that twitches with no body attached",
        "Growth rings that count more seasons than possible",
        "A scent caught between rot and fresh bread",
        "Eggs, spores, or buds at every stage at once",
        "Veins that pulse to an outside rhythm",
        "Skin that mimics whatever touches it",
        "A clutch that warms the air around it",
        "Marks of a feeding no local predator makes",
    ],
    "machine": [
        "Gears that turn with no spring or hand to drive them",
        "A casing grown rather than forged",
        "Ports that fit no tool anyone owns",
        "A readout in a script no guild teaches",
        "Heat where there should be no fuel",
        "Parts that repair themselves overnight",
        "A seal from the deepest Tower works",
        "A switch already set to a setting no one chose",
    ],
    "memory": [
        "A scene that plays back when the vial is warmed",
        "A voice that knows your name on the second hearing",
        "Emotions that arrive without a cause",
        "A face that sharpens the longer you look away",
        "A recorded life missing one deliberate hour",
        "Grief or joy that lingers after the playback ends",
        "Two versions of the same moment that disagree",
        "A memory that watches back",
    ],
}

HANDLING_BY_TYPE = {
    "ledger": [
        "Read it in order; the history unravels if taken out of sequence",
        "The essence inside wants to be remembered, not owned",
        "Closing it mid-reading can lose the world for good",
        "Two readers come away with two different histories",
        "It grows heavier the more of the world you have read",
        "Other recycled worlds in the archive stir when it is opened",
    ],
    "truth": [
        "Loses all leverage the moment a rival can call it a forgery",
        "Must stay inside one provable chain of custody",
        "Naming the wrong person aloud invites retaliation",
        "Half-decrypted, it implies the opposite of the truth",
        "Copies leak, only the original holds weight",
        "Reading it in public spends the secret for good",
    ],
    "object": [
        "Stable while observed, restless when stored alone",
        "Reacts to direct spellcasting",
        "Heavier to whoever currently owns it",
        "Marks the hands of repeat handlers",
        "Draws faction attention within hours of surfacing",
        "Behaves differently once it has been named",
    ],
    "phenomenon": [
        "Strengthens with each person who witnesses it",
        "Cannot be moved, only approached or contained",
        "Spreads along water, metal, or sound",
        "Fades when measured, returns when ignored",
        "Reacts to spellcasting nearby",
        "Resets on a cycle no one has timed yet",
    ],
    "biology": [
        "Hungry, do not feed it to test it",
        "Spreads by contact, breath, or blood",
        "Calms in cold, wakes in warmth",
        "Mimics nearby tissue if left in contact",
        "Distresses animals well before people notice",
        "Doubles quietly if given time and dark",
    ],
    "machine": [
        "Runs whether or not anyone wants it to",
        "Responds to a key or phrase no one has",
        "Draws power from its surroundings",
        "Repairs itself slowly when left alone",
        "Reacts badly to other Tower-made devices",
        "Locks onto the first operator to complete a cycle",
    ],
    "memory": [
        "Degrades a little with every playback",
        "Bleeds into whoever views it",
        "Plays only for one person at a time",
        "Edits itself to flatter whoever holds it",
        "Wakes when the right name is spoken",
        "Cannot be copied without losing the true hour",
    ],
}

IMPLICATIONS_BY_TYPE = {
    "ledger": [
        "it is the only surviving history of {subject}",
        "the Tower erased {subject} on purpose",
        "the essence inside could seed or restore a place",
        "factions will fight to own this record",
        "it proves the Tower recycles places that were still living",
        "whoever holds it holds the last memory of {subject}",
    ],
    "truth": [
        "it proves a faction lied",
        "it names people still in power",
        "the cipher itself is the real prize",
        "publishing it starts a feud",
        "it can be sold, buried, or weaponized",
        "someone will kill to keep it unread",
    ],
    "object": [
        "it belongs to someone who wants it back",
        "it is useful and dangerous in equal measure",
        "it proves a workshop or faction lied about its work",
        "it can seed a heist or a forgery",
        "owning it paints a target on your back",
        "it is one piece of a larger set",
    ],
    "phenomenon": [
        "it is spreading slowly outward",
        "it marks where something crossed over",
        "it can be triggered deliberately by the wrong people",
        "public panic is possible once it is named",
        "it rewrites what a district thought was safe",
        "it will not stay contained for long",
    ],
    "biology": [
        "it may be alive and aware",
        "it reproduces if ignored",
        "it proves something was bred, not born",
        "a cure or a weapon could be made from it",
        "public panic is possible",
        "it belongs to an ecology no one has mapped",
    ],
    "machine": [
        "it was built for a purpose no one will admit",
        "it is still partly running",
        "whoever holds the key holds the power",
        "it links to the deeper Tower works",
        "it is useful and dangerous in equal measure",
        "it can seed a puzzle or a sabotage",
    ],
    "memory": [
        "it contradicts an official account",
        "it implicates a person who is still alive",
        "it may be a copy, not the original life",
        "it can be edited to lie convincingly",
        "someone wants this hour forgotten",
        "it proves a death, a crime, or a betrayal",
    ],
}

CONTAINMENT_BY_TYPE = {
    "ledger": [
        "read the entries in order, never out of sequence",
        "one reader holds the thread at a time",
        "do not let the essence disperse in open air",
        "log every entry read aloud",
        "never burn it; the world dies a second time",
        "do not let rival factions claim the world's record",
    ],
    "truth": [
        "keep witness count low", "assign one trusted handler",
        "log every reader and every copy", "do not read it aloud in public",
        "do not let rival factions take custody", "verify it before you publish",
    ],
    "object": [
        "do not expose to direct spellcasting", "keep witness count low",
        "assign one handler", "record every change",
        "do not let rival factions take custody",
    ],
    "phenomenon": [
        "do not measure it head-on", "keep crowds back",
        "log every cycle and change", "limit spellcasting nearby",
        "do not let rival factions claim the site",
    ],
    "biology": [
        "no direct skin contact", "keep it cold and contained",
        "limit who breathes the same air", "record every change",
        "do not let it feed",
    ],
    "machine": [
        "do not complete an unknown cycle", "keep other devices away",
        "assign one operator", "record every change",
        "do not let rival factions take custody",
    ],
    "memory": [
        "limit playbacks", "one viewer at a time",
        "do not let it bleed into the handler", "log every playback",
        "do not let rival factions take custody",
    ],
}

# What the party actually walks away with, per discovery sub-type — keeps the
# fallback's "actual discovery" line concrete instead of "proof involving X".
FOUND_BY_TYPE = {
    "ledger": "a ledger holding the recorded history and essence of a world the Tower recycled",
    "truth": "evidence that overturns what the district believed",
    "object": "an object whose making and purpose no one will claim",
    "phenomenon": "an effect that should not be possible here",
    "biology": "living matter that should not exist in the Undercity",
    "machine": "a mechanism that is still, quietly, running",
    "memory": "a recorded life that remembers more than it should",
}

# Ledgers scale from the story of a single well up to a whole star system, and
# their worth scales with what they remember. EC bands are calibrated to the live
# economy (standard missions ~200 EC; TowerBay lots run tens of thousands and up).
LEDGER_SCOPES = [
    {"key": "well",     "label": "the story of a single well, shrine, or room", "subject": "a single well",  "worth": "a minor curio",        "ec": (40, 150),         "kharma": (2, 8),      "weight": 26, "cues": ("well", "shrine", "room", "grave", "alley")},
    {"key": "street",   "label": "the history of a street, market, or block",   "subject": "a city street",  "worth": "a collector's piece",  "ec": (150, 500),        "kharma": (8, 22),     "weight": 26, "cues": ("street", "market", "block", "row", "lane", "bazaar")},
    {"key": "district", "label": "the history of a whole district",             "subject": "a district",     "worth": "a guild-grade record", "ec": (600, 2000),       "kharma": (22, 60),    "weight": 22, "cues": ("district", "quarter", "ward", "borough")},
    {"key": "city",     "label": "the history of an entire city",              "subject": "a whole city",   "worth": "a treasure",           "ec": (3000, 12000),     "kharma": (60, 150),   "weight": 16, "cues": ("city", "town", "metropolis")},
    {"key": "world",    "label": "the last history of an entire world",        "subject": "an entire world","worth": "near-priceless",       "ec": (20000, 90000),    "kharma": (150, 400),  "weight": 8,  "cues": ("world", "planet", "globe", "continent")},
    {"key": "system",   "label": "the chronicle of an entire star system",     "subject": "a star system",  "worth": "priceless",            "ec": (250000, 2000000), "kharma": (400, 1200), "weight": 2,  "cues": ("star system", "solar system", "constellation", "galaxy")},
]


def _ledger_scope(mission: dict) -> Dict[str, Any]:
    """Pick how much world a ledger remembers. Honour an explicit scale cue in the
    mission text (largest mentioned wins); otherwise pick deterministically per
    mission id, biased toward smaller scopes so star-system ledgers stay rare."""
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "body", "description", "private_notes")).lower()
    for scope in reversed(LEDGER_SCOPES):  # largest -> smallest, so the biggest named scale wins
        if any(cue in text for cue in scope["cues"]):
            return scope
    seed = int(mission.get("id") or 0) or (sum(ord(c) for c in str(mission.get("title", "ledger"))) + 1)
    return random.Random(seed).choices(LEDGER_SCOPES, weights=[s["weight"] for s in LEDGER_SCOPES])[0]


def _ledger_value(mission: dict, scope: Dict[str, Any]) -> Dict[str, Any]:
    """Appraised worth of the ledger, scaling with scope, deterministic per mission."""
    rng = random.Random((int(mission.get("id") or 0) or 1) * 7 + len(scope["key"]))
    lo, hi = scope["ec"]
    klo, khi = scope["kharma"]
    return {"ec": rng.randint(lo, hi), "kharma": rng.randint(klo, khi), "worth": scope["worth"], "label": scope["label"]}


def _anchored_claims(mission: dict) -> List[str]:
    """Custody claims that lead with the factions actually named in the mission,
    then fill out with the generic custody bank."""
    owner = (mission.get("faction") or "").strip()
    antagonist = (mission.get("opposing_faction") or "").strip()
    claims: List[str] = []
    if owner and owner.lower() != "none":
        claims.append(f"{owner} wants to keep what it found and control the story")
    if antagonist and antagonist.lower() != "none":
        claims.append(f"{antagonist} wants it back, buried, or destroyed before it is read")
    for c in random.sample(FACTION_CUSTODY, len(FACTION_CUSTODY)):
        if len(claims) >= 5:
            break
        if c not in claims:
            claims.append(c)
    return claims[:5]


def _anchored_dialogue(object_hint: str) -> List[str]:
    """Dialogue lines that reference the actual object found, not a generic 'it'."""
    obj = (object_hint or "find").split(",")[0].strip() or "find"
    return [
        f"Scholar: Do not mistake this {obj} for something simple.",
        f"Witness: I knew about the {obj} before they told us to stay quiet.",
        "Warden: Can it hurt civilians today, yes or no.",
        "Archivist: Custody is not ownership. Write that down.",
        "Local: If it came from my street, why can I not see it.",
    ]


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


def _strip_card_meta(text: str) -> str:
    """Drop mission-card scaffolding lines (the Type/Difficulty/Expires/Reward
    stat line and the Opposes line) so their field labels never get mined as
    canon terms and leaked into the prose."""
    kept = []
    for line in (text or "").splitlines():
        bare = line.strip().strip("*").strip()
        low = bare.lower()
        if "|" in bare and low.startswith("type:"):
            continue
        if low.startswith("opposes:"):
            continue
        kept.append(line)
    return "\n".join(kept)


def _mission_context(mission: dict) -> Dict[str, Any]:
    text = _strip_card_meta(_mission_text(mission))
    terms = []
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9'’.-]*(?:\s+[A-Z][A-Za-z0-9'’.-]*){0,4}\b", text):
        # Cut at the first sentence boundary so a trailing ". She" / ". The" from
        # the next sentence is not swallowed into a proper-noun phrase.
        term = re.split(r"\.\s+", match.group(0).strip())[0].strip().rstrip(".")
        if not term:
            continue
        words = term.split()
        if all(w.lower().strip(".:,") in _LABEL_STOPWORDS for w in words):
            continue
        if term in terms:
            continue
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
    score = _specificity_score(plan, context)
    if has_context and score >= 3:
        # Anchored in mission canon -- markers alone cannot reject it. The
        # fallback fields merged into partial LLM plans contain some of our own
        # markers, so a marker hit on an anchored plan is self-poisoning, not
        # a signal the plan is generic.
        return False
    return (has_context and score < 3) or any(marker in blob for marker in GENERIC_PLAN_MARKERS)


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
    # A ledger is special canon: the recorded history and trapped essence of a
    # world the Tower recycled. Route it ahead of the generic document path.
    if re.search(r"\b(ledger|ledgers|chronicle|chronicles|world ?history|recorded history)\b", text):
        return "ledger"
    # Documents, records, and evidence are "truth" discoveries (what people
    # believe changes), not living anomalies. Route them before the generic scan.
    if re.search(r"\b(ledger|ledgers|record|records|document|documents|dossier|file|files|contract|letter|letters|manifest|cipher|code|codex|testimony|evidence|proof|account|accounts|archive)\b", text):
        return "truth"
    for key in DISCOVERY_TYPES:
        if key in text:
            return key
    if re.search(r"\b(spore|spores|egg|eggs|specimen|tissue|larva|symbiont|organism|bloom|fungus|hatchling)\b", text):
        return "biology"
    if re.search(r"\b(machine|mechanism|device|engine|gate|automaton|construct|apparatus|contraption)\b", text):
        return "machine"
    if re.search(r"\b(signal|echo|field|pulse|resonance|tremor|aura|hum|humming)\b", text):
        return "phenomenon"
    if re.search(r"\b(memory|memories|soul|recollection|recording|vision)\b", text):
        return "memory"
    return "object"


def _pick_context() -> Dict[str, Any]:
    rows = _db_rows("SELECT district, place_type, name, type_tag, description, extra_json FROM gazetteer_places ORDER BY RAND() LIMIT 1")
    return rows[0] if rows else {"district": "Grand Forum", "name": "a secured examination room", "description": "A quiet room filled with people trying not to touch the wrong thing."}


def _rift_fuel() -> List[Dict[str, Any]]:
    try:
        from src.news_feed import get_rift_mission_fuel
        return get_rift_mission_fuel(limit=5)
    except Exception:
        return []


def _fit_ctx(prompt: str, reply_tokens: int) -> int:
    """Size the Ollama context window to the prompt + planned reply. With no
    num_ctx set, Ollama uses a small default and silently truncates either the
    oversized prompt or the long plan JSON (yielding empty/unparseable plans ->
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

        decision = await wait_for_ollama_turn("discovery_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[DISCOVERY] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=220.0) as c:
            r = await c.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False, "options": {"temperature": 0.85, "num_predict": tokens, "num_ctx": _fit_ctx(prompt, tokens)}})
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
    scope_note = ""
    if dtype == "ledger":
        _scope = _ledger_scope(mission)
        _val = _ledger_value(mission, _scope)
        scope_note = (f"\nLedger scope: this ledger records {_scope['label']}. Worth scales to that: "
                      f"{_val['worth']}, about {_val['ec']} EC. Write the history, imagery, essence, and "
                      f"stakes at the scale of {_scope['subject']} - no larger, no smaller.")
    prompt = f"""Create a D&D Discovery mission plan as JSON only.
Mission: {mission.get('title', 'Discovery')}
Mission canon that must be preserved: {mission_context}
Discovery type: {dtype} - {DISCOVERY_TYPES[dtype]}{scope_note}
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
    data = None
    for attempt in range(3):
        raw = await _ollama(prompt)
        data = _parse_json(raw)
        if data:
            break
        logger.warning(f"[DISCOVERY] LLM returned no usable plan (attempt {attempt + 1}/3) for '{mission.get('title', 'Discovery')}'")
        await asyncio.sleep(2)
    if not data:
        logger.warning("[DISCOVERY] LLM unavailable after retries; using mission-faithful fallback")
    return _normalize_plan(data, mission, dtype, context, dcs)


def _fallback_plan(mission: dict, dtype: str, context: Dict[str, Any], dcs: Dict[str, int]) -> Dict[str, Any]:
    mission_context = _mission_context(mission)
    title = mission.get("title", "Discovery")
    canon = ", ".join(mission_context.get("canon_terms", [])[:6]) or title
    object_hint = ", ".join(mission_context.get("objects", [])[:3]) or DISCOVERY_TYPES[dtype]
    if dtype == "ledger":
        scope = _ledger_scope(mission)
        subj = scope["subject"]
        found = f"a ledger holding the recorded history and essence of {subj} the Tower recycled"
        _stake_default = f"custody of the last history of {subj} is contested, and what the Tower erased is no longer secret"
        _imagery = [s.format(subject=subj) for s in IMAGERY_BY_TYPE["ledger"]][:8]
        _implications = [s.format(subject=subj) for s in IMPLICATIONS_BY_TYPE["ledger"]]
        _containment = list(CONTAINMENT_BY_TYPE["ledger"])
        _handling = list(HANDLING_BY_TYPE["ledger"])[:5]
    else:
        found = FOUND_BY_TYPE.get(dtype, f"mission-specific proof involving {object_hint}")
        _stake_default = f"custody and public truth around {title}"
        _imagery = list(IMAGERY_BY_TYPE.get(dtype, IMAGERY_BY_TYPE["object"]))[:8]
        _implications = list(IMPLICATIONS_BY_TYPE.get(dtype, IMPLICATIONS_BY_TYPE["object"]))
        _containment = list(CONTAINMENT_BY_TYPE.get(dtype, CONTAINMENT_BY_TYPE["object"]))
        _handling = list(HANDLING_BY_TYPE.get(dtype, HANDLING_BY_TYPE["object"]))[:5]
    _stakes = mission_context.get("stakes") or [_stake_default]
    stake = _stakes[0]
    return {
        "briefing": f"Identify what {title} really revealed, preserve evidence tied to {canon}, and contain the consequences before rumor or misuse spreads.",
        "opening_read_aloud": (lambda: __import__('src.mission_builder.read_aloud_library', fromlist=['scene_read_aloud']).scene_read_aloud("s1", mission_type=_READ_ALOUD_HINT.get(dtype, "discovery"), contact="the contact", location=context.get('name','')))(),
        "actual_discovery": f"The party recovers {found}; it is tied to {canon}.",
        "proof_standard": f"Success requires two independent signs: physical handling proof from {context.get('name')} and testimony or records tying the find to {canon}.",
        "changed_world_state": f"Once reported, {stake}",
        "surface_description": f"The discovery was found near {context.get('name')} and nobody agrees whether it is safe, legal, alive, or politically explosive.",
        "first_imagery": _imagery,
        "identification_steps": [
            {"step": "Initial Examination", "skill": "Arcana or Investigation", "dc": dcs["identify"], "success": "Confirms the discovery type and rules out mundane causes", "failure": "Triggers a handling quirk — the object reacts unexpectedly"},
            {"step": "Environmental Reading", "skill": "Perception or Nature", "dc": dcs["identify"], "success": "Identifies what materials, energies, or creatures it affects nearby", "failure": "The examiner is briefly affected by a residual property"},
            {"step": "Factional Cross-Reference", "skill": "History or Investigation", "dc": dcs["identify"], "success": "Links the discovery to a known faction, event, or prior incident", "failure": "Produces a false lead; faction involvement seems plausible but wrong"},
            {"step": "Handling Safety Assessment", "skill": "Arcana or Medicine", "dc": dcs["contain"], "success": "Establishes safe handling conditions for transport", "failure": "Reveals a new unstable property — custody becomes more urgent"},
            {"step": "Origin Assessment", "skill": "Arcana or Religion", "dc": dcs["implication"], "success": "Determines where the discovery came from and what it implies about the world", "failure": "The origin remains ambiguous — two contradictory explanations both hold"},
        ],
        "containment_rules": _containment,
        "handling_states": _handling,
        "implication_tree": _implications,
        "faction_claims": _anchored_claims(mission),
        "dialogue": _anchored_dialogue(object_hint),
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
    if isinstance(steps, list) and steps and not all(isinstance(item, dict) for item in steps):
        # LLM returned list of strings — wrap each into a dict
        steps = [{"step": str(s), "skill": "Arcana or Investigation", "dc": dcs["identify"], "success": "Advances identification", "failure": "Triggers a handling complication"} for s in steps if s]
        plan["identification_steps"] = steps if steps else fallback["identification_steps"]
    elif not isinstance(steps, list) or not steps:
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
    def _setup(s: Dict[str, Any]) -> str:
        return s.get("setup") or f"Apply {s.get('skill', 'the relevant skill')} to {str(s.get('step', 'the discovery')).lower()}."
    return "<table><tr><th>Step</th><th>Skill</th><th>Setup</th><th>Success</th><th>Failure</th></tr>" + "".join(f"<tr><td>{_e(s.get('step'))}</td><td>{_e(s.get('skill'))} DC {_e(s.get('dc'))}</td><td>{_e(_setup(s))}</td><td>{_e(s.get('success'))}</td><td>{_e(s.get('failure'))}</td></tr>" for s in steps) + "</table>"


def render_module(mission: dict, dtype: str, context: Dict[str, Any], plan: Dict[str, Any], dcs: Dict[str, int], strength: Dict[str, Any]) -> str:
    title = mission.get("title", "Discovery")
    faction = mission.get("faction", "Wizards Tower")
    fc = _faction_color(faction)
    body = ""
    body += _card("Briefing", f"<p>{_e(plan.get('briefing'))}</p><p>{_e(_party_note(strength))}</p>", fc)
    if plan.get("opening_read_aloud"):
        body += _card("Read Aloud — First Encounter", f'<div style="font-style:italic;color:#333;">{_e(plan["opening_read_aloud"])}</div>', "#8a5a1f")
    body += _card("Actual Discovery", f"<p><strong>Discovery:</strong> {_e(plan.get('actual_discovery'))}</p><p><strong>Proof:</strong> {_e(plan.get('proof_standard'))}</p><p><strong>Changed World-State:</strong> {_e(plan.get('changed_world_state'))}</p>", "#2a6a2a")
    if dtype == "ledger":
        _scope = _ledger_scope(mission)
        _val = _ledger_value(mission, _scope)
        body += _card("Scope & Worth", f"<p><strong>Records:</strong> {_e(_scope['label'])}.</p><p><strong>Appraised worth:</strong> {_e(_val['worth'])} (about {_val['ec']:,} EC, plus {_val['kharma']} Kharma to the right buyer).</p><p>A ledger is worth as much as what it remembers: the story of a single well is a curio; the chronicle of a star system is priceless and worth killing for.</p>", "#6a3da0")
    body += _card("Surface Description", f"<p>{_e(plan.get('surface_description'))}</p><p><strong>Context:</strong> {_e(context.get('name'))} - {_e(context.get('district'))}</p>", "#8a5a1f")
    body += _card("Imagery", _ul(plan.get("first_imagery", [])), "#555")
    body += _card("Identification Logic", _step_table(plan.get("identification_steps", [])), "#3a6898")
    body += _card("Containment Sheet", _ul(plan.get("containment_rules", [])) + "<h3>Handling States</h3>" + _ul(plan.get("handling_states", [])), "#7b1e1e")
    body += _card("Implication Tree", _ul(plan.get("implication_tree", [])), "#2a6a2a")
    body += _card("Faction Custody Claims", _ul(plan.get("faction_claims", [])), "#8a5a1f")
    body += _card("Dialogue", _ul(plan.get("dialogue", [])), "#555")
    body += _card("Fate Options", _ul(plan.get("fate_options", [])) + f"<p><strong>Follow-up:</strong> {_e(plan.get('follow_up'))}</p>", "#2a6a2a")
    from src.treasure import loot_card as _loot_card
    body += _loot_card(mission)
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
    from src.mission_builder.mimir_module import create_module as _mc, render_mimir_section as _ms, push_documents as _mpd, enrich_mission_loot as _mel
    _mimir_id = await _mc(mission, mission_type="discovery")
    _html = render_module(mission, dtype, context, plan, dcs, strength)
    _loot_rewards = await _mel(_mimir_id or "", mission)
    _html += _ms([], _loot_rewards, _mimir_id or "")
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
    # Pull a site or scene map from the library
    _disc_maps: list = []
    try:
        from src.battle_map_library import copy_library_map_for_mission
        from src.mission_builder.html_renderer import render_maps_page
        _disc_lib = copy_library_map_for_mission(
            mission, out_dir / "maps" / "discovery_site.png",
            mission_type="discovery", map_type="interior",
        )
        if _disc_lib:
            _disc_maps = [_disc_lib]
            (out_dir / "maps.html").write_text(
                render_maps_page(title, faction, _disc_maps, "{}"), encoding="utf-8"
            )
    except Exception as _disc_me:
        logger.warning(f"[DISCOVERY] Library map failed: {_disc_me}")

    from src.mission_builder.html_renderer import render_index
    index_html = render_index(title, faction, tier, mission_cr(mission), mission.get("player_name", "") or "Open", [], component_links(bool(_disc_maps)), None, len(_disc_maps))
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    try:
        from src.mission_builder.mission_db import write_module_slug_for_mission
        write_module_slug_for_mission(mission, out_dir.name, log_prefix="DISCOVERY")
    except Exception as e:
        logger.warning(f"[DISCOVERY] Could not write module_slug: {e}")
    with zipfile.ZipFile(out_dir.parent / f"{out_dir.name}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))
    return index_path
