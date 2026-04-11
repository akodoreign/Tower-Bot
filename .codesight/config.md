# Config

## Environment Variables

- `A1111_ANIME_MODEL` (has default) — .env
- `A1111_MODEL` (has default) — .env
- `A1111_URL` (has default) — .env
- `ADMIN_USER_IDS` (has default) — .env.example
- `CHAR_MONITOR_CHANNEL_ID` (has default) — .env
- `CLAUDE_KEY` (has default) — .env.example
- `CONVERSATION_TRIM_SIZE` (has default) — .env.example
- `DDB_COBALT_TOKEN` **required** — src\character_monitor.py
- `DEFAULT_MODEL` (has default) — .env.example
- `DEFAULT_PROVIDER` (has default) — .env.example
- `DISCORD_BOT_TOKEN` **required** — .env.example
- `DISCORD_CHANNEL_ID` **required** — .env.example
- `DISCORD_GUILD_ID` (has default) — .env
- `DM_USER_ID` (has default) — .env
- `GEMINI_KEY` (has default) — .env.example
- `GROK_KEY` (has default) — .env.example
- `IMAGE_STYLE` (has default) — .env
- `KIMI_ENABLE_SUBAGENTS` (has default) — .env.example
- `KIMI_MODEL` (has default) — .env.example
- `LEARN_HOUR_END` **required** — src\self_learning.py
- `LEARN_HOUR_START` **required** — src\self_learning.py
- `LOGGING` (has default) — .env.example
- `MAPS_CHANNEL_ID` **required** — src\mission_builder\maps.py
- `MAX_CONVERSATION_LENGTH` (has default) — .env.example
- `MISSION_BOARD_CHANNEL_ID` (has default) — .env
- `MISSION_RESULTS_CHANNEL_ID` (has default) — .env
- `MODULE_OUTPUT_CHANNEL_ID` (has default) — .env
- `MYSQL_DB` **required** — sql_refactor_setup.py
- `MYSQL_HOST` **required** — sql_refactor_setup.py
- `MYSQL_PASSWORD` **required** — sql_refactor_setup.py
- `MYSQL_USER` **required** — sql_refactor_setup.py
- `OLLAMA_MODEL` (has default) — .env.example
- `OLLAMA_URL` (has default) — .env.example
- `OPENAI_ENABLED` **required** — src\art.py
- `OPENAI_KEY` (has default) — .env.example
- `QWEN_MODEL` (has default) — .env.example
- `REPLYING_ALL` (has default) — .env.example
- `REPLYING_ALL_DISCORD_CHANNEL_ID` **required** — .env.example

## Config Files

- `.env.example`
- `Dockerfile`
- `docker-compose.yml`

## Key Dependencies

- openai: ^6.32.0
