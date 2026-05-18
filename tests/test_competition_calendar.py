from datetime import datetime, timedelta

import src.competitions.bracket_engine as bracket_engine
import src.faction_calendar as faction_calendar


def test_competition_round_waits_for_posted_pc_mission(monkeypatch):
    bracket = {
        "round": 1,
        "matches": [
            {
                "a": "Asha Vale",
                "a_type": "pc",
                "b": "Davan Corst",
                "b_type": "npc",
                "round": 1,
                "scheduled": datetime.now().isoformat(),
                "status": "mission_posted",
                "winner": None,
                "mission_id": 123,
            },
            {
                "a": "Ilse Wren",
                "a_type": "npc",
                "b": "Pell the Twice-Broken",
                "b_type": "npc",
                "round": 1,
                "scheduled": datetime.now().isoformat(),
                "status": "pending",
                "winner": None,
                "mission_id": None,
            },
        ],
        "history": [],
    }
    advanced = {"called": False}
    saved = {}

    monkeypatch.setattr(
        bracket_engine,
        "_load_competition",
        lambda comp_id: {"id": comp_id, "bracket": bracket},
    )
    monkeypatch.setattr(bracket_engine, "raw_execute", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        bracket_engine,
        "_advance_to_next_round",
        lambda comp_id, bracket: advanced.update(called=True),
    )
    monkeypatch.setattr(
        bracket_engine,
        "_save_bracket",
        lambda comp_id, bracket: saved.update(bracket=bracket),
    )

    npc_match = bracket["matches"][1]
    bracket_engine._record_match_result(1, npc_match, "Ilse Wren")

    assert not advanced["called"]
    assert saved["bracket"]["matches"][0]["status"] == "mission_posted"
    assert saved["bracket"]["matches"][1]["status"] == "complete"


def test_calendar_resolves_past_unannounced_events(monkeypatch):
    event = {
        "faction": "Glass Sigil",
        "type": "Anomaly Symposium",
        "emoji": "",
        "description": "A finding needs review.",
        "event_date": (datetime.now() - timedelta(hours=2)).isoformat(),
        "announced": False,
        "resolved": False,
        "mission_spawned": False,
    }
    saved = []
    rep = []

    monkeypatch.setattr(faction_calendar, "_load_calendar", lambda: [event])
    monkeypatch.setattr(faction_calendar, "_top_up_calendar", lambda events: events)
    monkeypatch.setattr(faction_calendar, "_save_event", lambda ev: saved.append(dict(ev)))
    monkeypatch.setattr(
        faction_calendar,
        "_apply_reputation_shift",
        lambda faction, event_type: rep.append((faction, event_type)),
    )

    outputs = faction_calendar.tick_calendar()

    assert outputs == [{"type": "result", "event": event}]
    assert event["announced"] is True
    assert event["resolved"] is True
    assert saved and saved[0]["resolved"] is True
    assert rep == [("Glass Sigil", "Anomaly Symposium")]
