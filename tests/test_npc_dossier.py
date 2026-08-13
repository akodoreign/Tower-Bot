"""Regressions for NPC casting and the dossier that feeds module dialog.

Module dialog read dry because the generator knew four thin fields about the
speaker. Worse, missions carry a free-text contact ("Guild Liaison Varek at
Ironhold Outpost") and the old lookup was exact-name only, so it matched nothing
and the model improvised for a person with no past.
"""
from __future__ import annotations

import pytest

from src.npc_dossier import _plain, _strip_contact_string


# ---------------------------------------------------------------------------
# Contact-string parsing -- the reason casting used to fail
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Guild Liaison Varek at Ironhold Outpost", "Varek"),
    ("Warden Kree Scorch", "Kree Scorch"),
    ("Sergeant Jax Ironclaw at the Ash Gate", "Jax Ironclaw"),
    ("Quartermaster Hale of the Iron Fang Consortium", "Hale"),
    ("Brother Thane", "Thane"),
    ("Kree Scorch", "Kree Scorch"),
])
def test_contact_strings_reduce_to_a_name(raw, expected):
    assert _strip_contact_string(raw) == expected


def test_blank_contact_is_not_a_name():
    assert _strip_contact_string("") == ""
    assert _strip_contact_string("   ") == ""


# ---------------------------------------------------------------------------
# Presentation must not leak into character material
# ---------------------------------------------------------------------------

def test_bulletin_formatting_is_stripped_for_the_dossier():
    """mission_outcomes.notable_moments stores the bulletin AS POSTED to Discord."""
    posted = ("\U0001f3c6 **CONTRACT COMPLETE — Snatch It Back**  \n"
              "*Fracture Line Co. has returned.* They reclaimed the core.")
    out = _plain(posted)
    assert "**" not in out and "*" not in out
    assert "\U0001f3c6" not in out
    assert "CONTRACT COMPLETE" in out
    assert "reclaimed the core" in out


def test_plain_respects_a_limit():
    assert len(_plain("x" * 500, 120)) <= 120


# ---------------------------------------------------------------------------
# Casting resolution
# ---------------------------------------------------------------------------

def _roster(monkeypatch, rows):
    """Point npc_dossier's queries at a fixed roster."""
    import src.npc_dossier as nd

    def fake_query(sql, params=()):
        low = sql.lower()
        if "from npcs where name = %s" in low:
            return [r for r in rows if r["name"] == params[0]][:1]
        if "lower(name) = lower(" in low:
            return [r for r in rows if r["name"].lower() == str(params[0]).lower()][:1]
        if "name like" in low:
            needle = str(params[0]).strip("%").lower()
            return [r for r in rows if needle in r["name"].lower()][:5]
        if "from npcs where status = %s" in low:
            return [r for r in rows if r.get("status") == "alive"]
        return []

    monkeypatch.setattr(nd, "raw_query", fake_query)
    return nd


ROSTER = [
    {"id": 253, "name": "Kree Scorch", "faction": "Wardens of Ash", "status": "alive"},
    {"id": 91, "name": "Elara Ironclaw", "faction": "Iron Fang Syndicate", "status": "alive"},
    {"id": 12, "name": "Varek Thorne", "faction": "Deepvein Extractors", "status": "alive"},
]


def test_titles_and_places_do_not_block_a_real_match(monkeypatch):
    nd = _roster(monkeypatch, ROSTER)
    assert nd.resolve_npc("Warden Kree Scorch")["name"] == "Kree Scorch"
    assert nd.resolve_npc("Guild Liaison Varek at Ironhold Outpost")["name"] == "Varek Thorne"


def test_a_shared_surname_alone_is_not_a_match(monkeypatch):
    """'Jax Ironclaw' is a DIFFERENT person from 'Elara Ironclaw'.

    Silently casting her would put the wrong face, faction and history into the
    scene -- worse than falling back to the employing faction.
    """
    nd = _roster(monkeypatch, ROSTER)
    assert nd.resolve_npc("Sergeant Jax Ironclaw at the Ash Gate") is None


def test_one_token_plus_matching_faction_is_enough(monkeypatch):
    nd = _roster(monkeypatch, ROSTER)
    assert nd.resolve_npc("Kree", faction="Wardens of Ash")["name"] == "Kree Scorch"


def test_placeholder_contacts_resolve_to_nobody(monkeypatch):
    nd = _roster(monkeypatch, ROSTER)
    for junk in ("", "your contact", "unknown", "None", "n/a"):
        assert nd.resolve_npc(junk) is None


# ---------------------------------------------------------------------------
# The dossier itself
# ---------------------------------------------------------------------------

def test_dossier_carries_what_makes_a_person_playable(monkeypatch):
    import src.npc_dossier as nd

    npc = {
        "id": 253, "name": "Kree Scorch", "faction": "Wardens of Ash",
        "rank": "Warden", "role": "Patrols the Smoldering Quarter",
        "species": "Kobold",
        "quote": "The rifts are just mirrors. And mine's got a body missing.",
        "motivation": "Wants promotion, but secretly hunts a missing brother.",
        "secret": "Their brother defected to the Serpent Choir.",
        "oracle_notes": "Buried rage, and grief he cannot place.",
        "relationships": "Tense rivalry with Warden Jax Ironclaw.",
        "party_name": "",
    }
    monkeypatch.setattr(nd, "_history", lambda *a, **k: [
        {"event_date": "2026-05-20", "event_type": "injured",
         "body": "Took a rift burn holding the Ash Gate."}])
    monkeypatch.setattr(nd, "_revealed", lambda *a, **k: [])
    monkeypatch.setattr(nd, "_faction_standing", lambda *a, **k: {
        "leader": "Captain Havel Korin", "motto": "Hold the Line.",
        "reputation_score": 2, "tier": "Liked", "alignment": "Lawful Neutral"})
    monkeypatch.setattr(nd, "_recent_consequences", lambda *a, **k: [
        {"mission_title": "Hollow Grind Healer", "result": "completed",
         "notable_moments": "One member was lost to the refinery.",
         "key_decisions": "", "loose_threads": "The Wardens owe a debt.",
         "npcs_killed": ""}])

    block = nd.dossier_block({"id": 1, "faction": "Wardens of Ash"}, npc)

    # The material a performer actually needs.
    assert "Kree Scorch" in block
    assert "missing brother" in block
    assert "Jax Ironclaw" in block
    assert "Hold the Line." in block
    assert "rift burn" in block
    assert "Hollow Grind Healer" in block          # butterfly effect reaching dialog
    assert "The Wardens owe a debt." in block
    # The secret must be present but explicitly fenced.
    assert "Serpent Choir" in block
    assert "never say outright" in block


def test_dossier_is_empty_when_nobody_is_cast(monkeypatch):
    import src.npc_dossier as nd
    monkeypatch.setattr(nd, "cast_mission_contact", lambda m: None)
    assert nd.dossier_block({"id": 1, "contact": "nobody at all"}) == ""
