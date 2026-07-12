"""
gather_pipeline.py — Pipeline for Gathering mission modules.

A gathering mission has three acts:
  1. Contact scene  — meet a real faction NPC, banter, negotiate, learn what and where
  2. Gather phase   — skill checks at the location to collect items (finite stock, quota target)
                      random encounters fire between each check
  3. Debrief scene  — return to contact, emotional reaction based on quota hit

Reward scales with quota percentage. Complete failure loses faction reputation.

Exported:
    build_gather_module(mission: dict, out_dir: Path) -> Path
    is_gather_mission(mission_type: str) -> bool
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
from src.mission_builder.html_renderer import _faction_color, _CSS, _page
from src.mission_builder.cr_scaling import mission_cr, party_strength as _party_strength

OUTPUT_BASE  = Path(__file__).resolve().parent.parent.parent / "generated_modules"
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")

# ---------------------------------------------------------------------------
# Mission type detection
# ---------------------------------------------------------------------------

_GATHER_KEYWORDS = {"gather", "gathering", "collect", "collection", "retrieve", "forage", "salvage", "harvest"}

def is_gather_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _GATHER_KEYWORDS)


# ---------------------------------------------------------------------------
# Faction gather profiles
# ---------------------------------------------------------------------------

FACTION_GATHER: Dict[str, Dict] = {
    "Wardens of Ash": {
        "item_category": "supplies",
        "examples":      ["healing poultices", "climbing rope", "ration packs", "replacement armour straps", "torch oil"],
        "handling":      "sturdy — most items are practical goods, hard to damage",
        "fragility":     "low",
        "meet_locations": ["Adventurers Guild private room", "the base of the Tower challenger staging area", "a Wardens checkpoint"],
    },
    "Tower Authority": {
        "item_category": "evidence and contraband",
        "examples":      ["seized documentation", "restricted arcane components", "confiscated goods", "witness statements"],
        "handling":      "chain of custody matters — items must arrive intact and unhandled",
        "fragility":     "medium",
        "meet_locations": ["Adventurers Guild private room", "an enforcement anteroom", "a public checkpoint office"],
    },
    "Patchwork Saints": {
        "item_category": "food and medicine",
        "examples":      ["medicinal herbs", "preserved food stocks", "clean water containers", "bandaging materials", "fever root"],
        "handling":      "perishables need care but nothing exotic",
        "fragility":     "low",
        "meet_locations": ["the community food kitchen", "a Saints safehouse", "Adventurers Guild private room"],
    },
    "Wizards Tower": {
        "item_category": "arcane components",
        "examples":      ["void shards", "rift residue", "stabilised reagents", "mana crystals", "elemental cores"],
        "handling":      "volatile — void shards can detonate if struck, rift residue degrades within hours of exposure to air",
        "fragility":     "extreme",
        "meet_locations": ["a restricted annex anteroom", "a scholar café on Academy Row", "Adventurers Guild private room"],
    },
    "Argent Blades": {
        "item_category": "trophies and contract proof",
        "examples":      ["monster trophies", "signed contract documents", "recovered coin", "witness seals", "bounty tokens"],
        "handling":      "physical goods, handle them fine — just don't lose them",
        "fragility":     "low",
        "meet_locations": ["Adventurers Guild private room", "the Argent Blades contract house", "a hired booth at a tavern"],
    },
    "Iron Fang Consortium": {
        "item_category": "trade goods and raw materials",
        "examples":      ["processed ore samples", "salvage components", "market surplus goods", "raw crystal", "reclaimed machine parts"],
        "handling":      "industrial materials, tough to damage unless specifically volatile",
        "fragility":     "low",
        "meet_locations": ["a Consortium warehouse office", "a depot meeting room", "the docks", "Adventurers Guild private room"],
    },
    "Obsidian Lotus": {
        "item_category": "rare and sensitive items",
        "examples":      ["unique personal artifacts", "sealed correspondence", "stolen goods", "blackmail material", "rare curios"],
        "handling":      "discretion is the handling requirement — be seen with any of this and questions get asked",
        "fragility":     "medium",
        "meet_locations": ["a private dining room", "a front business back office", "a location with no witnesses"],
    },
    "Glass Sigil": {
        "item_category": "luxury goods and rare ingredients",
        "examples":      ["exotic herbs", "fine dye materials", "sealed correspondence", "rare mineral pigments", "luxury spices"],
        "handling":      "presentation matters — damaged goods are worth nothing to the Sigil",
        "fragility":     "medium",
        "meet_locations": ["a private gallery room", "a wealth-district club", "Adventurers Guild private room"],
    },
    "Serpent Choir": {
        "item_category": "ritual components",
        "examples":      ["blood moss", "grave soil from specific sites", "live specimens", "cultist relics", "shadow-touched crystals"],
        "handling":      "some items must stay alive, others must stay inert — the contact will specify which is which",
        "fragility":     "high",
        "meet_locations": ["a hidden shrine anteroom", "a converted cellar", "a cult-controlled back room — never public"],
    },
    "Guild of Ashen Scrolls": {
        "item_category": "historical artifacts and samples",
        "examples":      ["old manuscripts", "ruin debris samples", "dated pottery fragments", "archival photographs", "historical coins"],
        "handling":      "fragile — aged materials crack and crumble, must be wrapped properly",
        "fragility":     "high",
        "meet_locations": ["the Guild archive reading room", "a scholar café", "Adventurers Guild private room"],
    },
    "Brother Thane's Cult": {
        "item_category": "cult materials",
        "examples":      ["sanctified bones", "marked grave soil", "ritual candles", "the Returned's personal effects", "void-touched cloth"],
        "handling":      "treated with reverence — dropping or mishandling is an insult",
        "fragility":     "medium",
        "meet_locations": ["a cult-controlled space — they do not meet on neutral ground"],
    },
}

_DEFAULT_GATHER = {
    "item_category": "goods",
    "examples":      ["assorted valuables", "specific components", "requested materials"],
    "handling":      "standard care",
    "fragility":     "low",
    "meet_locations": ["Adventurers Guild private room"],
}

def _get_gather_profile(faction: str) -> Dict:
    for k, v in FACTION_GATHER.items():
        if k.lower() in faction.lower():
            return v
    return _DEFAULT_GATHER


# ---------------------------------------------------------------------------
# Skill mapping by item category
# ---------------------------------------------------------------------------

GATHER_SKILLS: Dict[str, List[str]] = {
    "arcane components":            ["Arcana", "Investigation"],
    "ritual components":            ["Religion", "Nature", "Investigation"],
    "food and medicine":            ["Nature", "Survival", "Medicine"],
    "supplies":                     ["Athletics", "Investigation", "Perception"],
    "evidence and contraband":      ["Investigation", "Stealth", "Perception"],
    "trade goods and raw materials":["Athletics", "Investigation", "Perception"],
    "trophies and contract proof":  ["Investigation", "Athletics", "Perception"],
    "rare and sensitive items":     ["Investigation", "Stealth", "Perception"],
    "luxury goods and rare ingredients": ["Nature", "Investigation", "History"],
    "historical artifacts and samples":  ["History", "Investigation", "Arcana"],
    "cult materials":               ["Religion", "Investigation", "Stealth"],
    "goods":                        ["Investigation", "Perception"],
}

FRAGILITY_DC: Dict[str, Dict[str, int]] = {
    #            standard  seasoned  elite  legend
    "low":      {"standard": 10, "seasoned": 12, "elite": 14, "legend": 16},
    "medium":   {"standard": 12, "seasoned": 14, "elite": 16, "legend": 18},
    "high":     {"standard": 14, "seasoned": 16, "elite": 18, "legend": 20},
    "extreme":  {"standard": 16, "seasoned": 18, "elite": 20, "legend": 22},
}


# ---------------------------------------------------------------------------
# Encounter table
# ---------------------------------------------------------------------------

ENCOUNTERS: List[Dict] = [
    # ── Comedic / Social ────────────────────────────────────────────────────
    {"type": "comedic", "title": "Argent Blades Commercial",
     "desc": "The Argent Blades have cordoned off the entire area with a film crew. A harried talent wrangler refuses to let anyone through until they wrap.",
     "mechanic": "DC 13 Persuasion or Performance to talk your way through — or wait 20 minutes (triggers another encounter roll)."},
    {"type": "comedic", "title": "The Vendor Who Won't Stop",
     "desc": "A merchant attaches themselves to the party, offering unsolicited opinions on everything being picked up and following them from spot to spot.",
     "mechanic": "DC 11 Persuasion or Deception to shake them. Until then, checks are made with disadvantage from the distraction."},
    {"type": "comedic", "title": "Tower Authority Routine Inspection",
     "desc": "A pair of officers begins a routine inspection of the area. Everyone must look completely normal while actively gathering.",
     "mechanic": "DC 13 Deception or Performance. Failure means a 10-minute delay while papers are checked."},
    {"type": "comedic", "title": "Domestic Dispute",
     "desc": "Two NPCs are having a spectacular argument directly on top of the gather spot and refuse to move.",
     "mechanic": "DC 12 Persuasion to mediate or DC 14 Intimidation to clear them. Otherwise wait them out (1 encounter clock tick)."},
    {"type": "comedic", "title": "The Child Who Found It First",
     "desc": "A street child has one of the items and knows exactly what it's worth to the right people.",
     "mechanic": "Trade, bribe (2d6 silver), tell a good story (DC 12 Performance), or pickpocket (DC 15 Sleight of Hand)."},
    {"type": "comedic", "title": "Street Performer",
     "desc": "A fire-spinner sets up right in the middle of the gather area and draws a crowd so thick the party can't move.",
     "mechanic": "All gather checks at disadvantage until the performer finishes (2 rounds) or is tipped generously (5gp)."},
    {"type": "comedic", "title": "Mistaken Identity",
     "desc": "Someone mistakes the party for city sanitation workers and starts loudly filing complaints about the neighbourhood.",
     "mechanic": "DC 11 Deception to maintain the cover and get useful area access, or DC 13 Persuasion to get rid of them."},
    {"type": "comedic", "title": "Upper District Tourist",
     "desc": "A bewildered tourist from the upper districts is photographing everything with an expensive arcane imager, including the party mid-gather.",
     "mechanic": "DC 12 Persuasion to redirect them. If they photograph an item, roll Stealth DC 13 or the image ends up in a society publication."},
    {"type": "comedic", "title": "Arcane Cart Explosion",
     "desc": "A nearby food cart's heating element fails spectacularly — smoke, scattered crowd, food everywhere.",
     "mechanic": "All gather checks at disadvantage for 1 round from chaos. On the upside, everyone else is distracted — Stealth checks DC is reduced by 3."},
    {"type": "comedic", "title": "Parade Route",
     "desc": "The gather area is directly on an unannounced parade route. The procession begins in three minutes.",
     "mechanic": "Gather everything possible before the parade arrives (2 quick gather checks at disadvantage) or wait it out for a full encounter clock tick."},
    {"type": "comedic", "title": "Old Acquaintance",
     "desc": "An NPC from a previous mission spots the party and wants to catch up. At length. Right now.",
     "mechanic": "DC 14 Persuasion to keep it brief. Otherwise lose a full gather attempt to catching up — though they may reveal a useful rumour."},
    {"type": "comedic", "title": "Bidding War",
     "desc": "A passing merchant realises what's being collected and immediately starts offering to outbid whoever hired the party.",
     "mechanic": "DC 13 Insight to read if they're genuine. Selling to them ends the mission early with partial reward — no faction rep hit if handled discreetly."},
    {"type": "comedic", "title": "Escaped Animals",
     "desc": "Someone drops a crate of live animals nearby. They scatter directly through the gather area.",
     "mechanic": "DC 12 Athletics to protect gathered items. Failure means 1d3 items are damaged or scattered (fragile items treated as one failed check)."},
    {"type": "comedic", "title": "Street Preacher",
     "desc": "A preacher sets up and begins loudly denouncing the collection of exactly what the party is gathering as an affront to the natural order.",
     "mechanic": "Gather checks at disadvantage while they preach. DC 14 Religion or Persuasion to convince them to move along."},
    {"type": "comedic", "title": "Scholar With a Notebook",
     "desc": "A Guild of Ashen Scrolls scholar is documenting the area and writing down everything the party does in a leather journal.",
     "mechanic": "DC 13 Deception or Persuasion to misdirect them. If ignored, there is now a written record of the gathering."},
    {"type": "comedic", "title": "Neighbourhood Council",
     "desc": "A spontaneous community meeting convenes in the gather area. Attendance appears mandatory.",
     "mechanic": "DC 11 Persuasion to get exempted. Staying gives a free Perception check to spot a useful area detail."},
    {"type": "comedic", "title": "The Knowing Beggar",
     "desc": "A street beggar clearly knows what the items are worth. Offers to help locate more — for a percentage.",
     "mechanic": "Pay them (10% of reward) for 1 free gather check success. DC 14 Insight to tell if they're trustworthy first."},
    {"type": "comedic", "title": "Portrait Session",
     "desc": "A notable figure is having their portrait painted precisely where the party needs to be.",
     "mechanic": "DC 14 Deception to pose as assistants and gather in the background. Failure draws attention."},
    {"type": "comedic", "title": "Rogue Maintenance Golem",
     "desc": "A malfunctioning city maintenance golem keeps wandering through, scooping up items it classifies as debris.",
     "mechanic": "DC 13 Arcana to redirect it. Each round ignored, it has a 1-in-4 chance of collecting a gathered item."},

    # ── Inconvenient / Mechanical ────────────────────────────────────────────
    {"type": "inconvenient", "title": "Rival Gatherers",
     "desc": "Another crew is working the same spot for a different buyer. Stock depletes faster.",
     "mechanic": "Each gather check, roll off against a rival (DC 13). Losses reduce available stock by 1 additional."},
    {"type": "inconvenient", "title": "Dome Malfunction",
     "desc": "A dome sector malfunctions — strange lighting, wrong-season weather, or a temperature spike.",
     "mechanic": "All gather checks +2 DC for the next 3 rounds until the sector resets."},
    {"type": "inconvenient", "title": "Area Recently Cleaned",
     "desc": "Tower Authority swept through recently. Some stock has been confiscated or moved.",
     "mechanic": "Reduce available stock by 1d4 before the gather begins."},
    {"type": "inconvenient", "title": "Vendor Occupation",
     "desc": "A vendor has set up directly on top of the gather spot and has a permit.",
     "mechanic": "DC 13 Persuasion or 5gp to relocate them. Otherwise all checks at disadvantage."},
    {"type": "inconvenient", "title": "Arcane Quarantine",
     "desc": "The area is under a minor arcane quarantine — harmless but requires showing travel papers.",
     "mechanic": "DC 12 Deception if papers are missing. Failure means 15-minute delay (encounter clock tick)."},
    {"type": "inconvenient", "title": "Water Main Burst",
     "desc": "A water main has burst, flooding part of the gather area. Some items may be washing away.",
     "mechanic": "DC 13 Athletics to secure gathered items. Unchecked, lose 1 gathered item per round to the current."},
    {"type": "inconvenient", "title": "Word Is Out",
     "desc": "The faction's rivals have put out word that someone is buying these items. Everyone in the area now knows.",
     "mechanic": "All gather checks at disadvantage from people watching. Price of any trade encounter increases by 50%."},
    {"type": "inconvenient", "title": "Construction Cordon",
     "desc": "Part of the gather area is cordoned off for city construction.",
     "mechanic": "Reduce available stock by 2. A DC 13 Stealth check lets the party access the cordoned section."},
    {"type": "inconvenient", "title": "Wrong Turf",
     "desc": "The area is controlled by a different faction than the contact implied. They want acknowledgement.",
     "mechanic": "DC 13 Persuasion to get temporary access. Failure means paying a toll (1d6 × 5gp) or leaving."},
    {"type": "inconvenient", "title": "No Permit",
     "desc": "The gather requires a district permit. The contact forgot to mention this.",
     "mechanic": "DC 14 Deception to bluff having one, or spend 30 minutes and 10gp obtaining it (encounter clock tick)."},
    {"type": "inconvenient", "title": "Sinkhole",
     "desc": "A sinkhole has opened near the gather spot. Some stock has dropped in.",
     "mechanic": "DC 14 Athletics to safely retrieve items from the sinkhole. Failure risks 1d6 damage and empty hands."},
    {"type": "inconvenient", "title": "Sector Darkness",
     "desc": "The dome sector goes dark mid-gather. Emergency lighting flickers but barely covers the area.",
     "mechanic": "All gather checks at disadvantage until power restores (1d4 rounds)."},
    {"type": "inconvenient", "title": "Competing Errand",
     "desc": "A runner from a different faction is here on eerily similar business. Awkward overlap.",
     "mechanic": "DC 12 Insight to read their intent. They may be willing to trade information for a share of the stock."},

    # ── Rare Combat ──────────────────────────────────────────────────────────
    {"type": "combat", "title": "Hired Muscle",
     "desc": "Someone doesn't want this faction getting these items and paid professionals to stop the party.",
     "mechanic": "1d4+1 thugs (CR 1/2), one veteran (CR 3). Defeated enemies may carry a note naming who hired them."},
    {"type": "combat", "title": "Item Destabilisation",
     "desc": "A gathered volatile item destabilises — void shard pulsing, reagent smoking, specimen escaping.",
     "mechanic": "DC 15 Arcana or relevant skill to contain. Failure causes 2d6 damage in a 10ft radius and ruins 1 gathered item."},
    {"type": "combat", "title": "Faction Intercept",
     "desc": "Rival faction operatives arrive to take what's already been gathered — not just competing, actively hostile.",
     "mechanic": "2 operatives (CR 2) attempt to grab the gathered items and run. Grapple or Athletics DC 14 to stop each one."},
    {"type": "combat", "title": "Bounty Hunter",
     "desc": "A bounty hunter is pursuing a party member — the timing is terrible.",
     "mechanic": "1 bounty hunter (CR 4). Will pursue until subdued, paid off (DC 15 Persuasion), or fled from."},
    {"type": "combat", "title": "Trapped Cache",
     "desc": "Whoever cached the items left a trap on the stash. Triggered on collection.",
     "mechanic": "DC 14 Perception to spot. Triggered: DC 13 Dexterity save or 3d6 damage (type matches item type — arcane, physical, etc.)."},
    {"type": "combat", "title": "Drawn Creature",
     "desc": "Something has been attracted to the item's magical or biological signature and followed it here.",
     "mechanic": "CR appropriate to tier. Creature wants the items, not the party — will grab and flee if possible."},
    {"type": "combat", "title": "Gang Shakedown",
     "desc": "A local street gang runs a protection racket on this block. Pay or fight — they are not interested in a third option.",
     "mechanic": "Pay 2d6 × 5gp or fight 1d4+2 bandits (CR 1/8). Paying doesn't stop them trying again if the party returns."},
    {"type": "combat", "title": "Corrupt Officer",
     "desc": "A Tower Authority officer runs a personal racket on this street. Badge, attitude, and two deputies.",
     "mechanic": "Pay 50gp, pass DC 15 Intimidation, or fight. Violence against Authority has consequences later."},
    {"type": "combat", "title": "Desperate NPC",
     "desc": "Someone else needs these exact items for a personal reason — medical, financial, survival. They are willing to fight for them.",
     "mechanic": "DC 14 Persuasion to find a solution. Failure: 1 desperate soul (CR 1), fights with everything they have."},
    {"type": "combat", "title": "Summoning Accident",
     "desc": "A summoning in an adjacent building goes wrong. Something comes through a wall into the gather area.",
     "mechanic": "Random CR-appropriate creature, confused and aggressive. Defeating it leaves a summoning circle worth investigating."},
    {"type": "combat", "title": "Assassination Attempt",
     "desc": "An assassin from the opposing faction knew the party would be here. They did not come to talk.",
     "mechanic": "1 assassin (CR 8 equivalent, scales to tier). Sneak attack round 1, then full combat."},
]


# ---------------------------------------------------------------------------
# Reward scaling
# ---------------------------------------------------------------------------

def _reward_outcome(quota: int, gathered: int) -> Dict:
    pct = gathered / max(quota, 1)
    if pct >= 1.2:
        return {"label": "Surplus",         "pay_mult": 1.25, "rep": +1,  "contact_mood": "joy"}
    if pct >= 1.0:
        return {"label": "Full quota",      "pay_mult": 1.0,  "rep":  0,  "contact_mood": "satisfied"}
    if pct >= 0.75:
        return {"label": "Short — minor",   "pay_mult": 0.75, "rep":  0,  "contact_mood": "disappointed"}
    if pct >= 0.5:
        return {"label": "Short — major",   "pay_mult": 0.5,  "rep": -1,  "contact_mood": "angry"}
    if pct > 0.0:
        return {"label": "Near failure",    "pay_mult": 0.25, "rep": -1,  "contact_mood": "cold"}
    return     {"label": "Complete failure","pay_mult": 0.0,  "rep": -2,  "contact_mood": "shut_down"}

CONTACT_MOOD_TEXT = {
    "joy":        "They light up when they see you coming. Count before you've even set the bag down.",
    "satisfied":  "They nod, check the goods efficiently, and pay without drama.",
    "disappointed":"They take the goods in silence. You can see them doing the math. They'll remember this.",
    "angry":      "They don't hide it. Every word is clipped. Payment is made, barely, and you're not invited back soon.",
    "cold":       "They take what you brought. Say nothing. The door doesn't quite slam, but it wants to.",
    "shut_down":  "They look at what you returned with, then at you. Then they close the ledger. No payment. No words.",
}


# ---------------------------------------------------------------------------
# NPC contact lookup
# ---------------------------------------------------------------------------

def _get_faction_contact(faction: str) -> Dict:
    """Pull a live NPC from the faction roster."""
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT name, role, location, description FROM npcs "
            "WHERE faction = %s AND status = 'alive' ORDER BY RAND() LIMIT 1",
            (faction,)
        )
        if rows:
            return rows[0]
    except Exception as e:
        logger.warning(f"[GATHER] NPC lookup failed: {e}")
    return {"name": "the contact", "role": "faction representative", "location": "", "description": ""}


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

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


async def _ollama(prompt: str, system: str = "", tokens: int = 1200) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model":    OLLAMA_MODEL,
        "messages": messages,
        "stream":   False,
        "options":  {"temperature": 0.85, "num_predict": tokens, "num_ctx": _fit_ctx(system + prompt, tokens)},
    }
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("gather_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[GATHER] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[GATHER] Ollama error: {e}")
        return ""


def _clean_json(raw: str) -> str:
    raw = raw.replace("\x5c\x27", "\x27")
    raw = raw.replace("\u2018", "'").replace("\u2019", "'")
    raw = raw.replace("\u201c", '"').replace("\u201d", '"')
    raw = raw.replace("\u2013", "-").replace("\u2014", "-")
    cleaned, in_string, i = [], False, 0
    while i < len(raw):
        ch = raw[i]
        if ch == '"' and (i == 0 or raw[i-1] != "\\"):
            in_string = not in_string
            cleaned.append(ch)
        elif in_string and ord(ch) in (10, 13):
            cleaned.append(" ")
        else:
            cleaned.append(ch)
        i += 1
    return "".join(cleaned)


def _parse_json(raw: str) -> Optional[dict]:
    for attempt in (raw, _clean_json(raw)):
        m = re.search(r"\{[\s\S]*\}", attempt)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Generation steps
# ---------------------------------------------------------------------------

async def _generate_contact_scene(
    mission: dict,
    contact: Dict,
    gather_profile: Dict,
    item: str,
    quota: int,
    meet_location: str,
) -> Dict:
    title    = mission.get("title", "Gathering Contract")
    faction  = mission.get("faction", "Independent")
    body     = mission.get("body") or mission.get("description") or ""

    prompt = f"""You are writing Scene 1 of a D&D gathering mission module.

Contact NPC: {contact.get('name','the contact')} — {contact.get('role','')} of {faction}
Meeting location: {meet_location}
What they want gathered: {item}
Quantity needed (quota): {quota}
Handling notes: {gather_profile['handling']}
Mission background: {body[:500]}

Write:
1. A brief scene-setting description of the meeting location (2 sentences)
2. The contact's opening — their personality, how they greet the party (warm/cold/nervous/businesslike based on faction culture)
3. The contact's motivation — WHY does this specific contact personally need the party for this specific item right now? (1-2 sentences, personal stakes or urgency, not just "faction needs it")
4. The negotiation beats — what the party can push for and what the contact will reveal under pressure
5. A Persuasion or Insight hook (DC 13) — what the party learns if they roll well (a second location, a rival also gathering, a handling hazard, a shortcut)
6. The send-off — where they're told to go and what to look for

The gather_location must be a SPECIFIC named place — a real district, street, landmark, park, garden,
plaza, or point of interest. Choose from places like: Grand Forum, The Garden of Accord, Cobbleway
Market, Spice Alley, Floating Bazaar, The Promenade, Neon Row, Hearthstone Market Square, Duskhollow
Night Market, Collapsed Plaza, Pantheon Walk, Scrapworks, Artisan Quarter, The Fringe, Shantytown
Heights, Artisan Cellars, Coppergate Cellars, The Reliquary, Night Pits. Pick whichever fits the
item being gathered and the faction — parks and open plazas for herbs/outdoor items, archives and
vaults for documents, markets for goods, ruins for salvage.

Return JSON only:
{{
  "scene_desc": "...",
  "contact_intro": "...",
  "contact_motivation": "1-2 sentences on why this contact specifically needs the party for this right now",
  "negotiation_beats": ["beat 1", "beat 2", "beat 3"],
  "insight_hook": "what a good roll reveals",
  "sendoff": "...",
  "gather_location": "specific named place in the city",
  "world_consequence": "1-2 sentences: what changes in the city or for the faction because this gather was completed — the real-world outcome beyond just the reward"
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    if not data:
        data = {
            "scene_desc":         f"{contact.get('name','The contact')} meets you at {meet_location}.",
            "contact_intro":      f"They get straight to it. {quota} units of {item}. You know where to look.",
            "contact_motivation": f"{contact.get('name','The contact')} needs this before their window closes — a rival order arrives tomorrow and {faction} gets nothing.",
            "negotiation_beats":  ["Standard pay up front", "Bonus for surplus", "Don't damage them"],
            "insight_hook":       "A good Insight roll reveals they know of a backup location if the first is dry.",
            "sendoff":            f"Head to the {gather_profile['examples'][0]} district. You'll know them when you see them.",
            "gather_location":    "the market district",
            "world_consequence":  f"{faction} secures its supply line. Without this, a planned operation stalls for a week.",
        }
    return data


async def _generate_item_details(
    faction: str,
    gather_profile: Dict,
    tier: str,
) -> Dict:
    """Pick a specific item from the faction's gather list and define quota/stock."""
    item = random.choice(gather_profile["examples"])
    fragility = gather_profile["fragility"]
    dc_table  = FRAGILITY_DC.get(fragility, FRAGILITY_DC["medium"])
    dc        = dc_table.get(tier, 14)

    skills = GATHER_SKILLS.get(gather_profile["item_category"], ["Investigation", "Perception"])
    primary_skill   = skills[0]
    secondary_skill = skills[1] if len(skills) > 1 else skills[0]

    # Quota and stock: stock is quota + 1 to several extras depending on fragility
    quota_map  = {"standard": (3,5), "seasoned": (4,6), "elite": (5,8), "legend": (6,10)}
    q_lo, q_hi = quota_map.get(tier, (3,5))
    quota      = random.randint(q_lo, q_hi)

    # Stock extras: extreme fragility = barely any surplus, low = plenty of room
    surplus_map = {"low": (3,6), "medium": (2,4), "high": (1,3), "extreme": (1,2)}
    s_lo, s_hi  = surplus_map.get(fragility, (2,4))
    stock       = quota + random.randint(s_lo, s_hi)

    return {
        "item":           item,
        "quota":          quota,
        "stock":          stock,
        "dc":             dc,
        "primary_skill":  primary_skill,
        "secondary_skill":secondary_skill,
        "fragility":      fragility,
        "handling":       gather_profile["handling"],
    }


async def _generate_gather_location_desc(
    gather_location: str,
    item: str,
    faction: str,
) -> str:
    prompt = f"""Write a 2-sentence read-aloud description of arriving at a gather location in a high fantasy cyberpunk city.

Location: {gather_location}
What's being searched for: {item}
Requesting faction: {faction}

Keep it atmospheric and specific to the location. No JSON — just the description text."""

    text = await _ollama(prompt, tokens=200)
    return text or (
        f"You reach {gather_location}. Foot traffic, vendors, and the day's noise wash over the place; "
        f"the {item} the contact wants is here, but scattered - tucked in corners, stalls, and the spots "
        f"locals would rather you did not poke at. Work the area methodically and watch who is watching you."
    )


async def _generate_debrief_lines(
    contact: Dict,
    faction: str,
    item: str,
    outcome: Dict,
    gathered: int,
    quota: int,
) -> str:
    mood  = outcome["contact_mood"]
    label = outcome["label"]

    prompt = f"""Write the debrief scene for a D&D gathering mission.

Contact: {contact.get('name','the contact')} — {contact.get('role','')} of {faction}
Item gathered: {item}
Quota: {quota} | Gathered: {gathered} | Result: {label}
Contact mood: {mood}

Write 2-3 sentences of dialogue from the contact. Their mood:
- joy: genuinely pleased, maybe surprised, warm and open
- satisfied: professional, efficient, no complaints
- disappointed: quiet, controlled, clearly calculating the shortfall
- angry: barely contained, clipped words, makes the party feel it
- cold: minimal words, no eye contact, transaction only
- shut_down: the ledger closes. Nothing.

No JSON — just the contact's words."""

    text = await _ollama(prompt, tokens=300)
    return text or CONTACT_MOOD_TEXT.get(mood, "They take the goods without a word.")


# ---------------------------------------------------------------------------
# A1111 map
# ---------------------------------------------------------------------------

def _gather_map_style(location: str) -> str:
    loc_low = location.lower()
    for key, style in _GATHER_LOCATION_STYLES:
        if key in loc_low:
            return style
    # Default — outdoor city street
    return "Town Exterior Table Map, cobblestone road, building facades, lamp posts, vendor stalls, crowd flow paths"


async def _generate_gather_map(
    gather_location: str,
    item: str,
    faction: str,
    out_dir: Path,
) -> Optional[Path]:
    out = out_dir / "gather_map.png"
    from src.battle_map_library import copy_library_map_for_mission
    return copy_library_map_for_mission(
        {"faction": faction},
        out,
        mission_type="gather",
        location_name=gather_location,
        description=item,
    )

def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _encounter_card(enc: Dict, idx: int) -> str:
    type_color = {"comedic": "#8b5cf6", "inconvenient": "#d97706", "combat": "#dc2626"}.get(enc["type"], "#555")
    type_label = {"comedic": "Comedic / Social", "inconvenient": "Inconvenient", "combat": "Rare Combat"}.get(enc["type"], enc["type"].title())
    return (
        f'<div style="border-left:4px solid {type_color};padding:10px 14px;margin:8px 0;background:#fafafa;border-radius:0 6px 6px 0;">'
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">'
        f'<span style="font-weight:bold;font-size:14px;">{_e(enc["title"])}</span>'
        f'<span style="font-size:11px;color:{type_color};border:1px solid {type_color};padding:1px 6px;border-radius:10px;">{type_label}</span>'
        f'</div>'
        f'<div style="font-size:13px;margin:4px 0;">{_e(enc["desc"])}</div>'
        f'<div style="font-size:12px;color:#555;margin-top:4px;font-style:italic;">{_e(enc["mechanic"])}</div>'
        f'</div>'
    )


def _quota_track(quota: int, stock: int) -> str:
    """Checkbox track: quota boxes in gold, surplus boxes in grey."""
    boxes = ""
    for i in range(stock):
        color = "#b8923a" if i < quota else "#aaa"
        label = "quota" if i < quota else "surplus"
        boxes += (
            f'<input type="checkbox" title="{label}" '
            f'style="width:20px;height:20px;margin:2px;accent-color:{color};">'
        )
    return (
        f'<div style="margin:12px 0;">'
        f'<div style="font-size:12px;color:#666;margin-bottom:6px;">'
        f'<span style="color:#b8923a;font-weight:bold;">■</span> Quota ({quota}) &nbsp;'
        f'<span style="color:#aaa;font-weight:bold;">■</span> Surplus stock ({stock - quota} extra available)'
        f'</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:2px;">{boxes}</div>'
        f'</div>'
    )


# Distinct micro-spots so the gather phase is not N identical "Religion DC 15"
# boxes. Location-agnostic but evocative; some carry a small mechanical wrinkle.
# Local to the gather pipeline by design (project rule: pipelines stay independent).
GATHER_SPOTS = [
    "Tucked behind a cracked planter near the entrance - easy reach, no complication.",
    "Wedged under a collapsed shelf; clear the debris first (Athletics DC 12 or lose the attempt).",
    "In plain sight on a vendor's table - but the vendor is watching (Sleight of Hand, or simply buy it).",
    "Down a damp side-passage where the light fails (disadvantage unless a light source is lit).",
    "High on a ledge; a quick climb (Acrobatics DC 12) grants advantage on this gather.",
    "Half-buried in a refuse pile - unpleasant but unguarded.",
    "Inside a locked supply chest (Thieves' Tools DC 13, or the contact's key if earned).",
    "Guarded by a territorial stray; calm it (Animal Handling DC 11) or work around it.",
    "Settled in a stagnant cistern; fish it out without fouling it (Sleight of Hand DC 13).",
    "Behind a chalk-marked false wall a previous crew left (Investigation DC 12 to confirm it is safe).",
    "Among a street shrine's offerings - taking it risks local ire unless handled with care.",
    "Fresh and exposed at the open center of the area: fast, but visible to everyone present.",
]

# Varied success/failure narration so per-attempt outcomes are not identical text.
_GATHER_RESULTS = [
    ("the sample comes away clean and whole (+1 gathered)", "it crumbles or spoils in your hands -- lost (-1 stock)"),
    ("you secure it without drawing notice (+1 gathered)", "you fumble it; it is damaged or someone sees (-1 stock)"),
    ("it is exactly what the contact described (+1 gathered)", "it turns out tainted or wrong -- discard it (-1 stock)"),
    ("you bag it fast and move on (+1 gathered)", "you knock it loose into the muck -- gone (-1 stock)"),
    ("a clean lift, no fuss (+1 gathered)", "it slips, breaks, or a passer-by clocks you (-1 stock)"),
]


def _skill_check_card(item_data: Dict, check_num: int, encounters_between: List[Dict], spot: str = "") -> str:
    enc_html = "".join(_encounter_card(e, i) for i, e in enumerate(encounters_between))
    enc_section = (
        f'<div style="margin:10px 0 0 0;">'
        f'<div style="font-size:12px;font-weight:bold;color:#666;margin-bottom:4px;">BETWEEN-CHECK ENCOUNTER (roll if triggered)</div>'
        f'{enc_html}'
        f'</div>'
    ) if enc_html else ""

    spot_html = (
        f'<div style="font-size:12px;color:#6a5a3a;font-style:italic;margin:2px 0 6px;">Spot: {_e(spot)}</div>'
        if spot else ""
    )

    # Contextual setup + result narration for this check (item-aware, varied).
    _item = item_data.get("item", "the item")
    _succ, _fail = _GATHER_RESULTS[(check_num - 1) % len(_GATHER_RESULTS)]
    narration_html = (
        f'<div style="font-size:12px;color:#555;margin:4px 0;border-left:3px solid #b8923a;padding-left:8px;">'
        f'<strong style="color:#5a4020;">Setup:</strong> Work {_e(_item)} loose from this spot without ruining it. '
        f'<strong style="color:#2a6a2a;">Success:</strong> {_succ}. '
        f'<strong style="color:#9a2a2a;">Failure:</strong> {_fail}.'
        f'</div>'
    )

    return (
        f'<div style="border:1px solid #b8923a;border-radius:8px;padding:14px 18px;margin:12px 0;background:#fffdf5;">'
        f'<div style="font-weight:bold;font-size:15px;margin-bottom:8px;">Gather Attempt {check_num}</div>'
        + spot_html
        + f'<div style="font-size:13px;margin:4px 0;">'
        f'<strong>Primary:</strong> {_e(item_data["primary_skill"])} DC {item_data["dc"]} &nbsp;|&nbsp; '
        f'<strong>Alt:</strong> {_e(item_data["secondary_skill"])} DC {item_data["dc"] + 2}'
        f'</div>'
        f'<div style="font-size:12px;color:#555;margin:4px 0;">'
        f'<strong>Success:</strong> +1 item gathered &nbsp;|&nbsp; '
        f'<strong>Failure:</strong> -1 from available stock (item lost/damaged/uncollectable)'
        f'</div>'
        + narration_html
        + f'<div style="margin:8px 0;">'
        f'<input type="checkbox" id="gc{check_num}s" style="accent-color:#2a6a2a;"> <label for="gc{check_num}s" style="color:#2a6a2a;">Success</label> &nbsp;&nbsp;'
        f'<input type="checkbox" id="gc{check_num}f" style="accent-color:#c82020;"> <label for="gc{check_num}f" style="color:#c82020;">Failure (stock -1)</label>'
        f'</div>'
        + enc_section
        + f'</div>'
    )


def render_gather_module(
    mission: dict,
    contact: Dict,
    gather_profile: Dict,
    item_data: Dict,
    contact_scene: Dict,
    location_desc: str,
    selected_encounters: List[Dict],
    strength: Dict[str, Any],
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title    = mission.get("title", "Gathering Contract")
    faction  = mission.get("faction", "Independent")
    fc       = _faction_color(faction)
    item     = item_data["item"]
    quota    = item_data["quota"]
    stock    = item_data["stock"]

    map_html = ""
    if map_path and map_path.exists():
        rel = map_path.relative_to(out_dir)
        map_html = (
            f'<div style="text-align:center;margin:20px 0;">'
            f'<img src="{rel}" style="max-width:100%;border:3px solid {fc};border-radius:8px;" alt="Gather Location Map">'
            f'<div style="font-size:12px;color:#888;margin-top:4px;">Gather location — {_e(contact_scene.get("gather_location",""))}</div>'
            f'</div>'
        )

    # Negotiation beats
    beats_html = "".join(f'<li style="margin:4px 0;">{_e(b)}</li>' for b in contact_scene.get("negotiation_beats", []))

    # Skill check cards — one per gather attempt (quota + a few extra for stock)
    check_cards = ""
    enc_pool = list(selected_encounters)
    random.shuffle(enc_pool)
    # Distinct spot per attempt so the gather phase is not a wall of identical boxes.
    spots = random.sample(GATHER_SPOTS, min(stock, len(GATHER_SPOTS)))
    while len(spots) < stock:
        spots.append(random.choice(GATHER_SPOTS))
    for i in range(1, stock + 1):
        # Give each 2nd check an encounter
        between = [enc_pool.pop(0)] if (i % 2 == 0 and enc_pool) else []
        check_cards += _skill_check_card(item_data, i, between, spots[i - 1])

    # Encounter reference — all selected encounters
    all_enc_html = "".join(_encounter_card(e, i) for i, e in enumerate(selected_encounters))
    scaling_html = (
        f'<div style="background:#eef6ff;border:1px solid #3a6898;border-radius:6px;'
        f'padding:10px 14px;margin:14px 0;font-size:13px;">'
        f'<strong>Live Party Scaling:</strong> {_e(_party_scaling_note(strength))} '
        f'Quota, stock, and gather DC are tuned from this read.</div>'
    )

    # Reward table
    reward_rows = ""
    for label, pct, rep, mood in [
        ("Surplus (120%+)",     1.25, "+1 rep",  "Joy"),
        ("Full quota (100%)",   1.0,  "No change","Satisfied"),
        ("Short minor (75%+)",  0.75, "No change","Disappointed"),
        ("Short major (50%+)",  0.5,  "-1 rep",   "Angry"),
        ("Near failure (>0%)",  0.25, "-1 rep",   "Cold"),
        ("Complete failure",    0.0,  "-2 rep",   "Shuts down"),
    ]:
        reward_rows += (
            f'<tr><td style="padding:6px 10px;">{label}</td>'
            f'<td style="padding:6px 10px;text-align:center;">{pct:.0%}</td>'
            f'<td style="padding:6px 10px;text-align:center;">{rep}</td>'
            f'<td style="padding:6px 10px;">{mood}</td></tr>'
        )

    body = f"""
<div style="border-left:4px solid {fc};padding:12px 18px;margin:20px 0;background:#fafafa;border-radius:0 8px 8px 0;">
  <h2 style="margin:0 0 8px;">Scene 1 — Meeting at {_e(contact_scene.get('gather_location','the meeting point'))}</h2>
  <div style="font-size:13px;color:#555;margin-bottom:10px;font-style:italic;">{_e(contact_scene.get('scene_desc',''))}</div>
  <div style="margin:10px 0;">
    <strong>{_e(contact.get('name','Contact'))}</strong> — {_e(contact.get('role',''))}
  </div>
  <div style="white-space:pre-line;font-style:italic;margin:10px 0;">{_e(contact_scene.get('contact_intro',''))}</div>
  <h3 style="margin:12px 0 6px;">Negotiation Beats</h3>
  <ul style="margin:0 0 10px;padding-left:20px;">{beats_html}</ul>
  <div style="background:#e8f0f8;border-radius:6px;padding:10px 14px;font-size:13px;">
    <strong>Insight / Persuasion DC 13:</strong> {_e(contact_scene.get('insight_hook',''))}
  </div>
  <div style="margin-top:12px;font-style:italic;">{_e(contact_scene.get('sendoff',''))}</div>
</div>

{scaling_html}

<h2>Scene 2 — The Gather</h2>
<div style="font-style:italic;margin-bottom:12px;">{_e(location_desc)}</div>

{map_html}

<div style="background:#fff8e6;border:1px solid #b8923a;border-radius:8px;padding:14px 18px;margin:16px 0;">
  <div style="display:flex;gap:32px;flex-wrap:wrap;">
    <div><strong>Item:</strong> {_e(item)}</div>
    <div><strong>Quota:</strong> {quota}</div>
    <div><strong>Stock available:</strong> {stock}</div>
    <div><strong>Primary skill:</strong> {_e(item_data['primary_skill'])} DC {item_data['dc']}</div>
    <div><strong>Handling:</strong> {_e(item_data['handling'])}</div>
  </div>
  {_quota_track(quota, stock)}
</div>

<h3>Gather Attempts</h3>
<div style="font-size:12px;color:#666;margin-bottom:8px;">
  Work through attempts in order. When stock hits zero, the area is depleted —
  quota not met means returning to the contact short.
</div>
{check_cards}

<hr>

<h2>Encounter Table</h2>
<div style="font-size:12px;color:#666;margin-bottom:10px;">
  Roll or choose when triggered between gather checks. DM may use any encounter regardless of sequence.
</div>
{all_enc_html}

<hr>

<h2>Scene 3 — The Debrief</h2>
<h3>Reward Scaling</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px;">
  <thead><tr style="background:#e8e0d0;">
    <th style="padding:6px 10px;text-align:left;">Result</th>
    <th style="padding:6px 10px;">Pay</th>
    <th style="padding:6px 10px;">Rep</th>
    <th style="padding:6px 10px;text-align:left;">Contact mood</th>
  </tr></thead>
  <tbody>{reward_rows}</tbody>
</table>

<div style="margin-top:20px;">
  <h3>Contact Reaction by Mood</h3>
  {"".join(
    f'<div style="margin:8px 0;padding:10px 14px;background:#f5f5f5;border-radius:6px;font-size:13px;">'
    f'<strong style="text-transform:capitalize;">{mood}:</strong> <em>{_e(text)}</em></div>'
    for mood, text in CONTACT_MOOD_TEXT.items()
  )}
</div>

<hr>

<h2>Debrief Record</h2>
<div style="background:#e8f5e8;border:1px solid #2a6a2a;border-radius:6px;padding:14px 18px;">
  <p><strong>Items gathered:</strong> <input type="number" min="0" max="{stock}" style="width:60px;"> / {quota} quota</p>
  <p><strong>Result:</strong> <select style="font-family:inherit;">
    <option>Surplus</option><option>Full quota</option><option>Short — minor</option>
    <option>Short — major</option><option>Near failure</option><option>Complete failure</option>
  </select></p>
  <p><strong>Encounters triggered:</strong> <input type="number" style="width:50px;"></p>
  <textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Session notes..."></textarea>
</div>
"""

    from src.treasure import loot_card as _loot_card
    body += _loot_card(mission)
    return _page(title, body, faction)


def render_gather_session(
    mission: dict,
    contact: Dict,
    contact_scene: Dict,
    item_data: Dict,
    selected_encounters: List[Dict],
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title    = mission.get("title", "Gathering Contract")
    faction  = mission.get("faction", "Independent")
    fc       = _faction_color(faction)
    item     = item_data["item"]
    quota    = item_data["quota"]
    stock    = item_data["stock"]

    def _card(heading: str, content: str, color: str = "#b8923a") -> str:
        return (
            f'<div style="border:2px solid {color};border-radius:10px;padding:18px 22px;'
            f'margin:20px 0;background:white;">'
            f'<h2 style="margin:0 0 12px;color:{color};">{heading}</h2>'
            f'{content}'
            f'</div>'
        )

    cards = ""

    # Contact card
    cards += _card(
        f"Scene 1 — {_e(contact.get('name','Contact'))} at {_e(contact_scene.get('gather_location',''))}",
        f'<p style="font-style:italic;">{_e(contact_scene.get("contact_intro","")[:400])}</p>'
        f'<p><strong>Insight DC 13:</strong> {_e(contact_scene.get("insight_hook",""))}</p>'
        f'<p style="font-style:italic;">{_e(contact_scene.get("sendoff",""))}</p>',
        fc,
    )

    # Gather card with quota track
    map_html = ""
    if map_path and map_path.exists():
        rel = map_path.relative_to(out_dir)
        map_html = f'<img src="{rel}" style="max-width:100%;border-radius:6px;margin:10px 0;" alt="Map">'

    gather_content = (
        f'{map_html}'
        f'<div style="margin:8px 0;"><strong>Item:</strong> {_e(item)} &nbsp;|&nbsp; <strong>Quota:</strong> {quota} &nbsp;|&nbsp; <strong>Stock:</strong> {stock}</div>'
        f'<div style="margin:8px 0;"><strong>Check:</strong> {_e(item_data["primary_skill"])} DC {item_data["dc"]} (alt: {_e(item_data["secondary_skill"])} DC {item_data["dc"]+2})</div>'
        f'{_quota_track(quota, stock)}'
        f'<div style="font-size:12px;color:#555;margin-top:8px;">Failure = stock -1. When stock = 0, area depleted.</div>'
    )
    cards += _card("Scene 2 — The Gather", gather_content, "#b8923a")

    # Encounter quick-ref card
    enc_lines = "".join(
        f'<div style="padding:4px 0;border-bottom:1px solid #eee;font-size:12px;">'
        f'<strong>{_e(e["title"])}</strong> — {_e(e["desc"][:80])}...</div>'
        for e in selected_encounters[:8]
    )
    cards += _card("Encounter Quick-Ref", enc_lines, "#8b5cf6")

    # Debrief card
    cards += _card(
        f"Scene 3 — Debrief with {_e(contact.get('name','Contact'))}",
        f'<p><strong>Items gathered:</strong> <input type="number" min="0" max="{stock}" style="width:60px;"> / {quota}</p>'
        f'<p><strong>Outcome:</strong> <select style="font-family:inherit;">'
        f'<option>Surplus</option><option>Full quota</option><option>Short — minor</option>'
        f'<option>Short — major</option><option>Near failure</option><option>Complete failure</option>'
        f'</select></p>'
        f'<textarea rows="2" style="width:100%;font-family:inherit;" placeholder="Notes..."></textarea>',
        "#2a6a2a",
    )

    body = (
        f'<div style="text-align:center;margin:0 0 24px;">'
        f'<h1 style="color:{fc};">{_e(title)}</h1>'
        f'<div style="font-size:14px;color:#666;">{_e(faction)} — Gathering: {_e(item_data["item"])}</div>'
        f'</div>'
        + cards
    )
    return _page(title, body, faction)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


def _party_strength() -> Dict[str, Any]:
    """Read live PC snapshots; copied here so gather stays standalone."""
    pcs = []
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC"
        ) or []
        for row in rows:
            snap = row.get("snapshot_json") or {}
            if isinstance(snap, str):
                try:
                    snap = json.loads(snap)
                except Exception:
                    snap = {}
            if not isinstance(snap, dict):
                continue
            level = int(snap.get("total_level") or 0)
            if level <= 0:
                continue
            pcs.append({
                "name": snap.get("name") or row.get("char_name"),
                "level": level,
                "max_hp": int(snap.get("max_hp") or 0),
            })
    except Exception as e:
        logger.warning(f"[GATHER] Could not read live party snapshots: {e}")
    levels = [p["level"] for p in pcs] or [5]
    return {
        "party_size": len(pcs) or 4,
        "avg_level": round(sum(levels) / len(levels), 1),
        "max_level": max(levels),
        "pcs": pcs,
    }


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    return (
        f"Live party read: {strength['party_size']} PCs, average level "
        f"{strength['avg_level']}, max level {strength['max_level']}."
    )


async def build_gather_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    """Full gather pipeline. Returns path to index.html."""
    title   = mission.get("title", "Gathering Contract")
    faction = mission.get("faction", "Independent")
    tier    = mission.get("tier", "standard")

    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[GATHER] Building: {title!r} | faction={faction} | tier={tier}")

    strength       = _party_strength()
    gather_profile = _get_gather_profile(faction)
    contact        = _get_faction_contact(faction)
    item_data      = await _generate_item_details(faction, gather_profile, tier)
    pressure       = max(0, strength["party_size"] - 4)
    level_pressure = max(0, strength["max_level"] - 5)
    item_data["quota"] = int(item_data.get("quota", 4)) + (pressure // 2)
    item_data["stock"] = max(int(item_data.get("stock", item_data["quota"] + 2)), item_data["quota"] + 2 + (pressure // 3))
    item_data["dc"] = int(item_data.get("dc", 13)) + min(4, (pressure // 3) + (level_pressure // 2))
    meet_location  = random.choice(gather_profile["meet_locations"])

    logger.info(f"[GATHER] Item={item_data['item']} | quota={item_data['quota']} | stock={item_data['stock']} | DC={item_data['dc']}")

    # Contact scene and location desc can run concurrently
    contact_scene_task = asyncio.create_task(
        _generate_contact_scene(mission, contact, gather_profile, item_data["item"], item_data["quota"], meet_location)
    )
    contact_scene = await contact_scene_task
    gather_location = contact_scene.get("gather_location", "the market district")

    location_desc = await _generate_gather_location_desc(gather_location, item_data["item"], faction)

    # Select encounters — mix of types, roughly: 60% comedic, 30% inconvenient, 10% combat
    comedic     = [e for e in ENCOUNTERS if e["type"] == "comedic"]
    inconvenient= [e for e in ENCOUNTERS if e["type"] == "inconvenient"]
    combat      = [e for e in ENCOUNTERS if e["type"] == "combat"]
    n_enc       = item_data["stock"] // 2 + 2  # roughly half the checks get an encounter
    selected = (
        random.sample(comedic,      min(int(n_enc * 0.6), len(comedic)))
        + random.sample(inconvenient, min(int(n_enc * 0.3), len(inconvenient)))
        + random.sample(combat,       min(max(1, int(n_enc * 0.1)), len(combat)))
    )
    random.shuffle(selected)

    # A1111 map
    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        map_path = await _generate_gather_map(gather_location, item_data["item"], faction, out_dir)

    from src.mission_builder.mimir_module import create_module as _mc, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd, enrich_mission_loot as _mel
    _mimir_id = await _mc(mission, mission_type="gather")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Gather Map")
    # Render HTML
    module_html = render_gather_module(
        mission, contact, gather_profile, item_data,
        contact_scene, location_desc, selected, strength, map_path, out_dir,
    )
    _loot_rewards = await _mel(_mimir_id or "", mission)
    module_html += _ms([], _loot_rewards, _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")

    session_html = render_gather_session(
        mission, contact, contact_scene, item_data, selected, map_path, out_dir,
    )
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    dm_md = (
        f"## Gather DM Guide\n"
        f"### Contact Scene\n"
        f"- Contact: {contact.get('name')} ({contact.get('role')})\n"
        f"- Meeting location: {meet_location}\n"
        f"- Gather location: {gather_location}\n"
        f"- Item: {item_data['item']}\n"
        f"- Quota: {item_data['quota']} from stock {item_data['stock']}\n"
        f"- DC: {item_data['dc']}\n\n"
        f"### Location\n{location_desc}\n\n"
        f"### Contact Brief\n{contact_scene.get('speech', contact_scene.get('contact_speech', ''))}\n\n"
        f"### Live Scaling\n{_party_scaling_note(strength)}"
    )
    players_md = (
        f"## Player Gather Guide\n"
        f"### Public Assignment\n"
        f"- Faction: {faction}\n"
        f"- Contact: {contact.get('name')}\n"
        f"- Item needed: {item_data['item']}\n"
        f"- Quota: {item_data['quota']}\n"
        f"- Known location: {gather_location}\n\n"
        f"### Handling\n{item_data.get('handling', 'Bring back the requested goods intact.')}"
    )
    chart_md = (
        f"## Gather Chart Pack\n"
        f"### Gather Check\n"
        f"- Skill DC: {item_data['dc']}\n"
        f"- Quota: {item_data['quota']}\n"
        f"- Available stock: {item_data['stock']}\n\n"
        f"### Encounters\n"
        + "\n".join(f"| {e.get('title')} | {e.get('type')} | {e.get('mechanic')} |" for e in selected)
        + "\n\n### Useful Skills\n"
        + "\n".join(f"- {category}: {', '.join(skills)}" for category, skills in GATHER_SKILLS.items())
        + "\n\n### Fragility DCs\n"
        + "\n".join(f"| {fragility} | standard {dcs['standard']} | seasoned {dcs['seasoned']} | elite {dcs['elite']} | legend {dcs['legend']} |" for fragility, dcs in FRAGILITY_DC.items())
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, faction, players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",      "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",           "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Quota & Encounters", "type": "custom",      "content": chart_md},
        ])
    maps_name = write_maps_page(out_dir, title, faction, [map_path] if map_path else [])
    box_components = component_links(has_maps=bool(maps_name))

    # Index
    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title,
            faction=faction,
            tier=tier,
            cr=mission_cr(mission),
            player_name=mission.get("player_name", "") or "Open",
            chapters=[],
            components=box_components,
            chart_pack=None,
            map_count=1 if map_path else 0,
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as _e:
        logger.warning(f"[GATHER] index.html failed: {_e}")
        index_path = out_dir / "module.html"

    # DB slug
    try:
        from src.mission_builder.mission_db import write_module_slug_for_mission
        write_module_slug_for_mission(mission, out_dir.name, log_prefix="GATHER")
    except Exception as _e:
        logger.warning(f"[GATHER] Could not write module_slug: {_e}")

    # Zip
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[GATHER] Complete: {title!r} → {out_dir.name}")
    return index_path
