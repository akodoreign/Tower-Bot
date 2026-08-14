"""Regressions for the relationship graph, grief, and coming back from the dead.

The world only ever recorded violence and career (injury 225, death 128,
promotion 12). 128 NPCs had died and nobody had mourned one, because nothing in
the schema could say who would miss them.

Death here is provisional: raise, resurrection, reincarnation, undead, and the
doppelganger wearing their face all exist. A bond therefore must NOT close on
death -- it becomes a motive. Only the Tower taking the soul ends it.
"""
from __future__ import annotations

import pytest

import src.npc_bonds as nb


@pytest.fixture
def graph(monkeypatch):
    """In-memory stand-in for npc_bonds + npcs + npc_history."""
    state = {
        "bonds": [],      # dicts mirroring npc_bonds rows
        "history": [],    # (npc_id, body, date, event_type)
        "npcs": {
            1: {"id": 1, "name": "Sera Vane", "status": "dead", "faction": "Glass Sigil"},
            2: {"id": 2, "name": "Mari Fen", "status": "alive", "faction": "Glass Sigil"},
            3: {"id": 3, "name": "Karghul Vorn", "status": "alive", "faction": "Iron Fang"},
        },
    }

    def add_bond(a, b, t, *, strength=50, note="", reciprocal=True):
        state["bonds"].append({
            "npc_a_id": a, "npc_b_id": b, "bond_type": t, "strength": strength,
            "status": "active", "stance": None,
            "other_name": state["npcs"][b]["name"],
            "other_status": state["npcs"][b]["status"],
        })
        if reciprocal and t in nb.RECIPROCAL:
            state["bonds"].append({
                "npc_a_id": b, "npc_b_id": a, "bond_type": nb.RECIPROCAL[t],
                "strength": strength, "status": "active", "stance": None,
                "other_name": state["npcs"][a]["name"],
                "other_status": state["npcs"][a]["status"],
            })
        return True

    def get_bonds(npc_id, *, active_only=True):
        return [b for b in state["bonds"]
                if b["npc_a_id"] == npc_id
                and (b["status"] == "active" or not active_only)]

    def fake_execute(sql, params=()):
        low = " ".join(sql.lower().split())
        if "set status='mourning'" in low:
            stance, dead_id, surv_id = params[0], params[1], params[2]
            for b in state["bonds"]:
                if {b["npc_a_id"], b["npc_b_id"]} == {dead_id, surv_id}:
                    b["status"], b["stance"] = "mourning", stance
        elif "set status=%s, stance=null, ended_at=null" in low:
            status, a, b_id = params[0], params[1], params[2]
            for b in state["bonds"]:
                if {b["npc_a_id"], b["npc_b_id"]} == {a, b_id}:
                    b["status"], b["stance"] = status, None
        elif "set status='severed'" in low:
            npc_id = params[0]
            for b in state["bonds"]:
                if npc_id in (b["npc_a_id"], b["npc_b_id"]):
                    b["status"], b["stance"] = "severed", None
        return 1

    def fake_query(sql, params=()):
        low = " ".join(sql.lower().split())
        if "b.status = 'mourning'" in low and "b.npc_a_id = %s" in low:
            return [b for b in state["bonds"]
                    if b["npc_a_id"] == params[0] and b["status"] == "mourning"]
        if "b.status in ('mourning','active')" in low:
            return [b for b in state["bonds"]
                    if b["npc_a_id"] == params[0]
                    and b["status"] in ("mourning", "active")]
        return []

    def fake_hist(npc_id, body, event_date=None, event_type=""):
        state["history"].append((npc_id, body, event_date, event_type))

    monkeypatch.setattr(nb, "add_bond", add_bond)
    monkeypatch.setattr(nb, "get_bonds", get_bonds)
    monkeypatch.setattr(nb, "raw_execute", fake_execute)
    monkeypatch.setattr(nb, "raw_query", fake_query)

    import src.db_api as db_api
    monkeypatch.setattr(db_api, "add_npc_history_event", fake_hist)

    state["add_bond"] = add_bond
    return state


# ---------------------------------------------------------------------------
# Grief
# ---------------------------------------------------------------------------

def test_death_records_grief_and_does_not_close_the_bond(graph):
    graph["add_bond"](1, 2, "spouse", strength=90)

    mourners = nb.bereave(1, "Sera Vane", "rift collapse")

    assert [m["name"] for m in mourners] == ["Mari Fen"]
    assert mourners[0]["stance"] == nb.STANCE_SEEK
    assert "Widowed" in mourners[0]["grief"]

    # The bond is mourning, NOT ended -- the soul is still in play.
    statuses = {b["status"] for b in graph["bonds"]}
    assert statuses == {"mourning"}
    assert "ended" not in statuses and "severed" not in statuses


def test_grief_reaches_npc_history_with_a_real_event_type(graph):
    """The 4-arg call used to raise TypeError into a swallowing except, so grief
    was silently never written at all."""
    graph["add_bond"](1, 2, "spouse")
    nb.bereave(1, "Sera Vane")

    assert graph["history"], "no grief event was recorded"
    npc_id, body, _date, etype = graph["history"][0]
    assert npc_id == 2
    assert etype == "grief"          # not the inferred catch-all "event"
    assert "Sera Vane" in body


def test_enemies_want_the_grave_to_hold(graph):
    graph["add_bond"](1, 3, "enemy", strength=70)
    mourners = nb.bereave(1, "Sera Vane")
    assert mourners[0]["stance"] == nb.STANCE_GONE
    assert "did not feel like winning" in mourners[0]["grief"]


def test_closest_bond_is_reported_first(graph):
    graph["add_bond"](1, 3, "enemy", strength=99)
    graph["add_bond"](1, 2, "spouse", strength=50)
    mourners = nb.bereave(1, "Sera Vane")
    # A spouse outranks a high-strength enemy for who speaks at the funeral.
    assert mourners[0]["bond_type"] == "spouse"


# ---------------------------------------------------------------------------
# Coming back -- and how you come back matters
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind,expect_status,needle", [
    ("raise",          "active",   "got them back"),
    ("resurrection",   "active",   "came back whole"),
    ("reincarnation",  "changed",  "stranger's face"),
    ("undead",         "haunted",  "put them back in the grave"),
    ("doppelganger",   "impostor", "wearing"),
])
def test_return_kind_decides_what_the_bond_becomes(graph, kind, expect_status, needle):
    graph["add_bond"](1, 2, "spouse", strength=90)
    nb.bereave(1, "Sera Vane")

    notes = nb.restore_on_return(1, "Sera Vane", kind)

    assert notes and needle in notes[0]
    assert {b["status"] for b in graph["bonds"]} == {expect_status}
    assert graph["history"][-1][3] == "return"


def test_only_the_tower_actually_ends_a_bond(graph):
    graph["add_bond"](1, 2, "spouse", strength=90)
    nb.bereave(1, "Sera Vane")
    assert {b["status"] for b in graph["bonds"]} == {"mourning"}

    nb.sever_on_tower_loss(1, "Sera Vane")

    assert {b["status"] for b in graph["bonds"]} == {"severed"}
    assert graph["history"][-1][3] == "soul_lost"
    assert "not coming back" in graph["history"][-1][1]


# ---------------------------------------------------------------------------
# Seeding from prose must not invent warmth
# ---------------------------------------------------------------------------

def test_unreadable_ties_are_acquaintances_not_friends(monkeypatch):
    """"she removed him from leadership cleanly" is the Iron Fang civil war.

    The old default filed it as a friendship.
    """
    roster = [
        {"id": 1, "name": "Sera Voss", "faction": "Iron Fang Syndicate",
         "relationships": "Serrik Dhal - she removed him from leadership cleanly."},
        {"id": 2, "name": "Serrik Dhal", "faction": "Iron Fang Consortium",
         "relationships": "Shares a wall with Quiet Yarrow."},
        {"id": 3, "name": "Quiet Yarrow", "faction": "Glass Sigil",
         "relationships": ""},
    ]
    monkeypatch.setattr(nb, "_roster", lambda: roster)
    monkeypatch.setattr(nb, "add_bond", lambda *a, **k: True)

    found = {(f["a"], f["b"]): f["bond_type"] for f in nb.seed_from_relationships(True)}

    assert found[("Sera Voss", "Serrik Dhal")] == "enemy"
    assert found[("Serrik Dhal", "Quiet Yarrow")] == "acquaintance"


# ---------------------------------------------------------------------------
# Unrequited love is the one bond that must never be mirrored
# ---------------------------------------------------------------------------

def test_unrequited_is_never_reciprocated():
    """Mari Fen keeps the Adventurers Guild running and carries feelings for two
    people who do not carry them back. A mirrored row would make it mutual, which
    is the opposite of the thing."""
    assert "unrequited" not in nb.RECIPROCAL


# ---------------------------------------------------------------------------
# The Unknown Party are the best of the best
# ---------------------------------------------------------------------------

def test_unknown_party_is_recognised():
    from src.npc_lifecycle import is_unknown_party_member
    for name in ("Sable", "The Mute", "The Ward", "Carrion", "Locket"):
        assert is_unknown_party_member(name)
        assert is_unknown_party_member(name.lower())
    assert not is_unknown_party_member("Some Random Thug")


def test_injury_recovery_odds_favour_the_unknown_party():
    """A flat 10% death on every injury tick had killed them repeatedly --
    The Ward died and was resurrected five times."""
    import inspect
    from src import npc_lifecycle

    src = inspect.getsource(npc_lifecycle.apply_npc_event)
    assert "is_unknown_party_member" in src, "injury tick has no Unknown Party guard"
    assert "0.98" in src, "Unknown Party recovery odds not raised"


def test_random_death_cannot_touch_the_unknown_party():
    import inspect
    from src import npc_lifecycle

    src = inspect.getsource(npc_lifecycle.apply_npc_event)
    guard = src.split("event == \"death\"")
    # Two guards must exist: faction leaders AND the Unknown Party.
    assert len(guard) >= 3, "expected both a leader guard and an Unknown Party guard"


# ---------------------------------------------------------------------------
# Unrequited: it may be HINTED at, never declared. That is the definition.
# ---------------------------------------------------------------------------

def test_unrequited_is_never_mirrored():
    """Mirroring it back would make it mutual -- the opposite of what it means."""
    from src.npc_bonds import RECIPROCAL
    assert "unrequited" not in RECIPROCAL


def test_unrequited_carries_a_prose_directive():
    """Handed over as a bare label, a model substitutes a relationship word it
    knows: an obituary read `unrequited: Aldric Vane` off Mari Fen's dossier and
    called her his spouse. The label must arrive with instructions."""
    from src.npc_bonds import bond_note

    note = bond_note("unrequited")
    assert note, "unrequited must carry a directive"
    assert "never" in note.lower()
    # It must permit the hint, not forbid the feeling entirely.
    assert "hint" in note.lower()
    # Ordinary ties need no special handling.
    assert bond_note("spouse") == ""


def test_obituary_never_names_an_unrequited_tie():
    """'their {bond_type}' rendered as 'their unrequited' -- not English, and an
    invitation to swap in a word that is."""
    import inspect
    from src import tower_news_voices

    src = inspect.getsource(tower_news_voices.obituary)
    assert 'bond_type == "unrequited"' in src, "obituary does not special-case unrequited"
    assert "never returned" in src
    # The piece must still be allowed to imply it.
    assert "do not name it" in src or "never name" in src


def test_a_dice_roll_cannot_make_unrequited_mutual():
    """If it ever becomes mutual that is a deliberate story beat, not a nightly
    50/50 that leaves the one-sided row sitting underneath it."""
    import inspect
    from src import npc_bonds

    src = inspect.getsource(npc_bonds.social_tick)
    assert "_unrequited_between" in src, "courtship tick can silently requite a one-sided bond"
