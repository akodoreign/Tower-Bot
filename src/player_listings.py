"""
player_listings.py — Player-submitted TowerBay auction listings.

Players use /towerbay to submit an item. The bot:
  1. Asks for item name & description, min bid via modal.
  2. Sends the DM (DM_USER_ID) a private approval embed with ✅/❌ buttons.
  3. On approval: 7-day auction goes live with phantom bidding. Player reminded to remove from sheet.
  4. On "Too Much": item still lists for 7 days but is frozen — no phantom bids, closes as unsold.

Hot Factor (days 4–7):
  Each hourly tick, phantom NPC bidders start competing with escalating bids
  and in-world handles. Two bidders can get into a brief war on the same tick.
  Frozen listings skip this entirely.

Listings persist in MySQL player_listings table.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import discord
from discord import app_commands

from src.log import logger
from src.db_api import raw_query, raw_execute, db

AUCTION_DAYS         = 7
HOT_PHASE_START_DAY  = 3   # hot bidding kicks in after 3 full days (days 4-7)

# ---------------------------------------------------------------------------
# NPC phantom bidder handles — shown to players so it feels alive
# ---------------------------------------------------------------------------

_PHANTOM_BIDDERS = [
    "Anonymous (Iron Fang-adjacent)",
    "Verified Buyer #7714",
    "Corvin_shadow_acct",
    "Undercity_Procurement_Office",
    "Bidder: Crimson Alley",
    "NightPits_Acquisitions",
    "The Widow (proxy bid)",
    "Dova (personal account)",
    "Anonymous — high rep",
    "Grand_Forum_Fence",
    "Outer_Wall_Supply",
    "Wandering_Broker_X",
    "Guild_Spires_Equipment",
    "Echo_Alley_Curios",
    "Sanctum_Quarter_Rep",
    "Ashen_Scrolls_Acquisition",
    "Tessaly_Alt_Acct",
    "FTA_Compliance_Surplus",
    "Anonymous (Serpent-adjacent)",
    "Patchwork_Saints_Proxy",
]


# ---------------------------------------------------------------------------
# Persistence — MySQL via db_api
# ---------------------------------------------------------------------------

def _ensure_listing_json_column():
    """Ensure listing_json column exists (added for complex data storage)."""
    try:
        # Check if column exists
        result = raw_query(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'player_listings' AND COLUMN_NAME = 'listing_json'"
        )
        if not result:
            raw_execute("ALTER TABLE player_listings ADD COLUMN listing_json JSON")
            logger.info("💾 Added listing_json column to player_listings table")
    except Exception as e:
        logger.debug(f"listing_json column check: {e}")

# Try to ensure column exists on module load
try:
    _ensure_listing_json_column()
except Exception:
    pass


def _load_listings() -> List[Dict]:
    """Load all listings from database."""
    try:
        rows = raw_query("SELECT * FROM player_listings ORDER BY created_at DESC")
        listings = []
        for row in rows:
            # Try to get full listing from listing_json, fall back to row data
            listing_data = row.get("listing_json")
            if listing_data:
                if isinstance(listing_data, str):
                    listing = json.loads(listing_data)
                else:
                    listing = listing_data
            else:
                # Construct from row columns
                listing = {
                    "id": f"pl_{row.get('id')}",
                    "player_id": int(row.get("player_id", 0)) if row.get("player_id") else 0,
                    "player_name": row.get("player_name", ""),
                    "item_name": row.get("item_name", ""),
                    "min_bid": row.get("asking_price", 0),
                    "current_bid": row.get("asking_price", 0),
                    "status": row.get("status", "active"),
                    "listed_at": row.get("created_at").isoformat() if row.get("created_at") else datetime.now().isoformat(),
                    "expires_at": (row.get("created_at") + timedelta(days=AUCTION_DAYS)).isoformat() if row.get("created_at") else (datetime.now() + timedelta(days=AUCTION_DAYS)).isoformat(),
                }
            listings.append(listing)
        return listings
    except Exception as e:
        logger.error(f"PlayerListings load error: {e}")
        return []


def _save_listing(listing: Dict) -> None:
    """Save a single listing to database (insert or update)."""
    try:
        listing_json = json.dumps(listing, ensure_ascii=False, default=str)
        listing_id = listing.get("id", "")
        
        # Extract numeric ID if it exists
        db_id = None
        if listing_id.startswith("pl_"):
            try:
                db_id = int(listing_id[3:])
            except ValueError:
                pass
        
        # Check if exists
        if db_id:
            existing = raw_query("SELECT id FROM player_listings WHERE id = %s", (db_id,))
        else:
            existing = raw_query(
                "SELECT id FROM player_listings WHERE player_id = %s AND item_name = %s AND status = 'active'",
                (str(listing.get("player_id", "")), listing.get("item_name", ""))
            )
        
        if existing:
            # Update
            raw_execute(
                "UPDATE player_listings SET status = %s, asking_price = %s, listing_json = %s WHERE id = %s",
                (listing.get("status"), listing.get("current_bid"), listing_json, existing[0]["id"])
            )
        else:
            # Insert
            new_id = db.insert("player_listings", {
                "player_id": str(listing.get("player_id", "")),
                "player_name": listing.get("player_name", ""),
                "item_name": listing.get("item_name", ""),
                "asking_price": listing.get("min_bid", 0),
                "status": listing.get("status", "active"),
                "listing_json": listing_json,
            })
            listing["id"] = f"pl_{new_id}"
    except Exception as e:
        logger.error(f"PlayerListings save error: {e}")


def _save_listings(listings: List[Dict]) -> None:
    """Save all listings (for batch updates)."""
    for listing in listings:
        _save_listing(listing)


# ---------------------------------------------------------------------------
# Tick — called every bulletin cycle (from tower_economy.tick_towerbay)
# ---------------------------------------------------------------------------

def tick_player_listings() -> List[Dict]:
    """
    Advance all active player listings by one tick.
    - Frozen listings: no phantom bids at any point, close as unsold on expiry.
    - Hot phase (days 4-7): phantom bidders compete with escalating bids on normal listings.
    - Expired listings: marked sold (normal) or unsold (frozen).
    Returns list of listings that JUST closed this tick (sold or unsold).
    """
    listings = _load_listings()
    now      = datetime.now()
    sold_now = []

    for item in listings:
        if item.get("status") != "active":
            continue

        try:
            expires = datetime.fromisoformat(item["expires_at"])
        except Exception:
            continue

        frozen = item.get("frozen", False)

        # --- EXPIRED ---
        if now >= expires:
            if frozen:
                # Frozen = overpriced, no interest — closes unsold
                item["status"]      = "unsold"
                item["sold_at"]     = now.isoformat()
                item["final_price"] = None
                sold_now.append(item)
                logger.info(
                    f"🏪 Player listing unsold (frozen): {item['item_name']} "
                    f"(player: {item['player_name']})"
                )
            else:
                item["status"]  = "sold"
                item["sold_at"] = now.isoformat()
                # Final price: current bid + small bump (3-10%)
                final = int(item["current_bid"] * random.uniform(1.03, 1.10))
                item["final_price"] = final
                item["current_bid"] = final
                sold_now.append(item)
                logger.info(
                    f"🏪 Player listing sold: {item['item_name']} "
                    f"→ {final:,} EC (player: {item['player_name']})"
                )
            continue

        # --- SKIP PHANTOM BIDDING FOR FROZEN LISTINGS ---
        if frozen:
            continue

        # --- HOT PHASE CHECK ---
        days_elapsed = (now - datetime.fromisoformat(item["listed_at"])).days
        in_hot_phase = days_elapsed >= HOT_PHASE_START_DAY

        # Base bid probability
        bid_chance = 0.40 if in_hot_phase else 0.15

        if random.random() > bid_chance:
            continue

        # Pick a phantom bidder (never repeat the last one)
        last_bidder = item.get("last_bidder", "")
        pool = [b for b in _PHANTOM_BIDDERS if b != last_bidder]
        bidder = random.choice(pool)

        if in_hot_phase:
            # Hot phase — multiple escalating bids possible on one tick
            bid_rounds = random.choices([1, 2, 3], weights=[0.50, 0.35, 0.15])[0]
            for _ in range(bid_rounds):
                increment = random.uniform(0.05, 0.18)
                item["current_bid"] = int(item["current_bid"] * (1 + increment))
                item["bid_count"]  += 1
                bidder2 = random.choice([b for b in _PHANTOM_BIDDERS if b != bidder])
                item.setdefault("bid_log", []).append({
                    "bidder":    bidder if _ == 0 else bidder2,
                    "amount":    item["current_bid"],
                    "at":        now.isoformat(),
                    "hot":       True,
                })
                bidder = bidder2
        else:
            # Normal phase — single quiet bid
            increment = random.uniform(0.03, 0.09)
            item["current_bid"] = int(item["current_bid"] * (1 + increment))
            item["bid_count"]  += 1
            item.setdefault("bid_log", []).append({
                "bidder": bidder,
                "amount": item["current_bid"],
                "at":     now.isoformat(),
                "hot":    False,
            })

        item["last_bidder"] = bidder

    _save_listings(listings)
    return sold_now


# ---------------------------------------------------------------------------
# Create a listing (called after DM decision)
# ---------------------------------------------------------------------------

def create_listing(
    player_id: int,
    player_name: str,
    item_name: str,
    description: str,
    min_bid: int,
    frozen: bool = False,
) -> Dict:
    """Create and save a new active listing. Returns the listing dict.
    frozen=True: lists publicly for 7 days but gets no phantom bids and closes as unsold."""
    now = datetime.now()

    listing = {
        "id":           f"pl_{int(now.timestamp())}",
        "player_id":    player_id,
        "player_name":  player_name,
        "item_name":    item_name,
        "description":  description,
        "min_bid":      min_bid,
        "current_bid":  min_bid,
        "bid_count":    0,
        "bid_log":      [],
        "last_bidder":  "",
        "listed_at":    now.isoformat(),
        "expires_at":   (now + timedelta(days=AUCTION_DAYS)).isoformat(),
        "status":       "active",
        "frozen":       frozen,
        "final_price":  None,
        "sold_at":      None,
    }

    _save_listing(listing)
    logger.info(
        f"🏪 New player listing {'(frozen) ' if frozen else ''}activated: {item_name} "
        f"by {player_name} (min {min_bid:,} EC)"
    )
    return listing


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _days_left(item: Dict) -> str:
    try:
        expires = datetime.fromisoformat(item["expires_at"])
        delta   = expires - datetime.now()
        days    = delta.days
        hours   = delta.seconds // 3600
        if days > 0:
            return f"{days}d {hours}h left"
        elif hours > 0:
            return f"{hours}h left"
        else:
            return "ending soon"
    except Exception:
        return "?"


def _hot_indicator(item: Dict) -> str:
    if item.get("frozen"):
        return "🔒"
    days_elapsed = (datetime.now() - datetime.fromisoformat(item["listed_at"])).days
    if days_elapsed >= HOT_PHASE_START_DAY:
        return "🔥"
    elif item["bid_count"] >= 3:
        return "📈"
    else:
        return "🆕"


def format_player_listings_embed() -> Optional[discord.Embed]:
    """Returns a Discord embed showing all active player listings, or None if empty."""
    listings = _load_listings()
    active   = [l for l in listings if l.get("status") == "active"]

    if not active:
        return None

    active.sort(key=lambda x: x["current_bid"], reverse=True)

    embed = discord.Embed(
        title="🏪 TowerBay — Player Listings",
        color=discord.Color.gold(),
    )

    for item in active:
        hot      = _hot_indicator(item)
        time_str = _days_left(item)
        frozen   = item.get("frozen", False)
        bids_str = f"{item['bid_count']} bid{'s' if item['bid_count'] != 1 else ''}"
        last_b   = item.get("last_bidder") or "no bids yet"

        bidder_note = f"\n> Last bid by: *{last_b}*" if item["bid_count"] > 0 else ""
        frozen_note = "\n> *No bids received — asking price may be too high.*" if frozen else ""

        desc_preview = item["description"][:100] + ("…" if len(item["description"]) > 100 else "")

        embed.add_field(
            name=f"{hot} {item['item_name']}  ·  ⏳ {time_str}",
            value=(
                f"_{desc_preview}_\n"
                f"**Current bid:** {item['current_bid']:,} EC  ·  {bids_str}"
                f"{bidder_note}{frozen_note}\n"
                f"*Listed by {item['player_name']}  ·  Min bid was {item['min_bid']:,} EC*"
            ),
            inline=False,
        )

    embed.set_footer(
        text="Bidding closes automatically. Results posted when listing expires. "
             "All sales final — item must be removed from your sheet."
    )
    return embed


def format_sold_notification(item: Dict) -> discord.Embed:
    """Returns an embed announcing a player listing has closed (sold or unsold)."""
    if item.get("status") == "unsold":
        embed = discord.Embed(
            title=f"🔔 Auction Closed — {item['item_name']}",
            description=(
                f"Your listing ran for 7 days and received **no bids**.\n\n"
                f"**Asking price:** {item['min_bid']:,} EC\n"
                f"**Listed by:** {item['player_name']}\n\n"
                f"*The item was not sold. You may keep it on your sheet or relist at a lower price.*"
            ),
            color=discord.Color.greyple(),
        )
        embed.set_footer(text="TowerBay — Item returned unsold.")
    else:
        embed = discord.Embed(
            title=f"🔔 Auction Closed — {item['item_name']}",
            description=(
                f"Your listing has ended.\n\n"
                f"**Final sale price:** {item.get('final_price', item['current_bid']):,} EC\n"
                f"**Total bids:** {item['bid_count']}\n"
                f"**Listed by:** {item['player_name']}\n\n"
                f"The EC has been credited to your account at the next Exchange kiosk visit.\n"
                f"*If you haven't already, remember to remove **{item['item_name']}** from your character sheet.*"
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="TowerBay — All sales final.")
    return embed


# ---------------------------------------------------------------------------
# DM Approval View
# ---------------------------------------------------------------------------

class _ListingApprovalView(discord.ui.View):
    """
    Sent to the DM when a player submits a listing.
    ✅ List it   — full auction with phantom bidding.
    ❌ Too Much  — lists for 7 days but frozen (no bids, closes unsold).
    """

    def __init__(
        self,
        player: discord.User,
        item_name: str,
        description: str,
        min_bid: int,
        player_channel: discord.TextChannel,
    ):
        super().__init__(timeout=48 * 3600)
        self.player         = player
        self.item_name      = item_name
        self.description    = description
        self.min_bid        = min_bid
        self.player_channel = player_channel
        self.decided        = False

    @discord.ui.button(label="✅ List it", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.decided:
            await interaction.response.send_message("Already decided.", ephemeral=True)
            return
        self.decided = True
        self.disable_all_items()

        create_listing(
            player_id   = self.player.id,
            player_name = self.player.display_name,
            item_name   = self.item_name,
            description = self.description,
            min_bid     = self.min_bid,
            frozen      = False,
        )

        await interaction.response.edit_message(
            content=f"✅ **Approved** — *{self.item_name}* is now live on TowerBay.",
            view=self,
        )

        try:
            await self.player_channel.send(
                f"{self.player.mention} Your listing **{self.item_name}** "
                f"is now live on TowerBay for **{self.min_bid:,} EC** minimum bid! "
                f"The auction runs for 7 days. ⚔️ *Don't forget to remove it from your character sheet.*"
            )
        except Exception as e:
            logger.warning(f"Could not notify player of approval: {e}")

        self.stop()

    @discord.ui.button(label="❌ Too Much", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.decided:
            await interaction.response.send_message("Already decided.", ephemeral=True)
            return
        self.decided = True
        self.disable_all_items()

        # List it anyway — but frozen so no phantom bids, closes unsold after 7 days
        create_listing(
            player_id   = self.player.id,
            player_name = self.player.display_name,
            item_name   = self.item_name,
            description = self.description,
            min_bid     = self.min_bid,
            frozen      = True,
        )

        await interaction.response.edit_message(
            content=f"❌ **Too Much** — *{self.item_name}* listed for 7 days but frozen (no bids).",
            view=self,
        )

        try:
            await self.player_channel.send(
                f"{self.player.mention} Your listing **{self.item_name}** "
                f"has been posted to TowerBay for **{self.min_bid:,} EC**, "
                f"but the market isn't biting at that price. "
                f"It'll run for 7 days — if no one bids, it comes back to you unsold."
            )
        except Exception as e:
            logger.warning(f"Could not notify player of frozen listing: {e}")

        self.stop()

    def disable_all_items(self):
        for child in self.children:
            child.disabled = True


# ---------------------------------------------------------------------------
# Modal — collects item details from the player
# ---------------------------------------------------------------------------

class _TowerBayModal(discord.ui.Modal, title="TowerBay — List an Item"):
    item_details = discord.ui.TextInput(
        label="Item name & description",
        placeholder="e.g. +1 Dagger — good condition, arcane focus, no longer needed",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )
    min_bid_str = discord.ui.TextInput(
        label="Minimum bid (EC)",
        placeholder="e.g. 5000",
        max_length=12,
        required=True,
    )

    def __init__(self, dm_user_id: int):
        super().__init__()
        self.dm_user_id = dm_user_id

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.min_bid_str.value.replace(",", "").replace(" ", "")
        try:
            min_bid = int(raw)
            if min_bid < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ That doesn't look like a valid EC amount. Please try again with a number.",
                ephemeral=True,
            )
            return

        details = self.item_details.value.strip()
        name = details.splitlines()[0][:80].strip()
        desc = details

        await interaction.response.send_message(
            f"📬 Submitted for DM review at **{min_bid:,} EC** minimum.\n"
            f"⚠️ **Remember to remove this item from your D&D Beyond character sheet** "
            f"before next session once it's approved.\n"
            f"You'll be notified here when the DM makes a decision.",
            ephemeral=True,
        )

        approval_embed = discord.Embed(
            title=f"🏪 TowerBay Listing — {interaction.user.display_name}",
            color=discord.Color.blurple(),
        )
        approval_embed.add_field(name="Player", value=interaction.user.display_name, inline=True)
        approval_embed.add_field(name="Min bid", value=f"{min_bid:,} EC", inline=True)
        approval_embed.add_field(name="Item details", value=desc, inline=False)
        approval_embed.set_footer(text="✅ List it = full auction  |  ❌ Too Much = lists frozen, closes unsold")

        view = _ListingApprovalView(
            player=interaction.user,
            item_name=name,
            description=desc,
            min_bid=min_bid,
            player_channel=interaction.channel,
        )

        try:
            dm_user = await interaction.client.fetch_user(self.dm_user_id)
            await dm_user.send(embed=approval_embed, view=view)
        except Exception as e:
            logger.error(f"Could not DM the DM for TowerBay approval: {e}")

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"TowerBay modal error: {error}")
        await interaction.response.send_message(
            "Something went wrong with your submission. Try again in a moment.",
            ephemeral=True,
        )
