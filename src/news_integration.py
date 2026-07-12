"""
src/news_integration.py — Bridge between news agents and news_feed.py

Provides:
- Agent-based bulletin generation for news, gossip, and sports
- Weighted random selection of bulletin types
- Integration with expandable bulletin UI
- Memory management (gossip excluded)

Usage in news_feed.py:
    from src.news_integration import generate_editorial_bulletin, EditorType
    
    result = await generate_editorial_bulletin(EditorType.RANDOM)
    # result.embed, result.view, result.save_to_memory, result.raw_content
"""

from __future__ import annotations

import random
import logging
from datetime import datetime
from typing import Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import discord

logger = logging.getLogger(__name__)

DISCORD_CONTENT_LIMIT = 2000
DISCORD_EMBED_TITLE_LIMIT = 256
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_EMBED_FOOTER_LIMIT = 2048


class EditorType(Enum):
    """Types of editorial content."""
    NEWS = "news"
    GOSSIP = "gossip"
    SPORTS = "sports"
    RANDOM = "random"  # Weighted random selection


# Weighted probabilities for random selection
# News is most common, gossip is occasional, sports follows arena schedule
EDITOR_WEIGHTS = {
    EditorType.NEWS: 0.60,    # 60% — Standard news
    EditorType.GOSSIP: 0.20,  # 20% — Gossip column
    EditorType.SPORTS: 0.20,  # 20% — Sports coverage
}


@dataclass
class EditorialResult:
    """Result from editorial bulletin generation."""
    embed: Optional[discord.Embed]
    view: Optional[discord.ui.View]
    raw_content: str
    preview: str
    headline: str
    editor_type: EditorType
    save_to_memory: bool
    success: bool
    error: Optional[str] = None
    
    @property
    def formatted_text(self) -> str:
        """Legacy format for text-only posting."""
        return self.raw_content


def _select_editor_type() -> EditorType:
    """Weighted random selection of editor type."""
    roll = random.random()
    cumulative = 0.0
    
    for editor_type, weight in EDITOR_WEIGHTS.items():
        cumulative += weight
        if roll < cumulative:
            return editor_type
    
    return EditorType.NEWS  # Fallback


async def generate_editorial_bulletin(
    editor_type: EditorType = EditorType.RANDOM,
    topic: Optional[str] = None,
    venue: Optional[str] = None,
) -> EditorialResult:
    """
    Generate a bulletin using the editorial agent system.
    
    Args:
        editor_type: Which editor to use (or RANDOM for weighted selection)
        topic: Optional topic seed for gossip/news
        venue: Optional venue for sports
        
    Returns:
        EditorialResult with embed, view, and metadata
    """
    from src.agents.news_agents import (
        NewsEditorAgent,
        GossipEditorAgent,
        SportsColumnistAgent,
    )
    from src.expandable_bulletin import create_bulletin_message
    
    # Select editor if random
    if editor_type == EditorType.RANDOM:
        editor_type = _select_editor_type()
    
    logger.info(f"📰 Generating {editor_type.value} bulletin")
    
    try:
        # Generate based on type
        if editor_type == EditorType.NEWS:
            agent = NewsEditorAgent()
            result = await agent.generate_bulletin(
                news_type="general",
                instruction=topic or "Write a news bulletin about recent events in the Undercity.",
            )
            await agent.close()
            
        elif editor_type == EditorType.GOSSIP:
            agent = GossipEditorAgent()
            result = await agent.generate_bulletin(
                topic=topic,
            )
            await agent.close()
            
        elif editor_type == EditorType.SPORTS:
            agent = SportsColumnistAgent()
            result = await agent.generate_bulletin(
                venue=venue,
            )
            await agent.close()
            
        else:
            return EditorialResult(
                embed=None,
                view=None,
                raw_content="",
                preview="",
                headline="",
                editor_type=editor_type,
                save_to_memory=False,
                success=False,
                error=f"Unknown editor type: {editor_type}",
            )
        
        if not result.success:
            return EditorialResult(
                embed=None,
                view=None,
                raw_content="",
                preview="",
                headline="",
                editor_type=editor_type,
                save_to_memory=False,
                success=False,
                error=result.error,
            )
        
        # Create expandable embed + view
        embed, view = create_bulletin_message(
            preview=result.preview,
            full_content=result.full_content,
            headline=result.headline,
            bulletin_type=result.bulletin_type,
            source_attribution=result.source_attribution,
            venue=result.venue,
        )
        
        return EditorialResult(
            embed=embed,
            view=view,
            raw_content=result.full_content,
            preview=result.preview,
            headline=result.headline,
            editor_type=editor_type,
            save_to_memory=result.save_to_memory,
            success=True,
        )
        
    except Exception as e:
        logger.error(f"📰 Editorial bulletin generation failed: {e}")
        return EditorialResult(
            embed=None,
            view=None,
            raw_content="",
            preview="",
            headline="",
            editor_type=editor_type,
            save_to_memory=False,
            success=False,
            error=str(e),
        )


async def generate_gossip_only(
    topic: Optional[str] = None,
    seed_npc: Optional[str] = None,
) -> EditorialResult:
    """
    Generate a gossip bulletin specifically.
    Convenience wrapper for GossipEditorAgent.
    
    NOTE: Gossip is NEVER saved to memory.
    """
    return await generate_editorial_bulletin(
        editor_type=EditorType.GOSSIP,
        topic=topic,
    )


async def generate_sports_only(
    event_type: Optional[str] = None,
    venue: Optional[str] = None,
) -> EditorialResult:
    """
    Generate a sports bulletin specifically.
    Convenience wrapper for SportsColumnistAgent.
    """
    return await generate_editorial_bulletin(
        editor_type=EditorType.SPORTS,
        venue=venue,
    )


def get_timestamp_line() -> str:
    """Generate the dual timestamp line for bulletins."""
    TOWER_YEAR_OFFSET = 10
    now = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    real_str = now.strftime("%Y-%m-%d %H:%M")
    tower_str = tower.strftime("%d %b %Y, %H:%M")
    return f"-# 🕰️ {real_str} | Tower: {tower_str}"


def _clamp_text(value: str, limit: int) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _prepare_embed_for_discord(embed: discord.Embed) -> discord.Embed:
    """Clamp mutable embed fields to Discord's per-field limits before send."""
    if embed.title:
        embed.title = _clamp_text(embed.title, DISCORD_EMBED_TITLE_LIMIT)
    if embed.description:
        embed.description = _clamp_text(embed.description, DISCORD_EMBED_DESCRIPTION_LIMIT)
    footer_text = getattr(embed.footer, "text", None)
    if footer_text:
        embed.set_footer(text=_clamp_text(footer_text, DISCORD_EMBED_FOOTER_LIMIT))
    return embed


def _fallback_editorial_text(result: EditorialResult) -> str:
    text = result.preview or result.raw_content or result.headline or "Editorial bulletin unavailable."
    return _clamp_text(text, DISCORD_CONTENT_LIMIT)


def _is_invalid_form_body(exc: Exception) -> bool:
    return (
        isinstance(exc, discord.HTTPException)
        and getattr(exc, "status", None) == 400
        and getattr(exc, "code", None) == 50035
    )


# ---------------------------------------------------------------------------
# Integration with news_feed.py posting
# ---------------------------------------------------------------------------

async def post_editorial_bulletin(
    channel: discord.TextChannel,
    editor_type: EditorType = EditorType.RANDOM,
    topic: Optional[str] = None,
    venue: Optional[str] = None,
    write_memory_func: Optional[callable] = None,
) -> Optional[discord.Message]:
    """
    Generate and post an editorial bulletin to a channel.
    
    This is the main integration point for news_feed.py.
    
    Args:
        channel: Discord channel to post to
        editor_type: Which editor to use
        topic: Optional topic seed
        venue: Optional venue for sports
        write_memory_func: Function to write to news memory (skipped for gossip)
        
    Returns:
        The posted message, or None if generation failed
    """
    result = await generate_editorial_bulletin(
        editor_type=editor_type,
        topic=topic,
        venue=venue,
    )
    
    if not result.success:
        logger.warning(f"📰 Editorial bulletin failed: {result.error}")
        return None
    
    try:
        # Add timestamp and clamp mutable fields to Discord's embed limits.
        if result.embed:
            timestamp_line = get_timestamp_line()
            body = result.embed.description or ""
            combined = f"{timestamp_line}\n\n{body}"
            result.embed.description = combined
            _prepare_embed_for_discord(result.embed)
        
        # Post with embed and Read More button
        try:
            message = await channel.send(
                embed=result.embed,
                view=result.view,
            )
        except Exception as e:
            if not _is_invalid_form_body(e):
                raise
            logger.error(
                "ðŸ“° Editorial embed rejected by Discord 50035; retrying text-only fallback "
                f"(preview={len(result.preview)}, full={len(result.raw_content)}, "
                f"headline={len(result.headline)})"
            )
            message = await channel.send(content=_fallback_editorial_text(result))
        
        # Save to memory (if not gossip)
        if result.save_to_memory and write_memory_func:
            # Strip to facts before saving
            write_memory_func(result.raw_content)
            logger.info(f"📰 {result.editor_type.value} bulletin saved to memory")
        elif not result.save_to_memory:
            logger.info(f"📰 {result.editor_type.value} bulletin NOT saved to memory (gossip)")
        
        return message
        
    except Exception as e:
        logger.error(f"📰 Failed to post editorial bulletin: {e}")
        return None


# ---------------------------------------------------------------------------
# Slash command helpers
# ---------------------------------------------------------------------------

async def generate_for_command(
    editor_type_str: str,
    topic: Optional[str] = None,
) -> Tuple[Optional[discord.Embed], Optional[discord.ui.View], str]:
    """
    Generate a bulletin for slash command usage.
    
    Returns: (embed, view, error_message)
    """
    try:
        editor_type = EditorType(editor_type_str.lower())
    except ValueError:
        return None, None, f"Unknown editor type: {editor_type_str}"
    
    result = await generate_editorial_bulletin(
        editor_type=editor_type,
        topic=topic,
    )
    
    if not result.success:
        return None, None, result.error or "Generation failed"
    
    return result.embed, result.view, ""
