from src.mission_builder import monster_roster as mr


def test_row_to_monster_decodes_saves_and_cr():
    row = {
        "name": "UC Test Monster",
        "cr": "12",
        "is_void": 1,
        "saves_json": '{"con": 9, "wis": 7}',
    }

    monster = mr._row_to_monster(row)

    assert monster["is_void"] is True
    assert monster["cr_float"] == 12.0
    assert monster["saves"] == {"con": 9, "wis": 7}


def test_monster_summary_includes_core_stats():
    monster = {
        "name": "UC Test Monster",
        "cr": "12",
        "size": "H",
        "creature_type": "aberration",
        "ac": 18,
        "hp": 250,
        "speed": "40 ft.",
        "traits": "Void Aura. Bad things happen.\n\nOther trait.",
        "actions": "Multiattack. Two attacks.\n\nBite.",
    }

    summary = mr.monster_summary(monster)

    assert "UC Test Monster" in summary
    assert "CR 12" in summary
    assert "AC 18" in summary
    assert "Void Aura" in summary


def test_mission_cr_uses_party_plus_four_and_numeric_difficulty(monkeypatch):
    from src.mission_builder import cr_scaling

    monkeypatch.setattr(
        cr_scaling,
        "party_strength",
        lambda: {"party_size": 4, "avg_level": 8, "max_level": 8, "min_level": 8, "pcs": []},
    )

    assert cr_scaling.mission_cr({"tier": "standard", "difficulty": 5}) == 12
    assert cr_scaling.mission_cr({"tier": "standard", "difficulty": 3}) == 10
    assert cr_scaling.mission_cr({"tier": "standard", "difficulty": 7}) == 14
