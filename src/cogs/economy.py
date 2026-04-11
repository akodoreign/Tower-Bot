"""Economy commands — /finances, /prices."""

import os
import discord
from discord import app_commands

from src.log import logger
from src.ec_exchange import format_all_prices, format_price_table, get_rate, PRICE_TABLES


def setup(client):
    """Register economy commands on the client's command tree."""

    @client.tree.command(
        name="finances",
        description="Undercity economy: EC/Kharma exchange rate and current prices"
    )
    @app_commands.describe(section="Which price table to show (leave blank for exchange rate + overview)")
    @app_commands.choices(section=[
        app_commands.Choice(name="Quest Rewards",     value="quest_rewards"),
        app_commands.Choice(name="Hireable Costs",    value="hireables"),
        app_commands.Choice(name="Services",          value="services"),
        app_commands.Choice(name="Common Goods",      value="goods"),
        app_commands.Choice(name="Kharma Uses",       value="kharma_uses"),
        app_commands.Choice(name="All Prices",        value="all"),
    ])
    async def finances_command(interaction: discord.Interaction, section: str = ""):
        await interaction.response.defer(ephemeral=False)

        rate = get_rate()

        if not section:
            embed = discord.Embed(
                title="\U0001f4b1 Undercity Economy",
                description=(
                    f"**Current EC/Kharma Exchange Rate**\n"
                    f"`{rate:.2f} EC` = 1 Kharma\n"
                    f"`{rate*10:.1f} EC` = 10 Kharma\n"
                    f"`{rate*100:.0f} EC` = 100 Kharma\n\n"
                    f"-# Use `/finances section:` to view specific price tables."
                ),
                color=discord.Color.gold(),
            )
            embed.add_field(
                name="Quest Rewards",
                value="Local +10K \u00b7 Standard +50K \u00b7 Major +100K \u00b7 Epic +500K",
                inline=False,
            )
            embed.add_field(
                name="Hireables (EC/day)",
                value="Rank 1: 50\u2013100 \u00b7 Rank 2: 100\u2013200 \u00b7 Rank 3+: 200\u2013500",
                inline=False,
            )
            embed.add_field(
                name="Common Services",
                value="Serpent Choir blessing 50\u2013500 \u00b7 Lotus memory job 500\u20135,000 \u00b7 FTA license 100/yr",
                inline=False,
            )
            embed.add_field(
                name="Common Goods",
                value="Hot meal 2\u20135 EC \u00b7 Bed 3\u201330 EC \u00b7 Healing potion 50\u2013150 EC",
                inline=False,
            )
            embed.set_footer(text="Exchange rates subject to market conditions. Glass Sigil Economic Monitoring.")
            await interaction.followup.send(embed=embed)

        elif section == "all":
            text = format_all_prices()
            chunks = []
            current = []
            for line in text.splitlines(keepends=True):
                if sum(len(l) for l in current) + len(line) > 1900:
                    chunks.append("".join(current))
                    current = []
                current.append(line)
            if current:
                chunks.append("".join(current))
            for i, chunk in enumerate(chunks):
                if chunk.strip():
                    if i == 0:
                        await interaction.followup.send(chunk)
                    else:
                        await interaction.channel.send(chunk)
        else:
            table_text = format_price_table(section)
            table_info = PRICE_TABLES.get(section, {})
            embed = discord.Embed(
                title=f"\U0001f4cb {table_info.get('title', section.replace('_', ' ').title())}",
                description=table_text,
                color=discord.Color.gold(),
            )
            embed.set_footer(text=f"Current exchange rate: {rate:.2f} EC = 1 Kharma")
            await interaction.followup.send(embed=embed)

    # ---- /prices ----

    @client.tree.command(
        name="prices",
        description="Look up item/spell/gear prices from the Player's Handbook or campaign docs"
    )
    @app_commands.describe(query="What do you want to look up? e.g. 'longsword', 'healing potion', 'plate armor'")
    async def prices_command(interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=False)

        import httpx
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
        ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

        from src.tower_rag import search_docs
        try:
            hits = search_docs(query, top_k=5)
            context_block = "\n\n".join(hits) if hits else "(No matching entries found in campaign docs.)"
        except Exception as e:
            logger.warning(f"/prices RAG error: {e}")
            context_block = "(RAG unavailable \u2014 answering from general knowledge.)"

        rate = get_rate()
        prompt = f"""You are a rulesmaster for a D&D 5e 2024 campaign set in the Undercity (Tower of Last Chance).
The Undercity uses Essence Coins (EC) as everyday currency.
Current EC/Kharma exchange rate: {rate:.2f} EC = 1 Kharma.

Relevant campaign/rulebook excerpts:
{context_block}

Player question: What is the price / cost / stats of: {query}

RULES:
- Answer concisely. Give the price in EC (primary) and note GP equivalent if relevant.
- If it's a standard PHB item, give the 5e 2024 price in GP and convert to EC (1 GP \u2248 1 EC as a baseline, adjusted for Undercity economy).
- If it's an Undercity-specific service or item, use campaign doc prices.
- Use Discord markdown. 2-5 lines max.
- If uncertain, say so honestly. Do NOT invent stats.
- Output ONLY the answer. No preamble."""

        try:
            async with httpx.AsyncClient(timeout=60.0) as http:
                resp = await http.post(ollama_url, json={
                    "model": ollama_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                })
                resp.raise_for_status()
                data = resp.json()

            answer = ""
            if isinstance(data, dict):
                msg = data.get("message", {})
                if isinstance(msg, dict):
                    answer = msg.get("content", "").strip()

            lines = answer.splitlines()
            skip  = ("sure", "here's", "here is", "certainly", "of course")
            while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
                lines.pop(0)
            answer = "\n".join(lines).strip()

            embed = discord.Embed(
                title=f"\U0001f4d6 Price Lookup: {query[:50]}",
                description=answer or "*No answer found.*",
                color=discord.Color.blurple(),
            )
            embed.set_footer(text=f"Rate: {rate:.2f} EC = 1 Kharma | Source: PHB 2024 + Undercity Sourcebook")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            import traceback
            logger.error(f"/prices error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            await interaction.followup.send(
                f"\u274c Lookup failed: `{type(e).__name__}: {e}`", ephemeral=True
            )
