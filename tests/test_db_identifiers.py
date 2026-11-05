"""db_api quotes identifiers: MySQL 8 reserves column names like `rank` (npcs.rank)."""
import sys

import pytest


class _Cursor:
    def __init__(self, log):
        self.log, self.lastrowid, self.rowcount = log, 1, 1

    def execute(self, sql, params=()):
        self.log.append(sql)

    def close(self):
        pass


class _Conn:
    def __init__(self, log):
        self.log = log

    def cursor(self, **kw):
        return _Cursor(self.log)

    def commit(self):
        pass

    def is_connected(self):
        return False


@pytest.fixture
def db(monkeypatch):
    if "src.db_api" not in sys.modules:          # importing it opens the pool
        from mysql.connector import pooling
        monkeypatch.setattr(pooling, "MySQLConnectionPool", lambda **kw: None)
    from src.db_api import DatabaseManager
    mgr = object.__new__(DatabaseManager)
    log = []

    class _Pool:
        def get_connection(self):
            return _Conn(log)

    mgr._pool = _Pool()
    return mgr, log


def test_insert_update_delete_quote_reserved_columns(db):
    mgr, log = db
    mgr.insert("npcs", {"name": "Tamsin", "rank": "Member"})
    mgr.update("npcs", {"rank": "Warden"}, {"name": "Tamsin"})
    mgr.delete("npcs", {"rank": "Warden"})
    assert log == [
        "INSERT INTO `npcs` (`name`, `rank`) VALUES (%s, %s)",
        "UPDATE `npcs` SET `rank` = %s WHERE `name` = %s",
        "DELETE FROM `npcs` WHERE `rank` = %s",
    ]


def test_unsafe_identifier_still_rejected(db):
    mgr, _ = db
    with pytest.raises(ValueError):
        mgr.insert("npcs", {"name`; DROP TABLE npcs; --": "x"})
