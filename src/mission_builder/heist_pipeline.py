"""
heist_pipeline.py - Heist / robbery mission modules.

Heist jobs are only offered by shady factions. The party is hired to acquire,
swap, plant, copy, or recover a valuable target through planning, security
bypass, controlled chaos, and escape. This is not generic infiltration: the
objective is the take, the heat, and getting out before the city knows who did it.

Exported:
    build_heist_module(mission: dict, out_dir: Path) -> Path
    is_heist_mission(mission_type: str, faction: str = "") -> bool
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

_HEIST_KEYWORDS = {
    "heist", "robbery", "rob", "steal", "theft", "thief", "smash and grab",
    "smash-and-grab", "vault", "bank job", "bank robbery", "museum theft",
    "museum heist", "auction theft", "score", "take the", "lift the",
    "crack the vault",
}

SHADY_FACTIONS = {
    "Obsidian Lotus",
    "Iron Fang Consortium",
    "Glass Sigil",
    "Argent Blades",
    "Serpent Choir",
    "Brother Thane's Cult",
}

SUBTYPES = {
    "smash_grab": {
        "label": "Smash-and-Grab",
        "tempo": "fast and loud",
        "map_prompt": "Town Interior and Exterior Table Map, storefront smash and grab, front room, locked display, back office, street escape route, bystanders, objects",
    },
    "bank_robbery": {
        "label": "Bank Robbery",
        "tempo": "controlled public chaos",
        "map_prompt": "Interior Objects Table Map, fantasy bank lobby, teller counters, vault door, manager office, public floor, side exits, security choke points, objects",
    },
    "underground_vault": {
        "label": "Underground Vault Heist",
        "tempo": "planned breach",
        "map_prompt": "Dungeon Interior Objects Table Map, underground vault complex, tunnels, warded vault door, guard stations, trap corridors, treasure room, escape shafts, objects",
    },
    "museum_swap": {
        "label": "Museum / Gallery Item Swap",
        "tempo": "clean hands and perfect timing",
        "map_prompt": "Interior Objects Table Map, museum gallery, display cases, curator office, exhibit halls, staff corridor, loading exit, security routes, objects",
    },
    "auction_house": {
        "label": "Auction House / Casino Score",
        "tempo": "social pressure and hidden theft",
        "map_prompt": "Interior Objects Table Map, auction hall casino floor, public tables, private bidding room, item display, cashier cage, VIP rooms, service exits, objects",
    },
    "archive_theft": {
        "label": "Archive / Ledger Theft",
        "tempo": "quiet extraction",
        "map_prompt": "Interior Objects Table Map, archive library records office, shelves, reading room, restricted stacks, clerk desk, secure document room, service stairs, objects",
    },
    "caper_jewel": {
        "label": "Elegant Jewel / Relic Caper",
        "tempo": "polished misdirection",
        "map_prompt": "Interior Objects Table Map, luxury hotel gallery gala room jewel display, service corridors, balcony, private salon, security office, exits, objects",
    },
    "noir_object": {
        "label": "Noir Object Chase",
        "tempo": "everyone wants the same cursed little thing",
        "map_prompt": "Town Exterior Objects Table Map, smoky office back room pawn shop private booth, alleys, hidden safe, rain-slick street exit, objects",
    },
    "train_score": {
        "label": "Train / Transit Heist",
        "tempo": "moving locked-room pressure",
        "map_prompt": "Interior Objects Table Map, fantasy train cars, passenger carriage, cargo carriage, dining car, private compartment, roof access, coupling points, narrow movement, objects",
    },
}

OBJECTIVE_ACTIONS = ["steal", "swap", "plant", "copy", "recover before another crew", "destroy after acquisition"]

SECURITY_LAYERS = [
    ("Outer Eyes", "watchers, clerks, staff, public witnesses, or bored guards"),
    ("Access Control", "locks, credentials, passphrases, social checks, delivery papers"),
    ("Detection", "wards, pressure plates, ledger audits, weight sensors, curious staff"),
    ("Response", "guards, private security, faction crew, alarm bells, sealed exits"),
    ("Aftermath Heat", "TNN rumor, formal complaint, bounty, assigned watcher, faction retaliation"),
]

CASING_QUESTIONS = [
    ("What is the target's true value?", "Appraisal, History, Arcana, Religion, or street gossip can reveal why the sponsor really wants it."),
    ("Who touches the target daily?", "Staff, guards, couriers, cleaners, clerks, and curators make better access points than locked doors."),
    ("What changes during shift change?", "Patrol timing, ward refresh, ledger handoff, delivery windows, and distracted managers."),
    ("Where does public traffic become private space?", "The best breach point is often a threshold, not a wall."),
    ("What is the quietest exit?", "The way out matters more than the way in once the score is moving."),
    ("Who benefits if the party gets blamed?", "A clean sponsor may still want a dirty crew framed."),
    ("What does security protect badly?", "Cheap locks, bored staff, forgotten windows, vanity displays, or old service doors."),
    ("What does security protect too well?", "Overbuilt security may hide a second, more important target nearby."),
    ("Who is pretending not to watch?", "The real watcher is often dressed as staff, guest, passenger, reporter, or drunk."),
    ("What is the alarm nobody thinks about?", "Screaming bystander, angry noble, curious child, divine omen, or automated ledger audit."),
]

PLANNING_CLOCK = [
    ("Case the joint", "Learn layout, public rhythm, likely score location, and one weakness."),
    ("Acquire cover", "Uniforms, tickets, false invitations, delivery papers, forged seals, or social alibi."),
    ("Neutralize one layer", "Bypass one lock, guard, ward, witness, clerk, inspector, or camera-equivalent."),
    ("Move the score", "Steal, swap, copy, plant, or destroy the objective."),
    ("Escape clean", "Leave before alarm, redirect heat, or survive pursuit."),
]

CREW_ASSETS = [
    "forged staff papers",
    "borrowed delivery cart",
    "bribed night clerk",
    "replica case with the same weight",
    "one-use silence charm",
    "borrowed noble invitation",
    "stolen maintenance uniform",
    "fake TNN press badge",
    "smoke bead",
    "tiny tracker to plant on the real owner",
    "arcane chalk that marks ward lines",
    "folding crowbar disguised as a cane",
    "sympathetic servant contact",
    "inside floor sketch",
    "fake emergency order",
]

MARK_TYPES = [
    "vain collector who loves being flattered",
    "bank manager hiding personal debt",
    "curator who believes the object belongs elsewhere",
    "auctioneer who knows the item is not what the catalog says",
    "security captain paid to look competent, not actually be competent",
    "retired adventurer guard who recognizes tricks",
    "noble guest with a gambling problem",
    "Tower Authority inspector making everything worse",
    "Obsidian Lotus watcher who may be protecting the same score",
    "Iron Fang broker counting profit while pretending neutrality",
    "Glass Sigil patron using the event as leverage",
    "train conductor who knows every locked compartment",
]

SECURITY_ARCHETYPES = [
    ("Professional", "disciplined patrols, boring procedures, reliable response"),
    ("Vanity Security", "flashy guards, visible deterrents, weak back rooms"),
    ("Arcane Lockdown", "wards, key sigils, alarm glyphs, unstable dispel consequences"),
    ("Social Gatekeeping", "guest lists, introductions, status checks, gossip traps"),
    ("Debt-Ridden Staff", "bribable, scared, and likely to panic at the wrong moment"),
    ("Counter-Heist Prepared", "bait displays, hidden watchers, decoy vaults, marked exits"),
    ("Transit Security", "narrow movement, moving jurisdiction, timed station stops"),
    ("Cultic Custody", "ritual taboos, sacred watchers, symbolic traps, zealot witnesses"),
]

TARGET_ODDITIES = [
    "it is heavier than it should be",
    "it whispers names when uncovered",
    "it is a decoy but still valuable",
    "it has a legal owner and a moral owner",
    "it is only valuable at a specific hour",
    "it records whoever touches it",
    "it is part of a larger mechanism",
    "it cannot cross running water",
    "it has a matching twin somewhere else",
    "it is worthless unless paired with a ledger entry",
    "it is fake, but the fake is the thing the sponsor really wants",
    "it is alive enough to object",
]

RIVAL_CREWS = [
    "quiet Obsidian Lotus pair already inside",
    "Iron Fang repo crew with legal-looking paperwork",
    "Glass Sigil social thieves pretending to be patrons",
    "Argent Blades professionals hired as 'security consultants'",
    "Patchwork Saints locals trying to steal it first for a good cause",
    "fake adventurer party from the party_profiles table if available",
    "solo thief with better style than judgment",
    "TNN stringer who thinks this is investigative journalism",
]

WITNESS_PROBLEMS = [
    "child saw everything and thinks it is a game",
    "drunk noble remembers one exact detail and nothing useful around it",
    "janitor notices shoes, not faces",
    "guard lies to hide sleeping on duty",
    "guest recognizes a PC from a previous mission",
    "reporter records the wrong moment at the right angle",
    "staff member wants to be bribed after the fact",
    "someone confesses to a different crime mid-heist",
]

ESCAPE_TWISTS = [
    "the planned exit is full of inspectors",
    "the getaway cart is real but belongs to someone else",
    "a sewer route floods at the worst time",
    "the train reaches the next station early",
    "street gates seal because of an unrelated incident",
    "the quiet exit leads through an occupied kitchen",
    "the decoy crew runs the wrong direction",
    "the score attracts pursuit by sound, scent, magic, or memory",
    "the crowd starts cheering for the wrong people",
    "the sponsor's pickup changes location mid-job",
]

HEAT_FALLOUT = [
    "formal complaint filed with Tower Authority",
    "assassin or watcher assigned to observe the party",
    "TNN hints the party was nearby",
    "target owner hires Argent Blades recovery specialists",
    "Glass Sigil turns suspicion into blackmail",
    "Iron Fang posts a quiet market penalty",
    "Obsidian Lotus sends a polite warning",
    "Patchwork Saints shelter a witness the party needs",
    "bounty appears under a deniable name",
    "future heist security increases by one layer",
]

TRAIN_CAR_OPTIONS = [
    "passenger car full of witnesses",
    "private sleeper with one lying occupant",
    "dining car during service rush",
    "cargo car with chained crates",
    "guard car with narrow line of sight",
    "roof path between tunnels",
    "engine access with crew-only rules",
    "station platform handoff window",
    "coupling point that can split the train",
    "baggage car with too many identical trunks",
]

HEAT_TRACK = [
    ("Cold", "No one knows the party was involved."),
    ("Warm", "Someone knows a crime happened, but the crew is clean."),
    ("Hot", "The party is suspected or a witness saw too much."),
    ("Burned", "The party is identified; complaints, bounties, or retaliation begin."),
    ("Inferno", "A faction makes an example of somebody."),
]

COMPLICATIONS = [
    "another crew is already inside",
    "the target is a fake and the real score moved earlier",
    "a bystander recognizes one PC",
    "the target is cursed, awake, or emotionally loaded",
    "security is weaker than expected because the real trap is after extraction",
    "the sponsor lied about who owns the target",
    "TNN is nearby covering an unrelated story",
    "the target has a hidden tracker",
    "an Obsidian Lotus counter-ambush is watching the ambushers",
    "the vault opens cleanly, but something inside wants out",
    "a famous inspector is on site for an unrelated reason",
    "three different crews are chasing the same tiny priceless object",
    "the train keeps moving and the next station changes who has jurisdiction",
    "everyone trapped in the same transit car has a motive",
]

STYLE_INFLUENCES = [
    "Ocean's 11 crew choreography",
    "Pink Panther jewel-caper elegance",
    "Maltese Falcon noir object obsession",
    "Orient Express train / locked-room suspicion",
    "Tower of Last Chance faction weirdness",
]

ESCAPE_PRESSURES = [
    "sealed street gates",
    "crowd panic",
    "service tunnels",
    "rooftop route",
    "canal / sewer exit",
    "bribed cart pickup",
    "chase through back rooms",
    "decoy crew splits attention",
    "public hostage misunderstanding",
    "silent exit before anyone notices",
]

OUTCOMES = [
    ("Clean score", "Target acquired, heat stays cold or warm."),
    ("Messy score", "Target acquired, but heat becomes hot."),
    ("Partial score", "Copy, fragment, decoy, or damaged target acquired."),
    ("Blown job", "No score; party escapes under pressure."),
    ("Double-cross", "Sponsor, rival crew, or target owner changes the job after success."),
]


def is_heist_mission(mission_type: str, faction: str = "") -> bool:
    low = (mission_type or "").lower()
    if not any(k in low for k in _HEIST_KEYWORDS):
        return False
    if not faction:
        return True
    return _is_shady(faction)


def _is_shady(faction: str) -> bool:
    low = (faction or "").lower()
    return any(name.lower() in low for name in SHADY_FACTIONS)


def _db_rows(query: str, params: tuple = ()) -> List[Dict]:
    try:
        from src.db_api import raw_query
        return raw_query(query, params) or []
    except Exception as e:
        logger.warning(f"[HEIST] DB read failed: {e}")
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
    rows = _db_rows("SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC")
    pcs = []
    for row in rows:
        snap = _json_col(row.get("snapshot_json"), {})
        if not isinstance(snap, dict):
            continue
        level = int(snap.get("total_level") or snap.get("level") or 0)
        if level <= 0:
            continue
        pcs.append({"name": snap.get("name") or row.get("char_name"), "level": level, "max_hp": int(snap.get("max_hp") or 0)})
    levels = [p["level"] for p in pcs] or [5]
    return {"party_size": len(pcs) or 4, "avg_level": round(sum(levels) / len(levels), 1), "max_level": max(levels), "pcs": pcs, "security_level": max(levels) + 4}


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    return f"Live party read: {strength['party_size']} PCs, average level {strength['avg_level']}, max level {strength['max_level']}; heist security may scale to party +4 (security level {strength['security_level']})."


def _factions() -> List[Dict]:
    rows = _db_rows("SELECT faction_name, reputation_score, tier, description FROM faction_reputation ORDER BY faction_name")
    return rows or [{"faction_name": "Obsidian Lotus"}, {"faction_name": "Iron Fang Consortium"}, {"faction_name": "Glass Sigil"}]


def _canon(name: str, factions: List[Dict]) -> str:
    raw = (name or "").strip()
    low = raw.lower()
    for row in factions:
        fname = row.get("faction_name") or ""
        if low and (low == fname.lower() or low in fname.lower() or fname.lower() in low):
            return fname
    return raw


def _resolve_roles(mission: dict) -> Dict[str, str]:
    factions = _factions()
    sponsor = _canon(mission.get("faction") or "", factions)
    if not _is_shady(sponsor):
        shady = [f.get("faction_name") for f in factions if _is_shady(f.get("faction_name", ""))]
        sponsor = random.choice(shady or sorted(SHADY_FACTIONS))
    target_owner = _canon(mission.get("opposing_faction") or mission.get("target_faction") or "", factions)
    if not target_owner or target_owner == sponsor:
        choices = [f.get("faction_name") for f in factions if f.get("faction_name") and f.get("faction_name") != sponsor]
        target_owner = random.choice(choices or ["private owner"])
    return {"sponsor": sponsor, "target_owner": target_owner}


def _pick_subtype(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    if "smash" in text or "grab" in text:
        return "smash_grab"
    if "bank" in text:
        return "bank_robbery"
    if "vault" in text or "underground" in text:
        return "underground_vault"
    if "museum" in text or "gallery" in text or "swap" in text:
        return "museum_swap"
    if "auction" in text or "casino" in text:
        return "auction_house"
    if "archive" in text or "ledger" in text or "record" in text:
        return "archive_theft"
    if "jewel" in text or "relic caper" in text or "panther" in text:
        return "caper_jewel"
    if "falcon" in text or "noir" in text:
        return "noir_object"
    if "train" in text or "transit" in text or "orient" in text:
        return "train_score"
    return random.choice(list(SUBTYPES.keys()))


def _pick_target(subtype: str, roles: Dict[str, str]) -> Dict[str, str]:
    if subtype in ("auction_house", "museum_swap"):
        rows = _db_rows("SELECT item_name, seller_name, current_bid, buy_now_price, status FROM towerbay_auctions WHERE status <> 'sold' ORDER BY RAND() LIMIT 1")
        if rows:
            r = rows[0]
            return {"name": r.get("item_name"), "source": "towerbay_auctions", "detail": f"seller: {r.get('seller_name')}; bid: {r.get('current_bid')}; buy-now: {r.get('buy_now_price')}; status: {r.get('status')}"}
    if subtype in ("smash_grab", "bank_robbery"):
        rows = _db_rows("SELECT item_name, player_name, asking_price, status FROM player_listings WHERE status <> 'sold' ORDER BY RAND() LIMIT 1")
        if rows:
            r = rows[0]
            return {"name": r.get("item_name"), "source": "player_listings", "detail": f"listed by: {r.get('player_name')}; asking: {r.get('asking_price')}; status: {r.get('status')}"}
    if subtype in ("underground_vault", "archive_theft"):
        rows = _db_rows("SELECT sector, value, trend FROM tia_market ORDER BY RAND() LIMIT 1")
        if rows:
            r = rows[0]
            return {"name": f"{r.get('sector') or 'Market'} ledger / reserve", "source": "tia_market", "detail": f"value: {r.get('value')}; trend: {r.get('trend')}"}
    if subtype in ("caper_jewel", "noir_object", "train_score"):
        rows = _db_rows("SELECT item_name, seller_name, current_bid, buy_now_price, status FROM towerbay_auctions ORDER BY RAND() LIMIT 1")
        if rows:
            r = rows[0]
            return {"name": r.get("item_name"), "source": "towerbay_auctions", "detail": f"seller: {r.get('seller_name')}; bid: {r.get('current_bid')}; buy-now: {r.get('buy_now_price')}; status: {r.get('status')}"}
    return {"name": random.choice(["sealed memory case", "black ledger", "vault relic", "payment lockbox", "soul-vial packet", "auction lot"]), "source": "generated fallback", "detail": f"belongs to or implicates {roles['target_owner']}"}


def _pick_location(subtype: str) -> Dict[str, str]:
    hints = {
        "smash_grab": "shop",
        "bank_robbery": "bank",
        "underground_vault": "vault",
        "museum_swap": "gallery",
        "auction_house": "auction",
        "archive_theft": "archive",
        "caper_jewel": "hotel",
        "noir_object": "office",
        "train_score": "train",
    }
    hint = hints.get(subtype, "")
    rows = _db_rows(
        "SELECT name, district, place_type, description FROM gazetteer_places WHERE LOWER(name) LIKE %s OR LOWER(description) LIKE %s OR LOWER(place_type) LIKE %s ORDER BY RAND() LIMIT 1",
        (f"%{hint}%", f"%{hint}%", f"%{hint}%"),
    )
    if not rows:
        rows = _db_rows("SELECT name, district, place_type, description FROM gazetteer_places ORDER BY RAND() LIMIT 1")
    if rows:
        r = rows[0]
        return {"name": r.get("name") or "Target Site", "district": r.get("district") or "Unknown District", "type": r.get("place_type") or "site", "description": r.get("description") or "A valuable site with security and escape problems."}
    return {"name": "Target Site", "district": "Unknown District", "type": "site", "description": "A valuable site with security and escape problems."}


def _crew_roles(strength: Dict[str, Any]) -> List[str]:
    return [
        "Face / distraction",
        "Lock or ward breaker",
        "Lookout",
        "Muscle / crowd control",
        "Inside hand",
        "Driver / escape lead",
        "Evidence cleaner",
    ][: max(4, min(7, strength.get("party_size", 4)))]


def _pick_heist_options(subtype: str, strength: Dict[str, Any]) -> Dict[str, Any]:
    role_count = max(4, min(7, strength.get("party_size", 4)))
    options = {
        "casing_questions": random.sample(CASING_QUESTIONS, 5),
        "planning_clock": PLANNING_CLOCK,
        "crew_assets": random.sample(CREW_ASSETS, min(role_count + 2, len(CREW_ASSETS))),
        "marks": random.sample(MARK_TYPES, 4),
        "security_archetypes": random.sample(SECURITY_ARCHETYPES, 3),
        "target_oddities": random.sample(TARGET_ODDITIES, 3),
        "rival_crews": random.sample(RIVAL_CREWS, 2),
        "witness_problems": random.sample(WITNESS_PROBLEMS, 3),
        "escape_twists": random.sample(ESCAPE_TWISTS, 3),
        "heat_fallout": random.sample(HEAT_FALLOUT, 4),
        "train_cars": random.sample(TRAIN_CAR_OPTIONS, 6) if subtype == "train_score" else [],
    }
    return options


async def _ollama(prompt: str, system: str = "", tokens: int = 1400) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": OLLAMA_MODEL, "messages": messages, "stream": False, "options": {"temperature": 0.84, "num_predict": tokens}}
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("heist_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[HEIST] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[HEIST] Ollama error: {e}")
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


def _fallback_plan(
    roles: Dict[str, str],
    target: Dict[str, str],
    location: Dict[str, str],
    options: Dict[str, Any],
    action: str,
    complication: str,
) -> Dict[str, Any]:
    return {
        "briefing": f"{roles['sponsor']} wants {target['name']} out of {location['name']}. They do not care how pretty it looks, only that the score lands and the crew does not drag the sponsor into the light.",
        "score": f"{action} {target['name']}",
        "site_description": f"{location['name']} is a {location['type']} in {location['district']}. {location['description']}",
        "opening_read_aloud": f"{location['name']} sits at the edge of {location['district']} — {location.get('description', 'a building that does not invite attention')}. From the outside it looks like any other address. The party knows better.",
        "security_plan": [f"{a}: {b}" for a, b in SECURITY_LAYERS],
        "casing_opportunities": [f"{q}: {note}" for q, note in options["casing_questions"]],
        "crew_assets": options["crew_assets"],
        "key_marks": options["marks"],
        "rival_pressure": random.choice(options["rival_crews"]),
        "target_oddity": random.choice(options["target_oddities"]),
        "approach_options": ["social cover", "silent entry", "arcane bypass", "brute-force timing", "inside distraction"],
        "alarm_trigger": "wrong item weight, broken ward, witness panic, or a guard reaching the alarm pull.",
        "escape_options": random.sample(ESCAPE_PRESSURES, 4),
        "heat_fallout": options["heat_fallout"],
        "complication": complication,
        "double_cross": "None unless the table wants the sponsor to change terms after the score.",
        "debrief": "Clean work earns quiet respect. Messy work gets paid but watched. Failure may turn the crew into a liability.",
    }


def _normalize_plan(
    data: Optional[dict],
    roles: Dict[str, str],
    target: Dict[str, str],
    location: Dict[str, str],
    options: Dict[str, Any],
    action: str,
    complication: str,
) -> Dict[str, Any]:
    fallback = _fallback_plan(roles, target, location, options, action, complication)
    if not isinstance(data, dict):
        return fallback

    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    for key in (
        "security_plan",
        "casing_opportunities",
        "crew_assets",
        "key_marks",
        "approach_options",
        "escape_options",
        "heat_fallout",
    ):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    return plan


async def _generate_plan(mission: dict, subtype: str, roles: Dict[str, str], target: Dict[str, str], location: Dict[str, str], strength: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    action = random.choice(OBJECTIVE_ACTIONS)
    complication = random.choice(COMPLICATIONS)
    prompt = f"""Write a D&D heist / robbery mission module plan.

Mission: {mission.get('title', 'Heist')}
Mission notes: {(mission.get('body') or mission.get('description') or '')[:350]}
Subtype: {SUBTYPES[subtype]['label']} ({SUBTYPES[subtype]['tempo']})
Shady sponsor: {roles['sponsor']}
Target owner / victim faction: {roles['target_owner']}
Objective action: {action}
Target: {target['name']} - {target['detail']}
Location: {location['name']} in {location['district']} - {location['description']}
Live party: {strength['party_size']} PCs, avg level {strength['avg_level']}, max {strength['max_level']}
Complication seed: {complication}
Style influences: {", ".join(STYLE_INFLUENCES)}
Rolled heist option bank:
- Casing questions: {json.dumps(options["casing_questions"], ensure_ascii=False)[:900]}
- Crew assets: {json.dumps(options["crew_assets"], ensure_ascii=False)}
- Marks: {json.dumps(options["marks"], ensure_ascii=False)}
- Security archetypes: {json.dumps(options["security_archetypes"], ensure_ascii=False)}
- Target oddities: {json.dumps(options["target_oddities"], ensure_ascii=False)}
- Rival crews: {json.dumps(options["rival_crews"], ensure_ascii=False)}
- Witness problems: {json.dumps(options["witness_problems"], ensure_ascii=False)}
- Escape twists: {json.dumps(options["escape_twists"], ensure_ascii=False)}
- Heat fallout: {json.dumps(options["heat_fallout"], ensure_ascii=False)}
- Train cars, if relevant: {json.dumps(options["train_cars"], ensure_ascii=False)}

Rules:
- Heist jobs are only offered by shady factions.
- The objective is the score and the escape.
- Include planning, security layers, alarm/heat pressure, and escape.
- Allow loud, stealthy, social, magical, scam-based, and brute-force approaches.
- Support elegant jewel caper, noir object chase, and train/locked-room suspicion when the subtype calls for it.
- The party can make a clean score, messy score, partial score, blown job, or get double-crossed.

Return JSON only:
{{
  "briefing": "2-3 paragraphs from the shady contact",
  "score": "what the party is taking/swapping/planting/copying",
  "site_description": "2-3 sentences",
  "opening_read_aloud": "2-3 sentences, present tense, sensory — what the party first sees and hears when they arrive at or near the target site for the first time (before going in)",
  "security_plan": ["5 security details"],
  "casing_opportunities": ["5 casing opportunities/questions"],
  "crew_assets": ["4-7 useful assets or prep options"],
  "key_marks": ["3-4 marks/security personalities/witnesses"],
  "rival_pressure": "rival crew or inspector pressure",
  "target_oddity": "specific weird/valuable problem with the score",
  "approach_options": ["5 approaches"],
  "alarm_trigger": "what makes the job go loud",
  "escape_options": ["4 escape options"],
  "heat_fallout": ["3-4 aftermath heat consequences"],
  "complication": "specific complication",
  "double_cross": "optional double-cross or none",
  "debrief": "how sponsor reacts by clean/messy/failure result"
}}"""
    data = _parse_json(await _ollama(prompt))
    return _normalize_plan(data, roles, target, location, options, action, complication)


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
            logger.info(f"[HEIST] A1111 not ready (attempt {attempt}/10) — waiting 30s…")
            await asyncio.sleep(30)
    logger.warning("[HEIST] A1111 unavailable after 10 attempts")
    return False


async def _generate_map(subtype: str, location: Dict[str, str], out_dir: Path) -> Optional[Path]:
    out = out_dir / "heist_map.png"
    import re
    _raw_style = SUBTYPES[subtype]["map_prompt"]
    is_dungeon = "dungeon" in _raw_style.lower()
    _style = re.sub(r'(?:Big |Small )?(?:[\w]+ )*?Table Map[, ]+', '', _raw_style, count=1, flags=re.IGNORECASE).strip(', ')
    lora_name = os.getenv("A1111_MAP_LORA_DUNGEON" if is_dungeon else "A1111_MAP_LORA_TOWN",
                           "EnvyFluxDungeonMap01" if is_dungeon else "EnvyFluxFantasyTownMap01")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    triggers = os.getenv("A1111_MAP_DUNGEON_TRIGGERS" if is_dungeon else "A1111_MAP_TOWN_TRIGGERS",
                          "detailed, map, dungeon" if is_dungeon else "detailed, map, village")
    loc_desc = (location.get("description") or "")[:200]
    parts = [
        f"<lora:{lora_name}:{lora_weight}>",
        triggers,
        _style,
        f"location: {location['name']} in {location['district']}",
        loc_desc,
        "security zones, objective room, alarm point, escape routes, cover, objects",
        "high fantasy cyberpunk fusion, wealth-stratified technology",
    ]
    prompt = ", ".join(p for p in parts if p)
    payload = {"prompt": prompt, "negative_prompt": "characters, people, isometric, perspective, watermark, text", "width": 1024, "height": 1024, "steps": 20, "cfg_scale": 1.0, "sampler_name": "Euler", "seed": -1}
    _map_ckpt = os.getenv("A1111_MAP_CHECKPOINT", "")
    if _map_ckpt:
        override: dict = {"sd_model_checkpoint": _map_ckpt}
        payload["override_settings"] = override
        payload["override_settings_restore_afterwards"] = True
    from src.news_feed import a1111_lock
    from src.resource_cop import wait_for_a1111_turn
    from src.mission_builder.vtt_renderer import save_vtt_battlemap
    _map_ctx = {"title": location.get("name"), "location": location, "prompt": prompt, "kind": "heist interior vault"}
    for map_attempt in range(1, 11):
        try:
            decision = await wait_for_a1111_turn("heist_map", max_wait_seconds=60)
            if not decision.run_now:
                logger.info(f"[HEIST] A1111 deferred by resource cop: {decision.reason}")
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
            logger.warning(f"[HEIST] Map generation attempt {map_attempt}/10 failed: {e}")
            if map_attempt < 10:
                backoff = min(30 * map_attempt, 120)
                logger.info(f"[HEIST] Retrying map in {backoff}s…")
                await asyncio.sleep(backoff)
    logger.error("[HEIST] Map generation failed after 10 attempts — using deterministic fallback")
    save_vtt_battlemap(out, None, context=_map_ctx)
    return out


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


def _checkbox_list(items: List[Any]) -> str:
    return "<ul>" + "".join(f"<li><input type='checkbox'> {_e(i)}</li>" for i in items) + "</ul>"


def _tuple_table(rows: List[tuple]) -> str:
    return _table([(a, b) for a, b in rows])


def _map_html(path: Optional[Path], out_dir: Path, fc: str, dm: bool) -> str:
    points = [
        ("E", "entry / casing point", 15, 78, "#3a6898"),
        ("S", "security layer", 38, 55, "#b8923a"),
        ("O", "score / objective", 62, 32, "#7b1e1e"),
        ("A", "alarm / response", 76, 48, "#8a5a1f"),
        ("X", "escape route", 86, 18, "#2a6a2a"),
    ]
    if not path or not path.exists():
        return "<ul>" + "".join(f"<li><strong>{_e(a)}</strong> - {_e(b)}</li>" for a, b, *_ in points) + "</ul>"
    rel = path.relative_to(out_dir)
    markers = ""
    if dm:
        for label, name, x, y, color in points:
            markers += f'<div title="{_e(name)}" style="position:absolute;left:{x}%;top:{y}%;transform:translate(-50%,-50%);width:30px;height:30px;border-radius:50%;background:{color};color:white;font-weight:bold;display:flex;align-items:center;justify-content:center;border:2px solid white;box-shadow:0 1px 5px #000;">{label}</div>'
    title = "DM Reference Map - score, security, alarm, escape" if dm else "Player Map - heist site"
    return f'<div style="margin:16px 0;"><div style="font-weight:bold;margin-bottom:6px;color:{("#7b1e1e" if dm else fc)};">{title}</div><div style="position:relative;display:inline-block;max-width:100%;"><img src="{rel}" style="max-width:100%;border:3px solid {("#7b1e1e" if dm else fc)};border-radius:8px;" alt="Heist Map">{markers}</div></div>'


def render_heist_module(mission: dict, subtype: str, roles: Dict[str, str], target: Dict[str, str], location: Dict[str, str], plan: Dict[str, Any], strength: Dict[str, Any], options: Dict[str, Any], map_path: Optional[Path], out_dir: Path) -> str:
    title = mission.get("title", "Heist")
    fc = _faction_color(roles["sponsor"])
    body = ""
    body += _card("Shady Availability", f"<p>This mission type should only be offered by shady sponsors. Active sponsor: <strong>{_e(roles['sponsor'])}</strong>.</p>", "#7b1e1e")
    body += _card("Briefing", f'<div style="white-space:pre-line;font-style:italic;">{_e(plan["briefing"])}</div>', fc)
    body += _card("Score", _table([
        ("Subtype", SUBTYPES[subtype]["label"]),
        ("Tempo", SUBTYPES[subtype]["tempo"]),
        ("Style influences", ", ".join(STYLE_INFLUENCES)),
        ("Target", target["name"]),
        ("Target source", target["source"]),
        ("Target detail", target["detail"]),
        ("Owner / victim", roles["target_owner"]),
        ("Site", f"{location['name']} - {location['district']}"),
        ("Score", plan["score"]),
    ]), "#8a5a1f")
    body += _card("Live Party Scaling", f"<p>{_e(_party_scaling_note(strength))}</p>", "#3a6898")
    body += _card("Site", f"<p>{_e(plan['site_description'])}</p>", fc)
    body += _card("Crew Roles", _ul(_crew_roles(strength)), "#555")
    body += _card("Casing Phase", _tuple_table(options["casing_questions"]) + "<p><strong>Rule:</strong> every answer should either create an approach, remove a security layer, or reveal a better escape route.</p>", "#3a6898")
    body += _card("Planning Clock", _table(options["planning_clock"]) + "<p>Use this as a progress track, not a railroad. The party can skip steps, but skipped steps should increase heat or uncertainty.</p>", "#8a5a1f")
    body += _card("Crew Assets / Prep Options", _checkbox_list(plan.get("crew_assets") or options["crew_assets"]), "#555")
    body += _card("Marks, Staff, And Social Pressure", _ul(plan.get("key_marks") or options["marks"]), "#8a5a1f")
    body += _card("Security Personalities", _table(options["security_archetypes"]), "#7b1e1e")
    body += _card("Target Oddities", _ul([plan.get("target_oddity", "")] + options["target_oddities"]), "#3a6898")
    body += _card("Security Layers", _ul(plan.get("security_plan", [])) + _table(SECURITY_LAYERS), "#7b1e1e")
    body += _card("Approach Options", _ul(plan.get("approach_options", [])), "#3a6898")
    body += _card("Alarm / Heat", _table([("Alarm trigger", plan.get("alarm_trigger", ""))]) + _table(HEAT_TRACK), "#8a5a1f")
    body += _card("Rival Crew / Inspector Pressure", _table([("Rolled pressure", plan.get("rival_pressure") or ", ".join(options["rival_crews"])), ("Other options", "; ".join(options["rival_crews"]))]), "#7b1e1e")
    body += _card("Witness Problems", _ul(options["witness_problems"]), "#555")
    if subtype == "train_score":
        body += _card("Train / Transit Cars", _ul(options["train_cars"]) + "<p>Use station stops as a countdown. Each stop can change jurisdiction, witnesses, or escape options.</p>", "#3a6898")
    body += _card("Map", _map_html(map_path, out_dir, fc, False) + _map_html(map_path, out_dir, fc, True), fc)
    body += _card("Escape", _ul(plan.get("escape_options", [])) + "<h3>Escape Twists</h3>" + _ul(options["escape_twists"]), "#2a6a2a")
    body += _card("Complication / Double-Cross", _table([("Complication", plan.get("complication", "")), ("Double-cross", plan.get("double_cross", ""))]), "#7b1e1e")
    body += _card("Outcomes", _table(OUTCOMES), "#555")
    body += _card("Heat Fallout", _ul(plan.get("heat_fallout") or options["heat_fallout"]) + _ul(HEAT_FALLOUT), "#8a5a1f")
    body += _card("Debrief", f'<p>{_e(plan.get("debrief", ""))}</p><p><strong>Outcome:</strong> <select><option>Clean score</option><option>Messy score</option><option>Partial score</option><option>Blown job</option><option>Double-cross</option></select></p><p><strong>Heat:</strong> <select><option>Cold</option><option>Warm</option><option>Hot</option><option>Burned</option><option>Inferno</option></select></p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Debrief notes..."></textarea>', "#2a6a2a")
    return _page(title, body, roles["sponsor"])


def render_heist_session(mission: dict, subtype: str, roles: Dict[str, str], target: Dict[str, str], plan: Dict[str, Any], strength: Dict[str, Any], options: Dict[str, Any], map_path: Optional[Path], out_dir: Path) -> str:
    title = mission.get("title", "Heist")
    fc = _faction_color(roles["sponsor"])
    approaches = "".join(f'<li><input type="checkbox"> {_e(a)}</li>' for a in plan.get("approach_options", []))
    escapes = "".join(f'<li><input type="checkbox"> {_e(a)}</li>' for a in plan.get("escape_options", []))
    body = f'<h1 style="color:{fc};">{_e(title)}</h1>'
    body += _card("Score", _table([("Sponsor", roles["sponsor"]), ("Subtype", SUBTYPES[subtype]["label"]), ("Target", target["name"]), ("Owner", roles["target_owner"]), ("Party", _party_scaling_note(strength))]), fc)
    body += _card("Map", _map_html(map_path, out_dir, fc, False), fc)
    body += _card("Casing / Prep", _checkbox_list([f"{a}: {b}" for a, b in options["casing_questions"]]) + _checkbox_list(plan.get("crew_assets") or options["crew_assets"]), "#3a6898")
    body += _card("Approach", f"<ul>{approaches}</ul>", "#3a6898")
    body += _card("Alarm / Escape", f"<p><strong>Alarm:</strong> {_e(plan.get('alarm_trigger', ''))}</p><ul>{escapes}</ul>", "#8a5a1f")
    body += _card("Heat / Outcome", '<p><strong>Heat:</strong> <select><option>Cold</option><option>Warm</option><option>Hot</option><option>Burned</option><option>Inferno</option></select></p><p><strong>Outcome:</strong> <select><option>Clean score</option><option>Messy score</option><option>Partial score</option><option>Blown job</option><option>Double-cross</option></select></p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Session notes..."></textarea>', "#7b1e1e")
    return _page(title, body, roles["sponsor"])


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


async def build_heist_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Heist")
    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    strength = _party_strength()
    roles = _resolve_roles(mission)
    subtype = _pick_subtype(mission)
    target = _pick_target(subtype, roles)
    location = _pick_location(subtype)
    options = _pick_heist_options(subtype, strength)

    logger.info(f"[HEIST] Building {title!r} | sponsor={roles['sponsor']} | subtype={subtype}")

    plan = await _generate_plan(mission, subtype, roles, target, location, strength, options)

    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            map_path = await _generate_map(subtype, location, out_dir)
        else:
            logger.warning("[HEIST] A1111 not available - skipping map")

    from src.mission_builder.mimir_module import create_module as _mc, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="heist")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Heist Map")
    module_html = render_heist_module(mission, subtype, roles, target, location, plan, strength, options, map_path, out_dir)
    module_html += _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")
    session_html = render_heist_session(mission, subtype, roles, target, plan, strength, options, map_path, out_dir)
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    dm_md = (
        f"## Heist DM Guide\n"
        f"### Shady Sponsor\n"
        f"- Sponsor: {roles['sponsor']}\n"
        f"- Target owner: {roles['target_owner']}\n"
        f"- Subtype: {SUBTYPES[subtype]['label']}\n"
        f"- Target: {target['name']}\n"
        f"- Location: {location.get('name')} - {location.get('district')}\n\n"
        f"### Security And Secrets\n"
        f"- Alarm trigger: {plan.get('alarm_trigger', '')}\n"
        f"- Complication: {plan.get('complication', '')}\n"
        f"- Double-cross: {plan.get('double_cross', '')}\n"
        f"- Rival pressure: {plan.get('rival_pressure', '')}\n\n"
        f"### Security Plan\n"
        + "\n".join(f"- {s}" for s in plan.get("security_plan", []))
        + f"\n\n### Live Scaling\n{_party_scaling_note(strength)}"
    )
    players_md = (
        f"## Player Brief\n{plan.get('briefing', '')}\n\n"
        f"### Score\n"
        f"- Target: {target['name']}\n"
        f"- Site: {location.get('name')} - {location.get('district')}\n"
        f"- Known owner/security faction: {roles['target_owner']}\n\n"
        f"### Prep Options\n"
        + "\n".join(f"- {a}" for a in (plan.get("crew_assets") or options["crew_assets"]))
        + "\n\nThe party can case, prepare, improvise, and choose the approach."
    )
    chart_md = (
        f"## Heist Chart Pack\n"
        f"### Planning Clock\n"
        + "\n".join(f"| {a} | {b} |" for a, b in options["planning_clock"])
        + "\n\n### Casing Questions\n"
        + "\n".join(f"| {a} | {b} |" for a, b in options["casing_questions"])
        + "\n\n### Security Layers\n"
        + "\n".join(f"| {a} | {b} |" for a, b in SECURITY_LAYERS)
        + "\n\n### Heat Track\n"
        + "\n".join(f"| {a} | {b} |" for a, b in HEAT_TRACK)
        + "\n\n### Outcomes\n"
        + "\n".join(f"| {a} | {b} |" for a, b in OUTCOMES)
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, roles["sponsor"], dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, roles["sponsor"], players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, roles["sponsor"], chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",          "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",               "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Security & Heat Track",  "type": "custom",      "content": chart_md},
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
        logger.warning(f"[HEIST] index.html failed: {e}")
        index_path = out_dir / "module.html"

    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as e:
        logger.warning(f"[HEIST] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[HEIST] Complete: {title!r} -> {out_dir.name}")
    return index_path
