"""Rules & spell lookup commands — /rules, /spell."""

import discord
from discord import app_commands

from src.rules_agent import answer_rules_question, lookup_spell_or_feature


def setup(client):
    """Register rules lookup commands on the client's command tree."""

    @client.tree.command(
        name="rules",
        description="Look up a D&D 5e 2024 rule, condition, or mechanic"
    )
    @app_commands.describe(
        question="What rule do you want to look up? e.g. 'how does grappling work', 'exhaustion', 'opportunity attacks'"
    )
    async def rules_command(interaction: discord.Interaction, question: str):
        await interaction.response.defer(ephemeral=False)

        result = await answer_rules_question(question)

        colour = {
            "high":      discord.Color.green(),
            "medium":    discord.Color.orange(),
            "low":       discord.Color.red(),
            "not_found": discord.Color.dark_grey(),
        }.get(result.confidence, discord.Color.blurple())

        embed = discord.Embed(
            title=f"\U0001f4d5 Rules: {question[:60]}",
            description=result.answer,
            color=colour,
        )

        if result.caveat:
            embed.add_field(name="\U0001f3f0 Undercity Rules Note", value=result.caveat, inline=False)

        conf_label = {
            "high":      "\u2705 PHB sourced",
            "medium":    "\u26a0\ufe0f General 5e 2024 knowledge",
            "low":       "\u274c Low confidence",
            "not_found": "\u2753 Not found",
        }.get(result.confidence, "")
        embed.set_footer(text=f"{conf_label} | D&D 5e 2024 (5.5e) | Tower of Last Chance campaign")

        await interaction.followup.send(embed=embed)

    @client.tree.command(
        name="spell",
        description="Look up a D&D 5e 2024 spell or class feature"
    )
    @app_commands.describe(
        name="Name of the spell or class feature, e.g. 'Fireball', 'Sneak Attack', 'Second Wind'"
    )
    async def spell_command(interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=False)

        result = await lookup_spell_or_feature(name)

        embed = discord.Embed(
            title=f"\u2728 Lookup: {name[:60]}",
            description=result,
            color=discord.Color.purple(),
        )
        embed.set_footer(text="D&D 5e 2024 (5.5e) | Source: PHB + campaign docs")
        await interaction.followup.send(embed=embed)
