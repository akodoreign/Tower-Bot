"""Soft resource scheduler for shared local AI services.

The cop does not hold long locks. It answers "can I run now?" with either a
RUN_NOW decision or a short wait recommendation so callers can back off and
ask again later.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx

ResourceName = Literal["a1111", "ollama"]
logger = logging.getLogger(__name__)

_pipeline_lock = threading.RLock()
_active_pipelines: dict[str, "PipelineRun"] = {}


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(frozen=True)
class ResourceDecision:
    resource: ResourceName
    label: str
    run_now: bool
    wait_seconds: float = 0.0
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls, resource: ResourceName, label: str, reason: str = "idle", **details: Any) -> "ResourceDecision":
        return cls(resource=resource, label=label, run_now=True, reason=reason, details=details)

    @classmethod
    def wait(
        cls,
        resource: ResourceName,
        label: str,
        wait_seconds: float,
        reason: str,
        **details: Any,
    ) -> "ResourceDecision":
        return cls(
            resource=resource,
            label=label,
            run_now=False,
            wait_seconds=max(1.0, float(wait_seconds)),
            reason=reason,
            details=details,
        )


@dataclass(frozen=True)
class PipelineRun:
    run_id: str
    label: str
    started_at: float
    mission_title: str = ""
    mission_type: str = ""
    phase: str = "started"
    details: dict[str, Any] = field(default_factory=dict)

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.monotonic() if now is None else now
        return {
            "run_id": self.run_id,
            "label": self.label,
            "mission_title": self.mission_title,
            "mission_type": self.mission_type,
            "phase": self.phase,
            "elapsed_seconds": max(0.0, current - self.started_at),
            "details": dict(self.details),
        }


async def start_pipeline(
    label: str,
    *,
    mission_title: str = "",
    mission_type: str = "",
    phase: str = "started",
    **details: Any,
) -> PipelineRun:
    """Record a whole-pipeline lifecycle span for scheduler visibility."""
    run = PipelineRun(
        run_id=uuid.uuid4().hex[:12],
        label=label,
        started_at=time.monotonic(),
        mission_title=mission_title or "",
        mission_type=mission_type or "",
        phase=phase,
        details={k: v for k, v in details.items() if v not in (None, "")},
    )
    with _pipeline_lock:
        _active_pipelines[run.run_id] = run
    logger.info(
        "[resource-cop] pipeline started: %s %s (%s)",
        label,
        mission_title or "",
        mission_type or "",
    )
    return run


async def set_pipeline_phase(run_id: str, phase: str, **details: Any) -> None:
    """Update a running pipeline's current phase/details."""
    with _pipeline_lock:
        run = _active_pipelines.get(run_id)
        if not run:
            return
        merged = dict(run.details)
        merged.update({k: v for k, v in details.items() if v not in (None, "")})
        _active_pipelines[run_id] = PipelineRun(
            run_id=run.run_id,
            label=run.label,
            started_at=run.started_at,
            mission_title=run.mission_title,
            mission_type=run.mission_type,
            phase=phase,
            details=merged,
        )


async def finish_pipeline(run_id: str, *, status: str = "finished") -> None:
    """Remove a running pipeline from the active registry."""
    with _pipeline_lock:
        run = _active_pipelines.pop(run_id, None)
    if run:
        elapsed = time.monotonic() - run.started_at
        log = logger.warning if status not in {"finished", "cancelled"} else logger.info
        log(
            "[resource-cop] pipeline %s: %s %s after %.1fs",
            status,
            run.label,
            run.mission_title or "",
            elapsed,
        )


async def append_pipeline_failure(run_id: str, exc: BaseException) -> None:
    """Append a concise failure breadcrumb to buglog.md for later diagnosis."""
    with _pipeline_lock:
        run = _active_pipelines.get(run_id)
    if not run:
        return

    elapsed = time.monotonic() - run.started_at
    repo_root = Path(__file__).resolve().parent.parent
    buglog = repo_root / "buglog.md"
    title = run.mission_title or "Untitled Mission"
    mission_type = run.mission_type or "unknown"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = (
        "\n"
        f"### {stamp} - Resource cop captured mission pipeline failure\n\n"
        "Status: open.\n\n"
        "Context:\n"
        f"- Pipeline: `{run.label}`\n"
        f"- Mission: `{title}`\n"
        f"- Type: `{mission_type}`\n"
        f"- Phase: `{run.phase}`\n"
        f"- Elapsed: `{elapsed:.1f}s`\n"
        f"- Error: `{type(exc).__name__}: {exc}`\n\n"
        "Next action:\n"
        "- Inspect the bot logs around this timestamp and the generated module directory, if one was created.\n"
        "- Reproduce through the same mission type before patching.\n"
    )
    try:
        with buglog.open("a", encoding="utf-8") as fh:
            fh.write(text)
    except Exception as write_exc:
        logger.warning("[resource-cop] could not append pipeline failure to buglog.md: %r", write_exc)


async def active_pipelines() -> list[dict[str, Any]]:
    """Return snapshots of whole pipelines currently in progress."""
    return active_pipelines_sync()


def active_pipelines_sync() -> list[dict[str, Any]]:
    """Synchronous snapshot for Flask/status routes."""
    with _pipeline_lock:
        runs = list(_active_pipelines.values())
    now = time.monotonic()
    return [run.snapshot(now=now) for run in runs]


def _a1111_url() -> str:
    return os.getenv("A1111_URL", "http://127.0.0.1:7860").split()[0].rstrip("/")


def _ollama_base_url() -> str:
    raw = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    return raw.split("/api/")[0].split("/v1")[0].rstrip("/")


def _existing_a1111_lock_busy() -> bool:
    try:
        from src.news_feed import a1111_lock

        return bool(a1111_lock.locked())
    except Exception:
        return False


def _ollama_queue_snapshot() -> dict[str, Any]:
    try:
        import src.ollama_queue as oq

        return {
            "primary_locked": bool(oq._lock.locked()),
            "quick_locked": bool(oq._quick_lock.locked()),
            "primary_waiting": int(getattr(oq, "_waiting", 0)),
            "quick_waiting": int(getattr(oq, "_quick_waiting", 0)),
        }
    except Exception:
        return {
            "primary_locked": False,
            "quick_locked": False,
            "primary_waiting": 0,
            "quick_waiting": 0,
        }


async def ask_a1111(label: str, *, model_hint: str | None = None, url: str | None = None) -> ResourceDecision:
    """Return whether A1111 appears safe for a new image/model-switch request."""
    if _existing_a1111_lock_busy():
        return ResourceDecision.wait("a1111", label, 10, "legacy A1111 lock is busy", model_hint=model_hint or "")

    base = (url or _a1111_url()).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("RESOURCE_COP_A1111_TIMEOUT", "3"))) as client:
            resp = await client.get(f"{base}/sdapi/v1/progress?skip_current_image=true")
            await _maybe_await(resp.raise_for_status())
            data = await _maybe_await(resp.json())
    except Exception as exc:
        return ResourceDecision.wait("a1111", label, 10, "A1111 progress probe failed", error=repr(exc))

    if not isinstance(data, dict):
        return ResourceDecision.allow(
            "a1111",
            label,
            "A1111 progress probe returned non-dict",
            model_hint=model_hint or "",
        )

    progress = float(data.get("progress") or 0.0)
    state = data.get("state") or {}
    job_count = int(state.get("job_count") or 0)
    job_no = int(state.get("job_no") or 0)
    sampling_step = int(state.get("sampling_step") or 0)
    busy = progress > 0.0 or sampling_step > 0 or (job_count > 0 and job_no < job_count)
    details = {
        "progress": progress,
        "job_count": job_count,
        "job_no": job_no,
        "sampling_step": sampling_step,
        "model_hint": model_hint or "",
    }
    if busy:
        wait = float(os.getenv("RESOURCE_COP_A1111_WAIT", "10"))
        return ResourceDecision.wait("a1111", label, wait, "A1111 reports active generation", **details)
    return ResourceDecision.allow("a1111", label, "A1111 idle", **details)


def ask_a1111_sync(label: str, *, model_hint: str | None = None, url: str | None = None) -> ResourceDecision:
    """Synchronous A1111 check for non-async paths such as pretty-map finalizers."""
    if _existing_a1111_lock_busy():
        return ResourceDecision.wait("a1111", label, 10, "legacy A1111 lock is busy", model_hint=model_hint or "")

    base = (url or _a1111_url()).rstrip("/")
    try:
        with httpx.Client(timeout=float(os.getenv("RESOURCE_COP_A1111_TIMEOUT", "3"))) as client:
            resp = client.get(f"{base}/sdapi/v1/progress?skip_current_image=true")
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return ResourceDecision.wait("a1111", label, 10, "A1111 progress probe failed", error=repr(exc))

    progress = float(data.get("progress") or 0.0)
    state = data.get("state") or {}
    job_count = int(state.get("job_count") or 0)
    job_no = int(state.get("job_no") or 0)
    sampling_step = int(state.get("sampling_step") or 0)
    busy = progress > 0.0 or sampling_step > 0 or (job_count > 0 and job_no < job_count)
    details = {
        "progress": progress,
        "job_count": job_count,
        "job_no": job_no,
        "sampling_step": sampling_step,
        "model_hint": model_hint or "",
    }
    if busy:
        wait = float(os.getenv("RESOURCE_COP_A1111_WAIT", "10"))
        return ResourceDecision.wait("a1111", label, wait, "A1111 reports active generation", **details)
    return ResourceDecision.allow("a1111", label, "A1111 idle", **details)


async def wait_for_a1111_turn(
    label: str,
    *,
    model_hint: str | None = None,
    url: str | None = None,
    max_wait_seconds: float | None = None,
) -> ResourceDecision:
    """Poll `ask_a1111` until it allows a request or the wait budget is exhausted."""
    max_wait = float(os.getenv("RESOURCE_COP_A1111_MAX_WAIT", "300")) if max_wait_seconds is None else max_wait_seconds
    deadline = asyncio.get_running_loop().time() + max_wait
    last = await ask_a1111(label, model_hint=model_hint, url=url)
    while not last.run_now:
        now = asyncio.get_running_loop().time()
        if now >= deadline:
            return last
        sleep_for = min(last.wait_seconds, max(1.0, deadline - now))
        logger.info(
            "[resource-cop] %s waiting %.0fs for A1111: %s",
            label,
            sleep_for,
            last.reason,
        )
        await asyncio.sleep(sleep_for)
        last = await ask_a1111(label, model_hint=model_hint, url=url)
    return last


async def ask_ollama(label: str, *, track: Literal["primary", "quick"] = "primary") -> ResourceDecision:
    """Return whether Ollama appears safe for a new generation request."""
    try:
        from src.ollama_busy import get_busy_reason, is_available

        if not is_available():
            return ResourceDecision.wait(
                "ollama",
                label,
                float(os.getenv("RESOURCE_COP_OLLAMA_BUSY_WAIT", "30")),
                "Ollama priority busy flag is active",
                busy_reason=get_busy_reason(),
            )
    except Exception:
        pass

    queue = _ollama_queue_snapshot()
    if track == "primary" and queue["primary_locked"]:
        return ResourceDecision.wait("ollama", label, 10, "Ollama primary queue is busy", **queue)
    if track == "quick" and queue["quick_waiting"] >= 3:
        return ResourceDecision.wait("ollama", label, 20, "Ollama quick queue is backed up", **queue)

    base = _ollama_base_url()
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("RESOURCE_COP_OLLAMA_TIMEOUT", "3"))) as client:
            resp = await client.get(f"{base}/api/ps")
            await _maybe_await(resp.raise_for_status())
            data = await _maybe_await(resp.json())
    except Exception as exc:
        return ResourceDecision.wait("ollama", label, 10, "Ollama ps probe failed", error=repr(exc), **queue)

    if not isinstance(data, dict):
        return ResourceDecision.allow("ollama", label, "Ollama ps probe returned non-dict", **queue)

    models = data.get("models") or []
    return ResourceDecision.allow("ollama", label, "Ollama reachable", loaded_models=len(models), **queue)


async def wait_for_ollama_turn(
    label: str,
    *,
    track: Literal["primary", "quick"] = "primary",
    max_wait_seconds: float | None = None,
) -> ResourceDecision:
    """Poll `ask_ollama` until it allows a request or the wait budget is exhausted."""
    max_wait = float(os.getenv("RESOURCE_COP_OLLAMA_MAX_WAIT", "300")) if max_wait_seconds is None else max_wait_seconds
    deadline = asyncio.get_running_loop().time() + max_wait
    last = await ask_ollama(label, track=track)
    while not last.run_now:
        now = asyncio.get_running_loop().time()
        if now >= deadline:
            return last
        sleep_for = min(last.wait_seconds, max(1.0, deadline - now))
        logger.info(
            "[resource-cop] %s waiting %.0fs for Ollama: %s",
            label,
            sleep_for,
            last.reason,
        )
        await asyncio.sleep(sleep_for)
        last = await ask_ollama(label, track=track)
    return last
