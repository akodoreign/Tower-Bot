"""
Backfill battle map area tags from the live gazetteer.

The map library matches missions through JSON fields on battle_maps_library:
  - suitable_districts: district slugs such as "grand_forum"
  - suitable_mission_types: mission slugs such as "investigation"
  - tags: readable environment/context tags

This script keeps that contract but rebuilds those fields with the current
gazetteer districts and place/profile metadata instead of stale hard-coded
guesses from the first downloader pass.

Usage:
  python scripts/backfill_battle_map_area_tags.py --status
  python scripts/backfill_battle_map_area_tags.py --dry-run --limit 20
  python scripts/backfill_battle_map_area_tags.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import dotenv_values

    for _k, _v in dotenv_values(ROOT / ".env").items():
        if _v is not None and _k not in os.environ:
            os.environ[_k] = _v
except Exception:
    pass

from src.db_api import raw_execute, raw_query


MISSION_BY_MAP_TYPE: dict[str, list[str]] = {
    "street": [
        "ambush", "escort", "battle", "assassination", "gather",
        "investigation", "negotiation", "defense", "strange_occurrences",
    ],
    "sewer": [
        "infestation", "rescue", "recovery", "heist", "discovery",
        "exploration", "sabotage", "strange_occurrences",
    ],
    "cave": [
        "infestation", "discovery", "exploration", "rescue", "recovery",
        "strange_occurrences", "first_contact",
    ],
    "dungeon": [
        "infestation", "heist", "rescue", "recovery", "discovery",
        "assault", "exploration", "puzzle", "strange_occurrences",
    ],
    "tavern": [
        "investigation", "negotiation", "gather", "ambush", "heist",
        "recovery", "assassination",
    ],
    "office": [
        "heist", "infiltration", "investigation", "sabotage",
        "negotiation", "recovery", "assassination",
    ],
    "temple": [
        "discovery", "puzzle", "first_contact", "strange_occurrences",
        "investigation", "recovery", "negotiation",
    ],
    "warehouse": [
        "heist", "ambush", "battle", "sabotage", "escort",
        "infiltration", "recovery",
    ],
    "arena": ["battle", "assassination", "defense", "strange_occurrences"],
    "rooftop": [
        "ambush", "assassination", "escort", "battle", "heist",
        "infiltration",
    ],
    "prison": ["rescue", "heist", "infiltration", "assault", "recovery"],
    "cistern": [
        "infestation", "discovery", "heist", "exploration", "rescue",
        "strange_occurrences",
    ],
    "forge": ["sabotage", "heist", "battle", "infestation", "recovery"],
}


DISTRICTS_BY_MAP_TYPE: dict[str, list[str]] = {
    "street": [
        "cobbleway_market", "markets_infinite", "neon_row",
        "hearthstone_district", "scrapworks", "grand_forum",
        "floating_bazaar", "coppergate", "artisan_quarter",
        "academy_heights", "diplomats_row", "temple_row",
    ],
    "sewer": [
        "grand_forum", "guild_spires", "archive_row", "sanctum_quarter",
        "cobbleway_market", "neon_row", "scrapworks", "ironworks",
        "shantytown_heights", "collapsed_plaza", "markets_infinite",
        "coppergate", "the_fringe",
    ],
    "cave": [
        "the_fringe", "collapsed_plaza", "ashfall_terraces",
        "shantytown_heights", "duskhollow", "the_reliquary",
    ],
    "dungeon": [
        "the_reliquary", "night_pits", "outer_wall", "collapsed_plaza",
        "cult_corners", "duskhollow", "the_fringe",
    ],
    "tavern": [
        "neon_row", "cobbleway_market", "hearthstone_district",
        "floating_bazaar", "coppergate", "markets_infinite",
        "artisan_quarter", "archive_row",
    ],
    "office": [
        "grand_forum", "guild_spires", "diplomats_row", "archive_row",
        "tower_of_last_chance", "academy_heights", "sanctum_quarter",
        "markets_infinite",
    ],
    "temple": [
        "sanctum_quarter", "temple_row", "cult_corners", "the_reliquary",
        "ashfall_terraces", "academy_heights",
    ],
    "warehouse": [
        "scrapworks", "ironworks", "ember_ward", "markets_infinite",
        "floating_bazaar", "coppergate",
    ],
    "arena": ["night_pits", "grand_forum", "outer_wall", "academy_heights"],
    "rooftop": [
        "guild_spires", "scrapworks", "neon_row", "shantytown_heights",
        "academy_heights", "archive_row", "diplomats_row",
    ],
    "prison": ["night_pits", "outer_wall", "tower_of_last_chance"],
    "cistern": [
        "sanctum_quarter", "archive_row", "the_fringe",
        "ashfall_terraces", "collapsed_plaza", "outer_wall",
    ],
    "forge": [
        "ironworks", "scrapworks", "ashfall_terraces", "artisan_quarter",
        "ember_ward",
    ],
}


MAP_TYPE_TAGS: dict[str, list[str]] = {
    "street": ["urban", "exterior", "street"],
    "sewer": ["underground", "wet", "tunnel", "infrastructure"],
    "cave": ["underground", "natural", "rough-terrain"],
    "dungeon": ["underground", "dungeon", "confined"],
    "tavern": ["interior", "social", "commercial"],
    "office": ["interior", "official", "records"],
    "temple": ["sacred", "ritual", "interior"],
    "warehouse": ["interior", "industrial", "storage"],
    "arena": ["open", "combat", "spectacle"],
    "rooftop": ["elevated", "urban", "exterior"],
    "prison": ["confined", "secure", "interior"],
    "cistern": ["underground", "wet", "infrastructure"],
    "forge": ["industrial", "fire", "workshop"],
}


TITLE_TAGS: list[tuple[tuple[str, ...], str]] = [
    (("flood", "water", "submerged", "canal", "dock", "ship", "boat"), "water"),
    (("forest", "jungle", "garden", "park", "grove", "tree"), "green-space"),
    (("ruin", "collapsed", "broken", "decay", "shattered"), "ruins"),
    (("magic", "arcane", "rune", "ritual", "wizard", "spell"), "arcane"),
    (("temple", "shrine", "church", "cathedral", "holy"), "sacred"),
    (("factory", "machine", "gear", "forge", "industrial"), "industrial"),
    (("market", "bazaar", "shop", "vendor", "mall"), "market"),
    (("office", "guild", "archive", "library", "study"), "official"),
    (("hospital", "clinic", "ward", "trauma"), "clinic"),
    (("prison", "jail", "cell", "cage"), "secure"),
    (("roof", "skyscraper", "tower", "spire"), "elevated"),
    (("pit", "arena", "colosseum", "coliseum"), "arena"),
    (("tavern", "inn", "pub", "bar"), "tavern"),
    (("sewer", "drain", "cistern"), "infrastructure"),
    (("cave", "cavern", "mine", "underground"), "underground"),
    (("lava", "fire", "flame", "ash", "volcano"), "fire"),
    (("snow", "ice", "frozen"), "cold"),
    (("dark", "shadow", "night", "gloom"), "dark"),
]


DISTRICT_TAGS: dict[str, list[str]] = {
    "tower_of_last_chance": ["elite", "official", "restricted", "tower"],
    "grand_forum": ["civic", "wealthy", "plaza", "official"],
    "guild_spires": ["wealthy", "guild", "elevated", "official"],
    "archive_row": ["archive", "scholarly", "official", "records"],
    "diplomats_row": ["wealthy", "diplomatic", "official"],
    "sanctum_quarter": ["sacred", "wealthy", "ritual"],
    "temple_row": ["sacred", "wealthy", "ritual"],
    "academy_heights": ["arcane", "scholarly", "campus"],
    "the_reliquary": ["sacred", "arcane", "dungeon"],
    "cult_corners": ["cult", "ritual", "dangerous"],
    "cobbleway_market": ["market", "commercial", "urban"],
    "floating_bazaar": ["market", "commercial", "water"],
    "neon_row": ["nightlife", "commercial", "urban"],
    "night_pits": ["arena", "dangerous", "poor"],
    "scrapworks": ["industrial", "poor", "scrap"],
    "artisan_quarter": ["workshop", "commercial", "craft"],
    "markets_infinite": ["market", "commercial", "dense"],
    "hearthstone_district": ["residential", "social", "middle"],
    "ember_ward": ["fire", "industrial", "poor"],
    "coppergate": ["gate", "market", "poor"],
    "ashfall_terraces": ["ash", "fire", "poor"],
    "duskhollow": ["dark", "dangerous", "poor"],
    "outer_wall": ["fortified", "gate", "military"],
    "ironworks": ["industrial", "forge", "workshop"],
    "shantytown_heights": ["poor", "elevated", "improvised"],
    "collapsed_plaza": ["ruins", "poor", "dangerous"],
    "the_fringe": ["edge", "wild", "poor"],
}


TITLE_DISTRICT_HINTS: list[tuple[tuple[str, ...], list[str]]] = [
    (("archive", "library", "book", "scroll", "study"), ["archive_row", "academy_heights"]),
    (("guild", "spire", "tower", "skyscraper"), ["guild_spires", "academy_heights", "tower_of_last_chance"]),
    (("forum", "plaza", "fountain", "civic"), ["grand_forum"]),
    (("diplomat", "embassy", "estate", "palace", "noble"), ["diplomats_row", "grand_forum"]),
    (("temple", "shrine", "church", "cathedral", "ritual"), ["temple_row", "sanctum_quarter", "the_reliquary", "cult_corners"]),
    (("market", "bazaar", "shop", "vendor", "stall"), ["markets_infinite", "cobbleway_market", "floating_bazaar"]),
    (("tavern", "inn", "pub", "bar"), ["hearthstone_district", "neon_row", "cobbleway_market"]),
    (("forge", "factory", "machine", "industrial", "warehouse"), ["ironworks", "scrapworks", "ember_ward", "artisan_quarter"]),
    (("arena", "pit", "colosseum", "coliseum"), ["night_pits", "grand_forum"]),
    (("prison", "jail", "cell", "guardhouse"), ["outer_wall", "night_pits", "tower_of_last_chance"]),
    (("cave", "mine", "cavern"), ["the_fringe", "collapsed_plaza", "ashfall_terraces"]),
    (("sewer", "drain", "cistern", "canal"), ["archive_row", "sanctum_quarter", "the_fringe", "floating_bazaar"]),
    (("ruin", "collapsed", "broken"), ["collapsed_plaza", "the_fringe", "duskhollow"]),
    (("hospital", "clinic", "ward", "trauma"), ["sanctum_quarter", "archive_row", "hearthstone_district"]),
]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def as_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if str(v).strip()]
        except Exception:
            pass
        return [value] if value.strip() else []
    return []


def ordered_unique(items: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
        if limit and len(out) >= limit:
            break
    return out


def load_known_districts() -> dict[str, dict[str, Any]]:
    rows = raw_query(
        "SELECT district, COUNT(*) AS places, ROUND(AVG(wealth_level), 1) AS wealth "
        "FROM gazetteer_places GROUP BY district"
    ) or []
    districts: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("district") or "")
        if not name:
            continue
        districts[slugify(name)] = {
            "name": name,
            "places": int(row.get("places") or 0),
            "wealth": float(row.get("wealth") or 0),
        }
    return districts


def title_tags(title: str) -> list[str]:
    low = str(title or "").lower()
    tags: list[str] = []
    for words, tag in TITLE_TAGS:
        if any(word in low for word in words):
            tags.append(tag)
    return tags


def title_districts(title: str, known: dict[str, dict[str, Any]]) -> list[str]:
    low = str(title or "").lower()
    districts: list[str] = []
    for words, slugs in TITLE_DISTRICT_HINTS:
        if any(word in low for word in words):
            districts.extend(s for s in slugs if s in known)
    return ordered_unique(districts)


def wealth_tag(wealth_tier: str, district_slugs: list[str], known: dict[str, dict[str, Any]]) -> str:
    tier = str(wealth_tier or "").lower()
    if tier in {"wealthy", "middle", "poor", "underground"}:
        return tier
    values = [known.get(slug, {}).get("wealth", 0) for slug in district_slugs]
    values = [float(v) for v in values if v]
    if not values:
        return "middle"
    avg = sum(values) / len(values)
    if avg >= 7:
        return "wealthy"
    if avg <= 3:
        return "poor"
    return "middle"


def rebuild_row(row: dict[str, Any], known: dict[str, dict[str, Any]]) -> dict[str, list[str] | str]:
    map_type = str(row.get("map_type") or "").strip().lower()
    title = str(row.get("reddit_title") or "")
    old_tags = as_json_list(row.get("tags"))
    old_districts = [slugify(v) for v in as_json_list(row.get("suitable_districts"))]
    old_missions = [slugify(v) for v in as_json_list(row.get("suitable_mission_types"))]

    base_districts = [s for s in DISTRICTS_BY_MAP_TYPE.get(map_type, []) if s in known]
    hinted_districts = title_districts(title, known)
    districts = ordered_unique(hinted_districts + base_districts + old_districts, limit=12)

    if not districts:
        districts = ordered_unique(old_districts, limit=12)

    missions = ordered_unique(
        MISSION_BY_MAP_TYPE.get(map_type, []) + old_missions,
        limit=12,
    )

    tags: list[str] = []
    tags.extend(MAP_TYPE_TAGS.get(map_type, []))
    tags.extend(title_tags(title))
    tags.append(wealth_tag(str(row.get("wealth_tier") or ""), districts, known))
    for slug in districts[:4]:
        tags.extend(DISTRICT_TAGS.get(slug, [])[:3])
    tags.extend(old_tags)
    tags = ordered_unique([slugify(t) for t in tags], limit=18)

    return {
        "suitable_districts": districts,
        "suitable_mission_types": missions,
        "tags": tags,
    }


def load_maps(limit: int = 0) -> list[dict[str, Any]]:
    sql = (
        "SELECT id, file_path, map_type, reddit_title, suitable_districts, "
        "suitable_mission_types, tags, wealth_tier FROM battle_maps_library "
        "ORDER BY id"
    )
    if limit:
        sql += " LIMIT %s"
        return raw_query(sql, (limit,)) or []
    return raw_query(sql) or []


def status() -> None:
    rows = raw_query(
        "SELECT map_type, COUNT(*) AS n, "
        "SUM(JSON_LENGTH(suitable_districts)) AS district_links, "
        "SUM(JSON_LENGTH(suitable_mission_types)) AS mission_links "
        "FROM battle_maps_library GROUP BY map_type ORDER BY n DESC"
    ) or []
    print("Battle map area tag status")
    print(f"{'type':<12} {'maps':>5} {'area links':>11} {'mission links':>13}")
    print("-" * 46)
    for row in rows:
        print(
            f"{row['map_type']:<12} {int(row['n'] or 0):>5} "
            f"{int(row['district_links'] or 0):>11} {int(row['mission_links'] or 0):>13}"
        )


def run(apply: bool = False, dry_run: bool = False, limit: int = 0) -> None:
    known = load_known_districts()
    maps = load_maps(limit=limit)
    if not known:
        raise SystemExit("No gazetteer_places districts found; aborting.")
    if not maps:
        print("No battle_maps_library rows found.")
        return

    changed = 0
    district_counter: Counter[str] = Counter()
    mission_counter: Counter[str] = Counter()
    by_type: defaultdict[str, int] = defaultdict(int)

    for row in maps:
        rebuilt = rebuild_row(row, known)
        old_districts = ordered_unique([slugify(v) for v in as_json_list(row.get("suitable_districts"))])
        old_missions = ordered_unique([slugify(v) for v in as_json_list(row.get("suitable_mission_types"))])
        old_tags = ordered_unique([slugify(v) for v in as_json_list(row.get("tags"))])

        is_changed = (
            rebuilt["suitable_districts"] != old_districts
            or rebuilt["suitable_mission_types"] != old_missions
            or rebuilt["tags"] != old_tags
        )
        if is_changed:
            changed += 1
            by_type[str(row.get("map_type") or "")] += 1

        district_counter.update(rebuilt["suitable_districts"])  # type: ignore[arg-type]
        mission_counter.update(rebuilt["suitable_mission_types"])  # type: ignore[arg-type]

        if dry_run and is_changed:
            print(f"#{row['id']} {row.get('map_type')} - {row.get('reddit_title')}")
            print(f"  districts: {old_districts} -> {rebuilt['suitable_districts']}")
            print(f"  missions:  {old_missions} -> {rebuilt['suitable_mission_types']}")
            print(f"  tags:      {old_tags} -> {rebuilt['tags']}")

        if apply and is_changed:
            raw_execute(
                "UPDATE battle_maps_library SET suitable_districts=%s, "
                "suitable_mission_types=%s, tags=%s WHERE id=%s",
                (
                    json.dumps(rebuilt["suitable_districts"]),
                    json.dumps(rebuilt["suitable_mission_types"]),
                    json.dumps(rebuilt["tags"]),
                    row["id"],
                ),
            )

    mode = "applied" if apply else "dry-run"
    print(f"{mode}: {changed}/{len(maps)} map rows would change" if not apply else f"applied: {changed}/{len(maps)} map rows changed")
    if by_type:
        print("changed by type:", dict(sorted(by_type.items())))
    print("top districts:", dict(district_counter.most_common(12)))
    print("top mission types:", dict(mission_counter.most_common(12)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes to battle_maps_library")
    parser.add_argument("--dry-run", action="store_true", help="Print changed rows without writing")
    parser.add_argument("--status", action="store_true", help="Print aggregate map tag status")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.status:
        status()
    else:
        run(apply=args.apply, dry_run=args.dry_run or not args.apply, limit=args.limit)
