# Skill: Mission Quality Analysis
**Keywords:** mission, quality, analysis, review, improve, pattern, problem, fix, learn
**Category:** learning
**Version:** 1
**Source:** seed

## Purpose
This skill teaches the self-learning system HOW to analyze generated missions for quality issues and generate actionable improvements. Read this before running mission quality analysis.

---

## WHAT MAKES A GOOD MISSION

### 1. Faction Coherence
Good missions feel like they came from the contracting faction:
- **Iron Fang Consortium** — smuggling, relic retrieval, "acquisitions," debt collection
- **Argent Blades** — martial challenges, arena disputes, honor duels, protection contracts
- **Wardens of Ash** — patrol support, threat investigation, defensive operations
- **Serpent Choir** — divine contracts, artifact recovery, "spiritual services"
- **Obsidian Lotus** — assassination, blackmail, memory erasure, secrets
- **Glass Sigil** — research, prophecy investigation, information retrieval
- **Patchwork Saints** — community defense, missing persons, Warrens problems
- **Adventurers Guild** — bounties, delves, creature hunts, anything dangerous
- **Guild of Ashen Scrolls** — historical recovery, lost knowledge, preservation
- **Tower Authority/FTA** — enforcement, licensing disputes, official investigations
- **Wizards Tower** — magical research, artifact study, arcane anomalies

**Red Flag:** A Patchwork Saints mission about political blackmail, or an Argent Blades mission about sneaky assassination. These don't fit faction identity.

### 2. Tier Appropriateness
The mission tier should match the scope:
- **Local/Patrol** — street-level, one neighborhood, 1-7 days
- **Standard/Escort/Investigation** — district-level, multiple locations, 7-30 days
- **Rift/Dungeon/Major/Inter-Guild** — city-wide implications, serious danger, 30-90 days
- **Epic/Divine/Tower** — changes the city, involves gods or Tower itself, 90+ days

**Red Flag:** An "epic" tier mission to find someone's lost cat, or a "local" tier mission to prevent a divine incursion.

### 3. Reward Balance
Rewards should match difficulty and risk:
- **EC (Essence Coins):** 50-100 for local, 100-200 for standard, 200-400 for major, 500+ for epic
- **Kharma:** Minimum 20 for any mission. 20-50 local, 50-150 standard, 150-500 major, 500-2000 epic
- **LP (Legend Points):** Only for genuinely heroic or famous deeds

**Red Flag:** 5000 EC for a simple delivery, or 10 Kharma for clearing a dungeon.

### 4. Variety and Freshness
Missions should feel different from each other:
- Different starting locations (not always Soot & Cinder)
- Different objectives (not always "go kill the thing")
- Different complicating factors
- Different NPCs involved

**Red Flag:** Three missions in a row that all start with "The party is summoned to the Grand Forum" or all involve "clearing out the warehouse."

### 5. Plot Coherence
The mission should make sense:
- The objective is achievable by adventurers
- The timeline is reasonable
- The faction's motivation is clear
- There's a reason it's being posted NOW

**Red Flag:** "Investigate the corruption that has existed for centuries" (why now?) or "Retrieve the artifact from the god's personal realm" (how would adventurers do that?).

---

## WHAT MAKES A BAD MISSION

### Common Failures to Detect

1. **Faction Mismatch** — Mission type doesn't fit faction identity
2. **Tier Mismatch** — Scope doesn't match tier label
3. **Reward Imbalance** — Too much/little reward for difficulty
4. **Structural Repetition** — Same format, same locations, same NPCs
5. **Lore Violations** — Invented factions, wrong NPC names, impossible scenarios
6. **Rift Overuse** — Rift missions should be rare, not every other posting
7. **Vague Objectives** — "Deal with the problem" instead of specific goals
8. **Impossible Timelines** — Epic quest that expires in 3 days

### Pattern Detection Questions

When analyzing a set of missions, ask:
1. How many missions came from each faction? Is one faction dominating?
2. How many missions use the same starting location?
3. How many are combat-focused vs investigation vs social?
4. Are Rift missions appearing too frequently? (Should be <10% of missions)
5. Do reward amounts cluster around the same values?
6. Are the same NPC names appearing repeatedly?

---

## HOW TO GENERATE IMPROVEMENT RECOMMENDATIONS

### Format for Recommendations
```
MISSION QUALITY REPORT — [Date]

## Patterns Observed
- [3-5 specific patterns found in recent missions]

## Quality Issues Detected
- [List specific problems with examples]
- "[Mission Title]" had issue: [description]

## Recommendations for Improvement
1. [Specific, actionable change]
2. [Specific, actionable change]
3. [Specific, actionable change]

## What's Working Well
- [1-2 things that are good and should continue]

## Suggested Emphasis for Next Generation Cycle
- Generate more [mission type] missions
- Use faction [name] more often (underrepresented)
- Avoid [specific pattern] for the next cycle
```

### Actionable vs Non-Actionable Recommendations

**Good (Actionable):**
- "Generate 3 investigation missions in the next cycle to balance the combat-heavy batch"
- "Use Patchwork Saints as quest-giver more often — they had 0 missions this week"
- "Reduce Rift mission frequency from 20% to under 10%"

**Bad (Non-Actionable):**
- "Make missions better"
- "Be more creative"
- "Fix the problems"

---

## SUCCESS METRICS

A healthy mission ecosystem should show:
- **Faction Distribution:** No faction has >25% of missions, none has 0%
- **Type Diversity:** At least 5 different mission types active at any time
- **Tier Spread:** Majority local/standard (70%), some major (25%), rare epic (5%)
- **Rift Rarity:** <10% of missions involve Rifts
- **Completion Rate:** 50-70% of missions get completed (too high = too easy, too low = too hard)
- **Claim Rate:** 30-60% of missions get claimed by players before NPC parties

Track these over time. Trends matter more than snapshots.

---

## OUTPUT FORMAT

When the self-learning system studies missions, output a skill file like:

```markdown
# Skill: Mission Quality Insights — [Date]
**Keywords:** mission, quality, current, recent, balance, recommendation
**Category:** learned
**Version:** 1
**Source:** self-learned

## Recent Mission Analysis
[Summary of what was analyzed]

## Quality Score: [X/10]
[Brief justification]

## Issues Detected
[Specific problems]

## Recommendations
[Numbered action items]

## Next Cycle Focus
[What the mission generator should emphasize]
```

Keep it under 2000 characters. Be specific. Be actionable.
