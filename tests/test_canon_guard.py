"""The guild leaders keep getting deposed by prose. They stay deposed unless
something checks.

Real cases from `news_memory`, 2026-05 through 2026-08: the Guildmaster of the
Adventurers Guild "suspended for smuggling", the Senior Archivist "suspended
from the Glass Sigil", and "the late Sable" seven separate times for a woman who
is alive and protected. 19 of 2589 bulletins rewrote someone's standing.
"""

import pytest

from src import canon_guard


PEOPLE = {
    "aldric vane": {"name": "Aldric Vane", "faction": "Adventurers Guild",
                    "kind": "leader", "rank": "Guildmaster", "title": "Guildmaster"},
    "captain havel korin": {"name": "Captain Havel Korin", "faction": "Wardens of Ash",
                            "kind": "leader", "rank": "Captain", "title": "Captain"},
    "director myra kess": {"name": "Director Myra Kess", "faction": "Tower Authority",
                           "kind": "leader", "rank": "Director", "title": "Director"},
    "senior archivist pell": {"name": "Senior Archivist Pell", "faction": "Glass Sigil",
                              "kind": "leader", "rank": "Senior Archivist", "title": "Senior Archivist"},
    "sable": {"name": "Sable", "faction": "Unknown Party", "kind": "unknown_party"},
    "the ward": {"name": "The Ward", "faction": "Unknown Party", "kind": "unknown_party"},
}


@pytest.fixture(autouse=True)
def fixed_roster(monkeypatch):
    """Never let this suite touch the live database."""
    monkeypatch.setattr(canon_guard, "protected_people", lambda force=False: PEOPLE)


# --------------------------------------------------------------------------
# Must reject -- every one of these is a real bulletin the bot published
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # news_memory id=2589
    "**Senior Adventurer Aldric Vane has been suspended by the Guild after being "
    "found in possession of enchanted relics bound for the Ironworks Combine.**",
    # id=2579 -- an obituary for a living man
    "The Adventurers Guild confirms the death of **Aldric Vane**, former Guildmaster.",
    # id=2169
    "Alaric Stonemason (Argent Blades) killed Aldric Vane (Adventurers Guild) "
    "during a sanctioned fight at Scrapworks.",
    # id=2512
    "the late Aldric Vane's apprentice, Pip Wrenthorn, has gone missing.",
    # Senior Archivist Pell, suspended by prose
    "Senior Archivist Pell has been suspended from the Glass Sigil after an audit.",
    # the Unknown Party are not disposable
    "Sable was killed in the Warrens last night by a Black Flame enforcer.",
    "The incident occurred during a duel between *the late Sable* and Thorn Silverwing.",
    # quieter removals
    "Captain Havel Korin was quietly replaced as head of the Wardens of Ash.",
    "Director Myra Kess stepped down this morning amid the audit scandal.",
    "Aldric Vane faces expulsion for violating adventurer ethics.",
])
def test_rejects_status_changes(text):
    assert canon_guard.check(text), f"should have been rejected: {text[:70]}"


# --------------------------------------------------------------------------
# Must pass -- a guard that blocks ordinary drama is worse than no guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # the leader is the one DOING it
    "Captain Havel Korin arrested three smugglers at the Irondraft Docks.",
    "Sable cut down the enforcer before he reached the stairwell.",
    # commenting on someone else's downfall
    "Guildmaster Aldric Vane condemned the arrests and refused to release the contract.",
    # criticism is fair game -- only STANDING is fixed
    "Critics say Aldric Vane has grown remote, and the Guild's juniors are furious.",
    "Half the Glass Sigil wants Senior Archivist Pell gone, and says so loudly.",
    # someone unprotected dies
    "A dock supervisor was found dead near the Irondraft Docks; Havel Korin is investigating.",
    # ordinary business
    "Director Myra Kess signed the quarantine order over Wardens objections.",
])
def test_allows_ordinary_drama(text):
    assert not canon_guard.check(text), f"false positive: {canon_guard.check(text)}"


def test_the_ward_is_not_the_wardens():
    """'The Ward' matched inside 'The Wardens' and flagged six innocent bulletins."""
    assert not canon_guard.check(
        "The Wardens are investigating whether the murder is linked to the quarantine."
    )
    assert canon_guard.check("The Ward was killed during the raid.")


def test_possessive_still_matches():
    """The trailing boundary must not eat "Vane's" -- that is the exact phrasing."""
    assert canon_guard.check("Pip Wrenthorn, the late Aldric Vane's apprentice, is missing.")


def test_allow_exempts_the_subject():
    """An obituary is allowed to bury the person it is about, and nobody else."""
    text = "The Guild confirms the death of Aldric Vane. Sable was killed in the same raid."
    assert not canon_guard.check("The Guild confirms the death of Aldric Vane.",
                                 allow=["Aldric Vane"])
    still = canon_guard.check(text, allow=["Aldric Vane"])
    assert still and "Sable" in still[0]


def test_invented_spouse_is_rejected():
    """Mari Fen's bond is `unrequited`; an obituary called her his spouse."""
    assert canon_guard.check("Mari Fen - Aldric Vane's spouse - refuses to leave the hall.")


def test_protected_block_states_the_real_title():
    """The suspension bulletin called the Guildmaster a 'Senior Adventurer'."""
    block = canon_guard.protected_block()
    assert "Aldric Vane is the Guildmaster of the Adventurers Guild and is alive." in block
    assert "suspended" in block and "demoted" in block
    assert "Sable" in block  # the Unknown Party are named too


def test_empty_and_clean_text():
    assert canon_guard.check("") == []
    assert canon_guard.is_clean("The rain came early to the Ash Ring.")
    assert canon_guard.reject_reason("The rain came early.") == ""


# --------------------------------------------------------------------------
# Retraction convention
# --------------------------------------------------------------------------

def test_recent_memory_skips_retracted(monkeypatch):
    """A retracted bulletin must not come back as context -- that is the whole
    mechanism by which one invented suspension becomes the premise of the next
    six bulletins."""
    import inspect
    from src import tower_news_voices

    src = inspect.getsource(tower_news_voices._recent_memory)
    assert "retracted" in src.lower(), "_recent_memory does not filter retracted rows"
    assert "news_type" in src, "filter must key off news_type, not facts"


def test_voiced_write_gates_before_persisting():
    """Generate, gate, THEN persist -- persisting first would poison memory even
    if the bulletin were never posted."""
    import inspect
    from src import tower_news_voices

    src = inspect.getsource(tower_news_voices._write)
    gate_at = src.find("check(text")
    persist_at = src.find("add_news_entry")
    assert gate_at != -1, "_write does not call the canon gate"
    assert persist_at != -1
    assert gate_at < persist_at, "canon gate must run before add_news_entry"


def test_news_feed_drops_violating_bulletins():
    import inspect
    from src import news_feed

    src = inspect.getsource(news_feed.generate_bulletin)
    assert "canon_guard" in src, "hourly bulletin has no canon gate"
    gate_at = src.find("canon_guard")
    write_at = src.find("_write_memory(bulletin)")
    assert write_at == -1 or gate_at < write_at, "gate must precede _write_memory"


def test_roster_query_selects_rank():
    """`rank` is read by _build_live_roster_block but was never SELECTed, so the
    Guildmaster arrived at the model with a blank title."""
    import inspect
    from src import news_feed

    src = inspect.getsource(news_feed._load_live_roster)
    assert "`rank`" in src, "roster query must select rank (backticked -- reserved word)"
    assert "species" in src


# --------------------------------------------------------------------------
# A rejected bulletin must be REGENERATED, never posted half-written
#
# Reported from live use: "a bunch of refuse failures without force rewrite --
# it was giving news bulletins with no info or half a sentence."
#
# Both halves of that are real. A truncated reply used to be logged as "may be
# malformed" and then posted AND persisted anyway; and a rejection with no retry
# silently loses the hour. The fix is neither: regenerate, then give up cleanly.
# --------------------------------------------------------------------------

def test_malformed_bulletin_is_rejected_not_posted():
    import inspect
    from src import news_feed

    src = inspect.getsource(news_feed.generate_bulletin)
    assert "malformed/truncated" in src, "short bulletins are not treated as failures"
    # The old behaviour was a bare warning followed by the normal return path.
    assert "may be malformed" not in src, "still warning-and-posting a malformed bulletin"


def test_rejected_bulletin_forces_a_rewrite():
    import inspect
    from src import news_feed

    src = inspect.getsource(news_feed.generate_bulletin)
    assert "_attempt=_attempt + 1" in src, "a rejected bulletin is dropped without retrying"
    assert news_feed._MAX_BULLETIN_ATTEMPTS >= 1
    # Bounded, so a broken model cannot spin the GPU all night.
    assert news_feed._MAX_BULLETIN_ATTEMPTS <= 4


def test_persist_only_happens_after_validation():
    """_write_memory must be unreachable for a rejected draft."""
    import inspect
    from src import news_feed

    src = inspect.getsource(news_feed.generate_bulletin)
    reject_at = src.find("if _reject:")
    persist_at = src.rfind("_write_memory(bulletin)")
    assert reject_at != -1 and persist_at != -1
    assert reject_at < persist_at, "a rejected bulletin can still reach news_memory"


def test_voiced_bulletins_reject_truncated_drafts():
    import inspect
    from src import tower_news_voices

    src = inspect.getsource(tower_news_voices._write)
    assert "truncated" in src, "voiced path accepts a truncated draft"


def test_editorial_path_is_guarded_too():
    """~35% of bulletins come from the agent editorial path, which had neither
    a completeness check nor a canon check."""
    from src.news_integration import _editorial_problem

    class _R:
        def __init__(self, text):
            self.raw_content = text
            self.success = True

    assert _editorial_problem(_R("The Ironworks District reported that"))
    assert _editorial_problem(_R(""))
    assert _editorial_problem(_R(
        "TNN Report\nSenior Archivist Pell has been suspended from the Glass Sigil."
    ))
    assert not _editorial_problem(_R(
        "IRONWORKS DISTRICT - FORGE STRIKE ENTERS THIRD DAY\n"
        "The Ironworks Combine confirmed that furnace crews walked out again, "
        "and Denn Ashkeel refused to meet the delegation."
    ))
