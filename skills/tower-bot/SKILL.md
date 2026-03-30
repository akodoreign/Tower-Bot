---
name: tower-bot
description: "Use this skill for ANY work on the Tower of Last Chance Discord bot project. This includes: editing bot code, working with cog modules, modifying news_feed.py, mission_board.py, aclient.py, or any src/ file; debugging bot behavior; adding slash commands; working with the campaign_docs data files; understanding the project architecture; working with Ollama/A1111 integrations; or any mention of 'Tower bot', 'Undercity', 'discord bot', 'mission board', 'news feed', 'cog', or the project path chatGPT-discord-bot. Always consult this skill FIRST before making changes — it contains critical architecture info, file maps, and conventions that prevent breaking the bot."
---

# Tower of Last Chance — Discord Bot Project Skill

## Project Location
`C:\Users\akodoreign\Desktop\chatGPT-discord-bot`

## Architecture Overview

This is a **discord.py** bot using `discord.Client` (NOT `commands.Bot`).
The client class is `DiscordClient` in `src/aclient.py`.
Because it's `discord.Client`, **native Cogs don't work** — we use a custom module-loading pattern instead.

### Boot Sequence
1. `main.py` → calls `run_discord_bot()` from `src/bot.py`
2. `src/bot.py` → lightweight loader (~60 lines):
   - Sets guild ID for command sync
   - Iterates `COG_MODULES` list, imports each, calls `module.setup(discordClient)`
   - Registers `on_ready` event (persistent views, process_messages task)
   - Calls `discordClient.run(token)`
3. `src/aclient.py` → `DiscordClient.__init__` creates the command tree, provider manager, queues
4. `aclient.py` → `process_messages()` spawns background loops:
   - `news_feed_loop` → hourly bulletins, rift ticks, economy ticks, weather, arena, calendar, missing persons
   - `mission_board_loop` → new mission posts, expiry checks, NPC claims/completions, bounties
   - `personal_mission_loop` → per-character personal missions on 1-3 day cycles
   - `story_image_loop` → A1111 SDXL image generation every 2-4 hours
   - `npc_lifecycle_loop` → daily NPC roster updates
   - `character_monitor_loop` → watches for character sheet changes
   - `chat_reminder_loop` → periodic /chat reminders
   - `log_cleanup_loop` → log rotation

### Cog Module Pattern
Each file in `src/cogs/` exports a `setup(client)` function that registers commands on `client.tree`:

```python
def setup(client):
    @client.tree.command(name="mycmd", description="...")
    async def mycmd(interaction: discord.Interaction):
        ...
```

**COG_MODULES** (loaded in order by `src/bot.py`):
- `src.cogs.chat` — `/chat`, `/reset`, `on_message`
- `src.cogs.character` — `/setcharprofile`, `/showcharprofile`, `/setcharappearance`, `/showcharappearance`
- `src.cogs.missions` — `/resolvemission`, `on_raw_reaction_add`
- `src.cogs.economy` — `/finances`, `/prices`
- `src.cogs.rules_lookup` — `/rules`, `/spell`
- `src.cogs.images` — `/draw`, `/drawscene`, `/gearrun`
- `src.cogs.world` — `/factionrep`, `/partyrep`, `/style`
- `src.cogs.admin` — `/sync`, `/provider`, `/switchpersona`, `/private`, `/replyall`, `/help`, `/towerbay`, `/myauctions`, `/newsdraft` + `_BulletinApprovalView`
- `src.cogs.skills` — `/skills` (list/view/stats/reload skill library)

### Key .env Variables
```
DISCORD_BOT_TOKEN          — Bot token
DISCORD_CHANNEL_ID         — News feed / bulletin channel
DISCORD_GUILD_ID           — Guild for instant slash command sync
MISSION_BOARD_CHANNEL_ID   — Where new missions get posted
MISSION_RESULTS_CHANNEL_ID — Where claim/complete/fail/expire notices go (separate from board)
DM_USER_ID                 — James's Discord ID (DM-only commands check this)
OLLAMA_MODEL               — Local LLM (mistral) for text generation
OLLAMA_URL                 — http://localhost:11434/api/chat
A1111_URL                  — http://127.0.0.1:7860 (Stable Diffusion WebUI)
A1111_MODEL                — Photorealistic checkpoint name
A1111_ANIME_MODEL          — AnimagineXL checkpoint name
IMAGE_STYLE                — "anime" or "photorealistic"
```

## File Map — Core Source Files

| File | Size | Purpose |
|------|------|---------|
| `src/aclient.py` | 40KB | DiscordClient class, all background loops, message processing |
| `src/news_feed.py` | 115KB | Bulletin generation, rift state machine, economy ticks, story image pipeline, district aesthetics |
| `src/mission_board.py` | 62KB | Mission generation, posting, claims, NPC completions, expiry, player reactions |
| `src/bot.py` | 2.2KB | Cog loader + on_ready |
| `src/memory_strip.py` | 5KB | Fact extractor — strips emojis/fluff from news memory entries |
| `src/tower_rag.py` | 27KB | RAG search over campaign_docs for /chat context |
| `src/skill_loader.py` | 8KB | Skill library loader + keyword matcher for /chat context injection |
| `src/self_learning.py` | 9KB | Nightly self-learning loop (1-2 AM) — studies logs, docs, generates skill files |
| `src/npc_consequence.py` | 12KB | Post-bulletin NPC death/injury scanner, resurrection queue, graveyard management |
| `src/tower_economy.py` | 33KB | TowerBay auction house, TIA stock market simulation |
| `src/npc_appearance.py` | 31KB | NPC visual descriptions for SD prompts |
| `src/npc_lifecycle.py` | 35KB | Daily NPC roster events (arrivals, departures, deaths) |
| `src/party_profiles.py` | 19KB | Adventurer party generation and profiles |
| `src/character_profiles.py` | 5KB | Player character profile CRUD |
| `src/npc_lookup.py` | 8KB | Fuzzy NPC name lookup for quoted names in /chat and /draw |
| `src/rules_agent.py` | 13KB | D&D 5e 2024 rules lookup via RAG + Ollama |
| `src/style_agent.py` | 16KB | Character/faction clothing descriptions |
| `src/ec_exchange.py` | 12KB | EC/Kharma exchange rate simulation |
| `src/faction_reputation.py` | 9KB | Faction rep tracking (events → tier shifts) |
| `src/bounty_board.py` | 10KB | Bounty generation and posting |
| `src/dome_weather.py` | 18KB | Dome weather simulation |
| `src/arena_season.py` | 12KB | Arena match simulation |
| `src/faction_calendar.py` | 12KB | Faction event calendar |
| `src/missing_persons.py` | 9.5KB | Missing persons notices |
| `src/player_listings.py` | 19KB | Player TowerBay auction listings |

## Self-Learning System (`src/self_learning.py`)

The bot runs a nightly self-learning loop during **1-2 AM local time** that:
1. Analyzes campaign data (missions, news, NPCs, factions, chat logs)
2. Generates skill files in `campaign_docs/skills/` with `learned_` prefix
3. Iteratively improves mission generation quality

### Study Functions (run each night)
| Function | Output Skill | Purpose |
|----------|--------------|--------|
| `_study_world_state()` | `learned_world_assessment_*.md` | Campaign health check guided by LEARNING_PHILOSOPHY |
| `_study_news_memory()` | `learned_current_events_*.md` | Recurring themes, NPC conflicts, what's hot |
| `_study_mission_patterns()` | `learned_mission_patterns_*.md` | Basic mission outcome statistics |
| `_study_mission_quality()` | `learned_mission_quality_*.md` | Deep quality analysis: faction balance, completion rates, type seeds |
| `_study_mission_type_variety()` | `learned_mission_type_ideas_*.md` | Generate 8 fresh mission type seeds for underrepresented areas |
| `_study_npc_roster()` | `learned_npc_landscape_*.md` | Faction distribution, district coverage, gaps |
| `_study_faction_reputation()` | `learned_faction_standing_*.md` | Political landscape, ally/enemy status |
| `_study_conversation_logs()` | `learned_conversation_insights_*.md` | What players ask about, unanswered questions |

### Mission Improvement Cycle
The system iteratively improves missions through:
1. **Quality Analysis** — `_study_mission_quality()` checks faction distribution, completion rates, claim ratios
2. **Type Innovation** — `_study_mission_type_variety()` finds underrepresented factions/objectives, generates fresh seeds
3. **Daily Generation** — `mission_board.py:refresh_mission_types_if_needed()` uses the seeds
4. **Learned Skills** — Bot reads its own `learned_mission_*` files to understand patterns

### LEARNING_PHILOSOPHY Constant
Guiding principles embedded in `self_learning.py`:
- **Rule 1:** PCs are the Tower's only hope — nurture them, tip balance slightly in their favor
- **Rule 2:** DM is a friend — flag uncertainties with `[DM QUESTION]` prefix in journal

### Manual Testing
```python
# Force a learning session without waiting for 1-2 AM:
from src.self_learning import run_learning_session
import asyncio
asyncio.run(run_learning_session())
```

Check results in:
- `campaign_docs/skills/learned_*.md` — generated skill files
- `logs/journal.txt` — timestamped learning log with `[DM QUESTION]` flags

## VTT Map Generation (`src/mission_builder/maps.py`)

Automatic battlemap generation integrated into the mission module pipeline:

### How It Works
1. After DOCX is generated, `generate_module_maps()` runs automatically
2. Extracts scenes from module (Act 2 leads + Act 4 confrontation)
3. Generates 1024x1024 top-down battlemaps via A1111
4. Uses `image_ref.py` for iterative improvement — each map becomes a reference for future maps of the same location
5. Maps posted to Discord alongside the module DOCX

### District Aesthetics
Each Undercity district has unique visual style:
- **Markets Infinite**: cobblestone, market stalls, lantern light
- **Warrens**: ruins, debris, makeshift shelters, dangerous terrain
- **Guild Spires**: polished stone, ornate pillars, guild banners
- **Sanctum Quarter**: temple architecture, religious symbols
- **Outer Wall**: fortifications, guard towers, defensive positions

### Iterative Improvement
```
Mission 1 uses "Collapsed Plaza" → txt2img (no reference)
Mission 2 uses "Collapsed Plaza" → img2img with denoise=0.50 (uses ref)
Mission 3 uses "Collapsed Plaza" → even better (refs compound)
```

### Key Functions
```python
from src.mission_builder.maps import (
    extract_map_scenes,     # Parse module for map-worthy scenes
    generate_vtt_map,       # Generate single map
    generate_module_maps,   # Generate all maps for a module
    post_maps_to_channel,   # Post maps to Discord
)
```

### Config
- `MAPS_CHANNEL_ID` — Optional separate channel for maps
- Falls back to `MODULE_OUTPUT_CHANNEL_ID`
- Max 4 maps per module

## File Map — More Source Files

| File | Size | Purpose |
|------|------|---------|
| `src/mission_builder/maps.py` | 12KB | VTT battlemap generation for modules |
| `src/providers.py` | 18KB | AI provider abstraction (free/openai/claude/etc) |
| `src/personas.py` | 2.7KB | Chat persona management |
| `src/log.py` | 2.7KB | Logging setup |

## File Map — Data Files (campaign_docs/)

| File | Purpose |
|------|---------|
| `news_memory.txt` | Cleaned factual log of all posted bulletins (max 40 entries) |
| `mission_memory.json` | All missions (active + resolved) |
| `character_memory.txt` | Player character records (NAME/CLASS/SPECIES/PLAYER blocks) |
| `npc_roster.json` | Current NPC roster with factions, roles, locations |
| `faction_reputation.json` | Faction rep scores and event history |
| `bounty_board.json` | Active bounties |
| `rift_state.json` | Active Rift state machine data |
| `arena_season.json` | Current arena season standings |
| `dome_weather.json` | Current weather state |
| `ec_exchange.json` | Current EC/Kharma exchange rate |
| `tia.json` | TIA stock market sector values |
| `faction_calendar.json` | Upcoming faction events |
| `missing_persons.json` | Active missing persons cases |
| `player_listings.json` | Player TowerBay auction items |
| `skills/*.md` | Bot skill library (seed + self-learned knowledge files) |
| `resurrection_queue.json` | Major NPCs queued for resurrection (2-7 day delay after news-feed death) |
| `npc_appearances/*.json` | Individual NPC visual descriptions |
| `party_profiles/*.json` | Adventurer party profiles |
| `char_snapshots/*.json` | D&D Beyond character snapshots |

## Critical Conventions

1. **Always use `filesystem:create_directory` before writing to a new directory** — writing to a non-existent path fails silently.
2. **Check file size with `filesystem:get_file_info` before reading large files** — `news_feed.py` is 115KB, `mission_board.py` is 62KB.
3. **The A1111 lock (`a1111_lock`) is shared** — all image generation (story loop, /draw, /drawscene, /gearrun) must acquire it.
4. **`_write_memory()` auto-strips** — the `memory_strip.py` module strips emojis and fluff before saving to `news_memory.txt`.
5. **Mission results go to `MISSION_RESULTS_CHANNEL_ID`**, new missions go to `MISSION_BOARD_CHANNEL_ID` — these are different channels.
6. **Image prompts must NOT contain**: "fate", "stay night", "type-moon", "ufotable", "official art", "anime screencap", "dark fantasy". Quality header is just: `masterpiece, best quality, very aesthetic, absurdres`.
7. **Backups go to `backups/`** with descriptive names including the date.
8. **Skill files** live in `campaign_docs/skills/` as markdown with `**Keywords:**` headers. The skill loader auto-reloads when files change.
9. **Self-learning** runs once per night (1-2 AM by default). Check `logs/journal.txt` for session logs. Max 50 self-learned skills.
10. **Module CR is dynamic** — parsed from `character_memory.txt` max PC level + tier offset (+1 to +5). Falls back to legacy fixed table if file unreadable.
11. **NPC consequence scanner** runs after every bulletin post. It scans for roster NPC names near death/injury language, updates `npc_roster.json` + `npc_graveyard.json`, and queues major NPCs for resurrection in 2-7 days. Check `resurrection_queue.json` for pending resurrections.
12. **Git remote points to upstream fork** (`Zero6992/chatGPT-discord-bot`) — James needs to set his own remote before pushing.

## Safe File Editing — CRITICAL

**NEVER use regex-based `filesystem:edit_file` for complex edits.** Regex edits with special characters, multi-line patterns, or code-like content corrupt files unpredictably.

### Safe Editing Pattern
1. **Read the entire file** with `filesystem:read_text_file`
2. **Make changes in memory** as a complete string
3. **Write the entire file** with `filesystem:write_file`

### When `filesystem:edit_file` is OK
- Simple, single-line text replacements
- No special characters (no quotes, backslashes, brackets)
- Exact string matches you've copied from the file

### When `filesystem:edit_file` will BREAK things
- Multi-line code blocks
- Regex patterns with `\s`, `\b`, `\n`, etc.
- Content with emojis, unicode, or special punctuation
- Function definitions, docstrings, f-strings
- Anything where whitespace matters

### Recovery Pattern
If a file gets corrupted:
1. Check `backups/` for a recent copy
2. Read the corrupted file to understand what was lost
3. Reconstruct the correct version
4. Write it with `filesystem:write_file` (full overwrite)

### Example: Corrupted `__init__.py` Recovery (2026-03-28)
The `mission_builder/__init__.py` was corrupted by a regex edit that duplicated content and broke the `_post_process_module_text()` function. Fixed by:
1. Reading the full corrupted file to identify the good parts
2. Reconstructing the complete module from scratch
3. Writing the corrected version with `filesystem:write_file`

## Common Patterns

### Adding a new slash command
1. Decide which cog it belongs to (or create a new one in `src/cogs/`)
2. Add the command inside the `setup(client)` function using `@client.tree.command()`
3. If new cog: add `"src.cogs.newmodule"` to `COG_MODULES` in `src/bot.py`
4. Run `/sync` in Discord to register the command

### Using Ollama for text generation
```python
import httpx, os
ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
async with httpx.AsyncClient(timeout=120.0) as client:
    resp = await client.post(ollama_url, json={
        "model": ollama_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    })
    data = resp.json()
    text = data.get("message", {}).get("content", "").strip()
```

### Using A1111 for image generation
Always acquire `a1111_lock` first, always check `_a1111_lock.locked()` before waiting:
```python
from src.news_feed import a1111_lock, _a1111_lock
if _a1111_lock.locked():
    # Tell user A1111 is busy
    return
async with a1111_lock:
    async with httpx.AsyncClient(timeout=900.0) as client:
        r = await client.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
```

### NPC Lookup with Fuzzy Matching
When users put NPC names in quotes (e.g., `"Serik Dhal"`), the `npc_lookup.py` module:
1. Extracts quoted strings from the message
2. Fuzzy-matches against `npc_roster.json` + `npc_graveyard.json`
3. Injects NPC context/appearance into prompts

**Integrated into:**
- `/chat` → `aclient.py:handle_response()` injects NPC bio/faction/motivation into system context
- `/draw` → `cogs/images.py` injects NPC appearance/SD prompt into image generation

```python
from src.npc_lookup import (
    extract_and_lookup_npcs,    # Extract quoted names, return matches with confidence
    get_npc_context_for_prompt, # Build context block for /chat AI prompt
    get_npc_sd_prompt,          # Build SD prompt fragment for /draw
    lookup_npc_by_name,         # Direct lookup by name
)

# Example: fuzzy match "Serik Dhal" → "Serrik Dhal" (confidence: 0.91)
matches = extract_and_lookup_npcs('Tell me about "Serik Dhal"')
for m in matches:
    print(f"{m['query']} → {m['name']} ({m['confidence']:.2f})")
```

Threshold: 0.6 minimum similarity. Matches first name, last name, or full name.
