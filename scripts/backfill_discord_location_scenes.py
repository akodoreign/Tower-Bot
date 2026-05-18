"""
Backfill location image refs from historical Discord "The Undercity" scene embeds.

Usage:
    python scripts/backfill_discord_location_scenes.py --limit 3000 --dry-run
    python scripts/backfill_discord_location_scenes.py --limit 3000
    python scripts/backfill_discord_location_scenes.py --channel 123456789 --limit 3000

Reads DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID from .env.
Captions like "**The Hollow Ledger** — Markets Infinite | Dawn..." are saved
as exact location refs under campaign_docs/image_refs/locations/the_hollow_ledger/.
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

from src.image_ref import save_location_ref


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _strip_md(text: str) -> str:
    return re.sub(r"[*_`]", "", text or "").strip()


def _parse_scene(description: str) -> tuple[str, str, str]:
    text = _strip_md(description)
    # Expected: The Hollow Ledger — Markets Infinite | Dawn, clear dome sky | wealth...
    match = re.match(r"(.+?)\s+(?:[—–-]|\?)\s+([^|]+)(?:\|(.+))?$", text)
    if not match:
        return "", "", text
    place = match.group(1).strip()
    district = match.group(2).strip()
    detail = (match.group(3) or "").strip()
    return place, district, detail


async def _image_bytes(msg: discord.Message, embed: discord.Embed | None = None) -> bytes | None:
    for att in msg.attachments:
        if (att.filename or "").lower().endswith(IMAGE_EXTS):
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
        matched = saved = skipped = failed = 0
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            matches = []
            print(f"Scanning #{getattr(channel, 'name', channel_id)} ({channel_id}) limit={limit}")
            async for msg in channel.history(limit=limit):
                for embed in msg.embeds:
                    title = _strip_md(embed.title or "")
                    if "The Undercity" not in title:
                        continue
                    place, district, detail = _parse_scene(embed.description or "")
                    if not place:
                        skipped += 1
                        continue
                    matches.append((msg, embed, place, district, detail))

            for msg, embed, place, district, detail in reversed(matches):
                img = await _image_bytes(msg, embed)
                if not img:
                    skipped += 1
                    continue
                matched += 1
                if dry_run:
                    print(f"DRY {place} :: {district or '?'} {len(img):,} bytes")
                else:
                    try:
                        path = save_location_ref(
                            place,
                            img,
                            metadata={
                                "source": "discord_location_backfill",
                                "message_id": str(msg.id),
                                "channel_id": str(channel_id),
                                "district": district,
                                "caption": embed.description or "",
                                "detail": detail,
                                "created_at": msg.created_at.isoformat(),
                            },
                        )
                        print(f"SAVED {place} :: {district or '?'} -> {path}")
                        saved += 1
                    except Exception as e:
                        failed += 1
                        print(f"FAILED {place} :: {district or '?'}: {e}")
        finally:
            print(f"Done. matched={matched} saved={saved} skipped={skipped} failed={failed} dry_run={dry_run}")
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
