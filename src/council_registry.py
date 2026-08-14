"""The Grand Council, in MySQL instead of Python literals and a JSON blob.

Two things lived outside the database and should not have:

1. The seats themselves were hardcoded dicts (`COUNCIL_MEMBERS`,
   `COUNCIL_PRESIDENT`) in `agents/guild_council.py`. A seat is a real thing in
   the world -- it is held by a real `npcs` row, it changes hands, and it should
   be queryable and editable from the dashboard. It also drifted: the president
   was "Guildmaster Mari Fen", a title she does not hold (she is rank Member and
   runs the Adventurers Guild front desk; the Guildmaster is Aldric Vane).

2. `global_state['council_rulings']` was a 64KB JSON list of 110 rulings, with
   `votes_yes` / `votes_no` as name arrays. Those are rows: a ruling is a record
   and a vote is a record, both of which get filtered, counted, and displayed on
   the dashboard. Exactly the case the JSON reflex check exists for.

Seats link to `npcs.id` so a seat-holder's motivation, secret, oracle_notes and
bonds reach the vote prompt through `_live_seat()` -- which is the whole reason
the council sounds like people instead of a form.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.db_api import raw_execute, raw_query
from src.log import logger

SEAT_PRESIDENT = "president"
SEAT_MEMBER = "member"

_SCHEMA_READY = False


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    try:
        raw_execute(
            """
            CREATE TABLE IF NOT EXISTS council_seats (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                seat_role   VARCHAR(16)  NOT NULL DEFAULT 'member',
                npc_id      INT          NULL,
                name        VARCHAR(120) NOT NULL,
                faction     VARCHAR(120) NOT NULL,
                title       VARCHAR(200) NOT NULL,
                agenda      VARCHAR(500) NOT NULL,
                bias        VARCHAR(700) NOT NULL,
                voice       VARCHAR(500) NOT NULL,
                sort_order  INT          NOT NULL DEFAULT 0,
                active      TINYINT(1)   NOT NULL DEFAULT 1,
                created_at  DATETIME     NOT NULL,
                updated_at  DATETIME     NOT NULL,
                UNIQUE KEY uniq_seat_name (name),
                KEY idx_role (seat_role, active),
                KEY idx_npc (npc_id)
            )
            """,
            (),
        )
        raw_execute(
            """
            CREATE TABLE IF NOT EXISTS council_rulings (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                ruled_at      DATETIME     NOT NULL,
                topic         VARCHAR(200) NOT NULL,
                proposal      TEXT         NOT NULL,
                passed        TINYINT(1)   NOT NULL DEFAULT 0,
                tiebreak      TINYINT(1)   NOT NULL DEFAULT 0,
                tiebreak_vote VARCHAR(8)   NULL,
                votes_yes     INT          NOT NULL DEFAULT 0,
                votes_no      INT          NOT NULL DEFAULT 0,
                session_date  DATE         NULL,
                created_at    DATETIME     NOT NULL,
                KEY idx_ruled (ruled_at),
                KEY idx_topic (topic),
                KEY idx_passed (passed)
            )
            """,
            (),
        )
        raw_execute(
            """
            CREATE TABLE IF NOT EXISTS council_ruling_votes (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                ruling_id  INT          NOT NULL,
                seat_name  VARCHAR(120) NOT NULL,
                vote       VARCHAR(8)   NOT NULL,
                position   TEXT         NULL,
                created_at DATETIME     NOT NULL,
                UNIQUE KEY uniq_vote (ruling_id, seat_name),
                KEY idx_ruling (ruling_id),
                KEY idx_seat (seat_name)
            )
            """,
            (),
        )
        _SCHEMA_READY = True
    except Exception as exc:
        logger.error(f"[council] schema init failed: {exc}")


# ---------------------------------------------------------------------------
# Seats
# ---------------------------------------------------------------------------

_SEAT_FIELDS = ("name", "faction", "title", "agenda", "bias", "voice")


def _row_to_seat(row: dict) -> dict:
    seat = {k: (row.get(k) or "") for k in _SEAT_FIELDS}
    seat["npc_id"] = row.get("npc_id")
    seat["seat_role"] = row.get("seat_role") or SEAT_MEMBER
    return seat


def get_members() -> list[dict]:
    """Voting seats, in table order. Empty list means the table is unseeded --
    callers keep their literal defaults as a fallback rather than convening an
    empty council."""
    ensure_schema()
    rows = raw_query(
        "SELECT * FROM council_seats WHERE seat_role=%s AND active=1 "
        "ORDER BY sort_order, id", (SEAT_MEMBER,)
    ) or []
    return [_row_to_seat(r) for r in rows]


def get_president() -> Optional[dict]:
    """The tiebreaker. None means unseeded."""
    ensure_schema()
    rows = raw_query(
        "SELECT * FROM council_seats WHERE seat_role=%s AND active=1 "
        "ORDER BY sort_order, id LIMIT 1", (SEAT_PRESIDENT,)
    ) or []
    return _row_to_seat(rows[0]) if rows else None


def upsert_seat(seat: dict, seat_role: str = SEAT_MEMBER, sort_order: int = 0,
                npc_id: Optional[int] = None) -> None:
    """Insert or update a seat by name. Resolves npc_id from `npcs` when not
    given, so the seat is tied to a real person rather than a string."""
    ensure_schema()
    now = datetime.now()
    name = str(seat.get("name") or "").strip()
    if not name:
        return

    if npc_id is None:
        npc_id = resolve_seat_npc_id(name)

    raw_execute(
        """
        INSERT INTO council_seats
            (seat_role, npc_id, name, faction, title, agenda, bias, voice,
             sort_order, active, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s)
        ON DUPLICATE KEY UPDATE
            seat_role=VALUES(seat_role), npc_id=VALUES(npc_id),
            faction=VALUES(faction), title=VALUES(title), agenda=VALUES(agenda),
            bias=VALUES(bias), voice=VALUES(voice),
            sort_order=VALUES(sort_order), active=1, updated_at=VALUES(updated_at)
        """,
        (seat_role, npc_id, name, seat.get("faction") or "", seat.get("title") or "",
         seat.get("agenda") or "", seat.get("bias") or "", seat.get("voice") or "",
         int(sort_order), now, now),
    )


def retire_seat(name: str) -> None:
    """Vacate a seat without deleting it -- who sat on the council and when is
    world history, not a config typo."""
    ensure_schema()
    raw_execute("UPDATE council_seats SET active=0, updated_at=%s WHERE name=%s",
                (datetime.now(), name))


def resolve_seat_npc_id(name: str) -> Optional[int]:
    """Match a seat label to a real `npcs` row.

    Seat names carry titles the roster does not ("Director Myra Kess" vs
    "Myra Kess"), so fall back to the last two name tokens before giving up.
    """
    if not name:
        return None
    rows = raw_query("SELECT id FROM npcs WHERE name=%s LIMIT 1", (name,)) or []
    if rows:
        return int(rows[0]["id"])
    parts = name.split()
    if len(parts) >= 2:
        bare = " ".join(parts[-2:])
        rows = raw_query("SELECT id FROM npcs WHERE name=%s LIMIT 1", (bare,)) or []
        if rows:
            return int(rows[0]["id"])
    if parts:
        rows = raw_query("SELECT id FROM npcs WHERE name LIKE %s LIMIT 2",
                         (f"%{parts[-1]}",)) or []
        if len(rows) == 1:
            return int(rows[0]["id"])
    return None


# ---------------------------------------------------------------------------
# Rulings
# ---------------------------------------------------------------------------

def record_ruling(topic: str, proposal: str, passed: bool, tiebreak: bool = False,
                  votes_yes: Optional[list] = None, votes_no: Optional[list] = None,
                  positions: Optional[dict] = None, tiebreak_vote: str = "",
                  ruled_at: Optional[datetime] = None) -> Optional[int]:
    """Persist one ruling and its individual votes. Returns the ruling id."""
    ensure_schema()
    votes_yes = list(votes_yes or [])
    votes_no = list(votes_no or [])
    now = datetime.now()
    when = ruled_at or now
    try:
        raw_execute(
            "INSERT INTO council_rulings (ruled_at, topic, proposal, passed, tiebreak, "
            "tiebreak_vote, votes_yes, votes_no, session_date, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (when, str(topic or "")[:200], str(proposal or ""), 1 if passed else 0,
             1 if tiebreak else 0, (tiebreak_vote or "")[:8],
             len(votes_yes), len(votes_no), when.date(), now),
        )
        rows = raw_query("SELECT LAST_INSERT_ID() AS id") or []
        ruling_id = int(rows[0]["id"]) if rows else None
    except Exception as exc:
        logger.error(f"[council] could not record ruling: {exc}")
        return None

    if not ruling_id:
        return None

    positions = positions or {}
    for seat_name, vote in ([(n, "yes") for n in votes_yes] + [(n, "no") for n in votes_no]):
        try:
            raw_execute(
                "INSERT INTO council_ruling_votes (ruling_id, seat_name, vote, position, created_at) "
                "VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE vote=VALUES(vote), "
                "position=VALUES(position)",
                (ruling_id, str(seat_name)[:120], vote,
                 str(positions.get(seat_name) or "")[:4000], now),
            )
        except Exception as exc:
            logger.debug(f"[council] vote row failed for {seat_name}: {exc}")
    return ruling_id


def recent_rulings(limit: int = 20) -> list[dict]:
    """Newest first. Shaped like the old JSON entries so existing readers and
    templates need no reshaping."""
    ensure_schema()
    rows = raw_query(
        "SELECT id, ruled_at, topic, proposal, passed, tiebreak, tiebreak_vote "
        "FROM council_rulings ORDER BY ruled_at DESC, id DESC LIMIT %s", (int(limit),)
    ) or []
    if not rows:
        return []

    ids = [int(r["id"]) for r in rows]
    votes: dict[int, dict[str, list]] = {i: {"yes": [], "no": []} for i in ids}
    try:
        placeholders = ",".join(["%s"] * len(ids))
        for v in raw_query(
            f"SELECT ruling_id, seat_name, vote FROM council_ruling_votes "
            f"WHERE ruling_id IN ({placeholders})", tuple(ids)
        ) or []:
            bucket = votes.get(int(v["ruling_id"]))
            if bucket is not None and v.get("vote") in bucket:
                bucket[v["vote"]].append(v.get("seat_name"))
    except Exception as exc:
        logger.debug(f"[council] vote fetch failed: {exc}")

    out = []
    for r in rows:
        rid = int(r["id"])
        out.append({
            "id": rid,
            "date": r["ruled_at"].isoformat() if r.get("ruled_at") else "",
            "topic": r.get("topic") or "",
            "proposal": r.get("proposal") or "",
            "passed": bool(r.get("passed")),
            "tiebreak": bool(r.get("tiebreak")),
            "tiebreak_vote": r.get("tiebreak_vote") or "",
            "votes_yes": votes[rid]["yes"],
            "votes_no": votes[rid]["no"],
        })
    return out


def ruling_count() -> int:
    ensure_schema()
    rows = raw_query("SELECT COUNT(*) c FROM council_rulings") or [{"c": 0}]
    return int(rows[0]["c"])
