---
name: tower-bot
description: "ALWAYS LOAD FIRST for ANY work on the Tower of Last Chance Discord bot. Contains the complete directory map, every slash command with source location, cog wiring, background loop schedule, known bugs, and critical conventions. Covers: editing bot code, cog modules, news_feed.py, mission_board.py, aclient.py, src/ files, campaign_docs, agents, mission_builder, debugging, slash commands, Ollama/A1111 integrations, or any mention of 'Tower bot', 'Undercity', 'discord bot', 'mission board', 'news feed', 'cog', or project path chatGPT-discord-bot."
---

# Tower of Last Chance — Master Project Skill

**Project root:** `C:\Users\akodoreign\Desktop\chatGPT-discord-bot`
**Debug log:** `logs/debug_log.md` — all spotted bugs tracked there

---

## Boot Sequence

```
main.py
  └─ src/bot.py: run_discord_bot()
       ├─ Imports each module in COG_MODULES, calls module.setup(discordClient)
       ├─ Registers on_ready (persistent views, process_messages task)
       └─ discordClient.run(token)

src/aclient.py: DiscordClient
  ├─ __init__: creates client.tree, provider manager, message queue
  ├─ setup_hook(): copy_global_to(guild) + tree.sync() — BEFORE gateway connect
  └─ on_ready → starts background loops (see below)
```

**setup_hook is canonical for command sync — never revert to on_ready sync.**

---

## COG_MODULES Load Order (`src/bot.py`)

| # | Module | File | Commands |
|---|--------|------|----------|
| 1 | `src.cogs.chat` | [src/cogs/chat.py](src/cogs/chat.py) | `/chat`, `/reset` |
| 2 | `src.cogs.character` | [src/cogs/character.py](src/cogs/character.py) | `/setcharprofile`, `/showcharprofile`, `/setcharappearance`, `/showcharappearance` |
| 3 | `src.cogs.missions` | [src/cogs/missions.py](src/cogs/missions.py) | `/resolvemission`, `on_raw_reaction_add` |
| 4 | `src.cogs.economy` | [src/cogs/economy.py](src/cogs/economy.py) | `/finances`, `/prices` |
| 5 | `src.cogs.rules_lookup` | [src/cogs/rules_lookup.py](src/cogs/rules_lookup.py) | `/rules`, `/spell` |
| 6 | `src.cogs.images` | [src/cogs/images.py](src/cogs/images.py) | `/draw`, `/drawscene`, `/gearrun`, `/pin`, `/refstats` |
| 7 | `src.cogs.world` | [src/cogs/world.py](src/cogs/world.py) | `/factionrep`, `/partyrep`, `/style` |
| 8 | `src.cogs.admin` | [src/cogs/admin.py](src/cogs/admin.py) | `/sync`, `/provider`, `/switchpersona`, `/private`, `/replyall`, `/help`, `/towerbay`, `/myauctions`, `/newsdraft`, `/archive`, `/riftlist`, `/sealrift` |
| 9 | `src.cogs.module_gen` | [src/cogs/module_gen.py](src/cogs/module_gen.py) | `/genmodule` |
| 10 | `src.cogs.skills` | [src/cogs/skills.py](src/cogs/skills.py) | `/skills` |
| 11 | `src.patch_approval` | [src/patch_approval.py](src/patch_approval.py) | Patch review reactions |

**To add a new command:** add it inside `setup(client)` using `@client.tree.command()` in the appropriate cog, then run `/sync` in Discord.

---

## All Slash Commands — Full Map

| Command | Cog File | Description | DM-Only? |
|---------|----------|-------------|----------|
| `/chat` | cogs/chat.py | Converse with the Tower Oracle (AI) | No |
| `/reset` | cogs/chat.py | Clear conversation history | No |
| `/setcharprofile` | cogs/character.py | Set Name/Class/Role/Notes for character | No |
| `/showcharprofile` | cogs/character.py | Display saved character profile | No |
| `/setcharappearance` | cogs/character.py | Upload char art for LLaVA description | DM only |
| `/showcharappearance` | cogs/character.py | Show generated appearance description | No |
| `/resolvemission` | cogs/missions.py | Mark mission complete/failed by title | DM only |
| `/finances` | cogs/economy.py | Show EC/Kharma exchange + price tables | No |
| `/prices` | cogs/economy.py | Lookup item prices (weapons, potions, armor) | No |
| `/rules` | cogs/rules_lookup.py | Lookup D&D 5e 2024 rules via RAG | No |
| `/spell` | cogs/rules_lookup.py | Lookup spell details | No |
| `/draw` | cogs/images.py | Generate scene image via A1111 | No |
| `/drawscene` | cogs/images.py | Generate labeled scene with elements | No |
| `/gearrun` | cogs/images.py | Generate character equipment display | No |
| `/pin` | cogs/images.py | Pin character/location reference image | No |
| `/refstats` | cogs/images.py | Generate character stat block image | No |
| `/factionrep` | cogs/world.py | Check faction reputation standings | No |
| `/partyrep` | cogs/world.py | Show party-wide faction scores | No |
| `/style` | cogs/world.py | Generate tactical situation descriptions | No |
| `/sync` | cogs/admin.py | Sync slash commands to Discord | DM only |
| `/provider` | cogs/admin.py | Switch AI provider (OpenAI/Claude/Gemini/Grok/Free) | DM only |
| `/switchpersona` | cogs/admin.py | Change bot AI personality | DM only |
| `/private` | cogs/admin.py | Toggle private reply mode | No |
| `/replyall` | cogs/admin.py | Toggle reply-all mode | DM only |
| `/help` | cogs/admin.py | Show all commands with descriptions | No |
| `/towerbay` | cogs/admin.py | Show EC/Kharma exchange rates | No |
| `/myauctions` | cogs/admin.py | Show player's active auctions | No |
| `/newsdraft` | cogs/admin.py | Draft bulletin before posting | DM only |
| `/archive` | cogs/admin.py | Archive old channel messages | DM only |
| `/riftlist` | cogs/admin.py | Show active rifts & stages | No |
| `/sealrift` | cogs/admin.py | Close/resolve a rift | DM only |
| `/genmodule` | cogs/module_gen.py | Generate D&D mission module (.docx + maps) | DM only |
| `/skills` | cogs/skills.py | List/view/reload skill files | DM only |

---

## Background Loops (all in `src/aclient.py`)

| Loop | Trigger | What It Does |
|------|---------|--------------|
| `news_feed_loop` | Hourly (~60min) | Bulletins, rift ticks, economy, weather, arena, calendar, missing persons |
| `mission_board_loop` | Periodic | Post new missions, expiry checks, NPC claims/completions, bounties |
| `personal_mission_loop` | 1-3 day cycles | Per-character personal missions |
| `story_image_loop` | Every 2-4 hours | A1111 SDXL image generation |
| `npc_lifecycle_loop` | Daily | NPC roster events (arrivals, departures, deaths) |
| `character_monitor_loop` | Every 30 min | Watches Avrae for character sheet changes |
| `chat_reminder_loop` | Periodic | Downtime /chat nudges |
| `log_cleanup_loop` | Daily | Log rotation (7-day retention) |
| `_self_learning_loop` | 1-4 AM window | Studies campaign data, generates skill files |

---

## Cog Dependency / Import Map

```
cogs/chat.py
  → aclient.py (handle_response, send_message)
  → tower_rag.py (campaign context)
  → skill_loader.py (skill injection)
  → npc_lookup.py (quoted name lookup)
  → providers.py (AI provider)

cogs/missions.py
  → mission_board.py (resolve_mission)
  → faction_reputation.py (rep changes)

cogs/images.py
  → news_feed.py (a1111_lock, _a1111_lock)
  → npc_lookup.py (NPC SD prompts)
  → npc_appearance.py (appearance descriptions)

cogs/admin.py
  → news_feed.py (bulletin posting)
  → tower_economy.py (TowerBay auctions)
  → rift_state.py (rift data)

cogs/module_gen.py
  → mission_builder/__init__.py (generate_module)
  → mission_builder/maps.py (VTT maps)

news_feed.py (115KB — THE BIG ONE)
  → agents/news_agents.py (editorial, gossip, sports)
  → agents/orchestrator.py
  → bulletin_embeds.py
  → tower_economy.py (economy tick)
  → ec_exchange.py
  → dome_weather.py
  → arena_season.py
  → faction_calendar.py
  → missing_persons.py
  → npc_consequence.py (post-bulletin death scanner)
  → rift_state.py

mission_board.py (62KB)
  → mission_builder/__init__.py
  → bounty_board.py
  → party_profiles.py
  → faction_reputation.py

mission_builder/__init__.py
  → mission_builder/json_generator.py (Ollama 4-pass)
  → mission_builder/schemas.py
  → mission_builder/npcs.py
  → mission_builder/locations.py
  → mission_builder/leads.py
  → mission_builder/rewards.py
  → mission_builder/encounters.py
  → mission_builder/docx_builder.py
  → mission_builder/maps.py

aclient.py
  → providers.py
  → skill_loader.py
  → tower_rag.py
  → news_feed.py (loop)
  → mission_board.py (loop)
  → npc_lifecycle.py (loop)
  → character_monitor.py (loop)
  → self_learning.py (loop)
```

---

## Full Source File Map

### Core (`src/`)

| File | Size | Purpose |
|------|------|---------|
| [aclient.py](src/aclient.py) | 40KB | DiscordClient, all background loops, message queue |
| [bot.py](src/bot.py) | 2.2KB | Cog loader, on_ready, setup_hook |
| [log.py](src/log.py) | 2.7KB | Colored logging setup |
| [providers.py](src/providers.py) | 18KB | Multi-LLM provider abstraction (Free/OpenAI/Claude/Gemini/Grok) |
| [personas.py](src/personas.py) | 2.7KB | AI personality templates for /switchpersona |
| [skills.py](src/skills.py) | — | Project-wide skill system (loads from /skills) |
| [skill_loader.py](src/skill_loader.py) | 8KB | Runtime skill matching + keyword injection for /chat |
| [db_api.py](src/db_api.py) | — | MySQL database operations |

### Content Generation

| File | Size | Purpose |
|------|------|---------|
| [news_feed.py](src/news_feed.py) | 115KB | Bulletins, rift state machine, economy ticks, story image pipeline, district aesthetics |
| [mission_board.py](src/mission_board.py) | 62KB | Mission lifecycle: generate, post, claim, NPC complete, expire |
| [mission_module_gen.py](src/mission_module_gen.py) | 5KB | Compatibility wrapper for mission_builder package |
| [bounty_board.py](src/bounty_board.py) | 10KB | Bounty generation and tracking |
| [missing_persons.py](src/missing_persons.py) | 9.5KB | Missing persons board |
| [arena_season.py](src/arena_season.py) | 12KB | Arena match simulation |
| [dome_weather.py](src/dome_weather.py) | 18KB | Dome weather state machine |
| [faction_calendar.py](src/faction_calendar.py) | 12KB | Faction event calendar |

### Mission Builder Package (`src/mission_builder/`)

| File | Purpose |
|------|---------|
| [__init__.py](src/mission_builder/__init__.py) | Orchestrator. Exports `generate_mission_module()` |
| [json_generator.py](src/mission_builder/json_generator.py) | 4-pass Ollama generation (overview → acts 1-2 → acts 3-4 → act 5) |
| [schemas.py](src/mission_builder/schemas.py) | MissionModule, DungeonRoom, NPC, Encounter pydantic schemas |
| [locations.py](src/mission_builder/locations.py) | Gazetteer integration (city_gazetteer.json) |
| [leads.py](src/mission_builder/leads.py) | Investigation leads, clues, red herrings |
| [encounters.py](src/mission_builder/encounters.py) | CR calculation, encounter budgets, stat blocks |
| [npcs.py](src/mission_builder/npcs.py) | NPC dialogue, secrets, faction hooks |
| [rewards.py](src/mission_builder/rewards.py) | Loot tables, faction rep rewards, item drops |
| [docx_builder.py](src/mission_builder/docx_builder.py) | Word document generation (.docx) |
| [image_generator.py](src/mission_builder/image_generator.py) | A1111 integration for mission images |
| [image_integration.py](src/mission_builder/image_integration.py) | Image refinement feedback loop |
| [mission_types.py](src/mission_builder/mission_types.py) | Mission type templates |
| [maps.py](src/mission_builder/maps.py) | VTT battlemap generation + Discord posting |
| [dungeon_delve/](src/mission_builder/dungeon_delve/) | Procedural dungeon gen (tiles, rooms, layouts, stitcher) |

### Agents (`src/agents/`)

| File | Purpose |
|------|---------|
| [base.py](src/agents/base.py) | BaseAgent class, AgentConfig, AgentResponse |
| [orchestrator.py](src/agents/orchestrator.py) | Agent selection and routing |
| [qwen_agent.py](src/agents/qwen_agent.py) | QwenAgent — fast local inference |
| [kimi_agent.py](src/agents/kimi_agent.py) | KimiAgent — complex reasoning tasks |
| [news_agents.py](src/agents/news_agents.py) | NewsAgents: editorial, gossip, sports genres |
| [learning_agents.py](src/agents/learning_agents.py) | Self-learning loop agents |
| [helpers.py](src/agents/helpers.py) | Agent utility functions |

### NPC & World Systems

| File | Size | Purpose |
|------|------|---------|
| [npc_lookup.py](src/npc_lookup.py) | 8KB | Fuzzy NPC name lookup (quoted names in /chat and /draw) |
| [npc_appearance.py](src/npc_appearance.py) | 31KB | NPC visual descriptions for SD prompts |
| [npc_lifecycle.py](src/npc_lifecycle.py) | 35KB | Daily NPC roster events |
| [npc_consequence.py](src/npc_consequence.py) | 12KB | Post-bulletin death/injury scanner |
| [faction_reputation.py](src/faction_reputation.py) | 9KB | Faction standing tracking |
| [faction_calendar.py](src/faction_calendar.py) | 12KB | Faction event calendar |
| [party_profiles.py](src/party_profiles.py) | 19KB | Adventurer party generation and profiles |
| [character_profiles.py](src/character_profiles.py) | 5KB | Player character profile CRUD |
| [character_monitor.py](src/character_monitor.py) | 10KB | Avrae character sheet monitoring |
| [character_memory.py](src/character_memory.py) | — | Character context for generation |

### Economy

| File | Size | Purpose |
|------|------|---------|
| [tower_economy.py](src/tower_economy.py) | 33KB | TowerBay auction house, TIA stock market |
| [ec_exchange.py](src/ec_exchange.py) | 12KB | EC/Kharma exchange rate simulation |
| [player_listings.py](src/player_listings.py) | 19KB | Player TowerBay auction items |

### RAG & Knowledge

| File | Size | Purpose |
|------|------|---------|
| [tower_rag.py](src/tower_rag.py) | 27KB | RAG search over campaign_docs for /chat context |
| [rules_agent.py](src/rules_agent.py) | 13KB | D&D 5e 2024 rules lookup via RAG + Ollama |
| [style_agent.py](src/style_agent.py) | 16KB | Character/faction clothing descriptions |
| [memory_strip.py](src/memory_strip.py) | 5KB | Strips emojis/fluff before saving to news_memory.txt |

### Supporting Systems

| File | Size | Purpose |
|------|------|---------|
| [patch_approval.py](src/patch_approval.py) | — | DM approval workflow for generated module patches |
| [module_quality_trainer.py](src/module_quality_trainer.py) | — | Feedback loop for module quality improvement |
| [self_learning.py](src/self_learning.py) | 15KB | Nightly self-learning loop (1-4 AM) |
| [bulletin_embeds.py](src/bulletin_embeds.py) | 3KB | Discord embed formatting for bulletins |
| [bulletin_cleaner.py](src/bulletin_cleaner.py) | — | Message cleanup utilities |
| [expandable_bulletin.py](src/expandable_bulletin.py) | — | "Read More" button handler |
| [image_ref.py](src/image_ref.py) | 8KB | Reference image storage for img2img generation |
| [ollama_busy.py](src/ollama_busy.py) | 2KB | Ollama busy-state tracking |
| [weekly_archive.py](src/weekly_archive.py) | — | Archive management |
| [archive_logs.py](src/archive_logs.py) | — | Log rotation |
| [rift_state.py](src/rift_state.py) | — | Rift tracking & stage management |

---

## Campaign Data (`campaign_docs/`)

### Core State Files

| File | Format | What It Tracks |
|------|--------|----------------|
| `npc_roster.json` | JSON | All alive/injured NPCs — faction, role, location, secrets |
| `npc_graveyard.json` | JSON | Dead NPCs (moved here on death) |
| `city_gazetteer.json` | JSON | Districts, establishments, transport, ring structure |
| `character_memory.txt` | Text | Player chars (NAME/CLASS/SPECIES/PLAYER blocks) |
| `faction_reputation.json` | JSON | Faction rep scores and event history |
| `news_memory.txt` | Text | Cleaned factual bulletin log (max 40 entries) |
| `mission_memory.json` | JSON | All missions: active + resolved |
| `rift_state.json` | JSON | Active rift state machine data |
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
| `resurrection_queue.json` | JSON | Major NPCs queued for resurrection (2-7 day delay) |
| `personal_mission_tracker.json` | JSON | Per-character personal mission state |

### Profile Directories

| Directory | Contents |
|-----------|----------|
| `npc_appearances/` | Individual NPC visual descriptions (JSON per NPC) + `_all_sd_prompts.json` |
| `party_profiles/` | Adventurer party profiles (JSON per party) |
| `char_snapshots/` | D&D Beyond character snapshots |
| `skills/` | Bot skill library: seed + `learned_*.md` self-learned files |
| `archives/` | Completed missions, news history, snapshots, outcomes, player_listings |

---

## Logs (`logs/`)

| File | Purpose |
|------|---------|
| `bot_stderr.log` | Error stream (~3.5MB) — main runtime log WITH color codes |
| `bot_stdout.log` | Standard output |
| `journal.txt` | Session journal: fixes, decisions, DM questions (`[DM QUESTION]`) |
| `debug_log.md` | **Bug tracker** — all spotted errors, status, investigation notes |
| `migration_log.txt` | Database migration history |
| `worklog_*.md` | Session-specific development notes (resumable) |
| `logs/learning/` | Self-learning training logs |

---

## Key .env Variables

```
DISCORD_BOT_TOKEN          — Bot token (required)
DISCORD_CHANNEL_ID         — News feed / bulletin channel
DISCORD_GUILD_ID           — Guild for instant command sync (1133378983786971147)
MISSION_BOARD_CHANNEL_ID   — Where missions get posted
MISSION_RESULTS_CHANNEL_ID — Claim/complete/fail/expire notices (separate channel!)
DM_USER_ID                 — James's Discord ID (DM-only command check)
OLLAMA_MODEL               — Local LLM (qwen3-8b-slim:latest)
OLLAMA_URL                 — http://localhost:11434/api/chat
A1111_URL                  — http://127.0.0.1:7860
A1111_MODEL                — Photorealistic checkpoint name
A1111_ANIME_MODEL          — AnimagineXL checkpoint name
IMAGE_STYLE                — "anime" or "photorealistic"
MAPS_CHANNEL_ID            — Optional separate channel for VTT maps
MODULE_OUTPUT_CHANNEL_ID   — Where /genmodule posts the .docx
```

---

## Self-Learning System

Runs nightly **1-4 AM** in `src/self_learning.py`. Produces files in `campaign_docs/skills/`:

| Study Function | Output File | What It Learns |
|---------------|-------------|----------------|
| `_study_world_state()` | `learned_world_assessment_*.md` | Campaign health check |
| `_study_news_memory()` | `learned_current_events_*.md` | Recurring themes, NPC conflicts |
| `_study_mission_patterns()` | `learned_mission_patterns_*.md` | Mission outcome statistics |
| `_study_mission_quality()` | `learned_mission_quality_*.md` | Faction balance, completion rates |
| `_study_mission_type_variety()` | `learned_mission_type_ideas_*.md` | 8 fresh mission seeds |
| `_study_npc_roster()` | `learned_npc_landscape_*.md` | Faction distribution, gaps |
| `_study_faction_reputation()` | `learned_faction_standing_*.md` | Political landscape |
| `_study_conversation_logs()` | `learned_conversation_insights_*.md` | What players ask about |

Check `logs/journal.txt` for `[DM QUESTION]` flags raised during learning.

---

## Critical Conventions

1. **setup_hook for command sync** — not on_ready. Never revert.
2. **Mission results → `MISSION_RESULTS_CHANNEL_ID`** / New missions → `MISSION_BOARD_CHANNEL_ID` — different channels.
3. **A1111 lock** — all image generation must acquire `a1111_lock` from `news_feed.py`. Check `_a1111_lock.locked()` first.
4. **`_write_memory()` auto-strips** — `memory_strip.py` removes emojis/fluff before saving to `news_memory.txt`.
5. **Module CR is dynamic** — parsed from `character_memory.txt` max PC level + tier offset. Falls back to legacy table if file unreadable.
6. **NPC consequence scanner** runs after every bulletin. Scans for roster NPC names near death/injury language, updates `npc_roster.json` + `npc_graveyard.json`, queues major NPCs in `resurrection_queue.json`.
7. **Image prompt forbidden terms:** "fate", "stay night", "type-moon", "ufotable", "official art", "anime screencap", "dark fantasy". Quality header: `masterpiece, best quality, very aesthetic, absurdres`.
8. **Self-learned skills:** max 50 files in `campaign_docs/skills/`.
9. **Backups:** go to `backups/` with descriptive date-stamped names.
10. **NEVER regex-edit multi-line code** — always read-full → modify in memory → write-full.

---

## Common Patterns

### Adding a slash command
```python
# Inside setup(client) in the appropriate src/cogs/*.py file:
@client.tree.command(name="mycmd", description="Description here")
async def mycmd(interaction: discord.Interaction):
    await interaction.response.defer()
    ...
    await interaction.followup.send("Result")
# Then run /sync in Discord
```

### Calling Ollama
```python
import httpx, os
ollama_url  = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
async with httpx.AsyncClient(timeout=120.0) as client:
    resp = await client.post(ollama_url, json={
        "model": ollama_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    })
    text = resp.json().get("message", {}).get("content", "").strip()
```

### A1111 Image Generation (always lock first)
```python
from src.news_feed import a1111_lock, _a1111_lock
if _a1111_lock.locked():
    return  # Tell user A1111 is busy
async with a1111_lock:
    async with httpx.AsyncClient(timeout=900.0) as client:
        r = await client.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
```

### NPC Fuzzy Lookup
```python
from src.npc_lookup import extract_and_lookup_npcs, get_npc_context_for_prompt
matches = extract_and_lookup_npcs('Tell me about "Serik Dhal"')
# Threshold: 0.6 minimum similarity. Matches first, last, or full name.
```

---

## Known Recurring Bugs (see `logs/debug_log.md` for full details)

| # | Error | Location | Status |
|---|-------|----------|--------|
| 1 | `generate_bulletin() returned None — mission board may be missing` | news_feed.py | ACTIVE — fires every bulletin cycle |
| 2 | `NPC load error: 'NoneType' object is not a mapping` | npc_lifecycle.py | ACTIVE — null entry in npc_roster.json |
| 3 | `Prompt agent: Mistral returned prose or too few tags` | image prompt agent | ACTIVE — Mistral not following tag format |
| 4 | `Bulletin failed validation (truncated)` | news_feed.py generate_bulletin | ACTIVE — bulletin text cut short |
| 5 | `Bulletin failed validation (too few lines)` | news_feed.py generate_bulletin | ACTIVE — single-line output discarded |
| 6 | `Fact-check: result too short, using original` | news_feed.py fact-checker | ACTIVE — fact-check agent returning empty |
| 7 | `Editor output invalid (empty) — using original draft` | news_feed.py editor agent | ACTIVE — editor agent silent failure |
