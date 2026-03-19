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

logger = logging.getLogger(__name__)

DOCS_DIR        = Path(__file__).resolve().parent.parent / "campaign_docs"
OUTCOMES_FILE   = DOCS_DIR / "mission_outcomes.json"
NPC_JSON_FILE   = DOCS_DIR / "npc_roster.json"
GRAVEYARD_FILE  = DOCS_DIR / "npc_graveyard.json"
ARCHIVES_DIR    = DOCS_DIR / "archives"
MISSION_ARCHIVE = ARCHIVES_DIR / "missions"
NEWS_ARCHIVE    = ARCHIVES_DIR / "news"
MEMORY_FILE     = DOCS_DIR / "news_memory.txt"


# ---------------------------------------------------------------------------
# Persistence — structured JSON (for code queries)
# ---------------------------------------------------------------------------

def _load_outcomes() -> List[Dict]:
    if not OUTCOMES_FILE.exists():
        return []
    try:
        return json.loads(OUTCOMES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_outcomes(outcomes: List[Dict]) -> None:
    try:
        OUTCOMES_FILE.write_text(
            json.dumps(outcomes, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"Failed to save mission outcomes: {e}")


def get_recent_outcomes(n: int = 10) -> List[Dict]:
    """Return the N most recent outcomes for code-level queries."""
    return _load_outcomes()[-n:]


# ---------------------------------------------------------------------------
# Save outcome — JSON + readable .md archive file
# ---------------------------------------------------------------------------

def save_outcome(outcome: Dict) -> None:
    """Save a mission outcome to both JSON and a readable archive file."""
    # Append to JSON
    outcomes = _load_outcomes()
    outcomes.append(outcome)
    _save_outcomes(outcomes)

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
    """Archive the current news_memory.txt to a dated file and trim it.
    Returns the archive filename, or None if nothing to archive."""
    NEWS_ARCHIVE.mkdir(parents=True, exist_ok=True)

    if not MEMORY_FILE.exists():
        return None

    try:
        content = MEMORY_FILE.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    if not content.strip():
        return None

    # Save archive
    now = datetime.now()
    fname = f"news_week_{now.strftime('%Y-%m-%d')}.txt"
    archive_path = NEWS_ARCHIVE / fname

    try:
        # Append to existing weekly file if same week, or create new
        if archive_path.exists():
            existing = archive_path.read_text(encoding="utf-8", errors="ignore")
            archive_path.write_text(
                existing + "\n\n--- CONTINUED ---\n\n" + content,
                encoding="utf-8"
            )
        else:
            header = f"# News Archive — Week of {now.strftime('%Y-%m-%d')}\n\n"
            archive_path.write_text(header + content, encoding="utf-8")

        # Trim memory to last 15 entries (keep recent for continuity, archive the rest)
        entries = [e.strip() for e in content.split("\n---ENTRY---\n") if e.strip()]
        if len(entries) > 15:
            trimmed = entries[-15:]
            MEMORY_FILE.write_text("\n---ENTRY---\n".join(trimmed), encoding="utf-8")
            logger.info(f"📰 News archived to {fname} — trimmed memory from {len(entries)} to 15 entries")
        else:
            logger.info(f"📰 News archived to {fname} — memory has {len(entries)} entries (no trim needed)")

        return fname
    except Exception as e:
        logger.error(f"📰 News archive failed: {e}")
        return None


def archive_outcomes_weekly() -> Optional[str]:
    """Archive older mission outcomes (keep last 10 in active JSON)."""
    outcomes = _load_outcomes()
    if len(outcomes) <= 10:
        return None  # nothing to archive

    # Already archived as individual .md files — just trim the JSON
    kept = outcomes[-10:]
    archived_count = len(outcomes) - 10
    _save_outcomes(kept)
    logger.info(f"📋 Trimmed mission_outcomes.json: archived {archived_count}, kept {len(kept)}")
    return f"trimmed_{archived_count}_outcomes"


# ---------------------------------------------------------------------------
# Consequence processing — NPC deaths, faction enmity, etc.
# ---------------------------------------------------------------------------

def _load_npcs() -> List[Dict]:
    if not NPC_JSON_FILE.exists():
        return []
    try:
        return json.loads(NPC_JSON_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_npcs(npcs: List[Dict]) -> None:
    try:
        NPC_JSON_FILE.write_text(json.dumps(npcs, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_graveyard() -> List[Dict]:
    if not GRAVEYARD_FILE.exists():
        return []
    try:
        return json.loads(GRAVEYARD_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_graveyard(graveyard: List[Dict]) -> None:
    try:
        GRAVEYARD_FILE.write_text(json.dumps(graveyard, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


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
                         and n.get("status") in ("alive", "injured")]
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
