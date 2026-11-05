import asyncio

import pytest

import src.gpu_queue as gpu_queue


@pytest.fixture(autouse=True)
def fake_backends(monkeypatch, isolated_gpu_queue):
    calls = []

    async def unload_ollama():
        calls.append("unload_ollama")

    async def free_comfy():
        calls.append("free_comfy")

    monkeypatch.setattr(gpu_queue, "_unload_ollama", unload_ollama)
    monkeypatch.setattr(gpu_queue, "_free_comfy", free_comfy)
    return calls


@pytest.mark.asyncio
async def test_switching_kind_frees_the_other_backend(fake_backends):
    async with gpu_queue.turn("text", "a"):
        pass
    async with gpu_queue.turn("text", "b"):
        pass
    async with gpu_queue.turn("image", "c"):
        pass
    async with gpu_queue.turn("text", "d"):
        pass

    # Repeating the same kind costs nothing; each switch frees the other side once.
    assert fake_backends == ["free_comfy", "unload_ollama", "free_comfy"]


@pytest.mark.asyncio
async def test_turns_run_one_at_a_time():
    running = 0
    peak = 0

    async def job(kind):
        nonlocal running, peak
        async with gpu_queue.turn(kind, kind):
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    await asyncio.gather(*(job("text" if i % 2 else "image") for i in range(6)))
    assert peak == 1
    assert not gpu_queue.locked()


@pytest.mark.asyncio
async def test_nested_turn_in_same_task_does_not_deadlock(fake_backends):
    async with gpu_queue.turn("image", "outer"):
        assert gpu_queue.holds_turn()
        async with gpu_queue.turn("text", "inner"):  # e.g. asking Ollama for a prompt mid-pipeline
            assert gpu_queue.locked()
    assert not gpu_queue.locked()
    assert fake_backends == ["unload_ollama", "free_comfy"]


@pytest.mark.asyncio
async def test_released_turn_is_not_inherited_by_leftover_tasks():
    leaked = []

    async with gpu_queue.turn("text", "parent"):
        child_ctx_task = asyncio.get_running_loop().create_future()

        async def child():
            await child_ctx_task
            leaked.append(gpu_queue.holds_turn())

        task = asyncio.create_task(child())

    child_ctx_task.set_result(None)
    await task
    assert leaked == [False]


@pytest.mark.asyncio
async def test_next_turn_prefers_the_kind_already_loaded(fake_backends):
    order = []
    release = asyncio.Event()

    async def holder():
        async with gpu_queue.turn("text", "first"):
            await release.wait()

    async def job(kind, name):
        async with gpu_queue.turn(kind, name):
            order.append(name)

    first = asyncio.create_task(holder())
    await asyncio.sleep(0)
    jobs = [asyncio.create_task(job(k, n)) for k, n in
            [("image", "img1"), ("text", "txt1"), ("image", "img2"), ("text", "txt2")]]
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, *jobs)

    # Text is loaded, so queued text runs first, then the images back to back.
    assert order == ["txt1", "txt2", "img1", "img2"]
    assert fake_backends == ["free_comfy", "unload_ollama"]


@pytest.mark.asyncio
async def test_starving_waiter_jumps_the_kind_preference(monkeypatch):
    monkeypatch.setenv("GPU_TURN_STARVE_SECONDS", "0")
    order = []
    release = asyncio.Event()

    async def holder():
        async with gpu_queue.turn("text", "first"):
            await release.wait()

    async def job(kind, name):
        async with gpu_queue.turn(kind, name):
            order.append(name)

    first = asyncio.create_task(holder())
    await asyncio.sleep(0)
    jobs = [asyncio.create_task(job(k, n)) for k, n in [("image", "img1"), ("text", "txt1")]]
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, *jobs)

    assert order == ["img1", "txt1"]   # everyone counts as starving, so plain arrival order


@pytest.mark.asyncio
async def test_player_request_jumps_background_work_but_waits_for_running_job():
    order = []
    release = asyncio.Event()

    async def holder():
        async with gpu_queue.turn("image", "story image"):
            await release.wait()
            order.append("story image")      # the running render is never interrupted

    async def job(kind, name, player=False):
        if player:
            gpu_queue.mark_player_facing()   # what the slash-command tree does
        async with gpu_queue.turn(kind, name):
            order.append(name)

    first = asyncio.create_task(holder())
    await asyncio.sleep(0)
    jobs = [asyncio.create_task(job("image", "portrait")),
            asyncio.create_task(job("text", "bulletin")),
            asyncio.create_task(job("text", "/chat", player=True))]
    await asyncio.sleep(0)
    assert gpu_queue.snapshot()["waiting_player"] == 1
    release.set()
    await asyncio.gather(first, *jobs)

    # Image is loaded, but the player's text goes first; then text stays loaded.
    assert order == ["story image", "/chat", "bulletin", "portrait"]


@pytest.mark.asyncio
async def test_player_facing_block_is_scoped():
    with gpu_queue.player_facing():
        assert gpu_queue._is_player()
    assert not gpu_queue._is_player()


async def test_batch_spawned_by_a_command_loses_player_priority():
    # /genmodule-style: the command marks itself, starts a long batch, returns.
    seen = {}
    release = asyncio.Event()

    async def batch():
        seen["while_command_runs"] = gpu_queue._is_player()
        await release.wait()
        seen["after_command_returned"] = gpu_queue._is_player()

    async def command():
        gpu_queue.mark_player_facing()
        t = asyncio.create_task(batch())
        await asyncio.sleep(0)             # batch starts while the command is alive
        return t

    t = await asyncio.create_task(command())
    release.set()
    await t
    assert seen == {"while_command_runs": True, "after_command_returned": False}


async def test_task_spawned_inside_player_block_loses_it_after_the_block():
    release = asyncio.Event()
    seen = []

    async def child():
        seen.append(gpu_queue._is_player())
        await release.wait()
        seen.append(gpu_queue._is_player())

    with gpu_queue.player_facing():
        t = asyncio.create_task(child())
        await asyncio.sleep(0)
    release.set()
    await t
    assert seen == [True, False]


@pytest.mark.asyncio
async def test_cancelled_waiter_leaves_the_queue():
    release = asyncio.Event()

    async def holder():
        async with gpu_queue.turn("text", "first"):
            await release.wait()

    async def waiter():
        async with gpu_queue.turn("image", "never"):
            pass

    first = asyncio.create_task(holder())
    await asyncio.sleep(0)
    w = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    assert gpu_queue.snapshot()["waiting"] == 1
    w.cancel()
    with pytest.raises(asyncio.CancelledError):
        await w
    assert gpu_queue.snapshot()["waiting"] == 0
    release.set()
    await first
    assert not gpu_queue.locked()


def test_think_in_options_is_promoted_to_top_level():
    payload = {"messages": [], "options": {"num_predict": 300, "think": False}}
    gpu_queue.normalize_ollama_payload(payload)
    assert payload["think"] is False
    assert "think" not in payload["options"]
    assert payload["options"]["num_predict"] == 300


def test_unspecified_think_defaults_off():
    payload = {"messages": [], "options": {"num_predict": 300}}
    assert gpu_queue.normalize_ollama_payload(payload)["think"] is False


def test_thinking_gets_extra_token_room(monkeypatch):
    monkeypatch.setenv("OLLAMA_THINK_TOKENS", "1000")
    payload = {"messages": [], "options": {"num_predict": 200, "think": True}}
    gpu_queue.normalize_ollama_payload(payload)
    assert payload["think"] is True
    assert payload["options"]["num_predict"] == 1200


def test_top_level_think_wins_and_non_ollama_payloads_are_untouched():
    payload = {"messages": [], "think": True, "options": {"think": False}}
    assert gpu_queue.normalize_ollama_payload(payload)["think"] is True
    other = {"model": "x", "keep_alive": 0}
    assert gpu_queue.normalize_ollama_payload(other) == {"model": "x", "keep_alive": 0}


@pytest.mark.asyncio
async def test_wait_budget_raises_gpu_busy(monkeypatch):
    monkeypatch.setenv("GPU_TURN_MAX_WAIT", "0.05")
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with gpu_queue.turn("text", "long chapter"):
            started.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await started.wait()
    with pytest.raises(gpu_queue.GpuBusyError):
        async with gpu_queue.turn("image", "impatient"):
            pass
    release.set()
    await task
