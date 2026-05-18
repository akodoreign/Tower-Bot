import pytest

from src.mission_builder import scene_dialogs
from src.resource_cop import ResourceDecision


@pytest.mark.asyncio
async def test_scene_dialogs_ask_defers_when_ollama_cop_waits(monkeypatch):
    async def fake_wait(*args, **kwargs):
        return ResourceDecision.wait("ollama", "scene_dialogs", 10, "primary busy")

    monkeypatch.setattr("src.resource_cop.wait_for_ollama_turn", fake_wait)

    assert await scene_dialogs._ask("prompt") == ""
