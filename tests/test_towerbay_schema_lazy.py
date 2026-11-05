"""TowerBay's bid-column check runs before the first TowerBay query, not on import."""
import importlib
import sys


def test_import_runs_no_schema_check(fake_db, monkeypatch):
    # Fresh import against the fake DB; monkeypatch puts the real module back after.
    monkeypatch.delitem(sys.modules, "src.tower_economy", raising=False)
    importlib.import_module("src.tower_economy")
    assert fake_db.executed == []                  # no ALTER / CREATE on import


def test_check_runs_once_on_first_use(fake_db, monkeypatch):
    from src import tower_economy as te
    calls = []
    monkeypatch.setattr(te, "_bid_schema_ready", False)
    monkeypatch.setattr(te, "_ensure_bid_columns", lambda: calls.append(1) or True)
    monkeypatch.setattr(te, "raw_query", lambda *a, **kw: [])
    te.get_active_listings()
    te.get_active_listings()
    assert calls == [1]


def test_failed_check_is_retried(fake_db, monkeypatch):
    from src import tower_economy as te
    results = iter([False, True])
    calls = []
    monkeypatch.setattr(te, "_bid_schema_ready", False)
    monkeypatch.setattr(te, "_ensure_bid_columns", lambda: calls.append(1) or next(results))
    monkeypatch.setattr(te, "raw_query", lambda *a, **kw: [])
    for _ in range(3):
        te.get_active_listings()
    assert calls == [1, 1]                         # failed once, succeeded, then cached
