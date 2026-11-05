"""Dashboard refuses cross-site writes, DNS rebinding and PIN-free LAN access."""
import pytest

import Webpage.app as dash

LAN = {"REMOTE_ADDR": "192.168.1.50"}


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setenv("DASHBOARD_EXTERNAL_PIN", "135790")
    monkeypatch.delenv("DASHBOARD_TRUSTED_NETS", raising=False)
    monkeypatch.delenv("DASHBOARD_ALLOWED_ORIGINS", raising=False)
    dash._pin_failures.clear()
    dash._pin_global_failures.clear()
    return dash.app.test_client()


def _bug(c, **kw):
    return c.post("/api/log-bug", json={}, **kw).status_code   # 400 = reached the handler


def test_same_origin_write_from_this_pc_is_allowed(c):
    assert _bug(c, headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}) == 400


def test_non_browser_write_from_this_pc_is_allowed(c):
    assert _bug(c) == 400


@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
])
def test_cross_site_write_is_refused(c, headers):
    assert _bug(c, headers=headers) == 403


def test_cross_site_text_plain_post_is_refused(c):
    # The classic no-preflight CSRF: force=True would otherwise parse this as JSON.
    r = c.post("/api/log-bug", data='{"message": "x"}', content_type="text/plain",
               headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_tunnel_write_from_the_real_site_reaches_the_pin_check(c):
    headers = {"CF-Ray": "x", "Host": "dashboard.tower-bot.com",
               "Origin": "https://dashboard.tower-bot.com", "X-Dashboard-Pin": "135790"}
    assert _bug(c, headers=headers) == 400


def test_dns_rebinding_host_is_refused_even_for_reads(c):
    assert c.get("/api/view-mode", headers={"Host": "evil.example:5001"}).status_code == 403


def test_allowed_origins_env(c, monkeypatch):
    monkeypatch.setenv("DASHBOARD_ALLOWED_ORIGINS", "http://127.0.0.1:8188")
    assert _bug(c, headers={"Origin": "http://127.0.0.1:8188"}) == 400


def test_lan_device_needs_the_pin(c):
    assert c.get("/api/view-mode", environ_base=LAN).get_json() == {"readonly": True}
    assert _bug(c, environ_base=LAN) == 403
    assert _bug(c, environ_base=LAN, headers={"X-Dashboard-Pin": "135790"}) == 400


def test_trusted_lan_is_local(c, monkeypatch):
    monkeypatch.setenv("DASHBOARD_TRUSTED_NETS", "192.168.1.0/24")
    assert c.get("/api/view-mode", environ_base=LAN).get_json() == {"readonly": False}


def test_lan_cannot_fake_cloudflare_ip_to_dodge_lockout(c):
    with dash.app.test_request_context("/", environ_base=LAN,
                                       headers={"CF-Ray": "x", "CF-Connecting-IP": "203.0.113.9"}):
        assert dash._client_ip() == "192.168.1.50"


def test_no_wildcard_cors(c):
    assert "Access-Control-Allow-Origin" not in c.get("/api/view-mode").headers
