"""Module generation cog — auto-generates D&D mission modules on player claims,
and provides /genmodule for manual generation.

Default pipeline:
  claimed mission -> table-first published-adventure module
  -> DM Guide, Module, Players Guide, Chart Pack, Maps manifest, ZIP.

The older novel-first pipeline remains available with MODULE_PIPELINE=novel."""

import os
import asyncio
import discord
from discord import app_commands

from src.log import logger

MODULE_CHANNEL_ID = int(os.getenv("MODULE_OUTPUT_CHANNEL_ID", "1484147249637359769"))


async def generate_and_post_module(mission: dict, player_name: str, client) -> None:
    """
    Background task: compile a mission into a playable module and post to Discord.
    """
    from src.mission_builder import generate_module, post_module_to_channel

    title = mission.get("title", "Unknown Mission")
    logger.info(f"📖 Module pipeline starting: '{title}' for {player_name}")

    try:
        output_path = await generate_module(mission, player_name)

        if output_path:
            logger.info(f"📖 Module generated: '{title}' → {output_path}")
            await post_module_to_channel(client, output_path, mission, player_name)
        else:
            logger.warning(f"📖 Module pipeline returned None for '{title}'")
            try:
                dm_id = int(os.getenv("DM_USER_ID", 0))
                if dm_id and client:
                    dm_user = await client.fetch_user(dm_id)
                    await dm_user.send(
                        f"❌ **Module generation failed** for *{title}* (claimed by {player_name}).\n"
                        f"Pipeline returned no output — check bot logs."
                    )
            except Exception:
                pass

    except Exception as e:
        logger.exception(f"📖 Module pipeline failed for '{title}': {e}")
        try:
            dm_id = int(os.getenv("DM_USER_ID", 0))
            if dm_id and client:
                dm_user = await client.fetch_user(dm_id)
                await dm_user.send(
                    f"❌ **Module generation failed** for *{title}* (claimed by {player_name}).\n"
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
        tier_cr = {
            "local": 4, "patrol": 4, "escort": 5, "standard": 6,
            "investigation": 6, "rift": 8, "dungeon": 8, "dungeon-delve": 8,
            "major": 8, "inter-guild": 10, "high-stakes": 10,
            "epic": 12, "divine": 12, "tower": 12,
        }
        cr = mission.get("cr", tier_cr.get(mission.get("tier", "standard"), 6))
        mission_type = mission.get("mission_type", "standard")

        await interaction.followup.send(
            f"📖 **Story pipeline starting:** *{mission['title']}*\n"
            f"Claimer: {claimer} | Tier: {mission.get('tier', '?').upper()} | CR: {cr}\n"
            f"Type: {mission_type} | Published module pipeline\n"
            f"I'll post the module package to the module channel when done.",
            ephemeral=True,
        )

        # Fire background compilation
        asyncio.get_running_loop().create_task(
            generate_and_post_module(mission, claimer, client)
        )
