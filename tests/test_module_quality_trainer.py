"""The module grader reported a hardcoded default as a verdict for three months.

campaign_docs/skills/module_quality.md records 54 nightly self-evaluations. The
first 20 have scores that move (0, 1, 2, 3, 4) and gaps that cite exact failing
lines. Every one of the 34 after 2026-05-15 reads exactly "5/10" with "Content
gaps: None identified" -- because 5 was the default in the result dict, the
reply was truncating before OVERALL_SCORE, and the parse failure silently left
the default in place.

A grader that cannot grade has to say so. This is the same failure class as the
learning loop recording a truncated reply as "nothing worth learning today".
"""

import inspect

from src import module_quality_trainer as mqt


def test_score_does_not_default_to_a_number():
    """The default must be None, or a parse failure reads as a real verdict."""
    src = inspect.getsource(mqt._compare_to_reference)
    marker = '"overall_score": None'
    assert marker in src, "overall_score still defaults to a number"
    assert '"overall_score": 5' not in src


def test_failed_critique_is_flagged_not_silently_defaulted():
    src = inspect.getsource(mqt._compare_to_reference)
    assert "critique_ok" in src
    # And it must be derived from actually parsing the score, not assumed.
    assert 'result["critique_ok"] = result["overall_score"] is not None' in src


def test_skill_file_never_prints_a_score_the_grader_did_not_produce():
    src = inspect.getsource(mqt._update_quality_skill_file)
    assert "score_line" in src
    assert "NOT SCORED" in src, "a failed critique still writes a number"


def test_grader_prompt_is_context_sized():
    """~9,500 chars in, ~900 tokens of structured output demanded. Unsized,
    Ollama truncates the REPLY -- which is generated last, so the scores parse
    and the gaps are lost."""
    src = inspect.getsource(mqt._ask_ollama)
    assert "num_ctx" in src and "_fit_ctx" in src
    assert "num_predict" in src


def test_fit_ctx_only_raises():
    fit = mqt._fit_ctx
    assert fit("") >= 8192
    assert fit("x" * 200_000) <= 32768
    sizes = [fit("x" * n) for n in (100, 5_000, 40_000, 120_000)]
    assert sizes == sorted(sizes)


def test_critique_gets_a_thinking_token_budget():
    """qwen3 spends num_predict on thinking as well as visible output. At the
    900 default the reply died mid-format, after the scores and before the gaps."""
    src = inspect.getsource(mqt._compare_to_reference)
    assert "reply_tokens=" in src, "the critique call uses the default budget"


def test_truncation_is_reported():
    src = inspect.getsource(mqt._ask_ollama)
    assert "context overflow" in src
