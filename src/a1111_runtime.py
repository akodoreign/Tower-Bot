"""Shared A1111 runtime helpers for model switching and cooldowns."""

from __future__ import annotations

import asyncio
import os

import httpx

from src.log import logger
from src.mission_builder.vtt_renderer import (
    A1111_COOLDOWN_SECONDS,
    A1111_MODEL_SWAP_COOLDOWN,
    wait_for_a1111_idle,
)

A1111_OPTIONS_GET_TIMEOUT = float(os.getenv("A1111_OPTIONS_GET_TIMEOUT", "10"))
A1111_MODEL_SWITCH_TIMEOUT = float(os.getenv("A1111_MODEL_SWITCH_TIMEOUT", "180"))


async def ensure_a1111_model(model: str, *, label: str = "A1111", url: str | None = None) -> bool:
    """Ensure A1111 is idle and using `model`.

    Call this while holding the shared A1111 lock when the next operation is
    image generation. This keeps model switch plus generation atomic.
    """
    if not model:
        await asyncio.to_thread(wait_for_a1111_idle, cooldown=A1111_COOLDOWN_SECONDS)
        return True

    a1111_url = (url or os.getenv("A1111_URL", "http://127.0.0.1:7860")).split()[0]
    await asyncio.to_thread(wait_for_a1111_idle, cooldown=A1111_COOLDOWN_SECONDS)

    try:
        async with httpx.AsyncClient(timeout=A1111_OPTIONS_GET_TIMEOUT) as client:
            opts = await client.get(f"{a1111_url}/sdapi/v1/options")
            opts.raise_for_status()
            current = str(opts.json().get("sd_model_checkpoint") or "")
        if model not in current:
            async with httpx.AsyncClient(timeout=A1111_MODEL_SWITCH_TIMEOUT) as client:
                resp = await client.post(
                    f"{a1111_url}/sdapi/v1/options",
                    json={"sd_model_checkpoint": model},
                )
                resp.raise_for_status()
            logger.info("[%s] A1111 model switched to: %s", label, model)
            await asyncio.to_thread(wait_for_a1111_idle, cooldown=A1111_MODEL_SWAP_COOLDOWN)
        return True
    except Exception as exc:
        logger.warning("[%s] A1111 model switch failed: %r", label, exc)
        return False


async def cool_down_a1111_after_generation(*, cooldown: float = 45) -> None:
    """Wait for A1111 to fully settle after an image generation request."""
    await asyncio.to_thread(wait_for_a1111_idle, cooldown=max(A1111_COOLDOWN_SECONDS, cooldown))
