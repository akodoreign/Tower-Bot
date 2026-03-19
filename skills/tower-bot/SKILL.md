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
| `src/tower_economy.py` | 33KB | TowerBay auction house, TIA stock market simulation |
| `src/npc_appearance.py` | 31KB | NPC visual descriptions for SD prompts |
| `src/npc_lifecycle.py` | 35KB | Daily NPC roster events (arrivals, departures, deaths) |
| `src/party_profiles.py` | 19KB | Adventurer party generation and profiles |
| `src/character_profiles.py` | 5KB | Player character profile CRUD |
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
8. **Git remote points to upstream fork** (`Zero6992/chatGPT-discord-bot`) — James needs to set his own remote before pushing.

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
