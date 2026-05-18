"""
monster_stat_gen.py — Generate full D&D 5e stat blocks for monster DDB push.

Provides:
  _SRD_STATS   — Accurate stats for all monsters in MONSTER_TABLES / infestation pools
  build_statblock() — Returns push_monster()-compatible dict for any monster
  format_actions_for_ddb() — Format attack list into DDB textarea text

SRD monsters get accurate ability scores, HP dice, and action text.
Unknown/custom monsters get CR-formula stats derived from DMG p.274-279.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

# ── CR helpers ────────────────────────────────────────────────────────────────

def _cr_num(cr: str) -> float:
    """Convert CR string to float."""
    try:
        return float(str(cr).replace("1/8", "0.125").replace("1/4", "0.25").replace("1/2", "0.5"))
    except Exception:
        return 1.0

def _prof(cr: str) -> int:
    n = _cr_num(cr)
    if n < 5:   return 2
    if n < 9:   return 3
    if n < 13:  return 4
    if n < 17:  return 5
    return 6

def _mod(score: int) -> int:
    return (score - 10) // 2


# ── SRD Stat Table ────────────────────────────────────────────────────────────
# Fields: size, type, ac, hp, die (die type string), dice (count),
#         str, dex, con, int, wis, cha, speed, langs, actions

_SRD: Dict[str, Dict[str, Any]] = {
    "Giant Rat": dict(
        size="T", type="beast", ac=11, hp=7, die="4", dice=2,
        str_=7, dex=15, con=11, int_=2, wis=10, cha=4,
        speed="30 ft., swim 30 ft.", langs="",
        actions="**Bite.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. Hit: 4 (1d4+2) piercing damage.",
    ),
    "Skeleton": dict(
        size="M", type="undead", ac=13, hp=13, die="8", dice=2,
        str_=10, dex=14, con=15, int_=6, wis=8, cha=5,
        speed="30 ft.", langs="understands languages it knew in life but can't speak",
        actions=(
            "**Shortsword.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. Hit: 5 (1d6+2) piercing damage.\n\n"
            "**Shortbow.** *Ranged Weapon Attack:* +4 to hit, range 80/320 ft., one target. Hit: 5 (1d6+2) piercing damage."
        ),
    ),
    "Zombie": dict(
        size="M", type="undead", ac=8, hp=22, die="8", dice=3,
        str_=13, dex=6, con=16, int_=3, wis=6, cha=5,
        speed="20 ft.", langs="understands the languages it knew in life but can't speak",
        actions="**Slam.** *Melee Weapon Attack:* +3 to hit, reach 5 ft., one target. Hit: 4 (1d6+1) bludgeoning damage.",
    ),
    "Goblin": dict(
        size="S", type="humanoid", ac=15, hp=7, die="6", dice=2,
        str_=8, dex=14, con=10, int_=10, wis=8, cha=8,
        speed="30 ft.", langs="Common, Goblin",
        actions=(
            "**Scimitar.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. Hit: 5 (1d6+2) slashing damage.\n\n"
            "**Shortbow.** *Ranged Weapon Attack:* +4 to hit, range 80/320 ft., one target. Hit: 5 (1d6+2) piercing damage."
        ),
    ),
    "Kobold": dict(
        size="S", type="humanoid", ac=12, hp=5, die="6", dice=2,
        str_=7, dex=15, con=9, int_=8, wis=7, cha=8,
        speed="30 ft.", langs="Common, Draconic",
        actions="**Dagger.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. Hit: 4 (1d4+2) piercing damage.",
    ),
    "Giant Spider": dict(
        size="L", type="beast", ac=14, hp=26, die="10", dice=4,
        str_=14, dex=16, con=12, int_=2, wis=11, cha=4,
        speed="30 ft., climb 30 ft.", langs="",
        actions=(
            "**Bite.** *Melee Weapon Attack:* +5 to hit, reach 5 ft., one creature. Hit: 7 (1d8+3) piercing damage plus 9 (2d8) poison damage (DC 11 Con save halves poison).\n\n"
            "**Web (Recharge 5-6).** *Ranged Weapon Attack:* +5 to hit, range 30/60 ft., one creature. The target is restrained (DC 12 Str check to escape)."
        ),
    ),
    "Ghoul": dict(
        size="M", type="undead", ac=12, hp=22, die="8", dice=5,
        str_=13, dex=15, con=10, int_=7, wis=10, cha=6,
        speed="30 ft.", langs="Common",
        actions=(
            "**Bite.** *Melee Weapon Attack:* +2 to hit, reach 5 ft., one creature. Hit: 9 (2d6+2) piercing damage.\n\n"
            "**Claws.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. Hit: 7 (2d4+2) slashing damage. If the target is a creature other than an elf or undead, it must DC 10 Con save or be paralyzed for 1 minute."
        ),
    ),
    "Specter": dict(
        size="M", type="undead", ac=12, hp=22, die="8", dice=5,
        str_=1, dex=14, con=11, int_=10, wis=10, cha=11,
        speed="0 ft., fly 50 ft. (hover)", langs="understands all languages it knew in life but can't speak",
        actions="**Life Drain.** *Melee Spell Attack:* +4 to hit, reach 5 ft., one creature. Hit: 10 (3d6) necrotic damage. The target must DC 10 Con save or its HP maximum is reduced by that amount until a long rest.",
    ),
    "Bugbear": dict(
        size="M", type="humanoid", ac=16, hp=27, die="8", dice=5,
        str_=15, dex=14, con=13, int_=8, wis=11, cha=9,
        speed="30 ft.", langs="Common, Goblin",
        actions="**Morningstar.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. Hit: 11 (2d8+2) piercing damage.",
    ),
    "Hobgoblin": dict(
        size="M", type="humanoid", ac=18, hp=11, die="8", dice=2,
        str_=13, dex=12, con=12, int_=10, wis=10, cha=9,
        speed="30 ft.", langs="Common, Goblin",
        actions=(
            "**Longsword.** *Melee Weapon Attack:* +3 to hit, reach 5 ft., one target. Hit: 5 (1d8+1) slashing damage.\n\n"
            "**Longbow.** *Ranged Weapon Attack:* +3 to hit, range 150/600 ft., one target. Hit: 5 (1d8+1) piercing damage."
        ),
    ),
    "Gray Ooze": dict(
        size="M", type="ooze", ac=8, hp=22, die="8", dice=3,
        str_=12, dex=6, con=16, int_=1, wis=6, cha=2,
        speed="10 ft., climb 10 ft.", langs="",
        actions="**Pseudopod.** *Melee Weapon Attack:* +3 to hit, reach 5 ft., one target. Hit: 4 (1d6+1) bludgeoning damage plus 7 (2d6) acid damage.",
    ),
    "Ogre": dict(
        size="L", type="giant", ac=11, hp=59, die="10", dice=7,
        str_=19, dex=8, con=16, int_=5, wis=7, cha=7,
        speed="40 ft.", langs="Common, Giant",
        actions="**Greatclub.** *Melee Weapon Attack:* +6 to hit, reach 5 ft., one target. Hit: 13 (2d8+4) bludgeoning damage.",
    ),
    "Ghast": dict(
        size="M", type="undead", ac=13, hp=36, die="8", dice=8,
        str_=16, dex=17, con=10, int_=11, wis=10, cha=8,
        speed="30 ft.", langs="Common",
        actions=(
            "**Multiattack.** The ghast makes one Bite attack and one Claws attack.\n\n"
            "**Bite.** *Melee Weapon Attack:* +3 to hit, reach 5 ft., one creature. Hit: 12 (2d8+3) piercing damage.\n\n"
            "**Claws.** *Melee Weapon Attack:* +5 to hit, reach 5 ft., one target. Hit: 10 (2d6+3) slashing damage. Non-undead: DC 10 Con save or paralyzed 1 minute."
        ),
    ),
    "Mimic": dict(
        size="M", type="monstrosity", ac=12, hp=58, die="8", dice=9,
        str_=17, dex=12, con=15, int_=5, wis=13, cha=8,
        speed="15 ft.", langs="",
        actions=(
            "**Pseudopod.** *Melee Weapon Attack:* +5 to hit, reach 5 ft., one target. Hit: 7 (1d8+3) bludgeoning damage. If the mimic is in object form, the target is also grappled (DC 13 Str escape).\n\n"
            "**Bite.** *Melee Weapon Attack:* +5 to hit, reach 5 ft., one grappled creature. Hit: 7 (1d8+3) piercing damage plus 9 (2d8) acid damage."
        ),
    ),
    "Owlbear": dict(
        size="L", type="monstrosity", ac=13, hp=59, die="10", dice=7,
        str_=20, dex=12, con=17, int_=3, wis=12, cha=7,
        speed="40 ft.", langs="",
        actions=(
            "**Multiattack.** The owlbear makes two attacks: one with its beak and one with its claws.\n\n"
            "**Beak.** *Melee Weapon Attack:* +7 to hit, reach 5 ft., one creature. Hit: 10 (1d10+5) piercing damage.\n\n"
            "**Claws.** *Melee Weapon Attack:* +7 to hit, reach 5 ft., one target. Hit: 14 (2d8+5) slashing damage."
        ),
    ),
    "Minotaur": dict(
        size="L", type="monstrosity", ac=14, hp=76, die="10", dice=9,
        str_=18, dex=11, con=16, int_=6, wis=16, cha=9,
        speed="40 ft.", langs="Abyssal",
        actions=(
            "**Multiattack.** The minotaur makes two attacks: one with its greataxe and one with its gore.\n\n"
            "**Greataxe.** *Melee Weapon Attack:* +6 to hit, reach 5 ft., one target. Hit: 17 (2d12+4) slashing damage.\n\n"
            "**Gore.** *Melee Weapon Attack:* +6 to hit, reach 5 ft., one target. Hit: 13 (2d8+4) piercing damage."
        ),
    ),
    "Wight": dict(
        size="M", type="undead", ac=14, hp=45, die="8", dice=6,
        str_=15, dex=14, con=16, int_=10, wis=13, cha=15,
        speed="30 ft.", langs="the languages it knew in life",
        actions=(
            "**Multiattack.** The wight makes two longsword attacks or two longbow attacks. It can replace one attack with Life Drain.\n\n"
            "**Life Drain.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one creature. Hit: 5 (1d6+2) necrotic damage. DC 13 Con save or HP maximum reduced by the damage.\n\n"
            "**Longsword.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. Hit: 6 (1d8+2) slashing damage."
        ),
    ),
    "Phase Spider": dict(
        size="L", type="monstrosity", ac=13, hp=32, die="10", dice=5,
        str_=15, dex=15, con=12, int_=6, wis=10, cha=6,
        speed="30 ft., climb 30 ft.", langs="",
        actions="**Bite.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one creature. Hit: 7 (1d10+2) piercing damage plus 18 (4d8) poison damage (DC 11 Con save halves).",
    ),
    "Wraith": dict(
        size="M", type="undead", ac=13, hp=67, die="8", dice=9,
        str_=6, dex=16, con=16, int_=12, wis=14, cha=15,
        speed="0 ft., fly 60 ft. (hover)", langs="the languages it knew in life",
        actions=(
            "**Life Drain.** *Melee Weapon Attack:* +6 to hit, reach 5 ft., one creature. Hit: 21 (4d8+3) necrotic damage. DC 14 Con save or HP maximum reduced.\n\n"
            "**Create Specter.** The wraith creates a specter from a humanoid it has killed (max 7 specters at a time)."
        ),
    ),
    "Troll": dict(
        size="L", type="giant", ac=15, hp=84, die="10", dice=8,
        str_=18, dex=13, con=20, int_=7, wis=9, cha=7,
        speed="30 ft.", langs="Giant",
        actions=(
            "**Multiattack.** The troll makes three attacks: one bite and two claws.\n\n"
            "**Bite.** *Melee Weapon Attack:* +7 to hit, reach 5 ft., one target. Hit: 7 (1d6+4) piercing damage.\n\n"
            "**Claw.** *Melee Weapon Attack:* +7 to hit, reach 5 ft., one target. Hit: 11 (2d6+4) slashing damage.\n\n"
            "**Regeneration.** The troll regains 10 HP at the start of its turn unless it took acid or fire damage since last turn."
        ),
    ),
    "Shambling Mound": dict(
        size="L", type="plant", ac=15, hp=136, die="10", dice=16,
        str_=18, dex=8, con=16, int_=5, wis=10, cha=5,
        speed="20 ft., swim 20 ft.", langs="",
        actions=(
            "**Multiattack.** The shambling mound makes two slam attacks. If both hit a Medium or smaller target, the target is grappled (DC 14 Str escape) and the mound can engulf it.\n\n"
            "**Slam.** *Melee Weapon Attack:* +7 to hit, reach 5 ft., one target. Hit: 13 (2d8+4) bludgeoning damage."
        ),
    ),
    "Flesh Golem": dict(
        size="M", type="construct", ac=9, hp=93, die="8", dice=11,
        str_=19, dex=9, con=18, int_=6, wis=10, cha=5,
        speed="30 ft.", langs="understands the languages of its creator but can't speak",
        actions=(
            "**Multiattack.** The golem makes two slam attacks.\n\n"
            "**Slam.** *Melee Weapon Attack:* +7 to hit, reach 5 ft., one target. Hit: 13 (2d8+4) bludgeoning damage."
        ),
    ),
    "Salamander": dict(
        size="L", type="elemental", ac=15, hp=90, die="10", dice=12,
        str_=18, dex=14, con=15, int_=11, wis=10, cha=12,
        speed="30 ft.", langs="Ignan",
        actions=(
            "**Multiattack.** The salamander makes two attacks: one with its spear and one with its tail.\n\n"
            "**Spear.** *Melee or Ranged Weapon Attack:* +7 to hit, reach 5 ft. or range 20/60 ft., one target. Hit: 11 (2d6+4) piercing damage plus 3 (1d6) fire damage.\n\n"
            "**Tail.** *Melee Weapon Attack:* +7 to hit, reach 10 ft., one target. Hit: 11 (2d6+4) bludgeoning damage and the target is grappled (DC 14 Str escape)."
        ),
    ),
    "Otyugh": dict(
        size="L", type="aberration", ac=14, hp=114, die="10", dice=12,
        str_=16, dex=11, con=19, int_=6, wis=13, cha=6,
        speed="30 ft.", langs="Otyugh",
        actions=(
            "**Multiattack.** The otyugh makes three attacks: one with its bite and two with its tentacles.\n\n"
            "**Bite.** *Melee Weapon Attack:* +6 to hit, reach 5 ft., one target. Hit: 12 (2d8+3) piercing damage. DC 15 Con save or diseased.\n\n"
            "**Tentacle.** *Melee Weapon Attack:* +6 to hit, reach 10 ft., one target. Hit: 10 (2d6+3) bludgeoning damage plus 4 (1d8) piercing damage. Grappled (DC 13 Str escape)."
        ),
    ),
    "Young White Dragon": dict(
        size="L", type="dragon", ac=17, hp=133, die="10", dice=14,
        str_=18, dex=10, con=18, int_=6, wis=11, cha=12,
        speed="40 ft., burrow 20 ft., fly 80 ft., swim 40 ft.", langs="Common, Draconic",
        actions=(
            "**Multiattack.** The dragon makes three attacks: one bite and two claws.\n\n"
            "**Bite.** *Melee Weapon Attack:* +6 to hit, reach 10 ft., one target. Hit: 15 (2d10+4) piercing damage plus 4 (1d8) cold damage.\n\n"
            "**Claw.** *Melee Weapon Attack:* +6 to hit, reach 5 ft., one target. Hit: 11 (2d6+4) slashing damage.\n\n"
            "**Cold Breath (Recharge 5-6).** 30-foot cone. DC 14 Con save, 45 (10d8) cold damage on fail, half on success."
        ),
    ),
    "Medusa": dict(
        size="M", type="monstrosity", ac=15, hp=127, die="8", dice=17,
        str_=10, dex=15, con=16, int_=12, wis=13, cha=15,
        speed="30 ft.", langs="Common",
        actions=(
            "**Multiattack.** The medusa makes either three melee attacks — one with its snake hair and two with its shortsword — or two ranged attacks with its longbow.\n\n"
            "**Snake Hair.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one creature. Hit: 4 (1d4+2) piercing damage plus 14 (4d6) poison damage.\n\n"
            "**Petrifying Gaze.** If a creature starts its turn within 30 ft. and can see the medusa's eyes, DC 14 Con save or petrified."
        ),
    ),
    "Cloaker": dict(
        size="L", type="aberration", ac=14, hp=78, die="10", dice=12,
        str_=17, dex=15, con=12, int_=13, wis=12, cha=14,
        speed="10 ft., fly 40 ft.", langs="Deep Speech, Undercommon",
        actions=(
            "**Multiattack.** The cloaker makes two attacks: one with its bite and one with its tail.\n\n"
            "**Bite.** *Melee Weapon Attack:* +6 to hit, reach 5 ft., one creature. Hit: 10 (2d6+3) piercing damage.\n\n"
            "**Moan.** Each non-aberration within 60 ft.: DC 13 Wis save or frightened until end of next turn."
        ),
    ),
    "Spirit Naga": dict(
        size="L", type="monstrosity", ac=15, hp=75, die="10", dice=10,
        str_=18, dex=17, con=14, int_=16, wis=15, cha=16,
        speed="40 ft.", langs="Abyssal, Common",
        actions=(
            "**Bite.** *Melee Weapon Attack:* +7 to hit, reach 10 ft., one creature. Hit: 7 (1d6+4) piercing damage plus 13 (3d8) poison damage (DC 13 Con save halves).\n\n"
            "**Spellcasting.** The naga is a 10th-level spellcaster (spell save DC 14, +6 spell attack)."
        ),
    ),
    "Hydra": dict(
        size="H", type="monstrosity", ac=15, hp=172, die="12", dice=15,
        str_=20, dex=12, con=20, int_=2, wis=10, cha=7,
        speed="30 ft., swim 30 ft.", langs="",
        actions=(
            "**Multiattack.** The hydra makes as many bite attacks as it has heads.\n\n"
            "**Bite.** *Melee Weapon Attack:* +8 to hit, reach 10 ft., one target. Hit: 10 (1d10+5) piercing damage.\n\n"
            "**Reactive Heads.** For each head beyond one, the hydra gets an extra reaction (each for one opportunity attack)."
        ),
    ),
    "Clay Golem": dict(
        size="L", type="construct", ac=14, hp=133, die="10", dice=14,
        str_=20, dex=9, con=18, int_=3, wis=8, cha=1,
        speed="20 ft.", langs="understands the languages of its creator but can't speak",
        actions=(
            "**Multiattack.** The golem makes two slam attacks.\n\n"
            "**Slam.** *Melee Weapon Attack:* +8 to hit, reach 5 ft., one target. Hit: 16 (2d10+5) bludgeoning damage. DC 15 Str save or knocked prone.\n\n"
            "**Haste (Recharge 5-6).** Until the end of its next turn, the golem gains +2 AC, advantage on Dex saves, and an additional slam attack."
        ),
    ),
    "Stone Golem": dict(
        size="L", type="construct", ac=17, hp=178, die="10", dice=17,
        str_=22, dex=9, con=20, int_=3, wis=11, cha=1,
        speed="30 ft.", langs="understands the languages of its creator but can't speak",
        actions=(
            "**Multiattack.** The golem makes two slam attacks.\n\n"
            "**Slam.** *Melee Weapon Attack:* +10 to hit, reach 5 ft., one target. Hit: 19 (3d8+6) bludgeoning damage.\n\n"
            "**Slow (Recharge 5-6).** Each creature within 10 ft.: DC 17 Wis save or slowed (speed halved, -2 AC and Dex saves, no reactions) for 1 minute."
        ),
    ),
    "Young Red Dragon": dict(
        size="L", type="dragon", ac=18, hp=178, die="10", dice=17,
        str_=23, dex=10, con=21, int_=14, wis=11, cha=19,
        speed="40 ft., climb 40 ft., fly 80 ft.", langs="Common, Draconic",
        actions=(
            "**Multiattack.** The dragon makes three attacks: one bite and two claws.\n\n"
            "**Bite.** *Melee Weapon Attack:* +10 to hit, reach 10 ft., one target. Hit: 17 (2d10+6) piercing plus 3 (1d6) fire damage.\n\n"
            "**Claw.** *Melee Weapon Attack:* +10 to hit, reach 5 ft., one target. Hit: 13 (2d6+6) slashing damage.\n\n"
            "**Fire Breath (Recharge 5-6).** 30-foot cone. DC 17 Dex save, 56 (16d6) fire damage on fail, half on success."
        ),
    ),
    "Aboleth": dict(
        size="L", type="aberration", ac=17, hp=135, die="10", dice=18,
        str_=21, dex=9, con=15, int_=18, wis=15, cha=18,
        speed="10 ft., swim 40 ft.", langs="Deep Speech, telepathy 120 ft.",
        actions=(
            "**Multiattack.** The aboleth makes three tentacle attacks.\n\n"
            "**Tentacle.** *Melee Weapon Attack:* +9 to hit, reach 10 ft., one target. Hit: 12 (2d6+5) bludgeoning damage. DC 14 Con save or the creature's skin becomes translucent and slimy.\n\n"
            "**Enslave (3/Day).** One creature within 30 ft.: DC 14 Wis save or charmed indefinitely."
        ),
    ),
    "Beholder": dict(
        size="L", type="aberration", ac=18, hp=180, die="10", dice=19,
        str_=10, dex=14, con=18, int_=17, wis=15, cha=17,
        speed="0 ft., fly 20 ft. (hover)", langs="Deep Speech, Undercommon",
        actions=(
            "**Bite.** *Melee Weapon Attack:* +5 to hit, reach 5 ft., one target. Hit: 14 (4d6) piercing damage.\n\n"
            "**Eye Rays.** The beholder shoots three of its magical eye rays at random targets it can see within 120 ft. (roll 1d10 each)."
        ),
    ),
    "Adult Black Dragon": dict(
        size="H", type="dragon", ac=19, hp=195, die="12", dice=17,
        str_=23, dex=14, con=21, int_=14, wis=13, cha=17,
        speed="40 ft., fly 80 ft., swim 40 ft.", langs="Common, Draconic",
        actions=(
            "**Multiattack.** The dragon uses Frightful Presence then makes three attacks: one bite and two claws.\n\n"
            "**Bite.** *Melee Weapon Attack:* +11 to hit, reach 10 ft., one target. Hit: 17 (2d10+6) piercing plus 4 (1d8) acid.\n\n"
            "**Acid Breath (Recharge 5-6).** 60-foot line, 5 ft. wide. DC 18 Dex save, 54 (12d8) acid on fail, half on success."
        ),
    ),
    "Mummy Lord": dict(
        size="M", type="undead", ac=17, hp=97, die="8", dice=13,
        str_=18, dex=10, con=17, int_=11, wis=18, cha=16,
        speed="20 ft.", langs="the languages it knew in life",
        actions=(
            "**Multiattack.** The mummy lord makes two attacks: one with its rotting fist and one with its Dreadful Glare.\n\n"
            "**Rotting Fist.** *Melee Weapon Attack:* +9 to hit, reach 5 ft., one target. Hit: 14 (3d6+4) bludgeoning plus 21 (6d6) necrotic. DC 16 Con save or max HP reduced.\n\n"
            "**Dreadful Glare.** One creature within 60 ft.: DC 16 Wis save or frightened until end of mummy lord's next turn."
        ),
    ),
    "Adult Blue Dragon": dict(
        size="H", type="dragon", ac=19, hp=225, die="12", dice=18,
        str_=25, dex=10, con=23, int_=16, wis=13, cha=20,
        speed="40 ft., burrow 30 ft., fly 80 ft.", langs="Common, Draconic",
        actions=(
            "**Multiattack.** The dragon uses Frightful Presence then makes three attacks: one bite and two claws.\n\n"
            "**Bite.** *Melee Weapon Attack:* +12 to hit, reach 10 ft., one target. Hit: 18 (2d10+7) piercing plus 5 (1d10) lightning.\n\n"
            "**Lightning Breath (Recharge 5-6).** 90-foot line, 5 ft. wide. DC 19 Dex save, 66 (12d10) lightning on fail, half on success."
        ),
    ),
    "Death Knight": dict(
        size="M", type="undead", ac=20, hp=180, die="8", dice=24,
        str_=20, dex=11, con=17, int_=12, wis=16, cha=18,
        speed="30 ft.", langs="Abyssal, Common",
        actions=(
            "**Multiattack.** The death knight makes three longsword attacks.\n\n"
            "**Longsword.** *Melee Weapon Attack:* +11 to hit, reach 5 ft., one target. Hit: 9 (1d8+5) slashing plus 18 (4d8) necrotic.\n\n"
            "**Hellfire Orb (1/Day).** 20-foot radius sphere within 180 ft. DC 18 Dex save: 35 (10d6) fire plus 35 (10d6) necrotic on fail, half on success."
        ),
    ),
    "Lich": dict(
        size="M", type="undead", ac=17, hp=135, die="8", dice=18,
        str_=11, dex=16, con=16, int_=20, wis=14, cha=16,
        speed="30 ft.", langs="Common plus up to 5 other languages",
        actions=(
            "**Paralyzing Touch.** *Melee Spell Attack:* +12 to hit, reach 5 ft., one creature. Hit: 10 (3d6) cold damage. DC 18 Con save or paralyzed 1 minute (save ends each turn).\n\n"
            "**Spellcasting.** 18th-level spellcaster (spell save DC 20, +12 spell attack). Spells include: disintegrate, finger of death, power word kill."
        ),
    ),
}

# ── CR-formula stats (DMG p.274-279) ─────────────────────────────────────────
# Maps creature type to (primary_ab, secondary_ab, typical_languages)
_TYPE_PROFILE: Dict[str, Dict] = {
    "beast":       dict(pri="str", sec="dex", langs=""),
    "humanoid":    dict(pri="str", sec="dex", langs="Common"),
    "undead":      dict(pri="str", sec="dex", langs="understands languages from life but can't speak"),
    "construct":   dict(pri="str", sec="con", langs="understands its creator's languages but can't speak"),
    "ooze":        dict(pri="str", sec="con", langs=""),
    "plant":       dict(pri="str", sec="con", langs=""),
    "giant":       dict(pri="str", sec="con", langs="Common, Giant"),
    "monstrosity": dict(pri="str", sec="con", langs=""),
    "aberration":  dict(pri="int", sec="str", langs="Deep Speech"),
    "dragon":      dict(pri="str", sec="cha", langs="Common, Draconic"),
    "fiend":       dict(pri="str", sec="cha", langs="Abyssal, Infernal"),
    "fey":         dict(pri="dex", sec="cha", langs="Common, Elvish, Sylvan"),
    "elemental":   dict(pri="str", sec="con", langs="Primordial"),
    "celestial":   dict(pri="str", sec="wis", langs="Celestial, Common"),
}

def _cr_formula(cr: str, creature_type: str, size: str,
                hp_override: Optional[int] = None,
                ac_override: Optional[int] = None) -> Dict[str, Any]:
    """Derive a full stat block from CR + type using DMG guidelines."""
    n   = _cr_num(cr)
    pb  = _prof(cr)
    profile = _TYPE_PROFILE.get(creature_type.lower(), _TYPE_PROFILE["humanoid"])
    pri = profile["pri"]   # "str", "dex", "int", etc.

    # Primary ability score: scales with CR
    primary = min(26, max(8, int(n * 1.4 + 11)))
    # Secondary ability score
    secondary = min(20, max(8, int(n * 0.6 + 10)))
    # Other scores depend on type
    base_mental = min(18, max(8, int(n * 0.4 + 9)))

    if pri == "str":
        str_ = primary;  dex = secondary; con = secondary; int_ = base_mental; wis = base_mental; cha = max(5, base_mental - 2)
    elif pri == "dex":
        dex = primary;   str_ = secondary; con = secondary; int_ = base_mental; wis = base_mental; cha = base_mental
    elif pri == "int":
        int_ = primary;  str_ = secondary; dex = base_mental; con = secondary; wis = base_mental; cha = base_mental
    else:
        str_ = primary;  dex = secondary; con = secondary; int_ = base_mental; wis = base_mental; cha = primary

    # Undead/constructs have low Cha; aberrations/dragons have high Int/Cha
    if creature_type in ("undead", "construct", "ooze", "plant"):
        cha = max(3, int(n * 0.2 + 4))
        int_ = max(3, int(n * 0.3 + 4)) if creature_type in ("undead",) else max(1, 3)
    elif creature_type in ("aberration", "dragon"):
        int_ = min(22, int(n * 0.8 + 10))
        cha  = min(22, int(n * 0.7 + 10))

    # HP: average die roll formula; use d8 for medium, d10 for large/huge
    _size_die = {"T": 4, "S": 6, "M": 8, "L": 10, "H": 12, "G": 20}.get(size, 8)
    _target_hp = hp_override if hp_override else max(5, int(n * 13 + 7))
    con_mod = _mod(con)
    _avg_per_die = _size_die / 2 + 0.5 + con_mod
    hp_dice_count = max(1, round(_target_hp / max(1, _avg_per_die)))
    _actual_hp = int(hp_dice_count * (_size_die / 2 + 0.5) + hp_dice_count * con_mod)

    ac = ac_override if ac_override else max(10, min(20, int(n * 0.4 + 12)))

    # Attack bonus
    atk_bonus = pb + _mod(primary)
    damage     = max(1, int(n * 2 + 3))
    pp         = 10 + _mod(wis) + (pb if n >= 1 else 0)

    actions = (
        f"**Attack.** *Melee Weapon Attack:* {'+' if atk_bonus >= 0 else ''}{atk_bonus} to hit, reach 5 ft., one target. "
        f"Hit: {damage} ({_damage_dice(damage, _size_die)}) damage."
    )

    return dict(
        size=size, type=creature_type,
        ac=ac, hp=_actual_hp, die=str(_size_die), dice=hp_dice_count,
        str_=str_, dex=dex, con=con, int_=int_, wis=wis, cha=cha,
        speed="30 ft.", langs=profile["langs"],
        actions=actions,
    )


def _damage_dice(target: int, die: int) -> str:
    """Return a dice expression close to a target average."""
    count = max(1, round(target / (die / 2 + 0.5)))
    return f"{count}d{die}"


# ── Public API ────────────────────────────────────────────────────────────────

def build_statblock(
    name:          str,
    cr:            str,
    creature_type: str  = "",
    size:          str  = "M",
    hp_override:   Optional[int] = None,
    ac_override:   Optional[int] = None,
    attacks:       Optional[List[str]] = None,
    notes:         str  = "",
) -> Dict[str, Any]:
    """
    Return a push_monster()-compatible dict for any monster.

    SRD monsters get accurate stats from _SRD.
    Unknown/custom monsters get CR-formula stats.
    attacks — raw attack strings from LLM (infestation roster).
    """
    # Normalise name for lookup (handle "+1 Skeleton" etc.)
    base_name = re.sub(r'^[\+\-]\d\s+', '', name).strip()

    srd = _SRD.get(base_name) or _SRD.get(name)

    if srd:
        sb = dict(srd)
    else:
        inferred_type = creature_type or _infer_type(name)
        inferred_size = size or "M"
        sb = _cr_formula(cr, inferred_type, inferred_size, hp_override, ac_override)

    # If the LLM gave us explicit attacks, use those instead
    if attacks:
        sb["actions"] = format_actions_for_ddb(attacks)

    # HP die count sanity
    if hp_override and not srd:
        sb["hp"] = hp_override
    if ac_override and not srd:
        sb["ac"] = ac_override

    pp = 10 + _mod(sb.get("wis", 10))

    return {
        "cr":            cr,
        "creature_type": sb.get("type", creature_type or "monstrosity"),
        "size":          sb.get("size", size or "M"),
        "ac":            sb.get("ac", 12),
        "hp":            sb.get("hp", 15),
        "hp_die":        str(sb.get("die", "8")),
        "hp_die_count":  sb.get("dice", 2),
        "str_":          sb.get("str_", 10),
        "dex":           sb.get("dex", 10),
        "con":           sb.get("con", 10),
        "int_":          sb.get("int_", 10),
        "wis":           sb.get("wis", 10),
        "cha":           sb.get("cha", 10),
        "passive_perc":  pp,
        "languages":     sb.get("langs", "Common") or "—",
        "actions":       sb.get("actions", ""),
        "notes":         notes or f"Campaign creature. CR {cr}.",
    }


def format_actions_for_ddb(attacks: List[str]) -> str:
    """Format a list of attack strings into DDB textarea format."""
    parts = []
    for a in attacks[:5]:
        a = a.strip()
        if not a:
            continue
        # Bold the action name if it contains a dot
        if "." in a:
            dot = a.index(".")
            name_part = a[:dot].strip()
            rest = a[dot + 1:].strip()
            parts.append(f"**{name_part}.** {rest}")
        else:
            parts.append(a)
    return "\n\n".join(parts)


def _infer_type(name: str) -> str:
    """Guess creature type from name keywords."""
    n = name.lower()
    if any(w in n for w in ["zombie","skeleton","ghost","wraith","specter","wight","lich","death","undead","mummy","revenant"]):
        return "undead"
    if any(w in n for w in ["ooze","slime","jelly","pudding","cube","blob","mold","mould"]):
        return "ooze"
    if any(w in n for w in ["fungus","myconid","plant","shrieker","vine","spore"]):
        return "plant"
    if any(w in n for w in ["golem","construct","automaton","clockwork","iron","bronze","steel","mechanical"]):
        return "construct"
    if any(w in n for w in ["demon","devil","fiend","imp","quasit","dretch"]):
        return "fiend"
    if any(w in n for w in ["dragon","drake","wyvern","wyrm"]):
        return "dragon"
    if any(w in n for w in ["aberration","beholder","aboleth","mind flayer","otyugh","piercer","cloaker","mimic","gibbering"]):
        return "aberration"
    if any(w in n for w in ["goblin","kobold","hobgoblin","bugbear","orc","gnoll","troglodyte","bandit","cultist","thug","humanoid","guard"]):
        return "humanoid"
    if any(w in n for w in ["elemental","mephit","gargoyle","salamander"]):
        return "elemental"
    # Default: if it sounds like an animal/monster without a type hint
    return "monstrosity"
