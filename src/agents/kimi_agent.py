"""
src/agents/kimi_agent.py — Complex reasoning agent using a larger local model.

KimiAgent is optimized for complex, multi-step reasoning tasks:
    - News bulletin generation (world state → coherent narrative)
    - Mission generation (multiple interconnected elements)
    - Multi-step analysis

Uses a larger local model (e.g., qwen3-8b-slim:latest, qwen:32b, llama3:70b) via Ollama.
Runs 100% locally — no cloud required.

Configuration via environment variables:
    KIMI_MODEL: Model name (default: "qwen:32b")
    OLLAMA_URL: Base URL (default: "http://localhost:11434")
    KIMI_ENABLE_SUBAGENTS: Enable subagent orchestration (default: "false")
"""

from __future__ import annotations

import os
import logging
from typing import Optional, List, Dict, Any

from src.agents.base import BaseAgent, AgentConfig, AgentResponse, ModelType

logger = logging.getLogger(__name__)


class KimiAgent(BaseAgent):
    """
    Complex reasoning agent using a larger local model via Ollama.
    
    Uses a larger local model for tasks requiring more reasoning depth
    than QwenAgent. Runs 100% locally — no cloud required.
    
    Recommended models: qwen3-8b-slim:latest, qwen:32b, llama3:70b
    
    Best for:
        - News bulletin generation
        - Mission/quest generation
        - Complex narrative tasks
        - Multi-step reasoning
    
    Usage:
        agent = KimiAgent()
        
        # Simple completion
        result = await agent.complete("Generate a news bulletin about...")
    """
    
    def _get_config(self) -> AgentConfig:
        """Return Kimi-specific configuration."""
        model = os.getenv("KIMI_MODEL", "qwen3-8b-slim:latest")  # Local model default
        base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        enable_subagents = os.getenv("KIMI_ENABLE_SUBAGENTS", "false").lower() == "true"  # Disabled by default
        
        # Ensure we're using the v1 API endpoint
        if not base_url.endswith("/v1"):
            if base_url.endswith("/api/chat"):
                base_url = base_url.replace("/api/chat", "/v1")
            else:
                base_url = f"{base_url.rstrip('/')}/v1"
        
        return AgentConfig(
            model_name=model,
            model_type=ModelType.LOCAL,  # Local model
            base_url=base_url,
            timeout=300.0,           # Larger local models need more time
            max_retries=2,           # Retry on transient failures
            temperature=0.8,         # Higher for creative tasks
            max_tokens=4096,         # Complex tasks need more output
            enable_subagents=enable_subagents,
            max_concurrent_subagents=4,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        """Build the system prompt for Kimi tasks."""
        base_prompt = """\
You are the narrative intelligence for the Tower of Last Chance Discord bot.
You generate rich, coherent content for a dark urban fantasy setting.

SETTING: The Undercity — a sealed city under a Dome around the Tower of Last Chance.
The city absorbs fragments from other worlds, creating a patchwork of cultures,
technologies, and magics. Think: dark medieval fantasy base crossed with salvaged tech,
divine bureaucracy, and post-apocalyptic survival.

FACTIONS: Iron Fang Consortium (mercantile-military), Argent Blades (arena glory-hunters),
Wardens of Ash (military defenders), Serpent Choir (divine bureaucrats),
Obsidian Lotus (information brokers), Glass Sigil (rift researchers),
Patchwork Saints (healers), Adventurers Guild, Guild of Ashen Scrolls,
Tower Authority, Brother Thane's Cult.

TONE: Dark, gritty, specific, grounded. Every detail should feel earned.
Rumors contradict. Factions have agendas. Nothing is simple.

RULES:
- Be vivid and specific. Name places, people, factions.
- Use Discord markdown: **bold** for key terms, *italics* for atmosphere.
- Ground everything in the setting — no generic fantasy filler.
- No preamble ("Sure!", "Here's...") — start with the content.
- No sign-off. Just the requested content.
"""
        if context:
            base_prompt += f"\n\nADDITIONAL CONTEXT:\n{context}"
        
        return base_prompt
    
    async def generate_bulletin(
        self,
        news_type: str,
        memory_context: str = "",
        rift_context: str = "",
        npc_context: str = "",
        additional_context: str = "",
    ) -> AgentResponse:
        """
        Generate a news bulletin for the Undercity.
        
        Args:
            news_type: Type of bulletin (rumour, announcement, faction_news, etc.)
            memory_context: Recent news history for continuity
            rift_context: Current rift state information
            npc_context: Relevant NPC information
            additional_context: Any other context
            
        Returns:
            AgentResponse with the bulletin text
        """
        context_parts = []
        
        if memory_context:
            context_parts.append(f"RECENT NEWS HISTORY (for continuity):\n{memory_context}")
        if rift_context:
            context_parts.append(f"CURRENT RIFT SITUATION:\n{rift_context}")
        if npc_context:
            context_parts.append(f"RELEVANT NPCS:\n{npc_context}")
        if additional_context:
            context_parts.append(additional_context)
        
        prompt = f"""Generate a {news_type} bulletin for the Undercity.

REQUIREMENTS:
- 3-5 lines. Punchy, specific, grounded.
- Reference real locations, factions, and NPCs where appropriate.
- If this follows from recent events in the memory, build on them.
- Discord markdown: **bold** key terms, *italics* for rumour attribution.
- Output ONLY the bulletin. No meta-commentary."""
        
        return await self.complete(
            prompt=prompt,
            context="\n\n".join(context_parts) if context_parts else None,
        )
    
    async def generate_mission(
        self,
        difficulty: str = "C",
        faction: str = "",
        location: str = "",
        mission_type: str = "",
        context: str = "",
    ) -> AgentResponse:
        """
        Generate a mission/quest for the mission board.
        
        Args:
            difficulty: Mission difficulty (S/A/B/C/D/E)
            faction: Requesting faction
            location: Mission location
            mission_type: Type of mission (investigation, combat, etc.)
            context: Additional world context
            
        Returns:
            AgentResponse with mission JSON
        """
        prompt = f"""Generate a mission for the Undercity mission board.

PARAMETERS:
- Difficulty: {difficulty} rank
- Faction: {faction or "any"}
- Location: {location or "any Undercity district"}
- Type: {mission_type or "any"}

OUTPUT FORMAT (JSON):
{{
    "title": "Short punchy title",
    "description": "2-3 sentences. What needs doing and why.",
    "objectives": ["Primary objective", "Optional secondary"],
    "rewards": {{
        "ec": 100,  // Essence Coins
        "reputation": "faction_name"
    }},
    "complications": ["One twist or complication"],
    "npc_contact": "NPC name and brief descriptor"
}}

Generate a mission that fits the Undercity setting. Be specific.
Output ONLY the JSON, no markdown code fences."""
        
        return await self.complete(
            prompt=prompt,
            context=context if context else None,
            temperature=0.9,  # Higher for mission variety
        )
    
    async def orchestrate(
        self,
        subtasks: List[str],
        synthesis_prompt: str = "",
    ) -> AgentResponse:
        """
        Orchestrate multiple subtasks with optional synthesis.
        
        This leverages Kimi's subagent capabilities for parallel execution.
        Each subtask is processed, then results are synthesized.
        
        Args:
            subtasks: List of subtask prompts to execute
            synthesis_prompt: How to combine the results
            
        Returns:
            AgentResponse with synthesized results
        """
        if not self.config.enable_subagents:
            # Fallback: process sequentially
            return await self._sequential_orchestrate(subtasks, synthesis_prompt)
        
        # Build orchestration prompt
        task_list = "\n".join(f"- {task}" for task in subtasks)
        
        prompt = f"""Execute these subtasks in parallel:

{task_list}

For each subtask, provide a clear, complete response.
Label each response with [SUBTASK N] where N is the task number (1-indexed).

{f'Then, synthesize the results: {synthesis_prompt}' if synthesis_prompt else ''}
{f'Label the synthesis with [SYNTHESIS].' if synthesis_prompt else ''}

Output all results."""
        
        response = await self.complete(prompt=prompt)
        
        # Parse subtask results
        if response.success:
            results = self._parse_subtask_results(response.content, len(subtasks))
            response.subagent_results = results
        
        return response
    
    async def _sequential_orchestrate(
        self,
        subtasks: List[str],
        synthesis_prompt: str = "",
    ) -> AgentResponse:
        """Fallback sequential processing when subagents are disabled."""
        results = []
        
        for i, task in enumerate(subtasks):
            result = await self.complete(prompt=task)
            if result.success:
                results.append({
                    "task_index": i,
                    "task": task,
                    "result": result.content,
                })
            else:
                results.append({
                    "task_index": i,
                    "task": task,
                    "error": result.error,
                })
        
        # Synthesize if requested
        if synthesis_prompt and results:
            result_summary = "\n\n".join(
                f"[SUBTASK {r['task_index'] + 1}]\n{r.get('result', r.get('error', ''))}"
                for r in results
            )
            
            synth_result = await self.complete(
                prompt=f"""Synthesize these results:

{result_summary}

{synthesis_prompt}"""
            )
            
            return AgentResponse(
                content=synth_result.content,
                model=self.config.model_name,
                success=synth_result.success,
                error=synth_result.error,
                subagent_results=results,
            )
        
        # Return combined results
        combined = "\n\n".join(
            f"[SUBTASK {r['task_index'] + 1}]\n{r.get('result', r.get('error', ''))}"
            for r in results
        )
        
        return AgentResponse(
            content=combined,
            model=self.config.model_name,
            success=all("error" not in r for r in results),
            subagent_results=results,
        )
    
    def _parse_subtask_results(self, content: str, expected_count: int) -> List[Dict]:
        """Parse subtask results from orchestration response."""
        import re
        
        results = []
        
        # Match [SUBTASK N] blocks
        pattern = r'\[SUBTASK\s+(\d+)\](.*?)(?=\[SUBTASK|\[SYNTHESIS\]|$)'
        matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
        
        for idx_str, result_text in matches:
            try:
                idx = int(idx_str) - 1  # Convert to 0-indexed
                results.append({
                    "task_index": idx,
                    "result": result_text.strip(),
                })
            except ValueError:
                continue
        
        # Fill in any missing indices
        found_indices = {r["task_index"] for r in results}
        for i in range(expected_count):
            if i not in found_indices:
                results.append({
                    "task_index": i,
                    "result": "",
                    "error": "No result found",
                })
        
        return sorted(results, key=lambda r: r["task_index"])
