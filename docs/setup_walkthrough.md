# New Campaign Setup Walkthrough

This repository is a clean source snapshot. It intentionally excludes private campaign notes, generated modules, logs, `.env`, `.venv`, browser profiles, and other local runtime data.

The fastest setup path on Windows is:

```powershell
.\setup_new_campaign.ps1
```

The guided script does four jobs:

1. Creates `.env` from `.env.example` if needed.
2. Asks for campaign, persona, tone, rules, Discord, MySQL, Ollama, and A1111 preferences.
3. Writes a campaign-neutral `system_prompt.txt`.
4. Writes `campaign_docs\rag_profile.txt`, which is local-only and ignored by git.

## Prerequisites

Install these before running the bot:

- Python 3.11
- MySQL 8 or a compatible MySQL server
- Ollama, if using local language models
- Stable Diffusion WebUI/A1111, if using image generation
- Node.js, if using document builder utilities
- A Discord application and bot token

## Discord Setup

Create a Discord app in the Discord Developer Portal, add a bot, and copy the bot token into `.env` as `DISCORD_BOT_TOKEN`.

Create or choose the channels used by the bot, then copy channel IDs into `.env`:

```text
DISCORD_CHANNEL_ID=
REPLYING_ALL_DISCORD_CHANNEL_ID=
MISSION_BOARD_CHANNEL_ID=
MAPS_CHANNEL_ID=
CHAR_MONITOR_CHANNEL_ID=
```

The bot needs the permissions required by your server setup, commonly reading messages, sending messages, adding reactions, attaching files, and using slash commands.

## Database Setup

Create a database and user, then apply the schema:

```powershell
mysql -u root -p -e "CREATE DATABASE towerbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p towerbot < database_schema.sql
```

Then put the connection values in `.env`:

```text
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=towerbot
MYSQL_PASSWORD=your-password
MYSQL_DB=towerbot
```

You may use a different database name. Match whatever you choose in `.env`.

## RAG and Campaign Notes

This clean repo keeps `campaign_docs/` blank in git. The setup script creates `campaign_docs/rag_profile.txt` locally. That file tells the RAG layer how to behave for this user's campaign without assuming the Tower of Last Chance setting.

Add more local lore as `.txt` files in `campaign_docs/`, for example:

```text
campaign_docs\factions.txt
campaign_docs\locations.txt
campaign_docs\house_rules.txt
campaign_docs\session_zero.txt
```

Keep one subject per file when possible. Private lore files in `campaign_docs/` are ignored by git by default.

The bot can also read imported training documents from MySQL. Use the local text files as the simple first path, then import larger references once the database workflow is ready.

## Local Models

For Ollama, set:

```text
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-8b-slim:latest
OLLAMA_FAST_MODEL=qwen3-8b-slim:latest
```

For A1111, set:

```text
A1111_URL=http://127.0.0.1:7860
A1111_MODEL=
MODULE_GENERATE_MAPS=true
```

Leave VAE override values blank unless you are deliberately diagnosing A1111. VAE overrides have broken image generation on the original rig before.

## Install Dependencies

The setup script can optionally install dependencies. Manual commands are:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
npm install
```

## Run the Bot

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

If you run the dashboard separately, use the `Webpage/` app entry point and make sure any configured port matches your deployment.

## Tests

```powershell
python -m pytest
```

Some tests and smoke paths expect local services such as MySQL, Ollama, A1111, or Discord mocks. Prefer focused tests for the subsystem you changed.

## What To Keep Out Of Git

Do not commit:

- `.env`
- `.venv/`
- `node_modules/`
- logs
- generated modules
- local browser profiles
- private campaign notes in `campaign_docs/`

The repository keeps a blank `campaign_docs/.gitkeep.md` only so new users know where local notes belong.
