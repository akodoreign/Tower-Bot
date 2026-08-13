"""
rewrite_monsters_2024_phrasing.py -- convert the `monsters` table stat block text
from 2014 (5e) phrasing to 2024 (5.5e / XMM) phrasing.

The campaign is D&D 2024. The 348 curated rows in `monsters` were seeded with 2014
attack phrasing ("Melee Weapon Attack: +6 to hit, reach 5 ft., one target.") while
the published 2024 Monster Manual (XMM) writes the same line as
"Melee Attack Roll: +6, reach 5 ft.". Target format verified directly against XMM
rows in the Mimir catalog, e.g. Warrior Veteran / Knight / Gladiator:

    {@atkr m} {@hit 5}, reach 5 ft. {@h}10 ({@damage 2d6 + 3}) Slashing damage.
    -> Melee Attack Roll: +5, reach 5 ft. Hit: 10 (2d6 + 3) Slashing damage.

What this rewrites (mechanical, reversible, verified by --dry-run):
  1. "<Melee|Ranged|Melee or Ranged> <Weapon|Spell> Attack: +N to hit," ->
     "<Melee|Ranged|Melee or Ranged> Attack Roll: +N,"
  2. drops the 2014 ", one target" / ", one creature" tail (2024 omits it)
  3. dice spacing "2d12+8" -> "2d12 + 8"
  4. damage types capitalised inside damage expressions ("piercing damage" ->
     "Piercing damage"), which is 2024 house style

What it deliberately does NOT touch:
  Abbreviated save clauses ("DC 19 Dex save or pulled 30 ft.", "must make a DC 18
  DEX save. On a failure, ..."). 2024 leads with "Dexterity Saving Throw: DC 19."
  and restructures the sentence around it, which a regex cannot do faithfully.
  Those are reported by --report-saves and left alone.

Usage:
    python scripts/rewrite_monsters_2024_phrasing.py --dry-run          # show diffs, write nothing
    python scripts/rewrite_monsters_2024_phrasing.py --dry-run --limit 5
    python scripts/rewrite_monsters_2024_phrasing.py --apply           # write to MySQL
    python scripts/rewrite_monsters_2024_phrasing.py --report-saves    # list rows with 2014 save clauses
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.db_api import raw_query, raw_execute  # noqa: E402

# Text columns that hold stat block prose.
TEXT_FIELDS = (
    "actions", "traits", "reactions", "bonus_actions",
    "legendary_actions", "mythic_actions", "lair_actions",
)

DAMAGE_TYPES = (
    "bludgeoning", "piercing", "slashing", "fire", "cold", "acid", "poison",
    "necrotic", "radiant", "psychic", "thunder", "lightning", "force",
)

_ATTACK_PREFIX = {
    "melee": "Melee",
    "ranged": "Ranged",
    "melee or ranged": "Melee or Ranged",
}

# "Melee Weapon Attack: +6 to hit," -> "Melee Attack Roll: +6,"
_RE_ATTACK = re.compile(
    r"\b(Melee or Ranged|Melee|Ranged)\s+(?:Weapon|Spell)\s+Attack:\s*([+-]?\d+)\s*to\s+hit\s*,",
    re.IGNORECASE,
)
# Same header without the "to hit" tail (a few rows omit it).
_RE_ATTACK_BARE = re.compile(
    r"\b(Melee or Ranged|Melee|Ranged)\s+(?:Weapon|Spell)\s+Attack:",
    re.IGNORECASE,
)
# 2014 target tail: ", one target." / ", one creature within 5 feet."
_RE_ONE_TARGET = re.compile(r",\s*one\s+(?:target|creature)[^.]*", re.IGNORECASE)
# "2d12+8" -> "2d12 + 8"
_RE_DICE = re.compile(r"(\d+d\d+)\s*([+-])\s*(\d+)")
# Damage types are only capitalised inside an unambiguous damage context. A blanket
# pass would wreck ordinary prose -- "fire at will", "cold iron", "force the door",
# "under fire" all appear in this flavour text.
_TYPES_ALT = "|".join(DAMAGE_TYPES)
# 1. right after a dice group: "(2d12 + 8) bludgeoning"
_RE_TYPE_AFTER_DICE = re.compile(r"(\)\s*)(" + _TYPES_ALT + r")\b", re.IGNORECASE)
# 2. a coordinated list ending in the word "damage": "fire or acid damage"
_RE_TYPE_LIST_DAMAGE = re.compile(
    r"\b((?:" + _TYPES_ALT + r")(?:\s*(?:,|and|or)\s*(?:" + _TYPES_ALT + r"))*)(\s+damage)\b",
    re.IGNORECASE,
)
# 3. a coordinated list after a resistance/immunity/vulnerability lead-in:
#    "Resistant to bludgeoning, piercing, slashing from nonmagical weapons"
_RE_TYPE_LIST_RESIST = re.compile(
    r"\b((?:resistan(?:t|ce)|immune|immunit(?:y|ies)|vulnerab(?:le|ility))\s+to\s+)"
    r"((?:" + _TYPES_ALT + r")(?:\s*(?:,|and|or)\s*(?:" + _TYPES_ALT + r"))*)",
    re.IGNORECASE,
)
_RE_ONE_TYPE = re.compile(r"\b(" + _TYPES_ALT + r")\b", re.IGNORECASE)


def _capitalise_types(text: str) -> str:
    """Capitalise every damage type inside an already-identified damage phrase."""
    return _RE_ONE_TYPE.sub(lambda m: m.group(1).capitalize(), text)
# Left alone, only reported.
_RE_SAVE_2014 = re.compile(
    r"DC\s*\d+\s*(?:STR|DEX|CON|INT|WIS|CHA|Strength|Dexterity|Constitution|"
    r"Intelligence|Wisdom|Charisma)\.?\s*(?:save|saving throw)",
    re.IGNORECASE,
)


def convert(text: str) -> str:
    """Apply the 2014 -> 2024 phrasing rewrite to one stat block field."""
    if not text:
        return text or ""

    out = text

    def _attack(m: re.Match) -> str:
        return f"{_ATTACK_PREFIX[m.group(1).lower()]} Attack Roll: {m.group(2)},"

    out = _RE_ATTACK.sub(_attack, out)
    out = _RE_ATTACK_BARE.sub(
        lambda m: f"{_ATTACK_PREFIX[m.group(1).lower()]} Attack Roll:", out
    )

    out = _RE_ONE_TARGET.sub("", out)
    out = _RE_DICE.sub(r"\1 \2 \3", out)
    out = _RE_TYPE_AFTER_DICE.sub(lambda m: m.group(1) + m.group(2).capitalize(), out)
    out = _RE_TYPE_LIST_DAMAGE.sub(
        lambda m: _capitalise_types(m.group(1)) + m.group(2), out
    )
    out = _RE_TYPE_LIST_RESIST.sub(
        lambda m: m.group(1) + _capitalise_types(m.group(2)), out
    )

    # Cleanup: removing ", one target" leaves "reach 5 ft.." and stray double spaces.
    out = re.sub(r"\.\.+", ".", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([.,])", r"\1", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes to MySQL")
    ap.add_argument("--dry-run", action="store_true", help="show diffs, write nothing")
    ap.add_argument("--report-saves", action="store_true",
                    help="list rows still carrying 2014 save clauses")
    ap.add_argument("--limit", type=int, default=0, help="only show N changed rows")
    args = ap.parse_args()

    if not (args.apply or args.dry_run or args.report_saves):
        ap.error("pass --dry-run, --apply, or --report-saves")

    cols = ", ".join(("id", "name", "cr", "source") + TEXT_FIELDS)
    rows = raw_query(f"SELECT {cols} FROM monsters ORDER BY id") or []

    if args.report_saves:
        hits = 0
        for row in rows:
            found = []
            for field in TEXT_FIELDS:
                for m in _RE_SAVE_2014.finditer(row.get(field) or ""):
                    found.append(f"{field}: ...{m.group(0)}...")
            if found:
                hits += 1
                print(f"#{row['id']:<4} {row['name']:<34} {found[0]}")
        print(f"\n{hits} of {len(rows)} rows carry 2014-style save clauses "
              f"(NOT rewritten -- needs sentence-level work).")
        return 0

    changed_rows = 0
    changed_fields = 0
    shown = 0

    for row in rows:
        updates: dict[str, str] = {}
        for field in TEXT_FIELDS:
            before = row.get(field) or ""
            after = convert(before)
            if after != before:
                updates[field] = after

        if not updates:
            continue

        changed_rows += 1
        changed_fields += len(updates)

        if args.dry_run and (not args.limit or shown < args.limit):
            shown += 1
            print(f"\n{'=' * 78}\n#{row['id']} {row['name']} (CR {row['cr']}, {row['source']})")
            for field, after in updates.items():
                print(f"--- {field} BEFORE ---")
                print((row.get(field) or "").strip())
                print(f"--- {field} AFTER ----")
                print(after.strip())

        if args.apply:
            sets = ", ".join(f"{f}=%s" for f in updates)
            raw_execute(
                f"UPDATE monsters SET {sets}, updated_at=NOW() WHERE id=%s",
                tuple(updates.values()) + (row["id"],),
            )

    verb = "would change" if args.dry_run and not args.apply else "changed"
    print(f"\n{verb}: {changed_rows} of {len(rows)} rows, {changed_fields} field(s).")

    if args.apply:
        leftovers = raw_query(
            "SELECT COUNT(*) c FROM monsters WHERE "
            "actions LIKE '%to hit%' OR actions LIKE '%Weapon Attack:%' "
            "OR actions LIKE '%Spell Attack:%' OR actions LIKE '%one target%'"
        )
        print(f"remaining 2014 attack phrasing in actions: {leftovers[0]['c']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
