"""
migrate_npcs_columns.py — Promote data_json scalar fields to real npcs columns.

Adds: rank, motivation, quote, oracle_notes, secret, relationships
Backfills from data_json for all existing rows.
Safe to re-run (idempotent ALTER TABLE, UPDATE skips rows already set).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from src.db_api import raw_execute, raw_query

NEW_COLUMNS = [
    ("rank",          "VARCHAR(150) DEFAULT NULL"),
    ("motivation",    "TEXT DEFAULT NULL"),
    ("quote",         "TEXT DEFAULT NULL"),
    ("oracle_notes",  "TEXT DEFAULT NULL"),
    ("secret",        "TEXT DEFAULT NULL"),
    ("relationships", "TEXT DEFAULT NULL"),
]


def _add_columns():
    existing = {r["Field"] for r in raw_query("SHOW COLUMNS FROM npcs")}
    for col, defn in NEW_COLUMNS:
        if col in existing:
            print(f"  SKIP  column {col!r} already exists")
        else:
            raw_execute(f"ALTER TABLE npcs ADD COLUMN `{col}` {defn}")
            print(f"  ADD   column {col!r}")


def _backfill():
    rows = raw_query("SELECT id, data_json FROM npcs")
    updated = 0
    for row in rows:
        dj = row.get("data_json") or {}
        if isinstance(dj, str):
            try:
                dj = json.loads(dj)
            except Exception:
                dj = {}
        if not isinstance(dj, dict):
            continue

        fields = {col: dj.get(col) or None for col, _ in NEW_COLUMNS}
        # Only update if at least one field has a value to write
        if not any(v for v in fields.values()):
            continue

        raw_execute(
            """UPDATE npcs SET
               `rank`         = COALESCE(`rank`, %s),
               motivation     = COALESCE(motivation, %s),
               quote          = COALESCE(quote, %s),
               oracle_notes   = COALESCE(oracle_notes, %s),
               secret         = COALESCE(secret, %s),
               relationships  = COALESCE(relationships, %s)
               WHERE id = %s""",
            (
                fields["rank"],
                fields["motivation"],
                fields["quote"],
                fields["oracle_notes"],
                fields["secret"],
                fields["relationships"],
                row["id"],
            ),
        )
        updated += 1

    print(f"  Backfilled {updated} / {len(rows)} rows from data_json")


def _verify():
    counts = raw_query(
        "SELECT "
        "COUNT(`rank`) as has_rank, "
        "COUNT(motivation) as has_motivation, "
        "COUNT(quote) as has_quote, "
        "COUNT(oracle_notes) as has_oracle, "
        "COUNT(secret) as has_secret, "
        "COUNT(relationships) as has_relationships, "
        "COUNT(*) as total "
        "FROM npcs"
    )[0]
    total = counts["total"]
    for field, count in counts.items():
        if field != "total":
            print(f"  {field:20s}: {count}/{total} rows populated")


if __name__ == "__main__":
    print("=== Step 1: Add columns ===")
    _add_columns()
    print("\n=== Step 2: Backfill from data_json ===")
    _backfill()
    print("\n=== Step 3: Verify ===")
    _verify()
    print("\nDone.")
