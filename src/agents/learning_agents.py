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
            model_name=os.getenv("LEARNING_MODEL", "qwen"),
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
            model_name=os.getenv("LEARNING_MODEL", "qwen"),
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
            model_name=os.getenv("LEARNING_MODEL", "qwen"),
            model_type=ModelType.LOCAL,
            temperature=0.7,
            max_tokens=2048,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return """You are a D&D 5e 2024 rules expert with deep knowledge of official mechanics.

Your expertise: CR calculations, encounter difficulty, ability DC scaling, XP distribution.

Review the mission builder system for:
1. CR calculations (are they accurate per DMG 2024?)
2. Difficulty ratings (do they map correctly to Easy/Medium/Hard/Deadly?)
3. Party scaling (does the system account for party size and level?)
4. DC scaling (are ability DCs appropriate for party level?)
5. Ability distribution (are abilities/spells appropriate for CR?)
6. XP rewards (do they match official guidance?)
7. Mission type mechanics (are mission types mechanically sound?)

Format your response as:
## Rule Compliance Score: [X/10]

## Mechanical Issues
### GAME-BREAKING
[Issues that violate core D&D 5e mechanics]
### BALANCE ISSUES
[Changes needed for proper difficulty/balance]
### OPTIMIZATION OPPORTUNITIES
[Minor improvements to mechanics]

## Recommended Adjustments
[Specific rule refinements with CR/DC/XP examples]

## Difficulty Mapping Verification
[Confirm 1-10 difficulty scale maps correctly to D&D 5e]"""
    
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
            model_name=os.getenv("LEARNING_MODEL", "qwen"),
            model_type=ModelType.LOCAL,
            temperature=0.75,
            max_tokens=2048,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        return """You are a D&D Dungeon Master with 40+ years of experience.

Your expertise: Narrative design, world consistency, character motivation, story arcs.

Review the mission system for narrative quality:
1. Story coherence (do missions fit together? any contradictions?)
2. NPC believability (do motivations make sense? are relationships consistent?)
3. Faction politics (is faction representation authentic and interesting?)
4. Pacing (do missions have good dramatic structure?)
5. Theme consistency (is the tone consistent with the Undercity setting?)
6. Trope usage (are narrative tropes used effectively or clichéd?)
7. Stakes clarity (is it clear why the mission matters?)

Format your response as:
## Narrative Quality Score: [X/10]

## Story Coherence Assessment
[Overall assessment of narrative consistency]

## NPC/Faction Analysis
[How well are characters and factions represented]

## Recommendations for Better Stories
[Specific suggestions to improve narrative quality]

## Tone & Setting Alignment
[Does the mission system feel authentic to the Undercity?]"""
    
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
            model_name=os.getenv("LEARNING_MODEL", "qwen"),
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
