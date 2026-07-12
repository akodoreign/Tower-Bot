"""
seed_treasure_items.py — Seed treasure_items table with campaign loot catalog.

Run: python scripts/seed_treasure_items.py
"""

import mysql.connector

db = mysql.connector.connect(
    host="localhost", user="Claude",
    password="WXdCPJmeDfaQALaktzF6!", database="tower_bot"
)
cur = db.cursor()

# ─── Gadgets (Tower Gadget Store) ────────────────────────────────────────────
GADGETS = [
    ("Lamp of Everburning",     "Light source, never goes out",                     "Permanent",  50,  0),
    ("Sticky Rope",             "Can cling to walls or ceiling",                    "1 use",      25,  0),
    ("Pocket Fan",              "Creates a small gust of wind",                     "3 uses",     10,  0),
    ("Chameleon Cloak",         "Blend into surroundings (Adv Stealth 1 min)",      "2 uses",     75,  0),
    ("Smoke Pellet",            "Small cloud of smoke 10 ft radius",                "1 use",      15,  0),
    ("Evercold Flask",          "Keeps 1 liter liquid perfectly chilled",           "Permanent",  50,  0),
    ("Mirror Tile",             "Reflect small area (10 ft), reveal passages",      "3 uses",     20,  0),
    ("Sound Bubble",            "Silence in 5 ft radius",                           "1 use",      25,  0),
    ("Miniature Grapnel",       "Pull small objects 20 ft",                         "5 uses",     30,  0),
    ("Pocket Sand",             "Blinds target 1 round",                            "1 use",      10,  0),
    ("Everclean Cloth",         "Cleans instantly any object",                      "Permanent",  10,  0),
    ("Ink Spray Pen",           "Spray ink 10 ft radius",                           "2 uses",     10,  0),
    ("Wind-up Toy Soldier",     "Distracts for 1 round",                            "1 use",      15,  0),
    ("Pocket Prism",            "Create dazzling light 5 ft radius",                "2 uses",     20,  0),
    ("Everwarm Mug",            "Keeps drink hot indefinitely",                     "Permanent",  10,  0),
    ("Flash Bubble",            "Flashbang 5 ft radius",                            "1 use",      20,  0),
    ("Signal Whistle",          "Audible for 1 mile",                               "1 use",       5,  0),
    ("Elastic Band of Strength","Plus 1 to lifting for 1 min",                      "2 uses",     20,  0),
    ("Pocket Telescope",        "1 mile visual range",                              "Permanent",  25,  0),
    ("Portable Fan Drone",      "Moves 5 ft of air",                               "3 uses",     20,  0),
    ("Everfresh Bread",         "Does not go stale",                                "Permanent",  10,  0),
    ("Grapple Hook Pen",        "Throws 10 ft tiny grapnel",                       "3 uses",     15,  0),
    ("Miniature Lantern Drone", "10 ft light radius",                               "5 uses",     25,  0),
    ("Pocket Magnifier",        "Examine fine details",                             "Permanent",   5,  0),
    ("Chime of Attention",      "Ring to alert one nearby ally",                    "1 use",      10,  0),
    ("Waterproof Scroll Case",  "Keeps scrolls dry",                               "Permanent",   5,  0),
    ("Tiny Smoke Signal Kit",   "Small smoke column visible at distance",           "1 use",      10,  0),
    ("Portable Ink Stamp",      "Marks items invisibly until touched",              "3 uses",     10,  0),
    ("Pocket Lantern",          "10 ft light radius",                               "1 use",      10,  0),
    ("Wind-up Alarm Mouse",     "Makes noise when area entered",                    "1 use",      15,  0),
    ("Portable Magnets",        "Small magnetic field, pull/push metallic objects", "5 uses",     15,  0),
    ("Everfull Quill",          "Writes indefinitely",                              "Permanent",  20,  0),
    ("Pocket Glowstones",       "Glow for 10 ft",                                  "2 uses",     10,  0),
    ("Mini Smoke Screen",       "Obscures 5 ft radius",                            "1 use",      15,  0),
    ("Elastic Slingshot",       "Shoots small objects as distraction",             "5 uses",     10,  0),
    ("Scent Masking Powder",    "Hides smell for 1 hour",                          "1 use",      20,  0),
    ("Everclean Shoes",         "Leaves no tracks",                                "Permanent",  25,  0),
    ("Mini Firework",           "Loud bang 20 ft radius",                          "1 use",      15,  0),
    ("Portable Ladder Kit",     "Build ladder 10 ft",                              "1 use",      25,  0),
    ("Pocket Soap",             "Lathers instantly",                               "Permanent",   5,  0),
    ("Everbright Candle",       "10 ft light radius",                              "2 uses",     10,  0),
    ("Wind-up Key Rat",         "Small scout 5 ft radius",                         "1 use",      15,  0),
    ("Pocket Compass",          "Always points north",                             "Permanent",   5,  0),
    ("Tiny Hologram Projector", "Shows 2 ft image",                               "3 uses",     25,  0),
    ("Miniature Smoke Bomb",    "Obscures 5 ft radius",                            "1 use",      15,  0),
    ("Everwriting Slate",       "Can erase and rewrite",                           "Permanent",  10,  0),
    ("Small Signal Mirror",     "Flash signal up to 1 mile",                       "Permanent",  10,  0),
    ("Wind-up Music Box",       "Plays tune 1 min",                                "2 uses",     10,  0),
    ("Pocket Water Filter",     "Makes 1 liter water safe to drink",               "Permanent",  10,  0),
    ("Mini Lantern Drone",      "10 ft radius light",                              "5 uses",     20,  0),
    ("Pocket Lockpicks",        "Plus 2 to Dexterity on lockpick checks",          "5 uses",     15,  0),
    ("Wind-up Hawk",            "Scout up to 50 ft",                               "1 use",      20,  0),
    ("Pocket Telescope Lens",   "Examine distant objects",                         "Permanent",  10,  0),
    ("Mini Smoke Bomb",         "5 ft radius distraction",                         "1 use",      10,  0),
    ("Evercool Fan",            "Keeps 10 ft zone cool",                           "Permanent",  10,  0),
    ("Pocket Chalk",            "Marks floor or walls",                            "10 uses",     5,  0),
    ("Wind-up Rabbit",          "Small scout or distraction",                      "1 use",      10,  0),
    ("Mini Signal Fire Kit",    "Small flame visible 50 ft",                       "1 use",      15,  0),
    ("Portable Magnifying Glass","Examine small details",                          "Permanent",   5,  0),
    ("Everburning Torch",       "Provides light, never extinguishes",              "1 use",      10,  0),
]

# ─── Utility (Tower General Store) ───────────────────────────────────────────
UTILITY = [
    ("Rope (50 ft)",           "Standard climbing rope",                    "Permanent",   1, 1),
    ("Iron Spikes (10)",       "Anchor or trapmaking",                      "Permanent",   1, 1),
    ("Flint & Steel",          "Light fire",                                "Permanent",   1, 1),
    ("Torches (5)",            "Provides 20 ft light, burns 1 hr each",    "5 uses",      1, 1),
    ("Crowbar",                "Lever or prying",                           "Permanent",   2, 1),
    ("Chalk (10 sticks)",      "Mark paths or messages",                    "10 uses",     1, 1),
    ("Ink & Quill",            "Writing tool",                              "Permanent",   2, 1),
    ("Paper (10 sheets)",      "Writing or drawing",                        "Permanent",   1, 1),
    ("Small Hammer",           "Light construction or trap-setting",        "Permanent",   2, 1),
    ("Nails (50)",             "Construction or trapmaking",                "Permanent",   1, 1),
    ("Rope Ladder",            "Climb walls or windows, collapsible",       "Permanent",   2, 1),
    ("Bucket",                 "Carry liquids",                             "Permanent",   1, 1),
    ("Waterskin",              "Holds 1 gallon water",                      "Permanent",   1, 1),
    ("Tent (1-person)",        "Shelter",                                   "Permanent",   3, 1),
    ("Blanket",                "Warmth",                                    "Permanent",   1, 1),
    ("Cooking Pot",            "Boil water or food",                        "Permanent",   2, 1),
    ("Rope Coil (10 ft)",      "Extra climbing aid",                        "Permanent",   1, 1),
    ("Lantern",                "Provides light, uses oil",                  "Permanent",   2, 1),
    ("Oil Flask (5)",          "Light source or fire, burns 1 hr each",    "5 uses",      1, 1),
    ("Bucket of Sand",         "Fire suppression",                          "Permanent",   1, 1),
    ("Hammer & Chisel",        "Stone or wood work",                        "Permanent",   2, 1),
    ("Small Mirror",           "See around corners, reveal hidden passages","Permanent",   1, 1),
    ("Rope Hooks (5)",         "Grapple or anchor",                         "Permanent",   2, 1),
    ("String (50 ft)",         "Tying or traps, cheap and multipurpose",   "Permanent",   1, 1),
    ("Bell",                   "Signal or scare, everyday communication",   "Permanent",   1, 1),
    ("Bucket of Water",        "Fire or cleaning",                          "Permanent",   1, 1),
    ("Small Bag",              "Carry items",                               "Permanent",   1, 1),
    ("Large Sack",             "Carry bulk items",                          "Permanent",   2, 1),
    ("Hammer",                 "Construction or improvised combat",         "Permanent",   2, 1),
    ("Rope Coil (25 ft)",      "Larger climbing rope",                      "Permanent",   2, 1),
    ("Cooking Kit",            "Pot, pan, and utensils",                    "Permanent",   2, 1),
    ("Bedroll",                "Sleep comfort",                             "Permanent",   1, 1),
    ("Soap",                   "Hygiene, clever uses possible",             "Permanent",   1, 1),
    ("Rope Bag",               "Organize rope",                             "Permanent",   1, 1),
    ("Water Flask",            "Hold liquids",                              "Permanent",   1, 1),
    ("Lantern Oil",            "Fuel for lantern, burns 1 hr each",        "5 uses",      1, 1),
    ("Small Shovel",           "Digging or survival",                       "Permanent",   2, 1),
    ("Pickaxe",                "Mining or climbing",                        "Permanent",   3, 1),
    ("Rope Pulley",            "Lift or pull items",                        "Permanent",   2, 1),
    ("Candles (5)",            "10 ft light each",                          "5 uses",      1, 1),
    ("Rope Sling",             "Throw or tie items",                        "Permanent",   1, 1),
    ("Small Saw",              "Cut wood",                                  "Permanent",   2, 1),
    ("Needle & Thread",        "Repair clothes",                            "Permanent",   1, 1),
    ("Fishing Hook",           "Fishing or trap-setting",                   "Permanent",   1, 1),
    ("Small Cage",             "Trap or carry small animals",               "Permanent",   2, 1),
    ("Oil Lamp",               "10 ft light",                               "5 uses",      1, 1),
    ("Rope Net",               "Trap or carrying",                          "Permanent",   2, 1),
    ("Rope Coil (100 ft)",     "Long climbing rope",                        "Permanent",   3, 1),
    ("Small Cooking Fire Set", "Fire-starting kit for survival",            "Permanent",   2, 1),
    ("Cloth Pouch",            "Hold coins or small items",                 "Permanent",   1, 1),
    ("Magnifying Glass",       "Examine small objects",                     "Permanent",   2, 1),
]

# ─── Food & Drink ─────────────────────────────────────────────────────────────
FOOD = [
    ("Hardtack (10 pieces)",  "Long-lasting biscuit, standard rations",   "10 uses", 1, 1),
    ("Dried Meat (5 strips)", "Preserved protein, salty",                  "5 uses",  1, 1),
    ("Cheese Wheel (small)",  "Sustains for days, portable luxury",        "5 uses",  2, 2),
    ("Dried Fruit (bag)",     "Sweet preserved fruit, energy boost",        "5 uses",  1, 1),
    ("Smoked Fish",           "Preserved fish, travel staple",              "3 uses",  1, 1),
    ("Honey Jar",             "Sweetener and antiseptic",                   "5 uses",  2, 2),
    ("Tea Leaves Pouch",      "Makes 10 cups of tea",                      "10 uses", 2, 2),
    ("Coffee Beans (bag)",    "10 servings, stimulant",                    "10 uses", 2, 2),
    ("Wine Bottle",           "Mild social lubricant",                      "1 use",   2, 2),
    ("Beer Flask",            "Relaxation, cheap brew",                     "1 use",   1, 1),
    ("Brandy Flask",          "Warming drink for cold weather",             "1 use",   2, 2),
    ("Spice Satchel",         "Enhances bland rations",                     "5 uses",  1, 1),
    ("Salt Pouch",            "Preserves meat, essential cooking",         "10 uses", 1, 1),
    ("Nuts & Seeds Bag",      "Sustains for days, travel snack",           "5 uses",  1, 1),
    ("Jerky Variety Pack",    "Different meats, higher quality",           "5 uses",  2, 2),
    ("Herbal Tea Mix",        "Mild calming effect, good for sleep",       "5 uses",  2, 2),
    ("Cured Sausage",         "Preserved protein, long-lasting",           "3 uses",  1, 1),
    ("Bread Loaf",            "Fills stomach, common staple",              "1 use",   1, 1),
    ("Vinegar Bottle",        "Flavor or disinfectant",                    "3 uses",  1, 1),
    ("Sugar Jar",             "Flavoring, sweet luxury",                   "5 uses",  2, 2),
]

# ─── Elemental Gems ───────────────────────────────────────────────────────────
ELEMENT_TYPES = [
    ("fire", 150), ("cold", 150), ("lightning", 150), ("poison", 100),
    ("acid", 100), ("force", 200), ("radiant", 200), ("necrotic", 200),
    ("thunder", 100), ("psychic", 175),
]
ELEMENTAL_GEMS = [
    (f"Elemental Gem of {elem.title()}",
     f"Socket into a weapon to deal +1d6 {elem} damage on hit. Attunement optional.",
     "Permanent",
     val, 0)
    for elem, val in ELEMENT_TYPES
] + [
    ("Elemental Gem of Silver",
     "Socket into a weapon — it counts as silvered, bypassing resistance/immunity of creatures such as lycanthropes and certain fiends. Permanent.",
     "Permanent",
     125, 0),
]

# ─── Common / Uncommon Magic Items ───────────────────────────────────────────
# Weapons
MAGIC_WEAPONS = [
    ("Weapon, +1 (any)",              "weapon", "+1 to attack and damage rolls",                                                      "uncommon"),
    ("Flame Tongue Dagger",           "weapon", "Bonus action: blade ignites, deals 2d6 fire extra on hit for 1 minute",              "uncommon"),
    ("Sword of Vengeance",            "weapon", "+1; on kill, regain 1d6 HP. Cursed — difficult to part with",                       "uncommon"),
    ("Trident of Fish Command",       "weapon", "Attune: cast Dominate Beast on aquatic creatures at will",                           "uncommon"),
    ("Vicious Weapon (any)",          "weapon", "On a nat 20, deal extra 2d6 damage",                                                 "uncommon"),
    ("Javelin of Lightning",          "weapon", "Thrown: becomes lightning bolt 5x30 ft (DC 13 Dex), then returns",                   "uncommon"),
    ("Dagger of Venom",               "weapon", "Bonus action: coat in poison (DC 15 Con, 2d10 poison) for 1 min once/day",          "uncommon"),
    ("Mace of Disruption",            "weapon", "Undead and fiends: extra 2d6 radiant, DC 15 Wis save or flee",                      "uncommon"),
    ("Sword of Life Stealing",        "weapon", "On crit vs living: deal extra 10 necrotic, gain 10 temp HP",                        "uncommon"),
    ("Shortsword of Warning",         "weapon", "Attune: can't be surprised; advantage on initiative",                               "uncommon"),
    ("Thundering Weapon (any)",       "weapon", "On crit: target takes extra 2d6 thunder, deafened 1 min (DC 14 Con)",               "uncommon"),
    ("Returning Weapon (any thrown)", "weapon", "Returns to hand after being thrown",                                                 "common"),
    ("Moon-Touched Sword (any)",      "weapon", "Blade glows in moonlight, counts as magic damage",                                  "common"),
    ("Weapon of Warning (any)",       "weapon", "Attune: can't be surprised while attuned",                                          "uncommon"),
    ("Giant Slayer (any axe/sword)",  "weapon", "vs Giants: extra 2d6 damage, DC 15 Str save or knocked prone",                      "uncommon"),
]

# Armor
MAGIC_ARMOR = [
    ("Armor, +1 (any)",              "armor",  "+1 to AC",                                                                           "uncommon"),
    ("Adamantine Armor (any medium/heavy)", "armor", "Any crit against you becomes a normal hit",                                    "uncommon"),
    ("Mithral Armor (any medium/heavy)", "armor", "No Strength requirement, no Stealth disadvantage",                               "uncommon"),
    ("Armor of Resistance (any)",    "armor",  "Attune: resistance to one damage type (roll or choose)",                             "uncommon"),
    ("Shield, +1",                   "armor",  "+1 bonus to AC when wielded",                                                        "uncommon"),
    ("Shield of Expression",         "armor",  "Bonus action: change face on shield, harmless effect",                              "common"),
    ("Cast-Off Armor (any)",         "armor",  "Bonus action: doff armor without help",                                             "common"),
    ("Shield of Missile Attraction", "armor",  "Attune: resistance to ranged weapon damage. Cursed: attacks from afar target you",  "uncommon"),
    ("Breastplate of Command",       "armor",  "Attune: advantage on Persuasion, friendly creatures within 30 ft +1 to saves",      "uncommon"),
    ("Glamoured Studded Leather",    "armor",  "Bonus action: change appearance while keeping benefits",                            "uncommon"),
]

# Wondrous Items
MAGIC_WONDROUS = [
    ("Bag of Holding",              "wondrous", "Holds 500 lbs in a 2x4 ft dimensional space",                                      "uncommon"),
    ("Cloak of Protection",         "wondrous", "Attune: +1 to AC and saving throws",                                               "uncommon"),
    ("Goggles of Night",            "wondrous", "Darkvision 60 ft",                                                                 "uncommon"),
    ("Boots of Elvenkind",          "wondrous", "Advantage on Stealth checks involving movement",                                   "uncommon"),
    ("Cloak of Elvenkind",          "wondrous", "Attune: disadvantage on Perception checks to see you; advantage on Stealth",      "uncommon"),
    ("Boots of Striding and Springing", "wondrous", "Speed 30 ft regardless of load; can jump 3x normal distance",                 "uncommon"),
    ("Bracers of Archery",          "wondrous", "Attune: +2 to damage with longbows and shortbows",                                "uncommon"),
    ("Cap of Water Breathing",      "wondrous", "Breathe underwater while worn",                                                    "uncommon"),
    ("Circlet of Blasting",         "wondrous", "1/day: cast Scorching Ray (3 rays) as action",                                    "uncommon"),
    ("Cloak of the Manta Ray",      "wondrous", "Breathe underwater, swim speed 60 ft while worn",                                 "uncommon"),
    ("Driftglobe",                  "wondrous", "Command: cast Light or Daylight; floats 5 ft away",                               "uncommon"),
    ("Dust of Disappearance",       "wondrous", "Spread on up to 10 creatures: all invisible 2d4 min",                             "uncommon"),
    ("Gloves of Missile Snaring",   "wondrous", "Attune: reaction to catch incoming ranged attack, reduce damage by 1d10+Dex",    "uncommon"),
    ("Gloves of Swimming and Climbing","wondrous","Attune: climb/swim speed equal to walking, no check needed",                     "uncommon"),
    ("Hat of Disguise",             "wondrous", "Attune: cast Disguise Self at will",                                              "uncommon"),
    ("Headband of Intellect",       "wondrous", "Attune: Intelligence becomes 19 while worn",                                      "uncommon"),
    ("Helm of Comprehending Languages","wondrous","Cast Comprehend Languages at will while worn",                                   "uncommon"),
    ("Immovable Rod",               "wondrous", "Button: fixed in place, holds 8,000 lbs, until button pressed again",            "uncommon"),
    ("Lantern of Revealing",        "wondrous", "Reveals invisible creatures in its light",                                        "uncommon"),
    ("Medallion of Thoughts",       "wondrous", "Attune: 3 charges; cast Detect Thoughts (DC 13) expend 1 charge",               "uncommon"),
    ("Necklace of Adaptation",      "wondrous", "Attune: breathe normally in any environment, advantage on gaseous saves",         "uncommon"),
    ("Periapt of Health",           "wondrous", "Immunity to disease while worn",                                                  "uncommon"),
    ("Periapt of Wound Closure",    "wondrous", "Attune: stabilize at 0 HP automatically; doubles HD healing",                   "uncommon"),
    ("Pipes of Haunting",           "wondrous", "3 charges/day: play to cast Fear (DC 13 Wis) on up to 10 creatures nearby",     "uncommon"),
    ("Ring of Swimming",            "wondrous", "Swimming speed 40 ft",                                                            "uncommon"),
    ("Rope of Climbing",            "wondrous", "60 ft, animates on command, ties/unties itself, holds 3,000 lbs",                "uncommon"),
    ("Sending Stones",              "wondrous", "Pair: cast Sending to each other once per day",                                   "uncommon"),
    ("Slippers of Spider Climbing", "wondrous", "Attune: climb speed equal to walking, hands-free on walls/ceilings",            "uncommon"),
    ("Stone of Good Luck",          "wondrous", "Attune: +1 to ability checks and saving throws",                                  "uncommon"),
    ("Wand of Magic Detection",     "wondrous", "3 charges, regain 1d3 at dawn: cast Detect Magic",                              "uncommon"),
    ("Wind Fan",                    "wondrous", "1/day: cast Gust of Wind (DC 13 Con save)",                                      "uncommon"),
    ("Candle of the Deep",          "wondrous", "Burns underwater, 5 ft bright, 5 ft dim",                                        "common"),
    ("Charlatan's Die",             "wondrous", "Choose result instead of rolling",                                                "common"),
    ("Cloak of Billowing",          "wondrous", "Bonus action: billow dramatically",                                               "common"),
    ("Enduring Spellbook",          "wondrous", "Cannot be destroyed by fire or water",                                            "common"),
    ("Instrument of Illusions",     "wondrous", "Play to create visual illusions that match the music",                           "common"),
    ("Moodmark Paint",              "wondrous", "Paint symbols on face that express mood magically",                               "common"),
    ("Pot of Awakening",            "wondrous", "Grow a shrub in it for 30 days, shrub becomes awakened",                         "common"),
    ("Ruby of the War Mage",        "wondrous", "Attune: use weapon as arcane focus",                                              "common"),
    ("Talking Doll",                "wondrous", "Attune: speak to it at night, it wakes you with a set phrase",                   "common"),
]

def insert_batch(category, items, rarity="common", item_type=None):
    count = 0
    for row in items:
        name, effect, charges, ec_val, kharma_val = row
        cur.execute("""
            INSERT INTO treasure_items (name, category, item_type, effect, charges, ec_value, kharma_value, rarity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, category, item_type, effect, charges, ec_val, kharma_val, rarity))
        count += 1
    return count

def insert_magic(category, items):
    count = 0
    for name, itype, effect, rarity in items:
        cur.execute("""
            INSERT INTO treasure_items (name, category, item_type, effect, charges, ec_value, kharma_value, rarity)
            VALUES (%s, 'magic_item', %s, %s, 'Permanent', 0, 0, %s)
        """, (name, itype, effect, rarity))
        count += 1
    return count

total = 0
total += insert_batch("gadget",       GADGETS,       "common")
total += insert_batch("utility",      UTILITY,       "common")
total += insert_batch("food",         FOOD,          "common")
total += insert_batch("elemental_gem",ELEMENTAL_GEMS,"uncommon")
total += insert_magic("magic_item",   MAGIC_WEAPONS)
total += insert_magic("magic_item",   MAGIC_ARMOR)
total += insert_magic("magic_item",   MAGIC_WONDROUS)
db.commit()

print(f"Seeded {total} treasure items")
cur.execute("SELECT category, COUNT(*) as n FROM treasure_items GROUP BY category")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")
