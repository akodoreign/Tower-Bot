# Tower Bot — The Tower of Last Chance

A Discord bot that runs a living D&D 5e (2024) campaign world. The **Tower of Last Chance** watches over the
Undercity: it posts the news, runs the mission board and the auction house, moves the weather and the markets, keeps
track of NPCs and adventuring parties, and answers players in character — between sessions, around the clock.

It runs on a local LLM stack (Ollama) with optional cloud providers, keeps all campaign data in MySQL, and can
generate full mission modules (`.docx`, with maps and portraits) for the DM.

---

## What it does

**A world that keeps moving**
- **News feed** — in-world bulletins on a schedule, with an optional DM approval step (`/newsdraft`).
- **Weather** — a simulated dome with 44 weather types.
- **Economy** — the EC/Kharma exchange rate, item prices and a stock-market sector index.
- **TowerBay** — an auction house: players list items from their character sheets, bid and buy out.
- **Factions** — reputation that shifts with events, plus a faction event calendar.
- **NPCs and parties** — rival adventuring parties with records and reputations; an NPC roster with daily life events
  (arrivals, departures, injuries, deaths), appearances and history.
- **Rifts, the arena, bounties, missing persons** — recurring threads the world posts about on its own.

**For the table**
- **Mission board** — new missions post to the board; NPC parties claim and complete them; players claim theirs, and
  the DM resolves the outcome (`/resolvemission`).
- **Mission modules** — a pipeline that turns a claimed mission into a DM-runnable module document with encounters,
  maps and NPC portraits (`/genmodule`).
- **In-character chat** — `/chat` talks to the Tower, with retrieval over the campaign so it remembers your world.
- **Rules lookup** — `/rules` and `/spell` for D&D 5e 2024 rules, conditions and spells.
- **Characters** — profiles and appearance notes per player character; style and clothing descriptions.
- **Images** — scene, NPC and location art through a local Stable Diffusion (A1111) server.

**Behind the scenes**
- Multi-agent generation (orchestrator, guild council, news agents) with a nightly self-learning loop.
- A web dashboard (Flask) with world state and loop-health monitoring.
- Optional sync with a Mimir campaign server for characters and equipment.

---

## Requirements

- **Python 3.11**
- **MySQL** — the authoritative store for all campaign data (schema in `database_schema.sql`)
- **[Ollama](https://ollama.com/)** — local LLM (the default model is set in `.env`, e.g. `qwen3-8b-slim`)
- **A Discord bot token** with the *Message Content* intent enabled
- Optional: **Stable Diffusion WebUI (A1111)** for images, API keys for OpenAI / Claude / Gemini / Grok, a Mimir server

## Setup

1. Clone the repository and install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill it in: the Discord token and channel IDs (news, mission board, mission
   results, maps), the MySQL connection, the Ollama URL and model, and any optional keys.
3. Create the database from `database_schema.sql`.
4. Create the bot at the [Discord Developer Portal](https://discord.com/developers/applications), turn on the
   *Message Content* intent, and invite it to your server.
5. Start it:
   ```bash
   python main.py
   ```
   The dashboard starts alongside the bot (port `DASHBOARD_PORT`, default 5000). On Windows, `start_tower.ps1`
   starts the whole stack (Ollama, A1111 and the bot) in order. Docker files are included as well.
6. In Discord, run `/sync` once so the slash commands register in your server.

---

## Commands

| Command | What it does |
|---|---|
| `/chat` | Talk to the Tower in character |
| `/reset` | Reset your chat history |
| `/rules`, `/spell` | Look up D&D 5e 2024 rules, conditions, spells and class features |
| `/setcharprofile`, `/showcharprofile` | Tell the Tower who your character is; see what it remembers |
| `/showcharappearance` | Show your character's saved appearance |
| `/style` | Clothing and style for a character or faction |
| `/finances`, `/prices` | The exchange rate, and item / spell / gear prices |
| `/towerbay`, `/myauctions` | List an item for auction; check your listings |
| `/bid`, `/buynow`, `/mybids` | Bid on, buy out, and track TowerBay lots |
| `/factionrep`, `/partyrep` | Faction standings; rival parties' records |
| `/skills` | The Tower's learned skills and knowledge |
| `/draw` | Generate an image of the Undercity |
| `/provider`, `/switchpersona` | Switch the AI provider or persona |
| `/private`, `/replyall`, `/help` | Reply settings and help |

**DM tools** (restricted): `/newsdraft`, `/resolvemission`, `/postmission`, `/postsubcontract`, `/genmodule`,
`/clearboard`, `/riftlist`, `/sealrift`, `/archive`, `/newareas`, `/generateareas`, `/drawscene`, `/pin`, `/refstats`,
`/backfill`, `/setcharappearance`, `/towerbay_restock`, `/npcgearrun`, `/standard`, `/epic`, `/sync`.

---

## Project layout

```
main.py                 entry point (bot + dashboard)
src/bot.py              loads the command modules
src/aclient.py          the Discord client and its background loops
src/cogs/               slash commands (chat, characters, missions, economy, images, world, admin...)
src/agents/             LLM agents and orchestration
src/mission_builder/    mission and module generation pipelines
src/db_api.py           MySQL access (the source of truth)
src/news_feed.py        bulletins and world events
Webpage/                the dashboard
skills/                 the Tower's skill library
tests/                  test suite
```

`MAP.md` has the full module-by-module map.

---

## Credits and license

Tower Bot began as a fork of [Zero6992/chatGPT-discord-bot](https://github.com/Zero6992/chatGPT-discord-bot) and has
grown into its own project. It is released under the **GNU General Public License v2.0** (see `LICENSE`).

D&D and Dungeons & Dragons are trademarks of Wizards of the Coast. This is an unofficial fan project.

---

## Support

This project is free and always will be. If you enjoy it and want to support me, you can
[buy me a coffee](https://buymeacoffee.com/akodoreign) — no strings attached, and thank you either way.
