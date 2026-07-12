import pytest

import src.resource_cop as resource_cop


@pytest.mark.asyncio
async def test_ask_a1111_waits_when_legacy_lock_busy(monkeypatch):
    monkeypatch.setattr(resource_cop, "_existing_a1111_lock_busy", lambda: True)

    decision = await resource_cop.ask_a1111("smoke")

    assert not decision.run_now
    assert decision.resource == "a1111"
    assert decision.wait_seconds == 10
    assert "lock" in decision.reason


@pytest.mark.asyncio
async def test_ask_ollama_waits_when_primary_queue_locked(monkeypatch):
    import src.ollama_busy as ollama_busy
    monkeypatch.setattr(ollama_busy, "is_available", lambda: True)
    monkeypatch.setattr(
        resource_cop,
        "_ollama_queue_snapshot",
        lambda: {"primary_locked": True, "quick_locked": False, "primary_waiting": 0, "quick_waiting": 0},
    )

    decision = await resource_cop.ask_ollama("smoke")

    assert not decision.run_now
    assert decision.resource == "ollama"
    assert "primary" in decision.reason.lower()


@pytest.mark.asyncio
async def test_wait_for_a1111_turn_stops_at_wait_budget(monkeypatch):
    async def fake_ask(*args, **kwargs):
        return resource_cop.ResourceDecision.wait("a1111", "smoke", 5, "busy")

    monkeypatch.setattr(
        resource_cop,
        "ask_a1111",
        fake_ask,
    )

    decision = await resource_cop.wait_for_a1111_turn("smoke", max_wait_seconds=0.01)

    assert not decision.run_now
    assert decision.reason == "busy"


def test_ask_a1111_sync_waits_when_legacy_lock_busy(monkeypatch):
    monkeypatch.setattr(resource_cop, "_existing_a1111_lock_busy", lambda: True)

    decision = resource_cop.ask_a1111_sync("pretty")

    assert not decision.run_now
    assert decision.resource == "a1111"
    assert "lock" in decision.reason


@pytest.mark.asyncio
async def test_pipeline_lifecycle_tracks_start_phase_and_finish():
    run = await resource_cop.start_pipeline(
        "mission_generation",
        mission_title="Glass Stair",
        mission_type="discovery",
        phase="routing",
    )

    try:
        active = await resource_cop.active_pipelines()
        assert any(item["run_id"] == run.run_id for item in active)
        assert any(item["run_id"] == run.run_id for item in resource_cop.active_pipelines_sync())
        tracked = next(item for item in active if item["run_id"] == run.run_id)
        assert tracked["mission_title"] == "Glass Stair"
        assert tracked["mission_type"] == "discovery"
        assert tracked["phase"] == "routing"

        await resource_cop.set_pipeline_phase(run.run_id, "rendering", out_dir="generated_modules/demo")
        tracked = next(item for item in await resource_cop.active_pipelines() if item["run_id"] == run.run_id)
        assert tracked["phase"] == "rendering"
        assert tracked["details"]["out_dir"] == "generated_modules/demo"
    finally:
        await resource_cop.finish_pipeline(run.run_id)

    assert all(item["run_id"] != run.run_id for item in await resource_cop.active_pipelines())


@pytest.mark.asyncio
async def test_append_pipeline_failure_writes_buglog_breadcrumb(monkeypatch, tmp_path):
    fake_resource_cop_path = tmp_path / "repo" / "src" / "resource_cop.py"
    fake_resource_cop_path.parent.mkdir(parents=True)
    fake_resource_cop_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(resource_cop, "__file__", str(fake_resource_cop_path))

    run = await resource_cop.start_pipeline(
        "mission_generation",
        mission_title="Broken Bell",
        mission_type="puzzle",
        phase="rendering",
    )
    try:
        await resource_cop.append_pipeline_failure(run.run_id, RuntimeError("boom"))
        text = (tmp_path / "repo" / "buglog.md").read_text(encoding="utf-8")
        assert "Resource cop captured mission pipeline failure" in text
        assert "Broken Bell" in text
        assert "RuntimeError: boom" in text
    finally:
        await resource_cop.finish_pipeline(run.run_id, status="failed")
