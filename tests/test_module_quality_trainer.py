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


# ---------------------------------------------------------------------------
# Type-aware rubric
#
# A difficulty 8 INVESTIGATION module -- clue web, suspect board, witness
# timelines, and an explicit "No Tactical Map" -- was failed CRITICAL for "No
# stat blocks: enemies cannot be run in combat" and for having no numbered
# areas. Both absences are correct for that type. The rubric hardcoded one
# shape: a dungeon crawl.
#
# `mission_type_templates.combat_posture` already encodes the design intent, so
# the grader reads it rather than inventing a taxonomy.
# ---------------------------------------------------------------------------

def test_posture_drives_statblock_severity():
    from src.module_quality_trainer import _STATBLOCK_SEVERITY

    assert _STATBLOCK_SEVERITY["EXPECTED"] == "CRITICAL"
    # Combat is what happens when these FAIL -- shipping encounters is not the job.
    assert _STATBLOCK_SEVERITY["CONSEQUENCE"] is None
    assert _STATBLOCK_SEVERITY["PERMITTED"] == "LOW"


def test_investigation_not_failed_for_missing_stat_blocks():
    text = ("Case Frame. Core Clue Web. Suspect Board. Witness Timeline. "
            "DC 15 Investigation. On a failure the trail goes cold. "
            "Read Aloud to Players: the shaft breathes cold air.")
    struct = mqt._structural_check(text, mission_type="investigation")
    joined = " ".join(struct["failures"])
    assert "enemies cannot be run in combat" not in joined
    assert struct["combat_posture"] == "CONSEQUENCE"


def test_combat_type_still_requires_stat_blocks():
    text = "1 - The Gate. Read Aloud to Players: horns. DC 15 Athletics. On a failure they fall."
    struct = mqt._structural_check(text, mission_type="battle")
    joined = " ".join(struct["failures"])
    assert "CRITICAL: No stat blocks" in joined, "a battle module must still need stat blocks"


def test_investigation_accepts_a_clue_web_instead_of_numbered_areas():
    """Location-driven play is not how these run."""
    text = ("Case Frame. Core Clue Web. Suspect Board. Witness Timeline - Elira Veyth. "
            "Read Aloud to Players: dust. DC 12 Insight. On a failure she clams up.")
    struct = mqt._structural_check(text, mission_type="investigation")
    joined = " ".join(struct["failures"])
    assert "no navigable spine" not in joined
    assert "locations are not scannable" not in joined


def test_investigation_with_no_spine_at_all_still_fails():
    """The relaxation is not a free pass -- SOME structure has to exist."""
    text = "Some prose about a mine. DC 12 Insight. Read Aloud to Players: dust."
    struct = mqt._structural_check(text, mission_type="investigation")
    assert any("no navigable spine" in f for f in struct["failures"])


# ---------------------------------------------------------------------------
# Component-library check (type-independent)
# ---------------------------------------------------------------------------

def test_component_check_flags_hand_rolled_styling():
    """A module built 2026-08-15 carried ZERO renderer classes across all eight
    files and 778 inline style attributes. No content rubric would surface that."""
    html = "<div " + 'style="color:red" ' * 60 + ">text</div>"
    comp = mqt._component_check(html)
    assert comp["component_total"] == 0
    assert any("bypasses the component library" in f for f in comp["failures"])


def test_component_check_passes_a_module_that_uses_the_library():
    html = ('<div class="scene-section"><div class="read-aloud">x</div>'
            '<div class="gm-note">y</div><div class="stat-block">z</div>'
            '<div class="transition">w</div></div>')
    comp = mqt._component_check(html)
    assert comp["component_total"] >= 5
    assert comp["failures"] == []


def test_component_check_ignores_css_selectors():
    """The markers must count as USED, not merely defined in a stylesheet."""
    html = "<style>.read-aloud{} .gm-note{} .stat-block{}</style><div>plain</div>"
    comp = mqt._component_check(html)
    assert comp["component_total"] == 0, "CSS selectors counted as usage"
