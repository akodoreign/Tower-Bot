# Quick Start: 5-Agent Self-Learning System

**TL;DR**: Your mission builder now has 5 AI specialists that analyze and improve it every night during 1-4 AM. All decisions logged to `logs/journal.txt`.

---

## How It Works (Simple Version)

1. **Time Trigger**: System runs autonomously between 1-4 AM every night
2. **Analysis**: 5 agents examine mission builder from different angles
3. **Findings**: All findings logged to `logs/journal.txt`
4. **Safe Changes**: Minor, high-confidence improvements applied automatically
5. **Major Changes**: Anything uncertain escalated to you with `[DM QUESTION]` prefix

---

## Files to Know

| File | Purpose |
|------|---------|
| `logs/journal.txt` | **READ THIS FIRST** - All agent activity logged here |
| `AGENT_SYSTEM.md` | Complete reference guide (850 lines) |
| `PHASE_3_IMPLEMENTATION_SUMMARY.md` | Integration overview |
| `src/agents/learning_agents.py` | The 5 agent implementations |
| `src/agents/orchestrator.py` | Coordination system |

---

## The 5 Agents Explained

| Agent | What They Do | Example Finding |
|-------|-------------|-----------------|
| 🐍 **Python Veteran** | Code quality, performance | "Add timeout to Ollama calls" |
| ⚔️ **D&D Expert** | Rules compliance, balance | "Deadly missions success rate too high" |
| 📖 **D&D Veteran** | Story quality, NPC believability | "Add female NPCs to faction leaders" |
| 🏗️ **AI Critic** | Architecture, patterns | "Extract repeated timeout code into helper" |
| 👔 **Project Manager** | Orchestrates & decides | "Apply top 3 recommendations, escalate rest" |

---

## Checking Results

### After each night (1-4 AM):

```bash
# View all agent activity
tail -50 logs/journal.txt | grep "\[AGENTS\]"

# See what changed
grep "APPLIED:" logs/journal.txt | tail -10

# See what needs your review
grep "ESCALATED:" logs/journal.txt
```

### Full session log format:

```
[2024-03-28 02:15:00] [AGENTS] ═══ AGENT LEARNING CYCLE START ═══
[2024-03-28 02:15:05] [AGENTS] Data collected: 6 categories
[2024-03-28 02:15:10] [AGENTS] Specialist agents completed: 4/4
[2024-03-28 02:15:30] [AGENTS] APPLIED: Fix timeout in json_generator
[2024-03-28 02:15:31] [AGENTS] ESCALATED: Refactor mission_types — requires DM approval
[2024-03-28 02:15:35] [AGENTS] ═══ AGENT LEARNING CYCLE COMPLETE ═══
```

---

## What Gets Changed Automatically

✅ **SAFE** (Applied automatically):
- Add missing type hints
- Fix timeout values
- Add helper functions
- Fix variable names
- Add error handling

❌ **NOT SAFE** (Escalated to you):
- Change API signatures
- Modify data structures
- Remove code
- Change mission output
- Add new dependencies

---

## Configuration

### Change Learning Window

Currently runs 1 AM - 4 AM. To change:

```bash
# Edit .env or system environment:
LEARN_HOUR_START=2    # Start at 2 AM
LEARN_HOUR_END=3      # End at 3 AM
```

### Choose Agent Model

```bash
# In .env:
LEARNING_MODEL=qwen           # Default (fast, local)
# LEARNING_MODEL=mistral      # Alternative
```

---

## Testing (Manual Run)

Want to test agents outside the 1-4 AM window?

```python
import asyncio
from src.agents import AgentOrchestrator

async def test():
    orchestrator = AgentOrchestrator()
    session = await orchestrator.run_learning_cycle()
    
    if session:
        print(f"✅ Completed {len(session.analyses)} analyses")
        for analysis in session.analyses:
            print(f"  {analysis.agent_name}:")
            print(f"    Issues: {len(analysis.issues_found)}")
            print(f"    Recommendations: {len(analysis.recommendations)}")
            print(f"    Confidence: {analysis.confidence:.0%}")

asyncio.run(test())
```

---

## Common Questions

### Q: Will this break my bot?
**A:** No. Only low-risk changes applied automatically. Breaking changes escalated to you.

### Q: How do I disable it?
**A:** Doesn't run outside 1-4 AM. Can edit `src/self_learning.py` to comment out PHASE 0 orchestrator call.

### Q: What if an agent makes a bad recommendation?
**A:** It's just a recommendation in the journal. Only high-confidence stuff applied automatically.

### Q: Can I review changes before they're applied?
**A:** Yes! Set confidence threshold higher in `src/agents/orchestrator.py`, or implement an approval mode (future feature).

### Q: How do I know if agents are working?
**A:** Check `logs/journal.txt` after 1-4 AM. Look for `[AGENTS]` entries.

---

## What's Really Happening (Behind the Scenes)

```
1. Time Check (every 15 min): "Is it 1-4 AM? And haven't we run today?"
                              ↓
2. Data Collection:         Mission history, code files, NPC roster
                            ↓
3. Parallel Analysis:       4 agents analyze simultaneously
   - Python Vet: 6-8 sec
   - D&D Expert: 6-8 sec
   - D&D Veteran: 6-8 sec
   - AI Critic: 5-7 sec
                            ↓
4. Synthesis (Sequential):  Project Manager reads all 4 analyses
                            ↓
5. Code Changes:            Apply high-confidence, non-breaking changes
                            ↓
6. Escalation:              Flag anything uncertain for you to review
                            ↓
7. Journal Logging:         Record everything
                            ↓
8. Continue:                Regular learning studies proceed
```

---

## Expected Improvements (Over Time)

**Week 1**: Initial recommendations logged, you review manually

**Week 2**: Safe improvements applied, system adjusts based on impact

**Week 3**: Patterns detected, more confident recommendations

**Week 4+**: Continuous incremental improvements (code quality, balance, story)

---

## Integration with Previous Phases

**Phase 1 (Skills)**: Agents use skills in analysis and generation
**Phase 2 (Mission Types)**: Agents analyze your 18 mission types for quality
**Phase 3 (Agents)**: **← YOU ARE HERE** - Agents improve Phases 1 & 2

---

## Detailed Documentation

For deep dives:

1. **AGENT_SYSTEM.md** (850 lines)
   - Complete architecture
   - Each agent's expertise explained
   - Data structures
   - Debugging guide

2. **PHASE_3_IMPLEMENTATION_SUMMARY.md** (500 lines)
   - Integration overview
   - Testing instructions
   - Troubleshooting
   - Configuration details

---

## Summary

✅ **5 AI specialists** analyzing your system every night
✅ **Autonomous improvements** applied with safety guardrails
✅ **Full transparency** via journal logging
✅ **No disruption** to normal bot operation
✅ **Continuous learning** that gets better over time

The system is live and ready. Check `logs/journal.txt` after your first 1-4 AM window to see what your agents found!

---

**Questions?** Read `AGENT_SYSTEM.md` for comprehensive documentation.

**Want to test?** Run the manual testing code above outside 1-4 AM.

**Found issues?** Check `logs/journal.txt` first - all activity is logged there.

🤖 = Your Tower-Bot's new brain centers are now online.
