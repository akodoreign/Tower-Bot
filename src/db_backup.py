"""
db_backup.py — Daily MySQL backup to D:\\DBBackup

Runs once every 24 hours inside the bot's async loop.
Uses mysqldump via subprocess — requires mysqldump on PATH
(ships with MySQL Server / MySQL Workbench).

Backup file format:  tower_bot_YYYY-MM-DD_HHMMSS.sql.gz
Retention policy:    keeps the 14 most recent backups, deletes the rest.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from src.log import logger

BACKUP_DIR = Path(r"D:\DBBackup")
RETENTION_COUNT = 14       # keep 2 weeks of daily backups
BACKUP_INTERVAL = 24 * 3600  # 24 hours in seconds


def _get_db_config() -> dict:
    return {
        "host":     os.getenv("MYSQL_HOST",     "localhost"),
        "port":     os.getenv("MYSQL_PORT",     "3306"),
        "user":     os.getenv("MYSQL_USER",     "Claude"),
        "password": os.getenv("MYSQL_PASSWORD", "WXdCPJmeDfaQALaktzF6!"),
        "database": os.getenv("MYSQL_DB",       "tower_bot"),
    }


def run_backup() -> Path:
    """
    Dump the tower_bot database to a gzipped .sql file in BACKUP_DIR.

    Returns the path of the created backup file.
    Raises RuntimeError on failure.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    cfg = _get_db_config()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{cfg['database']}_{timestamp}.sql.gz"
    dest = BACKUP_DIR / filename

    # Locate mysqldump — tries PATH first, then scans all MySQL Server versions
    mysqldump = shutil.which("mysqldump")
    if not mysqldump:
        mysql_root = Path(r"C:\Program Files\MySQL")
        if mysql_root.exists():
            # Pick the highest-version Server directory present
            for server_dir in sorted(mysql_root.iterdir(), reverse=True):
                candidate = server_dir / "bin" / "mysqldump.exe"
                if candidate.exists():
                    mysqldump = str(candidate)
                    break
        # x86 fallback
        if not mysqldump:
            mysql_root_x86 = Path(r"C:\Program Files (x86)\MySQL")
            if mysql_root_x86.exists():
                for server_dir in sorted(mysql_root_x86.iterdir(), reverse=True):
                    candidate = server_dir / "bin" / "mysqldump.exe"
                    if candidate.exists():
                        mysqldump = str(candidate)
                        break

    if not mysqldump:
        raise RuntimeError(
            "mysqldump not found. Set MYSQLDUMP_PATH env var to the full path, "
            "or add your MySQL\\bin directory to PATH."
        )

    # Allow override via env
    mysqldump = os.getenv("MYSQLDUMP_PATH", mysqldump)

    cmd = [
        mysqldump,
        f"--host={cfg['host']}",
        f"--port={cfg['port']}",
        f"--user={cfg['user']}",
        f"--password={cfg['password']}",
        "--single-transaction",   # consistent snapshot without locking
        "--routines",             # include stored procedures / functions
        "--triggers",             # include triggers
        "--set-gtid-purged=OFF",  # avoids GTID errors on restore
        cfg["database"],
    ]

    logger.info(f"💾 Starting DB backup → {dest.name}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=False,   # raw bytes — we gzip it ourselves
    )

    # mysqldump writes the dump to stdout; stderr has progress/warnings
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"mysqldump exited {result.returncode}: {stderr[:500]}")

    if not result.stdout:
        raise RuntimeError("mysqldump produced empty output — backup aborted")

    # Gzip and write
    with gzip.open(dest, "wb") as f:
        f.write(result.stdout)

    size_kb = dest.stat().st_size // 1024
    logger.info(f"✅ DB backup complete: {dest.name} ({size_kb:,} KB)")

    # Enforce retention — delete oldest beyond RETENTION_COUNT
    _prune_old_backups()

    return dest


def _prune_old_backups() -> None:
    """Delete oldest backups beyond RETENTION_COUNT."""
    backups = sorted(BACKUP_DIR.glob(f"*.sql.gz"), key=lambda p: p.stat().st_mtime)
    excess = backups[:-RETENTION_COUNT] if len(backups) > RETENTION_COUNT else []
    for old in excess:
        try:
            old.unlink()
            logger.info(f"🗑️ Pruned old backup: {old.name}")
        except Exception as e:
            logger.warning(f"🗑️ Could not delete old backup {old.name}: {e}")


async def db_backup_loop() -> None:
    """
    Async loop — runs run_backup() once per day.
    Fires at bot startup (after a short delay) then every 24 hours.
    """
    # Wait 2 minutes after startup before the first backup
    # so the bot is fully ready and DB connections are warm.
    await asyncio.sleep(120)

    while True:
        try:
            # Run the blocking dump in a thread so it doesn't stall the event loop
            loop = asyncio.get_event_loop()
            backup_path = await loop.run_in_executor(None, run_backup)
            logger.info(f"💾 Backup loop: next run in 24 hours (last: {backup_path.name})")
        except Exception as e:
            logger.error(f"💾 DB backup failed: {e}")

        await asyncio.sleep(BACKUP_INTERVAL)
