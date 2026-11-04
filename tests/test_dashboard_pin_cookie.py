"""Dashboard PIN cookie: a correct PIN is remembered for DASHBOARD_PIN_COOKIE_HOURS."""
import time

import pytest
from flask import Response

import Webpage.app as dash

PIN = "135790"
CF = {"CF-Ray": "x"}


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    monkeypatch.setenv("DASHBOARD_EXTERNAL_PIN", PIN)
    monkeypatch.delenv("DASHBOARD_PIN_COOKIE_HOURS", raising=False)


def _login_cookie() -> str:
    """Send the PIN once and return the Set-Cookie header the dashboard answers with."""
    with dash.app.test_request_context("/api/characters", query_string={"pin": PIN}, headers=CF):
        assert dash._pin_ok(dash.request.args)
        return dash._set_pin_cookie(Response()).headers.get("Set-Cookie", "")


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
    with dash.app.test_request_context("/", query_string={"pin": "000000"}, headers=CF):
        assert not dash._pin_ok(dash.request.args)
        assert "Set-Cookie" not in dash._set_pin_cookie(Response()).headers


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
