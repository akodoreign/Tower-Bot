"""The row-shaped global_state blobs are tables now.

Each was a JSON list that had to be decoded in full to read one entry and
rewritten in full to add one, and each carried a self-imposed cap -- 100
acquisitions, 200 wealth events -- that existed only because the whole history
had to fit in a single column.
"""

import inspect

from src import db_api


def _code_only(src: str) -> str:
    """Comments about a retired blob are not usages of it."""
    return " ".join(l for l in src.splitlines() if not l.strip().startswith("#"))


def test_wealth_log_is_a_table():
    src = _code_only(inspect.getsource(db_api.get_wealth_event_log))
    assert "district_wealth_events" in src
    assert "global_state" not in src


def test_wealth_log_keeps_the_historical_key_names():
    """Callers read ts/district/old/new/delta/reason -- do not break them."""
    src = inspect.getsource(db_api.get_wealth_event_log)
    for key in ('"ts"', '"district"', '"old"', '"new"', '"delta"', '"reason"'):
        assert key in src, f"accessor stopped returning {key}"


def test_wealth_log_is_filterable_by_district():
    """The JSON list could not do this without decoding every event."""
    import inspect as _i
    sig = _i.signature(db_api.get_wealth_event_log)
    assert "district" in sig.parameters


def test_used_parties_is_a_table():
    from src import mission_board

    load = _code_only(inspect.getsource(mission_board._load_used_parties))
    save = _code_only(inspect.getsource(mission_board._save_used_parties))
    assert "used_parties" in load and "state_key" not in load
    assert "ON DUPLICATE KEY" in save, "membership should be the index, not a rewritten list"


def test_acquisitions_written_as_rows():
    from src import tower_economy

    src = _code_only(inspect.getsource(tower_economy))
    assert 'set_global_state("towerbay_npc_acquisitions"' not in src, (
        "still rewriting the acquisitions blob"
    )
    assert "towerbay_npc_acquisitions" in src


def test_no_arbitrary_history_caps_remain():
    """[-100:] / [-200:] existed only to fit a column."""
    from src import tower_economy

    src = inspect.getsource(tower_economy)
    assert "acquisitions[-100:]" not in src
