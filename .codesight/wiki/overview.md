# chatgpt-discord-bot — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**chatgpt-discord-bot** is a python project built with flask, organized as a monorepo.

**Workspaces:** `tower-module-builder` (`src\docx_builder`), `Webpage` (`Webpage`)

## Scale

38 API routes · 15 database models · 300 library files · 6 middleware layers · 137 environment variables

## Subsystems

- **[Area-maps](./area-maps.md)** — 2 routes — touches: auth, db, cache, payment
- **[Arena](./arena.md)** — 1 routes — touches: auth, db, cache, queue, payment
- **[Bounties](./bounties.md)** — 1 routes — touches: auth, db, cache, payment
- **[Bulletins](./bulletins.md)** — 1 routes — touches: auth, db, cache, payment
- **[Claim-mission](./claim-mission.md)** — 1 routes — touches: auth, db, cache, queue, payment
- **[Compendium](./compendium.md)** — 3 routes — touches: auth, db, cache, queue, payment
- **[Complete-mission](./complete-mission.md)** — 1 routes — touches: auth, db, cache, payment
- **[Districts](./districts.md)** — 3 routes — touches: auth, db, cache, payment
- **[Drafts](./drafts.md)** — 1 routes — touches: auth, db, cache, payment
- **[Factions](./factions.md)** — 1 routes — touches: auth, db, cache, payment
- **[Generate-mission](./generate-mission.md)** — 1 routes — touches: auth, db, cache, payment
- **[Image-refs](./image-refs.md)** — 1 routes — touches: auth, db, cache, payment
- **[Log-bug](./log-bug.md)** — 1 routes — touches: auth, db, cache, queue, payment
- **[Logs](./logs.md)** — 1 routes — touches: auth, db, cache, payment
- **[Media](./media.md)** — 1 routes — touches: auth, db, cache, payment
- **[Mission-maps](./mission-maps.md)** — 1 routes — touches: auth, db, cache, queue, payment
- **[Mission-types](./mission-types.md)** — 1 routes — touches: auth, db, cache, payment
- **[Missions](./missions.md)** — 2 routes — touches: auth, db, cache, payment
- **[Modules](./modules.md)** — 4 routes — touches: auth, db, cache, payment
- **[Npcs](./npcs.md)** — 2 routes — touches: auth, db, cache, payment
- **[Parties](./parties.md)** — 1 routes — touches: auth, db, cache, payment
- **[Places](./places.md)** — 1 routes — touches: auth, db, cache, payment
- **[Portraits](./portraits.md)** — 1 routes — touches: auth, db, cache, queue, payment
- **[Post-mission-to-discord](./post-mission-to-discord.md)** — 1 routes — touches: auth, db, cache, queue, payment
- **[Print](./print.md)** — 1 routes — touches: auth, db, cache, payment
- **[Status](./status.md)** — 1 routes — touches: auth, db, cache, payment
- **[View-mode](./view-mode.md)** — 1 routes — touches: auth, db, cache, payment
- **[Infra](./infra.md)** — 1 routes — touches: auth, db, cache, payment

**Database:** unknown, 15 models — see [database.md](./database.md)

**Libraries:** 300 files — see [libraries.md](./libraries.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `/schemas.py` — imported by **6** files
- `/layouts.py` — imported by **5** files
- `/competition_types.py` — imported by **4** files
- `/locations.py` — imported by **3** files
- `/encounters.py` — imported by **3** files
- `/mission_json_builder.py` — imported by **3** files

## Required Environment Variables

- `A1111_EXPERIMENT_BASE_CFG` — `scripts\experiment_map_lanes.py`
- `A1111_EXPERIMENT_BASE_STEPS` — `scripts\experiment_map_lanes.py`
- `A1111_EXPERIMENT_FLUX_CFG` — `scripts\experiment_map_lanes.py`
- `A1111_EXPERIMENT_FLUX_STEPS` — `scripts\experiment_map_lanes.py`
- `A1111_EXPERIMENT_SDXL_CFG` — `scripts\experiment_map_lanes.py`
- `A1111_EXPERIMENT_SDXL_STEPS` — `scripts\experiment_map_lanes.py`
- `A1111_EXPERIMENT_TIMEOUT` — `scripts\experiment_map_lanes.py`
- `A1111_FLUX_CHECKPOINT` — `archive\backups_old\backups\codex_20260507_155641\vtt_renderer.py`
- `A1111_MAP_COOLDOWN_SECONDS` — `archive\backups_old\backups\codex_20260507_155641\vtt_renderer.py`
- `A1111_MAP_IDLE_TIMEOUT` — `archive\backups_old\backups\codex_20260507_155641\vtt_renderer.py`
- `A1111_MAP_LORA` — `src\mission_builder\image_generator.py`
- `A1111_MAP_MAX_ROUNDS` — `archive\backups_old\backups\codex_20260508_bug2_map_contract\src\mission_builder\maps.py`
- _...66 more_

---
_Back to [index.md](./index.md) · Generated 2026-05-17_