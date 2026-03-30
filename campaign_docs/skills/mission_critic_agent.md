# Skill: Mission Creation Critic Agent
**Keywords:** critic, review, quality, assessment, module, mission, expert, feedback, improve
**Category:** validation
**Version:** 1
**Source:** seed

## Purpose
This skill defines the Mission Critic Agent — an expert reviewer that runs at the end of each nightly self-learning session. The critic evaluates recent missions and modules from the perspective of an experienced D&D module designer and campaign runner.

The critic has TWO primary functions:
1. **Hallucination Elimination (50% of focus)** — Detect and flag content that contradicts lore
2. **Quality Assessment (50% of focus)** — Evaluate playability, structure, and design

---

## THE CRITIC'S PERSPECTIVE

The critic reviews content as if they are:
- A veteran DM who has run 100+ sessions
- A professional module editor at a game publisher
- A lore keeper who knows the Undercity intimately
- A player advocate who wants fun, playable content

The critic is **constructive but unsparing**. They call out problems directly but always explain WHY something is wrong and HOW to fix it.

---

## REVIEW PROCESS

### Step 1: Gather Evidence
Before critiquing, load canonical sources:
- `npc_roster.json` — all valid NPC names
- `city_gazetteer.json` — all valid locations
- `faction_reputation.json` — current faction standings
- `mission_memory.json` — recent mission data
- `generated_mission_types.json` — current type seeds
- Module files in `generated_modules/`

### Step 2: Hallucination Sweep (50% of time)
Systematically check for:

**Faction Validation:**
```
FOR each faction name mentioned:
  IF not in canonical list:
    FLAG as INVENTED_FACTION
  IF faction behavior contradicts their nature:
    FLAG as FACTION_VIOLATION
```

**NPC Validation:**
```
FOR each NPC name mentioned:
  IF not in npc_roster.json AND not clearly a new character:
    FLAG as INVENTED_NPC
  IF same NPC has different names in document:
    FLAG as NAME_INCONSISTENCY
```

**Location Validation:**
```
FOR each location mentioned:
  IF not in city_gazetteer.json:
    FLAG as INVENTED_LOCATION
  IF location placed in wrong district:
    FLAG as LOCATION_ERROR
```

**Rift Validation:**
```
FOR each Rift mention:
  IF district is NOT (Warrens OR Outer Wall):
    FLAG as CRITICAL_LORE_VIOLATION
```

### Step 3: Quality Assessment (50% of time)

**Structure Check:**
- Does it follow the 3-act structure?
- Are there 5-7 scenes (not 15)?
- Is estimated runtime ~2 hours?
- Are all stat blocks present and complete?

**Playability Check:**
- Can a DM run this without extensive prep?
- Are DCs and rewards balanced?
- Are there multiple valid approaches?
- Is there at least one non-combat resolution?

**Engagement Check:**
- Is the hook compelling?
- Is the complication interesting?
- Are NPCs memorable (not generic)?
- Does the climax feel earned?

**Consistency Check:**
- Do rewards match difficulty claims?
- Do enemy CRs match encounter tier?
- Are time estimates realistic?
- Does the plot make logical sense?

---

## CRITIQUE OUTPUT FORMAT

The critic generates a structured report:

```markdown
# Mission Critic Report — [Date]

## Summary
- Missions Reviewed: [N]
- Modules Reviewed: [N]
- Critical Issues: [N]
- Hallucinations Detected: [N]
- Quality Score: [X/10]

## Hallucination Report

### Critical (Must Fix)
1. [INVENTED_FACTION] "Shadow Guild" referenced in mission "Debt Collection"
   - Line: "The Shadow Guild needs your help..."
   - Fix: Replace with canonical faction (Obsidian Lotus fits this context)

2. [RIFT_VIOLATION] Rift placed in Grand Forum
   - Line: "A small Rift has opened near the fountain..."
   - Fix: Rifts can ONLY appear in Warrens or Outer Wall

### High (Should Fix)
[...]

### Medium (Consider Fixing)
[...]

## Quality Report

### Structural Issues
1. Mission "Warehouse Heist" has 12 scenes for a 2-hour session
   - Fix: Consolidate to 6-7 scenes max

### Playability Issues
1. Module "Serpent's Contract" has no stat block for the boss
   - Fix: Add complete 5e 2024 stat block

### Balance Issues
1. Mission "Local Courier Job" awards 500 EC
   - Expected for local tier: 50-100 EC
   - Fix: Reduce to 75 EC

## Correction Directives

These should be injected into future generation prompts:

1. NEVER reference "Shadow Guild" — use Obsidian Lotus instead
2. NEVER place Rifts outside Warrens/Outer Wall
3. ALWAYS provide stat blocks for all combat enemies
4. LIMIT scenes to 7 maximum for 2-hour modules
5. [...]

## Positive Observations

What's working well (reinforce these patterns):
- NPC dialogue quality has improved
- Location variety is good
- Faction distribution is balanced
```

---

## CORRECTION PERSISTENCE

The critic's corrections should persist and influence future generation:

### Immediate Corrections
Saved to `campaign_docs/generation_corrections.json`:
```json
{
  "last_updated": "2026-03-29",
  "forbidden_terms": [
    {"term": "Shadow Guild", "replacement": "Obsidian Lotus", "reason": "invented faction"},
    {"term": "Culinary Council", "replacement": null, "reason": "invented faction"}
  ],
  "rift_rules": {
    "allowed_districts": ["Warrens", "Outer Wall"],
    "forbidden_districts": ["Markets Infinite", "Grand Forum", "Guild Spires", "Sanctum Quarter"]
  },
  "structural_rules": [
    "Maximum 7 scenes per 2-hour module",
    "All enemies must have stat blocks",
    "No READ ALOUD blocks"
  ],
  "recent_hallucinations": [
    {"type": "faction", "value": "Shadow Guild", "date": "2026-03-29", "mission": "Debt Collection"}
  ]
}
```

### Long-Term Learning
Patterns that appear 3+ times become PERMANENT RULES:
- Added to the generation system prompt
- Added to validation checks
- Logged for DM review

---

## ITERATIVE IMPROVEMENT

The critic runs AFTER other learning functions because it needs their output:

```
1:00 AM — Learning session starts
  → _study_world_state()
  → _study_news_memory()
  → _study_mission_patterns()
  → _study_mission_quality()
  → _study_mission_type_variety()
  → _study_npc_roster()
  → _study_faction_reputation()
  → _study_conversation_logs()
  
1:45 AM — Critic phase begins
  → _detect_hallucinations()     # 50% of critic time
  → _critique_mission_quality()  # 50% of critic time
  → Save corrections
  → Generate critic report skill file
  
2:00 AM — Session ends
```

Each night builds on previous corrections. Over time:
- Hallucinations decrease
- Quality improves
- Patterns stabilize
- Generation becomes more reliable

---

## DM REVIEW INTEGRATION

The critic report is saved as a learned skill AND logged to journal:

```
[DM REVIEW NEEDED] Critic found 3 critical hallucinations
  - See: campaign_docs/skills/learned_critic_report_20260329.md
  - Action items flagged for human review
```

The DM can:
1. Review the report in the skill file
2. Approve/reject corrections
3. Add manual corrections to `generation_corrections.json`
4. Pin certain rules as permanent

---

## SUCCESS METRICS

The critic tracks its own effectiveness:

**Hallucination Rate:**
- Week 1: X hallucinations per mission
- Week 2: Y hallucinations per mission (target: decreasing)

**Repeat Offenders:**
- Which hallucination types keep appearing?
- Are corrections being applied?

**Quality Trend:**
- Average quality score over time
- Specific improvements (stat blocks, structure, etc.)

Report these in the weekly summary section of the critic report.
