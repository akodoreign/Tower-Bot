import pytest

from src.mission_builder import module_council
from src.resource_cop import ResourceDecision


@pytest.mark.asyncio
async def test_module_council_call_defers_when_ollama_cop_waits(monkeypatch, tmp_path):
    async def fake_wait(*args, **kwargs):
        return ResourceDecision.wait("ollama", "module_council:Architect", 10, "primary busy")

    monkeypatch.setattr("src.resource_cop.wait_for_ollama_turn", fake_wait)
    monkeypatch.setattr(module_council, "_LOG_PATH", tmp_path / "module_council.log")

    result = await module_council._call("system", "user", label="Architect")

    assert result == ""
    assert "resource-cop wait" in (tmp_path / "module_council.log").read_text(encoding="utf-8")
