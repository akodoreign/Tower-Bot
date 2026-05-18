"""
competitions — Undercity competition and tournament pipeline.

Handles all non-mission competitive events: arena combat brackets,
battle of the bands, wizard duels, craft fairs, lore championships, etc.

Each competition type has:
  - A sponsor faction (primary + optional co-sponsor)
  - A bracket or judged format
  - A skill pillar set (what checks the party faces)
  - A DM module generator (separate from the standard mission pipeline)

Competitions post to the mission board channel as claimable bracket missions.
Only rounds involving PCs generate full modules. NPC vs NPC rounds are
auto-resolved by the bracket engine and posted as result bulletins.

Public API
----------
  from src.competitions import get_competition_type, list_competition_types
  from src.competitions.bracket_engine import (
      create_competition, get_active_competitions,
      advance_bracket, auto_resolve_npc_round,
  )
  from src.competitions.post_competition import (
      post_bracket_announcement, post_round_mission, post_result_bulletin,
  )
"""

from .competition_types import CompetitionType, get_competition_type, list_competition_types

__all__ = ["CompetitionType", "get_competition_type", "list_competition_types"]
