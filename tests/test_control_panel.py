"""Tower Control: home-network-only page that starts/stops the bot (sc.exe is faked)."""
import asyncio
import importlib.util
import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("tower_control", ROOT / "control_panel" / "server.py")
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)

LAN = "192.168.68.70"
PAGE = {"Host": "192.168.68.61:5050", "Origin": "http://192.168.68.61:5050"}


@pytest.fixture
def world(monkeypatch, tmp_path):
    state = {"TowerBotService": "stopped", "TowerTunnel": "running", "MySQL96": "running"}
    calls = []

    def fake_sc(*args):
        calls.append(args)
        verb, name = args[0], args[1]
        if verb == "start":
            state[name] = "running"
        elif verb == "stop":
            state[name] = "stopped"
        return ""

    monkeypatch.setattr(tc, "_sc", fake_sc)
    monkeypatch.setattr(tc, "service_state", lambda name: state.get(name, "missing"))
    monkeypatch.setattr(tc, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(tc, "gpu_status", lambda: {})
    monkeypatch.setattr(tc, "_client_ip", lambda request: world_ip["addr"])
    monkeypatch.delenv("CONTROL_TRUSTED_NETS", raising=False)
    world_ip = {"addr": LAN}
    return state, calls, world_ip


async def _client():
    client = TestClient(TestServer(tc.make_app()))
    await client.start_server()
    return client


async def test_lan_can_load_the_page_and_status(world):
    client = await _client()
    try:
        assert (await client.get("/", headers=PAGE)).status == 200
        s = await (await client.get("/api/status", headers=PAGE)).json()
        assert s["services"]["TowerBotService"] == "stopped"
    finally:
        await client.close()


@pytest.mark.parametrize("addr", ["10.0.0.5", "203.0.113.9", "172.16.0.4"])
async def test_outside_the_home_network_is_refused(world, addr):
    world[2]["addr"] = addr
    client = await _client()
    try:
        assert (await client.get("/", headers=PAGE)).status == 403
    finally:
        await client.close()


async def test_tunnel_headers_are_refused(world):
    client = await _client()
    try:
        assert (await client.get("/", headers={**PAGE, "CF-Ray": "x"})).status == 403
    finally:
        await client.close()


async def test_dns_rebinding_host_is_refused(world):
    client = await _client()
    try:
        assert (await client.get("/api/status", headers={"Host": "evil.example:5050"})).status == 403
        assert (await client.get("/api/status", headers={"Host": "localhost:5050"})).status == 200
    finally:
        await client.close()


@pytest.mark.parametrize("headers", [
    {"Host": "192.168.68.61:5050"},                                        # no Origin
    {"Host": "192.168.68.61:5050", "Origin": "https://evil.example"},
])
async def test_cross_site_start_is_refused(world, headers):
    client = await _client()
    try:
        assert (await client.post("/api/bot/start", json={}, headers=headers)).status == 403
        assert world[1] == []                                              # sc.exe never called
    finally:
        await client.close()


async def test_start_for_hours_then_auto_stop(world, monkeypatch):
    state, calls, _ = world
    client = await _client()
    try:
        r = await client.post("/api/bot/start", json={"hours": 6}, headers=PAGE)
        assert r.status == 200
        for _ in range(50):
            if state["TowerBotService"] == "running":
                break
            await asyncio.sleep(0.02)
        assert state["TowerBotService"] == "running"
        at = tc._load_deadline()
        assert at and abs(at - (time.time() + 6 * 3600)) < 60
    finally:
        await client.close()

    # Session time is up: the loop stops the bot and clears the deadline.
    tc._save_deadline(time.time() - 1)
    real_sleep = asyncio.sleep

    async def fast_sleep(_):
        await real_sleep(0)

    monkeypatch.setattr(tc.asyncio, "sleep", fast_sleep)
    task = asyncio.ensure_future(tc.auto_stop_loop())
    for _ in range(200):
        if state["TowerBotService"] == "stopped":
            break
        await real_sleep(0.01)
    task.cancel()
    assert state["TowerBotService"] == "stopped"
    assert tc._load_deadline() is None


async def test_stop_clears_auto_stop_and_restart_runs_both(world):
    state, calls, _ = world
    state["TowerBotService"] = "running"
    tc._save_deadline(time.time() + 3600)
    client = await _client()
    try:
        assert (await client.post("/api/bot/stop", headers=PAGE)).status == 200
        assert tc._load_deadline() is None
        for _ in range(50):
            if not tc._action_lock.locked():
                break
            await asyncio.sleep(0.02)
        calls.clear()
        state["TowerBotService"] = "running"
        assert (await client.post("/api/bot/restart", headers=PAGE)).status == 200
        for _ in range(50):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.02)
        assert [c[0] for c in calls] == ["stop", "start"]
    finally:
        await client.close()


async def test_unknown_action_is_404(world):
    client = await _client()
    try:
        assert (await client.post("/api/bot/delete", headers=PAGE)).status == 404
    finally:
        await client.close()


async def test_studio_websocket_needs_same_origin(world):
    client = await _client()
    try:
        r = await client.get("/ws?clientId=x", headers={"Host": "192.168.68.61:5050",
                                                        "Origin": "https://evil.example"})
        assert r.status == 403
    finally:
        await client.close()
