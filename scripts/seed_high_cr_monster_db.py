"""
seed_high_cr_monster_db.py - Seed high-CR campaign monsters.

Adds original Undercity / campaign monsters from CR 8 through CR 25.
For every CR tier, creates:
  - 10 regular monsters
  - 5 void-corrupted variants of the first five regular monsters

This script uses the same `monsters` table created by scripts/seed_monster_db.py.
It is safe to rerun: inserts are skipped when the monster name already exists.

Mimir note:
  The roster is built in the same shape needed by Mimir/DDB pipelines, but it
  does not copy catalog statblocks. If Mimir MCP is available later, these rows
  can be cross-linked with DDB/Mimir IDs through ddb_url / ddb_edit_url or a
  future mimir_id column.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.db_api import raw_execute, raw_query
from scripts.seed_monster_db import CREATE_TABLE, INSERT_SQL


SOURCE = "undercity_high_cr"


@dataclass(frozen=True)
class Archetype:
    key: str
    title: str
    creature_type: str
    size: str
    primary: str
    secondary: str
    speed: str
    languages: str
    role: str
    theme: str
    attack: str
    damage_type: str
    save_ability: str


ARCHETYPES: list[Archetype] = [
    Archetype("rift", "Rift Colossus", "aberration", "H", "str", "con", "40 ft.", "Deep Speech, telepathy 120 ft.", "reality bruiser", "rift gravity and torn space", "Rift Maul", "force", "con"),
    Archetype("engine", "War Engine", "construct", "H", "str", "con", "30 ft.", "understands Common but cannot speak", "siege construct", "industrial wards and pressure cores", "Engine Fist", "bludgeoning", "dex"),
    Archetype("wyrm", "Dome Wyrm", "dragon", "H", "str", "cha", "40 ft., fly 80 ft.", "Draconic, Common", "aerial artillery", "false-sky lightning and corrosive breath", "Wyrm Bite", "lightning", "dex"),
    Archetype("seraph", "Tower Seraph", "celestial", "L", "cha", "wis", "30 ft., fly 60 ft.", "Celestial, Common", "radiant commander", "judgment light and oath law", "Radiant Brand", "radiant", "wis"),
    Archetype("lich", "Archive Lich", "undead", "M", "int", "cha", "30 ft., fly 40 ft. (hover)", "Common, Draconic, Infernal", "spell tyrant", "memory theft and forbidden records", "Mnemonic Lance", "psychic", "int"),
    Archetype("hydra", "Sewer Hydra", "monstrosity", "H", "str", "con", "40 ft., swim 40 ft.", "", "multi-head predator", "toxic water and regeneration", "Hydra Bite", "piercing", "con"),
    Archetype("titan", "Foundry Titan", "giant", "H", "str", "con", "40 ft.", "Giant, Common", "melee titan", "molten iron and wrecking strength", "Molten Hammer", "fire", "str"),
    Archetype("oracle", "Obsidian Oracle", "fiend", "M", "cha", "dex", "30 ft., fly 60 ft. (hover)", "Common, Infernal, telepathy 120 ft.", "control caster", "contracts, fear, and shadow prophecy", "Contract Lash", "necrotic", "cha"),
    Archetype("fey", "Neon Archfey", "fey", "M", "cha", "dex", "40 ft.", "Common, Sylvan", "trickster controller", "glamour, names, and impossible bargains", "Glamour Blade", "psychic", "wis"),
    Archetype("primordial", "Ash Primordial", "elemental", "H", "con", "str", "50 ft., burrow 30 ft.", "Primordial", "elemental disaster", "ash storms and living magma", "Ashen Slam", "fire", "dex"),
]

TIER_NAMES = {
    8: "Night",
    9: "Iron",
    10: "Glass",
    11: "Cinder",
    12: "Veiled",
    13: "Grave",
    14: "Storm",
    15: "Dread",
    16: "Crown",
    17: "Abyssal",
    18: "Eclipse",
    19: "Cathedral",
    20: "Mythic",
    21: "Worldscar",
    22: "Doom",
    23: "Elder",
    24: "Apocalypse",
    25: "Last Gate",
}


def mod(score: int) -> int:
    return (score - 10) // 2


def prof_for_cr(cr: int) -> int:
    if cr >= 25:
        return 8
    if cr >= 21:
        return 7
    if cr >= 17:
        return 6
    if cr >= 13:
        return 5
    return 4


def die_for_size(size: str) -> str:
    return {"M": "8", "L": "10", "H": "12", "G": "20"}.get(size, "10")


def ability_block(cr: int, arch: Archetype, void: bool = False) -> dict[str, int]:
    base = {
        "str": 14 + cr // 3,
        "dex": 12 + cr // 5,
        "con": 14 + cr // 3,
        "int": 10 + cr // 6,
        "wis": 12 + cr // 5,
        "cha": 11 + cr // 5,
    }
    type_boosts = {
        "aberration": ("wis", "int"),
        "construct": ("str", "con"),
        "dragon": ("str", "cha"),
        "celestial": ("cha", "wis"),
        "undead": ("int", "cha"),
        "monstrosity": ("str", "con"),
        "giant": ("str", "con"),
        "fiend": ("cha", "dex"),
        "fey": ("cha", "dex"),
        "elemental": ("con", "str"),
    }
    for key in type_boosts.get(arch.creature_type, (arch.primary, arch.secondary)):
        base[key] += 3
    base[arch.primary] += 3
    base[arch.secondary] += 2
    if void:
        base["con"] += 2
        base["wis"] += 1
        base["cha"] += 1
    return {k: min(30, v) for k, v in base.items()}


def hp_for(cr: int, arch: Archetype, abilities: dict[str, int], void: bool = False) -> tuple[int, str, int]:
    size_bonus = {"M": 0, "L": 18, "H": 42, "G": 90}.get(arch.size, 18)
    role_bonus = {
        "siege construct": 45,
        "melee titan": 55,
        "elemental disaster": 40,
        "spell tyrant": -20,
        "trickster controller": -30,
        "control caster": -20,
    }.get(arch.role, 0)
    hp = 82 + cr * 19 + size_bonus + role_bonus + mod(abilities["con"]) * 8
    if void:
        hp = int(hp * 1.18) + 20
    die = die_for_size(arch.size)
    die_avg = {"8": 4.5, "10": 5.5, "12": 6.5, "20": 10.5}[die]
    die_count = max(8, round(hp / max(1, die_avg + mod(abilities["con"]))))
    return hp, die, die_count


def ac_for(cr: int, arch: Archetype, void: bool = False) -> int:
    role_bonus = {
        "siege construct": 2,
        "melee titan": 1,
        "aerial artillery": 1,
        "spell tyrant": -1,
        "trickster controller": -1,
    }.get(arch.role, 0)
    return min(24, 15 + cr // 5 + role_bonus + (1 if void else 0))


def attack_bonus(cr: int, abilities: dict[str, int], arch: Archetype, void: bool = False) -> int:
    return prof_for_cr(cr) + mod(abilities[arch.primary]) + 2 + (1 if void else 0)


def save_dc(cr: int, abilities: dict[str, int], arch: Archetype, void: bool = False) -> int:
    return 8 + prof_for_cr(cr) + mod(abilities[arch.secondary]) + (1 if void else 0)


def damage_expr(cr: int, arch: Archetype, void: bool = False) -> tuple[str, int]:
    dice_count = max(2, cr // 4 + (1 if void else 0))
    die = "10" if arch.size in {"H", "G"} else "8"
    flat = mod(ability_block(cr, arch, void)[arch.primary]) + cr // 3
    avg = int(dice_count * (int(die) + 1) / 2 + flat)
    return f"{avg} ({dice_count}d{die}+{flat})", avg


def traits_for(cr: int, arch: Archetype, abilities: dict[str, int], void: bool = False) -> str:
    pb = prof_for_cr(cr)
    init = mod(abilities["dex"]) + pb // 2
    parts = [
        f"High-CR Threat. Initiative +{init}; proficiency bonus +{pb}.",
        f"Role: {arch.role.title()}. Built for {arch.theme}.",
    ]
    if arch.size in {"H", "G"}:
        parts.append("Siege Body. Deals double damage to objects and structures.")
    if arch.creature_type in {"construct", "celestial", "fiend", "undead", "dragon", "aberration"}:
        parts.append("Magic Resistance. Advantage on saving throws against spells and magical effects.")
    if cr >= 11:
        uses = 3 if cr >= 17 else 2
        parts.append(f"Legendary Resistance ({uses}/Day). If it fails a saving throw, it can choose to succeed instead.")
    if cr >= 17:
        parts.append("Mythic Pressure. When reduced below half HP for the first time, it immediately ends one condition on itself and recharges its signature power.")
    if void:
        parts.extend([
            "Void Form. Resistant to bludgeoning, piercing, and slashing damage from nonmagical attacks, plus necrotic and psychic damage.",
            "Void Aura. Creatures that start their turn within 15 feet must succeed on a DC "
            f"{save_dc(cr, abilities, arch, True)} Wisdom save or have disadvantage on the next save they make before the end of their next turn.",
            "Unstable Existence. Healing within 15 feet of the monster restores only half as many hit points unless the healer succeeds on a spellcasting ability check against the monster's save DC.",
        ])
    return "\n\n".join(parts)


def actions_for(cr: int, arch: Archetype, abilities: dict[str, int], void: bool = False) -> str:
    atk = attack_bonus(cr, abilities, arch, void)
    dc = save_dc(cr, abilities, arch, void)
    dmg, _avg = damage_expr(cr, arch, void)
    extra = f" plus {max(7, cr)} (2d6+{max(0, cr - 7)}) necrotic damage" if void else ""
    multi = "three" if cr >= 13 else "two"
    action = [
        f"Multiattack. The monster makes {multi} {arch.attack} attacks.",
        f"{arch.attack}. Melee or Ranged Spell Attack: +{atk} to hit, reach 10 ft. or range 90 ft., one target. Hit: {dmg} {arch.damage_type} damage{extra}.",
        f"Signature Power (Recharge 5-6). Each enemy in a 30-foot cone or 20-foot-radius sphere must make a DC {dc} {arch.save_ability.upper()} save. On a failure, the target takes {max(28, cr * 5)} ({max(6, cr // 2)}d10) {arch.damage_type} damage and suffers the monster's role pressure; on a success, half damage and no pressure.",
    ]
    if void:
        action.append(
            f"Reality Tear (1/Day). The monster opens a void wound within 120 feet. Creatures within 20 feet make a DC {dc} Constitution save or take {max(35, cr * 6)} necrotic damage and teleport 30 feet to a space the monster can see."
        )
    return "\n\n".join(action)


def bonus_actions_for(cr: int, arch: Archetype, void: bool = False) -> str:
    if arch.role in {"trickster controller", "control caster", "spell tyrant"}:
        return "Slip Position. Teleports up to 30 feet to a space it can see after casting a spell or hitting with an attack."
    if arch.role in {"melee titan", "siege construct", "reality bruiser"}:
        return "Crushing Advance. Moves up to half its speed. This movement can pass through enemy spaces, but each creature whose space it enters must succeed on a Strength save or fall prone."
    if void:
        return "Void Step. Teleports up to 30 feet and leaves dim purple afterimages until the start of its next turn."
    return ""


def reactions_for(cr: int, arch: Archetype, void: bool = False) -> str:
    dc = 8 + prof_for_cr(cr) + cr // 4
    if arch.role in {"radiant commander", "control caster"}:
        return f"Commanding Rebuke. When a creature within 60 feet hits the monster or one of its allies, the attacker must succeed on a DC {dc} Wisdom save or take psychic or radiant backlash damage."
    if arch.role in {"melee titan", "siege construct"}:
        return "Brace Impact. When hit by an attack, reduces the damage by 15 and may shove the attacker 10 feet if it is within reach."
    if void:
        return "Void Recoil. When hit, the attacker takes necrotic damage equal to the monster's CR unless it succeeds on a Constitution save."
    return "Instinctive Guard. Adds +3 AC against one attack that would hit it."


def legendary_for(cr: int, arch: Archetype, void: bool = False) -> str:
    if cr < 11:
        return ""
    points = 3 if cr < 21 else 4
    base = [
        f"Legendary Actions ({points}/Round). The monster can take legendary actions at the end of another creature's turn.",
        "Move. Moves up to half its speed without provoking opportunity attacks.",
        f"Strike. Makes one {arch.attack} attack.",
        "Pressure Pulse (Costs 2 Actions). Forces one creature it can see within 60 feet to repeat the saving throw against its Signature Power's secondary effect.",
    ]
    if void:
        base.append("Void Fold (Costs 2 Actions). Teleports up to 60 feet and briefly becomes insubstantial.")
    return "\n".join(base)


def lair_for(cr: int, arch: Archetype, void: bool = False) -> str:
    if cr < 17:
        return ""
    lines = [
        "Lair Actions. On initiative count 20, losing ties, one effect occurs:",
        f"- {arch.theme.title()} surge through the room; one area becomes difficult terrain and lightly obscured.",
        "- A hostile creature must make a saving throw against the monster's save DC or lose reactions until next round.",
        "- A terrain feature becomes dangerous, dealing damage equal to the monster's CR to creatures that cross it carelessly.",
    ]
    if void:
        lines.append("- Void static suppresses healing and teleportation until initiative count 20 next round.")
    return "\n".join(lines)


def saves_for(cr: int, arch: Archetype, abilities: dict[str, int], void: bool = False) -> dict[str, int]:
    pb = prof_for_cr(cr)
    keys = {arch.primary, arch.secondary, arch.save_ability}
    if void:
        keys.update({"con", "wis"})
    return {k: mod(abilities[k]) + pb for k in sorted(keys)}


def note_for(cr: int, arch: Archetype, tier: str, void: bool = False) -> str:
    base = f"{tier} {arch.title}. Original high-CR campaign monster for mission generation. CR {cr}. Designed as a {arch.role} using {arch.theme}."
    if void:
        return base + f" Void-corrupted version of UC {tier} {arch.title}; adds void aura, reality tear, nonmagical resistance, and healing suppression."
    return base + " Use as a DB-backed encounter seed instead of asking the LLM to invent a monster during mission generation."


def sd_for(arch: Archetype, tier: str, void: bool = False) -> str:
    prefix = "void-corrupted " if void else ""
    return (
        f"{prefix}{tier.lower()} {arch.title.lower()}, {arch.creature_type}, {arch.theme}, "
        "dark fantasy D&D monster concept art, dramatic lighting, full creature body, no text"
    )


def monster_row(cr: int, arch: Archetype, void: bool = False) -> dict[str, Any]:
    tier = TIER_NAMES[cr]
    base_name = f"UC {tier} {arch.title}"
    name = f"UC Void {tier} {arch.title}" if void else base_name
    abilities = ability_block(cr, arch, void)
    hp, die, die_count = hp_for(cr, arch, abilities, void)
    pp = 10 + mod(abilities["wis"]) + (prof_for_cr(cr) if arch.key in {"rift", "hydra", "wyrm", "oracle", "fey"} else 0)
    return {
        "name": name,
        "cr": str(cr),
        "creature_type": "aberration" if void and arch.creature_type not in {"construct", "undead"} else arch.creature_type,
        "size": arch.size,
        "ac": ac_for(cr, arch, void),
        "hp": hp,
        "hp_die": die,
        "hp_die_count": die_count,
        "stat_str": abilities["str"],
        "stat_dex": abilities["dex"],
        "stat_con": abilities["con"],
        "stat_int": abilities["int"],
        "stat_wis": abilities["wis"],
        "stat_cha": abilities["cha"],
        "passive_perc": pp,
        "languages": arch.languages if not void else f"{arch.languages}, Void cant",
        "speed": arch.speed,
        "actions": actions_for(cr, arch, abilities, void),
        "traits": traits_for(cr, arch, abilities, void),
        "reactions": reactions_for(cr, arch, void),
        "bonus_actions": bonus_actions_for(cr, arch, void),
        "legendary_actions": legendary_for(cr, arch, void),
        "mythic_actions": "Mythic Action. Once after entering mythic pressure, immediately uses Signature Power if recharged." if cr >= 21 else "",
        "lair_actions": lair_for(cr, arch, void),
        "saves_json": json.dumps(saves_for(cr, arch, abilities, void)),
        "notes": note_for(cr, arch, tier, void),
        "sd_appearance": sd_for(arch, tier, void),
        "source": SOURCE,
        "is_void": 1 if void else 0,
        "base_name": base_name if void else None,
    }


def build_monsters() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cr in range(8, 26):
        for arch in ARCHETYPES:
            rows.append(monster_row(cr, arch, void=False))
        for arch in ARCHETYPES[:5]:
            rows.append(monster_row(cr, arch, void=True))
    return rows


def insert_monster(m: dict[str, Any]) -> bool:
    try:
        raw_execute(INSERT_SQL, (
            m["name"], m["cr"], m["creature_type"], m["size"],
            m["ac"], m["hp"], m["hp_die"], m["hp_die_count"],
            m["stat_str"], m["stat_dex"], m["stat_con"], m["stat_int"],
            m["stat_wis"], m["stat_cha"],
            m["passive_perc"], m["languages"], m["speed"],
            m["actions"], m["traits"], m["reactions"], m["bonus_actions"],
            m["legendary_actions"], m["mythic_actions"], m["lair_actions"],
            m["saves_json"], m["notes"], m["sd_appearance"],
            m["source"], m["is_void"], m["base_name"],
        ))
        return True
    except Exception as exc:
        print(f"  ERROR inserting {m['name']!r}: {exc}")
        return False


def main() -> None:
    print("Creating monsters table if not exists...")
    raw_execute(CREATE_TABLE)
    rows = build_monsters()
    existing = {r["name"] for r in (raw_query("SELECT name FROM monsters") or [])}
    print(f"Prepared {len(rows)} high-CR monster rows. Existing monsters: {len(existing)}")

    ok = skip = fail = 0
    for m in rows:
        if m["name"] in existing:
            skip += 1
            continue
        if insert_monster(m):
            ok += 1
            print(f"  + {m['name']} (CR {m['cr']}, {'VOID' if m['is_void'] else 'regular'})")
        else:
            fail += 1

    total = raw_query("SELECT COUNT(*) AS n FROM monsters")[0]["n"]
    print(f"\nDone. Inserted {ok}, skipped {skip}, failed {fail}. Total monster rows: {total}")
    summary = raw_query(
        "SELECT cr, is_void, COUNT(*) AS n FROM monsters "
        "WHERE source=%s GROUP BY cr, is_void ORDER BY cr+0, is_void",
        (SOURCE,),
    ) or []
    print("\nHigh-CR monsters by CR:")
    for row in summary:
        tag = "void" if row["is_void"] else "regular"
        print(f"  CR {row['cr']} {tag}: {row['n']}")


if __name__ == "__main__":
    main()
