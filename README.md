# Tower Bot

A campaign-aware Discord bot and web dashboard for tabletop RPG servers. It supports mission boards, generated adventure modules, NPC lifecycle tools, campaign RAG, local LLM routing through Ollama, optional A1111 image generation, MySQL-backed state, and a Flask dashboard.

This repository is a clean source snapshot intended for other tables to adapt. Private campaign notes, generated modules, logs, `.env`, local model state, and runtime output are intentionally excluded.

## Credits

This project began as a fork of the open-source ChatGPT Discord Bot project and has since been heavily extended for tabletop campaign operations, mission generation, local model routing, RAG, dashboard tooling, and D&D workflow integrations.

Credit and thanks to the original ChatGPT Discord Bot authors and contributors for the base Discord bot foundation. All campaign-specific extensions, Tower Bot workflows, mission generation systems, dashboard work, and operational tooling in this snapshot are maintained by akodoreign.

## What It Does

- Discord bot for campaign chat, commands, mission interaction, and admin workflows
- Mission board and module generation across multiple mission types
- Tactical map generation support through A1111/Stable Diffusion WebUI
- Campaign RAG from MySQL training documents and local `campaign_docs/*.txt` files
- NPC lifecycle, portraits, scenes, calendar hooks, faction state, and campaign utilities
- Flask dashboard in `Webpage/`
- MySQL-backed persistent state
- Local-first LLM support through Ollama, with optional provider integrations

## Quick Setup

Windows users can run the guided setup script:

```powershell
.\setup_new_campaign.ps1
```

The script walks through campaign preferences, RAG/persona setup, Discord IDs, MySQL settings, Ollama, A1111, and optional dependency installation. It writes local-only files such as `.env` and `campaign_docs\rag_profile.txt`.

For the full walkthrough, read:

```text
docs/setup_walkthrough.md
```

## Prerequisites

- Python 3.11
- MySQL 8 or compatible MySQL server
- Discord bot token and channel IDs
- Ollama, if using local language models
- Stable Diffusion WebUI/A1111, if using image generation
- Node.js, if using JavaScript document builder utilities

## Manual Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
npm install
Copy-Item .env.example .env
```

Then edit `.env` with local secrets, database values, Discord IDs, and model settings.

## Database

MySQL is the source of truth for live bot state. Use these files as references:

```text
database_schema.sql
docs/mysql_schema_reference.md
.codesight/schema.md
```

A minimal local database setup looks like:

```powershell
mysql -u root -p -e "CREATE DATABASE towerbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p towerbot < database_schema.sql
```

Match the database name and credentials in `.env`.

## RAG and Campaign Notes

The clean repository keeps `campaign_docs/` blank except for a placeholder. Each table should add its own local `.txt` files there, or import training documents into MySQL.

The setup script creates:

```text
campaign_docs\rag_profile.txt
```

That file records campaign name, assistant persona, tone, house rules, and source preferences. It is ignored by git so private lore stays private.

## Running

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

If you run the dashboard separately, use the `Webpage/` app entry point and configure the desired port for your deployment.

## Tests

```powershell
python -m pytest
```

Some tests and smoke paths expect local services such as MySQL, Ollama, A1111, or Discord mocks. Prefer focused tests for the subsystem you changed.

## Repository Hygiene

Do not commit:

- `.env`
- `.venv/`
- `node_modules/`
- logs
- generated modules
- local browser profiles
- private campaign notes in `campaign_docs/`

## Notes

VAE override variables should be left blank unless deliberately diagnosing A1111. VAE overrides have broken image generation on the original rig before.
