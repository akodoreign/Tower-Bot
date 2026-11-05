"""Dashboard PIN cookie: a correct PIN is remembered for DASHBOARD_PIN_COOKIE_HOURS."""
import time

import pytest
from flask import Response

import Webpage.app as dash

PIN = "135790"
CF = {"CF-Ray": "x"}
# Tunnel requests reach the dashboard from cloudflared on this PC.
TUNNEL = {"REMOTE_ADDR": "127.0.0.1"}


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    monkeypatch.setenv("DASHBOARD_EXTERNAL_PIN", PIN)
    monkeypatch.delenv("DASHBOARD_PIN_COOKIE_HOURS", raising=False)
    dash._pin_failures.clear()
    dash._pin_global_failures.clear()


def _login_cookie() -> str:
    """Send the PIN once and return the Set-Cookie header the dashboard answers with."""
    with dash.app.test_request_context("/api/characters", headers={**CF, "X-Dashboard-Pin": PIN}):
        assert dash._pin_ok()
        return dash._set_pin_cookie(Response()).headers.get("Set-Cookie", "")


def _guess(pin: str, ip: str = "203.0.113.5", cookie: str = "") -> bool:
    headers = {**CF, "CF-Connecting-IP": ip, "X-Dashboard-Pin": pin}
    if cookie:
        headers["Cookie"] = f"tb_pin={cookie}"
    with dash.app.test_request_context("/", headers=headers, environ_base=TUNNEL):
        return dash._pin_ok()


def _cookie_value(set_cookie: str) -> str:
    return set_cookie.split(";", 1)[0].split("=", 1)[1]


def test_correct_pin_sets_seven_hour_strict_httponly_cookie():
    header = _login_cookie()
    assert header.startswith("tb_pin=")
    assert "Max-Age=25200" in header
    assert "HttpOnly" in header and "Secure" in header and "SameSite=Strict" in header
    assert PIN not in header


def test_cookie_alone_is_accepted():
    value = _cookie_value(_login_cookie())
    with dash.app.test_request_context("/", headers={**CF, "Cookie": f"tb_pin={value}"}):
        assert dash._pin_ok({})


def test_wrong_pin_sets_no_cookie_and_is_denied():
    with dash.app.test_request_context("/", headers={**CF, "X-Dashboard-Pin": "000000"}):
        assert not dash._pin_ok()
        assert "Set-Cookie" not in dash._set_pin_cookie(Response()).headers


def test_pin_in_query_string_is_ignored():
    with dash.app.test_request_context("/", query_string={"pin": PIN}, headers=CF):
        assert not dash._pin_ok()


def test_five_wrong_guesses_lock_that_address_out():
    for _ in range(dash.PIN_MAX_FAILS):
        assert not _guess("000000")
    assert not _guess(PIN)                      # even the right PIN, while locked
    assert _guess(PIN, ip="198.51.100.7")       # other players are unaffected


def test_lockout_expires(monkeypatch):
    for _ in range(dash.PIN_MAX_FAILS):
        _guess("000000")
    later = time.time() + dash.PIN_FAIL_WINDOW + 1
    monkeypatch.setattr(dash.time, "time", lambda: later)
    assert _guess(PIN)


def test_valid_cookie_still_works_while_locked_out():
    cookie = _cookie_value(_login_cookie())
    for _ in range(dash.PIN_MAX_FAILS):
        _guess("000000")
    assert _guess(PIN, cookie=cookie)


def test_guessing_spread_over_many_addresses_hits_the_global_cap():
    for i in range(dash.PIN_GLOBAL_MAX):
        _guess("000000", ip=f"10.0.{i // 250}.{i % 250}")
    assert not _guess(PIN, ip="198.51.100.7")


def test_locked_out_request_answers_429_and_logs_no_query(capsys):
    for _ in range(dash.PIN_MAX_FAILS):
        _guess("000000")
    c = dash.app.test_client()
    r = c.post("/api/log-bug?pin=000000", json={"message": "x"},
               headers={**CF, "CF-Connecting-IP": "203.0.113.5", "X-Dashboard-Pin": PIN})
    assert r.status_code == 429 and r.get_json()["pin_locked"]
    err = capsys.readouterr().err
    assert '"POST /api/log-bug HTTP/1.1" 429' in err
    assert "pin=" not in err


def test_expired_or_forged_cookie_is_denied():
    old = int(time.time()) - 8 * 3600
    expired = f"{old}.{dash._pin_cookie_sig(PIN, old)}"
    now = int(time.time())
    forged = f"{now}.{'0' * 64}"
    for value in (expired, forged, "garbage"):
        with dash.app.test_request_context("/", headers={**CF, "Cookie": f"tb_pin={value}"}):
            assert not dash._pin_ok({})


def test_changing_the_pin_voids_cookies(monkeypatch):
    value = _cookie_value(_login_cookie())
    monkeypatch.setenv("DASHBOARD_EXTERNAL_PIN", "246802")
    with dash.app.test_request_context("/", headers={**CF, "Cookie": f"tb_pin={value}"}):
        assert not dash._pin_ok({})


def test_cookie_does_not_bypass_fail_closed(monkeypatch):
    value = _cookie_value(_login_cookie())
    monkeypatch.delenv("DASHBOARD_EXTERNAL_PIN")
    with dash.app.test_request_context("/", headers={**CF, "Cookie": f"tb_pin={value}"}):
        assert not dash._pin_ok({})
