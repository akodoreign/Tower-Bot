"""
gpu_queue.py — one GPU, one job at a time.

The bot shares a single 12 GB card between Ollama (text) and ComfyUI (images).
Every GPU request takes a turn here first, and turns run one at a time. When
the turn changes kind the other backend is told to free its VRAM: switching
to an image job unloads Ollama's models, switching to a text job asks ComfyUI
to drop its models.

Switching costs real time (reloading the text model takes ~20 s), so when a
turn ends the next one goes to the oldest waiter of the kind already loaded.
Anyone who has waited longer than GPU_TURN_STARVE_SECONDS goes first, so the
other kind is never starved.

Turns are re-entrant for the task that holds them (and for tasks it spawns
while holding), so a pipeline that holds an image turn can still ask Ollama
for a prompt without deadlocking on itself.

Usage:
    from src.gpu_queue import turn, text_post

    async with turn("image", "npc_portrait"):
        ...

    r = await text_post(client, OLLAMA_URL, json=payload)   # drop-in for client.post
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal, Optional

import httpx

logger = logging.getLogger(__name__)

Kind = Literal["text", "image"]


class GpuBusyError(TimeoutError):
    """Raised when a caller waited longer than GPU_TURN_MAX_WAIT for its turn."""


@dataclass
class _Waiter:
    kind: Kind
    label: str
    since: float
    granted: asyncio.Future


_busy = False
_waiters: list[_Waiter] = []
_owner: Optional[object] = None          # token of the turn currently running
_held = contextvars.ContextVar("gpu_turn_token", default=None)
_current_kind: Optional[Kind] = None     # what is (probably) resident in VRAM
_current_label = ""
_turn_started = 0.0
_loop: Optional[asyncio.AbstractEventLoop] = None


def _max_wait() -> float:
    return float(os.getenv("GPU_TURN_MAX_WAIT", "1800"))


def _starve_seconds() -> float:
    return float(os.getenv("GPU_TURN_STARVE_SECONDS", "180"))


def _ollama_base() -> str:
    raw = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    return raw.split("/api/")[0].split("/v1")[0].rstrip("/")


def _comfy_base() -> str:
    return os.getenv("COMFY_URL", "http://127.0.0.1:8188").split()[0].rstrip("/")


def register_loop(loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    """Remember the bot's event loop so worker threads can submit GPU work to it."""
    global _loop
    _loop = loop or asyncio.get_running_loop()


def main_loop() -> Optional[asyncio.AbstractEventLoop]:
    return _loop if _loop is not None and _loop.is_running() else None


def holds_turn() -> bool:
    token = _held.get()
    return token is not None and token is _owner


def locked() -> bool:
    return _busy


def snapshot() -> dict[str, Any]:
    return {
        "busy": _busy,
        "kind": _current_kind,
        "label": _current_label,
        "running_for": round(time.monotonic() - _turn_started, 1) if _busy else 0.0,
        "waiting": len(_waiters),
        "waiting_text": sum(1 for w in _waiters if w.kind == "text"),
        "waiting_image": sum(1 for w in _waiters if w.kind == "image"),
    }


def _pick_next() -> Optional[_Waiter]:
    if not _waiters:
        return None
    now = time.monotonic()
    starving = [w for w in _waiters if now - w.since >= _starve_seconds()]
    if starving:
        return starving[0]
    same_kind = [w for w in _waiters if w.kind == _current_kind]
    return same_kind[0] if same_kind else _waiters[0]


def _release() -> None:
    """Hand the GPU straight to the next waiter, or mark it free."""
    global _busy
    nxt = _pick_next()
    if nxt is None:
        _busy = False
        return
    _waiters.remove(nxt)
    nxt.granted.set_result(None)       # _busy stays True: ownership passes directly


async def _acquire(kind: Kind, label: str) -> None:
    global _busy
    if not _busy and not _waiters:
        _busy = True
        return
    logger.info("🎛️ GPU: %s [%s] waiting behind %s [%s] (%d queued)",
                kind, label, _current_kind, _current_label, len(_waiters))
    waiter = _Waiter(kind, label, time.monotonic(), asyncio.get_running_loop().create_future())
    _waiters.append(waiter)
    try:
        done, _ = await asyncio.wait({waiter.granted}, timeout=_max_wait())
    except asyncio.CancelledError:
        if waiter.granted.done():
            _release()                 # granted just as we were cancelled: pass it on
        else:
            _waiters.remove(waiter)
        raise
    if not done:
        _waiters.remove(waiter)
        raise GpuBusyError(f"GPU busy with {_current_kind} [{_current_label}] for over {_max_wait():.0f}s")


async def _unload_ollama() -> None:
    base = _ollama_base()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            loaded = (await client.get(f"{base}/api/ps")).json().get("models") or []
            for model in loaded:
                name = model.get("name") or model.get("model")
                if name:
                    await client.post(f"{base}/api/generate", json={"model": name, "keep_alive": 0})
        if loaded:
            logger.info("🎛️ GPU: unloaded %d Ollama model(s) for an image job", len(loaded))
    except Exception as exc:
        logger.warning("🎛️ GPU: could not unload Ollama: %r", exc)


async def _comfy_vram_free(client: httpx.AsyncClient) -> float:
    devices = (await client.get(f"{_comfy_base()}/system_stats")).json().get("devices") or [{}]
    return float(devices[0].get("vram_free") or 0.0)


async def _free_comfy() -> None:
    # /free only sets a flag that ComfyUI's worker acts on between jobs, so
    # wait until the memory is actually back before letting Ollama load.
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            before = await _comfy_vram_free(client)
            await client.post(f"{_comfy_base()}/free", json={"unload_models": True, "free_memory": True})
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                if await _comfy_vram_free(client) > before + 512 * 2**20:
                    break
        logger.info("🎛️ GPU: freed ComfyUI VRAM for a text job")
    except Exception as exc:
        logger.warning("🎛️ GPU: could not free ComfyUI: %r", exc)


async def _switch_to(kind: Kind) -> None:
    global _current_kind
    if kind == _current_kind:
        return
    if kind == "image":
        await _unload_ollama()
    else:
        await _free_comfy()
    _current_kind = kind


@asynccontextmanager
async def turn(kind: Kind, label: str = "") -> AsyncIterator[None]:
    """Hold the GPU for one text or image job."""
    global _owner, _current_label, _turn_started

    if holds_turn():
        # Nested request from the task that already holds the GPU.
        await _switch_to(kind)
        yield
        return

    t0 = time.monotonic()
    await _acquire(kind, label)

    token = object()
    _owner = token
    ctx_token = _held.set(token)
    _current_label = label
    _turn_started = time.monotonic()
    waited = _turn_started - t0
    if waited > 5:
        logger.info("🎛️ GPU: %s [%s] started after waiting %.0fs", kind, label, waited)
    try:
        await _switch_to(kind)
        yield
    finally:
        try:
            _held.reset(ctx_token)
        except ValueError:
            pass  # exited from a different context (cancellation); the owner check covers it
        _owner = None
        _current_label = ""
        _release()


def _think_allowance() -> int:
    return int(os.getenv("OLLAMA_THINK_TOKENS", "1536"))


def normalize_ollama_payload(payload: Any) -> Any:
    """Make the thinking switch mean what the caller wrote.

    Ollama reads ``think`` only at the top level of a request; inside
    ``options`` it is silently ignored and a thinking model (qwen3.6) thinks
    anyway. Many callers put it in options, so promote it. A request that
    says nothing gets ``think: false`` -- every prompt here was written for a
    model that answered straight away. When thinking is on, num_predict is
    raised by OLLAMA_THINK_TOKENS, because Ollama counts thinking against it
    and a short budget would otherwise end before the answer starts.
    """
    if not isinstance(payload, dict) or "messages" not in payload and "prompt" not in payload:
        return payload
    opts = payload.get("options")
    if isinstance(opts, dict) and "think" in opts:
        payload.setdefault("think", opts.pop("think"))
    payload.setdefault("think", False)
    if payload["think"] and isinstance(opts, dict) and opts.get("num_predict", -1) > 0:
        opts["num_predict"] += _think_allowance()
    return payload


async def text_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
    """Drop-in for ``client.post(url, ...)`` on Ollama requests: runs inside a text turn."""
    if "json" in kwargs:
        kwargs["json"] = normalize_ollama_payload(kwargs["json"])
    async with turn("text", "ollama"):
        return await client.post(url, **kwargs)
