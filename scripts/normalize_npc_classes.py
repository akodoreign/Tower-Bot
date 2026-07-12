"""
Normalize NPC class/subclass JSON against the DB-backed D&D class catalog.

Usage:
  python scripts/normalize_npc_classes.py --dry-run
  python scripts/normalize_npc_classes.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db_api import (
    DND_CLASS_CATALOG,
    canonical_class_name,
    canonical_subclass_name,
    ensure_dnd_class_catalog_tables,
    pick_canonical_subclass,
    raw_execute,
    raw_query,
)


KNOWN_CLASSES = {row["class_name"].lower(): row["class_name"] for row in DND_CLASS_CATALOG}


def _json_load(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"none", "null", "nan"} else text


def _infer_class(row: Dict[str, Any], data: Dict[str, Any]) -> str:
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    current = _clean_text(stats.get("class") or data.get("dnd_class") or data.get("class"))
    if current:
        first = re.split(r"\s*/\s*|\s+and\s+", current, maxsplit=1)[0]
        canon = canonical_class_name(first)
        if canon.lower() in KNOWN_CLASSES:
            return canon

    text = " ".join(
        _clean_text(row.get(k) or data.get(k))
        for k in ("rank", "role", "faction", "description", "motivation")
    ).lower()
    checks = [
        (("gunslinger", "gunfighter", "pistol", "rifle", "firearm", "quickdraw", "quick-draw"), "Gunslinger"),
        (("monster hunter", "monster-hunter", "slayer", "quarry"), "Monster Hunter"),
        (("pugilist", "brawler", "boxer", "bare-knuckle", "bareknuckle"), "Pugilist"),
        (("archive", "librarian", "catalog", "spell", "arcane", "wizard", "rune"), "Wizard"),
        (("ritual", "cult", "pact", "patron", "serpent"), "Warlock"),
        (("heal", "medic", "clinic", "divine", "priest", "clergy"), "Cleric"),
        (("smuggl", "spy", "shadow", "dagger", "broker", "intelligence", "inquisit"), "Rogue"),
        (("ranger", "scout", "tracker", "hunt", "patrol"), "Ranger"),
        (("bard", "speaker", "song", "perform", "orator"), "Bard"),
        (("alchemist", "artificer", "construct", "device", "tinker"), "Artificer"),
        (("barbarian", "rage", "berserk"), "Barbarian"),
        (("monk", "martial artist"), "Monk"),
        (("paladin", "oath", "smite"), "Paladin"),
    ]
    for words, cls in checks:
        if any(word in text for word in words):
            return cls
    return "Fighter"


def _preferred_subclass(class_name: str, row: Dict[str, Any], data: Dict[str, Any], existing: str = "") -> str:
    canon = canonical_subclass_name(class_name, existing)
    if canon:
        return canon

    text = " ".join(
        _clean_text(row.get(k) or data.get(k))
        for k in ("name", "rank", "role", "faction", "description", "motivation")
    ).lower()
    if class_name == "Wizard" and "wizards tower" in text and any(
        word in text for word in ("oversees", "final authority", "yaulderna")
    ):
        return "Witch"
    role_choices = {
        "Wizard": [
            (("archive", "scribe", "library", "catalog", "scroll", "research"), "Order of Scribes"),
            (("prophecy", "oracle", "fate", "divin"), "Diviner"),
            (("blade", "duel", "sword", "elf"), "Bladesinger"),
            (("illusion", "deception", "mask", "shadow"), "Illusionist"),
            (("war", "battle", "warden"), "War Magic"),
        ],
        "Rogue": [
            (("investig", "inspector", "compliance", "inquisit"), "Inquisitor"),
            (("broker", "agent", "leader", "guildmaster", "coordinate"), "Mastermind"),
            (("shadow", "assassin", "kill"), "Assassin"),
            (("scout", "tracker", "patrol"), "Scout"),
            (("smuggl", "thief", "stolen", "black-market"), "Thief"),
        ],
        "Fighter": [
            (("captain", "leader", "command", "warden", "patrol"), "Battle Master"),
            (("arcane", "spell", "rune"), "Eldritch Knight"),
            (("arena", "champion"), "Champion"),
        ],
        "Cleric": [
            (("contract", "law", "order", "authority"), "Order Domain"),
            (("clinic", "heal", "saint", "life"), "Life Domain"),
            (("war", "battle"), "War Domain"),
            (("shadow", "trick"), "Trickery Domain"),
        ],
        "Ranger": [
            (("gloom", "shadow", "night"), "Gloom Stalker"),
            (("monster", "slayer"), "Monster Slayer"),
            (("scout", "hunt", "tracker"), "Hunter"),
        ],
        "Bard": [
            (("speaker", "orator", "diplomat", "network"), "College of Eloquence"),
            (("blade", "sword"), "College of Swords"),
            (("lore", "archive"), "College of Lore"),
        ],
        "Warlock": [
            (("serpent", "old one", "whisper", "ritual"), "Great Old One Patron"),
            (("fiend", "devil", "demon"), "Fiend Patron"),
            (("fey",), "Archfey Patron"),
            (("hex", "blade"), "Hexblade"),
        ],
    }
    for words, subclass in role_choices.get(class_name, []):
        if any(word in text for word in words):
            return subclass
    return pick_canonical_subclass(class_name, f"{row.get('name')}:{text}")


def _split_levels(total: int, parts: int) -> List[int]:
    total = max(total, parts)
    base = total // parts
    rem = total % parts
    return [base + (1 if i < rem else 0) for i in range(parts)]


def _multiclass_for_elf(row: Dict[str, Any], data: Dict[str, Any], primary: str, subclass: str) -> Tuple[str, str, List[Dict[str, Any]]]:
    species = _clean_text(row.get("species") or data.get("species")).lower()
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    level = int(stats.get("level") or data.get("level") or 5)
    context = " ".join(
        _clean_text(row.get(k) or data.get(k))
        for k in ("name", "rank", "role", "faction", "description", "motivation")
    ).lower()
    if (
        "elf" not in species
        or level < 8
        or "/" in primary
        or subclass == "Witch"
        or "final authority" in context
        or "oversees all wizards tower operations" in context
    ):
        return primary, subclass, []

    secondary_by_primary = {
        "Wizard": "Rogue",
        "Rogue": "Fighter",
        "Fighter": "Rogue",
        "Ranger": "Rogue",
        "Bard": "Rogue",
        "Cleric": "Fighter",
        "Warlock": "Rogue",
    }
    secondary = secondary_by_primary.get(primary)
    if not secondary:
        return primary, subclass, []

    levels = _split_levels(level, 2)
    secondary_subclass = _preferred_subclass(secondary, row, data)
    classes = [
        {"class": primary, "subclass": subclass, "level": levels[0]},
        {"class": secondary, "subclass": secondary_subclass, "level": levels[1]},
    ]
    return f"{primary} / {secondary}", f"{subclass} / {secondary_subclass}", classes


def normalize_row(row: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    data = _json_load(row.get("data_json"))
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    existing_multiclass = stats.get("multiclass")
    if isinstance(existing_multiclass, list) and existing_multiclass:
        return data, []
    before = json.dumps(data, ensure_ascii=False, sort_keys=True)

    primary = _infer_class(row, data)
    existing_sub = _clean_text(stats.get("subclass") or data.get("subclass"))
    subclass = _preferred_subclass(primary, row, data, existing_sub)
    class_display, subclass_display, multiclass = _multiclass_for_elf(row, data, primary, subclass)

    stats["class"] = class_display
    stats["subclass"] = subclass_display
    stats["multiclass"] = multiclass
    data["stats"] = stats
    data["dnd_class"] = class_display
    data["subclass"] = subclass_display

    after = json.dumps(data, ensure_ascii=False, sort_keys=True)
    changes: List[str] = []
    if before != after:
        changes.append(
            f"{row.get('name')}: {stats.get('level') or '?'} {class_display}"
            + (f" ({subclass_display})" if subclass_display else "")
        )
    return data, changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write normalized NPC JSON to MySQL.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing.")
    args = parser.parse_args()

    ensure_dnd_class_catalog_tables()
    rows = raw_query(
        """
        SELECT id, name, species, role, `rank`, faction, description, motivation, data_json
        FROM npcs
        WHERE data_json IS NOT NULL
        ORDER BY name
        """
    ) or []

    changed = 0
    examples: List[str] = []
    for row in rows:
        data, changes = normalize_row(row)
        if not changes:
            continue
        changed += 1
        examples.extend(changes[:1])
        if args.apply:
            raw_execute(
                "UPDATE npcs SET data_json=%s WHERE id=%s",
                (json.dumps(data, ensure_ascii=False), row["id"]),
            )

    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"{mode}: {changed} NPC rows would change" if not args.apply else f"{mode}: {changed} NPC rows changed")
    for line in examples[:40]:
        print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
