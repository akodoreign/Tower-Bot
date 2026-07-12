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

# Primary lock — heavy/pipeline tasks (Bob chapters, module building, DNDExpert).
# When held, the heavy task has exclusive GPU time on this track.
_lock = asyncio.Lock()
_waiting: int = 0

# Secondary lock — quick bot tasks (bulletins, events, NPC lifecycle, weather).
# Separate queue so short tasks never wait 45 minutes behind a chapter write.
# With OLLAMA_NUM_PARALLEL=2 set on the Ollama server, both locks can be active
# simultaneously — primary uses dedicated VRAM, secondary uses the 16GB shared pool.
_quick_lock = asyncio.Lock()
_quick_waiting: int = 0


async def call_ollama(
    payload: Dict[str, Any],
    timeout: float = 300.0,
    caller: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """
    Route one Ollama request through the global FIFO lock.

    Args:
        payload:  Full Ollama /api/chat request body (model, messages, options…)
        timeout:  Seconds allowed for Ollama to respond once it starts.
                  Lock wait time is NOT included — callers queue up indefinitely.
        caller:   Short label for log messages (e.g. "news_feed", "npc_lifecycle")
        force:    If True, bypass the busy check (use for internal pipeline calls
                  that already own the busy flag themselves).

    Returns:
        Parsed JSON response dict.

    Raises:
        OllamaBusyError  — a long-running task has called mark_busy(); skip this cycle.
        httpx.ReadTimeout / httpx.HTTPError — Ollama error; caller decides retry logic.
    """
    global _waiting
    import httpx

    tag = f"[{caller}] " if caller else ""

    # If the primary track is locked (pipeline writing a chapter) and this is not
    # a forced pipeline call, route to the secondary track automatically.
    # Requires OLLAMA_NUM_PARALLEL=2 on the Ollama server so both tracks run
    # simultaneously — primary in dedicated VRAM, secondary in 16GB shared pool.
    if not force and _lock.locked():
        logger.info(f"🔀 Primary track busy — routing {tag}to secondary (shared VRAM)")
        quick_timeout = float(os.getenv("OLLAMA_QUICK_TIMEOUT", "300"))
        return await call_ollama_quick(payload, timeout=min(timeout, quick_timeout), caller=caller)

    # Non-forced call when not locked: honour the old busy flag for truly overloaded cases
    # (e.g. nothing running but the queue depth is already maxed).
    global _waiting
    import httpx

    _waiting += 1
    try:
        if _waiting > 1:
            logger.info(f"🔀 Ollama queue {tag}waiting for slot (queue depth={_waiting})")

        async with _lock:
            _waiting -= 1
            if _waiting > 0:
                logger.info(f"🔀 Ollama queue {tag}slot acquired ({_waiting} still waiting)")

            # Auto-inject GPU/context options so every caller gets GPU acceleration
            # without needing to know the env vars.  Callers that already set these
            # in payload["options"] are NOT overwritten.
            if "options" not in payload:
                payload["options"] = {}
            opts = payload["options"]
            # Only inject num_gpu if explicitly non-zero — let Modelfile control GPU split
            _env_gpu = int(os.getenv("OLLAMA_NUM_GPU", "0"))
            if "num_gpu" not in opts and _env_gpu > 0:
                opts["num_gpu"] = _env_gpu
            if "num_ctx" not in opts:
                opts["num_ctx"] = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
            # Ollama requires 'think' at the TOP LEVEL of the request body, not inside options.
            # Callers put it in options for convenience — promote it here so it actually works.
            if "think" in opts:
                payload["think"] = opts.pop("think")

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


async def call_ollama_quick(
    payload: Dict[str, Any],
    timeout: float = 120.0,
    caller: str = "",
) -> Dict[str, Any]:
    """
    Secondary track for quick bot tasks (bulletins, events, NPC lifecycle, weather).

    Uses _quick_lock instead of the primary _lock, so short tasks never queue
    behind a 45-minute chapter write.  With OLLAMA_NUM_PARALLEL=2 set on the
    Ollama server, this runs in parallel with the primary track — primary uses
    dedicated VRAM, secondary uses the 16GB shared memory pool.

    Does NOT check the priority busy flag — quick tasks always go through.
    Falls back to the primary track if the secondary lock is heavily backed up.
    """
    global _quick_waiting
    import httpx

    tag = f"[{caller}] " if caller else ""
    _quick_waiting += 1

    try:
        if _quick_waiting > 3:
            # Secondary track is backed up — skip this cycle rather than pile on
            logger.info(f"🔀 Quick track {tag}backed up (depth={_quick_waiting}) — skipping")
            raise OllamaBusyError(f"quick track depth {_quick_waiting}")

        if _quick_waiting > 1:
            logger.info(f"🔀 Quick track {tag}waiting (depth={_quick_waiting})")

        async with _quick_lock:
            _quick_waiting -= 1

            if "options" not in payload:
                payload["options"] = {}
            opts = payload["options"]
            _env_gpu = int(os.getenv("OLLAMA_NUM_GPU", "0"))
            if "num_gpu" not in opts and _env_gpu > 0:
                opts["num_gpu"] = _env_gpu
            if "num_ctx" not in opts:
                opts["num_ctx"] = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
            if "think" in opts:
                payload["think"] = opts.pop("think")

            logger.info(f"🔀 Quick track {tag}sending (timeout={timeout}s)")
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
        if _quick_waiting > 0:
            _quick_waiting -= 1
        raise
