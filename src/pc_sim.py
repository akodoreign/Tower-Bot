"""
pc_sim.py — Solo simulation of personal missions for specific player characters.

Lammis, Boxxo, Frank, and Geralt auto-claim their personal missions when no player
claims them within the hold window. The bot simulates each mission in the character's
voice and records the outcome to world memory.

Rules:
- Always solo (no party, no group mechanics)
- Characters always retreat rather than die — failure means retreat, not death
- npcs_killed is never populated — PCs may kill monsters but do not record named NPC kills
- Character levels are pulled live from latest_character_snapshots (dynamic as they level up)
"""

from __future__ import annotations

import json
import random
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SIMULATED_PCS = {"Lammis", "Boxxo", "Frank", "Geralt"}

# Minimum hours a personal mission must sit unclaimed before the PC auto-claims it.
# This gives players a window to take it themselves.
_HOLD_HOURS = 18

# Completion scheduled 1–3 days after claim
_COMPLETE_MIN_HOURS = 24
_COMPLETE_MAX_HOURS = 72

# Per-character success probability
_SUCCESS_RATE = {
    "Lammis": 0.80,   # powerful but sometimes misreads the situation
    "Boxxo":  0.88,   # reliable; machine logic occasionally fails social nuance
    "Frank":  0.92,   # methodical, eliminates threats efficiently
    "Geralt": 0.90,   # professional; knows when the job is too dirty to finish cleanly
}

# ---------------------------------------------------------------------------
# Character persona prompts (used in completion simulation)
# ---------------------------------------------------------------------------

_PERSONAS = {
    "Lammis": (
        "Lammis is a Monk — extremely powerful, impossibly sweet, and not very smart. "
        "She is dumb as a box of bricks but her heart is pure gold. "
        "She solves most problems by hitting them very hard, or by being so earnest that "
        "people forget to be mean. She often misunderstands the plan but ends up doing "
        "exactly the right thing by accident. Write in her voice: simple words, honest "
        "observations, vague but genuine confidence."
    ),
    "Boxxo": (
        "Boxxo is a Warforged Sorcerer — literally a vending machine with a divine soul. "
        "He dispenses goods, magic, and the occasional grim remark. He has a distinct "
        "personality despite (or because of) being a machine. He speaks in short clipped "
        "phrases that carry more weight than they should. "
        "Write his report in his voice: terse, slightly mechanical, unexpectedly profound."
    ),
    "Frank": (
        "Frank is a Human Fighter — essentially the Punisher. Heavy firearms specialist, "
        "code-driven soldier, Honor Score 20. He does not waste words or movements. "
        "He identifies the threat, he eliminates the threat, he leaves. No drama, no "
        "philosophy. Just the job. Write his report like a battlefield after-action report: "
        "dry, factual, the bare minimum needed to understand what happened."
    ),
    "Geralt": (
        "Geralt is a Monster Hunter — essentially Geralt of Rivia. Professional, experienced, "
        "unimpressed by nearly everything. He has tracked and killed things that would make "
        "lesser people quit the city entirely. He completes contracts. He uses his training. "
        "Write his report in his voice: dry, tired, matter-of-fact. A low grunt conveys more "
        "than a paragraph. He never boasts."
    ),
}

# ---------------------------------------------------------------------------
# Live character stat lookup (level, feats, spells — all dynamic)
# ---------------------------------------------------------------------------

_BORING_FEATS = {
    "ability score improvement", "acolyte ability score improvements",
    "farmer ability score improvements", "beast hunter ability score increase",
}


def _get_pc_stats(name: str) -> dict:
    """
    Pull current level, feats, and spells from latest_character_snapshots.
    Returns a dict with: level, feats (list[str]), spells (list[str]), classes (str).
    Always current — picks up level-ups automatically.
    """
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT snapshot_json FROM latest_character_snapshots WHERE char_name = %s LIMIT 1",
            (name,),
        ) or []
        if not rows:
            return {"level": 5, "feats": [], "spells": [], "classes": ""}
        snap = rows[0].get("snapshot_json") or {}
        if isinstance(snap, str):
            snap = json.loads(snap)

        # Level
        lvl = snap.get("total_level") or snap.get("level") or snap.get("classes_level")
        if not lvl:
            classes = snap.get("classes")
            if isinstance(classes, dict):
                lvl = sum(int(v) for v in classes.values() if v)
            elif isinstance(classes, list):
                lvl = sum(c.get("level", 0) for c in classes if isinstance(c, dict))
        level = int(lvl) if lvl else 5

        # Classes string (e.g. "Fighter 6")
        cls_raw = snap.get("classes") or {}
        if isinstance(cls_raw, dict):
            classes_str = ", ".join(f"{k} {v}" for k, v in cls_raw.items())
        else:
            classes_str = ""

        # Feats — filter out boring bookkeeping entries
        raw_feats = snap.get("feats") or []
        feats = [
            f for f in raw_feats
            if isinstance(f, str) and f.lower().strip() not in _BORING_FEATS
        ]

        # Spells — only named spells level 1+
        raw_spells = snap.get("spells") or []
        spells = [
            s["name"] for s in raw_spells
            if isinstance(s, dict) and s.get("level", 0) >= 1 and s.get("name")
        ]

        return {"level": level, "feats": feats, "spells": spells, "classes": classes_str}
    except Exception:
        return {"level": 5, "feats": [], "spells": [], "classes": ""}


def _pick_random_ability(stats: dict) -> str:
    """Pick one feat or spell at random to highlight in the simulation notice."""
    options = stats.get("feats", []) + stats.get("spells", [])
    if not options:
        return ""
    return random.choice(options)


# ---------------------------------------------------------------------------
# Per-character failure flavor (what goes wrong when they fail, in their style)
# ---------------------------------------------------------------------------

_FAILURE_FLAVORS = {
    "Lammis": (
        "Lammis's failures are almost always intelligence-related — she misread the situation, "
        "misunderstood the objective, knocked on the wrong door, or punched the wrong thing. "
        "Even her Lucky feat sometimes can't save her from herself. "
        "She is never embarrassed about it. She retreated because she was confused, not scared. "
        "She might not entirely understand that she failed. Write it with affection and comedy."
    ),
    "Boxxo": (
        "Boxxo's failures are usually a mismatch between machine logic and organic chaos — "
        "he solved the wrong problem perfectly, dispensed the wrong item at the wrong moment, "
        "or encountered a social/moral complexity that his programming genuinely could not parse. "
        "He is not damaged. He retreated because the parameters exceeded his current build. "
        "He will restock and return. Probably."
    ),
    "Frank": (
        "Frank's failures are tactical — too many hostiles, wrong intel, ammo depleted before "
        "objective could be secured. He executed flawlessly but the job was bigger than one man. "
        "He extracted. Alive. That IS the mission for Frank: complete the objective or extract. "
        "Dying is not tactically sound. Write it as a cold after-action assessment, not a defeat."
    ),
    "Geralt": (
        "Geralt's failures are professional setbacks — the creature was immune to what he prepared, "
        "or stronger than the contract suggested, or the situation required backup he doesn't have. "
        "He retreated. He'll find a better angle. He has walked away from worse. "
        "He is not bothered. He is mildly irritated. Write it as quiet competence acknowledging limits."
    ),
}

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_sim_claim_prompt(name: str, mission: dict) -> str:
    title   = mission.get("title", "Unknown Contract")
    faction = mission.get("faction", "")
    tier    = mission.get("tier", "standard")
    body    = (mission.get("body") or "").strip()
    stats   = _get_pc_stats(name)
    level   = stats["level"]
    persona = _PERSONAS[name]

    return f"""You are writing a SHORT in-character claim notice for a solo adventurer picking up a personal contract.

CHARACTER: {name} (Level {level}, {stats['classes']})
{persona}

MISSION: {title}
FACTION: {faction}
TIER: {tier}
MISSION BRIEF: {body[:300]}

Write 1-2 lines in {name}'s voice — how they acknowledge this job is theirs.
Format:
⚔️ **{name} — {title}** (solo)
*[1 sentence in their voice: why they're taking it, or just that they are.]*

RULES:
- Totally in character. No preamble. No sign-off. The notice only.
- Lammis: simple words, earnest. Boxxo: short, mechanical, oddly meaningful.
  Frank: bare minimum. Geralt: dry and tired."""


def _build_sim_complete_prompt(name: str, mission: dict, success: bool) -> str:
    title      = mission.get("title", "Unknown Contract")
    faction    = mission.get("faction", "")
    tier       = mission.get("tier", "standard")
    body       = (mission.get("body") or "").strip()
    stats      = _get_pc_stats(name)
    level      = stats["level"]
    persona    = _PERSONAS[name]
    result_str = "completed" if success else "failed — retreated"

    ability    = _pick_random_ability(stats)
    ability_note = (
        f"\nIMPORTANT: Work in a specific moment where {name} used their [{ability}] "
        f"ability/feat naturally in the scene. Don't force it — make it feel earned."
        if ability else ""
    )

    # Include a stats line so the LLM can reference specifics (INT for Lammis, etc.)
    stat_block = stats.get("stat_summary", "")

    outcome_instruction = (
        "They succeeded. Describe briefly what they accomplished, what they fought "
        "(monsters and hazards only — not named NPCs), and what it cost them."
        if success else
        "They did not finish the job and retreated. They are alive — always alive. "
        "Describe what went wrong and how it is ON-BRAND for this character's specific weaknesses.\n"
        + _FAILURE_FLAVORS.get(name, (
            "They were outmatched. They retreated. They survived. "
            "NEVER describe the character as dead or permanently harmed."
        ))
    )

    return f"""You are writing a SHORT solo mission result notice for a player character.

CHARACTER: {name} (Level {level}, {stats['classes']})
{persona}

MISSION: {title}
FACTION: {faction}
TIER: {tier}
MISSION BRIEF: {body[:300]}
RESULT: {result_str}{ability_note}

{outcome_instruction}

Format:
{"🏆" if success else "💢"} **{name} — {title}** ({"contract fulfilled" if success else "withdrawn — contractor retreated"})
*[2-3 sentences in {name}'s voice: what happened, how they handled it.]*

RULES:
- In {name}'s voice throughout. No narrator voice.
- Monsters and creatures are fair game. Do NOT name or kill named NPCs.
- On failure: they are alive. Always alive. They retreated. Frame it as retreat not defeat.
- No preamble, no sign-off. The notice only."""


# ---------------------------------------------------------------------------
# Claim phase — scans unclaimed personal missions and auto-claims for these PCs
# ---------------------------------------------------------------------------

async def simulate_pc_personal_claims(channel, client=None) -> None:
    """
    Called hourly (alongside check_npc_completions).
    Scans for unclaimed personal missions belonging to simulated PCs.
    After the hold window, the PC claims it and schedules a completion.
    """
    from src.mission_board import _load_missions, _save_missions, _get_results_channel
    from src.agents import generate_mission_text

    missions = _load_missions()
    now      = datetime.utcnow()
    updated  = False

    for mission in missions:
        # Only unresolved personal missions for the sim-PC set
        if mission.get("resolved"):
            continue
        pc_name = mission.get("personal_for", "")
        if pc_name not in SIMULATED_PCS:
            continue
        # Skip already claimed (player-claimed, NPC-claimed, or already PC-sim-claimed)
        if mission.get("claimed") or mission.get("npc_claimed") or mission.get("pc_sim_claimed"):
            continue

        # Check hold window
        try:
            posted_at = datetime.fromisoformat(mission.get("posted_at", ""))
            age_hours = (now - posted_at).total_seconds() / 3600
        except Exception:
            continue

        if age_hours < _HOLD_HOURS:
            continue  # still in the player window

        # Atomic DB claim — prevents race with player or NPC claim
        from src.mission_board import _claim_mission_atomically
        mission_id = int(mission.get("id") or 0)
        if not mission_id or not _claim_mission_atomically(mission_id, pc_name):
            logger.info(f"pc_sim: claim lost race for {mission.get('title','?')} — skipping")
            continue

        complete_dt = now + timedelta(
            hours=random.randint(_COMPLETE_MIN_HOURS, _COMPLETE_MAX_HOURS)
        )
        outcome = "complete" if random.random() < _SUCCESS_RATE.get(pc_name, 0.85) else "fail"

        try:
            prompt = _build_sim_claim_prompt(pc_name, mission)
            notice = await generate_mission_text(prompt)
        except Exception as e:
            logger.warning(f"pc_sim claim notice failed for {pc_name}: {e}")
            notice = f"⚔️ **{pc_name} — {mission.get('title', '?')}** (solo)\n*Taking the job.*"

        if not notice:
            notice = f"⚔️ **{pc_name} — {mission.get('title', '?')}** (solo)\n*Taking the job.*"

        # Post claim notice
        try:
            results_ch = await _get_results_channel(client, fallback_channel=channel) if client else channel
            if results_ch:
                await results_ch.send(notice)
        except Exception as e:
            logger.warning(f"pc_sim claim post failed: {e}")

        mission["claimed"]            = True
        mission["pc_sim_claimed"]     = True
        mission["claim_party"]        = pc_name
        mission["npc_claimed"]        = False
        mission["pc_sim_complete_at"] = complete_dt.isoformat()
        mission["pc_sim_outcome"]     = outcome
        mission["resolved"]           = False
        updated = True

        logger.info(f"⚔️ PC sim claimed: {mission.get('title','?')} → {pc_name} ({outcome} at {complete_dt.strftime('%Y-%m-%d %H:%M')})")

    if updated:
        _save_missions(missions)


# ---------------------------------------------------------------------------
# Completion phase — resolves sim-claimed missions past their scheduled time
# ---------------------------------------------------------------------------

async def simulate_pc_personal_completions(channel, client=None) -> None:
    """
    Called hourly (alongside check_npc_completions).
    For each PC-sim-claimed mission past its completion time, simulate the result,
    record the outcome, and mark it resolved.
    """
    from src.mission_board import (
        _load_missions, _save_missions, _get_results_channel, _dm_notify,
    )
    from src.mission_outcomes import save_outcome
    from src.agents import generate_mission_text

    missions = _load_missions()
    now      = datetime.utcnow()
    updated  = False

    for mission in missions:
        if mission.get("resolved"):
            continue
        if not mission.get("pc_sim_claimed"):
            continue

        try:
            complete_dt = datetime.fromisoformat(mission["pc_sim_complete_at"])
        except Exception:
            continue
        if now < complete_dt:
            continue  # not time yet

        pc_name = mission.get("personal_for", mission.get("claim_party", "Unknown"))
        title   = mission.get("title", "Unknown Contract")
        faction = mission.get("faction", "")
        tier    = mission.get("tier", "standard")
        outcome = mission.get("pc_sim_outcome", "complete")
        success = outcome == "complete"

        # Generate simulation report in character's voice
        try:
            prompt = _build_sim_complete_prompt(pc_name, mission, success)
            notice = await generate_mission_text(prompt)
        except Exception as e:
            logger.warning(f"pc_sim completion notice failed for {pc_name}: {e}")
            notice = None

        if not notice:
            if success:
                notice = f"🏆 **{pc_name} — {title}** (contract fulfilled)\n*Job done.*"
            else:
                notice = f"💢 **{pc_name} — {title}** (withdrawn — contractor retreated)\n*Not today. {pc_name} pulled back. Alive.*"

        # Post to results channel
        try:
            results_ch = await _get_results_channel(client, fallback_channel=channel) if client else channel
            if results_ch:
                await results_ch.send(notice)
        except Exception as e:
            logger.warning(f"pc_sim completion post failed: {e}")

        # Record in world memory — npcs_killed always empty (rule: PCs don't log NPC kills here)
        save_outcome({
            "mission_id":       mission.get("id") or None,
            "mission_title":    title,
            "faction":          faction,
            "opposing_faction": mission.get("opposing_faction", ""),
            "tier":             tier,
            "completed_by":     pc_name,
            "completed_at":     now.strftime("%Y-%m-%d"),
            "result":           "completed" if success else "failed",
            "npcs_killed":      "",
            "key_decisions":    "",
            "location_changes": "",
            "loose_threads":    "" if success else f"{pc_name} retreated -- mission incomplete.",
            "notable_moments":  notice,
            "consequences":     [],
        })

        # DM notification
        if client:
            emoji = "🏆" if success else "💢"
            status = "Completed (solo sim)" if success else "Failed — retreated (solo sim)"
            try:
                from src.mission_board import _dm_notify as _dn
                await _dn(
                    client,
                    f"{emoji} PC Solo Sim — {title}",
                    f"**Character:** {pc_name} | **Faction:** {faction} | **Tier:** {tier.upper()}\n"
                    f"**Status:** {status}\n\n{notice}",
                )
            except Exception:
                pass

        mission["resolved"] = True
        if success:
            mission["completed"] = True
        else:
            mission["failed"] = True
        updated = True

        logger.info(f"{'🏆' if success else '💢'} PC sim {'completed' if success else 'failed'}: {title} by {pc_name}")

    if updated:
        _save_missions(missions)
