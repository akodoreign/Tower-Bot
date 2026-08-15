"""World tensions as rows, not a 17KB JSON list.

Every add_tension() used to decode the whole list, append, and write it all
back, with uniqueness enforced by an `in` check on the decoded blob. A tension
is a record: it starts, it is live, it gets resolved.
"""

import inspect

from src import db_api


def test_accessors_read_the_table_not_global_state():
    for fn in (db_api.get_active_tensions, db_api.add_tension, db_api.resolve_tension):
        src = inspect.getsource(fn)
        assert "world_tensions" in src, f"{fn.__name__} does not use the table"
        assert "get_global_state" not in src, f"{fn.__name__} still reads the blob"


def test_add_is_a_single_insert_not_read_modify_write():
    src = inspect.getsource(db_api.add_tension)
    assert "INSERT INTO world_tensions" in src
    assert "ON DUPLICATE KEY" in src, "uniqueness must be the index, not an `in` check"
    assert "get_active_tensions()" not in src


def test_resolved_tensions_are_retired_not_deleted():
    """What the world was worried about last month is history, not garbage."""
    for fn in (db_api.resolve_tension, db_api.set_active_tensions):
        src = inspect.getsource(fn)
        # Match the STATEMENT, not the word -- a docstring saying "never
        # deleted" is not a DELETE.
        assert "DELETE FROM" not in src.upper(), f"{fn.__name__} deletes history"
        assert "active = 0" in src


def test_schema_has_a_uniqueness_index():
    src = inspect.getsource(db_api._ensure_tension_table)
    assert "UNIQUE KEY" in src
    # A 400-char column needs a prefix index to stay inside the key length limit.
    assert "tension(255)" in src


def test_news_feed_uses_the_accessor():
    from src import news_feed

    src = inspect.getsource(news_feed)
    assert "state_key = 'world_active_tensions'" not in src, (
        "news_feed still reads the retired blob directly"
    )
