"""
Retroactively fix the last N mission board Discord posts that have broken
emoji/chars due to the Codex encoding bug.

Fetches each mission from DB, rebuilds the embed using the now-fixed
_build_mission_embed, and edits the Discord message in-place.

Usage:
  python scripts/_retrofix_mission_embeds.py
  python scripts/_retrofix_mission_embeds.py --limit 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import discord
from src.db_api import raw_query
from src.mission_board import _build_mission_embed


async def fix_posts(limit: int) -> None:
    from src.faction_reputation import get_faction_color, get_faction_tier_label

    rows = raw_query(
        "SELECT id, title, mission_json, message_id, posted_at, expires_at, status, tier "
        "FROM missions "
        "WHERE message_id IS NOT NULL AND message_id != 0 "
        "  AND status NOT IN ('expired', 'resolved', 'failed', 'complete') "
        "ORDER BY posted_at DESC LIMIT %s",
        (limit,),
    ) or []

    if not rows:
        print("No active missions with message IDs found.")
        return

    token      = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = int(os.getenv("MISSION_BOARD_CHANNEL_ID", "0"))
    if not token or not channel_id:
        print("ERROR: DISCORD_BOT_TOKEN or MISSION_BOARD_CHANNEL_ID not set")
        return

    intents = discord.Intents.default()
    client  = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"Logged in as {client.user}")
        channel = client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(channel_id)
            except Exception as e:
                print(f"ERROR: Cannot fetch channel {channel_id}: {e}")
                await client.close()
                return

        for row in rows:
            mission_id = row["id"]
            message_id = row["message_id"]
            title      = row["title"]

            # Deserialise mission JSON
            raw_json = row.get("mission_json") or {}
            if isinstance(raw_json, str):
                try:
                    mission = json.loads(raw_json)
                except Exception:
                    mission = {}
            else:
                mission = dict(raw_json)

            # Ensure top-level DB fields are present in the mission dict
            mission.setdefault("title",   title)
            mission.setdefault("tier",    row.get("tier") or "standard")
            mission.setdefault("faction", mission.get("faction", ""))

            # Color and tier label from faction reputation
            faction     = mission.get("faction", "")
            embed_color = get_faction_color(faction) if faction else 0xE6C300
            tier_label  = get_faction_tier_label(faction) if faction else "Neutral"

            # Days left
            expires_at = row.get("expires_at")
            try:
                days_left = max(1, (expires_at - datetime.utcnow()).days) if expires_at else 3
            except Exception:
                days_left = 3

            try:
                embed = _build_mission_embed(
                    mission=mission,
                    embed_color=embed_color,
                    tier_label=tier_label,
                    days_left=days_left,
                )
            except Exception as e:
                print(f"  SKIP #{mission_id} {title[:40]!r}: embed build failed: {e}")
                continue

            try:
                from src.mission_board import EMOJI_CLAIM
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=embed)

                # Re-add the claim reaction — the original add_reaction call
                # silently failed because EMOJI_CLAIM was broken mojibake.
                # Clear any stale broken reactions first, then add the correct one.
                try:
                    await msg.clear_reactions()
                except Exception:
                    pass
                try:
                    await msg.add_reaction(EMOJI_CLAIM)
                except Exception as re_err:
                    print(f"    warn: add_reaction failed: {re_err}")

                print(f"  FIXED #{mission_id} msg={message_id} — {title[:50]!r}")
            except discord.NotFound:
                print(f"  SKIP #{mission_id} msg={message_id} — message deleted")
            except discord.Forbidden:
                print(f"  SKIP #{mission_id} msg={message_id} — no edit permission")
            except Exception as e:
                print(f"  FAIL #{mission_id} msg={message_id}: {e}")

        print("Done.")
        await client.close()

    await client.start(token)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=4, help="Number of recent posts to fix")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(fix_posts(args.limit))
