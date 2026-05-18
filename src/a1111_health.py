"""A1111 health escalation for repeated empty image cycles."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

import httpx

from src.log import logger

_failure_counts: dict[str, int] = {}
_last_alert_at: dict[str, float] = {}


def _threshold() -> int:
    return max(1, int(os.getenv("A1111_NO_IMAGE_ALERT_THRESHOLD", "5")))


def _alert_cooldown_seconds() -> float:
    return max(60.0, float(os.getenv("A1111_NO_IMAGE_ALERT_COOLDOWN", "3600")))


def _buglog_enabled() -> bool:
    return os.getenv("A1111_NO_IMAGE_BUGLOG_ENABLED", "1").lower() not in {"0", "false", "no"}


def _a1111_url(url: str | None = None) -> str:
    return (url or os.getenv("A1111_URL", "http://127.0.0.1:7860")).split()[0].rstrip("/")


def _append_buglog_alert(label: str, count: int, reason: str) -> None:
    if not _buglog_enabled():
        return
    repo_root = Path(__file__).resolve().parent.parent
    buglog = repo_root / "buglog.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = (
        "\n"
        f"### {stamp} - A1111 repeated no-image alert\n\n"
        "Status: open.\n\n"
        "Context:\n"
        f"- Label: `{label}`\n"
        f"- Consecutive failures: `{count}`\n"
        f"- Last reason: `{reason}`\n\n"
        "Action taken:\n"
        "- Bot logged this at ERROR level and attempted `/sdapi/v1/interrupt`.\n\n"
        "Next action:\n"
        "- Inspect A1111 logs and bot logs around this timestamp.\n"
        "- If failures continue after interrupt, restart A1111 before changing prompts or VAE/model settings.\n"
    )
    try:
        with buglog.open("a", encoding="utf-8") as fh:
            fh.write(text)
    except Exception as exc:
        logger.warning("[A1111_HEALTH] Could not append alert to buglog.md: %r", exc)


async def _interrupt_a1111(label: str, url: str | None = None) -> None:
    base = _a1111_url(url)
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("A1111_INTERRUPT_TIMEOUT", "10"))) as client:
            response = await client.post(f"{base}/sdapi/v1/interrupt")
        if response.status_code >= 400:
            logger.error("[A1111_HEALTH] Interrupt for %s returned HTTP %s", label, response.status_code)
        else:
            logger.error("[A1111_HEALTH] Interrupt sent for %s after repeated no-image failures", label)
    except Exception as exc:
        logger.error("[A1111_HEALTH] Interrupt failed for %s: %r", label, exc)


async def record_a1111_success(label: str) -> None:
    previous = _failure_counts.pop(label, 0)
    if previous:
        logger.info("[A1111_HEALTH] %s recovered after %d consecutive failure(s)", label, previous)


async def record_a1111_failure(label: str, reason: str, *, url: str | None = None) -> int:
    count = _failure_counts.get(label, 0) + 1
    _failure_counts[label] = count

    threshold = _threshold()
    if count < threshold:
        return count

    now = time.monotonic()
    last_alert = _last_alert_at.get(label, 0.0)
    if last_alert and now - last_alert < _alert_cooldown_seconds():
        return count

    _last_alert_at[label] = now
    logger.error(
        "[A1111_HEALTH] %s has failed to produce images %d consecutive time(s); last reason: %s",
        label,
        count,
        reason,
    )
    await _interrupt_a1111(label, url=url)
    await asyncio.to_thread(_append_buglog_alert, label, count, reason)
    return count


def _reset_for_tests() -> None:
    _failure_counts.clear()
    _last_alert_at.clear()
