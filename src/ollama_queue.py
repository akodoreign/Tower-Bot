"""
ollama_queue.py — entry point for Ollama /api/chat requests.

Every request takes a text turn on the shared GPU queue (src/gpu_queue.py),
which runs all GPU work, text and image, one job at a time and in a fair
order. That queue is the only one.

This module used to keep its own primary and quick locks in front of the
GPU queue. Callers held them while waiting for the GPU, so one request queued
behind an image job made every other caller skip ("Ollama primary queue is
busy"), the quick track's depth counter leaked on every skip until it skipped
everything, and a task holding the GPU that asked for a lock could stall
behind a task waiting for the GPU. They are gone.

Usage:
    from src.ollama_queue import call_ollama

    data = await call_ollama(
        payload={"model": model, "messages": [...], "stream": False},
        timeout=300.0,
        caller="news_feed",
    )
    # Returns the parsed JSON dict, or raises on HTTP/timeout error.

The busy flag (src/ollama_busy) is checked by callers and the resource cop,
not here.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

import httpx

from src.gpu_queue import GpuBusyError, normalize_ollama_payload, turn as gpu_turn

# A child of src.log so these lines reach the bot's log handler.
logger = logging.getLogger("src.log.ollama_queue")


class OllamaBusyError(RuntimeError):
    """The request could not get a GPU turn in time; callers skip this cycle."""


def _prepare(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in GPU/context defaults (callers' own options win) and fix the think switch."""
    opts = payload.setdefault("options", {})
    env_gpu = int(os.getenv("OLLAMA_NUM_GPU", "0"))
    if "num_gpu" not in opts and env_gpu > 0:
        opts["num_gpu"] = env_gpu
    if "num_ctx" not in opts:
        opts["num_ctx"] = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    return normalize_ollama_payload(payload)


async def call_ollama(
    payload: Dict[str, Any],
    timeout: float = 300.0,
    caller: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """
    Send one Ollama request in its turn on the GPU queue.

    Args:
        payload:  Full Ollama /api/chat request body (model, messages, options…)
        timeout:  Seconds allowed for Ollama to respond once the request is sent.
                  Waiting for the GPU turn is not included.
        caller:   Short label for log messages (e.g. "news_feed", "npc_lifecycle")
        force:    Kept for existing callers; the busy flag is checked before this.

    Raises:
        OllamaBusyError  — no GPU turn within GPU_TURN_MAX_WAIT; skip this cycle.
        httpx.ReadTimeout / httpx.HTTPError — Ollama error; caller decides retry logic.
    """
    _prepare(payload)
    try:
        async with gpu_turn("text", caller or "ollama"):
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat"),
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
    except GpuBusyError as exc:
        logger.warning(f"🔀 [{caller or 'ollama'}] skipped: {exc}")
        raise OllamaBusyError(str(exc)) from exc


async def call_ollama_quick(
    payload: Dict[str, Any],
    timeout: float = 120.0,
    caller: str = "",
) -> Dict[str, Any]:
    """Same as call_ollama with a shorter default timeout (bulletins, events, weather)."""
    return await call_ollama(payload, timeout=timeout, caller=caller)
