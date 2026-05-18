"""
ambush_pipeline.py - Pipeline for Ambush mission modules.

The party is the ambushing side. They get a large tactical map, choose where to
set up, and do not know which route the moving target will take. The module
uses DB canon first: factions, NPCs, adventurer parties, locations, and live
player-character snapshots.

Core shape:
  1. Resolve roles - hiring faction, guarding faction, target/source faction,
     optional interference faction.
  2. Pick target - person, item, or convoy/group.
  3. Pick guard roster - faction-appropriate; Adventurers Guild uses DB party
     profiles when available.
  4. Build map plan - multiple approach routes, one actual route for the DM.
  5. Prep - max traps = party size + 1.
  6. Ambush - target moves on a 5-foot grid, usually 4 squares / 20 ft per turn.
  7. Escape - after the hit, the party should get away and may try to stay
     anonymous.
  8. Debrief - varies by faction and heat.

Exported:
    build_ambush_module(mission: dict, out_dir: Path) -> Path
    is_ambush_mission(mission_type: str) -> bool
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

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "generated_modules"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")


# ---------------------------------------------------------------------------
# Mission type detection
# ---------------------------------------------------------------------------

_AMBUSH_KEYWORDS = {
    "ambush", "hit the convoy", "hit a convoy", "intercept", "waylay",
    "roadside hit", "strike convoy", "stop the courier", "stop a courier",
}

def is_ambush_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _AMBUSH_KEYWORDS)


# ---------------------------------------------------------------------------
# Static fallback data - used only when DB/API lacks usable canon
# ---------------------------------------------------------------------------

FALLBACK_FACTIONS = [
    "Iron Fang Consortium",
    "Argent Blades",
    "Wardens of Ash",
    "Serpent Choir",
    "Obsidian Lotus",
    "Glass Sigil",
    "Patchwork Saints",
    "Adventurers Guild",
    "Guild of Ashen Scrolls",
    "Tower Authority",
    "Brother Thane's Cult",
    "Wizards Tower",
]

TARGET_TYPES = ["person", "item", "convoy"]

OBJECTIVES = {
    "person": [
        "capture the target alive and remove them from the map",
        "kill the target and escape before the guard identifies the party",
        "interrogate the target briefly, then withdraw",
        "plant false evidence on the target without being identified",
    ],
    "item": [
        "steal the item and escape with it intact",
        "destroy the item before it reaches its destination",
        "swap the item with a false copy and remain anonymous",
        "mark the item for later tracking without alerting the guard",
    ],
    "convoy": [
        "disable the convoy and seize the cargo",
        "delay the convoy long enough for another operation to happen",
        "destroy the lead vehicle or wagon and withdraw",
        "force the convoy to reroute into a prepared secondary trap",
    ],
}

BONUS_OBJECTIVES = [
    "No guards die.",
    "No civilians can identify the party.",
    "The target/source faction never learns who hired the hit.",
    "The party leaves no magical signature behind.",
    "The target is taken before the third round of combat ends.",
    "The party escapes before reinforcements arrive.",
    "The map still looks like an accident afterward.",
]

TRAP_MENU = [
    {
        "name": "Snare / Net",
        "setup": "DC 13 Survival or Sleight of Hand",
        "effect": "Restrains one Large or smaller creature until DC 14 Strength check breaks it.",
    },
    {
        "name": "Caltrops",
        "setup": "No check if placed slowly; DC 13 Sleight of Hand if hidden",
        "effect": "First creature entering the square makes DC 13 Dex save or stops and loses 10 ft speed.",
    },
    {
        "name": "Tripwire Alarm",
        "setup": "DC 12 Sleight of Hand",
        "effect": "Silent signal to the party, or loud clatter if they choose to spook the guard.",
    },
    {
        "name": "Falling Crate / Sign",
        "setup": "DC 14 Athletics or Tinker's Tools",
        "effect": "DC 13 Dex save or 2d6 bludgeoning and prone; creates difficult terrain.",
    },
    {
        "name": "Smoke Pot",
        "setup": "DC 12 Alchemist's Supplies or Sleight of Hand",
        "effect": "Creates a 20 ft heavily obscured cloud for 3 rounds.",
    },
    {
        "name": "Grease Patch",
        "setup": "DC 12 Sleight of Hand",
        "effect": "10 ft square; DC 13 Dex save or prone. Counts as difficult terrain.",
    },
    {
        "name": "Flash Rune",
        "setup": "DC 14 Arcana",
        "effect": "DC 13 Con save or blinded until end of next turn. Obvious magical heat if witnessed.",
    },
    {
        "name": "Pit / Weak Floor",
        "setup": "DC 15 Survival or Mason's Tools",
        "effect": "DC 14 Dex save or fall 10 ft, take 1d6 damage, and be separated from formation.",
    },
    {
        "name": "Barricade",
        "setup": "DC 12 Athletics",
        "effect": "Blocks 2 adjacent squares until smashed; AC 12, HP 20.",
    },
    {
        "name": "False Signal / Bait Marker",
        "setup": "DC 13 Deception or Performance",
        "effect": "Guard lead must beat DC 13 Insight or sends one escort to investigate.",
    },
]

HEAT_STATES = [
    {
        "state": "Unseen",
        "trigger": "No witnesses, no signature magic, fast escape.",
        "effect": "No one can tie the ambush to the party.",
    },
    {
        "state": "Suspected",
        "trigger": "Clues point toward the party, but no proof.",
        "effect": "Debrief may include warnings, reduced trust, or quiet faction irritation.",
    },
    {
        "state": "Exposed",
        "trigger": "The target, guards, or witnesses identify the party.",
        "effect": "Guarding/source faction reacts directly; future jobs may get harder.",
    },
    {
        "state": "Wanted",
        "trigger": "Public violence, civilian casualties, or failed escape.",
        "effect": "Formal complaint, Authority heat, or an assassin/observer may be assigned.",
    },
]

FACTION_GUARD_BEHAVIOR = {
    "Wardens of Ash": "form a shield line, put bodies between the party and the target, and keep the target moving",
    "Argent Blades": "split response: half protect the target while the rest counterattack hard",
    "Tower Authority": "lock down the area, call procedure-based reinforcements, and preserve evidence",
    "Obsidian Lotus": "treat obvious ambush spots as bait; hidden counter-ambushers may already be watching",
    "Glass Sigil": "use proxies, decoys, bribes, and legal/social pressure before direct violence",
    "Patchwork Saints": "scatter into improvised cover, protect each other, and try to destroy dangerous cargo if needed",
    "Serpent Choir": "protect the target through ritual discipline and sudden fanatic violence",
    "Brother Thane's Cult": "absorb losses without flinching and try to drag the target toward a prepared extraction point",
    "Guild of Ashen Scrolls": "protect records and specialists first; arguments inside the escort can slow their response",
    "Iron Fang Consortium": "calculate losses, secure the asset, and abandon replaceable guards if needed",
    "Wizards Tower": "use wards, reaction magic, and fragile but dangerous specialists",
    "Adventurers Guild": "reacts like a balanced NPC adventuring party: front line, striker, support, and problem-solver",
}

MAP_ARCHETYPES = [
    {
        "name": "Street-Side Market Cut",
        "prompt": "Town Exterior Table Map, dense market street, narrow vendor lanes, alley exits, carts and objects, multiple approach roads",
        "routes": ["north market gate", "east vendor lane", "south canal steps", "west alley mouth"],
    },
    {
        "name": "Canal Bridge Crossing",
        "prompt": "Town Exterior Table Map, canal bridge, tight streets, water edge, stone railings, side alleys, objects and crates",
        "routes": ["north bridge approach", "east canal walk", "south bridge approach", "west service alley"],
    },
    {
        "name": "Checkpoint Street",
        "prompt": "Town Exterior Table Map, urban checkpoint, barricades, guard booth, narrow street, side lanes, objects, constrained movement",
        "routes": ["main checkpoint road", "inspection lane", "side alley", "rear service path"],
    },
    {
        "name": "Sewer Split",
        "prompt": "Dungeon Interior Table Map, sewer tunnel junction, narrow walkways, water channels, maintenance rooms, grates and objects",
        "routes": ["north tunnel", "east drain walk", "south cistern path", "west maintenance gate"],
    },
    {
        "name": "Rooftop Drop",
        "prompt": "Town Exterior Table Map, rooftops, bridges between buildings, chimneys, skylights, alley below, objects, constrained paths",
        "routes": ["north roofline", "east skybridge", "south stairwell", "west clothesline roofs"],
    },
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_rows(query: str, params: tuple = ()) -> List[Dict]:
    try:
        from src.db_api import raw_query
        return raw_query(query, params) or []
    except Exception as e:
        logger.warning(f"[AMBUSH] DB read failed: {e}")
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


def _canonical_factions() -> List[Dict]:
    rows = _db_rows(
        "SELECT faction_name, reputation_score, tier, leader, location_name, description, motto "
        "FROM faction_reputation ORDER BY faction_name"
    )
    if rows:
        return rows
    return [{"faction_name": f, "tier": "", "leader": "", "description": ""} for f in FALLBACK_FACTIONS]


def _canon_name(name: str, factions: List[Dict]) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    for row in factions:
        fname = (row.get("faction_name") or "").strip()
        if low == fname.lower() or low in fname.lower() or fname.lower() in low:
            return fname
    return raw


def _pick_other_faction(factions: List[Dict], avoid: List[str]) -> str:
    avoid_lows = {a.lower() for a in avoid if a}
    names = [r.get("faction_name") for r in factions if r.get("faction_name") and r.get("faction_name").lower() not in avoid_lows]
    return random.choice(names or FALLBACK_FACTIONS)


def _resolve_roles(mission: dict) -> Dict[str, str]:
    factions = _canonical_factions()
    hiring = _canon_name(mission.get("faction") or mission.get("hiring_faction") or "", factions)
    if not hiring:
        hiring = _pick_other_faction(factions, [])

    guarding = _canon_name(
        mission.get("guarding_faction") or mission.get("opposing_faction") or mission.get("guard_faction") or "",
        factions,
    )
    if not guarding:
        guarding = _pick_other_faction(factions, [hiring])

    source = _canon_name(
        mission.get("target_source_faction") or mission.get("source_faction") or mission.get("owner_faction") or "",
        factions,
    )
    if not source:
        source = random.choice([guarding, _pick_other_faction(factions, [hiring, guarding])])

    interference = _canon_name(
        mission.get("interference_faction") or mission.get("third_party_faction") or "",
        factions,
    )
    if not interference and random.random() < 0.35:
        interference = _pick_other_faction(factions, [hiring, guarding, source])

    return {
        "hiring": hiring,
        "guarding": guarding,
        "source": source,
        "interference": interference,
    }


def _party_strength() -> Dict[str, Any]:
    rows = _db_rows(
        "SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots "
        "ORDER BY fetched_at DESC"
    )
    pcs = []
    for row in rows:
        snap = _json_col(row.get("snapshot_json"), {})
        if not isinstance(snap, dict):
            continue
        level = int(snap.get("total_level") or 0)
        hp = int(snap.get("max_hp") or 0)
        if level <= 0:
            continue
        pcs.append({
            "name": snap.get("name") or row.get("char_name"),
            "level": level,
            "classes": snap.get("classes") or {},
            "max_hp": hp,
            "fetched_at": str(row.get("fetched_at") or snap.get("fetched_at") or ""),
        })
    if not pcs:
        rows = _db_rows("SELECT name, profile_json FROM player_characters ORDER BY updated_at DESC")
        for row in rows:
            profile = _json_col(row.get("profile_json"), {})
            class_text = str(profile.get("CLASS") or "")
            nums = [int(n) for n in re.findall(r"\b(\d{1,2})\b", class_text)]
            level = max(nums) if nums else 5
            pcs.append({"name": row.get("name"), "level": level, "classes": class_text[:80], "max_hp": 0})

    levels = [p["level"] for p in pcs] or [5]
    return {
        "party_size": len(pcs) or 4,
        "avg_level": round(sum(levels) / len(levels), 1),
        "max_level": max(levels),
        "trap_limit": (len(pcs) or 4) + 1,
        "pcs": pcs,
    }


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    return (
        f"Live party read: {strength['party_size']} PCs, average level "
        f"{strength['avg_level']}, max level {strength['max_level']}."
    )


def _pick_location() -> Dict[str, str]:
    rows = _db_rows(
        "SELECT district, place_type, name, type_tag, description, wealth_level "
        "FROM gazetteer_places ORDER BY RAND() LIMIT 1"
    )
    if rows:
        row = rows[0]
        return {
            "district": row.get("district") or "Unknown District",
            "name": row.get("name") or "unknown street",
            "type": row.get("type_tag") or row.get("place_type") or "city route",
            "description": row.get("description") or "",
            "wealth_level": str(row.get("wealth_level") or ""),
        }
    return {
        "district": "Markets Infinite",
        "name": "a constricted side street",
        "type": "street-side route",
        "description": "A tight urban route with too many corners and not enough exits.",
        "wealth_level": "5",
    }


def _npcs_for_faction(faction: str, limit: int = 8) -> List[Dict]:
    return _db_rows(
        "SELECT name, faction, role, location, status, data_json FROM npcs "
        "WHERE status IN ('alive','injured','undead','doppelganger') "
        "AND faction LIKE %s ORDER BY RAND() LIMIT %s",
        (f"%{faction}%", limit),
    )


def _pick_adventurer_party(strength: Dict[str, Any]) -> Optional[Dict]:
    rows = _db_rows(
        "SELECT party_name, reputation, status, profile_json, members_json "
        "FROM party_profiles WHERE status = 'active' ORDER BY RAND() LIMIT 30"
    )
    usable = []
    for row in rows:
        profile = _json_col(row.get("profile_json"), {}) or _json_col(row.get("members_json"), {})
        members = profile.get("members") if isinstance(profile, dict) else []
        if not members:
            continue
        usable.append((row, profile))
    if not usable:
        names = _db_rows("SELECT party_name FROM party_profiles ORDER BY RAND() LIMIT 1")
        if names:
            return {"name": names[0].get("party_name"), "members": [], "note": "Name pulled from adventurer_parties; full profile missing."}
        return None
    row, profile = random.choice(usable)
    return {
        "name": row.get("party_name") or profile.get("name") or "Unknown Party",
        "members": profile.get("members") or [],
        "tier": profile.get("tier") or "Unknown",
        "specialty": profile.get("specialty") or "General contracts",
        "reputation_note": profile.get("reputation_note") or "",
        "level_note": f"Tune as up to party level + 4. Current max PC level: {strength['max_level']}.",
    }


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

async def _ollama(prompt: str, tokens: int = 1000) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.85, "num_predict": tokens},
    }
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("ambush_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[AMBUSH] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[AMBUSH] Ollama error: {e}")
        return ""


def _clean_json(raw: str) -> str:
    raw = re.sub(r"[“”]", '"', raw or "")
    raw = re.sub(r"[‘’]", "'", raw)
    cleaned, in_string = [], False
    for i, ch in enumerate(raw):
        if ch == '"' and (i == 0 or raw[i - 1] != "\\"):
            in_string = not in_string
        if in_string and ch in "\r\n":
            cleaned.append(" ")
        else:
            cleaned.append(ch)
    return "".join(cleaned)


def _parse_json(raw: str) -> Optional[dict]:
    for attempt in (raw, _clean_json(raw)):
        m = re.search(r"\{[\s\S]*\}", attempt or "")
        if not m:
            continue
        try:
            return json.loads(m.group())
        except Exception:
            continue
    return None


def _target_seed(mission: dict, roles: Dict[str, str]) -> Dict:
    target_type = (mission.get("target_type") or "").lower().strip()
    if target_type not in TARGET_TYPES:
        text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
        if any(k in text for k in ("convoy", "caravan", "wagon", "patrol", "transfer")):
            target_type = "convoy"
        elif any(k in text for k in ("item", "relic", "cargo", "package", "vial", "rose", "memory")):
            target_type = "item"
        else:
            target_type = random.choice(TARGET_TYPES)

    target_name = mission.get("target_name") or mission.get("target") or ""
    if not target_name and target_type == "person":
        npcs = _npcs_for_faction(roles["source"], 5) or _npcs_for_faction(roles["guarding"], 5)
        if npcs:
            n = random.choice(npcs)
            target_name = n.get("name")
    if not target_name:
        target_name = {
            "person": "a protected faction asset",
            "item": random.choice(["a bottled rose", "a sealed memory case", "a soul-vial packet", "a courier lockbox"]),
            "convoy": random.choice(["a guarded courier team", "a prisoner transfer", "a cargo wagon", "a faction patrol convoy"]),
        }[target_type]

    primary = random.choice(OBJECTIVES[target_type])
    bonus = random.choice(BONUS_OBJECTIVES)
    return {"type": target_type, "name": target_name, "primary": primary, "bonus": bonus}


async def _generate_target_details(mission: dict, target: Dict, roles: Dict[str, str]) -> Dict:
    prompt = f"""Write target mechanics for a D&D ambush mission.

Target type: {target['type']}
Target name: {target['name']}
Source faction: {roles['source']}
Guarding faction: {roles['guarding']}
Mission title: {mission.get('title', 'Ambush')}
Mission notes: {(mission.get('body') or mission.get('description') or '')[:400]}

Return JSON only:
{{
  "description": "2 sentences describing what the target is and why it matters",
  "durability": "HP/AC/speed/handling as appropriate; a paladin can be tanky, a bottled rose delicate",
  "panic_or_resist": "how the target behaves once the ambush starts",
  "capture_note": "what makes capture, theft, destruction, or delay difficult"
}}"""
    data = _parse_json(await _ollama(prompt, tokens=700))
    if data:
        return data
    if target["type"] == "item":
        return {
            "description": f"{target['name']} belongs to {roles['source']} and is fragile enough that careless violence can ruin the job.",
            "durability": "AC 11, HP 6, destroyed by a strong direct hit or obvious area damage unless protected.",
            "panic_or_resist": "The item does not resist, but whoever carries it will try to flee.",
            "capture_note": "Taking it quietly is easier than taking it intact under fire.",
        }
    if target["type"] == "convoy":
        return {
            "description": f"{target['name']} moves under {roles['guarding']} protection through a constrained route.",
            "durability": "Lead wagon/cart AC 13, HP 35, speed 20 ft; wheels can be disabled at AC 15, HP 10 each.",
            "panic_or_resist": "Drivers push forward unless blocked; guards try to keep the convoy moving.",
            "capture_note": "Stopping the vehicle is only half the job; the cargo still has to be seized or destroyed.",
        }
    return {
        "description": f"{target['name']} is moving under guard and must be handled according to the objective.",
        "durability": "AC 13, HP 30, speed 20 ft; adjust upward for elite/tanky targets and downward for civilians.",
        "panic_or_resist": "They move 4 squares per turn toward safety unless slowed, stunned, prone, restrained, or blocked.",
        "capture_note": "Capture requires control, not just damage.",
    }


def _guard_roster(roles: Dict[str, str], strength: Dict[str, Any]) -> Dict:
    faction = roles["guarding"]
    behavior = FACTION_GUARD_BEHAVIOR.get(faction, "protect the target, keep moving, and call for help if pinned")
    if faction.lower() == "adventurers guild":
        party = _pick_adventurer_party(strength)
        if party:
            members = []
            for m in party.get("members", []):
                if isinstance(m, dict):
                    members.append({
                        "name": m.get("name") or "Unnamed member",
                        "role": m.get("role") or m.get("class") or m.get("class_name") or "adventurer",
                        "note": m.get("personality") or m.get("note") or m.get("species") or "",
                    })
                else:
                    members.append({"name": str(m), "role": "adventurer", "note": ""})
            return {
                "style": "Adventurers Guild NPC party",
                "behavior": behavior,
                "party_name": party.get("name"),
                "members": members,
                "note": party.get("level_note") or f"Tune up to party level + 4. Current max PC level: {strength['max_level']}.",
            }

    npcs = _npcs_for_faction(faction, 5)
    roster = []
    if npcs:
        for npc in npcs[:5]:
            roster.append({
                "name": npc.get("name") or "Unnamed guard",
                "role": npc.get("role") or "faction guard",
                "note": npc.get("location") or "",
            })
    else:
        roster = [
            {"name": "Lead Guard", "role": "commander / handler", "note": "calls the first response"},
            {"name": "Escort Pair", "role": "2-4 escorts", "note": "body-block and move with the target"},
            {"name": "Specialist", "role": "caster, scout, or heavy", "note": "faction-specific trick"},
            {"name": "Lookout", "role": "reserve / signaler", "note": "calls reinforcements or spots traps"},
        ]
    return {"style": f"{faction} guard roster", "behavior": behavior, "members": roster, "note": "Faction-appropriate roster from DB when possible."}


def _map_plan() -> Dict:
    arch = random.choice(MAP_ARCHETYPES)
    routes = list(arch["routes"])
    random.shuffle(routes)
    chosen = random.choice(routes)
    markers = []
    coords = [(10, 12), (88, 18), (82, 84), (14, 78), (50, 8), (50, 90)]
    for i, route in enumerate(routes[:4]):
        x, y = coords[i]
        markers.append({"label": str(i + 1), "route": route, "x": x, "y": y, "actual": route == chosen})
    return {"name": arch["name"], "prompt": arch["prompt"], "routes": routes[:4], "chosen": chosen, "markers": markers}


async def _generate_briefing(mission: dict, roles: Dict[str, str], target: Dict, location: Dict, map_plan: Dict) -> Dict:
    prompt = f"""Write a D&D ambush mission briefing.

Hiring faction: {roles['hiring']}
Guarding faction: {roles['guarding']}
Target/source faction: {roles['source']}
Interference faction: {roles.get('interference') or 'none'}
Target: {target['name']} ({target['type']})
Primary objective: {target['primary']}
Bonus objective: {target['bonus']}
Location: {location['name']} in {location['district']}
Map type: {map_plan['name']}

Important facts:
- The party chooses their own setup spot on the map.
- They know the guarding faction, but not which route the target will use.
- After the hit, they should escape and may want to stay anonymous.

Return JSON only:
{{
  "contact_speech": "2-3 paragraphs from the hiring contact",
  "known_intel": "what the party knows before choosing setup",
  "unknowns": "what they do not know",
  "debrief_style": "where/how the hiring faction wants the debrief"
}}"""
    data = _parse_json(await _ollama(prompt, tokens=900))
    if data:
        return data
    return {
        "contact_speech": f"{roles['hiring']} wants {target['name']} hit before it clears {location['name']}. The guards are {roles['guarding']}. Pick your spot, do the job, and get away clean.",
        "known_intel": f"The target crosses {location['district']} under {roles['guarding']} protection.",
        "unknowns": "The exact entry route is unknown until the target appears.",
        "debrief_style": "Varies by heat; clean work gets a quiet handoff, messy work gets a colder meeting.",
    }


async def _check_a1111() -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{A1111_URL}/sdapi/v1/progress")
            return r.status_code == 200
    except Exception:
        return False


async def _generate_map(map_plan: Dict, location: Dict, roles: Dict[str, str], out_dir: Path) -> Optional[Path]:
    out = out_dir / "ambush_map.png"
    import re
    _style = map_plan["prompt"]
    # Strip SD1.5 LoRA prefix tokens (meaningless to Flux)
    _style = re.sub(r'(?:Big |Small )?(?:[\w]+ )*?Table Map[, ]+', '', _style, count=1, flags=re.IGNORECASE).strip(', ')
    is_dungeon = "dungeon" in _style.lower() or "Sewer" in map_plan["name"]
    lora_name = os.getenv("A1111_MAP_LORA_DUNGEON" if is_dungeon else "A1111_MAP_LORA_TOWN",
                           "EnvyFluxDungeonMap01" if is_dungeon else "EnvyFluxFantasyTownMap01")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    triggers = os.getenv("A1111_MAP_DUNGEON_TRIGGERS" if is_dungeon else "A1111_MAP_TOWN_TRIGGERS",
                          "detailed, map, dungeon" if is_dungeon else "detailed, map, village")
    positive = ", ".join(filter(None, [
        f"<lora:{lora_name}:{lora_weight}>",
        triggers,
        _style,
        "multiple visible approach lanes, constricted movement, places for ambushers to hide",
        f"district: {location.get('district')}, {location.get('type')}",
        "high fantasy cyberpunk fusion, wealth-stratified city",
    ]))
    negative = "characters, people, isometric, perspective, watermark, text"
    payload = {
        "prompt": positive,
        "negative_prompt": negative,
        "width": 1024,
        "height": 1024,
        "steps": 20,
        "cfg_scale": 1.0,
        "sampler_name": "Euler",
        "seed": -1,
    }
    _map_ckpt = os.getenv("A1111_MAP_CHECKPOINT", "")
    if _map_ckpt:
        override: dict = {"sd_model_checkpoint": _map_ckpt}
        payload["override_settings"] = override
        payload["override_settings_restore_afterwards"] = True
    try:
        from src.news_feed import a1111_lock
        from src.resource_cop import wait_for_a1111_turn
        decision = await wait_for_a1111_turn("ambush_map", max_wait_seconds=60)
        if not decision.run_now:
            logger.info(f"[AMBUSH] A1111 deferred by resource cop: {decision.reason}")
            from src.mission_builder.vtt_renderer import save_vtt_battlemap
            save_vtt_battlemap(out, None, context={"title": location.get("name"), "location": location, "prompt": positive, "kind": "ambush street"})
            return out
        async with a1111_lock:
            async with httpx.AsyncClient(timeout=600.0) as c:
                r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                r.raise_for_status()
                images = r.json().get("images", [])
        if not images:
            raise RuntimeError("A1111 returned no images")
        from src.mission_builder.vtt_renderer import save_vtt_battlemap
        save_vtt_battlemap(out, images[0], context={"title": location.get("name"), "location": location, "prompt": positive, "kind": "ambush street"})
        return out
    except Exception as e:
        logger.error(f"[AMBUSH] Map generation failed: {e}")
        from src.mission_builder.vtt_renderer import save_vtt_battlemap
        save_vtt_battlemap(out, None, context={"title": location.get("name"), "location": location, "prompt": positive, "kind": "ambush street"})
        return out


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _card(title: str, body: str, color: str) -> str:
    return f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;padding:14px 18px;margin:14px 0;background:#fff;">' \
           f'<h2 style="margin:0 0 8px;color:{color};">{title}</h2>{body}</div>'


def _map_html(map_path: Optional[Path], map_plan: Dict, out_dir: Path, fc: str, dm: bool) -> str:
    if not map_path or not map_path.exists():
        route_rows = "".join(
            f'<li><strong>{_e(m["label"])}.</strong> {_e(m["route"])}{" — ACTUAL ROUTE" if dm and m["actual"] else ""}</li>'
            for m in map_plan["markers"]
        )
        return f'<div style="padding:12px;background:#f5f5f5;border-radius:6px;"><strong>{_e(map_plan["name"])}</strong><ul>{route_rows}</ul></div>'
    rel = map_path.relative_to(out_dir)
    markers = ""
    if dm:
        for m in map_plan["markers"]:
            bg = "#7b1e1e" if m["actual"] else "#b8923a"
            label = f'{m["label"]}*' if m["actual"] else m["label"]
            markers += (
                f'<div title="{_e(m["route"])}" style="position:absolute;left:{m["x"]}%;top:{m["y"]}%;'
                f'transform:translate(-50%,-50%);width:30px;height:30px;border-radius:50%;'
                f'background:{bg};color:white;font-weight:bold;display:flex;align-items:center;'
                f'justify-content:center;border:2px solid white;box-shadow:0 1px 5px #000;">{_e(label)}</div>'
            )
    title = "DM Reference Map - possible entries and actual route" if dm else "Player Map - choose the ambush spot"
    return (
        f'<div style="margin:16px 0;">'
        f'<div style="font-weight:bold;margin-bottom:6px;color:{("#7b1e1e" if dm else fc)};">{title}</div>'
        f'<div style="position:relative;display:inline-block;max-width:100%;">'
        f'<img src="{rel}" style="max-width:100%;border:3px solid {("#7b1e1e" if dm else fc)};border-radius:8px;" alt="Ambush Map">'
        f'{markers}</div></div>'
    )


def _roster_html(guard: Dict) -> str:
    rows = ""
    for m in guard.get("members", []):
        rows += f'<tr><td style="padding:6px 8px;font-weight:bold;">{_e(m.get("name"))}</td><td style="padding:6px 8px;">{_e(m.get("role"))}</td><td style="padding:6px 8px;">{_e(m.get("note"))}</td></tr>'
    party = f'<div><strong>Party:</strong> {_e(guard.get("party_name"))}</div>' if guard.get("party_name") else ""
    return (
        f'{party}<div style="font-size:13px;margin:4px 0;"><strong>Behavior:</strong> {_e(guard.get("behavior"))}</div>'
        f'<div style="font-size:12px;color:#555;margin:4px 0;">{_e(guard.get("note"))}</div>'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;"><thead><tr style="background:#eee;">'
        f'<th style="text-align:left;padding:6px 8px;">Name</th><th style="text-align:left;padding:6px 8px;">Role</th><th style="text-align:left;padding:6px 8px;">Note</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
    )


def _trap_menu(limit: int) -> str:
    rows = "".join(
        f'<tr><td style="padding:6px 8px;"><input type="checkbox"> {_e(t["name"])}</td>'
        f'<td style="padding:6px 8px;">{_e(t["setup"])}</td><td style="padding:6px 8px;">{_e(t["effect"])}</td></tr>'
        for t in TRAP_MENU
    )
    slots = " ".join('<input type="checkbox" style="width:18px;height:18px;margin:2px;">' for _ in range(limit))
    return (
        f'<p><strong>Max placed traps:</strong> party size + 1 = {limit}</p>'
        f'<div style="margin:8px 0;"><strong>Trap slots:</strong> {slots}</div>'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;"><thead><tr style="background:#eee;">'
        f'<th style="text-align:left;padding:6px 8px;">Trap</th><th style="text-align:left;padding:6px 8px;">Setup</th><th style="text-align:left;padding:6px 8px;">Effect</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
    )


def _heat_html() -> str:
    rows = "".join(
        f'<tr><td style="padding:6px 8px;font-weight:bold;">{_e(h["state"])}</td><td style="padding:6px 8px;">{_e(h["trigger"])}</td><td style="padding:6px 8px;">{_e(h["effect"])}</td></tr>'
        for h in HEAT_STATES
    )
    return f'<table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody>{rows}</tbody></table>'


def render_ambush_module(
    mission: dict,
    roles: Dict[str, str],
    target: Dict,
    target_details: Dict,
    guard: Dict,
    location: Dict,
    map_plan: Dict,
    briefing: Dict,
    strength: Dict[str, Any],
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title = mission.get("title", "Ambush")
    fc = _faction_color(roles["hiring"])
    routes = "".join(
        f'<li><strong>{_e(m["label"])}.</strong> {_e(m["route"])}{" <strong>(actual route)</strong>" if m["actual"] else ""}</li>'
        for m in map_plan["markers"]
    )
    body = ""
    body += _card("Briefing",
        f'<div style="white-space:pre-line;font-style:italic;">{_e(briefing.get("contact_speech"))}</div>'
        f'<p><strong>Known:</strong> {_e(briefing.get("known_intel"))}</p>'
        f'<p><strong>Unknown:</strong> {_e(briefing.get("unknowns"))}</p>', fc)
    body += _card("Faction Roles",
        f'<p><strong>Hiring:</strong> {_e(roles["hiring"])}<br>'
        f'<strong>Guarding:</strong> {_e(roles["guarding"])}<br>'
        f'<strong>Target/source:</strong> {_e(roles["source"])}<br>'
        f'<strong>Interference:</strong> {_e(roles.get("interference") or "None")}</p>', "#555")
    body += _card("Target",
        f'<p><strong>{_e(target["name"])}</strong> ({_e(target["type"])})</p>'
        f'<p>{_e(target_details.get("description"))}</p>'
        f'<p><strong>Durability:</strong> {_e(target_details.get("durability"))}</p>'
        f'<p><strong>Behavior:</strong> {_e(target_details.get("panic_or_resist"))}</p>'
        f'<p><strong>Primary:</strong> {_e(target["primary"])}<br><strong>Bonus:</strong> {_e(target["bonus"])}</p>', "#7b1e1e")
    body += _card("Guard Roster", _roster_html(guard), "#8a5a1f")
    body += _card("Maps",
        _map_html(map_path, map_plan, out_dir, fc, dm=False)
        + _map_html(map_path, map_plan, out_dir, fc, dm=True)
        + f'<p><strong>DM route roll:</strong></p><ol>{routes}</ol>'
        + f'<p><strong>Actual route:</strong> {_e(map_plan["chosen"])}</p>', fc)
    body += _card("Setup Tools", _trap_menu(strength["trap_limit"]), "#2a6a2a")
    body += _card("Movement And Escape",
        '<p>Each square is 5 feet. Most targets move 4 squares / 20 feet per turn unless slowed, stunned, prone, restrained, blocked, or redirected by guards.</p>'
        '<p>After the objective resolves, the party should withdraw. Capture, theft, planting, and clean kills all become worse if the party stays long enough to be identified.</p>', "#3a6898")
    body += _card("Heat / Anonymity", _heat_html(), "#7b1e1e")
    body += _card("Debrief",
        f'<p>{_e(briefing.get("debrief_style"))}</p>'
        '<p><strong>Heat result:</strong> <select><option>Unseen</option><option>Suspected</option><option>Exposed</option><option>Wanted</option></select></p>'
        '<p><strong>Objective:</strong> <select><option>Primary complete</option><option>Primary + bonus complete</option><option>Partial success</option><option>Failed</option></select></p>'
        '<textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Debrief notes..."></textarea>', "#555")
    return _page(title, body, roles["hiring"])


def render_ambush_session(
    mission: dict,
    roles: Dict[str, str],
    target: Dict,
    guard: Dict,
    map_plan: Dict,
    strength: Dict[str, Any],
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title = mission.get("title", "Ambush")
    fc = _faction_color(roles["hiring"])
    body = f'<h1 style="color:{fc};">{_e(title)}</h1>'
    body += _card("Objective", f'<p><strong>Primary:</strong> {_e(target["primary"])}</p><p><strong>Bonus:</strong> {_e(target["bonus"])}</p>', fc)
    body += _card("Map", _map_html(map_path, map_plan, out_dir, fc, dm=False), fc)
    body += _card("Setup", _trap_menu(strength["trap_limit"]), "#2a6a2a")
    body += _card("Guard", f'<p><strong>{_e(roles["guarding"])}</strong>: {_e(guard.get("behavior"))}</p>', "#8a5a1f")
    body += _card("Escape / Heat",
        '<p><strong>Heat:</strong> <select><option>Unseen</option><option>Suspected</option><option>Exposed</option><option>Wanted</option></select></p>'
        '<p><strong>Escaped:</strong> <input type="checkbox"></p>'
        '<textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Session notes..."></textarea>', "#7b1e1e")
    return _page(title, body, roles["hiring"])


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


async def build_ambush_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Ambush")
    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    roles = _resolve_roles(mission)
    strength = _party_strength()
    location = _pick_location()
    target = _target_seed(mission, roles)
    guard = _guard_roster(roles, strength)
    map_plan = _map_plan()

    logger.info(
        f"[AMBUSH] Building {title!r} | hiring={roles['hiring']} guarding={roles['guarding']} "
        f"target={target['type']} party_size={strength['party_size']} avg_level={strength['avg_level']}"
    )

    details_task = asyncio.create_task(_generate_target_details(mission, target, roles))
    briefing_task = asyncio.create_task(_generate_briefing(mission, roles, target, location, map_plan))
    target_details, briefing = await asyncio.gather(details_task, briefing_task)

    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            map_path = await _generate_map(map_plan, location, roles, out_dir)
        else:
            logger.warning("[AMBUSH] A1111 not available - skipping map")

    from src.mission_builder.mimir_module import create_module as _mc, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="ambush")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Ambush Map")
    module_html = render_ambush_module(
        mission, roles, target, target_details, guard, location, map_plan,
        briefing, strength, map_path, out_dir,
    )
    module_html += _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")

    session_html = render_ambush_session(
        mission, roles, target, guard, map_plan, strength, map_path, out_dir,
    )
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    dm_md = (
        f"## Ambush DM Guide\n"
        f"### Job Truth\n"
        f"- Hiring faction: {roles['hiring']}\n"
        f"- Guarding faction: {roles['guarding']}\n"
        f"- Target type: {target['type']}\n"
        f"- Primary objective: {target['primary']}\n"
        f"- Bonus objective: {target['bonus']}\n\n"
        f"### Target Details\n{target_details}\n\n"
        f"### Guard Roster\n{guard.get('behavior', '')}\n\n"
        f"### Route Secret\nThe party gets the map and chooses setup spots. The target route and arrival direction stay DM-only.\n\n"
        f"### Live Scaling\n{_party_scaling_note(strength)} Trap limit is party size + 1: {strength['trap_limit']}."
    )
    players_md = (
        f"## Player Brief\n{briefing.get('contact_speech', '')}\n\n"
        f"### Known Assignment\n"
        f"- Target: {target['type']}\n"
        f"- Guarding faction: {roles['guarding']}\n"
        f"- Primary objective: {target['primary']}\n"
        f"- Bonus objective: {target['bonus']}\n\n"
        f"You know the map and the guarding faction, but not the route the target will take."
    )
    chart_md = (
        f"## Ambush Chart Pack\n"
        f"### Trap Setup\nTrap maximum: {strength['trap_limit']}.\n\n"
        f"### Trap Menu\n"
        + "\n".join(f"| {t['name']} | {t['effect']} |" for t in TRAP_MENU)
        + "\n\n### Heat States\n"
        + "\n".join(f"| {h['state']} | {h['effect']} |" for h in HEAT_STATES)
        + f"\n\n### Map Plan\n- {map_plan.get('name', '')}: {map_plan.get('prompt', '')}"
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, roles["hiring"], dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, roles["hiring"], players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, roles["hiring"], chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief", "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",     "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Heat & Traps",  "type": "custom",      "content": chart_md},
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
        logger.warning(f"[AMBUSH] index.html failed: {e}")
        index_path = out_dir / "module.html"

    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as e:
        logger.warning(f"[AMBUSH] Could not write module_slug: {e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[AMBUSH] Complete: {title!r} -> {out_dir.name}")
    return index_path
