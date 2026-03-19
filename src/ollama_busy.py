"""
ollama_busy.py — Shared busy flag for Ollama.

Prevents timeout cascades when a long-running task (e.g., module generation)
has Ollama locked up. Other systems check is_available() before calling Ollama
and skip gracefully if it's busy, instead of waiting 7 minutes to timeout.

Usage:
    from src.ollama_busy import is_available, mark_busy, mark_available

    # Long-running task (module generator):
    mark_busy("module generation: The Crimson Ledger")
    try:
        ... do 8 Ollama passes ...
    finally:
        mark_available()

    # Short-lived callers (news feed, mission board, etc.):
    if not is_available():
        logger.info(f"Ollama busy ({get_busy_reason()}) — skipping this cycle")
        return None
    ... call Ollama normally ...
"""

from __future__ import annotations
from datetime import datetime

_busy: bool = False
_busy_reason: str = ""
_busy_since: str = ""


def is_available() -> bool:
    """Returns True if Ollama is free for short requests."""
    return not _busy


def get_busy_reason() -> str:
    """Returns a human-readable reason why Ollama is busy, or empty string."""
    if not _busy:
        return ""
    elapsed = ""
    if _busy_since:
        try:
            delta = (datetime.now() - datetime.fromisoformat(_busy_since)).total_seconds()
            elapsed = f" ({delta:.0f}s ago)"
        except Exception:
            pass
    return f"{_busy_reason}{elapsed}"


def mark_busy(reason: str = "long-running generation") -> None:
    """Mark Ollama as busy. Other systems will skip their cycles."""
    global _busy, _busy_reason, _busy_since
    _busy = True
    _busy_reason = reason
    _busy_since = datetime.now().isoformat()


def mark_available() -> None:
    """Mark Ollama as available again."""
    global _busy, _busy_reason, _busy_since
    _busy = False
    _busy_reason = ""
    _busy_since = ""
