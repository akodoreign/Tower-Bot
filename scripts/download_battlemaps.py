"""
download_battlemaps.py — Download top-scoring battlemaps from r/battlemaps
and organize them into campaign_docs/battle_maps/<type>/ for use as district maps.

Filters:
  - Minimum score (default 300) to ensure quality
  - Image posts only (no videos, no links to external sites)
  - Skips nature/wilderness/ocean maps (not useful for Undercity)
  - Stops at MAX_GB total downloaded

Maps are categorized by type from post title keywords and saved as:
  campaign_docs/battle_maps/_downloaded/<type>/<score>_<slug>.png

Run --dry-run first to see what would be downloaded without actually fetching images.

Usage:
  python scripts/download_battlemaps.py
  python scripts/download_battlemaps.py --min-score 500
  python scripts/download_battlemaps.py --dry-run
  python scripts/download_battlemaps.py --type sewer
  python scripts/download_battlemaps.py --max-gb 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env before anything else — must happen before os.getenv calls
from dotenv import dotenv_values as _dv
for _k, _v in _dv(ROOT / ".env").items():
    if _v is not None and _k not in os.environ:
        os.environ[_k] = _v

import httpx

from src.db_api import raw_execute
from src.battle_map_library import ensure_battle_maps_library_schema

OUT_DIR  = ROOT / "campaign_docs" / "battle_maps" / "_downloaded"
LOG_FILE = ROOT / "logs" / "battlemap_download.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

def _reddit_headers() -> dict:
    """Build request headers. Token-only auth — sending Cookie alongside Bearer breaks OAuth."""
    token = os.getenv("REDDIT_TOKEN", "")
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

# ---------------------------------------------------------------------------
# Map type keyword matching — post title → our map type
# ---------------------------------------------------------------------------

# Types we actually want for the Undercity
TYPE_KEYWORDS: dict[str, list[str]] = {
    "street":    ["street", "town", "city", "urban", "alley", "district", "village",
                  "market", "road", "plaza", "square", "cobble", "neighbourhood",
                  "neighborhood", "quarter", "bazaar", "crossroads"],
    "sewer":     ["sewer", "drain", "pipe", "waterway", "cistern", "aqueduct",
                  "undercity", "beneath", "underground passage"],
    "cave":      ["cave", "cavern", "grotto", "underground", "tunnel", "mine",
                  "hollow", "spelunk", "stalactite", "underdark"],
    "tavern":    ["tavern", "inn", "bar", "pub", "alehouse", "brewery",
                  "drinking", "common room", "roadhouse"],
    "dungeon":   ["dungeon", "vault", "tomb", "crypt", "catacombs", "prison",
                  "jail", "cell", "keep", "fortress interior", "stronghold"],
    "temple":    ["temple", "shrine", "church", "cathedral", "sanctum", "chapel",
                  "monastery", "altar", "holy", "divine", "sacred", "religious"],
    "office":    ["office", "guild", "hall", "headquarters", "study", "library",
                  "archive", "laboratory", "lab", "workshop", "mansion", "manor",
                  "estate", "noble", "council"],
    "warehouse": ["warehouse", "dock", "storage", "cargo", "factory", "industrial",
                  "forge", "smithy", "foundry", "shipyard"],
    "rooftop":   ["rooftop", "roof", "skyline", "aerial", "tower top", "parapet"],
    "arena":     ["arena", "colosseum", "pit", "gladiator", "ring", "stadium",
                  "fighting pit", "combat arena"],
    "forest":    ["forest", "wood", "jungle", "swamp", "wilderness", "nature",
                  "outdoor", "exterior", "grassland", "plains", "field",
                  "beach", "ocean", "sea", "river", "lake", "coast", "island",
                  "desert", "tundra", "snow", "arctic", "volcanic", "lava"],  # SKIP
}

# Types to skip entirely — not useful for Undercity indoor/urban maps
SKIP_TYPES = {"forest"}

# Minimum score to bother downloading
DEFAULT_MIN_SCORE = 300
# Max total download size
DEFAULT_MAX_GB = 10.0
# Pause between Reddit API calls (be polite)
REDDIT_PAUSE = 1.5
# Image extensions we'll accept
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower().strip())[:60].strip("_")


def classify_post(title: str) -> Optional[str]:
    """Return map type for this post title, or None if unclassifiable/skipped."""
    title_lower = title.lower()
    scores: dict[str, int] = {}
    for mtype, keywords in TYPE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in title_lower)
        if hits:
            scores[mtype] = hits
    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    if best in SKIP_TYPES:
        return None
    return best


def dir_size_gb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 ** 3)


def extract_image_url(post: dict) -> Optional[str]:
    """Pull the best direct image URL from a Reddit post dict."""
    url: str = post.get("url", "")

    # Direct image link
    if any(url.lower().endswith(ext) for ext in IMAGE_EXTS):
        return url

    # i.redd.it
    if "i.redd.it" in url:
        return url

    # Reddit gallery — grab the highest-res first image
    if post.get("is_gallery") and post.get("media_metadata"):
        for item in post["media_metadata"].values():
            if item.get("status") == "valid" and item.get("s"):
                src = item["s"].get("u") or item["s"].get("gif")
                if src:
                    return src.replace("&amp;", "&")

    # preview image fallback
    preview = post.get("preview", {})
    images = preview.get("images", [])
    if images:
        source = images[0].get("source", {})
        if source.get("url"):
            return source["url"].replace("&amp;", "&")

    return None


# ---------------------------------------------------------------------------
# DB registration — write every saved map to battle_maps_library immediately.
# analyze_battle_maps.py fills in vision tags later; this ensures the DB
# knows about every file the moment it lands on disk.
# ---------------------------------------------------------------------------

_DB_INIT_DONE = False

def _db_ensure_table() -> None:
    global _DB_INIT_DONE
    if _DB_INIT_DONE:
        return
    try:
        ensure_battle_maps_library_schema()
        _DB_INIT_DONE = True
    except Exception as e:
        log(f"  [DB] Table init failed (non-fatal): {e}")


# Heuristic defaults used until Claude vision analysis runs
_HEURISTIC_DISTRICTS: dict[str, list[str]] = {
    "street":    ["cobbleway_market", "markets_infinite", "neon_row", "hearthstone_district", "scrapworks", "grand_forum"],
    "sewer":     ["grand_forum", "guild_spires", "archive_row", "sanctum_quarter", "cobbleway_market", "neon_row", "scrapworks", "ironworks", "shantytown_heights", "collapsed_plaza"],
    "cave":      ["the_fringe", "collapsed_plaza", "ashfall_terraces", "shantytown_heights", "duskhollow"],
    "dungeon":   ["the_reliquary", "night_pits", "outer_wall", "collapsed_plaza", "cult_corners"],
    "tavern":    ["neon_row", "cobbleway_market", "hearthstone_district", "floating_bazaar", "coppergate"],
    "office":    ["grand_forum", "guild_spires", "diplomats_row", "archive_row", "tower_of_last_chance"],
    "temple":    ["sanctum_quarter", "temple_row", "cult_corners", "the_reliquary"],
    "warehouse": ["scrapworks", "ironworks", "ember_ward", "markets_infinite"],
    "arena":     ["night_pits", "grand_forum"],
    "rooftop":   ["guild_spires", "scrapworks", "neon_row", "shantytown_heights"],
    "prison":    ["night_pits", "outer_wall"],
    "cistern":   ["sanctum_quarter", "archive_row", "the_fringe", "ashfall_terraces"],
    "forge":     ["ironworks", "scrapworks", "ashfall_terraces"],
}
_HEURISTIC_MISSIONS: dict[str, list[str]] = {
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

import json as _json

def _db_register(out_path: Path, mtype: str, score: int, title: str) -> None:
    """Insert map into battle_maps_library with heuristic defaults. No-op if already exists."""
    _db_ensure_table()
    kb = out_path.stat().st_size // 1024
    try:
        raw_execute(
            """INSERT IGNORE INTO battle_maps_library
               (file_path, source, map_type, reddit_score, reddit_title,
                suitable_districts, suitable_mission_types, file_size_kb)
               VALUES (%s, 'downloaded', %s, %s, %s, %s, %s, %s)""",
            (
                str(out_path), mtype, score, title,
                _json.dumps(_HEURISTIC_DISTRICTS.get(mtype, [])),
                _json.dumps(_HEURISTIC_MISSIONS.get(mtype, [])),
                kb,
            ),
        )
    except Exception as e:
        log(f"  [DB] Register failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Reddit fetcher
# ---------------------------------------------------------------------------

async def fetch_posts(
    after: str = "",
    limit: int = 100,
    timeframe: str = "all",
) -> tuple[list[dict], str]:
    """Fetch one page of top posts. Returns (posts, next_after)."""
    params = {"limit": limit, "t": timeframe, "raw_json": 1}
    if after:
        params["after"] = after

    # oauth.reddit.com is the only endpoint that works with Bearer token
    url = "https://oauth.reddit.com/r/battlemaps/top"

    try:
        async with httpx.AsyncClient(
            headers=_reddit_headers(), timeout=30.0, follow_redirects=True
        ) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        children = data["data"]["children"]
        posts = [c["data"] for c in children]
        next_after = data["data"].get("after") or ""
        return posts, next_after
    except Exception as e:
        log(f"  [Reddit] Fetch error: {e}")
        return [], ""


async def download_image(url: str, out_path: Path) -> bool:
    """Download a single image to out_path. Returns True on success."""
    try:
        async with httpx.AsyncClient(
            headers={**_reddit_headers(), "Accept": "image/*"},
            timeout=60.0,
            follow_redirects=True,
        ) as c:
            r = await c.get(url)
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            if "image" not in ct and "octet" not in ct:
                return False
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(r.content)
            return True
    except Exception as e:
        log(f"    [DL] Error {url}: {e}")
        return False


# ---------------------------------------------------------------------------
# Main pass
# ---------------------------------------------------------------------------

async def run(
    min_score: int = DEFAULT_MIN_SCORE,
    max_gb: float = DEFAULT_MAX_GB,
    type_filter: str = "",
    dry_run: bool = False,
    timeframes: list[str] | None = None,
) -> None:
    if timeframes is None:
        timeframes = ["all", "year", "month"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    skipped_score = skipped_type = skipped_ext = dl_ok = dl_fail = 0
    seen_ids: set[str] = set()

    log(f"\n{'='*60}")
    log(f"  Battlemap download  min_score={min_score}  max_gb={max_gb}  dry_run={dry_run}")
    log(f"{'='*60}")

    for tf in timeframes:
        log(f"\n  Timeframe: {tf}")
        after = ""
        pages = 0

        while True:
            if dir_size_gb(OUT_DIR) >= max_gb:
                log(f"  Size limit {max_gb}GB reached — stopping.")
                return

            posts, after = await fetch_posts(after=after, limit=100, timeframe=tf)
            if not posts:
                break
            pages += 1

            for post in posts:
                pid = post.get("id", "")
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)

                score = post.get("score", 0)
                title = post.get("title", "")

                if score < min_score:
                    skipped_score += 1
                    continue

                mtype = classify_post(title)
                if mtype is None:
                    skipped_type += 1
                    continue

                if type_filter and mtype != type_filter:
                    continue

                img_url = extract_image_url(post)
                if not img_url:
                    skipped_ext += 1
                    continue

                ext = Path(img_url.split("?")[0]).suffix.lower() or ".png"
                if ext not in IMAGE_EXTS:
                    skipped_ext += 1
                    continue

                slug = slugify(title)
                filename = f"{score:06d}_{slug}{ext}"
                out_path = OUT_DIR / mtype / filename

                if out_path.exists():
                    continue

                size_gb = dir_size_gb(OUT_DIR)
                log(f"  [{mtype:10s}] score={score:5d}  {title[:60]}  ({size_gb:.2f}GB)")

                if dry_run:
                    counts[mtype] = counts.get(mtype, 0) + 1
                    continue

                ok = await download_image(img_url, out_path)
                if ok:
                    kb = out_path.stat().st_size // 1024
                    log(f"    -> saved {kb}KB")
                    _db_register(out_path, mtype, score, title)
                    dl_ok += 1
                    counts[mtype] = counts.get(mtype, 0) + 1
                else:
                    dl_fail += 1

                await asyncio.sleep(0.5)

            log(f"  Page {pages}: processed {len(posts)} posts, after={after or 'END'}")
            if not after:
                break
            await asyncio.sleep(REDDIT_PAUSE)

    log(f"\n{'='*60}")
    log(f"  Downloaded: {dl_ok}  Failed: {dl_fail}  Skipped (score): {skipped_score}  Skipped (type): {skipped_type}")
    log(f"  Total size: {dir_size_gb(OUT_DIR):.2f}GB")
    log(f"\n  By type:")
    for t, n in sorted(counts.items()):
        log(f"    {t:<12} {n}")
    log(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE,
                   help="Minimum Reddit score (default 300)")
    p.add_argument("--max-gb",    type=float, default=DEFAULT_MAX_GB,
                   help="Max total download size in GB (default 10)")
    p.add_argument("--type",      default="",
                   help="Only download one map type (e.g. sewer)")
    p.add_argument("--dry-run",   action="store_true",
                   help="List what would be downloaded without saving")
    p.add_argument("--timeframe", default="",
                   help="Comma-separated timeframes: all,year,month (default: all three)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    tf = [t.strip() for t in args.timeframe.split(",") if t.strip()] or None
    asyncio.run(run(
        min_score=args.min_score,
        max_gb=args.max_gb,
        type_filter=args.type,
        dry_run=args.dry_run,
        timeframes=tf,
    ))
