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
    assert all("skill" in clue and "dc" in clue for clue in plan["clue_web"])
    assert "DC" in ip._clue_web(plan["clue_web"])


def test_normalize_investigation_plan_adds_missing_clue_web_dcs():
    mission, roles, tones, locations, suspects = _fixtures()
    mission["body"] = "Mara Vell and the Glass Sigil are tied to the Missing Ledger cover up."

    plan = ip._normalize_plan(
        {
            "briefing": "Tower Authority needs the party to prove what happened to the Missing Ledger before the Glass Sigil turns Mara Vell into the public scapegoat.",
            "truth": "The ledger was copied, not stolen.",
            "public_story": "The street says Mara Vell stole the Missing Ledger for the Glass Sigil.",
            "culprit_or_cause": "Mara Vell",
            "clue_web": [
                {
                    "clue": "The archive seal was restamped after midnight.",
                    "source": "paper trail",
                    "proves": "The Missing Ledger timeline is false.",
                    "unlocks": "interview the night clerk",
                },
                "A witness gives Mara Vell the wrong alibi.",
            ],
        },
        mission,
        "theft / missing item",
        roles,
        tones,
        locations,
        suspects,
    )

    assert plan["clue_web"][0]["skill"] == "Investigation"
    assert isinstance(plan["clue_web"][0]["dc"], int)
    assert plan["clue_web"][1]["skill"] == "Insight"
    assert isinstance(plan["clue_web"][1]["dc"], int)
