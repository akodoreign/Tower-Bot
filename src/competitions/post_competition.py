"""
post_competition.py — Discord posting for competition events.

Handles:
  - Bracket announcement (new competition opened)
  - Round mission posting (PC-involved round → claimable mission on board)
  - NPC round result bulletin (auto-resolved → news channel bulletin)
  - Champion bulletin (competition complete)
  - Tick function called from aclient.py loops
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .bracket_engine import (
    get_active_competitions, get_pending_rounds, is_pc_round,
    auto_resolve_npc_match, get_standings, _load_competition,
    _ensure_tables,
)
from .competition_types import get_competition_type

logger = logging.getLogger(__name__)

TOWER_YEAR_OFFSET = 10


def _dual_ts() -> str:
    now   = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    return f"{now.strftime('%Y-%m-%d %H:%M')} | Tower: {tower.strftime('%d %b %Y, %H:%M')}"


# ---------------------------------------------------------------------------
# Announcement — posted to news channel when a competition opens
# ---------------------------------------------------------------------------

def format_bracket_announcement(comp: Dict, comp_type) -> str:
    entries  = comp.get("entries", [])
    pc_names = [e["name"] for e in entries if e.get("entry_type") == "pc"]
    npc_sample = [e["name"] for e in entries if e.get("entry_type") == "npc"][:4]

    contestant_lines = []
    for name in pc_names:
        contestant_lines.append(f"  ⚔️ **{name}** (PC)")
    for name in npc_sample:
        contestant_lines.append(f"  · {name}")
    if len(entries) > len(pc_names) + len(npc_sample):
        contestant_lines.append(f"  · ...and {len(entries) - len(pc_names) - len(npc_sample)} others")

    sponsor_str = " + ".join(comp_type.sponsors)
    lines = [
        f"🏆 **{comp['name'].upper()}**",
        f"-# {_dual_ts()}",
        "",
        f"*{comp_type.description}*",
        "",
        f"**Sponsored by:** {sponsor_str}",
        f"**Format:** {'Elimination bracket' if comp_type.format == 'bracket' else 'Judged competition'}",
        f"**Contestants:** {len(entries)} entered",
        "",
        "**Registered:**",
    ] + contestant_lines + [
        "",
        "-# Round 1 missions will post to the board when scheduled. Claim your round before the date passes.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# NPC round result bulletin — posted to news channel
# ---------------------------------------------------------------------------

_NPC_RESULT_LINES = [
    "{winner} defeated {loser} in Round {round}. The result was not disputed.",
    "{loser} is out. {winner} advances to the next round.",
    "Round {round}: {winner} over {loser}. Clean result. {loser} is eliminated.",
    "{winner} took the Round {round} bout. {loser} fought well. Not well enough.",
    "The Round {round} match between {winner} and {loser} went to {winner}.",
]


def format_npc_result_bulletin(result: Dict, comp_name: str, comp_type) -> str:
    winner = result["winner"]
    loser  = result["loser"]
    rnd    = result["round"]
    line   = random.choice(_NPC_RESULT_LINES).format(winner=winner, loser=loser, round=rnd)

    lines = [
        f"⚔️ **{comp_name.upper()} — ROUND {rnd} RESULT**",
        f"-# {_dual_ts()}",
        "",
        line,
        "",
        f"-# {comp_type.name} — {' + '.join(comp_type.sponsors)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Champion bulletin
# ---------------------------------------------------------------------------

def format_champion_bulletin(champion: str, comp: Dict, comp_type) -> str:
    sponsor_str = " + ".join(comp_type.sponsors)
    lines = [
        f"🏆 **{comp['name'].upper()} — CHAMPION**",
        f"-# {_dual_ts()}",
        "",
        f"**{champion}** has won the {comp_type.name}.",
        "",
        f"*{comp_type.description}*",
        "",
        f"Sponsored by {sponsor_str}.",
        "-# Final standings available from the Guild of Ashen Scrolls archive.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tick — called from aclient.py loops
# ---------------------------------------------------------------------------

async def check_competition_tick(
    mission_board_channel,
    news_channel,
    client=None,
) -> None:
    """
    Process all active/upcoming competitions for this tick.

    For each pending match that is due:
      - If NPC vs NPC: auto-resolve, post result bulletin to news channel
      - If PC vs NPC or PC vs PC: generate round module and post to mission board

    Called from mission_board_loop (has access to both channels).
    """
    _ensure_tables()

    try:
        competitions = get_active_competitions()
    except Exception as e:
        logger.warning(f"[comp-tick] Could not load competitions: {e}")
        return

    for comp in competitions:
        comp_type = get_competition_type(comp["slug"])
        if not comp_type:
            logger.warning(f"[comp-tick] Unknown comp type slug: {comp['slug']}")
            continue

        try:
            await _process_competition(comp, comp_type, mission_board_channel, news_channel)
        except Exception as e:
            logger.exception(f"[comp-tick] Error processing comp_id={comp['id']}: {e}")


async def _process_competition(
    comp:                  Dict,
    comp_type,
    mission_board_channel,
    news_channel,
) -> None:
    from src.db_api import raw_query
    from .bracket_engine import get_pending_rounds
    from .mission_builder import build_round_mission
    from src.mission_board import _add_mission, _build_mission_embed, EMOJI_CLAIM
    from src.faction_reputation import get_faction_color, get_faction_tier_label

    comp_id = comp["id"]
    pending = get_pending_rounds(comp_id)
    if not pending:
        return

    # Determine total rounds from competition type
    bracket   = comp.get("bracket", {})
    all_rounds = [m["round"] for m in bracket.get("history", [])]
    max_round_seen = max(all_rounds) if all_rounds else 0
    total_rounds   = comp_type.rounds_bracket

    for match in pending:
        round_number = match["round"]

        if not is_pc_round(match):
            # Auto-resolve NPC vs NPC
            result = auto_resolve_npc_match(comp_id, match)
            bulletin = format_npc_result_bulletin(result, comp["name"], comp_type)
            try:
                from src.news_feed import wrap_bulletin, make_bulletin_view
                await news_channel.send(
                    embed=wrap_bulletin(bulletin, "competition"),
                    view=make_bulletin_view(bulletin, "competition",
                                           source_attribution=comp_type.sponsors[0]),
                )
                logger.info(
                    f"[comp-tick] NPC result posted: {result['winner']} beat {result['loser']} "
                    f"(R{round_number}, comp_id={comp_id})"
                )
            except Exception as e:
                logger.warning(f"[comp-tick] Could not post NPC result bulletin: {e}")

            # Check if competition is now complete
            await _check_completion(comp_id, comp["name"], comp_type, news_channel)

        else:
            # PC round — generate module and post to mission board
            if match.get("status") == "mission_posted":
                continue  # Already posted this round

            pc_name  = match["a"] if match.get("a_type") == "pc" else match["b"]
            opp_name = match["b"] if match.get("a_type") == "pc" else match["a"]

            contestant = {
                "name":       pc_name,
                "entry_type": "pc",
                "faction":    _get_entry_faction(comp_id, pc_name),
            }
            opponent = {
                "name":       opp_name,
                "entry_type": match.get("b_type") if match.get("a_type") == "pc" else match.get("a_type"),
                "faction":    _get_entry_faction(comp_id, opp_name),
            }

            mission = await build_round_mission(
                comp_id, comp_type, round_number, total_rounds,
                contestant, opponent, match,
            )

            if not mission:
                logger.info(f"[comp-tick] Round module deferred for comp_id={comp_id} R{round_number}")
                continue

            # Post to mission board
            faction     = comp_type.sponsors[0]
            embed_color = get_faction_color(faction) if faction else 0xE6C300
            tier_label  = get_faction_tier_label(faction) if faction else "😐 Neutral"
            expires_dt  = datetime.fromisoformat(mission["expires_at"])
            days_left   = max(1, (expires_dt - datetime.utcnow()).days)

            embed = _build_mission_embed(mission, embed_color, tier_label, days_left,
                                         personal_for=mission.get("personal_for", ""))
            msg = await mission_board_channel.send(embed=embed)
            mission["message_id"] = msg.id
            _add_mission(mission)

            try:
                await msg.add_reaction(EMOJI_CLAIM)
            except Exception:
                pass

            # Mark match as mission_posted in bracket
            _mark_match_mission_posted(comp_id, match, msg.id)

            logger.info(
                f"[comp-tick] Round mission posted: '{mission['title']}' "
                f"(comp_id={comp_id} R{round_number})"
            )


async def _check_completion(comp_id: int, comp_name: str, comp_type, news_channel) -> None:
    """Post champion bulletin if the competition just completed."""
    from src.db_api import raw_query
    comp = _load_competition(comp_id)
    if not comp or comp.get("status") != "complete":
        return

    rows = raw_query(
        "SELECT name FROM competition_entries WHERE comp_id = %s AND status = 'champion' LIMIT 1",
        (comp_id,),
    ) or []
    if not rows:
        return

    champion = rows[0]["name"]
    bulletin = format_champion_bulletin(champion, {"name": comp_name}, comp_type)
    try:
        from src.news_feed import wrap_bulletin, make_bulletin_view
        await news_channel.send(
            embed=wrap_bulletin(bulletin, "competition"),
            view=make_bulletin_view(bulletin, "competition",
                                    source_attribution=comp_type.sponsors[0]),
        )
        logger.info(f"[comp-tick] Champion bulletin posted: {champion} ({comp_name})")
    except Exception as e:
        logger.warning(f"[comp-tick] Could not post champion bulletin: {e}")


def _get_entry_faction(comp_id: int, name: str) -> str:
    from src.db_api import raw_query
    rows = raw_query(
        "SELECT faction FROM competition_entries WHERE comp_id = %s AND name = %s LIMIT 1",
        (comp_id, name),
    ) or []
    return rows[0]["faction"] if rows else "Independent"


def _mark_match_mission_posted(comp_id: int, match: Dict, message_id: int) -> None:
    """Update bracket JSON to mark this match as having a mission posted."""
    from .bracket_engine import _load_competition, _save_bracket
    comp = _load_competition(comp_id)
    if not comp:
        return
    bracket = comp["bracket"]
    for m in bracket.get("matches", []):
        if m["a"] == match["a"] and m["b"] == match["b"] and m["round"] == match["round"]:
            m["status"]     = "mission_posted"
            m["mission_id"] = message_id
    _save_bracket(comp_id, bracket)
