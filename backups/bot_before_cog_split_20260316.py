## BACKUP OF src/bot.py BEFORE COG SPLIT — 2026-03-16
## This file contains the original monolithic bot.py for rollback purposes.
## To restore: copy this file to src/bot.py and delete src/cogs/

import os
import random
import asyncio
import discord
from discord import app_commands

from src.aclient import discordClient
from src.providers import ProviderType
from src import personas
from src.log import logger

from src.mission_board import (
    handle_reaction_claim,
    EMOJI_CLAIM,
)
from src.faction_reputation import format_full_rep_for_display, format_npc_rep_for_display

from src.character_profiles import (
    has_character_profile,
    load_character_profile,
    save_character_profile,
    load_character_appearance,
    save_character_appearance,
)
from src.nudge_state import (
    has_been_nudged,
    mark_nudged,
)
from src.ec_exchange import (
    format_exchange_line, format_all_prices, format_price_table, get_rate, PRICE_TABLES,
)
from src.rules_agent import answer_rules_question, lookup_spell_or_feature, COMMON_RULES_TOPICS
from src.npc_appearance import generate_all_npc_appearances, get_npc_appearance, get_npc_sd_prompt
from src.style_agent import (
    describe_character_style, faction_style_summary,
    FACTION_STYLE_NOTES, OCCASION_NOTES,
)
from src.player_listings import (
    _TowerBayModal, format_player_listings_embed,
)


class _BulletinApprovalView(discord.ui.View):
    def __init__(self, formatted, raw, channel_id):
        super().__init__(timeout=300)
        self.formatted = formatted
        self.raw = raw
        self.channel_id = channel_id

    @discord.ui.button(label="Post it", style=discord.ButtonStyle.green, emoji="✅")
    async def approve(self, interaction, button):
        from src.news_feed import _write_memory
        _write_memory(self.raw)
        channel = interaction.client.get_channel(self.channel_id)
        if channel:
            await channel.send(self.formatted)
            await interaction.response.edit_message(content="✅ **Posted to channel.**", view=None)
        else:
            await interaction.response.edit_message(content="❌ Could not find channel to post to.", view=None)

    @discord.ui.button(label="Discard", style=discord.ButtonStyle.red, emoji="❌")
    async def discard(self, interaction, button):
        await interaction.response.edit_message(content="❌ **Bulletin discarded.**", view=None)

    @discord.ui.button(label="Regenerate", style=discord.ButtonStyle.grey, emoji="🔄")
    async def regenerate(self, interaction, button):
        await interaction.response.defer()
        from src.news_feed import generate_bulletin_draft
        formatted, raw = await generate_bulletin_draft()
        if not formatted:
            await interaction.followup.send("❌ Regeneration failed.", ephemeral=True)
            return
        self.formatted = formatted
        self.raw = raw
        new_view = _BulletinApprovalView(formatted, raw, self.channel_id)
        await interaction.edit_original_response(content=f"**📝 Draft bulletin for review:**\n\n{formatted}", view=new_view)


## NOTE: The full original run_discord_bot() function was ~1700 lines.
## It has been split into src/cogs/{chat,character,missions,economy,rules_lookup,images,world,admin}.py
## See the new src/bot.py for the loader.
