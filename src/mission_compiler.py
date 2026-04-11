"""
mission_compiler.py — Compiles mission JSON into full .docx modules using agents and skills.

This is Stage 2 of the mission pipeline:
  Stage 1: Generate mission JSON (via mission_json_builder.py or mission_board.py)
  Stage 2: Compile JSON → use agents + skills → expand content → build .docx → post to Discord

The compiler uses FOUR agents for quality enhancement:
  - ProAuthorAgent: FIRST PASS - transforms JSON into compelling narrative prose
  - DNDExpertAgent: Validates mechanics, CR, encounter balance, D&D 5e 2024 compliance
  - DNDVeteranAgent: Enhances narrative, NPC dialogue, atmosphere, world consistency  
  - AICriticAgent: Final quality check, identifies gaps, suggests improvements

Skills are auto-selected based on mission type and injected into generation prompts.

Usage:
    from src.mission_compiler import MissionCompiler
    
    compiler = MissionCompiler(client)
    docx_path = await compiler.compile_and_post(mission_dict, player_name)
"""

from __future__ import annotations

import os
import json
import asyncio
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from src.log import logger
from src.ollama_busy import mark_busy, mark_available, is_available
from src.skills import (
    load_all_skills,
    get_skill_for_task,
    build_system_prompt_with_skills,
    get_skill_content,
)
from src.agents.learning_agents import (
    DNDExpertAgent,
    DNDVeteranAgent,
    AICriticAgent,
    ProAuthorAgent,
)
from src.mission_builder.docx_builder import build_docx, format_module_for_docx
from src.mission_builder.mission_json_builder import MissionJsonBuilder

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = PROJECT_ROOT / "generated_modules"
PENDING_DIR = GENERATED_DIR / "pending"
COMPLETED_DIR = GENERATED_DIR / "completed"
CAMPAIGN_DOCS = PROJECT_ROOT / "campaign_docs"

# Discord channel for posting modules
MODULE_CHANNEL_ID = 1484147249637359769

# Tier → CR mapping (same as module_generator.py)
TIER_CR_MAP = {
    "local": 4, "patrol": 4, "escort": 5, "standard": 6,
    "investigation": 6, "rift": 8, "dungeon": 8, "dungeon-delve": 8,
    "major": 8, "inter-guild": 10, "high-stakes": 10,
    "epic": 12, "divine": 12, "tower": 12,
}

# Mission type → skill mapping
MISSION_TYPE_SKILLS = {
    "standard": ["module-quality", "cw-mission-gen", "tower-bot"],
    "dungeon-delve": ["module-quality", "cw-mission-gen", "dnd5e-srd", "tower-bot"],
    "investigation": ["module-quality", "cw-mission-gen", "tower-bot"],
    "combat": ["module-quality", "cw-mission-gen", "dnd5e-srd"],
    "social": ["module-quality", "cw-mission-gen", "tower-bot"],
    "heist": ["module-quality", "cw-mission-gen", "tower-bot"],
    "rift": ["module-quality", "cw-mission-gen", "tower-bot"],
}


class MissionCompiler:
    """
    Compiles mission JSON into full .docx modules using agents and skills.
    
    Attributes:
        client: Discord client for posting modules
        agents: Dict of initialized agent instances
        skills: Loaded skill cache
    """
    
    def __init__(self, client=None):
        """
        Initialize the compiler.
        
        Args:
            client: Discord client for posting (optional, can be set later)
        """
        self.client = client
        self.agents = {
            "pro_author": ProAuthorAgent(),  # Runs FIRST
            "dnd_expert": DNDExpertAgent(),
            "dnd_veteran": DNDVeteranAgent(),
            "ai_critic": AICriticAgent(),
        }
        self.skills = None
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure required directories exist."""
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        COMPLETED_DIR.mkdir(parents=True, exist_ok=True)
    
    def _load_skills(self) -> Dict:
        """Load skills if not already loaded."""
        if self.skills is None:
            self.skills = load_all_skills()
            logger.info(f"📚 Loaded {len(self.skills)} skills for compilation")
        return self.skills
    
    def _get_skills_for_mission(self, mission_type: str) -> List[str]:
        """Get relevant skill names for a mission type."""
        return MISSION_TYPE_SKILLS.get(mission_type, ["cw-mission-gen", "tower-bot"])
    
    def _build_skill_context(self, mission_type: str, max_chars: int = 4000) -> str:
        """
        Build skill context string for injection into prompts.
        
        Args:
            mission_type: Type of mission (dungeon-delve, investigation, etc.)
            max_chars: Maximum characters to include
        
        Returns:
            Formatted skill context string
        """
        skills = self._load_skills()
        skill_names = self._get_skills_for_mission(mission_type)
        
        context_parts = []
        total_chars = 0
        
        for name in skill_names:
            if name in skills:
                content = skills[name].content
                # Truncate if needed
                remaining = max_chars - total_chars
                if remaining <= 0:
                    break
                if len(content) > remaining:
                    content = content[:remaining] + "\n... [truncated]"
                context_parts.append(f"### SKILL: {name}\n{content}")
                total_chars += len(content)
        
        if context_parts:
            return "\n\n".join(context_parts)
        return ""
    
    async def _load_campaign_context(self) -> Dict[str, Any]:
        """Load campaign context (NPCs, factions, recent news)."""
        context = {}
        
        # NPC roster — from MySQL
        try:
            from src.db_api import raw_query as _rq_mc
            _npc_rows = _rq_mc(
                "SELECT name, faction, role, location, status FROM npcs "
                "WHERE status = 'alive' ORDER BY name LIMIT 20"
            ) or []
            context["npcs"] = [dict(r) for r in _npc_rows]
        except Exception:
            context["npcs"] = []

        # Faction info — from MySQL
        try:
            from src.db_api import get_all_faction_reputations
            _rep_rows = get_all_faction_reputations() or []
            context["factions"] = {
                r["faction_name"]: {"tier": r["tier"], "points": r["reputation_score"]}
                for r in _rep_rows
            }
        except Exception:
            context["factions"] = {}
        
        # Recent news — from MySQL
        try:
            from src.db_api import raw_query as _rq_n
            _nrows = _rq_n("SELECT facts FROM news_memory ORDER BY id DESC LIMIT 8") or []
            context["news"] = "\n".join(r.get("facts") or "" for r in _nrows if r.get("facts"))
        except Exception:
            news_path = CAMPAIGN_DOCS / "news_memory.txt"
            context["news"] = ""
            if news_path.exists():
                try:
                    context["news"] = news_path.read_text(encoding="utf-8")[-3000:]
                except Exception:
                    pass
        
        return context
    
    async def _agent_enhance_mechanics(
        self,
        content: str,
        mission_data: Dict,
        skill_context: str,
    ) -> Tuple[str, Dict]:
        """
        Use DNDExpertAgent to validate and enhance mechanics.
        
        Returns:
            Tuple of (enhanced_content, agent_feedback)
        """
        agent = self.agents["dnd_expert"]
        
        cr = mission_data.get("metadata", {}).get("cr", 6)
        tier = mission_data.get("metadata", {}).get("tier", "standard")
        mission_type = mission_data.get("metadata", {}).get("mission_type", "standard")
        
        prompt = f"""Review and enhance the mechanics in this D&D 5e 2024 mission module.

MISSION METADATA:
- CR: {cr}
- Tier: {tier}
- Type: {mission_type}

CURRENT CONTENT:
{content[:3000]}

SKILL GUIDANCE:
{skill_context[:1500]}

TASKS:
1. Verify all DCs are appropriate for the party level (DC = 8 + proficiency + ability mod)
2. Check encounter balance against CR {cr}
3. Add specific stat blocks or creature references where missing
4. Ensure XP rewards match difficulty
5. Add skill check DCs where narrative implies challenges

Output the enhanced content with mechanical details added inline.
Keep the narrative structure but inject concrete numbers and rules references."""
        
        response = await agent.complete(prompt, force=True)  # force=True bypasses busy check
        
        feedback = {
            "agent": "DNDExpert",
            "success": response.success,
            "issues": [],
            "enhancements": [],
        }
        
        if response.success and response.content:
            # Extract any issues mentioned
            if "issue" in response.content.lower() or "problem" in response.content.lower():
                feedback["issues"].append("Mechanics review found potential issues")
            return response.content, feedback
        
        return content, feedback
    
    async def _agent_enhance_narrative(
        self,
        content: str,
        mission_data: Dict,
        campaign_context: Dict,
        skill_context: str,
    ) -> Tuple[str, Dict]:
        """
        Use DNDVeteranAgent to enhance narrative quality.
        
        Returns:
            Tuple of (enhanced_content, agent_feedback)
        """
        agent = self.agents["dnd_veteran"]
        
        faction = mission_data.get("metadata", {}).get("faction", "Independent")
        title = mission_data.get("metadata", {}).get("title", "Unknown Mission")
        
        # Build NPC reference
        npc_refs = []
        for npc in campaign_context.get("npcs", [])[:8]:
            npc_refs.append(f"- {npc.get('name', '?')} ({npc.get('faction', '?')}): {npc.get('role', '?')}")
        npc_block = "\n".join(npc_refs) if npc_refs else "No NPCs loaded"
        
        prompt = f"""Enhance the narrative quality of this D&D mission module.

MISSION: {title}
FACTION: {faction}

CURRENT CONTENT:
{content[:3000]}

AVAILABLE NPCs (use these names for consistency):
{npc_block}

RECENT UNDERCITY NEWS:
{campaign_context.get('news', '')[:800]}

SKILL GUIDANCE:
{skill_context[:1500]}

TASKS:
1. Add vivid read-aloud text for key scenes (box it with >>> markers)
2. Enhance NPC dialogue with personality and motivation
3. Add atmospheric descriptions (sounds, smells, lighting)
4. Ensure faction motivations are clear and authentic
5. Add dramatic tension and stakes

Output the enhanced content with narrative improvements inline.
Preserve all mechanical content but wrap it in compelling story."""
        
        response = await agent.complete(prompt, force=True)  # force=True bypasses busy check
        
        feedback = {
            "agent": "DNDVeteran",
            "success": response.success,
            "narrative_score": 0.7,
        }
        
        if response.success and response.content:
            return response.content, feedback
        
        return content, feedback
    
    async def _agent_quality_check(
        self,
        content: str,
        mission_data: Dict,
    ) -> Dict:
        """
        Use AICriticAgent for final quality check.
        
        Returns:
            Quality assessment dict
        """
        agent = self.agents["ai_critic"]
        
        prompt = f"""Perform a final quality check on this D&D mission module.

MISSION TITLE: {mission_data.get('metadata', {}).get('title', '?')}

CONTENT:
{content[:4000]}

CHECKLIST:
1. Does it have a clear hook and objective?
2. Are there at least 2-3 distinct encounters?
3. Is read-aloud text present for key moments?
4. Are NPCs named and motivated?
5. Are rewards specified?
6. Is the pacing good (setup → rising action → climax → resolution)?
7. Are mechanical elements (DCs, stats, XP) present?

Output a quality score (1-10) and list any critical gaps."""
        
        response = await agent.complete(prompt, force=True)  # force=True bypasses busy check
        
        quality = {
            "agent": "AICritic",
            "success": response.success,
            "score": 7,  # Default
            "gaps": [],
            "ready_for_play": True,
        }
        
        if response.success and response.content:
            # Try to extract score
            import re
            score_match = re.search(r'(\d+)\s*/\s*10|score[:\s]+(\d+)', response.content.lower())
            if score_match:
                score = int(score_match.group(1) or score_match.group(2))
                quality["score"] = min(10, max(1, score))
            
            # Check for critical issues
            if "critical" in response.content.lower() or "missing" in response.content.lower():
                quality["gaps"].append("Quality check found gaps")
                if quality["score"] < 5:
                    quality["ready_for_play"] = False
        
        return quality
    
    async def _generate_section(
        self,
        section_name: str,
        mission_data: Dict,
        skill_context: str,
        campaign_context: Dict,
        previous_sections: str = "",
    ) -> str:
        """
        Generate a single section of the module using Ollama + skills.
        
        Args:
            section_name: Name of section (overview, act_1, act_2, etc.)
            mission_data: Mission JSON data
            skill_context: Skill content to inject
            campaign_context: Campaign context (NPCs, factions, news)
            previous_sections: Previously generated sections for continuity
        
        Returns:
            Generated section content
        """
        import httpx
        
        title = mission_data.get("metadata", {}).get("title", "Unknown Mission")
        faction = mission_data.get("metadata", {}).get("faction", "Independent")
        tier = mission_data.get("metadata", {}).get("tier", "standard")
        cr = mission_data.get("metadata", {}).get("cr", 6)
        mission_type = mission_data.get("metadata", {}).get("mission_type", "standard")
        
        # Build NPC reference
        npc_refs = []
        for npc in campaign_context.get("npcs", [])[:5]:
            if npc.get("faction", "").lower() == faction.lower():
                npc_refs.append(f"{npc.get('name', '?')} ({npc.get('role', '?')})")
        
        section_prompts = {
            "overview": f"""Write the OVERVIEW section for a D&D 5e 2024 mission module.

MISSION: {title}
FACTION: {faction}
TIER: {tier} (CR {cr})
TYPE: {mission_type}

Include:
- Mission hook (why the party is hired)
- Primary objective
- Key locations (2-3)
- Major NPCs involved: {', '.join(npc_refs) if npc_refs else 'To be introduced'}
- Expected challenges
- Reward summary

Write 400-600 words. Be specific and evocative.""",

            "act_1": f"""Write ACT 1 (Setup & Hook) for the mission module.

MISSION: {title}
FACTION: {faction}
CR: {cr}

PREVIOUS CONTEXT:
{previous_sections[:1500]}

Include:
- Opening scene with read-aloud text (mark with >>>)
- NPC who delivers the mission brief
- Initial information gathering opportunities
- First minor challenge or encounter (social or exploration)
- Clues pointing to Act 2

Write 500-800 words. Include at least one read-aloud box.""",

            "act_2": f"""Write ACT 2 (Rising Action) for the mission module.

MISSION: {title}
FACTION: {faction}
CR: {cr}

PREVIOUS CONTEXT:
{previous_sections[:1500]}

Include:
- Travel or exploration scene
- Major encounter (combat or complex social)
- Environmental hazards or puzzles
- Discovery that raises stakes
- NPC interaction that provides crucial info

Write 600-900 words. Include stat blocks or DCs for encounters.""",

            "act_3": f"""Write ACT 3 (Climax) for the mission module.

MISSION: {title}
FACTION: {faction}
CR: {cr}

PREVIOUS CONTEXT:
{previous_sections[:1500]}

Include:
- Final location description with read-aloud
- Boss encounter OR major challenge
- Full stat block or encounter breakdown
- Environmental factors that affect combat
- Victory and failure conditions

Write 600-900 words. Be tactically specific.""",

            "rewards": f"""Write the REWARDS & CONCLUSION section.

MISSION: {title}
FACTION: {faction}
TIER: {tier}

PREVIOUS CONTEXT:
{previous_sections[:1000]}

Include:
- XP awards (individual and party)
- Gold/treasure rewards
- Faction reputation changes
- Magic items or special rewards (if any)
- Consequences of success/failure
- Hooks for future missions

Write 300-500 words.""",
        }
        
        prompt = section_prompts.get(section_name, f"Write the {section_name} section.")
        
        system = f"""You are a master D&D 5e 2024 module writer for the Tower of Last Chance campaign.
The setting is the Undercity — a dark urban fantasy underworld beneath a massive tower.

═══ ANTI-PATTERNS (NEVER USE) ═══
❌ Purple prose ("ethereal glow", "otherworldly pallor")
❌ Echo chamber (saying the same thing multiple ways)
❌ Hedging ("seemed to", "appeared to", "might be")
❌ Adjective avalanche (more than one adjective per noun)
❌ Generic locations ("a warehouse" → name it specifically)
❌ Banned phrases: "It is worth noting", "Needless to say", "A sense of"

═══ REQUIRED PATTERNS ═══
✓ Specific names, numbers, times, locations
✓ Sensory grounding (sight, sound, smell, texture)
✓ Read-aloud text in present tense, second person
✓ Short sentences for action, varied length for description
✓ NPCs have: Appearance (2-3 details), Voice, Knows, Wants
✓ Encounters have: Setup, Terrain, Morale, Loot

SKILL GUIDANCE:
{skill_context[:4000]}

Write vivid, specific, playable content. Every scene should be immediately runnable at the table."""
        
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
        
        try:
            from src.ollama_queue import call_ollama, OllamaBusyError
            data = await call_ollama(
                payload={
                    "model": ollama_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                },
                timeout=300.0,
                caller="mission_compiler",
            )

            content = ""
            if isinstance(data, dict):
                msg = data.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content", "").strip()

            # Strip AI preamble
            lines = content.splitlines()
            skip_prefixes = ("sure", "here's", "here is", "certainly", "of course")
            while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip_prefixes):
                lines.pop(0)
                
                return "\n".join(lines).strip()
                
        except Exception as e:
            logger.error(f"📖 Section generation failed ({section_name}): {e}")
            return f"[Section {section_name} generation failed]"
    
    async def compile_mission(
        self,
        mission_data: Dict,
        player_name: str = "Unknown Adventurer",
    ) -> Optional[Path]:
        """
        Compile a mission dict into a full .docx module.
        
        Args:
            mission_data: Mission JSON dict (from MissionJsonBuilder or loaded from file)
            player_name: Name of player who claimed the mission
        
        Returns:
            Path to generated .docx, or None on failure
        """
        title = mission_data.get("metadata", {}).get("title", "Unknown Mission")
        mission_type = mission_data.get("metadata", {}).get("mission_type", "standard")
        
        logger.info(f"📖 Starting mission compilation: {title}")
        logger.info(f"📖 Mission type: {mission_type}, Player: {player_name}")
        
        # Mark Ollama busy
        mark_busy(f"compiling module: {title}")
        
        try:
            # Load skills and campaign context
            skill_context = self._build_skill_context(mission_type)
            campaign_context = await self._load_campaign_context()
            
            logger.info(f"📖 Loaded {len(skill_context)} chars of skill context")
            
            # Generate sections
            sections = {}
            accumulated = ""
            
            for section in ["overview", "act_1", "act_2", "act_3", "rewards"]:
                logger.info(f"📖 Generating section: {section}")
                content = await self._generate_section(
                    section,
                    mission_data,
                    skill_context,
                    campaign_context,
                    accumulated,
                )
                sections[section] = content
                accumulated += f"\n\n### {section.upper()}\n{content}"
                logger.info(f"📖 Section {section}: {len(content)} chars")
            
            # Combine for agent enhancement
            full_content = accumulated
            
            # Agent pass 0: ProAuthor (narrative transformation) - RUNS FIRST
            logger.info("📖 Agent pass: ProAuthor (narrative transformation)")
            pro_author = self.agents["pro_author"]
            enhanced, author_feedback = await pro_author.transform_to_narrative(
                mission_data, full_content, campaign_context
            )
            if author_feedback["success"]:
                full_content = enhanced
                logger.info(f"📖 ProAuthor enhanced: {author_feedback['enhancement_ratio']:.1%} ratio")
            
            # Agent pass 1: Mechanics
            logger.info("📖 Agent pass: DNDExpert (mechanics)")
            enhanced, mech_feedback = await self._agent_enhance_mechanics(
                full_content, mission_data, skill_context
            )
            if mech_feedback["success"]:
                full_content = enhanced
            
            # DNDExpert: Generate creature appendix
            logger.info("📖 Generating creature appendix...")
            dnd_expert = self.agents["dnd_expert"]
            cr = mission_data.get("metadata", {}).get("cr", 6)
            tier = mission_data.get("metadata", {}).get("tier", "standard")
            creature_appendix = await dnd_expert.generate_creature_appendix(
                full_content, cr, tier
            )
            
            # Agent pass 2: Narrative
            logger.info("📖 Agent pass: DNDVeteran (narrative)")
            enhanced, narr_feedback = await self._agent_enhance_narrative(
                full_content, mission_data, campaign_context, skill_context
            )
            if narr_feedback["success"]:
                full_content = enhanced
            
            # DNDVeteran: Generate location appendix (includes rumors, charts)
            logger.info("📖 Generating location appendix...")
            dnd_veteran = self.agents["dnd_veteran"]
            faction = mission_data.get("metadata", {}).get("faction", "Unknown")
            location_appendix, location_names = await dnd_veteran.generate_location_appendix(
                full_content, faction, tier
            )
            logger.info(f"📖 Extracted {len(location_names)} locations for map generation")
            
            # Agent pass 3: Quality check
            logger.info("📖 Agent pass: AICritic (quality)")
            quality = await self._agent_quality_check(full_content, mission_data)
            logger.info(f"📖 Quality score: {quality['score']}/10")
            
            # Append appendices to content
            full_content_with_appendices = full_content + creature_appendix + location_appendix
            
            # Build docx data
            # Split content back into sections for docx builder
            docx_data = format_module_for_docx(
                title=title,
                overview=sections.get("overview", ""),
                acts_1_2=sections.get("act_1", "") + "\n\n" + sections.get("act_2", ""),
                acts_3_4=sections.get("act_3", ""),
                act_5_rewards=sections.get("rewards", "") + creature_appendix + location_appendix,
                metadata=mission_data.get("metadata", {}),
            )
            
            # Add compilation metadata
            docx_data["compilation"] = {
                "compiled_at": datetime.now().isoformat(),
                "player_name": player_name,
                "quality_score": quality["score"],
                "agents_used": ["ProAuthor", "DNDExpert", "DNDVeteran", "AICritic"],
                "skills_used": self._get_skills_for_mission(mission_type),
                "location_names": location_names,  # For map generation
            }
            
            # Build docx
            logger.info("📖 Building .docx file")
            safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
            safe_title = safe_title.replace(" ", "_")[:50]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"MODULE_{safe_title}_{timestamp}"
            
            docx_path = await build_docx(docx_data, filename)
            
            if docx_path and docx_path.exists():
                logger.info(f"📖 Module compiled: {docx_path}")
                
                # Generate VTT maps for locations from appendix
                if location_names:
                    try:
                        from src.mission_builder.maps import generate_module_maps
                        _map_module_data = {
                            "title": title,
                            "sections": {
                                "acts_1_2": sections.get("act_1", "") + "\n\n" + sections.get("act_2", ""),
                                "acts_3_4": sections.get("act_3", ""),
                            },
                            "metadata": mission_data.get("metadata", {}),
                        }
                        map_paths = await generate_module_maps(
                            _map_module_data, output_subdir=safe_title, max_maps=4
                        )
                        if map_paths:
                            logger.info(f"📖 Generated {len(map_paths)} VTT maps")
                            docx_data["map_paths"] = [str(p) for p in map_paths]
                    except Exception as e:
                        logger.warning(f"📖 Map generation failed (non-fatal): {e}")
                
                # Save JSON to completed
                json_path = COMPLETED_DIR / f"{filename}.json"
                mission_data["compilation"] = docx_data.get("compilation", {})
                json_path.write_text(json.dumps(mission_data, indent=2), encoding="utf-8")
                
                return docx_path
            else:
                logger.error("📖 DOCX build failed")
                return None
            
        except Exception as e:
            logger.exception(f"📖 Compilation error: {e}")
            return None
        finally:
            mark_available()
    
    async def compile_and_post(
        self,
        mission_data: Dict,
        player_name: str = "Unknown Adventurer",
        client=None,
    ) -> Optional[Path]:
        """
        Compile a mission and post the result to Discord.
        
        Args:
            mission_data: Mission JSON dict
            player_name: Name of player who claimed the mission
            client: Discord client (uses self.client if not provided)
        
        Returns:
            Path to generated .docx, or None on failure
        """
        import discord
        
        client = client or self.client
        if not client:
            logger.error("📖 No Discord client available for posting")
            return await self.compile_mission(mission_data, player_name)
        
        docx_path = await self.compile_mission(mission_data, player_name)
        
        if not docx_path:
            # Notify DM of failure
            try:
                dm_id = int(os.getenv("DM_USER_ID", 0))
                if dm_id:
                    dm_user = await client.fetch_user(dm_id)
                    title = mission_data.get("metadata", {}).get("title", "Unknown")
                    await dm_user.send(
                        f"❌ **Module compilation failed** for *{title}* (claimed by {player_name})."
                    )
            except Exception:
                pass
            return None
        
        # Post to Discord
        channel = client.get_channel(MODULE_CHANNEL_ID)
        if not channel:
            logger.warning(f"📖 Module channel {MODULE_CHANNEL_ID} not found")
            # Try DM fallback
            try:
                dm_id = int(os.getenv("DM_USER_ID", 0))
                if dm_id:
                    channel = await client.fetch_user(dm_id)
            except Exception:
                pass
        
        if channel:
            try:
                title = mission_data.get("metadata", {}).get("title", "Unknown")
                faction = mission_data.get("metadata", {}).get("faction", "Unknown")
                tier = mission_data.get("metadata", {}).get("tier", "standard").upper()
                cr = mission_data.get("metadata", {}).get("cr", 6)
                mission_type = mission_data.get("metadata", {}).get("mission_type", "standard")
                
                file_size = docx_path.stat().st_size
                
                embed = discord.Embed(
                    title=f"📖 Mission Module: {title}",
                    description=(
                        f"**Claimed by:** {player_name}\n"
                        f"**Faction:** {faction} | **Tier:** {tier} | **CR:** {cr}\n"
                        f"**Type:** {mission_type}\n"
                        f"**File:** {docx_path.name} ({file_size // 1024}KB)\n\n"
                        f"*Full D&D 5e 2024 adventure module compiled with agent enhancement.*"
                    ),
                    color=discord.Color.dark_gold(),
                )
                embed.set_footer(text="Tower of Last Chance — Agent-Compiled Module")
                
                file = discord.File(str(docx_path), filename=docx_path.name)
                await channel.send(embed=embed, file=file)
                logger.info(f"📖 Module posted to channel: {title}")
                
            except Exception as e:
                logger.error(f"📖 Failed to post module: {e}")
        
        return docx_path
    
    async def compile_from_json_file(
        self,
        json_path: Path,
        player_name: str = "Unknown Adventurer",
        client=None,
    ) -> Optional[Path]:
        """
        Load a mission JSON file and compile it.
        
        Args:
            json_path: Path to mission JSON file
            player_name: Name of player
            client: Discord client
        
        Returns:
            Path to generated .docx
        """
        try:
            mission_data = json.loads(json_path.read_text(encoding="utf-8"))
            return await self.compile_and_post(mission_data, player_name, client)
        except Exception as e:
            logger.error(f"📖 Failed to load JSON {json_path}: {e}")
            return None


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

async def compile_mission(
    mission_dict: Dict,
    player_name: str,
    client=None,
) -> Optional[Path]:
    """
    Convenience function to compile a mission.
    
    Usage:
        from src.mission_compiler import compile_mission
        docx_path = await compile_mission(mission, player_name, client)
    """
    compiler = MissionCompiler(client)
    return await compiler.compile_and_post(mission_dict, player_name, client)


def build_mission_json(
    title: str,
    faction: str,
    tier: str,
    mission_type: str = "standard",
    **kwargs
) -> Dict:
    """
    Build a minimal mission JSON dict for compilation.
    
    Usage:
        mission = build_mission_json(
            title="The Silent Vault",
            faction="Glass Sigil",
            tier="high-stakes",
            cr=9,
            party_level=8,
        )
        docx_path = await compile_mission(mission, "PlayerName", client)
    """
    builder = MissionJsonBuilder(
        title=title,
        faction=faction,
        tier=tier,
        mission_type=mission_type,
        **kwargs
    )
    return builder.build(validate=False)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "MissionCompiler",
    "compile_mission",
    "build_mission_json",
    "MODULE_CHANNEL_ID",
]
