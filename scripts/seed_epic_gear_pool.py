"""Seed the epic_gear_pool table with a large variety of high-level D&D items."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()
from src.db_api import raw_execute, raw_query

ITEMS = [
    # ── WEAPONS — martial ──────────────────────────────────────────────────────
    ("Vorpal Sword",                  "weapon", "martial",  17, "legendary"),
    ("Sword of Sharpness",            "weapon", "martial",  13, "very_rare"),
    ("Holy Avenger",                  "weapon", "paladin",  13, "legendary"),
    ("Defender",                      "weapon", "martial",  13, "legendary"),
    ("Sword of Wounding",             "weapon", "martial",  13, "very_rare"),
    ("Sword of Life Stealing",        "weapon", "martial",  13, "very_rare"),
    ("Sword of the Planes",           "weapon", "martial",  17, "legendary"),
    ("Dancing Sword",                 "weapon", "martial",  13, "very_rare"),
    ("Nine Lives Stealer",            "weapon", "martial",  13, "very_rare"),
    ("Flame Tongue",                  "weapon", "martial",  13, "rare"),
    ("Frost Brand",                   "weapon", "martial",  13, "very_rare"),
    ("Sun Blade",                     "weapon", "martial",  13, "very_rare"),
    ("Scimitar of Speed",             "weapon", "martial",  13, "very_rare"),
    ("Berserker Axe",                 "weapon", "martial",  13, "rare"),
    ("Giant Slayer",                  "weapon", "martial",  13, "rare"),
    ("Dwarven Thrower",               "weapon", "martial",  17, "very_rare"),
    ("Hammer of Thunderbolts",        "weapon", "martial",  17, "legendary"),
    ("Mace of Disruption",            "weapon", "martial",  13, "rare"),
    ("Mace of Smiting",               "weapon", "martial",  13, "rare"),
    ("Mace of Terror",                "weapon", "martial",  13, "rare"),
    ("Trident of Fish Command",       "weapon", "martial",  13, "uncommon"),
    ("Spear of Backbiting",           "weapon", "martial",  13, "very_rare"),
    ("Javelin of Lightning",          "weapon", "martial",  13, "uncommon"),
    ("Arrow of Slaying",              "weapon", "ranger",   13, "very_rare"),
    ("Oathbow",                       "weapon", "ranger",   13, "very_rare"),
    ("Dagger of Venom",               "weapon", "any",      13, "rare"),
    ("Dragon Slayer",                 "weapon", "martial",  13, "rare"),
    ("Vicious Weapon",                "weapon", "any",      13, "rare"),
    ("Weapon of Warning",             "weapon", "any",      13, "uncommon"),
    ("Luck Blade",                    "weapon", "any",      17, "legendary"),
    ("Vorpal Scimitar",               "weapon", "martial",  17, "legendary"),
    ("Battering Shield",              "weapon", "martial",  13, "very_rare"),

    # ── ARMOR — martial ────────────────────────────────────────────────────────
    ("Armor, +3",                     "armor",  "martial",  13, "legendary"),
    ("Armor of Invulnerability",      "armor",  "martial",  17, "legendary"),
    ("Armor of Resistance",           "armor",  "any",      13, "rare"),
    ("Demon Armor",                   "armor",  "martial",  13, "very_rare"),
    ("Dragon Scale Mail",             "armor",  "any",      13, "very_rare"),
    ("Dwarven Plate",                 "armor",  "martial",  13, "very_rare"),
    ("Elven Chain",                   "armor",  "any",      13, "rare"),
    ("Mithral Armor",                 "armor",  "any",      13, "uncommon"),
    ("Adamantine Armor",              "armor",  "any",      13, "uncommon"),
    ("Glamoured Studded Leather",     "armor",  "ranger",   13, "rare"),
    ("Plate Armor of Etherealness",   "armor",  "martial",  17, "legendary"),
    ("Spellguard Shield",             "armor",  "any",      13, "very_rare"),
    ("Armor, +2",                     "armor",  "any",      13, "rare"),

    # ── SHIELD ─────────────────────────────────────────────────────────────────
    ("Shield, +3",                    "shield", "martial",  13, "very_rare"),
    ("Shield of Missile Attraction",  "shield", "martial",  13, "rare"),
    ("Sentinel Shield",               "shield", "martial",  13, "uncommon"),
    ("Shield of the Hidden Lord",     "shield", "martial",  17, "legendary"),

    # ── WONDROUS — martial / any ───────────────────────────────────────────────
    ("Belt of Giant Strength (Storm)","wondrous","martial", 17, "legendary"),
    ("Belt of Giant Strength (Fire)", "wondrous","martial", 17, "legendary"),
    ("Belt of Giant Strength (Frost)","wondrous","martial", 17, "legendary"),
    ("Belt of Giant Strength (Stone)","wondrous","martial", 13, "very_rare"),
    ("Belt of Giant Strength (Hill)", "wondrous","martial", 13, "rare"),
    ("Gauntlets of Ogre Power",       "wondrous","martial", 13, "uncommon"),
    ("Ring of Protection",            "wondrous","any",     13, "rare"),
    ("Ring of Regeneration",          "wondrous","any",     13, "very_rare"),
    ("Ring of Resistance",            "wondrous","any",     13, "rare"),
    ("Ring of Spell Turning",         "wondrous","any",     17, "legendary"),
    ("Ring of Three Wishes",          "wondrous","any",     17, "legendary"),
    ("Ring of Invisibility",          "wondrous","any",     17, "legendary"),
    ("Cloak of Displacement",         "wondrous","any",     13, "rare"),
    ("Cloak of Invisibility",         "wondrous","any",     17, "legendary"),
    ("Cloak of Protection",           "wondrous","any",     13, "uncommon"),
    ("Cloak of the Bat",              "wondrous","any",     13, "rare"),
    ("Ioun Stone, Mastery",           "wondrous","any",     17, "legendary"),
    ("Ioun Stone, Protection",        "wondrous","any",     13, "rare"),
    ("Ioun Stone, Regeneration",      "wondrous","any",     17, "legendary"),
    ("Helm of Brilliance",            "wondrous","any",     13, "very_rare"),
    ("Helm of Telepathy",             "wondrous","any",     13, "uncommon"),
    ("Helm of Teleportation",         "wondrous","any",     13, "rare"),
    ("Amulet of Health",              "wondrous","any",     13, "rare"),
    ("Amulet of Proof against Detection","wondrous","any", 13, "uncommon"),
    ("Amulet of the Planes",          "wondrous","any",     17, "very_rare"),
    ("Boots of Speed",                "wondrous","martial", 13, "rare"),
    ("Boots of Striding and Springing","wondrous","any",   13, "uncommon"),
    ("Boots of Teleportation",        "wondrous","any",     17, "very_rare"),
    ("Bracers of Archery",            "wondrous","ranger",  13, "uncommon"),
    ("Bracers of Defense",            "wondrous","caster",  13, "rare"),
    ("Gem of Seeing",                 "wondrous","any",     13, "rare"),
    ("Eyes of the Eagle",             "wondrous","any",     13, "uncommon"),
    ("Scarab of Protection",          "wondrous","any",     17, "legendary"),
    ("Horn of Valhalla, Iron",        "wondrous","martial", 13, "legendary"),
    ("Horn of Valhalla, Bronze",      "wondrous","martial", 13, "very_rare"),
    ("Mantle of Spell Resistance",    "wondrous","any",     13, "rare"),
    ("Necklace of Prayer Beads",      "wondrous","paladin", 13, "rare"),
    ("Periapt of Proof against Poison","wondrous","any",   13, "rare"),
    ("Periapt of Wound Closure",      "wondrous","any",     13, "uncommon"),
    ("Winged Boots",                  "wondrous","any",     13, "uncommon"),
    ("Cape of the Mountebank",        "wondrous","any",     13, "rare"),
    ("Dimensional Shackles",          "wondrous","any",     13, "rare"),

    # ── WONDROUS — caster ─────────────────────────────────────────────────────
    ("Staff of Power",                "wondrous","caster",  17, "very_rare"),
    ("Staff of the Magi",             "wondrous","caster",  17, "legendary"),
    ("Rod of Absorption",             "wondrous","caster",  13, "very_rare"),
    ("Rod of Lordly Might",           "wondrous","caster",  17, "legendary"),
    ("Robe of the Archmagi",          "wondrous","caster",  17, "legendary"),
    ("Robe of Stars",                 "wondrous","caster",  13, "very_rare"),
    ("Tome of Clear Thought",         "wondrous","caster",  17, "very_rare"),
    ("Manual of Quickness of Action", "wondrous","any",     17, "very_rare"),
    ("Manual of Bodily Health",       "wondrous","any",     17, "very_rare"),
    ("Wand of Fireballs",             "wondrous","caster",  13, "rare"),
    ("Wand of Lightning Bolts",       "wondrous","caster",  13, "rare"),
    ("Wand of the War Mage, +3",      "wondrous","caster",  13, "very_rare"),
    ("Wand of Wonder",                "wondrous","caster",  13, "rare"),
    ("Necklace of Fireballs",         "wondrous","any",     13, "rare"),

    # ── FOCUS — caster ────────────────────────────────────────────────────────
    ("Arcane Grimoire, +3",           "focus",   "caster",  13, "very_rare"),
    ("Bloodwell Vial, +3",            "focus",   "caster",  13, "very_rare"),
    ("All-Purpose Tool, +3",          "focus",   "caster",  13, "very_rare"),
    ("Moon Sickle, +3",               "focus",   "caster",  13, "very_rare"),
    ("Rod of the Pact Keeper, +3",    "focus",   "caster",  13, "very_rare"),
    ("Tome of the Stilled Tongue",    "focus",   "caster",  17, "legendary"),
    ("Cauldron of Rebirth",           "focus",   "caster",  17, "very_rare"),
]

def main():
    inserted = skipped = 0
    for row in ITEMS:
        name, slot, class_tags, min_level, rarity = row
        notes = None
        try:
            raw_execute(
                "INSERT IGNORE INTO epic_gear_pool (name, slot, class_tags, min_level, rarity, notes) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (name, slot, class_tags, min_level, rarity, notes),
            )
            inserted += 1
        except Exception as e:
            print(f"  ERROR {name}: {e}")
            skipped += 1

    total = raw_query("SELECT COUNT(*) as n FROM epic_gear_pool")[0]["n"]
    print(f"Seeded {inserted} items ({skipped} skipped). Total in table: {total}")

if __name__ == "__main__":
    main()
