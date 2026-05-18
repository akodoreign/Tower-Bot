# TowerBot Setup Notes

This is a clean source snapshot of the current bot code. The old `.git` directory, local `.env`, virtualenv, node_modules, logs, browser profile, generated modules, private campaign docs, and other runtime output were intentionally not copied.

## Quick Guided Setup

On Windows, run the guided setup script from the repository root:

```powershell
.\setup_new_campaign.ps1
```

The script walks a new user through campaign preferences, RAG/persona setup, Discord IDs, MySQL settings, Ollama, A1111, and optional dependency installation. It creates local-only files that should not be committed:

- `.env`
- `campaign_docs\rag_profile.txt`
- runtime folders such as `logs\` and `generated_modules\`

For the full manual walkthrough, read `docs/setup_walkthrough.md`.

## What is included

- Python bot source in `src/`
- Flask dashboard in `Webpage/`
- utility scripts in `scripts/`
- tests in `tests/`
- project skills, docs, schema references, and CodeSight navigation docs
- blank `campaign_docs/` placeholder only; live campaign data and training material are local-only
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

Use the guided setup script above, or do the basics manually:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install
Copy-Item .env.example .env
```

Edit `.env` and fill in secrets, Discord channel IDs, MySQL credentials, model names, and local tool paths.

## RAG and campaign preferences

The clean repo does not include private campaign documents. The setup script creates `campaign_docs\rag_profile.txt`, which seeds the local RAG behavior with the user's campaign name, persona, tone, rules policy, and source preferences.

Additional local lore can be added as `.txt` files in `campaign_docs/`. Those files are ignored by git by default.

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

The dashboard is served by the bot/web process currently used in production. If running the dashboard separately, use the `Webpage/` app entry point and match the desired port configuration.

## Tests

```powershell
python -m pytest
```

Some tests and smoke paths may require live Ollama, A1111, MySQL, Discord mocks, or local campaign state. Prefer focused tests for touched subsystems.

## Operational notes

- Do not set VAE override variables unless deliberately diagnosing A1111. VAE overrides have previously broken image generation on the original rig.
- Keep `.env`, logs, generated modules, `.venv`, `node_modules`, browser profiles, and live runtime data out of git.
- Coordinate bug work through `buglog.md` when multiple agents are working.
- Read `CLAUDE.md`, `buglog.md`, and `MAP.md` before changing code.
