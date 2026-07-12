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
import random
import asyncio
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple


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
from src.mission_builder.monster_roster import get_monsters_by_cr_sources, monster_summary

OUTPUT_BASE     = Path(__file__).resolve().parent.parent.parent / "generated_modules"
ROOM_MAP_CACHE  = OUTPUT_BASE / "_room_map_cache"
OLLAMA_URL      = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")

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
        "options":  {"num_predict": tokens, "temperature": 0.75, "num_ctx": _fit_ctx(system + prompt, tokens)},
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


def _attacks_from_db(monster: dict, limit: int = 3) -> List[str]:
    actions = monster.get("actions") or ""
    if not actions:
        return [f"Attack. Uses its listed CR {monster.get('cr')} combat routine."]
    return [p.strip() for p in str(actions).split("\n\n") if p.strip()][:limit]


def _variant_from_db(monster: dict, density_note: str) -> dict:
    return {
        "name": monster.get("name"),
        "cr": str(monster.get("cr") or "1"),
        "hp": int(monster.get("hp") or 10),
        "ac": int(monster.get("ac") or 12),
        "speed": monster.get("speed") or "30 ft.",
        "attacks": _attacks_from_db(monster, 2),
        "special": (str(monster.get("traits") or "").split("\n\n")[0] or None),
        "density_note": density_note,
        "db_summary": monster_summary(monster),
    }


def _boss_from_db(monster: dict) -> dict:
    traits = str(monster.get("traits") or "")
    return {
        "name": monster.get("name"),
        "cr": str(monster.get("cr") or "1"),
        "hp": int(monster.get("hp") or 30),
        "ac": int(monster.get("ac") or 14),
        "speed": monster.get("speed") or "30 ft.",
        "attacks": _attacks_from_db(monster, 4),
        "legendary_actions": monster.get("legendary_actions") or None,
        "lair_action": monster.get("lair_actions") or "At initiative count 20, the lair shifts and one room feature becomes difficult terrain.",
        "tactics": (traits.split("\n\n")[0] if traits else "Uses terrain and minions to isolate the weakest target."),
        "db_summary": monster_summary(monster),
    }


def _db_infestation_roster(subtype: str, cr: int, faction: str) -> dict:
    prefer_void = any(w in f"{subtype} {faction}".lower() for w in ("void", "rift", "corrupt"))
    variants = get_monsters_by_cr_sources(
        max(1, cr - 2),
        cr + 1,
        count=3,
        include_void=not prefer_void,
        only_void=prefer_void,
        sources=("undercity", "undercity_high_cr"),
    )
    boss_rows = get_monsters_by_cr_sources(
        cr + 1,
        cr + 3,
        count=1,
        include_void=True,
        only_void=prefer_void,
        sources=("undercity", "undercity_high_cr"),
    )
    if len(variants) < 2 or not boss_rows:
        return {}
    primary = variants[0]
    secondary = variants[1] if len(variants) > 1 else variants[0]
    notes = [
        "light rooms",
        "normal/heavy rooms",
        "heavy rooms and boss-room minions",
    ]
    return {
        "primary_type": primary.get("name"),
        "secondary_type": secondary.get("name"),
        "variants": [_variant_from_db(m, notes[i] if i < len(notes) else "normal rooms") for i, m in enumerate(variants)],
        "boss": _boss_from_db(boss_rows[0]),
        "infestation_note": f"{primary.get('name')} and related threats have claimed this {subtype}; their pressure now intersects {faction}.",
        "source": "monsters_db",
    }


async def generate_monster_roster(subtype: str, cr: int, faction: str) -> dict:
    db_roster = _db_infestation_roster(subtype, cr, faction)
    if db_roster:
        return db_roster

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

    # Build explicit monster roster lines for the prompt so the LLM uses real names
    variants = monsters.get("variants") or []
    roster_lines = []
    for v in variants:
        cr_str  = v.get("cr", "?")
        density = v.get("density_note", "").lower()
        if "light" in density:
            count_hint = "1–2"
        elif "heavy" in density or "swarm" in density:
            count_hint = "4–6"
        else:
            count_hint = "2–4"
        roster_lines.append(f"  - {v.get('name','?')} (CR {cr_str}) — {count_hint} in normal/heavy rooms")
    if boss_name:
        boss_cr = str(monsters.get("boss", {}).get("cr", "?"))
        roster_lines.append(f"  - {boss_name} (CR {boss_cr}) — BOSS ROOM ONLY, plus 2-3 minions from above")
    roster_text = "\n".join(roster_lines) or f"  - {primary} (use judgment)"

    prompt = f"""Infestation mission: "{mission.get('title','Unknown')}"
Location type: {layout.subtype} — {len(layout.rooms)} rooms total.
Faction: {mission.get('faction','Independent')}
Infestation note: {note}

MONSTER ROSTER (use ONLY these names — no invented creatures):
{roster_text}

DENSITY GUIDE:
  empty  → no monsters
  light  → 1-2 of the weakest roster creature
  normal → 2-4 mixed roster creatures
  heavy  → 4-6 mixed, at least one stronger variant
  boss   → {boss_name} + 2-3 minions

Generate content for these {len(room_list)} rooms. Output exactly this JSON:
{{
  "rooms": [
    {{
      "id": <room id number>,
      "name": "short evocative room name",
      "read_aloud": "2-3 sentences read aloud to players. Specific sensory details. No monster spoilers unless visible.",
      "dm_notes": "What the DM knows: hidden features, monster positions, traps, secrets.",
      "monsters": "REQUIRED: Name the exact creatures present and their count. E.g. '2 Giant Sewer Rats lurking behind the pipes, 1 Black Pudding in the drainage channel.' For rooms with no enemies write 'empty'.",
      "features": ["feature 1", "feature 2", "feature 3"],
      "exits": "Describe how exits look — a corroded hatch, a collapsed archway, etc.",
      "treasure": "Loot or nothing — be specific (e.g. '12 EC in a rusted tin', 'a faction signet ring').",
      "hazard": "Environmental hazard or trap (or null if none)."
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


def _room_map_cache_path(subtype: str, room_type: str, density: str) -> Path:
    """Stable cache path keyed on subtype + room_type + density."""
    slug = re.sub(r"[^\w]", "_", room_type.lower().strip())[:40]
    return ROOM_MAP_CACHE / subtype / f"{slug}__{density}.png"


# Subtype → map_type tag used to query battle_maps_library
_SUBTYPE_MAP_TYPE: Dict[str, str] = {
    "sewer":    "sewer",
    "basement": "dungeon",
    "lair":     "cave",
    "dungeon":  "dungeon",
}


def _annotate_map_with_labels(
    src_path: Path,
    rooms: List[InfestationRoom],
    layout: InfestationLayout,
    label_order: List[int],   # room_ids in A/B/C order
    out_path: Path,
) -> Path:
    """
    Draw a yellow circle with a black letter (A, B, C…) onto the map image
    at each room's grid position.  Returns the annotated image path.

    How label positions work:
      Each InfestationRoom has grid_x / grid_y — its column/row in the
      abstract dungeon grid.  We scale those to pixel coordinates using the
      grid's bounding box and a 10 % margin so labels don't land on edges.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(src_path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    W, H = img.size

    room_by_id = {r.room_id: r for r in rooms}

    xs = [r.grid_x for r in rooms]
    ys = [r.grid_y for r in rooms]
    span_x = max(1, max(xs) - min(xs))
    span_y = max(1, max(ys) - min(ys))
    min_x, min_y = min(xs), min(ys)

    MARGIN = 0.10   # keep labels 10 % away from edges
    usable_w = W * (1 - 2 * MARGIN)
    usable_h = H * (1 - 2 * MARGIN)

    # Circle radius scales with image size — comfortable on any resolution
    radius = max(14, min(W, H) // 28)
    font_size = max(12, radius)

    # Try to load a readable TTF; fall back to PIL default if unavailable
    font = None
    for candidate in [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            font = ImageFont.truetype(candidate, font_size)
            break
        except Exception:
            pass

    for i, room_id in enumerate(label_order):
        room = room_by_id.get(room_id)
        if not room:
            continue
        letter = chr(ord("A") + i)

        # Map grid coordinates → pixel coordinates
        px = int(W * MARGIN + ((room.grid_x - min_x) / span_x) * usable_w) if span_x else W // 2
        py = int(H * MARGIN + ((room.grid_y - min_y) / span_y) * usable_h) if span_y else H // 2

        # Draw shadow for legibility on any background
        for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
            draw.ellipse(
                [px - radius + dx, py - radius + dy, px + radius + dx, py + radius + dy],
                fill=(0, 0, 0, 160),
            )

        # Main circle — yellow fill, black border
        draw.ellipse(
            [px - radius, py - radius, px + radius, py + radius],
            fill=(255, 220, 40, 230),
            outline=(0, 0, 0, 255),
            width=2,
        )

        # Letter centred in circle
        if font:
            bbox = font.getbbox(letter)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text((px - tw // 2, py - th // 2), letter, fill=(0, 0, 0, 255), font=font)
        else:
            draw.text((px, py), letter, fill=(0, 0, 0, 255), anchor="mm")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, "PNG")
    return out_path


def pull_and_annotate_overview(
    layout: InfestationLayout,
    label_order: List[int],
    out_dir: Path,
) -> Optional[Path]:
    """
    Pull one map from battle_maps_library matching the infestation subtype,
    annotate it with A/B/C… labels at room grid positions, and save to
    out_dir/maps/overview_labeled.png.

    Returns the annotated path, or None if no library map is available.
    """
    from src.battle_map_library import get_battle_map
    import shutil

    maps_dir = out_dir / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)

    map_type = _SUBTYPE_MAP_TYPE.get(layout.subtype, "dungeon")
    row = get_battle_map(map_type=map_type)
    if not row:
        # Fallback: any analyzed map will do
        row = get_battle_map()
    if not row:
        logger.warning("[INFEST] No library map found for overview — skipping annotation")
        return None

    src = Path(row.get("file_path", ""))
    if not src.exists():
        logger.warning(f"[INFEST] Library map file missing: {src}")
        return None

    raw_path = maps_dir / f"overview_raw_{layout.subtype}.png"
    shutil.copy2(src, raw_path)
    try:
        from src.mission_builder.vtt_renderer import write_grid_sidecar
        write_grid_sidecar(raw_path, {"map_type": map_type, "subtype": layout.subtype, "source": str(src)})
    except Exception as _sc_err:
        logger.warning(f"[INFEST] VTT sidecar write failed for raw map: {_sc_err}")

    out_path = maps_dir / "overview_labeled.png"
    try:
        result = _annotate_map_with_labels(raw_path, layout.rooms, layout, label_order, out_path)
        if result and result.exists():
            try:
                from src.mission_builder.vtt_renderer import write_grid_sidecar
                write_grid_sidecar(result, {"map_type": map_type, "subtype": layout.subtype, "labeled": True})
            except Exception as _sc_err2:
                logger.warning(f"[INFEST] VTT sidecar write failed for labeled map: {_sc_err2}")
        return result
    except Exception as exc:
        logger.warning(f"[INFEST] Map annotation failed: {exc} — using raw map")
        return raw_path

def _esc(t: str) -> str:
    import html
    return html.escape(str(t or ""))


# Bare density labels the LLM sometimes outputs instead of real content
_DENSITY_LABELS = {"empty", "light", "normal", "heavy", "boss"}


def _format_monsters(monsters_field, room: InfestationRoom, roster: dict) -> str:
    """
    Render the room's monsters field as a clean text string.

    Handles three cases:
      1. List of dicts  — from plot-room injection: {"monster": name, "placement": ..., "count": N}
      2. Bare density   — LLM returned "light" / "heavy" etc. instead of names; fall back to roster
      3. Normal string  — LLM returned a proper description; use as-is
    """
    # Case 1: list of placement dicts (plot room)
    if isinstance(monsters_field, list):
        parts = []
        for entry in monsters_field:
            if isinstance(entry, dict):
                name  = entry.get("monster") or entry.get("name") or "Unknown creature"
                count = entry.get("count", 1)
                place = entry.get("placement") or entry.get("position") or ""
                line  = f"{count}× {name}"
                if place:
                    line += f" — {place}"
                parts.append(line)
            else:
                parts.append(str(entry))
        return "\n".join(parts) if parts else "None."

    text = str(monsters_field or "").strip()

    # Treat literal "None" strings (Python None leaked to str, or LLM echo) as empty
    if text.lower() in ("none", "none.", "null", "") or text.lower().startswith("none —") or text.lower().startswith("none --"):
        text = "empty"

    # Case 2: bare density label — substitute from roster
    if text.lower() in _DENSITY_LABELS:
        density = room.monster_density
        variants = roster.get("variants") or []
        boss     = roster.get("boss") or {}

        if density == "empty":
            return "Empty — signs of recent passage only."
        if density == "boss" and boss:
            boss_name    = boss.get("name", "Boss creature")
            boss_cr      = boss.get("cr", "?")
            minion_name  = variants[0].get("name", "minion") if variants else "minion"
            return f"1× {boss_name} (CR {boss_cr}) — central threat\n2–3× {minion_name} — flanking"
        if not variants:
            return f"{density.title()} encounter — see roster."
        if density == "light":
            v = variants[0]
            return f"1–2× {v.get('name','creature')} (CR {v.get('cr','?')})"
        if density == "heavy":
            lines = []
            for v in variants[:2]:
                lines.append(f"3–4× {v.get('name','creature')} (CR {v.get('cr','?')})")
            return "\n".join(lines)
        # normal
        lines = []
        for v in variants[:2]:
            lines.append(f"2–3× {v.get('name','creature')} (CR {v.get('cr','?')})")
        return "\n".join(lines)

    # Case 3: LLM gave a real description
    return text if text else "None."


def render_infestation_module(
    layout: InfestationLayout,
    monsters: dict,
    room_contents: Dict[int, dict],
    room_maps: Dict[int, Path],      # kept for signature compatibility — not used for per-room images
    mission: dict,
    strength: Optional[Dict[str, Any]] = None,
    overview_map: Optional[Path] = None,
    label_order: Optional[List[int]] = None,
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
    _lo       = label_order or layout.room_sequence or [r.room_id for r in layout.rooms]
    rooms_seq = [by_id[rid] for rid in _lo if rid in by_id]
    # Map room_id → letter label (A, B, C…)
    room_label: Dict[int, str] = {rid: chr(ord("A") + i) for i, rid in enumerate(_lo)}

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

    # Overview map HTML — labeled image if available, ASCII fallback always shown
    overview_map_html = ""
    if overview_map and overview_map.exists():
        overview_map_html = (
            f'<img class="inf-room-map" style="max-height:520px;margin-bottom:6px;" '
            f'src="maps/{_esc(overview_map.name)}" alt="Dungeon overview map with area labels">'
            f'<p style="font-size:11px;color:#888;margin:0 0 14px;">Areas A–{chr(ord("A")+len(rooms_seq)-1)} '
            f'correspond to room descriptions below.</p>'
        )

    # Area legend — one line per room: A — Sewer Junction (heavy)
    _boss_tag  = '  <em style="color:#8a1a1a">[Boss]</em>'
    _entry_tag = '  <em style="color:#2a6a2a">[Entry]</em>'
    legend_rows = "".join(
        '<tr>'
        f'<td style="font-weight:700;padding:2px 10px 2px 0;color:var(--faction);">{room_label.get(r.room_id, "?")}</td>'
        f'<td style="padding:2px 0;">{_esc(r.room_type.title())}'
        + (_boss_tag if r.is_boss else "")
        + (_entry_tag if r.is_entry else "")
        + '</td></tr>'
        for r in rooms_seq
    )
    legend_html = f'<table style="font-size:13px;border-collapse:collapse;margin:10px 0 18px;">{legend_rows}</table>'

    overview_html = f"""
<div class="chapter-header">
  <div class="ch-label">{_esc(title)}</div>
  <h2>Infestation — {layout.subtype.title()}</h2>
</div>
<h1>{_esc(title)}</h1>
<p><strong>Type:</strong> {layout.subtype.title()} infestation &nbsp;|&nbsp;
<strong>Areas:</strong> {len(layout.rooms)} &nbsp;|&nbsp;
<strong>Faction:</strong> {_esc(faction)}</p>

{scaling_html}

<h2>Infestation Overview</h2>
<p>{_esc(monsters.get('infestation_note',''))}</p>

{overview_map_html}

<h2>Area Legend</h2>
{legend_html}

<details style="margin:10px 0 20px;">
  <summary style="cursor:pointer;font-size:12px;color:#888;">ASCII layout (DM reference)</summary>
  <div class="inf-ascii">{_esc(layout.ascii_map)}</div>
</details>

<h2>Monster Roster</h2>
<h3>Variants (weakest → strongest)</h3>
{variants_html}
<h3>Boss: {_esc(boss.get('name','?'))}</h3>
{boss_card}
<hr>
<h2>Area Descriptions</h2>
"""

    # ── Room cards ──
    room_cards = []
    for room in rooms_seq:
        rc  = room_contents.get(room.room_id, {})
        lbl = room_label.get(room.room_id, "?")

        badges = ""
        if room.is_entry: badges += '<span class="inf-badge inf-badge-entry">Entry</span>'
        if room.is_boss:  badges += '<span class="inf-badge inf-badge-boss">Boss</span>'
        if room.monster_density == "empty": badges += '<span class="inf-badge inf-badge-empty">Clear</span>'
        if room.monster_density == "heavy": badges += '<span class="inf-badge inf-badge-heavy">Heavy</span>'

        den_css = f'inf-den-{room.monster_density}'

        # No per-room map images — overview handles spatial reference
        map_path = None
        map_html = ""
        if False:  # placeholder — kept for future per-room map support
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
        hazard_val = rc.get("hazard")
        if hazard_val and str(hazard_val).strip().lower() not in ("none", "null", "n/a", "-"):
            hazard_html = f'<div class="inf-hazard">⚠️ Hazard: {_esc(hazard_val)}</div>'

        # Boss enhancement
        boss_enhancement_html = ""
        if room.is_boss and rc.get("boss_read_aloud"):
            triggers_html = "".join(f"<li>{_esc(t)}</li>" for t in (rc.get("boss_triggers") or []))
            phases_html = "".join(f"<li>{_esc(p)}</li>" for p in (rc.get("boss_phase_changes") or []))
            boss_enhancement_html = (
                f'<div class="inf-section"><div class="inf-section-label" style="color:#8a1a1a;">Boss Encounter Read Aloud</div>'
                f'<div class="inf-section-body read-aloud" style="background:#1a0808;color:#fcc;border-left:5px solid #8a1a1a;padding:10px 14px;border-radius:0 5px 5px 0;font-style:italic;">'
                f'{_esc(rc.get("boss_read_aloud",""))}</div></div>'
                + (f'<div class="inf-section"><div class="inf-section-label">Boss Triggers</div><ul class="inf-feature-list">{triggers_html}</ul></div>' if triggers_html else "")
                + (f'<div class="inf-section"><div class="inf-section-label">Phase Changes (≤50% HP)</div><ul class="inf-feature-list">{phases_html}</ul></div>' if phases_html else "")
                + (f'<div class="inf-section"><div class="inf-section-label">Death Effect</div><div class="inf-section-body">{_esc(rc.get("boss_death_effect",""))}</div></div>' if rc.get("boss_death_effect") else "")
            )

        # Plot anchor badge
        plot_anchor_html = ""
        if rc.get("plot_anchor"):
            plot_anchor_html = f'<div style="background:#2a1a5a;color:#c8b8ff;border-radius:4px;padding:4px 10px;font-size:11px;font-weight:bold;margin-bottom:8px;display:inline-block;">📌 Canon anchor: {_esc(rc["plot_anchor"])}</div>'

        room_cards.append(f"""
<div class="inf-room" id="room-{room.room_id}">
  <div class="inf-room-header">
    <span class="inf-room-num">Area {lbl}</span>
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
    <div class="inf-monster-block">{_esc(_format_monsters(rc.get('monsters'), room, monsters))}</div>
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
  {plot_anchor_html}
  {(f'<div class="inf-section"><div class="inf-section-label">Treasure</div><div class="inf-section-body">{_esc(rc.get("treasure","Nothing of value."))}</div></div>') if rc.get('treasure') else ''}
  {hazard_html}
  {boss_enhancement_html}
</div>""")

    # Room progress tracker — interactive HTML checkboxes for session use
    tracker_rows = "".join(
        f'<label style="display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer;">'
        f'<input type="checkbox" style="width:16px;height:16px;cursor:pointer;"> '
        f'<span style="font-family:monospace;font-size:13px;">Area {room_label.get(r.room_id, str(r.room_id))} — '
        f'{_esc(room_contents.get(r.room_id, {}).get("name", r.room_type.title()))}</span>'
        f'</label>'
        for r in layout.rooms
    )
    tracker_html = f"""
<div style="border:2px solid #c8b89a;border-radius:8px;margin:20px 0;padding:16px 20px;background:#fdfaf5;">
  <h2 style="margin:0 0 12px;font-size:14px;text-transform:uppercase;letter-spacing:.1em;color:#555;">
    Session Tracker
  </h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:2px 24px;margin-bottom:12px;">
    {tracker_rows}
  </div>
  <div style="margin-top:8px;">
    <div style="font-size:12px;text-transform:uppercase;color:#888;margin-bottom:4px;">Session Notes</div>
    <textarea rows="4" style="width:100%;font-family:inherit;font-size:13px;padding:8px;border:1px solid #ddd;border-radius:4px;resize:vertical;"
      placeholder="Rooms cleared, bypassed monsters, hazards triggered, treasure recovered, unresolved lair effects..."></textarea>
  </div>
  <div style="margin-top:6px;display:flex;gap:12px;flex-wrap:wrap;">
    <label style="font-size:12px;display:flex;align-items:center;gap:6px;cursor:pointer;">
      <input type="checkbox"> Boss encountered
    </label>
    <label style="font-size:12px;display:flex;align-items:center;gap:6px;cursor:pointer;">
      <input type="checkbox"> Boss defeated
    </label>
    <label style="font-size:12px;display:flex;align-items:center;gap:6px;cursor:pointer;">
      <input type="checkbox"> Objective complete
    </label>
    <label style="font-size:12px;display:flex;align-items:center;gap:6px;cursor:pointer;">
      <input type="checkbox"> Retreat triggered
    </label>
  </div>
</div>"""

    from src.treasure import loot_card as _loot_card
    content = overview_html + tracker_html + "\n".join(room_cards) + _loot_card(mission)

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


def _mission_context(mission: dict) -> Dict[str, Any]:
    """Extract named entities and stakes from the mission body for canon injection."""
    parts: List[str] = []
    for key in ("title", "faction", "npc_giver", "body", "description"):
        val = mission.get(key)
        if val:
            parts.append(str(val))
    text = " ".join(parts)
    terms = []
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9''.-]*(?:\s+[A-Z][A-Za-z0-9''.-]*){0,3}\b", text):
        t = m.group(0).strip()
        if t.lower() not in {"infestation", "dungeon", "standard", "mission", "posted"} and t not in terms:
            terms.append(t)
    stakes = re.findall(r"[^.!?\n]*(?:clear|infest|exterminate|contain|retrieve|evidence|culprit|contract|nest)[^.!?\n]*", text, flags=re.I)
    return {
        "canon_terms": terms[:12],
        "stakes": [s.strip() for s in stakes[:4] if s.strip()],
    }


def _pick_plot_room_id(layout: InfestationLayout) -> Optional[int]:
    """Find the room immediately before the boss in sequence; must not be entry."""
    seq = layout.room_sequence
    by_id = {r.room_id: r for r in layout.rooms}
    boss_idx = next((i for i, rid in enumerate(seq) if by_id.get(rid) and by_id[rid].is_boss), None)
    if boss_idx is None or boss_idx == 0:
        return None
    for i in range(boss_idx - 1, -1, -1):
        rid = seq[i]
        room = by_id.get(rid)
        if room and not room.is_entry and not room.is_boss:
            return rid
    return None


async def _generate_plot_room_content(
    room: "InfestationRoom",
    layout: "InfestationLayout",
    monsters: dict,
    mission: dict,
    canon_terms: List[str],
) -> dict:
    """Generate a single plot-room with mission canon baked into the prompt."""
    primary   = monsters.get("primary_type", "creatures")
    boss_name = (monsters.get("boss") or {}).get("name", "the boss")
    canon_str = ", ".join(canon_terms[:8]) or mission.get("title", "this mission")
    conns     = ", ".join(f"R{c[0]:02d} via {c[1]}" for c in room.connections) or "one onward passage"
    prompt = f"""D&D 5e dungeon room for "{mission.get('title','Infestation')}".
This is the PLOT ROOM — one room before the boss. It must contain a visible reference to the mission's canon terms: {canon_str}.

Room type: {room.room_type} | Density: {room.monster_density} | Connections: {conns}
Infestation: {primary} and {monsters.get('secondary_type', primary)}. Boss: {boss_name}.

Write content that:
- Makes the mission canon visible (a symbol, name, object, or sign tied to {canon_terms[0] if canon_terms else mission.get('faction','the faction')})
- Hints at what the boss room holds
- Gives players a clue about what created the infestation

Return JSON only:
{{
  "id": {room.room_id},
  "name": "evocative room name",
  "read_aloud": "2-3 sentences — mention one detail from the mission's canon context",
  "dm_notes": "DM secret: what the canon detail means; what this reveals about the infestation's true cause",
  "monsters": "monster placement and count",
  "features": ["feature 1", "feature 2", "feature 3"],
  "exits": "exit description",
  "treasure": "specific loot or nothing",
  "hazard": "environmental hazard or null",
  "plot_anchor": "the specific canon term or object visible in this room"
}}"""
    raw = await _ask(prompt, system=_SYSTEM_ROOMS, timeout=90, tokens=700)
    data = _parse_json(raw)
    if not data or not data.get("read_aloud"):
        return {}
    return data


async def _generate_boss_enhancement(
    boss_room_content: dict,
    monsters: dict,
    mission: dict,
    canon_terms: List[str],
) -> dict:
    """Generate rich boss encounter additions for the boss room."""
    boss = monsters.get("boss") or {}
    boss_name = boss.get("name", "the boss")
    canon_str = ", ".join(canon_terms[:6]) or mission.get("title", "this mission")
    existing_read_aloud = boss_room_content.get("read_aloud", "")
    prompt = f"""Enhance the boss room for a D&D 5e infestation mission.

Mission: "{mission.get('title','Infestation')}"
Canon context: {canon_str}
Boss creature: {boss_name} (CR {boss.get('cr','?')}, HP {boss.get('hp','?')})
Boss tactics: {boss.get('tactics','')}
Existing read-aloud: {existing_read_aloud}

Return JSON only:
{{
  "boss_read_aloud": "3 sentences — read aloud when players enter and see the boss for the first time. Make it specific to the mission canon.",
  "boss_triggers": ["3 environmental events or reactions the boss causes during the fight"],
  "boss_phase_changes": ["2 visible changes when the boss drops below 50% HP"],
  "boss_death_effect": "What happens to the room/environment when the boss is defeated — collapse, silence, release, revelation, etc."
}}"""
    raw = await _ask(prompt, system=_SYSTEM_ROOMS, timeout=90, tokens=500)
    data = _parse_json(raw)
    if not isinstance(data, dict) or not data.get("boss_read_aloud"):
        return {
            "boss_read_aloud": f"{boss_name} is already aware of you. It turns — not in surprise, but in the way a predator turns when it has decided the waiting is over.",
            "boss_triggers": ["The nest walls flex and seal one exit at initiative 20.", "Boss screech stuns anyone within 10 ft (DC 13 CON or stunned 1 turn, once per fight).", "At 50% HP, 1d4 minions surge from the walls."],
            "boss_phase_changes": [f"{boss_name} drops to all four limbs and its speed doubles.", "The lair action changes to a targeted area slam instead of difficult terrain."],
            "boss_death_effect": f"When {boss_name} falls, the infestation sounds cease instantly — the colony's link to its alpha severed. The nest material begins to dry and crumble. One previously sealed passage is now open.",
        }
    return data


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
        enrich_mission_loot as mimir_loot,
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

    # 3b. Plot room — inject mission canon into the pre-boss room
    mission_ctx = _mission_context(mission)
    canon_terms = mission_ctx.get("canon_terms", [])
    plot_room_id = _pick_plot_room_id(layout)
    if plot_room_id is not None and canon_terms:
        logger.info(f"[INFEST] Plot-room targeted generation for R{plot_room_id} with canon: {canon_terms[:4]}")
        by_id_tmp = {r.room_id: r for r in layout.rooms}
        plot_room_obj = by_id_tmp.get(plot_room_id)
        if plot_room_obj:
            plot_content = await _generate_plot_room_content(plot_room_obj, layout, monsters, mission, canon_terms)
            if plot_content and plot_content.get("read_aloud"):
                room_contents[plot_room_id] = plot_content
                logger.info(f"[INFEST] Plot room R{plot_room_id} content injected with anchor: {plot_content.get('plot_anchor','?')}")

    # 3c. Boss room enhancement pass
    boss_room_id = next((r.room_id for r in layout.rooms if r.is_boss), None)
    if boss_room_id is not None:
        logger.info(f"[INFEST] Boss enhancement pass for R{boss_room_id}")
        boss_enhancement = await _generate_boss_enhancement(room_contents.get(boss_room_id, {}), monsters, mission, canon_terms)
        if boss_enhancement:
            room_contents[boss_room_id] = {**room_contents.get(boss_room_id, {}), **boss_enhancement}

    # Mimir: push boss room and entrance read-aloud docs
    if mimir_module_id:
        _docs = []
        for rid in layout.room_sequence[:3]:        # push first 3 rooms
            rc = room_contents.get(rid, {})
            desc = rc.get("read_aloud") or rc.get("description") or rc.get("title", "")
            if desc:
                _docs.append({"title": rc.get("name", f"Room {rid}"), "type": "read_aloud", "content": desc})
        await mimir_docs(mimir_module_id, _docs)

    # 4. Overview map — pull one library map by subtype and annotate with A/B/C… labels
    label_order: List[int] = layout.room_sequence or [r.room_id for r in layout.rooms]
    overview_map: Optional[Path] = None
    room_maps: Dict[int, Path] = {}   # kept for HTML renderer signature compatibility
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        logger.info("[INFEST] Pulling and annotating overview map from battle_maps_library...")
        overview_map = pull_and_annotate_overview(layout, label_order, out_dir)
        if overview_map:
            logger.info(f"[INFEST] Overview map annotated: {overview_map.name}")
            if mimir_module_id:
                await mimir_map(mimir_module_id, overview_map, map_name="Dungeon Overview")
        else:
            logger.warning("[INFEST] No library map available for overview — module will have no map")

    # 5. Module HTML
    logger.info("[INFEST] Rendering module HTML...")
    module_html = render_infestation_module(layout, monsters, room_contents, room_maps, mission, strength,
                                            overview_map=overview_map, label_order=label_order)
    # Append Mimir stat-block reference section
    _loot_rewards = await mimir_loot(mimir_module_id or "", mission)
    module_html += render_mimir_section(enriched_enemies, _loot_rewards, mimir_module_id or "")
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
    actual_maps = [p for p in [overview_map] if p]
    maps_name = write_maps_page(out_dir, title, faction, actual_maps)
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
            map_count=len(actual_maps),
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as _e:
        logger.warning(f"[INFEST] Could not write index.html: {_e}")
        index_path = module_path

    # 7. Write module_slug back to DB
    try:
        from src.mission_builder.mission_db import write_module_slug_for_mission
        write_module_slug_for_mission(mission, out_dir.name, log_prefix="INFEST")
    except Exception as _e:
        logger.warning(f"[INFEST] Could not write module_slug: {_e}")

    # 8. Zip
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[INFEST] Complete: {title!r} → {out_dir.name} ({len(layout.rooms)} rooms, {len(actual_maps)} maps)")
    return index_path
