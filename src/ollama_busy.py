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
_busy_reason: str = ""
_busy_since: str = ""
_busy_model: str = ""  # Track which model/agent triggered the busy state


def is_available() -> bool:
    """Returns True if Ollama is free for requests."""
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
    model_info = f" [{_busy_model}]" if _busy_model else ""
    return f"{_busy_reason}{model_info}{elapsed}"


def mark_busy(reason: str = "long-running generation", model: str = "") -> None:
    """
    Mark Ollama as busy. Other systems will skip their cycles.
    
    Args:
        reason: Human-readable description of what's happening
        model: Optional model name (qwen, kimi, etc.) for debugging
    """
    global _busy, _busy_reason, _busy_since, _busy_model
    _busy = True
    _busy_reason = reason
    _busy_since = datetime.now().isoformat()
    _busy_model = model


def mark_available() -> None:
    """Mark Ollama as available again."""
    global _busy, _busy_reason, _busy_since, _busy_model
    _busy = False
    _busy_reason = ""
    _busy_since = ""
    _busy_model = ""


def get_busy_duration() -> Optional[float]:
    """Returns seconds since marked busy, or None if not busy."""
    if not _busy or not _busy_since:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(_busy_since)).total_seconds()
    except Exception:
        return None
