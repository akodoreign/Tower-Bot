"""Mimir pull links same-name NPCs instead of re-inserting them; sync_npc runs one at a time per NPC."""
import asyncio
import sys

import pytest


@pytest.fixture
def ms(monkeypatch):
    if "src.db_api" not in sys.modules:          # importing it opens the pool
        from mysql.connector import pooling
        monkeypatch.setattr(pooling, "MySQLConnectionPool", lambda **kw: None)
    from src import mimir_sync
    monkeypatch.setattr(mimir_sync, "_reported_dup_mimir_ids", set())
    return mimir_sync


def _fake_db(monkeypatch, ms, mapped):
    executed = []

    def raw_query(sql, params=()):
        if "FROM npcs WHERE name=" in sql:
            return [{"id": 7}]
        if "entity_type=%s AND entity_id=%s" in sql:
            return [{"mimir_id": mapped, "sync_hash": "h"}] if mapped else []
        return []                                  # pass 1 rows, known mimir ids

    monkeypatch.setattr(ms, "raw_query", raw_query)
    monkeypatch.setattr(ms, "raw_execute", lambda sql, params=(): executed.append((sql, params)))
    return executed


class _Mimir:
    available = True

    async def list_characters(self, character_type=None):
        return [{"id": "m-new", "name": "Silt Gable"}]


def _pull(monkeypatch, ms):
    monkeypatch.setattr(ms, "get_mimir", lambda: _Mimir())
    return asyncio.run(ms.MimirSyncEngine().pull_npc_changes())


def test_unmapped_bot_npc_is_linked_not_inserted(monkeypatch, ms):
    executed = _fake_db(monkeypatch, ms, mapped=None)
    assert _pull(monkeypatch, ms) == 1
    assert not any("INSERT INTO npcs" in sql for sql, _ in executed)
    assert any("INSERT INTO mimir_sync" in sql and params[:3] == ("npc", "7", "m-new")
               for sql, params in executed)


def test_second_mimir_copy_is_reported_once(monkeypatch, ms):
    executed = _fake_db(monkeypatch, ms, mapped="m-old")
    warnings = []
    monkeypatch.setattr(ms.logger, "warning", lambda msg, *a, **k: warnings.append(msg))
    _pull(monkeypatch, ms)
    _pull(monkeypatch, ms)
    assert executed == []
    assert len(warnings) == 1 and "Duplicate NPC in Mimir" in warnings[0]


def test_sync_npc_serialized_per_npc(monkeypatch, ms):
    active, peak = 0, 0

    async def body(self, npc_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return True

    monkeypatch.setattr(ms.MimirSyncEngine, "_sync_npc", body)
    monkeypatch.setattr(ms, "_npc_sync_locks", {})

    async def run():
        eng = ms.MimirSyncEngine()
        await asyncio.gather(eng.sync_npc(5), eng.sync_npc(5))

    asyncio.run(run())
    assert peak == 1
