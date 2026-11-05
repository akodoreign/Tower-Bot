"""Prompt Studio jobs wait their turn in the GPU queue, ahead of loop work."""
import asyncio

import httpx
import pytest

import src.comfy_client as comfy
import src.gpu_queue as gpu_queue


@pytest.fixture(autouse=True)
def no_backend_switching(monkeypatch, isolated_gpu_queue):
    async def nothing():
        return None
    monkeypatch.setattr(gpu_queue, "_unload_ollama", nothing)
    monkeypatch.setattr(gpu_queue, "_free_comfy", nothing)


class FakeComfy:
    """ComfyUI with the studio holding pen: one parked job, rendering takes a few polls."""

    def __init__(self):
        self.held = ["job-1"]
        self.running = []
        self.events = []
        self.polls_left = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/studio/held":
            return httpx.Response(200, json={"held": len(self.held)})
        if path == "/studio/release":
            self.events.append(("release", gpu_queue.snapshot()["label"]))
            self.running, self.held = self.held, []
            self.polls_left = 2
            return httpx.Response(200, json={"queued": self.running})
        if path == "/queue":
            if self.running and self.polls_left == 0:
                self.events.append(("done", gpu_queue.snapshot()["label"]))
                self.running = []
            self.polls_left = max(0, self.polls_left - 1)
            return httpx.Response(200, json={"queue_running": [[0, pid] for pid in self.running],
                                             "queue_pending": []})
        return httpx.Response(404)


@pytest.fixture
def fake_comfy(monkeypatch):
    fake = FakeComfy()
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(comfy.httpx, "AsyncClient", client)
    return fake


async def test_parked_job_runs_in_its_own_image_turn_after_the_current_job(fake_comfy):
    order = []
    release = asyncio.Event()

    async def bulletin():
        async with gpu_queue.turn("text", "bulletin"):
            await release.wait()
            order.append("bulletin")

    async def portrait():
        await asyncio.sleep(0.01)
        async with gpu_queue.turn("image", "portrait"):
            order.append("portrait")

    holder = asyncio.create_task(bulletin())
    await asyncio.sleep(0)
    gate = asyncio.create_task(comfy.studio_gate_loop(poll_seconds=0.01))
    queued_bg = asyncio.create_task(portrait())
    await asyncio.sleep(0.05)
    assert not fake_comfy.events                 # still parked: the GPU is busy with text
    release.set()
    await holder
    await queued_bg
    gate.cancel()
    with pytest.raises(asyncio.CancelledError):
        await gate

    # Released inside its own turn and held until ComfyUI finished it;
    # the person waiting on the studio went ahead of the queued portrait.
    assert fake_comfy.events == [("release", "prompt studio"), ("done", "prompt studio")]
    assert order == ["bulletin", "portrait"]
    assert not gpu_queue.locked()
