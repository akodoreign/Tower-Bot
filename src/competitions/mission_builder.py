"""
mission_builder.py — Competition round DM module generator.

Separate from the standard mission pipeline (json_generator.py).
Generates a round-specific DM module in bracket format:
  - Opponent profile
  - Venue and crowd
  - Ordered phase challenges with DCs
  - Win/loss/draw outcomes
  - Advancement or elimination

Uses KimiAgent for prose quality. Full resource cop integration.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from .competition_types import CompetitionType, get_competition_type

logger = logging.getLogger(__name__)

TOWER_YEAR_OFFSET = 10


def _tower_date(dt: datetime) -> str:
    t = dt.replace(year=dt.year + TOWER_YEAR_OFFSET)
    return t.strftime("%d %b %Y")


async def generate_round_module(
    comp_id:       int,
    comp_type:     CompetitionType,
    round_number:  int,
    total_rounds:  int,
    contestant:    Dict,   # {"name": str, "faction": str, "entry_type": "pc"|"npc"}
    opponent:      Dict,   # same structure
    match:         Dict,   # bracket match dict
    round_date:    Optional[datetime] = None,
) -> Optional[str]:
    """
    Generate the full DM module text for one competition round.
    Returns formatted markdown string or None on failure.

    Caller must handle cop permission and pipeline registration.
    """
    from src.agents import generate_with_kimi
    from src.db_api import raw_query

    round_date = round_date or datetime.now() + timedelta(hours=comp_type.expire_hours)
    tower_dt   = _tower_date(round_date)

    # Scale DCs by round number — later rounds are harder
    dc_bump = (round_number - 1) * 2

    # Pull opponent NPC detail from DB if available
    opp_detail = ""
    if opponent.get("entry_type") == "npc":
        rows = raw_query(
            "SELECT role, data_json FROM npcs WHERE name = %s LIMIT 1",
            (opponent["name"],),
        ) or []
        if rows:
            import json as _json
            role = (rows[0].get("role") or "")[:120]
            dj   = {}
            if rows[0].get("data_json"):
                try:
                    dj = _json.loads(rows[0]["data_json"]) if isinstance(rows[0]["data_json"], str) else rows[0]["data_json"]
                except Exception:
                    pass
            motivation = dj.get("motivation") or dj.get("secret") or ""
            opp_detail = f"{role}. {motivation}".strip(". ")

    # Build phase table for prompt
    phase_lines = []
    for i, phase in enumerate(comp_type.phases):
        dc = phase.dc_base + dc_bump
        adv_note = " (Advantage if previous phase won)" if phase.advantage_if_prev_won else ""
        phase_lines.append(
            f"  Phase {i+1} — {phase.name}: {phase.description}\n"
            f"  Skill: {phase.skill} | DC: {dc}{adv_note}"
        )

    # Reward info
    is_final = round_number >= total_rounds
    reward_ec = comp_type.reward_ec_final if is_final else (
        comp_type.reward_ec_base * round_number
    )
    kharma = comp_type.kharma_per_win * round_number

    sponsor_str = " + ".join(comp_type.sponsors)
    venue       = comp_type.flavor_venues[round_number % len(comp_type.flavor_venues)]
    crowd_note  = comp_type.flavor_crowds[round_number % len(comp_type.flavor_crowds)]

    prompt = f"""You are writing a DM-facing module document for the Undercity Dispatch tabletop campaign.

SETTING: The Undercity — a sealed city under a Dome. Dense, mixed-species, dark fantasy/cyberpunk tone.
Community, pride, dark humour alongside real danger. NOT grimdark for its own sake.

COMPETITION: {comp_type.name}
SPONSORED BY: {sponsor_str}
ROUND: {round_number} of {total_rounds}{"  ← FINAL" if is_final else ""}
DATE (Tower calendar): {tower_dt}

CONTESTANT (the party): {contestant["name"]} — {contestant.get("faction","Adventurers Guild")}
OPPONENT: {opponent["name"]} — {opponent.get("faction","Independent")}
{f'Opponent background: {opp_detail}' if opp_detail else ''}

VENUE: {venue}
CROWD: {crowd_note}

SKILL PILLARS FOR THIS COMPETITION: {", ".join(comp_type.skill_pillars)}

ROUND PHASE STRUCTURE:
{chr(10).join(phase_lines)}

REWARDS:
- Win this round: {reward_ec:,} EC + {kharma} Kharma + advancement{"  → CHAMPION TITLE" if is_final else f" to Round {round_number+1}"}
- Loss: Elimination + {comp_type.reward_ec_base // 2:,} EC consolation

Write a DM-facing module document with these sections. Use markdown headers. Be specific — name places, NPCs, and stakes.

## Competition: {comp_type.name} — Round {round_number}
*{contestant["name"]} vs {opponent["name"]}*

## The Stakes
What winning this round means. Who is watching and why. What faction interests are riding on the outcome. Keep it specific — name people, not abstractions.

## Opponent Profile: {opponent["name"]}
Their record and reputation in this circuit. Fighting/performing style. Known weaknesses. Who is backing them and what they expect. 3-4 sentences.

## Venue & Atmosphere
Describe the specific location. Who is in the crowd and why they're invested. Any environmental factors the DM should flag (lighting, acoustics, distractions). 2-3 sentences.

## Round Structure
For each phase below, write 1-2 sentences of DM description, then the mechanical call:

{chr(10).join(f"### Phase {i+1}: {p.name}" for i, p in enumerate(comp_type.phases))}

(For each: DM flavour, then: **Check:** {comp_type.phases[0].skill} DC [X] — [what success looks like / what failure costs])

## Outcomes
**Victory:** [immediate reward + narrative consequence + what happens next]
**Defeat:** [elimination narrative + consolation + any ongoing hook]
**Draw (if applicable):** [tiebreaker mechanic or judge decision]

## Complications (optional — DM discretion)
One optional complication the DM can introduce: rival faction interference, side bet gone wrong, a judge with a conflict of interest, or a crowd moment that changes the stakes. Keep it optional, not mandatory.

FORMAT RULES:
- Write for a DM who will run this in real time
- Every NPC mentioned should have a name and a stake in the outcome
- DCs should match the phase table above — do not invent new ones
- Do not preamble — output the document only
- Total length: 500-800 words"""

    try:
        text = await generate_with_kimi(prompt, temperature=0.75)
        if not text:
            logger.warning(
                f"[comp-builder] KimiAgent returned empty for "
                f"'{comp_type.name}' R{round_number} {contestant['name']} vs {opponent['name']}"
            )
            return None
        return text
    except Exception as e:
        logger.error(f"[comp-builder] Generation failed: {e}", exc_info=True)
        return None


async def build_round_mission(
    comp_id:      int,
    comp_type:    CompetitionType,
    round_number: int,
    total_rounds: int,
    contestant:   Dict,
    opponent:     Dict,
    match:        Dict,
) -> Optional[Dict]:
    """
    Full pipeline wrapper with resource cop. Returns a mission dict
    ready for the mission board, or None if deferred/failed.

    Mission dict includes:
      title, body, faction, type, tier, reward, expires_at,
      comp_id, comp_round, bracket_match (serialised)
    """
    from src.resource_cop import (
        wait_for_ollama_turn, start_pipeline, finish_pipeline, append_pipeline_failure,
    )

    is_final = round_number >= total_rounds
    label    = f"competition_round_gen_{'final' if is_final else f'r{round_number}'}"

    decision = await wait_for_ollama_turn(label, track="primary")
    if not decision.run_now:
        logger.warning(f"[comp-builder] Deferred by cop: {decision.reason}")
        return None

    run = await start_pipeline(
        label,
        mission_title=f"[comp] {comp_type.name} R{round_number}: {contestant['name']} vs {opponent['name']}",
        mission_type=comp_type.slug,
        phase="generating",
    )

    try:
        now        = datetime.now()
        round_date = now + timedelta(hours=comp_type.expire_hours)
        text       = await generate_round_module(
            comp_id, comp_type, round_number, total_rounds,
            contestant, opponent, match, round_date,
        )
        if not text:
            await finish_pipeline(run.run_id, status="empty")
            return None

        import json as _json
        # Tier scales with round
        tiers      = ["local", "standard", "investigation", "major", "high-stakes", "epic"]
        tier_idx   = min(round_number - 1, len(tiers) - 1)
        tier       = tiers[tier_idx]
        reward_ec  = comp_type.reward_ec_final if is_final else comp_type.reward_ec_base * round_number
        reward_str = f"{reward_ec:,} EC + {comp_type.kharma_per_win * round_number} Kharma"

        mission = {
            "title":         f"[{comp_type.name}] R{round_number}: {contestant['name']} vs {opponent['name']}",
            "body":          text,
            "public_text":   (
                f"{contestant['name']} advances to Round {round_number} of the {comp_type.name}. "
                f"Next opponent: {opponent['name']} ({opponent.get('faction','Independent')}). "
                f"Venue: {comp_type.flavor_venues[0]}."
            ),
            "faction":       comp_type.sponsors[0],
            "type":          comp_type.slug,
            "tier":          tier,
            "reward":        reward_str,
            "expires_at":    round_date.isoformat(),
            "comp_id":       comp_id,
            "comp_round":    round_number,
            "bracket_match": _json.dumps(match, default=str),
            "personal_for":  contestant["name"] if contestant.get("entry_type") == "pc" else "",
        }

        await finish_pipeline(run.run_id, status="finished")
        logger.info(
            f"[comp-builder] Round module built: '{mission['title']}' "
            f"tier={tier} reward={reward_str}"
        )
        return mission

    except Exception as exc:
        await append_pipeline_failure(run.run_id, exc)
        await finish_pipeline(run.run_id, status="failed")
        logger.error(f"[comp-builder] Failed: {exc}", exc_info=True)
        return None
