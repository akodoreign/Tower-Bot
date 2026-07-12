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

# Concrete occasions that give a believable reason to be inside without obvious
# weapons. `venue_kind` picks the matching venue type (society vs cult). Each
# drives the contact briefing and the cover.
INFILTRATION_EVENTS = [
    {"event": "Grand Masquerade Ball", "venue_kind": "society", "dress": "formal masque attire with a mask",
     "weapons": "no visible weapons -- though a mask and gown make a concealed blade easier (Sleight of Hand to hide one)",
     "access": "the ballroom and galleries, and, for the bold, the private wings upstairs"},
    {"event": "Charity Gala and Auction", "venue_kind": "society", "dress": "formal eveningwear",
     "weapons": "strictly no weapons; there is a coat-check and a polite pat-down at the door",
     "access": "the auction floor, the donor lounges, and the secure lot-room behind them"},
    {"event": "Art Unveiling and Salon", "venue_kind": "society", "dress": "refined gallery attire",
     "weapons": "no weapons -- the host frowns on anything that might 'damage the collection'",
     "access": "the gallery, the curator's office, and the climate-controlled vault rooms"},
    {"event": "Noble Investiture and Reception", "venue_kind": "society", "dress": "court formal; house colors earn warmer nods",
     "weapons": "ceremonial blades only, peace-bonded; everything else is checked at the door",
     "access": "the great hall, the receiving rooms, and the records wing"},
    {"event": "Opera Premiere", "venue_kind": "society", "dress": "formal box attire",
     "weapons": "no weapons in the boxes; the ushers are watchful",
     "access": "the private boxes, the green room, and the patrons' lounge"},
    {"event": "Guild Banquet and Summit", "venue_kind": "society", "dress": "guild formal or sharp business attire",
     "weapons": "tools are allowed for 'demonstrations'; weapons are checked",
     "access": "the banquet hall, the negotiation rooms, and the strongroom"},
    {"event": "High Wedding", "venue_kind": "society", "dress": "wedding formal; arrive with a gift",
     "weapons": "no weapons; both families have brought private guards",
     "access": "the ceremony, the reception, and the family's private floor"},
    {"event": "Collectors' Exhibition", "venue_kind": "society", "dress": "upscale collector attire",
     "weapons": "no weapons; the display cases are warded and watched",
     "access": "the exhibition floor, the appraisal room, and the back vault"},
    {"event": "Rite of Induction (a cult's indoctrination ceremony)", "venue_kind": "cult",
     "dress": "plain initiate's robes handed out at the door; no house colors, no jewelry, faces bared or veiled as the rite demands",
     "weapons": "all weapons and arcane focuses surrendered at the threshold as a sign of submission (Sleight of Hand to keep one, with real consequences if it is found)",
     "access": "the congregation hall, the initiates' cells, and -- past the veil -- the inner sanctum"},
    {"event": "Vigil of the Faithful (a closed devotional service)", "venue_kind": "cult",
     "dress": "modest worshipper's attire; sponsors must vouch for newcomers",
     "weapons": "no weapons in the sanctified space; the faithful consider it desecration",
     "access": "the nave, the side chapels, and the reliquary behind the altar"},
]

# Venue types matched to each event's venue_kind: (LIKE tags, prefer_high_wealth).
VENUE_KINDS = {
    "society": (["hall", "gallery", "manor", "estate", "opera", "theater", "theatre", "club", "museum", "court", "ballroom", "salon"], True),
    "cult":    (["shrine", "temple", "sanctum", "chapel", "undercroft", "crypt", "catacomb", "cathedral", "tabernacle", "hall"], False),
}

# Cult ceremonies are about secrets, not silverware -- scout these instead.
INFIL_TARGET_CULT = [
    "what the rite actually does to the people it 'elevates'",
    "the true name or master the cult secretly serves",
    "the identity of the hooded celebrant leading the rite",
    "where the cult keeps the initiates who 'ascended' and never came back",
    "the relic or sacrifice at the heart of the ceremony",
    "which respectable citizens are quietly sworn members",
]

# What the crew is actually there for. Items read as a smash-and-grab-by-charm;
# intel reads as scouting (and several seed a follow-up heist the DM can generate).
INFIL_TARGET_ITEMS = [
    "a small jade falcon statuette on open display",
    "a portrait the host has no honest right to own",
    "a signet ring the host never takes off",
    "a sealed ledger in a writing-desk",
    "an aged bottle from the private cellar",
    "a relic on loan to the host for the night",
    "a ceremonial dagger in a warded display case",
    "a jeweled reliquary kept in the back rooms",
]
INFIL_TARGET_INTEL = [
    "the floor plan and ward layout for an upcoming heist",
    "the rotation of the house guard and when the vault goes unwatched",
    "the true identity behind a particular masked guest",
    "which official on the guest list is taking bribes -- and from whom",
    "where the host has hidden the real prize",
    "the date and route of a coming shipment",
    "who the host is quietly meeting tonight, and why",
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


def _pick_event() -> Dict[str, Any]:
    return random.choice(INFILTRATION_EVENTS)


def _pick_location(needs_map: bool, event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    prefer_hi = False
    if event and event.get("venue_kind") in VENUE_KINDS:
        # The occasion decides the venue: a ball wants a hall, a cult rite a shrine.
        tags, prefer_hi = VENUE_KINDS[event["venue_kind"]]
    elif needs_map:
        tags = ["archive", "gallery", "vault", "museum", "office", "library", "shrine", "warehouse", "facility"]
    else:
        tags = ["hall", "gallery", "manor", "estate", "opera", "theater", "theatre", "club", "museum", "court", "ballroom", "guild", "salon"]
        prefer_hi = True
    where = " OR ".join(["LOWER(name) LIKE %s OR LOWER(type_tag) LIKE %s OR LOWER(description) LIKE %s"] * len(tags))
    params = []
    for tag in tags:
        params.extend([f"%{tag}%", f"%{tag}%", f"%{tag}%"])
    # Prefer high-wealth venues for society events; fall back if none match.
    if prefer_hi:
        hi = _db_rows(
            f"SELECT district, place_type, name, type_tag, description, wealth_level FROM gazetteer_places "
            f"WHERE ({where}) AND COALESCE(wealth_level,5) >= 6 ORDER BY RAND() LIMIT 1",
            tuple(params),
        )
        if hi:
            return hi[0]
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


def _pick_contact(roles: Dict[str, str]) -> Dict[str, str]:
    """A NAMED handler from the hiring faction who briefs the crew."""
    rows = _npcs_for_site(roles.get("hiring", ""), limit=8)
    # Prefer someone whose role reads like a fixer/handler/liaison.
    pref = [r for r in rows if any(w in str(r.get("role", "")).lower()
            for w in ("liaison", "fixer", "handler", "agent", "broker", "spymaster", "quartermaster", "contact"))]
    pick = (pref or rows or [None])[0]
    if pick and pick.get("name"):
        return {"name": pick["name"], "role": pick.get("role") or f"{roles.get('hiring','the faction')} agent"}
    return {"name": f"a {roles.get('hiring','faction')} fixer", "role": "handler"}


def _scenario(mission: dict, roles: Dict[str, str], location: Dict[str, Any], objectives: Dict[str, str], event: Dict[str, Any]) -> Dict[str, Any]:
    """Turn the abstract objective into a concrete occasion: an event, a venue, a
    date within the week, a dress/weapon rule, a specific target, and a named
    contact. This is what makes the briefing a scene instead of a template."""
    obj = objectives.get("primary", "")
    if event.get("venue_kind") == "cult":
        # Cult ceremonies are about uncovering secrets, not lifting silverware.
        target = random.choice(INFIL_TARGET_CULT)
        target_kind = "intel"
    elif any(w in obj for w in ("item", "artifact", "acquire", "recover", "swap", "deliver", "plant")):
        target = random.choice(INFIL_TARGET_ITEMS)
        target_kind = "item"
    else:
        target = random.choice(INFIL_TARGET_INTEL)
        target_kind = "intel"
    nights = random.randint(3, 7)  # within a week of the hire
    contact = _pick_contact(roles)
    return {
        "event": event["event"],
        "dress": event["dress"],
        "weapons": event["weapons"],
        "access": event["access"],
        "venue": location.get("name", "the venue"),
        "district": location.get("district", "a high-district"),
        "target": target,
        "target_kind": target_kind,
        "nights": nights,
        "date_phrase": "tomorrow night" if nights == 1 else f"{nights} nights from tonight",
        "contact_name": contact["name"],
        "contact_role": contact["role"],
        "host_faction": roles.get("site", "the host"),
        "seeds_heist": target_kind == "intel" and "heist" in target,
    }


def _scenario_briefing_fallback(scenario: Dict[str, Any], roles: Dict[str, str]) -> str:
    """Dynamic, in-character handler briefing built from the scenario specifics."""
    sc = scenario
    looking = ("walk out with " + sc["target"]) if sc["target_kind"] == "item" else ("come back with " + sc["target"])
    weapons = sc["weapons"][:1].upper() + sc["weapons"][1:] if sc.get("weapons") else ""
    blend = "blend in with the faithful" if sc.get("target_kind") == "intel" and "rite" in sc.get("event", "").lower() else "mingle and charm"
    return (
        f"\"{sc['contact_name']} sets a row of engraved cards on the table. "
        f"'The {sc['event']} at {sc['venue']}, {sc['district']} -- {sc['date_phrase']}. "
        f"I've gotten you all in. Dress the part: {sc['dress']}. {weapons}. "
        f"You {blend}, you {looking}, and you are gone before the last toast. "
        f"Draw steel or draw eyes and {roles.get('hiring','we')} never sent a soul -- understood?'\""
    )


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


async def _ollama(prompt: str, tokens: int = 1200) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.85, "num_predict": tokens, "num_ctx": _fit_ctx(prompt, tokens)},
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


async def _generate_briefing(mission: dict, roles: Dict[str, str], objectives: Dict[str, str], location: Dict[str, Any], covers: List[Dict[str, Any]], scenario: Dict[str, Any]) -> Dict[str, Any]:
    sc = scenario
    looking = f"steal {sc['target']}" if sc["target_kind"] == "item" else f"find out {sc['target']}"
    prompt = f"""Write the briefing scene for a D&D social-infiltration caper. Make it a SCENE, not a summary.

The occasion: the {sc['event']} at {sc['venue']}, in the {sc['district']} district, {sc['date_phrase']} (within a week of hire).
Hiring faction: {roles['hiring']}. Their named handler delivering this briefing: {sc['contact_name']} ({sc['contact_role']}).
Host / mark at the event: {sc['host_faction']}.
Dress code: {sc['dress']}. Weapon rule: {sc['weapons']}.
The job: get in under the cover of a guest, {looking}, and slip out before anyone notices.
Mission notes: {(mission.get('body') or mission.get('description') or '')[:300]}

Tone: roleplay-first heist-prologue. The handler is specific and a little wry.

Return JSON only:
{{
  "contact_speech": "3-5 sentences IN CHARACTER from {sc['contact_name']}, naming the event, the venue, the date, the dress code, the weapon rule, and exactly what to {('take' if sc['target_kind']=='item' else 'learn')}. Direct address to the party.",
  "briefing": "1 short paragraph of out-of-character context for the DM (who the host is, why this matters, what success unlocks).",
  "site_description": "2 sentences setting the {sc['event']} at {sc['venue']} -- the look, the crowd, the mood.",
  "opening_read_aloud": "2-3 sentences, present tense, sensory -- the party arriving at the {sc['event']} in costume, the first thing they see, hear, and smell.",
  "win_condition": "what success means here",
  "failure_note": "what failure looks like before lockdown",
  "debrief": "where/how the debrief happens after"
}}"""
    data = None
    for attempt in range(3):
        data = _parse_json(await _ollama(prompt))
        if data and data.get("contact_speech"):
            break
        logger.warning(f"[INFILTRATION] LLM returned no usable briefing (attempt {attempt + 1}/3)")
        await asyncio.sleep(2)
    if data and data.get("contact_speech"):
        data.setdefault("briefing", data.get("contact_speech", ""))
        return data
    # Scenic deterministic fallback -- still a specific, voiced briefing.
    take_learn = "lift" if sc["target_kind"] == "item" else "uncover"
    return {
        "contact_speech": _scenario_briefing_fallback(sc, roles),
        "briefing": f"{roles['hiring']} is sending the party into the {sc['event']} at {sc['venue']} ({sc['district']}) hosted by {sc['host_faction']}, {sc['date_phrase']}. The job is to {take_learn} {sc['target']} under guest cover and leave clean."
                    + (" The intel sets up a heist the DM can run next." if sc.get("seeds_heist") else ""),
        "site_description": location.get("description") or f"The {sc['event']} fills {sc['venue']} with light, music, and {sc['host_faction']}'s best-dressed guests; the real business happens in the quiet rooms off the floor.",
        "opening_read_aloud": f"You step into the {sc['event']} at {sc['venue']} in your borrowed finery. Warm light, layered conversation, the clink of glasses -- and not one face here knows what you actually came for.",
        "win_condition": f"Leave with {sc['target']} (or solid proof of it) and the cover intact.",
        "failure_note": "Failure starts as social suspicion -- a sharp question, a doubled guard -- before it becomes lockdown.",
        "debrief": f"{sc['contact_name']} takes the handoff somewhere quiet once the party is clear of {sc['venue']}.",
    }


async def _generate_map(location: Dict[str, Any], roles: Dict[str, str], out_dir: Path) -> Optional[Path]:
    out = out_dir / "infiltration_map.png"
    from src.battle_map_library import copy_library_map_for_mission
    return copy_library_map_for_mission(
        {"faction": roles.get("hiring", "") or roles.get("site", "")},
        out,
        mission_type="infiltration",
        location_name=location.get("name", ""),
        district=location.get("district", ""),
        description=f"{roles.get('site', '')} {location.get('description', '')}",
        map_type="office",
    )

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


def _approach_checks(strength: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rogue/face approach beats for infiltration: get in, blend, bypass, get out."""
    base = 12 + max(0, (int(strength.get("avg_level", 5)) - 3) // 2)
    return [
        {"phase": "Cross the perimeter", "skill": "Stealth", "dc": base,
         "setup": "Pick the gap in patrols and sightlines and slip inside the cordon.",
         "success": "Inside unseen; the alert track stays at baseline.",
         "failure": "A patrol clocks movement -- alert +1 and a roaming guard sweeps your entry."},
        {"phase": "Sell the cover", "skill": "Deception (or Performance)", "dc": base + 1,
         "setup": "Hold your assumed identity through a checkpoint, badge, or pointed question.",
         "success": "The cover holds; staff wave you deeper with no second look.",
         "failure": "The story frays -- suspicion rises, alert +1, and someone remembers your face."},
        {"phase": "Read the room", "skill": "Insight / Perception", "dc": base,
         "setup": "Mark the target, the watchers, and the fastest quiet route before acting.",
         "success": "You spot the mark, the camera, and a side exit the brief missed.",
         "failure": "You misread the room and step toward the wrong person or a watched door."},
        {"phase": "Bypass a lock or terminal", "skill": "Thieves' Tools / Sleight of Hand", "dc": base + 1,
         "setup": "Defeat a locked door, drawer, or access panel between you and the objective.",
         "success": "Open and re-secured behind you; no trace, no noise.",
         "failure": "It sticks or pings -- lose time, or a soft alarm puts a guard en route (alert +1)."},
        {"phase": "Move through the restricted zone", "skill": "Stealth", "dc": base + 2,
         "setup": "Reach the objective through the most-watched stretch of the site.",
         "success": "You cross unseen and reach the objective with the scene calm.",
         "failure": "A near-miss forces a hide or a bluff; alert +1 and the timer tightens."},
        {"phase": "Exfiltrate clean", "skill": "Stealth / Deception", "dc": base + 1,
         "setup": "Leave the way you planned -- or improvise out while the cover still holds.",
         "success": "You are gone before anyone connects the dots; no pursuit.",
         "failure": "Exit is contested -- a checkpoint, a lockdown, or a witness who can describe you."},
    ]


def _approach_table(beats: List[Dict[str, Any]]) -> str:
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


# Party-support options for the non-rogue crew (2024 / D&D 5.5e accurate).
INFILTRATION_CREW_SUPPORT = [
    ("Bard -- Bardic Inspiration & Friends",
     "Bonus action: give an infiltrator a Bardic Inspiration die (d6/d8/d10/d12 by level) to add to a Deception, Stealth, or Insight check -- usable after the d20 is rolled, before the result is read. Friends (cantrip, Concentration): Advantage on Charisma checks against one creature that isn't hostile -- ideal for sweet-talking a guard -- but when it ends the creature knows magic swayed it and becomes Hostile, so use it on someone you can leave behind."),
    ("Cleric or Druid -- Guidance",
     "Guidance (cantrip, Concentration up to 1 min): the touched ally adds 1d4 to one ability check -- spend it on the cover (Deception) at the checkpoint or the read-the-room (Insight/Perception) check."),
    ("Druid or Ranger -- Pass Without Trace",
     "2nd-level spell, Concentration up to 1 hour: each chosen creature within 30 ft gains +10 to Dexterity (Stealth) checks and can't be tracked nonmagically -- carry it through the perimeter cross and the restricted zone."),
    ("Wizard -- Disguise Self / Minor Illusion",
     "Disguise Self (1st level, up to 1 hour, no Concentration): backs a cover identity -- a uniform, a different face, altered gear; physical inspection or an Investigation check vs your spell save DC reveals it. Minor Illusion (cantrip): throw a sound or a 5-ft image to pull a patrol off a corridor (Investigation vs your spell save DC to disbelieve)."),
    ("Sorcerer -- Subtle Spell",
     "Subtle Spell metamagic (1 sorcery point): cast Charm Person (1st, Wis save), Disguise Self, or Suggestion (2nd, Wis save) with no Verbal or Somatic components -- nobody at the checkpoint sees you cast. Suggestion can talk a guard into 'escorting' you exactly where you wanted to go."),
    ("Rogue, Fighter, or anyone -- Help & cover",
     "Help action (Assist an Ability Check): if you are proficient with the same skill or tool the lead is using (Stealth, Deception, Sleight of Hand), they gain Advantage on that check before your next turn. Or manufacture a reason to be there -- a delivery, a loud complaint, a 'spilled' crate (Charisma (Deception) or a quick Sleight of Hand) -- to reset a suspicious guard without tripping the alert."),
]


def _crew_support_html(options: List[tuple]) -> str:
    return "".join(
        f'<div style="border-left:3px solid #6b3fa0;padding:8px 12px;margin:6px 0;background:#f7f4fc;">'
        f'<div style="font-weight:bold;color:#5a2d8a;">{_e(who)}</div>'
        f'<div style="font-size:13px;margin-top:2px;">{_e(text)}</div></div>'
        for who, text in options
    )


def _crew_jobs(strength: Dict[str, Any], site: str, objective: str, mark: str) -> List[Dict[str, Any]]:
    """Ocean's-Eleven crew jobs mapped to D&D 5.5e (2024), each a real skill check
    with multiple skill options and setup/success/failure, woven to THIS mission's
    site, objective, and mark. DCs scale to party level."""
    base = 12 + max(0, (int(strength.get("avg_level", 5)) - 3) // 2)
    s, obj, mk = site or "the site", objective or "the objective", mark or "the mark"
    return [
        {"job": "The Mastermind -- the plan", "dc": base,
         "skills": "Intelligence (Investigation), Wisdom (Insight), or Intelligence (History)",
         "setup": f"Read {s} and {mk}'s routine, then set the order of operations before anyone moves.",
         "success": f"The crew gets the timing window and the safest sequence to reach {obj}; the first chosen approach starts with Advantage.",
         "failure": "The plan has a blind spot -- the DM keeps one surprise (an extra patrol or ward) in reserve.",
         "signature": "Any class. Turns the Casing answers into the running order and calls the audible when the alert track climbs."},
        {"job": "The Face / Grifter", "dc": base + 1,
         "skills": "Charisma (Deception), Charisma (Persuasion), or Charisma (Performance); Disguise Kit",
         "setup": f"Sell the cover to whoever stands between the crew and {obj} -- a clerk, a guard, or {mk} themselves.",
         "success": "They wave you through and let slip something useful: a name, a door, a schedule.",
         "failure": "Suspicion rises (alert +1) and that person remembers your face.",
         "signature": "Bard, Sorcerer, Warlock, Rogue. Disguise Self (1st); Suggestion (2nd, Wis save) to redirect a guard; Charm Person (1st), who knows once it ends."},
        {"job": "The Ghost / Inside Man", "dc": base + 1,
         "skills": "Dexterity (Stealth), Dexterity (Acrobatics), or Strength (Athletics) for a climb",
         "setup": f"Reach the inside of {s} by the route no one watches and open a way for the crew.",
         "success": "A door, window, or shaft opens from the inside; the crew skips the front entirely.",
         "failure": "The route is tighter or more watched than it looked -- lose time, or alert +1.",
         "signature": "Monk, Rogue, Ranger. Rides Pass Without Trace (+10 Stealth, 30 ft)."},
        {"job": "The Box-Man / Safecracker", "dc": base + 2,
         "skills": "Thieves' Tools, Dexterity (Sleight of Hand), or Intelligence (Investigation) to find the catch",
         "setup": f"Defeat the lock or container guarding {obj}.",
         "success": "It opens clean and re-secures behind you; no trace left.",
         "failure": "It sticks or pings -- lose time, or trip a soft alarm (alert +1).",
         "signature": "Rogue or anyone tool-proficient. Far safer inside a Silence sphere; see the Approach Checks above."},
        {"job": "The Wardbreaker / 'Hacker'", "dc": base + 2,
         "skills": "Intelligence (Arcana); Detect Magic or Dispel Magic if prepared",
         "setup": f"Map and defeat the magical security around {obj}.",
         "success": "The ward, glyph, or alarm is down or routed around; the path is safe.",
         "failure": "The ward holds or backlashes -- a magical alarm fires or a glyph triggers.",
         "signature": "Wizard, Sorcerer, Arcane Trickster Rogue. Detect Magic (1st) to map, Dispel Magic (3rd) to drop a ward, Knock (2nd) when speed beats silence."},
        {"job": "The Showman / Distraction", "dc": base + 1,
         "skills": "Charisma (Performance) or Charisma (Deception)",
         "setup": f"Stage a scene loud enough to pull {s}'s security toward you and away from the real move.",
         "success": "Security commits to the distraction; the quiet team works unopposed for a round or two.",
         "failure": "The act is thin -- guards split their attention, or call it in (alert +1).",
         "signature": "Bard. Minor Illusion (cantrip) or Major Image (3rd: sight, sound, smell); Bardic Inspiration to prop up whoever is on the line."},
        {"job": "The Eye in the Sky / Coordinator", "dc": base,
         "skills": "Wisdom (Perception) or Wisdom (Insight)",
         "setup": f"Watch {s} from cover or afar and feed the crew live information.",
         "success": "The crew gets a heads-up on the next patrol or change; one ally gains Advantage on their next check.",
         "failure": "A blind spot -- the crew misses a moving guard and the DM springs it.",
         "signature": "Any; casters add reach. Message (cantrip) for comms; Find Familiar (1st) to scout and see through its eyes; Clairvoyance (3rd) to watch from outside."},
        {"job": "The Muscle & Driver / Exfil", "dc": base + 1,
         "skills": "Strength (Athletics) or Dexterity (Stealth) for a quiet exit",
         "setup": f"Own the way out of {s} and be ready to move the score and the crew.",
         "success": "The exit stays open and the getaway is clean; no pursuit.",
         "failure": "The route closes or pursuit forms -- a chase, or a witness who can name a face.",
         "signature": "Fighter, Barbarian, Ranger. Help action (Assist) when proficient with the ally's skill or tool."},
    ]


def _crew_jobs_html(jobs: List[Dict[str, Any]]) -> str:
    cards = ""
    for j in jobs:
        cards += (
            '<div style="border:1px solid #6b3fa0;border-left:5px solid #6b3fa0;border-radius:6px;padding:10px 14px;margin:8px 0;background:#f7f4fc;">'
            f'<div style="font-weight:bold;color:#5a2d8a;font-size:14px;">{_e(j["job"])}</div>'
            f'<div style="font-size:12px;color:#444;margin:3px 0;"><strong>Check:</strong> {_e(j["skills"])} <span style="white-space:nowrap;">(DC {j["dc"]})</span></div>'
            f'<div style="font-size:13px;margin:2px 0;"><strong style="color:#5a4020;">Setup:</strong> {_e(j["setup"])}</div>'
            f'<div style="font-size:13px;margin:2px 0;"><strong style="color:#2a6a2a;">On Success:</strong> {_e(j["success"])}</div>'
            f'<div style="font-size:13px;margin:2px 0;"><strong style="color:#9a2a2a;">On Failure:</strong> {_e(j["failure"])}</div>'
            f'<div style="font-size:12px;color:#555;margin-top:3px;"><strong>Signature:</strong> {_e(j["signature"])}</div>'
            '</div>'
        )
    return cards


def _the_play_html(site: str, objective: str, mark: str) -> str:
    s   = _e(site or "the site")
    obj = _e(objective or "the objective")
    mk  = _e(mark or "the mark")
    return (
        '<div style="font-size:13px;line-height:1.6;">'
        f'<p><strong>Act I -- The Case &amp; The Plant.</strong> The crew cases {s} (Investigation, Perception, a planted contact or item) and establishes what {mk} treats as normal. Nothing is taken yet; the job is information and a foothold -- a cover identity inside, a propped door, a bribed schedule.</p>'
        f'<p><strong>Act II -- The Switch.</strong> Run a loud, visible play (the Showman&#39;s distraction, the Face&#39;s scene, the obvious approach) so {mk}&#39;s security commits to the wrong threat -- while the real move on {obj} happens quietly elsewhere. Name the one <em>tell</em> that blows it (a face {mk} knows, a ward that resets, a guard who counts heads) so the table knows what to protect.</p>'
        f'<p><strong>Act III -- The Getaway.</strong> Walk out of {s} clean before anyone realizes. The best capers end with {mk} not knowing they were robbed until long after the crew is gone -- bank the win on the exfil, not the grab.</p>'
        '<div style="border-left:4px solid #b8621a;background:#fff8ee;padding:8px 12px;margin:8px 0;">'
        f'<strong>The Complication (pick or roll one):</strong> a patrol rotates early; {mk} recognizes a face; a magical ward resets mid-job; a rival crew is working the same mark; or {obj} isn&#39;t where intel said. Every caper has the &quot;oh no&quot; beat -- reward the players who planned a contingency.</div>'
        '<div style="border-left:4px solid #2a6a2a;background:#f1f8f1;padding:8px 12px;margin:8px 0;">'
        '<strong>The Twist (optional, high level):</strong> let the players run a plan within the plan. Seeming (5th) puts the whole crew in disguise; Mislead (5th) sends an illusory double through the front while the caster slips out invisibly. The con the audience sees should not be the con that actually works.</div>'
        '</div>'
    )


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
    scenario: Optional[Dict[str, Any]] = None,
) -> str:
    title = mission.get("title", "Infiltration")
    scenario = scenario or {}
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
    if scenario:
        _contact_q = briefing.get("contact_speech") or _scenario_briefing_fallback(scenario, roles)
        body += _card(
            f"The Job - {scenario.get('contact_name', 'Your Contact')} Briefs the Crew",
            f'<blockquote style="border-left:4px solid {fc};margin:0 0 10px;padding:6px 14px;font-style:italic;color:#3a2d1a;background:#faf7f0;">{_e(_contact_q)}</blockquote>'
            + _table([
                ("Occasion", scenario.get("event", "")),
                ("Venue", f"{scenario.get('venue', '')}, {scenario.get('district', '')} district"),
                ("When", f"{scenario.get('date_phrase', '')} (within a week of hire)"),
                ("Dress code", scenario.get("dress", "")),
                ("Weapons", scenario.get("weapons", "")),
                ("Looking for", scenario.get("target", "")),
                ("Your contact", f"{scenario.get('contact_name', '')} ({scenario.get('contact_role', '')}, {roles['hiring']})"),
                ("Host / mark", scenario.get("host_faction", "")),
            ]),
            fc,
        )
    body += _card("Briefing (DM context)", f'<div style="white-space:pre-line;font-style:italic;">{_e(briefing["briefing"])}</div><p>{_e(briefing["site_description"])}</p>', fc)
    body += _card("Live Party Scaling", f'<p>{_e(_party_scaling_note(strength))} Cover pressure, alert severity, and suggested PC roles use this read.</p>', "#3a6898")
    body += _card("Objective", _table([
        ("Primary", objectives["primary"]),
        ("Secondary", objectives["secondary"]),
        ("Win condition", briefing["win_condition"]),
        ("Failure before lockdown", briefing["failure_note"]),
    ]), "#7b1e1e")
    # Ocean's-Eleven caper layer, woven to this mission's actual event / target / mark.
    _cap_site = scenario.get("venue") or location.get("name", "the site")
    _cap_obj  = scenario.get("target") or objectives.get("primary", "the objective")
    _cap_mark = scenario.get("host_faction") or mission.get("opposing_faction") or location.get("district") or "the mark"
    body += _card("The Play - Run It in Three Acts", _the_play_html(_cap_site, _cap_obj, _cap_mark), "#6b3fa0")
    body += _card("The Crew - Assign the Jobs (Ocean's-Eleven Style)", _crew_jobs_html(_crew_jobs(strength, _cap_site, _cap_obj, _cap_mark)) + "<p style='font-size:12px;color:#666;margin-top:6px;'>Hand every player a job. Each is a real check with skill options and its own setup/success/failure, scaled to the party and tied to this mark.</p>", "#6b3fa0")
    body += _card("Cover Options", cover_html, "#8a5a1f")
    body += _card("Suggested PC Roles", _table(pc_rows), "#3a6898")
    body += _card("Social Cast", _table(cast_rows), "#555")
    body += _card("Scene Sequence", _table(scene_rows), "#8a5a1f")
    body += _card("Approach Checks - Get In, Blend, Bypass, Get Out", _approach_table(_approach_checks(strength)) + "<p style='font-size:12px;color:#666;margin-top:6px;'>The infiltration spine: each phase is a skill check with its own setup and success/failure. A failed check usually advances the alert track rather than ending the run.</p>", "#3a6898")
    body += _card("Crew Support - How the Rest of the Party Helps", _crew_support_html(INFILTRATION_CREW_SUPPORT) + "<p style='font-size:12px;color:#666;margin-top:6px;'>2024-rules ways non-face/non-rogue members buy advantage, cover, or a quiet way past -- without burning the alert track.</p>", "#6b3fa0")
    body += _card("Alert Track", _table(alert_rows) + f"<h3>Consequences</h3><ul>{consequences}</ul>", "#7b1e1e")
    body += map_section
    body += _card("Debrief", f'<p>{_e(briefing["debrief"])}</p><p><strong>Alert result:</strong> <select><option>Clear</option><option>Curious</option><option>Suspicious</option><option>Searching</option><option>Lockdown</option></select></p><p><strong>Cover maintained:</strong> <input type="checkbox"></p><textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Debrief notes..."></textarea>', "#2a6a2a")
    from src.treasure import loot_card as _loot_card
    body += _loot_card(mission)
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
    event = _pick_event()
    needs_map = _needs_map(mission, objectives["primary"])
    location = _pick_location(needs_map, event)
    covers = _cover_options(roles)
    cast = _social_cast(roles["site"])
    scenes = _scene_sequence(objectives["primary"], needs_map)
    pc_roles = _suggest_pc_roles(strength)
    scenario = _scenario(mission, roles, location, objectives, event)

    # Record this scout into the recon repository so follow-up heist/assassination
    # jobs can build on it. Outcome derives from mission status; an NPC party
    # resolving the mission later upgrades it to success/failure (by mission_id).
    try:
        from src.db_api import record_recon_dossier
        _st = str(mission.get("status") or "").lower()
        _out = "success" if _st == "completed" else "failure" if _st == "failed" else "scouted"
        record_recon_dossier(
            mission_id=mission.get("id"), party_name=mission.get("player_claimer") or "",
            event_name=scenario["event"], venue=scenario["venue"], district=scenario["district"],
            host_faction=roles.get("site", ""), hiring_faction=roles.get("hiring", ""),
            target=scenario["target"], target_kind=scenario["target_kind"], outcome=_out,
            dossier=scenario,
        )
    except Exception as _recon_err:
        logger.debug(f"[INFILTRATION] recon record skipped: {_recon_err}")

    logger.info(f"[INFILTRATION] Building {title!r} | hiring={roles['hiring']} site={roles['site']} | event={scenario['event']} | target={scenario['target']!r}")

    briefing = await _generate_briefing(mission, roles, objectives, location, covers, scenario)

    map_path = None
    if needs_map and str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        map_path = await _generate_map(location, roles, out_dir)

    from src.mission_builder.mimir_module import create_module as _mc, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd, enrich_mission_loot as _mel
    _mimir_id = await _mc(mission, mission_type="infiltration")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Infiltration Map")
    module_html = render_infiltration_module(
        mission, roles, objectives, location, briefing, covers, cast, scenes,
        pc_roles, strength, needs_map, map_path, out_dir, scenario,
    )
    _loot_rewards = await _mel(_mimir_id or "", mission)
    module_html += _ms([], _loot_rewards, _mimir_id or "")
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
        from src.mission_builder.mission_db import write_module_slug_for_mission
        write_module_slug_for_mission(mission, out_dir.name, log_prefix="INFILTRATION")
    except Exception as e:
        logger.warning(f"[INFILTRATION] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[INFILTRATION] Complete: {title!r} -> {out_dir.name}")
    return index_path
