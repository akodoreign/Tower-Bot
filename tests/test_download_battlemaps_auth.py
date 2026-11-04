"""download_battlemaps: app-only Reddit OAuth, and the token never leaves Reddit."""
import importlib.util
from pathlib import Path

import httpx
import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "download_battlemaps.py"
_spec = importlib.util.spec_from_file_location("download_battlemaps", _PATH)
dbm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dbm)


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setattr(dbm, "LOG_FILE", tmp_path / "dl.log")
    dbm._token.update(value="", expires=0.0)


def _mock(handler, monkeypatch):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(wrapped)
    monkeypatch.setattr(dbm, "_client", lambda **kw: httpx.AsyncClient(transport=transport, **kw))
    return seen


def _listing(request):
    if request.url.path == "/api/v1/access_token":
        return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
    return httpx.Response(200, json={"data": {"children": [{"data": {"id": "a"}}], "after": "t3_a"}})


async def test_fetch_gets_app_only_token_and_reuses_it(monkeypatch):
    seen = _mock(_listing, monkeypatch)
    posts, after = await dbm.fetch_posts()
    await dbm.fetch_posts()
    assert posts == [{"id": "a"}] and after == "t3_a"
    token_calls = [r for r in seen if r.url.path == "/api/v1/access_token"]
    assert len(token_calls) == 1
    assert b"grant_type=client_credentials" in token_calls[0].content
    assert token_calls[0].headers["Authorization"].startswith("Basic ")
    api = [r for r in seen if r.url.host == "oauth.reddit.com"]
    assert all(r.headers["Authorization"] == "Bearer tok-1" for r in api)


async def test_401_renews_the_token_once(monkeypatch):
    tokens = iter(["old", "new"])

    def handler(request):
        if request.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": next(tokens), "expires_in": 3600})
        if request.headers["Authorization"] == "Bearer old":
            return httpx.Response(401)
        return httpx.Response(200, json={"data": {"children": [], "after": None}})

    _mock(handler, monkeypatch)
    posts, after = await dbm.fetch_posts()
    assert posts == [] and after == ""
    assert dbm._token["value"] == "new"


async def test_missing_credentials_fetches_nothing(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_SECRET")
    seen = _mock(_listing, monkeypatch)
    assert await dbm.fetch_posts() == ([], "")
    assert not [r for r in seen if r.url.host == "oauth.reddit.com"]


async def test_image_download_never_sends_the_token(monkeypatch, tmp_path):
    dbm._token.update(value="tok-1", expires=9e18)
    seen = _mock(lambda r: httpx.Response(200, content=b"png", headers={"content-type": "image/png"}),
                 monkeypatch)
    assert await dbm.download_image("https://i.imgur.com/x.png", tmp_path / "x.png")
    assert "Authorization" not in seen[0].headers


def test_log_survives_a_locked_file(monkeypatch, tmp_path):
    monkeypatch.setattr(dbm, "LOG_FILE", tmp_path)  # a directory: open() raises
    dbm.log("still running")
