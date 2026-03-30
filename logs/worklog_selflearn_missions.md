# Worklog: Self-Learning Mission Improvement System
**Started:** 2026-03-29 02:00 UTC
**Status:** ✅ COMPLETE

## Task Summary
Teach the bot's self-learning system to:
1. Study generated missions each night
2. Identify quality patterns and problems
3. Iteratively improve mission generation
4. Create new mission type variations

## Steps
- [x] 1. Read current self_learning.py to understand architecture
- [x] 2. Read mission generation code (mission_board.py, mission_builder)
- [x] 3. Read existing mission types (generated_mission_types.json)
- [x] 4. Read existing skills (module_quality.md, missions.md)
- [x] 5. Create mission_quality_analysis.md skill — teaches bot HOW to analyze missions
- [x] 6. Create mission_type_innovation.md skill — teaches bot HOW to create new mission types
- [x] 7. Add _study_mission_quality() function to self_learning.py
- [x] 8. Add _study_mission_type_variety() function to self_learning.py
- [x] 9. Wire new study functions into nightly learning cycle
- [x] 10. Update worklog and verify

## Files Created/Modified

### New Skill Files (Teaching Documents)
| File | Purpose |
|------|---------|
| `campaign_docs/skills/mission_quality_analysis.md` | Teaches bot HOW to recognize good vs bad missions, faction coherence, tier appropriateness, reward balance, variety |
| `campaign_docs/skills/mission_type_innovation.md` | Teaches bot HOW to generate fresh mission types using combination, faction lens, complication, and inversion methods |

### Modified Code
| File | Changes |
|------|---------|
| `src/self_learning.py` | Added `_study_mission_quality()` and `_study_mission_type_variety()` functions; wired into nightly study cycle |

## How It Works

### Nightly Learning Cycle (1-2 AM)
The self-learning loop now runs 8 study functions:
1. `world_state` — Overall campaign health assessment
2. `news_memory` — Current events digest
3. `mission_patterns` — Basic mission outcome patterns
4. **NEW** `mission_quality` — Deep quality analysis (faction balance, completion rates, type seeds)
5. **NEW** `mission_types` — Generate 8 fresh mission type seeds for underrepresented areas
6. `npc_roster` — NPC landscape mapping
7. `faction_reputation` — Political standings
8. `conversation_logs` — Player question patterns

### What Gets Generated Each Night
The new functions create two skill files:
- `learned_mission_quality_YYYYMMDD.md` — Quality report with score, issues, recommendations
- `learned_mission_type_ideas_YYYYMMDD.md` — Fresh mission type seeds ready for use

### How Mission Types Improve Over Time
1. `_study_mission_quality()` analyzes recent missions for:
   - Faction distribution (flags imbalance)
   - Completion rates (flags difficulty issues)
   - Player vs NPC claim ratio
   - Quality of current type seeds

2. `_study_mission_type_variety()` generates new seeds by:
   - Finding underrepresented factions
   - Tracking overused objective words (retrieve, escort, etc.)
   - Applying innovation methods (combination, faction lens, complication, inversion)
   - Outputting 8 fresh seed lines

3. The daily `refresh_mission_types_if_needed()` in mission_board.py already picks from generated types — so new seeds get used automatically

### Manual Integration (Optional)
The DM can review `logs/journal.txt` for:
- Quality scores and recommendations
- New type seeds to manually add to `generated_mission_types.json`
- [DM QUESTION] flags for uncertain decisions

## Testing
To verify the system works:
1. Wait for 1-2 AM learning window, OR
2. Manually call `await run_learning_session()` from Python
3. Check `campaign_docs/skills/` for new `learned_mission_*` files
4. Check `logs/journal.txt` for session output

## Progress Log
### 2026-03-29 02:00 UTC
- Started task
- Read existing code and skills

### 2026-03-29 02:15 UTC
- Created mission_quality_analysis.md skill (teaching document)
- Created mission_type_innovation.md skill (teaching document)

### 2026-03-29 02:25 UTC
- Added _study_mission_quality() function (~95 lines)
- Added _study_mission_type_variety() function (~90 lines)
- Wired into studies list
- Verified code compiles correctly

### 2026-03-29 02:30 UTC
- Task complete!
