# chatgpt-discord-bot — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**chatgpt-discord-bot** is a python project built with raw-http.

## Scale

15 database models · 3 middleware layers · 38 environment variables

**Database:** unknown, 15 models — see [database.md](./database.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `/layouts.py` — imported by **5** files
- `/schemas.py` — imported by **5** files
- `/base.py` — imported by **3** files
- `/mission_json_builder.py` — imported by **2** files
- `/encounters.py` — imported by **2** files
- `/locations.py` — imported by **2** files

## Required Environment Variables

- `DDB_COBALT_TOKEN` — `src\character_monitor.py`
- `DISCORD_BOT_TOKEN` — `.env.example`
- `DISCORD_CHANNEL_ID` — `.env.example`
- `LEARN_HOUR_END` — `src\self_learning.py`
- `LEARN_HOUR_START` — `src\self_learning.py`
- `MAPS_CHANNEL_ID` — `src\mission_builder\maps.py`
- `MYSQL_DB` — `sql_refactor_setup.py`
- `MYSQL_HOST` — `sql_refactor_setup.py`
- `MYSQL_PASSWORD` — `sql_refactor_setup.py`
- `MYSQL_USER` — `sql_refactor_setup.py`
- `OPENAI_ENABLED` — `src\art.py`
- `REPLYING_ALL_DISCORD_CHANNEL_ID` — `.env.example`

---
_Back to [index.md](./index.md) · Generated 2026-04-09_