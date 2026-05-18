# 5-Agent Self-Learning System Documentation

**Last Updated:** 2024
**Status:** Phase 3 - Self-Learning Agent Integration (Complete)
**Integration Point:** `src/self_learning.py` → runs during 1-4 AM window

---

## Table of Contents

1. [System Overview](#system-overview)
2. [The 5 Specialized Agents](#the-5-specialized-agents)
3. [Orchestrator Architecture](#orchestrator-architecture)
4. [Integration with Self-Learning Loop](#integration-with-self-learning-loop)
5. [Agent Analysis Output](#agent-analysis-output)
6. [Code Change Safeguards](#code-change-safeguards)
7. [Debug and Monitoring](#debug-and-monitoring)
8. [Future Enhancements](#future-enhancements)

---

## System Overview

The 5-Agent Self-Learning System autonomously analyzes and improves the mission builder during off-hours (1-4 AM). Each agent specializes in a different domain:

```
Self-Learning Loop (1-4 AM)
    ↓
PHASE 0: Agent Orchestrator Launches
    ↓ (Runs in parallel)
4 Specialist Agents:
├─ Python Veteran (Code Quality)
├─ D&D Expert (Rule Balance)
├─ D&D Veteran (Story Coherence)
└─ AI Critic (System Architecture)
    ↓ (Sequential)
Project Manager Agent Synthesizes
    ↓
Phase Manager Applies Safe Changes
    ↓
Journal Entry Logged
    ↓
Regular Learning Studies Continue
```

### Key Features

- **Autonomous Analysis**: 4 specialist agents run in parallel, analyzing different aspects
- **Synthesis**: Project Manager coordinates findings and prioritizes recommendations
- **Safe Implementation**: Only low-risk, high-confidence changes applied automatically
- **Full Transparency**: Every decision logged to `logs/journal.txt`
- **DM Override**: Escalates uncertain decisions for human review
- **Incremental Improvement**: Continuous iteration without breaking existing functionality

---

## The 5 Specialized Agents

### 1. **ProjectManagerAgent**
**Role:** Orchestrator and Decision Maker
**Specialization:** System coordination, priority management

```python
from src.agents import ProjectManagerAgent

pm = ProjectManagerAgent()

# Synthesizes analyses from all specialists
pm_analysis = await pm.analyze_learning_session(
    agent_analyses=specialist_results,
    mission_metrics=current_metrics,
)
```

**Responsibilities:**
- Receive analyses from 4 specialist agents
- Identify critical issues across all domains
- Rank recommendations by impact and priority
- Decide which code changes are safe to apply
- Escalate uncertain decisions to DM journal
- Generate comprehensive session summaries

**Output:**
- Priority-ranked list of all recommendations
- Approval status for each code change
- DM escalation notes for uncertain decisions
- Next cycle focus areas

---

### 2. **PythonVeteranAgent**
**Role:** Code Quality & Architecture Expert
**Specialization:** Python 3.11, performance, async patterns

```python
from src.agents import PythonVeteranAgent

python_vet = PythonVeteranAgent()

# Analyze mission builder source code
analysis = await python_vet.analyze_code({
    "mission_types.py": code_content,
    "json_generator.py": code_content,
    "schemas.py": code_content,
    "api.py": code_content,
})
```

**Responsibilities:**
- Review Python 3.11 compatibility
- Check async/await patterns
- Validate type hints completeness
- Identify performance bottlenecks
- Suggest refactoring opportunities
- Detect error handling gaps
- Review dependency imports

**Issues Scored by Severity:**
- **CRITICAL**: Memory leaks, crashes, security issues
- **HIGH**: Performance problems, breaking changes
- **MEDIUM**: Code style, maintainability
- **LOW**: Documentation, nice-to-haves

**Example Output:**
```
Code Quality Score: 8.2/10

CRITICAL ISSUES:
- Potential unbounded list accumulation in json_generator._generation_context

HIGH PRIORITY:
- Async timeout not set on Ollama HTTP calls (could hang)
- Type hints incomplete on 3 functions

RECOMMENDATIONS:
1. Add max_size parameter to context dict in json_generator.py
2. Set timeout=120 on all httpx.AsyncClient() calls
3. Add return type hints to generate_dynamic_title()
```

---

### 3. **DNDExpertAgent**
**Role:** D&D 5e 2024 Rules Specialist
**Specialization:** Balance, encounter design, mechanics

```python
from src.agents import DNDExpertAgent

dnd_expert = DNDExpertAgent()

# Analyze mission balance and rule compliance
analysis = await dnd_expert.analyze_balance(
    missions_data={
        'sample_count': 147,
        'avg_party_level': 5,
        'party_size': 4,
        'avg_difficulty': 5.2,
        'deadly_success_rate': 0.45,
        'hard_success_rate': 0.65,
        'easy_success_rate': 0.92,
    },
    difficulty_scale={
        1: "Trivial", 2: "Easy", 3: "Moderate", 4: "Challenging",
        5: "Hard", 6: "Dangerous", 7: "Deadly", 8: "Extreme",
        9: "Catastrophic", 10: "Epic"
    }
)
```

**Responsibilities:**
- Verify CR calculations per DMG 2024
- Check difficulty rating mappings to D&D mechanics
- Validate encounter difficulty scaling
- Review DC scaling by party level
- Assess XP distribution fairness
- Ensure ability distribution is appropriate for CR
- Identify game-breaking mechanics

**Difficulty Mapping Verification:**
```
1-3 (Trivial-Moderate)    → Easy      → 20% deadly, 0% PC death
4 (Challenging)            → Medium    → 50% deadly, minimal death
5-6 (Hard-Dangerous)       → Hard      → 70% deadly, 1-2 deaths possible
7-8 (Deadly-Extreme)       → Deadly    → 90%+ deadly, TPK possible
9-10 (Catastrophic-Epic)   → Impossible→ 99%+ deadly, TPK likely
```

**Example Output:**
```
Rule Compliance Score: 7.1/10

BALANCE ISSUES:
- Deadly missions (9-10) have 45% success rate (should be 10-20%)
- Easy missions (1-3) have 92% success (good, target 85-95%)

RECOMMENDATIONS:
1. Increase Deadly mission encounter difficulty (add +2 CR)
2. Reduce Extreme mission reward scaling (currently 2x fair XP)
3. Verify 5-6 zone encounters for party level scaling
```

---

### 4. **DNDVeteranAgent**
**Role:** Narrative & World Designer
**Specialization:** Story coherence, NPC believability, worldbuilding

```python
from src.agents import DNDVeteranAgent

dnd_veteran = DNDVeteranAgent()

# Analyze narrative quality and consistency
analysis = await dnd_veteran.analyze_narrative(
    missions_sample=[mission1, mission2, ...],
    npc_data={'npcs': [npc1, npc2, ...], 'total_count': 50},
    faction_info={'Obsidian Lotus': {...}, ...}
)
```

**Responsibilities:**
- Ensure missions tell coherent stories
- Verify NPC motivations and consistency
- Assess faction politics alignment
- Review story pacing and dramatic tension
- Check worldbuilding detail accuracy
- Validate narrative trope usage
- Ensure stakes are clear

**Quality Dimensions:**
- **Story Coherence** (0-1): Do missions form a narrative arc?
- **NPC Believability** (0-1): Are motivations and relationships authentic?
- **Faction Authenticity** (0-1): Do factions feel real and consistent?
- **Pacing** (0-1): Good dramatic structure?
- **Theme Consistency** (0-1): Does tone fit the Undercity setting?

**Example Output:**
```
Narrative Quality Score: 7.8/10

STORY COHERENCE:
Missions generally cohere well. Notable issue: 3 recovery missions
mention same magical artifact but with different descriptions.

NPC ANALYSIS:
Strong characterization overall. Faction reps feel authentic.
Concern: No female NPCs in top 10 most frequent (check bias).

RECOMMENDATIONS:
1. Standardize artifact descriptions (create lore entry)
2. Add 2-3 female NPCs to high-frequency faction representatives
3. Create faction rivalry subplot thread through mission sequence
```

---

### 5. **AICriticAgent**
**Role:** Code Pattern Detection & Synthesis Specialist
**Specialization:** Architecture patterns, anti-patterns, improvement synthesis

```python
from src.agents import AICriticAgent

ai_critic = AICriticAgent()

# Analyze system for patterns and synergies
analysis = await ai_critic.analyze_system({
    'total_lines': 2847,
    'num_modules': 4,
    'cyclomatic_complexity': 12,
    'duplication_rate': 3.5,
})
```

**Responsibilities:**
- Identify code duplication opportunities
- Detect architectural anti-patterns
- Find data flow inefficiencies
- Spot missing error handling
- Assess system scalability
- Synthesize findings into unified recommendations
- Rate solution quality and confidence

**System Health Dimensions:**
- **Duplication** (% of lines): Below 5% is good
- **Complexity** (avg per module): Below 8 is good
- **Error Handling**: Try/except coverage
- **Scalability**: Performance with 10x data
- **Integration**: How well do components connect?

**Example Output:**
```
System Health Score: 7.5/10

PATTERNS DETECTED:
- Repeated "check mission_path.exists()" pattern (3 occurrences)
- Similar Ollama timeout handling appears in 2 places

CRITICAL SYNTHESIS:
Single highest-impact change: Extract `_mission_exists()` utility
and timeout handling into helpers. Would:
- Reduce duplication by ~8%
- Improve consistency
- Make future changes easier

Confidence: 0.85 | Expected Impact: Medium
```

---

## Orchestrator Architecture

### `AgentOrchestrator` Main Flow

```python
from src.agents import AgentOrchestrator

orchestrator = AgentOrchestrator()
session = await orchestrator.run_learning_cycle()
```

**5-Phase Execution:**

#### Phase 1: Data Collection
```
↓
Gathers metrics and code files:
├─ Mission metrics (success rates, difficulty distribution)
├─ Recent missions for narrative analysis
├─ Source code files (mission_types.py, json_generator.py, etc.)
├─ Code metrics (LOC, complexity, duplication)
├─ NPC roster and faction data
└─ Current difficulty scale reference
```

#### Phase 2: Parallel Specialist Analysis
```
↓
4 agents run simultaneously:
├─ PythonVeteranAgent.analyze_code(code_files)
├─ DNDExpertAgent.analyze_balance(missions, difficulty_scale)
├─ DNDVeteranAgent.analyze_narrative(missions, npcs, factions)
└─ AICriticAgent.analyze_system(code_metrics)
↓
All complete (fastest + slowest time = total time)
```

#### Phase 3: Project Manager Synthesis
```
↓
ProjectManagerAgent receives all 4 analyses:
├─ Reads all issues and recommendations
├─ Creates unified priority list
├─ Identifies critical problems
├─ Decides on code change safety
└─ Prepares DM escalations
```

#### Phase 4: Safe Code Application
```
↓
For each approved code change:
├─ Check confidence >= 0.8
├─ Flag if breaking change (escalate to DM)
├─ Create backup
├─ Apply change
├─ Validate syntax (Python compile check)
├─ Write back to file
└─ Log to journal
```

#### Phase 5: Session Complete
```
↓
Return LearningSession with:
├─ All analyses
├─ Applied changes
├─ Session summary
└─ Overall priority level (critical/high/medium/low)
```

### Data Structures

**AgentAnalysis** - Single agent's findings:
```python
@dataclass
class AgentAnalysis:
    agent_name: str              # "PythonVeteran", "DNDExpert", etc.
    agent_role: str              # Full role description
    timestamp: str               # ISO format
    component: str               # What was analyzed (e.g., "mission_balance")
    issues_found: List[str]      # Specific problems detected
    severity_scores: Dict[float] # Issue → 0-1 score (higher = worse)
    recommendations: List[str]   # What to do about issues
    code_changes: Optional[List] # Specific code modifications with file/line info
    confidence: float            # 0-1 how confident the agent is
```

**LearningSession** - Complete session results:
```python
@dataclass
class LearningSession:
    session_id: str                  # Timestamp-based ID
    timestamp: str                   # When session ran
    analyses: List[AgentAnalysis]    # All 5 agents' outputs
    overall_priority: str            # "critical"|"high"|"medium"|"low"
    approved_changes: List[Dict]     # Code changes that were applied
    journal_entry: str               # Summary written to journal
```

---

## Integration with Self-Learning Loop

### Integration Point: `src/self_learning.py`

The agent system runs as **PHASE 0** of the learning session, before regular studies:

```python
async def run_learning_session():
    """Execute one full learning session."""
    _journal("═══ LEARNING SESSION START ═══")
    logger.info("🧠 Self-learning session starting...")

    # PHASE 0: Run 5-Agent Autonomous Improvement System
    _journal("PHASE 0: 5-Agent Autonomous Improvement System")
    try:
        orchestrator = AgentOrchestrator()
        agent_session = await orchestrator.run_learning_cycle()
        
        if agent_session:
            _journal(f"Agent session complete: {len(agent_session.analyses)} analyses")
            for analysis in agent_session.analyses:
                _journal(f"  {analysis.agent_name}: ...")
        else:
            _journal("Agent session failed or returned no results")
    except Exception as e:
        logger.error(f"Agent orchestrator error: {e}")
        _journal(f"ERROR: Agent orchestrator failed: {e}")

    # PHASES 1-9: Regular studies continue...
    studies = [
        ("failure_analysis", _study_failure_logs, "failure_analysis"),
        ...
    ]
```

### Trigger Timing

- **When**: Every night during configured window (default 1-4 AM)
- **How often**: Once per night (tracked by date)
- **If it fails**: Session marked as complete, won't retry that night
- **If it succeeds**: Results logged and mission builder possibly improved

---

## Agent Analysis Output

### Journal Logging Example

```
[2024-03-28 02:15:00] [AGENTS] ═══ AGENT LEARNING CYCLE START ═══
[2024-03-28 02:15:00] [AGENTS] PHASE 1: Data Collection (02:15:00)
[2024-03-28 02:15:05] [AGENTS] Data collected: 6 categories
[2024-03-28 02:15:05] [AGENTS] PHASE 2: Parallel Agent Analysis (02:15:05)
[2024-03-28 02:15:27] [AGENTS] Specialist agents completed: 4/4
[2024-03-28 02:15:27] [AGENTS] PHASE 3: Project Manager Synthesis (02:15:27)
[2024-03-28 02:15:32] [AGENTS] PHASE 4: Code Change Application (02:15:32)
[2024-03-28 02:15:32] [AGENTS] SKIPPED: Extract helper method — confidence too low
[2024-03-28 02:15:33] [AGENTS] APPLIED: Fix timeout in json_generator (by PythonVeteran)
[2024-03-28 02:15:34] [AGENTS] ═══ AGENT LEARNING CYCLE COMPLETE ═══
[2024-03-28 02:15:34] [AGENTS] Changes applied: 1
```

### Analysis Object Format (JSON)

```json
{
  "agent_name": "PythonVeteran",
  "agent_role": "Code Quality Expert",
  "timestamp": "2024-03-28T02:15:10+00:00",
  "component": "code_quality",
  "issues_found": [
    "Async timeout not set on Ollama HTTP calls",
    "Type hints incomplete on generate_dynamic_title()"
  ],
  "severity_scores": {
    "Async timeout...": 0.75,
    "Type hints...": 0.4
  },
  "recommendations": [
    "Add timeout=120 to all httpx.AsyncClient() calls",
    "Add return type hints to function"
  ],
  "code_changes": [
    {
      "file": "mission_builder/json_generator.py",
      "type": "replace",
      "description": "Add timeout to Ollama calls",
      "old_code": "async with httpx.AsyncClient() as client:",
      "new_code": "async with httpx.AsyncClient(timeout=120) as client:",
      "breaking_change": false
    }
  ],
  "confidence": 0.85
}
```

---

## Code Change Safeguards

### Automatic Safeguards

1. **Confidence Threshold**: Only changes with confidence ≥ 0.8 applied
2. **Breaking Change Flag**: Changes marked `breaking_change: true` escalated to DM
3. **Syntax Validation**: Python files validated with `compile()` before write
4. **File Backup**: (Future) Could keep backup of changed files
5. **Single-File Changes**: One change per file per session (prevent cascades)

### Escalation to DM

Changes requiring DM approval are logged with `[DM QUESTION]` prefix:

```
[2024-03-28 02:15:33] [AGENTS] ESCALATED: Add @dataclass to MissionType — requires DM approval
```

The DM can then review in `logs/journal.txt` and make a decision.

### Prevented Changes

These types of changes are **never** applied automatically:

- ❌ Breaking API changes
- ❌ Changes to schema structure
- ❌ New dependencies
- ❌ Changes affecting mission generation output
- ❌ Low-confidence (< 0.8) recommendations
- ❌ Any change to self_learning.py (too risky)

### Safe Changes

These types of changes **can** be safely applied:

- ✅ Add utility functions (if no new dependencies)
- ✅ Fix timeout/error handling
- ✅ Add type hints
- ✅ Optimize existing loops
- ✅ Fix variable names (refactoring)
- ✅ Add comments/docstrings
- ✅ Extract repeated code into helpers

---

## Debug and Monitoring

### Checking Agent Session Results

Query the journal:

```bash
# See all agent activity
tail -100 logs/journal.txt | grep "\[AGENTS\]"

# See specific agent findings
grep "PythonVeteran\|DNDExpert" logs/journal.txt | tail -20

# See code changes applied
grep "APPLIED\|ESCALATED\|SKIPPED" logs/journal.txt
```

### Enable Verbose Logging

```python
import logging

# In your startup code:
logging.getLogger("src.agents").setLevel(logging.DEBUG)
logging.getLogger("src.agents.orchestrator").setLevel(logging.DEBUG)
```

### Testing Individual Agents

```python
from src.agents import PythonVeteranAgent

agent = PythonVeteranAgent()

# Read mission builder code
code_files = {
    "mission_types.py": open("src/mission_builder/mission_types.py").read(),
}

# Analyze
analysis = await agent.analyze_code(code_files)

# Inspect results
print(f"Issues found: {len(analysis.issues_found)}")
print(f"Recommendations: {analysis.recommendations[:3]}")
print(f"Confidence: {analysis.confidence:.0%}")
```

### Manual Orchestrator Run

For testing (outside the 1-4 AM window):

```python
from src.agents import AgentOrchestrator

orchestrator = AgentOrchestrator()
session = await orchestrator.run_learning_cycle()

# Review session
for analysis in session.analyses:
    print(f"\n{analysis.agent_name}:")
    print(f"  Component: {analysis.component}")
    print(f"  Issues: {len(analysis.issues_found)}")
    print(f"  Recommendations: {len(analysis.recommendations)}")
    print(f"  Confidence: {analysis.confidence:.0%}")
    
if session.approved_changes:
    print(f"\nApplied {len(session.approved_changes)} code changes")
    for change in session.approved_changes:
        print(f"  - {change['description']}")
```

---

## Future Enhancements

### Short-term (Next Sprint)

- [ ] Agent debate mode: Agents provide opposing viewpoints before PM decides
- [ ] Quality metrics: Track how recommendations impact next mission quality
- [ ] Confidence learning: Agents learn which recommendations actually help
- [ ] Code backup: Create snapshots before applying changes

### Medium-term (Roadmap)

- [ ] Fine-tuning: Train agents on Tower-Bot's specific domain
- [ ] Specialized knowledge: Let agents access campaign_docs for context
- [ ] Real-time monitoring: Agents track missions as they're played
- [ ] Player feedback loop: Agents learn from mission reception feedback
- [ ] Multi-language support: Generate agents for different game systems

### Long-term (Vision)

- [ ] Agents propose new mission types based on player behavior
- [ ] Autonomous NPC creation and faction management
- [ ] Campaign-wide narrative arc generation
- [ ] Dynamic difficulty tuning per player party
- [ ] Competitive agent evolution (agents vote on best improvements)

---

## Troubleshooting

### "Agent orchestrator error: ..."

Check if Ollama is running:

```bash
curl http://localhost:11434/api/tags
```

If down, restart:

```bash
# Windows
net start ollama

# Linux
systemctl start ollama

# macOS
brew services start ollama
```

### "Agent analysis failed"

Check individual agent logs in `src/agents/`:

```
logger.error(f"Agent {agent_name} failed: {result}")
```

### "Code changes not applying"

Verify file paths in orchestrator:

```python
# Check mission builder files exist
import os
files = os.listdir("src/mission_builder/")
print(files)

# Manually run file collection
data = await orchestrator._collect_code_files()
print(f"Collected {len(data)} files")
```

### "Changes keep failing validation"

Agents can propose invalid Python. Check the proposed change syntax:

```python
# Test if proposed code is valid Python
proposed_code = "..."  # The code change
try:
    compile(proposed_code, "test", "exec")
    print("✅ Valid Python")
except SyntaxError as e:
    print(f"❌ Syntax error: {e}")
```

---

## Summary

The 5-Agent Self-Learning System provides:

✅ **Autonomous Code Analysis** - Every night, 4 specialized agents analyze your code and mission system from different angles

✅ **Safe Improvements** - Only low-risk, high-confidence changes applied automatically; uncertain decisions escalated to DM

✅ **Full Transparency** - Every analysis, decision, and change logged to journal for review

✅ **Domain Expertise** - Each agent brings deep knowledge (Python, D&D rules, storytelling, architecture)

✅ **Continuous Improvement** - Iterative refinement of mission builder and campaign systems

✅ **Human Oversight** - DM retains complete control; can review and override any recommendation

This system enables Tower-Bot to continuously learn and improve without manual intervention, while maintaining the highest standards of code quality, game balance, and narrative excellence.

---

**For questions or issues, check `logs/journal.txt` first — all agent activity is logged there.**
