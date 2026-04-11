"""NPC Consequence Scanner — detects deaths/injuries in bulletins and updates the roster.

After every news bulletin is generated, this module scans the text for
roster NPC names appearing near death/injury language. If detected:
- Death → NPC is moved to the graveyard (npc_roster.json → npc_graveyard.json)
- Injury → NPC status set to "injured" in roster
- Major NPCs get queued for resurrection (2-7 day delay)

The scanner also provides a "recently deceased" context block so future
bulletins can reference recent deaths as story hooks rather than pretending
they never happened.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from src.log import logger
from src.db_api import raw_query as _rq, raw_execute as _rx

DOCS_DIR       = Path(__file__).resolve().parent.parent / "campaign_docs"
NPC_JSON_FILE  = DOCS_DIR / "npc_roster.json"
GRAVEYARD_FILE = DOCS_DIR / "npc_graveyard.json"
NPC_TXT_FILE   = DOCS_DIR / "npc_roster.txt"
RESURRECTION_QUEUE_FILE = DOCS_DIR / "resurrection_queue.json"

# ── Detection patterns ─────────────────────────────────────────────────

# Words/phrases that indicate death when near an NPC name
_DEATH_PATTERNS = [
    r"(?:was|were|been|found|confirmed|reported)\s+(?:killed|slain|murdered|assassinated|dead)",
    r"died\b",
    r"body\s+(?:was|of)\s+(?:found|discovered|recovered)",
    r"did\s+not\s+(?:survive|make\s+it)",
    r"(?:fatally|mortally)\s+(?:wounded|struck|stabbed|injured)",
    r"killed\s+(?:in|during|by|when)",
    r"(?:fell|dropped)\s+dead",
    r"life\s+(?:ended|extinguished|snuffed)",
    r"(?:perished|expired)\b",
    r"last\s+(?:breath|moments?)",
    r"(?:no\s+)?survivors?.*(?:among|including)",
    r"(?:tragic|untimely)\s+(?:death|end|demise)",
    r"did\s+not\s+(?:come\s+back|return|emerge)",
    r"(?:remains|corpse)\s+(?:was|were|of)",
]

# Words/phrases that indicate injury
_INJURY_PATTERNS = [
    r"(?:was|were|been|found)\s+(?:injured|wounded|hurt|struck\s+down|hospitali[sz]ed)",
    r"(?:suffered|sustained)\s+(?:injuries|wounds|a\s+wound)",
    r"(?:critical|serious|grave)\s+(?:condition|injuries|wounds)",
    r"(?:barely|narrowly)\s+(?:survived|escaped|made\s+it)",
    r"(?:recovering|convalescing)\s+(?:from|after)",
    r"(?:left|found)\s+(?:bleeding|unconscious|incapacitated)",
    r"(?:carried|rushed|taken)\s+(?:to|away|from)\s+(?:the\s+)?(?:healer|apothecary|medic|infirmary)",
]

# Compile them
_DEATH_RE = [re.compile(p, re.IGNORECASE) for p in _DEATH_PATTERNS]
_INJURY_RE = [re.compile(p, re.IGNORECASE) for p in _INJURY_PATTERNS]

# How many characters around the name to search for context
_CONTEXT_WINDOW = 200


# ── Roster helpers ─────────────────────────────────────────────────────

def _load_roster() -> List[Dict]:
    """Load alive/injured NPCs from MySQL."""
    try:
        rows = _rq(
            "SELECT name, faction, role, location, status, data_json FROM npcs "
            "WHERE status IN ('alive', 'injured') ORDER BY name"
        ) or []
        npcs = []
        for row in rows:
            dj = row.get("data_json") or {}
            if isinstance(dj, str):
                try:
                    dj = json.loads(dj)
                except Exception:
                    dj = {}
            npc = {**dj, "name": row["name"], "faction": row["faction"],
                   "role": row["role"], "location": row["location"],
                   "status": row["status"], "_db_id": row.get("id")}
            npcs.append(npc)
        return npcs
    except Exception as e:
        logger.error(f"npc_consequence: roster load error: {e}")
        # Fallback to JSON file
        if NPC_JSON_FILE.exists():
            try:
                return json.loads(NPC_JSON_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []


def _save_roster(npcs: List[Dict]) -> None:
    """Save roster back to MySQL and keep JSON/txt in sync."""
    try:
        from src.npc_lifecycle import _save_npc, _rebuild_txt
        for npc in npcs:
            _save_npc(npc)
        _rebuild_txt(npcs)
    except Exception as e:
        logger.error(f"npc_consequence: roster save error: {e}")


def _load_graveyard() -> List[Dict]:
    """Load dead NPCs from MySQL."""
    try:
        rows = _rq(
            "SELECT name, faction, role, location, status, data_json FROM npcs "
            "WHERE status = 'dead' ORDER BY name"
        ) or []
        graveyard = []
        for row in rows:
            dj = row.get("data_json") or {}
            if isinstance(dj, str):
                try:
                    dj = json.loads(dj)
                except Exception:
                    dj = {}
            npc = {**dj, "name": row["name"], "faction": row["faction"],
                   "role": row["role"], "location": row["location"],
                   "status": "dead", "_db_id": row.get("id")}
            graveyard.append(npc)
        return graveyard
    except Exception as e:
        logger.error(f"npc_consequence: graveyard load error: {e}")
        if GRAVEYARD_FILE.exists():
            try:
                return json.loads(GRAVEYARD_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []


def _save_graveyard(graveyard: List[Dict]) -> None:
    """Save dead NPCs back to MySQL (status=dead already set)."""
    try:
        from src.npc_lifecycle import _save_npc
        for npc in graveyard:
            npc["status"] = "dead"
            _save_npc(npc)
    except Exception as e:
        logger.error(f"npc_consequence: graveyard save error: {e}")


def _load_resurrection_queue() -> List[Dict]:
    """Load resurrection queue from MySQL."""
    try:
        rows = _rq(
            "SELECT id, npc_name, died_at, resurrect_at, status FROM resurrection_queue "
            "WHERE status = 'pending' ORDER BY resurrect_at"
        ) or []
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"npc_consequence: resurrection queue load error: {e}")
        if RESURRECTION_QUEUE_FILE.exists():
            try:
                return json.loads(RESURRECTION_QUEUE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []


def _save_resurrection_queue(queue: List[Dict]) -> None:
    """Upsert resurrection queue entries into MySQL."""
    try:
        for entry in queue:
            npc_name = entry.get("npc_name") or entry.get("name", "")
            died_at = entry.get("died_at")
            resurrect_at = entry.get("resurrect_at")
            status = entry.get("status", "pending")
            if not npc_name:
                continue
            existing = _rq(
                "SELECT id FROM resurrection_queue WHERE npc_name=%s AND status='pending'",
                (npc_name,)
            )
            if existing:
                _rx(
                    "UPDATE resurrection_queue SET resurrect_at=%s, status=%s WHERE id=%s",
                    (resurrect_at, status, existing[0]["id"])
                )
            else:
                _rx(
                    "INSERT INTO resurrection_queue (npc_name, died_at, resurrect_at, status) "
                    "VALUES (%s, %s, %s, %s)",
                    (npc_name, died_at, resurrect_at, status)
                )
    except Exception as e:
        logger.error(f"npc_consequence: resurrection queue save error: {e}")


# ── Core scanner ───────────────────────────────────────────────────────

def _is_major_npc(npc: Dict) -> bool:
    """Determine if an NPC is 'major' enough to warrant resurrection."""
    # Faction leaders (high rank)
    rank = npc.get("rank", "").lower()
    leader_ranks = [
        "guildmaster", "captain", "commander", "high apostle", "the widow",
        "sigil master", "director", "head archivist", "archmage", "thane",
        "coordinator", "s-rank", "ss-rank",
    ]
    if any(lr in rank for lr in leader_ranks):
        return True

    # NPCs with secrets or rich history
    if npc.get("secret") and len(npc.get("secret", "")) > 20:
        return True
    if len(npc.get("history", [])) >= 5:
        return True
    if npc.get("revealed_secrets"):
        return True

    # NPCs with oracle notes (DM has marked them as important)
    if npc.get("oracle_notes"):
        return True

    return False


def scan_bulletin_for_consequences(bulletin_text: str) -> List[Dict]:
    """
    Scan a bulletin for death or injury mentions of roster NPCs.

    Returns a list of consequence dicts:
    [
        {"name": "Gruum Boneshaper", "consequence": "death", "context": "...snippet..."},
        {"name": "Eira Ashflame", "consequence": "injury", "context": "...snippet..."},
    ]
    """
    if not bulletin_text or len(bulletin_text) < 20:
        return []

    roster = _load_roster()
    alive_npcs = [n for n in roster if n.get("status") in ("alive", "injured")]

    if not alive_npcs:
        return []

    text_lower = bulletin_text.lower()
    consequences = []

    for npc in alive_npcs:
        name = npc.get("name", "")
        if not name or len(name) < 3:
            continue

        # Check if the NPC name appears in the bulletin
        name_lower = name.lower()

        # Try full name first, then last name for two-word names
        name_parts = [name_lower]
        words = name.split()
        if len(words) >= 2:
            # Also check last name alone (e.g., "Boneshaper was killed")
            name_parts.append(words[-1].lower())

        for name_variant in name_parts:
            if name_variant not in text_lower:
                continue

            # Found the name — now check nearby context for death/injury patterns
            idx = text_lower.find(name_variant)
            while idx != -1:
                start = max(0, idx - _CONTEXT_WINDOW)
                end = min(len(text_lower), idx + len(name_variant) + _CONTEXT_WINDOW)
                context = text_lower[start:end]
                original_context = bulletin_text[start:end]

                # Check death patterns first (stronger signal)
                is_death = any(pat.search(context) for pat in _DEATH_RE)
                is_injury = any(pat.search(context) for pat in _INJURY_RE)

                if is_death:
                    consequences.append({
                        "name": name,
                        "consequence": "death",
                        "context": original_context.strip(),
                    })
                    break  # Don't double-count
                elif is_injury and npc.get("status") != "injured":
                    consequences.append({
                        "name": name,
                        "consequence": "injury",
                        "context": original_context.strip(),
                    })
                    break

                # Look for next occurrence
                idx = text_lower.find(name_variant, idx + 1)

            # If we already found a consequence for this NPC, skip other name variants
            if any(c["name"] == name for c in consequences):
                break

    return consequences


def apply_consequences(consequences: List[Dict]) -> List[str]:
    """
    Apply detected consequences to the roster.

    Returns a list of log messages describing what changed.
    """
    if not consequences:
        return []

    roster = _load_roster()
    graveyard = _load_graveyard()
    res_queue = _load_resurrection_queue()
    changes = []
    roster_changed = False
    graveyard_changed = False
    queue_changed = False

    for cons in consequences:
        name = cons["name"]
        ctype = cons["consequence"]
        context = cons.get("context", "")

        # Find the NPC in roster
        npc = None
        npc_idx = None
        for i, n in enumerate(roster):
            if n.get("name") == name:
                npc = n
                npc_idx = i
                break

        if npc is None:
            continue

        if ctype == "death":
            is_major = _is_major_npc(npc)

            # Add death to history
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            npc.setdefault("history", []).append(
                f"[{ts}] DIED — narrated in news bulletin"
            )
            npc["status"] = "dead"
            npc["death_date"] = ts
            npc["death_cause"] = f"News bulletin: {context[:200]}"

            # Move to graveyard
            graveyard.append(npc)
            graveyard_changed = True
            roster.pop(npc_idx)
            roster_changed = True

            change_msg = f"💀 {name} ({npc.get('faction', '?')}) killed in news bulletin"
            logger.info(f"npc_consequence: {change_msg}")
            changes.append(change_msg)

            # Queue resurrection for major NPCs
            if is_major:
                import random
                res_days = random.randint(2, 7)
                res_date = (datetime.now() + timedelta(days=res_days)).isoformat()
                res_queue.append({
                    "name": name,
                    "faction": npc.get("faction", "Unknown"),
                    "rank": npc.get("rank", "Unknown"),
                    "species": npc.get("species", "Unknown"),
                    "scheduled_for": res_date,
                    "death_date": ts,
                    "death_cause": context[:200],
                    "queued_at": datetime.now().isoformat(),
                })
                queue_changed = True
                res_msg = f"✨ {name} queued for resurrection in {res_days} days (major NPC)"
                logger.info(f"npc_consequence: {res_msg}")
                changes.append(res_msg)

        elif ctype == "injury":
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            npc.setdefault("history", []).append(
                f"[{ts}] INJURED — narrated in news bulletin"
            )
            npc["status"] = "injured"
            roster_changed = True

            change_msg = f"🩹 {name} ({npc.get('faction', '?')}) injured in news bulletin"
            logger.info(f"npc_consequence: {change_msg}")
            changes.append(change_msg)

    # Persist
    if roster_changed:
        _save_roster(roster)
    if graveyard_changed:
        _save_graveyard(graveyard)
    if queue_changed:
        _save_resurrection_queue(res_queue)

    return changes


# ── Resurrection check ─────────────────────────────────────────────────

def check_resurrection_queue() -> List[Dict]:
    """
    Check if any resurrection is due. Returns list of NPCs to resurrect.
    Called from npc_lifecycle daily loop.

    Each returned dict has the NPC's old data for re-creation.
    """
    queue = _load_resurrection_queue()
    if not queue:
        return []

    now = datetime.now()
    due = []
    remaining = []

    for entry in queue:
        try:
            scheduled = datetime.fromisoformat(entry["scheduled_for"])
            if now >= scheduled:
                due.append(entry)
            else:
                remaining.append(entry)
        except Exception:
            remaining.append(entry)  # malformed → keep for retry

    if due:
        _save_resurrection_queue(remaining)

    return due


def resurrect_npc(entry: Dict) -> Optional[Dict]:
    """
    Resurrect an NPC from the graveyard back into the active roster.
    Returns the resurrected NPC dict, or None if not found in graveyard.
    """
    name = entry.get("name", "")
    graveyard = _load_graveyard()
    roster = _load_roster()

    # Find in graveyard
    npc = None
    for i, g in enumerate(graveyard):
        if g.get("name") == name:
            npc = graveyard.pop(i)
            break

    if npc is None:
        logger.warning(f"npc_consequence: {name} not found in graveyard for resurrection")
        return None

    # Resurrect
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    npc["status"] = "alive"
    npc.setdefault("history", []).append(
        f"[{ts}] RESURRECTED — returned from death via divine/arcane intervention"
    )
    npc["resurrected_at"] = ts

    # Add to roster
    roster.append(npc)
    _save_roster(roster)
    _save_graveyard(graveyard)

    logger.info(f"npc_consequence: ✨ {name} resurrected and returned to active roster")
    return npc


# ── Context block for bulletin prompts ─────────────────────────────────

def get_recently_deceased_block(days: int = 7) -> str:
    """
    Build a context block of recently deceased NPCs for bulletin prompt injection.
    This lets the news feed reference recent deaths as story hooks instead
    of pretending they never happened.
    """
    graveyard = _load_graveyard()
    if not graveyard:
        return ""

    cutoff = datetime.now() - timedelta(days=days)
    recent = []
    for npc in graveyard:
        death_date_str = npc.get("death_date", "")
        if not death_date_str:
            continue
        try:
            death_date = datetime.strptime(death_date_str, "%Y-%m-%d %H:%M")
            if death_date >= cutoff:
                recent.append(npc)
        except Exception:
            continue

    if not recent:
        return ""

    lines = [
        "RECENTLY DECEASED (died in the last week — reference their death for story continuity, "
        "do NOT write them as alive or active):"
    ]
    for npc in recent:
        name = npc.get("name", "Unknown")
        faction = npc.get("faction", "?")
        cause = npc.get("death_cause", "unknown circumstances")[:100]
        lines.append(f"- {name} ({faction}) — {cause}")

    # Check resurrection queue
    queue = _load_resurrection_queue()
    pending = [q["name"] for q in queue]
    for npc in recent:
        if npc.get("name") in pending:
            lines.append(
                f"  ↳ NOTE: Rumours persist that {npc['name']} may not truly be gone. "
                f"(You may hint at mysterious circumstances around their death.)"
            )

    return "\n".join(lines)


# ── Single-call convenience ────────────────────────────────────────────

def process_bulletin(bulletin_text: str) -> List[str]:
    """
    Convenience function: scan a bulletin and apply any consequences.
    Returns list of change log messages (empty if nothing happened).
    """
    consequences = scan_bulletin_for_consequences(bulletin_text)
    if not consequences:
        return []
    return apply_consequences(consequences)
