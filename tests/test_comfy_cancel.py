"""_run_graph cancels its ComfyUI job when the bot stops waiting, and only then."""
import asyncio
import json

import aiohttp
import pytest

from src import comfy_client as cc


class _Ctx:
    def __init__(self, obj):
        self.obj = obj

    async def __aenter__(self):
        return self.obj

    async def __aexit__(self, *exc):
        return False


class _Resp:
    status = 200

    async def text(self):
        return json.dumps({"prompt_id": "pid-123456789"})


class _Msg:
    def __init__(self, data):
        self.type, self.data = aiohttp.WSMsgType.TEXT, json.dumps(data)


class _WS:
    def __init__(self, script):
        self.script = script

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for item in self.script:
            if isinstance(item, BaseException):
                raise item
            if item == "hang":
                await asyncio.sleep(3600)
            yield _Msg(item)


class _Session:
    def __init__(self, script, **kw):
        self.ws = _WS(script)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def ws_connect(self, url, **kw):
        return _Ctx(self.ws)

    def post(self, url, **kw):
        return _Ctx(_Resp())


@pytest.fixture
def run(monkeypatch):
    cancelled = []

    async def fake_cancel(pid):
        cancelled.append(pid)

    monkeypatch.setattr(cc, "_cancel_prompt", fake_cancel)

    def go(script, timeout=None):
        monkeypatch.setattr(cc.aiohttp, "ClientSession", lambda **kw: _Session(script))
        coro = cc._run_graph({}, 900)
        if timeout is not None:
            coro = asyncio.wait_for(coro, timeout)
        return asyncio.run(coro)

    return go, cancelled


DONE = {"type": "executing", "data": {"node": None, "prompt_id": "pid-123456789"}}


def test_finished_job_is_not_cancelled(run):
    go, cancelled = run
    assert go([DONE]) == []
    assert cancelled == []


def test_comfy_error_is_not_cancelled(run):
    go, cancelled = run
    err = {"type": "execution_error", "data": {"prompt_id": "pid-123456789", "node_type": "KSampler"}}
    with pytest.raises(cc.ComfyError):
        go([err])
    assert cancelled == []


def test_timeout_cancels_the_job(run):
    go, cancelled = run
    with pytest.raises(asyncio.TimeoutError):
        go([asyncio.TimeoutError()])
    assert cancelled == ["pid-123456789"]


def test_caller_cancel_cancels_the_job(run):
    go, cancelled = run
    with pytest.raises(asyncio.TimeoutError):          # wait_for turns the cancel into TimeoutError
        go(["hang"], timeout=0.05)
    assert cancelled == ["pid-123456789"]


def test_socket_closed_cancels_the_job(run):
    go, cancelled = run
    with pytest.raises(cc.ComfyError):
        go([])
    assert cancelled == ["pid-123456789"]
