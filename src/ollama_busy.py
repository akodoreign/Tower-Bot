"""
ollama_busy.py — Shared busy flag for Ollama Pi/OpenClaw stack.

Prevents timeout cascades when a long-running task (e.g., module generation)
has Ollama locked up. Other systems check is_available() before calling Ollama
and skip gracefully if it's busy, instead of waiting 7 minutes to timeout.

REFACTORED for Pi/OpenClaw:
    Both QwenAgent and KimiAgent share the same Ollama instance, so they share
    the same busy state. The helpers in src/agents/helpers.py automatically
    check is_available() before making calls.

Usage:
    from src.ollama_busy import is_available, mark_busy, mark_available

    # Long-running task (module generator):
    mark_busy("module generation: The Crimson Ledger")
    try:
        ... do 8 Ollama passes ...
    finally:
        mark_available()

    # Short-lived callers (using agents — automatic check):
    from src.agents import generate_with_kimi
    text = await generate_with_kimi(prompt)  # Checks is_available() internally

    # Manual check if needed:
    if not is_available():
        logger.info(f"Ollama busy ({get_busy_reason()}) — skipping this cycle")
        return None
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional

_busy: bool = False
_busy_count: int = 0          # reference count — cleared only when this hits 0
_busy_reason: str = ""
_busy_since: str = ""
_busy_model: str = ""         # Track which model/agent triggered the busy state
_priority_busy: bool = False  # High-priority flag (mission building) "" lifecycle yields immediately

# Who is holding the flag, counted per holder. The flag means "OTHER callers stay
# out" -- a task must never be blocked by its own claim, so a holder that then
# asks permission to call Ollama has to be exempt from itself. Without this a
# task that marks busy and then goes through the resource cop deadlocks against
# itself and silently produces nothing. See is_available_for().
_busy_holders: dict[str, int] = {}

# Cross-process DB cache — avoid hammering DB on every check
_db_cache_ts: float = 0.0
_db_cache_val: bool = False
_DB_CACHE_TTL: float = 10.0   # re-read DB at most every 10 seconds


def _db_priority_busy() -> bool:
    """
    Read pipeline_busy flag from global_state DB.
    Cached for 10s so bot loops don't hammer the DB.
    This is the cross-process signal — survives separate scripts.
    """
    global _db_cache_ts, _db_cache_val
    import time
    now = time.monotonic()
    if now - _db_cache_ts < _DB_CACHE_TTL:
        return _db_cache_val
    try:
        from src.db_api import get_global_state as _gs
        val = _gs("pipeline_busy")
        # val is a dict {"active": true, ...} or None/False
        if isinstance(val, dict):
            result = bool(val.get("active", False))
        else:
            result = bool(val)
        _db_cache_val = result
        _db_cache_ts  = now
        return result
    except Exception:
        _db_cache_ts = now  # don't retry immediately on DB error
        return _db_cache_val


def is_available() -> bool:
    """Returns True if Ollama is free for requests."""
    return not _busy and not _db_priority_busy()


def is_available_for(holder: str = "") -> bool:
    """Availability from `holder`'s point of view -- its OWN claim never blocks it.

    The busy flag is a "stay out" signal aimed at other callers. A long task that
    marks busy and then asks the resource cop for a turn is asking about itself,
    and must be told yes. Any claim held by someone else, or a priority claim from
    another process, still blocks normally.

    With no holder this is exactly is_available().
    """
    if is_available():
        return True                       # nothing is busy -- the common path
    mine = _busy_holders.get(holder, 0)
    if not holder or not mine:
        return False                      # not a holder: exactly the old behaviour
    if _busy and (_busy_count - mine) > 0:
        return False                      # somebody else is holding it too
    if _db_priority_busy() and not _priority_busy:
        return False                      # a cross-process claim we do not own
    return True


def busy_holders() -> dict[str, int]:
    """Snapshot of current holders, for diagnostics."""
    return dict(_busy_holders)


def is_priority_busy() -> bool:
    """Returns True if a high-priority task has claimed Ollama — checks both in-process and DB."""
    return _priority_busy or _db_priority_busy()


def get_busy_reason() -> str:
    """Returns a human-readable reason why Ollama is busy, or empty string."""
    if _busy:
        elapsed = ""
        if _busy_since:
            try:
                delta = (datetime.now() - datetime.fromisoformat(_busy_since)).total_seconds()
                elapsed = f" ({delta:.0f}s ago)"
            except Exception:
                pass
        model_info = f" [{_busy_model}]" if _busy_model else ""
        return f"{_busy_reason}{model_info}{elapsed}"
    # In-process not busy — check DB flag for a reason
    if _db_priority_busy():
        try:
            from src.db_api import get_global_state as _gs
            val = _gs("pipeline_busy")
            if isinstance(val, dict) and val.get("active"):
                reason = val.get("reason", "DB pipeline lock")
                since = val.get("since", "")
                elapsed = ""
                if since:
                    try:
                        from datetime import datetime as _dt
                        delta = (_dt.now() - _dt.fromisoformat(since)).total_seconds()
                        elapsed = f" ({delta / 3600:.1f}h ago)"
                    except Exception:
                        pass
                return f"DB: {reason}{elapsed}"
        except Exception:
            pass
        return "DB pipeline lock"
    return ""


def mark_busy(reason: str = "long-running generation", model: str = "",
              holder: str = "") -> None:
    """
    Mark Ollama as busy. Other systems will skip their cycles.
    Reference-counted: mark_available() only clears the flag when all callers are done.

    Args:
        reason: Human-readable description of what's happening
        model: Optional model name (qwen, kimi, etc.) for debugging
        holder: Stable key identifying the claimant. Pass this whenever the task
            will itself call Ollama through the resource cop, and pass the SAME
            key to the cop -- it is what exempts a task from its own flag.
            Must be paired with mark_available(holder=...).
    """
    global _busy, _busy_count, _busy_reason, _busy_since, _busy_model
    _busy_count += 1
    _busy = True
    if holder:
        _busy_holders[holder] = _busy_holders.get(holder, 0) + 1
    if _busy_count == 1:
        # First caller sets the reason/timestamp
        _busy_reason = reason
        _busy_since = datetime.now().isoformat()
        _busy_model = model


def mark_available(holder: str = "") -> None:
    """
    Mark one caller as done. Clears the busy flag only when all callers have finished.
    Reference-counted to handle overlapping long-running tasks correctly.

    Pass the same `holder` given to mark_busy(). Holders are cleared wholesale when
    the reference count reaches zero, so a mismatched pair leaks nothing.
    """
    global _busy, _busy_count, _busy_reason, _busy_since, _busy_model
    _busy_count = max(0, _busy_count - 1)
    if holder and _busy_holders.get(holder):
        _busy_holders[holder] -= 1
        if _busy_holders[holder] <= 0:
            _busy_holders.pop(holder, None)
    if _busy_count == 0:
        _busy = False
        _busy_reason = ""
        _busy_since = ""
        _busy_model = ""
        _busy_holders.clear()   # self-healing: nothing is busy, so nobody holds it


def mark_priority_busy(reason: str = "mission building", model: str = "",
                       holder: str = "") -> None:
    """
    Mark Ollama as busy with HIGH priority.
    Writes to DB so external scripts and separate bot processes all see the flag.

    `holder` behaves exactly as in mark_busy(): it exempts the claimant from its
    own flag when it later asks the resource cop for a turn.
    """
    global _priority_busy, _db_cache_val, _db_cache_ts
    _priority_busy = True
    _db_cache_val  = True
    _db_cache_ts   = 0.0   # force next read to hit DB
    mark_busy(reason, model, holder=holder)
    try:
        from src.db_api import set_global_state as _ss
        import datetime as _dt
        _ss("pipeline_busy", {
            "active":  True,
            "reason":  reason,
            "model":   model,
            "since":   _dt.datetime.now().isoformat(timespec="seconds"),
        })
    except Exception:
        pass  # in-process flag still works; DB write best-effort


def unmark_priority_busy(holder: str = "") -> None:
    """Clear the high-priority busy flag in-process and in DB."""
    global _priority_busy, _db_cache_val, _db_cache_ts
    _priority_busy = False
    _db_cache_val  = False
    _db_cache_ts   = 0.0
    mark_available(holder=holder)
    try:
        from src.db_api import set_global_state as _ss
        _ss("pipeline_busy", {"active": False, "reason": "", "since": ""})
    except Exception:
        pass


def get_busy_duration() -> Optional[float]:
    """Returns seconds since marked busy, or None if not busy."""
    if not _busy or not _busy_since:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(_busy_since)).total_seconds()
    except Exception:
        return None
