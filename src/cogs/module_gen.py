"""Module generation cog — auto-generates D&D mission modules on player claims,
and provides /genmodule for manual generation.

NEW ARCHITECTURE (v2):
  Stage 1: Mission JSON is built from mission board data
  Stage 2: MissionCompiler uses agents + skills to expand → .docx → Discord

Posts completed .docx files to channel 1484147249637359769."""

import os
import asyncio
import discord
from discord import app_commands

from src.log import logger
from src.mission_compiler import MissionCompiler, build_mission_json


# Channel for posting generated mission modules
MODULE_CHANNEL_ID = 1484147249637359769


async def generate_and_post_module(mission: dict, player_name: str, client) -> None:
    """
    Background task: compile a mission into a .docx module and post to Discord.
    
    Uses the new MissionCompiler with agent enhancement and skill injection.
    """
    title = mission.get("title", "Unknown Mission")
    logger.info(f"📖 Mission compilation starting: '{title}' for {player_name}")
    
    # Build mission JSON from the mission board dict
    # The mission_compiler handles busy flag internally
    mission_json = build_mission_json(
        title=title,
        faction=mission.get("faction", "Independent"),
        tier=mission.get("tier", "standard"),
        mission_type=mission.get("mission_type", "standard"),
        cr=mission.get("cr", 6),
        party_level=mission.get("party_level", 5),
        player_name=player_name,
        player_count=mission.get("player_count", 4),
    )
    
    # Add any existing content from the mission board
    if mission.get("body"):
        mission_json["content"] = mission_json.get("content", {})
        mission_json["content"]["board_description"] = mission.get("body")
    
    if mission.get("reward"):
        mission_json["metadata"]["reward"] = mission.get("reward")
    
    if mission.get("personal_for"):
        mission_json["metadata"]["personal_for"] = mission.get("personal_for")
    
    # Compile using the new agent-enhanced compiler
    compiler = MissionCompiler(client)
    
    try:
        output_path = await compiler.compile_and_post(mission_json, player_name, client)
        
        if output_path:
            logger.info(f"📖 Module compilation complete: '{title}' → {output_path}")
        else:
            logger.warning(f"📖 Module compilation returned None for '{title}'")
            
    except Exception as e:
        logger.exception(f"📖 Module compilation failed for '{title}': {e}")
        # Notify DM
        try:
            dm_id = int(os.getenv("DM_USER_ID", 0))
            if dm_id and client:
                dm_user = await client.fetch_user(dm_id)
                await dm_user.send(
                    f"❌ **Module compilation failed** for *{title}* (claimed by {player_name}).\n"
                    f"Error: `{type(e).__name__}: {e}`"
                )
        except Exception:
            pass


def setup(client):
    """Register module generation commands."""

    @client.tree.command(
        name="genmodule",
        description="[DM only] Manually generate a mission module .docx for a claimed mission."
    )
    @app_commands.describe(
        title="Part of the mission title to search for"
    )
    async def genmodule(interaction: discord.Interaction, title: str):
        dm_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_id:
            await interaction.response.send_message("❌ DM only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from src.mission_board import _load_missions
        missions = _load_missions()

        # Find matching mission
        matches = [
            m for m in missions
            if title.lower() in m.get("title", "").lower()
        ]

        if not matches:
            await interaction.followup.send(
                f"❌ No mission found matching **'{title}'**.", ephemeral=True
            )
            return

        if len(matches) > 1:
            names = "\n".join(f"- {m['title']}" for m in matches)
            await interaction.followup.send(
                f"❌ Multiple matches — be more specific:\n{names}", ephemeral=True
            )
            return

        mission = matches[0]
        claimer = mission.get("player_claimer", "Unknown Adventurer")

        # Get CR from mission or estimate from tier
        from src.mission_compiler import MissionCompiler
        tier_cr = {
            "local": 4, "patrol": 4, "escort": 5, "standard": 6,
            "investigation": 6, "rift": 8, "dungeon": 8, "dungeon-delve": 8,
            "major": 8, "inter-guild": 10, "high-stakes": 10,
            "epic": 12, "divine": 12, "tower": 12,
        }
        cr = mission.get("cr", tier_cr.get(mission.get("tier", "standard"), 6))
        mission_type = mission.get("mission_type", "standard")

        await interaction.followup.send(
            f"📖 **Compiling module for:** *{mission['title']}*\n"
            f"Claimer: {claimer} | Tier: {mission.get('tier', '?').upper()} | CR: {cr}\n"
            f"Type: {mission_type} | Using: DNDExpert + DNDVeteran + AICritic agents\n"
            f"This takes 5-10 minutes. I'll post it to the module channel when done.",
            ephemeral=True,
        )

        # Fire background compilation
        asyncio.get_event_loop().create_task(
            generate_and_post_module(mission, claimer, client)
        )
