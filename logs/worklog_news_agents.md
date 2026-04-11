# News Agents Refactor Worklog

**Created:** 2026-04-04
**Status:** IN PROGRESS

## Goal

Refactor the news bulletin system into a multi-agent editorial team:

1. **News Editor Agent** — Factual news with creative writing skills + fact-checking
2. **Gossip Editor Agent** — Half-truths and rumors (NEVER saved to memory)
3. **Sports Columnist Agent** — Arena coverage across all dome venues
4. **Expandable Bulletins** — 3-line preview with "Read More" expansion

---

**2026-04-04 08:45** — Core modules created.

### Files Created

1. ✅ `campaign_docs/arena_venues.json` — 10 arena venues across districts
   - Arena of Ascendance (Guild Spires) — Premier combat
   - Night Pits (Warrens) — Illegal underground
   - Grand Forum Stage (Grand Forum) — Magical duels
   - Iron Maw Tracks (Markets Infinite) — Racing
   - Beast Dome (Residential Ring) — Creature shows
   - Sanctum Trials (Sanctum Quarter) — Divine duels
   - Ash Ring (Outer Wall) — Warden drills
   - Floating Ring (Markets Infinite) — Barge fights
   - Scrapworks Pit (Warrens) — Construct battles
   - Tower Colosseum (Tower Base) — Official FTA events

2. ✅ `src/agents/news_agents.py` — Three editorial agents
   - `NewsEditorAgent` — Factual news, fact-checked, saved to memory
   - `GossipEditorAgent` — Rumors, NOT saved to memory
   - `SportsColumnistAgent` — Arena coverage across all venues
   - `FactCheckerMixin` — Validates against NPC roster, gazetteer
   - Integrated cw-prose-writing principles into system prompts

3. ✅ `src/expandable_bulletin.py` — Discord expansion system
   - `BulletinStorage` — In-memory cache for full content
   - `ExpandBulletinView` — Persistent view with Read More button
   - `create_bulletin_message()` — Factory for embed + view
   - `handle_bulletin_interaction()` — For bot's on_interaction

4. ✅ `src/agents/__init__.py` — Updated exports

### Remaining Steps

- [ ] Wire `handle_bulletin_interaction()` into bot.py on_interaction
- [ ] Update news_feed.py to use new agents and expandable bulletins
- [ ] Add "gossip" and "sports" to generated_news_types.json
- [ ] Test all three agent types
- [ ] Verify gossip NOT saved to news_memory.txt

---

**2026-04-04 09:15** — Integration layer complete.

### Additional Files Created/Modified

5. ✅ `src/news_integration.py` — Bridge module for news_feed.py
   - `EditorType` enum (NEWS, GOSSIP, SPORTS, RANDOM)
   - `generate_editorial_bulletin()` — Main generation function
   - `post_editorial_bulletin()` — Post with memory management
   - Weighted random selection (60% news, 20% gossip, 20% sports)

6. ✅ `src/bot.py` — Added on_interaction handler
   - Handles `bulletin_expand:` custom IDs
   - Routes to `handle_bulletin_interaction()`

### Ready For Testing

To use the new system in news_feed.py, add to the bulletin cycle:

```python
from src.news_integration import post_editorial_bulletin, EditorType

# In the bulletin loop, occasionally use agent-based generation:
if random.random() < 0.40:  # 40% chance to use new agent system
    result = await post_editorial_bulletin(
        channel=news_channel,
        editor_type=EditorType.RANDOM,
        write_memory_func=_write_memory,
    )
    if result:
        continue  # Skip legacy generation
```

### Remaining Integration Steps

- [ ] Modify news_feed.py bulletin loop to use new system
- [ ] Test each agent type individually
- [ ] Verify Read More button expansion works
- [ ] Confirm gossip not saved to news_memory.txt

---

## File Summary

| File | Status | Purpose |
|------|--------|--------|
| `campaign_docs/arena_venues.json` | ✅ Created | 10 arena venues across districts |
| `src/agents/news_agents.py` | ✅ Created | NewsEditor, GossipEditor, SportsColumnist agents |
| `src/expandable_bulletin.py` | ✅ Created | Discord embed + Read More button system |
| `src/news_integration.py` | ✅ Created | Bridge module for news_feed.py |
| `src/agents/__init__.py` | ✅ Updated | Export new agents |
| `src/bot.py` | ✅ Updated | on_interaction handler for bulletin expansion |
| `scripts/test_news_agents.py` | ✅ Created | Test script for agents |

## Next Steps

1. **Test agents**: `python scripts/test_news_agents.py --type all`
2. ~~**Integrate into news_feed.py**: Use `post_editorial_bulletin()` in bulletin loop~~
3. **Restart bot**: Apply changes
4. **Monitor**: Watch for gossip NOT being saved, Read More working

---

**2026-04-04 09:45** — Integration into aclient.py complete.

### Changes to src/aclient.py

- Added import: `from src.news_integration import post_editorial_bulletin, EditorType`
- Added `import random` 
- Added `_write_memory` to news_feed imports
- Modified `news_feed_loop()`:
  - Startup bulletins: 35% chance to use agent system
  - Main loop bulletins: 35% chance to use agent system
  - Agent bulletins use `post_editorial_bulletin()` with expandable Read More buttons
  - Gossip bulletins automatically excluded from memory via `save_to_memory=False`

### Integration Complete ✅

The system is now wired. On restart:
- 35% of bulletins will use the new agent system (news/gossip/sports)
- Gossip will appear with 👁️ icon and purple color, NOT saved to memory
- Sports will appear with 🏟️ icon and gold color
- All agent bulletins have "Read More" button for full content
- 65% of bulletins use the legacy system (unchanged)

---

## Requirements

### News Editor Agent
- Uses creative writing skills (cw-prose-writing style)
- Has fact-checking pass (NPC factions, locations, dead/alive status)
- Polished, grounded news bulletins
- Output IS saved to memory for continuity

### Gossip Editor Agent
- Produces rumors, half-truths, unverified reports
- May contradict facts or speculate wildly
- Marked clearly as gossip/rumor
- Output is NOT saved to memory (prevents pollution)
- Fun unreliable narrator voice

### Sports Columnist Agent
- Covers arena events across multiple venues
- Different arena types: combat, racing, magical duels, beast shows, etc.
- Personality-driven sports commentary
- Results, standings, upcoming events
- New arenas needed in different districts

### Expandable Bulletins
- Discord embed with 3-line preview
- "Read More" button/interaction to expand
- Full story available on click
- Works with all bulletin types

---

## Steps

### Phase 1: Research & Design
- [ ] Read creative writing skills structure
- [ ] Read current arena_season.py
- [ ] Read existing agent framework in src/agents/
- [ ] Design agent base class for news editors
- [ ] Design arena/venue data structure

### Phase 2: Arena System Expansion
- [ ] Create arena_venues.json with multiple arenas
- [ ] Add arena types: Combat, Racing, Magical Duels, Beast Shows, etc.
- [ ] Assign arenas to districts with unique flavor
- [ ] Update arena_season.py to use new venue system

### Phase 3: News Agent Framework
- [ ] Create src/agents/news_agents.py
- [ ] Implement NewsEditorAgent base class
- [ ] Implement FactChecker mixin
- [ ] Implement GossipEditorAgent
- [ ] Implement SportsColumnistAgent

### Phase 4: Expandable Bulletins
- [ ] Design Discord embed format with preview
- [ ] Create bulletin storage for full content
- [ ] Add View interaction for expansion
- [ ] Update news_feed.py to use new system

### Phase 5: Integration
- [ ] Wire agents into news_feed.py
- [ ] Update bulletin posting logic
- [ ] Test all agent types
- [ ] Verify gossip NOT saved to memory

---

## Progress Log

**2026-04-04 08:15** — Research complete. Starting implementation.

### Architecture Decisions

1. **Agent Base**: Extend `BaseAgent` from `src/agents/base.py`
2. **Skills Integration**: Inject cw-prose-writing principles into system prompts
3. **Fact Checking**: Build as a mixin that queries NPC roster, gazetteer, graveyard
4. **Gossip Memory**: Add `save_to_memory=False` flag to bulletin generation
5. **Expandable Bulletins**: Use Discord embeds with buttons (View) + full_content storage
6. **Arena System**: Create `arena_venues.json` with multiple venue types/districts

### New Files To Create

- `campaign_docs/arena_venues.json` — Multi-venue arena data
- `src/agents/news_agents.py` — NewsEditor, GossipEditor, SportsColumnist agents
- `src/expandable_bulletin.py` — Discord embed + interaction for read more

---

