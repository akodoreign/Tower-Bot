---
name: tower-bot-files
description: "Self-documenting file map for the Tower of Last Chance Discord bot. Use this skill to understand the project structure, find specific files, and know what each file does. CRITICAL: After ANY file creation, deletion, or significant refactor, UPDATE THIS SKILL to reflect the changes. This skill is the single source of truth for 'where is X' and 'what does Y do'."
---

# Tower Bot File Map — Self-Documenting Reference

> **MAINTENANCE RULE**: Whenever you create, delete, move, or significantly refactor a file in this project, UPDATE THIS SKILL. Add new files, remove deleted ones, update descriptions for changed functionality. This skill must stay accurate or it becomes useless.

## Project Root
`C:\Users\akodoreign\Desktop\chatGPT-discord-bot`

---

## Source Code (`src/`)

### Core Architecture

| File | Size | What It Does |
|------|------|--------------|
| `aclient.py` | 40KB | The heart of the bot. `DiscordClient` class, all background loops (news, missions, images, NPC lifecycle), message queue processing. Start here to understand how the bot runs. |
| `bot.py` | 2.2KB | Lightweight cog loader. Imports modules from `COG_MODULES` list, calls `setup(client)` on each, registers `on_ready`. |
| `log.py` | 2.7KB | Logging configuration. |
| `providers.py` | 18KB | AI provider abstraction (free/openai/claude). Handles API calls to different LLM backends. |
| `personas.py` | 2.7KB | Chat persona definitions for /switchpersona. |

### Cog Modules (`src/cogs/`)

Each cog exports a `setup(client)` function that registers slash commands on `client.tree`.

| File | Commands | What It Does |
|------|----------|--------------|
| `chat.py` | `/chat`, `/reset` | Main chat interface with Tower Oracle, conversation reset |
| `character.py` | `/setcharprofile`, `/showcharprofile`, `/setcharappearance`, `/showcharappearance` | Player character profile and appearance management |
| `missions.py` | `/resolvemission` | Mission resolution, reaction handlers for claims |
| `economy.py` | `/finances`, `/prices` | Economy queries, price lookups |
| `rules_lookup.py` | `/rules`, `/spell` | D&D 5e rules and spell lookup via RAG |
| `images.py` | `/draw`, `/drawscene`, `/gearrun` | Image generation commands using A1111 |
| `world.py` | `/factionrep`, `/partyrep`, `/style` | Faction reputation, party reputation, style queries |
| `admin.py` | `/sync`, `/provider`, `/switchpersona`, `/private`, `/replyall`, `/help`, `/towerbay`, `/myauctions`, `/newsdraft` | Admin and utility commands, bulletin approval view |

### Content Generation

| File | Size | What It Does |
|------|------|--------------|
| `news_feed.py` | 115KB | **THE BIG ONE.** Hourly bulletin generation, Rift state machine, district aesthetics, story image prompts, economy tick dispatching. All AI-generated news content flows through here. |
| `mission_board.py` | 62KB | Mission generation and lifecycle. Posting, claims, NPC completions, expiry, faction assignment. |
| `mission_module_gen.py` | 5KB | Compatibility wrapper for `mission_builder/` package. Unchanged external API. |
| `bounty_board.py` | 10KB | Bounty post generation and tracking. |
| `missing_persons.py` | 9.5KB | Missing persons notice generation. |
| `arena_season.py` | 12KB | Arena match simulation and results. |
| `dome_weather.py` | 18KB | Dome weather state machine and reports. |
| `faction_calendar.py` | 12KB | Faction event calendar and announcements. |

### Mission Builder Package (`src/mission_builder/`)

Modular mission document generation, refactored from monolithic `mission_module_gen.py`.

| File | What It Does |
|------|--------------|
| `__init__.py` | Orchestrator. Exports `generate_mission_module()`, coordinates all sub-generators. |
| `locations.py` | Gazetteer integration. Pulls location details from `city_gazetteer.json`. |
| `leads.py` | Investigation lead generation. Creates clues, red herrings, faction connections. |
| `encounters.py` | Combat encounter generation. Stat blocks, environmental hazards, tactical notes. |
| `npcs.py` | NPC dialogue and secrets. Pulls from `npc_roster.json`, generates conversation hooks. |
| `rewards.py` | Loot tables and consequences. EC/Kharma rewards, faction rep changes, item drops. |
| `docx_builder.py` | Document formatting. Converts generated content to formatted .docx output. |

### Economy & Markets

| File | Size | What It Does |
|------|------|--------------|
| `tower_economy.py` | 33KB | TowerBay auction house, TIA stock market simulation. |
| `ec_exchange.py` | 12KB | EC/Kharma exchange rate simulation with drift and shocks. |
| `player_listings.py` | 19KB | Player-created TowerBay auction items. |

### NPC Systems

| File | Size | What It Does |
|------|------|--------------|
| `npc_appearance.py` | 31KB | NPC visual descriptions for SD image prompts. |
| `npc_lifecycle.py` | 35KB | Daily NPC roster events — arrivals, departures, deaths, injuries. |
| `npc_consequence.py` | 12KB | Post-bulletin scanner for NPC deaths/injuries mentioned in news. |
| `party_profiles.py` | 19KB | Adventurer party generation and profile management. |

### RAG & Knowledge

| File | Size | What It Does |
|------|------|--------------|
| `tower_rag.py` | 27KB | RAG search over `campaign_docs/` for `/chat` context injection. |
| `rules_agent.py` | 13KB | D&D 5e 2024 rules lookup via RAG + Ollama. |
| `skill_loader.py` | 8KB | Skill matching and injection for `/chat` context. |

### Supporting Systems

| File | Size | What It Does |
|------|------|--------------|
| `memory_strip.py` | 5KB | Strips emojis/fluff from bulletins before saving to news memory. |
| `bulletin_embeds.py` | 3KB | Wraps text bulletins in themed Discord embeds. |
| `style_agent.py` | 16KB | Character/faction clothing and style descriptions. |
| `faction_reputation.py` | 9KB | Faction reputation tracking and tier calculations. |
| `character_profiles.py` | 5KB | Player character profile CRUD. |
| `character_monitor.py` | 10KB | D&D Beyond character sheet change detection. |
| `image_ref.py` | 8KB | Reference image storage for img2img generation. |
| `ollama_busy.py` | 2KB | Ollama busy-state tracking to prevent request collisions. |
| `self_learning.py` | 15KB | Nightly self-learning loop (prompt improvement). |

---

## Campaign Data (`campaign_docs/`)

### Core Data Files

| File | Format | What It Stores |
|------|--------|----------------|
| `npc_roster.json` | JSON | All alive/injured NPCs with factions, roles, locations, secrets |
| `npc_graveyard.json` | JSON | Dead NPCs (moved here from roster on death) |
| `city_gazetteer.json` | JSON | All city districts, establishments, transport, ring structure |
| `Updated_Pantheon_Ranks(import).csv` | CSV | All deities, faithlight scores, domains, alliances |
| `character_memory.txt` | Text | Player character records (NAME/CLASS/SPECIES/PLAYER blocks) |
| `faction_reputation.json` | JSON | Faction rep scores and event history |

### State Files

| File | Format | What It Tracks |
|------|--------|----------------|
| `news_memory.txt` | Text | Cleaned factual log of posted bulletins (max 40 entries) |
| `mission_memory.json` | JSON | All missions (active + resolved) |
| `rift_state.json` | JSON | Active Rift state machine data |
| `arena_season.json` | JSON | Current arena season standings |
| `dome_weather.json` | JSON | Current weather state |
| `ec_exchange.json` | JSON | Current EC/Kharma exchange rate |
| `tia.json` | JSON | TIA stock market sector values |
| `faction_calendar.json` | JSON | Upcoming faction events |
| `missing_persons.json` | JSON | Active missing persons cases |
| `bounty_board.json` | JSON | Active bounties |
| `player_listings.json` | JSON | Player TowerBay auction items |
| `economy_cadence.json` | JSON | Last-post timestamps for TowerBay/TIA/exchange |
| `generated_news_types.json` | JSON | AI-generated daily bulletin type seeds |
| `generated_mission_types.json` | JSON | AI-generated daily mission type seeds |

### Profile Directories

| Directory | Contents |
|-----------|----------|
| `npc_appearances/` | Individual NPC visual descriptions (JSON per NPC) |
| `party_profiles/` | Adventurer party profiles (JSON per party) |
| `char_snapshots/` | D&D Beyond character snapshots |

### Reference Documents

| File | What It Contains |
|------|------------------|
| `MISSION_BOARD_DM.txt` | Current mission board state (parsed by news_feed for context) |
| `MISSION_TYPES.md` | Master list of mission archetypes |
| `NPC_TEMPLATES.md` | NPC generation templates |
| `LOCATION_GUIDE.md` | District and location writing guide |

---

## Backups (`backups/`)

| File | What It Preserves |
|------|-------------------|
| `bot_before_cog_split_20260316.py` | Original monolithic bot.py before cog refactor |
| `mission_module_gen_before_leads_20260327.py` | mission_module_gen.py before mission_builder refactor |

---

## Skills (`skills/`)

Claude skills for this project. Copy to your Claude skills directory to use.

| Skill | Purpose |
|-------|---------|
| `tower-bot-files/` | THIS FILE. Self-documenting file map. |
| `cw-prose-writing/` | Narrative prose writing principles for AI generation |
| `cw-news-gen/` | News bulletin generation guidelines |
| `cw-mission-gen/` | Mission content generation guidelines |

---

## Logs (`logs/`)

| File | What It Contains |
|------|------------------|
| `*.log` | Bot runtime logs (auto-cleaned, 7-day retention) |
| `*_worklog.md` | Operation worklogs for multi-step tasks (resumable) |

---

## Configuration

| File | What It Does |
|------|--------------|
| `.env` | Environment variables (tokens, channel IDs, model names) |
| `requirements.txt` | Python dependencies |
| `system_prompt.txt` | Legacy system prompt (mostly unused — Tower RAG is primary now) |

---

## Update Checklist

When you modify the project, check these:

- [ ] **Created a new file?** Add it to the appropriate section above.
- [ ] **Deleted a file?** Remove it from this skill.
- [ ] **Moved a file?** Update the path.
- [ ] **Changed what a file does?** Update the description.
- [ ] **Added a new directory?** Add a new section.
- [ ] **Refactored a module into a package?** Document the package structure.

**This skill is only useful if it's accurate. Keep it updated.**
