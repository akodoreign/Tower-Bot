"""
seed_monster_db.py — Create monsters table and seed with Undercity creatures.

60 new campaign monsters: CR 5-8 (10 regular each) + void versions (5 per CR, CR+2).
EBP spaceship creatures are NOT touched — they are already imported.

Run from project root:
    python scripts/seed_monster_db.py

Safe to re-run: uses INSERT IGNORE so existing rows are skipped.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.db_api import raw_execute, raw_query

# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS monsters (
    id              INT NOT NULL AUTO_INCREMENT,
    name            VARCHAR(255) NOT NULL,
    cr              VARCHAR(10)  NOT NULL DEFAULT '1',
    creature_type   VARCHAR(50)  NOT NULL DEFAULT 'monstrosity',
    size            CHAR(1)      NOT NULL DEFAULT 'M',
    ac              INT NOT NULL DEFAULT 12,
    hp              INT NOT NULL DEFAULT 15,
    hp_die          VARCHAR(5)   NOT NULL DEFAULT '8',
    hp_die_count    INT NOT NULL DEFAULT 2,
    stat_str        INT NOT NULL DEFAULT 10,
    stat_dex        INT NOT NULL DEFAULT 10,
    stat_con        INT NOT NULL DEFAULT 10,
    stat_int        INT NOT NULL DEFAULT 10,
    stat_wis        INT NOT NULL DEFAULT 10,
    stat_cha        INT NOT NULL DEFAULT 10,
    passive_perc    INT NOT NULL DEFAULT 10,
    languages       VARCHAR(500) DEFAULT 'Common',
    speed           VARCHAR(200) DEFAULT '30 ft.',
    actions         TEXT,
    traits          TEXT,
    reactions       TEXT,
    bonus_actions   TEXT,
    legendary_actions TEXT,
    mythic_actions  TEXT,
    lair_actions    TEXT,
    saves_json      JSON,
    notes           TEXT,
    sd_appearance   TEXT,
    source          VARCHAR(100) DEFAULT 'undercity',
    is_void         TINYINT(1)   NOT NULL DEFAULT 0,
    base_name       VARCHAR(255) DEFAULT NULL,
    ddb_url         VARCHAR(500) DEFAULT NULL,
    ddb_edit_url    VARCHAR(500) DEFAULT NULL,
    portrait_path   VARCHAR(500) DEFAULT NULL,
    enriched_at     DATETIME DEFAULT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_name (name),
    INDEX idx_cr (cr),
    INDEX idx_type (creature_type),
    INDEX idx_void (is_void),
    INDEX idx_source (source),
    INDEX idx_enriched (enriched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# ---------------------------------------------------------------------------
# Monster definitions
# ---------------------------------------------------------------------------
# All names prefixed "UC " (Undercity) to distinguish from EBP spaceship series.
# Fields map directly to DB columns; saves_json is a dict serialised to JSON.
# ---------------------------------------------------------------------------

def _m(name, cr, ctype, size, ac, hp, hp_die, hp_die_count,
        s, d, co, i, wi, ch, pp, lang, speed,
        actions, traits="", reactions="", bonus_actions="", legendary_actions="", lair_actions="",
        notes="", sd="", is_void=0, base_name=None, saves=None,
        bonus="", legendary="", lair=""):
    if bonus and not bonus_actions:
        bonus_actions = bonus
    if legendary and not legendary_actions:
        legendary_actions = legendary
    if lair and not lair_actions:
        lair_actions = lair
    return dict(
        name=name, cr=cr, creature_type=ctype, size=size,
        ac=ac, hp=hp, hp_die=hp_die, hp_die_count=hp_die_count,
        stat_str=s, stat_dex=d, stat_con=co, stat_int=i, stat_wis=wi, stat_cha=ch,
        passive_perc=pp, languages=lang, speed=speed,
        actions=actions, traits=traits, reactions=reactions,
        bonus_actions=bonus_actions, legendary_actions=legendary_actions,
        mythic_actions="", lair_actions=lair_actions,
        saves_json=json.dumps(saves or {}),
        notes=notes, sd_appearance=sd,
        source="undercity", is_void=is_void, base_name=base_name,
    )


MONSTERS: list[dict] = [

    # =========================================================================
    # CR 5 — 10 regular
    # =========================================================================

    _m("UC Rift Lurker", "5", "aberration", "L",
       ac=14, hp=82, hp_die="10", hp_die_count=11,
       s=17, d=15, co=14, i=8, wi=12, ch=6, pp=14,
       lang="—", speed="30 ft.",
       actions=(
           "Multiattack. Two Void Claw attacks.\n\n"
           "Void Claw. Melee Weapon Attack: +6 to hit, reach 10 ft., one target. "
           "Hit: 11 (2d8+3) slashing plus 9 (2d8) psychic damage.\n\n"
           "Phasing Shift (Recharge 5-6). Until the start of its next turn the lurker gains +4 AC "
           "and resistance to all damage."
       ),
       traits=(
           "Rift Sense. Detects active rift tears within 120 ft. automatically.\n\n"
           "Ambush Predator. Advantage on attack rolls against any creature that has not yet taken "
           "a turn in the current combat."
       ),
       notes="Dimensional stalker that slips between rift tears in the Dome. Immune to the charmed condition.",
       sd="aberrant alien predator, glowing rift tears in its flesh, long clawed limbs, dark void-purple skin, "
          "D&D monster, dramatic lighting, fantasy concept art",
       saves={"wis": 4}),

    _m("UC Iron Fang Enforcer", "5", "humanoid", "M",
       ac=17, hp=65, hp_die="8", hp_die_count=10,
       s=18, d=12, co=14, i=11, wi=13, ch=14, pp=13,
       lang="Common", speed="30 ft.",
       actions=(
           "Multiattack. Three Longsword attacks.\n\n"
           "Longsword. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. "
           "Hit: 8 (1d8+4) slashing plus 3 (1d6) necrotic damage.\n\n"
           "Syndicate Judgment (1/Day). One creature within 30 ft. makes a DC 14 Wis save or is "
           "frightened for 1 minute (save ends each turn). While frightened the target has "
           "disadvantage on attacks against Iron Fang allies."
       ),
       traits=(
           "Syndicate Mark. The first time this enforcer is reduced to 0 HP it makes a DC 13 Con "
           "save. On success it drops to 1 HP instead (once per combat)."
       ),
       notes="Elite enforcer for the Iron Fang Consortium. Usually deployed with backup.",
       sd="armoured mercenary soldier, black plate armour with iron fang insignia, "
          "necrotic glowing blade, grim expression, D&D humanoid fighter, cinematic lighting",
       saves={"str": 7, "con": 5}),

    _m("UC Sewer Hydra Juvenile", "5", "monstrosity", "L",
       ac=13, hp=85, hp_die="10", hp_die_count=10,
       s=18, d=11, co=16, i=2, wi=10, ch=5, pp=10,
       lang="—", speed="20 ft., swim 30 ft.",
       actions=(
           "Four Bite attacks (one per head).\n\n"
           "Bite. Melee Weapon Attack: +7 to hit, reach 10 ft., one target. "
           "Hit: 11 (2d6+4) piercing damage."
       ),
       traits=(
           "Multiple Heads (4). Advantage on saves vs. blinded, charmed, deafened, frightened, "
           "stunned, and unconscious while it has more than one head.\n\n"
           "Reactive Heads. For each head beyond one the hydra gains one additional reaction.\n\n"
           "Head Regrowth. If a head is severed (10+ damage in a single hit) two grow back at the "
           "end of the hydra's next turn unless fire or acid damage is dealt to the stump first.\n\n"
           "Amphibious. Can breathe air and water."
       ),
       notes="4-headed juvenile hydra adapted to the Undercity sewer system.",
       sd="four-headed juvenile hydra, sewer slime coating, bioluminescent eyes, dark fantasy creature, "
          "cyberpunk dungeon environment, D&D monstrosity"),

    _m("UC Dome Shade", "5", "undead", "M",
       ac=13, hp=67, hp_die="8", hp_die_count=9,
       s=6, d=16, co=16, i=13, wi=14, ch=16, pp=12,
       lang="Any languages known in life", speed="0 ft., fly 40 ft. (hover)",
       actions=(
           "Life Drain. Melee Spell Attack: +6 to hit, reach 5 ft., one creature. "
           "Hit: 21 (4d8+3) necrotic. DC 14 Con save or max HP reduced by damage taken until long rest.\n\n"
           "Haunting Wail (Recharge 5-6). 30-ft. radius. DC 14 Wis save or frightened 1 minute "
           "(save ends each turn). A frightened creature must use its movement to flee."
       ),
       traits=(
           "Incorporeal Movement. Can move through creatures and objects as difficult terrain. "
           "Takes 5 (1d10) force damage if it ends its turn inside an object.\n\n"
           "Dome-Bound. Cannot travel more than 100 ft. below the Dome apex."
       ),
       notes="Ghost formed from memories trapped in the Dome's artificial sky layer. "
             "Immune to cold, necrotic, poison. Immune to charmed, exhaustion, frightened, "
             "grappled, paralyzed, petrified, poisoned, prone, restrained.",
       sd="translucent ghost, glowing artificial sky reflected in spectral form, trailing void energy, "
          "haunting expression, floating, D&D undead, dramatic lighting",
       saves={}),

    _m("UC Tower Automaton", "5", "construct", "M",
       ac=16, hp=71, hp_die="8", hp_die_count=11,
       s=18, d=12, co=14, i=14, wi=10, ch=6, pp=10,
       lang="Understands Tower Authority commands, cannot speak", speed="30 ft.",
       actions=(
           "Multiattack. Two Force Strike attacks.\n\n"
           "Force Strike. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. "
           "Hit: 13 (2d8+4) force damage.\n\n"
           "Arc Discharge (Recharge 5-6). 15-ft. cone. DC 14 Dex save: 22 (4d10) lightning on fail, "
           "half on success. Creatures in metal armour have disadvantage on this save."
       ),
       traits=(
           "Magic Resistance. Advantage on saves vs. spells and magical effects.\n\n"
           "Tower Protocol. Advantage on attack rolls against targets flagged by Tower Authority orders.\n\n"
           "Construct Immunities. Immune to poison, psychic, charmed, exhaustion, frightened, "
           "paralyzed, petrified, poisoned."
       ),
       notes="Malfunctioning Tower Authority security construct. Still responds to old patrol commands.",
       sd="sleek humanoid security robot, Tower Authority insignia, glowing blue eyes, "
          "crackling arc energy, dark fantasy cyberpunk fusion, D&D construct"),

    _m("UC Rust Drake", "5", "dragon", "M",
       ac=15, hp=65, hp_die="8", hp_die_count=10,
       s=17, d=14, co=14, i=8, wi=10, ch=8, pp=10,
       lang="Draconic, understands Common", speed="30 ft., fly 50 ft.",
       actions=(
           "Multiattack. One Bite and one Claw attack.\n\n"
           "Bite. Melee Weapon Attack: +6 to hit, reach 10 ft., one target. "
           "Hit: 13 (2d8+4) piercing damage.\n\n"
           "Claw. Melee Weapon Attack: +6 to hit, reach 5 ft., one target. "
           "Hit: 8 (1d8+4) slashing damage.\n\n"
           "Acid Breath (Recharge 5-6). 15-ft. line 5 ft. wide. DC 14 Dex save: 27 (6d8) acid on fail, "
           "half on success. Non-magical metal armour takes a permanent -1 AC on a failed save "
           "(cumulative, min -3 total)."
       ),
       traits="Acid Resistance. Resistant to acid damage.",
       notes="Industrial drake adapted to Undercity smelting districts. Acid-spitter variant.",
       sd="rust-coloured drake, corroded metal scales, acid dripping from jaws, industrial wasteland background, "
          "D&D dragon, dark fantasy cyberpunk, dramatic lighting"),

    _m("UC Spore Mother", "5", "plant", "L",
       ac=13, hp=88, hp_die="10", hp_die_count=11,
       s=16, d=8, co=16, i=6, wi=10, ch=5, pp=10,
       lang="—", speed="20 ft.",
       actions=(
           "Multiattack. Two Slam attacks.\n\n"
           "Slam. Melee Weapon Attack: +6 to hit, reach 10 ft., one target. "
           "Hit: 14 (2d10+3) bludgeoning damage.\n\n"
           "Spore Burst (Recharge 5-6). 20-ft. radius sphere. DC 14 Con save: 18 (4d8) poison plus "
           "Poisoned condition for 1 minute on fail. Half damage, no condition on success."
       ),
       traits=(
           "Colony Mind. Undead and plant creatures within 60 ft. have advantage on attack rolls "
           "while the Spore Mother is alive and conscious.\n\n"
           "Spore Regeneration. Regains 5 HP at the start of its turn if it has at least 1 HP.\n\n"
           "Immunities. Immune to blinded, deafened conditions."
       ),
       notes="Colony commander for Undercity infestation networks. Fungal overmind for smaller spore servants.",
       sd="enormous fungal plant creature, pulsing spore sacs, bioluminescent mushroom growths, "
          "sewer environment, D&D plant monstrosity, horror lighting"),

    _m("UC Glass Sigil Operative", "5", "humanoid", "M",
       ac=15, hp=55, hp_die="8", hp_die_count=10,
       s=12, d=20, co=12, i=14, wi=13, ch=14, pp=13,
       lang="Common, Thieves' Cant", speed="30 ft.",
       actions=(
           "Multiattack. Three Dagger attacks. One additional attack if the operative is hidden.\n\n"
           "Dagger. Melee or Ranged Weapon Attack: +8 to hit, reach 5 ft. or range 20/60 ft., one target. "
           "Hit: 7 (1d4+5) piercing plus 10 (3d6) poison damage.\n\n"
           "Hand Crossbow. Ranged Weapon Attack: +8 to hit, range 30/120 ft., one target. "
           "Hit: 7 (1d6+5) piercing plus 7 (2d6) poison damage."
       ),
       traits=(
           "Sneak Attack (4d6). Once per turn deals +14 (4d6) extra damage when it has advantage "
           "on the attack roll or when an ally is adjacent to the target.\n\n"
           "Expertise. Stealth +9, Deception +5."
       ),
       bonus_actions=(
           "Shadow Meld. When in dim light or darkness the operative Disengages and moves up to "
           "15 ft. without provoking opportunity attacks."
       ),
       notes="Glass Sigil field operative. Information broker's field agent. Expertise in Stealth and Deception.",
       sd="cloaked assassin, glass-and-shadow armour, Glass Sigil emblem, glowing poisoned blade, "
          "cyberpunk alley background, D&D rogue, dramatic rim lighting",
       saves={"dex": 8, "int": 5}),

    _m("UC Warden Champion", "5", "humanoid", "M",
       ac=18, hp=82, hp_die="8", hp_die_count=11,
       s=20, d=10, co=16, i=12, wi=14, ch=13, pp=12,
       lang="Common", speed="30 ft.",
       actions=(
           "Multiattack. Three Warden Spear attacks.\n\n"
           "Warden Spear. Melee Weapon Attack: +8 to hit, reach 10 ft., one target. "
           "Hit: 9 (1d8+5) piercing damage.\n\n"
           "Rally (Action). All friendly creatures within 30 ft. gain 10 temporary HP."
       ),
       traits=(
           "Courage Aura. Friendly creatures within 30 ft. can't be frightened while the champion is conscious.\n\n"
           "Indomitable (1/Day). Rerolls one failed saving throw."
       ),
       bonus_actions="Second Wind (1/Combat). Regains 14 (2d10+3) HP.",
       notes="Tower Authority elite combat operative.",
       sd="imposing Tower Authority champion in heavy plate, glowing warden spear, "
          "commanding stance, cyberpunk fortress background, D&D paladin fighter, heroic lighting",
       saves={"str": 8, "con": 6}),

    _m("UC Bile Crawler", "5", "monstrosity", "L",
       ac=13, hp=76, hp_die="10", hp_die_count=8,
       s=16, d=14, co=18, i=3, wi=10, ch=3, pp=10,
       lang="—", speed="30 ft., climb 30 ft.",
       actions=(
           "Multiattack. One Bite attack and one Acid Spray (if recharged).\n\n"
           "Bite. Melee Weapon Attack: +6 to hit, reach 5 ft., one target. "
           "Hit: 14 (2d10+3) piercing damage.\n\n"
           "Acid Spray (Recharge 5-6). 20-ft. cone. DC 14 Dex save: 27 (6d8) acid on fail, "
           "half on success."
       ),
       traits=(
           "Dissolving Grip. Creatures grappled by the bile crawler take 9 (2d8) acid damage at "
           "the start of their turns.\n\n"
           "Spider Climb. Can climb difficult surfaces including ceilings without a check.\n\n"
           "Acid Immunity. Immune to acid damage."
       ),
       notes="Warrens-bred acid-spitting crawler from the deep undercity sewers.",
       sd="six-legged acid-spitting crawler, translucent abdomen full of bile, glistening carapace, "
          "sewer stone background, D&D monstrosity, horror lighting"),

    # =========================================================================
    # CR 5 → Void versions at CR 7 (5 monsters)
    # =========================================================================

    _m("UC Void Rift Lurker", "7", "aberration", "L",
       ac=15, hp=133, hp_die="10", hp_die_count=14,
       s=18, d=16, co=18, i=10, wi=14, ch=8, pp=15,
       lang="—", speed="35 ft.",
       actions=(
           "Multiattack. Two Void Claw attacks or one Void Claw and one Reality Tear.\n\n"
           "Void Claw. Melee Weapon Attack: +7 to hit, reach 10 ft., one target. "
           "Hit: 13 (2d8+4) slashing plus 13 (3d8) psychic damage.\n\n"
           "Reality Tear (Recharge 5-6). A 5-ft. rift opens at a point within 60 ft. Creatures "
           "within 15 ft. of the tear: DC 16 Con save or teleported 30 ft. in a random direction "
           "and take 18 (4d8) necrotic damage.\n\n"
           "Phasing Shift (Recharge 5-6). +4 AC and damage resistance until start of next turn."
       ),
       traits=(
           "Void Form. Resistant to bludgeoning, piercing, and slashing from nonmagical weapons.\n\n"
           "Void Aura. Creatures that start their turn within 10 ft. have disadvantage on Con saves.\n\n"
           "Rift Sense. Detects active rift tears within 120 ft. automatically.\n\n"
           "Ambush Predator. Advantage on attacks vs. creatures that haven't taken a turn yet."
       ),
       notes="Void-corrupted Rift Lurker. Void version of UC Rift Lurker (CR 5).",
       sd="void-corrupted aberrant predator, crackling rift energy tears in its body, "
          "purple-black void tendrils, glowing dimensional wounds, D&D monster, dramatic void lighting",
       is_void=1, base_name="UC Rift Lurker",
       saves={"wis": 6, "con": 7}),

    _m("UC Void Iron Fang Enforcer", "7", "humanoid", "M",
       ac=18, hp=117, hp_die="8", hp_die_count=18,
       s=20, d=12, co=14, i=11, wi=13, ch=14, pp=13,
       lang="Common", speed="30 ft.",
       actions=(
           "Multiattack. Three Longsword attacks plus one Void Strike.\n\n"
           "Longsword. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 9 (1d8+5) slashing plus 9 (2d8) necrotic damage.\n\n"
           "Void Strike. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 16 (2d10+5) necrotic. DC 16 Wis save or disadvantage on next attack roll.\n\n"
           "Syndicate Judgment (1/Day). DC 16 Wis save or frightened 1 minute."
       ),
       traits=(
           "Void Resilience. Resistant to psychic damage. Immune to charmed condition.\n\n"
           "Syndicate Mark. Drops to 1 HP instead of 0 on first death (DC 13 Con save, once per combat).\n\n"
           "Void Form. Resistant to bludgeoning, piercing, and slashing from nonmagical weapons."
       ),
       notes="Void-corrupted Iron Fang Enforcer. Void version of UC Iron Fang Enforcer (CR 5).",
       sd="armoured enforcer with void corruption seeping through cracked plate, "
          "necrotic energy pulsing from wounds, Iron Fang insignia, D&D humanoid, dark fantasy",
       is_void=1, base_name="UC Iron Fang Enforcer",
       saves={"str": 9, "con": 6}),

    _m("UC Void Tower Automaton", "7", "construct", "L",
       ac=17, hp=120, hp_die="10", hp_die_count=11,
       s=20, d=12, co=20, i=14, wi=10, ch=6, pp=10,
       lang="Understands Tower Authority commands", speed="30 ft.",
       actions=(
           "Multiattack. Three Force Strike attacks.\n\n"
           "Force Strike. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 15 (2d10+4) force damage.\n\n"
           "Arc Discharge (Recharge 5-6). 20-ft. cone. DC 15 Dex save: 33 (6d10) lightning on fail, "
           "half on success.\n\n"
           "Gravity Pulse (Recharge 6). 30-ft. radius. DC 15 Str save or pulled 20 ft. toward the "
           "automaton and knocked prone."
       ),
       traits=(
           "Void Core. Resistant to bludgeoning, piercing, and slashing from nonmagical weapons.\n\n"
           "Magic Resistance. Advantage on saves vs. spells and magical effects.\n\n"
           "Construct Immunities. Immune to poison, psychic, charmed, exhaustion, frightened, "
           "paralyzed, petrified, poisoned."
       ),
       notes="Void-infused Tower Automaton, size upgraded. Void version of UC Tower Automaton (CR 5).",
       sd="large void-infused security robot, cracks in armour plating leaking void energy, "
          "gravity distortion field, Tower Authority markings, D&D construct, cyberpunk fantasy",
       is_void=1, base_name="UC Tower Automaton"),

    _m("UC Void Rust Drake", "7", "dragon", "L",
       ac=16, hp=126, hp_die="10", hp_die_count=11,
       s=19, d=14, co=22, i=8, wi=10, ch=8, pp=10,
       lang="Draconic, understands Common", speed="30 ft., fly 60 ft.",
       actions=(
           "Multiattack. One Bite and two Claw attacks.\n\n"
           "Bite. Melee Weapon Attack: +7 to hit, reach 10 ft., one target. "
           "Hit: 15 (2d10+4) piercing plus 7 (2d6) acid damage.\n\n"
           "Claw. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. "
           "Hit: 9 (1d10+4) slashing damage.\n\n"
           "Void Acid Breath (Recharge 5-6). 20-ft. cone. DC 16 Dex save: 49 (9d10) necrotic + acid "
           "on fail, half on success. On fail: max HP also reduced by 9 (2d8) until long rest."
       ),
       traits=(
           "Acid Immunity. Immune to acid damage.\n\n"
           "Void Taint. Creatures damaged by this drake's acid emit void energy for 1 minute; "
           "void-tagged UC monsters have advantage on attacks against them.\n\n"
           "Void Form. Resistant to bludgeoning, piercing, and slashing from nonmagical weapons."
       ),
       notes="Void-corrupted Rust Drake, size upgraded to Large. Void version of UC Rust Drake (CR 5).",
       sd="large void-corrupted drake, scales cracked with void energy seeping out, "
          "acid and necrotic vapour from jaws, industrial ruins background, D&D dragon, dark void lighting",
       is_void=1, base_name="UC Rust Drake"),

    _m("UC Void Bile Crawler", "7", "monstrosity", "H",
       ac=14, hp=138, hp_die="12", hp_die_count=12,
       s=18, d=14, co=20, i=3, wi=10, ch=3, pp=10,
       lang="—", speed="30 ft., climb 30 ft.",
       actions=(
           "Multiattack. One Bite and one Acid Spray (if recharged) or Void Maw.\n\n"
           "Bite. Melee Weapon Attack: +8 to hit, reach 10 ft., one target. "
           "Hit: 17 (3d8+4) piercing plus 14 (4d6) acid damage.\n\n"
           "Acid Spray (Recharge 5-6). 30-ft. cone. DC 16 Dex save: 36 (8d8) acid on fail, "
           "half on success. This crawler's acid ignores acid resistance (not immunity).\n\n"
           "Void Maw (Recharge 6). One Medium or smaller grappled creature: DC 16 Str save or "
           "swallowed (blinded, restrained, 14 (4d6) acid per turn). One creature at a time."
       ),
       traits=(
           "Dissolving Grip. Grappled creatures take 9 (2d8) acid at start of their turns.\n\n"
           "Spider Climb.\n\n"
           "Void Acid. Acid damage from this crawler bypasses acid resistance.\n\n"
           "Acid Immunity. Immune to acid damage.\n\n"
           "Void Form. Resistant to bludgeoning, piercing, and slashing from nonmagical weapons."
       ),
       notes="Void-corrupted Bile Crawler, size upgraded to Huge. Void version of UC Bile Crawler (CR 5).",
       sd="huge void-corrupted acid crawler, massive translucent void-bile abdomen, "
          "crackling void energy around carapace, six massive legs, D&D monstrosity, horror lighting",
       is_void=1, base_name="UC Bile Crawler"),

    # =========================================================================
    # CR 6 — 10 regular
    # =========================================================================

    _m("UC Warped Golem", "6", "construct", "L",
       ac=16, hp=104, hp_die="10", hp_die_count=11,
       s=20, d=9, co=18, i=5, wi=9, ch=3, pp=9,
       lang="Understands its creator's language", speed="25 ft.",
       actions=(
           "Multiattack. Two Slam attacks.\n\n"
           "Slam. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. "
           "Hit: 18 (2d12+5) bludgeoning damage.\n\n"
           "Warp Pulse (Recharge 5-6). 20-ft. radius. DC 15 Int save or teleported 30 ft. in a "
           "random direction and takes 16 (3d10) force damage. Half damage, no teleport on success."
       ),
       traits=(
           "Magic Resistance. Advantage on saves vs. spells.\n\n"
           "Immutable Form. Immune to any spell or effect that alters its form.\n\n"
           "Construct Immunities. Immune to poison, psychic, charmed, exhaustion, frightened, "
           "paralyzed, petrified, poisoned."
       ),
       notes="Tower-grown construct corrupted by rift energy exposure.",
       sd="large stone golem with rift cracks glowing, spatial distortion field around it, "
          "Tower Authority runes half-erased, D&D construct, dramatic lighting"),

    _m("UC Echo Wraith", "6", "undead", "M",
       ac=14, hp=78, hp_die="8", hp_die_count=12,
       s=1, d=18, co=15, i=14, wi=14, ch=17, pp=12,
       lang="Any languages known in life", speed="0 ft., fly 60 ft. (hover)",
       actions=(
           "Life Drain. Melee Spell Attack: +7 to hit, reach 5 ft., one creature. "
           "Hit: 25 (4d10+3) necrotic. DC 15 Con save or max HP reduced by amount taken.\n\n"
           "Echo Scream (Recharge 5-6). 60-ft. cone. DC 15 Wis save or frightened 1 minute AND "
           "stunned until end of next turn on fail. Save ends each turn."
       ),
       traits=(
           "Incorporeal Movement. Can move through creatures and objects as difficult terrain; "
           "5 (1d10) force damage if it ends its turn inside a solid object.\n\n"
           "Temporal Echo. When the wraith takes damage from a creature, it echoes half that damage "
           "back to the attacker (no save). Once per round.\n\n"
           "Undead Immunities. Immune to cold, necrotic, poison. Immune to charmed, exhaustion, "
           "frightened, grappled, paralyzed, petrified, poisoned, prone, restrained."
       ),
       notes="Wraith formed from memories trapped in the Dome's echo-archive nodes.",
       sd="glowing spectral wraith, archive data streams visible through translucent form, "
          "haunting screaming face, cyberpunk data environment, D&D undead, cold blue lighting"),

    _m("UC Toxic Shambler", "6", "plant", "L",
       ac=15, hp=114, hp_die="10", hp_die_count=12,
       s=19, d=8, co=18, i=5, wi=10, ch=5, pp=10,
       lang="—", speed="20 ft., swim 20 ft.",
       actions=(
           "Multiattack. Two Slam attacks. If both hit the same Medium or smaller target "
           "the Shambler can attempt to Engulf.\n\n"
           "Slam. Melee Weapon Attack: +7 to hit, reach 10 ft., one target. "
           "Hit: 14 (2d8+5) bludgeoning damage.\n\n"
           "Engulf. Target DC 15 Str save or engulfed: restrained, cannot breathe air, "
           "13 (3d8) poison per turn. Escape DC 15 Str. Up to 2 Medium or 4 Small creatures."
       ),
       traits=(
           "Toxic Spore Cloud. At the start of each of its turns, creatures within 15 ft. must "
           "DC 13 Con save or be Poisoned until start of their next turn.\n\n"
           "Resistances. Resistant to cold, fire, lightning.\n\n"
           "Condition Immunities. Immune to blinded, deafened."
       ),
       notes="Undercity shambling mound variant, toxin-producing sewer plant.",
       sd="massive shambling plant creature, toxic spores billowing, sewer slime coating, "
          "bioluminescent fungal growths, D&D plant monstrosity, dim green lighting"),

    _m("UC Rift Stalker Alpha", "6", "aberration", "L",
       ac=15, hp=102, hp_die="10", hp_die_count=12,
       s=19, d=16, co=16, i=10, wi=14, ch=8, pp=15,
       lang="—", speed="40 ft.",
       actions=(
           "Multiattack. Three Rift Claw attacks. One can be replaced by Phase Pounce if available.\n\n"
           "Rift Claw. Melee Weapon Attack: +7 to hit, reach 10 ft., one target. "
           "Hit: 13 (2d8+4) slashing plus 9 (2d8) psychic damage.\n\n"
           "Phase Pounce (Recharge 5-6). Teleport up to 40 ft. to a visible point, then make a "
           "Rift Claw attack with advantage. On hit: +18 (4d8) psychic and target knocked prone."
       ),
       traits=(
           "Rift Sense. Detects creatures within 60 ft. regardless of hiding.\n\n"
           "Phase Ambush. First round after entering from a rift: advantage on all attacks, "
           "+3d6 psychic on first hit."
       ),
       notes="Pack leader of rift lurkers. Proficient in Perception and Stealth.",
       sd="apex aberrant predator, multiple glowing eyes, rift energy wounds in its body, "
          "pack hunter stance, dark cyberpunk dungeon, D&D aberration, predatory dramatic lighting",
       saves={"wis": 5}),

    _m("UC Syndicate Captain", "6", "humanoid", "M",
       ac=18, hp=90, hp_die="8", hp_die_count=12,
       s=19, d=12, co=16, i=13, wi=14, ch=16, pp=12,
       lang="Common, Thieves' Cant", speed="30 ft.",
       actions=(
           "Multiattack. Three Blade attacks.\n\n"
           "Blade. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. "
           "Hit: 8 (1d8+4) slashing plus 10 (3d6) necrotic damage."
       ),
       traits=(
           "Leadership (1/Day). All allies within 30 ft. add 1d4 to attack rolls and saves "
           "for 1 minute."
       ),
       reactions="Parry. +3 bonus to AC vs. one melee attack per round.",
       bonus_actions=(
           "Commander's Call. One allied creature within 30 ft. makes one weapon attack as "
           "a reaction."
       ),
       notes="Iron Fang Consortium field captain. Usually accompanied by 2-4 Enforcers.",
       sd="commanding mercenary captain, Iron Fang plate armour, necrotic blade glowing, "
          "tactical stance, urban war background, D&D humanoid leader, dramatic lighting",
       saves={"str": 7, "con": 6, "cha": 6}),

    _m("UC Cinder Elemental", "6", "elemental", "M",
       ac=14, hp=90, hp_die="8", hp_die_count=12,
       s=14, d=18, co=16, i=8, wi=12, ch=10, pp=11,
       lang="Ignan", speed="50 ft.",
       actions=(
           "Multiattack. Two Cinder Touch attacks.\n\n"
           "Cinder Touch. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. "
           "Hit: 17 (3d8+4) fire damage. DC 15 Dex save or catch fire: 3 (1d6) ongoing fire "
           "at start of each turn (action to extinguish).\n\n"
           "Cinder Explosion (Recharge 5-6). 20-ft. radius. DC 15 Dex save: 35 (10d6) fire on fail, "
           "half on success. Area heavily obscured with cinder smoke until end of next turn."
       ),
       traits=(
           "Fire Form. Can enter a hostile creature's space; deals 5 (1d10) fire on entry. "
           "Can move through openings as narrow as 1 inch.\n\n"
           "Illumination. Bright light 30 ft., dim 60 ft.\n\n"
           "Fire Immunity. Immune to fire. Resistant to nonmagical bludgeoning, piercing, slashing."
       ),
       notes="Elemental drawn to the Dome's heat vents. Leaves cinder trails distinct from standard fire elementals.",
       sd="humanoid form of swirling cinders and flame, cinder trail behind it, "
          "industrial heat vent background, D&D fire elemental, orange ember lighting"),

    _m("UC Bone Engine", "6", "construct", "M",
       ac=15, hp=85, hp_die="8", hp_die_count=10,
       s=18, d=14, co=20, i=10, wi=11, ch=5, pp=10,
       lang="Understands its creator's language", speed="35 ft.",
       actions=(
           "Multiattack. Two Bone Blade attacks.\n\n"
           "Bone Blade. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. "
           "Hit: 13 (2d8+4) slashing damage.\n\n"
           "Bone Spike (Recharge 5-6). Three targets within a 10-ft. radius, range 60 ft. "
           "DC 15 Dex save: 22 (4d10) piercing on fail, half on success."
       ),
       traits=(
           "Death Burst. When destroyed: creatures within 10 ft. DC 13 Dex save or "
           "13 (2d12) piercing (half on success).\n\n"
           "Construct Resilience. Advantage on saves vs. spells of 4th level or lower.\n\n"
           "Construct Immunities. Immune to poison, psychic, necrotic, charmed, exhaustion, "
           "frightened, paralyzed, petrified, poisoned."
       ),
       notes="Necromantic construct assembled from dungeon remains. Explodes on destruction.",
       sd="skeletal construct warrior, bone blades extending from arms, rune-carved ribs exposed, "
          "necromantic energy pulsing, D&D construct undead fusion, dark dungeon lighting"),

    _m("UC Plague Rat Alpha", "6", "beast", "L",
       ac=13, hp=97, hp_die="10", hp_die_count=13,
       s=18, d=16, co=14, i=4, wi=13, ch=5, pp=14,
       lang="—", speed="30 ft.",
       actions=(
           "Multiattack. One Bite attack. If target is already infected the Plague Rat can "
           "use Plague Swarm instead.\n\n"
           "Bite. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. "
           "Hit: 15 (2d10+4) piercing. DC 14 Con save or diseased: -1d4 to Con saves/checks "
           "for 24 hours (effects stack).\n\n"
           "Plague Swarm (Recharge 5-6). 20-ft. radius. DC 14 Con save or diseased as Bite."
       ),
       traits=(
           "Pack Tactics. Advantage on attacks when an ally is within 5 ft. of the target.\n\n"
           "Alpha Aura. Rat swarms and giant rats within 30 ft. have advantage on attack rolls "
           "while the alpha is alive.\n\n"
           "Keen Smell. Advantage on Perception checks using smell."
       ),
       notes="Mutated alpha of a sewer rat colony. Boss of rat infestations.",
       sd="massive plague rat, matted diseased fur, glowing diseased eyes, "
          "sewer environment, flanked by smaller rats, D&D beast, grim horror lighting"),

    _m("UC Obsidian Lotus Phantom", "6", "undead", "M",
       ac=15, hp=71, hp_die="8", hp_die_count=11,
       s=1, d=20, co=14, i=16, wi=15, ch=18, pp=12,
       lang="Any languages known in life", speed="0 ft., fly 50 ft. (hover)",
       actions=(
           "Mind Pierce. Melee Spell Attack: +7 to hit, reach 5 ft., one creature. "
           "Hit: 21 (3d12+2) psychic damage.\n\n"
           "Memory Theft (Recharge 5-6). One creature within 30 ft.: DC 15 Wis save or one skill "
           "proficiency suppressed for 1 hour. While suppressed the phantom can use that proficiency.\n\n"
           "Corporate Phantasm (1/Day). Takes on exact appearance of one creature seen in past week. "
           "DC 18 Investigation to detect the illusion."
       ),
       traits=(
           "Incorporeal Movement.\n\n"
           "Intelligence Seeker. Knows if any creature within 60 ft. holds information it "
           "considers mission-critical (DM decides).\n\n"
           "Undead Immunities. Immune to cold, necrotic, poison. Immune to charmed, frightened, "
           "grappled, prone, restrained."
       ),
       notes="Ghost of an Obsidian Lotus agent, bound to complete its final mission.",
       sd="translucent corporate assassin ghost, Obsidian Lotus lotus emblem visible through form, "
          "psychic data streams, elegant and terrifying, D&D undead, cold neon cyberpunk lighting"),

    _m("UC Warzone Troll", "6", "giant", "L",
       ac=15, hp=120, hp_die="10", hp_die_count=11,
       s=20, d=12, co=20, i=7, wi=9, ch=7, pp=9,
       lang="Giant, Common", speed="30 ft.",
       actions=(
           "Multiattack. One Bite and two Claw attacks.\n\n"
           "Bite. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. "
           "Hit: 12 (2d6+5) piercing damage.\n\n"
           "Claw. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. "
           "Hit: 12 (2d6+5) slashing damage."
       ),
       traits=(
           "Regeneration. Regains 10 HP at start of its turn unless it took acid or fire damage "
           "since its last turn.\n\n"
           "Warzone Adaptation. Resistant to piercing and slashing damage from nonmagical weapons."
       ),
       notes="Troll variant adapted to Undercity urban warfare zones.",
       sd="scarred urban troll in makeshift armour, battle-worn wounds visibly regenerating, "
          "rubble and warfare background, D&D giant, brutal industrial lighting"),

    # =========================================================================
    # CR 6 → Void versions at CR 8 (5 monsters)
    # =========================================================================

    _m("UC Void Warped Golem", "8", "construct", "H",
       ac=17, hp=168, hp_die="12", hp_die_count=16,
       s=22, d=9, co=18, i=5, wi=9, ch=3, pp=9,
       lang="Understands its creator's language", speed="25 ft.",
       actions=(
           "Multiattack. Three Slam attacks.\n\n"
           "Slam. Melee Weapon Attack: +9 to hit, reach 10 ft., one target. "
           "Hit: 22 (3d10+6) bludgeoning damage.\n\n"
           "Void Warp Pulse (Recharge 5-6). 30-ft. radius. DC 17 Int save or teleported 40 ft. "
           "random direction and takes 27 (5d10) force damage. Half, no teleport on success.\n\n"
           "Void Surge (1/Day). 30-ft. radius. DC 17 Con save: 45 (10d8) force on fail, "
           "half on success. Knocked prone on fail."
       ),
       traits=(
           "Void Core. Resistant to bludgeoning, piercing, and slashing from nonmagical weapons.\n\n"
           "Magic Resistance.\n\n"
           "Immutable Form.\n\n"
           "Construct Immunities."
       ),
       notes="Void-corrupted Warped Golem, size upgraded to Huge. Void version of UC Warped Golem (CR 6).",
       sd="huge void-infused golem, spatial rift cracks covering stone body, "
          "reality warping distortions, Tower runes corrupted, D&D construct, void energy lighting",
       is_void=1, base_name="UC Warped Golem"),

    _m("UC Void Echo Wraith", "8", "undead", "M",
       ac=15, hp=130, hp_die="8", hp_die_count=20,
       s=1, d=19, co=15, i=16, wi=16, ch=19, pp=13,
       lang="Any languages known in life", speed="0 ft., fly 70 ft. (hover)",
       actions=(
           "Multiattack. Two Life Drain attacks.\n\n"
           "Life Drain. Melee Spell Attack: +8 to hit, reach 5 ft., one creature. "
           "Hit: 29 (6d8+2) necrotic. DC 16 Con save or max HP reduced.\n\n"
           "Void Echo Scream (Recharge 5-6). 90-ft. cone. DC 16 Wis save or frightened 1 minute "
           "AND stunned until end of next turn. Save ends each turn.\n\n"
           "Void Echo (1/Day). The wraith splits into 3 copies until start of next turn. "
           "Attacks against it have 2-in-3 chance of hitting a copy (no damage). Copies vanish when hit."
       ),
       traits=(
           "Incorporeal Movement.\n\n"
           "Temporal Echo (x2). Echoes half damage from two separate attacks per round.\n\n"
           "Void Form. Resistant to bludgeoning, piercing, and slashing from nonmagical weapons.\n\n"
           "Undead Immunities. Immune to cold, necrotic, poison and relevant conditions."
       ),
       notes="Void-corrupted Echo Wraith. Void version of UC Echo Wraith (CR 6).",
       sd="void-corrupted wraith splitting into echo copies, archive data corrupted by void energy, "
          "multiple screaming faces in translucent form, D&D undead, void-blue lighting",
       is_void=1, base_name="UC Echo Wraith"),

    _m("UC Void Rift Stalker Alpha", "8", "aberration", "H",
       ac=16, hp=168, hp_die="12", hp_die_count=13,
       s=21, d=17, co=22, i=12, wi=16, ch=8, pp=16,
       lang="—", speed="45 ft.",
       actions=(
           "Multiattack. Four Void Rift Claw attacks.\n\n"
           "Void Rift Claw. Melee Weapon Attack: +8 to hit, reach 15 ft., one target. "
           "Hit: 16 (2d10+5) slashing plus 13 (3d8) psychic damage.\n\n"
           "Void Phase Pounce (Recharge 5-6). Teleport 60 ft., then make two Void Rift Claw "
           "attacks against the same target with advantage. If both hit: DC 17 Con save or "
           "stunned until end of next turn.\n\n"
           "Rift Tear (Recharge 6). 10-ft. rift opens between two points within 60 ft. "
           "Creatures in path: DC 17 Dex save or sucked through, taking 4d12 necrotic per round."
       ),
       traits=(
           "Void Form. Resistant to bludgeoning, piercing, and slashing from nonmagical weapons.\n\n"
           "Rift Sense. Detects all creatures within 120 ft. automatically.\n\n"
           "Phase Ambush. Advantage + extra 3d6 psychic when entering from a rift."
       ),
       notes="Void-corrupted Rift Stalker Alpha, size upgraded to Huge. Void version of UC Rift Stalker Alpha (CR 6).",
       sd="enormous void-corrupted apex predator, multiple glowing void eyes, "
          "rift tears in its massive body, eight-limbed stance, D&D aberration, void dimensional lighting",
       is_void=1, base_name="UC Rift Stalker Alpha",
       saves={"wis": 7, "con": 9}),

    _m("UC Void Cinder Elemental", "8", "elemental", "L",
       ac=15, hp=142, hp_die="10", hp_die_count=15,
       s=16, d=20, co=18, i=8, wi=12, ch=10, pp=11,
       lang="Ignan", speed="60 ft.",
       actions=(
           "Multiattack. Three Void Cinder Touch attacks.\n\n"
           "Void Cinder Touch. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. "
           "Hit: 21 (4d8+3) fire damage. Creatures that take damage can't regain HP until "
           "end of their next turn.\n\n"
           "Void Cinder Explosion (Recharge 5-6). 25-ft. radius. DC 17 Dex save: 52 (8d12) "
           "fire + necrotic on fail, half on success. On fail: DC 14 Con save or blinded 1 round."
       ),
       traits=(
           "Fire Form (enhanced). Deals 10 (2d10) fire on entry into creature's space.\n\n"
           "Void Flame. Fire damage from this elemental prevents HP recovery until end of next turn.\n\n"
           "Fire Immunity. Immune to fire. Resistant to nonmagical bludgeoning, piercing, slashing.\n\n"
           "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons."
       ),
       notes="Void-corrupted Cinder Elemental, size upgraded to Large. Void version of UC Cinder Elemental (CR 6).",
       sd="large void-corrupted cinder elemental, black flame with void energy cores, "
          "necrotic cinder trails, reality-scorching fire, D&D elemental, dark void fire lighting",
       is_void=1, base_name="UC Cinder Elemental"),

    _m("UC Void Warzone Troll", "8", "giant", "H",
       ac=16, hp=184, hp_die="12", hp_die_count=16,
       s=22, d=12, co=20, i=7, wi=9, ch=7, pp=9,
       lang="Giant, Common", speed="30 ft.",
       actions=(
           "Multiattack. One Bite and three Claw attacks.\n\n"
           "Void Bite. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 13 (2d6+6) piercing plus 9 (2d8) necrotic damage.\n\n"
           "Claw. Melee Weapon Attack: +9 to hit, reach 10 ft., one target. "
           "Hit: 13 (2d6+6) slashing damage.\n\n"
           "Void Roar (Recharge 5-6). 30-ft. radius. DC 16 Con save: 35 (10d6) thunder on fail, "
           "half on success. Knocked prone on fail."
       ),
       traits=(
           "Void Regeneration. Regains 15 HP at start of its turn. Only radiant damage interrupts it.\n\n"
           "Warzone Adaptation. Resistant to piercing and slashing from nonmagical weapons.\n\n"
           "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons."
       ),
       notes="Void-corrupted Warzone Troll, size upgraded to Huge. Void version of UC Warzone Troll (CR 6).",
       sd="huge void-corrupted troll, void energy seeping from wounds that don't close, "
          "necrotic aura, battle-scarred massive form, D&D giant, dark void industrial lighting",
       is_void=1, base_name="UC Warzone Troll"),

    # =========================================================================
    # CR 7 — 10 regular
    # =========================================================================

    _m("UC Arcane Leviathan", "7", "aberration", "H",
       ac=16, hp=133, hp_die="12", hp_die_count=14,
       s=22, d=8, co=18, i=16, wi=14, ch=16, pp=15,
       lang="Deep Speech, telepathy 120 ft.", speed="20 ft., swim 50 ft.",
       actions=(
           "Multiattack. Three Tentacle attacks.\n\n"
           "Tentacle. Melee Weapon Attack: +9 to hit, reach 15 ft., one target. "
           "Hit: 15 (2d8+6) bludgeoning. Grappled (escape DC 17). Max 4 tentacles active.\n\n"
           "Arcane Blast. Ranged Spell Attack: +7 to hit, range 90 ft., one creature. "
           "Hit: 28 (4d12+2) force damage. Does not require hands.\n\n"
           "Consume Mind (Recharge 5-6). One grappled creature: DC 16 Int save or 35 (5d12+2) "
           "psychic and stunned 1 round. On fail the leviathan learns its surface thoughts."
       ),
       traits=(
           "Antimagic Aura (1/Day). Once per day can activate a 30-ft. antimagic field for "
           "1 minute as an action.\n\n"
           "Magic Resistance. Advantage on saves vs. spells and magical effects."
       ),
       notes="Ancient aberration that drifts through rift-flooded cisterns beneath the Tower.",
       sd="massive tentacled sea creature, arcane runes glowing on its flesh, "
          "deep flooded cistern environment, eldritch horror aesthetic, D&D aberration, bioluminescent lighting",
       saves={"int": 7, "wis": 6, "cha": 7}),

    _m("UC Death Broker", "7", "undead", "M",
       ac=17, hp=110, hp_die="8", hp_die_count=13,
       s=18, d=16, co=18, i=17, wi=16, ch=18, pp=13,
       lang="All languages known in life, Abyssal", speed="30 ft.",
       actions=(
           "Multiattack. Two Death Scythe attacks.\n\n"
           "Death Scythe. Melee Weapon Attack: +7 to hit, reach 10 ft., one target. "
           "Hit: 14 (2d10+3) necrotic. DC 15 Con save or max HP reduced by amount taken.\n\n"
           "Bargain of Last Breath (1/Day). One concentrating, dying, or death-saving creature: "
           "DC 16 Wis save or automatically fails one death save; broker gains 15 temp HP.\n\n"
           "Soul Bind (Recharge 5-6). One creature within 30 ft.: DC 16 Cha save or bound "
           "1 hour; allies of bound creature can't benefit from healing within 10 ft. of broker."
       ),
       traits=(
           "Life Sense. Knows exact HP and death save count of any creature within 60 ft.\n\n"
           "Undead Resistances. Resistant to cold, nonmagical bludgeoning/piercing/slashing. "
           "Immune to poison, necrotic."
       ),
       notes="Undead entity that literally brokers deals involving life and death. "
             "Found operating in black-market resurrection operations.",
       sd="gaunt undead figure in dark brokerage robes, death scythe trailing soul energy, "
          "ledger of names in hand, D&D undead, cold necrotic neon lighting",
       saves={"wis": 7, "cha": 8}),

    _m("UC Rift Hydra", "7", "monstrosity", "H",
       ac=14, hp=136, hp_die="12", hp_die_count=13,
       s=20, d=11, co=18, i=2, wi=10, ch=5, pp=10,
       lang="—", speed="20 ft., swim 30 ft.",
       actions=(
           "Five Rift Bite attacks (one per head).\n\n"
           "Rift Bite. Melee Weapon Attack: +8 to hit, reach 10 ft., one target. "
           "Hit: 13 (2d8+4) piercing plus 9 (2d8) necrotic damage.\n\n"
           "Phase Breathe (Recharge 6). Each of 5 heads exhales a 15-ft. cone in separate "
           "directions simultaneously. DC 15 Dex save: 27 (6d8) necrotic on fail, half on success."
       ),
       traits=(
           "Multiple Heads (5). Advantage vs. blinded/charmed/deafened/frightened/stunned/"
           "unconscious. Extra reaction per head beyond one.\n\n"
           "Rift Regeneration. Severed heads regrow in 1 round. Regrowth only prevented by "
           "radiant damage (not regular fire/acid).\n\n"
           "Amphibious.\n\n"
           "Void Sense. Detects active rifts within 120 ft. automatically."
       ),
       notes="Rift-energy mutated 5-headed hydra. Regrowth only stopped by radiant damage.",
       sd="five-headed hydra with rift energy crackling between heads, "
          "necrotic bite marks on surroundings, D&D monstrosity, dimensional void horror lighting"),

    _m("UC Vault Guardian", "7", "construct", "L",
       ac=18, hp=123, hp_die="10", hp_die_count=13,
       s=22, d=9, co=18, i=10, wi=14, ch=5, pp=12,
       lang="Understands creator's language", speed="20 ft.",
       actions=(
           "Multiattack. Two Adamantine Slam attacks.\n\n"
           "Adamantine Slam. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 19 (3d8+6) bludgeoning. DC 17 Str save or knocked back 10 ft. and prone.\n\n"
           "Security Protocol (Recharge 5-6). Choose one: Stasis Pulse — 30-ft. radius DC 16 Con "
           "save or Paralyzed 1 round; OR Alarm Shriek — 60-ft., DC 16 Con save or deafened "
           "1 minute + 11 (2d10) thunder."
       ),
       traits=(
           "Magic Resistance.\n\n"
           "Immutable Form.\n\n"
           "False Appearance. Indistinguishable from a metal statue while motionless.\n\n"
           "Vault Ward. While guarding a designated area immune to forced movement.\n\n"
           "Construct Immunities. Immune to poison, psychic and relevant conditions."
       ),
       notes="Adamantine vault guardian construct protecting high-value Tower Authority assets.",
       sd="large adamantine armoured construct guardian, vault door in background, "
          "security runes glowing, imposing stance, D&D construct, cold security lighting"),

    _m("UC Magma Crawler", "7", "elemental", "L",
       ac=15, hp=115, hp_die="10", hp_die_count=10,
       s=20, d=12, co=22, i=6, wi=10, ch=5, pp=10,
       lang="Primordial", speed="30 ft., burrow 20 ft.",
       actions=(
           "Multiattack. Two Magma Claw attacks.\n\n"
           "Magma Claw. Melee Weapon Attack: +8 to hit, reach 10 ft., one target. "
           "Hit: 15 (2d10+4) slashing plus 13 (3d8) fire damage.\n\n"
           "Magma Eruption (Recharge 5-6). Creates a 15-ft. radius magma pool at point within 60 ft. "
           "Entering or starting turn in pool: 33 (6d10) fire. Persists 1 minute. Difficult terrain."
       ),
       traits=(
           "Heated Body. Creatures hitting with melee attacks take 7 (2d6) fire damage.\n\n"
           "Fire Immunity. Immune to fire. Resistant to nonmagical bludgeoning/piercing/slashing.\n\n"
           "Tremorsense 60 ft."
       ),
       notes="Magma elemental drawn up through the Dome's heat infrastructure. "
             "Drawn to the Tower's thermal exhaust vents.",
       sd="magma-covered large elemental crawler, lava dripping from clawed limbs, "
          "industrial heat vent background, D&D elemental, molten orange glow"),

    _m("UC Syndicate Assassin", "7", "humanoid", "M",
       ac=17, hp=90, hp_die="8", hp_die_count=12,
       s=14, d=22, co=16, i=15, wi=15, ch=16, pp=13,
       lang="Common, Thieves' Cant", speed="30 ft.",
       actions=(
           "Multiattack. Four Dagger attacks or two Daggers + one Hand Crossbow.\n\n"
           "Dagger. Melee or Ranged Weapon Attack: +10 to hit, reach 5 ft. or 20/60 ft. "
           "Hit: 8 (1d4+6) piercing plus 21 (6d6) poison damage.\n\n"
           "Nerve Strike (Recharge 5-6). One target within 5 ft.: DC 15 Con save or Paralyzed "
           "1 minute (save ends each turn)."
       ),
       traits=(
           "Sneak Attack (7d6). Once per turn.\n\n"
           "Assassination. On a creature that hasn't taken a turn: always has advantage and "
           "attack is an automatic critical hit.\n\n"
           "Expertise. Stealth +12, Deception +9."
       ),
       bonus_actions="Shadow Slip. Teleport up to 30 ft. to unoccupied dim light or darkness.",
       notes="Top-tier Iron Fang Consortium or Obsidian Lotus hired killer.",
       sd="sleek assassin in shadow-weave armour, poison-coated daggers drawn, "
          "mid-teleport between shadows, D&D rogue, cyberpunk noir dramatic lighting",
       saves={"dex": 10, "wis": 6}),

    _m("UC Undercity Drake", "7", "dragon", "L",
       ac=16, hp=123, hp_die="10", hp_die_count=13,
       s=20, d=14, co=18, i=10, wi=12, ch=10, pp=11,
       lang="Draconic, Common", speed="40 ft., fly 70 ft.",
       actions=(
           "Multiattack. One Bite and two Claw attacks.\n\n"
           "Bite. Melee Weapon Attack: +8 to hit, reach 10 ft., one target. "
           "Hit: 16 (2d10+5) piercing plus 9 (2d8) acid damage.\n\n"
           "Claw. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. "
           "Hit: 12 (2d6+5) slashing damage.\n\n"
           "Undercity Breath (Recharge 5-6). 20-ft. cone. Choose: Acid — DC 15 Dex save, "
           "49 (9d10) acid; or Smoke — DC 15 Con save, 42 (12d6) poison + Poisoned 1 min."
       ),
       traits=(
           "Flyby. Doesn't provoke opportunity attacks when flying out of reach.\n\n"
           "Adapted Senses. Blindsight 30 ft.\n\n"
           "Resistances. Resistant to fire and acid."
       ),
       notes="Drake adapted to the Undercity's industrial sewer-and-air environment.",
       sd="sleek industrial drake, acid-scarred scales, sewer pipe background, "
          "glowing acid breath, D&D dragon, dark fantasy cyberpunk lighting"),

    _m("UC Fungal Colossus", "7", "plant", "H",
       ac=14, hp=157, hp_die="12", hp_die_count=15,
       s=24, d=6, co=18, i=3, wi=10, ch=3, pp=10,
       lang="—", speed="30 ft.",
       actions=(
           "Multiattack. Two Slam attacks.\n\n"
           "Slam. Melee Weapon Attack: +10 to hit, reach 10 ft., one target. "
           "Hit: 24 (3d10+7) bludgeoning plus 9 (2d8) poison damage.\n\n"
           "Toxic Cloud (Recharge 5-6). 30-ft. radius. DC 15 Con save: 35 (10d6) poison + "
           "Poisoned 1 min on fail, half damage, no condition on success."
       ),
       traits=(
           "Spore Carrier. Creatures ending their turn within 10 ft.: DC 13 Con save or Poisoned "
           "until start of next turn.\n\n"
           "Colony Anchor. Infestation creatures within 120 ft. gain +1 to attack and damage rolls.\n\n"
           "Fungal Regeneration. Regains 15 HP at start of its turn unless it took fire damage."
       ),
       notes="Massive fungal creature, anchor of large infestation colonies. "
             "Controlling boss of fungal infestation missions.",
       sd="enormous humanoid fungal colossus, massive mushroom cap head, "
          "spore clouds billowing, sewer environment, D&D plant, bioluminescent horror lighting"),

    _m("UC Warden Juggernaut", "7", "construct", "L",
       ac=19, hp=123, hp_die="10", hp_die_count=13,
       s=22, d=8, co=18, i=10, wi=12, ch=6, pp=11,
       lang="Understands Tower Authority commands", speed="25 ft.",
       actions=(
           "Multiattack. Two Warden Maul attacks.\n\n"
           "Warden Maul. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 20 (4d6+6) bludgeoning. DC 17 Str save or knocked prone.\n\n"
           "Stampede (Recharge 5-6). Move up to 30 ft. in a straight line. Creatures in path: "
           "DC 17 Str save or 28 (4d12) bludgeoning + knocked back 10 ft. and prone.\n\n"
           "Suppression Blast (Recharge 6). 30-ft. cone. DC 16 Con save: 35 (10d6) lightning "
           "on fail, half on success. On fail: can't use reactions until start of next turn."
       ),
       traits=(
           "Siege Monster. Double damage to structures and objects.\n\n"
           "Construct Immunities. Immune to poison, psychic and relevant conditions."
       ),
       notes="Heavy-armour Tower Authority siege construct. Used in district lock-downs.",
       sd="massive armoured juggernaut construct, Tower Authority siege markings, "
          "lightning suppression cannon integrated, D&D construct, industrial military lighting"),

    _m("UC Abyssal Rat", "7", "fiend", "L",
       ac=15, hp=126, hp_die="10", hp_die_count=11,
       s=20, d=17, co=22, i=8, wi=13, ch=10, pp=11,
       lang="Abyssal, understands Common", speed="40 ft., burrow 20 ft.",
       actions=(
           "Multiattack. One Bite and one Gnawing Swarm attack.\n\n"
           "Bite. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. "
           "Hit: 17 (2d12+4) piercing. DC 15 Con save or Poisoned 1 minute.\n\n"
           "Gnawing Swarm. Melee Weapon Attack: +8 to hit, reach 10 ft., one target. "
           "Hit: 14 (3d6+4) piercing. Armoured targets: DC 14 Dex save or armour takes "
           "permanent -1 AC (cumulative, min -3).\n\n"
           "Hellshriek (Recharge 5-6). 40-ft. radius. DC 15 Wis save: frightened 1 min on fail. "
           "On a roll of 1-5 on save: also stunned 1 round."
       ),
       traits=(
           "Devil's Sight. Magical darkness doesn't impede darkvision.\n\n"
           "Magic Resistance. Advantage on saves vs. spells.\n\n"
           "Pack Tactics. Advantage when ally is within 5 ft. of target.\n\n"
           "Resistances. Cold, fire, lightning, nonmagical bludgeoning/piercing/slashing. "
           "Immune to poison."
       ),
       notes="Fiendish rat that slipped through a rift from the Abyss into the Undercity sewers.",
       sd="enormous fiendish rat, abyssal markings on mangy fur, hellfire in eyes, "
          "rift tear visible behind it, D&D fiend, dark abyssal red lighting"),

    # =========================================================================
    # CR 7 → Void versions at CR 9 (5 monsters)
    # =========================================================================

    _m("UC Void Arcane Leviathan", "9", "aberration", "H",
       ac=17, hp=195, hp_die="12", hp_die_count=17,
       s=24, d=8, co=20, i=18, wi=16, ch=16, pp=16,
       lang="Deep Speech, telepathy 120 ft.", speed="20 ft., swim 60 ft.",
       actions=(
           "Multiattack. Four Void Tentacle attacks.\n\n"
           "Void Tentacle. Melee Weapon Attack: +10 to hit, reach 20 ft., one target. "
           "Hit: 17 (2d10+6) bludgeoning plus 9 (2d8) psychic. Grappled (escape DC 18).\n\n"
           "Void Arcane Blast. Ranged Spell Attack: +9 to hit, range 120 ft. "
           "Hit: 45 (10d8) force; target can't cast spells until end of its next turn.\n\n"
           "Void Consume Mind (Recharge 5-6). Grappled creature: DC 18 Int save or 49 (7d12+2) "
           "psychic + stunned 1 round + last 24 hrs memory erased (restored on long rest).\n\n"
           "Mind Web (1/Day). 60-ft. radius. DC 18 Int save or charmed 1 minute; "
           "all affected share surface thoughts with the leviathan."
       ),
       traits=(
           "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons.\n\n"
           "Antimagic Aura (1/Day).\n\n"
           "Magic Resistance."
       ),
       notes="Void-corrupted Arcane Leviathan. Void version of UC Arcane Leviathan (CR 7).",
       sd="massive void-corrupted tentacled leviathan, arcane runes corrupted by void energy, "
          "reality tears around its body, D&D aberration, deep void dimensional lighting",
       is_void=1, base_name="UC Arcane Leviathan",
       saves={"int": 9, "wis": 8, "cha": 9}),

    _m("UC Void Rift Hydra", "9", "monstrosity", "H",
       ac=15, hp=190, hp_die="12", hp_die_count=20,
       s=22, d=11, co=18, i=2, wi=10, ch=5, pp=10,
       lang="—", speed="20 ft., swim 30 ft.",
       actions=(
           "Seven Void Rift Bite attacks (one per head).\n\n"
           "Void Rift Bite. Melee Weapon Attack: +9 to hit, reach 15 ft., one target. "
           "Hit: 15 (2d8+6) piercing plus 13 (3d8) necrotic damage.\n\n"
           "Void Phase Breathe (Recharge 5-6). Seven 20-ft. cones simultaneously. "
           "DC 17 Dex save: 36 (8d8) necrotic on fail plus Blinded 1 round."
       ),
       traits=(
           "Multiple Heads (7). Advantage vs. relevant conditions; extra reactions.\n\n"
           "Void Regeneration. Severed heads regrow in 1 round; only radiant stops regrowth.\n\n"
           "Amphibious.\n\n"
           "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons."
       ),
       notes="Void-corrupted Rift Hydra with 7 heads. Void version of UC Rift Hydra (CR 7).",
       sd="seven-headed void-corrupted hydra, each head crackling with rift energy, "
          "dimensional tears around neck stumps, D&D monstrosity, necrotic dimensional lighting",
       is_void=1, base_name="UC Rift Hydra"),

    _m("UC Void Vault Guardian", "9", "construct", "L",
       ac=19, hp=189, hp_die="10", hp_die_count=18,
       s=24, d=9, co=20, i=10, wi=14, ch=5, pp=12,
       lang="Understands creator's language", speed="20 ft.",
       actions=(
           "Multiattack. Three Void Adamantine Slam attacks.\n\n"
           "Void Adamantine Slam. Melee Weapon Attack: +10 to hit, reach 5 ft., one target. "
           "Hit: 22 (3d10+6) bludgeoning plus 9 (2d8) force. DC 18 Str save or knocked "
           "back 15 ft. and prone.\n\n"
           "Vault Lockdown (Recharge 5-6). 60-ft. radius. DC 18 Dex save or trapped in place "
           "until end of their next turn (can still act, can't move).\n\n"
           "Void Security Protocol (Recharge 6). DC 18 Con save or Paralyzed 2 rounds."
       ),
       traits=(
           "Void Core. Resistant to bludgeoning, piercing, slashing from nonmagical weapons.\n\n"
           "Magic Resistance.\n\n"
           "Immutable Form.\n\n"
           "Construct Immunities."
       ),
       notes="Void-enhanced Vault Guardian. Void version of UC Vault Guardian (CR 7).",
       sd="adamantine construct guardian with void energy integrated into armour, "
          "gravitational distortion field, imposing vault backdrop, D&D construct, cold void lighting",
       is_void=1, base_name="UC Vault Guardian"),

    _m("UC Void Undercity Drake", "9", "dragon", "L",
       ac=17, hp=172, hp_die="10", hp_die_count=15,
       s=22, d=14, co=22, i=10, wi=12, ch=10, pp=11,
       lang="Draconic, Common", speed="40 ft., fly 80 ft.",
       actions=(
           "Multiattack. One Bite and three Claw attacks.\n\n"
           "Void Bite. Melee Weapon Attack: +9 to hit, reach 10 ft., one target. "
           "Hit: 17 (2d12+4) piercing plus 13 (3d8) necrotic plus 9 (2d8) acid.\n\n"
           "Claw. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 13 (2d8+4) slashing.\n\n"
           "Void Undercity Breath (Recharge 5-6). 30-ft. cone. DC 17 Dex save: "
           "60 (11d10) acid + necrotic on fail, half on success. On fail: max HP reduced by "
           "14 (4d6) until long rest."
       ),
       traits=(
           "Flyby.\n\n"
           "Void Taint. Void-tagged UC monsters in 120 ft. have advantage on attacks vs. "
           "targets this drake has hit.\n\n"
           "Resistances. Fire, acid, nonmagical bludgeoning/piercing/slashing."
       ),
       notes="Void-corrupted Undercity Drake. Void version of UC Undercity Drake (CR 7).",
       sd="void-corrupted large drake, scales cracked with void and acid energy, "
          "necrotic vapour breath, Undercity industrial background, D&D dragon, dark void acid lighting",
       is_void=1, base_name="UC Undercity Drake"),

    _m("UC Void Fungal Colossus", "9", "plant", "H",
       ac=15, hp=218, hp_die="12", hp_die_count=23,
       s=26, d=6, co=18, i=3, wi=10, ch=3, pp=10,
       lang="—", speed="30 ft.",
       actions=(
           "Multiattack. Three Void Slam attacks.\n\n"
           "Void Slam. Melee Weapon Attack: +11 to hit, reach 15 ft., one target. "
           "Hit: 28 (3d12+8) bludgeoning plus 13 (3d8) poison plus 9 (2d8) necrotic.\n\n"
           "Void Toxic Cloud (Recharge 5-6). 40-ft. radius. DC 17 Con save: 52 (8d12) poison + "
           "Poisoned 1 minute on fail, half damage, no condition on success. Also: all corpses in "
           "area animate as void zombies (same as zombies but deal extra 3 necrotic on attacks)."
       ),
       traits=(
           "Void Spore Carrier. DC 16 Con save to resist Poisoned for 1 minute (not just 1 turn).\n\n"
           "Void Colony Anchor. Infestation creatures in 120 ft. gain +2 attack and damage.\n\n"
           "Void Regeneration. Regains 20 HP/turn; only fire or radiant interrupts it.\n\n"
           "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons."
       ),
       notes="Void-corrupted Fungal Colossus. Void version of UC Fungal Colossus (CR 7).",
       sd="enormous void-corrupted fungal colossus, spores mixed with void energy, "
          "necrotic mushroom growths, corpses animated in background, D&D plant, dark void bioluminescence",
       is_void=1, base_name="UC Fungal Colossus"),

    # =========================================================================
    # CR 8 — 10 regular
    # =========================================================================

    _m("UC Rift Colossus", "8", "aberration", "H",
       ac=16, hp=157, hp_die="12", hp_die_count=15,
       s=24, d=8, co=18, i=12, wi=14, ch=10, pp=15,
       lang="Deep Speech", speed="30 ft.",
       actions=(
           "Multiattack. Three Rift Slam attacks.\n\n"
           "Rift Slam. Melee Weapon Attack: +10 to hit, reach 15 ft., one target. "
           "Hit: 20 (2d12+7) bludgeoning plus 13 (2d12) psychic damage.\n\n"
           "Rift Rupture (Recharge 5-6). Three rifts open at three points within 90 ft. "
           "Each rift: 10-ft. radius. DC 17 Dex save or pulled 30 ft. toward rift + "
           "27 (6d8) necrotic. Rifts close at start of next turn.\n\n"
           "Void Emanation (1/Day). 60-ft. radius. DC 17 Int save or Confused "
           "(as confusion spell) for 1 minute. Save ends each turn."
       ),
       traits=(
           "Magic Resistance.\n\n"
           "Rift Sense. Detects all creatures within 120 ft. regardless of hiding or invisibility.\n\n"
           "Psychic Resistance. Resistant to psychic damage."
       ),
       notes="Massive aberration born from a large rift collapse. Pulls reality around it.",
       sd="colossal aberrant mass with three simultaneous rift tears, "
          "enormous reaching limbs, reality distortion halo, D&D aberration, dimensional void lighting",
       saves={"con": 8, "wis": 6}),

    _m("UC Iron Fang Lieutenant", "8", "humanoid", "M",
       ac=19, hp=138, hp_die="8", hp_die_count=12,
       s=21, d=12, co=22, i=14, wi=15, ch=18, pp=12,
       lang="Common, Thieves' Cant", speed="30 ft.",
       actions=(
           "Multiattack. Three Longsword attacks and one Syndicate Authority.\n\n"
           "Longsword. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 9 (1d8+5) slashing plus 14 (4d6) necrotic damage.\n\n"
           "Syndicate Authority. One creature within 30 ft.: DC 17 Wis save or Frightened "
           "1 minute AND dropped to 0 initiative until end of next turn."
       ),
       traits=(
           "Legendary Mark (3 uses/day). Reaction: when self or ally within 30 ft. takes damage, "
           "halve that damage.\n\n"
           "Undying Devotion. When reduced to 0 HP: DC 15 Con save to stay at 1 HP (once per combat)."
       ),
       bonus_actions="Command. One ally within 30 ft. has advantage on its next attack roll.",
       notes="Senior Iron Fang Consortium field commander. Controls district-level operations.",
       sd="imposing Iron Fang lieutenant in void-enhanced plate armour, necrotic command aura, "
          "battle scars and insignia, D&D humanoid commander, dark syndicate lighting",
       saves={"str": 9, "con": 10, "wis": 6}),

    _m("UC Bone Cathedral", "8", "undead", "H",
       ac=16, hp=168, hp_die="12", hp_die_count=16,
       s=24, d=7, co=18, i=10, wi=12, ch=6, pp=11,
       lang="Understands all languages but can't speak", speed="20 ft.",
       actions=(
           "Multiattack. Two Bone Crush attacks.\n\n"
           "Bone Crush. Melee Weapon Attack: +10 to hit, reach 10 ft., one target. "
           "Hit: 22 (3d10+6) bludgeoning plus 9 (2d8) necrotic. DC 17 Str save or Grappled "
           "(escape DC 17).\n\n"
           "Osseous Rain (Recharge 5-6). 30-ft. radius. DC 16 Dex save: 45 (10d8) piercing "
           "on fail, half on success. Grappled creatures have disadvantage on this save.\n\n"
           "Raise Bone Minions (1/Day). Raises 2d4 Skeleton CR 1/4 from bone debris nearby."
       ),
       traits=(
           "Necrotic Absorption. When hit by necrotic, regains HP equal to damage instead.\n\n"
           "Bone Reconstruction. Regains 10 HP at start of its turn if it has at least 1 HP.\n\n"
           "Undead Immunities. Immune to poison, necrotic. Resistant to cold, nonmagical B/P/S."
       ),
       notes="Huge undead construct assembled from thousands of bones in old Undercity graveyards.",
       sd="enormous cathedral-like undead construct of interlocking bones, "
          "necromantic energy pulsing through joints, bone rain attack, D&D undead, crypt lighting"),

    _m("UC Storm Engine", "8", "construct", "H",
       ac=17, hp=175, hp_die="12", hp_die_count=14,
       s=24, d=7, co=22, i=12, wi=10, ch=5, pp=10,
       lang="Understands Tower Authority commands", speed="20 ft.",
       actions=(
           "Multiattack. Two Thunder Slam attacks plus one Lightning Bolt.\n\n"
           "Thunder Slam. Melee Weapon Attack: +10 to hit, reach 10 ft., one target. "
           "Hit: 22 (3d10+6) bludgeoning plus 10 (3d6) thunder. DC 18 Str save or knocked prone.\n\n"
           "Lightning Bolt. Ranged Spell Attack: +8 to hit, range 120 ft., one target. "
           "Hit: 28 (8d6) lightning. Ignores cover.\n\n"
           "Tempest Core (Recharge 5-6). 40-ft. radius. DC 17 Con save: 56 (16d6) lightning + "
           "thunder on fail, half on success. All metallic objects in area electrified "
           "(5 lightning damage to anything touching them for 1 round)."
       ),
       traits=(
           "Lightning Absorption. When hit by lightning, regains HP equal to damage taken.\n\n"
           "Siege Monster. Double damage to structures and objects.\n\n"
           "Construct Immunities. Immune to lightning, thunder, poison, psychic."
       ),
       notes="Tower Authority heavy siege construct armed with storm weaponry.",
       sd="massive storm-engine construct, lightning coils integrated into hull, "
          "thunder shockwave visible, Tower Authority siege markings, D&D construct, electric storm lighting"),

    _m("UC Dome Wyrm", "8", "dragon", "H",
       ac=17, hp=178, hp_die="12", hp_die_count=17,
       s=22, d=12, co=18, i=12, wi=12, ch=14, pp=14,
       lang="Draconic, Common", speed="40 ft., fly 80 ft.",
       actions=(
           "Frightful Presence. 120-ft. DC 16 Wis save or Frightened 1 minute.\n\n"
           "Multiattack. Uses Frightful Presence then one Bite and two Claws.\n\n"
           "Bite. Melee Weapon Attack: +9 to hit, reach 10 ft., one target. "
           "Hit: 18 (2d12+5) piercing plus 9 (2d8) lightning damage.\n\n"
           "Claw. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 13 (2d8+4) slashing damage.\n\n"
           "Dome Breath (Recharge 5-6). 30-ft. cone. DC 16 Dex save: 52 (8d12) lightning on fail, "
           "half on success. Creatures in metal armour have disadvantage on this save."
       ),
       traits=(
           "Blindsight 30 ft., Darkvision 120 ft.\n\n"
           "Resistances. Lightning, thunder."
       ),
       notes="Ancient wyrm that nests in the upper Dome architecture, adapted to artificial weather.",
       sd="massive lightning wyrm coiled in dome infrastructure, storm clouds around it, "
          "Tower visible below, D&D dragon, electric storm dramatic lighting"),

    _m("UC Plague Hulk", "8", "monstrosity", "H",
       ac=13, hp=168, hp_die="12", hp_die_count=16,
       s=22, d=8, co=18, i=3, wi=8, ch=3, pp=9,
       lang="—", speed="20 ft.",
       actions=(
           "Multiattack. Two Plague Slam attacks.\n\n"
           "Plague Slam. Melee Weapon Attack: +9 to hit, reach 10 ft., one target. "
           "Hit: 20 (2d12+7) bludgeoning. DC 16 Con save or infected: diseased "
           "(-2 to all attack rolls and saves, stacks, max -6).\n\n"
           "Plague Burst (Recharge 5-6). 30-ft. radius. DC 16 Con save: 49 (9d10) poison "
           "+ infected as Plague Slam on fail.\n\n"
           "Corpse Spawn (Reaction). When a creature dies within 30 ft.: animate it as a zombie "
           "that acts on the hulk's next turn."
       ),
       traits=(
           "Plague Aura. Creatures within 15 ft. at start of their turn: DC 14 Con save or infected.\n\n"
           "Immunities. Immune to poison. Resistant to nonmagical bludgeoning/piercing/slashing."
       ),
       notes="Massive disease-spreading Undercity monstrosity. Turns corpses into zombie minions.",
       sd="enormous rotting hulk, plague boils erupting, zombie hands reaching from its mass, "
          "sewer wasteland background, D&D monstrosity, putrid sickly green horror lighting"),

    _m("UC Void-Touched Berserker", "8", "humanoid", "L",
       ac=15, hp=145, hp_die="10", hp_die_count=10,
       s=24, d=14, co=22, i=6, wi=10, ch=8, pp=10,
       lang="Common", speed="40 ft.",
       actions=(
           "Multiattack. Three Greataxe attacks.\n\n"
           "Greataxe. Melee Weapon Attack: +10 to hit, reach 5 ft., one target. "
           "Hit: 20 (2d12+7) slashing plus 9 (2d8) necrotic damage.\n\n"
           "Void Frenzy (Recharge 5-6). Make 5 Greataxe attacks split among any targets in reach.\n\n"
           "Void Howl (1/Day). 30-ft. radius. DC 16 Wis save or Frightened 1 minute "
           "+ movement speed halved while frightened."
       ),
       traits=(
           "Reckless. On its turn: advantage on all melee attacks until start of next turn, "
           "but attacks against it also have advantage until then.\n\n"
           "Void-Touched Rage. When the berserker drops to half HP it gains +4 to damage rolls "
           "for the rest of the combat.\n\n"
           "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons."
       ),
       notes="Rift-energy-corrupted humanoid berserker. No longer fully in control of itself.",
       sd="massive void-corrupted berserker, void energy cracking through skin, "
          "huge greataxe dripping necrotic, frenzy state, D&D humanoid void fighter, dark dramatic lighting",
       saves={"str": 10, "con": 9}),

    _m("UC Necrotic Shambler", "8", "undead", "L",
       ac=15, hp=157, hp_die="10", hp_die_count=15,
       s=20, d=9, co=20, i=5, wi=10, ch=5, pp=10,
       lang="—", speed="25 ft., swim 20 ft.",
       actions=(
           "Multiattack. Three Necrotic Slam attacks. If all three hit the same target "
           "the Shambler can Engulf.\n\n"
           "Necrotic Slam. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. "
           "Hit: 14 (2d8+5) bludgeoning plus 13 (3d8) necrotic damage.\n\n"
           "Engulf. DC 16 Str save or engulfed: restrained, 21 (3d8 + con mod equivalent) "
           "necrotic per turn. Escape DC 16 Str. Up to 2 Large or 4 Medium simultaneously."
       ),
       traits=(
           "Necrotic Absorption. Takes no necrotic damage; instead regains HP equal to damage.\n\n"
           "Undead Fortitude. When reduced to 0 HP by non-radiant non-critical damage: "
           "DC 5 + damage taken Con save to drop to 1 HP instead.\n\n"
           "Immunities. Immune to poison, necrotic. Resistant to cold, nonmagical B/P/S."
       ),
       notes="Massive undead shambling mound variant, necrotic energy where plants once were.",
       sd="enormous necrotic shambling mound, dead vines and bone fragments in its mass, "
          "necrotic energy pulsing, undead corpse fragments visible, D&D undead plant, death green lighting"),

    _m("UC Tower Seraph", "8", "celestial", "M",
       ac=17, hp=127, hp_die="8", hp_die_count=15,
       s=18, d=18, co=18, i=17, wi=20, ch=20, pp=18,
       lang="All languages, telepathy 120 ft.", speed="30 ft., fly 60 ft.",
       actions=(
           "Multiattack. Two Radiant Blade attacks.\n\n"
           "Radiant Blade. Melee Weapon Attack: +8 to hit, reach 5 ft., one target. "
           "Hit: 9 (1d10+4) slashing plus 18 (4d8) radiant. Undead and fiends take max radiant.\n\n"
           "Divine Verdict (Recharge 5-6). 60-ft. radius. DC 17 Wis save: 56 (16d6) radiant "
           "on fail, half on success. Undead and fiends auto-fail this save."
       ),
       traits=(
           "Truesight 120 ft.\n\n"
           "Magic Resistance. Advantage on saves vs. spells.\n\n"
           "Angelic Weapons. All attacks are magical and deal +4d8 radiant (included).\n\n"
           "Note: This seraph serves Tower Authority and may act against adventurers if ordered.\n\n"
           "Immunities. Immune to radiant, poison. Resistant to nonmagical bludgeoning/piercing/slashing."
       ),
       notes="Divine being bound to Tower Authority service. Neutral or antagonistic depending on orders.",
       sd="radiant angelic figure, Tower Authority seal on breastplate, divine sword raised, "
          "light halo with Tower architecture, D&D celestial, divine cold white dramatic lighting",
       saves={"wis": 9, "cha": 9}),

    _m("UC Acid Cauldron", "8", "ooze", "H",
       ac=8, hp=184, hp_die="12", hp_die_count=16,
       s=22, d=6, co=20, i=1, wi=6, ch=1, pp=8,
       lang="—", speed="20 ft., climb 20 ft., swim 40 ft.",
       actions=(
           "Pseudopod. Melee Weapon Attack: +9 to hit, reach 10 ft., one target. "
           "Hit: 18 (3d8+5) bludgeoning plus 27 (6d8) acid. Nonmagical metal objects hit: "
           "destroyed if below 10 HP.\n\n"
           "Acid Pool (Recharge 5-6). Creates 20-ft. radius acid pool at its location. "
           "Creatures in pool: 49 (9d10) acid per turn. Persists 1 minute.\n\n"
           "Engulf. Moves up to speed through creatures' spaces. Each: DC 17 Str save or engulfed: "
           "blinded, restrained, 56 (16d6) acid/turn. Escape DC 17 Str. One Huge at a time."
       ),
       traits=(
           "Amorphous. Can move through 1-inch spaces.\n\n"
           "Acid Seep. Any nonmagical weapon that hits the cauldron deals 7 (2d6) acid back to "
           "the wielder after each hit.\n\n"
           "Blindsight 60 ft.\n\n"
           "Immunities. Immune to acid, poison. Resistant to cold, fire, nonmagical B/P/S."
       ),
       notes="Enormous acid ooze that formed in industrial waste sumps beneath the Tower.",
       sd="vast translucent acid cauldron ooze, bubbling toxic surface, "
          "dissolved metal and bone visible inside, industrial waste cavern, D&D ooze, sickly acid green lighting"),

    # =========================================================================
    # CR 8 → Void versions at CR 10 (5 monsters)
    # =========================================================================

    _m("UC Void Rift Colossus", "10", "aberration", "H",
       ac=17, hp=218, hp_die="12", hp_die_count=19,
       s=26, d=8, co=20, i=14, wi=16, ch=10, pp=16,
       lang="Deep Speech", speed="30 ft.",
       actions=(
           "Multiattack. Four Void Rift Slam attacks.\n\n"
           "Void Rift Slam. Melee Weapon Attack: +11 to hit, reach 20 ft., one target. "
           "Hit: 24 (2d12+8) bludgeoning plus 18 (4d8) psychic. Grapples target (escape DC 19).\n\n"
           "Void Rift Rupture (Recharge 5-6). Five rifts simultaneously at points within 90 ft. "
           "DC 19 Dex save or pulled 30 ft. + 36 (8d8) necrotic per rift.\n\n"
           "Dimension Collapse (1/Day). 90-ft. radius. DC 19 Int save: 70 (10d12+5) force + "
           "psychic on fail + Stunned 1 round. Half on success."
       ),
       traits=(
           "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons.\n\n"
           "Psychic Resistance. Resistant to psychic damage.\n\n"
           "Magic Resistance.\n\n"
           "Rift Sense. Detects all creatures in 120 ft. regardless of hiding or invisibility."
       ),
       notes="Void-corrupted Rift Colossus. Void version of UC Rift Colossus (CR 8).",
       sd="colossal void-corrupted aberration, five rift tears orbiting it, "
          "reality collapsing around it, dimensional chaos background, D&D aberration, void dimensional collapse lighting",
       is_void=1, base_name="UC Rift Colossus",
       saves={"con": 9, "wis": 8}),

    _m("UC Void Storm Engine", "10", "construct", "H",
       ac=18, hp=230, hp_die="12", hp_die_count=20,
       s=26, d=7, co=24, i=12, wi=10, ch=5, pp=10,
       lang="Understands Tower Authority commands", speed="20 ft.",
       actions=(
           "Multiattack. Three Void Thunder Slam attacks and one Void Lightning Bolt.\n\n"
           "Void Thunder Slam. Melee Weapon Attack: +11 to hit, reach 15 ft., one target. "
           "Hit: 26 (3d12+7) bludgeoning plus 14 (4d6) thunder plus 14 (4d6) void energy.\n\n"
           "Void Lightning Bolt. Ranged Spell Attack: +9 to hit, range 150 ft., one target. "
           "Hit: 45 (10d8) lightning. Does not require line of sight (arcs through terrain).\n\n"
           "Void Tempest Core (Recharge 5-6). 60-ft. radius. DC 19 Con save: "
           "77 (14d10) lightning + thunder on fail, half on success. All metal objects in area "
           "electrified 1 round."
       ),
       traits=(
           "Lightning Absorption. When hit by lightning regains HP equal to damage.\n\n"
           "Void Core. Resistant to bludgeoning, piercing, slashing from nonmagical weapons.\n\n"
           "Siege Monster. Double damage to structures.\n\n"
           "Construct Immunities. Immune to lightning, thunder, poison, psychic."
       ),
       notes="Void-enhanced Storm Engine. Void version of UC Storm Engine (CR 8).",
       sd="colossal void-enhanced storm engine construct, void lightning integrated with storm coils, "
          "reality distortions around its hull, D&D construct, void electric storm lighting",
       is_void=1, base_name="UC Storm Engine"),

    _m("UC Void Dome Wyrm", "10", "dragon", "H",
       ac=18, hp=225, hp_die="12", hp_die_count=18,
       s=24, d=12, co=22, i=14, wi=14, ch=16, pp=14,
       lang="Draconic, Common", speed="40 ft., fly 90 ft.",
       actions=(
           "Frightful Presence. 120-ft. DC 18 Wis save or Frightened 1 minute.\n\n"
           "Multiattack. Frightful Presence then one Bite, three Claws, and one Tail.\n\n"
           "Void Bite. Melee Weapon Attack: +10 to hit, reach 15 ft., one target. "
           "Hit: 19 (2d12+6) piercing plus 18 (4d8) void energy.\n\n"
           "Claw. Melee Weapon Attack: +10 to hit, reach 5 ft. Hit: 14 (2d8+5) slashing.\n\n"
           "Tail. Melee Weapon Attack: +10 to hit, reach 20 ft. Hit: 16 (2d10+5) bludgeoning. "
           "DC 18 Str save or knocked prone.\n\n"
           "Void Dome Breath (Recharge 5-6). 40-ft. cone. DC 18 Dex save: 91 (14d12) "
           "lightning + necrotic on fail, half on success. On fail: target can't regain HP for 1 min."
       ),
       traits=(
           "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons.\n\n"
           "Resistances. Lightning, thunder.\n\n"
           "Blindsight 30 ft., Darkvision 120 ft."
       ),
       notes="Void-corrupted Dome Wyrm. Void version of UC Dome Wyrm (CR 8).",
       sd="colossal void-corrupted wyrm coiling through dome void tears, "
          "void lightning breath, dimensional rifts in its wake, D&D dragon, dark void storm lighting",
       is_void=1, base_name="UC Dome Wyrm"),

    _m("UC Void Plague Hulk", "10", "monstrosity", "H",
       ac=14, hp=230, hp_die="12", hp_die_count=20,
       s=24, d=8, co=20, i=3, wi=8, ch=3, pp=9,
       lang="—", speed="20 ft.",
       actions=(
           "Multiattack. Three Void Plague Slam attacks.\n\n"
           "Void Plague Slam. Melee Weapon Attack: +10 to hit, reach 15 ft., one target. "
           "Hit: 22 (2d14+7) bludgeoning plus 18 (4d8) poison and necrotic. "
           "DC 18 Con save or infected (-3 to all checks/saves, stacks, max -9).\n\n"
           "Void Plague Burst (Recharge 5-6). 40-ft. radius. DC 18 Con save: 70 (10d12+5) "
           "poison + void on fail, half on success. All corpses in area animate as void zombies "
           "(zombies that deal +3 necrotic on their attacks).\n\n"
           "Void Corpse Spawn (Reaction). When a creature dies within 30 ft.: "
           "animate it as a void zombie."
       ),
       traits=(
           "Plague Aura. DC 14 Con save at start of turn within 15 ft. or infected.\n\n"
           "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons.\n\n"
           "Immunities. Immune to poison."
       ),
       notes="Void-corrupted Plague Hulk. Void version of UC Plague Hulk (CR 8).",
       sd="colossal void-corrupted plague hulk, void and plague energy merged, "
          "void zombie horde emerging from its mass, D&D monstrosity, toxic void green horror lighting",
       is_void=1, base_name="UC Plague Hulk"),

    _m("UC Void Tower Seraph", "10", "celestial", "M",
       ac=18, hp=175, hp_die="8", hp_die_count=27,
       s=20, d=20, co=14, i=20, wi=24, ch=22, pp=20,
       lang="All languages, telepathy 120 ft.", speed="30 ft., fly 80 ft.",
       actions=(
           "Multiattack. Three Void Radiant Blade attacks.\n\n"
           "Void Radiant Blade. Melee Weapon Attack: +9 to hit, reach 5 ft., one target. "
           "Hit: 9 (1d10+4) slashing plus 27 (6d8) radiant. On hit vs. undead/fiends: "
           "DC 18 Wis save or Banished for 1 minute.\n\n"
           "Void Divine Verdict (Recharge 5-6). 90-ft. radius. DC 19 Wis save: 84 (24d6) "
           "radiant on fail, half on success. Void creatures (is_void) take extra 27 (6d8) radiant.\n\n"
           "Divine Wrath (1/Day). 60-ft. line. DC 19 Dex save or 70 (20d6) radiant. Undead/fiends "
           "below 100 HP: DC 19 Wis save or destroyed."
       ),
       traits=(
           "Truesight 120 ft.\n\n"
           "Magic Resistance.\n\n"
           "Void Angelic Weapons. All attacks magical, deal +4d8 radiant.\n\n"
           "Void Seraph Aura. Void creatures within 30 ft. take 14 (4d6) radiant at start of "
           "their turns.\n\n"
           "Immunities. Immune to radiant, poison. Resistant to nonmagical bludgeoning/piercing/slashing."
       ),
       notes="Void-corrupted Tower Seraph — whether this is corruption or evolution is unclear. "
             "Void version of UC Tower Seraph (CR 8).",
       sd="radiant seraph partially consumed by void energy, divine light and dark void intertwined, "
          "Tower Authority seal cracked, D&D celestial void hybrid, divine void dramatic lighting",
       is_void=1, base_name="UC Tower Seraph",
       saves={"wis": 11, "cha": 10}),
]


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

INSERT_SQL = """
INSERT IGNORE INTO monsters (
    name, cr, creature_type, size,
    ac, hp, hp_die, hp_die_count,
    stat_str, stat_dex, stat_con, stat_int, stat_wis, stat_cha,
    passive_perc, languages, speed,
    actions, traits, reactions, bonus_actions,
    legendary_actions, mythic_actions, lair_actions,
    saves_json, notes, sd_appearance,
    source, is_void, base_name
) VALUES (
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s
)
"""


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


def main():
    print("Creating monsters table if not exists...")
    raw_execute(CREATE_TABLE)
    print("Table ready.")

    existing = {r["name"] for r in (raw_query("SELECT name FROM monsters") or [])}
    print(f"Existing rows: {len(existing)}")

    ok = skip = fail = 0
    for m in MONSTERS:
        if m["name"] in existing:
            skip += 1
            continue
        if insert_monster(m):
            print(f"  + {m['name']} (CR {m['cr']}, {'VOID' if m['is_void'] else 'regular'})")
            ok += 1
        else:
            fail += 1

    total = raw_query("SELECT COUNT(*) AS n FROM monsters")[0]["n"]
    print(f"\nDone. Inserted {ok}, skipped {skip}, failed {fail}. Total rows: {total}")

    # Summary by CR
    by_cr = raw_query(
        "SELECT cr, is_void, COUNT(*) AS n FROM monsters "
        "WHERE source='undercity' GROUP BY cr, is_void ORDER BY cr+0, is_void"
    ) or []
    print("\nUndercity monsters by CR:")
    for row in by_cr:
        tag = "void" if row["is_void"] else "regular"
        print(f"  CR {row['cr']} {tag}: {row['n']}")


if __name__ == "__main__":
    main()
