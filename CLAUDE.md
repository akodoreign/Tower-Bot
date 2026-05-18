## Session Orientation (read on every session start and after every compact)

At the start of every session and after any context compaction, read these three files in order:
1. `CLAUDE.md` — project rules and constraints (this file)
2. `buglog.md` — active bugs B-1 through B-48; know what's broken before touching anything
3. `MAP.md` — full codebase map; know where everything lives

Do not rely on conversation memory alone after a compact — always re-read these files.

**Bug fixing rule (from buglog.md):** Before fixing any bug, smoke test the current behavior and map connected callers. After the fix, re-run the same smoke path. Do not patch from the note alone.

**No refactoring mission pipelines** — each pipeline (ambush, defense, heist, etc.) is intentionally distinct. Do not condense, abstract, or merge them.

---

## Data Layer — MySQL is Authoritative

**Use the DB and API, not JSON or text files.**

## Quality Bar

For this bot, accuracy, completeness, prose quality, and correct visual artifacts are more important than speed. Mission generation may take 20+ minutes if needed. Do not choose fast/lazy fallbacks that omit required content, maps, portraits, faction context, or prose quality; prefer waiting, retrying, or using a stronger/more appropriate model when the output would otherwise be incomplete or wrong.
All campaign data (NPCs, missions, bulletins, factions, skills, economy, weather, etc.) lives in MySQL.
- Read from DB via `src/db_api.py` (`raw_query`, `raw_execute`, `get_global_state`, `set_global_state`)
- Never read from or write to `campaign_docs/` JSON/txt files in new code
- File fallbacks have been removed — DB is the only source of truth
- The `city_gazetteer.json` full structure is the only remaining file-based read (no DB table yet)

### Live MySQL Tables

Use this table list as the first place to look for campaign data. Prefer `src/db_api.py` helpers (`raw_query`, `raw_execute`, `get_global_state`, `set_global_state`) over file reads.

For exact columns, types, indexes, and foreign keys, read `docs/mysql_schema_reference.md`.
Do not treat `.codesight/schema.md` as the live DB schema source; CodeSight may regenerate that file.

World / places:
- `gazetteer`
- `gazetteer_places`
- `area_profiles`
- `weather_state`
- `rift_state`
- `gods`

Missions / modules:
- `missions`
- `mission_types`
- `mission_type_templates`
- `mission_outcomes`
- `personal_missions`

NPCs / characters / parties:
- `npcs`
- `npc_appearances`
- `character_snapshots`
- `latest_character_snapshots`
- `player_characters`
- `party_profiles`
- `party_interviews`
- `adventurer_parties`
- `missing_persons`
- `resurrection_queue`

Factions / reputation / events:
- `faction_reputation`
- `faction_events`

Bulletins / news / memory:
- `news_entries`
- `news_memory`
- `news_types`
- `bulletin_cache`

Economy / market:
- `economy_state`
- `tia_market`
- `towerbay_auctions`
- `towerbay_bids`
- `player_listings`
- `bounties`

Competitions / arena:
- `competitions`
- `competition_entries`
- `arena_seasons`

Bot / system / integrations:
- `global_state`
- `bot_commands`
- `image_refs`
- `mimir_sync`
- `skills`
- `training_docs`

Lifecycle:
- `lifecycle_events`
- `lifecycle_daily_events`

---
name: chatgpt-discord-bot
type: project-skill
description: Project context and operating rules for the chatgpt Discord bot codebase
stack:
  - python
  - raw-http
routes: 0
models: 15
environment_variables_count: 38
import_links: 36
required_env_vars:
  - DDB_COBALT_TOKEN
  - DISCORD_BOT_TOKEN
  - DISCORD_CHANNEL_ID
  - LEARN_HOUR_END
  - LEARN_HOUR_START
  - MAPS_CHANNEL_ID
  - MYSQL_DB
  - MYSQL_HOST
  - MYSQL_PASSWORD
  - MYSQL_USER
  - OPENAI_ENABLED
  - REPLYING_ALL_DISCORD_CHANNEL_ID
high_impact_files:
  - layouts.py
  - schemas.py
  - base.py
  - mission_json_builder.py
  - encounters.py
---

## chatgpt-discord-bot — Project Context

**Stack:** raw-http (none), python  
**Routes:** 0  
**Models:** 15  
**Env vars:** 38  
**Import links:** 36  

### High-impact files (change carefully)
- `/layouts.py` (imported by 5 files)
- `/schemas.py` (imported by 5 files)
- `/base.py` (imported by 3 files)
- `/mission_json_builder.py` (imported by 2 files)
- `/encounters.py` (imported by 2 files)

### Required environment variables
- `DDB_COBALT_TOKEN`
- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID`
- `LEARN_HOUR_END`
- `LEARN_HOUR_START`
- `MAPS_CHANNEL_ID`
- `MYSQL_DB`
- `MYSQL_HOST`
- `MYSQL_PASSWORD`
- `MYSQL_USER`
- `OPENAI_ENABLED`
- `REPLYING_ALL_DISCORD_CHANNEL_ID`

---

## Instructions for Claude Code

### Two-Step Rule (mandatory)

**Step 1 — Orient**  
Use wiki articles to find **where** things live.

**Step 2 — Verify**  
Read the **actual source files** listed in the wiki article **before writing any code**.

Wiki articles are **structural summaries extracted by AST**.  
They show routes, models, and file locations.

They do **NOT** show:
- Full function logic
- Middleware internals
- Dynamic runtime behavior

**Never write or modify code based solely on wiki content — always read source files first.**

### Required read order at session start
1. `.codesight/wiki/index.md` — orientation map (~200 tokens)
2. `.codesight/wiki/overview.md` — architecture overview (~500 tokens)
3. Domain article (e.g. `.codesight/wiki/auth.md`)  
   - Check **Source Files**
   - Read those files
4. `.codesight/CODESIGHT.md` — full context map for deep exploration

### Important notes
- Routes marked **[inferred]** in wiki articles were detected via regex  
  → **Always verify against source**
- If any source file shows ⚠ in the wiki:
  ```bash
  npx codesight --wiki
 


# chatgpt-discord-bot — Project Context

**Stack:** raw-http | none | python

0 routes | 15 models | 38 env vars | 36 import links


**High-impact files** (change carefully):
- /layouts.py (imported by 5 files)
- /schemas.py (imported by 5 files)
- /base.py (imported by 3 files)
- /mission_json_builder.py (imported by 2 files)
- /encounters.py (imported by 2 files)

**Required env vars:** DDB_COBALT_TOKEN, DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, LEARN_HOUR_END, LEARN_HOUR_START, MAPS_CHANNEL_ID, MYSQL_DB, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_USER, OPENAI_ENABLED, REPLYING_ALL_DISCORD_CHANNEL_ID

---

## Instructions for Claude Code

### Two-Step Rule (mandatory)
**Step 1 — Orient:** Use wiki articles to find WHERE things live.
**Step 2 — Verify:** Read the actual source files listed in the wiki article BEFORE writing any code.

Wiki articles are structural summaries extracted by AST. They show routes, models, and file locations.
They do NOT show full function logic, middleware internals, or dynamic runtime behavior.
**Never write or modify code based solely on wiki content — always read source files first.**

Read in order at session start:
1. `.codesight/wiki/index.md` — orientation map (~200 tokens)
2. `.codesight/wiki/overview.md` — architecture overview (~500 tokens)
3. Domain article (e.g. `.codesight/wiki/auth.md`) → check "Source Files" section → read those files
4. `.codesight/CODESIGHT.md` — full context map for deep exploration

Routes marked `[inferred]` in wiki articles were detected via regex — verify against source before trusting.
If any source file shows ⚠ in the wiki, re-run `npx codesight --wiki` before proceeding.

Or use the codesight MCP server for on-demand queries:
   - `codesight_get_wiki_article` — read a specific wiki article by name
   - `codesight_get_wiki_index` — get the wiki index
   - `codesight_get_summary` — quick project overview
   - `codesight_get_routes --prefix /api/users` — filtered routes
   - `codesight_get_blast_radius --file src/lib/db.ts` — impact analysis before changes
   - `codesight_get_schema --model users` — specific model details

Only open specific files after consulting codesight context. This saves ~52,624 tokens per conversation.---

## CodeSight Context (Precompiled)

This repository has been analyzed with **CodeSight** to precompile structural and architectural context for AI tools.

- CodeSight was run from the project root using:
  - 
px codesight --wiki
  - 
px codesight --init
- The generated, authoritative project context lives in:
  - .codesight/
  - .codesight/wiki/

### Guidance for AI assistants
- Prefer reading .codesight/wiki/*.md over scanning raw source files.
- Use .codesight/CODESIGHT.md as the high-level project map.
- The wiki is intentionally kept up to date to reduce redundant exploration and token usage.

If information is missing, outdated, or unclear, note it explicitly rather than re-scanning the entire repository.

---
---

## CodeSight MCP (Optional, On-Demand)

This project supports a **CodeSight MCP server** for live, queryable context.

- The MCP server is **not always running by default**.
- If deep structural queries, dependency lookups, or precise impact analysis are needed:
  - Prompt the user to start the server with:
    \\\ash
    npx codesight --mcp
    \\\
  - Assume the server becomes available after startup.

### Guidance for AI assistants
- Prefer the static wiki under \.codesight/wiki/\ for most tasks.
- Use the MCP server **only when dynamic or tool-based queries provide clear value**.
- Do not assume MCP availability unless the user confirms it is running.

---
