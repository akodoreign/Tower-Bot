"""
mission_outcomes.py — Persistent world memory from completed missions.

When the DM completes/fails a mission via the debrief questionnaire, answers
are saved as readable archive files and consequences are processed (NPC deaths,
faction enmity, etc.).

Archives are NOT injected into AI prompts — they're reference files the DM or
AI can look up when needed. This keeps prompts lean.

Storage:
  campaign_docs/mission_outcomes.json          — structured data (all outcomes)
  campaign_docs/archives/missions/             — one .md file per mission outcome
  campaign_docs/archives/news/                 — weekly news feed archives
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.db_api import raw_query as _rq, raw_execute as _rx

logger = logging.getLogger(__name__)

DOCS_DIR        = Path(__file__).resolve().parent.parent / "campaign_docs"
ARCHIVES_DIR    = DOCS_DIR / "archives"
MISSION_ARCHIVE = ARCHIVES_DIR / "missions"
NEWS_ARCHIVE    = ARCHIVES_DIR / "news"


# ---------------------------------------------------------------------------
# Persistence — MySQL (primary) with JSON file fallback
# ---------------------------------------------------------------------------

def _load_outcomes() -> List[Dict]:
    try:
        rows = _rq("SELECT * FROM mission_outcomes ORDER BY id") or []
        results = []
        for row in rows:
            o = dict(row)
            cj = o.pop("consequences_json", None)
            if cj:
                try:
                    o["consequences"] = json.loads(cj) if isinstance(cj, str) else cj
                except Exception:
                    o["consequences"] = []
            else:
                o["consequences"] = []
            results.append(o)
        if results:
            return results
    except Exception as e:
        logger.exception(f"mission_outcomes DB load error: {e}")
    return []


def _save_outcomes(outcomes: List[Dict]) -> None:
    """Write new outcome entries to MySQL (DB is authoritative)."""
    try:
        existing_ids = {r["id"] for r in (_rq("SELECT id FROM mission_outcomes") or [])}
        for o in outcomes:
            oid = o.get("id")
            if oid and oid in existing_ids:
                continue
            _rx(
                """INSERT INTO mission_outcomes
                   (mission_title, faction, opposing_faction, tier, completed_by,
                    completed_at, result, npcs_killed, key_decisions, location_changes,
                    loose_threads, notable_moments, consequences_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (o.get("mission_title"), o.get("faction"), o.get("opposing_faction",""),
                 o.get("tier"), o.get("completed_by"), o.get("completed_at"),
                 o.get("result"), o.get("npcs_killed"), o.get("key_decisions"),
                 o.get("location_changes"), o.get("loose_threads"), o.get("notable_moments"),
                 json.dumps(o.get("consequences", []), ensure_ascii=False))
            )
    except Exception as e:
        logger.exception(f"mission_outcomes DB save error: {e}")


def get_recent_outcomes(n: int = 10) -> List[Dict]:
    """Return the N most recent outcomes for code-level queries."""
    try:
        rows = _rq("SELECT * FROM mission_outcomes ORDER BY id DESC LIMIT %s", (n,)) or []
        results = []
        for row in rows:
            o = dict(row)
            cj = o.pop("consequences_json", None)
            try:
                o["consequences"] = (json.loads(cj) if isinstance(cj, str) else cj) or []
            except Exception:
                o["consequences"] = []
            results.append(o)
        return list(reversed(results))
    except Exception:
        return _load_outcomes()[-n:]


# ---------------------------------------------------------------------------
# Save outcome — JSON + readable .md archive file
# ---------------------------------------------------------------------------

def save_outcome(outcome: Dict) -> None:
    """Save a mission outcome to MySQL (DB is authoritative)."""
    try:
        _rx(
            """INSERT INTO mission_outcomes
               (mission_title, faction, opposing_faction, tier, completed_by,
                completed_at, result, npcs_killed, key_decisions, location_changes,
                loose_threads, notable_moments, consequences_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (outcome.get("mission_title"), outcome.get("faction"), outcome.get("opposing_faction",""),
             outcome.get("tier"), outcome.get("completed_by"), outcome.get("completed_at"),
             outcome.get("result"), outcome.get("npcs_killed"), outcome.get("key_decisions"),
             outcome.get("location_changes"), outcome.get("loose_threads"), outcome.get("notable_moments"),
             json.dumps(outcome.get("consequences", []), ensure_ascii=False))
        )
    except Exception as e:
        logger.error(f"save_outcome DB error: {e}")

    # Write readable .md archive file
    MISSION_ARCHIVE.mkdir(parents=True, exist_ok=True)
    title   = outcome.get("mission_title", "Unknown")
    safe    = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip().replace(" ", "_")
    date    = outcome.get("completed_at", datetime.now().strftime("%Y-%m-%d"))
    result  = outcome.get("result", "completed").upper()
    fname   = f"{date}_{result}_{safe}.md"

    opposing = outcome.get('opposing_faction', '')
    lines = [
        f"# Mission Outcome: {title}",
        f"",
        f"**Date:** {date}",
        f"**Result:** {result}",
        f"**Faction:** {outcome.get('faction', '?')}",
        f"**Opposing Faction:** {opposing if opposing else 'None'}",
        f"**Tier:** {outcome.get('tier', '?')}",
        f"**Completed by:** {outcome.get('completed_by', '?')}",
        f"",
        f"---",
        f"",
    ]

    if outcome.get("npcs_killed"):
        lines.append(f"## NPCs Killed / Removed")
        lines.append(f"{outcome['npcs_killed']}")
        lines.append(f"")

    if outcome.get("key_decisions"):
        lines.append(f"## Key Decisions")
        lines.append(f"{outcome['key_decisions']}")
        lines.append(f"")

    if outcome.get("location_changes"):
        lines.append(f"## Location Changes")
        lines.append(f"{outcome['location_changes']}")
        lines.append(f"")

    if outcome.get("loose_threads"):
        lines.append(f"## Loose Threads")
        lines.append(f"{outcome['loose_threads']}")
        lines.append(f"")

    if outcome.get("notable_moments"):
        lines.append(f"## Notable Moments")
        lines.append(f"{outcome['notable_moments']}")
        lines.append(f"")

    if outcome.get("consequences"):
        lines.append(f"## Consequences Applied")
        for c in outcome["consequences"]:
            lines.append(f"- {c}")
        lines.append(f"")

    try:
        (MISSION_ARCHIVE / fname).write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"📋 Mission archive saved: archives/missions/{fname}")
    except Exception as e:
        logger.warning(f"📋 Could not write mission archive: {e}")


# ---------------------------------------------------------------------------
# Weekly news archive — call from a scheduled task or manually
# ---------------------------------------------------------------------------

def archive_news_weekly() -> Optional[str]:
    """Archive news_memory rows older than 7 days to a dated txt file, then delete them.
    Returns the archive filename, or None if nothing to archive."""
    NEWS_ARCHIVE.mkdir(parents=True, exist_ok=True)
    now = datetime.now()

    try:
        from src.db_api import raw_query as _rq, raw_execute as _rx
        # Fetch all rows older than 7 days
        rows = _rq(
            "SELECT id, bulletin_text, facts, news_type, created_at FROM news_memory "
            "WHERE created_at < DATE_SUB(NOW(), INTERVAL 7 DAY) ORDER BY id"
        ) or []
        if not rows:
            logger.info("📰 News archive: no entries older than 7 days — nothing to archive")
            return None

        # Build archive text
        lines = [f"# News Archive — Week of {now.strftime('%Y-%m-%d')}\n"]
        for row in rows:
            ts = row.get("created_at", "")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            text = row.get("bulletin_text") or row.get("facts") or ""
            lines.append(f"[{ts}]\n{text}\n---ENTRY---")

        content = "\n".join(lines)
        fname = f"news_week_{now.strftime('%Y-%m-%d')}.txt"
        archive_path = NEWS_ARCHIVE / fname

        if archive_path.exists():
            existing = archive_path.read_text(encoding="utf-8", errors="ignore")
            archive_path.write_text(existing + "\n\n--- CONTINUED ---\n\n" + content, encoding="utf-8")
        else:
            archive_path.write_text(content, encoding="utf-8")

        # Delete archived rows from DB
        ids = [r["id"] for r in rows]
        id_placeholders = ",".join(["%s"] * len(ids))
        _rx(f"DELETE FROM news_memory WHERE id IN ({id_placeholders})", tuple(ids))

        logger.info(f"📰 News archived to {fname} — {len(rows)} entries removed from DB")
        return fname
    except Exception as e:
        logger.error(f"📰 News archive failed: {e}")
        return None


def archive_outcomes_weekly() -> Optional[str]:
    """Archive older mission outcomes (keep last 10 in DB)."""
    outcomes = _load_outcomes()
    if len(outcomes) <= 10:
        return None  # nothing to archive

    kept = outcomes[-10:]
    kept_ids = {o.get("id") for o in kept if o.get("id")}
    to_delete = [o["id"] for o in outcomes if o.get("id") and o["id"] not in kept_ids]
    archived_count = len(to_delete)
    if to_delete:
        try:
            placeholders = ",".join(["%s"] * len(to_delete))
            _rx(f"DELETE FROM mission_outcomes WHERE id IN ({placeholders})", tuple(to_delete))
        except Exception as e:
            logger.error(f"📋 Outcome trim failed: {e}")
            return None
    logger.info(f"📋 Trimmed mission_outcomes: archived {archived_count}, kept {len(kept)}")
    return f"trimmed_{archived_count}_outcomes"


# ---------------------------------------------------------------------------
# Consequence processing — NPC deaths, faction enmity, etc.
# ---------------------------------------------------------------------------

def _load_npcs() -> List[Dict]:
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT name, faction, role, location, status, data_json FROM npcs WHERE status IN ('alive','injured','undead','doppelganger') ORDER BY name") or []
        npcs = []
        for row in rows:
            dj = row.get("data_json") or {}
            if isinstance(dj, str):
                try: dj = json.loads(dj)
                except: dj = {}
            # DB columns win over stale data_json values
            npc = {**dj,
                   "name": row["name"], "faction": row["faction"], "role": row["role"],
                   "location": row["location"], "status": row["status"]}
            if "history" not in npc:
                npc["history"] = []
            npcs.append(npc)
        return npcs
    except Exception as e:
        logger.warning(f"_load_npcs DB error: {e}")
    return []


def _save_npcs(npcs: List[Dict]) -> None:
    """Delegate NPC saves to npc_lifecycle which owns that table."""
    try:
        from src.npc_lifecycle import _save_npc, _rebuild_txt
        for npc in npcs:
            _save_npc(npc)
        _rebuild_txt(npcs)
    except Exception as e:
        logger.error(f"_save_npcs error: {e}")


def _load_graveyard() -> List[Dict]:
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT name, faction, role, status, data_json FROM npcs WHERE status='dead' ORDER BY name") or []
        npcs = []
        for row in rows:
            npc = {"name": row["name"], "faction": row["faction"], "role": row["role"], "status": "dead"}
            dj = row.get("data_json") or {}
            if isinstance(dj, str):
                try: dj = json.loads(dj)
                except: dj = {}
            npc.update(dj)
            if "history" not in npc:
                npc["history"] = []
            npcs.append(npc)
        return npcs
    except Exception as e:
        logger.warning(f"_load_graveyard DB error: {e}")
    return []


def _save_graveyard(graveyard: List[Dict]) -> None:
    """Graveyard is now just npcs with status='dead' — delegate to npc_lifecycle."""
    try:
        from src.npc_lifecycle import _save_npc
        for npc in graveyard:
            npc["status"] = "dead"
            _save_npc(npc)
    except Exception as e:
        logger.error(f"_save_graveyard error: {e}")


def _fuzzy_find_npc(name: str, npcs: List[Dict]) -> Optional[Dict]:
    """Find an NPC by fuzzy name match (case-insensitive, partial)."""
    name_lower = name.strip().lower()
    # Exact match first
    for n in npcs:
        if n.get("name", "").lower() == name_lower:
            return n
    # Partial match
    for n in npcs:
        npc_name = n.get("name", "").lower()
        if name_lower in npc_name or npc_name in name_lower:
            return n
    return None


def process_npc_deaths(killed_text: str, mission_title: str) -> List[str]:
    """Parse the 'NPCs killed' answer and move matching NPCs to the graveyard.
    Returns list of consequence descriptions."""
    if not killed_text or killed_text.strip().lower() in ("none", "no", "n/a", "nobody", ""):
        return []

    npcs = _load_npcs()
    graveyard = _load_graveyard()
    consequences = []
    today = datetime.now().strftime("%Y-%m-%d")

    # Split on commas, "and", newlines
    names = re.split(r'[,\n]|\band\b', killed_text)
    names = [n.strip().strip('"').strip("'").strip("-").strip() for n in names if n.strip()]

    for name in names:
        if not name or name.lower() in ("none", "no", "n/a"):
            continue

        npc = _fuzzy_find_npc(name, npcs)
        if not npc:
            consequences.append(f"⚠️ NPC '{name}' not found in roster — manual check needed")
            continue

        npc_name = npc.get("name", name)
        faction  = npc.get("faction", "Independent")

        # Mark dead and move to graveyard
        npc["status"] = "dead"
        npc["history"].append(f"[{today}] Killed during mission: {mission_title}")
        npc["moved_to_graveyard_at"] = datetime.now().isoformat()
        npc["cause_of_death"] = f"Killed by adventurers during '{mission_title}'"

        # Avoid duplicate in graveyard
        if not any(g.get("name") == npc_name for g in graveyard):
            graveyard.append(npc)

        # Remove from active roster
        npcs = [n for n in npcs if n.get("name") != npc_name]

        consequences.append(f"💀 {npc_name} ({faction}) moved to graveyard — killed during '{mission_title}'")

        # Flag if this was a faction leader — special handling triggers in next lifecycle
        try:
            from src.npc_lifecycle import is_faction_leader
            if is_faction_leader(npc_name):
                consequences.append(f"\U0001f451 **{npc_name} was a FACTION LEADER of {faction}!** Special death protocol will trigger next lifecycle cycle.")
        except Exception:
            pass

        # Add enmity to same-faction NPCs
        faction_allies = [n for n in npcs
                         if n.get("faction", "").lower() == faction.lower()
                         and n.get("status") in ("alive", "injured", "undead", "doppelganger")]
        for ally in faction_allies:
            ally_name = ally.get("name", "?")
            ally["history"].append(
                f"[{today}] Faction-mate {npc_name} was killed by adventurers. Enmity noted."
            )
            existing_notes = ally.get("oracle_notes", "")
            enmity_note = f"Hostile toward adventurers who killed {npc_name}."
            if enmity_note not in existing_notes:
                ally["oracle_notes"] = (existing_notes + " " + enmity_note).strip()

            consequences.append(f"😠 {ally_name} ({faction}) — enmity toward party for killing {npc_name}")

    _save_npcs(npcs)
    _save_graveyard(graveyard)

    # Rebuild the RAG txt file
    try:
        from src.npc_lifecycle import _rebuild_txt
        _rebuild_txt(npcs)
    except Exception:
        pass

    return consequences


def process_outcome_consequences(outcome: Dict) -> List[str]:
    """Process all consequences from a mission outcome.
    Returns list of consequence description strings."""
    consequences = []

    # NPC deaths
    killed = outcome.get("npcs_killed", "")
    title  = outcome.get("mission_title", "Unknown Mission")
    if killed:
        consequences.extend(process_npc_deaths(killed, title))

    return consequences
