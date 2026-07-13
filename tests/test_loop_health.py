"""Tests for the background-loop heartbeat registry (src/loop_health.py)."""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def loop_health(monkeypatch):
    """loop_health backed by an in-memory heartbeat store (no MySQL)."""
    store: dict = {}
    mod = types.ModuleType("src.db_api")

    def raw_execute(sql, params=()):
        if "INSERT INTO loop_heartbeats" in sql:
            name, ok, note, fails = params
            row = store.get(name, {"loop_name": name, "run_count": 0, "fail_count": 0})
            row.update(last_run=datetime.utcnow(), ok=ok, note=note)
            row["run_count"] += 1
            row["fail_count"] += fails
            store[name] = row
        return 1

    def raw_query(sql, params=()):
        return list(store.values()) if "loop_heartbeats" in sql else []

    mod.raw_execute = raw_execute
    mod.raw_query = raw_query
    monkeypatch.setitem(sys.modules, "src.db_api", mod)
    import importlib
    import src.loop_health as lh
    importlib.reload(lh)
    lh._store = store
    return lh


def test_fresh_boot_all_never_ran(loop_health):
    health = loop_health.get_loop_health()
    assert len(health) == len(loop_health.EXPECTED)
    assert all(l["status"] == "never-ran" for l in health)


def test_heartbeat_then_ok(loop_health):
    loop_health.record_loop_heartbeat("news_feed", ok=True, note="posted")
    nf = next(l for l in loop_health.get_loop_health() if l["loop"] == "news_feed")
    assert nf["status"] == "ok" and nf["runs"] == 1 and nf["fails"] == 0


def test_overdue_detection(loop_health):
    loop_health.record_loop_heartbeat("news_feed", ok=True)
    loop_health._store["news_feed"]["last_run"] = datetime.utcnow() - timedelta(hours=6)
    nf = next(l for l in loop_health.get_loop_health() if l["loop"] == "news_feed")
    assert nf["status"] == "overdue"  # threshold is 3h


def test_failing_beat(loop_health):
    loop_health.record_loop_heartbeat("ad_feed", ok=False, note="Ollama down")
    af = next(l for l in loop_health.get_loop_health() if l["loop"] == "ad_feed")
    assert af["status"] == "failing" and af["fails"] == 1


def test_worst_first_ordering(loop_health):
    for n in loop_health.EXPECTED:
        loop_health.record_loop_heartbeat(n, ok=True)
    loop_health._store["news_feed"]["last_run"] = datetime.utcnow() - timedelta(hours=6)
    loop_health.record_loop_heartbeat("ad_feed", ok=False)
    health = loop_health.get_loop_health()
    rank = {"never-ran": 0, "overdue": 1, "failing": 2, "ok": 3}
    ranks = [rank[l["status"]] for l in health]
    assert ranks == sorted(ranks)
    assert health[0]["status"] == "overdue"


def test_record_never_raises(monkeypatch):
    """A heartbeat failure must never propagate into the loop."""
    mod = types.ModuleType("src.db_api")

    def boom(*a, **kw):
        raise RuntimeError("db down")

    mod.raw_execute = boom
    mod.raw_query = boom
    monkeypatch.setitem(sys.modules, "src.db_api", mod)
    import importlib
    import src.loop_health as lh
    importlib.reload(lh)
    # must swallow the error, not raise
    lh.record_loop_heartbeat("news_feed", ok=True)
    assert lh.get_loop_health() == [] or isinstance(lh.get_loop_health(), list)
