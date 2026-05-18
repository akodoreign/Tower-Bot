"""
infestation_pipeline.py — Full pipeline for Infestation mission modules.

Replaces the generic dungeon/scene pipeline for missions of type
'infestation', 'dungeon', or 'extermination'.

Flow:
  1. Choose subtype  (sewer / basement / lair / dungeon)
  2. Generate ASCII layout  (pure Python — no LLM)
  3. Generate monster roster  (Ollama — 2-3 monster types + boss)
  4. Generate room content    (Ollama — one call per room batch)
  5. Generate A1111 maps      (one map per room, ASCII passed as layout ref)
  6. Render module HTML        (room-by-room, not scene-by-scene)
  7. Write session.html, maps.html, index.html

Exported:
    build_infestation_module(mission: dict, out_dir: Path) -> Path
    is_infestation_mission(mission_type: str) -> bool
"""

from __future__ import annotations

import os
import re
import json
import base64
import random
import asyncio
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple

import httpx

from src.log import logger
from src.mission_builder.infestation_layout import (
    InfestationLayout,
    InfestationRoom,
    generate_layout,
    layout_summary,
    render_ascii,
    ROOM_COUNTS,
)
from src.mission_builder.html_renderer import _faction_color, _CSS, _page
from src.mission_builder.cr_scaling import mission_cr, party_strength as _party_strength

OUTPUT_BASE     = Path(__file__).resolve().parent.parent.parent / "generated_modules"
ROOM_MAP_CACHE  = OUTPUT_BASE / "_room_map_cache"
OLLAMA_URL      = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
A1111_URL       = os.getenv("A1111_URL", "http://127.0.0.1:7860")

# ---------------------------------------------------------------------------
# Mission type detection
# ---------------------------------------------------------------------------

_INFESTATION_KEYWORDS = {
    "infestation", "dungeon", "delve", "extermination", "pest",
    "sewer run", "basement clear", "nest", "lair",
}


def is_infestation_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _INFESTATION_KEYWORDS)


# ---------------------------------------------------------------------------
# Subtype selection
# ---------------------------------------------------------------------------

_SUBTYPE_KEYWORDS = {
    "sewer":    ["sewer", "drain", "pipes", "cistern", "waterway", "runoff"],
    "basement": ["basement", "cellar", "building", "foundation", "warehouse", "sub-level"],
    "lair":     ["lair", "nest", "cave", "burrow", "den", "warren", "cavern"],
    "dungeon":  ["dungeon", "vault", "prison", "ruin", "catacombs", "undercroft"],
}


def choose_subtype(mission: dict) -> str:
    text = " ".join([
        mission.get("title", ""),
        mission.get("description", ""),
        mission.get("body", ""),
        mission.get("primary_location", ""),
    ]).lower()
    for subtype, keywords in _SUBTYPE_KEYWORDS.items():
        if any(k in text for k in keywords):
            return subtype
    return random.choice(["sewer", "basement", "lair"])


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

async def _ask(prompt: str, system: str = "", timeout: int = 120, tokens: int = 1200) -> str:
    """Call Ollama via the shared queue with up to 10 retries and backoff."""
    from src.ollama_queue import call_ollama

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model":    OLLAMA_MODEL,
        "messages": messages,
        "stream":   False,
        "think":    False,
        "options":  {"num_predict": tokens, "temperature": 0.75},
    }

    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            data    = await call_ollama(payload, timeout=float(timeout), caller="infestation", force=True)
            content = (data.get("message") or {}).get("content", "").strip()
            if content:
                return content
            # Ollama returned 200 but empty body — treat as transient failure
            logger.warning(f"[INFEST] Empty response (attempt {attempt}/{max_attempts})")
        except Exception as e:
            logger.warning(f"[INFEST] Ollama error attempt {attempt}/{max_attempts}: {e}")

        if attempt < max_attempts:
            wait = min(30 * attempt, 120)   # 30s, 60s, 90s, 120s … capped at 2 min
            logger.info(f"[INFEST] Retrying in {wait}s…")
            await asyncio.sleep(wait)

    logger.error("[INFEST] All 10 attempts exhausted — returning empty string")
    return ""


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.replace("’", "'").replace("‘", "'")
    raw = raw.replace("“", '"').replace("”", '"')
    raw = raw.replace("—", "--").replace("–", "-")
    # Strip bare newlines inside strings
    cleaned, in_str, esc = [], False, False
    for ch in raw:
        if esc: cleaned.append(ch); esc = False; continue
        if ch == "\\" and in_str: cleaned.append(ch); esc = True; continue
        if ch == '"': in_str = not in_str; cleaned.append(ch); continue
        if in_str and ch in ("\n", "\r"): cleaned.append(" "); continue
        cleaned.append(ch)
    raw = "".join(cleaned).strip()
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try: return json.loads(m.group(0))
            except Exception: pass
    return {}


# ---------------------------------------------------------------------------
# Monster roster generation
# ---------------------------------------------------------------------------

_MONSTER_POOLS: Dict[str, List[str]] = {
    "sewer":    ["giant rats", "sewer oozes", "rot grubs", "giant centipedes",
                 "black puddings", "sewer crocodiles", "giant leeches"],
    "basement": ["giant rats", "rot grubs", "giant spiders", "cave centipedes",
                 "cockroach swarms", "mold colonies", "giant beetles"],
    "lair":     ["giant beetles", "carrion crawlers", "giant centipedes",
                 "otyughs", "cave fishers", "ropers", "giant toads"],
    "dungeon":  ["grey oozes", "gelatinous cubes", "piercers", "green slimes",
                 "lurkers above", "troglodytes", "violet fungi"],
}

_SYSTEM_MONSTERS = (
    "You are a D&D 5e monster designer. Be specific, concise, and table-ready. "
    "Output valid JSON only, no markdown fences, no commentary."
)

# Keyword → D&D creature type for DDB push
_CREATURE_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "ooze":        ["ooze", "pudding", "slime", "cube", "jelly", "blob"],
    "plant":       ["fungus", "fungi", "mold", "mould", "shrieker", "violet", "myconid", "plant"],
    "undead":      ["undead", "zombie", "skeleton", "ghost", "wraith", "specter", "ghoul", "wight", "revenant"],
    "construct":   ["construct", "golem", "automaton", "mechanical", "scrap", "clockwork",
                    "iron", "bronze", "steel", "machine", "robot", "drone", "gear"],
    "aberration":  ["aberration", "aberrant", "otyugh", "piercer", "lurker", "beholder", "mimic", "gibbering"],
    "monstrosity": ["monstrosity", "carrion", "roper", "cave fisher", "trapper", "displacer",
                    "manticore", "chimera", "basilisk", "cockatrice"],
    "humanoid":    ["troglodyte", "goblin", "kobold", "cultist", "bandit", "thug", "guard",
                    "gnoll", "hobgoblin", "orc", "bugbear"],
    "fiend":       ["demon", "devil", "fiend", "imp", "quasit", "dretch", "lemure"],
    "elemental":   ["elemental", "mephit", "salamander", "magmin", "gargoyle"],
}


def _infer_creature_type(name: str, primary_type: str = "") -> str:
    """Infer D&D creature type from monster name/concept for DDB stat block."""
    text = (name + " " + primary_type).lower()
    for ctype, keywords in _CREATURE_TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return ctype
    # Most dungeon vermin (rats, spiders, beetles, centipedes, toads) are beasts
    return "beast"


async def generate_monster_roster(subtype: str, cr: int, faction: str) -> dict:
    pool = _MONSTER_POOLS.get(subtype, _MONSTER_POOLS["lair"])
    chosen = random.sample(pool, min(2, len(pool)))
    main_type = chosen[0]

    prompt = f"""Design a monster roster for a D&D 5e infestation mission in a {subtype}.
Setting: Dark fantasy / cyberpunk city. Faction context: {faction}.
Primary monster concept: {main_type}.
Challenge Rating range: CR {max(1, cr-2)} to CR {cr+2}.

Output exactly this JSON:
{{
  "primary_type": "{main_type}",
  "secondary_type": "{chosen[1] if len(chosen) > 1 else chosen[0]}",
  "variants": [
    {{
      "name": "specific creature name",
      "cr": "1/4 or number",
      "hp": 7,
      "ac": 11,
      "speed": "30 ft.",
      "attacks": ["Attack name. Melee/Ranged Weapon Attack: +X to hit, reach Yft., one target. Hit: Z type damage."],
      "special": "One short special trait or action (or null)",
      "density_note": "appears in: empty/light/normal/heavy rooms"
    }},
    ... exactly 3 variants from weakest to strongest
  ],
  "boss": {{
    "name": "Boss creature name — a named unique version of the primary type",
    "cr": "{cr+1}",
    "hp": {30 + cr * 15},
    "ac": {13 + cr // 3},
    "speed": "30 ft.",
    "attacks": [
      "Attack 1. Melee Weapon Attack: +{cr+2} to hit, reach 10ft., one target. Hit: {8+cr*2} damage.",
      "Attack 2 (recharge 5-6). Area or special attack."
    ],
    "legendary_actions": null,
    "lair_action": "One lair action the boss can use at initiative count 20.",
    "tactics": "How the boss fights: when it retreats, who it targets, what makes it dangerous."
  }},
  "infestation_note": "One sentence: why this type of creature has infested this location and what they want."
}}"""

    raw = await _ask(prompt, system=_SYSTEM_MONSTERS, timeout=90, tokens=900)
    data = _parse_json(raw)
    if not data:
        # Fallback minimal roster
        data = {
            "primary_type": main_type,
            "secondary_type": chosen[-1],
            "variants": [
                {"name": f"Young {main_type.rstrip('s')}", "cr": "1/4", "hp": 7, "ac": 11,
                 "speed": "30 ft.", "attacks": [f"Bite. +3 to hit, 1d4 piercing."],
                 "special": None, "density_note": "light/normal rooms"},
                {"name": f"{main_type.rstrip('s').title()}", "cr": "1", "hp": 18, "ac": 12,
                 "speed": "30 ft.", "attacks": [f"Bite. +4 to hit, 1d6+2 piercing."],
                 "special": "Pack Tactics", "density_note": "normal/heavy rooms"},
                {"name": f"Giant {main_type.rstrip('s').title()}", "cr": "2", "hp": 32, "ac": 13,
                 "speed": "40 ft.", "attacks": [f"Bite. +5 to hit, 2d6+3 piercing."],
                 "special": "Frightening Screech (recharge 5-6)", "density_note": "heavy rooms"},
            ],
            "boss": {
                "name": f"The Patriarch", "cr": str(cr + 1), "hp": cr * 20 + 30,
                "ac": 14, "speed": "40 ft.",
                "attacks": [f"Bite +{cr+3} to hit, 3d6+{cr} piercing.",
                            f"Frenzy (recharge 5-6): all creatures in 10ft make DC {10+cr} DEX save."],
                "legendary_actions": None,
                "lair_action": "The nest shifts — difficult terrain expands to fill a 10-ft radius.",
                "tactics": "Targets the smallest target first. Retreats at 25% HP to trigger lair action.",
            },
            "infestation_note": f"The {main_type} have claimed this {subtype} as their breeding ground.",
        }
    return data


# ---------------------------------------------------------------------------
# Room content generation
# ---------------------------------------------------------------------------

_SYSTEM_ROOMS = (
    "You are a D&D 5e dungeon designer writing terse, table-ready room content. "
    "Be specific. Avoid vague descriptions. Each room should feel distinct. "
    "Output valid JSON only, no markdown, no commentary."
)


async def generate_room_batch(
    rooms: List[InfestationRoom],
    layout: InfestationLayout,
    monsters: dict,
    mission: dict,
) -> Dict[int, dict]:
    """Generate content for up to 5 rooms in one Ollama call."""
    room_list = []
    for r in rooms:
        conns = [f"R{c[0]:02d} via {c[1]}" for c in r.connections]
        room_list.append({
            "id": r.room_id,
            "type": r.room_type,
            "density": r.monster_density,
            "is_entry": r.is_entry,
            "is_boss": r.is_boss,
            "connects_to": conns,
        })

    primary   = monsters.get("primary_type", "creatures")
    secondary = monsters.get("secondary_type", primary)
    boss_name = monsters.get("boss", {}).get("name", "the boss")
    note      = monsters.get("infestation_note", "")

    prompt = f"""Infestation mission: "{mission.get('title','Unknown')}"
Location type: {layout.subtype} — {len(layout.rooms)} rooms total.
Faction: {mission.get('faction','Independent')}
Primary infestation: {primary} and {secondary}. {note}
Boss creature: {boss_name} (in the boss room only).

Generate content for these {len(room_list)} rooms. Output exactly this JSON:
{{
  "rooms": [
    {{
      "id": <room id number>,
      "name": "short evocative room name",
      "read_aloud": "2-3 sentences read aloud to players. Specific sensory details. No monster spoilers unless visible.",
      "dm_notes": "What the DM knows: hidden features, monster positions, traps, secrets.",
      "monsters": "Which monsters are here and how many. Use density: empty=none, light=1-2 weak, normal=2-4 standard, heavy=4-6 mixed, boss=boss creature + 2-3 minions.",
      "features": ["feature 1", "feature 2", "feature 3"],
      "exits": "Describe how exits look — a corroded hatch, a collapsed archway, etc.",
      "treasure": "Loot or nothing — be specific (e.g. '12 EC in a rusted tin', 'a faction signet ring').",
      "hazard": "Environmental hazard or trap (or null)."
    }}
  ]
}}

Rooms to generate:
{json.dumps(room_list, indent=2)}"""

    raw  = await _ask(prompt, system=_SYSTEM_ROOMS, timeout=120, tokens=1600)
    data = _parse_json(raw)
    result = {}
    for rd in (data.get("rooms") or []):
        rid = rd.get("id")
        if rid:
            result[int(rid)] = rd
    return result


_STUB_MARKER = "is quiet. Something has been here recently."


def _is_stub_room_content(rc: dict | None) -> bool:
    if not rc:
        return True
    read_aloud = str(rc.get("read_aloud") or rc.get("description") or "").strip()
    features = rc.get("features")
    if _STUB_MARKER in read_aloud:
        return True
    if len(read_aloud) < 40:
        return True
    if isinstance(features, list) and not features:
        return True
    return False


def _fallback_room_content(room: InfestationRoom, layout: InfestationLayout, monsters: dict, mission: dict) -> dict:
    primary = monsters.get("primary_type", "infesting creatures") if isinstance(monsters, dict) else "infesting creatures"
    secondary = monsters.get("secondary_type", primary) if isinstance(monsters, dict) else primary
    boss = monsters.get("boss", {}) if isinstance(monsters, dict) else {}
    boss_name = boss.get("name", "the alpha creature")
    faction = mission.get("faction", "the hiring faction")
    connector_text = ", ".join(f"R{rid:02d} via {kind}" for rid, kind in room.connections) or "one narrow onward passage"

    subtype_features = {
        "sewer": ["slick maintenance ledge", "black water channel", "rusted grate cover"],
        "basement": ["cracked support column", "collapsed shelving", "exposed pipe run"],
        "lair": ["packed nesting debris", "gnawed bone scatter", "slick territorial markings"],
        "dungeon": ["scored flagstones", "iron doorframe", "broken torch sconce"],
    }
    room_features = {
        "egg": ["clustered eggs", "protective slime", "warm organic residue"],
        "nest": ["woven nesting mass", "half-buried remains", "defensive choke point"],
        "pump": ["manual valve wheel", "pressure gauge bank", "shuddering pipe joint"],
        "boiler": ["split boiler casing", "hot steam vent", "coal-dust drift"],
        "vault": ["warped lockbox", "scratched floor safe", "fallen ledger shelf"],
        "shrine": ["defaced idol niche", "ritual ash line", "cracked offering bowl"],
        "boss": ["wide killing floor", "dominant lair marker", "elevated retreat point"],
    }
    feature_key = "boss" if room.is_boss else next((k for k in room_features if k in room.room_type.lower()), "")
    features = list(subtype_features.get(layout.subtype, subtype_features["dungeon"]))
    if feature_key:
        features = room_features[feature_key][:2] + features[:1]

    density_monsters = {
        "empty": "No creatures are present, but tracks show recent movement through the room.",
        "light": f"1-2 {primary} linger near cover and retreat if badly hurt.",
        "normal": f"2-4 {primary} hold the room, using the terrain to split intruders.",
        "heavy": f"4-6 mixed {primary} and {secondary} crowd the best cover and try to surround the party.",
        "boss": f"{boss_name} lairs here with 2-3 {primary} minions guarding the exits.",
    }
    hazard_by_density = {
        "empty": None,
        "light": "Loose debris makes one 10-foot patch difficult terrain.",
        "normal": "A fouled floor patch forces a DC 12 Dexterity save or the creature falls prone.",
        "heavy": "Disturbing the nest releases choking spores; DC 13 Constitution save or poisoned until end of next turn.",
        "boss": "The lair reacts on initiative 20: slime, steam, or rubble turns one exit into difficult terrain for a round.",
    }
    treasure_by_density = {
        "empty": "A salvageable tool pouch worth 8 EC is wedged behind debris.",
        "light": "A cracked guild token and 10 EC are caught in the room's refuse.",
        "normal": "A rusted tin holds 18 EC and a minor potion vial with its label half-eaten.",
        "heavy": "A dead courier's satchel contains 30 EC, a faction seal, and one usable clue.",
        "boss": f"The boss hoard contains 60 EC, a marked signet tied to {faction}, and one mission-relevant trophy.",
    }

    visible = "no creatures are immediately visible" if room.monster_density == "empty" else "movement stirs behind cover"
    read_aloud = (
        f"The {room.room_type} opens into a foul {layout.subtype} chamber where {features[0]} dominates the floor. "
        f"{features[1].capitalize()} and {features[2]} show where the infestation has changed the room's original purpose. "
        f"{visible.capitalize()}, and the air carries the sharp, wet smell of a site that is still active."
    )
    return {
        "id": room.room_id,
        "name": room.room_type.title(),
        "read_aloud": read_aloud,
        "dm_notes": (
            f"Deterministic fallback content: density={room.monster_density}; connectors={connector_text}. "
            "Use the room features as cover and telegraph the hazard before it triggers."
        ),
        "monsters": density_monsters.get(room.monster_density, density_monsters["normal"]),
        "features": features,
        "exits": f"Visible exits connect to {connector_text}. Each connector is partially marked by scratches, residue, or drag trails.",
        "treasure": treasure_by_density.get(room.monster_density, treasure_by_density["normal"]),
        "hazard": hazard_by_density.get(room.monster_density, hazard_by_density["normal"]),
    }


async def generate_all_rooms(
    layout: InfestationLayout,
    monsters: dict,
    mission: dict,
) -> Dict[int, dict]:
    """Generate all rooms in batches of 4, with a retry pass for any stubs."""
    by_id = {r.room_id: r for r in layout.rooms}
    room_sequence = [by_id[rid] for rid in layout.room_sequence if rid in by_id]
    all_content: Dict[int, dict] = {}
    batch_size = 4

    for i in range(0, len(room_sequence), batch_size):
        batch = room_sequence[i:i + batch_size]
        logger.info(f"[INFEST] Generating rooms {[r.room_id for r in batch]}")
        content = await generate_room_batch(batch, layout, monsters, mission)
        all_content.update(content)
        await asyncio.sleep(3)

    # Fill rooms the LLM missed entirely with placeholder stubs
    for room in layout.rooms:
        if room.room_id not in all_content:
            all_content[room.room_id] = {
                "id":        room.room_id,
                "name":      room.room_type.title(),
                "read_aloud": f"The {room.room_type} {_STUB_MARKER}",
                "dm_notes":  f"Density: {room.monster_density}. Type: {room.room_type}.",
                "monsters":  "None visible." if room.monster_density == "empty" else f"{monsters.get('primary_type','creatures')} present.",
                "features":  [],
                "exits":     "Passages lead onward.",
                "treasure":  "Nothing of value.",
                "hazard":    None,
            }

    # End-of-pipeline retry pass — re-attempt any rooms that are still stubs.
    # _ask already retried 10 times internally; this catches cases where the whole
    # batch came back empty (parse failure, not a per-call timeout).
    stub_rooms = [by_id[rid] for rid, rc in all_content.items() if _is_stub_room_content(rc) and rid in by_id]
    if stub_rooms:
        logger.info(f"[INFEST] Retry pass: {len(stub_rooms)} stub room(s) — {[r.room_id for r in stub_rooms]}")
        await asyncio.sleep(15)
        for i in range(0, len(stub_rooms), batch_size):
            batch = stub_rooms[i:i + batch_size]
            logger.info(f"[INFEST] Retry batch {[r.room_id for r in batch]}")
            retry_content = await generate_room_batch(batch, layout, monsters, mission)
            # Only overwrite if we actually got real content back
            for rid, rc in retry_content.items():
                if not _is_stub_room_content(rc):
                    all_content[rid] = rc
                    logger.info(f"[INFEST] Retry succeeded for room {rid}")
            failed = [r.room_id for r in batch if _is_stub_room_content(all_content.get(r.room_id))]
            if failed:
                logger.warning(f"[INFEST] Retry still stubbed room(s): {failed}")
            if i + batch_size < len(stub_rooms):
                await asyncio.sleep(10)

    final_stubs = [by_id[rid] for rid, rc in all_content.items() if _is_stub_room_content(rc) and rid in by_id]
    if final_stubs:
        ids = [r.room_id for r in final_stubs]
        logger.error(f"[INFEST] Final room audit found stub room(s) {ids}; applying deterministic fallback content")
        for room in final_stubs:
            all_content[room.room_id] = _fallback_room_content(room, layout, monsters, mission)

    return all_content


# ---------------------------------------------------------------------------
# A1111 map generation per room
# ---------------------------------------------------------------------------

_SUBTYPE_BASE_PROMPTS: Dict[str, str] = {
    "sewer": (
        "top-down battle map, sewer tunnel interior, brick arched walls, "
        "central water channel with scum surface, iron grate covers on floor, "
        "maintenance walkway along edges, pipe bundles on walls, "
        "slick wet stone, dim emergency lighting strips, "
        "dark fantasy cyberpunk fusion city infrastructure"
    ),
    "basement": (
        "top-down battle map, building sub-basement interior, "
        "exposed concrete and stone foundation walls, overhead pipe runs, "
        "rusted shelving units, support column grid, "
        "bare bulb lighting (some smashed), drainage floor grating, "
        "debris and old crates, gritty urban infrastructure"
    ),
    "lair": (
        "top-down battle map, creature lair interior, organic cave walls, "
        "uneven stone floor with debris and bone scatter, "
        "webbing or slime trails on walls, fungal growths in corners, "
        "rough natural rock ceiling implied, bioluminescent patches, "
        "dark and claustrophobic atmosphere"
    ),
    "dungeon": (
        "top-down battle map, stone dungeon chamber, "
        "carved stone walls with torch sconce positions, "
        "heavy iron door frames, flagstone floor with grime in joints, "
        "old ruin aesthetic, scattered broken furniture or equipment, "
        "dim torch lighting with deep shadows"
    ),
}

_ROOM_TYPE_OVERLAYS: Dict[str, str] = {
    "entry shaft":           "entrance shaft, ladder rungs on wall, open access hatch in floor",
    "entry":                 "entrance room, access hatch visible, first encounter staging",
    "boss":                  "large open area, dramatic centrepiece, lair features, environmental hazard positions",
    "pump room":             "large pump machinery, valve controls, pipe cluster centre-piece",
    "boiler room":           "industrial boiler, steam pipes, pressure gauges, heat vents",
    "cistern":               "large water storage pit, walkway around edge, depth unknown below",
    "egg chamber":           "nest material packed in corners, organic egg masses, protective debris ring",
    "breeding chamber":      "mass of organic matter, eggs and young, defended nest core",
    "flooding":              "floor covered in shallow black water, debris floating",
    "altar":                 "ritual raised platform, symbolic markings, damaged religious iconography",
    "prison":                "cell doors along walls, rusted bars, restraint fixtures",
    "torture chamber":       "devices of restraint, drain in floor, hooks on ceiling",
    "vault":                 "heavy reinforced door at back, empty shelf niches, evidence of looting",
}


async def _check_a1111() -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{A1111_URL}/sdapi/v1/sd-models")
            return r.status_code == 200
    except Exception:
        return False


_loras_refreshed = False


async def _ensure_loras_refreshed() -> None:
    global _loras_refreshed
    if _loras_refreshed:
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{A1111_URL}/sdapi/v1/refresh-loras")
            logger.info(f"[INFEST] A1111 LoRA list refreshed ({r.status_code})")
    except Exception as e:
        logger.warning(f"[INFEST] LoRA refresh failed (non-fatal): {e}")
    _loras_refreshed = True


def _room_map_cache_path(subtype: str, room_type: str, density: str) -> Path:
    """Stable cache path keyed on subtype + room_type + density."""
    slug = re.sub(r"[^\w]", "_", room_type.lower().strip())[:40]
    return ROOM_MAP_CACHE / subtype / f"{slug}__{density}.png"


async def generate_room_map(
    room: InfestationRoom,
    room_content: dict,
    layout: InfestationLayout,
    out_dir: Path,
    lora_name: str = "",
    lora_weight: float = 0.0,
) -> Optional[Path]:
    """Generate a single A1111 map for one room. Returns Path or None.

    Checks ROOM_MAP_CACHE first — identical subtype+room_type+density reuse the
    existing PNG so A1111 is skipped for rooms we've seen before.
    """
    import shutil

    maps_dir = out_dir / "maps"
    maps_dir.mkdir(exist_ok=True)

    # Name by grid coordinate (A1, B2, …) so filenames never collide with real area names.
    _col = (room.room_id - 1) % layout.grid_w
    _row = (room.room_id - 1) // layout.grid_w + 1
    _grid_coord = f"{chr(65 + _col)}{_row}"
    ts = datetime.now().strftime("%H%M%S")
    out_path = maps_dir / f"R{room.room_id:02d}_{_grid_coord}_{ts}.png"

    # --- Cache lookup ---
    room_title = (
        room_content.get("name")
        or room_content.get("title")
        or room.room_type.title()
    )
    cache_path = _room_map_cache_path(layout.subtype, room.room_type, room.monster_density)
    map_context = {
        "title": room_title,
        "location": room_title,
        "description": room_content.get("read_aloud", ""),
        "kind": "infestation cave nest dungeon",
    }
    if cache_path.exists():
        shutil.copy2(cache_path, out_path)
        try:
            from src.mission_builder.vtt_renderer import stylize_pretty_battlemap, write_grid_sidecar
            write_grid_sidecar(out_path, map_context)
            stylize_pretty_battlemap(out_path, map_context)
        except Exception as _pe:
            logger.warning(f"[INFEST] Cached map pretty pass failed: {_pe}")
        logger.info(f"[INFEST] Room map cache hit: {cache_path.name} → {out_path.name}")
        return out_path

    base = _SUBTYPE_BASE_PROMPTS.get(layout.subtype, _SUBTYPE_BASE_PROMPTS["dungeon"])

    # Room-type specific overlay
    rtype_key = room.room_type.lower()
    overlay = next(
        (v for k, v in _ROOM_TYPE_OVERLAYS.items() if k in rtype_key),
        ""
    )
    if room.is_boss:
        overlay = _ROOM_TYPE_OVERLAYS["boss"]

    # Pull features from room content
    features = room_content.get("features", [])
    feature_str = ", ".join(features[:3]) if features else ""

    # Monster flavour
    density_str = {
        "empty":  "empty, no creatures",
        "light":  "signs of creature activity",
        "normal": "creature tracks and spoor",
        "heavy":  "nest material, creature presence",
        "boss":   "large nest, alpha territory markings, bone scatter",
    }.get(room.monster_density, "")

    # Infestation is always dungeon — override any caller-supplied defaults
    _lora = lora_name or os.getenv("A1111_MAP_LORA_DUNGEON", "EnvyFluxDungeonMap01")
    _weight = lora_weight if lora_weight > 0 else float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    _triggers = os.getenv("A1111_MAP_DUNGEON_TRIGGERS", "detailed, map, dungeon")
    prompt_parts = [
        f"<lora:{_lora}:{_weight}>",
        _triggers,
        base,
        overlay,
        feature_str,
        density_str,
        "high contrast, clear room boundaries, grid-ready, flat top-down orthographic view",
    ]
    positive = ", ".join(p for p in prompt_parts if p)
    negative = (
        "isometric, perspective, 3D, characters, people, text, watermark, "
        "blurry, low quality, side view, sky, outdoor, above ground"
    )

    payload = {
        "prompt":          positive,
        "negative_prompt": negative,
        "width":           1024,
        "height":          1024,
        "steps":           20,
        "cfg_scale":       1.0,
        "sampler_name":    "Euler",
        "seed":            -1,
    }

    _map_ckpt = os.getenv("A1111_MAP_CHECKPOINT", "")
    if _map_ckpt:
        override: dict = {"sd_model_checkpoint": _map_ckpt}
        payload["override_settings"] = override
        payload["override_settings_restore_afterwards"] = True

    await _ensure_loras_refreshed()
    try:
        from src.news_feed import a1111_lock
        from src.resource_cop import wait_for_a1111_turn
        wait_seconds = int(os.getenv("INFESTATION_ROOM_MAP_WAIT_SECONDS", "1200"))
        decision = await wait_for_a1111_turn("infestation_room_map", max_wait_seconds=wait_seconds)
        if not decision.run_now:
            logger.info(f"[INFEST] A1111 deferred by resource cop for R{room.room_id}: {decision.reason}")
            return None
        async with a1111_lock:
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                resp.raise_for_status()
                data = resp.json()
    except Exception as e:
        logger.error(f"[INFEST] A1111 failed for R{room.room_id}: {e}")
        return None

    images = data.get("images", [])
    if not images:
        return None

    try:
        from src.mission_builder.vtt_renderer import save_vtt_battlemap_bytes
        map_context["prompt"] = positive
        ai_bytes = base64.b64decode(images[0])
        await asyncio.to_thread(save_vtt_battlemap_bytes, out_path, ai_bytes, map_context)
        png_bytes = out_path.read_bytes()
        logger.info(f"[INFEST] Map saved: {out_path.name}")
        # Write to persistent cache so future missions skip A1111 for this room type
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(png_bytes)
            logger.info(f"[INFEST] Room map cached: {cache_path.relative_to(OUTPUT_BASE)}")
        except Exception as _ce:
            logger.warning(f"[INFEST] Could not cache map: {_ce}")
        return out_path
    except Exception as e:
        logger.error(f"[INFEST] Map save failed for R{room.room_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

def _esc(t: str) -> str:
    import html
    return html.escape(str(t or ""))


def render_infestation_module(
    layout: InfestationLayout,
    monsters: dict,
    room_contents: Dict[int, dict],
    room_maps: Dict[int, Path],      # room_id → PNG path relative to out_dir
    mission: dict,
    strength: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the full module HTML for an infestation mission."""
    title   = mission.get("title", "Unknown Infestation")
    faction = mission.get("faction", "Independent")

    fc  = _faction_color(faction)
    css = _CSS.replace("--faction:   #4682b4;", f"--faction:   {fc};")

    # ── Infestation-specific CSS additions ──
    extra_css = """
.inf-ascii {
  font-family: 'Courier New', Courier, monospace;
  font-size: 11px;
  line-height: 1.3;
  background: #111;
  color: #9fa;
  padding: 14px 16px;
  border-radius: 6px;
  border: 1px solid #2a4a2a;
  overflow-x: auto;
  white-space: pre;
  margin: 20px 0;
}
.inf-room {
  border: 1px solid var(--rule-light);
  border-left: 5px solid var(--faction);
  border-radius: 6px;
  padding: 18px 22px;
  margin: 28px 0;
  background: var(--parchment);
  page-break-inside: avoid;
}
.inf-room-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--rule-light);
  padding-bottom: 8px;
}
.inf-room-num {
  font-family: Arial, sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--faction);
  flex-shrink: 0;
}
.inf-room-name {
  font-size: 17px;
  font-weight: 700;
  font-family: Georgia, serif;
}
.inf-room-badges {
  margin-left: auto;
  display: flex;
  gap: 6px;
}
.inf-badge {
  font-family: Arial, sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .1em;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 3px;
}
.inf-badge-entry  { background: #2a6a2a; color: #fff; }
.inf-badge-boss   { background: #8a1a1a; color: #fff; }
.inf-badge-empty  { background: #555; color: #ccc; }
.inf-badge-heavy  { background: #6a1a1a; color: #fcc; }
.inf-density-bar  { height: 4px; border-radius: 2px; margin-bottom: 10px; }
.inf-den-empty    { background: #555; width: 10%; }
.inf-den-light    { background: #5a9; width: 30%; }
.inf-den-normal   { background: #ca5; width: 60%; }
.inf-den-heavy    { background: #c55; width: 85%; }
.inf-den-boss     { background: #811; width: 100%; }
.inf-room-map     { width: 100%; max-height: 380px; object-fit: cover; border-radius: 6px;
                    border: 1px solid var(--rule-light); margin-bottom: 12px; display: block; }
.inf-section      { margin-top: 10px; }
.inf-section-label {
  font-family: Arial, sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: rgba(26,22,18,.45);
  margin-bottom: 3px;
}
.inf-section-body { font-size: 14px; line-height: 1.6; color: var(--ink); }
.inf-feature-list { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.5; }
.inf-monster-block {
  background: #1a1208;
  color: #e8d9b4;
  border-radius: 6px;
  padding: 10px 14px;
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
  line-height: 1.5;
  margin-top: 8px;
}
.inf-stat-block {
  background: var(--stat-bg);
  border: 2px solid var(--stat-br);
  border-radius: 6px;
  padding: 14px 18px;
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
  line-height: 1.6;
  margin: 14px 0;
}
.inf-hazard {
  background: #3a1a0a;
  color: #fcc;
  border-left: 4px solid #c55;
  border-radius: 0 5px 5px 0;
  padding: 8px 12px;
  font-size: 13px;
  margin-top: 8px;
}
"""
    full_css = css + extra_css

    nav = (
        '<nav class="nav-bar">'
        '<a href="/" style="margin-right:24px;opacity:.7;">⬅ Dashboard</a>'
        '<a href="index.html">◀ Index</a>'
        '<span style="color:#6a5030;font-family:Arial,sans-serif;font-size:13px;margin-left:auto;">'
        'Tower of Last Chance — D&amp;D 5e 2024'
        '</span>'
        '</nav>'
    )

    by_id     = {r.room_id: r for r in layout.rooms}
    rooms_seq = [by_id[rid] for rid in layout.room_sequence if rid in by_id]

    # ── Monster stat card (reusable) ──
    def _stat_card(m: dict) -> str:
        attacks = "".join(f"<div>⚔ {_esc(a)}</div>" for a in (m.get("attacks") or []))
        special = f'<div>★ {_esc(m.get("special",""))}</div>' if m.get("special") else ""
        return (
            f'<div class="inf-stat-block">'
            f'<b>{_esc(m.get("name","?"))}</b> — CR {_esc(str(m.get("cr","?")))} | '
            f'HP {_esc(str(m.get("hp","?")))} | AC {_esc(str(m.get("ac","?")))} | '
            f'{_esc(m.get("speed","30 ft."))}'
            f'{attacks}{special}'
            f'</div>'
        )

    # ── Infestation overview ──
    variants_html = "".join(_stat_card(v) for v in (monsters.get("variants") or []))
    boss = monsters.get("boss") or {}
    boss_attacks = "".join(f"<div>⚔ {_esc(a)}</div>" for a in (boss.get("attacks") or []))
    boss_card = (
        f'<div class="inf-stat-block" style="border-color:#8a1a1a;">'
        f'<b>👑 {_esc(boss.get("name","?"))}</b> — CR {_esc(str(boss.get("cr","?")))} | '
        f'HP {_esc(str(boss.get("hp","?")))} | AC {_esc(str(boss.get("ac","?")))} | '
        f'{_esc(boss.get("speed","30 ft."))}'
        f'{boss_attacks}'
        + (f'<div>🗺️ Lair action: {_esc(boss.get("lair_action",""))}</div>' if boss.get("lair_action") else "")
        + (f'<div>🎯 Tactics: {_esc(boss.get("tactics",""))}</div>' if boss.get("tactics") else "")
        + f'</div>'
    )

    scaling_html = ""
    if strength:
        scaling_html = (
            f'<div style="background:#eef6ff;border:1px solid #3a6898;border-radius:6px;'
            f'padding:10px 14px;margin:14px 0;font-size:13px;">'
            f'<strong>Live Party Scaling:</strong> {_esc(_party_scaling_note(strength))} '
            f'CR and infestation pressure are tuned from this read.</div>'
        )

    overview_html = f"""
<div class="chapter-header">
  <div class="ch-label">{_esc(title)}</div>
  <h2>Infestation — {layout.subtype.title()}</h2>
</div>
<h1>{_esc(title)}</h1>
<p><strong>Type:</strong> {layout.subtype.title()} infestation &nbsp;|&nbsp;
<strong>Rooms:</strong> {len(layout.rooms)} &nbsp;|&nbsp;
<strong>Faction:</strong> {_esc(faction)}</p>

{scaling_html}

<h2>Infestation Overview</h2>
<p>{_esc(monsters.get('infestation_note',''))}</p>

<h2>ASCII Layout Map</h2>
<div class="inf-ascii">{_esc(layout.ascii_map)}</div>

<h2>Monster Roster</h2>
<h3>Variants (weakest → strongest)</h3>
{variants_html}
<h3>Boss: {_esc(boss.get('name','?'))}</h3>
{boss_card}
<hr>
<h2>Room Descriptions</h2>
"""

    # ── Room cards ──
    room_cards = []
    for room in rooms_seq:
        rc = room_contents.get(room.room_id, {})
        badges = ""
        if room.is_entry: badges += '<span class="inf-badge inf-badge-entry">Entry</span>'
        if room.is_boss:  badges += '<span class="inf-badge inf-badge-boss">Boss</span>'
        if room.monster_density == "empty": badges += '<span class="inf-badge inf-badge-empty">Clear</span>'
        if room.monster_density == "heavy": badges += '<span class="inf-badge inf-badge-heavy">Heavy</span>'

        den_css = f'inf-den-{room.monster_density}'

        # Map image
        map_path = room_maps.get(room.room_id)
        map_html = ""
        if map_path:
            preview = map_path.with_name(f"{map_path.stem}_pretty{map_path.suffix}")
            if not preview.exists():
                preview = map_path.with_name(f"{map_path.stem}_nice{map_path.suffix}")
            shown = preview if preview.exists() else map_path
            map_html = f'<img class="inf-room-map" src="maps/{_esc(shown.name)}" alt="Room map R{room.room_id:02d}" loading="lazy">'

        # Connections
        conns = ", ".join(
            f'R{c[0]:02d} ({c[1]})' for c in room.connections
        )

        # Features
        features = rc.get("features") or []
        feat_html = ""
        if features:
            feat_html = "<ul class='inf-feature-list'>" + "".join(f"<li>{_esc(f)}</li>" for f in features) + "</ul>"

        # Hazard
        hazard_html = ""
        if rc.get("hazard"):
            hazard_html = f'<div class="inf-hazard">⚠️ Hazard: {_esc(rc["hazard"])}</div>'

        room_cards.append(f"""
<div class="inf-room" id="room-{room.room_id}">
  <div class="inf-room-header">
    <span class="inf-room-num">R{room.room_id:02d}</span>
    <span class="inf-room-name">{_esc(rc.get('name', room.room_type.title()))}</span>
    <span class="inf-room-badges">{badges}</span>
  </div>
  <div class="inf-density-bar {den_css}"></div>
  {map_html}
  <div class="inf-section">
    <div class="inf-section-label">Read Aloud</div>
    <div class="inf-section-body read-aloud" style="background:#f0f4f8;border-left:5px solid var(--faction);padding:10px 14px;border-radius:0 5px 5px 0;">
      {_esc(rc.get('read_aloud',''))}
    </div>
  </div>
  <div class="inf-section">
    <div class="inf-section-label">DM Notes</div>
    <div class="inf-section-body">{_esc(rc.get('dm_notes',''))}</div>
  </div>
  <div class="inf-section">
    <div class="inf-section-label">Monsters</div>
    <div class="inf-monster-block">{_esc(rc.get('monsters','None.'))}</div>
  </div>
  {(f'<div class="inf-section"><div class="inf-section-label">Room Features</div>{feat_html}</div>') if feat_html else ''}
  <div class="inf-section">
    <div class="inf-section-label">Exits</div>
    <div class="inf-section-body">{_esc(rc.get('exits',''))}</div>
  </div>
  <div class="inf-section">
    <div class="inf-section-label">Connections</div>
    <div class="inf-section-body" style="font-family:monospace;font-size:12px;">{_esc(conns)}</div>
  </div>
  {(f'<div class="inf-section"><div class="inf-section-label">Treasure</div><div class="inf-section-body">{_esc(rc.get("treasure","Nothing of value."))}</div></div>') if rc.get('treasure') else ''}
  {hazard_html}
</div>""")

    content = overview_html + "\n".join(room_cards)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Infestation — {_esc(title)}</title>
<style>{full_css}</style>
</head>
<body>
<div class="page clearfix">
{nav}
{content}
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen]


def _party_strength() -> Dict[str, Any]:
    """Read live PC snapshots; copied here so infestation stays standalone."""
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
            pcs.append({"name": snap.get("name") or row.get("char_name"), "level": level, "max_hp": int(snap.get("max_hp") or 0)})
    except Exception as e:
        logger.warning(f"[INFEST] Could not read live party snapshots: {e}")
    levels = [p["level"] for p in pcs] or [5]
    return {"party_size": len(pcs) or 4, "avg_level": round(sum(levels) / len(levels), 1), "max_level": max(levels), "pcs": pcs}


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    return f"Live party read: {strength['party_size']} PCs, average level {strength['avg_level']}, max level {strength['max_level']}."


async def build_infestation_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    """
    Full infestation pipeline. Returns the path to the written module HTML.
    """
    title   = mission.get("title", "Unknown Infestation")
    faction = mission.get("faction", "Independent")
    strength = _party_strength()
    cr = mission_cr(mission)

    if out_dir is None:
        safe = _safe_filename(title)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{safe}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    subtype = choose_subtype(mission)
    logger.info(f"[INFEST] Starting: {title!r} — subtype={subtype}")

    # Mimir: create campaign-side module (non-blocking, fails silently)
    from src.mission_builder.mimir_module import (
        create_module as mimir_create,
        enrich_monsters as mimir_monsters,
        push_documents as mimir_docs,
        upload_map as mimir_map,
        render_mimir_section,
    )
    mimir_module_id = await mimir_create(mission, mission_type="infestation")

    # 1. Layout
    layout = generate_layout(subtype)
    logger.info(f"[INFEST] Layout: {len(layout.rooms)} rooms, grid {layout.grid_w}×{layout.grid_h}")

    # Save ASCII map as standalone file
    (out_dir / "dungeon_map.txt").write_text(layout.ascii_map + "\n\n" + layout_summary(layout), encoding="utf-8")

    # 2. Monster roster
    logger.info("[INFEST] Generating monster roster...")
    monsters = await generate_monster_roster(subtype, cr, faction)

    # Mimir: enrich monsters with real catalog stat blocks
    # NOTE: roster uses "variants" key — was incorrectly "monsters" before
    _monster_list = monsters.get("variants", []) if isinstance(monsters, dict) else []
    _boss         = monsters.get("boss", {})     if isinstance(monsters, dict) else {}
    _primary_type = monsters.get("primary_type", "") if isinstance(monsters, dict) else ""

    _enemy_input = [
        {
            "name":          m.get("name", ""),
            "cr":            str(m.get("cr", "1")),
            "count":         1,
            "notes":         m.get("special") or m.get("density_note", ""),
            "creature_type": _infer_creature_type(m.get("name", ""), _primary_type),
            # Pass existing stat data so DDB push skips redundant LLM generation
            "hp":            m.get("hp"),
            "ac":            m.get("ac"),
            "speed":         m.get("speed", "30 ft."),
            "attacks":       m.get("attacks", []),
        }
        for m in _monster_list
    ]
    if _boss.get("name"):
        _enemy_input.append({
            "name":          _boss["name"],
            "cr":            str(_boss.get("cr", "3")),
            "count":         1,
            "notes":         _boss.get("tactics", "Boss"),
            "creature_type": _infer_creature_type(_boss["name"], _primary_type),
            "hp":            _boss.get("hp"),
            "ac":            _boss.get("ac"),
            "speed":         _boss.get("speed", "30 ft."),
            "attacks":       _boss.get("attacks", []),
        })
    enriched_enemies = await mimir_monsters(mimir_module_id or "", _enemy_input)

    # Direct DDB homebrew push — fires when Mimir is unavailable but DDB session is set.
    # enrich_monsters() exits early without pushing anything if Mimir is down, so we
    # push each enemy directly here as a fallback.
    if not mimir_module_id:
        try:
            from src.ddb_homebrew import push_mission_enemy as _ddb_push, ENABLED as _ddb_en
            if _ddb_en:
                async def _push_all_direct():
                    for _e in _enemy_input:
                        if not _e.get("name"):
                            continue
                        _cr = str(_e.get("cr", "1"))
                        try:
                            _cr_num = float(_cr.replace("1/8","0.125").replace("1/4","0.25").replace("1/2","0.5"))
                        except Exception:
                            _cr_num = 1.0
                        try:
                            from src.mission_builder.monster_stat_gen import build_statblock
                            _prebuilt = build_statblock(
                                name          = _e.get("name", ""),
                                cr            = _cr,
                                creature_type = _e.get("creature_type", "beast"),
                                size          = "M",
                                hp_override   = _e.get("hp"),
                                ac_override   = _e.get("ac"),
                                attacks       = _e.get("attacks") or [],
                                notes         = _e.get("notes", ""),
                            )
                        except Exception:
                            _prebuilt = {
                                "hp":            _e.get("hp") or max(1, int(_cr_num * 13 + 7)),
                                "ac":            _e.get("ac") or max(10, min(18, int(_cr_num + 12))),
                                "creature_type": _e.get("creature_type", "beast"),
                            }
                        try:
                            await _ddb_push(_e, cr_val=_cr, statblock=_prebuilt)
                            logger.info(f"[DDB_HB] Direct push: {_e['name']!r} CR {_cr}")
                        except Exception as _de:
                            logger.warning(f"[DDB_HB] Direct push failed for {_e.get('name')!r}: {_de}")
                async def _push_with_cop():
                    try:
                        from src.resource_cop import (
                            wait_for_ollama_turn, start_pipeline,
                            finish_pipeline, append_pipeline_failure,
                        )
                        _dec = await wait_for_ollama_turn("infestation_ddb_push", track="primary")
                        if not _dec.run_now:
                            logger.warning(f"[DDB_HB] Infestation DDB push deferred by cop: {_dec.reason}")
                            return
                        _run = await start_pipeline(
                            "infestation_ddb_push",
                            mission_type="infestation",
                            phase="ddb_push",
                        )
                        try:
                            await _push_all_direct()
                            await finish_pipeline(_run.run_id, status="finished")
                        except Exception as _pe:
                            await append_pipeline_failure(_run.run_id, _pe)
                            await finish_pipeline(_run.run_id, status="failed")
                    except Exception:
                        await _push_all_direct()   # cop unavailable — push anyway
                asyncio.create_task(_push_with_cop())
        except Exception as _dex:
            logger.warning(f"[DDB_HB] Could not start direct push task: {_dex}")

    # 3. Room content
    logger.info("[INFEST] Generating room descriptions...")
    room_contents = await generate_all_rooms(layout, monsters, mission)

    # Mimir: push boss room and entrance read-aloud docs
    if mimir_module_id:
        _docs = []
        for rid in layout.room_sequence[:3]:        # push first 3 rooms
            rc = room_contents.get(rid, {})
            desc = rc.get("read_aloud") or rc.get("description") or rc.get("title", "")
            if desc:
                _docs.append({"title": rc.get("name", f"Room {rid}"), "type": "read_aloud", "content": desc})
        await mimir_docs(mimir_module_id, _docs)

    # 4. A1111 maps (if enabled)
    room_maps: Dict[int, Path] = {}
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            logger.info("[INFEST] Generating room maps...")
            lora = os.getenv("A1111_MAP_LORA_DUNGEON", "EnvyFluxDungeonMap01")
            lora_w = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
            map_attempts = max(1, int(os.getenv("INFESTATION_ROOM_MAP_ATTEMPTS", "3")))
            retry_delay = max(1, int(os.getenv("INFESTATION_ROOM_MAP_RETRY_DELAY", "45")))
            by_id = {r.room_id: r for r in layout.rooms}
            for rid in layout.room_sequence:
                room = by_id.get(rid)
                if not room:
                    continue
                rc = room_contents.get(rid, {})
                path = None
                for attempt in range(1, map_attempts + 1):
                    path = await generate_room_map(room, rc, layout, out_dir, lora, lora_w)
                    if path:
                        break
                    if attempt < map_attempts:
                        logger.info(
                            f"[INFEST] Room map R{rid} not ready "
                            f"(attempt {attempt}/{map_attempts}); retrying in {retry_delay}s"
                        )
                        await asyncio.sleep(retry_delay)
                if path:
                    room_maps[rid] = path
                    # Mimir: upload first map per module (boss room preferred)
                    if mimir_module_id and room.is_boss:
                        await mimir_map(mimir_module_id, path, map_name=f"Boss: {room.room_type}")
                else:
                    logger.warning(f"[INFEST] Room map unavailable after {map_attempts} attempt(s): R{rid}")
                await asyncio.sleep(1)
        else:
            logger.warning("[INFEST] A1111 not available — skipping maps")

    # 5. Module HTML
    logger.info("[INFEST] Rendering module HTML...")
    module_html = render_infestation_module(layout, monsters, room_contents, room_maps, mission, strength)
    # Append Mimir stat-block reference section
    module_html += render_mimir_section(enriched_enemies, [], mimir_module_id or "")
    module_path = out_dir / "module.html"
    module_path.write_bytes(module_html.encode("utf-8"))

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    room_lookup = {r.room_id: r for r in layout.rooms}
    room_rows = []
    for rid in layout.room_sequence:
        room = room_lookup.get(rid)
        rc = room_contents.get(rid, {})
        if room:
            room_rows.append(f"- Room {rid} ({room.room_type}): {rc.get('title', rc.get('name', 'Infested chamber'))}")
    monster_list = monsters.get("variants", []) if isinstance(monsters, dict) else []
    boss = monsters.get("boss", {}) if isinstance(monsters, dict) else {}
    dm_md = (
        f"## Infestation DM Guide\n"
        f"### Site\n"
        f"- Subtype: {subtype}\n"
        f"- Rooms: {len(layout.rooms)}\n"
        f"- Grid: {layout.grid_w} x {layout.grid_h}\n"
        f"- Live scaling: {_party_scaling_note(strength)}\n\n"
        f"### Monster Roster\n"
        + "\n".join(f"- {m.get('name')}: CR {m.get('cr')} / {m.get('density_note', '')}" for m in monster_list)
        + f"\n\n### Boss\n{boss.get('name', 'Infestation boss')} - {boss.get('tactics', '')}\n\n"
        f"### Room Sequence\n"
        + "\n".join(room_rows)
    )
    players_md = (
        f"## Player Infestation Guide\n"
        f"### Public Situation\nThe site is infested and needs to be cleared, investigated, or contained for {faction}.\n\n"
        f"### What You Can Tell From Outside\n"
        f"- Infestation type: {subtype}\n"
        f"- Approximate room count: {len(layout.rooms)}\n"
        f"- Expect hazards, lair signs, and monster behavior shaped by the infestation.\n\n"
        f"Proceed room by room. Visible room descriptions and read-aloud text are in the module."
    )
    chart_md = (
        f"## Infestation Chart Pack\n"
        f"### Dungeon Map\n```\n{layout.ascii_map}\n```\n\n"
        f"### Room Checklist\n"
        + "\n".join(room_rows)
        + "\n\n### Monster Quick Reference\n"
        + "\n".join(f"| {m.get('name')} | CR {m.get('cr')} | {m.get('density_note', '')} | {m.get('special', '')} |" for m in monster_list)
    )
    session_md = (
        f"## Infestation Session Runner\n"
        f"### Room Progress\n"
        + "\n".join(f"- [ ] {row[2:]}" for row in room_rows)
        + "\n\n### Session Notes\nTrack rooms cleared, monsters bypassed, hazards triggered, treasure recovered, and unresolved lair effects."
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, faction, players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, chart_md)
    write_component(out_dir, "session", "Run Session", title, faction, session_md)
    maps_name = write_maps_page(out_dir, title, faction, list(room_maps.values()))
    box_components = component_links(has_maps=bool(maps_name))

    # 6. Index HTML — needed by the Flask /modules/<slug>/ route
    try:
        from src.mission_builder.html_renderer import render_index
        component_links = box_components
        index_html = render_index(
            novel_title=title,
            faction=faction,
            tier=mission.get("tier", "standard"),
            cr=cr,
            player_name=mission.get("player_name", "") or "Open",
            chapters=[],
            components=component_links,
            chart_pack=None,
            map_count=len(room_maps),
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as _e:
        logger.warning(f"[INFEST] Could not write index.html: {_e}")
        index_path = module_path

    # 7. Write module_slug back to DB
    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as _e:
        logger.warning(f"[INFEST] Could not write module_slug: {_e}")

    # 8. Zip
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[INFEST] Complete: {title!r} → {out_dir.name} ({len(layout.rooms)} rooms, {len(room_maps)} maps)")
    return index_path
