"""
weekly_archive.py — Weekly data archiver for Tower of Last Chance campaign docs.

Moves resolved/completed/sold records from active JSON files into dated
archive files. Active files stay lean for fast reads. Archives are still
accessible for lookups via search_archive() and load_archive().

Archive layout:
  campaign_docs/archives/
    missions/         — resolved mission records (already has .md files)
    towerbay/         — sold TowerBay listings
    player_listings/  — closed player auction listings
    bounties/         — resolved bounty postings
    missing_persons/  — resolved missing persons cases
    outcomes/         — mission debrief outcomes
    news_snapshots/   — weekly snapshots of news_memory.txt
    graveyard/        — tower-absorbed NPCs (permanently dead)

Each archive file: {category}/week_{YYYY-MM-DD}.json
News snapshots: news_snapshots/week_{YYYY-MM-DD}.txt

Run manually:  python -m src.weekly_archive
Run from bot:  from src.weekly_archive import run_weekly_archive

Retrieval:
    search_archive("missions", "Serpent Choir") — full-text search across archives
    load_archive("towerbay", "2026-03-17")      — load a specific week's archive
    load_all_archives("bounties")               — load ALL archived bounties
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.log import logger

DOCS_DIR     = Path(__file__).resolve().parent.parent / "campaign_docs"
ARCHIVES_DIR = DOCS_DIR / "archives"

# Ensure archive subdirs exist
for _sub in ("missions", "towerbay", "player_listings", "bounties",
             "missing_persons", "outcomes", "news_snapshots", "graveyard"):
    (ARCHIVES_DIR / _sub).mkdir(parents=True, exist_ok=True)


def _week_key() -> str:
    """Return current week key like '2026-03-17' (Monday of this week)."""
    now = datetime.now()
    monday = now.date() - __import__("datetime").timedelta(days=now.weekday())
    return monday.isoformat()


def _archive_path(category: str) -> Path:
    return ARCHIVES_DIR / category / f"week_{_week_key()}.json"


def _append_to_archive(category: str, records: list) -> int:
    """Append records to this week's archive file. Returns count appended."""
    if not records:
        return 0
    path = _archive_path(category)
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    existing.extend(records)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(records)


# ---------------------------------------------------------------------------
# Individual archivers
# ---------------------------------------------------------------------------

def _archive_missions() -> int:
    """Archive resolved missions from mission_memory.json."""
    path = DOCS_DIR / "mission_memory.json"
    if not path.exists():
        return 0
    try:
        missions = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    resolved = [m for m in missions if m.get("resolved")]
    active   = [m for m in missions if not m.get("resolved")]

    if not resolved:
        return 0

    count = _append_to_archive("missions", resolved)
    path.write_text(json.dumps(active, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"📦 Archived {count} resolved missions ({len(active)} still active)")
    return count


def _archive_towerbay() -> int:
    """Archive sold TowerBay listings."""
    path = DOCS_DIR / "towerbay.json"
    if not path.exists():
        return 0
    try:
        listings = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    sold   = [l for l in listings if l.get("sold")]
    active = [l for l in listings if not l.get("sold")]

    if not sold:
        return 0

    count = _append_to_archive("towerbay", sold)
    path.write_text(json.dumps(active, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"📦 Archived {count} sold TowerBay listings ({len(active)} still active)")
    return count


def _archive_player_listings() -> int:
    """Archive closed player auction listings (sold or unsold)."""
    path = DOCS_DIR / "player_listings.json"
    if not path.exists():
        return 0
    try:
        listings = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    closed = [l for l in listings if l.get("status") in ("sold", "unsold")]
    active = [l for l in listings if l.get("status") not in ("sold", "unsold")]

    if not closed:
        return 0

    count = _append_to_archive("player_listings", closed)
    path.write_text(json.dumps(active, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"📦 Archived {count} closed player listings ({len(active)} still active)")
    return count


def _archive_bounties() -> int:
    """Archive resolved bounties."""
    path = DOCS_DIR / "bounty_board.json"
    if not path.exists():
        return 0
    try:
        bounties = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    resolved = [b for b in bounties if b.get("resolved")]
    active   = [b for b in bounties if not b.get("resolved")]

    if not resolved:
        return 0

    count = _append_to_archive("bounties", resolved)
    path.write_text(json.dumps(active, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"📦 Archived {count} resolved bounties ({len(active)} still active)")
    return count


def _archive_missing_persons() -> int:
    """Archive resolved missing persons cases."""
    path = DOCS_DIR / "missing_persons.json"
    if not path.exists():
        return 0
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    resolved = [r for r in records if r.get("resolved")]
    active   = [r for r in records if not r.get("resolved")]

    if not resolved:
        return 0

    count = _append_to_archive("missing_persons", resolved)
    path.write_text(json.dumps(active, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"📦 Archived {count} resolved missing persons ({len(active)} still active)")
    return count


def _archive_outcomes() -> int:
    """Archive mission outcomes (completed debriefs)."""
    path = DOCS_DIR / "mission_outcomes.json"
    if not path.exists():
        return 0
    try:
        outcomes = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    if not outcomes:
        return 0

    count = _append_to_archive("outcomes", outcomes)
    # Clear the active file — outcomes are write-once records
    path.write_text("[]", encoding="utf-8")
    logger.info(f"📦 Archived {count} mission outcomes")
    return count


def _archive_graveyard() -> int:
    """Archive tower-absorbed NPCs from npc_graveyard.json.
    These can never come back, so they're safe to move out of active data.
    Non-absorbed dead NPCs stay — they might get graveyard events."""
    path = DOCS_DIR / "npc_graveyard.json"
    if not path.exists():
        return 0
    try:
        graveyard = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    absorbed = [n for n in graveyard if n.get("tower_absorbed")]
    active   = [n for n in graveyard if not n.get("tower_absorbed")]

    if not absorbed:
        return 0

    count = _append_to_archive("graveyard", absorbed)
    path.write_text(json.dumps(active, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"📦 Archived {count} tower-absorbed NPCs ({len(active)} still in graveyard)")
    return count


def _snapshot_news() -> bool:
    """Take a weekly snapshot of news_memory.txt.
    The active file self-trims to 40 entries, so this preserves full history."""
    path = DOCS_DIR / "news_memory.txt"
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return False

    if not content.strip():
        return False

    snap_path = ARCHIVES_DIR / "news_snapshots" / f"week_{_week_key()}.txt"

    # Append to existing snapshot if one already exists this week
    if snap_path.exists():
        existing = snap_path.read_text(encoding="utf-8")
        # Only append if there's new content not already in the snapshot
        if content.strip() != existing.strip():
            snap_path.write_text(
                existing + "\n\n--- SNAPSHOT UPDATE ---\n\n" + content,
                encoding="utf-8",
            )
    else:
        snap_path.write_text(content, encoding="utf-8")

    logger.info(f"📦 News memory snapshot saved: {snap_path.name}")
    return True


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_weekly_archive() -> dict:
    """
    Run all archivers. Returns summary dict.
    Safe to call multiple times — only moves records that are actually resolved.
    """
    logger.info("📦 Weekly archive starting...")

    results = {
        "missions":        _archive_missions(),
        "towerbay":        _archive_towerbay(),
        "player_listings": _archive_player_listings(),
        "bounties":        _archive_bounties(),
        "missing_persons": _archive_missing_persons(),
        "outcomes":        _archive_outcomes(),
        "graveyard":       _archive_graveyard(),
        "news_snapshot":   _snapshot_news(),
    }

    total = sum(v for v in results.values() if isinstance(v, int))
    logger.info(f"📦 Weekly archive complete — {total} records archived")

    return results


# ---------------------------------------------------------------------------
# Retrieval API — search and load archived data
# ---------------------------------------------------------------------------

def load_archive(category: str, week_date: str = "") -> list:
    """
    Load archived records for a category.
    If week_date provided (e.g. '2026-03-17'), loads that specific week.
    If empty, loads the current week's archive.
    Returns list of records, or [] if not found.
    """
    if week_date:
        path = ARCHIVES_DIR / category / f"week_{week_date}.json"
    else:
        path = _archive_path(category)

    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def load_all_archives(category: str) -> list:
    """
    Load ALL archived records for a category across all weeks.
    Returns combined list sorted by file date (oldest first).
    """
    cat_dir = ARCHIVES_DIR / category
    if not cat_dir.exists():
        return []

    all_records = []
    for path in sorted(cat_dir.glob("week_*.json")):
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
            all_records.extend(records)
        except Exception:
            continue
    return all_records


def search_archive(category: str, query: str, max_results: int = 20) -> list:
    """
    Full-text search across all archived records in a category.
    Searches JSON string representation of each record.
    Returns list of matching records (up to max_results).
    """
    query_lower = query.lower()
    all_records = load_all_archives(category)
    matches = []

    for record in all_records:
        record_str = json.dumps(record, ensure_ascii=False).lower()
        if query_lower in record_str:
            matches.append(record)
            if len(matches) >= max_results:
                break

    return matches


def list_archive_weeks(category: str) -> list[str]:
    """List all available archive week dates for a category."""
    cat_dir = ARCHIVES_DIR / category
    if not cat_dir.exists():
        return []
    return sorted(
        path.stem.replace("week_", "")
        for path in cat_dir.glob("week_*.json")
    )


def archive_summary() -> dict:
    """Return a summary of all archives — category: {weeks, total_records}."""
    summary = {}
    for category in ("missions", "towerbay", "player_listings", "bounties",
                     "missing_persons", "outcomes", "graveyard"):
        cat_dir = ARCHIVES_DIR / category
        if not cat_dir.exists():
            summary[category] = {"weeks": 0, "records": 0}
            continue
        weeks = list(cat_dir.glob("week_*.json"))
        total = 0
        for w in weeks:
            try:
                total += len(json.loads(w.read_text(encoding="utf-8")))
            except Exception:
                pass
        summary[category] = {"weeks": len(weeks), "records": total}

    # News snapshots are text, count differently
    snap_dir = ARCHIVES_DIR / "news_snapshots"
    snap_count = len(list(snap_dir.glob("week_*.txt"))) if snap_dir.exists() else 0
    summary["news_snapshots"] = {"weeks": snap_count, "records": snap_count}

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = run_weekly_archive()
    print(f"\n📦 Archive complete:")
    for k, v in results.items():
        print(f"  {k}: {v}")
    print(f"\n📊 Archive inventory:")
    for cat, info in archive_summary().items():
        print(f"  {cat}: {info['weeks']} weeks, {info['records']} records")
