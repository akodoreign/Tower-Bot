import pytest

from src.mission_builder import mimir_module
from src.resource_cop import ResourceDecision


@pytest.mark.asyncio
async def test_mimir_statblock_defers_when_ollama_cop_waits(monkeypatch):
    async def fake_wait(*args, **kwargs):
        return ResourceDecision.wait("ollama", "mimir_statblock", 10, "primary busy")

    monkeypatch.setattr("src.resource_cop.wait_for_ollama_turn", fake_wait)

    result = await mimir_module._generate_statblock_llm("Ash Clerk", "1", "undead", "office haunt")

    assert result == {}
