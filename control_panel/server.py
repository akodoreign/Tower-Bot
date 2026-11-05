"""
Tower Control: an always-on page to start/stop the bot and open Prompt Studio.

The dashboard lives inside the bot (port 5001), so it goes down with it. This
small server runs as its own service (TowerControl, LocalSystem, auto start)
and stays up while the bot sleeps between sessions:

    GET  /                      the control page
    GET  /api/status            services, ComfyUI, Ollama, GPU power, auto-stop
    POST /api/bot/start         {"hours": n} optional: stop again after n hours
    POST /api/bot/stop
    POST /api/bot/restart
    POST /api/gpu/free          unload Ollama models, ask ComfyUI to free VRAM
    GET  /studio, /ws, POST /studio/hold
                                Prompt Studio, passed through to ComfyUI
                                (only the routes the page uses; the rest of
                                ComfyUI stays on 127.0.0.1)

Home network only: loopback and 192.168.0.0/16 (CONTROL_TRUSTED_NETS), never
the Cloudflare tunnel. Writes and the websocket must come from this page's own
origin, and the Host must be an IP, localhost or this PC's name (no DNS
rebinding). Prompt Studio prompts are never logged.

Run: .venv\\Scripts\\python.exe control_panel\\server.py
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import web

HERE = Path(__file__).resolve().parent
PORT = int(os.getenv("CONTROL_PORT", "5050"))
COMFY_URL = os.getenv("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
OLLAMA_URL = os.getenv("CONTROL_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DASHBOARD_URL = "http://127.0.0.1:" + os.getenv("DASHBOARD_PORT", "5001")
BOT_SERVICE = "TowerBotService"
WATCHED_SERVICES = (BOT_SERVICE, "TowerTunnel", "MySQL96")
STATE_FILE = HERE / "state.json"            # auto-stop deadline survives a restart
SERVICE_WAIT = 90                           # seconds to wait for stop/start

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tower_control")


# ---------------------------------------------------------------------------
# Who may use it
# ---------------------------------------------------------------------------

def _trusted_nets() -> list:
    raw = os.getenv("CONTROL_TRUSTED_NETS", "192.168.0.0/16")
    nets = [ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128")]
    nets += [ipaddress.ip_network(n.strip(), strict=False) for n in raw.split(",") if n.strip()]
    return nets


def _client_ip(request: web.Request) -> str:
    return request.remote or ""


def _trusted(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _trusted_nets())


def _host_names() -> set:
    pc = socket.gethostname().lower()
    extra = {h.strip().lower() for h in os.getenv("CONTROL_HOSTNAMES", "towerbot").split(",") if h.strip()}
    return {"localhost", pc, pc + ".local"} | extra


def _host_ok(host_header: str) -> bool:
    """An IP literal, localhost, or this PC's name. A domain name pointing at us
    (DNS rebinding) is refused, so other websites can't read this page."""
    host = (host_header or "").strip().lower()
    if host.startswith("["):                                 # [::1]:5050
        host = host[1:].split("]")[0]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return host in _host_names()


def _same_origin(request: web.Request) -> bool:
    origin = (request.headers.get("Origin") or "").rstrip("/").lower()
    return origin == f"http://{request.host}".lower()


@web.middleware
async def guard(request: web.Request, handler):
    if request.headers.get("CF-Ray") or request.headers.get("CF-Connecting-IP"):
        return web.Response(status=403, text="Tower Control is home-network only.")
    if not _trusted(_client_ip(request)):
        return web.Response(status=403, text="Tower Control is home-network only.")
    if not _host_ok(request.host):
        return web.Response(status=403, text="Unexpected Host.")
    unsafe = request.method not in ("GET", "HEAD", "OPTIONS")
    if (unsafe or request.path == "/ws") and not _same_origin(request):
        return web.Response(status=403, text="Cross-site request refused.")
    return await handler(request)


# ---------------------------------------------------------------------------
# Windows services (sc.exe; the service account is LocalSystem)
# ---------------------------------------------------------------------------

_STATES = {"1": "stopped", "2": "starting", "3": "stopping", "4": "running"}


def _sc(*args: str) -> str:
    r = subprocess.run(["sc.exe", *args], capture_output=True, text=True, timeout=30)
    return (r.stdout or "") + (r.stderr or "")


def service_state(name: str) -> str:
    out = _sc("query", name)
    for line in out.splitlines():
        if "STATE" in line and ":" in line:
            code = line.split(":", 1)[1].strip().split()[0]
            return _STATES.get(code, "unknown")
    return "missing" if "1060" in out else "unknown"


async def _wait_for(name: str, want: str, timeout: float = SERVICE_WAIT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await asyncio.to_thread(service_state, name) == want:
            return True
        await asyncio.sleep(1)
    return False


_action_lock = asyncio.Lock()
_last_action = {"action": "", "result": "", "at": 0.0}


async def _run_action(action: str) -> None:
    async with _action_lock:
        ok = True
        if action in ("stop", "restart"):
            await asyncio.to_thread(_sc, "stop", BOT_SERVICE)
            ok = await _wait_for(BOT_SERVICE, "stopped")
        if ok and action in ("start", "restart"):
            await asyncio.to_thread(_sc, "start", BOT_SERVICE)     # starts MySQL96 + TowerTunnel too
            ok = await _wait_for(BOT_SERVICE, "running")
        result = "done" if ok else "timed out"
        _last_action.update(action=action, result=result, at=time.time())
        log.info("bot %s: %s", action, result)


# ---------------------------------------------------------------------------
# Auto-stop ("start for N hours")
# ---------------------------------------------------------------------------

def _load_deadline() -> Optional[float]:
    try:
        return float(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("auto_stop_at") or 0) or None
    except (OSError, ValueError):
        return None


def _save_deadline(at: Optional[float]) -> None:
    STATE_FILE.write_text(json.dumps({"auto_stop_at": at}), encoding="utf-8")


async def auto_stop_loop() -> None:
    while True:
        await asyncio.sleep(30)
        at = _load_deadline()
        if at and time.time() >= at:
            _save_deadline(None)
            if await asyncio.to_thread(service_state, BOT_SERVICE) != "stopped":
                log.info("auto-stop: session time is up, stopping the bot")
                await _run_action("stop")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def gpu_status() -> dict:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,power.draw,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        name, watts, used, total, util = [p.strip() for p in r.stdout.strip().split(",")]
        return {"name": name, "watts": float(watts), "mem_used_mb": int(float(used)),
                "mem_total_mb": int(float(total)), "util": int(float(util))}
    except Exception:
        return {}


async def _up(session: aiohttp.ClientSession, url: str) -> bool:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
            return r.status < 500
    except Exception:
        return False


async def status(request: web.Request) -> web.Response:
    services = {}
    for name in WATCHED_SERVICES:
        services[name] = await asyncio.to_thread(service_state, name)
    async with aiohttp.ClientSession() as s:
        comfy, ollama, dash = await asyncio.gather(
            _up(s, f"{COMFY_URL}/system_stats"), _up(s, f"{OLLAMA_URL}/api/version"),
            _up(s, f"{DASHBOARD_URL}/api/view-mode"))
    return web.json_response({
        "services": services,
        "comfyui": comfy,
        "ollama": ollama,
        "dashboard": dash,
        "gpu": await asyncio.to_thread(gpu_status),
        "auto_stop_at": _load_deadline(),
        "busy": _action_lock.locked(),
        "last_action": _last_action,
        "now": time.time(),
    })


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

async def bot_action(request: web.Request) -> web.Response:
    action = request.match_info["action"]
    if action not in ("start", "stop", "restart"):
        raise web.HTTPNotFound()
    if _action_lock.locked():
        return web.json_response({"ok": False, "error": "Another start/stop is still running."}, status=409)
    body = {}
    if request.can_read_body:
        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            body = {}
    if action == "stop":
        _save_deadline(None)
    elif action == "start":
        try:
            hours = float(body.get("hours") or 0)
        except (TypeError, ValueError):
            hours = 0
        _save_deadline(time.time() + hours * 3600 if 0 < hours <= 48 else None)
    asyncio.get_running_loop().create_task(_run_action(action))
    return web.json_response({"ok": True, "action": action})


async def free_gpu(request: web.Request) -> web.Response:
    freed = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        try:
            async with s.get(f"{OLLAMA_URL}/api/ps") as r:
                models = (await r.json()).get("models") or []
            for m in models:
                name = m.get("name") or m.get("model")
                if name:
                    async with s.post(f"{OLLAMA_URL}/api/generate", json={"model": name, "keep_alive": 0}):
                        freed.append(f"Ollama: {name}")
        except Exception as exc:
            log.warning("free gpu: ollama: %r", exc)
        try:
            async with s.post(f"{COMFY_URL}/free", json={"unload_models": True, "free_memory": True}):
                freed.append("ComfyUI models")
        except Exception as exc:
            log.warning("free gpu: comfyui: %r", exc)
    return web.json_response({"ok": True, "freed": freed})


# ---------------------------------------------------------------------------
# Prompt Studio passthrough (never logs prompts)
# ---------------------------------------------------------------------------

async def studio_page(request: web.Request) -> web.Response:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{COMFY_URL}/studio", timeout=aiohttp.ClientTimeout(total=10)) as r:
                return web.Response(body=await r.read(), status=r.status,
                                    content_type=r.content_type or "text/html")
    except Exception:
        return web.Response(status=502, text="ComfyUI is not running.")


async def studio_hold(request: web.Request) -> web.Response:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{COMFY_URL}/studio/hold", data=await request.read(),
                              headers={"Content-Type": "application/json"},
                              timeout=aiohttp.ClientTimeout(total=60)) as r:
                return web.Response(body=await r.read(), status=r.status, content_type="application/json")
    except Exception:
        return web.json_response({"error": {"message": "ComfyUI is not running."}}, status=502)


async def studio_ws(request: web.Request) -> web.WebSocketResponse:
    client = web.WebSocketResponse(max_msg_size=0)
    await client.prepare(request)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(f"{COMFY_URL.replace('http', 'ws', 1)}/ws?{request.query_string}",
                                    max_msg_size=0) as upstream:
                async def pump(src, dst):
                    async for msg in src:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await dst.send_str(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            await dst.send_bytes(msg.data)
                        else:
                            break
                tasks = [asyncio.ensure_future(pump(upstream, client)), asyncio.ensure_future(pump(client, upstream))]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in tasks:
                    t.cancel()
    except Exception as exc:
        log.info("studio websocket closed: %s", type(exc).__name__)
    finally:
        await client.close()
    return client


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(HERE / "index.html", headers={"Cache-Control": "no-store"})


_AUTO_STOP_TASK = web.AppKey("auto_stop_task", asyncio.Task)


def make_app() -> web.Application:
    app = web.Application(middlewares=[guard], client_max_size=64 * 2**20)   # img2img uploads
    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/bot/{action}", bot_action)
    app.router.add_post("/api/gpu/free", free_gpu)
    app.router.add_get("/studio", studio_page)
    app.router.add_post("/studio/hold", studio_hold)
    app.router.add_get("/ws", studio_ws)

    async def start_background(app):
        app[_AUTO_STOP_TASK] = asyncio.get_running_loop().create_task(auto_stop_loop())

    async def stop_background(app):
        app[_AUTO_STOP_TASK].cancel()

    app.on_startup.append(start_background)
    app.on_cleanup.append(stop_background)
    return app


if __name__ == "__main__":
    log.info("Tower Control on http://0.0.0.0:%d (home network only)", PORT)
    # access_log=None: request lines are not logged (no prompts, no query strings).
    web.run_app(make_app(), host="0.0.0.0", port=PORT, access_log=None, print=None)
