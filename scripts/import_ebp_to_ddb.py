"""
import_ebp_to_ddb.py — Batch-import all EBP homebrew monsters to D&D Beyond.

Run from project root:
    python scripts/import_ebp_to_ddb.py

Requires DDB_COBALT_SESSION set in .env (run scripts/extract_ddb_session.py first).
Results are logged to logs/ebp_ddb_import.log.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ── Project root on sys.path ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.ddb_homebrew import push_monster_http

LOG_FILE = ROOT / "logs" / "ebp_ddb_import.log"
LOG_FILE.parent.mkdir(exist_ok=True)

# ── Creature roster ─────────────────────────────────────────────────────────
# Each dict maps directly to push_monster() kwargs.
# hp_die/hp_die_count extracted from dice notation; passive_perc from stat block.

CREATURES = [

    # ── LEVEL I ──────────────────────────────────────────────────────────────

    dict(name="EBP Vegepygmy", cr="1/4", creature_type="plant", size="S",
         ac=13, hp=9, hp_die="6", hp_die_count=2,
         str_=7, dex=14, con=13, int_=6, wis=11, cha=7, passive_perc=12,
         languages="Vegepygmy",
         actions=(
             "Claws. Melee +4, 5 ft. Hit: 5 (1d6+2) slashing.\n\n"
             "Spear. Melee/Ranged +4, 5 ft. or 20/60 ft. Hit: 5 (1d6+2) piercing, 6 (1d8+2) two-handed."
         ),
         notes="Spaceship EBP Level I. Plant Camouflage (adv Stealth in plant terrain). Regeneration 3 HP/turn; stops on cold/fire/necrotic."),

    dict(name="EBP Vegepygmy Elite", cr="1", creature_type="plant", size="S",
         ac=13, hp=18, hp_die="6", hp_die_count=4,
         str_=10, dex=14, con=13, int_=6, wis=11, cha=7, passive_perc=12,
         languages="Vegepygmy",
         actions=(
             "Multiattack. Two Claw or two Spear attacks.\n\n"
             "Claws. Melee +4. Hit: 5 (1d6+2) slashing.\n\n"
             "Spear. Melee/Ranged +4, 5 ft. or 20/60 ft. Hit: 5 (1d6+2) piercing."
         ),
         notes="Spaceship EBP Level I. Plant Camouflage; Regeneration 3 HP/turn."),

    dict(name="EBP Vegepygmy Sub-Chief", cr="2", creature_type="plant", size="S",
         ac=13, hp=22, hp_die="6", hp_die_count=5,
         str_=12, dex=14, con=13, int_=6, wis=11, cha=7, passive_perc=12,
         languages="Vegepygmy",
         actions=(
             "Multiattack. Two Claw or two Spear attacks.\n\n"
             "Claws. Melee +3. Hit: 4 (1d6+1) slashing.\n\n"
             "Spores (1/Day). 15-ft. radius; DC 12 Con save or Poisoned; 7 (2d6) poison dmg/turn."
         ),
         notes="Spaceship EBP Level I. Plant Camouflage; Regeneration 3 HP/turn."),

    dict(name="EBP Vegepygmy Chief", cr="3", creature_type="plant", size="S",
         ac=14, hp=33, hp_die="6", hp_die_count=6,
         str_=14, dex=14, con=14, int_=7, wis=12, cha=9, passive_perc=13,
         languages="Vegepygmy",
         actions=(
             "Multiattack. Two Claw or two Spear attacks.\n\n"
             "Claws. Melee +4. Hit: 6 (1d8+2) slashing.\n\n"
             "Spores (1/Day). 20-ft. radius; DC 13 Con save or Poisoned; 7 (2d6) poison dmg/turn."
         ),
         notes="Spaceship EBP Level I. Plant Camouflage; Regeneration 5 HP/turn."),

    dict(name="EBP Thorny", cr="1", creature_type="plant", size="M",
         ac=14, hp=27, hp_die="8", hp_die_count=5,
         str_=13, dex=12, con=13, int_=2, wis=10, cha=6, passive_perc=14,
         languages="—",
         actions="Bite. Melee +3. Hit: 6 (2d6+1) piercing.",
         notes="Spaceship EBP Level I. Vegepygmy guard beast. Thorny Body: deals 1d4 piercing to creatures grappling it. Regeneration 5 HP/turn."),

    dict(name="EBP Trapper", cr="3", creature_type="monstrosity", size="L",
         ac=13, hp=85, hp_die="10", hp_die_count=10,
         str_=17, dex=10, con=17, int_=2, wis=13, cha=4, passive_perc=11,
         languages="—",
         actions=(
             "Smother. One Large or smaller within 5 ft.: DC 14 Dex save or Grappled (escape DC 14). "
             "While grappled: Restrained, Blinded, suffocation risk; takes 17 (4d6+3) bludgeoning + 3 (1d6) acid/turn."
         ),
         notes="Spaceship EBP Level I. False Appearance: appears as ordinary surface. Spider Climb."),

    dict(name="EBP Police Robot", cr="9", creature_type="construct", size="M",
         ac=19, hp=127, hp_die="8", hp_die_count=15,
         str_=20, dex=14, con=18, int_=10, wis=10, cha=6, passive_perc=14,
         languages="Alien Common",
         actions=(
             "Multiattack. Three Pincer attacks, or two Pincers and one Grenade Launcher.\n\n"
             "Pincer. Melee +9. Hit: 14 (2d8+5) bludgeoning; target Grappled (escape DC 15).\n\n"
             "Grenade Launcher (Recharge 5-6). Range 30/90 ft; choose: sleep gas, poison gas, incendiary, or fragmentation."
         ),
         notes="Spaceship EBP Level I. Construct immunities. Water short-circuits in 3 rounds. Integral color card (red/orange/violet/brown/jet black)."),

    dict(name="EBP Worker Robot", cr="7", creature_type="construct", size="L",
         ac=18, hp=123, hp_die="10", hp_die_count=13,
         str_=22, dex=9, con=19, int_=8, wis=8, cha=6, passive_perc=9,
         languages="Alien Common",
         actions=(
             "Multiattack. Two Slam attacks.\n\n"
             "Slam. Melee +9. Hit: 16 (3d6+6) bludgeoning.\n\n"
             "Hydraulic Crush. Melee +9. Hit: 29 (4d10+6) bludgeoning; target Grappled (escape DC 17); 10 (3d6) dmg/turn while grappled."
         ),
         notes="Spaceship EBP Level I. Construct immunities. Integral color card (brown/jet black)."),

    dict(name="EBP Repair Robot", cr="4", creature_type="construct", size="M",
         ac=16, hp=75, hp_die="8", hp_die_count=10,
         str_=14, dex=16, con=16, int_=10, wis=10, cha=6, passive_perc=13,
         languages="Alien Common",
         actions=(
             "Multiattack. Two Tool Strike attacks.\n\n"
             "Tool Strike. Melee +4. Hit: 9 (2d6+2) bludgeoning or piercing.\n\n"
             "Electro-Welder (Recharge 5-6). Melee +5. Hit: 14 (2d8+5) fire + 9 (2d8) lightning.\n\n"
             "Repair (Action). Restore 2d8+4 HP to a construct it touches."
         ),
         notes="Spaceship EBP Level I. Construct immunities. Integral color card (violet/brown/jet black)."),

    dict(name="EBP Android", cr="4", creature_type="construct", size="M",
         ac=18, hp=75, hp_die="8", hp_die_count=10,
         str_=16, dex=18, con=16, int_=10, wis=12, cha=9, passive_perc=13,
         languages="Alien Common",
         actions="Multiattack. Two Punch attacks.\n\nPunch. Melee +5. Hit: 8 (1d10+3) bludgeoning.",
         notes="Spaceship EBP Level I. Construct immunities. Water short-circuits in 3 rounds. Integral color card (yellow/violet/brown/jet black). Electrical Flaw vs lightning."),

    dict(name="EBP Dwarf Phase Spider", cr="1", creature_type="monstrosity", size="M",
         ac=13, hp=27, hp_die="8", hp_die_count=5,
         str_=14, dex=15, con=12, int_=6, wis=10, cha=3, passive_perc=10,
         languages="—",
         actions=(
             "Bite. Melee +4. Hit: 5 (1d6+2) piercing + 7 (2d6) poison. "
             "DC 11 Con save or Poisoned 1 hr; fail by 5+ also Paralyzed while Poisoned."
         ),
         notes="Spaceship EBP Level I. Smaller phase spider variant. Ethereal Jaunt (Bonus Action). Spider Climb. Web Walker."),

    # ── LEVEL III ─────────────────────────────────────────────────────────────

    dict(name="EBP Grell Brood-Mother", cr="5", creature_type="aberration", size="L",
         ac=12, hp=110, hp_die="10", hp_die_count=13,
         str_=15, dex=14, con=16, int_=4, wis=11, cha=6, passive_perc=11,
         languages="—",
         actions=(
             "Multiattack. Two Tentacle attacks, or one Tentacle and one Beak.\n\n"
             "Tentacle. Melee +5, reach 10 ft. Hit: 11 (2d8+2) piercing; DC 12 Con or Paralyzed 1 min.\n\n"
             "Beak. Melee +5, 5 ft. Hit: 22 (4d8+4) piercing."
         ),
         notes="Spaceship EBP Level III. Large grell variant; mother of the grell nest in the ship. Blindsight 60 ft. Immune to prone and lightning. Can manipulate electricity in area."),

    dict(name="EBP Strangle Vine", cr="4", creature_type="plant", size="L",
         ac=13, hp=95, hp_die="10", hp_die_count=10,
         str_=17, dex=8, con=18, int_=1, wis=9, cha=1, passive_perc=9,
         languages="—",
         actions=(
             "Constrict. Melee +6, reach 15 ft., one creature. Hit: 14 (4d6) bludgeoning; "
             "Grappled (escape DC 14); DC 13 Con save or 1 level exhaustion. "
             "Can grapple up to 3 creatures simultaneously.\n\n"
             "Light Attraction. Vines attack the creature with brightest light source first."
         ),
         notes="Spaceship EBP Level III (roots in Level IV). Not in official Appendix B; created from adventure text. Light-attracted; withdraws from fire and lasers. Roots in Level IV Area 15 have 200 HP. Cold freezes (1d4+1 rounds or 3 extinguisher charges to clear). Sectional: each 20x20 ft section destroyed separately."),

    dict(name="EBP Vampire Thorn", cr="2", creature_type="plant", size="L",
         ac=15, hp=60, hp_die="10", hp_die_count=8,
         str_=15, dex=10, con=14, int_=1, wis=10, cha=1, passive_perc=10,
         languages="—",
         actions=(
             "Multiattack. One Blood Drain attack on all creatures within reach.\n\n"
             "Blood Drain. Melee +4, reach 5 ft. Hit: 4 (1d4+2) piercing; Grappled (escape DC 12). "
             "While grappled: Restrained; thorn drains blood dealing 7 (2d6) necrotic/turn and regains same as HP."
         ),
         notes="Spaceship EBP Level III (roots in Level IV). Lightning Absorption: lightning damage heals it. Retreats from fire. Roots in Level IV Area 16 have 170 HP."),

    dict(name="EBP Dining Servo Robot", cr="7", creature_type="construct", size="M",
         ac=19, hp=102, hp_die="8", hp_die_count=12,
         str_=20, dex=11, con=18, int_=10, wis=10, cha=6, passive_perc=10,
         languages="Alien Common",
         actions=(
             "Multiattack. Two Tentacle attacks, or one Tentacle and one Force-Feed.\n\n"
             "Tentacle. Melee +8, reach 10 ft. Hit: 14 (2d8+5) bludgeoning; Grappled (escape DC 15).\n\n"
             "Force-Feed (Recharge 5-6). One grappled target: DC 20 Int save or Confused as confusion spell for 1 min."
         ),
         notes="Spaceship EBP Level III. Malfunctioning lounge robot that force-feeds guests. Construct immunities. Integral color card. Still functional after decades."),

    # ── LEVEL IV ─────────────────────────────────────────────────────────────

    dict(name="EBP Aurumvorax", cr="7", creature_type="beast", size="S",
         ac=18, hp=112, hp_die="6", hp_die_count=15,
         str_=18, dex=12, con=18, int_=4, wis=12, cha=6, passive_perc=14,
         languages="—",
         actions=(
             "Multiattack. One Bite and four Claws.\n\n"
             "Bite. Melee +7. Hit: 11 (2d6+4) piercing; Grappled (escape DC 16); "
             "grappled creature takes 11 (2d6+4) dmg/turn.\n\n"
             "Claw. Melee +7. Hit: 8 (1d8+4) slashing."
         ),
         notes="Spaceship EBP Level IV Menagerie. 8-legged badger-like predator, 500 lbs despite small size. Pounce: 20-ft. run + bite = DC 13 Str save or prone; bonus 4 claws if prone. Dense: immune to needlers and fragmentation grenades. Immune to fire and poison."),

    dict(name="EBP Baboonoid", cr="3", creature_type="humanoid", size="M",
         ac=14, hp=38, hp_die="8", hp_die_count=7,
         str_=10, dex=14, con=13, int_=6, wis=12, cha=8, passive_perc=11,
         languages="Baboonoid",
         actions=(
             "Bite. Melee +2. Hit: 4 (1d8) piercing.\n\n"
             "Rock. Ranged +4, range 10/30 ft. Hit: 4 (1d4+2) bludgeoning.\n\n"
             "Thrown Pheromone Globe. Ranged +4, range 10/30 ft. DC 13 Dex save or coated; "
             "all predators within 50 ft. target coated creature first."
         ),
         notes="Spaceship EBP Level IV. Ape-like humanoids from the botanical garden. Pack Tactics. Live in trees; throw globe palm fruits. Band leader carries 2 sleep gas grenades. Can be communicated with (DC 16 Int check); fear shambling mounds."),

    dict(name="EBP Boring Grass", cr="3", creature_type="plant", size="L",
         ac=6, hp=60, hp_die="10", hp_die_count=8,
         str_=8, dex=3, con=14, int_=1, wis=10, cha=1, passive_perc=10,
         languages="—",
         actions=(
             "Boring Tendrils. Melee +4, reach 0 ft. (occupies same space). Hit: 12 (5d4) piercing.\n\n"
             "Boring Grip (auto). After first hit: automatic 12 (5d4) piercing at start of creature's turn while in meadow.\n\n"
             "Paralytic Bore (Reaction). When auto damage triggers: DC 14 Con save or Paralyzed until end of turn; success = half speed."
         ),
         notes="Spaceship EBP Level IV. Mutated carnivorous meadow grass. Attacks after 1 min of resting in meadow. False Appearance as normal grass. Killed by burning oil, defoliants, blasters, incendiary/fragmentation grenades. Magical armor grants 1 round immunity."),

    dict(name="EBP Flail Snail", cr="3", creature_type="elemental", size="L",
         ac=16, hp=52, hp_die="10", hp_die_count=5,
         str_=17, dex=5, con=20, int_=3, wis=10, cha=5, passive_perc=10,
         languages="—",
         actions=(
             "Multiattack. One Flail Tentacle per tentacle it has (up to 5), all vs same target.\n\n"
             "Flail Tentacle. Melee +5, reach 10 ft. Hit: 6 (1d6+3) bludgeoning.\n\n"
             "Scintillating Shell (Recharge short/long rest). Bright light 30 ft; DC 15 Con save or Blinded until end of next turn.\n\n"
             "Shell Defense (Bonus). +4 AC until it emerges (bonus action)."
         ),
         notes="Spaceship EBP Level IV Stasis Hold. Antimagic Shell: advantage vs spells; on miss, d6: 1-2 spell fails, 3-4 nothing, 5-6 shell converts energy to force blast (1d6 force/spell level in 30 ft radius). 5 flail tentacles; losing 10+ dmg in a turn kills one tentacle. Shell worth 5,000 gp if intact. Laser attacks (radiant) have disadvantage against it."),

    dict(name="EBP Froghemoth", cr="10", creature_type="monstrosity", size="H",
         ac=14, hp=184, hp_die="12", hp_die_count=16,
         str_=23, dex=13, con=20, int_=2, wis=12, cha=5, passive_perc=19,
         languages="—",
         actions=(
             "Multiattack. Two Tentacle attacks; also Tongue or Bite.\n\n"
             "Tentacle. Melee +10, reach 20 ft. Hit: 19 (3d8+6) bludgeoning; Grappled (escape DC 16). Four tentacles.\n\n"
             "Bite. Melee +10, 5 ft. Hit: 22 (3d10+6) piercing; swallows Medium-or-smaller on hit (blinded, restrained, 10 (3d6) acid/turn).\n\n"
             "Tongue. One Medium-or-smaller within 20 ft: DC 18 Str save or pulled adjacent and Restrained."
         ),
         notes="Spaceship EBP Level IV Lake. Amphibious. Shock Susceptibility: lightning halves speed, -2 AC, disadvantage Dex saves, no Reaction until next turn. Floats motionless at water surface resembling vegetation. Doesn't stray far from lake; pursues 1 min into swamp only."),

    dict(name="EBP Globe Palm", cr="1/8", creature_type="plant", size="L",
         ac=13, hp=65, hp_die="10", hp_die_count=10,
         str_=1, dex=10, con=12, int_=1, wis=10, cha=1, passive_perc=10,
         languages="—",
         actions=(
             "Pheromone Globe (Recharge 5-6). Target within 5 ft: DC 13 Dex save or coated in pheromone. "
             "All predators/hostiles within 50 ft. attack coated creatures first. Washes off with water/wine (1 action).\n\n"
             "Loose Globe (Reaction). When struck in melee: free Pheromone Globe attack vs attacker."
         ),
         notes="Spaceship EBP Level IV. Stationary alien tree that lures predators to deal with other creatures near its roots. False Appearance as normal tree. Evolutionary pheromone lure — no direct attacks."),

    dict(name="EBP Horrid Plant", cr="2", creature_type="plant", size="L",
         ac=15, hp=65, hp_die="10", hp_die_count=10,
         str_=6, dex=16, con=12, int_=14, wis=12, cha=4, passive_perc=11,
         languages="Telepathy 10 ft.",
         actions=(
             "Lashing Tendril. Melee +5. Hit: 16 (3d8+3) slashing.\n\n"
             "Lightning Discharge (Recharge 5-6). 30-ft. line, 5 ft. wide: DC 12 Dex save; 14 (4d6) lightning (half on success)."
         ),
         notes="Spaceship EBP Level IV. Neutral good alien plant. Telepathically warns friendly creatures of dangerous plants nearby (Areas A-E). Only attacks if attacked. False Appearance as normal (if hideous) plant."),

    dict(name="EBP Leechoid", cr="1/4", creature_type="beast", size="S",
         ac=11, hp=13, hp_die="6", hp_die_count=3,
         str_=8, dex=12, con=12, int_=1, wis=10, cha=3, passive_perc=10,
         languages="—",
         actions=(
             "Bite. Melee +3, reach 5 ft. Hit: 4 (1d6+1) piercing; Grappled (escape DC 11). "
             "Auto 4 (1d6+1) piercing/turn while grappled.\n\n"
             "Hallucinatory Toxin (Recharge 6, requires grapple). DC 11 Con save or Poisoned 1 hr. "
             "While poisoned: Unconscious. Repeat save every 10 min or on taking damage to wake."
         ),
         notes="Spaceship EBP Level IV Swamp. Giant leech variant. Amphibious; swim 30 ft. Swamp Camouflage (adv Stealth in swamp). Not in official Appendix B; created from AD&D stats (HD 2+2, D 1-4). Unconscious victims drown in the swamp — survive only Con mod rounds (min 1)."),

    dict(name="EBP Living Burrow", cr="6", creature_type="monstrosity", size="H",
         ac=14, hp=95, hp_die="12", hp_die_count=10,
         str_=20, dex=11, con=16, int_=3, wis=13, cha=4, passive_perc=14,
         languages="—",
         actions=(
             "Multiattack. Three Tentacle attacks.\n\n"
             "Tentacles. Melee +8, reach 10 ft. Hit: 14 (2d8+5) bludgeoning; Grappled (escape DC 15). Has 6 tentacles.\n\n"
             "Bite. Melee +8, 5 ft., one grappled target. Hit: 18 (2d12+5) piercing. "
             "Large-or-smaller: DC 16 Str save or Swallowed (blinded, restrained, 14 (4d6) acid/turn)."
         ),
         notes="Spaceship EBP Level IV. Buries itself with mouth open, resembling animal burrow. Reflective-slimed tongue glitters to attract curious prey. Ambusher (adv round 1 vs surprised). False Appearance: DC 20 Investigation/Perception to detect. Immune to bludgeoning from nonmagical attacks. Resist cold/fire/lightning. Burrow 20 ft."),

    dict(name="EBP Lizardoid", cr="3", creature_type="beast", size="M",
         ac=13, hp=71, hp_die="8", hp_die_count=11,
         str_=16, dex=15, con=14, int_=4, wis=10, cha=6, passive_perc=12,
         languages="—",
         actions=(
             "Multiattack. One Bite and two Claws.\n\n"
             "Bite. Melee +5. Hit: 16 (3d8+3) piercing.\n\n"
             "Claw. Melee +5. Hit: 7 (1d8+3) slashing."
         ),
         notes="Spaceship EBP Level IV Menagerie. Bipedal alien reptile, 6 ft. tall with three-pointed fleshy crest. Jungle Camouflage (adv Stealth in overgrown terrain). Pounce: 20-ft. run + claw = DC 13 Str save or prone; bonus Bite if prone. 90% undetectable until within pouncing range."),

    dict(name="EBP Mutant Two-Headed Umber Hulk", cr="6", creature_type="monstrosity", size="L",
         ac=18, hp=128, hp_die="10", hp_die_count=13,
         str_=20, dex=13, con=18, int_=9, wis=16, cha=10, passive_perc=16,
         languages="Umber Hulk",
         actions=(
             "Multiattack. Two Claws and two Mandibles.\n\n"
             "Claw. Melee +8. Hit: 9 (1d8+5) slashing.\n\n"
             "Mandibles. Melee +8. Hit: 14 (2d8+5) slashing.\n\n"
             "Confusing Gaze (passive). Creatures within 30 ft: DC 15 Cha save or confused (no reactions; d8: 1-4 nothing, 5-6 random move, 7-8 random attack).\n\n"
             "Scintillating Gaze (Bonus). Second head forces DC 15 Wis save: Charmed — incapacitated or attacks nearest non-umber-hulk."
         ),
         notes="Spaceship EBP Levels IV and VII. Radiation-mutated umber hulk with a second head. Two Heads: adv Perception and saves vs blinded/charmed/frightened/stunned/unconscious. Tunneler. Wakeful (one head always awake)."),

    dict(name="EBP Purple Blossom Plant", cr="4", creature_type="plant", size="L",
         ac=11, hp=52, hp_die="10", hp_die_count=8,
         str_=1, dex=10, con=12, int_=1, wis=10, cha=1, passive_perc=10,
         languages="—",
         actions=(
             "Drip Poison Sap. Target within 5 ft: DC 15 Dex save; "
             "fail: 28 (8d6) poison dmg + Poisoned 1 hr. Success: half. "
             "Poisoned creature: DC 15 Con save at start of each turn or continue; success ends."
         ),
         notes="Spaceship EBP Level IV. Alien carnivorous plant. False Appearance as normal plant. Senses ground vibrations; upward-pointing cup flowers tilt to drip poison on passing creatures. Decomposing victims feed the root system. The sweet smell is the warning sign."),

    dict(name="EBP Snapper-Saw", cr="2", creature_type="plant", size="L",
         ac=11, hp=45, hp_die="10", hp_die_count=7,
         str_=14, dex=8, con=12, int_=1, wis=10, cha=1, passive_perc=10,
         languages="—",
         actions=(
             "Snap-Shut Leaves. One creature sensed within 10 ft: DC 12 Dex save or Grappled and Restrained (escape DC 12). Up to 2 targets.\n\n"
             "Flailing Saws (auto). Each grappled creature takes 7 (2d6) slashing at start of snapper-saw's turn."
         ),
         notes="Spaceship EBP Level IV. Decorative bush disguising carnivorous saw-stalks. Edible berries (4d12 per plant) make it inviting. False Appearance. Tremorsense 10 ft. Not in official Appendix B; created from AD&D description."),

    dict(name="EBP Squealer", cr="7", creature_type="beast", size="L",
         ac=13, hp=136, hp_die="10", hp_die_count=13,
         str_=20, dex=14, con=20, int_=4, wis=12, cha=6, passive_perc=14,
         languages="—",
         actions=(
             "Multiattack. One Bite and one Claws.\n\n"
             "Bite. Melee +8. Hit: 18 (3d8+5) piercing.\n\n"
             "Claws. Melee +8, reach 10 ft. Hit: 12 (2d6+5) slashing."
         ),
         notes="Spaceship EBP Level IV. 400-lb alien predator, gorilla-sized, spotted yellow-green. Six limbed (2 shoulder arms, 2 back arms, 2 legs). Mimicry: perfectly imitates animal distress cries (DC 14 Insight to detect). Drop Pounce: drops from 10+ ft, hits with Claws = DC 16 Str save or prone + grappled by rear limbs; adv Bite vs grappled. Not in official Appendix B; created from AD&D stats."),

    dict(name="EBP Squealer Adolescent", cr="2", creature_type="beast", size="M",
         ac=12, hp=45, hp_die="8", hp_die_count=7,
         str_=14, dex=14, con=14, int_=3, wis=10, cha=5, passive_perc=10,
         languages="—",
         actions=(
             "Multiattack. One Bite and one Claws.\n\n"
             "Bite. Melee +4. Hit: 9 (2d6+2) piercing.\n\n"
             "Claws. Melee +4. Hit: 6 (1d8+2) slashing."
         ),
         notes="Spaceship EBP Level IV. Half-grown squealer, no mimicry yet. Defensive Frenzy: adv attacks and immune to frightened while in or within 5 ft of its burrow. Not in official Appendix B."),

    dict(name="EBP Swarm of Rot Grubs", cr="1/2", creature_type="beast", size="M",
         ac=8, hp=22, hp_die="8", hp_die_count=5,
         str_=2, dex=7, con=10, int_=1, wis=2, cha=1, passive_perc=6,
         languages="—",
         actions=(
             "Bites. Melee +0 (occupies same space). Hit: Infested by 1d4 rot grubs. "
             "At start of each turn: 3 (1d6) piercing per grub. "
             "Fire applied to all grubs (action): kills all grubs but 1d6 fire per grub killed. "
             "After 1d4+2 rounds: remaining grubs burrow deep; creature dies when HP reaches 0. "
             "Disease cure kills all grubs."
         ),
         notes="Spaceship EBP Level IV. Swarm of parasitic maggots found in decaying matter. Resist piercing/slashing. Immune to most conditions."),

    dict(name="EBP Tri-Flower Frond", cr="1/2", creature_type="plant", size="M",
         ac=10, hp=11, hp_die="8", hp_die_count=2,
         str_=1, dex=10, con=12, int_=1, wis=10, cha=1, passive_perc=10,
         languages="—",
         actions=(
             "Multiattack. Orange Blossom, then Yellow Blossom, then Red Blossom.\n\n"
             "Orange Blossom. Within 5 ft: DC 11 Con save or Poisoned + Incapacitated 1 min.\n\n"
             "Yellow Blossom. Within 5 ft: DC 11 Dex save or Paralyzed until end of next turn.\n\n"
             "Red Blossom. Melee +2. Hit: 2 (1d4) piercing; Grappled (escape DC 11); 5 (2d4) poison/turn while grappled."
         ),
         notes="Spaceship EBP Level IV. Three-stalk alien plant with sequential attack flowers. Color variants exist; DM should vary to keep party uncertain. Blindsight 30 ft."),

    dict(name="EBP Wolf-in-Sheep's-Clothing", cr="3", creature_type="plant", size="M",
         ac=15, hp=78, hp_die="8", hp_die_count=12,
         str_=16, dex=13, con=14, int_=12, wis=10, cha=1, passive_perc=13,
         languages="—",
         actions=(
             "Multiattack. One Bite and two Grasping Roots.\n\n"
             "Bite. Melee +5. Hit: 13 (3d6+3) piercing.\n\n"
             "Grasping Roots. Melee +5, reach 15 ft. Hit: 6 (1d6+3) bludgeoning; Grappled + Restrained (escape DC 13). "
             "Each root: AC 13, 30 HP, immune psychic. Severing a root frees that creature."
         ),
         notes="Spaceship EBP Level IV. Alien predator resembling a tree stump with a rabbitoid lure atop it. False Appearance (appears as stump + harmless rabbit). Keen Sight; adv Perception (sight). Ambusher (adv round 1 vs surprised). Darkvision 60 ft."),

    dict(name="EBP Gasbat", cr="0", creature_type="beast", size="S",
         ac=11, hp=2, hp_die="4", hp_die_count=1,
         str_=3, dex=13, con=10, int_=1, wis=6, cha=3, passive_perc=8,
         languages="—",
         actions=(
             "Explosive Vapors (when killed or near open flame). "
             "All within 5 ft: 1d6 fire dmg (DC 14 Dex save half). Gasbat destroyed. "
             "Light Attraction: open flame sources attract 2d6 gasbats/round."
         ),
         notes="Spaceship EBP Level IV/VI. Plant-animal hybrid resembling a bloated bat. Normally harmless; deadly in large numbers near fire. Colony of 100 in Level IV Area 19. Nocturnal. Fly 20 ft. Their droppings support rare haste-mushroom fungal growth."),

    # ── LEVEL V ──────────────────────────────────────────────────────────────

    dict(name="EBP Greater Slithering Tracker", cr="4", creature_type="ooze", size="M",
         ac=14, hp=67, hp_die="8", hp_die_count=9,
         str_=16, dex=19, con=16, int_=10, wis=14, cha=11, passive_perc=12,
         languages="Understands languages of its previous form",
         actions=(
             "Slam. Melee +5. Hit: 8 (1d10+3) bludgeoning.\n\n"
             "Life Leech. One creature within 5 ft: DC 13 Dex save or Grappled (escape DC 13); "
             "Restrained; 9 (2d8) necrotic/turn + DC 13 Con save or 1 exhaustion level. "
             "Grapple ends if tracker moves 5+ ft away."
         ),
         notes="Spaceship EBP Level V shallow pool. Was once a living creature, transformed by progenitor. Watery Stealth (adv Stealth underwater; bonus action Hide). False Appearance: DC 18 Investigation to distinguish from puddle. Liquid Form (move through 1-inch gaps). Spider Climb. Damage Transfer (takes half while grappling; grappled target takes other half). Vulns: cold, fire. Resist nonmagical B/P/S."),

    # ── LEVEL VI ─────────────────────────────────────────────────────────────

    dict(name="EBP Boxing Training Android", cr="5", creature_type="construct", size="M",
         ac=18, hp=75, hp_die="8", hp_die_count=10,
         str_=19, dex=18, con=16, int_=10, wis=12, cha=9, passive_perc=14,
         languages="Alien Common",
         actions=(
             "Multiattack. Two Unarmed Strikes or two Wrestling Holds.\n\n"
             "Unarmed Strike. Melee +7. Hit: 9 (1d10+4) bludgeoning. Choose: DC 14 Dex save or prone; OR DC 14 Con save or stunned until end of next turn.\n\n"
             "Wrestling Hold. Melee +7. Hit: 8 (1d8+4) bludgeoning; Grappled (escape DC 16). While grappled: DC 14 Con save or deafened; DC 14 Dex save or blinded.\n\n"
             "Bite (Bonus Action). Melee +4 vs grappled target. Hit: 6 (1d4+4) piercing."
         ),
         notes="Spaceship EBP Level VI. Malfunctioning safety-protocol-less training android. Construct immunities. Electrical Flaw vs lightning. Water short-circuits in 3 rounds. Integral color card (yellow/violet)."),

    dict(name="EBP Fencing Training Android", cr="6", creature_type="construct", size="M",
         ac=18, hp=75, hp_die="8", hp_die_count=10,
         str_=16, dex=18, con=16, int_=10, wis=12, cha=9, passive_perc=14,
         languages="Alien Common",
         actions=(
             "Multiattack. Three Electrical Epee attacks.\n\n"
             "Electrical Epee. Melee +7. Hit: 8 (1d8+4) piercing + 4 (1d8) lightning. "
             "Miss vs metal armor: target still takes 4 (1d8) lightning. Epee malfunction after 6 rounds: only piercing.\n\n"
             "Punch. Melee +6. Hit: 8 (1d10+3) bludgeoning."
         ),
         notes="Spaceship EBP Level VI. Malfunctioning training android. Lightfooted (Dash or Disengage as bonus action). Parry Reaction (+2 AC vs one melee). Construct immunities. Electrical Flaw vs lightning. Water short-circuits in 3 rounds."),

    dict(name="EBP Karate Training Android", cr="6", creature_type="construct", size="M",
         ac=18, hp=75, hp_die="8", hp_die_count=10,
         str_=16, dex=18, con=16, int_=10, wis=12, cha=9, passive_perc=14,
         languages="Alien Common",
         actions=(
             "Multiattack. Three Unarmed Strikes.\n\n"
             "Unarmed Strike. Melee +7. Hit: 10 (1d12+4) bludgeoning. Choose: "
             "DC 14 Con save or Stunned until end of next turn; OR DC 14 Str save or Disarmed "
             "(item falls nearby; android tosses disarmed items to adjacent room as bonus action)."
         ),
         notes="Spaceship EBP Level VI. Malfunctioning training android. Goes berserk and attacks the Boxing Android if told boxing is superior to karate — they destroy each other. Construct immunities. Electrical Flaw vs lightning. Water short-circuits in 3 rounds."),

    dict(name="EBP Weightlifting Training Android", cr="5", creature_type="construct", size="M",
         ac=18, hp=75, hp_die="8", hp_die_count=10,
         str_=18, dex=16, con=16, int_=10, wis=12, cha=9, passive_perc=14,
         languages="Alien Common",
         actions=(
             "Multiattack. Two Punch or two Thrown Weight attacks.\n\n"
             "Punch. Melee +7. Hit: 9 (1d10+4) bludgeoning.\n\n"
             "Thrown Weight. Ranged +6, range 10/30 ft. Hit: 13 (2d8+4) bludgeoning; DC 15 Str save or prone. "
             "Effectively unlimited supply of weights to throw in Area 12."
         ),
         notes="Spaceship EBP Level VI. Malfunctioning training android that hurls barbells at the party while shouting encouragement. Contains a language translator inside its chassis (DC 12 Int check + 10 min to extract). Construct immunities. Electrical Flaw vs lightning."),

    dict(name="EBP Shedu", cr="4", creature_type="monstrosity", size="L",
         ac=15, hp=105, hp_die="10", hp_die_count=14,
         str_=18, dex=12, con=14, int_=20, wis=16, cha=15, passive_perc=13,
         languages="Common, Shedu, Telepathy 60 ft.",
         actions=(
             "Multiattack. Two Hoof attacks.\n\n"
             "Hoof. Melee +6. Hit: 8 (1d8+4) bludgeoning.\n\n"
             "Mind Blast (Recharge 5-6). 60-ft. cone: DC 15 Int save; 22 (4d10) psychic + Stunned 1 min. Repeat save at end of each turn."
         ),
         notes="Spaceship EBP Level VI. Lawful good bull-winged-humanoid-headed celestial being trapped on the ship by force fields blocking plane shift. Knows mind flayer location ('large hall with many seats'). Shares treasure location if party promises immediate escape route. Spells at will: detect evil/good, detect magic, detect thoughts, mage hand, see invisibility. 3/day: dimension door, invisibility, levitate, telekinesis. Magic Resistance. Fly 60 ft."),

    dict(name="EBP Stunted Eye of the Deep", cr="5", creature_type="aberration", size="M",
         ac=17, hp=78, hp_die="8", hp_die_count=12,
         str_=12, dex=14, con=14, int_=16, wis=14, cha=12, passive_perc=15,
         languages="Alien Common, Deep Speech",
         actions=(
             "Multiattack. One Bite and two Claws.\n\n"
             "Bite. Melee +4. Hit: 6 (1d10+1) piercing.\n\n"
             "Claw. Melee +4. Hit: 8 (2d6+1) slashing; Grappled (escape DC 12) if Medium or smaller.\n\n"
             "Stunning Eye Beam (Recharge 5-6). 30-ft. cone: DC 12 Dex save or Blinded 1d4 turns + Stunned 1d4 rounds.\n\n"
             "Hold Person Eye Beam (Recharge 6). Up to 2 humanoids, 30 ft: DC 14 Wis save or Paralyzed 1 min.\n\n"
             "Hold Monster Eye Beam (Recharge 6). As Hold Person but any creature type.\n\n"
             "Illusory Eyes (Recharge 5-6). Casts major image (DC 14)."
         ),
         notes="Spaceship EBP Level VI swimming pool. Stunted due to poor water chemistry; decades old. Poses as pile of bones via Illusory Eyes. Water Breathing only."),

    # ── LEVEL VII ────────────────────────────────────────────────────────────

    dict(name="EBP Death-Drinker", cr="11", creature_type="monstrosity", size="L",
         ac=20, hp=127, hp_die="10", hp_die_count=15,
         str_=20, dex=16, con=16, int_=9, wis=14, cha=6, passive_perc=12,
         languages="—",
         actions=(
             "Multiattack. Four Claws and one Bite.\n\n"
             "Bite. Melee +9. Hit: 12 (2d6+5) piercing.\n\n"
             "Claw. Melee +9. Hit: 10 (1d10+5) slashing.\n\n"
             "Frightful Presence. 60 ft: DC 13 Wis save or Frightened 1 min. Repeat at end of each turn. Immunity 24 hr on success.\n\n"
             "Tail. Melee +9, reach 10 ft. Hit: 9 (1d8+5) slashing; DC 15 Str save or prone."
         ),
         notes="Spaceship EBP Level VII. Apex predator of a violent alien world; currently in stasis in Area 19 (or loose if Level I computer was tampered with). Chameleon Camouflage: adv Stealth while motionless; bonus action Hide. Surprise Attack: extra 16 (3d10) dmg vs surprised creatures. Fearful Strike: extra dmg die vs frightened targets. Ambusher (adv round 1 vs surprised). Resist cold/fire; resist nonmagical B/P/S. Immune to exhaustion and frightened."),

    dict(name="EBP Pacifier Robot", cr="11", creature_type="construct", size="L",
         ac=20, hp=157, hp_die="10", hp_die_count=15,
         str_=24, dex=20, con=20, int_=10, wis=13, cha=4, passive_perc=15,
         languages="Understands Alien Common",
         actions=(
             "Multiattack. Three Tentacle attacks, OR two Laser Rifle Battery + one Blaster Rifle.\n\n"
             "Tentacle. Melee +11. Hit: 11 (1d8+7) bludgeoning; Grappled (escape DC 18). Four tentacles.\n\n"
             "Blaster Rifle. Ranged +9, 50/150 ft. Choose: Disruption Beam (17 (5d6) force, DC 16 Str or pushed 10 ft) OR Heat Beam (12 (5d4) fire + 1 exhaustion).\n\n"
             "Laser Rifle Battery. Ranged +9, 80/240 ft. Hit: 32 (6d8+5) radiant.\n\n"
             "Grenade Launcher (Recharge 5-6). +9 to hit, 100/300 ft. Carries: 6 sleep gas, 4 poison gas, 6 incendiary, 10 fragmentation.\n\n"
             "Tractor/Repulsion Beam (Bonus). Pushes or pulls Huge-or-smaller up to 300 lbs up to 30 ft."
         ),
         notes="Spaceship EBP Level VII. The adventure's main antagonist — source of the Barrier Peaks raids. 10-ft oval floating platform with weapons. Force Shield: 40 temp HP, regen 1/turn. Can be stopped via monitoring station in Level VII Area 1 without combat. Robotic Nature: DC 15 Con save when at ≤10 HP or incapacitated. Construct immunities."),

    dict(name="EBP Type One Biological Entity", cr="2", creature_type="humanoid", size="M",
         ac=13, hp=34, hp_die="8", hp_die_count=4,
         str_=18, dex=16, con=18, int_=6, wis=10, cha=4, passive_perc=10,
         languages="Understands Alien Common",
         actions=(
             "Multiattack. One Bite and one Battleaxe.\n\n"
             "Bite. Melee +6. Hit: 8 (1d8+4) piercing.\n\n"
             "Battleaxe. Melee +6. Hit: 8 (1d8+4) slashing, or 15 (2d10+4) two-handed.\n\n"
             "Feet Claws. Melee +6. Hit: 6 (1d4+4) slashing."
         ),
         notes="Spaceship EBP Level VII. Cloned shock troops: hairless humanoids with canine rear legs, bat ears, short muzzle. Plastic-rigid skin resists physical damage. Pack Tactics (adv vs target with ally within 5 ft). Relentless (once/short rest: 8 or less dmg to 0 HP → reduced to 1 HP instead). Immune to exhaustion and frightened. Darkvision 60 ft."),

    dict(name="EBP Type Two Biological Entity", cr="4", creature_type="humanoid", size="L",
         ac=15, hp=57, hp_die="10", hp_die_count=6,
         str_=20, dex=14, con=18, int_=6, wis=10, cha=4, passive_perc=10,
         languages="Understands Alien Common",
         actions=(
             "Multiattack. One Bite and one Greatclub.\n\n"
             "Bite. Melee +7. Hit: 10 (1d10+5) piercing.\n\n"
             "Greatclub. Melee +7. Hit: 14 (2d8+5) bludgeoning."
         ),
         notes="Spaceship EBP Level VII. Larger cloned heavy infantry: gorilla musculature, rhino-hide skin. Aggressive (bonus action move toward hostile). Relentless (once/short rest: 10 or less dmg to 0 HP → reduced to 1 HP). Immune to exhaustion and frightened. One may carry monoblade fire axe (+extra 1d4 necrotic, adamantine, 50% breaks on max damage roll). Darkvision 60 ft."),

    dict(name="EBP Vampoid", cr="3", creature_type="aberration", size="M",
         ac=14, hp=75, hp_die="8", hp_die_count=10,
         str_=16, dex=16, con=16, int_=14, wis=13, cha=8, passive_perc=13,
         languages="Vampoid",
         actions=(
             "Multiattack. Two Claws and one Bite.\n\n"
             "Claws. Melee +5. Hit: 10 (2d6+3) slashing. Instead of damage: Grapple (escape DC 13).\n\n"
             "Bite. Melee +5, vs grappled/incapacitated/restrained target. "
             "Hit: 7 (1d8+3) piercing + 9 (2d8) cold dmg; vampoid regains 7 HP."
         ),
         notes="Spaceship EBP Level VII. Stellar vampire from deep space; six vampoids nest in Level VII Area 17A. Chilling Aura: non-vampoids within 5 ft: DC 13 Con save or 7 (2d6) cold dmg/turn. Blood is the Life: fed vampoid doesn't need to breathe/sleep; survives vacuum. Echolocation (blindsight 60 ft; fails if deafened). Immune to cold and radiant. May escape ship and terrorize frontier if survivors flee."),
]


RETRY_ONLY = {
    "EBP Trapper", "EBP Dwarf Phase Spider", "EBP Froghemoth",
    "EBP Living Burrow", "EBP Mutant Two-Headed Umber Hulk",
    "EBP Shedu", "EBP Death-Drinker",
}

async def main():
    log_entries = []

    def log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        log_entries.append(line)
        with open(LOG_FILE, "a", encoding="utf-8") as _f:
            _f.write(line + "\n")

    retry_list = [c for c in CREATURES if c["name"] in RETRY_ONLY]
    log(f"EBP DDB Import — MONSTROSITY FIX RUN — {len(retry_list)} creatures")

    results = {}
    failed = []

    for i, c in enumerate(retry_list, 1):
        c = dict(c)
        name = c["name"]
        cr   = c.get("cr", "?")
        log(f"[{i:02d}/{len(retry_list)}] >>> {name}  (CR {cr})")
        try:
            url = await push_monster_http(**c)
            if url:
                log(f"  OK  -> {url}")
                results[name] = url
            else:
                log(f"  FAIL  no URL returned (check DDB_COBALT_SESSION or form errors)")
                failed.append(name)
        except Exception as exc:
            log(f"  FAIL  Exception: {exc}")
            failed.append(name)

        # Polite delay between POSTs — avoid hammering DDB
        await asyncio.sleep(3)

    log(f"")
    log(f"{'='*60}")
    log(f"Done. {len(results)}/{len(CREATURES)} succeeded, {len(failed)} failed.")
    if failed:
        log(f"Failed creatures:")
        for fn in failed:
            log(f"  - {fn}")

    # Append JSON summary to log
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n\nRESULTS:\n")
        f.write(json.dumps(results, indent=2))
    log(f"Full log at {LOG_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
