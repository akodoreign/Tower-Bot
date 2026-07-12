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

_HEIST_KEYWORDS = {
    "heist", "robbery", "rob", "steal", "theft", "thief", "smash and grab",
    "smash-and-grab", "vault", "bank job", "bank robbery", "museum theft",
    "museum heist", "smuggling", "smuggle", "contraband", "black market run",
    "auctiontheft", "score", "take the", "lift the",
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


def _failed_recon_heat(roles: Dict[str, str], location: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Read non-consuming failed recon that should harden this heist site."""
    host = roles.get("target_owner", "")
    district = location.get("district", "")
    rows = _db_rows(
        "SELECT * FROM recon_dossiers WHERE outcome = 'failure' "
        "AND (host_faction = %s OR district = %s) "
        "ORDER BY created_at DESC LIMIT 1",
        (host, district),
    )
    if not rows:
        return None
    row = rows[0]
    dossier = _json_col(row.get("dossier_json"), {})
    if isinstance(dossier, dict):
        row["dossier"] = dossier
    return row


def _failed_recon_heat_html(failed_recon: Optional[Dict[str, Any]]) -> str:
    if not failed_recon:
        return ""
    dossier = failed_recon.get("dossier") or {}
    who = failed_recon.get("party_name") or "a prior crew"
    venue = failed_recon.get("venue") or dossier.get("venue") or "this security circle"
    event = failed_recon.get("event_name") or dossier.get("event") or "an earlier infiltration"
    details = failed_recon.get("details") or "The previous attempt failed loudly enough to change procedures."
    return (
        f'<div style="background:#fff0e8;border:1px solid #c85320;border-radius:6px;'
        f'padding:10px 12px;margin:10px 0;font-size:13px;">'
        f'<strong>Heightened security from failed recon:</strong> {_e(who)} was burned at {_e(venue)} during {_e(event)}. '
        f'{_e(details)} Add one extra security layer, make staff challenge repeated casing, and start Heat at Warm instead of Cold.'
        f'</div>'
    )


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


async def _ollama(prompt: str, system: str = "", tokens: int = 1400) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": OLLAMA_MODEL, "messages": messages, "stream": False, "options": {"temperature": 0.84, "num_predict": tokens, "num_ctx": _fit_ctx(system + prompt, tokens)}}
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
        "double_cross": "No double-cross planned — unless the table wants the sponsor to change terms after the score.",
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


async def _generate_map(subtype: str, location: Dict[str, str], out_dir: Path) -> Optional[Path]:
    out = out_dir / "heist_map.png"
    from src.battle_map_library import copy_library_map_for_mission
    return copy_library_map_for_mission(
        {"faction": location.get("faction", "")},
        out,
        mission_type="heist",
        location_name=location.get("name", ""),
        district=location.get("district", ""),
        description=f"{subtype} {location.get('description', '')}",
        map_type="dungeon" if "dungeon" in SUBTYPES[subtype]["map_prompt"].lower() else "office",
    )

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


def _execution_checks(strength: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rogue-leaning execution beats for the heist: the lockpicking/stealth/lift
    spine the job is actually about. DCs scale to party level."""
    base = 12 + max(0, (int(strength.get("avg_level", 5)) - 3) // 2)
    return [
        {"phase": "Infiltrate the approach", "skill": "Stealth", "dc": base,
         "setup": "Slip past the outer watch and reach the first security layer unseen.",
         "success": "The crew reaches the entry point with surprise; the heat track stays clean.",
         "failure": "A guard half-notices -- advance the heat/alarm one step before the job even starts."},
        {"phase": "Beat the entry lock or ward", "skill": "Thieves' Tools (Arcana vs wards)", "dc": base + 1,
         "setup": "Work the lock, glyph, or alarm contact on the way in.",
         "success": "The way opens clean and silent; no trace left at the threshold.",
         "failure": "The mechanism resists or nicks you -- lose a clock tick or trip a soft alarm."},
        {"phase": "Crack the vault or container", "skill": "Sleight of Hand / Thieves' Tools", "dc": base + 2,
         "setup": "Defeat the final container holding the score -- tumblers, seals, or a pressure catch.",
         "success": "The container yields; the prize is in reach with the scene still calm.",
         "failure": "A tumbler slips -- the catch resets, or a fail-safe begins to arm (heat +1)."},
        {"phase": "Lift the target clean", "skill": "Sleight of Hand", "dc": base + 1,
         "setup": "Remove the target without disturbing weight plates, wards, or watching eyes.",
         "success": "The lift is invisible; discovery is delayed well past the exit.",
         "failure": "Something shifts -- a plate, a ward, a witness; the discovery clock starts now."},
        {"phase": "Cover the theft", "skill": "Deception / Sleight of Hand", "dc": base,
         "setup": "Leave a convincing nothing -- a decoy, a reset, or a cool word to a mark.",
         "success": "Buys the crew real time before anyone realises what is gone.",
         "failure": "The cover is thin; the owner or alarm catches on within the hour."},
        {"phase": "Break contact under heat", "skill": "Stealth / Athletics", "dc": base + 2,
         "setup": "Clear the site and shake any pursuit before going to ground.",
         "success": "The crew vanishes into the district; the trail goes cold.",
         "failure": "Pursuit holds -- a chase, a checkpoint, or a witness who can name a face."},
    ]


def _execution_table(beats: List[Dict[str, Any]]) -> str:
    head = (
        '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        '<tr>'
        '<th style="text-align:left;padding:6px 8px;background:#2a2218;color:#e8dcc8;">Phase</th>'
        '<th style="text-align:left;padding:6px 8px;background:#2a2218;color:#e8dcc8;white-space:nowrap;">Check</th>'
        '<th style="text-align:left;padding:6px 8px;background:#2a2218;color:#e8dcc8;">Setup</th>'
        '<th style="text-align:left;padding:6px 8px;background:#2a2218;color:#e8dcc8;">On Success</th>'
        '<th style="text-align:left;padding:6px 8px;background:#2a2218;color:#e8dcc8;">On Failure</th>'
        '</tr>'
    )
    rows = "".join(
        f'<tr style="border-bottom:1px solid #e0d8c0;">'
        f'<td style="padding:6px 8px;font-weight:bold;vertical-align:top;">{_e(b["phase"])}</td>'
        f'<td style="padding:6px 8px;vertical-align:top;white-space:nowrap;">{_e(b["skill"])} DC {b["dc"]}</td>'
        f'<td style="padding:6px 8px;vertical-align:top;">{_e(b["setup"])}</td>'
        f'<td style="padding:6px 8px;vertical-align:top;color:#2a6a2a;">{_e(b["success"])}</td>'
        f'<td style="padding:6px 8px;vertical-align:top;color:#7b1e1e;">{_e(b["failure"])}</td>'
        f'</tr>'
        for b in beats
    )
    return head + rows + "</table>"


# --- Recon dossier: the intel a prior infiltration would have gathered, turned
# --- into known facts so the heist is informed scouting, not a cold approach.
HEIST_PRIZE_SPOTS = [
    "a warded display case on the main floor",
    "a concealed wall-safe behind the owner's desk",
    "the strongroom two levels down",
    "a reliquary niche behind the altar",
    "a locked archive drawer hidden among hundreds of decoys",
    "a private vault that only opens on a timed cycle",
]
HEIST_LAYOUT_NOTES = [
    "one public floor, a staff corridor, and a restricted back wing",
    "a single guarded stair is the only way down to the vault",
    "the prize room has two doors -- one watched, one forgotten",
    "service lifts connect every floor but groan loudly",
    "a central atrium gives sightlines to every balcony",
]
HEIST_MUNDANE_SEC = [
    "{n} guards on a {m}-minute patrol loop",
    "a door warden who checks seals and faces, plus {n} roving guards",
    "a night shift of {n} with a brief blind spot at the {m}-minute shift change",
    "pressure plates on the approaches and {n} guards who answer them",
]
HEIST_ARCANE_SEC = [
    "an alarm glyph on the prize itself (Dispel Magic, or Arcana to suppress it)",
    "a ward that pings if the case opens without the owner's sigil",
    "a chime keyed to forced entry that shatters any Silence",
    "no arcane security at all -- the owner distrusts magic (lucky you)",
]
HEIST_BLIND_WINDOW = [
    "during the change of the guard at the top of the hour",
    "while the owner hosts a gala upstairs",
    "in the dawn lull before the day staff arrive",
    "during a scheduled delivery when the dock doors stand open",
]
HEIST_ENTRY = ["the service entrance behind the kitchens", "a roof skylight over the atrium", "the front door, in plain sight under a cover", "an old coal chute into the cellar", "a shared wall with the building next door"]
HEIST_EXIT = ["back through the service corridor to the canal", "up and over the roofline to the next block", "out the front during the next crowd surge", "down into the maintenance tunnels", "on the delivery cart that leaves on schedule"]
HEIST_RECON_GAPS = [
    "recon could not confirm whether the prize on display is the real one",
    "the owner may have added a guard since the last look",
    "the vault's timed cycle was not fully mapped -- expect a margin of error",
    "one interior door was never opened; what waits behind it is unknown",
]


def _heist_contact(roles: Dict[str, str]) -> Dict[str, str]:
    """A NAMED fence/handler from the sponsor faction who hands over the job."""
    rows = _db_rows(
        "SELECT name, role FROM npcs WHERE status IN ('alive','injured','undead','doppelganger') "
        "AND faction LIKE %s ORDER BY RAND() LIMIT 8",
        (f"%{roles.get('sponsor','')}%",),
    )
    pref = [r for r in rows if any(w in str(r.get("role", "")).lower()
            for w in ("fence", "broker", "fixer", "liaison", "agent", "quartermaster", "handler", "contact"))]
    pick = (pref or rows or [None])[0]
    if pick and pick.get("name"):
        return {"name": pick["name"], "role": pick.get("role") or "fence"}
    return {"name": f"a {roles.get('sponsor','sponsor')} fence", "role": "fence"}


def _recon_dossier(strength: Dict[str, Any], target: Dict[str, str], location: Dict[str, str]) -> Dict[str, str]:
    """The gathered intel (as if a prior infiltration scouted it)."""
    n = max(2, strength.get("party_size", 4) // 2 + 1)
    m = random.choice([10, 15, 20])
    return {
        "prize":   target.get("name", "the score"),
        "where":   random.choice(HEIST_PRIZE_SPOTS),
        "layout":  random.choice(HEIST_LAYOUT_NOTES),
        "mundane": random.choice(HEIST_MUNDANE_SEC).format(n=n, m=m),
        "arcane":  random.choice(HEIST_ARCANE_SEC),
        "window":  random.choice(HEIST_BLIND_WINDOW),
        "entry":   random.choice(HEIST_ENTRY),
        "exit":    random.choice(HEIST_EXIT),
        "gap":     random.choice(HEIST_RECON_GAPS),
    }


def _recon_card_html(recon: Dict[str, str]) -> str:
    return _table([
        ("The score", recon["prize"]),
        ("Where it's kept", recon["where"]),
        ("Layout", recon["layout"]),
        ("Mundane security", recon["mundane"]),
        ("Arcane security", recon["arcane"]),
        ("Blind window", recon["window"]),
        ("Best entry", recon["entry"]),
        ("Best exit", recon["exit"]),
        ("Unconfirmed (the risk)", recon["gap"]),
    ])


def _heist_brief(roles: Dict[str, str], target: Dict[str, str], location: Dict[str, str], contact: Dict[str, str], recon: Dict[str, str]) -> str:
    nights = random.randint(2, 6)
    return (
        f"\"{contact['name']} taps the table. 'The score is {target.get('name','the prize')} -- "
        f"recon puts it in {recon['where']} at {location.get('name','the site')}, {location.get('district','')}. "
        f"{roles.get('target_owner','the owner')} guards it like it matters. Your window is {recon['window']}, "
        f"{nights} nights out. Get in, lift it, leave no name. {roles.get('sponsor','we')} pay clean when it's in my hands -- not before.'\""
    )


# Party-support options for the non-rogue crew (2024 / D&D 5.5e accurate).
HEIST_CREW_SUPPORT = [
    ("Bard -- Bardic Inspiration & misdirection",
     "Bonus action: hand the safecracker a Bardic Inspiration die (d6 at 1st level, d8 at 5th, d10 at 10th, d12 at 15th). They add it to the Thieves' Tools or Sleight of Hand check, and may choose to use it after the d20 is rolled but before the DM announces success. Or pull a guard's attention with a Charisma (Performance) check while the crew slips past."),
    ("Cleric or Druid -- Guidance",
     "Guidance (cantrip, Concentration up to 1 min): the touched ally adds 1d4 to one ability check of their choice. Only one check at a time -- save it for the vault or the lift."),
    ("Druid or Ranger -- Pass Without Trace",
     "2nd-level spell, Concentration up to 1 hour: each chosen creature within 30 ft gains a +10 bonus to Dexterity (Stealth) checks and can't be tracked except by magic. Turns a risky approach and getaway into a clean one (it doesn't stack with a second casting)."),
    ("Wizard -- Silence / Knock / Minor Illusion",
     "Silence (2nd, Concentration): a 20-ft-radius sphere where no sound is created or passes -- drop it over the vault so a snapped pick, a dropped bar, or an alarm bell stays mute (it also blocks Verbal spell components). Knock (2nd): springs one lock or bar instantly, but the boom is audible up to 300 ft (advance Heat). Minor Illusion (cantrip): a sound or a 5-ft image to bait a patrol; a guard who studies it makes an Investigation check vs your spell save DC to disbelieve."),
    ("Sorcerer -- Subtle Spell + Mage Hand / Charm Person",
     "Subtle Spell metamagic (1 sorcery point): cast a spell with no Verbal or Somatic components -- unseen and unheard, even mid-conversation. Pair with Mage Hand (cantrip, 30 ft, up to 10 lb, can't activate magic items) to flip a switch or lift a key from cover, or Charm Person (1st level, Wisdom save) on a lone guard, who realizes they were charmed once it ends."),
    ("Fighter, Barbarian, or anyone -- Help & diversion",
     "Help action (Assist an Ability Check): if you are proficient with the same skill or tool the rogue is using (e.g. Thieves' Tools, Sleight of Hand, or Stealth), they gain Advantage on that check, used before the start of your next turn. Off the clock, a staged commotion -- a 'drunk' argument (Charisma (Deception or Performance)) or a toppled stall (Strength (Athletics)) -- lets the DM pull a guard off the route for a round or two."),
]


def _crew_support_html(options: List[tuple]) -> str:
    return "".join(
        f'<div style="border-left:3px solid #6b3fa0;padding:8px 12px;margin:6px 0;background:#f7f4fc;">'
        f'<div style="font-weight:bold;color:#5a2d8a;">{_e(who)}</div>'
        f'<div style="font-size:13px;margin-top:2px;">{_e(text)}</div></div>'
        for who, text in options
    )


def render_heist_module(mission: dict, subtype: str, roles: Dict[str, str], target: Dict[str, str], location: Dict[str, str], plan: Dict[str, Any], strength: Dict[str, Any], options: Dict[str, Any], map_path: Optional[Path], out_dir: Path, prior_recon: Optional[dict] = None, failed_recon: Optional[dict] = None) -> str:
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
    if failed_recon:
        body += _card("Heightened Security", _failed_recon_heat_html(failed_recon), "#c85320")
    # The chain payoff: a named fence lays out the job, and the recon a prior
    # infiltration would have gathered is already on the table.
    _heist_ct = _heist_contact(roles)
    _heist_recon = _recon_dossier(strength, target, location)
    # If a prior infiltration scouted this mark, build the score on its real result.
    _recon_provenance = ""
    if prior_recon:
        _pd = prior_recon.get("dossier") or {}
        if _pd.get("target"):
            _heist_recon["prize"] = _pd["target"]
        _who = prior_recon.get("party_name") or "a prior crew"
        _ev = _pd.get("event") or prior_recon.get("event_name") or "an earlier job"
        _vn = prior_recon.get("venue") or location.get("name", "the site")
        _oc = prior_recon.get("outcome", "scouted")
        _note = (" -- that scout came back clean, so the intel is solid"
                 if _oc == "success" else
                 " -- that scout was partially blown, so treat the intel as good-but-incomplete"
                 if _oc == "partial" else
                 " -- that scout went sideways, so verify everything before you commit")
        _recon_provenance = (
            f'<div style="background:#eef6ff;border:1px solid #3a6898;border-radius:6px;padding:8px 12px;margin:0 0 8px;font-size:13px;">'
            f'<strong>Built on prior recon:</strong> {_e(_who)} scouted {_e(_vn)} during {_e(_ev)} ({_e(_oc)}){_e(_note)}.'
            f'</div>'
        )
    body += _card(
        f"The Contract - {_heist_ct['name']} Lays Out the Score",
        f'<blockquote style="border-left:4px solid {fc};margin:0 0 10px;padding:6px 14px;font-style:italic;color:#3a2d1a;background:#faf7f0;">{_e(_heist_brief(roles, target, location, _heist_ct, _heist_recon))}</blockquote>',
        fc,
    )
    body += _card(
        "Recon Dossier - What the Scouting Turned Up",
        _recon_provenance
        + _recon_card_html(_heist_recon)
        + "<p style='font-size:12px;color:#666;margin-top:6px;'>Treat this as the fruit of a prior infiltration (or the party's own casing). It answers most of the casing questions below -- so the table can plan the execution instead of guessing.</p>",
        "#3a6898",
    )
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
    body += _card("Execution Checks - Rogue Work", _execution_table(_execution_checks(strength)) + "<p style='font-size:12px;color:#666;margin-top:6px;'>The spine of the job: each phase is a skill check with its own setup and success/failure. Scale DCs to the party; a clever plan can grant advantage or skip a phase.</p>", "#8a5a1f")
    body += _card("Crew Support - How the Rest of the Party Helps", _crew_support_html(HEIST_CREW_SUPPORT) + "<p style='font-size:12px;color:#666;margin-top:6px;'>Non-rogue members are not spectators. These are 2024-rules ways they buy the safecracker advantage, silence, cover, or a clean exit.</p>", "#6b3fa0")
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
    from src.treasure import loot_card as _loot_card
    body += _loot_card(mission)
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

    # Build on a prior infiltration's recon. A spawned follow-up carries an explicit
    # parent_recon_id (hard link); otherwise fall back to the best match for this mark.
    prior_recon = None
    try:
        from src.db_api import find_recon_for_followup, get_recon_by_id
        _pid = mission.get("parent_recon_id")
        if _pid:
            prior_recon = get_recon_by_id(_pid)
        if not prior_recon:
            prior_recon = find_recon_for_followup(host_faction=roles.get("target_owner", ""), district=location.get("district", ""))
    except Exception as _recon_err:
        logger.debug(f"[HEIST] recon lookup skipped: {_recon_err}")
    failed_recon = _failed_recon_heat(roles, location)

    logger.info(f"[HEIST] Building {title!r} | sponsor={roles['sponsor']} | subtype={subtype}")

    plan = await _generate_plan(mission, subtype, roles, target, location, strength, options)

    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        map_path = await _generate_map(subtype, location, out_dir)

    from src.mission_builder.mimir_module import create_module as _mc, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd, enrich_mission_loot as _mel
    _mimir_id = await _mc(mission, mission_type="heist")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Heist Map")
    module_html = render_heist_module(mission, subtype, roles, target, location, plan, strength, options, map_path, out_dir, prior_recon, failed_recon)
    if prior_recon and prior_recon.get("id"):
        try:
            from src.db_api import mark_recon_consumed
            mark_recon_consumed(prior_recon["id"], mission.get("id"))
        except Exception as _recon_err:
            logger.debug(f"[HEIST] recon consume skipped: {_recon_err}")
    _loot_rewards = await _mel(_mimir_id or "", mission)
    module_html += _ms([], _loot_rewards, _mimir_id or "")
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
        + (
            f"### Heightened Security From Failed Recon\n"
            f"- Prior failed dossier: #{failed_recon.get('id')}\n"
            f"- Effect: add one extra security layer; start Heat at Warm; staff challenge repeated casing.\n\n"
            if failed_recon else ""
        )
        + f"### Security Plan\n"
        + "\n".join(f"- {s}" for s in plan.get("security_plan", []))
        + f"\n\n### Live Scaling\n{_party_scaling_note(strength)}"
    )
    players_md = (
        f"## Player Brief\n{plan.get('briefing', '')}\n\n"
        f"### Score\n"
        f"- Target: {target['name']}\n"
        f"- Site: {location.get('name')} - {location.get('district')}\n"
        f"- Known owner/security faction: {roles['target_owner']}\n\n"
        + (
            "### Security Warning\n"
            "A previous scout was burned around this owner or district. Expect tighter checks and suspicious staff.\n\n"
            if failed_recon else ""
        )
        + f"### Prep Options\n"
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
        + (
            "\n\n### Heightened Security\n"
            "| Failed prior recon | Add one security layer, start Heat at Warm, and make repeated casing draw attention. |"
            if failed_recon else ""
        )
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
        from src.mission_builder.mission_db import write_module_slug_for_mission
        write_module_slug_for_mission(mission, out_dir.name, log_prefix="HEIST")
    except Exception as e:
        logger.warning(f"[HEIST] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[HEIST] Complete: {title!r} -> {out_dir.name}")
    return index_path
