"""Internet visitors (players) don't get DM-only material; this PC still does."""
import pytest

import Webpage.app as dash

TUNNEL = {"CF-Ray": "x", "Host": "dashboard.tower-bot.com"}
REMOTE = {"REMOTE_ADDR": "127.0.0.1"}            # cloudflared connects locally


@pytest.fixture
def modules(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    mod = root / "generated_modules" / "CASE_1"
    (mod / "maps").mkdir(parents=True)
    for name in ("index.html", "players_guide.html", "maps.html", "dm_guide.html", "module.html",
                 "session.html", "chart_pack.html", "npcs.html", "chapter_1.html",
                 "box_set.zip", "mission.json", "battle_map.vtt.json", "maps_manifest.json"):
        (mod / name).write_text("x", encoding="utf-8")
    (mod / "maps" / "R01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(dash, "PROJECT_ROOT", root)
    monkeypatch.setattr(dash, "MODULES_DIR", root / "generated_modules")
    monkeypatch.setattr(dash, "_MEDIA_ALLOWED_ROOTS", [root / "generated_modules"])
    return dash.app.test_client()


@pytest.mark.parametrize("name, player_ok", [
    ("index.html", True), ("players_guide.html", True), ("maps.html", True),
    ("maps/R01.png", True), ("battle_map.vtt.json", True), ("maps_manifest.json", True),
    ("dm_guide.html", False), ("module.html", False), ("session.html", False),
    ("chart_pack.html", False), ("npcs.html", False), ("chapter_1.html", False),
    ("box_set.zip", False), ("mission.json", False),
])
def test_module_files_for_players(modules, name, player_ok):
    r = modules.get(f"/modules/CASE_1/{name}", headers=TUNNEL, environ_base=REMOTE)
    assert (r.status_code == 200) is player_ok
    assert modules.get(f"/modules/CASE_1/{name}").status_code == 200        # the DM's PC


def test_media_route_applies_the_same_rule(modules):
    url = "/media/project/generated_modules/CASE_1/dm_guide.html"
    assert modules.get(url, headers=TUNNEL, environ_base=REMOTE).status_code == 403
    assert modules.get(url).status_code == 200


def test_module_listing_hides_dm_files_from_players(modules):
    files = modules.get("/api/modules", headers=TUNNEL, environ_base=REMOTE).get_json()["modules"][0]["files"]
    assert "dm_guide.html" not in files and "box_set.zip" not in files
    assert "players_guide.html" in files
    local = modules.get("/api/modules").get_json()["modules"][0]["files"]
    assert "dm_guide.html" in local


def test_trusted_laptop_gets_dm_material(modules, monkeypatch):
    # The garage laptop: a trusted Wi-Fi address, browsing http://<pc>:5001/.
    monkeypatch.setenv("DASHBOARD_TRUSTED_NETS", "192.168.68.70/32")
    laptop = {"REMOTE_ADDR": "192.168.68.70"}
    page = {"Host": "192.168.68.61:5001", "Origin": "http://192.168.68.61:5001"}
    assert modules.get("/api/view-mode", environ_base=laptop, headers=page).get_json() == {"readonly": False}
    assert modules.get("/modules/CASE_1/dm_guide.html", environ_base=laptop, headers=page).status_code == 200
    assert modules.get("/api/logs", environ_base=laptop, headers=page).status_code == 200
    # A same-origin write from the laptop reaches the handler (400 = missing message), no PIN.
    assert modules.post("/api/log-bug", json={}, environ_base=laptop, headers=page).status_code == 400
    # Any other Wi-Fi device is still a player.
    other = {"REMOTE_ADDR": "192.168.68.80"}
    assert modules.get("/modules/CASE_1/dm_guide.html", environ_base=other, headers=page).status_code == 403


def test_trusting_all_192_168_covers_the_wifi_but_not_the_tunnel(modules, monkeypatch):
    monkeypatch.setenv("DASHBOARD_TRUSTED_NETS", "192.168.0.0/16")
    page = {"Host": "192.168.68.61:5001"}
    for addr in ("192.168.68.70", "192.168.71.200"):
        r = modules.get("/modules/CASE_1/dm_guide.html", environ_base={"REMOTE_ADDR": addr}, headers=page)
        assert r.status_code == 200
    # Tunnel visitors stay players even with the whole range trusted.
    assert modules.get("/modules/CASE_1/dm_guide.html", headers=TUNNEL, environ_base=REMOTE).status_code == 403
    # Outside 192.168 is still a player.
    assert modules.get("/modules/CASE_1/dm_guide.html", environ_base={"REMOTE_ADDR": "10.0.0.5"},
                       headers=page).status_code == 403


def test_log_is_dm_only():
    c = dash.app.test_client()
    r = c.get("/api/logs", headers=TUNNEL, environ_base=REMOTE)
    assert r.status_code == 403 and r.get_json()["dm_only"]


def test_npc_secrets_blank_for_players():
    row = {"id": None, "name": "Vex", "secret": "is the cult's treasurer",
           "oracle_notes": "lies about the ledger", "data_json": "{}"}
    with dash.app.test_request_context("/api/npcs", headers=TUNNEL, environ_base=REMOTE):
        npc = dash._serialize_npc(row)
    assert npc["secret"] == "" and npc["oracle_notes"] == ""
    with dash.app.test_request_context("/api/npcs", environ_base=REMOTE):
        npc = dash._serialize_npc(row)
    assert npc["secret"] == "is the cult's treasurer"
