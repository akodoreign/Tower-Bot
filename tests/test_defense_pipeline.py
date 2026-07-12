import asyncio

from src.mission_builder import defense_pipeline as dp


def test_mission_force_modifiers_normalizes_dash_variants():
    mission = {
        "force_modifiers": "intel — captured scout; watch - intercepted messenger",
        "completed_intel_modifiers": ["intel â€” captured scout"],
    }

    applied = dp._mission_force_modifiers(mission)

    assert len(applied) == 2
    assert any(dp._normalize_force_modifier_key(key) == "intel - captured scout" for key in applied)
    assert any(dp._normalize_force_modifier_key(key) == "watch - intercepted messenger" for key in applied)


def test_generate_waves_applies_force_modifier_deltas(monkeypatch):
    async def empty_ollama(*args, **kwargs):
        return ""

    monkeypatch.setattr(dp, "_ollama", empty_ollama)
    monkeypatch.setattr(dp.random, "randint", lambda low, high: high)

    waves = asyncio.run(
        dp._generate_waves(
            {"faction": "Wardens of Ash", "opposing_faction": "Tower Authority"},
            dp.FACTION_PROFILES["Tower Authority"],
            dp.ARMY_TYPES["warband"],
            dp.TIER_SCALES["standard"],
            ["intel — captured scout", "watch — intercepted messenger"],
        )
    )

    assert waves[1]["grunts"] == 4
    assert waves[1]["lieutenants"] == 2
    assert waves[1]["force_modifier_grunt_delta"] == -5
    assert waves[1]["force_modifier_lieutenant_delta"] == -1
    assert waves[1]["force_modifier_morale_delta"] == -5
