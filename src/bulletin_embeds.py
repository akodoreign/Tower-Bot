"""
bulletin_embeds.py - Wraps text bulletins in themed Discord embeds.

Each bulletin type gets a color and title. The existing markdown text goes into
the embed description. Emoji are intentional here because these embeds face
Discord directly.
"""

from __future__ import annotations

import discord

from src.text_mojibake import repair_mojibake


# ---------------------------------------------------------------------------
# Bulletin type themes
# ---------------------------------------------------------------------------

THEMES = {
    "news": {
        "title": "📰 Undercity Dispatch",
        "color": 0x3366AA,
    },
    "rift": {
        "title": "🌀 Rift Alert",
        "color": 0xAA33CC,
    },
    "tia": {
        "title": "📊 Tower Industrial Average",
        "color": 0x33AA55,
    },
    "tia_flash": {
        "title": "📊 TIA Market Flash",
        "color": 0xCC6633,
    },
    "weather": {
        "title": "🌫️ Dome Weather Report",
        "color": 0x6699BB,
    },
    "arena": {
        "title": "🏟️ Arena of Ascendance",
        "color": 0xCC3333,
    },
    "calendar": {
        "title": "📅 Faction Calendar",
        "color": 0x9966CC,
    },
    "missing": {
        "title": "🔍 Missing Persons",
        "color": 0x996633,
    },
    "exchange": {
        "title": "💱 EC / Kharma Exchange",
        "color": 0xCCAA33,
    },
    "bounty": {
        "title": "🎯 Bounty Board",
        "color": 0xCC4444,
    },
    "reminder": {
        "title": "🗼 Tower Oracle",
        "color": 0x555555,
    },
}


def _preview(text: str, max_lines: int = 4, max_chars: int = 400) -> str:
    """Return a short preview: first max_lines non-empty lines, capped at max_chars."""
    text = repair_mojibake(text or "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= max_lines and len(text) <= max_chars:
        return text
    preview = "\n".join(lines[:max_lines])
    if len(preview) > max_chars:
        preview = preview[:max_chars].rsplit(" ", 1)[0]
    if preview.rstrip() != text.rstrip():
        preview = preview.rstrip() + "\n-# *Read More for full story*"
    return preview


def wrap_bulletin(text: str, bulletin_type: str = "news") -> discord.Embed:
    """Wrap a text bulletin in a themed embed with a short preview.

    Full content is accessible via the Read More button (make_bulletin_view).
    """
    theme = THEMES.get(bulletin_type, THEMES["news"])
    text = repair_mojibake(text or "")

    embed = discord.Embed(
        description=_preview(text),
        color=theme["color"],
    )
    embed.set_author(name=repair_mojibake(theme["title"]))

    return embed


def wrap_bulletin_with_title(text: str, title: str, color: int = 0x3366AA) -> discord.Embed:
    """Wrap a bulletin with a custom title and color. Shows a short preview."""
    embed = discord.Embed(description=_preview(text), color=color)
    embed.set_author(name=repair_mojibake(title or ""))
    return embed
