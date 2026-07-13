"""loop_health.py — heartbeat registry for the bot's background loops.

The dashboard's /api/status answers "are the SERVICES alive?" (Ollama, A1111,
DB, Discord, Mimir). This module answers the question that has bitten this
project twice: "did the LOOPS actually run?" — the hourly news generator died
silently for 30+ hours behind green services, and the party lifecycle existed
for six weeks without ever being wired into a loop at all.

Each loop calls record_loop_heartbeat(name, ok, note) at the end of every
pass (aclient wraps this as self._beat(...)). get_loop_health() compares each
loop's last beat against its expected cadence and flags anything overdue.

Real MySQL table (CLAUDE.md JSON-reflex rule: these fields are filtered and
shown in the dashboard, so they get real columns). Survives restarts, which
also makes the first post-outage boot observable: watch each loop report in.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# loop name -> (human label, overdue threshold seconds).
# Thresholds are ~2.5x the loop's nominal cadence, padded for jitter, busy
# retries, and the weekday 4-9pm peak-power pause on the image loops.
EXPECTED: Dict[str, tuple] = {
    "discord_heartbeat":  ("Discord heartbeat",        10 * 60),
    "mission_board":      ("Mission board tick",       10 * 60),
    "personal_missions":  ("Personal mission tick",    10 * 60),
    "towerbot_world_shop":("TowerBot shop DM queue",   10 * 60),
    "character_monitor":  ("DDB character monitor",    30 * 60),
    "news_feed":          ("News bulletin cycle",       3 * 60 * 60),
    "ad_feed":            ("Ad / job postings",         2 * 60 * 60),
    "towerbot_item_art":  ("TowerBot item art",         2 * 60 * 60),
    "chat_reminder":      ("Chat reminder",            10 * 60 * 60),
    "story_images":       ("Story / city images",      22 * 60 * 60),
    "npc_portraits":      ("NPC portraits",            26 * 60 * 60),
    "npc_lifecycle":      ("NPC lifecycle",            44 * 60 * 60),
    "party_lifecycle":    ("Party lifecycle",          44 * 60 * 60),
    "log_cleanup":        ("Log cleanup",              50 * 60 * 60),
    "db_backup":          ("MySQL backup",             50 * 60 * 60),
}

_TABLE_READY = False


def _ensure_table() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    from src.db_api import raw_execute
    raw_execute("""
        CREATE TABLE IF NOT EXISTS loop_heartbeats (
            loop_name  VARCHAR(64) PRIMARY KEY,
            last_run   DATETIME NOT NULL,
            ok         TINYINT(1) NOT NULL DEFAULT 1,
            note       VARCHAR(255) NOT NULL DEFAULT '',
            run_count  INT NOT NULL DEFAULT 0,
            fail_count INT NOT NULL DEFAULT 0
        )
    """)
    _TABLE_READY = True


def record_loop_heartbeat(loop_name: str, ok: bool = True, note: str = "") -> None:
    """Stamp a completed loop pass. Never raises — a heartbeat failure must
    never take a loop down with it."""
    try:
        from src.db_api import raw_execute
        _ensure_table()
        raw_execute(
            """INSERT INTO loop_heartbeats (loop_name, last_run, ok, note, run_count, fail_count)
               VALUES (%s, UTC_TIMESTAMP(), %s, %s, 1, %s)
               ON DUPLICATE KEY UPDATE
                 last_run = UTC_TIMESTAMP(),
                 ok = VALUES(ok),
                 note = VALUES(note),
                 run_count = run_count + 1,
                 fail_count = fail_count + VALUES(fail_count)""",
            (loop_name, 1 if ok else 0, (note or "")[:255], 0 if ok else 1),
        )
    except Exception as e:
        logger.debug(f"loop heartbeat skipped ({loop_name}): {e}")


def get_loop_health() -> List[Dict[str, Any]]:
    """Verdict per known loop: ok / failing / overdue / never-ran.

    A loop is 'overdue' when its last beat is older than its threshold —
    including loops that have NEVER beaten (the party-lifecycle failure mode).
    """
    rows: Dict[str, dict] = {}
    try:
        from src.db_api import raw_query
        _ensure_table()
        for r in raw_query("SELECT * FROM loop_heartbeats") or []:
            rows[r["loop_name"]] = r
    except Exception as e:
        logger.warning(f"loop health read failed: {e}")

    now = datetime.utcnow()
    out: List[Dict[str, Any]] = []
    for name, (label, threshold) in EXPECTED.items():
        r = rows.get(name)
        if not r:
            out.append({"loop": name, "label": label, "status": "never-ran",
                        "age_seconds": None, "ok": False, "note": "no heartbeat recorded",
                        "runs": 0, "fails": 0})
            continue
        age = max(0, int((now - r["last_run"]).total_seconds()))
        if age > threshold:
            status = "overdue"
        elif not r.get("ok", 1):
            status = "failing"
        else:
            status = "ok"
        out.append({"loop": name, "label": label, "status": status,
                    "age_seconds": age, "ok": bool(r.get("ok", 1)),
                    "note": r.get("note") or "",
                    "runs": int(r.get("run_count") or 0),
                    "fails": int(r.get("fail_count") or 0)})
    # unknown-but-beating loops still show up (future loops without registry entries)
    for name, r in rows.items():
        if name not in EXPECTED:
            age = max(0, int((now - r["last_run"]).total_seconds()))
            out.append({"loop": name, "label": name, "status": "ok" if r.get("ok", 1) else "failing",
                        "age_seconds": age, "ok": bool(r.get("ok", 1)),
                        "note": r.get("note") or "",
                        "runs": int(r.get("run_count") or 0),
                        "fails": int(r.get("fail_count") or 0)})
    # worst problems first, then by name for stable ordering
    rank = {"never-ran": 0, "overdue": 1, "failing": 2, "ok": 3}
    out.sort(key=lambda d: (rank.get(d["status"], 9), d["loop"]))
    return out
