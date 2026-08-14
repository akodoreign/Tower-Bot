"""The nightly learning loop is the easiest place in the codebase for a failure
to look like a finding.

It runs once a night at 1 AM, writes to a journal file, and every one of its
prompts grows with the world. For months it made ~15 Ollama calls with NO
num_ctx at all -- the exact silent-truncation shape that killed the hourly news
bulletin, except here a truncated reply is recorded as "nothing worth learning
today" instead of raising anything.
"""

import inspect

from src import self_learning


def test_every_learning_prompt_is_context_sized():
    """No num_ctx means Ollama picks a small default and truncates in silence."""
    src = inspect.getsource(self_learning._ask_ollama)
    assert "num_ctx" in src, "learning loop calls Ollama without sizing the context"
    assert "_fit_ctx" in src


def test_fit_ctx_only_ever_raises():
    """Floor 8192, cap 32768, monotonic -- the established pipeline pattern."""
    fit = self_learning._fit_ctx
    assert fit("") >= 8192
    assert fit("x" * 200_000) <= 32768
    sizes = [fit("x" * n) for n in (100, 5_000, 40_000, 80_000, 200_000)]
    assert sizes == sorted(sizes), "context sizing must be monotonic"


def test_truncation_is_reported_not_swallowed():
    """A 1-char reply to a large prompt is a failure, not an empty finding."""
    src = inspect.getsource(self_learning._ask_ollama)
    assert "possible context overflow" in src, (
        "a near-empty reply to a large prompt must be logged as truncation"
    )


def test_learner_never_reads_retracted_bulletins():
    """`facts or bulletin_text` reached straight past an emptied facts field and
    fed retracted prose to the one reader that turns a bulletin into a persisted
    lesson. The exclusion has to happen in the QUERY."""
    src = inspect.getsource(self_learning._study_news_memory)
    assert "retracted" in src.lower(), "learning loop still reads retracted bulletins"
    assert "news_type" in src and "NOT LIKE" in src, (
        "retracted rows must be excluded in SQL, not filtered after the fallback"
    )


def test_learning_loop_stamps_a_heartbeat():
    """A nightly loop that writes only to a journal file can die for a week
    before anyone notices."""
    src = inspect.getsource(self_learning.self_learning_loop)
    assert "_heartbeat" in src, "learning loop records no heartbeat"
    # Both outcomes, or a failing loop looks identical to a healthy one.
    assert src.count("_heartbeat") >= 2, "heartbeat must record failure as well as success"


def test_loop_health_knows_about_the_learner():
    from src.loop_health import EXPECTED

    assert "self_learning" in EXPECTED, "self_learning missing from the loop-health card"
    label, threshold = EXPECTED["self_learning"]
    assert label
    # It runs once a night and will not retry after a failure, so the staleness
    # threshold has to clear a full day plus margin.
    assert threshold > 24 * 60 * 60


def test_party_interview_is_sized_and_gated():
    """Interviews are posted to Discord AND persisted to party_interviews --
    a world-facing generator, so it needs both the sizing and the canon gate."""
    from src import party_interview

    ask = inspect.getsource(party_interview._ask_ollama)
    assert "num_ctx" in ask, "interview prompts are not context-sized"

    post = inspect.getsource(party_interview.maybe_post_interview) \
        if hasattr(party_interview, "maybe_post_interview") else ""
    if not post:
        # Fall back to scanning the module for the gate.
        post = inspect.getsource(party_interview)
    assert "canon_guard" in post, "interview output is not canon-gated"


# ---------------------------------------------------------------------------
# Studies vs actions
# ---------------------------------------------------------------------------

def test_actions_do_not_pollute_the_skill_corpus():
    """A study produces knowledge; an action does something and reports on it.

    Three actions were filing their reports into the retrieval corpus as if they
    were knowledge -- and since a report carries no `**Keywords:**` header,
    score_skill could never surface them. One row was the literal status line
    "Interview archive: no expired interviews to archive tonight."
    """
    src = inspect.getsource(self_learning.run_learning_session)
    assert "saves_skill" in src, "studies and actions are not distinguished"
    # The three known actions must be declared as non-skill.
    for action in ("ad_generation", "council_outcomes", "interview_archive"):
        idx = src.find(f'("{action}"')
        assert idx != -1, f"{action} missing from the study table"
        entry = src[idx:idx + 200]
        assert "False" in entry, f"{action} still saves a skill"


def test_studies_still_save_skills():
    src = inspect.getsource(self_learning.run_learning_session)
    for study in ("failure_analysis", "world_state", "news_memory", "npc_roster"):
        idx = src.find(f'("{study}"')
        assert idx != -1
        assert "True" in src[idx:idx + 200], f"{study} no longer saves a skill"


def test_council_dispatches_are_canon_gated():
    """The dispatch prompt asks for scandal and corruption BY NAME, then inserts
    the answer into news_memory where every later generator reads it back."""
    src = inspect.getsource(self_learning._study_council_outcomes)
    assert "canon_guard" in src, "council dispatches are not gated"
    gate = src.find("canon_check")
    insert = src.find("INSERT INTO news_memory")
    assert gate != -1 and insert != -1
    assert gate < insert, "the gate must run before the insert"


def test_council_dispatch_prompt_carries_standing():
    src = inspect.getsource(self_learning._council_canon)
    assert "protected_block" in src
