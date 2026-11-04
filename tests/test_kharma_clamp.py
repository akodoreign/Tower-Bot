"""Mission rewards: Kharma is clamped per difficulty; easy missions carry none."""
import pytest


@pytest.mark.parametrize("reward, difficulty, expected", [
    ("150 EC + 38 Kharma", 2, "150 EC"),
    ("150 EC & 28 Kharma", 1, "150 EC"),
    ("200 EC, 30 Kharma", 2, "200 EC"),
    ("38 Kharma", 2, "See posting"),
    ("400 EC + 90 Kharma", 4, "400 EC + 40 Kharma"),
    ("400 EC + 1,200 Kharma", 10, "400 EC + 285 Kharma"),
    ("400 EC + 30 Kharma", 4, "400 EC + 30 Kharma"),   # under the cap: untouched
    ("150 EC", 2, "150 EC"),                             # no Kharma at all
])
def test_clamp_kharma(reward, difficulty, expected, fake_db):
    # imported here so fake_db replaces src.db_api first (mission_board connects on import)
    from src.mission_board import _clamp_kharma
    assert _clamp_kharma(reward, difficulty) == expected
