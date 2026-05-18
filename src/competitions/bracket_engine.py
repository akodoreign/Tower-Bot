"""
bracket_engine.py — Competition bracket state machine.

Manages the full lifecycle of a competition:
  - Creating brackets and seeding contestants
  - Auto-resolving NPC vs NPC rounds
  - Tracking PC advancement through rounds
  - Generating result data for mission_builder and post_competition

DB tables (auto-created on first import):
  competitions          — one row per competition instance
  competition_entries   — one row per contestant per competition

PC rounds are flagged is_pc_round=True. The post layer generates a
mission for those. NPC rounds auto-resolve here and return a result dict
for a bulletin post.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.db_api import raw_query, raw_execute, db
from .competition_types import CompetitionType, get_competition_type

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

_SCHEMA_COMPETITIONS = """
CREATE TABLE IF NOT EXISTS competitions (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    slug            VARCHAR(64) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    sponsor         VARCHAR(128) NOT NULL,
    status          ENUM('upcoming','active','complete') DEFAULT 'upcoming',
    current_round   INT DEFAULT 0,
    bracket_json    MEDIUMTEXT,
    started_at      DATETIME,
    completed_at    DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

_SCHEMA_ENTRIES = """
CREATE TABLE IF NOT EXISTS competition_entries (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    comp_id         INT NOT NULL,
    name            VARCHAR(128) NOT NULL,
    entry_type      ENUM('pc','npc') NOT NULL,
    faction         VARCHAR(128) DEFAULT '',
    seed            INT DEFAULT 0,
    status          ENUM('active','eliminated','champion') DEFAULT 'active',
    round_reached   INT DEFAULT 0,
    wins            INT DEFAULT 0,
    losses          INT DEFAULT 0,
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_comp (comp_id),
    INDEX idx_status (status)
)
"""


def _ensure_tables() -> None:
    try:
        raw_execute(_SCHEMA_COMPETITIONS)
        raw_execute(_SCHEMA_ENTRIES)
    except Exception as e:
        logger.warning(f"[bracket] Table creation warning: {e}")


# ---------------------------------------------------------------------------
# NPC competitor pool
# ---------------------------------------------------------------------------

def _pull_npc_competitors(
    comp_type: CompetitionType,
    count: int,
    exclude_names: Optional[List[str]] = None,
) -> List[Dict]:
    """Pull NPC contestants from the DB based on the competition's faction list."""
    exclude = set(exclude_names or [])
    placeholders = ",".join(["%s"] * len(comp_type.npc_factions))
    try:
        rows = raw_query(
            f"SELECT name, faction, role FROM npcs "
            f"WHERE faction IN ({placeholders}) "
            f"AND status NOT IN ('dead','removed','missing') "
            f"ORDER BY RAND() LIMIT %s",
            tuple(comp_type.npc_factions) + (count * 3,),
        ) or []
    except Exception as e:
        logger.warning(f"[bracket] NPC pool query failed: {e}")
        rows = []

    seen: set = set()
    result = []
    for r in rows:
        if r["name"] in exclude or r["name"] in seen:
            continue
        seen.add(r["name"])
        result.append({
            "name":       r["name"],
            "faction":    r.get("faction", "Independent"),
            "role":       (r.get("role") or "")[:80],
            "entry_type": "npc",
        })
        if len(result) >= count:
            break

    # Pad with generic names if DB doesn't have enough
    fallbacks = [
        "Davan Corst", "Ilse Wren", "Pell the Twice-Broken", "Nadara Quick",
        "Gorvan Fitch", "Elss Moorward", "Triset", "Burg Nallo",
    ]
    for name in fallbacks:
        if len(result) >= count:
            break
        if name not in seen and name not in exclude:
            result.append({"name": name, "faction": "Independent", "role": "", "entry_type": "npc"})

    return result[:count]


# ---------------------------------------------------------------------------
# Bracket creation
# ---------------------------------------------------------------------------

def create_competition(
    comp_type: CompetitionType,
    pc_names: Optional[List[str]] = None,
    pc_factions: Optional[Dict[str, str]] = None,
    round_interval_hours: int = 48,
) -> int:
    """
    Create a new competition, seed the bracket, and return the DB id.

    pc_names: list of PC character names entering the competition.
    pc_factions: {name: faction_name} for PC entries (optional).
    round_interval_hours: real-world hours between rounds.
    """
    _ensure_tables()

    pc_names    = pc_names or []
    pc_factions = pc_factions or {}
    max_slots   = comp_type.contestants_max
    pc_slots    = min(len(pc_names), max_slots)
    npc_slots   = max_slots - pc_slots

    entries: List[Dict] = []
    for name in pc_names[:pc_slots]:
        entries.append({
            "name":       name,
            "entry_type": "pc",
            "faction":    pc_factions.get(name, "Adventurers Guild"),
        })

    npcs = _pull_npc_competitors(comp_type, npc_slots, exclude_names=pc_names)
    entries.extend(npcs)

    random.shuffle(entries)
    for i, e in enumerate(entries):
        e["seed"] = i + 1

    sponsor = comp_type.sponsors[0]
    now = datetime.now()
    bracket = _build_bracket(entries, round_interval_hours, now)

    comp_id = db.insert("competitions", {
        "slug":         comp_type.slug,
        "name":         f"{comp_type.name} — {now.strftime('%b %Y')}",
        "sponsor":      sponsor,
        "status":       "upcoming",
        "current_round": 0,
        "bracket_json": json.dumps(bracket, default=str),
        "started_at":   now,
    })

    for e in entries:
        db.insert("competition_entries", {
            "comp_id":    comp_id,
            "name":       e["name"],
            "entry_type": e["entry_type"],
            "faction":    e.get("faction", "Independent"),
            "seed":       e["seed"],
            "status":     "active",
        })

    logger.info(
        f"[bracket] Created '{comp_type.name}' comp_id={comp_id} "
        f"with {len(entries)} contestants ({pc_slots} PC, {npc_slots} NPC)"
    )
    return comp_id


def _build_bracket(
    entries: List[Dict],
    interval_hours: int,
    start: datetime,
) -> Dict:
    """Build the initial bracket structure — pairs for Round 1."""
    n = len(entries)
    pairs = []
    scheduled = start + timedelta(hours=interval_hours)
    for i in range(0, n - 1, 2):
        pairs.append({
            "a":          entries[i]["name"],
            "a_type":     entries[i]["entry_type"],
            "b":          entries[i + 1]["name"],
            "b_type":     entries[i + 1]["entry_type"],
            "round":      1,
            "scheduled":  scheduled.isoformat(),
            "status":     "pending",   # pending | mission_posted | complete
            "winner":     None,
            "mission_id": None,
        })
    return {
        "round":   1,
        "matches": pairs,
        "history": [],
    }


# ---------------------------------------------------------------------------
# Bracket state helpers
# ---------------------------------------------------------------------------

def _load_competition(comp_id: int) -> Optional[Dict]:
    rows = raw_query("SELECT * FROM competitions WHERE id = %s", (comp_id,))
    if not rows:
        return None
    row = dict(rows[0])
    if row.get("bracket_json"):
        row["bracket"] = json.loads(row["bracket_json"])
    else:
        row["bracket"] = {"round": 1, "matches": [], "history": []}
    return row


def _save_bracket(comp_id: int, bracket: Dict) -> None:
    raw_execute(
        "UPDATE competitions SET bracket_json = %s WHERE id = %s",
        (json.dumps(bracket, default=str), comp_id),
    )


def get_active_competitions() -> List[Dict]:
    """Return all competitions that are upcoming or active."""
    rows = raw_query(
        "SELECT * FROM competitions WHERE status IN ('upcoming','active') ORDER BY started_at ASC"
    ) or []
    result = []
    for row in rows:
        r = dict(row)
        if r.get("bracket_json"):
            r["bracket"] = json.loads(r["bracket_json"])
        else:
            r["bracket"] = {}
        result.append(r)
    return result


def get_pending_rounds(comp_id: int) -> List[Dict]:
    """Return matches in the current round that are still pending and due."""
    comp = _load_competition(comp_id)
    if not comp:
        return []
    now = datetime.now()
    pending = []
    for match in comp["bracket"].get("matches", []):
        if match["status"] != "pending":
            continue
        try:
            sched = datetime.fromisoformat(match["scheduled"])
        except Exception:
            continue
        if now >= sched:
            pending.append(match)
    return pending


def is_pc_round(match: Dict) -> bool:
    return match.get("a_type") == "pc" or match.get("b_type") == "pc"


# ---------------------------------------------------------------------------
# Auto-resolve NPC vs NPC
# ---------------------------------------------------------------------------

def auto_resolve_npc_match(comp_id: int, match: Dict) -> Dict:
    """
    Simulate an NPC vs NPC match. Returns result dict with winner/loser/narrative.
    Updates bracket state in DB.
    """
    a, b = match["a"], match["b"]
    winner, loser = (a, b) if random.random() < 0.5 else (b, a)

    _record_match_result(comp_id, match, winner)

    return {
        "comp_id":  comp_id,
        "round":    match["round"],
        "winner":   winner,
        "loser":    loser,
        "is_pc":    False,
        "auto":     True,
    }


def _record_match_result(comp_id: int, match: Dict, winner: str) -> None:
    """Update bracket JSON and entry records after a match resolves."""
    comp = _load_competition(comp_id)
    if not comp:
        return
    bracket = comp["bracket"]
    loser = match["b"] if winner == match["a"] else match["a"]

    for m in bracket["matches"]:
        if m["a"] == match["a"] and m["b"] == match["b"] and m["round"] == match["round"]:
            m["status"] = "complete"
            m["winner"] = winner
            bracket["history"].append(dict(m))

    # Update entry records
    raw_execute(
        "UPDATE competition_entries SET wins = wins + 1, round_reached = %s WHERE comp_id = %s AND name = %s",
        (match["round"], comp_id, winner),
    )
    raw_execute(
        "UPDATE competition_entries SET losses = losses + 1, status = 'eliminated', round_reached = %s "
        "WHERE comp_id = %s AND name = %s",
        (match["round"], comp_id, loser),
    )

    # Advance only when every match in the current round is complete.
    # PC-involved matches sit at mission_posted while the party is playing them;
    # those must block advancement just like pending matches do.
    incomplete = [m for m in bracket["matches"] if m.get("status") != "complete"]
    if not incomplete:
        _advance_to_next_round(comp_id, bracket)

    _save_bracket(comp_id, bracket)


def _advance_to_next_round(comp_id: int, bracket: Dict) -> None:
    """Build the next round's matches from winners of the current round."""
    winners = [m["winner"] for m in bracket["matches"] if m["status"] == "complete" and m["winner"]]
    if len(winners) < 2:
        # Competition over
        champion = winners[0] if winners else "Unknown"
        raw_execute(
            "UPDATE competitions SET status = 'complete', completed_at = %s WHERE id = %s",
            (datetime.now(), comp_id),
        )
        raw_execute(
            "UPDATE competition_entries SET status = 'champion' WHERE comp_id = %s AND name = %s",
            (comp_id, champion),
        )
        logger.info(f"[bracket] comp_id={comp_id} complete — champion: {champion}")
        return

    next_round = bracket["round"] + 1
    interval   = 48  # default hours between rounds
    scheduled  = datetime.now() + timedelta(hours=interval)

    new_matches = []
    random.shuffle(winners)
    for i in range(0, len(winners) - 1, 2):
        # Look up entry types
        a_type = _get_entry_type(comp_id, winners[i])
        b_type = _get_entry_type(comp_id, winners[i + 1])
        new_matches.append({
            "a":         winners[i],
            "a_type":    a_type,
            "b":         winners[i + 1],
            "b_type":    b_type,
            "round":     next_round,
            "scheduled": scheduled.isoformat(),
            "status":    "pending",
            "winner":    None,
            "mission_id": None,
        })

    bracket["matches"]      = new_matches
    bracket["round"]        = next_round
    bracket["history_round"] = bracket.get("history_round", []) + [next_round - 1]

    raw_execute(
        "UPDATE competitions SET current_round = %s, status = 'active' WHERE id = %s",
        (next_round, comp_id),
    )
    logger.info(f"[bracket] comp_id={comp_id} advanced to round {next_round} with {len(new_matches)} matches")


def _get_entry_type(comp_id: int, name: str) -> str:
    rows = raw_query(
        "SELECT entry_type FROM competition_entries WHERE comp_id = %s AND name = %s LIMIT 1",
        (comp_id, name),
    )
    return (rows[0]["entry_type"] if rows else "npc")


# ---------------------------------------------------------------------------
# Record a PC round result (called by DM after mission completion)
# ---------------------------------------------------------------------------

def record_pc_result(comp_id: int, match: Dict, winner: str) -> Dict:
    """Record a PC-involved match result. Returns advancement info."""
    _record_match_result(comp_id, match, winner)
    loser = match["b"] if winner == match["a"] else match["a"]

    comp = _load_competition(comp_id)
    next_match = None
    if comp:
        for m in comp["bracket"].get("matches", []):
            if m["a"] == winner or m["b"] == winner:
                next_match = m
                break

    return {
        "comp_id":    comp_id,
        "round":      match["round"],
        "winner":     winner,
        "loser":      loser,
        "next_match": next_match,
        "is_final":   next_match is None,
    }


# ---------------------------------------------------------------------------
# Standings query for web / Discord
# ---------------------------------------------------------------------------

def get_standings(comp_id: int) -> List[Dict]:
    """Return current standings sorted by wins desc, round_reached desc."""
    rows = raw_query(
        "SELECT name, entry_type, faction, seed, status, round_reached, wins, losses "
        "FROM competition_entries WHERE comp_id = %s "
        "ORDER BY wins DESC, round_reached DESC, losses ASC",
        (comp_id,),
    ) or []
    return [dict(r) for r in rows]
