"""generate() checks each render; re-rolls once only when enabled and the check fails."""
import base64
import io

import pytest
from PIL import Image

import src.comfy_client as comfy
import src.gpu_queue as gpu_queue
import src.image_check as image_check


def _png(color):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def fake_render(monkeypatch, isolated_gpu_queue):
    renders = []

    async def run_graph(graph, timeout):
        renders.append(gpu_queue.holds_turn())
        return [_png((len(renders) * 40, 0, 0))]

    async def nothing():
        return None

    monkeypatch.setattr(comfy, "_run_graph", run_graph)
    monkeypatch.setattr(gpu_queue, "_unload_ollama", nothing)
    monkeypatch.setattr(gpu_queue, "_free_comfy", nothing)
    return renders


def _verdict(style_ok):
    return image_check.Verdict(recipe="anime", style="anime", style_ok=style_ok, prompt_sim=0.25,
                               flags={"blank": 0.1, "text": 0.9})


@pytest.mark.parametrize("reroll, first, expect_renders", [
    ("0", 0.1, 1),      # failing check, re-roll off: logged only
    ("1", 0.9, 1),      # passing check: no re-roll
    ("1", 0.1, 2),      # failing check, re-roll on: one more render, same turn
])
async def test_reroll_only_when_enabled_and_failing(monkeypatch, fake_render, reroll, first, expect_renders):
    monkeypatch.setenv("IMAGE_CHECK_REROLL", reroll)
    scores = iter([first, 0.9])
    monkeypatch.setattr(image_check, "check", lambda png, prompt, recipe: _verdict(next(scores)))
    out = await comfy.generate({"prompt": "a knight", "width": 64, "height": 64}, label="t", checkpoint="anime")
    assert len(fake_render) == expect_renders
    assert all(fake_render)                                   # every render held the GPU turn
    assert base64.b64decode(out["images"][0]) == _png((expect_renders * 40, 0, 0))


async def test_check_disabled_or_unavailable_changes_nothing(monkeypatch, fake_render):
    monkeypatch.setenv("IMAGE_CHECK", "0")
    out = await comfy.generate({"prompt": "a knight", "width": 64, "height": 64}, label="t", checkpoint="anime")
    assert len(fake_render) == 1 and out["images"]


def test_text_flag_does_not_fail_an_image():
    assert _verdict(0.9).ok                  # text=0.9 is reported, not judged
    assert not image_check.Verdict("scene", "photo", 0.9, 0.2, {"blank": 0.87}).ok
