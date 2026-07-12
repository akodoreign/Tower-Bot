"""
monster_stat_gen.py — Generate full D&D 5e stat blocks for monster DDB push.

Provides:
  _SRD_STATS   — Accurate stats for all monsters in MONSTER_TABLES / infestation pools
  build_statblock() — Returns push_monster()-compatible dict for any monster
  format_actions_for_ddb() — Format attack list into DDB textarea text

Known monsters get accurate 2024 Monster Manual (XMM) ability scores, HP
dice, and action text, extracted from the Mimir catalog on 2026-07-11 (some
2024 renames noted inline: Goblin -> Goblin Warrior, Kobold -> Kobold Warrior,
Bugbear -> Bugbear Warrior, Hobgoblin -> Hobgoblin Warrior, Minotaur ->
Minotaur of Baphomet). Table keys stay the classic names because pipeline
rosters look them up by those names.
Unknown/custom monsters get CR-formula stats derived from DMG guidelines.
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
        size="S", type="beast", ac=13, hp=7, die="6", dice=2,
        str_=7, dex=16, con=11, int_=2, wis=10, cha=4,
        speed="30 ft., climb 30 ft.", langs="",
        actions=(
            "**Bite.** *Melee Attack Roll:* +5, reach 5 feet. *Hit:* 5 (1d4 + 3) Piercing damage.\n\n"
            "**Pack Tactics (Trait).** The rat has Advantage on an attack roll against a creature if at least one of the rat's allies is within 5 feet of the creature and the ally doesn't have the Incapacitated condition."
        ),
    ),
    "Skeleton": dict(
        size="M", type="undead", ac=14, hp=13, die="8", dice=2,
        str_=10, dex=16, con=15, int_=6, wis=8, cha=5,
        speed="30 ft.", langs="understands Common plus one other language but can't speak",
        actions=(
            "**Shortsword.** *Melee Attack Roll:* +5, reach 5 ft. *Hit:* 6 (1d6 + 3) Piercing damage.\n\n"
            "**Shortbow.** *Ranged Attack Roll:* +5, range 80/320 ft. *Hit:* 6 (1d6 + 3) Piercing damage."
        ),
    ),
    "Zombie": dict(
        size="M", type="undead", ac=8, hp=15, die="8", dice=2,
        str_=13, dex=6, con=16, int_=3, wis=6, cha=5,
        speed="20 ft.", langs="understands Common plus one other language but can't speak",
        actions=(
            "**Slam.** *Melee Attack Roll:* +3, reach 5 ft. *Hit:* 5 (1d8 + 1) Bludgeoning damage.\n\n"
            "**Undead Fortitude (Trait).** If damage reduces the zombie to 0 Hit Points, it makes a Constitution saving throw (DC 5 plus the damage taken) unless the damage is Radiant or from a Critical Hit. On a successful save, the zombie drops to 1 Hit Point instead."
        ),
    ),
    "Goblin": dict(  # 2024 MM: Goblin Warrior
        size="S", type="fey", ac=15, hp=10, die="6", dice=3,
        str_=8, dex=15, con=10, int_=10, wis=8, cha=8,
        speed="30 ft.", langs="Common, Goblin",
        actions=(
            "**Scimitar.** *Melee Attack Roll:* +4, reach 5 ft. *Hit:* 5 (1d6 + 2) Slashing damage, plus 2 (1d4) Slashing damage if the attack roll had Advantage.\n\n"
            "**Shortbow.** *Ranged Attack Roll:* +4, range 80/320 ft. *Hit:* 5 (1d6 + 2) Piercing damage, plus 2 (1d4) Piercing damage if the attack roll had Advantage."
        ),
    ),
    "Kobold": dict(  # 2024 MM: Kobold Warrior
        size="S", type="dragon", ac=14, hp=7, die="6", dice=3,
        str_=7, dex=15, con=9, int_=8, wis=7, cha=8,
        speed="30 ft.", langs="Common, Draconic",
        actions=(
            "**Dagger.** *Melee or Ranged Attack Roll:* +4, reach 5 ft. or range 20/60 ft. *Hit:* 4 (1d4 + 2) Piercing damage.\n\n"
            "**Pack Tactics (Trait).** The kobold has Advantage on an attack roll against a creature if at least one of the kobold's allies is within 5 feet of the creature and the ally doesn't have the Incapacitated condition.\n\n"
            "**Sunlight Sensitivity (Trait).** While in sunlight, the kobold has Disadvantage on ability checks and attack rolls."
        ),
    ),
    "Giant Spider": dict(
        size="L", type="beast", ac=14, hp=26, die="10", dice=4,
        str_=14, dex=16, con=12, int_=2, wis=11, cha=4,
        speed="30 ft., climb 30 ft.", langs="",
        actions=(
            "**Bite.** *Melee Attack Roll:* +5, reach 5 ft. *Hit:* 7 (1d8 + 3) Piercing damage plus 7 (2d6) Poison damage.\n\n"
            "**Web (Recharge 5-6).** *Dexterity Saving Throw:* DC 13, one creature the spider can see within 60 feet. *Failure:* The target has the Restrained condition until the web is destroyed (AC 10; HP 5; Vulnerability to Fire damage; Immunity to Poison and Psychic damage).\n\n"
            "**Spider Climb (Trait).** The spider can climb difficult surfaces, including along ceilings, without needing to make an ability check.\n\n"
            "**Web Walker (Trait).** The spider ignores movement restrictions caused by webs, and it knows the location of any other creature in contact with the same web."
        ),
    ),
    "Ghoul": dict(
        size="M", type="undead", ac=12, hp=22, die="8", dice=5,
        str_=13, dex=15, con=10, int_=7, wis=10, cha=6,
        speed="30 ft.", langs="Common",
        actions=(
            "**Multiattack.** The ghoul makes two Bite attacks.\n\n"
            "**Bite.** *Melee Attack Roll:* +4, reach 5 ft. *Hit:* 5 (1d6 + 2) Piercing damage plus 3 (1d6) Necrotic damage.\n\n"
            "**Claw.** *Melee Attack Roll:* +4, reach 5 ft. *Hit:* 4 (1d4 + 2) Slashing damage. If the target is a creature that isn't an Undead or elf, it is subjected to the following effect. *Constitution Saving Throw:* DC 10. *Failure:* The target has the Paralyzed condition until the end of its next turn."
        ),
    ),
    "Specter": dict(
        size="M", type="undead", ac=12, hp=22, die="8", dice=5,
        str_=1, dex=14, con=11, int_=10, wis=10, cha=11,
        speed="30 ft., fly 50 ft. (hover)", langs="understands Common plus one other language but can't speak",
        actions=(
            "**Life Drain.** *Melee Attack Roll:* +4, reach 5 ft. *Hit:* 7 (2d6) Necrotic damage. If the target is a creature, its Hit Point maximum decreases by an amount equal to the damage taken.\n\n"
            "**Incorporeal Movement (Trait).** The specter can move through other creatures and objects as if they were Difficult Terrain. It takes 5 (1d10) Force damage if it ends its turn inside an object.\n\n"
            "**Sunlight Sensitivity (Trait).** While in sunlight, the specter has Disadvantage on ability checks and attack rolls."
        ),
    ),
    "Bugbear": dict(  # 2024 MM: Bugbear Warrior
        size="M", type="fey", ac=14, hp=33, die="8", dice=6,
        str_=15, dex=14, con=13, int_=8, wis=11, cha=9,
        speed="30 ft.", langs="Common, Goblin",
        actions=(
            "**Grab.** *Melee Attack Roll:* +4, reach 10 ft. *Hit:* 9 (2d6 + 2) Bludgeoning damage. If the target is a Medium or smaller creature, it has the Grappled condition (escape DC 12).\n\n"
            "**Light Hammer.** *Melee or Ranged Attack Roll:* +4 (with Advantage if the target is Grappled by the bugbear), reach 10 ft. or range 20/60 ft. *Hit:* 9 (3d4 + 2) Bludgeoning damage.\n\n"
            "**Abduct (Trait).** The bugbear needn't spend extra movement to move a creature it is grappling."
        ),
    ),
    "Hobgoblin": dict(  # 2024 MM: Hobgoblin Warrior
        size="M", type="fey", ac=18, hp=11, die="8", dice=2,
        str_=13, dex=12, con=12, int_=10, wis=10, cha=9,
        speed="30 ft.", langs="Common, Goblin",
        actions=(
            "**Longsword.** *Melee Attack Roll:* +3, reach 5 ft. *Hit:* 12 (2d10 + 1) Slashing damage.\n\n"
            "**Longbow.** *Ranged Attack Roll:* +3, range 150/600 ft. *Hit:* 5 (1d8 + 1) Piercing damage plus 7 (3d4) Poison damage.\n\n"
            "**Pack Tactics (Trait).** The hobgoblin has Advantage on an attack roll against a creature if at least one of the hobgoblin's allies is within 5 feet of the creature and the ally doesn't have the Incapacitated condition."
        ),
    ),
    "Gray Ooze": dict(
        size="M", type="ooze", ac=9, hp=22, die="8", dice=3,
        str_=12, dex=6, con=16, int_=1, wis=6, cha=2,
        speed="10 ft., climb 10 ft.", langs="",
        actions=(
            "**Pseudopod.** *Melee Attack Roll:* +3, reach 5 ft. *Hit:* 10 (2d8 + 1) Acid damage. Nonmagical armor worn by the target takes a -1 penalty to the AC it offers. The armor is destroyed if the penalty reduces its AC to 10. The penalty can be removed by casting the Mending spell on the armor.\n\n"
            "**Amorphous (Trait).** The ooze can move through a space as narrow as 1 inch without expending extra movement to do so.\n\n"
            "**Corrosive Form (Trait).** Nonmagical ammunition is destroyed immediately after hitting the ooze and dealing any damage. Any nonmagical weapon takes a cumulative -1 penalty to attack rolls immediately after dealing damage to the ooze and coming into contact with it. The weapon is destroyed if the penalty reaches -5. The penalty can be removed by casting the Mending spell on the weapon. The ooze can eat through 2-inch-thick, nonmagical metal or wood in 1 round."
        ),
    ),
    "Ogre": dict(
        size="L", type="giant", ac=11, hp=68, die="10", dice=8,
        str_=19, dex=8, con=16, int_=5, wis=7, cha=7,
        speed="40 ft.", langs="Common, Giant",
        actions=(
            "**Greatclub.** *Melee Attack Roll:* +6, reach 5 ft. *Hit:* 13 (2d8 + 4) Bludgeoning damage.\n\n"
            "**Javelin.** *Melee or Ranged Attack Roll:* +6, reach 5 ft. or range 30/120 ft. *Hit:* 11 (2d6 + 4) Piercing damage."
        ),
    ),
    "Ghast": dict(
        size="M", type="undead", ac=13, hp=36, die="8", dice=8,
        str_=16, dex=17, con=10, int_=11, wis=10, cha=8,
        speed="30 ft.", langs="Common",
        actions=(
            "**Bite.** *Melee Attack Roll:* +5, reach 5 ft. *Hit:* 7 (1d8 + 3) Piercing damage plus 9 (2d8) Necrotic damage.\n\n"
            "**Claw.** *Melee Attack Roll:* +5, reach 5 ft. *Hit:* 10 (2d6 + 3) Slashing damage. If the target is a non-Undead creature, it is subjected to the following effect. *Constitution Saving Throw:* DC 10. *Failure:* The target has the Paralyzed condition until the end of its next turn.\n\n"
            "**Stench (Trait).** *Constitution Saving Throw:* DC 10, any creature that starts its turn in a 5-foot Emanation originating from the ghast. *Failure:* The target has the Poisoned condition until the start of its next turn. *Success:* The target is immune to this ghast's Stench for 24 hours."
        ),
    ),
    "Mimic": dict(
        size="M", type="monstrosity", ac=12, hp=58, die="8", dice=9,
        str_=17, dex=12, con=15, int_=5, wis=13, cha=8,
        speed="20 ft.", langs="",
        actions=(
            "**Bite.** *Melee Attack Roll:* +5 (with Advantage if the target is Grappled by the mimic), reach 5 ft. *Hit:* 7 (1d8 + 3) Piercing damage-or 12 (2d8 + 3) Piercing damage if the target is Grappled by the mimic-plus 4 (1d8) Acid damage.\n\n"
            "**Pseudopod.** *Melee Attack Roll:* +5, reach 5 ft. *Hit:* 7 (1d8 + 3) Bludgeoning damage plus 4 (1d8) Acid damage. If the target is a Large or smaller creature, it has the Grappled condition (escape DC 13). Ability checks made to escape this grapple have Disadvantage.\n\n"
            "**Adhesive (Object Form Only) (Trait).** The mimic adheres to anything that touches it. A Huge or smaller creature adhered to the mimic has the Grappled condition (escape DC 13). Ability checks made to escape this grapple have Disadvantage."
        ),
    ),
    "Owlbear": dict(
        size="L", type="monstrosity", ac=13, hp=59, die="10", dice=7,
        str_=20, dex=12, con=17, int_=3, wis=12, cha=7,
        speed="40 ft., climb 40 ft.", langs="",
        actions=(
            "**Multiattack.** The owlbear makes two Rend attacks.\n\n"
            "**Rend.** *Melee Attack Roll:* +7, reach 5 ft. *Hit:* 14 (2d8 + 5) Slashing damage."
        ),
    ),
    "Minotaur": dict(  # 2024 MM: Minotaur of Baphomet
        size="L", type="monstrosity", ac=14, hp=85, die="10", dice=10,
        str_=18, dex=11, con=16, int_=6, wis=16, cha=9,
        speed="40 ft.", langs="Abyssal",
        actions=(
            "**Abyssal Glaive.** *Melee Attack Roll:* +6, reach 10 ft. *Hit:* 10 (1d12 + 4) Slashing damage plus 10 (3d6) Necrotic damage.\n\n"
            "**Gore (Recharge 5-6).** *Melee Attack Roll:* +6, reach 5 ft. *Hit:* 18 (4d6 + 4) Piercing damage. If the target is a Large or smaller creature and the minotaur moved 10+ feet straight toward it immediately before the hit, the target takes an extra 10 (3d6) Piercing damage and has the Prone condition."
        ),
    ),
    "Wight": dict(
        size="M", type="undead", ac=14, hp=82, die="8", dice=11,
        str_=15, dex=14, con=16, int_=10, wis=13, cha=15,
        speed="30 ft.", langs="Common plus one other language",
        actions=(
            "**Multiattack.** The wight makes two attacks, using Necrotic Sword or Necrotic Bow in any combination. It can replace one attack with a use of Life Drain.\n\n"
            "**Necrotic Sword.** *Melee Attack Roll:* +4, reach 5 ft. *Hit:* 6 (1d8 + 2) Slashing damage plus 4 (1d8) Necrotic damage.\n\n"
            "**Necrotic Bow.** *Ranged Attack Roll:* +4, range 150/600 ft. *Hit:* 6 (1d8 + 2) Piercing damage plus 4 (1d8) Necrotic damage.\n\n"
            "**Life Drain.** *Constitution Saving Throw:* DC 13, one creature within 5 feet. *Failure:* 6 (1d8 + 2) Necrotic damage, and the target's Hit Point maximum decreases by an amount equal to the damage taken. A Humanoid slain by this attack rises 24 hours later as a Zombie under the wight's control, unless the Humanoid is restored to life or its body is destroyed. The wight can have no more than twelve zombies under its control at a time.\n\n"
            "**Sunlight Sensitivity (Trait).** While in sunlight, the wight has Disadvantage on ability checks and attack rolls."
        ),
    ),
    "Phase Spider": dict(
        size="L", type="monstrosity", ac=14, hp=45, die="10", dice=7,
        str_=15, dex=16, con=12, int_=6, wis=10, cha=6,
        speed="30 ft., climb 30 ft.", langs="",
        actions=(
            "**Multiattack.** The spider makes two Bite attacks.\n\n"
            "**Bite.** *Melee Attack Roll:* +5, reach 5 ft. *Hit:* 8 (1d10 + 3) Piercing damage plus 9 (2d8) Poison damage. If this damage reduces the target to 0 Hit Points, the target becomes Stable, and it has the Poisoned condition for 1 hour. While Poisoned, the target also has the Paralyzed condition.\n\n"
            "**Ethereal Sight (Trait).** The spider can see 60 feet into the Ethereal Plane while on the Material Plane and vice versa.\n\n"
            "**Spider Climb (Trait).** The spider can climb difficult surfaces, including along ceilings, without needing to make an ability check.\n\n"
            "**Web Walker (Trait).** The spider ignores movement restrictions caused by webs, and the spider knows the location of any other creature in contact with the same web."
        ),
    ),
    "Wraith": dict(
        size="S", type="undead", ac=13, hp=67, die="8", dice=9,
        str_=6, dex=16, con=16, int_=12, wis=14, cha=15,
        speed="5 ft., fly 60 ft. (hover)", langs="Common plus two other languages",
        actions=(
            "**Life Drain.** *Melee Attack Roll:* +6, reach 5 ft. *Hit:* 21 (4d8 + 3) Necrotic damage. If the target is a creature, its Hit Point maximum decreases by an amount equal to the damage taken.\n\n"
            "**Create Specter.** The wraith targets a Humanoid corpse within 10 feet of itself that has been dead for no longer than 1 minute. The target's spirit rises as a Specter in the space of its corpse or in the nearest unoccupied space. The specter is under the wraith's control. The wraith can have no more than seven specters under its control at a time.\n\n"
            "**Incorporeal Movement (Trait).** The wraith can move through other creatures and objects as if they were Difficult Terrain. It takes 5 (1d10) Force damage if it ends its turn inside an object.\n\n"
            "**Sunlight Sensitivity (Trait).** While in sunlight, the wraith has Disadvantage on ability checks and attack rolls."
        ),
    ),
    "Troll": dict(
        size="L", type="giant", ac=15, hp=94, die="10", dice=9,
        str_=18, dex=13, con=20, int_=7, wis=9, cha=7,
        speed="30 ft.", langs="Giant",
        actions=(
            "**Multiattack.** The troll makes three Rend attacks.\n\n"
            "**Rend.** *Melee Attack Roll:* +7, reach 10 ft. *Hit:* 11 (2d6 + 4) Slashing damage.\n\n"
            "**Loathsome Limbs (4/Day) (Trait).** If the troll ends any turn Bloodied and took 15+ Slashing damage during that turn, one of the troll's limbs is severed, falls into the troll's space, and becomes a Troll Limb. The limb acts immediately after the troll's turn. The troll has 1 Exhaustion level for each missing limb, and it grows replacement limbs the next time it regains Hit Points.\n\n"
            "**Regeneration (Trait).** The troll regains 15 Hit Points at the start of each of its turns. If the troll takes Acid or Fire damage, this trait doesn't function on the troll's next turn. The troll dies only if it starts its turn with 0 Hit Points and doesn't regenerate."
        ),
    ),
    "Shambling Mound": dict(
        size="L", type="plant", ac=15, hp=110, die="10", dice=13,
        str_=18, dex=8, con=16, int_=5, wis=10, cha=5,
        speed="30 ft., swim 20 ft.", langs="",
        actions=(
            "**Multiattack.** The shambling mound makes three Charged Tendril attacks. It can replace one attack with a use of Engulf.\n\n"
            "**Charged Tendril.** *Melee Attack Roll:* +7, reach 10 ft. *Hit:* 7 (1d6 + 4) Bludgeoning damage plus 5 (2d4) Lightning damage. If the target is a Medium or smaller creature, the shambling mound pulls the target 5 feet straight toward itself.\n\n"
            "**Engulf.** *Strength Saving Throw:* DC 15, one Medium or smaller creature within 5 feet. *Failure:* The target is pulled into the shambling mound's space and has the Grappled condition (escape DC 14). Until the grapple ends, the target has the Blinded and Restrained conditions, and it takes 10 (3d6) Lightning damage at the start of each of its turns. When the shambling mound moves, the Grappled target moves with it, costing it no extra movement. The shambling mound can have only one creature Grappled by this action at a time.\n\n"
            "**Lightning Absorption (Trait).** Whenever the shambling mound is subjected to Lightning damage, it regains a number of Hit Points equal to the Lightning damage dealt."
        ),
    ),
    "Flesh Golem": dict(
        size="M", type="construct", ac=9, hp=127, die="8", dice=15,
        str_=19, dex=9, con=18, int_=6, wis=10, cha=5,
        speed="30 ft.", langs="understands Common plus one other language but can't speak",
        actions=(
            "**Multiattack.** The golem makes two Slam attacks.\n\n"
            "**Slam.** *Melee Attack Roll:* +7, reach 5 ft. *Hit:* 13 (2d8 + 4) Bludgeoning damage plus 4 (1d8) Lightning damage.\n\n"
            "**Aversion to Fire (Trait).** If the golem takes Fire damage, it has Disadvantage on attack rolls and ability checks until the end of its next turn.\n\n"
            "**Berserk (Trait).** Whenever the golem starts its turn Bloodied, roll 1d6. On a 6, the golem goes berserk. On each of its turns while berserk, the golem attacks the nearest creature it can see. If no creature is near enough to move to and attack, the golem attacks an object. Once the golem goes berserk, it remains so until it is destroyed or it is no longer Bloodied. The golem's creator, if within 60 feet of the berserk golem, can try to calm it by taking an action to make a DC 15 Charisma (Persuasion) check; the golem must be able to hear its creator. If this check succeeds, the golem ceases being berserk until the start of its next turn, at which point it resumes rolling for the Berserk trait again if it is still Bloodied.\n\n"
            "**Immutable Form (Trait).** The golem can't shape-shift.\n\n"
            "**Lightning Absorption (Trait).** Whenever the golem is subjected to Lightning damage, it regains a number of Hit Points equal to the Lightning damage dealt."
        ),
    ),
    "Salamander": dict(
        size="L", type="elemental", ac=15, hp=90, die="10", dice=12,
        str_=18, dex=14, con=15, int_=11, wis=10, cha=12,
        speed="30 ft., climb 30 ft.", langs="Primordial (Ignan)",
        actions=(
            "**Multiattack.** The salamander makes two Flame Spear attacks. It can replace one attack with a use of Constrict.\n\n"
            "**Flame Spear.** *Melee or Ranged Attack Roll:* +7, reach 5 ft. or range 20/60 ft. *Hit:* 13 (2d8 + 4) Piercing damage plus 7 (2d6) Fire damage. *Hit or Miss:* The spear magically returns to the salamander's hand immediately after a ranged attack.\n\n"
            "**Constrict.** *Strength Saving Throw:* DC 15, one Large or smaller creature the salamander can see within 10 feet. *Failure:* 11 (2d6 + 4) Bludgeoning damage plus 7 (2d6) Fire damage. The target has the Grappled condition (escape DC 14), and it has the Restrained condition until the grapple ends.\n\n"
            "**Fire Aura (Trait).** At the end of each of the salamander's turns, each creature of the salamander's choice in a 5-foot Emanation originating from the salamander takes 7 (2d6) Fire damage."
        ),
    ),
    "Otyugh": dict(
        size="L", type="aberration", ac=14, hp=104, die="10", dice=11,
        str_=16, dex=11, con=19, int_=6, wis=13, cha=6,
        speed="30 ft.", langs="Otyugh; telepathy 120 ft. (doesn't allow the receiving creature to respond telepathically)",
        actions=(
            "**Multiattack.** The otyugh makes one Bite attack and two Tentacle attacks.\n\n"
            "**Bite.** *Melee Attack Roll:* +6, reach 5 ft. *Hit:* 12 (2d8 + 3) Piercing damage, and the target has the Poisoned condition. Whenever the Poisoned target finishes a Long Rest, it is subjected to the following effect. *Constitution Saving Throw:* DC 15. *Failure:* The target's Hit Point maximum decreases by 5 (1d10) and doesn't return to normal until the Poisoned condition ends on the target. *Success:* The Poisoned condition ends.\n\n"
            "**Tentacle.** *Melee Attack Roll:* +6, reach 10 ft. *Hit:* 12 (2d8 + 3) Piercing damage. If the target is a Medium or smaller creature, it has the Grappled condition (escape DC 13) from one of two tentacles.\n\n"
            "**Tentacle Slam.** *Constitution Saving Throw:* DC 14, each creature Grappled by the otyugh. *Failure:* 16 (3d8 + 3) Bludgeoning damage, and the target has the Stunned condition until the start of the otyugh's next turn. *Success:* Half damage only."
        ),
    ),
    "Young White Dragon": dict(
        size="L", type="dragon", ac=17, hp=123, die="10", dice=13,
        str_=18, dex=10, con=18, int_=6, wis=11, cha=12,
        speed="40 ft., burrow 20 ft., fly 80 ft., swim 40 ft.", langs="Common, Draconic",
        actions=(
            "**Multiattack.** The dragon makes three Rend attacks.\n\n"
            "**Rend.** *Melee Attack Roll:* +7, reach 10 ft. *Hit:* 9 (2d4 + 4) Slashing damage plus 2 (1d4) Cold damage.\n\n"
            "**Cold Breath (Recharge 5-6).** *Constitution Saving Throw:* DC 15, each creature in a 30-foot Cone. *Failure:* 40 (9d8) Cold damage. *Success:* Half damage.\n\n"
            "**Ice Walk (Trait).** The dragon can move across and climb icy surfaces without needing to make an ability check. Additionally, Difficult Terrain composed of ice or snow doesn't cost it extra movement."
        ),
    ),
    "Medusa": dict(
        size="M", type="monstrosity", ac=15, hp=127, die="8", dice=17,
        str_=10, dex=17, con=16, int_=12, wis=13, cha=15,
        speed="30 ft.", langs="Common plus one other language",
        actions=(
            "**Multiattack.** The medusa makes two Claw attacks and one Snake Hair attack, or it makes three Poison Ray attacks.\n\n"
            "**Claw.** *Melee Attack Roll:* +6, reach 5 ft. *Hit:* 10 (2d6 + 3) Slashing damage.\n\n"
            "**Snake Hair.** *Melee Attack Roll:* +6, reach 5 ft. *Hit:* 5 (1d4 + 3) Piercing damage plus 14 (4d6) Poison damage.\n\n"
            "**Poison Ray.** *Ranged Attack Roll:* +5, range 150 ft. *Hit:* 11 (2d8 + 2) Poison damage."
        ),
    ),
    "Cloaker": dict(
        size="L", type="aberration", ac=14, hp=91, die="10", dice=14,
        str_=17, dex=15, con=12, int_=13, wis=14, cha=7,
        speed="10 ft., fly 40 ft.", langs="Deep Speech, Undercommon",
        actions=(
            "**Multiattack.** The cloaker makes one Attach attack and two Tail attacks.\n\n"
            "**Attach.** *Melee Attack Roll:* +6, reach 5 ft. *Hit:* 13 (3d6 + 3) Piercing damage. If the target is a Large or smaller creature, the cloaker attaches to it. While the cloaker is attached, the target has the Blinded condition, and the cloaker can't make Attach attacks against other targets. In addition, the cloaker halves the damage it takes (round down), and the target takes the same amount of damage. The cloaker can detach itself by spending 5 feet of movement. The target or a creature within 5 feet of it can take an action to try to detach the cloaker, doing so by succeeding on a DC 14 Strength (Athletics) check.\n\n"
            "**Tail.** *Melee Attack Roll:* +6, reach 10 ft. *Hit:* 8 (1d10 + 3) Slashing damage.\n\n"
            "**Light Sensitivity (Trait).** While in Bright Light, the cloaker has Disadvantage on attack rolls."
        ),
    ),
    "Spirit Naga": dict(
        size="L", type="fiend", ac=17, hp=135, die="10", dice=18,
        str_=18, dex=17, con=14, int_=16, wis=15, cha=16,
        speed="40 ft.", langs="Abyssal, Common",
        actions=(
            "**Multiattack.** The naga makes three attacks, using Bite or Necrotic Ray in any combination.\n\n"
            "**Bite.** *Melee Attack Roll:* +7, reach 10 ft. *Hit:* 7 (1d6 + 4) Piercing damage plus 14 (4d6) Poison damage.\n\n"
            "**Necrotic Ray.** *Ranged Attack Roll:* +6, range 60 ft. *Hit:* 21 (6d6) Necrotic damage.\n\n"
            "**Fiendish Restoration (Trait).** If it dies, the naga returns to life in 1d6 days and regains all its Hit Points. Only a Wish spell can prevent this trait from functioning."
        ),
    ),
    "Hydra": dict(
        size="H", type="monstrosity", ac=15, hp=184, die="12", dice=16,
        str_=20, dex=12, con=20, int_=2, wis=10, cha=7,
        speed="40 ft., swim 40 ft.", langs="",
        actions=(
            "**Multiattack.** The hydra makes as many Bite attacks as it has heads.\n\n"
            "**Bite.** *Melee Attack Roll:* +8, reach 10 ft. *Hit:* 10 (1d10 + 5) Piercing damage.\n\n"
            "**Hold Breath (Trait).** The hydra can hold its breath for 1 hour.\n\n"
            "**Multiple Heads (Trait).** The hydra has five heads. Whenever the hydra takes 25 damage or more on a single turn, one of its heads dies. The hydra dies if all its heads are dead. At the end of each of its turns when it has at least one living head, the hydra grows two heads for each of its heads that died since its last turn, unless it has taken Fire damage since its last turn. The hydra regains 20 Hit Points when it grows new heads.\n\n"
            "**Reactive Heads (Trait).** For each head the hydra has beyond one, it gets an extra Reaction that can be used only for Opportunity Attacks."
        ),
    ),
    "Clay Golem": dict(
        size="L", type="construct", ac=14, hp=123, die="10", dice=13,
        str_=20, dex=9, con=18, int_=3, wis=8, cha=1,
        speed="20 ft.", langs="Common plus one other language",
        actions=(
            "**Multiattack.** The golem makes two Slam attacks, or it makes three Slam attacks if it used Hasten this turn.\n\n"
            "**Slam.** *Melee Attack Roll:* +9, reach 5 ft. *Hit:* 10 (1d10 + 5) Bludgeoning damage plus 6 (1d12) Acid damage, and the target's Hit Point maximum decreases by an amount equal to the Acid damage taken.\n\n"
            "**Acid Absorption (Trait).** Whenever the golem is subjected to Acid damage, it takes no damage and instead regains a number of Hit Points equal to the Acid damage dealt.\n\n"
            "**Berserk (Trait).** Whenever the golem starts its turn Bloodied, roll 1d6. On a 6, the golem goes berserk. On each of its turns while berserk, the golem attacks the nearest creature it can see. If no creature is near enough to move to and attack, the golem attacks an object. Once the golem goes berserk, it continues to be berserk until it is destroyed or it is no longer Bloodied.\n\n"
            "**Immutable Form (Trait).** The golem can't shape-shift.\n\n"
            "**Magic Resistance (Trait).** The golem has Advantage on saving throws against spells and other magical effects."
        ),
    ),
    "Stone Golem": dict(
        size="L", type="construct", ac=18, hp=220, die="10", dice=21,
        str_=22, dex=9, con=20, int_=3, wis=11, cha=1,
        speed="30 ft.", langs="understands Common plus two other languages but can't speak",
        actions=(
            "**Multiattack.** The golem makes two attacks, using Slam or Force Bolt in any combination.\n\n"
            "**Slam.** *Melee Attack Roll:* +10, reach 5 ft. *Hit:* 15 (2d8 + 6) Bludgeoning damage plus 9 (2d8) Force damage.\n\n"
            "**Force Bolt.** *Ranged Attack Roll:* +9, range 120 ft. *Hit:* 22 (4d10) Force damage.\n\n"
            "**Immutable Form (Trait).** The golem can't shape-shift.\n\n"
            "**Magic Resistance (Trait).** The golem has Advantage on saving throws against spells and other magical effects."
        ),
    ),
    "Young Red Dragon": dict(
        size="L", type="dragon", ac=18, hp=178, die="10", dice=17,
        str_=23, dex=10, con=21, int_=14, wis=11, cha=19,
        speed="40 ft., climb 40 ft., fly 80 ft.", langs="Common, Draconic",
        actions=(
            "**Multiattack.** The dragon makes three Rend attacks.\n\n"
            "**Rend.** *Melee Attack Roll:* +10, reach 10 ft. *Hit:* 13 (2d6 + 6) Slashing damage plus 3 (1d6) Fire damage.\n\n"
            "**Fire Breath (Recharge 5-6).** *Dexterity Saving Throw:* DC 17, each creature in a 30-foot Cone. *Failure:* 56 (16d6) Fire damage. *Success:* Half damage."
        ),
    ),
    "Aboleth": dict(
        size="L", type="aberration", ac=17, hp=150, die="10", dice=20,
        str_=21, dex=9, con=15, int_=18, wis=15, cha=18,
        speed="10 ft., swim 40 ft.", langs="Deep Speech; telepathy 120 ft.",
        actions=(
            "**Multiattack.** The aboleth makes two Tentacle attacks and uses either Consume Memories or Dominate Mind if available.\n\n"
            "**Tentacle.** *Melee Attack Roll:* +9, reach 15 ft. *Hit:* 12 (2d6 + 5) Bludgeoning damage. If the target is a Large or smaller creature, it has the Grappled condition (escape DC 14) from one of four tentacles.\n\n"
            "**Consume Memories.** *Intelligence Saving Throw:* DC 16, one creature within 30 feet that is Charmed or Grappled by the aboleth. *Failure:* 10 (3d6) Psychic damage. *Success:* Half damage. *Failure or Success:* The aboleth gains the target's memories if the target is a Humanoid and is reduced to 0 Hit Points by this action.\n\n"
            "**Dominate Mind (2/Day).** *Wisdom Saving Throw:* DC 16, one creature the aboleth can see within 30 feet. *Failure:* The target has the Charmed condition until the aboleth dies or is on a different plane of existence from the target. While Charmed, the target acts as an ally to the aboleth and is under its control while within 60 feet of it. In addition, the aboleth and the target can communicate telepathically with each other over any distance. The target repeats the save whenever it takes damage as well as after every 24 hours it spends at least 1 mile away from the aboleth, ending the effect on itself on a success.\n\n"
            "**Amphibious (Trait).** The aboleth can breathe air and water.\n\n"
            "**Eldritch Restoration (Trait).** If destroyed, the aboleth gains a new body in 5d10 days, reviving with all its Hit Points in the Far Realm or another location chosen by the DM."
        ),
    ),
    "Beholder": dict(
        size="L", type="aberration", ac=18, hp=190, die="10", dice=20,
        str_=16, dex=14, con=18, int_=17, wis=15, cha=17,
        speed="5 ft., fly 40 ft. (hover)", langs="Deep Speech, Undercommon",
        actions=(
            "**Multiattack.** The beholder uses Eye Rays three times.\n\n"
            "**Bite.** *Melee Attack Roll:* +8, reach 5 ft. *Hit:* 13 (3d6 + 3) Piercing damage.\n\n"
            "**Eye Rays.** The beholder randomly shoots one of the following magical rays at a target it can see within 120 feet of itself (roll 1d10; reroll if the beholder has already used that ray during this turn):\n\n"
            "**Legendary Resistance (3/Day, or 4/Day in Lair) (Trait).** If the beholder fails a saving throw, it can choose to succeed instead."
        ),
    ),
    "Adult Black Dragon": dict(
        size="H", type="dragon", ac=19, hp=195, die="12", dice=17,
        str_=23, dex=14, con=21, int_=14, wis=13, cha=19,
        speed="40 ft., fly 80 ft., swim 40 ft.", langs="Common, Draconic",
        actions=(
            "**Multiattack.** The dragon makes three Rend attacks. It can replace one attack with a use of Spellcasting to cast Melf's Acid Arrow (level 3 version).\n\n"
            "**Rend.** *Melee Attack Roll:* +11, reach 10 ft. *Hit:* 13 (2d6 + 6) Slashing damage plus 4 (1d8) Acid damage.\n\n"
            "**Acid Breath (Recharge 5-6).** *Dexterity Saving Throw:* DC 18, each creature in a 60-foot-long, 5-foot-wide Line. *Failure:* 54 (12d8) Acid damage. *Success:* Half damage.\n\n"
            "**Amphibious (Trait).** The dragon can breathe air and water.\n\n"
            "**Legendary Resistance (3/Day, or 4/Day in Lair) (Trait).** If the dragon fails a saving throw, it can choose to succeed instead."
        ),
    ),
    "Mummy Lord": dict(
        size="S", type="undead", ac=17, hp=187, die="8", dice=25,
        str_=18, dex=10, con=17, int_=11, wis=19, cha=16,
        speed="30 ft.", langs="Common plus three other languages",
        actions=(
            "**Multiattack.** The mummy makes one Rotting Fist or Channel Negative Energy attack, and it uses Dreadful Glare.\n\n"
            "**Rotting Fist.** *Melee Attack Roll:* +9, reach 5 ft. *Hit:* 15 (2d10 + 4) Bludgeoning damage plus 10 (3d6) Necrotic damage. If the target is a creature, it is cursed. While cursed, the target can't regain Hit Points, it gains no benefit from finishing a Long Rest, and its Hit Point maximum decreases by 10 (3d6) every 24 hours that elapse. A creature dies and turns to dust if reduced to 0 Hit Points by this attack.\n\n"
            "**Channel Negative Energy.** *Ranged Attack Roll:* +9, range 60 ft. *Hit:* 25 (6d6 + 4) Necrotic damage.\n\n"
            "**Dreadful Glare.** *Wisdom Saving Throw:* DC 17, one creature the mummy can see within 60 feet. *Failure:* 25 (6d6 + 4) Psychic damage, and the target has the Paralyzed condition until the end of the mummy's next turn.\n\n"
            "**Legendary Resistance (3/Day, or 4/Day in Lair) (Trait).** If the mummy fails a saving throw, it can choose to succeed instead.\n\n"
            "**Magic Resistance (Trait).** The mummy has Advantage on saving throws against spells and other magical effects."
        ),
    ),
    "Adult Blue Dragon": dict(
        size="H", type="dragon", ac=19, hp=212, die="12", dice=17,
        str_=25, dex=10, con=23, int_=16, wis=15, cha=20,
        speed="40 ft., burrow 30 ft., fly 80 ft.", langs="Common, Draconic",
        actions=(
            "**Multiattack.** The dragon makes three Rend attacks. It can replace one attack with a use of Spellcasting to cast Shatter.\n\n"
            "**Rend.** *Melee Attack Roll:* +12, reach 10 ft. *Hit:* 16 (2d8 + 7) Slashing damage plus 5 (1d10) Lightning damage.\n\n"
            "**Lightning Breath (Recharge 5-6).** *Dexterity Saving Throw:* DC 19, each creature in a 90-foot-long, 5-foot-wide Line. *Failure:* 60 (11d10) Lightning damage. *Success:* Half damage.\n\n"
            "**Legendary Resistance (3/Day, or 4/Day in Lair) (Trait).** If the dragon fails a saving throw, it can choose to succeed instead."
        ),
    ),
    "Death Knight": dict(
        size="S", type="undead", ac=20, hp=199, die="8", dice=21,
        str_=20, dex=11, con=20, int_=12, wis=16, cha=18,
        speed="30 ft.", langs="Abyssal, Common",
        actions=(
            "**Multiattack.** The death knight makes three Dread Blade attacks.\n\n"
            "**Dread Blade.** *Melee Attack Roll:* +11, reach 5 ft. *Hit:* 12 (2d6 + 5) Slashing damage plus 13 (3d8) Necrotic damage.\n\n"
            "**Hellfire Orb (Recharge 5-6).** *Dexterity Saving Throw:* DC 18, each creature in a 20-foot-radius Sphere centered on a point the death knight can see within 120 feet. *Failure:* 35 (10d6) Fire damage plus 35 (10d6) Necrotic damage. *Success:* Half damage.\n\n"
            "**Legendary Resistance (3/Day) (Trait).** If the death knight fails a saving throw, it can choose to succeed instead.\n\n"
            "**Magic Resistance (Trait).** The death knight has Advantage on saving throws against spells and other magical effects.\n\n"
            "**Marshal Undead (Trait).** Undead creatures of the death knight's choice (excluding itself) in a 60-foot Emanation originating from it have Advantage on attack rolls and saving throws. It can't use this trait if it has the Incapacitated condition."
        ),
    ),
    "Lich": dict(
        size="M", type="undead", ac=20, hp=315, die="8", dice=42,
        str_=11, dex=16, con=16, int_=21, wis=14, cha=16,
        speed="30 ft.", langs="all",
        actions=(
            "**Multiattack.** The lich makes three attacks, using Eldritch Burst or Paralyzing Touch in any combination.\n\n"
            "**Eldritch Burst.** *Melee or Ranged Attack Roll:* +12, reach 5 ft. or range 120 ft. *Hit:* 31 (4d12 + 5) Force damage.\n\n"
            "**Paralyzing Touch.** *Melee Attack Roll:* +12, reach 5 ft. *Hit:* 15 (3d6 + 5) Cold damage, and the target has the Paralyzed condition until the start of the lich's next turn.\n\n"
            "**Legendary Resistance (4/Day, or 5/Day in Lair) (Trait).** If the lich fails a saving throw, it can choose to succeed instead.\n\n"
            "**Spirit Jar (Trait).** If destroyed, the lich reforms in 1d10 days if it has a spirit jar, reviving with all its Hit Points. The new body appears in an unoccupied space within the lich's lair."
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
        f"**Attack.** *Melee Attack Roll:* {'+' if atk_bonus >= 0 else ''}{atk_bonus}, reach 5 ft. "
        f"*Hit:* {damage} ({_damage_dice(damage, _size_die)}) damage."
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
