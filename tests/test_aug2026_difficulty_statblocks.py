"""Regressions for the two August 2026 mission-generation defects.

1. A difficulty 9 contract was built as a difficulty 5 one. Pipelines keyed their
   scale tables off the raw `tier` string, but live tiers are open vocabulary
   ('high-stakes', 'divine', 'rift', 'tower', 'inter-guild'...) and the tables
   only had rows for standard/seasoned/elite/legend -- so every lookup but
   'standard' fell through to 'standard' and the numeric difficulty was never
   read at all.

2. Modules shipped monster *chips* (name/CR/HP/AC) instead of stat blocks, and
   fabricated Mimir homebrew + LLM stat blocks for creatures that already exist,
   fully statted and DDB-pushed, in our curated `monsters` table.
"""
from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from src.mission_builder import mimir_module
from src.mission_builder.cr_scaling import difficulty_band, mission_difficulty
from src.mission_builder.monster_roster import mission_enemy_entry


# A row shaped exactly like `monsters` returns one (post _row_to_monster).
CURATED_ROW = {
    "id": 605,
    "name": "Faction Enforcer",
    "cr": "3",
    "creature_type": "humanoid",
    "size": "M",
    "ac": 16,
    "hp": 58,
    "hp_die": "8",
    "hp_die_count": 9,
    "stat_str": 18, "stat_dex": 12, "stat_con": 15,
    "stat_int": 10, "stat_wis": 12, "stat_cha": 12,
    "passive_perc": 11,
    "languages": "Common plus one faction language or cant",
    "speed": "30 ft.",
    "actions": (
        "Multiattack. Two Mace or Crossbow attacks.\n\n"
        "Mace. Melee Weapon Attack: +6 to hit, reach 5 ft., one target. "
        "Hit: 8 (1d8+4) bludgeoning damage."
    ),
    "traits": "Tactical Pairing. The target has disadvantage on its next attack.",
    "reactions": "Interpose. The enforcer can take half the damage instead.",
    "bonus_actions": "",
    "saves": {"con": 4, "str": 6},
    "notes": "Generic faction role.",
    "source": "faction_generic",
    "ddb_url": "https://www.dndbeyond.com/homebrew/creations/monsters/6462839-faction-enforcer/edit",
    "portrait_path": r"C:\portraits\Faction_Enforcer.png",
}


# ---------------------------------------------------------------------------
# 1. Difficulty actually reaches the build
# ---------------------------------------------------------------------------

def test_numeric_difficulty_wins_over_tier_name():
    """The board posts difficulty as a string on the missions row."""
    assert mission_difficulty({"difficulty": "9", "tier": "high-stakes"}) == 9
    assert difficulty_band({"difficulty": "9", "tier": "high-stakes"}) == "elite"
    assert difficulty_band({"difficulty": "10", "tier": "divine"}) == "legend"
    assert difficulty_band({"difficulty": "6", "tier": "rift"}) == "seasoned"
    assert difficulty_band({"difficulty": "4", "tier": "standard"}) == "standard"


def test_difficulty_falls_back_to_tier_when_unset():
    """A tier-only mission still scales instead of silently landing on standard."""
    assert mission_difficulty({"tier": "tower"}) == 10
    assert mission_difficulty({"tier": "local"}) == 4
    assert mission_difficulty({}) == 5
    assert mission_difficulty({"difficulty": "not a number", "tier": "epic"}) == 9


@pytest.mark.parametrize("tier", [
    "high-stakes", "divine", "rift", "tower", "investigation",
    "major", "local", "patrol", "escort", "inter-guild", "dungeon",
])
def test_live_tiers_no_longer_all_collapse_to_standard(tier):
    """Every one of these used to return the 'standard' row regardless of difficulty."""
    from src.mission_builder import defense_pipeline as dp
    from src.mission_builder import assault_pipeline as ap

    hard = {"tier": tier, "difficulty": "9"}
    assert dp._tier_scale(hard) is dp.TIER_SCALES["elite"]
    assert ap._tier_scale(hard) is ap.TIER_SCALES["elite"]


def test_defense_hard_contract_outscales_a_standard_one():
    from src.mission_builder import defense_pipeline as dp

    easy = dp._tier_scale({"tier": "standard", "difficulty": "4"})
    hard = dp._tier_scale({"tier": "high-stakes", "difficulty": "9"})

    assert hard["wave_count"] > easy["wave_count"]
    assert hard["grunt_bonus"] > easy["grunt_bonus"]
    assert hard["morale_mult"] > easy["morale_mult"]


def test_defense_enemy_cr_tracks_mission_cr(monkeypatch):
    """Ranks were pinned at cr_max 3/6/8 no matter how hard the contract was."""
    from src.mission_builder import defense_pipeline as dp

    seen: list[dict] = []

    def fake_roles(roles, **kw):
        seen.append(kw)
        return [dict(CURATED_ROW)]

    monkeypatch.setattr(dp, "faction_role_monsters", fake_roles)
    dp._defense_mimir_enemies(
        [{"number": 1, "label": "Probe", "grunts": 2, "lieutenants": 1}],
        dp.ARMY_TYPES["warband"],
        dp._get_profile("Unknown Threat"),
        target_cr=13,
    )

    caps = [kw["cr_max"] for kw in seen]
    assert caps == [7, 10, 12], f"CR caps did not follow mission_cr 13: {caps}"


def test_gather_uses_band_not_tier():
    """FRAGILITY_DC / quota_map are band-keyed; a raw live tier hit neither row.

    Passing 'high-stakes' straight through (what the caller used to do) silently
    produced the easiest DC in the table. The band for that same mission is
    'elite', which is a real row.
    """
    from src.mission_builder import gather_pipeline as gp

    mission = {"tier": "high-stakes", "difficulty": "9"}
    assert difficulty_band(mission) == "elite"

    # Synthetic profile so the assertion does not ride on whichever fragility a
    # given faction happens to carry.
    profile = {**gp._DEFAULT_GATHER, "fragility": "extreme",
               "item_category": "arcane components"}

    raw_tier = asyncio.run(gp._generate_item_details("Iron Fang Consortium", profile, mission["tier"]))
    banded   = asyncio.run(gp._generate_item_details("Iron Fang Consortium", profile, difficulty_band(mission)))
    easy     = asyncio.run(gp._generate_item_details("Iron Fang Consortium", profile, "standard"))

    assert raw_tier["dc"] == 14, "an unknown key should hit the hardcoded default"
    assert banded["dc"] == gp.FRAGILITY_DC["extreme"]["elite"] == 20
    assert banded["dc"] > easy["dc"] > raw_tier["dc"] - 1
    assert banded["dc"] > raw_tier["dc"], "a difficulty 9 gather must not use the fallback DC"


# ---------------------------------------------------------------------------
# 2. Curated stat blocks, never generated ones
# ---------------------------------------------------------------------------

def test_enemy_entry_carries_the_whole_curated_block():
    entry = mission_enemy_entry(CURATED_ROW, count=7, notes="Wave 2.")

    assert entry["db_backed"] is True
    assert entry["ddb_url"].endswith("faction-enforcer/edit")
    sb = entry["statblock"]
    assert sb["str_"] == 18 and sb["cha"] == 12
    assert sb["saves"] == {"con": 4, "str": 6}
    assert sb["passive_perc"] == 11
    assert "Multiattack" in sb["actions"]
    assert "Interpose" in sb["reactions"]
    assert sb["hp_die_count"] == 9


def test_rendered_section_is_a_runnable_stat_block():
    entry = mission_enemy_entry(CURATED_ROW, count=7)
    html = mimir_module.render_mimir_section([entry], [], "mod-1")

    # The DM has to fight this at the table.
    for expected in ("STR", "18", "(+4)", "Multiattack", "Interpose",
                     "Tactical Pairing", "Passive Perception", "Saves"):
        assert expected in html, f"missing {expected!r} from rendered stat block"
    assert "x7" in html


def test_curated_payload_is_all_db_values():
    entry = mission_enemy_entry(CURATED_ROW)
    data = json.loads(mimir_module._curated_monster_data(entry["statblock"]))

    assert data["str"] == 18
    assert data["ac"] == [{"ac": 16}]
    assert data["hp"] == {"average": 58, "formula": "9d8"}
    assert data["speed"] == {"walk": 30}
    assert data["save"] == {"con": "+4", "str": "+6"}
    assert data["action"][0]["name"] == "Multiattack"
    assert data["reaction"][0]["name"] == "Interpose"


def test_curated_monsters_never_hit_the_llm_or_the_catalog(monkeypatch, fake_mimir):
    """The old path fuzzy-searched the catalog, missed, then invented a stub."""
    fake_mimir.available = True

    async def boom(*a, **kw):
        raise AssertionError("LLM stat block generated for a curated monster")

    monkeypatch.setattr(mimir_module, "_generate_statblock_llm", boom)

    synced: list = []

    async def fake_sync(mimir, enemy):
        synced.append(enemy["name"])

    monkeypatch.setattr(mimir_module, "_sync_curated_homebrew", fake_sync)

    entry = mission_enemy_entry(CURATED_ROW, count=4, notes="Wave 1.")
    out = asyncio.run(mimir_module.enrich_monsters("mod-1", [entry]))

    assert fake_mimir.monster_searches == [], "catalog was searched for a curated monster"
    assert fake_mimir.monsters_added == [("mod-1", "Faction Enforcer", 4)]
    assert synced == ["Faction Enforcer"]
    assert out[0]["statblock"]["str_"] == 18


# ---------------------------------------------------------------------------
# 3. 2024 phrasing rewrite (scripts/rewrite_monsters_2024_phrasing.py)
# ---------------------------------------------------------------------------

def _convert(text: str) -> str:
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from rewrite_monsters_2024_phrasing import convert

    return convert(text)


@pytest.mark.parametrize("before,after", [
    # Target format verified against XMM (Warrior Veteran, Knight, Gladiator).
    (
        "Shortbow. Ranged Weapon Attack: +5 to hit, range 80/320 ft., one target. "
        "Hit: 6 (1d6+3) piercing damage.",
        "Shortbow. Ranged Attack Roll: +5, range 80/320 ft. Hit: 6 (1d6 + 3) Piercing damage.",
    ),
    (
        "Wyrm Bite. Melee or Ranged Spell Attack: +16 to hit, reach 10 ft. or range 90 ft., "
        "one target. Hit: 36 (4d10+14) lightning damage.",
        "Wyrm Bite. Melee or Ranged Attack Roll: +16, reach 10 ft. or range 90 ft. "
        "Hit: 36 (4d10 + 14) Lightning damage.",
    ),
    # Coordinated damage lists capitalise as a unit, not half-way.
    (
        "two grow back unless fire or acid damage is dealt first.",
        "two grow back unless Fire or Acid damage is dealt first.",
    ),
    (
        "Void Form. Resistant to bludgeoning, piercing, slashing from nonmagical weapons.",
        "Void Form. Resistant to Bludgeoning, Piercing, Slashing from nonmagical weapons.",
    ),
])
def test_2024_phrasing_conversion(before, after):
    assert _convert(before) == after


def test_rewrite_leaves_ordinary_prose_alone():
    """fire/cold/force/acid have non-damage senses all over this flavour text."""
    prose = ("The guard can fire at will and holds the line under fire; "
             "cold iron does not force the door, and the acid vat is sealed.")
    assert _convert(prose) == prose


def test_rewrite_is_idempotent():
    once = _convert("Mace. Melee Weapon Attack: +6 to hit, reach 5 ft., one target. "
                    "Hit: 8 (1d8+4) bludgeoning damage.")
    assert _convert(once) == once


# ---------------------------------------------------------------------------
# 4. The save-rewrite validation gate (scripts/rewrite_monster_saves_2024.py)
#
# An LLM does the restructuring, so the gate is the only thing standing between
# a hallucination and the campaign's authoritative rules text. Every case below
# is a real failure mode observed during the run.
# ---------------------------------------------------------------------------

def _validate(before: str, after: str):
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from rewrite_monster_saves_2024 import validate

    return validate(before, after)


CONE = ("Each enemy in a 30-foot cone must make a DC 16 CON save. On a failure, the "
        "target takes 40 (6d10) Force damage; on a success, half damage.")
CONE_OK = ("Constitution Saving Throw: DC 16, each creature in a 30-foot Cone. "
           "Failure: 40 (6d10) Force damage. Success: Half damage.")


def test_clean_save_rewrite_passes():
    ok, why = _validate(CONE, CONE_OK)
    assert ok, why


@pytest.mark.parametrize("label,bad", [
    ("changed DC", CONE_OK.replace("DC 16", "DC 15")),
    ("changed dice", CONE_OK.replace("6d10", "6d8")),
    ("changed damage type", CONE_OK.replace("Force", "Fire")),
    ("changed ability", CONE_OK.replace("Constitution", "Dexterity")),
    ("added a condition", CONE_OK.replace("Force damage.", "Force damage and the Prone condition.")),
    ("dropped the area size", CONE_OK.replace("30-foot Cone", "Cone")),
    ("bare area, no target", CONE_OK.replace("each creature in a 30-foot Cone", "a 30-foot Cone")),
    ("still 2014", "Each enemy must make a DC 16 CON save. Constitution Saving Throw: whatever."),
    ("model chatter", "Here is the rewrite: " + CONE_OK),
])
def test_save_gate_rejects_tampering(label, bad):
    ok, why = _validate(CONE, bad)
    assert not ok, f"gate let {label!r} through"


def test_save_gate_rejects_reverting_the_2024_attack_line():
    """The model 'helpfully' undid the attack-phrasing rewrite on a mixed paragraph."""
    before = ("Melee Attack Roll: +6, reach 5 ft. Hit: 21 (4d8 + 3) Necrotic. "
              "DC 14 Con save or max HP reduced by damage taken until long rest.")
    reverted = ("Melee Weapon Attack: +6 to hit, reach 5 feet. Hit: 21 (4d8 + 3) Necrotic "
                "damage. Constitution Saving Throw: DC 14, the target. Failure: max HP "
                "reduced by the damage taken until long rest.")
    ok, why = _validate(before, reverted)
    assert not ok and "2014" in why

    # Even a cosmetic touch to the attack line is refused.
    nudged = ("Melee Attack Roll: +6, reach 5 feet. Hit: 21 (4d8 + 3) Necrotic. "
              "Constitution Saving Throw: DC 14, the target. Failure: max HP reduced "
              "by the damage taken until long rest.")
    ok, why = _validate(before, nudged)
    assert not ok and "attack line" in why


def test_save_gate_rejects_a_flipped_success_branch():
    """Numbers all match, but the rule is inverted -- numeric checks cannot see this."""
    before = ("The first time this enforcer is reduced to 0 HP it makes a DC 13 Con save. "
              "On success it drops to 1 HP instead (once per combat).")
    flipped = ("Constitution Saving Throw: DC 13, the first time this enforcer is reduced "
               "to 0 HP. Failure: The enforcer drops to 1 HP instead (once per combat).")
    ok, why = _validate(before, flipped)
    assert not ok and "success branch" in why


def test_save_gate_rejects_invented_branches():
    """Numerically clean, semantically fabricated -- both seen in the real run."""
    before = ("Melee Attack Roll: +8, reach 5 ft. Hit: 29 (6d8 + 2) Necrotic. "
              "DC 16 Con save or max HP reduced.")
    invented = ("Melee Attack Roll: +8, reach 5 ft. Hit: 29 (6d8 + 2) Necrotic. "
                "Constitution Saving Throw: DC 16, each creature hit. Failure: The "
                "target's maximum HP is reduced by that amount. Success: The target's "
                "maximum HP is reduced by half that amount.")
    ok, why = _validate(before, invented)
    assert not ok and "invented a 'Success:'" in why

    honest = ("Melee Attack Roll: +8, reach 5 ft. Hit: 29 (6d8 + 2) Necrotic. "
              "Constitution Saving Throw: DC 16, each creature hit. Failure: The "
              "target's maximum HP is reduced by the amount of damage taken.")
    ok, why = _validate(before, honest)
    assert ok, why


def test_save_gate_rejects_invented_conditions():
    before = ("One creature within 30 ft.: DC 15 Wis save or one skill proficiency "
              "suppressed for 1 hour.")
    made_up = ("Wisdom Saving Throw: DC 15, one creature within 30 feet. Failure: The "
               "target has the Skill Suppression condition for 1 hour.")
    ok, why = _validate(before, made_up)
    assert not ok and "Skill Suppression" in why

    plain = ("Wisdom Saving Throw: DC 15, one creature within 30 feet. Failure: The "
             "target has one skill proficiency suppressed for 1 hour.")
    ok, why = _validate(before, plain)
    assert ok, why


def test_condition_gate_reads_the_name_not_the_whole_clause():
    """Leftmost-match once captured 'target has the Stunned' and false-rejected."""
    before = ("60-ft. cone. DC 15 Wis save or frightened 1 minute AND stunned until "
              "end of next turn on fail.")
    after = ("Wisdom Saving Throw: DC 15, each creature in a 60-foot Cone. Failure: The "
             "target has the Frightened condition for 1 minute, and the target has the "
             "Stunned condition until the end of its next turn.")
    ok, why = _validate(before, after)
    assert ok, why


def test_unknown_creatures_still_get_the_old_homebrew_path(monkeypatch, fake_mimir):
    """Only curated rows short-circuit; a one-off enemy must still be created."""
    fake_mimir.available = True

    async def fake_llm(*a, **kw):
        return {"str_": 11}

    monkeypatch.setattr(mimir_module, "_generate_statblock_llm", fake_llm)

    invented = {"name": "Ledgerbound Revenant", "cr": "6", "count": 1,
                "notes": "One-off haunt.", "creature_type": "undead"}
    asyncio.run(mimir_module.enrich_monsters("mod-1", [invented]))

    assert fake_mimir.monster_searches, "catalog search skipped for an unknown creature"
    assert [h["name"] for h in fake_mimir.homebrew] == ["Ledgerbound Revenant"]


# ---------------------------------------------------------------------------
# 5. Recovering a rewrite the model spoiled with one extra clause
#
# The dominant failure on the first full pass (10 of 23 rejections): the source
# is a plain "save or suffer X" with no success behaviour, and the model appends
# a Success: clause anyway because most 2024 saves have one. The restructure is
# otherwise correct, so throwing it away wastes a good rewrite -- but the clause
# cannot be kept, because it invents a rule the monster never had.
# ---------------------------------------------------------------------------

def _trim(before: str, after: str) -> str:
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from rewrite_monster_saves_2024 import drop_invented_success

    return drop_invented_success(before, after)


# Verbatim shape of UC Void Iron Fang Enforcer's Syndicate Judgment: a DC, a
# duration, and no area -- so a faithful rewrite introduces no new numbers.
SAVE_OR_SUFFER = "DC 16 Wis save or frightened 1 minute."
WITH_INVENTED = ("Wisdom Saving Throw: DC 16, one creature the enforcer can see. "
                 "Failure: The target has the Frightened condition for 1 minute. "
                 "Success: The target is unaffected.")


def test_invented_success_clause_is_dropped():
    out = _trim(SAVE_OR_SUFFER, WITH_INVENTED)
    assert "Success:" not in out
    assert "Failure:" in out, "the Failure branch must survive"
    assert "Frightened" in out and "DC 16" in out


def test_trimmed_rewrite_then_passes_the_gate():
    """The whole point: recover the rewrite, then re-run the FULL validator."""
    assert not _validate(SAVE_OR_SUFFER, WITH_INVENTED)[0], "gate should reject the invention"
    ok, why = _validate(SAVE_OR_SUFFER, _trim(SAVE_OR_SUFFER, WITH_INVENTED))
    assert ok, why


def test_legitimate_success_clause_is_left_alone():
    """When the source DOES say what happens on a save, the clause is real."""
    assert _trim(CONE, CONE_OK) == CONE_OK


def test_never_trims_away_the_only_branch():
    """Refuse rather than hand back something with no Failure branch."""
    only_success = "Wisdom Saving Throw: DC 16, each creature. Success: The target is unaffected."
    assert _trim(SAVE_OR_SUFFER, only_success) == only_success


def test_trimmer_touches_no_numbers():
    out = _trim(SAVE_OR_SUFFER, WITH_INVENTED)
    import re
    assert re.findall(r"\d+", out) == ["16", "1"], "the trimmer must not alter numbers"


def test_length_band_allows_2024_scaffolding_on_terse_sources():
    """These statblocks are shorthand; 2024 form has fixed overhead.

    "DC 16 Wis save or frightened 1 minute." is 8 words. The faithful rewrite
    carries "<Ability> Saving Throw: DC n, <who>. Failure: ..." and lands near
    21. A flat 2.0x ceiling called that rambling and threw away correct output.
    """
    ok, why = _validate(SAVE_OR_SUFFER, _trim(SAVE_OR_SUFFER, WITH_INVENTED))
    assert ok, why


def test_length_band_still_catches_actual_rambling():
    """The additive allowance must not become a licence to pad."""
    padded = (WITH_INVENTED + " The enforcer's reputation precedes them throughout "
              "the district, and witnesses describe the moment as one of profound "
              "and lingering dread that follows them home for many nights after.")
    ok, _ = _validate(SAVE_OR_SUFFER, padded)
    assert not ok, "gate should still reject padded output"


@pytest.mark.parametrize("label,draft", [
    ("trailing period",
     "Wisdom Saving Throw: DC 16, one creature the enforcer can see. "
     "Failure: The target has the Frightened condition for 1 minute. "
     "Success: The target is unaffected."),
    # The model usually ends HERE, with no full stop, because the invented
    # clause is the last thing it writes. Requiring a terminator made the
    # trimmer a silent no-op and cost two full 27B passes.
    ("no trailing period",
     "Wisdom Saving Throw: DC 16, one creature the enforcer can see. "
     "Failure: The target has the Frightened condition for 1 minute. "
     "Success: The target is unaffected"),
    ("no-effect wording",
     "Wisdom Saving Throw: DC 16, one creature the enforcer can see. "
     "Failure: The target has the Frightened condition for 1 minute. "
     "Success: No effect"),
    ("success before failure",
     "Wisdom Saving Throw: DC 16, one creature the enforcer can see. "
     "Success: No effect. "
     "Failure: The target has the Frightened condition for 1 minute."),
])
def test_invented_success_trimmed_in_every_shape(label, draft):
    """Whatever shape the invention takes, the rewrite must be recoverable."""
    out = _trim(SAVE_OR_SUFFER, draft)
    assert out != draft, f"trimmer was a no-op on {label!r}"
    assert "Success:" not in out
    assert "Failure:" in out
    ok, why = _validate(SAVE_OR_SUFFER, out)
    assert ok, f"{label}: {why}"


# ---------------------------------------------------------------------------
# 6. A restatement is not a change
#
# 2024 form requires the area to be named again INSIDE the save clause. The
# source says "Each rift: 10-ft. radius" and the rewrite must also say "each
# creature in a 10-foot Radius", so a correct rewrite carries that 10 twice.
# Multiset comparison called that "numbers changed (added ['10'])" and rejected
# it. Real case, UC Rift Colossus.
# ---------------------------------------------------------------------------

RIFT = ("Three rifts open at three points within 90 ft. Each rift: 10-ft. radius. "
        "DC 17 Dex save or pulled 30 ft. toward rift + 27 (6d8) Necrotic. "
        "Rifts close at start of next turn.")
RIFT_OK = ("Three rifts open at three points within 90 feet. Each rift: 10-foot radius. "
           "Dexterity Saving Throw: DC 17, each creature in a 10-foot Radius. "
           "Failure: Pulled 30 feet toward the rift and takes 27 (6d8) Necrotic damage. "
           "Rifts close at the start of the monster's next turn.")


def test_repeated_area_is_not_a_number_change():
    ok, why = _validate(RIFT, RIFT_OK)
    assert ok, why


@pytest.mark.parametrize("label,bad", [
    ("dropped the pull distance", RIFT_OK.replace("Pulled 30 feet toward", "Pulled toward")),
    ("dropped the damage type", RIFT_OK.replace("Necrotic damage", "damage")),
    ("halved the damage", RIFT_OK.replace("27 (6d8)", "13 (3d8)")),
    ("changed the save ability", RIFT_OK.replace("Dexterity Saving", "Constitution Saving")),
    ("invented a range", RIFT_OK.replace("within 90 feet", "within 120 feet")),
    ("changed the DC", RIFT_OK.replace("DC 17", "DC 15")),
])
def test_set_semantics_still_catch_real_tampering(label, bad):
    """Relaxing repetition must not relax invention or loss."""
    ok, _ = _validate(RIFT, bad)
    assert not ok, f"gate let {label!r} through"


def test_5etools_markup_is_stripped_from_candidates():
    """'[Area of Effect]' is the rendered leftover of a {@variantrule ...} tag in
    the WotC few-shot corpus -- contamination, not rules text."""
    import re as _re
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import rewrite_monster_saves_2024 as rw

    src = _re.sub(r"\s*\[Area of Effect\]", "", "each creature in a 10-foot Radius [Area of Effect].")
    assert "[Area of Effect]" not in src
    assert "10-foot Radius" in src
    assert "Area of Effect" in inspect.getsource(rw.restructure)


# ---------------------------------------------------------------------------
# 7. A save construct implies a failure effect
#
# RE_SRC_FAILURE matched "save or" ADJACENTLY. The shorthand in this corpus puts
# a clause between them -- "DC 14 Con save at start of turn within 15 ft. or
# infected" -- so the gate decided the source had no failure branch and rejected
# the correct rewrite for inventing one. Real case, UC Void Plague Hulk.
# ---------------------------------------------------------------------------

AURA = "DC 14 Con save at start of turn within 15 ft. or infected."
AURA_OK = ("Constitution Saving Throw: DC 14, each creature within 15 feet. "
           "Failure: The target is infected.")


def test_save_construct_implies_a_failure_branch():
    ok, why = _validate(AURA, AURA_OK)
    assert ok, why


def test_invented_success_then_failure_recovers_in_one_go():
    """The full recovery path on the real draft: trim the invented Success, and
    the remaining Failure branch must be accepted rather than called invented."""
    draft = AURA_OK + " Success: None."
    assert not _validate(AURA, draft)[0]
    ok, why = _validate(AURA, _trim(AURA, draft))
    assert ok, why


def test_failure_branch_still_rejected_when_there_is_no_save():
    """The relaxation keys off an actual save construct, not off nothing."""
    no_save = "The hulk lumbers 15 feet and knocks over a brazier."
    ok, _ = _validate(no_save, AURA_OK)
    assert not ok, "a Failure branch was accepted for a source with no save"


# ---------------------------------------------------------------------------
# 8. The gate must accept genuine WotC 2024 text
#
# Checked against real XMM entries pulled from mimir.db. The gate was calibrated
# for ONE shape -- a monster imposing a save on targets -- and rejected all three
# WotC forms below. Rules content comes from Mimir, never from model memory, and
# that applies to the VALIDATOR as much as to the model.
# ---------------------------------------------------------------------------

# Arcanaloth, Banishing Claw (XMM): attack, connective, then a save with NO
# target clause -- the attack already named the target.
ARC_SRC = ("Melee Attack Roll: +9, reach 5 ft. Hit: 10 (2d4 + 5) Slashing damage plus "
           "19 (3d12) Psychic damage. On hit vs. creatures: DC 17 Cha save or trapped "
           "in a demiplane.")
ARC_OK = ("Melee Attack Roll: +9, reach 5 ft. Hit: 10 (2d4 + 5) Slashing damage plus "
          "19 (3d12) Psychic damage. If the target is a creature, it is subjected to the "
          "following effect. Cha Saving Throw: DC 17. Failure: The target is trapped in "
          "a demiplane.")


def test_attack_led_save_needs_no_target_clause():
    """XMM writes 'Cha Saving Throw: DC 17. Failure:' with no 'each creature in'."""
    ok, why = _validate(ARC_SRC, ARC_OK)
    assert ok, why


def test_attack_span_stops_at_the_damage_sentence():
    """The span ran to the SAVE, swallowing the connective ('On hit vs. ...') --
    text a correct rewrite must restructure. 'ft.' and 'vs.' are abbreviations,
    not sentence ends."""
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from rewrite_monster_saves_2024 import attack_span

    span = attack_span(ARC_SRC)
    assert span.endswith("Psychic damage."), f"span mis-cut: {span!r}"
    assert "On hit" not in span
    assert "vs." not in span


@pytest.mark.parametrize("text,expected", [
    # The monster's own survival save -- 2024 keeps these as prose (XMM Undead
    # Fortitude), so there is nothing to convert.
    ("Syndicate Mark. Drops to 1 HP instead of 0 on first death (DC 13 Con save).", True),
    ("Undying Devotion. When reduced to 0 HP: DC 15 Con save to stay at 1 HP.", True),
    # Saves the monster IMPOSES must never be mistaken for one.
    ("Engulf. Target DC 15 Str save or engulfed: restrained.", False),
    ("25-ft. radius. DC 17 Dex save: 52 (8d12) Fire on fail, half on success.", False),
    ("Each: DC 17 Str save or engulfed: blinded, restrained.", False),
])
def test_self_save_detection(text, expected):
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from rewrite_monster_saves_2024 import is_self_save

    assert is_self_save(text) is expected
