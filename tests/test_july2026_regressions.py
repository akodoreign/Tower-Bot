"""Regression tests for the July 2026 overhaul.

Each test pins a specific fix so it cannot silently regress. Grouped by system.
All run offline via the conftest fake-world fixtures — no MySQL, no Ollama, no
Mimir, no Discord.
"""
from __future__ import annotations

import asyncio
import importlib
import json

import pytest


# ---------------------------------------------------------------------------
# num_ctx fitting — the news-bulletin failure class
# ---------------------------------------------------------------------------

def _fit_ctx_of(module_name: str):
    mod = importlib.import_module(module_name)
    return getattr(mod, "_fit_ctx")


@pytest.mark.parametrize("module_name", [
    "src.mission_builder.first_contact_pipeline",
    "src.mission_builder.discovery_pipeline",
    "src.mission_builder.heist_pipeline",
    "src.mission_builder.rescue_pipeline",
    "src.mission_builder.negotiation_pipeline",
])
def test_fit_ctx_floors_and_caps(module_name):
    fit = _fit_ctx_of(module_name)
    assert fit("hello", 500) == 8192           # small prompt -> floor
    assert fit("x" * 120000, 2000) == 32768    # huge prompt -> cap
    # monotonic-ish: a bigger prompt never asks for a smaller window
    assert fit("x" * 40000, 1000) >= fit("x" * 4000, 1000)


# ---------------------------------------------------------------------------
# Generic-plan gate self-poisoning (6 pipelines)
# ---------------------------------------------------------------------------

def test_first_contact_gate_keeps_anchored_plan():
    fc = importlib.import_module("src.mission_builder.first_contact_pipeline")
    mission = {"title": "The Glasswing Refugees",
               "body": "Refugees near Market Square Garden. Iron Fang Syndicate circling."}
    ctx = fc._mission_context(mission)
    # sentence boundary must not be swallowed into a canon term
    assert "Market Square Garden" in ctx["canon_terms"]
    assert not any(". " in t for t in ctx["canon_terms"])
    # an anchored plan (>=2 canon terms) survives even if it also hits a marker
    fallback = fc._fallback_plan(mission, "refugees")
    anchored = {**fallback,
                "briefing": "Meet the Glasswing Refugees' elders at Market Square Garden "
                            "before the Iron Fang Syndicate does."}
    assert fc._is_generic_plan(anchored, ctx) is False
    # a truly generic, unanchored plan is still rejected
    junk = {"briefing": "Some strange people arrived. An unknown group needs help."}
    assert fc._is_generic_plan(junk, ctx) is True


@pytest.mark.parametrize("module_name", [
    "src.mission_builder.discovery_pipeline",
    "src.mission_builder.exploration_pipeline",
    "src.mission_builder.recovery_pipeline",
    "src.mission_builder.rescue_pipeline",
    "src.mission_builder.strange_occurrences_pipeline",
])
def test_gate_has_canon_anchor_override(module_name):
    """Every de-poisoned gate must short-circuit to 'not generic' at score>=3."""
    mod = importlib.import_module(module_name)
    src = importlib.import_module(module_name).__file__
    text = open(src, encoding="utf-8").read()
    assert "score >= 3" in text, f"{module_name} missing canon-anchor override"


# ---------------------------------------------------------------------------
# scene_dialogs literal-"None" foe leak
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("opp", ["None", "none", "N/A", "TBD", "unknown", "", None])
def test_scene_dialogs_sanitizes_none_foe(opp):
    from src.mission_builder import scene_dialogs
    npc = scene_dialogs._npc_context(
        {"title": "T", "faction": "Glass Sigil", "opposing_faction": opp})
    assert npc["antagonist_faction"] == "the opposition"


def test_scene_dialogs_keeps_real_foe():
    from src.mission_builder import scene_dialogs
    npc = scene_dialogs._npc_context(
        {"title": "T", "faction": "Glass Sigil", "opposing_faction": "Iron Fang Syndicate"})
    assert npc["antagonist_faction"] == "Iron Fang Syndicate"
    blob = json.dumps(scene_dialogs._fallback_module_dialog({"title": "T"}, npc))
    assert '"None"' not in blob and " None " not in blob


# ---------------------------------------------------------------------------
# Loot enrichment (treasure caching + Mimir item matching)
# ---------------------------------------------------------------------------

def test_loot_card_caches_package(fake_db):
    fake_db.rows_for("treasure_items", [])  # empty pools -> EC-only, deterministic
    from src import treasure
    mission = {"title": "T", "tier": "standard", "difficulty": 5}
    h1 = treasure.loot_card(mission)
    assert "_loot_pkg" in mission
    h2 = treasure.loot_card(mission)
    assert h1 == h2  # second render reuses the cached package


def test_enrich_mission_loot_matches_catalog(fake_mimir):
    fake_mimir.available = True
    fake_mimir.items = {"flame tongue": {"name": "Flame Tongue", "rarity": "rare", "type": "weapon"}}
    from src.mission_builder import mimir_module
    mission = {"_loot_pkg": {"ec": 100,
                             "magic": {"name": "Flame Tongue Longsword", "rarity": "rare",
                                       "item_type": "weapon", "effect": "flaming"}}}
    rewards = asyncio.run(mimir_module.enrich_mission_loot("mod-1", mission))
    assert rewards and rewards[0]["catalog_data"]["name"] == "Flame Tongue"
    assert ("mod-1", "Flame Tongue") in fake_mimir.added


def test_enrich_mission_loot_noops_without_lootable_slots(fake_mimir):
    fake_mimir.available = True
    from src.mission_builder import mimir_module
    assert asyncio.run(mimir_module.enrich_mission_loot("mod-1", {"_loot_pkg": {"ec": 50}})) == []
    assert asyncio.run(mimir_module.enrich_mission_loot("", {"_loot_pkg": {"magic": {"name": "X"}}})) == []


# ---------------------------------------------------------------------------
# Party lifecycle: mission casualties
# ---------------------------------------------------------------------------

def _load_party_lifecycle(fake_db, monkeypatch):
    fake_db.rows_for("FROM npcs WHERE party_name",
                     [{"name": "Korra Vex"}, {"name": "Tilda Marsh"}, {"name": "Grimthar Holt"}])
    fake_db.rows_for("SELECT id FROM party_profiles", [{"id": 7}])
    fake_db.rows_for("SELECT id FROM npcs WHERE name", [{"id": 9}])
    import types as _t
    npcl = _t.ModuleType("src.npc_lifecycle")
    npcl.wound_npc_in_combat = lambda name, cause="": True
    monkeypatch.setitem(__import__("sys").modules, "src.npc_lifecycle", npcl)
    import src.party_lifecycle as pl
    return importlib.reload(pl)


def test_casualties_skip_nonviolent_and_protected(fake_db, monkeypatch):
    pl = _load_party_lifecycle(fake_db, monkeypatch)
    assert pl.mission_party_casualties("Crew", {"type": "Negotiation"}, False) == \
        {"wounded": [], "destroyed": False}
    assert pl.mission_party_casualties("Unknown Party", {"type": "Battle"}, False) == \
        {"wounded": [], "destroyed": False}


def test_casualties_wound_and_wipeout(fake_db, monkeypatch):
    pl = _load_party_lifecycle(fake_db, monkeypatch)
    monkeypatch.setattr(pl.random, "random", lambda: 0.10)
    r = pl.mission_party_casualties("Crew", {"type": "Assault", "title": "Storm", "difficulty": 5}, False)
    assert len(r["wounded"]) == 1 and not r["destroyed"]
    # wipeout: failed, difficulty>=8, roll<0.04
    monkeypatch.setattr(pl.random, "random", lambda: 0.01)
    r = pl.mission_party_casualties("Crew", {"type": "Battle", "title": "Break", "difficulty": 9}, False)
    assert r["destroyed"] and len(r["wounded"]) == 3


# ---------------------------------------------------------------------------
# Restart storm caps
# ---------------------------------------------------------------------------

def test_npc_completions_cap(fake_db, fake_ollama, monkeypatch):
    monkeypatch.setenv("NPC_COMPLETIONS_PER_PASS", "3")
    import src.mission_board as mb
    from datetime import datetime, timedelta
    past = (datetime.utcnow() - timedelta(days=30)).isoformat()
    missions = [{"id": i, "title": f"C{i}", "faction": "Patchwork Saints", "tier": "standard",
                 "npc_claimed": True, "npc_complete_at": past, "npc_outcome": "complete",
                 "claim_party": f"Crew {i}", "type": "Gathering"} for i in range(6)]
    monkeypatch.setattr(mb, "_load_missions", lambda: missions)
    monkeypatch.setattr(mb, "_save_missions", lambda ms: None)

    async def fake_gen(prompt, **kw):
        return "The crew returned."
    monkeypatch.setattr(mb, "_generate", fake_gen)
    monkeypatch.setattr(mb, "_apply_mission_consequences", lambda *a, **kw: None)

    class LaxDict(dict):
        def __missing__(self, k):
            return ""
    rep = lambda *a, **kw: LaxDict(new_tier="Bronze", points=1)
    import src.faction_reputation as fr
    monkeypatch.setattr(fr, "on_npc_party_complete", rep)
    monkeypatch.setattr(fr, "on_npc_party_fail", rep)
    import src.party_profiles as pp
    monkeypatch.setattr(pp, "format_party_rank_change", lambda *a, **kw: "")

    class Ch:
        async def send(self, *a, **kw):
            return None
    asyncio.run(mb.check_npc_completions(Ch(), client=None))
    assert sum(1 for m in missions if m.get("resolved")) == 3


# ---------------------------------------------------------------------------
# Dashboard PIN fail-closed (security regression)
# ---------------------------------------------------------------------------

def test_dashboard_pin_fails_closed(monkeypatch):
    monkeypatch.delenv("DASHBOARD_EXTERNAL_PIN", raising=False)
    from Webpage.app import app
    c = app.test_client()
    cf = {"CF-Ray": "x"}
    # no PIN configured -> external actions denied, old public default rejected
    assert c.post("/api/claim-mission", json={"mission_id": 1, "pin": "86753"}, headers=cf).status_code == 403
    # generate-mission hard-blocked externally regardless
    assert c.post("/api/generate-mission", json={"pin": "86753"}, headers=cf).status_code == 403


def test_dashboard_local_not_pin_gated():
    from Webpage.app import app
    c = app.test_client()
    # no CF-Ray -> local; must reach the handler (400 missing id), never 403
    assert c.post("/api/claim-mission", json={}).status_code != 403
