"""Chat and conversation commands — /chat, /reset, on_message handler."""

import os
import random
import discord
from discord import app_commands

from src.log import logger
from src.character_profiles import has_character_profile
from src.nudge_state import has_been_nudged, mark_nudged


def setup(client):
    """Register chat commands on the client's command tree."""

    @client.tree.command(
        name="chat",
        description="Ask the Tower of Last Chance a question or talk to it in-character.",
    )
    @app_commands.describe(message="What do you say to the Tower?")
    async def chat(interaction: discord.Interaction, message: str):
        """Core chat command to talk to the Tower Oracle."""

        if len(message) > 2000:
            await interaction.response.send_message(
                "❌ Message too long (max 2000 characters).", ephemeral=True,
            )
            return

        cleaned = message.replace("\x00", "").strip()
        if not cleaned:
            await interaction.response.send_message(
                "❌ Please provide a non-empty message.", ephemeral=True,
            )
            return

        username = str(interaction.user)
        client.current_channel = interaction.channel
        logger.info(
            f"\x1b[31m{username}\x1b[0m : /chat [{cleaned}] in ({client.current_channel})"
        )

        await client.enqueue_message(interaction, cleaned)

        user_id = interaction.user.id

        # One-time character profile nudge
        if not has_character_profile(user_id) and not has_been_nudged(user_id):
            mark_nudged(user_id)
            await interaction.followup.send(
                "👁️ **The Tower watches you.**\n"
                "\u201cYou\u2019re a strange one in the Undercity.\n"
                "If you tell me your **name**, **class**, and what you\u2019re **good at**, "
                "I will remember you.\u201d\n\n"
                "**Option A \u2013 Quick profile (recommended):**\n"
                "Use `/setcharprofile` to tell me who you are.\n"
                "Example:\n"
                "`/setcharprofile profile: Name: Dusk | Class: Warlock 5 | Role: Face | "
                "Notes: Bad at saying no to gods`\n\n"
                "**Option B \u2013 Full D&D Beyond + Avrae (for power users):**\n"
                "1. On D&D Beyond: open your character \u2192 click **Share** \u2192 **Copy Link**.\n"
                "2. In this Discord, in a channel Avrae can see, run:\n"
                "`!import https://ddb.ac/characters/...`\n"
                "3. After import, set it active with:\n"
                "`!character <n>`\n"
                "4. You can check your link with `!ddb`.\n\n"
                "_Avrae will then know your full sheet; I\u2019ll still use `/setcharprofile` "
                "for personality & role flavor._",
                ephemeral=True,
            )

        # Occasional downtime reminder (~10% chance)
        DOWNTIME_NAG_CHANCE = 0.10
        if random.random() < DOWNTIME_NAG_CHANCE:
            if has_character_profile(user_id):
                await interaction.followup.send(
                    "\u23f3 **The Tower murmurs about idle hours\u2026**\n"
                    "Between dives, you can treat time as a resource too.\n"
                    "Talk with your DM about **downtime activities** in the Undercity:\n"
                    "- training, research, faction favors, crafting, information brokering,\n"
                    "- or running small jobs for gods, guilds, or Rift crews.\n\n"
                    "When you log your downtime, the Tower can turn it into **Kharma, favors, "
                    "and little boons** at the table.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "\u23f3 **The Tower eyes you curiously.**\n"
                    "You\u2019re still a shadow in the ledger \u2014 no profile, no proper account.\n\n"
                    "1. Use `/setcharprofile` so I know your **name, class, and role**.\n"
                    "2. Then, between sessions, tell your DM what your character does in "
                    "**downtime**: training, scheming, working for guilds, praying to gods.\n\n"
                    "The more clearly you describe downtime, the easier it is for the Tower "
                    "to reward you with **Kharma, perks, and story hooks**.",
                    ephemeral=True,
                )

    @client.tree.command(name="reset", description="Reset chat history")
    async def reset(interaction: discord.Interaction):
        client.reset_conversation_history()
        await interaction.response.send_message(
            "\U0001f504 Conversation reset.", ephemeral=False,
        )

    # --- on_message handler (replyAll mode) ---
    @client.event
    async def on_message(message: discord.Message):
        if client.is_replying_all:
            if message.author == client.user:
                return
            client.current_channel = message.channel
            await client.enqueue_message(message, message.content)
