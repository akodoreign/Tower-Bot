"""ollama_queue: every request waits its turn on the GPU queue, and nothing skips for queue depth."""
import asyncio

import pytest

import src.gpu_queue as gpu_queue
import src.ollama_queue as oq


class _FakeResp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": "ok"}}


@pytest.fixture
def fake_ollama_http(monkeypatch):
    """httpx client stand-in that records the GPU state at the moment each request is sent."""
    sent = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            sent.append({"payload": json, "holds_turn": gpu_queue.holds_turn(),
                         "kind": gpu_queue.snapshot()["kind"]})
            await asyncio.sleep(0.01)
            return _FakeResp()

    monkeypatch.setattr(oq.httpx, "AsyncClient", FakeClient)
    return sent


async def test_request_runs_inside_a_text_turn(fake_ollama_http):
    data = await oq.call_ollama({"messages": [{"role": "user", "content": "hi"}]}, caller="t")
    assert data["message"]["content"] == "ok"
    sent = fake_ollama_http[0]
    assert sent["holds_turn"] and sent["kind"] == "text"
    assert sent["payload"]["think"] is False              # think switch normalized
    assert sent["payload"]["options"]["num_ctx"] > 0      # defaults filled in


async def test_many_concurrent_calls_all_run_none_skip(fake_ollama_http):
    # The old quick track skipped at depth > 3 and leaked its counter doing so.
    calls = [oq.call_ollama_quick({"messages": []}, caller=f"c{i}") for i in range(8)]
    results = await asyncio.gather(*calls)
    assert len(results) == 8 and len(fake_ollama_http) == 8


async def test_calls_queue_behind_an_image_job(fake_ollama_http):
    order = []

    async def image_job():
        async with gpu_queue.turn("image", "portrait"):
            order.append("image start")
            await asyncio.sleep(0.05)
            order.append("image end")

    async def text_job():
        await asyncio.sleep(0.01)               # arrives while the image runs
        await oq.call_ollama({"messages": []}, caller="bulletin")
        order.append("text done")

    await asyncio.gather(image_job(), text_job())
    assert order == ["image start", "image end", "text done"]


async def test_gpu_timeout_becomes_ollama_busy(monkeypatch, fake_ollama_http):
    monkeypatch.setenv("GPU_TURN_MAX_WAIT", "0.05")
    release = asyncio.Event()

    async def long_render():                     # another task, so the text call really waits
        async with gpu_queue.turn("image", "long render"):
            await release.wait()

    render = asyncio.create_task(long_render())
    await asyncio.sleep(0)
    with pytest.raises(oq.OllamaBusyError):
        await oq.call_ollama({"messages": []}, caller="bulletin")
    release.set()
    await render
    assert not fake_ollama_http
