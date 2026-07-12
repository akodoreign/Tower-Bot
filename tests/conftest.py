"""Shared test fixtures for the Tower bot.

Central home for the fake-world harness that regression tests reuse instead of
re-mocking src.db_api / src.resource_cop / src.ollama_queue / src.mimir_client
in every file (a throwaway version of this once leaked rows into the live DB —
see buglog 2026-07-12). Import these via fixture args; do not hand-roll.
"""
from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def fake_db(monkeypatch):
    """A stand-in src.db_api whose queries return canned rows and whose writes
    are captured (never touch MySQL).

    Usage:
        def test_x(fake_db):
            fake_db.rows_for("SELECT COUNT(*) c FROM npcs", [{"c": 2}])
            ...                      # exercise code
            assert fake_db.executed  # list of (sql, params) writes
    """
    class FakeDB:
        def __init__(self):
            self._matchers: list[tuple[str, list]] = []
            self.executed: list[tuple] = []
            self.default_rows: list = []

        def rows_for(self, needle: str, rows: list):
            """When a query CONTAINS `needle`, return `rows`. First match wins."""
            self._matchers.append((needle, rows))
            return self

        def raw_query(self, sql, params=()):
            for needle, rows in self._matchers:
                if needle in sql:
                    return list(rows)
            return list(self.default_rows)

        def raw_execute(self, sql, params=()):
            self.executed.append((sql, params))
            return 1

    fake = FakeDB()
    mod = types.ModuleType("src.db_api")
    mod.raw_query = fake.raw_query
    mod.raw_execute = fake.raw_execute
    mod.db = types.SimpleNamespace(insert=lambda *a, **kw: None,
                                   fetch_all=lambda *a, **kw: [])
    mod.add_party_history_event = lambda *a, **kw: fake.executed.append(("PHIST", a))
    mod.add_npc_history_event = lambda *a, **kw: fake.executed.append(("NHIST", a))
    mod.get_faction_reputation = lambda *a, **kw: 0
    mod.set_faction_reputation = lambda *a, **kw: None
    mod.get_global_state = lambda *a, **kw: None
    mod.set_global_state = lambda *a, **kw: None
    mod.__getattr__ = lambda name: (lambda *a, **kw: [])  # tolerate any helper
    monkeypatch.setitem(sys.modules, "src.db_api", mod)
    return fake


@pytest.fixture
def fake_ollama(monkeypatch):
    """Fake src.ollama_queue + src.resource_cop so no model is ever called.

    Set `.reply` to control what call_ollama returns; `.calls` records every
    payload (assert on num_ctx, num_predict, prompt, etc.).
    """
    class FakeOllama:
        def __init__(self):
            self.reply = ""
            self.calls: list[dict] = []
            self.run_now = True

    fake = FakeOllama()

    cop = types.ModuleType("src.resource_cop")

    class _Decision:
        def __init__(self, run_now):
            self.run_now = run_now
            self.reason = "test"

    async def wait_for_ollama_turn(*a, **kw):
        return _Decision(fake.run_now)

    async def wait_for_a1111_turn(*a, **kw):
        return _Decision(fake.run_now)

    cop.wait_for_ollama_turn = wait_for_ollama_turn
    cop.wait_for_a1111_turn = wait_for_a1111_turn
    monkeypatch.setitem(sys.modules, "src.resource_cop", cop)

    queue = types.ModuleType("src.ollama_queue")

    async def call_ollama(payload, **kw):
        fake.calls.append(payload)
        return {"message": {"content": fake.reply}}

    queue.call_ollama = call_ollama
    queue.call_ollama_quick = call_ollama
    monkeypatch.setitem(sys.modules, "src.ollama_queue", queue)
    return fake


@pytest.fixture
def fake_mimir(monkeypatch):
    """Fake src.mimir_client. Available=False by default (enrichment no-ops);
    set `.available = True` and populate `.items` to exercise catalog matching.
    """
    class FakeMimirClient:
        available = False
        items: dict = {}
        added: list = []

        async def ensure_connected(self):
            return self.available

        async def search_items(self, **kw):
            name = (kw.get("name") or "").lower()
            for key, val in self.items.items():
                if key.lower() in name:
                    return [val]
            return []

        async def add_item(self, module_id, name):
            self.added.append((module_id, name))

    client = FakeMimirClient()
    mod = types.ModuleType("src.mimir_client")
    mod.get_mimir = lambda: client
    monkeypatch.setitem(sys.modules, "src.mimir_client", mod)
    # Consumers do `from src.mimir_client import get_mimir` at import time, so the
    # sys.modules swap alone misses their already-bound reference. Patch the name
    # in any consumer module that is already imported.
    for mod_name in ("src.mission_builder.mimir_module", "src.treasure"):
        if mod_name in sys.modules:
            monkeypatch.setattr(sys.modules[mod_name], "get_mimir",
                                lambda: client, raising=False)
    return client


@pytest.fixture
def no_sleep(monkeypatch):
    """Make asyncio.sleep instant so retry/backoff loops run fast."""
    import asyncio
    real = asyncio.sleep

    async def fast(_s):
        await real(0)

    monkeypatch.setattr(asyncio, "sleep", fast)
    return fast
