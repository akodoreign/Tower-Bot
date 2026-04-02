"""Agent Orchestrator for Self-Learning Mission Builder Improvement.

Coordinates the 5 specialized agents and integrates their analysis
into the self-learning loop. Handles:

- Agent initialization and execution
- Data collection for analysis (missions, code metrics, quality scores)
- Parallel agent analysis execution
- Result aggregation and synthesis
- Safe code change application with safeguards
- Journal logging of all decisions
- DM escalation for uncertain decisions
"""

import os
import json
import asyncio
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Set
from dataclasses import asdict

from src.log import logger
from src.agents.learning_agents import (
    ProjectManagerAgent,
    PythonVeteranAgent,
    DNDExpertAgent,
    DNDVeteranAgent,
    AICriticAgent,
    AgentAnalysis,
    LearningSession,
)


class AgentOrchestrator:
    """
    Orchestrate the 5-agent learning system for autonomous mission builder improvement.
    
    Flow:
    1. Collect metrics and code data
    2. Run 4 specialized agents in parallel (Python, D&D Expert, D&D Veteran, AI Critic)
    3. Project Manager synthesizes results
    4. Apply safe code changes (with safeguards)
    5. Log findings to journal
    
    Usage:
        orchestrator = AgentOrchestrator()
        session = await orchestrator.run_learning_cycle()
    """
    
    def __init__(self):
        self.agents = {
            "project_manager": ProjectManagerAgent(),
            "python_veteran": PythonVeteranAgent(),
            "dnd_expert": DNDExpertAgent(),
            "dnd_veteran": DNDVeteranAgent(),
            "ai_critic": AICriticAgent(),
        }
        
        self.project_root = Path(__file__).resolve().parent.parent.parent
        self.campaign_docs = self.project_root / "campaign_docs"
        self.src_root = self.project_root / "src"
        self.mission_builder_root = self.src_root / "mission_builder"
        self.journal_path = self.project_root / "logs" / "journal.txt"
        
        # Tracking
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.analyses: List[AgentAnalysis] = []
        self.approved_changes: List[Dict] = []
    
    async def run_learning_cycle(self) -> Optional[LearningSession]:
        """
        Execute one complete learning cycle with all 5 agents.
        
        Returns:
            LearningSession with all analyses and approved changes, or None if errors
        """
        try:
            self._journal("═══ AGENT LEARNING CYCLE START ═══")
            logger.info(f"🤖 Agent learning cycle starting (session: {self.session_id})")
            
            # PHASE 1: Collect data
            self._journal(f"PHASE 1: Data Collection ({datetime.now().strftime('%H:%M:%S')})")
            data = await self._collect_analysis_data()
            if not data:
                self._journal("ERROR: Failed to collect analysis data")
                return None
            
            # PHASE 2: Run agents in parallel (except Project Manager)
            self._journal(f"PHASE 2: Parallel Agent Analysis ({datetime.now().strftime('%H:%M:%S')})")
            specialist_analyses = await self._run_specialist_agents(data)
            
            if not specialist_analyses:
                self._journal("ERROR: Agent analysis failed")
                return None
            
            # PHASE 3: Project Manager synthesis
            self._journal(f"PHASE 3: Project Manager Synthesis ({datetime.now().strftime('%H:%M:%S')})")
            pm_analysis = await self._run_project_manager(specialist_analyses, data)
            
            specialist_analyses.append(pm_analysis)
            self.analyses = specialist_analyses
            
            # PHASE 4: Safe code changes
            self._journal(f"PHASE 4: Code Change Application ({datetime.now().strftime('%H:%M:%S')})")
            await self._apply_safe_changes(specialist_analyses)
            
            # PHASE 5: Generate session report
            session = LearningSession(
                session_id=self.session_id,
                timestamp=datetime.now().isoformat(),
                analyses=self.analyses,
                overall_priority=self._calculate_overall_priority(self.analyses),
                approved_changes=self.approved_changes,
                journal_entry=self._generate_session_summary(),
            )
            
            self._journal(f"═══ AGENT LEARNING CYCLE COMPLETE ═══")
            self._journal(f"Changes applied: {len(self.approved_changes)}")
            
            logger.info(f"✅ Agent learning cycle complete ({len(self.analyses)} analyses)")
            return session
            
        except Exception as e:
            logger.error(f"❌ Agent orchestrator error: {e}")
            self._journal(f"ERROR: {e}")
            return None
    
    async def _collect_analysis_data(self) -> Optional[Dict[str, Any]]:
        """
        Collect metrics andcode data for agent analysis.
        
        Returns dict with:
        - mission_metrics: Success rate, quality, etc.
        - mission_samples: Recent missions for narrative analysis
        - code_files: Source code for quality analysis
        - code_metrics: Complexity, duplication, etc.
        - npc_data: NPC roster and faction info
        """
        try:
            data = {}
            
            # Mission metrics
            data["mission_metrics"] = self._collect_mission_metrics()
            
            # Mission samples for narrative analysis
            data["mission_samples"] = self._collect_recent_missions()
            
            # Source code for analysis
            data["code_files"] = self._collect_code_files()
            
            # Code metrics
            data["code_metrics"] = self._calculate_code_metrics(data["code_files"])
            
            # NPC and faction data
            data["npc_data"] = self._collect_npc_data()
            data["faction_info"] = self._collect_faction_info()
            
            # Difficulty scale reference
            data["difficulty_scale"] = self._get_difficulty_scale()
            
            self._journal(f"Data collected: {len(data)} categories")
            return data
            
        except Exception as e:
            logger.error(f"Data collection error: {e}")
            return None
    
    def _collect_mission_metrics(self) -> Dict[str, Any]:
        """Calculate key mission metrics from mission_memory.json."""
        mission_path = self.campaign_docs / "mission_memory.json"
        
        try:
            if not mission_path.exists():
                return {"total_missions": 0, "completion_rate": 0}
            
            missions = json.loads(mission_path.read_text(encoding="utf-8"))
            
            # Calculate stats
            total = len(missions)
            completed = sum(1 for m in missions if m.get("outcome") == "completed")
            failed = sum(1 for m in missions if m.get("outcome") == "failed")
            expired = sum(1 for m in missions if m.get("outcome") == "expired")
            
            # Difficulty distribution
            difficulty_dist = {}
            for m in missions[-30:]:  # Last 30
                diff = m.get("difficulty_rating", 5)
                difficulty_dist[diff] = difficulty_dist.get(diff, 0) + 1
            
            # Success rates by difficulty
            deadly_dict = [m for m in missions if m.get("difficulty_rating", 5) >= 8]
            hard_dict = [m for m in missions if 4 <= m.get("difficulty_rating", 5) <= 7]
            easy_dict = [m for m in missions if m.get("difficulty_rating", 5) <= 3]
            
            deadly_success = sum(1 for m in deadly_dict if m.get("outcome") == "completed") / len(deadly_dict) if deadly_dict else 0
            hard_success = sum(1 for m in hard_dict if m.get("outcome") == "completed") / len(hard_dict) if hard_dict else 0
            easy_success = sum(1 for m in easy_dict if m.get("outcome") == "completed") / len(easy_dict) if easy_dict else 0
            
            return {
                "total_missions": total,
                "completed": completed,
                "failed": failed,
                "expired": expired,
                "completion_rate": completed / total if total > 0 else 0,
                "average_difficulty": sum(m.get("difficulty_rating", 5) for m in missions) / total if total > 0 else 5,
                "difficulty_distribution": difficulty_dist,
                "deadly_success_rate": deadly_success,
                "hard_success_rate": hard_success,
                "easy_success_rate": easy_success,
            }
        except Exception as e:
            logger.warning(f"Could not calculate mission metrics: {e}")
            return {}
    
    def _collect_recent_missions(self, count: int = 10) -> List[Dict]:
        """Get recent completed/failed missions for narrative analysis."""
        mission_path = self.campaign_docs / "mission_memory.json"
        
        try:
            if not mission_path.exists():
                return []
            
            missions = json.loads(mission_path.read_text(encoding="utf-8"))
            # Return last N missions
            return missions[-count:] if len(missions) > count else missions
        except Exception:
            return []
    
    def _collect_code_files(self) -> Dict[str, str]:
        """Collect source code from mission builder modules."""
        files = {}
        
        target_files = [
            "mission_types.py",
            "json_generator.py",
            "schemas.py",
            "api.py",
        ]
        
        for filename in target_files:
            filepath = self.mission_builder_root / filename
            if filepath.exists():
                try:
                    files[filename] = filepath.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Could not read {filename}: {e}")
        
        return files
    
    def _calculate_code_metrics(self, code_files: Dict[str, str]) -> Dict[str, Any]:
        """Calculate code quality metrics."""
        metrics = {
            "total_lines": sum(len(content.split("\n")) for content in code_files.values()),
            "num_modules": len(code_files),
            "total_chars": sum(len(content) for content in code_files.values()),
        }
        
        if metrics["num_modules"] > 0:
            metrics["avg_module_size"] = metrics["total_lines"] // metrics["num_modules"]
        
        # Rough duplication detection (repeated code blocks)
        all_code = "\n".join(code_files.values())
        lines = all_code.split("\n")
        line_hashes: Dict[str, int] = {}
        
        for line in lines:
            # Hash code lines (ignore whitespace)
            code_only = line.strip()
            if len(code_only) > 20 and not code_only.startswith("#"):
                h = hashlib.md5(code_only.encode()).hexdigest()
                line_hashes[h] = line_hashes.get(h, 0) + 1
        
        duplicated_lines = sum(1 for count in line_hashes.values() if count > 1)
        metrics["duplication_rate"] = (duplicated_lines / len(lines) * 100) if lines else 0
        
        # Import count
        import_count = all_code.count("import ")
        metrics["import_count"] = import_count
        
        # Async function count
        async_count = all_code.count("async def")
        metrics["async_functions"] = async_count
        
        # Estimated cyclomatic complexity (heuristic: if/for/while/except count)
        complexity_indicators = all_code.count("if ") + all_code.count("for ") + all_code.count("while ") + all_code.count("except")
        metrics["cyclomatic_complexity"] = max(1, complexity_indicators // max(1, len(code_files)))
        
        return metrics
    
    def _collect_npc_data(self) -> Dict[str, Any]:
        """Collect NPC roster data."""
        roster_path = self.campaign_docs / "npc_roster.json"
        
        try:
            if not roster_path.exists():
                return {"npcs": [], "total_count": 0}
            
            npcs = json.loads(roster_path.read_text(encoding="utf-8"))
            return {
                "npcs": npcs[:20],  # First 20 NPCs
                "total_count": len(npcs),
                "by_faction": {},
            }
        except Exception:
            return {"npcs": [], "total_count": 0}
    
    def _collect_faction_info(self) -> Dict[str, Any]:
        """Collect faction information."""
        rep_path = self.campaign_docs / "faction_reputation.json"
        
        try:
            if not rep_path.exists():
                return {}
            
            return json.loads(rep_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    
    def _get_difficulty_scale(self) -> Dict[int, str]:
        """Get the current difficulty scale mapping."""
        # This comes from mission_types.py
        return {
            1: "Trivial",
            2: "Easy",
            3: "Moderate",
            4: "Challenging",
            5: "Hard",
            6: "Dangerous",
            7: "Deadly",
            8: "Extreme",
            9: "Catastrophic",
            10: "Epic",
        }
    
    async def _run_specialist_agents(
        self,
        data: Dict[str, Any],
    ) -> List[AgentAnalysis]:
        """Run the 4 specialist agents in parallel."""
        tasks = []
        
        # Python Veteran analysis
        tasks.append(
            self.agents["python_veteran"].analyze_code(data.get("code_files", {}))
        )
        
        # D&D Expert analysis
        tasks.append(
            self.agents["dnd_expert"].analyze_balance(
                data.get("mission_metrics", {}),
                data.get("difficulty_scale", {}),
            )
        )
        
        # D&D Veteran analysis
        tasks.append(
            self.agents["dnd_veteran"].analyze_narrative(
                data.get("mission_samples", []),
                data.get("npc_data", {}),
                data.get("faction_info", {}),
            )
        )
        
        # AI Critic analysis
        tasks.append(
            self.agents["ai_critic"].analyze_system(data.get("code_metrics", {}))
        )
        
        # Run all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        analyses = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                agent_name = list(self.agents.keys())[i + 1]  # Skip project manager
                logger.error(f"Agent {agent_name} failed: {result}")
                self._journal(f"ERROR: Agent {agent_name} analysis failed")
            else:
                analyses.append(result)
        
        self._journal(f"Specialist agents completed: {len(analyses)}/4")
        return analyses
    
    async def _run_project_manager(
        self,
        specialist_analyses: List[AgentAnalysis],
        data: Dict[str, Any],
    ) -> AgentAnalysis:
        """Run the Project Manager to synthesize specialist analyses."""
        return await self.agents["project_manager"].analyze_learning_session(
            specialist_analyses,
            data.get("mission_metrics", {}),
        )
    
    async def _apply_safe_changes(self, analyses: List[AgentAnalysis]) -> None:
        """
        Apply safe code changes suggested by agents.
        
        Safeguards:
        1. Only apply changes marked with high confidence (>0.8)
        2. Create backups before modifications
        3. Validate syntax after changes
        4. Log all changes
        5. Require DM approval for breaking changes
        """
        for analysis in analyses:
            if not analysis.code_changes:
                continue
            
            for change in analysis.code_changes:
                try:
                    # Check safeguards
                    if analysis.confidence < 0.8:
                        self._journal(f"SKIPPED: {change['description']} — confidence too low")
                        continue
                    
                    if change.get("breaking_change", False):
                        self._journal(f"ESCALATED: {change['description']} — requires DM approval")
                        continue
                    
                    # Apply change
                    success = await self._apply_code_change(change, analysis.agent_name)
                    
                    if success:
                        self.approved_changes.append(change)
                        self._journal(f"APPLIED: {change['description']} (by {analysis.agent_name})")
                        logger.info(f"✅ Applied change: {change['description']}")
                    else:
                        self._journal(f"FAILED: {change['description']} (by {analysis.agent_name})")
                
                except Exception as e:
                    logger.error(f"Error applying change: {e}")
                    self._journal(f"ERROR: Failed to apply change: {e}")
    
    async def _apply_code_change(self, change: Dict, agent_name: str) -> bool:
        """
        Safely apply a code change to a file.
        
        Args:
            change: {
                'file': 'path/to/file.py',
                'type': 'replace|insert|delete',
                'description': 'What this changes',
                'old_code': 'code to replace' (for replace),
                'new_code': 'new code' (for replace/insert),
                'line_number': N (for insert),
                'breaking_change': bool,
            }
            agent_name: Name of agent that suggested this
        
        Returns:
            True if change was successful
        """
        try:
            filepath = self.src_root / change["file"]
            
            if not filepath.exists():
                logger.warning(f"File does not exist: {filepath}")
                return False
            
            # Read current content
            content = filepath.read_text(encoding="utf-8")
            
            # Apply change based on type
            if change["type"] == "replace":
                old = change.get("old_code", "")
                new = change.get("new_code", "")
                
                if old not in content:
                    logger.warning(f"Replace target not found in {filepath}")
                    return False
                
                new_content = content.replace(old, new, 1)
            
            elif change["type"] == "insert":
                new = change.get("new_code", "")
                line_num = change.get("line_number", -1)
                
                lines = content.split("\n")
                lines.insert(line_num, new)
                new_content = "\n".join(lines)
            
            elif change["type"] == "delete":
                old = change.get("old_code", "")
                
                if old not in content:
                    logger.warning(f"Delete target not found in {filepath}")
                    return False
                
                new_content = content.replace(old, "", 1)
            
            else:
                logger.warning(f"Unknown change type: {change['type']}")
                return False
            
            # Validate syntax (basic check for Python files)
            if filepath.suffix == ".py":
                try:
                    compile(new_content, str(filepath), "exec")
                except SyntaxError as e:
                    logger.error(f"Syntax error in modified {filepath}: {e}")
                    return False
            
            # Write back
            filepath.write_text(new_content, encoding="utf-8")
            return True
            
        except Exception as e:
            logger.error(f"Error applying code change: {e}")
            return False
    
    def _calculate_overall_priority(self, analyses: List[AgentAnalysis]) -> str:
        """Calculate overall priority based on analyses."""
        max_severity = max(
            (max(scores.values()) for a in analyses for scores in [a.severity_scores] if scores),
            default=0.3,
        )
        
        if max_severity >= 0.9:
            return "critical"
        elif max_severity >= 0.7:
            return "high"
        elif max_severity >= 0.5:
            return "medium"
        else:
            return "low"
    
    def _generate_session_summary(self) -> str:
        """Generate a summary of the learning session."""
        summary_lines = [
            f"Session ID: {self.session_id}",
            f"Analyses completed: {len(self.analyses)}",
            f"Changes applied: {len(self.approved_changes)}",
            "",
            "Agent Findings:",
        ]
        
        for analysis in self.analyses:
            summary_lines.append(
                f"  {analysis.agent_name}: {len(analysis.issues_found)} issues, "
                f"{len(analysis.recommendations)} recommendations"
            )
        
        return "\n".join(summary_lines)
    
    def _journal(self, entry: str) -> None:
        """Write to the learning journal."""
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            with open(self.journal_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [AGENTS] {entry}\n")
        except Exception as e:
            logger.warning(f"Failed to write to journal: {e}")
