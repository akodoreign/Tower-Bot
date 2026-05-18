"""
purge_channel.py — Delete all messages from a Discord channel.

Bulk-deletes messages < 14 days old (Discord limit), then individually
deletes older ones. Runs as a one-shot bot login.

Usage:
    python scripts/purge_channel.py 1459652462045827113
"""
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import discord

CHANNEL_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1459652462045827113
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not TOKEN:
    print("ERROR: DISCORD_BOT_TOKEN not set in .env")
    sys.exit(1)


async def purge():
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"Logged in as {client.user}")
        channel = client.get_channel(CHANNEL_ID)
        if channel is None:
            print(f"ERROR: Channel {CHANNEL_ID} not found (bot may not be in that server)")
            await client.close()
            return

        print(f"Purging #{channel.name} ({CHANNEL_ID})...")

        cutoff = datetime.now(timezone.utc) - timedelta(days=13, hours=23)
        bulk = []
        old = []
        total = 0

        async for msg in channel.history(limit=None):
            total += 1
            if msg.created_at > cutoff:
                bulk.append(msg)
            else:
                old.append(msg)

        print(f"Found {total} messages: {len(bulk)} bulk-deletable, {len(old)} old (individual delete)")

        # Bulk delete in chunks of 100
        deleted_bulk = 0
        for i in range(0, len(bulk), 100):
            chunk = bulk[i:i+100]
            try:
                await channel.delete_messages(chunk)
                deleted_bulk += len(chunk)
                print(f"  Bulk deleted {deleted_bulk}/{len(bulk)}...")
                await asyncio.sleep(1)
            except discord.HTTPException as e:
                print(f"  Bulk delete error: {e}")

        # Delete old messages one by one
        deleted_old = 0
        for msg in old:
            try:
                await msg.delete()
                deleted_old += 1
                if deleted_old % 5 == 0:
                    print(f"  Deleted {deleted_old}/{len(old)} old messages...")
                await asyncio.sleep(0.75)  # rate limit cushion
            except discord.HTTPException as e:
                print(f"  Delete error on msg {msg.id}: {e}")

        print(f"\nDone. Deleted {deleted_bulk + deleted_old}/{total} messages.")
        await client.close()

    await client.start(TOKEN)


asyncio.run(purge())
