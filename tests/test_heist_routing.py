from src.mission_builder.heist_pipeline import is_heist_mission
from src.mission_builder.investigation_pipeline import is_investigation_mission


def test_non_shady_theft_stays_investigation_candidate():
    assert not is_heist_mission("theft", "Tower Authority")
    assert is_investigation_mission("theft")


def test_shady_theft_can_route_to_heist():
    assert is_heist_mission("theft", "Obsidian Lotus")
