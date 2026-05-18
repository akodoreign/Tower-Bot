"""
Backfill NPC portrait refs from historical Discord roster embeds.

Usage:
    python scripts/backfill_discord_npc_portraits.py --limit 1000
    python scripts/backfill_discord_npc_portraits.py --channel 123456789 --limit 2000

Reads DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID from .env. Normal roster embeds
are saved as npc_portrait; "Alt Universe" embeds are saved as npc_portrait_alt.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import discord

from src.image_ref import save_npc_alt_ref, save_npc_ref
from src.db_api import raw_query


def _clean_title(title: str) -> tuple[str, bool]:
    text = re.sub(r"^[^\w'\"-]+", "", title or "").strip()
    is_alt = "alt universe" in text.lower()
    text = re.sub(r"\s+(?:[\u2014\u2013-]|\?)\s+Alt Universe\s*$", "", text, flags=re.IGNORECASE).strip()
    return text, is_alt


def _canonical_npc_names() -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        rows = raw_query("SELECT name FROM npcs WHERE COALESCE(status, 'alive') <> 'dead'") or []
        for row in rows:
            name = (row.get("name") or "").strip()
            if name:
                names[name.lower()] = name
    except Exception:
        pass
    try:
        rows = raw_query("SELECT name FROM player_characters") or []
        for row in rows:
            name = (row.get("name") or "").strip()
            if name:
                names[name.lower()] = name
    except Exception:
        pass
    return names


async def _image_bytes(msg: discord.Message, embed: discord.Embed | None = None) -> bytes | None:
    for att in msg.attachments:
        if (att.filename or "").lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            return await att.read()
    if embed and embed.image and embed.image.url:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(embed.image.url) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception:
            return None
    return None


async def run(channel_id: int, limit: int, dry_run: bool) -> None:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is not set in .env")

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        saved = skipped = seen = name_skipped = failed = 0
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            canonical_npcs = _canonical_npc_names()
            matches = []
            print(f"Scanning #{getattr(channel, 'name', channel_id)} ({channel_id}) limit={limit}")
            async for msg in channel.history(limit=limit):
                for embed in msg.embeds:
                    title = embed.title or ""
                    footer = embed.footer.text if embed.footer else ""
                    if "Undercity Roster" not in footer and "What If" not in footer and "Alt Universe" not in title:
                        continue
                    name, is_alt = _clean_title(title)
                    canonical_name = canonical_npcs.get(name.lower())
                    if not canonical_name:
                        name_skipped += 1
                        skipped += 1
                        continue
                    matches.append((msg, embed, canonical_name, is_alt))

            for msg, embed, name, is_alt in reversed(matches):
                img = await _image_bytes(msg, embed)
                if not img:
                    skipped += 1
                    continue
                seen += 1
                if dry_run:
                    print(f"DRY {name} {'ALT' if is_alt else 'MAIN'} {len(img):,} bytes")
                else:
                    saver = save_npc_alt_ref if is_alt else save_npc_ref
                    try:
                        path = saver(
                            name,
                            img,
                            metadata={
                                "source": "discord_backfill",
                                "message_id": str(msg.id),
                                "channel_id": str(channel_id),
                                "alt_universe": is_alt,
                                "created_at": msg.created_at.isoformat(),
                            },
                        )
                        print(f"SAVED {name} {'ALT' if is_alt else 'MAIN'} -> {path}")
                        saved += 1
                    except Exception as e:
                        failed += 1
                        print(f"FAILED {name} {'ALT' if is_alt else 'MAIN'}: {e}")
        finally:
            print(
                f"Done. matched={seen} saved={saved if not dry_run else 0} "
                f"skipped={skipped} name_mismatch={name_skipped} failed={failed} dry_run={dry_run}"
            )
            await client.close()

    async with client:
        await client.start(token)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", type=int, default=int(os.getenv("DISCORD_CHANNEL_ID") or 0))
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.channel:
        raise SystemExit("Pass --channel or set DISCORD_CHANNEL_ID in .env")
    asyncio.run(run(args.channel, args.limit, args.dry_run))


if __name__ == "__main__":
    main()
