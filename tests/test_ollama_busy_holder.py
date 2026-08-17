"""The busy flag must never block the task that set it.

Regression cover for the self-deadlock found 2026-08-17: a long task called
mark_busy() to keep other loops off the GPU, then asked the resource cop for a
turn and was refused by its own claim. It waited out the budget and returned an
empty string, which the caller recorded as a failed generation.

Two live victims:
  * module_quality_trainer -- graded nothing for every run in the log window
  * npc_lifecycle quote backfill -- "stopping at 0", 195/209 NPCs without a quote

The flag still has to work: a caller that does NOT hold it must be blocked
exactly as before, or this fix would just disable the resource cop.
"""

import pytest

import src.ollama_busy as ollama_busy
import src.resource_cop as resource_cop


@pytest.fixture(autouse=True)
def clean_flag(monkeypatch):
    """Isolate module-level busy state, and keep the DB out of these tests."""
    monkeypatch.setattr(ollama_busy, "_busy", False)
    monkeypatch.setattr(ollama_busy, "_busy_count", 0)
    monkeypatch.setattr(ollama_busy, "_busy_holders", {})
    monkeypatch.setattr(ollama_busy, "_priority_busy", False)
    monkeypatch.setattr(ollama_busy, "_db_priority_busy", lambda: False)
    yield


def test_holder_is_not_blocked_by_its_own_claim():
    ollama_busy.mark_busy("module quality training", holder="module_quality_trainer")
    assert ollama_busy.is_available_for("module_quality_trainer") is True


def test_everyone_else_is_still_blocked():
    """The whole point of the flag. If this fails the fix broke the resource cop."""
    ollama_busy.mark_busy("module quality training", holder="module_quality_trainer")
    assert ollama_busy.is_available() is False
    assert ollama_busy.is_available_for("news_feed") is False
    assert ollama_busy.is_available_for("") is False


def test_two_holders_block_each_other():
    ollama_busy.mark_busy("a", holder="alpha")
    ollama_busy.mark_busy("b", holder="beta")
    assert ollama_busy.is_available_for("alpha") is False
    assert ollama_busy.is_available_for("beta") is False

    ollama_busy.mark_available(holder="beta")
    assert ollama_busy.is_available_for("alpha") is True


def test_release_clears_the_holder():
    ollama_busy.mark_busy("x", holder="alpha")
    ollama_busy.mark_available(holder="alpha")
    assert ollama_busy.busy_holders() == {}
    assert ollama_busy.is_available() is True


def test_mismatched_pair_does_not_leak_a_holder():
    """A caller that forgets holder= on release must not stay exempt forever."""
    ollama_busy.mark_busy("x", holder="alpha")
    ollama_busy.mark_available()          # no holder -- the old signature
    assert ollama_busy.busy_holders() == {}
    assert ollama_busy.is_available() is True


def test_a_cross_process_claim_we_do_not_own_still_blocks(monkeypatch):
    """Our own mark_busy() must not exempt us from another process's priority lock."""
    monkeypatch.setattr(ollama_busy, "_db_priority_busy", lambda: True)
    ollama_busy.mark_busy("local work", holder="alpha")
    assert ollama_busy.is_available_for("alpha") is False


def test_our_own_priority_claim_does_not_block_us(monkeypatch):
    monkeypatch.setattr(ollama_busy, "_db_priority_busy", lambda: True)
    monkeypatch.setattr(ollama_busy, "_priority_busy", True)
    ollama_busy.mark_busy("mission building", holder="mission_compiler")
    assert ollama_busy.is_available_for("mission_compiler") is True
    assert ollama_busy.is_available_for("news_feed") is False


@pytest.mark.asyncio
async def test_resource_cop_lets_the_holder_through(monkeypatch):
    monkeypatch.setattr(
        resource_cop, "_ollama_queue_snapshot",
        lambda: {"primary_locked": False, "quick_locked": False,
                 "primary_waiting": 0, "quick_waiting": 0},
    )
    ollama_busy.mark_busy("module quality training", holder="module_quality_trainer")

    blocked = await resource_cop.ask_ollama("news_feed", track="primary")
    assert not blocked.run_now

    # The label IS the holder key here -- the trainer's own call.
    allowed = await resource_cop.ask_ollama("module_quality_trainer", track="primary")
    assert allowed.run_now


@pytest.mark.asyncio
async def test_resource_cop_holder_may_differ_from_label(monkeypatch):
    """The quote backfill runs under its own label inside the lifecycle's claim."""
    monkeypatch.setattr(
        resource_cop, "_ollama_queue_snapshot",
        lambda: {"primary_locked": False, "quick_locked": False,
                 "primary_waiting": 0, "quick_waiting": 0},
    )
    ollama_busy.mark_busy("npc lifecycle cycle", holder="npc_lifecycle")

    without = await resource_cop.ask_ollama("npc_quote_backfill", track="quick")
    assert not without.run_now, "control: no holder must behave as before"

    with_holder = await resource_cop.ask_ollama(
        "npc_quote_backfill", track="quick", holder="npc_lifecycle")
    assert with_holder.run_now


def test_the_two_live_call_sites_pass_a_holder():
    """Pin the actual wiring: a correct helper is useless if nobody passes the key."""
    import pathlib
    import re

    trainer = pathlib.Path("src/module_quality_trainer.py").read_text(encoding="utf-8")
    assert re.search(r"mark_busy\([^)]*holder=_BUSY_HOLDER", trainer)
    assert re.search(r"mark_available\(holder=_BUSY_HOLDER\)", trainer)
    assert '_BUSY_HOLDER = "module_quality_trainer"' in trainer

    life = pathlib.Path("src/npc_lifecycle.py").read_text(encoding="utf-8")
    assert re.search(r"mark_busy\([^)]*holder=_BUSY_HOLDER", life)
    assert re.search(r"mark_available\(holder=_BUSY_HOLDER\)", life)
    assert re.search(r"npc_quote_backfill\"[^)]*holder=_BUSY_HOLDER", life, re.S)
