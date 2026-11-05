"""db_api opens its MySQL pool on first use, so importing bot code needs no database."""
import os
import subprocess
import sys
import threading
from pathlib import Path

import mysql.connector
import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_import_does_not_connect():
    # A fresh interpreter pointed at a port nothing listens on: import must still work.
    env = {**os.environ, "MYSQL_HOST": "127.0.0.1:1", "MYSQL_USER": "nobody", "MYSQL_PASSWORD": ""}
    code = "import src.db_api as d; print('pool', d.db._pool)"
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "pool None" in r.stdout


@pytest.fixture
def fresh(monkeypatch):
    from src import db_api
    made = []

    class _Pool:
        def __init__(self, **kw):
            made.append(kw)

        def get_connection(self):
            raise mysql.connector.Error("no server in tests")

    monkeypatch.setattr(db_api.pooling, "MySQLConnectionPool", _Pool)
    mgr = object.__new__(db_api.DatabaseManager)
    mgr._pool = None
    return mgr, made


def test_pool_opens_once_under_concurrent_first_use(fresh):
    mgr, made = fresh
    barrier = threading.Barrier(8)

    def first_use():
        barrier.wait()
        mgr._get_pool()

    threads = [threading.Thread(target=first_use) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(made) == 1


def test_failed_open_is_retried(fresh, monkeypatch):
    mgr, made = fresh
    from src import db_api
    calls = {"n": 0}
    real = db_api.pooling.MySQLConnectionPool

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise mysql.connector.Error("MySQL still starting")
        return real(**kw)

    monkeypatch.setattr(db_api.pooling, "MySQLConnectionPool", flaky)
    with pytest.raises(mysql.connector.Error):
        mgr._get_pool()
    assert mgr._get_pool() is not None      # second use opens it
    assert calls["n"] == 2
