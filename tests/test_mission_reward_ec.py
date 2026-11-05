"""missions.reward_ec is written on insert and update (it was dropped since April 2026)."""
import types

import pytest


@pytest.fixture
def mb(fake_db, monkeypatch):
    # imported here so fake_db replaces src.db_api first (mission_board connects on import)
    from src import mission_board
    inserted = []
    monkeypatch.setattr(mission_board, "raw_query", fake_db.raw_query)
    monkeypatch.setattr(mission_board, "raw_execute", fake_db.raw_execute)
    monkeypatch.setattr(mission_board, "db", types.SimpleNamespace(
        insert=lambda table, row: inserted.append((table, row)) or 1))
    for name in ("_bake_assassination_target", "_bake_strange_occurrence_subject"):
        monkeypatch.setattr(mission_board, name, lambda m: None)
    return mission_board, fake_db, inserted


@pytest.mark.parametrize("mission, expected", [
    ({"reward": "250 EC + 40 Kharma"}, 250),
    ({"reward": "1,200 EC, 90 Kharma"}, 1200),
    ({"reward": "45 Kharma"}, 0),
    ({"reward": "See posting"}, 0),
    ({"reward_ec": 500, "reward": "300 EC"}, 500),     # an explicit number wins
    ({"reward_ec": "bad", "reward": "300 EC"}, 300),
    ({}, 0),
])
def test_reward_ec_for(mb, mission, expected):
    assert mb[0]._reward_ec_for(mission) == expected


def test_insert_writes_reward_ec(mb):
    board, _, inserted = mb
    board._save_mission({"title": "T", "difficulty": 5, "reward": "250 EC + 40 Kharma"})
    (table, row), = inserted
    assert table == "missions" and row["reward_ec"] == 250
    assert "reward_ec" not in row["mission_json"]          # still a column, not a blob key


def test_update_writes_reward_ec(mb):
    board, fake, _ = mb
    fake.rows_for("SELECT id FROM missions WHERE id", [{"id": 7}])
    board._save_mission({"id": 7, "title": "T", "difficulty": 5, "reward": "180 EC"})
    (sql, params), = fake.executed
    assert "reward_ec = %s WHERE id = %s" in sql
    assert params[-2:] == (180, 7)
