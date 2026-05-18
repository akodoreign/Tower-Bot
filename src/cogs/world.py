"""World & faction commands — /factionrep, /partyrep, /style."""

import discord
from discord import app_commands

from src.faction_reputation import format_full_rep_for_display, format_npc_rep_for_display
from src.style_agent import (
    describe_character_style, faction_style_summary,
    FACTION_STYLE_NOTES,
)


def setup(client):
    """Register world/faction commands on the client's command tree."""

    @client.tree.command(
        name="factionrep",
        description="Show current faction reputation standings."
    )
    async def factionrep(interaction: discord.Interaction):
        rep_text = format_full_rep_for_display()
        embed = discord.Embed(
            title="\U0001f4ca Faction Reputation Standings",
            description=rep_text,
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text="3 events = 1 tier shift \u2022 \u2705 complete +1 \u2022 \u274c fail/expire \u22121")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @client.tree.command(
        name="partyrep",
        description="Show NPC adventurer party reputation and track records."
    )
    async def partyrep(interaction: discord.Interaction):
        rep_text = format_npc_rep_for_display()
        embed = discord.Embed(
            title="\U0001f4ca NPC Adventurer Party Records",
            description=rep_text,
            color=discord.Color.dark_teal(),
        )
        embed.set_footer(text="5 events = 1 tier shift \u2022 80% complete / 20% fail chance")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---- /style ----

    @client.tree.command(
        name="style",
        description="Get a clothing and style description for your character or a faction"
    )
    @app_commands.describe(
        character="Character name (leave blank for faction-only lookup)",
        char_class="Character class, e.g. 'Fighter', 'Rogue', 'Cleric'",
        faction="Faction affiliation",
        occasion="What is the occasion?",
        notes="Any extra context, e.g. 'she never wears skirts' or 'he always carries a sword'",
    )
    @app_commands.choices(faction=[
        app_commands.Choice(name="Iron Fang Consortium",  value="iron_fang"),
        app_commands.Choice(name="Argent Blades",         value="argent_blades"),
        app_commands.Choice(name="Wardens of Ash",        value="wardens_of_ash"),
        app_commands.Choice(name="Serpent Choir",         value="serpent_choir"),
        app_commands.Choice(name="Obsidian Lotus",        value="obsidian_lotus"),
        app_commands.Choice(name="Glass Sigil",           value="glass_sigil"),
        app_commands.Choice(name="Patchwork Saints",      value="patchwork_saints"),
        app_commands.Choice(name="Adventurers' Guild",    value="adventurers_guild"),
        app_commands.Choice(name="Ashen Scrolls",         value="ashen_scrolls"),
        app_commands.Choice(name="Independent",           value="independent"),
    ])
    @app_commands.choices(occasion=[
        app_commands.Choice(name="Combat",          value="combat"),
        app_commands.Choice(name="Diplomacy",       value="diplomacy"),
        app_commands.Choice(name="Infiltration",    value="infiltration"),
        app_commands.Choice(name="Downtime",        value="downtime"),
        app_commands.Choice(name="Arena",           value="arena"),
        app_commands.Choice(name="Church/Temple",   value="church"),
        app_commands.Choice(name="Market",          value="market"),
        app_commands.Choice(name="Tavern",          value="tavern"),
        app_commands.Choice(name="The Warrens",     value="warrens"),
        app_commands.Choice(name="Guild Meeting",   value="guild meeting"),
    ])
    async def style_command(
        interaction: discord.Interaction,
        faction: str = "independent",
        occasion: str = "downtime",
        character: str = "",
        char_class: str = "",
        notes: str = "",
    ):
        await interaction.response.defer(ephemeral=False)

        if not character:
            summary = faction_style_summary(faction)
            faction_data = FACTION_STYLE_NOTES.get(faction, {})
            embed = discord.Embed(
                title=f"\U0001f9f5 {faction_data.get('name', faction)} \u2014 Style Profile",
                description=summary,
                color=discord.Color.from_rgb(180, 140, 80),
            )
            embed.set_footer(text="Use /style character: to generate a specific character outfit")
            await interaction.followup.send(embed=embed)
            return

        description = await describe_character_style(
            char_name=character,
            char_class=char_class,
            faction=faction,
            occasion=occasion,
            extra_notes=notes,
        )

        faction_data = FACTION_STYLE_NOTES.get(faction, {})
        occasion_label = occasion.replace("_", " ").title()

        embed = discord.Embed(
            title=f"\U0001f9f5 {character} \u2014 {occasion_label} Outfit",
            description=description,
            color=discord.Color.from_rgb(180, 140, 80),
        )
        embed.set_footer(
            text=f"Faction: {faction_data.get('name', faction)} | Class: {char_class or 'unspecified'} | Occasion: {occasion_label}"
        )
        await interaction.followup.send(embed=embed)
