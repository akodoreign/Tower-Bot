"""
src/agents/helpers.py — Convenience helpers for agent calls across the codebase.

Provides lazy-loaded singleton agents and common generation patterns
used by news_feed.py, mission_board.py, and other modules.

Usage:
    from src.agents.helpers import generate_bulletin, generate_with_kimi, generate_with_qwen

    # Quick generation using Kimi (complex tasks)
    text = await generate_with_kimi(prompt, context=..., temperature=0.8)

    # Quick generation using Qwen (fast tasks)
    text = await generate_with_qwen(prompt, temperature=0.5)

    # News bulletin generation (uses Kimi)
    bulletin = await generate_bulletin(news_type="rift", instruction="...", context="...")
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-loaded agent singletons
# ---------------------------------------------------------------------------

_qwen_agent = None
_kimi_agent = None


def _get_qwen():
    """Get or create QwenAgent singleton."""
    global _qwen_agent
    if _qwen_agent is None:
        from src.agents import QwenAgent
        _qwen_agent = QwenAgent()
    return _qwen_agent


def _get_kimi():
    """Get or create KimiAgent singleton."""
    global _kimi_agent
    if _kimi_agent is None:
        from src.agents import KimiAgent
        _kimi_agent = KimiAgent()
    return _kimi_agent


# ---------------------------------------------------------------------------
# Quick generation helpers
# ---------------------------------------------------------------------------

async def generate_with_qwen(
    prompt: str,
    context: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> str:
    """
    Quick generation using QwenAgent (fast local inference).
    
    Returns the generated text, or empty string on failure.
    """
    from src.ollama_busy import is_available, get_busy_reason
    
    if not is_available():
        logger.info(f"🤖 Qwen skipping — Ollama busy ({get_busy_reason()})")
        return ""
    
    try:
        agent = _get_qwen()
        response = await agent.complete(
            prompt=prompt,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        if response.success:
            return response.content
        else:
            logger.warning(f"generate_with_qwen error: {response.error}")
            return ""
    except Exception as e:
        logger.error(f"generate_with_qwen exception: {type(e).__name__}: {e}")
        return ""


async def generate_with_kimi(
    prompt: str,
    context: Optional[str] = None,
    temperature: float = 0.8,
    max_tokens: int = 4096,
) -> str:
    """
    Quick generation using KimiAgent (complex reasoning).
    
    Returns the generated text, or empty string on failure.
    """
    from src.ollama_busy import is_available, get_busy_reason
    
    if not is_available():
        logger.info(f"🤖 Kimi skipping — Ollama busy ({get_busy_reason()})")
        return ""
    
    try:
        agent = _get_kimi()
        response = await agent.complete(
            prompt=prompt,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        if response.success:
            return response.content
        else:
            logger.warning(f"generate_with_kimi error: {response.error}")
            return ""
    except Exception as e:
        logger.error(f"generate_with_kimi exception: {type(e).__name__}: {e}")
        return ""


# ---------------------------------------------------------------------------
# News bulletin generation helper
# ---------------------------------------------------------------------------

_WORLD_LORE_BRIEF = """\
SETTING: The Undercity — a sealed city under a Dome around the Tower of Last Chance.
Rifts are rare tears in reality. Most common in the Warrens (structurally weak districts).
Extremely rare in other districts. They start tiny and escalate over days if ignored.
FACTIONS: Iron Fang Consortium, Argent Blades, Wardens of Ash, Serpent Choir,
Obsidian Lotus, Glass Sigil, Patchwork Saints, Adventurers Guild,
Guild of Ashen Scrolls, Tower Authority, Independent, Brother Thane's Cult.
TONE: Dark urban fantasy. Gritty, specific, grounded."""


async def generate_bulletin(
    news_type: str,
    instruction: str,
    memory_context: str = "",
    additional_context: str = "",
    max_lines: int = 4,
) -> Optional[str]:
    """
    Generate a news bulletin using KimiAgent.
    
    Args:
        news_type: Type of bulletin (rift, rumour, faction_news, etc.)
        instruction: Specific instructions for this bulletin
        memory_context: Recent news history for continuity
        additional_context: Any other context needed
        max_lines: Maximum lines for the bulletin
        
    Returns:
        Generated bulletin text, or None on failure
    """
    from src.ollama_busy import is_available, get_busy_reason
    
    if not is_available():
        logger.info(f"📰 Bulletin skipping — Ollama busy ({get_busy_reason()})")
        return None
    
    context_parts = [_WORLD_LORE_BRIEF]
    if memory_context:
        context_parts.append(f"RECENT NEWS HISTORY:\n{memory_context}")
    if additional_context:
        context_parts.append(additional_context)
    
    prompt = f"""{instruction}

RULES:
- Output ONLY the bulletin. No preamble, no sign-off.
- Use Discord markdown. {max_lines} lines max.
- Ground it in specific locations, NPCs, and factions.
- If your response contains anything other than the bulletin, you have failed."""
    
    try:
        agent = _get_kimi()
        response = await agent.complete(
            prompt=prompt,
            context="\n\n".join(context_parts),
            temperature=0.8,
        )
        
        if response.success and response.content:
            return response.content
        else:
            logger.warning(f"generate_bulletin error: {response.error}")
            return None
    except Exception as e:
        logger.error(f"generate_bulletin exception: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# Mission generation helper
# ---------------------------------------------------------------------------

async def generate_mission_text(
    prompt: str,
    context: str = "",
    temperature: float = 0.9,
) -> Optional[str]:
    """
    Generate mission content using KimiAgent.
    
    Returns generated text, or None on failure.
    """
    from src.ollama_busy import is_available, get_busy_reason
    
    if not is_available():
        logger.info(f"📋 Mission gen skipping — Ollama busy ({get_busy_reason()})")
        return None
    
    try:
        agent = _get_kimi()
        response = await agent.complete(
            prompt=prompt,
            context=context,
            temperature=temperature,
        )
        
        if response.success and response.content:
            return response.content
        else:
            logger.warning(f"generate_mission_text error: {response.error}")
            return None
    except Exception as e:
        logger.error(f"generate_mission_text exception: {type(e).__name__}: {e}")
        return None
