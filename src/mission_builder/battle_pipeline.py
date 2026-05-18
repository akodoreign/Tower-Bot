"""
battle_pipeline.py — Pipeline for Battle mission modules.

A battle is a large-scale clash the party is hired into before it begins.
Three conflict types: faction vs faction, faction vs void/rift creatures,
or a monster breakout from a contained source.

The party fights a series of pocket fights within the larger battle.
Allies can provide support between fights; enemies can receive reinforcements.
An optional Glory Fight can slot between any two pocket fights — a high-risk
engagement with a notable enemy target for bonus rep and reward.

Flow:
  1. Conflict type determined from keywords / mission data
  2. Briefing — hiring faction, opposing side, location, 5-day max timer
  3. Pocket fights — 3 (monster) or 4 (faction vs faction), each with
       enemy force scaled to party CR+4, optional reinforcement
  4. Glory Fight — optional, slottable between fights 1-2 or 2-3,
       targets a high-value enemy (bannerman, cleric, siege operator)
  5. Support table — faction-appropriate ally actions available per fight
  6. Battle Tide tracker — tracks which side is winning across fights
  7. Map — one big contextual map, wide area, A1111 via EnvyFlux LoRA
  8. Debrief — battlefield survey then commander's tent / faction HQ
  9. index.html + session.html + zip + DB slug

Conflict Types:
  faction_vs_faction — two factions clashing, mercenary contract
  faction_vs_void    — faction vs rift-corrupted creatures, Glass Sigil primary issuer
  monster_breakout   — creatures escaped from sewers / secret lab / collapsed site

Exported:
    build_battle_module(mission: dict, out_dir: Path) -> Path
    is_battle_mission(mission_type: str) -> bool
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
from typing import Optional, Dict, List, Any, Tuple

import httpx

from src.log import logger
from src.mission_builder.html_renderer import _faction_color, _page
from src.mission_builder.cr_scaling import mission_cr, party_strength as _party_strength

OUTPUT_BASE  = Path(__file__).resolve().parent.parent.parent / "generated_modules"
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
A1111_URL    = os.getenv("A1111_URL", "http://127.0.0.1:7860")

MAX_TIMER_DAYS = 5


# ---------------------------------------------------------------------------
# Mission type detection
# ---------------------------------------------------------------------------

_BATTLE_KEYWORDS = {
    "battle", "war", "clash", "skirmish", "warfront", "open battle",
    "field battle", "street war", "mass combat", "conflict", "large scale",
    "all-out", "full assault", "city battle", "district war",
}

def is_battle_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _BATTLE_KEYWORDS)


# ---------------------------------------------------------------------------
# Conflict types
# ---------------------------------------------------------------------------

CONFLICT_TYPES: Dict[str, Dict] = {
    "faction_vs_faction": {
        "label":        "Faction War",
        "pocket_fights": 4,
        "bulletin_tone": "mercenary contract — professional, matter-of-fact, EC reward front and center",
        "map_hint":     "wide urban battle ground, barricades, rubble cover, flanking alleys",
        "debrief_location": "commander's field tent or nearest faction HQ",
        "enemy_label":  "Opposing Force",
        "reinforcement": "enemy squad trickles in — add grunts or a lieutenant",
        "tide_win":     "The faction's forces hold and push. The opposing line begins to fracture.",
        "tide_loss":    "The opposing force presses hard. Friendly lines are thinning.",
    },
    "faction_vs_void": {
        "label":        "Void Surge",
        "pocket_fights": 3,
        "bulletin_tone": "emergency dispatch — urgent, clinical, issued by Glass Sigil or Tower Authority",
        "map_hint":     "dungeon corrupted urban terrain, rift crack across floor, warped stone, containment markers",
        "debrief_location": "Glass Sigil monitoring post or nearest Warden outpost",
        "enemy_label":  "Void Creatures",
        "reinforcement": "a corrupted creature tears through from deeper in the rift — add one void monster",
        "tide_win":     "The void surge weakens. Creature density is dropping.",
        "tide_loss":    "More creatures are pouring through. The rift is widening.",
    },
    "monster_breakout": {
        "label":        "Breakout Containment",
        "pocket_fights": 3,
        "bulletin_tone": "sealed incident notice — terse, issued by Tower Authority or the site's owner, details withheld",
        "map_hint":     "dungeon sewer junction underground lab, tight stone corridors, drainage channels, blast doors",
        "debrief_location": "site supervisor's office or a sealed briefing room above the incident level",
        "enemy_label":  "Escaped Creatures",
        "reinforcement": "another creature breaks containment — add one monster from the source",
        "tide_win":     "Creature count is dropping. Containment is holding.",
        "tide_loss":    "More creatures are escaping the source. Containment has failed at another point.",
    },
}

# Primary void battle issuers — Glass Sigil first, others secondary
VOID_PRIMARY_FACTIONS = ["Glass Sigil", "Tower Authority", "Wardens of Ash"]

# ---------------------------------------------------------------------------
# Faction force profiles (standalone — not imported from other pipelines)
# ---------------------------------------------------------------------------

FACTION_FORCES: Dict[str, Dict] = {
    "Wardens of Ash": {
        "force_label":  "Ash Company",
        "grunt_label":  "Shield Wardens",
        "lt_label":     "Ash Captains",
        "base_morale":  22,
        "tactics":      "disciplined line, protect the weak, hold until relieved",
        "morale_note":  "hold long — they do not break for morale reasons easily",
        "support_style": "healing and shield wall — they protect the people around them",
    },
    "Tower Authority": {
        "force_label":  "Enforcement Column",
        "grunt_label":  "Enforcement Officers",
        "lt_label":     "Senior Inspectors",
        "base_morale":  18,
        "tactics":      "formation advance, crowd control, escalating response",
        "morale_note":  "professional — hold steady until command gives retreat order",
        "support_style": "volley of crossbow fire, arrest restraints on enemy lt, call backup",
    },
    "Patchwork Saints": {
        "force_label":  "Saint's Mob",
        "grunt_label":  "District Volunteers",
        "lt_label":     "Saint Wardens",
        "base_morale":  14,
        "tactics":      "guerrilla, street knowledge, improvised cover, protect locals",
        "morale_note":  "passionate but fragile — boost morale with a rousing moment",
        "support_style": "field medic, local shortcut revealed, civilian barricade",
    },
    "Argent Blades": {
        "force_label":  "Blade Company",
        "grunt_label":  "Blade Mercenaries",
        "lt_label":     "Blade Officers",
        "base_morale":  20,
        "tactics":      "professional advance, contract-focused, no heroics without pay",
        "morale_note":  "hold until they calculate the risk is no longer worth the EC",
        "support_style": "flanking unit, precision strike on enemy leader, equipment loan",
    },
    "Obsidian Lotus": {
        "force_label":  "Lotus Cell",
        "grunt_label":  "Lotus Agents",
        "lt_label":     "Cell Commanders",
        "base_morale":  16,
        "tactics":      "shadow strike, poison use, disappear and reappear elsewhere",
        "morale_note":  "operate in cells — loss of one cell does not shake the others",
        "support_style": "smoke screen, planted distraction, enemy lt suddenly neutralized",
    },
    "Iron Fang Consortium": {
        "force_label":  "Fang Security",
        "grunt_label":  "Security Contractors",
        "lt_label":     "Senior Contractors",
        "base_morale":  17,
        "tactics":      "asset protection, escalate force incrementally, document everything",
        "morale_note":  "fight until the contract says stop — then they walk",
        "support_style": "armoured vehicle escort, medical contractor, tactical overwatch",
    },
    "Glass Sigil": {
        "force_label":  "Sigil Response Team",
        "grunt_label":  "Sigil Operators",
        "lt_label":     "Senior Analysts",
        "base_morale":  15,
        "tactics":      "precision containment, rift-aware positioning, minimal collateral",
        "morale_note":  "not fighters by nature — confidence drops fast under sustained combat",
        "support_style": "rift suppression burst, real-time enemy tracking feed, arcane barrier",
    },
    "Serpent Choir": {
        "force_label":  "Choir Congregation",
        "grunt_label":  "Choir Devotees",
        "lt_label":     "Serpent Priors",
        "base_morale":  19,
        "tactics":      "ritual intimidation, poison, coordinated chant disruption",
        "morale_note":  "fanatical — losing a Prior actually increases devotee morale briefly",
        "support_style": "poisoned weapon blessings, fear chant to shake enemy morale, healer-prior",
    },
    "Wizards Tower": {
        "force_label":  "Tower Warband",
        "grunt_label":  "Tower Auxiliaries",
        "lt_label":     "Mage Supervisors",
        "base_morale":  13,
        "tactics":      "arcane bombardment from distance, barrier magic, terrain manipulation",
        "morale_note":  "intellectually brave but physically fragile — protect the mages",
        "support_style": "spell volley on enemy group, arcane barrier, levitation extraction",
    },
    "Brother Thane's Cult": {
        "force_label":  "Cult Faithful",
        "grunt_label":  "True Believers",
        "lt_label":     "Thane Devotees",
        "base_morale":  21,
        "tactics":      "overwhelming zeal, no retreat, sacrifice is honourable",
        "morale_note":  "nearly unbreakable morale — they do not value their own lives",
        "support_style": "martyr surge (sacrifices a follower to boost party), blessing of endurance",
    },
    "Independent": {
        "force_label":  "Hired Company",
        "grunt_label":  "Hired Fighters",
        "lt_label":     "Company Officers",
        "base_morale":  15,
        "tactics":      "flexible, paid work, no ideological attachment",
        "morale_note":  "hold while the money is good — EC bonuses restore morale mid-battle",
        "support_style": "backup fighters, field medic, cover fire",
    },
}

# ---------------------------------------------------------------------------
# Void creature types (corrupted by rift exposure)
# ---------------------------------------------------------------------------

VOID_CREATURES: List[Dict] = [
    {"name": "Corrupted Rats",        "cr": "1/4", "desc": "swarm of vermin whose eyes glow white — bites cause brief hallucinations",      "bulk": True},
    {"name": "Rift Crawler",          "cr": "2",   "desc": "spider-like thing assembled from reassembled city debris and void energy",       "bulk": False},
    {"name": "Corrupted Guard",       "cr": "3",   "desc": "a Tower Authority officer whose void exposure has rewritten their loyalty — fights without hesitation or pain", "bulk": False},
    {"name": "Void Hound",            "cr": "2",   "desc": "a city dog grown to twice its size, mouth full of crystallised rift matter",     "bulk": False},
    {"name": "Smear",                 "cr": "4",   "desc": "a former humanoid now a two-dimensional shadow that can slip under doors",       "bulk": False},
    {"name": "Corrupted Golem Shard", "cr": "5",   "desc": "a piece of a destroyed construct still animated by void static, grinding and sparking", "bulk": False},
    {"name": "Rift Bloom",            "cr": "1",   "desc": "an ambulatory fungal growth that releases void spores on damage",               "bulk": True},
    {"name": "Void Hulk",             "cr": "6",   "desc": "a thing the size of a horse made from fused, corrupted flesh — still recognisable as several creatures at once", "bulk": False},
]

# ---------------------------------------------------------------------------
# Breakout sources
# ---------------------------------------------------------------------------

BREAKOUT_SOURCES: List[Dict] = [
    {"name": "Sewer Junction",        "location_hint": "sewer tunnel, maintenance walkway, drainage channel",          "creature_type": "rats, gators, corrupted vermin"},
    {"name": "Abandoned Lab",         "location_hint": "underground laboratory, specimen tanks, containment cells",    "creature_type": "experiments, constructs, test subjects"},
    {"name": "Collapsed Market Vault","location_hint": "underground storage chamber, collapsed ceiling, old tunnels",  "creature_type": "whatever was stored or escaped from below"},
    {"name": "Old Arena Sub-Level",   "location_hint": "beast pens, sand pit access tunnel, rusted cages",            "creature_type": "arena beasts, escaped monsters"},
    {"name": "Warden Containment Pen","location_hint": "fortified lower level, heavy blast doors, emergency locks",   "creature_type": "creatures confiscated from black-market dealers"},
    {"name": "Glass Sigil Test Site", "location_hint": "rift monitoring chamber, containment wards, instrument racks", "creature_type": "void creatures attracted to active rift sensors"},
    {"name": "Forgotten Necropolis",  "location_hint": "ancient burial chamber, collapsed archway, bone-dust floors",  "creature_type": "undead disturbed by construction or rift activity"},
]

# ---------------------------------------------------------------------------
# Glory Fight targets
# ---------------------------------------------------------------------------

GLORY_TARGETS: List[Dict] = [
    {"name": "Enemy Bannerman",      "cr_bonus": 2, "reward_bonus": "150 EC + Kharma",  "desc": "Cutting down their standard breaks enemy morale — the side loses 1d4 morale immediately."},
    {"name": "Faction Cleric",       "cr_bonus": 3, "reward_bonus": "200 EC + Kharma",  "desc": "The cleric is keeping their side healed and protected. Removing them cuts off battlefield recovery."},
    {"name": "Siege Operator",       "cr_bonus": 2, "reward_bonus": "150 EC + Kharma",  "desc": "They're running the ballista, the fire apparatus, or the arcane suppressor. Disable it or them."},
    {"name": "Field Commander",      "cr_bonus": 4, "reward_bonus": "300 EC + Kharma",  "desc": "The battle-mind keeping the enemy coordinated. Capture or kill — either breaks their cohesion."},
    {"name": "Void Anchor",          "cr_bonus": 3, "reward_bonus": "200 EC + Kharma",  "desc": "A void-touched creature acting as a beacon — others cluster around it. It must be destroyed."},
    {"name": "Breakout Alpha",       "cr_bonus": 3, "reward_bonus": "200 EC + Kharma",  "desc": "The largest creature that escaped first — others follow its behaviour. Putting it down slows the rest."},
    {"name": "Enemy Scout Captain",  "cr_bonus": 2, "reward_bonus": "150 EC + Kharma",  "desc": "They're coordinating flanking manoeuvres. Taking them out blinds the enemy's movements."},
    {"name": "Rogue Mage",           "cr_bonus": 4, "reward_bonus": "250 EC + Kharma",  "desc": "A caster who defected or broke — launching spells at both sides. Neutralise them to stop the chaos."},
]

# ---------------------------------------------------------------------------
# Battle Tide track
# ---------------------------------------------------------------------------

# The tide is tracked as a simple 5-state: Crushing / Winning / Even / Losing / Broken
TIDE_STATES = [
    ("Crushing",  "The battle is almost won. Enemy cohesion has collapsed.",              "#2d6a2d"),
    ("Winning",   "The party's side has the edge. Morale is holding.",                    "#5b8c3a"),
    ("Even",      "Both sides are bloodied. The next pocket fight decides the momentum.", "#8a7a4a"),
    ("Losing",    "Enemy pressure is mounting. Friendly forces are pulling back.",         "#a05a2a"),
    ("Broken",    "The battle may be lost even if the party survives.",                    "#8b1a1a"),
]

# ---------------------------------------------------------------------------
# Pocket fight enemy scaling
# ---------------------------------------------------------------------------

def _scale_cr(party_level: int, difficulty_bonus: int = 4) -> int:
    """Return target enemy CR as party_level + difficulty_bonus."""
    return max(1, party_level + difficulty_bonus)


def _grunt_count(party_size: int, fight_index: int, conflict_type: str) -> int:
    """
    Grunt count scales with party size and increases across fights.
    Monster conflicts run slightly fewer grunts (quality over quantity).
    """
    base = max(4, party_size * 2)
    progression = fight_index * 2  # each fight is harder
    if conflict_type == "faction_vs_faction":
        return base + progression
    return max(3, base + progression - 2)


# ---------------------------------------------------------------------------
# DB / party helpers
# ---------------------------------------------------------------------------

def _db_rows(sql: str, params: tuple = ()) -> List[Dict]:
    try:
        from src.db_api import raw_query
        return raw_query(sql, params) or []
    except Exception as e:
        logger.warning(f"[BATTLE] DB read failed: {e}")
        return []


def _party_strength() -> Dict[str, Any]:
    rows = _db_rows(
        "SELECT char_name, snapshot_json FROM latest_character_snapshots ORDER BY fetched_at DESC"
    )
    pcs = []
    for row in rows:
        snap = row.get("snapshot_json") or {}
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except Exception:
                continue
        level = int(snap.get("total_level") or snap.get("level") or 0)
        if level > 0:
            pcs.append({"name": snap.get("name") or row.get("char_name"), "level": level})
    levels = [p["level"] for p in pcs] or [5]
    return {
        "party_size": len(pcs) or 4,
        "avg_level":  round(sum(levels) / len(levels), 1),
        "max_level":  max(levels),
        "pcs":        pcs,
    }


def _party_scaling_note(strength: Dict) -> str:
    return (
        f"Live party: {strength['party_size']} PCs, avg level {strength['avg_level']}, "
        f"max level {strength['max_level']}. Enemy CR target: {_scale_cr(int(strength['avg_level']))}."
    )


def _get_force(faction: str) -> Dict:
    for key, val in FACTION_FORCES.items():
        if key.lower() in (faction or "").lower() or (faction or "").lower() in key.lower():
            return {**val, "faction": key}
    return {**FACTION_FORCES["Independent"], "faction": faction or "Independent"}


def _pick_location(conflict_type: str, faction: str) -> Dict[str, str]:
    """Pull a gazetteer location contextual to the conflict type."""
    if conflict_type == "monster_breakout":
        hints = ["sewer", "tunnel", "lab", "underground", "vault", "storage", "basement", "arena"]
    elif conflict_type == "faction_vs_void":
        hints = ["market", "plaza", "gate", "district", "street", "square"]
    else:
        hints = ["market", "plaza", "district", "street", "gate", "docks", "square", "forum"]

    clause = " OR ".join(["LOWER(name) LIKE %s OR LOWER(description) LIKE %s OR LOWER(place_type) LIKE %s"] * len(hints))
    params = []
    for h in hints:
        params.extend([f"%{h}%", f"%{h}%", f"%{h}%"])
    rows = _db_rows(
        f"SELECT name, district, place_type, description FROM gazetteer_places WHERE {clause} ORDER BY RAND() LIMIT 1",
        tuple(params),
    )
    if not rows:
        rows = _db_rows("SELECT name, district, place_type, description FROM gazetteer_places ORDER BY RAND() LIMIT 1")
    if rows:
        r = rows[0]
        return {
            "name":        r.get("name", "Unknown Site"),
            "district":    r.get("district", "Unknown District"),
            "place_type":  r.get("place_type", "site"),
            "description": r.get("description", ""),
        }
    return {"name": "Unknown Site", "district": "Unknown District", "place_type": "site", "description": ""}


def _pick_contact(faction: str) -> Dict[str, str]:
    rows = _db_rows(
        "SELECT name, role FROM npcs WHERE faction=%s AND status='alive' ORDER BY RAND() LIMIT 1",
        (faction,),
    )
    if rows:
        return {"name": rows[0].get("name", "Unknown Contact"), "role": rows[0].get("role", "")}
    return {"name": "Unknown Contact", "role": "Field Coordinator"}


def _pick_opposing_faction(hiring_faction: str) -> str:
    rows = _db_rows(
        "SELECT faction_name FROM faction_reputation WHERE faction_name != %s ORDER BY RAND() LIMIT 1",
        (hiring_faction,),
    )
    if rows:
        return rows[0].get("faction_name", "Unknown Faction")
    return "Rival Faction"


def _determine_conflict_type(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    if any(w in text for w in ("void", "rift", "corrupted", "rift creature", "void surge")):
        return "faction_vs_void"
    if any(w in text for w in ("breakout", "escape", "sewer", "lab", "contained", "loose")):
        return "monster_breakout"
    return "faction_vs_faction"


def _pick_void_creatures(party_level: int, count: int) -> List[Dict]:
    target_cr = _scale_cr(party_level)
    pool = sorted(VOID_CREATURES, key=lambda c: abs(int(c["cr"].split("/")[0]) - target_cr))
    chosen = pool[:max(3, count)]
    random.shuffle(chosen)
    return chosen[:count]


def _battle_enemy_type(conflict_type: str, enemy_name: str = "", enemy_desc: str = "") -> str:
    """Infer a Mimir/DDB creature type without flattening battle variants."""
    text = f"{conflict_type} {enemy_name} {enemy_desc}".lower()
    if "faction_vs_faction" in text or "infantry" in text:
        return "humanoid"
    if "undead" in text or "necropolis" in text:
        return "undead"
    if any(word in text for word in ("construct", "experiment", "test site")):
        return "construct"
    if any(word in text for word in ("rat", "gator", "beast", "vermin")):
        return "beast"
    if any(word in text for word in ("void", "rift", "corrupted", "abomination")):
        return "aberration"
    return "monstrosity"


def _battle_mimir_enemies(
    pocket_fights: List[Dict],
    glory: Dict,
    strength: Dict,
    conflict_type: str,
) -> List[Dict]:
    """Build battle-specific Mimir enemy entries from the actual pocket fights."""
    enemies: List[Dict] = []
    seen: dict[tuple[str, str], Dict] = {}

    for fight in pocket_fights:
        name = str(fight.get("enemy_name") or "").strip()
        if not name:
            continue
        cr = str(fight.get("cr_target", 1))
        key = (name.lower(), cr)
        count = int(fight.get("grunt_count") or 1)
        note = (
            f"Fight {fight.get('index', len(enemies) + 1)}: {fight.get('name', 'Pocket Fight')}. "
            f"{fight.get('enemy_desc', '')} {fight.get('enemy_tactic', '')}"
        ).strip()
        if key in seen:
            seen[key]["count"] += count
            seen[key]["notes"] = f"{seen[key].get('notes', '')}\n{note}".strip()
            continue
        entry = {
            "name": name,
            "cr": cr,
            "count": count,
            "notes": note,
            "creature_type": _battle_enemy_type(conflict_type, name, str(fight.get("enemy_desc", ""))),
        }
        seen[key] = entry
        enemies.append(entry)

    if glory and glory.get("name"):
        enemies.append({
            "name": glory["name"],
            "cr": str(int(strength.get("avg_level", 3)) + int(glory.get("cr_bonus", 0))),
            "count": 1,
            "notes": f"Glory Fight. {glory.get('desc', '')}".strip(),
            "creature_type": _battle_enemy_type(conflict_type, glory.get("name", ""), glory.get("desc", "")),
        })

    return enemies


def _pick_breakout_source() -> Dict:
    return random.choice(BREAKOUT_SOURCES)


def _pick_glory_target(conflict_type: str) -> Dict:
    if conflict_type == "faction_vs_void":
        pool = [t for t in GLORY_TARGETS if t["name"] in ("Void Anchor", "Rogue Mage", "Breakout Alpha")]
    elif conflict_type == "monster_breakout":
        pool = [t for t in GLORY_TARGETS if t["name"] in ("Breakout Alpha", "Void Anchor", "Rogue Mage")]
    else:
        pool = [t for t in GLORY_TARGETS if t["name"] not in ("Void Anchor", "Breakout Alpha")]
    return random.choice(pool or GLORY_TARGETS)


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


# ---------------------------------------------------------------------------
# Ollama generation helpers
# ---------------------------------------------------------------------------

async def _ollama(prompt: str, tokens: int = 1400) -> str:
    """Call Ollama via the shared queue with up to 10 retries and backoff."""
    from src.ollama_queue import call_ollama

    payload = {
        "model":    OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream":   False,
        "think":    False,
        "options":  {"temperature": 0.84, "num_predict": tokens},
    }

    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            data    = await call_ollama(payload, timeout=180.0, caller="battle", force=True)
            content = (data.get("message") or {}).get("content", "").strip()
            if content:
                return content
            logger.warning(f"[BATTLE] Empty response (attempt {attempt}/{max_attempts})")
        except Exception as e:
            logger.warning(f"[BATTLE] Ollama error attempt {attempt}/{max_attempts}: {e}")

        if attempt < max_attempts:
            wait = min(30 * attempt, 120)
            logger.info(f"[BATTLE] Retrying in {wait}s…")
            await asyncio.sleep(wait)

    logger.error("[BATTLE] All 10 attempts exhausted — returning empty string")
    return ""


# ---------------------------------------------------------------------------
# LLM generation tasks
# ---------------------------------------------------------------------------

async def _generate_briefing(
    mission: dict,
    conflict_type: str,
    hiring_faction: str,
    opposing_side: str,
    contact: Dict,
    location: Dict,
    strength: Dict,
    source: Optional[Dict],
) -> Dict[str, Any]:
    conflict_cfg = CONFLICT_TYPES[conflict_type]
    force = _get_force(hiring_faction)
    timer = random.randint(2, MAX_TIMER_DAYS)

    void_note = ""
    if conflict_type == "faction_vs_void":
        void_note = f"\nVoid context: rift-corrupted creatures are consuming everything. Glass Sigil detected early. The creatures are not negotiating. The rift source is named but sealing it is a future mission.\n"
    elif conflict_type == "monster_breakout":
        void_note = f"\nBreakout source: {source['name']} — {source['creature_type']}. The creatures have broken containment. The source location is sealed but breached.\n"

    prompt = f"""Write a battle mission briefing for a D&D Undercity campaign.

MISSION: {mission.get('title', 'Battle')}
CONFLICT TYPE: {conflict_cfg['label']}
HIRING FACTION: {hiring_faction} ({force['tactics']})
OPPOSING SIDE: {opposing_side}
CONTACT NPC: {contact['name']} — {contact['role']}
LOCATION: {location['name']}, {location['district']}
TIME PRESSURE: {timer} days until the clash begins
PARTY: {strength['party_size']} PCs, avg level {strength['avg_level']}
{void_note}
BULLETIN TONE: {conflict_cfg['bulletin_tone']}

Write ONLY a JSON object with these keys, no markdown:
{{
  "contact_speech": "2-3 sentences the contact says when hiring the party — specific, urgent, with a real personal stake",
  "situation": "1-2 sentences describing the public situation and where the battle will be",
  "timer_reason": "one sentence explaining why the 5-day clock is fixed",
  "opposing_desc": "one sentence describing the opposing side",
  "win_conditions": ["3 bullet strings — specific things the party can do to turn the tide"],
  "lose_condition": "one sentence — what happens if the battle is lost",
  "debrief_location": "{conflict_cfg['debrief_location']}"
}}"""

    text = await _ollama(prompt, 1000)
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            data = json.loads(m.group())
            data["timer_days"] = timer
            return data
        except Exception:
            pass
    return {
        "contact_speech":   f"{contact['name']} needs fighters for what's coming. {hiring_faction} has {timer} days.",
        "situation":        f"A battle is coming to {location['name']}.",
        "timer_reason":     "The opposing side has already committed. There is no postponing this.",
        "opposing_desc":    f"The {opposing_side} are not standing down.",
        "win_conditions":   ["Hold the line through all pocket fights", "Complete the glory fight if attempted", "Keep morale from collapsing"],
        "lose_condition":   "The battle is lost and the faction loses ground in the district.",
        "debrief_location": conflict_cfg["debrief_location"],
        "timer_days":       timer,
    }


async def _generate_pocket_fight(
    fight_index: int,
    conflict_type: str,
    opposing_side: str,
    location: Dict,
    strength: Dict,
    void_creatures: Optional[List[Dict]],
    source: Optional[Dict],
) -> Dict[str, Any]:
    conflict_cfg = CONFLICT_TYPES[conflict_type]
    cr_target = _scale_cr(int(strength["avg_level"]))
    grunt_count = _grunt_count(strength["party_size"], fight_index, conflict_type)
    reinforce_chance = 40 + fight_index * 10  # later fights more likely to have reinforcement

    if conflict_type == "faction_vs_void" and void_creatures:
        creature = void_creatures[fight_index % len(void_creatures)]
        enemy_desc = f"{creature['name']} (CR {creature['cr']}) — {creature['desc']}"
        enemy_name = creature["name"]
    elif conflict_type == "monster_breakout" and source:
        enemy_name = f"Escaped {source['creature_type'].split(',')[0].strip()}"
        enemy_desc = f"Escaped from {source['name']} — {source['creature_type']}"
    else:
        enemy_name = f"{opposing_side} Infantry"
        enemy_desc = f"Standard {opposing_side} fighters in formation"

    prompt = f"""Write a pocket fight card for a D&D Undercity battle mission.

FIGHT NUMBER: {fight_index + 1}
CONFLICT TYPE: {CONFLICT_TYPES[conflict_type]['label']}
LOCATION: {location['name']}, {location['district']}
ENEMY: {enemy_name} — {enemy_desc}
GRUNT COUNT: {grunt_count} grunts + 1 lieutenant at CR {cr_target}
REINFORCEMENT CHANCE: {reinforce_chance}% — {conflict_cfg['reinforcement']}

Write ONLY a JSON object, no markdown:
{{
  "name": "short evocative fight name (3-5 words)",
  "setting": "one sentence — where exactly in the battle this pocket fight takes place",
  "enemy_tactic": "one sentence — how the enemy fights in this pocket fight",
  "environmental_hazard": "one sentence — one terrain or situation hazard in this specific area (or null)",
  "reinforcement_trigger": "one sentence — what triggers the reinforcement if it happens",
  "outcome_if_won": "one sentence — what changes in the broader battle if the party wins this fight",
  "outcome_if_lost": "one sentence — what changes if the party loses or retreats"
}}"""

    text = await _ollama(prompt, 600)
    m = re.search(r"\{[\s\S]*\}", text)
    data: Dict[str, Any] = {}
    if m:
        try:
            data = json.loads(m.group())
        except Exception:
            pass

    return {
        "index":                fight_index + 1,
        "name":                 data.get("name", f"Pocket Fight {fight_index + 1}"),
        "setting":              data.get("setting", f"A clash near {location['name']}."),
        "enemy_name":           enemy_name,
        "enemy_desc":           enemy_desc,
        "grunt_count":          grunt_count,
        "cr_target":            cr_target,
        "reinforce_chance":     reinforce_chance,
        "reinforcement_trigger":data.get("reinforcement_trigger", "When grunts drop below half."),
        "enemy_tactic":         data.get("enemy_tactic", "Press forward with numbers."),
        "hazard":               data.get("environmental_hazard"),
        "outcome_won":          data.get("outcome_if_won", "The tide shifts slightly in the party's favour."),
        "outcome_lost":         data.get("outcome_if_lost", "The enemy presses the advantage."),
    }


async def _generate_support_table(hiring_faction: str, conflict_type: str) -> List[Dict]:
    force = _get_force(hiring_faction)
    prompt = f"""Generate a battle support action table for a D&D game.

FACTION: {hiring_faction}
SUPPORT STYLE: {force['support_style']}
CONFLICT TYPE: {CONFLICT_TYPES[conflict_type]['label']}

Write ONLY a JSON array of 5 support actions, no markdown:
[
  {{
    "name": "short action name",
    "trigger": "when the party can call this in (once per battle / once per fight / on request)",
    "effect": "one sentence — what it does mechanically (restore HP, reduce grunt count, add temp ally, etc.)",
    "cost": "what it costs (nothing / action / roll DC 12 / uses one call)"
  }}
]"""

    text = await _ollama(prompt, 700)
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            actions = json.loads(m.group())
            if isinstance(actions, list) and actions:
                return actions[:5]
        except Exception:
            pass
    return [
        {"name": "Field Healer", "trigger": "once per battle", "effect": "One PC recovers 2d8 HP.", "cost": "nothing"},
        {"name": "Cover Fire",   "trigger": "once per fight",  "effect": "Remove 1d4 grunts before the fight begins.", "cost": "action"},
        {"name": "Shield Wall",  "trigger": "once per battle", "effect": "Party has +2 AC for one pocket fight.", "cost": "call"},
        {"name": "Temp Ally",    "trigger": "once per battle", "effect": f"A {hiring_faction} lieutenant joins for one fight (CR {3}).", "cost": "roll DC 12"},
        {"name": "Retreat Route","trigger": "once per battle", "effect": "Party can disengage from a fight with no opportunity attacks.", "cost": "uses one call"},
    ]


async def _generate_debrief(
    mission: dict,
    conflict_type: str,
    hiring_faction: str,
    contact: Dict,
    location: Dict,
    briefing: Dict,
) -> Dict[str, Any]:
    force = _get_force(hiring_faction)
    prompt = f"""Write a debrief scene for a D&D battle mission.

FACTION: {hiring_faction}
CONTACT: {contact['name']}
LOCATION AFTER BATTLE: {briefing.get('debrief_location', 'commander tent')}
BATTLEFIELD: {location['name']}, {location['district']}
FACTION MORALE NOTE: {force['morale_note']}
CONFLICT TYPE: {CONFLICT_TYPES[conflict_type]['label']}

The debrief has two parts: a battlefield survey first (walking the aftermath),
then a meeting at the commander's location.

Write ONLY a JSON object, no markdown:
{{
  "survey_desc": "2 sentences — what the battlefield looks like immediately after the fighting stops",
  "survey_find": "one specific detail the party notices on the walk — a clue, a casualty, or a strange object",
  "commander_reaction_win":  "2 sentences — how the contact reacts if the party's side won",
  "commander_reaction_lose": "2 sentences — how the contact reacts if the party's side lost",
  "stay_offer": "one sentence — optional offer to stay on for further work (or null if the contact wouldn't offer it)",
  "reward_note": "one sentence — how payment is delivered"
}}"""

    text = await _ollama(prompt, 800)
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {
        "survey_desc":              f"The battlefield at {location['name']} is quiet now. The ground is marked.",
        "survey_find":              "A dropped insignia from one of the enemy lieutenants.",
        "commander_reaction_win":   f"{contact['name']} nods. 'You did what we needed. {hiring_faction} remembers.'",
        "commander_reaction_lose":  f"{contact['name']} is already planning the next move. 'We held long enough. Payment still stands.'",
        "stay_offer":               f"{hiring_faction} has more work coming. {contact['name']} mentions it without asking directly.",
        "reward_note":              "EC transferred on the spot. Kharma logged with the faction record.",
    }


# ---------------------------------------------------------------------------
# A1111 map generation
# ---------------------------------------------------------------------------

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
            logger.info(f"[BATTLE] A1111 not ready (attempt {attempt}/10) — waiting 30s…")
            await asyncio.sleep(30)
    logger.warning("[BATTLE] A1111 unavailable after 10 attempts")
    return False


async def _generate_battle_map(
    conflict_type: str,
    location: Dict,
    out_dir: Path,
) -> Optional[Path]:
    out = out_dir / "battle_map.png"
    conflict_cfg = CONFLICT_TYPES[conflict_type]
    loc_desc = (location.get("description") or "")[:150]
    _hint = conflict_cfg["map_hint"]
    is_dungeon = "dungeon" in _hint.lower()
    lora_name = os.getenv("A1111_MAP_LORA_DUNGEON" if is_dungeon else "A1111_MAP_LORA_TOWN",
                           "EnvyFluxDungeonMap01" if is_dungeon else "EnvyFluxFantasyTownMap01")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    triggers = os.getenv("A1111_MAP_DUNGEON_TRIGGERS" if is_dungeon else "A1111_MAP_TOWN_TRIGGERS",
                          "detailed, map, dungeon" if is_dungeon else "detailed, map, village")

    prompt = ", ".join(filter(None, [
        f"<lora:{lora_name}:{lora_weight}>",
        triggers,
        _hint,
        f"{location['name']} {location['district']}",
        loc_desc,
        "multiple entry zones, cover positions, open killing ground, flanking routes",
        "high fantasy cyberpunk fusion, wealth-stratified city",
    ]))
    negative = "characters, people, isometric, perspective, watermark, text"
    payload = {
        "prompt":          prompt,
        "negative_prompt": negative,
        "width":  1280,
        "height": 1024,
        "steps":  20,
        "cfg_scale": 1.0,
        "sampler_name": "Euler",
        "seed": -1,
    }
    _map_ckpt = os.getenv("A1111_MAP_CHECKPOINT", "")
    if _map_ckpt:
        override: dict = {"sd_model_checkpoint": _map_ckpt}
        payload["override_settings"] = override
        payload["override_settings_restore_afterwards"] = True
    max_map_attempts = 10
    for map_attempt in range(1, max_map_attempts + 1):
        try:
            from src.news_feed import a1111_lock
            from src.resource_cop import wait_for_a1111_turn
            decision = await wait_for_a1111_turn("battle_map", max_wait_seconds=60)
            if not decision.run_now:
                logger.info(f"[BATTLE] A1111 deferred by resource cop: {decision.reason}")
                from src.mission_builder.vtt_renderer import save_vtt_battlemap
                save_vtt_battlemap(out, None, context={"title": location.get("name"), "location": location, "prompt": prompt, "kind": "battle"})
                return out
            async with a1111_lock:
                async with httpx.AsyncClient(timeout=600.0) as c:
                    r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                    r.raise_for_status()
                    images = r.json().get("images", [])
            if not images:
                raise RuntimeError("A1111 returned no images")
            from src.mission_builder.vtt_renderer import save_vtt_battlemap
            save_vtt_battlemap(out, images[0], context={"title": location.get("name"), "location": location, "prompt": prompt, "kind": "battle"})
            logger.info(f"[BATTLE] Map saved: {out.name}")
            return out
        except Exception as e:
            logger.warning(f"[BATTLE] Map attempt {map_attempt}/{max_map_attempts} failed: {e}")
            if map_attempt < max_map_attempts:
                wait = min(30 * map_attempt, 120)
                logger.info(f"[BATTLE] Retrying map in {wait}s…")
                await asyncio.sleep(wait)

    logger.error("[BATTLE] Map generation failed after 10 attempts — using deterministic fallback")
    from src.mission_builder.vtt_renderer import save_vtt_battlemap
    save_vtt_battlemap(out, None, context={"title": location.get("name"), "location": location, "prompt": prompt, "kind": "battle"})
    logger.info(f"[BATTLE] Deterministic VTT map saved: {out.name}")
    return out


# ---------------------------------------------------------------------------
# HTML rendering helpers
# ---------------------------------------------------------------------------

def _e(text: Any) -> str:
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _card(title: str, body: str, color: str = "#4a3f34") -> str:
    return (
        f'<div style="background:#1a1612;border:1px solid {color};border-radius:8px;'
        f'margin:12px 0;padding:16px;">'
        f'<div style="color:{color};font-weight:700;font-size:13px;letter-spacing:.08em;'
        f'text-transform:uppercase;margin-bottom:10px;">{title}</div>'
        f'{body}</div>'
    )


def _ul(items: List[str], color: str = "#c8a96e") -> str:
    return "<ul style='margin:0;padding-left:18px;'>" + "".join(
        f'<li style="color:{color};margin:3px 0;">{_e(i)}</li>' for i in items
    ) + "</ul>"


def _checkbox(label: str, color: str = "#c8a96e") -> str:
    return (
        f'<label style="display:flex;align-items:center;gap:8px;margin:4px 0;color:{color};font-size:13px;">'
        f'<input type="checkbox" style="accent-color:{color};width:14px;height:14px;">'
        f'{_e(label)}</label>'
    )


def _tide_track() -> str:
    states = TIDE_STATES
    cells = ""
    for label, desc, color in states:
        cells += (
            f'<div style="flex:1;padding:8px 4px;background:{color}22;border:1px solid {color};'
            f'border-radius:4px;text-align:center;">'
            f'<div style="font-size:10px;font-weight:700;color:{color};">{label}</div>'
            f'<input type="checkbox" style="margin-top:4px;accent-color:{color};">'
            f'</div>'
        )
    return (
        '<div style="margin:8px 0;">'
        '<div style="font-size:11px;color:#8a7a5c;margin-bottom:4px;">BATTLE TIDE — mark current state after each pocket fight</div>'
        f'<div style="display:flex;gap:4px;">{cells}</div>'
        '</div>'
    )


def _pocket_fight_card(fight: Dict, glory_slot: Optional[int], glory: Dict, fc: str) -> str:
    glory_note = ""
    if glory_slot == fight["index"]:
        glory_note = (
            f'<div style="background:#2a1a0a;border:1px solid #c8531f;border-radius:6px;'
            f'padding:10px;margin-top:10px;">'
            f'<div style="color:#c8531f;font-weight:700;font-size:11px;letter-spacing:.08em;">GLORY FIGHT AVAILABLE HERE</div>'
            f'<div style="color:#c8a96e;font-size:13px;margin-top:4px;"><b>{_e(glory["name"])}</b> — {_e(glory["desc"])}</div>'
            f'<div style="color:#8a7a5c;font-size:12px;margin-top:4px;">CR target +{glory["cr_bonus"]} · Bonus: {_e(glory["reward_bonus"])}</div>'
            f'</div>'
        )

    reinforce_pct = fight.get("reinforce_chance", 40)
    reinforce_color = "#c8531f" if reinforce_pct >= 60 else "#8a7a5c"

    return _card(
        f'Pocket Fight {fight["index"]} — {_e(fight["name"])}',
        f'<div style="color:#c8a96e;margin-bottom:8px;">{_e(fight["setting"])}</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">'
        f'<div><div style="font-size:11px;color:#8a7a5c;">ENEMY</div>'
        f'<div style="color:#c8a96e;">{_e(fight["enemy_name"])}</div>'
        f'<div style="color:#8a7a5c;font-size:12px;">{_e(fight["enemy_desc"])}</div></div>'
        f'<div><div style="font-size:11px;color:#8a7a5c;">FORCE</div>'
        f'<div style="color:#c8a96e;">{fight["grunt_count"]} grunts · 1 LT (CR {fight["cr_target"]})</div>'
        f'<div style="font-size:11px;color:{reinforce_color};">Reinforce chance: {reinforce_pct}%</div></div>'
        f'</div>'
        + (f'<div style="color:#c8531f;font-size:12px;margin-bottom:6px;">⚠ Hazard: {_e(fight["hazard"])}</div>' if fight.get("hazard") else "")
        + f'<div style="font-size:12px;color:#8a7a5c;margin-bottom:4px;">Tactic: {_e(fight["enemy_tactic"])}</div>'
        f'<div style="font-size:12px;color:#8a7a5c;margin-bottom:4px;">Reinforce trigger: {_e(fight["reinforcement_trigger"])}</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;">'
        f'<div style="background:#0a1a0a;padding:6px;border-radius:4px;font-size:12px;color:#9bc98a;">WIN: {_e(fight["outcome_won"])}</div>'
        f'<div style="background:#1a0a0a;padding:6px;border-radius:4px;font-size:12px;color:#c87a7a;">LOSE: {_e(fight["outcome_lost"])}</div>'
        f'</div>'
        + glory_note
        + f'<div style="margin-top:10px;">{_checkbox("Fight complete", fc)}</div>',
        fc,
    )


def _support_table_card(actions: List[Dict], faction: str, fc: str) -> str:
    rows = ""
    for a in actions:
        rows += (
            f'<div style="border-bottom:1px solid #2a2521;padding:8px 0;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="color:#c8a96e;font-weight:600;">{_e(a.get("name",""))}</span>'
            f'<span style="font-size:11px;color:#8a7a5c;">{_e(a.get("trigger",""))}</span>'
            f'</div>'
            f'<div style="color:#8a7a5c;font-size:12px;">{_e(a.get("effect",""))}</div>'
            f'<div style="font-size:11px;color:#5a6b3a;">Cost: {_e(a.get("cost","none"))}</div>'
            f'{_checkbox("Used", fc)}'
            f'</div>'
        )
    return _card(f"Allied Support — {_e(faction)}", rows, fc)


# ---------------------------------------------------------------------------
# Full HTML render
# ---------------------------------------------------------------------------

def render_battle_module(
    mission: dict,
    conflict_type: str,
    hiring_faction: str,
    opposing_side: str,
    contact: Dict,
    location: Dict,
    briefing: Dict,
    pocket_fights: List[Dict],
    glory: Dict,
    glory_slot: int,
    support_actions: List[Dict],
    debrief: Dict,
    strength: Dict,
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title = mission.get("title", "Battle")
    fc    = _faction_color(hiring_faction)
    conflict_cfg = CONFLICT_TYPES[conflict_type]
    body  = ""

    # Header
    body += _card("Briefing", (
        f'<div style="color:{fc};font-size:13px;font-style:italic;margin-bottom:10px;">'
        f'{_e(briefing.get("contact_speech",""))}</div>'
        f'<div style="color:#c8a96e;margin-bottom:6px;">{_e(briefing.get("situation",""))}</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:10px 0;">'
        f'<div><div style="font-size:11px;color:#8a7a5c;">CONFLICT TYPE</div><div style="color:#c8a96e;">{_e(conflict_cfg["label"])}</div></div>'
        f'<div><div style="font-size:11px;color:#8a7a5c;">LOCATION</div><div style="color:#c8a96e;">{_e(location["name"])}, {_e(location["district"])}</div></div>'
        f'<div><div style="font-size:11px;color:#8a7a5c;">TIMER</div><div style="color:#c8531f;">{briefing.get("timer_days",5)} DAYS</div></div>'
        f'</div>'
        f'<div style="margin-top:8px;"><div style="font-size:11px;color:#8a7a5c;">OPPOSING SIDE</div>'
        f'<div style="color:#c8a96e;">{_e(opposing_side)} — {_e(briefing.get("opposing_desc",""))}</div></div>'
        f'<div style="margin-top:8px;font-size:12px;color:#c8531f;">{_e(briefing.get("timer_reason",""))}</div>'
    ), fc)

    # Win/Lose conditions
    body += _card("Objectives",
        _ul(briefing.get("win_conditions", []), fc)
        + f'<div style="color:#c8531f;font-size:12px;margin-top:8px;">Fail: {_e(briefing.get("lose_condition",""))}</div>',
        fc,
    )

    # Battle Tide
    body += _card("Battle Tide", _tide_track(), "#5b6b3a")

    # Map
    if map_path and map_path.exists():
        rel = map_path.relative_to(out_dir)
        body += _card("Battlefield Map",
            f'<div><img src="{rel}" style="max-width:100%;border:2px solid {fc};border-radius:6px;" alt="Battle Map"></div>'
            f'<div style="font-size:11px;color:#8a7a5c;margin-top:6px;">{_e(location["name"])} — {_e(conflict_cfg["label"])}</div>',
            fc,
        )

    # Pocket fights
    body += f'<div style="color:{fc};font-weight:700;font-size:14px;margin:16px 0 8px;letter-spacing:.05em;">POCKET FIGHTS</div>'
    for fight in pocket_fights:
        body += _pocket_fight_card(fight, glory_slot, glory, fc)

    # Glory fight (after last fight)
    if glory_slot == len(pocket_fights):
        body += _card("Glory Fight — Final Position",
            f'<div style="color:#c8531f;font-size:13px;font-weight:700;">Target: {_e(glory["name"])}</div>'
            f'<div style="color:#c8a96e;margin:6px 0;">{_e(glory["desc"])}</div>'
            f'<div style="font-size:12px;color:#8a7a5c;">CR +{glory["cr_bonus"]} above standard · Reward: {_e(glory["reward_bonus"])}</div>'
            f'<div style="margin-top:8px;">{_checkbox("Glory fight attempted", "#c8531f")}</div>'
            f'<div style="margin-top:4px;">{_checkbox("Glory fight won", "#9bc98a")}</div>',
            "#c8531f",
        )

    # Support table
    body += _support_table_card(support_actions, hiring_faction, fc)

    # Debrief
    body += _card("Debrief — Battlefield Survey",
        f'<div style="color:#c8a96e;margin-bottom:6px;">{_e(debrief.get("survey_desc",""))}</div>'
        f'<div style="color:#8a7a5c;font-size:12px;">Notable find: {_e(debrief.get("survey_find",""))}</div>',
        fc,
    )
    body += _card(f"Debrief — {_e(briefing.get('debrief_location','Commander Tent'))}",
        f'<div style="font-size:11px;color:#8a7a5c;">IF WON</div>'
        f'<div style="color:#9bc98a;font-size:13px;margin-bottom:8px;">{_e(debrief.get("commander_reaction_win",""))}</div>'
        f'<div style="font-size:11px;color:#8a7a5c;">IF LOST</div>'
        f'<div style="color:#c87a7a;font-size:13px;margin-bottom:8px;">{_e(debrief.get("commander_reaction_lose",""))}</div>'
        + (f'<div style="font-size:12px;color:#8a7a5c;border-top:1px solid #2a2521;padding-top:8px;margin-top:4px;">Stay offer: {_e(debrief.get("stay_offer",""))}</div>' if debrief.get("stay_offer") else "")
        + f'<div style="font-size:12px;color:#5b6b3a;margin-top:6px;">{_e(debrief.get("reward_note",""))}</div>',
        fc,
    )

    # Scaling
    body += _card("Live Scaling", f'<div style="color:#8a7a5c;font-size:12px;">{_e(_party_scaling_note(strength))}</div>', "#4a3f34")

    return _page(title, body, hiring_faction)


def render_battle_session(
    mission: dict,
    conflict_type: str,
    hiring_faction: str,
    opposing_side: str,
    location: Dict,
    briefing: Dict,
    pocket_fights: List[Dict],
    glory: Dict,
    glory_slot: int,
    support_actions: List[Dict],
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title = mission.get("title", "Battle")
    fc    = _faction_color(hiring_faction)
    conflict_cfg = CONFLICT_TYPES[conflict_type]
    body  = f'<h1 style="color:{fc};">{_e(title)}</h1>'
    body += f'<p style="color:#c8a96e;">{_e(conflict_cfg["label"])} · {_e(location["name"])} · {briefing.get("timer_days",5)} days</p>'

    body += "<h3>Situation</h3>"
    body += f'<p>{_e(briefing.get("situation",""))}</p>'
    body += f'<blockquote style="border-left:3px solid {fc};padding-left:12px;color:#c8a96e;">{_e(briefing.get("contact_speech",""))}</blockquote>'

    body += "<h3>Win Conditions</h3>"
    body += _ul(briefing.get("win_conditions", []), "#c8a96e")

    body += "<h3>Battle Tide</h3>"
    body += _tide_track()

    if map_path and map_path.exists():
        rel = map_path.relative_to(out_dir)
        body += f'<div style="margin:12px 0;"><img src="{rel}" style="max-width:100%;border:2px solid {fc};border-radius:6px;" alt="Battlefield Map"></div>'

    body += "<h3>Pocket Fights</h3>"
    for fight in pocket_fights:
        glory_here = glory_slot == fight["index"]
        body += (
            f'<div style="border:1px solid {fc};border-radius:6px;padding:12px;margin:8px 0;">'
            f'<b style="color:{fc};">Fight {fight["index"]}: {_e(fight["name"])}</b><br>'
            f'<span style="color:#c8a96e;">{_e(fight["setting"])}</span><br>'
            f'<span style="color:#8a7a5c;">{fight["grunt_count"]} grunts · LT CR {fight["cr_target"]} · {fight["reinforce_chance"]}% reinforce</span><br>'
            + (f'<span style="color:#c8531f;font-size:12px;">Hazard: {_e(fight["hazard"])}</span><br>' if fight.get("hazard") else "")
            + (
                f'<div style="background:#2a1a0a;border:1px solid #c8531f;border-radius:4px;padding:8px;margin:6px 0;font-size:12px;">'
                f'<b style="color:#c8531f;">GLORY FIGHT:</b> {_e(glory["name"])} — {_e(glory["desc"])}<br>'
                f'Bonus: {_e(glory["reward_bonus"])}'
                f'</div>'
                if glory_here else ""
            )
            + f'{_checkbox("Fight complete", fc)}'
            f'</div>'
        )

    body += "<h3>Allied Support</h3>"
    for a in support_actions:
        body += (
            f'<div style="padding:6px 0;border-bottom:1px solid #2a2521;">'
            f'<b style="color:#c8a96e;">{_e(a.get("name",""))}</b> '
            f'<span style="font-size:11px;color:#8a7a5c;">({_e(a.get("trigger",""))})</span><br>'
            f'<span style="font-size:12px;color:#8a7a5c;">{_e(a.get("effect",""))}</span><br>'
            f'{_checkbox("Used", fc)}'
            f'</div>'
        )

    return _page(title, body, hiring_faction)


# ---------------------------------------------------------------------------
# Main build entry point
# ---------------------------------------------------------------------------

async def build_battle_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    """Full battle pipeline. Returns path to index.html."""
    title           = mission.get("title", "Battle")
    hiring_faction  = mission.get("faction", "Independent")
    tier            = mission.get("tier", "standard")

    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine conflict type
    conflict_type   = _determine_conflict_type(mission)
    conflict_cfg    = CONFLICT_TYPES[conflict_type]
    fight_count     = conflict_cfg["pocket_fights"]

    # For void missions, prefer Glass Sigil as issuer
    if conflict_type == "faction_vs_void" and hiring_faction not in VOID_PRIMARY_FACTIONS:
        if random.random() < 0.6:
            hiring_faction = "Glass Sigil"

    # Opposing side
    if conflict_type == "faction_vs_faction":
        opposing_side = mission.get("opposing_faction") or _pick_opposing_faction(hiring_faction)
    elif conflict_type == "faction_vs_void":
        opposing_side = "Void Creatures"
    else:
        opposing_side = "Escaped Creatures"

    strength = _party_strength()
    location = _pick_location(conflict_type, hiring_faction)
    contact  = _pick_contact(hiring_faction)

    # Conflict-specific data
    void_creatures  = _pick_void_creatures(int(strength["avg_level"]), fight_count) if conflict_type == "faction_vs_void" else None
    source          = _pick_breakout_source() if conflict_type == "monster_breakout" else None

    # Glory fight — slot between fight 1-2 or 2-3 (or after last fight)
    glory       = _pick_glory_target(conflict_type)
    glory_slot  = random.choice([1, 2]) if fight_count >= 3 else 1

    logger.info(
        f"[BATTLE] Building: {title!r} | type={conflict_type} | faction={hiring_faction} "
        f"| opposing={opposing_side} | fights={fight_count} | glory_slot={glory_slot}"
    )

    # Generate concurrently
    briefing_task = asyncio.create_task(
        _generate_briefing(mission, conflict_type, hiring_faction, opposing_side, contact, location, strength, source)
    )
    support_task  = asyncio.create_task(
        _generate_support_table(hiring_faction, conflict_type)
    )

    pocket_tasks = [
        asyncio.create_task(
            _generate_pocket_fight(i, conflict_type, opposing_side, location, strength, void_creatures, source)
        )
        for i in range(fight_count)
    ]

    briefing, support_actions, *pocket_results = await asyncio.gather(
        briefing_task, support_task, *pocket_tasks
    )
    pocket_fights: List[Dict] = list(pocket_results)

    debrief = await _generate_debrief(
        mission, conflict_type, hiring_faction, contact, location, briefing
    )

    # Map
    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            map_path = await _generate_battle_map(conflict_type, location, out_dir)
        else:
            logger.warning("[BATTLE] A1111 not available — skipping map")

    # Mimir: catalog-enriched stat blocks for this battle
    from src.mission_builder.mimir_module import create_module as _mc, enrich_monsters as _me, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="battle")
    _b_enemies = _battle_mimir_enemies(pocket_fights, glory, strength, conflict_type)
    _enriched = await _me(_mimir_id or "", _b_enemies)

    # Direct DDB homebrew push — fires when Mimir is unavailable but DDB session is set.
    # enrich_monsters() exits early without pushing anything if Mimir is down, so we
    # push each enemy directly here as a fallback.
    if not _mimir_id:
        try:
            from src.ddb_homebrew import push_mission_enemy as _ddb_push, ENABLED as _ddb_en
            if _ddb_en:
                async def _push_all_direct():
                    for _e in _b_enemies:
                        if not _e.get("name"):
                            continue
                        _cr = str(_e.get("cr", "1"))
                        try:
                            _cr_num = float(_cr.replace("1/8", "0.125").replace("1/4", "0.25").replace("1/2", "0.5"))
                        except Exception:
                            _cr_num = 1.0
                        _prebuilt = {
                            "hp":            _e.get("hp") or max(1, int(_cr_num * 13 + 7)),
                            "ac":            _e.get("ac") or max(10, min(18, int(_cr_num + 12))),
                            "creature_type": _e.get("creature_type", "humanoid"),
                            "speed":         _e.get("speed", "30 ft."),
                        }
                        _atks = _e.get("attacks", [])
                        if _atks:
                            _prebuilt["actions"] = "\n\n".join(
                                f"**{a.split('.')[0]}.** {'.'.join(a.split('.')[1:]).strip()}"
                                if '.' in a else f"**Attack.** {a}"
                                for a in _atks[:4]
                            )
                        try:
                            await _ddb_push(_e, cr_val=_cr, statblock=_prebuilt)
                            logger.info(f"[DDB_HB] Direct push: {_e['name']!r} CR {_cr}")
                        except Exception as _de:
                            logger.warning(f"[DDB_HB] Direct push failed for {_e.get('name')!r}: {_de}")
                asyncio.create_task(_push_all_direct())
        except Exception as _dex:
            logger.warning(f"[DDB_HB] Could not start direct push task: {_dex}")

    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Battle Map")

    # Render
    module_html = render_battle_module(
        mission, conflict_type, hiring_faction, opposing_side, contact, location,
        briefing, pocket_fights, glory, glory_slot, support_actions, debrief,
        strength, map_path, out_dir,
    )
    module_html += _ms(_enriched, [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")

    session_html = render_battle_session(
        mission, conflict_type, hiring_faction, opposing_side, location,
        briefing, pocket_fights, glory, glory_slot, support_actions, map_path, out_dir,
    )
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    # Component guides via boxset_utils
    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page

    dm_md = (
        f"## Battle DM Guide\n"
        f"### Conflict Type\n{conflict_cfg['label']} — {conflict_type}\n\n"
        f"### Location\n{location['name']}, {location['district']}\n{location.get('description','')}\n\n"
        f"### Opposing Side\n{opposing_side}\n\n"
        f"### Contact\n{contact['name']} — {contact['role']}\n\n"
        f"### Timer\n{briefing.get('timer_days', MAX_TIMER_DAYS)} days\n\n"
        f"### Glory Fight\nTarget: {glory['name']} (slot: after fight {glory_slot})\n"
        f"{glory['desc']}\nBonus: {glory['reward_bonus']}\n\n"
        f"### Live Scaling\n{_party_scaling_note(strength)}\n\n"
        f"### Pocket Fights\n"
        + "\n".join(f"- Fight {f['index']}: {f['name']} — {f['grunt_count']} grunts, CR {f['cr_target']}" for f in pocket_fights)
        + f"\n\n### Debrief Location\n{briefing.get('debrief_location', '')}\n"
    )

    players_md = (
        f"## Player Brief\n{briefing.get('contact_speech','')}\n\n"
        f"### Situation\n{briefing.get('situation','')}\n\n"
        f"### Win Conditions\n"
        + "\n".join(f"- {w}" for w in briefing.get("win_conditions", []))
        + f"\n\n### Allied Support Available\n"
        + "\n".join(f"- **{a.get('name','')}** ({a.get('trigger','')}): {a.get('effect','')}" for a in support_actions)
    )

    chart_md = (
        f"## Battle Chart Pack\n"
        f"### Battle Tide\nCrushing → Winning → Even → Losing → Broken\n\n"
        f"### Pocket Fights\n"
        + "\n".join(
            f"| Fight {f['index']} | {f['name']} | {f['grunt_count']} grunts | CR {f['cr_target']} | Reinforce {f['reinforce_chance']}% |"
            for f in pocket_fights
        )
        + f"\n\n### Glory Fight\n{glory['name']} — {glory['desc']}\n"
        f"CR bonus: +{glory['cr_bonus']} | Reward: {glory['reward_bonus']}\n\n"
        f"### Support Actions\n"
        + "\n".join(f"- {a.get('name','')} ({a.get('trigger','')}): {a.get('effect','')}" for a in support_actions)
    )

    write_component(out_dir, "dm_guide",      "DM Guide",      title, hiring_faction, dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, hiring_faction, players_md)
    write_component(out_dir, "chart_pack",    "Chart Pack",    title, hiring_faction, chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",      "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",           "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Battle Tide & Fights","type": "custom",     "content": chart_md},
        ])

    maps_name = write_maps_page(out_dir, title, hiring_faction, [map_path] if map_path else [])
    box_components = component_links(has_maps=bool(maps_name))

    # Index
    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title, faction=hiring_faction, tier=tier,
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
        logger.warning(f"[BATTLE] index.html failed: {_e}")
        index_path = out_dir / "module.html"

    # DB slug
    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as _e:
        logger.warning(f"[BATTLE] Could not write module_slug: {_e}")

    # Zip
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[BATTLE] Complete: {title!r} → {out_dir.name}")
    return index_path
