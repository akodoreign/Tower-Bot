"""
npc_statblock_backfill.py — Fill missing D&D 5e stat block fields for NPCs.

Runs 2-3 NPCs per lifecycle cycle. Generates deterministically:
  speed, skills, senses, languages, CR/XP, saving throw line, actions (from equipment)

Generates via Kimi:
  traits (2 flavor abilities in module sidebar style)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Speed by species keyword ──────────────────────────────────────────────────
_SPEED: Dict[str, int] = {
    "dwarf": 25, "halfling": 25, "gnome": 25,
    "elf": 30, "half-elf": 30, "human": 30, "tiefling": 30,
    "dragonborn": 30, "half-orc": 30, "tabaxi": 30,
    "aasimar": 30, "genasi": 30, "goliath": 35,
    "firbolg": 30, "kenku": 30, "lizardfolk": 30, "triton": 30,
    "kobold": 30, "goblin": 30, "hobgoblin": 30, "orc": 30,
    "warforged": 30, "changeling": 30, "kalashtar": 30,
    "leonin": 35, "loxodon": 30, "minotaur": 30,
}

# ── Darkvision species ────────────────────────────────────────────────────────
_DARKVISION = {
    "elf", "half-elf", "dwarf", "gnome", "half-orc", "tiefling",
    "aasimar", "dragonborn", "kobold", "goblin", "hobgoblin",
    "orc", "drow", "shadar-kai", "shadar kai", "yuan-ti",
}

# ── Languages by species ──────────────────────────────────────────────────────
_LANGUAGES: Dict[str, List[str]] = {
    "elf": ["Common", "Elvish"],
    "drow": ["Common", "Elvish", "Undercommon"],
    "dwarf": ["Common", "Dwarvish"],
    "halfling": ["Common", "Halfling"],
    "gnome": ["Common", "Gnomish"],
    "tiefling": ["Common", "Infernal"],
    "dragonborn": ["Common", "Draconic"],
    "half-orc": ["Common", "Orc"],
    "half-elf": ["Common", "Elvish"],
    "tabaxi": ["Common"],
    "human": ["Common"],
    "genasi": ["Common", "Primordial"],
    "aasimar": ["Common", "Celestial"],
    "firbolg": ["Common", "Elvish", "Giant"],
    "goliath": ["Common", "Giant"],
    "kobold": ["Common", "Draconic"],
    "goblin": ["Common", "Goblin"],
    "hobgoblin": ["Common", "Goblin"],
    "lizardfolk": ["Common", "Draconic"],
    "yuan-ti": ["Common", "Abyssal", "Draconic"],
    "triton": ["Common", "Primordial"],
}

# ── Faction bonus language ────────────────────────────────────────────────────
_FACTION_LANG: Dict[str, str] = {
    "Guild of Ashen Scrolls": "one additional language",
    "Wizards Tower": "one additional language",
    "Glass Sigil": "Undercommon",
    "Serpent Choir": "Abyssal",
    "Brother Thane's Cult": "Infernal",
    "Obsidian Lotus": "Undercommon",
}

# ── Skill → ability ───────────────────────────────────────────────────────────
SKILL_ABILITY: Dict[str, str] = {
    "Athletics": "STR",
    "Acrobatics": "DEX", "Sleight of Hand": "DEX", "Stealth": "DEX",
    "Arcana": "INT", "History": "INT", "Investigation": "INT",
    "Nature": "INT", "Religion": "INT",
    "Animal Handling": "WIS", "Insight": "WIS", "Medicine": "WIS",
    "Perception": "WIS", "Survival": "WIS",
    "Deception": "CHA", "Intimidation": "CHA",
    "Performance": "CHA", "Persuasion": "CHA",
}

# ── Class → (n_skills, pool) ──────────────────────────────────────────────────
_CLASS_SKILLS: Dict[str, tuple] = {
    "barbarian":  (2, ["Athletics", "Intimidation", "Nature", "Perception", "Survival", "Animal Handling"]),
    "bard":       (3, ["Acrobatics", "Athletics", "Deception", "History", "Insight", "Intimidation",
                       "Investigation", "Medicine", "Perception", "Performance", "Persuasion",
                       "Sleight of Hand", "Stealth"]),
    "cleric":     (2, ["History", "Insight", "Medicine", "Persuasion", "Religion"]),
    "druid":      (2, ["Arcana", "Animal Handling", "Insight", "Medicine", "Nature", "Perception",
                       "Religion", "Survival"]),
    "fighter":    (2, ["Acrobatics", "Athletics", "History", "Insight", "Intimidation", "Perception", "Survival"]),
    "monk":       (2, ["Acrobatics", "Athletics", "History", "Insight", "Religion", "Stealth"]),
    "paladin":    (2, ["Athletics", "Insight", "Intimidation", "Medicine", "Persuasion", "Religion"]),
    "ranger":     (3, ["Animal Handling", "Athletics", "Insight", "Investigation", "Nature",
                       "Perception", "Stealth", "Survival"]),
    "rogue":      (4, ["Acrobatics", "Athletics", "Deception", "Insight", "Intimidation", "Investigation",
                       "Perception", "Performance", "Persuasion", "Sleight of Hand", "Stealth"]),
    "sorcerer":   (2, ["Arcana", "Deception", "Insight", "Intimidation", "Persuasion", "Religion"]),
    "warlock":    (2, ["Arcana", "Deception", "History", "Intimidation", "Investigation", "Nature", "Religion"]),
    "wizard":     (2, ["Arcana", "History", "Insight", "Investigation", "Medicine", "Religion"]),
}

# ── CR / XP by level ──────────────────────────────────────────────────────────
_LEVEL_CR: Dict[int, str] = {
    1: "1/4", 2: "1/2", 3: "1", 4: "2",
    5: "3", 6: "3", 7: "4", 8: "4",
    9: "5", 10: "6", 11: "7", 12: "8",
    13: "9", 14: "10", 15: "11", 16: "12",
    17: "13", 18: "14", 19: "15", 20: "17",
}
_CR_XP: Dict[str, int] = {
    "0": 10, "1/8": 25, "1/4": 50, "1/2": 100,
    "1": 200, "2": 450, "3": 700, "4": 1100,
    "5": 1800, "6": 2300, "7": 2900, "8": 3900,
    "9": 5000, "10": 5900, "11": 7200, "12": 8400,
    "13": 10000, "14": 11500, "15": 13000,
}

# ── Weapon table (name_keyword, die, damage_type, range_type, reach_or_range) ─
_WEAPONS: List[tuple] = [
    ("Greatsword",      "2d6",  "slashing",    "melee",           "reach 5 ft., one target"),
    ("Greataxe",        "1d12", "slashing",    "melee",           "reach 5 ft., one target"),
    ("Longsword",       "1d8",  "slashing",    "melee",           "reach 5 ft., one target"),
    ("Shortsword",      "1d6",  "piercing",    "melee",           "reach 5 ft., one target"),
    ("Rapier",          "1d8",  "piercing",    "melee",           "reach 5 ft., one target"),
    ("Handaxe",         "1d6",  "slashing",    "melee_or_ranged", "reach 5 ft. or range 20/60 ft., one target"),
    ("Battleaxe",       "1d8",  "slashing",    "melee",           "reach 5 ft., one target"),
    ("Warhammer",       "1d8",  "bludgeoning", "melee",           "reach 5 ft., one target"),
    ("Mace",            "1d6",  "bludgeoning", "melee",           "reach 5 ft., one target"),
    ("Quarterstaff",    "1d6",  "bludgeoning", "melee",           "reach 5 ft., one target"),
    ("Dagger",          "1d4",  "piercing",    "melee_or_ranged", "reach 5 ft. or range 20/60 ft., one target"),
    ("Javelin",         "1d6",  "piercing",    "melee_or_ranged", "reach 5 ft. or range 30/120 ft., one target"),
    ("Spear",           "1d6",  "piercing",    "melee_or_ranged", "reach 5 ft. or range 20/60 ft., one target"),
    ("Flail",           "1d8",  "bludgeoning", "melee",           "reach 5 ft., one target"),
    ("Scimitar",        "1d6",  "slashing",    "melee",           "reach 5 ft., one target"),
    ("Whip",            "1d4",  "slashing",    "melee",           "reach 10 ft., one target"),
    ("Longbow",         "1d8",  "piercing",    "ranged",          "range 150/600 ft., one target"),
    ("Shortbow",        "1d6",  "piercing",    "ranged",          "range 80/320 ft., one target"),
    ("Heavy Crossbow",  "1d10", "piercing",    "ranged",          "range 100/400 ft., one target"),
    ("Light Crossbow",  "1d8",  "piercing",    "ranged",          "range 80/320 ft., one target"),
    ("Hand Crossbow",   "1d6",  "piercing",    "ranged",          "range 30/120 ft., one target"),
    ("Crossbow",        "1d8",  "piercing",    "ranged",          "range 80/320 ft., one target"),
]

_FINESSE = {"rapier", "shortsword", "dagger", "whip", "scimitar"}
_MULTIATTACK_CLASSES = {"fighter", "ranger", "barbarian", "paladin", "monk"}
_CASTER_CLASSES = {"wizard", "sorcerer", "warlock", "druid", "cleric", "bard"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mod(score: int) -> int:
    return (score - 10) // 2

def _sign(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)

def _needs_backfill(stats: dict) -> bool:
    return not stats.get("speed") or not stats.get("skills") or not stats.get("traits")


# ── Deterministic generators ──────────────────────────────────────────────────

def _build_speed(species: str) -> int:
    s = (species or "").lower()
    for kw, spd in _SPEED.items():
        if kw in s:
            return spd
    return 30

def _build_skills(class_name: str, stats: dict, pb: int) -> Dict[str, int]:
    cls = (class_name or "").lower().split()[0]
    n, pool = _CLASS_SKILLS.get(cls, (2, ["Perception", "Insight", "Athletics"]))
    pool_sorted = sorted(pool, key=lambda sk: -_mod(stats.get(SKILL_ABILITY.get(sk, "WIS"), 10)))
    result = {}
    for sk in pool_sorted[:n]:
        ab = SKILL_ABILITY.get(sk, "WIS")
        result[sk] = _mod(stats.get(ab, 10)) + pb
    return result

def _build_senses(species: str, stats: dict, skills: Dict[str, int]) -> dict:
    s = (species or "").lower()
    senses: dict = {}
    for kw in _DARKVISION:
        if kw in s:
            senses["darkvision"] = "60 ft."
            break
    perc = skills.get("Perception")
    senses["passive_perception"] = (10 + perc) if perc is not None else (10 + _mod(stats.get("WIS", 10)))
    return senses

def _build_languages(species: str, faction: str) -> List[str]:
    s = (species or "").lower()
    langs: List[str] = ["Common"]
    for kw, lang_list in _LANGUAGES.items():
        if kw in s:
            langs = list(lang_list)
            break
    extra = _FACTION_LANG.get(faction or "")
    if extra and extra not in langs:
        langs.append(extra)
    return langs

def _build_saves(stats: dict, save_profs: list, pb: int) -> Dict[str, int]:
    result = {}
    for ab in (save_profs or []):
        score = stats.get(ab, 10)
        result[ab] = _mod(score) + pb
    return result

def _build_actions(equipment: list, stats: dict, pb: int, level: int, class_name: str) -> List[dict]:
    cls = (class_name or "").lower()
    str_mod = _mod(stats.get("STR", 10))
    dex_mod = _mod(stats.get("DEX", 10))

    weapons_found: List[tuple] = []
    for item in (equipment or []):
        if not isinstance(item, dict):
            continue
        iname = item.get("name", "")
        for wname, wdie, wdtype, wrange, wreachrange in _WEAPONS:
            if wname.lower() in iname.lower():
                weapons_found.append((iname, wname, wdie, wdtype, wrange, wreachrange))
                break

    actions: List[dict] = []

    # Multiattack
    attacks = 1
    if any(c in cls for c in _MULTIATTACK_CLASSES) and level >= 5:
        attacks = 2
    if level >= 11:
        attacks = 3
    if weapons_found and attacks >= 2:
        wlist = " and ".join(w[0] for w in weapons_found[:attacks])
        actions.append({
            "name": "Multiattack",
            "description": f"The {cls.split()[0]} makes {attacks} attacks: {wlist}.",
        })

    # Individual weapon attacks
    for iname, wname, wdie, wdtype, wrange, wreachrange in weapons_found[:3]:
        magic = 0
        m = re.search(r'\+(\d)', iname)
        if m:
            magic = int(m.group(1))

        is_finesse = wname.lower() in _FINESSE
        if wrange == "ranged":
            atk_ab = dex_mod
        elif is_finesse:
            atk_ab = max(str_mod, dex_mod)
        else:
            atk_ab = str_mod

        atk_bonus = atk_ab + pb + magic
        dmg_mod   = atk_ab + magic
        dmg_str   = f"{wdie} + {dmg_mod}" if dmg_mod >= 0 else f"{wdie} - {abs(dmg_mod)}"

        if wrange == "ranged":
            prefix = "Ranged Weapon Attack"
        elif wrange == "melee_or_ranged":
            prefix = "Melee or Ranged Weapon Attack"
        else:
            prefix = "Melee Weapon Attack"

        actions.append({
            "name": iname,
            "description": f"{prefix}: {_sign(atk_bonus)} to hit, {wreachrange}. Hit: {dmg_str} {wdtype} damage.",
        })

    # Spellcasting line for casters
    if any(c in cls for c in _CASTER_CLASSES):
        int_m = _mod(stats.get("INT", 10))
        wis_m = _mod(stats.get("WIS", 10))
        cha_m = _mod(stats.get("CHA", 10))
        spell_ab = max(int_m, wis_m, cha_m)
        spell_dc = 8 + pb + spell_ab
        spell_atk = pb + spell_ab
        actions.append({
            "name": "Spellcasting",
            "description": f"Spell attack {_sign(spell_atk)}, spell save DC {spell_dc}. "
                           f"The {cls.split()[0]} has a list of spells prepared appropriate to their level.",
        })

    return actions


# ── Trait generation (Kimi) ───────────────────────────────────────────────────

async def _generate_traits(data: dict) -> List[dict]:
    from src.agents import generate_with_kimi
    stats    = data.get("stats") or {}
    name     = data.get("name", "Unknown")
    cls      = stats.get("class", data.get("dnd_class", "warrior"))
    level    = stats.get("level", data.get("level", 1))
    faction  = data.get("faction", "Independent")
    role     = data.get("role", "")
    motiv    = data.get("motivation", "")

    prompt = (
        f"Write 2 special traits for a D&D 5e module sidebar NPC.\n"
        f"NPC: {name}, {cls} Lv{level}, {faction}\n"
        f"Role: {role}\n"
        f"Motivation: {motiv}\n\n"
        f"Format: TraitName. One-sentence mechanical or behavioral description (max 25 words).\n"
        f"Example:\n"
        f"Driven. This creature has advantage on saving throws against being charmed and frightened.\n"
        f"Unconventional. On each of its turns, this creature can use a bonus action to take the Use an Object action.\n\n"
        f"Output only 2 traits, nothing else."
    )
    try:
        raw = await generate_with_kimi(prompt, max_tokens=120)
        if not raw:
            return []
        traits = []
        for line in raw.strip().splitlines():
            line = line.strip().lstrip("0123456789.-) ")
            if not line or len(line) < 8:
                continue
            if "." in line:
                dot = line.index(".")
                tname = line[:dot].strip().strip("*_")
                desc  = line[dot + 1:].strip()
                if tname and desc:
                    traits.append({"name": tname, "description": desc})
            if len(traits) >= 2:
                break
        return traits
    except Exception as e:
        logger.warning(f"[statblock-backfill] Trait gen failed for {name}: {e}")
        return []


# ── Main backfill ─────────────────────────────────────────────────────────────

def _get_npcs_needing_backfill(limit: int = 3) -> List[dict]:
    from src.db_api import raw_query
    rows = raw_query(
        "SELECT * FROM npcs WHERE status != 'deceased' AND data_json IS NOT NULL ORDER BY RAND()"
    ) or []
    result = []
    for r in rows:
        data = r.get("data_json") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                continue
        stats = data.get("stats") or {}
        if _needs_backfill(stats) and stats.get("level"):
            r["_data"] = data
            result.append(r)
        if len(result) >= limit:
            break
    return result


async def backfill_one(npc_row: dict) -> bool:
    from src.db_api import raw_execute
    data = npc_row.get("_data") or npc_row.get("data_json") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return False

    stats = data.get("stats") or {}
    if not stats.get("level"):
        return False

    level     = int(stats.get("level", 1))
    pb        = int(stats.get("proficiency_bonus", 2))
    cls_name  = stats.get("class", data.get("dnd_class", "fighter"))
    species   = data.get("species", "human")
    faction   = data.get("faction", npc_row.get("faction", "Independent"))
    equipment = data.get("equipment", [])
    save_profs = stats.get("save_proficiencies", [])

    # Deterministic fields
    stats["speed"]     = _build_speed(species)
    stats["skills"]    = _build_skills(cls_name, stats, pb)
    stats["senses"]    = _build_senses(species, stats, stats["skills"])
    stats["languages"] = _build_languages(species, faction)
    stats["saves"]     = _build_saves(stats, save_profs, pb)
    cr = _LEVEL_CR.get(level, "1")
    stats["cr"]  = cr
    stats["xp"]  = _CR_XP.get(cr, 200)
    actions = _build_actions(equipment, stats, pb, level, cls_name)
    if actions:
        stats["actions"] = actions

    # Prefer real columns for fields used in trait generation
    for _col in ("motivation", "role", "oracle_notes"):
        if npc_row.get(_col) and not data.get(_col):
            data[_col] = npc_row[_col]

    # Traits via Kimi
    traits = await _generate_traits(data)
    if traits:
        stats["traits"] = traits

    data["stats"] = stats
    name = npc_row.get("name") or data.get("name", "")

    try:
        raw_execute(
            "UPDATE npcs SET data_json = %s WHERE name = %s",
            (json.dumps(data, ensure_ascii=False), name),
        )
        logger.info(
            f"[statblock-backfill] {name}: speed={stats['speed']}, "
            f"{len(stats['skills'])} skills, {len(traits)} traits, {len(actions)} actions"
        )
        return True
    except Exception as e:
        logger.warning(f"[statblock-backfill] DB save failed for {name}: {e}")
        return False


async def run_statblock_backfill(n: int = 2) -> int:
    """Fill stat block for up to n NPCs. Returns count filled."""
    try:
        rows = _get_npcs_needing_backfill(limit=n)
    except Exception as e:
        logger.warning(f"[statblock-backfill] Load failed: {e}")
        return 0

    filled = 0
    for row in rows:
        try:
            from src.resource_cop import wait_for_ollama_turn
            decision = await wait_for_ollama_turn(
                "npc_statblock_backfill", track="quick", max_wait_seconds=600
            )
            if not decision.run_now:
                logger.info(f"[statblock-backfill] Ollama still busy after 10min — skipping {row.get('name')}")
                continue
        except Exception:
            pass  # cop unavailable — proceed anyway

        try:
            if await backfill_one(row):
                filled += 1
        except Exception as e:
            logger.warning(f"[statblock-backfill] Error for {row.get('name')}: {e}")
    return filled
