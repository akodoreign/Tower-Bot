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

def _db_rows_to_list(rows) -> list:
    """Convert DB rows (dicts) to plain serialisable list."""
    result = []
    for row in (rows or []):
        r = dict(row)
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
        result.append(r)
    return result


def _archive_query_in_batches(category: str, where_sql: str = "", params: tuple = (), batch_size: int = 500) -> int:
    """Append matching DB rows to an archive without loading a whole table at once."""
    from src.db_api import raw_query

    total = 0
    last_id = 0
    while True:
        rows = raw_query(
            f"SELECT * FROM {category} WHERE id > %s {where_sql} ORDER BY id ASC LIMIT %s",
            (last_id, *params, batch_size),
        ) or []
        if not rows:
            break
        records = _db_rows_to_list(rows)
        total += _append_to_archive(category, records)
        last_id = int(rows[-1]["id"])
        if len(rows) < batch_size:
            break
    return total


def _archive_named_query_in_batches(category: str, table: str, where_sql: str = "", params: tuple = (), batch_size: int = 500) -> int:
    """Append rows from table into a differently named archive category."""
    from src.db_api import raw_query

    total = 0
    last_id = 0
    while True:
        rows = raw_query(
            f"SELECT * FROM {table} WHERE id > %s {where_sql} ORDER BY id ASC LIMIT %s",
            (last_id, *params, batch_size),
        ) or []
        if not rows:
            break
        records = _db_rows_to_list(rows)
        total += _append_to_archive(category, records)
        last_id = int(rows[-1]["id"])
        if len(rows) < batch_size:
            break
    return total


def _archive_missions() -> int:
    """Archive completed/failed/expired missions from DB."""
    try:
        count = _archive_query_in_batches("missions", "AND status IN ('completed','failed','expired')")
        if count:
            logger.info("Archived %d resolved missions", count)
        return count
        from src.db_api import raw_query, raw_execute
        rows = raw_query(
            "SELECT * FROM missions WHERE status IN ('completed','failed','expired')"
        ) or []
        records = _db_rows_to_list(rows)
        if not records:
            return 0
        count = _append_to_archive("missions", records)
        logger.info(f"📦 Archived {count} resolved missions")
        return count
    except Exception as e:
        logger.warning(f"📦 _archive_missions DB error: {e}")
        return 0


def _archive_towerbay() -> int:
    """Archive sold/ended TowerBay auctions from DB."""
    try:
        count = _archive_named_query_in_batches("towerbay", "towerbay_auctions", "AND status IN ('sold','ended','expired')")
        if count:
            logger.info("Archived %d TowerBay auctions", count)
        return count
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT * FROM towerbay_auctions WHERE status IN ('sold','ended','expired')"
        ) or []
        records = _db_rows_to_list(rows)
        if not records:
            return 0
        count = _append_to_archive("towerbay", records)
        logger.info(f"📦 Archived {count} TowerBay auctions")
        return count
    except Exception as e:
        logger.warning(f"📦 _archive_towerbay DB error: {e}")
        return 0


def _archive_player_listings() -> int:
    """Archive closed player listings (sold/unsold) from DB."""
    try:
        count = _archive_query_in_batches("player_listings", "AND status IN ('sold','unsold','expired')")
        if count:
            logger.info("Archived %d player listings", count)
        return count
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT * FROM player_listings WHERE status IN ('sold','unsold','expired')"
        ) or []
        records = _db_rows_to_list(rows)
        if not records:
            return 0
        count = _append_to_archive("player_listings", records)
        logger.info(f"📦 Archived {count} player listings")
        return count
    except Exception as e:
        logger.warning(f"📦 _archive_player_listings DB error: {e}")
        return 0


def _archive_bounties() -> int:
    """Archive resolved/completed bounties from DB."""
    try:
        count = _archive_query_in_batches("bounties", "AND status IN ('completed','expired','cancelled')")
        if count:
            logger.info("Archived %d bounties", count)
        return count
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT * FROM bounties WHERE status IN ('completed','expired','cancelled')"
        ) or []
        records = _db_rows_to_list(rows)
        if not records:
            return 0
        count = _append_to_archive("bounties", records)
        logger.info(f"📦 Archived {count} bounties")
        return count
    except Exception as e:
        logger.warning(f"📦 _archive_bounties DB error: {e}")
        return 0


def _archive_missing_persons() -> int:
    """Archive resolved missing persons cases from DB."""
    try:
        count = _archive_query_in_batches("missing_persons", "AND status IN ('found','resolved','closed')")
        if count:
            logger.info("Archived %d missing persons cases", count)
        return count
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT * FROM missing_persons WHERE status IN ('found','resolved','closed')"
        ) or []
        records = _db_rows_to_list(rows)
        if not records:
            return 0
        count = _append_to_archive("missing_persons", records)
        logger.info(f"📦 Archived {count} missing persons cases")
        return count
    except Exception as e:
        logger.warning(f"📦 _archive_missing_persons DB error: {e}")
        return 0


def _archive_outcomes() -> int:
    """Archive mission outcome debriefs from DB."""
    try:
        count = _archive_named_query_in_batches("outcomes", "mission_outcomes")
        if count:
            logger.info("Archived %d mission outcomes", count)
        return count
        from src.db_api import raw_query
        rows = raw_query("SELECT * FROM mission_outcomes ORDER BY id") or []
        records = _db_rows_to_list(rows)
        if not records:
            return 0
        count = _append_to_archive("outcomes", records)
        logger.info(f"📦 Archived {count} mission outcomes")
        return count
    except Exception as e:
        logger.warning(f"📦 _archive_outcomes DB error: {e}")
        return 0


def _archive_graveyard() -> int:
    """Archive tower-absorbed NPCs from DB (status=dead, tower_absorbed=1)."""
    try:
        count = _archive_named_query_in_batches("graveyard", "npcs", "AND status = 'dead' AND tower_absorbed = 1")
        if count:
            logger.info("Archived %d tower-absorbed NPCs", count)
        return count
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT * FROM npcs WHERE status = 'dead' AND tower_absorbed = 1"
        ) or []
        absorbed = _db_rows_to_list(rows)
        if not absorbed:
            return 0
        count = _append_to_archive("graveyard", absorbed)
        logger.info(f"📦 Archived {count} tower-absorbed NPCs")
        return count
    except Exception as e:
        logger.warning(f"📦 _archive_graveyard DB error: {e}")
        return 0


def _snapshot_news() -> bool:
    """Take a weekly snapshot of news_memory from MySQL (falls back to txt file)."""
    content = ""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT bulletin_text, facts, created_at FROM news_memory ORDER BY id") or []
        parts = []
        for row in rows:
            ts = row.get("created_at", "")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            text = row.get("bulletin_text") or row.get("facts") or ""
            if text:
                parts.append(f"[{ts}]\n{text}")
        content = "\n\n---ENTRY---\n\n".join(parts)
    except Exception:
        pass
    if not content:
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
