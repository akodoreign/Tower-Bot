"""
src/agents/qwen_agent.py — Fast local inference agent using Qwen.

QwenAgent is optimized for quick, single-shot tasks:
    - Rules lookups
    - Style descriptions
    - Short text generation
    - Quick formatting tasks

Uses Qwen running locally via Ollama for zero-cost, low-latency inference.
No cloud tokens, no rate limits, instant responses.

Configuration via environment variables:
    QWEN_MODEL: Model name (default: "qwen")
    OLLAMA_URL: Base URL (default: "http://localhost:11434")
"""

from __future__ import annotations

import os
from typing import Optional

from src.agents.base import BaseAgent, AgentConfig, AgentResponse, ModelType


class QwenAgent(BaseAgent):
    """
    Fast local inference agent using Qwen via Ollama.
    
    Best for:
        - Rules lookups (D&D 5e questions)
        - Style/clothing descriptions
        - Short, focused text generation
        - Quick formatting tasks
        - Any task where speed > reasoning depth
    
    Usage:
        agent = QwenAgent()
        result = await agent.complete("What are the rules for opportunity attacks?")
        print(result.content)
    """
    
    def _get_config(self) -> AgentConfig:
        """Return Qwen-specific configuration."""
        model = os.getenv("QWEN_MODEL", "qwen3-8b-slim:latest")
        base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        
        # Ensure we're using the v1 API endpoint
        if not base_url.endswith("/v1"):
            if base_url.endswith("/api/chat"):
                base_url = base_url.replace("/api/chat", "/v1")
            else:
                base_url = f"{base_url.rstrip('/')}/v1"
        
        return AgentConfig(
            model_name=model,
            model_type=ModelType.LOCAL,
            base_url=base_url,
            timeout=180.0,         # Increased for slower Qwen 8B inference
            max_retries=2,         # Added retry for local model timeouts
            temperature=0.7,
            max_tokens=2048,       # Most local tasks don't need huge outputs
            enable_subagents=False,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        """Build the system prompt for Qwen tasks."""
        base_prompt = """\
You are a precise, helpful assistant for the Tower of Last Chance Discord bot.
You provide clear, concise answers formatted for Discord.

RULES:
- Be direct. No preamble ("Sure!", "Of course!") — start with the answer.
- Use Discord markdown: **bold** for emphasis, `code` for game terms.
- Keep responses focused. 2-6 lines unless more detail is explicitly needed.
- If you don't know something, say so briefly.
- Do NOT sign off with "Let me know if..." or similar.
"""
        if context:
            base_prompt += f"\n\nADDITIONAL CONTEXT:\n{context}"
        
        return base_prompt
    
    async def rules_query(
        self,
        question: str,
        rag_context: Optional[str] = None,
        campaign_overrides: Optional[str] = None,
    ) -> AgentResponse:
        """
        Specialized method for D&D rules questions.
        
        Args:
            question: The rules question to answer
            rag_context: Retrieved rulebook text from RAG
            campaign_overrides: Undercity-specific rule modifications
            
        Returns:
            AgentResponse with the rules answer
        """
        context_parts = []
        
        if rag_context:
            context_parts.append(f"RELEVANT RULEBOOK EXCERPTS:\n{rag_context}")
        else:
            context_parts.append("No matching excerpts found. Answer from general D&D 5e 2024 knowledge.")
        
        if campaign_overrides:
            context_parts.append(f"CAMPAIGN-SPECIFIC RULES:\n{campaign_overrides}")
        
        prompt = f"""Answer this D&D 5e 2024 rules question:

{question}

RULES FOR YOUR ANSWER:
- Answer based on the excerpts if they cover the topic. Quote the key rule briefly.
- If excerpts don't fully answer it, use general D&D 5e 2024 knowledge but say so.
- Be concise: 2-6 lines. Use Discord markdown (**bold** for key terms, `inline code` for dice/numbers).
- State the rule clearly first. Then explain edge cases if relevant.
- Do NOT write "According to the Player's Handbook..." — just state the rule.
- Do NOT repeat the question back.
- Output ONLY the answer."""
        
        return await self.complete(
            prompt=prompt,
            context="\n\n".join(context_parts),
            temperature=0.5,  # Lower temperature for factual answers
        )
    
    async def style_description(
        self,
        character_name: str,
        character_class: str = "",
        faction: str = "independent",
        occasion: str = "general",
        faction_style: Optional[str] = None,
        class_style: Optional[str] = None,
    ) -> AgentResponse:
        """
        Specialized method for character style/clothing descriptions.
        
        Args:
            character_name: Name of the character
            character_class: D&D class (fighter, rogue, etc.)
            faction: Undercity faction affiliation
            occasion: What the outfit is for (combat, diplomacy, etc.)
            faction_style: Pre-built faction style guide
            class_style: Pre-built class style notes
            
        Returns:
            AgentResponse with the style description
        """
        context_parts = []
        
        if faction_style:
            context_parts.append(f"FACTION AESTHETIC:\n{faction_style}")
        if class_style:
            context_parts.append(f"CLASS STYLE TENDENCY:\n{class_style}")
        
        prompt = f"""Write a vivid clothing and style description for this character:

CHARACTER: {character_name}
CLASS: {character_class or 'unspecified'}
FACTION: {faction}
OCCASION: {occasion}

SETTING: The Undercity — a sealed dark fantasy city with fashion from absorbed worlds.
Materials range from medieval cloth to salvaged tech to divine silk.
Lighting is mostly artificial: torch, bioluminescent vials, neon enchantment.

Include: primary outfit, colours, key materials, 2-3 specific accessories, footwear,
and one distinctive detail that makes this outfit immediately recognisable as THEIRS.

RULES:
- Be specific and tactile. Name fabrics, describe wear and repair.
- 4-6 lines. Discord markdown: **bold** key items, *italics* for atmosphere.
- Output ONLY the description. No preamble."""
        
        return await self.complete(
            prompt=prompt,
            context="\n\n".join(context_parts) if context_parts else None,
            temperature=0.8,  # Higher temperature for creative descriptions
        )
    
    async def format_text(
        self,
        text: str,
        format_instructions: str,
    ) -> AgentResponse:
        """
        Quick text formatting/transformation.
        
        Args:
            text: The text to format
            format_instructions: How to format it
            
        Returns:
            AgentResponse with the formatted text
        """
        prompt = f"""{format_instructions}

TEXT TO FORMAT:
{text}

Output ONLY the formatted text. No preamble or explanation."""
        
        return await self.complete(
            prompt=prompt,
            temperature=0.3,  # Low temperature for formatting tasks
        )
