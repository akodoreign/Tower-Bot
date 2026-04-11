"""
ollama_queue.py — Serialized FIFO queue for all Ollama HTTP requests.

Problem: multiple async loops (news_feed, npc_lifecycle, agents, etc.) call
Ollama concurrently.  Ollama is single-threaded — concurrent calls cause
ReadTimeout cascades where every request fails.

Solution: one asyncio.Lock gates all Ollama POST requests.  Callers wait
their turn in arrival order; none compete and none time out waiting for
the model itself.

Usage:
    from src.ollama_queue import call_ollama

    data = await call_ollama(
        payload={"model": model, "messages": [...], "stream": False},
        timeout=300.0,
        caller="news_feed",
    )
    # Returns the parsed JSON dict, or raises on HTTP/timeout error.

The busy flag (src/ollama_busy) is still honoured for very long tasks like
module generation that would otherwise make the queue 30+ minutes deep.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Single global lock — all Ollama callers acquire this before POSTing.
# asyncio.Lock is FIFO: requests run in the order they reach `await _lock.acquire()`.
_lock = asyncio.Lock()
_waiting: int = 0   # callers currently queued waiting for the lock


async def call_ollama(
    payload: Dict[str, Any],
    timeout: float = 300.0,
    caller: str = "",
) -> Dict[str, Any]:
    """
    Route one Ollama request through the global FIFO lock.

    Args:
        payload:  Full Ollama /api/chat request body (model, messages, options…)
        timeout:  Seconds allowed for Ollama to respond once it starts.
                  Lock wait time is NOT included — callers queue up indefinitely.
        caller:   Short label for log messages (e.g. "news_feed", "npc_lifecycle")

    Returns:
        Parsed JSON response dict.

    Raises:
        OllamaBusyError  — a long-running task has called mark_busy(); skip this cycle.
        httpx.ReadTimeout / httpx.HTTPError — Ollama error; caller decides retry logic.
    """
    global _waiting
    import httpx

    # Honour the busy flag for very long tasks (module generation, ~30 min) that
    # explicitly call mark_busy() — queuing those would stall everything for too long.
    from src.ollama_busy import is_available, get_busy_reason
    if not is_available():
        tag = f"[{caller}] " if caller else ""
        logger.info(f"🔀 Ollama queue {tag}skipping — long task busy: {get_busy_reason()}")
        raise OllamaBusyError(get_busy_reason())

    tag = f"[{caller}] " if caller else ""
    _waiting += 1
    try:
        if _waiting > 1:
            logger.info(f"🔀 Ollama queue {tag}waiting for slot (queue depth={_waiting})")

        async with _lock:
            _waiting -= 1
            if _waiting > 0:
                logger.info(f"🔀 Ollama queue {tag}slot acquired ({_waiting} still waiting)")

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat"),
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()

    except OllamaBusyError:
        raise
    except BaseException:
        # If we raised before entering the lock context (shouldn't happen with asyncio.Lock)
        # make sure the waiting counter is corrected.  Normally the `async with _lock` block
        # handles the decrement, so this is just a safety net.
        if _waiting > 0:
            _waiting -= 1
        raise


class OllamaBusyError(RuntimeError):
    """Raised when call_ollama is skipped because a long task holds the busy flag."""
    pass
