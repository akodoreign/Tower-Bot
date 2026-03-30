# Skill: Missions & Mission Board
**Keywords:** mission, missions, quest, board, claim, resolve, complete, fail, expire, bounty, reward, objective, NPC, contract
**Category:** systems
**Version:** 1
**Source:** seed

## How Missions Work

The Mission Board is a living system that generates, posts, and resolves missions automatically.

### Mission Lifecycle
1. **Generation** — The bot creates missions using Ollama, drawing on current world state (news, factions, NPCs, rift activity).
2. **Posting** — Missions appear in the mission board channel with details: title, description, objectives, reward, difficulty, deadline.
3. **Claiming** — Players react with ⚔️ to claim a mission. Only one player/group can claim at a time.
4. **Resolution** — Players use `/resolvemission` to report outcomes. The DM can also resolve missions.
5. **Expiry** — Unclaimed missions expire after their deadline. NPC adventurer parties may claim expired missions.

### Mission Types
Missions are categorized by type — generated dynamically based on world state. Types include things like Cargo Recovery, Rift Investigation, Faction Diplomacy, Bounty Hunt, Escort, Sabotage, etc.

### NPC Mission Claims
If a mission goes unclaimed, NPC adventurer parties may pick it up. Their success/failure is simulated and the results posted to the mission results channel. This keeps the world feeling alive.

### Personal Missions
Individual characters can receive personal missions tied to their backstory, faction ties, or recent activities. These cycle on 1-3 day intervals.

### Bounties
Separate from missions — bounties target specific NPCs or creatures. They appear on the bounty board and have their own reward structure.

## Oracle Guidance on Missions
When players ask about missions, the Oracle should:
- Reference actual active missions from mission_memory.json
- Not invent missions that don't exist
- Hint at upcoming opportunities without spoiling specifics
- Acknowledge completed missions and their consequences
