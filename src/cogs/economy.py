"""Economy commands — /finances, /prices, /bid, /buynow, /mybids."""

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
            from src.resource_cop import wait_for_ollama_turn

            decision = await wait_for_ollama_turn("price_lookup", track="quick", max_wait_seconds=45)
            if not decision.run_now:
                await interaction.followup.send(
                    f"\u23f3 Price lookup is busy right now ({decision.reason}). Try again in a minute.",
                    ephemeral=True,
                )
                return

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

    # ---- /bid ----

    @client.tree.command(
        name="bid",
        description="Place a bid on an active TowerBay listing. Use /towerbay-board to see Lot numbers.",
    )
    @app_commands.describe(
        lot="Lot number (shown on the TowerBay board embed footer, e.g. 42)",
        amount="Your bid in EC (must be ≥5% above current bid)",
        max_autobid="(Optional) Set a max and the system auto-bids for you up to this amount",
    )
    async def bid_command(
        interaction: discord.Interaction,
        lot: str,
        amount: int,
        max_autobid: int = 0,
    ):
        await interaction.response.defer(ephemeral=True)

        from src.tower_economy import place_bid, get_active_listings
        from src.player_listings import place_bid_on_player_listing

        proxy = max_autobid if max_autobid > amount else None
        listing_type = "player" if lot.startswith("pl_") else "ai"

        if listing_type == "ai":
            try:
                listing_id = int(lot)
            except ValueError:
                await interaction.followup.send("❌ Invalid lot number.", ephemeral=True)
                return
            result = place_bid(
                listing_id  = listing_id,
                bidder_id   = interaction.user.id,
                bidder_name = interaction.user.display_name,
                amount      = amount,
                proxy_max   = proxy,
            )
        else:
            result = place_bid_on_player_listing(
                listing_id  = lot,
                bidder_id   = interaction.user.id,
                bidder_name = interaction.user.display_name,
                amount      = amount,
                proxy_max   = proxy,
            )

        # Notify the outbid player
        if result.get("success") and result.get("outbid_user"):
            outbid = result["outbid_user"]
            try:
                outbid_member = await interaction.client.fetch_user(int(outbid["id"]))
                item_name = result.get("item_name", "an item")
                await outbid_member.send(
                    f"🔔 **You've been outbid on TowerBay!**\n"
                    f"*{item_name}* — new high bid: **{result['new_price']:,} EC**\n"
                    f"Use `/bid` to counter."
                )
            except Exception:
                pass

        color = discord.Color.green() if result["success"] else discord.Color.red()
        icon  = "✅" if result["success"] else "❌"
        embed = discord.Embed(
            title=f"{icon} TowerBay — Bid",
            description=result["message"],
            color=color,
        )
        if result["success"] and proxy:
            embed.add_field(
                name="Auto-bid active",
                value=f"System will bid for you up to **{proxy:,} EC**.",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bid_command.autocomplete("lot")
    async def bid_lot_autocomplete(
        interaction: discord.Interaction, current: str
    ):
        from src.tower_economy import get_active_listings
        from src.player_listings import _load_listings

        choices = []
        # AI listings
        for row in get_active_listings()[:15]:
            lid   = str(row.get("id", ""))
            name  = row.get("item_name", "?")[:40]
            bid   = row.get("current_bid", 0)
            label = f"Lot #{lid} — {name} ({bid:,} EC)"
            if not current or current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=lid))

        # Player listings
        for pl in _load_listings():
            if pl.get("status") != "active":
                continue
            lid   = pl.get("id", "")
            name  = pl.get("item_name", "?")[:30]
            bid   = pl.get("current_bid", 0)
            label = f"{lid} — {name} ({bid:,} EC) [player]"
            if not current or current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=str(lid)))

        return choices[:25]

    # ---- /buynow ----

    @client.tree.command(
        name="buynow",
        description="Instantly purchase a TowerBay listing at its Buy Now price.",
    )
    @app_commands.describe(lot="Lot number or listing ID (shown on the board)")
    async def buynow_command(interaction: discord.Interaction, lot: str):
        await interaction.response.defer(ephemeral=True)

        from src.tower_economy import buy_now
        from src.player_listings import buy_now_player_listing

        listing_type = "player" if lot.startswith("pl_") else "ai"

        if listing_type == "ai":
            try:
                listing_id = int(lot)
            except ValueError:
                await interaction.followup.send("❌ Invalid lot number.", ephemeral=True)
                return
            result = buy_now(
                listing_id = listing_id,
                buyer_id   = interaction.user.id,
                buyer_name = interaction.user.display_name,
            )
        else:
            result = buy_now_player_listing(
                listing_id = lot,
                buyer_id   = interaction.user.id,
                buyer_name = interaction.user.display_name,
            )

        # Notify outbid player whose bid was ended by buy-now
        if result.get("success") and result.get("outbid_user"):
            outbid = result["outbid_user"]
            try:
                outbid_member = await interaction.client.fetch_user(int(outbid["id"]))
                item_name = result.get("item_name", "an item")
                await outbid_member.send(
                    f"🔔 **Buy Now on TowerBay** — *{item_name}* was purchased outright before your bid closed.\n"
                    f"Your bid has been voided. Better luck next time."
                )
            except Exception:
                pass

        color = discord.Color.green() if result["success"] else discord.Color.red()
        icon  = "🛒" if result["success"] else "❌"
        embed = discord.Embed(
            title=f"{icon} TowerBay — Buy Now",
            description=result["message"],
            color=color,
        )
        if result.get("success"):
            embed.set_footer(text="All sales final. Collect your item at any registered Exchange kiosk.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @buynow_command.autocomplete("lot")
    async def buynow_lot_autocomplete(interaction: discord.Interaction, current: str):
        from src.tower_economy import get_active_listings
        from src.player_listings import _load_listings

        choices = []
        for row in get_active_listings():
            if not row.get("buy_now_price"):
                continue
            lid   = str(row.get("id", ""))
            name  = row.get("item_name", "?")[:35]
            price = row.get("buy_now_price", 0)
            label = f"Lot #{lid} — {name} · Buy Now {price:,} EC"
            if not current or current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=lid))
        for pl in _load_listings():
            if pl.get("status") != "active" or not pl.get("buy_now_price"):
                continue
            lid   = pl.get("id", "")
            name  = pl.get("item_name", "?")[:30]
            price = pl.get("buy_now_price", 0)
            label = f"{lid} — {name} · Buy Now {price:,} EC [player]"
            if not current or current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=str(lid)))
        return choices[:25]

    # ---- /mybids ----

    @client.tree.command(
        name="mybids",
        description="See your active bids on TowerBay — what you're winning, what you've lost.",
    )
    async def mybids_command(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        from src.tower_economy import get_active_listings, get_player_bids

        active = {str(r["id"]): r for r in get_active_listings()}
        bids   = get_player_bids(interaction.user.id)

        if not bids:
            await interaction.followup.send(
                "You haven't placed any bids yet. Use `/bid` to get started.",
                ephemeral=True,
            )
            return

        seen = set()
        winning, losing, closed = [], [], []

        for b in bids:
            lid = str(b.get("listing_id", ""))
            if lid in seen:
                continue
            seen.add(lid)

            item_name     = b.get("item_name") or "Unknown"
            status        = b.get("listing_status") or "unknown"
            current_win   = b.get("current_winner_id")
            my_bid        = b.get("amount", 0)
            listing_row   = active.get(lid)
            current_price = listing_row.get("current_bid", my_bid) if listing_row else my_bid

            if status in ("sold", "unsold", "expired"):
                won = current_win and int(current_win) == interaction.user.id
                closed.append((item_name, my_bid, won))
            elif current_win and int(current_win) == interaction.user.id:
                winning.append((item_name, current_price, lid))
            else:
                losing.append((item_name, current_price, my_bid, lid))

        embed = discord.Embed(
            title="🏪 My TowerBay Bids",
            color=discord.Color.gold(),
        )

        if winning:
            lines = []
            for name, price, lid in winning:
                lines.append(f"🏆 **{name}** — leading at **{price:,} EC** (Lot #{lid})")
            embed.add_field(name="✅ Currently Winning", value="\n".join(lines), inline=False)

        if losing:
            lines = []
            for name, price, my_bid, lid in losing:
                lines.append(
                    f"❌ **{name}** — outbid · current **{price:,} EC** · your last bid {my_bid:,} EC "
                    f"· `/bid {lid} <amount>` to counter"
                )
            embed.add_field(name="⚠️ Outbid", value="\n".join(lines), inline=False)

        if closed:
            lines = []
            for name, my_bid, won in closed:
                icon = "✅ Won" if won else "❌ Lost"
                lines.append(f"{icon} — **{name}** (your bid: {my_bid:,} EC)")
            embed.add_field(name="📦 Recently Closed", value="\n".join(lines[:8]), inline=False)

        embed.set_footer(text="Use /bid to place or raise a bid. Use /buynow for instant purchase.")
        await interaction.followup.send(embed=embed, ephemeral=True)
