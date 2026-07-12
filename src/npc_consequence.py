"""NPC Consequence Scanner — detects deaths/injuries in bulletins and updates the roster.

After every news bulletin is generated, this module scans the text for
roster NPC names appearing near death/injury language. If detected:
- Death → NPC status set to "dead" in npcs table, queued in resurrection_queue
- Injury → NPC status set to "injured" in roster
- Major NPCs get queued for resurrection (2-7 day delay)

The scanner also provides a "recently deceased" context block so future
bulletins can reference recent deaths as story hooks rather than pretending
they never happened.
"""

from __future__ import annotations

import re
import json
import random
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from src.log import logger
from src.db_api import raw_query as _rq, raw_execute as _rx, add_npc_history_event, get_npc_history_count, has_revealed_secrets

DOCS_DIR       = Path(__file__).resolve().parent.parent / "campaign_docs"

UNKNOWN_PARTY_MEMBERS = {
    "The Ward": {"true_faction": "Tower Authority", "designation": "WARD", "cover": "Independent enforcer"},
    "Carrion": {"true_faction": "Iron Fang Consortium", "designation": "CARRION", "cover": "Independent scavenger"},
    "Sable": {"true_faction": "Glass Sigil", "designation": "SABLE", "cover": "Serpent Choir (disputed)"},
    "Locket": {"true_faction": "Obsidian Lotus", "designation": "LOCKET", "cover": "Independent"},
    "The Mute": {"true_faction": "Wardens of Ash", "designation": "VIGIL", "cover": "Independent"},
}

UNKNOWN_PARTY_REPLACEMENT_DESIGNATIONS = [
    "LANTERN", "CIPHER", "SUTURE", "HUSH", "VEIL", "MOTH", "GRAVITY",
    "LOCKSTEP", "CANDLE", "THRESHOLD", "MARROW", "STATIC",
]

MAJOR_RAISE_DEAD_LOST_TO_TOWER_CHANCE = 0.10

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


def _hist(npc: dict, body: str) -> None:
    npc_id = npc.get("_db_id") or npc.get("id")
    if npc_id:
        add_npc_history_event(int(npc_id), body)
    npc.setdefault("history", []).append(body)


# ── Roster helpers ─────────────────────────────────────────────────────

def _load_roster() -> List[Dict]:
    """Load alive/injured NPCs from MySQL."""
    try:
        rows = _rq(
            "SELECT id, name, faction, role, location, status, data_json FROM npcs "
            "WHERE status IN ('alive', 'injured', 'undead', 'doppelganger') ORDER BY name"
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
            "SELECT id, name, faction, role, location, status, data_json FROM npcs "
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
            if not resurrect_at:
                resurrect_at = entry.get("scheduled_for")
            if not died_at:
                died_at = entry.get("death_date") or entry.get("queued_at") or datetime.now()
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
    if npc.get("name") in UNKNOWN_PARTY_MEMBERS:
        return True

    secret_text = " ".join(str(npc.get(k, "")) for k in ("secret", "oracle_notes", "role", "rank")).lower()
    if any(token in secret_text for token in ("designation", "code name", "codename", "classified", "black-cell")):
        return True

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
    if get_npc_history_count(npc.get("_db_id") or 0) >= 5:
        return True
    if has_revealed_secrets(npc.get("_db_id") or 0):
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
    alive_npcs = [n for n in roster if n.get("status") in ("alive", "injured", "undead", "doppelganger")]

    if not alive_npcs:
        return []

    text_lower = bulletin_text.lower()
    consequences = []

    # Unknown Party members have their own death protocol (npc_lifecycle.py).
    # Their short alias names ("ward", "carrion", "sable", etc.) appear in normal
    # Undercity prose constantly and cause false-positive deaths here. Skip them.
    try:
        from src.npc_lifecycle import is_unknown_party_member as _is_up
    except Exception:
        _is_up = lambda _: False

    for npc in alive_npcs:
        name = npc.get("name", "")
        if not name or len(name) < 3:
            continue
        if _is_up(name):
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
            _hist(npc, f"[{ts}] DIED — narrated in news bulletin")
            npc["status"] = "dead"
            npc["death_date"] = ts
            npc["death_cause"] = f"News bulletin: {context[:200]}"
            npc_id = npc.get("_db_id") or npc.get("id")
            if npc_id:
                _rx("UPDATE npcs SET death_cause=%s WHERE id=%s", (npc["death_cause"], npc_id))

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
                res_days = random.randint(1, 3)
                res_date = (datetime.now() + timedelta(days=res_days)).isoformat()
                res_queue.append({
                    "name": name,
                    "npc_name": name,
                    "faction": npc.get("faction", "Unknown"),
                    "rank": npc.get("rank", "Unknown"),
                    "species": npc.get("species", "Unknown"),
                    "resurrect_at": res_date,
                    "died_at": ts,
                    "death_cause": context[:200],
                    "queued_at": datetime.now().isoformat(),
                })
                queue_changed = True
                res_msg = f"✨ {name} queued for resurrection in {res_days} days (major NPC)"
                if "resurrection" in res_msg:
                    res_msg = f"Raise dead funded for {name}; expected return in {res_days} days, unless the Tower claims them."
                logger.info(f"npc_consequence: {res_msg}")
                changes.append(res_msg)

        elif ctype == "injury":
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            _hist(npc, f"[{ts}] INJURED — narrated in news bulletin")
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
    """Check pending raise dead rows and mark due entries as resolving."""
    queue = _load_resurrection_queue()
    if not queue:
        return []

    now = datetime.now()
    due = []
    for entry in queue:
        try:
            scheduled_raw = entry.get("resurrect_at") or entry.get("scheduled_for")
            scheduled = datetime.fromisoformat(str(scheduled_raw))
        except Exception:
            continue
        if now >= scheduled:
            due.append(entry)

    for entry in due:
        entry_id = entry.get("id")
        if entry_id:
            _rx("UPDATE resurrection_queue SET status='resolving' WHERE id=%s", (entry_id,))
    return due


def _mark_queue_resolved(entry: Dict, status: str) -> None:
    entry_id = entry.get("id")
    name = entry.get("npc_name") or entry.get("name")
    if entry_id:
        _rx("UPDATE resurrection_queue SET status=%s WHERE id=%s", (status, entry_id))
    elif name:
        _rx(
            "UPDATE resurrection_queue SET status=%s WHERE npc_name=%s AND status IN ('pending','resolving')",
            (status, name),
        )


def _unknown_party_data(name: str) -> Optional[Dict]:
    return UNKNOWN_PARTY_MEMBERS.get(name)


def _make_unknown_party_replacement(lost_npc: Dict) -> Dict:
    # _load_roster() merges data_json into the flat NPC dict, so designation
    # is already a top-level key rather than nested under data_json.
    used = {n.get("designation") for n in _load_roster() if n.get("designation")}
    designation = next(
        (d for d in UNKNOWN_PARTY_REPLACEMENT_DESIGNATIONS if d not in used),
        random.choice(UNKNOWN_PARTY_REPLACEMENT_DESIGNATIONS),
    )
    codename = f"The {designation.title()}"
    faction = lost_npc.get("faction") or "Independent"
    true_faction = _unknown_party_data(lost_npc.get("name", "")) or {}
    true_faction_name = true_faction.get("true_faction", faction)
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "name": codename,
        "faction": "Independent",
        "role": "Replacement covert operative",
        "rank": "Unfiled",
        "species": "Unknown",
        "location": "Unknown Party dead-drop circuit",
        "status": "alive",
        "designation": designation,
        "secret": (
            f"TRUE FACTION: {true_faction_name}. Replacement asset activated after "
            f"{lost_npc.get('name', 'a prior member')} was lost to the Tower. "
            "Uses a secret code name only; public identity intentionally absent."
        ),
        "oracle_notes": (
            f"Unknown Party replacement for {lost_npc.get('name', 'unknown')}. "
            "Major player. Treat as a full operative, not filler."
        ),
        "history": [
            f"[{today}] Activated as replacement designation {designation} after Tower-loss protocol."
        ],
    }


def resurrect_npc(entry: Dict) -> Optional[Dict]:
    """
    Resurrect an NPC from the graveyard back into the active roster.
    Returns the resurrected NPC dict, or None if not found in graveyard.
    """
    name = entry.get("npc_name") or entry.get("name", "")
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
        _mark_queue_resolved(entry, "missing_body")
        return None

    if random.random() < MAJOR_RAISE_DEAD_LOST_TO_TOWER_CHANCE:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        _hist(npc, f"[{ts}] LOST TO THE TOWER - raise dead failed; soul unavailable.")
        npc["tower_absorbed"] = True
        npc["lost_to_tower"] = True
        npc["status"] = "dead"
        npc_id = npc.get("_db_id") or npc.get("id")
        if npc_id:
            _rx("UPDATE npcs SET tower_absorbed=1 WHERE id=%s", (npc_id,))
        npc["oracle_notes"] = (
            npc.get("oracle_notes", "") +
            " Raise dead was funded, diamond secured, spell cast. The Tower kept them anyway."
        ).strip()
        graveyard.append(npc)

        replacement = None
        if name in UNKNOWN_PARTY_MEMBERS:
            replacement = _make_unknown_party_replacement(npc)
            roster.append(replacement)
            logger.info(
                f"npc_consequence: {name} lost to Tower; replacement {replacement['name']} "
                f"({replacement['designation']}) activated"
            )

        _save_roster(roster)
        _save_graveyard(graveyard)
        _mark_queue_resolved(entry, "lost_to_tower")
        return {
            "name": name,
            "faction": npc.get("faction", "Unknown"),
            "status": "lost_to_tower",
            "replacement": replacement,
        }

    # Resurrect
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    npc["status"] = "alive"
    _hist(npc, f"[{ts}] RESURRECTED — returned from death via divine/arcane intervention")
    npc["resurrected_at"] = ts

    # Add to roster
    roster.append(npc)
    _save_roster(roster)
    _save_graveyard(graveyard)
    _mark_queue_resolved(entry, "raised")

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

    def _parse_any_date(npc: dict) -> Optional[datetime]:
        """Try every date field an NPC might have, return datetime or None."""
        for field in ("death_date", "moved_to_graveyard_at", "deceased_at"):
            raw = npc.get(field)
            if not raw:
                continue
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    # Handle datetime objects from DB
                    if hasattr(raw, 'strftime'):
                        return raw
                    return datetime.strptime(str(raw)[:19], fmt[:len(fmt)])
                except Exception:
                    continue
        return None

    for npc in graveyard:
        death_date = _parse_any_date(npc)
        if death_date and death_date >= cutoff:
            recent.append(npc)

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
    pending = [q.get("npc_name") or q.get("name", "") for q in queue]
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
