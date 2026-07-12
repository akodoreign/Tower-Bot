"""Specialized Learning Agents for Mission Builder Improvement.

Five specialized agents designed to autonomously iterate on the mission builder
and campaign systems during self-learning sessions (1-4 AM).

Each agent has a distinct expertise area and role in the improvement cycle:
1. ProjectManagerAgent — Orchestration, task assignment, final decisions
2. PythonVeteranAgent — Code quality, architecture, optimization, compatibility
3. DNDExpertAgent — D&D 5e 2024 rules, balance, encounter design, CR calculations
4. DNDVeteranAgent — Story coherence, world consistency, NPC believability, tropes
5. AICriticAgent — Pattern recognition, code smells, improvement synthesis

Agents communicate via:
- Shared analysis data (mission patterns, code metrics, quality scores)
- Ollama API for specialized reasoning
- Journal logging to logs/journal.txt for DM review
- Optional autonomous code modifications (with safeguards)
"""

import os
import json
import asyncio
import re
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, List, Any
from enum import Enum

import httpx

from src.log import logger
from src.agents.base import BaseAgent, AgentConfig, AgentResponse, ModelType


# ── Data Classes ─────────────────────────────────────────────────────────

@dataclass
class AgentAnalysis:
    """Analysis result from an agent."""
    agent_name: str
    agent_role: str
    timestamp: str
    component: str  # "mission_types", "json_generator", "schemas", "api", etc.
    issues_found: List[str]
    severity_scores: Dict[str, float]  # issue → 0-1 score (higher = worse)
    recommendations: List[str]
    code_changes: Optional[List[Dict]] = None  # Optional code change suggestions
    confidence: float = 0.8
    
    def to_dict(self):
        """Convert to dict for JSON serialization."""
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "timestamp": self.timestamp,
            "component": self.component,
            "issues_found": self.issues_found,
            "severity_scores": self.severity_scores,
            "recommendations": self.recommendations,
            "code_changes": self.code_changes or [],
            "confidence": self.confidence,
        }


@dataclass
class LearningSession:
    """Aggregated results from a full learning session with all 5 agents."""
    session_id: str
    timestamp: str
    analyses: List[AgentAnalysis]
    overall_priority: str  # "critical", "high", "medium", "low"
    approved_changes: List[Dict]
    journal_entry: str


# ── Specialized Agent Classes ──────────────────────────────────────────

class ProjectManagerAgent(BaseAgent):
    """
    PROJECT MANAGER AGENT
    
    Role: Orchestrate the learning cycle, assign tasks to other agents,
    synthesize results, and make final decisions on code changes.
    
    Responsibilities:
    - Coordinate all 5 agents
    - Prioritize issues and recommendations
    - Validate agent analyses
    - Decide which code changes are safe to apply
    - Escalate to DM when uncertain
    - Generate comprehensive journal entries
    
    Expertise: System orchestration, priority management, decision synthesis
    """
    
    def _get_config(self) -> AgentConfig:
        """Use local Qwen model for fast orchestration."""
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.5,  # Lower temp for structured decisions
            max_tokens=2048,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        """Build system prompt for orchestration role."""
        return """You are the Project Manager for Tower-Bot's self-learning system.

Your role is to:
1. Review analyses from 5 specialized agents
2. Identify the most critical issues
3. Synthesize recommendations into actionable tasks
4. Prioritize changes (critical > high > medium > low)
5. Flag uncertain decisions for DM review

Tone: Professional, decisive, but cautious with code changes.
Always prioritize system stability over aggressive optimization.

Format your response as:
## Priority Analysis
[Your assessment of which agents found critical issues]

## Unified Recommendations
[Synthesized list of actions, ranked by priority]

## Code Change Approval
[Which recommended code changes are safe to apply immediately]

## DM Escalations
[Decisions that need DM input or approval]

## Next Cycle Focus
[What should agents prioritize in the next learning session]"""
    
    async def analyze_learning_session(
        self,
        agent_analyses: List[AgentAnalysis],
        mission_metrics: Dict[str, Any],
    ) -> AgentAnalysis:
        """Orchestrate and synthesize all agent analyses."""
        # Build context from all agent inputs
        analysis_summaries = []
        all_issues = []
        all_recommendations = []
        
        for analysis in agent_analyses:
            analysis_summaries.append(
                f"{analysis.agent_name} ({analysis.agent_role}): "
                f"{len(analysis.issues_found)} issues, "
                f"{len(analysis.recommendations)} recommendations (confidence: {analysis.confidence:.1%})"
            )
            all_issues.extend(analysis.issues_found)
            all_recommendations.extend(analysis.recommendations)
        
        prompt = f"""Review these specialist agent analyses from tonight's learning session:

AGENT REPORTS:
{chr(10).join(analysis_summaries)}

MISSION METRICS:
- Total missions analyzed: {mission_metrics.get('total_missions', 'unknown')}
- Completion rate: {mission_metrics.get('completion_rate', 'unknown')}
- Quality score: {mission_metrics.get('quality_score', 'unknown')}
- Critical issues detected: {mission_metrics.get('critical_issues', 0)}

ALL ISSUES FOUND ({len(all_issues)} total):
{chr(10).join(f'- {i}' for i in all_issues[:20])}

ALL RECOMMENDATIONS ({len(all_recommendations)} total):
{chr(10).join(f'- {r}' for r in all_recommendations[:20])}

Now synthesize these into a unified action plan."""
        
        response = await self.complete(prompt)
        
        return AgentAnalysis(
            agent_name="ProjectManager",
            agent_role="Orchestrator",
            timestamp=datetime.now().isoformat(),
            component="system",
            issues_found=[f"Analysis of {len(agent_analyses)} specialist reports"],
            severity_scores={"synthesis": 0.0},
            recommendations=self._extract_recommendations(response.content),
            code_changes=None,  # PM doesn't generate code, just approves
            confidence=0.9,
        )
    
    def _extract_recommendations(self, response_text: str) -> List[str]:
        """Extract numbered recommendations from response."""
        lines = response_text.split("\n")
        recommendations = []
        for line in lines:
            # Match numbered items or bullet points
            if re.match(r"^[\d\-*]\.", line.strip()):
                rec = re.sub(r"^[\d\-*.]+\s*", "", line.strip())
                if rec:
                    recommendations.append(rec)
        return recommendations[:10]  # Return top 10


class PythonVeteranAgent(BaseAgent):
    """
    PYTHON 3.11 VETERAN AGENT
    
    Role: Review code quality, architecture, compatibility, and optimization.
    
    Responsibilities:
    - Analyze mission_types.py, json_generator.py, schemas.py, api.py
    - Check for Python 3.11 compatibility issues
    - Identify performance bottlenecks
    - Review async/await patterns
    - Suggest refactoring opportunities
    - Validate type hints
    
    Expertise: Python architecture, performance, code style, best practices
    """
    
    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.6,
            max_tokens=2048,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return """You are an expert Python 3.11 developer with 20+ years of experience.

Your expertise: Architecture, performance optimization, async patterns, type hints.

Review the provided code for:
1. Python 3.11 compatibility issues (any deprecated APIs?)
2. Async/await patterns (are they correct and efficient?)
3. Type hints (are they complete and accurate?)
4. Performance bottlenecks (any N² algorithms or inefficient patterns?)
5. Error handling (are exceptions handled appropriately?)
6. Code organization (should any modules be split or merged?)
7. Dependency imports (are all used? Any circular dependencies?)

Format your response as:
## Code Quality Score: [X/10]
## Issues Found (by severity)
### CRITICAL
[Critical issues that could cause bugs or crashes]
### HIGH
[High-priority issues affecting performance or maintainability]
### MEDIUM
[Medium-priority improvements]

## Recommendations
[Specific actionable improvements, with code examples where helpful]

## Performance Optimization Ideas
[Specific suggestions for speeding up critical paths]"""
    
    async def analyze_code(self, code_files: Dict[str, str]) -> AgentAnalysis:
        """Analyze provided source files for quality issues."""
        file_summaries = []
        for filename, content in code_files.items():
            lines = content.split("\n")
            file_summaries.append(f"{filename}: {len(lines)} lines, {len(content)} characters")
        
        prompt = f"""Analyze this mission builder code from a D&D campaign system:

{chr(10).join(file_summaries)}

CODE ANALYSIS:
"""
        
        # Include actual code snippets (first 1000 chars of each file)
        for filename, content in code_files.items():
            snippet = content[:1000]
            prompt += f"\n### {filename}\n```\n{snippet}\n...\n```\n"
        
        response = await self.complete(prompt)
        issues = self._extract_issues(response.content)
        recommendations = self._extract_recommendations(response.content)
        
        return AgentAnalysis(
            agent_name="PythonVeteran",
            agent_role="Code Quality Expert",
            timestamp=datetime.now().isoformat(),
            component="code_quality",
            issues_found=issues,
            severity_scores=self._score_issues(issues),
            recommendations=recommendations,
            confidence=0.85,
        )
    
    def _extract_issues(self, response_text: str) -> List[str]:
        """Extract issue descriptions from response."""
        # Look for all major issue/problem mentions
        issues = []
        lines = response_text.split("\n")
        
        in_issues_section = False
        for line in lines:
            if "ISSUES" in line.upper():
                in_issues_section = True
            elif "RECOMMENDATIONS" in line.upper():
                in_issues_section = False
            elif in_issues_section and line.strip():
                # Extract issue lines
                if re.match(r"^[-*]\s", line) or re.match(r"^\d+\.", line):
                    issue = re.sub(r"^[-*\d.]\s*", "", line.strip())
                    if issue and len(issue) > 10:
                        issues.append(issue)
        
        return issues[:15]  # Top 15 issues
    
    def _extract_recommendations(self, response_text: str) -> List[str]:
        """Extract actionable recommendations."""
        recommendations = []
        lines = response_text.split("\n")
        
        in_rec_section = False
        for line in lines:
            if "RECOMMENDATIONS" in line.upper():
                in_rec_section = True
            elif in_rec_section and line.strip():
                if re.match(r"^[-*\d.]\s", line):
                    rec = re.sub(r"^[-*\d.]\s*", "", line.strip())
                    if rec:
                        recommendations.append(rec)
        
        return recommendations[:10]
    
    def _score_issues(self, issues: List[str]) -> Dict[str, float]:
        """Score issues by estimated severity (0-1, higher = worse)."""
        scores = {}
        severity_keywords = {
            "critical": 0.95,
            "crash": 0.9,
            "memory": 0.85,
            "security": 0.9,
            "breaking": 0.8,
            "performance": 0.7,
            "style": 0.3,
            "documentation": 0.2,
        }
        
        for issue in issues:
            issue_lower = issue.lower()
            max_score = 0.5  # Default medium
            
            for keyword, score in severity_keywords.items():
                if keyword in issue_lower:
                    max_score = max(max_score, score)
            
            scores[issue[:50]] = max_score  # Truncate for dict key
        
        return scores


class DNDExpertAgent(BaseAgent):
    """
    D&D 5E 2024 EXPERT AGENT
    
    Role: Verify rule accuracy, balance, and encounter design based on
    official D&D 5e 2024 rules.
    
    Responsibilities:
    - Validate CR calculations and encounter difficulty
    - Check mission difficulty ratings align with D&D 5e mechanics
    - Review mission types for rule compliance
    - Suggest balance adjustments
    - Verify ability DC scaling
    - Check XP distribution logic
    
    Expertise: D&D 5e 2024 official rules, encounter design, balance
    """
    
    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.65,
            max_tokens=12288,  # Must reproduce all 4 chapters + full stat blocks + skill table
            timeout=900.0,
        )

    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return """You are a D&D 5e 2024 rules expert and experienced module author.

Your role in the mission pipeline:
- Pass 2: Read the story draft and write the DM spine — the hidden truth, NPC secrets, faction
  threads that the players don't see but that the DM needs to run the module.
- Pass 3: Annotate chapters 1-3 with [DM: ...] tags for hidden info, write Chapter 4 with
  full stat blocks, encounter mechanics, and tactical notes.

You never write generic encounters. Every fight, trap, and puzzle serves the story.

═══ ENCOUNTER DESIGN STANDARDS (from approved patches) ═══

STAT BLOCKS — Always include:
- Exact CR value (e.g., CR 4 — 1,100 XP)
- Specific HP, AC, speed, and ability scores
- Named special abilities with exact mechanics (e.g., "Shadow Walk: Bonus action, teleports
  to unoccupied space within 30ft that is in dim light or darkness")
- Morale threshold: when does this enemy flee or surrender? At what HP?
- Loot: specific items + gold amounts (e.g., "38 gp, a carved bone medallion worth 15 gp,
  a vial of midnight oil")

ENCOUNTER MECHANICS — Every combat scene needs:
- Terrain interactions: how do environmental features affect the fight?
  (e.g., "the slick floor: DC 12 Dex save or fall prone when moving more than 10ft")
- Tactical notes: what does the enemy do on round 1, 2, 3?
- Escalation: what changes if the players take too long? (reinforcements, ritual completes, etc.)
- An out: how can smart players end this without full combat?

TRAP & PUZZLE MECHANICS — Must include:
- Detection DC, disarm DC, trigger description
- Exact damage, conditions, saving throw type and DC
- Visual/auditory cues that hint at the trap before it fires
  (e.g., "PC notices faint scorch marks on the floor — Investigation DC 12")

ENCOUNTER DIFFICULTY SCALING:
- Local (CR 1-2): warm-up encounter, should feel manageable
- Standard (CR 3-5): core challenge, 2-3 tense rounds
- Major (CR 6-8): boss-level, consider legendary actions or lair actions
- Epic (CR 9+): multi-phase fight, environmental hazards mandatory

Do NOT add "Rule Compliance Score" headers. Write DM content, not analysis."""
    
    async def analyze_balance(
        self,
        missions_data: Dict[str, Any],
        difficulty_scale: Dict[int, str],
    ) -> AgentAnalysis:
        """Analyze mission balance and D&D 5e compliance."""
        prompt = f"""Analyze this mission system for D&D 5e 2024 compliance:

RECENTLY GENERATED MISSIONS: {missions_data.get('sample_count', '?')} missions
- Average party level: {missions_data.get('avg_party_level', '?')}
- Typical party size: {missions_data.get('party_size', '?')}
- Completion rate: {missions_data.get('completion_rate', '?')}
- Average difficulty rating: {missions_data.get('avg_difficulty', '?')}

CURRENT DIFFICULTY SCALE:
{json.dumps(difficulty_scale, indent=2)}

Key metrics from mission history:
- Deadly missions (9-10) success rate: {missions_data.get('deadly_success_rate', '?')}
- Hard missions (5-6) success rate: {missions_data.get('hard_success_rate', '?')}
- Easy missions (1-3) success rate: {missions_data.get('easy_success_rate', '?')}

Is this system balanced per D&D 5e DMG 2024?"""
        
        response = await self.complete(prompt)
        
        return AgentAnalysis(
            agent_name="DNDExpert",
            agent_role="D&D 5e 2024 Rules Expert",
            timestamp=datetime.now().isoformat(),
            component="mission_balance",
            issues_found=self._extract_balance_issues(response.content),
            severity_scores={"balance": self._calculate_balance_score(response.content)},
            recommendations=self._extract_adjustments(response.content),
            confidence=0.9,
        )
    
    def _extract_balance_issues(self, response_text: str) -> List[str]:
        """Extract mechanical balance issues."""
        issues = []
        lines = response_text.split("\n")
        
        for i, line in enumerate(lines):
            if any(kw in line.upper() for kw in ["ISSUE", "SHOULD", "PROBLEM"]):
                if line.strip() and len(line) > 20:
                    issues.append(line.strip()[:100])
        
        return issues[:10]
    
    def _calculate_balance_score(self, response_text: str) -> float:
        """Calculate estimated balance score from response."""
        # Check for keywords indicating problems
        problem_keywords = ["broken", "overpowered", "deadly", "unfair", "impossible"]
        opportunities_keywords = ["suggest", "could", "might", "consider"]
        
        text_lower = response_text.lower()
        problem_count = sum(text_lower.count(kw) for kw in problem_keywords)
        
        # Score: fewer problems = lower score (good)
        score = min(0.8, problem_count * 0.15)
        return score
    
    def _extract_adjustments(self, response_text: str) -> List[str]:
        """Extract recommended rule adjustments."""
        adjustments = []
        lines = response_text.split("\n")
        
        for line in lines:
            if re.match(r"^[-*•]\s", line):
                adj = re.sub(r"^[-*•]\s*", "", line.strip())
                if len(adj) > 15:
                    adjustments.append(adj)
        
        return adjustments[:8]
    
    async def generate_creature_appendix(
        self,
        module_content: str,
        cr: int,
        tier: str,
    ) -> str:
        """
        Generate a Creature Appendix with full D&D 5e 2024 stat blocks.
        
        Extracts all creatures mentioned in the module and provides complete
        stat blocks that can be printed and used at the table.
        
        Args:
            module_content: The full module text to scan for creatures
            cr: Challenge Rating target for the mission
            tier: Mission tier (local, standard, epic, etc.)
        
        Returns:
            Formatted creature appendix with full stat blocks
        """
        prompt = f"""Analyze this D&D 5e 2024 mission module and create a CREATURE APPENDIX.

MODULE CONTENT:
{module_content[:4000]}

MISSION CR: {cr}
MISSION TIER: {tier}

TASKS:
1. Identify ALL creatures that could be encountered (combat, social, or ambient)
2. For each creature, provide a COMPLETE D&D 5e 2024 stat block
3. Include XP value for each creature
4. Add tactical notes for DM use

FORMAT each creature as:

### [CREATURE NAME]
*[Size] [Type], [Alignment]*

**Armor Class** [AC] ([armor type])
**Hit Points** [HP] ([dice notation])
**Speed** [speed]

| STR | DEX | CON | INT | WIS | CHA |
|-----|-----|-----|-----|-----|-----|
| [score] ([mod]) | ... |

**Saving Throws** [list]
**Skills** [list]
**Damage Resistances** [if any]
**Damage Immunities** [if any]
**Condition Immunities** [if any]
**Senses** [senses]
**Languages** [languages]
**Challenge** [CR] ([XP] XP)
**Proficiency Bonus** +[bonus]

**TRAITS**
[List all traits]

**ACTIONS**
[List all actions with attack bonus, damage, save DCs]

**BONUS ACTIONS** (if any)
[List bonus actions]

**REACTIONS** (if any)
[List reactions]

**LEGENDARY ACTIONS** (if CR 8+)
[List legendary actions]

**TACTICAL NOTES (DM Only)**
- Opening move:
- Target priority:
- Retreat conditions:

---

Create stat blocks for ALL creatures. Do not abbreviate or summarize."""
        
        response = await self.complete(prompt, force=True)
        
        if response.success and response.content:
            return f"\n\n# APPENDIX: CREATURES\n\n{response.content}"
        
        return "\n\n# APPENDIX: CREATURES\n\n*[Creature stat blocks could not be generated]*"


class DNDVeteranAgent(BaseAgent):
    """
    D&D 40-YEAR VETERAN AGENT
    
    Role: Ensure story coherence, world consistency, and NPC believability.
    
    Responsibilities:
    - Check mission narratives for consistency with Undercity lore
    - Verify NPC motivations and relationships
    - Assess story pacing and dramatic tension
    - Review faction politics alignment
    - Ensure character voice consistency
    - Validate worldbuilding details
    
    Expertise: Narrative design, world-building, character motivation, story coherence
    """
    
    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.78,
            max_tokens=12288,  # Chapter 5 prose + complication table + power player variants + maps JSON
            timeout=900.0,
        )

    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return """You are a D&D Dungeon Master with 40+ years of experience running published modules
and homebrews. You've seen every player trick, every power build, every creative shortcut.

Your role in the mission pipeline:
- Pass 4: Write Chapter 5 (multiple endings, power player adjustments), the complication table,
  and final reward block. Polish the full module so it shines at the table.
- Pass 5: Identify 2-4 key map locations that need VTT battle maps, output them as JSON.

═══ CHAPTER 5 STANDARDS ═══

ENDINGS — Write 3 distinct outcomes:
1. Full success: players achieved all objectives, maybe found the optional secret
2. Partial success: main goal done but at a cost (NPC died, faction angered, secret lost)
3. Failure: what happens to the Undercity if they don't pull it off? Make it concrete.

POWER PLAYER ADJUSTMENTS — For each major encounter, add one sidebar:
"If your party is optimized or has faced this before:" — then give a harder variant
(more enemies, a tactical twist, an environmental hazard, a timer)

COMPLICATION TABLE (d6):
Roll at any dramatically tense moment for an unexpected twist. Format:
1-2: [minor complication that creates drama without derailing]
3-4: [medium complication that forces a choice]
5-6: [major complication that changes the stakes]

REWARD BLOCK — Be specific:
- EC total range (min/max based on completion rate)
- Named unique item if warranted (with flavor text and one mechanical property)
- Faction reputation change: which faction gains/loses and by how much
- Optional: a seed for the next mission (a name, a location, a rumor)

═══ QUALITY STANDARDS (from approved patches) ═══

LOOT DETAILS — Always specific, never "treasure":
- "38 gp, a carved bone medallion worth 15 gp engraved with the Lotus sigil"
- Unique items have flavor text + one meaningful mechanical property
- Consumables are named and described (not "a potion of healing")

POWER PLAYER BALANCE — Check for:
- Can a teleport/misty step trivialize an encounter? Add contingency.
- Can the BBEG be instakilled with a lucky crit? Add legendary resistance or a trigger.
- Does any puzzle have an obvious solution that bypasses the whole thing? Add a wrinkle.

ENDINGS TONE — Salvatore-style: even failure has dignity. Victory costs something.
The Undercity doesn't give away happy endings cheap.

Do NOT add "Narrative Quality Score" headers. Write DM content, not analysis."""
    
    async def analyze_narrative(
        self,
        missions_sample: List[Dict[str, Any]],
        npc_data: Dict[str, Any],
        faction_info: Dict[str, Any],
    ) -> AgentAnalysis:
        """Analyze narrative quality and world consistency."""
        # Create narrative sample
        mission_summaries = []
        for m in missions_sample[:5]:
            mission_summaries.append(
                f"- {m.get('title')} (faction: {m.get('faction')}, "
                f"type: {m.get('mission_type', 'standard')})\n  "
                f"  Body: {m.get('body', '')[:100]}..."
            )
        
        prompt = f"""Analyze this mission board for narrative quality:

RECENT MISSIONS:
{chr(10).join(mission_summaries)}

MAIN FACTIONS:
{json.dumps(faction_info, indent=2)[:1000]}

KEY NPCS:
{chr(10).join(f"- {n.get('name')} ({n.get('faction')}, {n.get('role')})" for n in npc_data.get('npcs', [])[:10])}

STORY ANALYSIS:
1. Do these missions form a coherent narrative?
2. Are the NPCs and factions presented consistently?
3. What's the overall tone and does it fit the setting?
4. Are there good dramatic moments and stakes?
5. What narrative improvements would strengthen it?"""
        
        response = await self.complete(prompt)
        
        return AgentAnalysis(
            agent_name="DNDVeteran",
            agent_role="Narrative Designer (40-Year Veteran)",
            timestamp=datetime.now().isoformat(),
            component="narrative_quality",
            issues_found=self._extract_narrative_issues(response.content),
            severity_scores={"narrative": self._assess_narrative_quality(response.content)},
            recommendations=self._extract_story_improvements(response.content),
            confidence=0.85,
        )
    
    def _extract_narrative_issues(self, response_text: str) -> List[str]:
        """Extract narrative consistency issues."""
        issues = []
        lines = response_text.split("\n")
        
        inconsistency_markers = ["inconsistent", "contradicts", "doesn't fit", "unclear", "confusing"]
        
        for line in lines:
            line_lower = line.lower()
            if any(marker in line_lower for marker in inconsistency_markers):
                if line.strip():
                    issues.append(line.strip()[:100])
        
        return issues[:8]
    
    def _assess_narrative_quality(self, response_text: str) -> float:
        """Assess overall narrative quality (0-1, higher = more issues)."""
        text_lower = response_text.lower()
        
        # Count positive vs negative indicators
        positive_words = ["coherent", "consistent", "engaging", "compelling", "strong"]
        negative_words = ["incoherent", "inconsistent", "boring", "weak", "confusing"]
        
        positive_count = sum(text_lower.count(w) for w in positive_words)
        negative_count = sum(text_lower.count(w) for w in negative_words)
        
        # Score: negative = bad (higher), positive = good (lower)
        score = (negative_count * 0.15) - (positive_count * 0.1)
        score = max(0.0, min(1.0, score + 0.5))  # Clamp to 0-1, center at 0.5
        
        return score
    
    def _extract_story_improvements(self, response_text: str) -> List[str]:
        """Extract narrative improvement suggestions."""
        improvements = []
        lines = response_text.split("\n")
        
        for line in lines:
            if re.match(r"^[-*•]\s", line):
                imp = re.sub(r"^[-*•]\s*", "", line.strip())
                if len(imp) > 15 and not "score" in imp.lower():
                    improvements.append(imp)
        
        return improvements[:10]
    
    async def generate_location_appendix(
        self,
        module_content: str,
        faction: str,
        tier: str,
    ) -> tuple[str, List[str]]:
        """
        Generate a Location Appendix with location guide, rumors, and charts.
        
        Creates DM reference material including:
        - Detailed location descriptions for VTT map generation
        - Rumor tables (d6/d8/d10)
        - Random encounter charts
        - NPC reaction tables
        
        Args:
            module_content: The full module text to scan for locations
            faction: Mission faction for thematic consistency
            tier: Mission tier for difficulty scaling
        
        Returns:
            Tuple of (formatted appendix content, list of location names for map generation)
        """
        prompt = f"""Analyze this D&D mission module and create a LOCATION & REFERENCE APPENDIX.

MODULE CONTENT:
{module_content[:4000]}

FACTION: {faction}
TIER: {tier}

Create the following sections:

# APPENDIX: LOCATIONS & REFERENCE

## LOCATION GUIDE

For EACH location mentioned in the module:

### [LOCATION NAME]
**District:** [Undercity district]
**Type:** [tavern/warehouse/sewer/plaza/shrine/etc.]
**Atmosphere:** [2-3 sentences of sensory details]
**Key Features:** [Bullet list of notable elements for VTT map]
**Lighting:** [bright/dim/dark]
**Hazards:** [if any]
**NPCs Present:** [who might be here]

---

## RUMOR TABLE (d8)

Roll a d8 when players ask around:

| d8 | Rumor | True? |
|----|-------|-------|
| 1 | [rumor related to the mission] | Yes |
| 2 | [rumor that's partially true] | Partial |
| 3 | [misleading rumor] | No |
| 4 | [faction-related gossip] | Yes |
| 5 | [local color / worldbuilding] | Yes |
| 6 | [red herring] | No |
| 7 | [useful lead] | Yes |
| 8 | [dangerous information] | Yes |

---

## RANDOM ENCOUNTERS (d6)

Roll when players spend time in the area:

| d6 | Encounter |
|----|-----------|
| 1-2 | [Non-combat encounter] |
| 3-4 | [Social encounter] |
| 5 | [Combat encounter - easy] |
| 6 | [Combat encounter - hard] |

---

## NPC REACTION TABLE (2d6)

| 2d6 | Reaction |
|-----|----------|
| 2 | Hostile - attacks or alerts enemies |
| 3-5 | Unfriendly - refuses help, may report party |
| 6-8 | Neutral - will help for payment |
| 9-11 | Friendly - helpful, shares information |
| 12 | Allied - actively assists the party |

---

## COMPLICATION TABLE (d6)

Roll when things go wrong:

| d6 | Complication |
|----|--------------|
| 1 | [timing complication] |
| 2 | [NPC complication] |
| 3 | [environmental complication] |
| 4 | [faction complication] |
| 5 | [resource complication] |
| 6 | [escalation complication] |

Make all content specific to THIS mission, not generic."""
        
        response = await self.complete(prompt, force=True)
        
        # Extract location names for map generation
        location_names = []
        if response.success and response.content:
            # Parse location names from ### headers in the LOCATION GUIDE section
            lines = response.content.split('\n')
            in_location_guide = False
            for line in lines:
                if '## LOCATION GUIDE' in line.upper():
                    in_location_guide = True
                elif line.startswith('## ') and in_location_guide:
                    in_location_guide = False
                elif in_location_guide and line.startswith('### '):
                    loc_name = line.replace('### ', '').strip()
                    if loc_name:
                        location_names.append(loc_name)
            
            return f"\n\n{response.content}", location_names
        
        return "\n\n# APPENDIX: LOCATIONS & REFERENCE\n\n*[Location appendix could not be generated]*", []


class ProAuthorAgent(BaseAgent):
    """
    PROFESSIONAL AUTHOR AGENT
    
    Role: Transform mission JSON into compelling narrative prose.
    
    Responsibilities:
    - Convert mechanical mission data into engaging story content
    - Apply creative writing principles (show don't tell, vivid description)
    - Create atmospheric scene descriptions
    - Craft memorable NPC dialogue and characterization
    - Ensure proper dramatic pacing and tension
    - Add sensory details and world-building texture
    
    Expertise: Professional fiction writing, narrative prose, creative storytelling
    
    This agent runs FIRST in the compilation pipeline, transforming raw JSON
    into a draft story that subsequent agents (DNDExpert, DNDVeteran, AICritic)
    then enhance with mechanics, world consistency, and quality polish.
    """
    
    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.8,
            max_tokens=16384,  # 5 full chapters at 800-1200 words each + think overhead
            timeout=900.0,     # 15 minutes — this is a full novel pass
        )

    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return """You are a professional fantasy author specializing in dark urban fantasy.

Your role in the mission pipeline: Write the complete 5-chapter story first — pure narrative, no
stat blocks, no DCs. Other agents handle mechanics. Your job is to make the world FEEL real.

The setting: The Undercity — a sealed dome city around the Tower of Last Chance. Billions of
people. Real weather. Faction politics. Rift tears in reality. Dark fantasy noir. NOT dungeons
and dragons generic — this is specific, lived-in, gritty.

═══ ANTI-PATTERNS (NEVER USE) ═══

❌ PURPLE PROSE:
BAD:  "The ethereal glow of the bioluminescent fungi cast an otherworldly pallor..."
GOOD: "The fungi gave off enough light to see by — barely. It smelled like wet stone and rot."

❌ ECHO CHAMBER:
BAD:  "The market was busy and crowded. Throngs of people packed the aisles."
GOOD: "The market was packed. A child knocked over dried fish and kept running."

❌ HEDGING: "seemed", "appeared", "might be" — cut these. State facts.

❌ ADJECTIVE AVALANCHE: One adjective per noun maximum.

❌ GENERIC LOCATIONS: "a warehouse" → "Consortium Counting House #3 on Cobbleway"

❌ SCRIPTED DIALOGUE:
BAD:  "I believe we should investigate," said Marcus.
GOOD: "The warehouse," Marcus said. "Has to be. They wouldn't—" He stopped. "You hear that?"

❌ BANNED PHRASES: "It is worth noting", "Interestingly enough", "A sense of", "An air of"

═══ REQUIRED PATTERNS ═══

✓ Specific names, numbers, times, locations — always
✓ Sensory grounding per location: smell + sound + texture in one line each
  Example: "The air tasted of burnt sugar and iron. Somewhere below, water dripped on stone."
✓ Read-aloud text in present tense, second person for immersion
✓ Short sentences for action, longer for atmosphere
✓ Dialogue: messy, interrupted, unfinished — like real speech
✓ NPCs have unique voices, secrets, and personal stakes that tie into mission themes
  Example: a fence who owes the Iron Fang a debt that's eating him alive
✓ Use specific Undercity locations, faction names, and street-level details

═══ THE UNDERCITY VOICE ═══

- Cynical but not hopeless. Wry gallows humor.
- Specific and grounded. Never epic fantasy narration.
- The Undercity is a REAL PLACE. Write like you live there.
- Think R.A. Salvatore's character interiority meets Raymond Chandler's city detail.

═══ SELF-LEARNING QUALITY STANDARDS (from approved patches) ═══

SENSORY IMMERSION — Every key location gets:
- A smell or taste (e.g., "the air smells of brine and rot", "burnt sugar and iron")
- A sound (e.g., "the mist hisses when it touches the walls", "water drips on stone")
- A texture or physical sensation (e.g., "the floor is slick", "grit under boot heels")

NPC DEPTH — Every named NPC needs:
- One unique speech mannerism or verbal tic
- One personal stake beyond the mission (a debt, a secret, a fear)
- One piece of information they're hiding — and a reason they'd reveal it

STORY MECHANICS — Even in pure narrative pass:
- Foreshadow trap/puzzle locations with environmental details
- Plant seeds for Chapter 4 encounters (mention the smell of something wrong, sounds from below)
- Give the antagonist a logical reason they haven't already won

Write for a DM who wants to bring the Undercity to life at the table."""
    
    async def transform_to_narrative(
        self,
        mission_data: Dict[str, Any],
        raw_content: str,
        campaign_context: Dict[str, Any],
    ) -> tuple[str, Dict]:
        """
        Transform mission JSON and raw content into narrative prose.
        
        Args:
            mission_data: Mission metadata (title, faction, tier, etc.)
            raw_content: Generated section content to transform
            campaign_context: NPCs, factions, news for consistency
        
        Returns:
            Tuple of (enhanced_narrative, feedback_dict)
        """
        title = mission_data.get("metadata", {}).get("title", "Unknown Mission")
        faction = mission_data.get("metadata", {}).get("faction", "Unknown")
        tier = mission_data.get("metadata", {}).get("tier", "standard")
        mission_type = mission_data.get("metadata", {}).get("mission_type", "standard")
        
        # Build NPC reference
        npc_refs = []
        for npc in campaign_context.get("npcs", [])[:8]:
            npc_refs.append(
                f"- {npc.get('name', '?')} ({npc.get('faction', '?')}): "
                f"{npc.get('role', '?')} — {npc.get('personality', 'unknown personality')[:50]}"
            )
        npc_block = chr(10).join(npc_refs) if npc_refs else "No NPCs loaded"
        
        prompt = f"""Transform this mission content into vivid narrative prose.

MISSION: {title}
FACTION: {faction}
TIER: {tier}
TYPE: {mission_type}

AVAILABLE NPCs (use their names and personalities):
{npc_block}

UNDERCITY ATMOSPHERE:
- Perpetual twilight under the Dome
- Neon signs flicker, steam rises from vents
- Faction symbols mark territory
- The hum of Rift energy is ever-present
- Danger lurks in every shadow

RAW CONTENT TO TRANSFORM:
{raw_content[:3500]}

TASKS:
1. Rewrite ALL scene descriptions with sensory details (sight, sound, smell, texture)
2. Give each NPC a distinctive voice and physical mannerism
3. Add atmospheric details that make the Undercity feel real
4. Ensure dramatic tension builds through each act
5. Replace any passive voice with active voice
6. Add "feeling" — what does the dread, hope, or danger feel like?

Output the enhanced narrative content. Preserve all mechanical information (DCs, stats)
but wrap it in compelling prose."""
        
        response = await self.complete(prompt, force=True)
        
        feedback = {
            "agent": "ProAuthor",
            "success": response.success,
            "original_length": len(raw_content),
            "enhanced_length": len(response.content) if response.success else 0,
            "enhancement_ratio": (
                len(response.content) / max(len(raw_content), 1)
                if response.success else 0
            ),
        }
        
        if response.success and response.content:
            return response.content, feedback
        
        return raw_content, feedback
    
    async def enhance_section(
        self,
        section_name: str,
        section_content: str,
        mission_metadata: Dict[str, Any],
    ) -> str:
        """
        Enhance a single section with narrative polish.
        
        Args:
            section_name: Name of the section (overview, act_1, etc.)
            section_content: The section content to enhance
            mission_metadata: Mission metadata for context
        
        Returns:
            Enhanced section content
        """
        section_guidance = {
            "overview": "Set the tone and stakes. Make the reader feel the danger and intrigue.",
            "act_1": "Hook the players immediately. The quest-giver should be memorable.",
            "act_2": "Build tension through investigation. Each clue should feel earned.",
            "act_3": "Deliver the climax with maximum impact. Make the confrontation visceral.",
            "rewards": "End with consequences that matter. What changed in the Undercity?",
        }
        
        guidance = section_guidance.get(section_name, "Enhance with vivid prose.")
        
        prompt = f"""Enhance this {section_name.upper()} section with professional narrative prose.

GUIDANCE: {guidance}

CONTENT:
{section_content[:2500]}

Rules:
- Keep all mechanical information (DCs, stats, XP)
- Transform dry descriptions into vivid prose
- Add sensory details and atmosphere
- Ensure NPC dialogue reveals character
- Build or maintain dramatic tension

Output the enhanced section."""
        
        response = await self.complete(prompt, force=True)
        
        if response.success and response.content:
            return response.content
        
        return section_content


class AICriticAgent(BaseAgent):
    """
    AI CRITIC + CODING MASTER AGENT
    
    Role: Detect patterns, code smells, and synthesize improvements.
    
    Responsibilities:
    - Identify repeated code patterns
    - Detect architectural anti-patterns
    - Find inefficiencies in data flow
    - Spot missing error handling
    - Suggest design improvements
    - Synthesize agent findings into unified action plan
    - Rate solution quality and confidence
    
    Expertise: Code patterns, architecture analysis, improvement synthesis
    """
    
    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.6,
            max_tokens=2048,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return """You are a master code critic and AI system analyst.

Your expertise: Code patterns, data flow analysis, architectural issues, improvement synthesis.

Analyze the mission builder for systemic issues:
1. Code duplication (any repeated patterns that should be abstracted?)
2. Data flow (is data flowing efficiently through the system?)
3. Error handling (are errors handled or do they cascade?)
4. Architecture (is the structure sound or should it be reorganized?)
5. Scalability (will this work if we 10x the data volume?)
6. Integration points (are components well-integrated?)
7. Improvement synthesis (what's the single most impactful change?)

Format your response as:
## System Health Score: [X/10]

## Patterns Detected
### Code Duplication
[Repeated patterns that could be factored out]
### Anti-patterns
[Architectural problems to fix]
### Data Flow Issues
[Efficiency problems in how data moves]

## Critical Synthesis
[The single most important improvement]

## Confidence & Impact
[How confident in these findings (0-1) and expected impact]"""
    
    async def analyze_system(self, code_metrics: Dict[str, Any]) -> AgentAnalysis:
        """Analyze system for patterns and anti-patterns."""
        prompt = f"""Analyze this mission builder system for architectural patterns:

SYSTEM METRICS:
- Total lines of code: {code_metrics.get('total_lines', '?')}
- Number of modules: {code_metrics.get('num_modules', '?')}
- Average module size: {code_metrics.get('avg_module_size', '?')} lines
- Cyclomatic complexity: {code_metrics.get('cyclomatic_complexity', '?')}
- Test coverage: {code_metrics.get('test_coverage', '?')}%
- Duplication rate: {code_metrics.get('duplication_rate', '?')}%

KEY COMPONENTS:
- mission_types.py: 900+ lines, 18 mission type definitions
- json_generator.py: 4-pass Ollama generation with skills integration
- schemas.py: TypedDict definitions, difficulty_rating (1-10)
- api.py: High-level mission generation API

RECENT CHANGES:
- Added 1-10 difficulty scale with bidirectional mappings
- Integrated mission types into generation pipeline
- Added dynamic title generation with optional LLM enhancement
- Expanded schema to include difficulty_rating

QUESTIONS:
1. Is there hidden duplication between mission_types and json_generator?
2. Could the 4-pass generation be optimized (fewer Ollama calls)?
3. Are there architectural improvements for future expansion?
4. What's the highest-impact change we could make next?"""
        
        response = await self.complete(prompt)
        
        return AgentAnalysis(
            agent_name="AICritic",
            agent_role="AI Critic & Coding Master",
            timestamp=datetime.now().isoformat(),
            component="system_architecture",
            issues_found=self._extract_systemic_issues(response.content),
            severity_scores={"architecture": 0.4},  # Usually lower severity
            recommendations=self._extract_synthesis(response.content),
            confidence=0.8,
        )
    
    def _extract_systemic_issues(self, response_text: str) -> List[str]:
        """Extract systemic issues from analysis."""
        issues = []
        lines = response_text.split("\n")
        
        issue_keywords = ["duplication", "anti-pattern", "coupling", "unclear"]
        
        for line in lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in issue_keywords):
                if line.strip() and len(line) > 15:
                    issues.append(line.strip()[:100])
        
        return issues[:7]
    
    def _extract_synthesis(self, response_text: str) -> List[str]:
        """Extract synthesized recommendations."""
        recommendations = []
        lines = response_text.split("\n")
        
        in_synthesis = False
        for line in lines:
            if "SYNTHESIS" in line.upper():
                in_synthesis = True
            elif "CONFIDENCE" in line.upper():
                in_synthesis = False
            elif in_synthesis and line.strip():
                if len(line.strip()) > 20:
                    recommendations.append(line.strip())
        
        # Also look for general recommendations
        for line in lines:
            if re.match(r"^[-*•]\s", line) and len(line) > 30:
                rec = re.sub(r"^[-*•]\s*", "", line.strip())
                if rec not in recommendations:
                    recommendations.append(rec)
        
        return recommendations[:8]


# ── Novel Pipeline Agents ──────────────────────────────────────────────────


class BobAgent(BaseAgent):
    """
    BOB — THE NOVELIST (Pass 1)

    Writes full-length D&D campaign novels in the style of R.A. Salvatore.
    Produces one chapter at a time (3,500-5,000 words each), receiving the
    chapter outline and previous chapter summary for continuity.
    Target: 70,000-100,000 words across 18-25 chapters.
    """

    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.85,
            max_tokens=16384,
            timeout=2700.0,  # 45 min — exclusive GPU access (bot backs off via DB busy flag)
        )

    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return (
            "You are Bob, a professional fantasy novelist writing in the style of R.A. Salvatore.\n\n"
            "THE SETTING: The Undercity — a vast sealed city beneath a dome, built around the Tower of "
            "Last Chance which pierces the center and stretches to the heavens. Artificial sky. Real weather. "
            "Billions of people. Faction politics. Rift tears in reality where monsters bleed through. "
            "Dark fantasy noir. Every location is named and specific.\n\n"
            "SALVATORE STYLE:\n"
            "- COMBAT: Real-time, blow by blow. Characters have personal fighting styles. Combat reveals "
            "character. Wounds linger. The aftermath matters.\n"
            "- INTERIORITY: We live inside characters. Fear, desire, unspoken truth. Action over rumination.\n"
            "- DIALOGUE: Unfinished. Interrupted. Characters talk around what they mean. Subtext first.\n"
            "- MORAL WEIGHT: Violence has consequences. Characters who kill know what they did.\n"
            "- PACING: Action beats fast. Emotional scenes slow. Chapter endings leave something open.\n"
            "- SPECIFICITY: Names, smells, textures. The Undercity smells of iron, ozone, machine oil, "
            "and a thousand cuisines. Every district is different.\n\n"
            "CHAPTER RULES:\n"
            "- Minimum 3,500 words. Never fewer. This is a novel.\n"
            "- Open with action already in motion. No preamble.\n"
            "- End on a beat: revelation, choice made, or question raised.\n"
            "- Name every character and location. No placeholders.\n\n"
            "Output ONLY the chapter prose. No headers. No commentary. Just the story."
        )


class ProAuthorReviewerAgent(BaseAgent):
    """
    PRO AUTHOR REVIEWER (Pass 2)

    Senior fiction editor reviewing Bob's novel chapter by chapter.
    Fixes pacing, deepens character voice, sharpens ending beats,
    improves specificity. Outputs the full revised chapter.
    """

    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.75,
            max_tokens=16384,
            timeout=1200.0,
        )

    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return (
            "You are a senior fiction editor reviewing a fantasy novel for publication.\n\n"
            "YOUR JOB: Read the chapter and improve it. Real editorial work — not a gentle nudge.\n\n"
            "WHAT YOU FIX:\n"
            "- Pacing: Find where it drags and compress it\n"
            "- Character voice: Every character sounds distinct. Fix dialogue that bleeds together.\n"
            "- Interiority: Are we in the right head at the right moment? Deepen it.\n"
            "- Ending beat: Does it land and earn its emotion, or arrive cheap?\n"
            "- Specificity: Replace vague description with concrete sensory detail.\n\n"
            "WHAT YOU DO NOT DO:\n"
            "- Do not change the plot, characters, or outcomes.\n"
            "- Do not add new characters or locations.\n"
            "- Do not add purple prose. Fixes should be leaner, not more elaborate.\n\n"
            "Output the FULL revised chapter text.\n"
            "After the chapter, add a '---' divider and one short paragraph on what you changed and why."
        )


class BookToModuleAgent(BaseAgent):
    """
    BOOK TO MODULE CONVERTER (Pass 3)

    Converts the finished novel into a D&D 5e box set.
    Modeled on how the Icewind Dale Trilogy became a boxed set.
    Produces: DM Guide, Module (scene-by-scene), Players Guide, Maps list.
    Called once per section type with the relevant novel chapters as input.
    """

    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.65,
            max_tokens=16384,
            timeout=1200.0,
        )

    def _load_training_guide(self) -> str:
        """Load the curated module format guide from published examples."""
        import os
        guide_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "campaign_docs",
            "skills", "training_modules", "MODULE_FORMAT_GUIDE.md"
        )
        try:
            with open(os.path.normpath(guide_path), "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        training = self._load_training_guide()
        training_block = (
            f"\n\n═══════════════════════════════════════════\n"
            f"PUBLISHED MODULE EXAMPLES (match this quality and format)\n"
            f"═══════════════════════════════════════════\n"
            f"{training[:6000]}"  # cap at 6k chars to stay within context
        ) if training else ""

        return f"""You are a senior RPG module designer. You have read the full novel provided and are now extracting it into a professional D&D 5e one-shot module.

The novel is your SOURCE. Do not invent new content — extract, restructure, and make playable what the novel already built. Every NPC line of dialogue, every clue, every scene beat already exists in the novel. Your job is to surface it in a format a DM can run cold.

═══════════════════════════════════════════
REAL PUBLISHED MODULE FORMAT (follow exactly)
═══════════════════════════════════════════

SCENE STRUCTURE (from published modules like Oni Mother, Respect Your Elderly):

CRITICAL FORMAT RULE — THE NUMBERED HEADER IS THE ONLY HEADER FORMAT ALLOWED:
  CORRECT:   1 - THE RUINED MARKET
  WRONG:     Scene 1: The Ruined Market
  WRONG:     ### Scene 1
  WRONG:     **Area 1 - The Ruined Market**
The number and dash with ALL CAPS name is what makes a module scannable at a table.

1 - THE RUINED MARKET

📖 READ ALOUD:
[3-4 sentences. Pull directly from the novel's description of this moment. Sensory detail — what they see, hear, smell. END WITH A PERSON, SOUND, OR THREAT THAT PLAYERS MUST RESPOND TO — never end with pure atmosphere. "A figure in ash-stained robes turns toward you" is correct. "The air smells of burning" is wrong.]

📝 DM NOTES:
- [What is REALLY happening here that players don't know]
- [What physical evidence is present — readable, visible, findable]
- [The key thing that must happen to move to the next scene]
- [What happens if players attack immediately / do nothing / leave]

👤 NPCs PRESENT:
[Name] — [role/description from novel]
- Wants: [what they want right now in this scene — specific, not vague]
- Knows: [the information they have that matters to the plot]
- Hides: [what they won't volunteer — and exactly why they're hiding it]
- If players attack: [immediate consequence]
- Dialogue examples (pull verbatim or close paraphrase from the novel):
  * [NPC's exact voice — the line the novel gave them]
  * [A second line that reveals character, not just plot information]

CONVERSATION BRANCHES (minimum 3 per NPC with dialogue):
If players ask about [topic A]: [Exact NPC response — what they give freely] [DC X Skill if check needed — specify what success AND failure each reveal]
  On success (DC X): [specific information gained]
  On failure: [what happens — NPC closes down, gives wrong info, asks suspicious question]
If players ask about [topic B]: [NPC response]
If players ask about [topic C]: [NPC response]
If players say nothing / wait: [what the NPC does unprompted]

Clue A — given automatically when players arrive: [clue text — no check needed]
Clue B — requires DC [X] [Skill]: [clue text]
Clue C — requires creative approach or specific action: [clue text]

🎲 MECHANICS:
- [Skill] DC [X]: [Specific thing success reveals — a name, a location, a lie caught]
  On failure: [what happens — never leave this blank]
- [Skill] DC [X]: [What success unlocks]
  On failure: [consequence]

⚡ WHAT HAPPENS:
- If players do X: [outcome]
- If players do Y: [different outcome]
- If players do nothing: [what happens anyway — scenes never stall]
- If players fail the main objective: [scene still advances — just differently]

➡️ TRANSITION:
[One specific sentence: what players see/hear/learn that makes them WANT to go to the next scene. NEVER "the party proceeds." Give a pull — a mystery, a threat, a dying whisper, a glimpsed figure.]

---

STAT BLOCKS (place immediately after scene — NEVER in an appendix):

[Enemy Name]
[Size] [Type], [Alignment]
Armor Class [X] ([source])
Hit Points [X] ([dice])
Speed [X] ft.

STR [X] ([mod]) | DEX [X] ([mod]) | CON [X] ([mod]) | INT [X] ([mod]) | WIS [X] ([mod]) | CHA [X] ([mod])

Saving Throws: [list]
Skills: [list]
Senses: passive Perception [X]
Languages: [list]
Challenge [X] ([XP] XP)

[Trait Name]. [Description]

Actions
[Attack]. [Melee/Ranged] Weapon Attack: +[X] to hit, reach [X] ft., one target. Hit: [damage] [type] damage.

Tactics: Round 1: [specific action]. When bloodied (half HP): [behavior change]. Surrenders/flees when: [condition].

BATTLEFIELD:
[3-sentence description of terrain]
- Cover: [specific cover objects]
- Hazards: [anything that can hurt or hinder]
- Interactables: [objects that can be used cleverly]
- Lighting: [lighting conditions]

═══════════════════════════════════════════
CRITICAL RULES
═══════════════════════════════════════════
1. EVERY enemy that might fight the players gets a full stat block, placed right after their first scene.
2. Conversation branches are MANDATORY for every NPC scene. No NPC exists just to give one line of exposition.
3. The three-clue rule: every conclusion players need to reach has THREE independent clues pointing to it.
4. Transitions are pull not push — give players a reason to go forward, not just "they proceed."
5. READ ALOUD is for sensory atmosphere only. DM NOTES is for game mechanics and truth.
6. No generic fantasy. Every name, place, and faction comes from the novel or the Undercity setting.
7. Scene count is DYNAMIC — count story beats first, then write that many scenes. Never default to 5.
8. Time pressure must exist: something bad happens if players take too long.

═══════════════════════════════════════════
DYNAMIC SCENE COUNT — DO THIS FIRST
═══════════════════════════════════════════

Before writing scene 1, do a beat analysis of the novel:

STEP 1 — LIST EVERY DISTINCT STORY BEAT:
  Entry/approach | Investigation/exploration (each major location) |
  Complication (reveal or faction that changes the goal) |
  Climax (fight, confrontation, or showdown) |
  Moral choice or second climax (if the story has both a fight AND a decision) |
  Resolution (consequences, rewards, what changes)

STEP 2 — DECIDE THE SCENE COUNT:
  3 scenes: Linear story, one complication, one payoff. Simple heist / rescue / delivery.
  4 scenes: One mid-story complication that reorients the goal. Standard investigation.
  5 scenes: Two distinct climax beats (a fight AND a moral choice). Most major missions.
  6 scenes: Multiple factions with competing agendas each needing a scene. Multi-front conflict.
  7 scenes: Campaign-weight session only. Do not use for standard missions.

STEP 3 — LABEL EACH SCENE BEFORE WRITING IT:
  One label per scene: [Approach] [Intel] [Investigation] [Complication] [Pivot] [Climax] [Choice] [Resolution] [Epilogue]
  If two scenes share a label — merge them. If a beat has no scene — cut that beat from the count.

WRONG: Generating 5 scenes because 5 is the default.
RIGHT: Counting 4 beats → writing 4 scenes. Counting 6 beats → writing 6 scenes.{training_block}"""


class ColumbusAgent(BaseAgent):
    """
    COLUMBUS — VTT MAP QUALITY REVIEWER

    Reviews maps generated that day using LLaVA vision + prompt/settings analysis.
    Calls llava:latest via Ollama to visually assess each PNG, then combines that
    with knowledge of Flux.1, LoRA behavior, and VTT standards to diagnose problems
    and propose concrete fixes.

    Vision model: llava:latest (Ollama)
    Analysis model: qwen3 (Ollama) for synthesis and patch generation

    Expertise:
    - Stable Diffusion (Flux.1 dev FP8, SDXL/XL, Pony/Illustrious)
    - LoRA mechanics (weights, trigger words, stacking, folder placement)
    - VTT battlemap standards (D&D Beyond, Roll20, Foundry VTT)
    - Top-down orthographic map generation via SD
    - Grid compatibility (1024x1024 minimum, 5ft-per-square scale)
    - Prompt engineering specifically for map generation
    """

    VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llava:latest")
    OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name=os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            model_type=ModelType.LOCAL,
            temperature=0.6,
            max_tokens=3072,
            timeout=180.0,
        )

    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return """You are Columbus, a VTT battlemap specialist and Stable Diffusion expert.

═══ YOUR KNOWLEDGE BASE ═══

STABLE DIFFUSION MODELS (what is installed):
  Flux.1 [dev] FP8 (flux1-dev-fp8.safetensors)
    - THE map model. Requires CFG scale 1.0 — higher values degrade quality.
    - Needs its own VAE: flux-vae-bf16.safetensors (without it, colours are washed out or pink).
    - Largely ignores negative prompts at CFG=1.0 — don't rely on them.
    - Best results: 20-28 steps, Euler or DPM++ 2M sampler.
    - LoRAs MUST have their trigger words in the prompt or the LoRA does nothing.
    - LoRA tag format: <lora:ModelName:weight> — must be FIRST token in prompt.

  SDXL models (epicrealismXL, Juggernaut-XL, RealVisXL, waiIllustrious, etc.)
    - NOT for maps. Cannot use Flux LoRAs. Produces portraits, not top-down maps.
    - Only use if Flux.1 is unavailable (fallback only — mark output as low quality).

  Pony / Illustrious models
    - NOT for maps. Anime style. Wrong aesthetic entirely.

LORAS INSTALLED (in models\Lora\):
  EnvyFluxDungeonMap01.safetensors [Flux] — 36.6 MB
    - Produces: top-down dungeon room maps, stone walls, grid-ready
    - Use for: underground rooms, caves, infestation, sewer, rift chambers
    - Trigger words (verify on CivitAI): "detailed, map, dungeon"
    - Weight: 0.7-0.85 recommended. Above 0.9 = over-baked, loses detail.

  EnvyFluxVillageMap01.safetensors [Flux] — 36.6 MB
    - Produces: top-down outdoor/street maps, cobblestone, building facades
    - Use for: city streets, plazas, markets, rooftops, escort/courier scenes
    - Trigger words (verify on CivitAI): "detailed, map, village"
    - Weight: 0.7-0.85 recommended.

  DD_Table_RPG.safetensors [SDXL/Pony] — 217.9 MB
    - Legacy backup only. Cannot be used with Flux.1 checkpoints.
    - If this is appearing in Flux prompts something is wrong.

  Interior LoRA: NOT YET INSTALLED
    - Heist, infiltration, sabotage, investigation missions currently fall back to
      the village LoRA. This is a known gap — flag it per session.

VTT MAP STANDARDS:
  Resolution  : 1024x1024 minimum for VTT tokens (2048x2048 preferred for large battles)
  View        : Strictly top-down orthographic. Zero perspective. Zero isometric.
  Grid        : Grid-ready = high contrast walls/floor boundary, 5ft-per-square scale implied
  Content     : No characters, no people, no text overlays, no watermarks
  Contrast    : Clear distinction between passable floor and impassable walls
  Lighting    : Flat top-down — no dramatic side-lighting, no raking shadows

PROMPT ENGINEERING FOR MAPS:
  Correct order: <lora:Name:weight>, trigger_words, environment_description, quality_modifiers
  Critical: LoRA tag + trigger words MUST come first — Flux is order-sensitive
  Negative prompt: limited effect at CFG=1.0 but still include:
    "characters, people, isometric, perspective, 3D render, watermark, text, sky, horizon"
  Avoid: excessive flavour text before the LoRA trigger (dilutes LoRA activation)
  Avoid: conflicting style words ("photorealistic portrait" competes with "top-down map")

COMMON FAILURE MODES YOU DIAGNOSE:
  1. LoRA not in models\Lora\ → tag silently ignored → SDXL fallback, no map structure
  2. A1111 LoRA list not refreshed after moving files → same failure as above
  3. Wrong VAE for Flux → washed-out colours, grey/pink tones
  4. CFG > 1.5 with Flux → over-sharpened, artifacts, loses coherence
  5. Trigger words wrong/missing → LoRA loads but doesn't activate map mode
  6. Atmospheric prose before trigger words → prompt front-loaded wrong, LoRA activation weak
  7. Interior scenes using town LoRA → layout doesn't match building floor plan expectation
  8. Too few steps (< 18) → unfinished detail in wall boundaries and floor texture
  9. Step count too high (> 35) → over-rendered, loses top-down feel with Flux

═══ YOUR ROLE ═══

You review maps generated by the Tower bot's pipeline. You cannot see the pixels, but you
know exactly what each prompt/settings combination will produce. Given the prompt, LoRA,
checkpoint, and scene metadata, you diagnose what likely went wrong and what to fix.

Be specific. Name the exact problem. Say "the trigger words are wrong" not "quality could improve".
Propose concrete changes — exact trigger words, exact weight values, exact prompt restructuring.
If the settings look correct for the scene type, say so — not everything needs a fix."""

    async def _vision_assess(self, map_file: str, scene_name: str, mission_type: str) -> str:
        """
        Use llava:latest to visually inspect a map PNG.
        Returns a short assessment string, or empty string on failure.
        """
        import base64
        from pathlib import Path

        path = Path(map_file)
        if not path.exists() or not path.suffix.lower() == ".png":
            return ""

        try:
            img_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        except Exception as e:
            logger.warning(f"🗺️ Columbus: could not read {path.name}: {e}")
            return ""

        vision_prompt = (
            f"This is a generated map for a D&D {mission_type} mission scene called '{scene_name}'. "
            f"Assess it as a VTT battlemap expert:\n"
            f"1. Is it top-down orthographic (bird's eye view)? Or does it have perspective/isometric?\n"
            f"2. Are there visible characters or people? (bad — maps should be empty)\n"
            f"3. Are walls and floor boundaries clear and high-contrast?\n"
            f"4. Does it look like a usable D&D battlemap or more like a scene illustration?\n"
            f"5. One-line verdict: GOOD MAP / NEEDS WORK / UNUSABLE — and why.\n"
            f"Be concise. Max 150 words."
        )

        try:
            from src.resource_cop import wait_for_ollama_turn

            decision = await wait_for_ollama_turn(
                "columbus_vision",
                track="primary",
                max_wait_seconds=60,
            )
            if not decision.run_now:
                logger.info(f"Columbus vision deferred: {decision.reason}")
                return ""

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    self.OLLAMA_URL,
                    json={
                        "model": self.VISION_MODEL,
                        "messages": [{
                            "role": "user",
                            "content": vision_prompt,
                            "images": [img_b64],
                        }],
                        "stream": False,
                    },
                )
                data = resp.json()
                return data.get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.warning(f"🗺️ Columbus vision call failed for {path.name}: {e}")
            return ""

    async def review_maps(
        self,
        maps_today: List[Dict[str, Any]],
        current_settings: Dict[str, Any],
    ) -> AgentAnalysis:
        """
        Review today's generated maps using LLaVA vision + prompt analysis.

        For each map: calls llava:latest to visually inspect the PNG, then
        combines visual verdict with prompt/settings analysis to find problems.

        maps_today: list of dicts with keys:
          scene_name, location, district, scene_type, mission_type,
          prompt (reconstructed), lora_used, checkpoint, steps, cfg, map_file
        current_settings: dict of current .env map settings
        """
        if not maps_today:
            return AgentAnalysis(
                agent_name="Columbus",
                agent_role="VTT Map Quality Reviewer",
                timestamp=datetime.now().isoformat(),
                component="map_generation",
                issues_found=["No maps generated today — nothing to review"],
                severity_scores={},
                recommendations=[],
                confidence=1.0,
            )

        settings_block = "\n".join(f"  {k}: {v}" for k, v in current_settings.items())

        # ── Vision pass: LLaVA looks at each map ──────────────────────────
        vision_results: List[str] = []
        for m in maps_today[:8]:  # cap at 8 — LLaVA is slow
            map_file = m.get("map_file", "")
            scene    = m.get("scene_name", "?")
            mtype    = m.get("mission_type", "unknown")
            if map_file:
                logger.info(f"🗺️ Columbus: LLaVA inspecting {Path(map_file).name}…")
                verdict = await self._vision_assess(map_file, scene, mtype)
                if verdict:
                    vision_results.append(f"  [{scene}]: {verdict}")
                    logger.info(f"🗺️ Columbus vision — {scene}: {verdict[:120].replace(chr(10),' ')}")
            await asyncio.sleep(2)

        vision_block = "\n".join(vision_results) if vision_results else "  (no visual assessments completed)"

        # ── Synthesis: combine visual findings with prompt/settings analysis ──
        map_summaries = []
        for m in maps_today[:8]:
            map_summaries.append(
                f"  {m.get('scene_name','?')} | type={m.get('mission_type','?')} "
                f"| district={m.get('district','?')} | lora={m.get('lora_used','?')}\n"
                f"  prompt: {m.get('prompt','?')[:250]}"
            )

        synthesis_prompt = f"""You are Columbus, a VTT battlemap expert. Review today's generated maps.

CURRENT MAP SETTINGS:
{settings_block}

MAPS GENERATED TODAY ({len(maps_today)} total):
{chr(10).join(map_summaries)}

LLAVA VISUAL ASSESSMENTS (actual pixel analysis):
{vision_block}

Cross-reference the visual verdicts against the prompts and settings. Identify:
1. Where visual quality failed and WHY (wrong LoRA? wrong triggers? wrong model?)
2. Where settings are suboptimal regardless of today's results
3. Specific prompt or settings changes that would fix the worst problems

Output:
## Issues Found
[bullet list — be specific, e.g. "EnvyFluxDungeonMap01 not activating in R03 — UNUSABLE verdict confirms LoRA miss"]

## Recommended Fixes
[bullet list — concrete, e.g. "Add 'top-down, orthographic' to dungeon trigger string" or "Increase steps from 20 to 25 for dungeon maps"]"""

        response = await self.complete(synthesis_prompt, max_tokens=2048)

        issues = self._extract_issues(response.content)
        recs   = self._extract_recommendations(response.content)

        # Append any UNUSABLE verdicts from LLaVA as direct issues
        for vr in vision_results:
            if "UNUSABLE" in vr.upper() or "NEEDS WORK" in vr.upper():
                snippet = vr.strip()[:120]
                if snippet not in issues:
                    issues.insert(0, snippet)

        return AgentAnalysis(
            agent_name="Columbus",
            agent_role="VTT Map Quality Reviewer",
            timestamp=datetime.now().isoformat(),
            component="map_generation",
            issues_found=issues[:12],
            severity_scores={i[:50]: (0.9 if "UNUSABLE" in i.upper() else 0.7) for i in issues},
            recommendations=recs,
            confidence=0.9,
        )

    def _extract_issues(self, text: str) -> List[str]:
        issues = []
        in_issues = False
        for line in text.split("\n"):
            if "ISSUES" in line.upper() or "## Issues" in line:
                in_issues = True
            elif line.startswith("##"):
                in_issues = False
            if in_issues:
                l = line.strip()
                if re.match(r"^[-*\d.]\s", l) and len(l) > 15:
                    issues.append(re.sub(r"^[-*\d.]\s*", "", l))
        if not issues:
            # fallback: any bullet line
            for line in text.split("\n"):
                l = line.strip()
                if re.match(r"^[-*]\s", l) and len(l) > 15:
                    issues.append(re.sub(r"^[-*]\s*", "", l))
        return issues[:12]

    def _extract_recommendations(self, text: str) -> List[str]:
        recs = []
        in_rec = False
        for line in text.split("\n"):
            if any(w in line for w in ("Recommended", "RECOMMEND", "## Fix", "## Rec")):
                in_rec = True
            elif line.startswith("##"):
                in_rec = False
            if in_rec:
                l = line.strip()
                if re.match(r"^[-*\d.]\s", l) and len(l) > 20:
                    recs.append(re.sub(r"^[-*\d.]\s*", "", l))
        return recs[:8]
