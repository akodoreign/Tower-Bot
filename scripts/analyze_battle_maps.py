"""
analyze_battle_maps.py — Classify downloaded battlemaps using PIL image
analysis + title keyword extraction. No API calls required.

Analysis method:
  - Image brightness + color palette → wealth_tier, environment tags
  - Pixel dimensions → size_class
  - Reddit title keywords → additional tags, refine map type
  - Map type heuristics → suitable_districts, suitable_mission_types

Stores results in battle_maps_library (created by download_battlemaps.py).

Usage:
  python scripts/analyze_battle_maps.py              # analyze all pending
  python scripts/analyze_battle_maps.py --dry-run    # list pending only
  python scripts/analyze_battle_maps.py --status     # DB summary
  python scripts/analyze_battle_maps.py --limit 50   # max N per run
  python scripts/analyze_battle_maps.py --retype     # re-run all
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values as _dv
for _k, _v in _dv(ROOT / ".env").items():
    if _v is not None and _k not in os.environ:
        os.environ[_k] = _v

from PIL import Image, ImageFile
Image.MAX_IMAGE_PIXELS = None   # suppress decompression bomb warning for large maps
ImageFile.LOAD_TRUNCATED_IMAGES = True
from src.db_api import raw_execute, raw_query
from src.log import logger
from src.battle_map_library import ensure_battle_maps_library_schema

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DOWNLOAD_DIR = ROOT / "campaign_docs" / "battle_maps" / "_downloaded"
LOG_FILE     = ROOT / "logs" / "battlemap_analysis.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# Thumbnail size for color analysis — fast, accurate enough
THUMB_SIZE = (64, 64)

# DB schema is managed by src/battle_map_library.ensure_battle_maps_library_schema()
# Do not define DDL here — edit the source function instead.

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ---------------------------------------------------------------------------
# District + mission heuristics (by map type)
# ---------------------------------------------------------------------------

_DISTRICTS: dict[str, list[str]] = {
    "street":    ["cobbleway_market", "markets_infinite", "neon_row",
                  "hearthstone_district", "scrapworks", "grand_forum",
                  "floating_bazaar", "coppergate", "artisan_quarter"],
    "sewer":     ["grand_forum", "guild_spires", "archive_row",
                  "sanctum_quarter", "cobbleway_market", "neon_row",
                  "scrapworks", "ironworks", "shantytown_heights", "collapsed_plaza"],
    "cave":      ["the_fringe", "collapsed_plaza", "ashfall_terraces",
                  "shantytown_heights", "duskhollow"],
    "dungeon":   ["the_reliquary", "night_pits", "outer_wall",
                  "collapsed_plaza", "cult_corners"],
    "tavern":    ["neon_row", "cobbleway_market", "hearthstone_district",
                  "floating_bazaar", "coppergate"],
    "office":    ["grand_forum", "guild_spires", "diplomats_row",
                  "archive_row", "tower_of_last_chance"],
    "temple":    ["sanctum_quarter", "temple_row", "cult_corners", "the_reliquary"],
    "warehouse": ["scrapworks", "ironworks", "ember_ward", "markets_infinite"],
    "arena":     ["night_pits", "grand_forum"],
    "rooftop":   ["guild_spires", "scrapworks", "neon_row", "shantytown_heights"],
    "prison":    ["night_pits", "outer_wall"],
    "cistern":   ["sanctum_quarter", "archive_row", "the_fringe", "ashfall_terraces"],
    "forge":     ["ironworks", "scrapworks", "ashfall_terraces"],
}

_MISSIONS: dict[str, list[str]] = {
    "street":    ["ambush", "escort", "battle", "assassination", "strange_occurrences"],
    "sewer":     ["infestation", "rescue", "heist", "discovery", "sabotage"],
    "cave":      ["infestation", "discovery", "exploration", "rescue"],
    "dungeon":   ["infestation", "heist", "rescue", "discovery", "assault"],
    "tavern":    ["investigation", "negotiation", "gather", "ambush"],
    "office":    ["heist", "infiltration", "investigation", "sabotage"],
    "temple":    ["discovery", "puzzle", "first_contact", "strange_occurrences"],
    "warehouse": ["heist", "ambush", "battle", "sabotage", "escort"],
    "arena":     ["battle", "assassination", "strange_occurrences"],
    "rooftop":   ["ambush", "assassination", "escort", "battle"],
    "prison":    ["rescue", "heist", "infiltration", "assault"],
    "cistern":   ["infestation", "discovery", "heist", "exploration"],
    "forge":     ["sabotage", "heist", "battle", "infestation"],
}

# ---------------------------------------------------------------------------
# Title keyword → extra tags
# ---------------------------------------------------------------------------

_TITLE_TAGS: list[tuple[list[str], str]] = [
    (["flooded", "water", "flood", "submerged"],         "flooded"),
    (["dark", "shadow", "black", "night", "gloomy"],     "dark"),
    (["ruin", "ruined", "collapsed", "broken", "decay"], "ruins"),
    (["forest", "jungle", "outdoor", "exterior"],        "outdoor"),
    (["multi", "two floor", "two level", "upper"],       "multi-level"),
    (["grand", "opulent", "ornate", "noble", "palace"],  "ornate"),
    (["industrial", "factory", "machine", "gear"],       "industrial"),
    (["sci-fi", "scifi", "futuristic", "tech", "cyber"], "sci-fi"),
    (["snow", "ice", "frozen", "arctic", "tundra"],      "cold"),
    (["lava", "volcano", "fire", "flame", "ash"],        "volcanic"),
    (["magic", "arcane", "rune", "ritual", "enchant"],   "arcane"),
    (["ship", "boat", "vessel", "galleon", "dock"],      "nautical"),
    (["cramped", "narrow", "tight", "corridor"],         "cramped"),
    (["open", "wide", "plaza", "courtyard", "field"],    "open"),
    (["prison", "jail", "cell", "cage", "dungeon"],      "confined"),
    (["horror", "undead", "blood", "gore", "corpse"],    "horror"),
    (["city", "town", "village", "urban", "street"],     "urban"),
    (["cave", "cavern", "underground", "mine"],          "underground"),
    (["tavern", "inn", "bar", "pub"],                    "interior"),
    (["office", "guild", "library", "archive", "study"], "interior"),
    (["temple", "shrine", "church", "cathedral"],        "sacred"),
]

def _tags_from_title(title: str, map_type: str) -> list[str]:
    tl = title.lower()
    tags: list[str] = []
    for keywords, tag in _TITLE_TAGS:
        if any(kw in tl for kw in keywords):
            tags.append(tag)

    # Grid size from title e.g. [30x30] [20x40]
    m = re.search(r"\[?\b(\d{1,3})\s*[xX×]\s*(\d{1,3})\b\]?", title)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        sq = w * h
        if sq <= 400:
            tags.append("small")
        elif sq <= 1600:
            tags.append("medium")
        else:
            tags.append("large")

    # Map-type default tag
    type_tag = {
        "street": "urban", "sewer": "underground", "cave": "underground",
        "dungeon": "underground", "tavern": "interior", "office": "interior",
        "temple": "sacred", "warehouse": "interior", "arena": "open",
        "rooftop": "elevated", "prison": "confined", "cistern": "underground",
        "forge": "industrial",
    }.get(map_type, "")
    if type_tag and type_tag not in tags:
        tags.append(type_tag)

    return list(dict.fromkeys(tags))  # dedupe, preserve order


# ---------------------------------------------------------------------------
# PIL image analysis
# ---------------------------------------------------------------------------

def _analyze_image(img_bytes: bytes, map_type: str, title: str) -> dict:
    """
    Derive wealth_tier, size_class, tags, and notes from the image + metadata.
    No network calls — pure PIL + heuristics.
    """
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        return _fallback_analysis(map_type, title, f"PIL open failed: {e}")

    w, h = img.size

    # Thumbnail for fast pixel analysis
    thumb = img.resize(THUMB_SIZE, Image.LANCZOS)
    raw    = thumb.tobytes()
    pixels = [(raw[i], raw[i+1], raw[i+2]) for i in range(0, len(raw), 3)]
    n = len(pixels)

    # Mean RGB
    r_mean = sum(p[0] for p in pixels) / n
    g_mean = sum(p[1] for p in pixels) / n
    b_mean = sum(p[2] for p in pixels) / n
    brightness = (r_mean + g_mean + b_mean) / 3

    # Color spread (standard deviation of brightness per pixel)
    lums = [(p[0]*299 + p[1]*587 + p[2]*114) / 1000 for p in pixels]
    lum_mean = sum(lums) / n
    lum_std  = (sum((l - lum_mean) ** 2 for l in lums) / n) ** 0.5

    # Dominant hue bias
    warm_pixels = sum(1 for p in pixels if p[0] > p[2] + 20)   # red > blue
    cool_pixels = sum(1 for p in pixels if p[2] > p[0] + 20)   # blue > red
    warm_ratio  = warm_pixels / n
    cool_ratio  = cool_pixels / n
    grey_ratio  = sum(1 for p in pixels
                      if abs(p[0]-p[1]) < 20 and abs(p[1]-p[2]) < 20) / n

    # --- Wealth tier ---
    # Dark + underground types → underground
    # Bright + low contrast → wealthy (clean, well-lit)
    # Warm + moderate → middle
    # Dark + warm → poor (torchlit warrens)
    if map_type in {"sewer", "cave", "cistern", "dungeon", "prison"}:
        wealth_tier = "underground"
    elif brightness > 160 and lum_std < 50:
        wealth_tier = "wealthy"
    elif brightness < 80:
        wealth_tier = "poor" if warm_ratio > 0.3 else "underground"
    elif warm_ratio > 0.4 and brightness < 130:
        wealth_tier = "poor"
    else:
        wealth_tier = "middle"

    # --- Size class from pixel dimensions ---
    # Standard VTT is 70-140px per 5ft square
    # Estimate grid squares along shorter edge at 70px/sq
    short_edge  = min(w, h)
    est_squares = short_edge / 70
    if est_squares < 15:
        size_class = "small"
    elif est_squares < 30:
        size_class = "medium"
    else:
        size_class = "large"

    # --- Image-derived tags ---
    img_tags: list[str] = []
    if brightness < 80:
        img_tags.append("dark")
    elif brightness > 180:
        img_tags.append("bright")
    if warm_ratio > 0.45:
        img_tags.append("warm-toned")
    if cool_ratio > 0.35:
        img_tags.append("cool-toned")
    if grey_ratio > 0.5:
        img_tags.append("desaturated")
    if lum_std > 80:
        img_tags.append("high-contrast")

    # --- Title-derived tags ---
    title_tags = _tags_from_title(title, map_type)

    tags = list(dict.fromkeys(title_tags + img_tags))[:8]

    # --- Notes ---
    bright_desc = "dim" if brightness < 80 else ("bright" if brightness > 160 else "moderate")
    tone_desc   = "warm-toned" if warm_ratio > 0.4 else ("cool-toned" if cool_ratio > 0.35 else "neutral")
    size_desc   = f"~{int(est_squares)}x{int(short_edge/70 * (max(w,h)/min(w,h)))} grid squares"
    notes = f"{bright_desc} {tone_desc} {map_type} map, {size_desc} estimated, {wealth_tier} tier aesthetic."

    return {
        "suitable_districts":     _DISTRICTS.get(map_type, []),
        "suitable_mission_types": _MISSIONS.get(map_type, []),
        "tags":       tags,
        "wealth_tier": wealth_tier,
        "size_class":  size_class,
        "notes":       notes,
        "width":  w,
        "height": h,
    }


def _fallback_analysis(map_type: str, title: str, reason: str = "") -> dict:
    tags = _tags_from_title(title, map_type)
    return {
        "suitable_districts":     _DISTRICTS.get(map_type, []),
        "suitable_mission_types": _MISSIONS.get(map_type, []),
        "tags":        tags or [map_type],
        "wealth_tier": "underground" if map_type in {"sewer","cave","dungeon","cistern"} else "middle",
        "size_class":  "medium",
        "notes":       f"{map_type} map (image analysis unavailable: {reason})" if reason else f"{map_type} map.",
        "width":  0,
        "height": 0,
    }

# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

def _parse_filename(path: Path) -> tuple[int, str]:
    stem = path.stem
    m    = re.match(r"(\d+)_(.*)", stem)
    if m:
        return int(m.group(1)), m.group(2).replace("_", " ").strip()
    return 0, stem.replace("_", " ").strip()

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_init() -> None:
    ensure_battle_maps_library_schema()


def _db_upsert(
    file_path: str,
    map_type: str,
    score: int,
    title: str,
    analysis: dict,
) -> None:
    raw_execute(
        """INSERT INTO battle_maps_library
           (file_path, source, map_type, reddit_score, reddit_title,
            suitable_districts, suitable_mission_types, tags,
            wealth_tier, size_class, width, height, file_size_kb,
            analysis_notes, analyzed_at)
           VALUES (%s,'downloaded',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
           ON DUPLICATE KEY UPDATE
             map_type=%s, reddit_score=%s, reddit_title=%s,
             suitable_districts=%s, suitable_mission_types=%s, tags=%s,
             wealth_tier=%s, size_class=%s, width=%s, height=%s,
             file_size_kb=%s, analysis_notes=%s, analyzed_at=NOW()""",
        (
            file_path, map_type, score, title,
            json.dumps(analysis["suitable_districts"]),
            json.dumps(analysis["suitable_mission_types"]),
            json.dumps(analysis["tags"]),
            analysis["wealth_tier"],
            analysis["size_class"],
            analysis.get("width", 0),
            analysis.get("height", 0),
            Path(file_path).stat().st_size // 1024 if Path(file_path).exists() else 0,
            analysis["notes"],
            # ON DUPLICATE
            map_type, score, title,
            json.dumps(analysis["suitable_districts"]),
            json.dumps(analysis["suitable_mission_types"]),
            json.dumps(analysis["tags"]),
            analysis["wealth_tier"],
            analysis["size_class"],
            analysis.get("width", 0),
            analysis.get("height", 0),
            Path(file_path).stat().st_size // 1024 if Path(file_path).exists() else 0,
            analysis["notes"],
        ),
    )


def _db_get_analyzed_paths() -> set[str]:
    rows = raw_query(
        "SELECT file_path FROM battle_maps_library WHERE analyzed_at IS NOT NULL"
    ) or []
    return {r["file_path"] for r in rows}

# ---------------------------------------------------------------------------
# Main pass
# ---------------------------------------------------------------------------

def run(limit: int = 0, dry_run: bool = False, retype: bool = False) -> None:
    _db_init()

    all_pngs: list[Path] = []
    for type_dir in sorted(DOWNLOAD_DIR.iterdir()):
        if type_dir.is_dir():
            for ext in ("*.png", "*.jpg", "*.jpeg"):
                all_pngs.extend(sorted(type_dir.glob(ext)))

    if not all_pngs:
        log(f"No maps found in {DOWNLOAD_DIR}")
        return

    analyzed  = _db_get_analyzed_paths() if not retype else set()
    pending   = [p for p in all_pngs if str(p) not in analyzed]

    log(f"\n{'='*60}")
    log(f"  Battlemap Analysis  total={len(all_pngs)}  analyzed={len(analyzed)}  pending={len(pending)}")
    log(f"{'='*60}\n")

    if not pending:
        log("All maps already analyzed.")
        return

    if limit:
        pending = pending[:limit]
        log(f"  Limiting to {limit} maps\n")

    if dry_run:
        for p in pending:
            score, title = _parse_filename(p)
            log(f"  WOULD ANALYZE: [{p.parent.name}] score={score}  {title[:60]}")
        return

    ok = fail = 0
    for i, path in enumerate(pending, 1):
        map_type        = path.parent.name
        score, title    = _parse_filename(path)
        log(f"[{i:04d}/{len(pending)}] [{map_type}] score={score}  {title[:55]}")

        try:
            img_bytes = path.read_bytes()
            analysis  = _analyze_image(img_bytes, map_type, title)
        except Exception as e:
            log(f"  ERROR: {e} — using fallback")
            analysis = _fallback_analysis(map_type, title, str(e))
            fail += 1
        else:
            ok += 1

        log(f"  tier={analysis['wealth_tier']}  size={analysis['size_class']}  "
            f"tags={', '.join(analysis['tags'][:4])}")

        _db_upsert(str(path), map_type, score, title, analysis)

    log(f"\n{'='*60}")
    log(f"  Done: {ok} analyzed  {fail} fallback")
    log(f"{'='*60}")

# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def print_status() -> None:
    _db_init()
    rows = raw_query("""
        SELECT map_type, wealth_tier,
               COUNT(*) AS total,
               SUM(analyzed_at IS NOT NULL) AS analyzed,
               AVG(reddit_score) AS avg_score
        FROM battle_maps_library
        GROUP BY map_type, wealth_tier
        ORDER BY map_type, wealth_tier
    """) or []

    if not rows:
        log("No maps in library yet.")
        return

    total_all    = sum(r["total"] for r in rows)
    analyzed_all = sum(r["analyzed"] or 0 for r in rows)
    log(f"\n  Battle Map Library: {analyzed_all}/{total_all} analyzed\n")
    log(f"  {'Type':<14} {'Tier':<12} {'Count':>6} {'Analyzed':>9} {'Avg Score':>10}")
    log(f"  {'-'*55}")
    for r in rows:
        log(f"  {r['map_type']:<14} {(r['wealth_tier'] or 'unset'):<12} "
            f"{r['total']:>6} {int(r['analyzed'] or 0):>9} {int(r['avg_score'] or 0):>10}")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--status",  action="store_true")
    p.add_argument("--limit",   type=int, default=0)
    p.add_argument("--retype",  action="store_true", help="Re-analyze already-processed maps")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.status:
        print_status()
    else:
        run(limit=args.limit, dry_run=args.dry_run, retype=args.retype)
