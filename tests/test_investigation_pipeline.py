from src.mission_builder import investigation_pipeline as ip


def _fixtures():
    mission = {"title": "Missing Ledger", "faction": "Tower Authority"}
    roles = {"sponsor": "Tower Authority", "pressure": "Glass Sigil"}
    tones = {"primary": "procedural", "secondary": "noir", "wildcard": "comic red herring"}
    locations = [{"name": "Archive", "district": "Stacks", "description": "dusty public records"}]
    suspects = [{"name": "Mara Vell", "faction": "Glass Sigil", "case_role": "witness", "note": "owes a debt"}]
    return mission, roles, tones, locations, suspects


def test_normalize_investigation_plan_fills_partial_llm_json():
    mission, roles, tones, locations, suspects = _fixtures()

    plan = ip._normalize_plan(
        {"truth": "The ledger was copied, not stolen.", "timeline": "Day 1: interview clerk\nDay 2: verify copy"},
        mission,
        "theft / missing item",
        roles,
        tones,
        locations,
        suspects,
    )

    assert plan["truth"]  # may come from LLM data or mission-specific fallback
    assert plan["briefing"]
    assert plan["public_story"]
    assert plan["culprit_or_cause"]
    assert plan["resolution"]
    assert plan["timeline"]  # may come from LLM data or mission-specific fallback
