# TowerBot Setup Notes

This is a clean source snapshot of the current Tower of Last Chance bot code. The old `.git` directory, local `.env`, virtualenv, node_modules, logs, browser profile, generated modules, and other runtime output were intentionally not copied.

## What is included

- Python bot source in `src/`
- Flask dashboard in `Webpage/`
- utility scripts in `scripts/`
- tests in `tests/`
- project skills, docs, schema references, and CodeSight navigation docs
- `campaign_docs/city_gazetteer.json` and `campaign_docs/TrainingPDFS/` reference material
- a fresh `.env.example` with placeholders only

## Prerequisites

- Python 3.11
- MySQL reachable by the values in `.env`
- Ollama running locally, normally at `http://localhost:11434`
- Stable Diffusion WebUI/A1111 running locally, normally at `http://127.0.0.1:7860`, if image generation is enabled
- Node.js if using the JavaScript document builder utilities
- Discord bot token and channel IDs
- Optional: Mimir MCP binary and D&D Beyond credentials/tokens for those integrations

## First-time setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install
Copy-Item .env.example .env
```

Edit `.env` and fill in secrets, Discord channel IDs, MySQL credentials, model names, and local tool paths.

## Database

MySQL is the authoritative data store. Use `database_schema.sql` and `docs/mysql_schema_reference.md` as schema references. Do not rely on legacy JSON files for live campaign data.

At minimum, configure these values in `.env`:

```text
MYSQL_HOST=
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DB=
```

## Running locally

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

The dashboard is served by the bot/web process currently used in production. If running the dashboard separately, use the `Webpage/` app entry point and match the production port configuration.

## Tests

```powershell
python -m pytest
```

Some tests and smoke paths may require live Ollama, A1111, MySQL, Discord mocks, or local campaign state. Prefer focused tests for touched subsystems.

## Operational notes

- Do not set VAE override variables unless deliberately diagnosing A1111. VAE overrides have previously broken image generation on this rig.
- Keep `.env`, logs, generated modules, `.venv`, `node_modules`, browser profiles, and live runtime data out of git.
- Coordinate bug work through `buglog.md` when multiple agents are working.
- Read `CLAUDE.md`, `buglog.md`, and `MAP.md` before changing code.
