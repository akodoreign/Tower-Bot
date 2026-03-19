"""
bulletin_embeds.py — Wraps text bulletins in themed Discord embeds.

Each bulletin type gets a color and title. The existing markdown text
goes into the embed description. This keeps all the formatting functions
unchanged while giving Discord a polished, color-coded look.
"""

from __future__ import annotations
import discord


# ---------------------------------------------------------------------------
# Bulletin type themes
# ---------------------------------------------------------------------------

THEMES = {
    "news": {
        "title": "📰 Undercity Dispatch",
        "color": 0x3366AA,   # blue
    },
    "rift": {
        "title": "🌀 Rift Alert",
        "color": 0xAA33CC,   # purple
    },
    "tia": {
        "title": "📊 Tower Industrial Average",
        "color": 0x33AA55,   # green
    },
    "tia_flash": {
        "title": "📊 TIA Market Flash",
        "color": 0xCC6633,   # orange
    },
    "weather": {
        "title": "🌫️ Dome Weather Report",
        "color": 0x6699BB,   # sky blue
    },
    "arena": {
        "title": "🏟️ Arena of Ascendance",
        "color": 0xCC3333,   # red
    },
    "calendar": {
        "title": "📅 Faction Calendar",
        "color": 0x9966CC,   # lavender
    },
    "missing": {
        "title": "🔍 Missing Persons",
        "color": 0x996633,   # brown
    },
    "exchange": {
        "title": "💱 EC / Kharma Exchange",
        "color": 0xCCAA33,   # gold
    },
    "bounty": {
        "title": "🎯 Bounty Board",
        "color": 0xCC4444,   # dark red
    },
    "reminder": {
        "title": "🗼 Tower Oracle",
        "color": 0x555555,   # dark grey
    },
}


def wrap_bulletin(text: str, bulletin_type: str = "news") -> discord.Embed:
    """Wrap a text bulletin in a themed embed.
    
    Args:
        text: The bulletin text (markdown formatted)
        bulletin_type: Key from THEMES dict
    
    Returns:
        discord.Embed ready to send
    """
    theme = THEMES.get(bulletin_type, THEMES["news"])

    # Discord embed description limit is 4096 chars
    if len(text) > 4096:
        text = text[:4090] + "\n…"

    embed = discord.Embed(
        description=text,
        color=theme["color"],
    )
    # Set the title as the author field — looks cleaner than the big title
    embed.set_author(name=theme["title"])

    return embed


def wrap_bulletin_with_title(text: str, title: str, color: int = 0x3366AA) -> discord.Embed:
    """Wrap a bulletin with a custom title and color (for one-off uses)."""
    if len(text) > 4096:
        text = text[:4090] + "\n…"
    embed = discord.Embed(description=text, color=color)
    embed.set_author(name=title)
    return embed
