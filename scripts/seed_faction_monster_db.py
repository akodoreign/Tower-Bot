"""
seed_faction_monster_db.py - Seed generic faction role monsters.

These are reusable humanoid stat blocks for mission pipelines that need
ordinary faction troops without asking an LLM to invent combatants during
module generation.

Run from project root:
    python scripts/seed_faction_monster_db.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from scripts.seed_monster_db import CREATE_TABLE, INSERT_SQL
from src.db_api import raw_execute, raw_query


SOURCE = "faction_generic"


def mod(score: int) -> int:
    return (score - 10) // 2


def _role(
    name: str,
    cr: str,
    ac: int,
    hp: int,
    stats: tuple[int, int, int, int, int, int],
    role_note: str,
    actions: str,
    traits: str = "",
    bonus_actions: str = "",
    reactions: str = "",
    saves: dict | None = None,
    sd: str = "",
) -> dict:
    s, d, co, i, wi, ch = stats
    return {
        "name": f"Faction {name}",
        "cr": cr,
        "creature_type": "humanoid",
        "size": "M",
        "ac": ac,
        "hp": hp,
        "hp_die": "8",
        "hp_die_count": max(2, round(hp / max(1, 4.5 + mod(co)))),
        "stat_str": s,
        "stat_dex": d,
        "stat_con": co,
        "stat_int": i,
        "stat_wis": wi,
        "stat_cha": ch,
        "passive_perc": 10 + mod(wi),
        "languages": "Common plus one faction language or cant",
        "speed": "30 ft.",
        "actions": actions,
        "traits": traits,
        "reactions": reactions,
        "bonus_actions": bonus_actions,
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "saves_json": json.dumps(saves or {}),
        "notes": (
            f"Generic faction role: {role_note} Re-skin clothing, symbol, damage flavor, "
            "and doctrine to match the active faction. Useful aliases include gang member, "
            "guild agent, cult cell, house guard, syndicate crew, and temple retainer."
        ),
        "sd_appearance": sd or f"fantasy faction {name.lower()}, campaign uniform, distinctive insignia, D&D humanoid enemy",
        "source": SOURCE,
        "is_void": 0,
        "base_name": None,
    }


MONSTERS: list[dict] = [
    _role(
        "Thug", "1", 12, 26, (15, 11, 14, 9, 10, 10),
        "Cheap muscle, dockside tough, or desperate street-level blade.",
        "Multiattack. Two Club or Knife attacks.\n\nClub. Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 5 (1d6+2) bludgeoning damage.\n\nKnife. Melee or Ranged Weapon Attack: +4 to hit, reach 5 ft. or range 20/60 ft., one target. Hit: 4 (1d4+2) piercing damage.",
        "Pack Pressure. The thug has advantage on melee attacks while an allied faction creature is within 5 feet of the target.",
    ),
    _role(
        "Scout", "1", 14, 22, (10, 16, 12, 11, 14, 10),
        "Lookout, tail, messenger, or perimeter runner.",
        "Shortsword. Melee Weapon Attack: +5 to hit, reach 5 ft., one target. Hit: 6 (1d6+3) piercing damage.\n\nShortbow. Ranged Weapon Attack: +5 to hit, range 80/320 ft., one target. Hit: 6 (1d6+3) piercing damage.",
        "Skirmisher. The scout can move through an ally's space and ignores nonmagical difficult terrain in urban streets or ruins.",
        bonus_actions="Slip Away. The scout takes the Disengage or Hide action.",
        saves={"dex": 5},
    ),
    _role(
        "Archer", "2", 14, 33, (11, 17, 12, 11, 13, 10),
        "Rooftop shooter, alley overwatch, or disciplined house bow.",
        "Multiattack. Two Longbow attacks.\n\nLongbow. Ranged Weapon Attack: +5 to hit, range 150/600 ft., one target. Hit: 7 (1d8+3) piercing damage.\n\nKnife. Melee Weapon Attack: +5 to hit, reach 5 ft., one target. Hit: 5 (1d4+3) piercing damage.",
        "Marked Target. Once per turn, the archer deals 3 (1d6) extra damage to a creature marked by an allied lieutenant, captain, or priest.",
    ),
    _role(
        "Bruiser", "2", 13, 45, (18, 10, 16, 8, 11, 10),
        "Door breaker, bodyguard, pit fighter, or intimidation specialist.",
        "Multiattack. Two Heavy Fist attacks.\n\nHeavy Fist. Melee Weapon Attack: +6 to hit, reach 5 ft., one target. Hit: 8 (1d8+4) bludgeoning damage.\n\nShove Through. One creature within 5 feet must succeed on a DC 14 Strength save or be pushed 10 feet and knocked prone.",
        "Hold the Line. Opportunity attacks made by the bruiser reduce the target's speed to 0 until the end of the turn.",
        saves={"str": 6, "con": 5},
    ),
    _role(
        "Enforcer", "3", 16, 58, (18, 12, 15, 10, 12, 12),
        "Reliable trained muscle for claimed territory, prisoner handling, and debt collection.",
        "Multiattack. Two Mace or Crossbow attacks.\n\nMace. Melee Weapon Attack: +6 to hit, reach 5 ft., one target. Hit: 8 (1d8+4) bludgeoning damage.\n\nHeavy Crossbow. Ranged Weapon Attack: +4 to hit, range 100/400 ft., one target. Hit: 7 (1d10+2) piercing damage.",
        "Tactical Pairing. If the enforcer hits a creature that is adjacent to one of the enforcer's allies, the target has disadvantage on its next attack before the end of its next turn.",
        reactions="Interpose. When an allied faction creature within 5 feet is hit, the enforcer can take half the damage instead.",
        saves={"str": 6, "con": 4},
    ),
    _role(
        "Priest", "3", 13, 44, (10, 12, 13, 12, 17, 15),
        "Faction preacher, shrine minder, cult celebrant, battlefield medic, or oath speaker.",
        "Sacred Brand. Ranged Spell Attack: +5 to hit, range 60 ft., one target. Hit: 13 (3d8) radiant or necrotic damage.\n\nCensure (Recharge 5-6). Each enemy in a 15-foot cone must make a DC 13 Wisdom save, taking 18 (4d8) radiant or necrotic damage on a failure, or half on a success.",
        "Faction Rite. Allied faction creatures within 10 feet add 1d4 to saving throws against being charmed or frightened.",
        bonus_actions="Battle Prayer. One allied creature within 30 feet gains 9 (2d8) temporary hit points.",
        saves={"wis": 5, "cha": 4},
    ),
    _role(
        "Saboteur", "4", 15, 52, (10, 17, 14, 15, 12, 11),
        "Bomb maker, lock breaker, arsonist, trap setter, or industrial vandal.",
        "Multiattack. Two Dagger attacks or one Dagger and one Alchemical Charge.\n\nDagger. Melee or Ranged Weapon Attack: +5 to hit, reach 5 ft. or range 20/60 ft., one target. Hit: 6 (1d4+4) piercing damage.\n\nAlchemical Charge. Ranged Weapon Attack: +5 to hit, range 30/90 ft., one point. Hit or miss, creatures within 5 feet of that point make a DC 13 Dexterity save or take 14 (4d6) fire or acid damage.",
        "Trap Sense. Advantage on checks and saves involving traps, locks, explosives, and unstable machinery.",
        bonus_actions="Smoke Drop. A 10-foot-radius smoke cloud appears within 5 feet and lasts until the start of the saboteur's next turn.",
        saves={"dex": 5, "int": 4},
    ),
    _role(
        "Zealot", "4", 15, 67, (16, 13, 16, 9, 14, 14),
        "Fanatic shock troop for religious, void, revolutionary, or revenge-driven factions.",
        "Multiattack. Two Fervor Blade attacks.\n\nFervor Blade. Melee Weapon Attack: +5 to hit, reach 5 ft., one target. Hit: 9 (1d10+4) slashing plus 4 (1d8) radiant or necrotic damage.\n\nMartyr's Cry (1/Day). Enemies within 10 feet make a DC 13 Wisdom save or are frightened until the end of the zealot's next turn.",
        "Refuse Death (1/Day). If damage would reduce the zealot to 0 hit points, it drops to 1 hit point instead.",
        saves={"wis": 4, "cha": 4},
    ),
    _role(
        "Mage", "5", 12, 49, (9, 14, 13, 18, 13, 14),
        "Faction arcanist, ward breaker, ritual assistant, or battlefield controller.",
        "Arcane Burst. Ranged Spell Attack: +7 to hit, range 120 ft., one target. Hit: 18 (4d8) force damage.\n\nPattern Lock (Recharge 5-6). Creatures of the mage's choice in a 20-foot cube within 90 feet make a DC 15 Intelligence save or are restrained by glowing sigils until the end of the mage's next turn.",
        "Ritual Countermeasures. The mage has advantage on checks to identify, disable, or hijack magical wards.",
        bonus_actions="Ward Step. The mage teleports up to 30 feet to an unoccupied space it can see.",
        saves={"int": 7, "wis": 4},
    ),
    _role(
        "Lieutenant", "5", 16, 82, (16, 14, 15, 14, 13, 16),
        "Cell commander, watch sergeant, gang second, or tactical officer.",
        "Multiattack. Three Officer Blade attacks.\n\nOfficer Blade. Melee Weapon Attack: +6 to hit, reach 5 ft., one target. Hit: 8 (1d8+4) slashing damage.\n\nCommanding Shot. Ranged Weapon Attack: +5 to hit, range 80/320 ft., one target. Hit: 8 (1d10+3) piercing damage, and one allied faction creature can move up to half its speed.",
        "Command Aura. Allied faction creatures within 20 feet add 2 to damage rolls and Wisdom saves.",
        bonus_actions="Mark Priority. One enemy the lieutenant can see is marked until the start of the lieutenant's next turn. The first ally to hit it deals 7 (2d6) extra damage.",
        reactions="Correct the Line. When an ally within 30 feet misses, the lieutenant grants +1d4 to the roll, possibly turning it into a hit.",
        saves={"str": 6, "cha": 6},
    ),
    _role(
        "Shieldbearer", "3", 18, 64, (17, 10, 16, 10, 12, 11),
        "Portable cover, hallway blocker, riot guard, or oath-sworn protector.",
        "Shield Bash. Melee Weapon Attack: +5 to hit, reach 5 ft., one target. Hit: 7 (1d8+3) bludgeoning damage, and the target must succeed on a DC 13 Strength save or be pushed 5 feet.\n\nSpear. Melee or Ranged Weapon Attack: +5 to hit, reach 5 ft. or range 20/60 ft., one target. Hit: 6 (1d6+3) piercing damage.",
        "Moving Wall. Allied faction creatures within 5 feet of the shieldbearer gain half cover against ranged attacks.",
        reactions="Shield Catch. When an adjacent ally is hit by an attack, the shieldbearer adds 2 to that ally's AC against the triggering attack.",
        saves={"str": 5, "con": 5},
    ),
    _role(
        "Handler", "4", 14, 59, (12, 15, 14, 13, 16, 12),
        "Controls beasts, constructs, hired muscle, prisoners, or unstable faction assets.",
        "Hooked Staff. Melee Weapon Attack: +5 to hit, reach 10 ft., one target. Hit: 8 (1d10+3) bludgeoning damage, and the target cannot take reactions until the start of its next turn.\n\nCommand Asset. One allied beast, construct, monstrosity, or faction bruiser within 60 feet uses its reaction to move up to half its speed and make one attack.",
        "Read the Leash. The handler has advantage on Wisdom checks to predict animal, construct, or prisoner behavior.",
        bonus_actions="Drive Forward. One allied creature within 30 feet gains 10 temporary hit points and advantage on its next attack before the end of its turn.",
        saves={"wis": 5},
    ),
    _role(
        "Alchemist", "4", 13, 48, (9, 15, 14, 17, 12, 10),
        "Potion maker, gas specialist, field medic, or industrial hazard expert.",
        "Acid Flask. Ranged Weapon Attack: +5 to hit, range 30/90 ft., one target. Hit: 14 (4d6) acid damage.\n\nVolatile Mix (Recharge 5-6). A 10-foot-radius burst within 60 feet forces a DC 14 Dexterity save. On a failure, a creature takes 21 (6d6) fire, acid, or poison damage; on a success, half damage.",
        "Field Mixtures. At the start of combat, choose fire, acid, or poison. The alchemist's damage features use that type for the encounter.",
        bonus_actions="Emergency Draught. One allied creature within 5 feet regains 11 (2d8+2) hit points.",
        saves={"int": 5},
    ),
    _role(
        "Duelist", "5", 17, 76, (12, 19, 14, 13, 13, 16),
        "Faction blade, honor killer, bodyguard, or flashy elite combatant.",
        "Multiattack. Three Rapier attacks.\n\nRapier. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. Hit: 8 (1d8+4) piercing damage.\n\nDisarming Flourish (Recharge 5-6). One creature hit by the duelist this turn must succeed on a DC 15 Dexterity save or drop one held item of the duelist's choice.",
        "One-on-One. The duelist gains +2 AC while only one enemy is within 5 feet.",
        reactions="Parry. The duelist adds 3 to its AC against one melee attack that would hit it.",
        saves={"dex": 7, "cha": 6},
    ),
    _role(
        "Quartermaster", "6", 16, 91, (14, 14, 16, 17, 14, 15),
        "Logistics boss, paymaster, corrupt supply officer, or faction resource node.",
        "Multiattack. Two Reinforced Cane or Hand Crossbow attacks.\n\nReinforced Cane. Melee Weapon Attack: +5 to hit, reach 5 ft., one target. Hit: 7 (1d8+3) bludgeoning damage.\n\nHand Crossbow. Ranged Weapon Attack: +5 to hit, range 30/120 ft., one target. Hit: 6 (1d6+3) piercing damage plus 7 (2d6) poison, fire, or lightning damage.",
        "Prepared Supplies. The first time each allied faction creature within 30 feet takes damage, it gains resistance to that damage type until the end of its next turn.",
        bonus_actions="Issue Kit. One allied creature within 30 feet either regains 14 (4d6) hit points, reloads a special weapon, or removes one of the poisoned, blinded, or restrained conditions.",
        saves={"int": 6, "wis": 5},
    ),
    _role(
        "Assassin", "6", 15, 78, (11, 20, 14, 14, 14, 12),
        "Professional killer, quiet knife, poisoner, or faction problem-solver.",
        "Multiattack. Two Venom Blade attacks.\n\nVenom Blade. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. Hit: 8 (1d6+5) piercing plus 14 (4d6) poison damage.\n\nDead Drop Bolt. Ranged Weapon Attack: +8 to hit, range 80/320 ft., one target. Hit: 9 (1d8+5) piercing plus 10 (3d6) poison damage.",
        "Opening Kill. During the first round of combat, the assassin has advantage on attack rolls against any creature that has not taken a turn.",
        bonus_actions="Vanish. The assassin takes the Hide action and can move up to half its speed.",
        saves={"dex": 8, "int": 5},
    ),
    _role(
        "Captain", "7", 18, 112, (18, 14, 16, 14, 14, 18),
        "Named field leader suitable as the face of a mission encounter.",
        "Multiattack. Three Captain's Weapon attacks.\n\nCaptain's Weapon. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. Hit: 10 (1d10+5) slashing damage.\n\nRally Volley (Recharge 5-6). Up to three allied faction creatures within 60 feet can each make one weapon attack as a reaction.",
        "Battle Plan. At initiative count 20, the captain chooses advance, hold, or scatter. Allied faction creatures gain +10 speed, +2 AC, or the Disengage action respectively until the next initiative count 20.",
        reactions="No, You Don't. When an enemy within 5 feet hits the captain or an ally, the captain makes one weapon attack against that enemy.",
        saves={"str": 7, "con": 6, "cha": 7},
    ),
    _role(
        "Champion", "8", 18, 136, (20, 14, 18, 12, 14, 16),
        "Elite duelist, faction hero, executioner, or personal guard for important NPCs.",
        "Multiattack. Three Champion Strike attacks.\n\nChampion Strike. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. Hit: 12 (1d12+6) slashing plus 4 (1d8) damage matching the faction theme.\n\nChallenge the Strongest (Recharge 5-6). One creature within 60 feet must make a DC 15 Wisdom save or have disadvantage on attacks against creatures other than the champion until the end of its next turn.",
        "Legendary Poise. The champion has advantage on saves against being charmed, frightened, knocked prone, or stunned.",
        bonus_actions="Press. The champion moves up to 15 feet and makes one Champion Strike with disadvantage.",
        saves={"str": 8, "con": 7, "wis": 5},
    ),
]


def insert_monster(m: dict) -> bool:
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

    existing = {r["name"] for r in (raw_query("SELECT name FROM monsters") or [])}
    ok = skip = fail = 0
    for m in MONSTERS:
        if m["name"] in existing:
            skip += 1
            continue
        if insert_monster(m):
            print(f"  + {m['name']} (CR {m['cr']})")
            ok += 1
        else:
            fail += 1

    rows = raw_query(
        "SELECT cr, COUNT(*) AS n FROM monsters WHERE source=%s GROUP BY cr ORDER BY cr+0",
        (SOURCE,),
    ) or []
    print(f"\nDone. Inserted {ok}, skipped {skip}, failed {fail}.")
    print("Faction generic monsters by CR:")
    for row in rows:
        print(f"  CR {row['cr']}: {row['n']}")


if __name__ == "__main__":
    main()
