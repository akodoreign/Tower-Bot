"""Module generation cog — auto-generates D&D mission modules on player claims,
and provides /genmodule for manual generation.

Posts completed .docx files to MISSION_MODULE_CHANNEL_ID."""

import os
import asyncio
import discord
from discord import app_commands

from src.log import logger


# Channel for posting generated mission modules
MODULE_CHANNEL_ID = 1484147249637359769


async def generate_and_post_module(mission: dict, player_name: str, client) -> None:
    """Background task: generate a mission module .docx and post it to Discord."""
    from src.module_generator import generate_module
    from src.ollama_busy import mark_busy, mark_available

    title = mission.get("title", "Unknown Mission")
    logger.info(f"📖 Background module generation starting: '{title}' for {player_name}")

    # Mark Ollama as busy so news feed / mission board / captions skip gracefully
    mark_busy(f"module generation: {title}")
    logger.info(f"📖 Ollama marked BUSY — other systems will skip until module is done")

    try:
        output_path = await generate_module(mission, player_name)
    except Exception as e:
        logger.error(f"📖 Module generation failed for '{title}': {e}")
        # Notify DM of failure
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
        return
    finally:
        # ALWAYS clear the busy flag, even on error
        mark_available()
        logger.info(f"📖 Ollama marked AVAILABLE — other systems resuming")

    if output_path is None:
        logger.warning(f"📖 Module generation returned None for '{title}'")
        try:
            dm_id = int(os.getenv("DM_USER_ID", 0))
            if dm_id and client:
                dm_user = await client.fetch_user(dm_id)
                await dm_user.send(
                    f"⚠️ **Module generation failed** for *{title}* (claimed by {player_name}).\n"
                    f"Ollama may be overloaded or returned empty content."
                )
        except Exception:
            pass
        return

    # Post the .docx to the module channel
    channel = client.get_channel(MODULE_CHANNEL_ID)
    if channel is None:
        logger.warning(f"📖 Module channel {MODULE_CHANNEL_ID} not found — trying DM to DM user")
        try:
            dm_id = int(os.getenv("DM_USER_ID", 0))
            if dm_id:
                channel = await client.fetch_user(dm_id)
        except Exception:
            pass

    if channel is None:
        logger.error(f"📖 No channel available to post module for '{title}'")
        return

    try:
        file_size = output_path.stat().st_size
        faction = mission.get("faction", "Unknown")
        tier = mission.get("tier", "standard").upper()
        personal = f" *(personal contract for {mission.get('personal_for', '')})*" if mission.get("personal_for") else ""

        embed = discord.Embed(
            title=f"📖 Mission Module: {title}",
            description=(
                f"**Claimed by:** {player_name}{personal}\n"
                f"**Faction:** {faction} | **Tier:** {tier}\n"
                f"**File:** {output_path.name} ({file_size // 1024}KB)\n\n"
                f"*Full D&D 5e 2024 adventure module — ~2 hours of gameplay. "
                f"Print or read on any device.*"
            ),
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text="Tower of Last Chance — Auto-Generated Mission Module")

        file = discord.File(str(output_path), filename=output_path.name)
        await channel.send(embed=embed, file=file)
        logger.info(f"📖 Module posted to channel: '{title}' ({file_size // 1024}KB)")

    except Exception as e:
        logger.error(f"📖 Failed to post module to Discord: {e}")
        # Try DM as fallback
        try:
            dm_id = int(os.getenv("DM_USER_ID", 0))
            if dm_id and client:
                dm_user = await client.fetch_user(dm_id)
                file = discord.File(str(output_path), filename=output_path.name)
                await dm_user.send(
                    f"📖 Module for *{title}* (claimed by {player_name}) — "
                    f"couldn't post to channel, sending here instead.",
                    file=file,
                )
        except Exception as e2:
            logger.error(f"📖 DM fallback also failed: {e2}")


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

        await interaction.followup.send(
            f"📖 **Generating module for:** *{mission['title']}*\n"
            f"Claimer: {claimer} | Tier: {mission.get('tier', '?').upper()} | "
            f"CR: {__import__('src.module_generator', fromlist=['TIER_CR_MAP']).TIER_CR_MAP.get(mission.get('tier', 'standard'), 6)}\n"
            f"This takes 5-10 minutes. I'll post it to the module channel when done.",
            ephemeral=True,
        )

        # Fire background generation
        asyncio.get_event_loop().create_task(
            generate_and_post_module(mission, claimer, client)
        )
