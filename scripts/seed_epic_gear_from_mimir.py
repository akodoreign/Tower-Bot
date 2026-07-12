"""
Seed epic_gear_pool from the live Mimir catalog.
Pulls all very_rare and legendary items, classifies each by slot and class_tags,
and upserts into the DB. Run this any time you want to refresh the pool.

Usage:
    python scripts/seed_epic_gear_from_mimir.py [--dry-run]
"""
import sys, os, asyncio, re, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.db_api import raw_execute, raw_query

# ── Slot classification ────────────────────────────────────────────────────────
# These keyword sets classify Mimir items into our slot/class_tags scheme.

_WEAPON_WORDS = {
    "sword", "blade", "dagger", "axe", "mace", "hammer", "spear", "lance",
    "bow", "crossbow", "club", "flail", "glaive", "halberd", "maul", "morningstar",
    "pike", "rapier", "scimitar", "shortsword", "sickle", "trident", "war pick",
    "warhammer", "whip", "quarterstaff", "javelin", "dart", "sling", "net",
    "arrow", "bolt", "flame tongue", "frost brand", "vorpal", "defender",
    "berserker", "dancing", "nine lives", "sun blade", "dragon slayer",
    "giant slayer", "luck blade", "oathbow", "dwarven thrower",
}
_ARMOR_WORDS = {
    "armor", "mail", "plate", "leather", "hide", "chain", "scale", "breastplate",
    "half plate", "ring mail", "splint", "studded",
}
_SHIELD_WORDS = {"shield"}
_FOCUS_WORDS  = {
    "grimoire", "bloodwell", "all-purpose tool", "moon sickle", "rod of the pact",
    "tome of the stilled", "cauldron of rebirth", "spellbook",
}
_CASTER_WORDS = {
    "staff", "wand", "rod", "orb", "robe", "archmagi", "tome", "scroll",
    "grimoire", "bloodwell", "moon sickle", "pact keeper", "cauldron",
    "spellbook", "crystal", "arcane focus",
}
_MARTIAL_WORDS = {
    "sword", "axe", "hammer", "mace", "spear", "flail", "glaive", "halberd",
    "maul", "pike", "scimitar", "trident", "war pick", "warhammer", "berserker",
    "giant slayer", "dragon slayer", "dwarven thrower", "defender", "vorpal",
    "belt of giant", "gauntlets of ogre", "boots of speed", "horn of valhalla",
}
_RANGER_WORDS = {
    "bow", "arrow", "crossbow", "oathbow", "bracers of archery",
    "glamoured", "hunter",
}
_PALADIN_WORDS = {
    "holy avenger", "necklace of prayer", "devotion", "aura",
}

RARITY_MIN_LEVEL = {
    "uncommon": 5,
    "rare":     9,
    "very_rare": 13,
    "legendary": 17,
    "artifact":  17,
}


def _classify(item: dict) -> dict | None:
    """Return {slot, class_tags, min_level} or None if we can't classify it."""
    raw_name = (item.get("name") or "").strip()
    raw_type = (item.get("item_type") or item.get("type") or "").lower()
    rarity   = (item.get("rarity") or "").lower().replace(" ", "_")
    name_low = raw_name.lower()

    if not raw_name or rarity not in RARITY_MIN_LEVEL:
        return None

    min_level = RARITY_MIN_LEVEL[rarity]

    # Slot
    if any(w in name_low for w in _SHIELD_WORDS) and "shield" in raw_type:
        slot = "shield"
    elif any(w in name_low for w in _FOCUS_WORDS):
        slot = "focus"
    elif any(w in name_low for w in _WEAPON_WORDS) or "weapon" in raw_type:
        slot = "weapon"
    elif any(w in name_low for w in _ARMOR_WORDS) or "armor" in raw_type:
        slot = "armor"
    else:
        slot = "wondrous"

    # Class tags
    if any(w in name_low for w in _PALADIN_WORDS):
        class_tags = "paladin"
    elif any(w in name_low for w in _RANGER_WORDS):
        class_tags = "ranger"
    elif any(w in name_low for w in _CASTER_WORDS) or slot == "focus":
        class_tags = "caster"
    elif any(w in name_low for w in _MARTIAL_WORDS):
        class_tags = "martial"
    else:
        class_tags = "any"

    return {"slot": slot, "class_tags": class_tags, "min_level": min_level, "rarity": rarity}


async def fetch_all_epic(mimir) -> list[dict]:
    """Pull very_rare and legendary items from the Mimir catalog."""
    all_items = []
    for rarity in ("rare", "very rare", "legendary", "artifact"):
        print(f"  Querying Mimir: rarity={rarity!r}...")
        try:
            items = await mimir.search_items(rarity=rarity)
            print(f"    -> {len(items)} items")
            all_items.extend(items)
        except Exception as e:
            print(f"    -> ERROR: {e}")
    return all_items


async def main_async(dry: bool):
    from src.mimir_client import get_mimir
    mimir = get_mimir()
    connected = mimir.available or await mimir.connect()
    if not connected:
        print("ERROR: Mimir not connected.")
        return

    print("Fetching epic items from Mimir catalog...")
    items = await fetch_all_epic(mimir)
    print(f"Total fetched: {len(items)}\n")

    inserted = skipped = unclassified = 0
    for item in items:
        name = (item.get("name") or "").strip()
        if not name:
            continue

        info = _classify(item)
        if not info:
            unclassified += 1
            continue

        if dry:
            print(f"  [{info['slot']:8}] [{info['class_tags']:8}] lv{info['min_level']} {name}")
            inserted += 1
            continue

        try:
            raw_execute(
                """INSERT INTO epic_gear_pool (name, slot, class_tags, min_level, rarity, enabled)
                   VALUES (%s, %s, %s, %s, %s, 1)
                   ON DUPLICATE KEY UPDATE
                     slot=VALUES(slot), class_tags=VALUES(class_tags),
                     min_level=VALUES(min_level), rarity=VALUES(rarity), enabled=1""",
                (name, info["slot"], info["class_tags"], info["min_level"], info["rarity"]),
            )
            inserted += 1
        except Exception as e:
            print(f"  DB error for {name!r}: {e}")
            skipped += 1

    total = raw_query("SELECT COUNT(*) as n FROM epic_gear_pool")[0]["n"] if not dry else "N/A"
    print(f"\nInserted/updated: {inserted} | Skipped: {skipped} | Unclassified: {unclassified}")
    print(f"Total in table: {total}")
    if dry:
        print("(dry run — nothing written)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args.dry_run))


if __name__ == "__main__":
    main()
