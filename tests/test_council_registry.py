"""The Grand Council belongs in MySQL, not in Python literals and a JSON blob.

Two things had drifted out of the database:

  - The seats were hardcoded dicts, and the president literal read
    "Guildmaster Mari Fen" -- a title she has never held. She is rank Member and
    runs the Adventurers Guild front desk; Aldric Vane is the Guildmaster. A
    seat is held by a real person and changes hands, so it is a row.
  - `global_state['council_rulings']` was a 64KB JSON list of 110 rulings whose
    `votes_yes` / `votes_no` were name arrays. Rulings and votes are records
    that get counted, filtered and shown on the dashboard -- exactly the case
    the JSON reflex check exists for.
"""

import inspect

import pytest

from src import council_registry as cr
from src.agents import guild_council


# ---------------------------------------------------------------------------
# Seats
# ---------------------------------------------------------------------------

def test_seats_come_from_the_database():
    """The literals are seed data; the live roster is the table."""
    members_src = inspect.getsource(guild_council.council_members)
    pres_src = inspect.getsource(guild_council.council_president)
    assert "council_registry" in members_src
    assert "council_registry" in pres_src


def test_no_call_site_still_reads_the_literals():
    """Every consumer must go through the accessor, or a seat change in the DB
    silently fails to reach the vote."""
    src = inspect.getsource(guild_council)
    body = src.split("def council_president", 1)[1]
    # Past the accessor definitions, nothing should touch the raw literals.
    after_accessors = body.split("# ── Data Classes", 1)[-1]
    assert "COUNCIL_MEMBERS" not in after_accessors, "a call site still reads the literal member list"
    assert "COUNCIL_PRESIDENT" not in after_accessors, "a call site still reads the literal president"


def test_president_is_no_longer_mari_fen():
    """She was mislabelled Guildmaster here and nowhere else in the world."""
    pres = cr.get_president()
    if pres is None:
        pytest.skip("council_seats not seeded in this environment")
    assert "Mari Fen" not in pres["name"]
    assert pres["faction"], "president must carry a faction"


def test_president_is_seated_to_a_real_npc():
    """A seat tied to a bare string cannot reach a dossier, which is the whole
    reason the council sounds like people instead of a form."""
    pres = cr.get_president()
    if pres is None:
        pytest.skip("council_seats not seeded in this environment")
    assert pres.get("npc_id"), "president seat is not linked to an npcs row"


def test_seat_carries_every_prompt_field():
    """A seat missing agenda/bias/voice votes like a form letter."""
    pres = cr.get_president()
    if pres is None:
        pytest.skip("council_seats not seeded in this environment")
    for field in ("name", "faction", "title", "agenda", "bias", "voice"):
        assert pres.get(field), f"president seat missing {field}"


def test_retire_keeps_the_row():
    """Who sat on the council and when is world history, not a config typo."""
    src = inspect.getsource(cr.retire_seat)
    assert "UPDATE" in src and "active=0" in src
    assert "DELETE" not in src.upper()


# ---------------------------------------------------------------------------
# Rulings
# ---------------------------------------------------------------------------

def _code_only(src: str) -> str:
    """Strip comment lines -- a comment explaining what global_state USED to do
    is not the same as code that still writes it."""
    return "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )


def test_rulings_are_rows_not_a_blob():
    src = _code_only(inspect.getsource(guild_council.GuildCouncil._apply_passed_rulings))
    assert "record_ruling" in src, "rulings are not persisted as rows"
    assert "global_state" not in src, "still writing the JSON blob"
    assert "json.dumps" not in src


def test_decided_topics_no_longer_decode_json():
    src = inspect.getsource(guild_council.GuildCouncil._load_decided_topics)
    assert "recent_rulings" in src
    assert "json.loads" not in src


def test_recent_rulings_keeps_the_old_entry_shape():
    """Readers and templates should not have to be reshaped."""
    rows = cr.recent_rulings(limit=3)
    if not rows:
        pytest.skip("no rulings in this environment")
    for key in ("date", "topic", "proposal", "passed", "votes_yes", "votes_no"):
        assert key in rows[0], f"entry shape lost {key}"
    assert isinstance(rows[0]["votes_yes"], list)


def test_schema_uses_real_columns():
    """No JSON column smuggled into the new tables."""
    src = inspect.getsource(cr.ensure_schema)
    assert "council_seats" in src and "council_rulings" in src
    assert "council_ruling_votes" in src
    assert " JSON" not in src.upper().replace("_JSON", ""), "a JSON column crept back in"
