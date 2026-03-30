# Worklog: Mission Critic Agent
**Started:** 2026-03-29 08:50 UTC
**Status:** IN PROGRESS

## Task Summary
Create a mission/module critic agent that:
1. Runs iteratively at the end of each nightly self-learning session
2. Based on mission and module building expertise
3. Spends 50% of time detecting and eliminating hallucinations
4. Outputs actionable corrections for the generation system

## Steps
- [ ] 1. Create hallucination detection skill (defines what to look for)
- [ ] 2. Create mission_critic skill (expert reviewer perspective)
- [ ] 3. Add _critique_mission_generation() function to self_learning.py
- [ ] 4. Add _detect_hallucinations() helper function
- [ ] 5. Wire critic to run at END of learning session (after other studies)
- [ ] 6. Output learned corrections that feed back into generation
- [ ] 7. Update tower-bot skill documentation

## Hallucination Categories to Detect
1. **Invented Factions** — factions not in the canonical list
2. **Wrong NPC Names** — NPCs that don't exist in roster, name mismatches between sections
3. **Location Errors** — places not in city_gazetteer.json
4. **Lore Violations** — Rifts in wrong districts, wrong faction behaviors
5. **Mechanical Errors** — impossible stat blocks, wrong DCs, broken math
6. **Structural Failures** — READ ALOUD blocks, missing stat blocks, wrong formats

## Progress Log
### 2026-03-29 08:50 UTC
- Starting task
- Will create teaching skills first, then the code
