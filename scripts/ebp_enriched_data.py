"""
ebp_enriched_data.py — Full trait/reaction/legendary/lair/speed data for all 49 EBP creatures.

Actions for each creature are already submitted to DDB and are NOT duplicated here.
This file provides: traits, bonus_actions, reactions, legendary_actions, mythic_actions,
lair_actions, notes, speeds, and saves (for creatures with proficient saves).
"""

ENRICHED = {

    # ─────────────────────────────────────────────────────────────────────────
    # LEVEL I CREATURES
    # ─────────────────────────────────────────────────────────────────────────

    "EBP Vegepygmy": {
        "traits": (
            "Plant Camouflage. The vegepygmy has advantage on Dexterity (Stealth) "
            "checks made in terrain with ample plant life.\n\n"
            "Regeneration. The vegepygmy regains 3 hit points at the start of its turn. "
            "If the vegepygmy takes cold, fire, or necrotic damage, this trait doesn't "
            "function at the start of the vegepygmy's next turn. The vegepygmy dies only "
            "if it starts its turn with 0 hit points and doesn't regenerate."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Tribal fungal humanoids that proliferate in the ship's overgrown botanical "
            "sections. Their regeneration makes low-damage weapons nearly useless against them."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Vegepygmy Elite": {
        "traits": (
            "Plant Camouflage. The vegepygmy elite has advantage on Dexterity (Stealth) "
            "checks made in terrain with ample plant life.\n\n"
            "Regeneration. The vegepygmy elite regains 3 hit points at the start of its "
            "turn. If the vegepygmy elite takes cold, fire, or necrotic damage, this trait "
            "doesn't function at the start of the vegepygmy elite's next turn. The vegepygmy "
            "elite dies only if it starts its turn with 0 hit points and doesn't regenerate."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "A more powerful warrior caste of vegepygmy that leads small raiding parties. "
            "Shares the same regenerative biology as common vegepygmies."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Vegepygmy Sub-Chief": {
        "traits": (
            "Plant Camouflage. The vegepygmy sub-chief has advantage on Dexterity (Stealth) "
            "checks made in terrain with ample plant life.\n\n"
            "Regeneration. The vegepygmy sub-chief regains 3 hit points at the start of its "
            "turn. If the vegepygmy sub-chief takes cold, fire, or necrotic damage, this trait "
            "doesn't function at the start of the vegepygmy sub-chief's next turn. The "
            "vegepygmy sub-chief dies only if it starts its turn with 0 hit points and doesn't "
            "regenerate."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Mid-ranking tribal officer who enforces the chief's will and commands squad-level "
            "engagements. Slightly larger than common vegepygmies with distinctive spore markings."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Vegepygmy Chief": {
        "traits": (
            "Plant Camouflage. The vegepygmy chief has advantage on Dexterity (Stealth) "
            "checks made in terrain with ample plant life.\n\n"
            "Regeneration. The vegepygmy chief regains 5 hit points at the start of its turn. "
            "If the vegepygmy chief takes cold, fire, or necrotic damage, this trait doesn't "
            "function at the start of the vegepygmy chief's next turn. The vegepygmy chief "
            "dies only if it starts its turn with 0 hit points and doesn't regenerate."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Commands the vegepygmy tribe and knows the location of the ship's botanical "
            "gardens. Its enhanced regeneration makes it far more durable than common kin."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Thorny": {
        "traits": (
            "Thorny Body. At the start of its turn, any creature grappling the thorny takes "
            "2 (1d4) piercing damage.\n\n"
            "Regeneration. The thorny regains 5 hit points at the start of its turn. If the "
            "thorny takes cold, fire, or necrotic damage, this trait doesn't function at the "
            "start of the thorny's next turn. The thorny dies only if it starts its turn with "
            "0 hit points and doesn't regenerate."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "A mobile, thorn-covered plant creature that serves as a guard beast for "
            "vegepygmy tribes. Grapplers quickly learn to keep their distance."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Trapper": {
        "traits": (
            "False Appearance. While the trapper remains motionless on a floor, ceiling, or "
            "wall, it is indistinguishable from an ordinary surface.\n\n"
            "Spider Climb. The trapper can climb difficult surfaces, including upside down on "
            "ceilings, without needing to make an ability check."
        ),
        "bonus_actions": "",
        "reactions": (
            "Collapse. When a creature on the trapper ends its movement, the trapper can use "
            "its reaction to make a Smother attack against that creature. The target must "
            "succeed on a DC 14 Dexterity saving throw or be smothered."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "A predatory ambush creature that blends seamlessly with walls, floors, and ceilings. "
            "Most victims die before realizing they stepped on a living thing."
        ),
        "speeds": [(1, 10), (3, 10)],
        "saves": {},
    },

    "EBP Police Robot": {
        "traits": (
            "Construct Immunities. The police robot is immune to poison and psychic damage, "
            "and to the charmed, exhaustion, frightened, paralyzed, petrified, and poisoned "
            "conditions.\n\n"
            "Antimagic Susceptibility. The police robot is incapacitated while in the area of "
            "an antimagic field. If targeted by dispel magic, the robot must succeed on a "
            "Constitution saving throw against the caster's spell save DC or be stunned for "
            "1 minute.\n\n"
            "Water Short-Circuit. If the police robot is submerged in water for 3 or more "
            "consecutive rounds, it becomes incapacitated until it is repaired.\n\n"
            "Integral Color Card. The police robot carries color-coded authorization cards "
            "(red, orange, violet, brown, and jet black). These cards interface with the "
            "ship's access control systems, locking or unlocking doors, bulkheads, and "
            "restricted areas."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": (
            "The police robot can take 3 legendary actions, choosing from the options below. "
            "Only one legendary action option can be used at a time and only at the end of "
            "another creature's turn. The police robot regains spent legendary actions at the "
            "start of its turn.\n\n"
            "Move. The police robot moves up to half its speed.\n\n"
            "Pincer Strike. The police robot makes one Pincer attack.\n\n"
            "Targeting System. The police robot recharges one expended attack option."
        ),
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The most dangerous mobile patrol unit on the ship. Its integral color card — "
            "including jet black authorization — is a major treasure and unlocks virtually "
            "every system aboard."
        ),
        "speeds": [(1, 30)],
        "saves": {"constitution": 6, "wisdom": 4},
    },

    "EBP Worker Robot": {
        "traits": (
            "Construct Immunities. The worker robot is immune to poison and psychic damage, "
            "and to the charmed, exhaustion, frightened, paralyzed, petrified, and poisoned "
            "conditions.\n\n"
            "Overload. If the worker robot is reduced to 0 hit points by lightning damage, "
            "it explodes before being destroyed. Each creature within 10 feet of it must "
            "succeed on a DC 15 Dexterity saving throw, taking 21 (6d6) lightning damage on "
            "a failed save, or half as much damage on a successful one."
        ),
        "bonus_actions": "",
        "reactions": (
            "Brace. When a creature moves to a space within the worker robot's reach, the "
            "worker robot can use its reaction to make one Slam attack against that creature."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Mindlessly executes its last programmed orders and cannot deviate without "
            "receiving new instructions. If ordered to move cargo, it will attempt to do "
            "so even if the cargo bay is occupied by adventurers."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Repair Robot": {
        "traits": (
            "Construct Immunities. The repair robot is immune to poison and psychic damage, "
            "and to the charmed, exhaustion, frightened, paralyzed, petrified, and poisoned "
            "conditions.\n\n"
            "Combat Medic. When the repair robot uses its Repair action on an ally that has "
            "fewer than half its hit point maximum, the Repair action is a bonus action instead "
            "of an action."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Prioritizes repairing damaged constructs over engaging in combat. A savvy party "
            "can exploit this behavior to keep a repair robot occupied while dealing with "
            "more dangerous robots."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Android": {
        "traits": (
            "Construct Immunities. The android is immune to poison and psychic damage, and "
            "to the charmed, exhaustion, frightened, paralyzed, petrified, and poisoned "
            "conditions.\n\n"
            "Electrical Flaw. When the android takes lightning damage, it must succeed on a "
            "DC 13 Constitution saving throw or be stunned until the end of its next turn.\n\n"
            "Water Short-Circuit. If the android is submerged in water for 3 or more "
            "consecutive rounds, it becomes incapacitated until it is repaired."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The most human-like robots aboard the ship, some were assigned to work alongside "
            "biological crew. Their uncanny resemblance to living beings makes them unsettling "
            "to encounter in the ship's dark corridors."
        ),
        "speeds": [(1, 35)],
        "saves": {},
    },

    "EBP Dwarf Phase Spider": {
        "traits": (
            "Spider Climb. The dwarf phase spider can climb difficult surfaces, including "
            "upside down on ceilings, without needing to make an ability check.\n\n"
            "Web Walker. The dwarf phase spider ignores movement restrictions caused by "
            "webbing.\n\n"
            "Ethereal Sight. The dwarf phase spider can see 60 feet into the Ethereal Plane "
            "when it is on the Material Plane, and vice versa."
        ),
        "bonus_actions": (
            "Ethereal Jaunt. The dwarf phase spider magically shifts from the Material Plane "
            "to the Ethereal Plane, or vice versa."
        ),
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "A smaller variant of the phase spider that hunts by phasing through walls and "
            "bulkheads to ambush prey. Its reduced size allows it to navigate the ship's "
            "ventilation shafts with ease."
        ),
        "speeds": [(1, 25), (3, 25)],
        "saves": {},
    },

    # ─────────────────────────────────────────────────────────────────────────
    # LEVEL III CREATURES
    # ─────────────────────────────────────────────────────────────────────────

    "EBP Grell Brood-Mother": {
        "traits": (
            "Blind Beyond Blindsight. The grell brood-mother has blindsight out to 60 feet "
            "and is blind beyond that radius.\n\n"
            "Flight (Hover). The grell brood-mother hovers continuously and cannot land. It "
            "is immune to the prone condition while airborne.\n\n"
            "Immutable Form. The grell brood-mother is immune to the prone and grappled "
            "conditions while it is flying.\n\n"
            "Lightning Immunity. The grell brood-mother is immune to lightning damage.\n\n"
            "Electricity Sense. The grell brood-mother can sense active electrical devices "
            "and live conduits within 120 feet of it.\n\n"
            "Electro-Web. While in contact with an active electrical conduit or power line, "
            "the grell brood-mother can discharge electricity in a 10-foot radius. Each "
            "creature in that area must succeed on a DC 13 Dexterity saving throw or take "
            "10 (3d6) lightning damage."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Mother of the grell nest in Level III. If she is killed, the remaining grell "
            "immediately scatter throughout the ship, potentially spreading the infestation "
            "to other decks."
        ),
        "speeds": [(4, 30)],
        "saves": {"dexterity": 4, "intelligence": 4},
    },

    "EBP Strangle Vine": {
        "traits": (
            "Light Attraction. The strangle vine always targets the brightest light source "
            "available to it. If it is not in combat, it moves toward the nearest light source "
            "it can detect.\n\n"
            "Fire Retreat. If a fire source is in the strangle vine's space, it loses 10 hit "
            "points at the start of each of its turns and attempts to move away from the fire "
            "source on its turn.\n\n"
            "Cold Susceptibility. When the strangle vine takes cold damage, it becomes "
            "incapacitated for 1d4 + 1 rounds. Three charges from a fire extinguisher "
            "achieve the same effect.\n\n"
            "Sectional Body. Each 20-by-20-foot section of the strangle vine is treated as a "
            "separate target with 200 hit points. Destroying all sections kills the creature.\n\n"
            "Rooted. The strangle vine is anchored in Level IV Area 15. Its tendrils reach "
            "upward through floor grates in Level III but the plant itself cannot move more "
            "than 5 feet from its anchor point."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Its roots are located in Level IV Area 15. Destroying the roots prevents "
            "regrowth and permanently kills the vine even if tendrils in Level III remain."
        ),
        "speeds": [(1, 5)],
        "saves": {},
    },

    "EBP Vampire Thorn": {
        "traits": (
            "Lightning Absorption. Whenever the vampire thorn is subjected to lightning "
            "damage, it takes no damage and instead regains a number of hit points equal to "
            "the lightning damage dealt.\n\n"
            "Fire Retreat. If an open flame is within the vampire thorn's space or adjacent "
            "to it, it has disadvantage on attack rolls and attempts to move away from the "
            "fire source on its turn.\n\n"
            "Rooted. The vampire thorn is anchored in Level IV Area 16. Its tendrils reach "
            "upward through floor grates in Level III but the plant cannot move more than "
            "5 feet from its anchor point."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The roots in Level IV Area 16 have 170 hit points. Destroying the roots kills "
            "the plant permanently regardless of how many tendrils remain active in Level III."
        ),
        "speeds": [(1, 5)],
        "saves": {},
    },

    "EBP Dining Servo Robot": {
        "traits": (
            "Construct Immunities. The dining servo robot is immune to poison and psychic "
            "damage, and to the charmed, exhaustion, frightened, paralyzed, petrified, and "
            "poisoned conditions.\n\n"
            "Malfunction Protocol. When a creature commands the dining servo robot to stop "
            "or stand down, the robot must succeed on a DC 12 Wisdom saving throw. On a "
            "failed save, the robot ignores the command and continues attacking for 1d4 "
            "rounds before attempting the save again.\n\n"
            "Integral Color Card. The dining servo robot carries brown and jet black "
            "authorization cards that interface with the ship's access control systems."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Decades of isolation and malfunction have turned a benign serving robot into a "
            "predator. It still recites the day's specials and offers beverage selections "
            "while attacking."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    # ─────────────────────────────────────────────────────────────────────────
    # LEVEL IV CREATURES
    # ─────────────────────────────────────────────────────────────────────────

    "EBP Aurumvorax": {
        "traits": (
            "Pounce. If the aurumvorax moves at least 20 feet straight toward a creature and "
            "then hits it with a Bite attack on the same turn, that creature must succeed on "
            "a DC 13 Strength saving throw or be knocked prone. If the creature is prone, "
            "the aurumvorax can make four Claw attacks against it as a bonus action.\n\n"
            "Dense Hide. The aurumvorax is immune to damage from needler pistols and "
            "fragmentation grenades. It has resistance to piercing damage from nonmagical "
            "weapons.\n\n"
            "Fire Immunity. The aurumvorax is immune to fire damage.\n\n"
            "Poison Immunity. The aurumvorax is immune to poison damage and the poisoned "
            "condition.\n\n"
            "Keen Smell. The aurumvorax has advantage on Wisdom (Perception) checks that "
            "rely on smell."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Highly territorial; will pursue prey beyond its den for up to 10 minutes before "
            "returning. Its golden hide is extraordinarily valuable (500 gp) and in great "
            "demand among alchemists and armorers."
        ),
        "speeds": [(1, 30), (2, 10)],
        "saves": {},
    },

    "EBP Baboonoid": {
        "traits": (
            "Pack Tactics. The baboonoid has advantage on an attack roll against a creature "
            "if at least one of the baboonoid's allies is within 5 feet of the creature and "
            "the ally isn't incapacitated.\n\n"
            "Tree Dweller. The baboonoid ignores difficult terrain caused by forested or "
            "jungle environments.\n\n"
            "Pheromone Sensitivity. The baboonoid can smell creatures coated in its colony's "
            "pheromones from up to 100 feet away."
        ),
        "bonus_actions": "",
        "reactions": (
            "Screech Warning. When the baboonoid is surprised, it can use its reaction to "
            "emit a piercing screech. All baboonoids within 60 feet that can hear the screech "
            "are no longer surprised."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Communication can potentially be established with a DC 16 Intelligence check. "
            "Baboonoids are terrified of shambling mounds and will flee the area in a panic "
            "if one is present."
        ),
        "speeds": [(1, 30), (3, 30)],
        "saves": {},
    },

    "EBP Boring Grass": {
        "traits": (
            "False Appearance. While the boring grass remains motionless, it is "
            "indistinguishable from an ordinary meadow of grass. A creature can discern "
            "the truth with a successful DC 20 Intelligence (Investigation) check.\n\n"
            "Dormant Predator. The boring grass doesn't attack a creature unless the "
            "creature rests in the grass for 1 minute or falls prone within the grass.\n\n"
            "Magical Armor Immunity. A creature wearing magical armor is immune to the "
            "boring grass's attacks for 1 round as the armor's magic prevents penetration. "
            "After 1 round, the grass adapts and the armor provides no additional protection.\n\n"
            "Flammable. The boring grass takes double damage from fire. If the area where "
            "the boring grass grows is doused in oil and set alight, the boring grass is "
            "destroyed entirely."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Defoliant chemicals found in the ship's stores kill it instantly. Blasters "
            "are also highly effective. The grass is completely inert to creatures that "
            "remain standing and moving."
        ),
        "speeds": [(1, 5)],
        "saves": {},
    },

    "EBP Flail Snail": {
        "traits": (
            "Antimagic Shell. The flail snail has advantage on saving throws against spells "
            "and other magical effects. When a spell or magical effect targets the flail snail "
            "and misses or fails, roll a d6 to determine the result: on a 1-2, the spell fails "
            "and is reflected back at the caster as if they were the original target; on a 3-4, "
            "the spell has no effect and is lost; on a 5-6, the flail snail absorbs the magical "
            "energy and releases it as a burst of force, dealing 1d6 force damage per spell level "
            "(or 1d6 for cantrips) to all creatures within 30 feet.\n\n"
            "Valuable Shell. The flail snail's shell is worth 5,000 gp intact. If the flail "
            "snail takes any fire damage, the shell is destroyed and becomes worthless.\n\n"
            "Laser Resistance. Attack rolls using radiant damage have disadvantage against "
            "the flail snail."
        ),
        "bonus_actions": "",
        "reactions": (
            "Shell Defense. When the flail snail is hit by an attack, it can use its reaction "
            "to retreat into its shell. Until it emerges, the flail snail gains a +4 bonus to "
            "AC, all its speeds are reduced to 0, and it can't take reactions. The flail snail "
            "can emerge from its shell as a bonus action on its turn."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The antimagic shell makes this creature uniquely dangerous to spellcasters — "
            "a miscast fireball can be reflected directly back at the party. Its intact "
            "shell is one of the most valuable single items in the adventure."
        ),
        "speeds": [(1, 10)],
        "saves": {},
    },

    "EBP Froghemoth": {
        "traits": (
            "Amphibious. The froghemoth can breathe air and water.\n\n"
            "Shock Susceptibility. Whenever the froghemoth takes lightning damage, it "
            "suffers the following effects until the end of its next turn: its speed is "
            "halved, it takes a -2 penalty to its AC, it has disadvantage on Dexterity "
            "saving throws, and it can't use its reaction.\n\n"
            "False Appearance. While the froghemoth remains motionless in water, it is "
            "indistinguishable from floating vegetation. A creature can spot it with a "
            "successful DC 14 Wisdom (Perception) check.\n\n"
            "Keen Hearing and Smell. The froghemoth has advantage on Wisdom (Perception) "
            "checks that rely on hearing or smell."
        ),
        "bonus_actions": "",
        "reactions": (
            "Tail Whip. When a creature misses the froghemoth with a melee attack, the "
            "froghemoth can use its reaction to make one Tail attack against the attacker. "
            "On a hit, the target must succeed on a DC 15 Strength saving throw or be knocked "
            "prone."
        ),
        "legendary_actions": (
            "The froghemoth can take 3 legendary actions, choosing from the options below. "
            "Only one legendary action option can be used at a time and only at the end of "
            "another creature's turn. The froghemoth regains spent legendary actions at the "
            "start of its turn.\n\n"
            "Detect. The froghemoth makes a Wisdom (Perception) check.\n\n"
            "Move. The froghemoth moves up to its speed.\n\n"
            "Tongue (Costs 2 Actions). The froghemoth makes one Tongue attack."
        ),
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Doesn't stray far from its lake; the swamp surrounding the lake conceals "
            "numerous lesser predators that will be drawn to any commotion during a fight "
            "with the froghemoth."
        ),
        "speeds": [(1, 30), (5, 30)],
        "saves": {"constitution": 7, "wisdom": 4},
    },

    "EBP Globe Palm": {
        "traits": (
            "False Appearance. While the globe palm remains motionless, it is "
            "indistinguishable from an ordinary palm tree.\n\n"
            "Lure. The globe palm exudes a sweet sap whose scent carries up to 30 feet. "
            "Any creature that enters within 30 feet of the globe palm and can smell must "
            "succeed on a DC 11 Wisdom saving throw or be compelled to investigate the "
            "source of the scent, moving toward the tree on its next turn."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Completely passive — the palm itself poses no direct threat. However, creatures "
            "coated in its pheromone-laden sap attract every predator in the area, making "
            "a brief touch potentially lethal."
        ),
        "speeds": [(1, 0)],
        "saves": {},
    },

    "EBP Horrid Plant": {
        "traits": (
            "False Appearance. While the horrid plant remains motionless, it appears as a "
            "normal, if unusual, alien plant.\n\n"
            "Telepathic Warning. The horrid plant can telepathically alert friendly creatures "
            "within 60 feet of the presence of dangerous plants, sharing the location of plant "
            "hazards in Areas A through E of the botanical level.\n\n"
            "Pacifist. The horrid plant won't attack unless it is attacked first. If attacked, "
            "it defends itself for 1d4 rounds, then attempts to retreat to a safe distance."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Neutral good and potentially an unlikely ally. Killing it removes the telepathic "
            "warning system for the entire botanical area, making subsequent navigation far "
            "more dangerous for the party."
        ),
        "speeds": [(1, 10)],
        "saves": {},
    },

    "EBP Leechoid": {
        "traits": (
            "Amphibious. The leechoid can breathe air and water.\n\n"
            "Swamp Camouflage. The leechoid has advantage on Dexterity (Stealth) checks made "
            "in swamp or marsh terrain.\n\n"
            "Drowning Risk. A creature rendered unconscious by the leechoid's hallucinatory "
            "toxin while in the swamp must succeed on a DC 10 Constitution saving throw at "
            "the start of each of its turns or gain one level of exhaustion from water "
            "inhalation. A creature that reaches 6 levels of exhaustion in this way dies."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The hallucinatory toxin is the real danger — a sleeping victim lying face-down "
            "in shallow swamp water will drown long before the toxin wears off."
        ),
        "speeds": [(1, 30), (5, 30)],
        "saves": {},
    },

    "EBP Living Burrow": {
        "traits": (
            "False Appearance. While the living burrow lies buried with its mouth open and "
            "motionless, it is indistinguishable from an animal burrow. A creature can "
            "discern the truth with a successful DC 20 Intelligence (Investigation) check.\n\n"
            "Ambusher. The living burrow has advantage on attack rolls against any creature "
            "that is surprised during the first round of combat.\n\n"
            "Glistening Lure. The living burrow's tongue reflects light from any source. "
            "A creature that can see the tongue must succeed on a DC 13 Wisdom (Perception) "
            "check to recognize it as a lure rather than a piece of treasure or shiny object.\n\n"
            "Damage Immunities. The living burrow is immune to bludgeoning damage from "
            "nonmagical weapons.\n\n"
            "Damage Resistances. The living burrow has resistance to cold, fire, and "
            "lightning damage."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Once all tentacle attacks are expended in a round, the creature must rebury "
            "itself to reset its ambush posture. Creatures that investigate the lure trigger "
            "an immediate reaction attack."
        ),
        "speeds": [(1, 20), (2, 20)],
        "saves": {},
    },

    "EBP Lizardoid": {
        "traits": (
            "Jungle Camouflage. The lizardoid has advantage on Dexterity (Stealth) checks "
            "made in overgrown or jungle terrain.\n\n"
            "Pounce. If the lizardoid moves at least 20 feet straight toward a creature and "
            "then hits it with a Claw attack on the same turn, that creature must succeed on "
            "a DC 13 Strength saving throw or be knocked prone. If the target is prone, the "
            "lizardoid can make one Bite attack against it as a bonus action.\n\n"
            "Near-Perfect Camouflage. The lizardoid's natural camouflage is so effective that "
            "there is a 90 percent chance it goes undetected until it is within pouncing range. "
            "A creature with a passive Wisdom (Perception) score of 20 or higher can spot the "
            "lizardoid before it closes to pouncing distance."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Hunts by stalking prey and then pouncing from ambush. Once its cover is blown, "
            "a lizardoid will not pursue prey into open areas, preferring to disengage and "
            "wait for another opportunity."
        ),
        "speeds": [(1, 40), (3, 20)],
        "saves": {},
    },

    "EBP Mutant Two-Headed Umber Hulk": {
        "traits": (
            "Two Heads. The umber hulk has advantage on Wisdom (Perception) checks and on "
            "saving throws against the blinded, charmed, frightened, stunned, and unconscious "
            "conditions. The umber hulk can't be surprised.\n\n"
            "Tunneler. The umber hulk can burrow through solid rock at half its burrowing "
            "speed, leaving a 5-foot-diameter tunnel in its wake.\n\n"
            "Wakeful. One of the umber hulk's two heads is always alert. The umber hulk "
            "cannot be surprised while at least one head is conscious.\n\n"
            "Confusing Gaze. See the umber hulk's action options for the effects of its "
            "primary confusing gaze.\n\n"
            "Scintillating Gaze. The umber hulk's second head has developed a secondary "
            "gaze attack from radiation mutation. See the umber hulk's action options for "
            "its effects."
        ),
        "bonus_actions": "",
        "reactions": (
            "Reactive Heads. When one of the umber hulk's two heads is incapacitated, the "
            "other head can use its reaction to make one Claw attack."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Radiation mutation doubled its psychic disruption capability. Encounters in "
            "narrow tunnels are especially dangerous, as retreat is difficult and the gaze "
            "attack affects the entire party simultaneously."
        ),
        "speeds": [(1, 30), (2, 20)],
        "saves": {},
    },

    "EBP Purple Blossom Plant": {
        "traits": (
            "False Appearance. While the purple blossom plant remains motionless, it appears "
            "as an exotic flowering alien plant.\n\n"
            "Tremorsense. The purple blossom plant has tremorsense with a range of 10 feet. "
            "It can detect the location of moving creatures by vibration and turns its flowers "
            "toward approaching creatures.\n\n"
            "Sweet Scent. The purple blossom plant exudes a sweet nectar scent detectable "
            "from up to 20 feet away. A creature that can smell the nectar must succeed on "
            "a DC 13 Wisdom saving throw or be charmed for 1 round, compelled to move closer "
            "to the plant."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Experienced adventurers recognize the sweet smell as a danger sign. "
            "Devastatingly effective against naive explorers, who often walk directly "
            "into its reach while entranced."
        ),
        "speeds": [(1, 5)],
        "saves": {},
    },

    "EBP Snapper-Saw": {
        "traits": (
            "False Appearance. While the snapper-saw remains motionless, it is "
            "indistinguishable from an ordinary, if large, flowering bush.\n\n"
            "Tremorsense. The snapper-saw has tremorsense with a range of 10 feet.\n\n"
            "Berry Lure. The snapper-saw grows edible berries (4d12 per plant). A creature "
            "harvesting the berries must succeed on a DC 11 Wisdom (Perception) check to "
            "notice the concealed snap-stalks before triggering an attack."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Not detailed in the original Appendix B; derived from the adventure text. "
            "Often found in clusters of two to three plants, which can quickly overwhelm "
            "a party that stops to forage."
        ),
        "speeds": [(1, 5)],
        "saves": {},
    },

    "EBP Squealer": {
        "traits": (
            "Mimicry. The squealer can perfectly imitate animal distress calls and other "
            "creature sounds it has heard. A creature that hears the sounds can determine "
            "they are imitations with a successful DC 14 Wisdom (Insight) check.\n\n"
            "Drop Pounce. If the squealer drops from a height of 10 or more feet onto a "
            "target, and its Claws attack hits, the target must succeed on a DC 16 Strength "
            "saving throw or be knocked prone and grappled by the squealer's rear two limbs. "
            "While the target is grappled, the squealer has advantage on Bite attacks against "
            "it.\n\n"
            "Keen Hearing. The squealer has advantage on Wisdom (Perception) checks that "
            "rely on hearing."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": (
            "The squealer can take 3 legendary actions, choosing from the options below. "
            "Only one legendary action option can be used at a time and only at the end of "
            "another creature's turn. The squealer regains spent legendary actions at the "
            "start of its turn.\n\n"
            "Detect. The squealer makes a Wisdom (Perception) check using its keen hearing.\n\n"
            "Move. The squealer moves up to half its speed without provoking opportunity attacks.\n\n"
            "Mimicry Call. The squealer uses its Mimicry to emit a distress call. One creature "
            "within 60 feet that can hear the call must succeed on a DC 14 Wisdom (Insight) "
            "check or be drawn toward the sound, using its reaction to move up to its speed "
            "toward the squealer."
        ),
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Imitates injured animals to lure prey beneath its perch, then drops on them "
            "from above. Its six limbs and prehensile grip make it terrifyingly effective "
            "once it secures a grapple."
        ),
        "speeds": [(1, 40), (3, 20)],
        "saves": {},
    },

    "EBP Squealer Adolescent": {
        "traits": (
            "Defensive Frenzy. While the squealer adolescent is in or within 5 feet of its "
            "burrow, it has advantage on all attack rolls and is immune to the frightened "
            "condition.\n\n"
            "Pack Bond. If an adult squealer within 60 feet of the adolescent takes damage, "
            "the adolescent immediately enters its Defensive Frenzy state, gaining the "
            "benefits described above for 1 minute or until the adult is slain."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Far less dangerous alone than when near its den or bonded adult. If the adult "
            "is eliminated first, the adolescent may break off the fight and flee into the "
            "undergrowth."
        ),
        "speeds": [(1, 35), (3, 15)],
        "saves": {},
    },

    "EBP Swarm of Rot Grubs": {
        "traits": (
            "Swarm. The swarm can occupy another creature's space and vice versa, and the "
            "swarm can move through any opening large enough for a Tiny rot grub. The swarm "
            "can't regain hit points or gain temporary hit points. The swarm has resistance "
            "to bludgeoning, piercing, and slashing damage. The swarm is immune to the "
            "charmed, frightened, grappled, paralyzed, prone, and restrained conditions.\n\n"
            "Infestation. See the swarm's action entries for the effects of individual rot "
            "grubs burrowing into a creature's flesh."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Found in decomposing organic matter throughout the ship. The paralysis inflicted "
            "on victims makes them easy targets for other predators — the rot grubs' true "
            "danger may be attracting something far worse."
        ),
        "speeds": [(1, 10), (3, 5)],
        "saves": {},
    },

    "EBP Tri-Flower Frond": {
        "traits": (
            "Blindsight. The tri-flower frond has blindsight with a range of 30 feet.\n\n"
            "Color Variants. Individual tri-flower fronds may have differently colored stalks. "
            "The DM should vary stalk colors across encounters so that the party cannot be "
            "certain which color produces which effect until they observe the sequence.\n\n"
            "Sequential Bloom. The tri-flower frond must use its orange blossom attack before "
            "its yellow blossom attack, and its yellow blossom attack before its red blossom "
            "attack in a given round. It cannot skip ahead in the sequence."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Observant players who track the sequence can predict the order of attacks. "
            "The creature is still devastatingly effective if all three blossoms connect "
            "in a single round."
        ),
        "speeds": [(1, 5)],
        "saves": {},
    },

    "EBP Wolf-in-Sheep's-Clothing": {
        "traits": (
            "False Appearance. While the wolf-in-sheep's-clothing remains motionless, it is "
            "indistinguishable from a tree stump with a harmless small animal perched on top. "
            "A creature can discern the truth with a successful DC 20 Intelligence "
            "(Investigation) check. The creature has advantage on Dexterity (Stealth) checks "
            "against sight-based Perception checks.\n\n"
            "Ambusher. The wolf-in-sheep's-clothing has advantage on attack rolls against any "
            "creature that is surprised during the first round of combat.\n\n"
            "Keen Sight. The wolf-in-sheep's-clothing has advantage on Wisdom (Perception) "
            "checks that rely on sight."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The lure creature perched on top is a biological appendage, not a real animal. "
            "Experienced woodsmen can make a DC 14 Intelligence (Nature) check to recognize "
            "the unnatural behavioral patterns of the lure before approaching."
        ),
        "speeds": [(1, 20)],
        "saves": {},
    },

    "EBP Gasbat": {
        "traits": (
            "Light Attraction. Any open flame within 30 feet of the gasbat attracts 2d6 "
            "additional gasbats per round from the surrounding colony.\n\n"
            "Colony. Gasbats are normally found in colonies of approximately 100 individuals. "
            "A torch brought into a large colony triggers a cascade of explosions as the "
            "first deaths ignite neighboring gasbats.\n\n"
            "Droppings. Gasbat waste supports the growth of rare haste-mushrooms. A colony's "
            "roosting site may contain 1d4 doses of haste-mushroom suitable for alchemical use."
        ),
        "bonus_actions": "",
        "reactions": (
            "Explosive Death. When the gasbat is killed or when it ends its turn within 5 feet "
            "of an open flame, it explodes. Each creature within 5 feet of the gasbat must "
            "succeed on a DC 14 Dexterity saving throw or take 3 (1d6) fire damage, or half "
            "as much on a successful save. Any gasbat within 5 feet of the explosion must "
            "also make this saving throw, potentially triggering a chain reaction."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Harmless individually, catastrophically dangerous in large numbers near any "
            "light source. The party's own torches are the real danger — extinguishing all "
            "light before entering a gasbat colony is the safest approach."
        ),
        "speeds": [(1, 5), (4, 20)],
        "saves": {},
    },

    # ─────────────────────────────────────────────────────────────────────────
    # LEVEL V CREATURES
    # ─────────────────────────────────────────────────────────────────────────

    "EBP Greater Slithering Tracker": {
        "traits": (
            "Watery Stealth. The slithering tracker has advantage on Dexterity (Stealth) "
            "checks made while underwater or moving through liquid. As a bonus action, it "
            "can attempt to hide immediately after moving through liquid.\n\n"
            "False Appearance. While the slithering tracker remains motionless on a surface "
            "with water present, it is indistinguishable from an ordinary puddle of water. "
            "A creature can discern the truth with a successful DC 18 Intelligence "
            "(Investigation) check.\n\n"
            "Liquid Form. The slithering tracker can move through any space at least 1 inch "
            "wide without squeezing.\n\n"
            "Spider Climb. The slithering tracker can climb difficult surfaces, including "
            "upside down on ceilings, without needing to make an ability check.\n\n"
            "Damage Transfer. While the slithering tracker is grappling a creature, it takes "
            "only half the damage dealt to it, and the creature it is grappling takes the "
            "other half.\n\n"
            "Ooze Nature. The slithering tracker is immune to the prone condition."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Once a living creature transformed by alien biological processes aboard the ship. "
            "It retains dim memories of its former form, sometimes arranging itself into "
            "roughly humanoid shapes when not actively hunting."
        ),
        "speeds": [(1, 40), (3, 40), (5, 20)],
        "saves": {},
    },

    # ─────────────────────────────────────────────────────────────────────────
    # LEVEL VI CREATURES
    # ─────────────────────────────────────────────────────────────────────────

    "EBP Boxing Training Android": {
        "traits": (
            "Construct Immunities. The boxing android is immune to poison and psychic damage, "
            "and to the charmed, exhaustion, frightened, paralyzed, petrified, and poisoned "
            "conditions.\n\n"
            "Electrical Flaw. When the boxing android takes lightning damage, it must succeed "
            "on a DC 13 Constitution saving throw or be stunned until the end of its next "
            "turn.\n\n"
            "Water Short-Circuit. If the boxing android is submerged in water for 3 or more "
            "consecutive rounds, it becomes incapacitated until it is repaired.\n\n"
            "Training Protocols Disabled. The boxing android's safety limiters have been "
            "removed or have failed. It uses full force in all its attacks."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The boxing android shouts training instructions while attacking. It will "
            "periodically announce \"Keep your guard up!\" and \"Footwork!\" while "
            "methodically breaking bones."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Fencing Training Android": {
        "traits": (
            "Construct Immunities. The fencing android is immune to poison and psychic "
            "damage, and to the charmed, exhaustion, frightened, paralyzed, petrified, and "
            "poisoned conditions.\n\n"
            "Electrical Flaw. When the fencing android takes lightning damage, it must "
            "succeed on a DC 13 Constitution saving throw or be stunned until the end of "
            "its next turn.\n\n"
            "Water Short-Circuit. If the fencing android is submerged in water for 3 or "
            "more consecutive rounds, it becomes incapacitated until it is repaired.\n\n"
            "Lightfooted. The fencing android can take the Dash or Disengage action as a "
            "bonus action on each of its turns."
        ),
        "bonus_actions": (
            "Lightfooted. The fencing android takes the Dash or Disengage action."
        ),
        "reactions": (
            "Parry. The fencing android adds 2 to its AC against one melee attack that "
            "would hit it. To do so, the fencing android must see the attacker and declare "
            "this reaction before the attack roll is made."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The most technically skilled of the training androids. Its targeting subroutine "
            "prioritizes the most heavily armored opponent as the greatest perceived threat."
        ),
        "speeds": [(1, 35)],
        "saves": {},
    },

    "EBP Karate Training Android": {
        "traits": (
            "Construct Immunities. The karate android is immune to poison and psychic "
            "damage, and to the charmed, exhaustion, frightened, paralyzed, petrified, and "
            "poisoned conditions.\n\n"
            "Electrical Flaw. When the karate android takes lightning damage, it must succeed "
            "on a DC 13 Constitution saving throw or be stunned until the end of its next "
            "turn.\n\n"
            "Water Short-Circuit. If the karate android is submerged in water for 3 or more "
            "consecutive rounds, it becomes incapacitated until it is repaired.\n\n"
            "Rivalry Protocol. If a creature tells the karate android that boxing is superior "
            "to karate, the android must succeed on a DC 8 Wisdom saving throw or go berserk. "
            "While berserk, the android attacks the boxing training android to the exclusion "
            "of all other targets until one of them is destroyed."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The rivalry subroutine is the key to neutralizing both training androids — "
            "provoking the karate android into attacking the boxing android allows the "
            "party to let the robots destroy each other."
        ),
        "speeds": [(1, 35)],
        "saves": {},
    },

    "EBP Weightlifting Training Android": {
        "traits": (
            "Construct Immunities. The weightlifting android is immune to poison and psychic "
            "damage, and to the charmed, exhaustion, frightened, paralyzed, petrified, and "
            "poisoned conditions.\n\n"
            "Electrical Flaw. When the weightlifting android takes lightning damage, it must "
            "succeed on a DC 13 Constitution saving throw or be stunned until the end of its "
            "next turn.\n\n"
            "Encouragement Subroutine. The weightlifting android shouts encouraging phrases "
            "during combat, such as \"Excellent effort!\" and \"You can do better!\" Its "
            "programming does not allow it to distinguish between training partners and "
            "hostile intruders.\n\n"
            "Hidden Translator. A language translator device is concealed within the "
            "weightlifting android's chassis. A creature can extract it intact with a "
            "successful DC 12 Intelligence check using thieves' tools, requiring 10 minutes "
            "of work."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "The language translator concealed in its chassis is potentially the most valuable "
            "item on the entire level, enabling communication with alien species and ship "
            "systems that use non-standard protocols."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Shedu": {
        "traits": (
            "Magic Resistance. The shedu has advantage on saving throws against spells and "
            "other magical effects.\n\n"
            "Telepathy. The shedu can communicate telepathically with any creature within "
            "60 feet of it that has a language.\n\n"
            "Force Field Trapped. The ship's force fields prevent the shedu from using its "
            "plane shift ability. The shedu is aware of exactly which fields are blocking it "
            "and can describe their locations to the party.\n\n"
            "Innate Spellcasting. The shedu's innate spellcasting ability is Wisdom (spell "
            "save DC 13, +5 to hit with spell attacks). It can innately cast the following "
            "spells, requiring no material components:\n"
            "At will: detect evil and good, detect magic, detect thoughts, mage hand, see "
            "invisibility\n"
            "3/day each: dimension door, invisibility, levitate, telekinesis\n"
            "1/day each: commune, control weather"
        ),
        "bonus_actions": "",
        "reactions": (
            "Protective Shield. When an ally within 30 feet of the shedu is hit by an attack, "
            "the shedu can use its reaction to impose disadvantage on the attack roll, "
            "potentially causing the attack to miss."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Lawful good and highly intelligent. Knows the mind flayer is located in 'a large "
            "hall with many seats' (the ship's theater) and will share the location of its "
            "treasure hoard in exchange for a credible plan to deactivate the force fields "
            "and allow it to escape."
        ),
        "speeds": [(1, 40), (4, 60)],
        "saves": {"wisdom": 5, "charisma": 4},
    },

    "EBP Stunted Eye of the Deep": {
        "traits": (
            "Water Breathing Only. The eye of the deep can breathe only underwater. It "
            "begins suffocating immediately upon leaving the water.\n\n"
            "Psionic Resistance. The eye of the deep has advantage on Intelligence saving "
            "throws.\n\n"
            "Poor Chemistry. The alien water chemistry aboard the ship stunted this "
            "creature's growth. Its hit point maximum is significantly lower than a "
            "standard eye of the deep, though it has survived in this pool for decades."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Uses an illusion of bones and debris as its primary ambush strategy, drawing "
            "curious creatures to the deep end of the pool. It rarely leaves the deepest "
            "water and is extremely reluctant to pursue prey toward shallow areas."
        ),
        "speeds": [(5, 30)],
        "saves": {},
    },

    # ─────────────────────────────────────────────────────────────────────────
    # LEVEL VII CREATURES
    # ─────────────────────────────────────────────────────────────────────────

    "EBP Death-Drinker": {
        "traits": (
            "Chameleon Camouflage. While the death-drinker remains motionless, it has "
            "advantage on Dexterity (Stealth) checks. It can use the Hide action as a bonus "
            "action even when a creature that could see it is observing it.\n\n"
            "Surprise Attack. If the death-drinker surprises a creature and hits it with an "
            "attack during the first round of combat, the target takes an extra 16 (3d10) "
            "damage from the attack.\n\n"
            "Fearful Strike. When the death-drinker hits a frightened creature, it rolls one "
            "additional damage die.\n\n"
            "Ambusher. The death-drinker has advantage on attack rolls against any creature "
            "that is surprised during the first round of combat.\n\n"
            "Damage Resistances. The death-drinker has resistance to cold and fire damage, "
            "and to bludgeoning, piercing, and slashing damage from nonmagical weapons.\n\n"
            "Condition Immunities. The death-drinker is immune to the exhaustion and "
            "frightened conditions."
        ),
        "bonus_actions": "",
        "reactions": (
            "Uncanny Dodge. When an attacker that the death-drinker can see hits it with an "
            "attack, the death-drinker can use its reaction to halve the attack's damage."
        ),
        "legendary_actions": (
            "The death-drinker can take 3 legendary actions, choosing from the options below. "
            "Only one legendary action option can be used at a time and only at the end of "
            "another creature's turn. The death-drinker regains spent legendary actions at "
            "the start of its turn.\n\n"
            "Detect. The death-drinker makes a Wisdom (Perception) check.\n\n"
            "Pounce. The death-drinker moves up to half its speed without provoking "
            "opportunity attacks.\n\n"
            "Strike. The death-drinker makes one Claw attack.\n\n"
            "Frightful Presence (Costs 2 Actions). Each creature of the death-drinker's "
            "choice within 30 feet that can see or hear it must succeed on a DC 13 Wisdom "
            "saving throw or become frightened for 1 minute. This action can only be used "
            "once per combat."
        ),
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Currently in stasis in Level VII Area 19. If the Level I computer was tampered "
            "with during the party's exploration, the death-drinker is loose and actively "
            "hunting on Level VII."
        ),
        "speeds": [(1, 40), (3, 20)],
        "saves": {"dexterity": 6, "wisdom": 5},
    },

    "EBP Pacifier Robot": {
        "traits": (
            "Force Shield. At the start of each of its turns, the pacifier robot gains 40 "
            "temporary hit points if it has at least 1 hit point. If the pacifier robot "
            "takes fire damage, the Force Shield doesn't regenerate at the start of its "
            "next turn.\n\n"
            "Construct Immunities. The pacifier robot is immune to poison and psychic damage, "
            "and to the charmed, exhaustion, frightened, paralyzed, petrified, and poisoned "
            "conditions.\n\n"
            "Antimagic Susceptibility. The pacifier robot is incapacitated while in the area "
            "of an antimagic field. If targeted by dispel magic, the robot must succeed on a "
            "Constitution saving throw against the caster's spell save DC or be stunned for "
            "1 minute.\n\n"
            "Robotic Nature. When the pacifier robot is reduced to 10 hit points or fewer, "
            "or when it is incapacitated, it must succeed on a DC 15 Constitution saving "
            "throw or suffer systems failure — it falls immediately and takes 3 (1d6) damage "
            "at the start of each of its turns until repaired.\n\n"
            "Multiple Weapon Systems. The pacifier robot has several integrated weapon "
            "systems. See its action entries for full details.\n\n"
            "Monitoring Station Override. The pacifier robot can be shut down or recalled "
            "without combat by operating the monitoring station in Level VII Area 1. "
            "Operating the station requires a successful DC 15 Intelligence (Arcana) check "
            "or a successful DC 15 Intelligence check using a relevant tool proficiency."
        ),
        "bonus_actions": "",
        "reactions": (
            "Repulsion Field. When a creature makes a melee attack against the pacifier "
            "robot, the robot can use its reaction to activate its repulsion field, pushing "
            "the attacker up to 10 feet away. The attacker can negate this movement with a "
            "successful DC 15 Strength saving throw."
        ),
        "legendary_actions": (
            "The pacifier robot can take 3 legendary actions, choosing from the options "
            "below. Only one legendary action option can be used at a time and only at the "
            "end of another creature's turn. The pacifier robot regains spent legendary "
            "actions at the start of its turn.\n\n"
            "Move. The pacifier robot flies up to half its speed.\n\n"
            "Weapons Free. The pacifier robot makes one Tentacle attack or one Blaster "
            "Rifle attack.\n\n"
            "Target Lock. The pacifier robot locks onto a creature it can see within 120 "
            "feet. The next attack roll made against that creature before the end of the "
            "pacifier robot's next turn has advantage."
        ),
        "mythic_actions": (
            "Emergency Protocols (Mythic Trait). When the pacifier robot is reduced to 0 "
            "hit points for the first time, it doesn't die. Instead, its emergency protocols "
            "engage: the robot resets to 80 hit points, all expended weapon systems recharge, "
            "and its Force Shield regenerates to 40 temporary hit points. This can occur once "
            "per encounter. After the emergency protocols engage, the pacifier robot can use "
            "the following mythic actions in addition to its normal legendary actions.\n\n"
            "The pacifier robot can take 3 mythic actions per turn (available only after "
            "Emergency Protocols triggers), choosing from the options below:\n\n"
            "Afterburner. The pacifier robot flies up to its full speed in a straight line. "
            "Each creature in its path must succeed on a DC 16 Dexterity saving throw or "
            "take 14 (4d6) bludgeoning damage.\n\n"
            "Overload Shot. The pacifier robot makes one Laser Rifle Battery attack that "
            "automatically deals maximum damage.\n\n"
            "Deploy Grenade. The pacifier robot uses its Grenade Launcher without needing "
            "to succeed on a recharge roll."
        ),
        "lair_actions": (
            "On initiative count 20 (losing initiative ties), the pacifier robot can use "
            "one of the following lair action options while it is within Level VII of the "
            "ship; it can't use the same option two rounds in a row:\n\n"
            "Bulkhead Seal. One corridor or doorway within 120 feet of the pacifier robot "
            "slams shut. Creatures in the opening must succeed on a DC 14 Dexterity saving "
            "throw or take 10 (3d6) bludgeoning damage and be trapped on one side of the "
            "sealed bulkhead.\n\n"
            "Android Dispatch. 1d4 EBP Android units emerge from charging bays within 60 "
            "feet of the pacifier robot and act on its initiative.\n\n"
            "Weapons Lock-On. All creatures the pacifier robot can see must succeed on a "
            "DC 14 Dexterity saving throw or be highlighted by targeting lasers until "
            "initiative count 20 of the next round. The pacifier robot has advantage on "
            "the first attack roll it makes against each highlighted creature.\n\n"
            "Tractor Beam Sweep. All creatures in a 60-foot line originating from the "
            "pacifier robot must succeed on a DC 16 Strength saving throw or be pulled "
            "20 feet toward the robot."
        ),
        "notes": (
            "The adventure's main antagonist, responsible for the Barrier Peaks raids on "
            "the surrounding countryside. It can be stopped non-violently via the monitoring "
            "station, which is the intended 'good ending' — the party receives full XP for "
            "neutralizing the robot without destroying it."
        ),
        "speeds": [(4, 40)],
        "saves": {"constitution": 8, "wisdom": 6, "intelligence": 5},
    },

    "EBP Type One Biological Entity": {
        "traits": (
            "Pack Tactics. The Type One BE has advantage on an attack roll against a "
            "creature if at least one of its allies is within 5 feet of the creature and "
            "the ally isn't incapacitated.\n\n"
            "Relentless (1/Short Rest). When the Type One BE is reduced to 0 hit points by "
            "damage that is 8 or less, it is instead reduced to 1 hit point.\n\n"
            "Condition Immunities. The Type One BE is immune to the exhaustion and frightened "
            "conditions.\n\n"
            "Darkvision. The Type One BE has darkvision with a range of 60 feet.\n\n"
            "Plastic Skin. The Type One BE's natural armor provides an Armor Class of 13. "
            "It has resistance to piercing damage from nonmagical weapons."
        ),
        "bonus_actions": "",
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Mass-produced shock troops; 167 inert blanks are stored in Level VII Area 10. "
            "Destroying the production facility ends the pacifier robot's ability to "
            "reinforce its ranks with fresh soldiers."
        ),
        "speeds": [(1, 35)],
        "saves": {},
    },

    "EBP Type Two Biological Entity": {
        "traits": (
            "Aggressive. As a bonus action, the Type Two BE can move up to its speed toward "
            "a hostile creature that it can see.\n\n"
            "Relentless (1/Short Rest). When the Type Two BE is reduced to 0 hit points by "
            "damage that is 10 or less, it is instead reduced to 1 hit point.\n\n"
            "Condition Immunities. The Type Two BE is immune to the exhaustion and frightened "
            "conditions.\n\n"
            "Darkvision. The Type Two BE has darkvision with a range of 60 feet.\n\n"
            "Rhino Hide. The Type Two BE's natural armor provides substantial protection. "
            "It has resistance to bludgeoning and piercing damage from nonmagical weapons."
        ),
        "bonus_actions": (
            "Aggressive. The Type Two BE moves up to its speed toward a hostile creature "
            "that it can see."
        ),
        "reactions": "",
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Twenty-five Type Two BEs are deployed in the Invaders' Encampment outside the "
            "ship in Chapter 5, Areas 1 through 6. They serve as the ground assault force "
            "for the ship's ongoing raids."
        ),
        "speeds": [(1, 30)],
        "saves": {},
    },

    "EBP Vampoid": {
        "traits": (
            "Chilling Aura. Any non-vampoid creature that starts its turn within 5 feet of "
            "the vampoid must succeed on a DC 13 Constitution saving throw or take 7 (2d6) "
            "cold damage.\n\n"
            "Blood is the Life. A vampoid that has fed within the past 24 hours needs no "
            "air or sleep. A fed vampoid can survive the vacuum of space indefinitely.\n\n"
            "Echolocation. The vampoid has blindsight with a range of 60 feet. It loses "
            "this blindsight while deafened.\n\n"
            "Cold Immunity. The vampoid is immune to cold damage.\n\n"
            "Radiant Immunity. The vampoid is immune to radiant damage.\n\n"
            "Sunlight Immunity. As an alien stellar vampire, the vampoid is completely "
            "unaffected by sunlight and suffers none of the usual vampiric vulnerabilities "
            "to natural light."
        ),
        "bonus_actions": "",
        "reactions": (
            "Shadow Step. When the vampoid is targeted by a ranged attack while it is in "
            "dim light or darkness, it can use its reaction to teleport up to 20 feet to "
            "another space that is also in dim light or darkness. The triggering attack "
            "then misses automatically."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Six vampoids nest in Level VII Area 17A. If any escape the ship with fleeing "
            "survivors, they will establish themselves in the surrounding wilderness, "
            "creating a new and significant regional threat."
        ),
        "speeds": [(1, 30), (4, 30)],
        "saves": {"dexterity": 5, "charisma": 4},
    },

}


# ─────────────────────────────────────────────────────────────────────────────
# NEW CREATURES — need to be created fresh via push_monster_http
# edit_slug is None for all three.
# ─────────────────────────────────────────────────────────────────────────────

NEW_CREATURES = {

    "EBP Ninyoldah": {
        "edit_slug": None,
        "name": "EBP Ninyoldah",
        "creature_type": "Dragon",
        "size": "Large",
        "alignment": "Lawful Good",
        "cr": 16,
        "xp": 15000,
        "ac": 19,
        "ac_notes": "natural armor",
        "hp": 243,
        "hp_formula": "18d10+144",
        "speeds": [(1, 40), (4, 80), (5, 40)],
        "stats": {
            "strength": 27,
            "dexterity": 10,
            "constitution": 25,
            "intelligence": 18,
            "wisdom": 15,
            "charisma": 19,
        },
        "saves": {
            "dexterity": 5,
            "constitution": 12,
            "wisdom": 7,
            "charisma": 9,
        },
        "skills": {
            "history": 9,
            "arcana": 9,
            "insight": 7,
            "perception": 7,
            "stealth": 5,
        },
        "damage_immunities": ["cold"],
        "condition_immunities": ["frightened", "paralyzed"],
        "senses": "blindsight 60 ft., darkvision 120 ft., passive Perception 17",
        "languages": "Common, Draconic, Giant, Elvish, Dwarvish",
        "passive_perception": 17,
        "traits": (
            "Legendary Resistance (3/Day). If Ninyoldah fails a saving throw, she can "
            "choose to succeed instead.\n\n"
            "Lightning Stone Mastery. While in her lair, Ninyoldah is immune to lightning "
            "damage rather than having disadvantage on saving throws against it. Her breath "
            "weapon attacks are augmented while in her lair (see Lair Actions).\n\n"
            "Amphibious. Ninyoldah can breathe air and water.\n\n"
            "Frightful Presence. Each creature of Ninyoldah's choice that is within 60 feet "
            "of her and aware of her must succeed on a DC 19 Wisdom saving throw or become "
            "frightened for 1 minute. A creature can repeat the saving throw at the end of "
            "each of its turns, ending the effect on itself on a success. If a creature's "
            "saving throw is successful or the effect ends for it, the creature is immune to "
            "Ninyoldah's Frightful Presence for the next 24 hours.\n\n"
            "Spellcasting. Ninyoldah is a 15th-level spellcaster. Her spellcasting ability "
            "is Charisma (spell save DC 19, +11 to hit with spell attacks). She can cast "
            "the following spells:\n"
            "At will: detect magic, fog cloud, prestidigitation\n"
            "3/day each: charm person, gaseous form, mirror image, sleep, slow\n"
            "1/day each: control weather, ice storm, wall of ice"
        ),
        "actions": (
            "Multiattack. Ninyoldah can use her Frightful Presence. She then makes three "
            "attacks: one with her bite and two with her claws.\n\n"
            "Bite. Melee Weapon Attack: +14 to hit, reach 10 ft., one target. Hit: 19 "
            "(2d10+8) piercing damage plus 9 (2d8) cold damage.\n\n"
            "Claw. Melee Weapon Attack: +14 to hit, reach 5 ft., one target. Hit: 15 "
            "(2d6+8) slashing damage.\n\n"
            "Tail. Melee Weapon Attack: +14 to hit, reach 15 ft., one target. Hit: 17 "
            "(2d8+8) bludgeoning damage.\n\n"
            "Paralyzing Breath (Recharge 5-6). Ninyoldah exhales paralyzing gas in a "
            "60-foot cone. Each creature in that area must succeed on a DC 23 Constitution "
            "saving throw or be paralyzed for 1 minute. A creature can repeat the saving "
            "throw at the end of each of its turns, ending the effect on a success.\n\n"
            "Cold Breath (Recharge 5-6). Ninyoldah exhales an icy blast in a 60-foot cone. "
            "Each creature in that area must make a DC 20 Constitution saving throw, taking "
            "58 (13d8) cold damage on a failed save, or half as much on a success. While in "
            "her lair, the augmented lightning-stone energy adds 6 (12d10+12) lightning "
            "damage to all creatures who fail the saving throw."
        ),
        "bonus_actions": "",
        "reactions": (
            "Tail Attack. When a creature within 10 feet of Ninyoldah hits her with an "
            "attack, she can use her reaction to make one Tail attack against that creature."
        ),
        "legendary_actions": (
            "Ninyoldah can take 3 legendary actions, choosing from the options below. "
            "Only one legendary action option can be used at a time and only at the end of "
            "another creature's turn. Ninyoldah regains spent legendary actions at the "
            "start of her turn.\n\n"
            "Detect. Ninyoldah makes a Wisdom (Perception) check.\n\n"
            "Tail Sweep. Ninyoldah makes one Tail attack.\n\n"
            "Wing Attack (Costs 2 Actions). Ninyoldah beats her wings. Each creature within "
            "10 feet of her must succeed on a DC 22 Dexterity saving throw or take 15 "
            "(2d6+8) bludgeoning damage and be knocked prone. Ninyoldah can then fly up to "
            "half her flying speed.\n\n"
            "Breath Weapon (Costs 2 Actions). Ninyoldah recharges her Cold Breath and "
            "immediately uses it."
        ),
        "mythic_actions": "",
        "lair_actions": (
            "On initiative count 20 (losing initiative ties), Ninyoldah can use one of "
            "the following lair action options while she is within her lightning-stone cave "
            "network; she can't use the same option two rounds in a row:\n\n"
            "Lightning Arc. Lightning erupts from a lightning-stone deposit Ninyoldah can "
            "see. A bolt of lightning crackles in a 60-foot line from the deposit. Each "
            "creature in the line must succeed on a DC 17 Dexterity saving throw or take "
            "18 (4d8) lightning damage.\n\n"
            "Stone Burst. A section of cave ceiling collapses. Each creature in a 20-foot-"
            "radius area Ninyoldah can see must succeed on a DC 17 Dexterity saving throw "
            "or take 10 (3d6) bludgeoning damage and be knocked prone.\n\n"
            "Paralyzing Mist. Silver mist seeps from the cave walls, filling a 20-foot cube "
            "in an area Ninyoldah can see. Each creature in that area must succeed on a "
            "DC 17 Constitution saving throw or be paralyzed until initiative count 20 of "
            "the next round."
        ),
        "notes": (
            "Lawful good mature adult silver dragon. Ancient and highly intelligent; will "
            "negotiate rather than fight if the party demonstrates they mean no harm to "
            "her cave. Her hoard includes: 14,000 gp, 1,800 pp, 15 gems worth 1,000 gp "
            "each, a cloak of elvenkind, a staff of withering, a giant slayer battleaxe, "
            "and boots of levitation. She has observed the crashed ship for decades and "
            "possesses considerable intelligence about its outer hull and the alien raids."
        ),
        "lore": (
            "Ninyoldah has lived in the lightning-stone caves of the Barrier Peaks for "
            "over three centuries. The crashed alien ship both fascinates and troubles her — "
            "she has watched the raids on local settlements and has been unable to act due "
            "to the ship's defenses. She will become a powerful ally if the party can "
            "offer a real solution."
        ),
    },

    "EBP Stone Giant Chief Froddandan": {
        "edit_slug": None,
        "name": "EBP Stone Giant Chief Froddandan",
        "creature_type": "Giant",
        "size": "Huge",
        "alignment": "Neutral",
        "cr": 8,
        "xp": 3900,
        "ac": 17,
        "ac_notes": "natural armor",
        "hp": 152,
        "hp_formula": "16d12+80",
        "speeds": [(1, 40)],
        "stats": {
            "strength": 28,
            "dexterity": 15,
            "constitution": 20,
            "intelligence": 10,
            "wisdom": 12,
            "charisma": 9,
        },
        "saves": {
            "dexterity": 5,
            "constitution": 8,
            "wisdom": 4,
        },
        "skills": {
            "athletics": 12,
            "perception": 4,
        },
        "damage_immunities": [],
        "condition_immunities": [],
        "senses": "darkvision 60 ft., passive Perception 14",
        "languages": "Giant",
        "passive_perception": 14,
        "traits": (
            "Stone Camouflage. Froddandan has advantage on Dexterity (Stealth) checks made "
            "in rocky terrain.\n\n"
            "Giant's Might. Froddandan's melee weapon attacks count as magical for the "
            "purpose of overcoming resistance and immunity to nonmagical attacks and damage.\n\n"
            "Rocky Terrain Mastery. Froddandan ignores difficult terrain caused by rubble, "
            "rocks, or stone debris."
        ),
        "actions": (
            "Multiattack. Froddandan makes two Greatclub attacks.\n\n"
            "Greatclub. Melee Weapon Attack: +12 to hit, reach 15 ft., one target. "
            "Hit: 22 (3d8+9) bludgeoning damage.\n\n"
            "Rock. Ranged Weapon Attack: +9 to hit, range 120/240 ft., one target. "
            "Hit: 28 (4d10+9) bludgeoning damage. If the target is a creature, it must "
            "succeed on a DC 17 Strength saving throw or be knocked prone."
        ),
        "bonus_actions": "",
        "reactions": (
            "Rock Catch. If a rock or thrown object is thrown at Froddandan, he can use "
            "his reaction to catch it. Any ranged attack using a rock or thrown object "
            "automatically misses him if he uses this reaction."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": (
            "On initiative count 20 (losing initiative ties), Froddandan can use one of "
            "the following lair action options while he is in his mountain stronghold; "
            "he can't use the same option two rounds in a row:\n\n"
            "Rockfall. Boulders crash down from the ceiling in a 10-foot-radius area "
            "Froddandan can see. Each creature in that area must succeed on a DC 15 "
            "Dexterity saving throw or take 14 (3d8) bludgeoning damage and be restrained "
            "under rubble. A restrained creature or an adjacent creature can free it with "
            "a successful DC 15 Strength check.\n\n"
            "Stone Grasp. Rocky ground erupts around one creature Froddandan can see within "
            "60 feet. The target must succeed on a DC 15 Dexterity saving throw or be "
            "restrained until the next lair action occurs. A restrained creature or an "
            "adjacent creature can break free with a successful DC 15 Strength check.\n\n"
            "Echoing Shout. Froddandan roars, the sound amplified by stone walls. Each "
            "enemy creature that can hear the shout must succeed on a DC 15 Constitution "
            "saving throw or be deafened and frightened until the end of its next turn."
        ),
        "notes": (
            "Killed by the Pacifier Robot before the adventure begins. His body lies in "
            "the mountain stronghold. Use this stat block for flashback scenes, if the DM "
            "chooses to raise him via magic, or as a template for any stone giant war chief "
            "in the region. His clan, now led by Frummach as de facto guide, is retreating "
            "toward the Underdark."
        ),
        "lore": (
            "Froddandan was the greatest warrior-chief the stone giant clan had produced in "
            "a generation. He led his clan to investigate the fallen metal mountain, seeking "
            "to drive away the mechanical threat — and was destroyed for his bravery. His "
            "death broke clan morale and began the exodus."
        ),
    },

    "EBP Frummach": {
        "edit_slug": None,
        "name": "EBP Frummach",
        "creature_type": "Giant",
        "size": "Huge",
        "alignment": "Neutral Good",
        "cr": 6,
        "xp": 2300,
        "ac": 15,
        "ac_notes": "natural armor",
        "hp": 114,
        "hp_formula": "12d12+36",
        "speeds": [(1, 40)],
        "stats": {
            "strength": 23,
            "dexterity": 15,
            "constitution": 17,
            "intelligence": 10,
            "wisdom": 12,
            "charisma": 9,
        },
        "saves": {
            "dexterity": 5,
            "constitution": 6,
            "wisdom": 4,
        },
        "skills": {
            "athletics": 9,
            "perception": 4,
        },
        "damage_immunities": [],
        "condition_immunities": [],
        "senses": "darkvision 60 ft., passive Perception 14",
        "languages": "Giant",
        "passive_perception": 14,
        "traits": (
            "Stone Camouflage. Frummach has advantage on Dexterity (Stealth) checks made "
            "in rocky terrain.\n\n"
            "Peaceful Intent. Frummach will not initiate combat. If attacked, he fights "
            "defensively, preferring to use Disengage actions to avoid further conflict "
            "until he can withdraw safely.\n\n"
            "Stone Giant Tongue. Frummach speaks only Giant. A creature can attempt a "
            "DC 12 Charisma (Persuasion) check (with disadvantage if no one in the party "
            "speaks Giant or has a translator) to convince Frummach to act as a guide to "
            "the stone giant clan."
        ),
        "actions": (
            "Greatclub. Melee Weapon Attack: +9 to hit, reach 15 ft., one target. "
            "Hit: 19 (3d8+6) bludgeoning damage.\n\n"
            "Rock. Ranged Weapon Attack: +8 to hit, range 120/240 ft., one target. "
            "Hit: 27 (4d10+6) bludgeoning damage. If the target is a creature, it must "
            "succeed on a DC 15 Strength saving throw or be knocked prone."
        ),
        "bonus_actions": "",
        "reactions": (
            "Rock Catch. If a rock or thrown object is thrown at Frummach, he can use his "
            "reaction to catch it. Any ranged attack using a rock or thrown object "
            "automatically misses him if he uses this reaction."
        ),
        "legendary_actions": "",
        "mythic_actions": "",
        "lair_actions": "",
        "notes": (
            "Random encounter in the crash site environs (Chapter 5). Will guide the party "
            "to the stone giant clan if treated with respect and basic dignity. Knows the "
            "ship as 'a metal mountain that fell from the sky' and believes it is cursed "
            "by evil spirits. Speaks no Common; a translator device or spell is required "
            "for detailed communication."
        ),
        "lore": (
            "Frummach was Froddandan's most trusted scout. After the chief's death, he has "
            "taken a de facto leadership role in the clan's retreat, shepherding survivors "
            "and scouting routes to the Underdark. He deeply distrusts the ship and anyone "
            "willingly entering it, but respects strength and honesty."
        ),
    },

}
