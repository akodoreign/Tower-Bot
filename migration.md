# JSON to DB/API Migration Plan

Generated: 2026-05-22

This is an exploration and migration plan only. No source code or campaign JSON data was changed as part of this pass.

## Scope

Scanned active project JSON files while excluding generated module output, dependency folders, browser profiles, battle map downloads, and training PDF assets. JSON families are grouped where the code treats the directory as one state surface.

Package metadata, MCP config, skill metadata, and lockfiles are not campaign state and should stay file based unless the build/deployment process changes.

## Executive Summary

The project is already partly migrated to MySQL. Missions, bounties, NPC appearances, party profiles, character snapshots, faction reputation, weather, economy, missing persons, rift state, TIA, TowerBay, and player listings all have DB tables or DB-facing code paths.

The main migration risk is stale dual-authority: some modules read from DB, while comments, skills, or fallback routines still reference old JSON files. That can make an issue look fixed in one surface while Discord, Mimir, dashboard port 5001, or mission generation still sees older file state.

Highest-priority migration targets:

1. `campaign_docs/city_gazetteer.json` because mission locations, map matching, news context, and Mimir/world context still touch it directly.
2. `campaign_docs/npc_roster.json` because NPC identity, lifecycle, appearance, and news validation need one canonical source.
3. `campaign_docs/mission_memory.json` because source comments and older routines still describe it even though mission state is mostly DB now.
4. Generated type/state JSONs because the dashboard and learning cycle should consume them through DB/API, not local files.
5. Singleton campaign state files such as economy, weather, council rulings, arena venues, faction calendar, and used parties.

## Outside-In Migration Order

This is the recommended execution order from the furthest-out data to the innermost runtime core. The goal is to retire/archive one layer at a time while keeping Discord, dashboard 5001, Mimir, mission pipelines, and MySQL pointed at the same authority.

Rule of thumb:

- **Outer layers** are artifacts, staging data, exports, and optional history. They can be archived first because running code should not depend on them.
- **Middle layers** are reference/world state. They influence generation quality and continuity but can usually be migrated behind helper APIs.
- **Inner layers** are live runtime state. They touch claims, missions, NPC lifecycle, Discord messages, dashboard views, Mimir sync, and scheduled jobs. These need the most careful cutover.

### Layer 0: Non-Campaign JSON To Exclude

Archive action: none. Keep these as files and exclude them from future migration audits.

| File family | Why it stays outside migration |
|---|---|
| `package*.json`, `src/docx_builder/package*.json` | Build/dependency metadata. |
| `.mcp.json`, `.claude/settings*.json`, skill metadata | Tool and agent configuration. |
| `.venv/**`, `.chrome_ddb_profile/**` | Dependency/browser cache state. |
| `logs/ddb_vtt_probe.json` | Diagnostic output. |

Done condition:

- Migration scripts ignore these paths by default.
- `migration.md` keeps them listed as explicitly out of scope.

### Layer 1: Generated Outputs And Learning/Test Artifacts

Archive action: keep as immutable output folders or move to a dated archive. Do not migrate into operational tables unless a dashboard/search feature truly needs them.

| File family | Plan |
|---|---|
| `generated_modules/**/maps_manifest.json`, `*.vtt.json` | Keep with generated module output. Optional: index module/map metadata in DB, but the artifact body should remain with the module. |
| `logs/learning/test_modules/*.json` | Keep as learning logs. Only migrate summaries/scores into `module_quality_samples` if the learning cycle needs queryable history. |
| `campaign_docs/archives/**/*.json` | Keep immutable unless a specific archive search/API is requested. |
| `campaign_docs/TrainingPDFS/*.json` | Treat as corpus build artifacts. If needed live, migrate text/chunks to `training_docs` or `training_chunks`, not raw JSON. |

Done condition:

- These paths are marked archive/log/build artifacts.
- No runtime Discord/dashboard/Mimir/mission code reads them for current state.

### Layer 2: One-Off Import/Staging JSON

Archive action: import if useful, then move to dated archive with source hash. These should not remain live state.

| File family | DB/API destination | Plan |
|---|---|---|
| `scripts/npc_ddb_staging.json` | Optional `ddb_import_batches` / `ddb_import_rows` | Keep file-based unless DDB imports become recurring. If recurring, create import batch tables and archive each staging file after successful import. |
| `scripts/creature_ddb_staging.json` | Optional `ddb_import_batches` / `ddb_import_rows` | Same as NPC staging. |
| `campaign_docs/faction_leaders_to_add.json`, `campaign_docs/faction_leaders_new.json` | `npcs`, `faction_reputation`, `faction_events` | Import useful leaders into canonical NPC/faction tables, then archive. |

Done condition:

- No scheduler/runtime process reads these files.
- Any imported rows record source filename/hash where practical.

### Layer 3: Historical Player/Character Exports

Archive action: backfill missing DB identity links, verify parity, then archive sidecars.

| File family | DB/API destination | Plan |
|---|---|---|
| `campaign_docs/char_snapshots/*.json` | `character_snapshots`, `latest_character_snapshots` | DB already has 30 snapshots and 8 latest rows. Import any file-only history that matters, then archive snapshots as exports. |
| `src/character_appearance/*.json` | `player_characters.profile_json` | DB already has appearance text for all 8 PCs; sidecars cover only 3. Backfill `player_discord_id` first so Discord commands do not create duplicate rows. Then compare/import sidecars and archive. |
| `campaign_docs/character_memory.txt` | Generated export from `player_characters`/snapshots | Keep only as generated RAG/export artifact. Do not use as writable source of truth. |

Done condition:

- Discord character commands load the intended `player_characters` row by `player_discord_id`.
- Mimir and mission pipelines read `player_characters` / `latest_character_snapshots`.
- Character sidecar JSON files are no longer a live fallback.

### Layer 4: Market, Economy, And Scheduler State

Archive action: migrate into existing DB tables/global state, then archive old JSON after parity checks.

| File | DB/API destination | Plan |
|---|---|---|
| `campaign_docs/ec_exchange.json` | `economy_state` or typed economy table | Import current exchange value/trend/history if useful. |
| `campaign_docs/economy_cadence.json` | `global_state.economy_cadence` or `scheduler_state` | DB already has `economy_cadence`; merge old file-only keys before archive. |
| `campaign_docs/tia.json` | `tia_market`, plus `global_state.tia_market_state` for whole-market metadata | Keep sectors row-based; preserve `last_event` somewhere DB-backed. |
| `campaign_docs/towerbay.json` | `towerbay_auctions.auction_json` | Live DB has more rows than file. Import only file-only history. |
| `campaign_docs/player_listings.json` | `player_listings.listing_json` | Live table is empty; import the 2 rich historical listings and bid logs. |

Done condition:

- Dashboard/API has typed routes for economy, TIA, TowerBay, and player listings.
- Scheduled economy/news posts read/write DB only.
- Old files can be regenerated as exports if wanted.

### Layer 5: World Reference Data And Maps

Archive action: make DB the canonical reference layer; keep JSON only as seed/export.

| File/family | DB/API destination | Plan |
|---|---|---|
| `campaign_docs/city_gazetteer.json` | `gazetteer`, `gazetteer_places`, `area_profiles`; optional `gazetteer_districts` / `gazetteer_edges` | Live DB already has 312 places and 27 area profiles. Replace direct file readers in area map generation, Mimir sync, location helpers, dungeon delve, seed scripts, and stale comments/docs. |
| downloaded battle maps | `battle_maps_library`, `battle_map_area_memory` | Already DB-indexed. Mission pipelines should request maps through `src.battle_map_library` or the mission-builder map wrapper, never scan downloads. |
| `campaign_docs/arena_venues.json` | Short term `global_state.arena_venues`; long term `arena_venues` table | Import now to satisfy existing `news_agents` behavior; table later if filtering matters. |
| `campaign_docs/dome_weather.json` | `weather_state` or `global_state.dome_weather` | DB-backed weather exists; verify no live file fallback remains. |
| `campaign_docs/rift_state.json` | `rift_state`, optional `rift_events` | Preserve active/current rift in `rift_state`; use event table if historical rifts matter. |

Done condition:

- Mission location selection, map matching, news context, Mimir world overview, and dashboard area pages all use DB/API.
- `battle_map_area_memory` has no easily recoverable blank `district_slug`/`map_type` rows.
- `city_gazetteer.json` can be archived or regenerated from DB.

### Layer 6: News, Civic Arcs, And Faction State

Archive action: migrate into DB/global state, then remove file guidance that can reintroduce JSON drift.

| File | DB/API destination | Plan |
|---|---|---|
| `campaign_docs/generated_news_types.json` | `global_state.generated_news_types` or `news_types` | DB key already exists. Use one canonical DB path for learning/news generation. |
| `campaign_docs/faction_reputation.json` | `faction_reputation`, `faction_events`, `faction_affiliations` | File is a subset of DB by faction names. Archive after docs and skills stop pointing at it. |
| `campaign_docs/faction_calendar.json` | `faction_events` | Import future beats/scheduled faction events. |
| `campaign_docs/council_rulings.json` | `global_state.council_rulings` or dedicated `council_rulings` table | DB key already has rulings. Use a table only if rulings need filtering/mechanics. |
| public health / outbreak state | `global_state.public_health_arcs`, `world_active_tensions`, `news_entries`, `news_memory` | Already has the right DB shape. Make mission generation read these DB arcs when creating affected-populace missions. |

Done condition:

- News generation, mission hooks, and Mimir context read the same DB faction/civic state.
- Skills/docs no longer tell agents to edit faction/news JSON.
- Long-running arcs such as flu/magic-resistant-virus live for weeks through DB state, not a file.

### Layer 7: Actor Reference Data

Archive action: verify parity, replace file scans/fallbacks, then archive sidecars.

| File/family | DB/API destination | Plan |
|---|---|---|
| `campaign_docs/npc_roster.json` | `npcs`, `npc_appearances`, `resurrection_queue`, `faction_events` | File appears to be a subset of DB; meaningful fields are covered by columns/JSON blobs. Remove first-run/file fallback behavior and stale docs. |
| `campaign_docs/npc_appearances/*.json` | `npc_appearances`, `npcs.appearance_json`, `image_refs` | Import remaining file-only appearances, then remove `npc_lookup.py` sidecar fallback. Keep actual image media files. |
| `campaign_docs/party_profiles/*.json` | `party_profiles`, optional `party_usage_events` | All 110 files matched DB. Preserve one `oracle_notes` field, then replace `news_feed.py` directory scan. |
| `campaign_docs/used_parties.json` | `global_state.used_parties` now; better `party_usage_events` later | Merge file-only/DB-only values deliberately. Prefer events over a mutable list if selection history matters. |

Done condition:

- NPC lifecycle, news validation, image generation, party selection, and mission pipelines all use DB helpers.
- Graveyard/resurrection flow writes DB status and `resurrection_queue`, not roster/graveyard files.
- Party usage/claim selection no longer mutates a JSON list.

### Layer 8: Bulletin-Like Operational State

Archive action: widen tables first, then backfill and archive. These are close to runtime because news and missions can spawn from them.

| File | DB/API destination | Plan |
|---|---|---|
| `campaign_docs/bounty_board.json` | widened `bounties` with `body`, `issuer`, `proxy_faction`, `posted_at`, `expires_at`, `message_id`, `bounty_json` | Current DB writes are lossy. Add columns/update writer before import. |
| `campaign_docs/missing_persons.json` | widened `missing_persons` with `notice_body`, `filed_by`, `posted_at`, `expires_at`, `resolved_at`, `record_json` | Current DB writes drop body/circumstances. Add columns/update writer before import. |

Done condition:

- Bounty and missing-person Discord posts can be reconstructed from DB.
- Dashboard/Mimir can see full notice text and status.
- Expiration/resolution routines update DB rows without needing file history.

### Layer 9: Mission Type And Pipeline Configuration

Archive action: consolidate generated/template state into DB before touching mission runtime.

| File | DB/API destination | Plan |
|---|---|---|
| `campaign_docs/generated_mission_types.json` | `mission_type_templates` plus `global_state.generated_mission_types` if needed | Live DB has 34 `mission_type_templates`; prefer that for pipeline/template behavior. Use `global_state` only for generated rotation metadata. |
| mission pipeline map-selection assumptions | `battle_maps_library`, `battle_map_area_memory` | Ensure every pipeline calls the same map wrapper and records map memory consistently. |

Done condition:

- Dashboard `/api/mission-types`, mission board, learning cycle, and pipelines agree on the same mission type/template list.
- Pipeline map usage is DB library plus memory, not generation or file scanning.

### Layer 10: Mission Runtime Core

Archive action: this is last. Add missing lifecycle storage, backfill, then cut over.

| File | DB/API destination | Plan |
|---|---|---|
| `campaign_docs/mission_memory.json` | `missions`, `mission_outcomes`, new `mission_claims`, new `mission_lifecycle_events`, and `mission_json` for mission-specific extras | All 333 old entries match live mission titles, but important lifecycle fields are missing from DB. Do not delete until those fields are preserved. |

Required before archive:

1. Add `mission_claims` for current claim state: claimant type/name, claim time, claim message id, scheduled NPC completion, outcome status/json.
2. Add `mission_lifecycle_events` for audit/history: claim, post, complete, fail, expire, NPC checkout, NPC return-to-graveyard, module generated.
3. Backfill old `claim_message_id`, `npc_complete_at`, `npc_outcome`, `claim_at`, `claim_party`, `opposing_faction`, `personal_for`, `doppelganger_of`, and missing `expires_at`.
4. Update Discord claim/complete/fail handlers, dashboard claim flow, NPC party claim flow, and mission outcome backfills to use the new DB storage.
5. Verify dashboard claimed/completed tabs, Discord result posts, Mimir mission context, module generation, and NPC lifecycle behavior.

Done condition:

- `mission_memory.json` contains no live-only data.
- New claims from dashboard and Discord create DB lifecycle rows.
- NPC parties can claim strange occurrences and any graveyard return/resolution flow is represented in DB.
- Mission pipelines can read mission context from DB without file fallback.

### Layer 11: Skills, Docs, And Agent Memory Cleanup

Archive action: update guidance last, after runtime is actually cut over.

Targets:

- `skills/tower-bot/SKILL.md`
- `skills/tower-bot-files/SKILL.md`
- `skills/dnd-mission-docx/SKILL.md`
- `skills/stepped-operations/SKILL.md`
- `skills/windows-mcp-access/SKILL.md`
- stale comments in runtime files that still mention JSON as canonical

Done condition:

- Future agents are told: DB/API is king.
- JSON files are described only as seed/import/export/archive artifacts.
- Direct JSON-read audit becomes a small allowlist, not a sprawling cleanup hunt.

## Outside-In Cutover Checklist

For each layer, use this same sequence:

1. Classify each JSON file as `keep`, `archive`, `staging`, `seed`, or `live-state-to-migrate`.
2. Run a parity check against live MySQL.
3. Add/widen DB schema only if current tables would lose data.
4. Add typed `db_api` helpers before editing Discord/dashboard/pipeline callers.
5. Backfill from JSON into DB with source hash and timestamp where practical.
6. Switch runtime readers/writers to DB/API.
7. Verify Discord, dashboard 5001, Mimir, and mission pipeline behavior.
8. Archive the JSON file or convert it to generated export only.
9. Update docs/skills/comments so the old file path does not come back.

## Active JSON Inventory

| JSON file or family | What it stores | Known code/docs that touch it | DB target | API target | Migration plan |
|---|---|---|---|---|---|
| `campaign_docs/city_gazetteer.json` | Canonical city/area/place lore, districts, tags, hooks, travel context | `scripts/seed_battle_maps.py`, `src/area_map_generator.py`, `src/mission_builder/locations.py`, `src/mission_builder/dungeon_delve/__init__.py`, `src/mimir_sync.py`, `src/agents/news_agents.py`, docs/skills, dashboard DB readers | Existing `gazetteer`, `gazetteer_places`, `area_profiles`; possibly add `gazetteer_districts` and `gazetteer_edges` | `GET /api/gazetteer`, `GET /api/gazetteer/places`, `GET /api/areas`, admin `PUT`/`PATCH` endpoints | Import the file as the canonical seed, then replace direct file readers with `db_api` functions. Keep a manual export command for backup, but remove runtime file authority. This should be first because map selection and mission context depend on area tags. |
| `campaign_docs/npc_roster.json` | NPC roster, identity, role, faction, location, lifecycle hints | `src/npc_appearance.py`, `src/npc_lookup.py`, `src/news_feed.py` comments/fallbacks, `src/npc_consequence.py` comments, `cogs/images.py` through appearance helpers, docs/skills | `npcs`, `npc_appearances`, `resurrection_queue`, possibly `faction_events` for lifecycle impacts | `GET /api/npcs`, `GET /api/npcs/{id}`, `PATCH /api/npcs/{id}`, `GET /api/npc-appearances` | Verify every roster NPC exists in `npcs`. Move any remaining file-only fields into `npcs.data_json` or explicit columns. Remove file fallback after parity. |
| `campaign_docs/mission_memory.json` | Historical mission memory, outcomes, reuse guards | `src/mission_board.py` comments, `src/module_quality_trainer.py` comments, docs/skills | `missions`, `personal_missions`, possible new `mission_outcomes` or `mission_memory_events` | `GET /api/missions`, `GET /api/missions/{id}`, `GET /api/mission-memory` | Confirm all active runtime reads already use DB. If any useful legacy history remains, import it into a memory/events table keyed by mission id, area, faction, and party. Archive JSON after parity. |
| `campaign_docs/generated_mission_types.json` | Learned or generated mission type definitions | Docs/skills, `src/mission_board.py` uses/generated equivalent in `global_state` | Existing `mission_types` or `global_state.generated_mission_types`; long term prefer `mission_type_templates` | `GET /api/mission-types`, admin `POST/PATCH /api/mission-types` | Treat DB as authoritative. If still present on disk, import once, dedupe by slug/name, then remove runtime file reads. |
| `campaign_docs/generated_news_types.json` | Learned or generated news bulletin type definitions | Docs/skills, news generation routines by concept | Existing `news_types` or `global_state.generated_news_types` | `GET /api/news-types`, admin `POST/PATCH /api/news-types` | Same as mission types. Use DB/API so Discord headlines, dashboard previews, and learning cycle share one source. |
| `campaign_docs/faction_reputation.json` | Faction reputation by faction/player/party and notes | Source comments indicate DB is already authoritative; docs/skills still mention JSON | `faction_reputation`, `faction_events` | `GET /api/factions/reputation`, `PATCH /api/factions/reputation` | Run a parity import/check. Archive old JSON once row counts and faction keys match. |
| `campaign_docs/faction_calendar.json` | Scheduled faction events and future beats | Faction/news cadence docs and likely faction bulletin routines | `faction_events`; scheduler metadata can go in `global_state` | `GET /api/faction-calendar`, admin scheduling endpoints | Create/verify event rows with dates, factions, severity, and source. News/missions should query DB for active and upcoming faction beats. |
| `campaign_docs/faction_leaders_to_add.json`, `campaign_docs/faction_leaders_new.json` | One-time faction leader staging/import data | Import/planning artifacts, docs references | `npcs`, `faction_reputation`, possibly `faction_events` | Admin import endpoint or script-only | Treat as staging, not live state. Import into `npcs` and faction tables, then archive with source hash. |
| `campaign_docs/ec_exchange.json` | EC/Kharma exchange state | Economy docs/skills; economy code appears DB-oriented | `economy_state`; optional `economy_events` | `GET /api/economy/exchange`, `PATCH /api/economy/exchange` | Import current value/trend. Ensure dashboard and Discord economy posts read DB only. |
| `campaign_docs/economy_cadence.json` | Economy posting cadence and last-run timestamps | Economy scheduler/cadence references | `global_state` or new `scheduler_state` | `GET /api/scheduler/economy`, admin reset endpoint | Move cadence to DB so restarts and dashboard controls agree. |
| `campaign_docs/dome_weather.json` | Dome weather state and effects | Weather/news routines and docs | `weather_state` | `GET /api/weather`, `PATCH /api/weather` | Import current weather/effects. Convert file readers to DB/API. |
| `campaign_docs/council_rulings.json` | Council rulings and legal/political outcomes | News/lore docs, likely bulletin context | New `council_rulings` table or `news_entries` with `category='council'` | `GET /api/council/rulings`, admin create endpoint | Use a dedicated table if rulings affect mechanics or missions; use news entries if they are only historical headlines. |
| `campaign_docs/arena_venues.json` | Arena venue names, tags, locations, flavor | Arena/news/mission context | New `arena_venues`; existing `arena_seasons` keeps season state | `GET /api/arena/venues` | Import as reference data. Mission generation should query tagged venues from DB. |
| `campaign_docs/bounty_board.json` | Active bounty board | Bounty board routines, dashboard equivalents | `bounties` | `GET /api/bounties`, claim/complete endpoints | DB table exists. Import any file-only bounties, then remove JSON as runtime source. |
| `campaign_docs/missing_persons.json` | Missing person hooks/cases | News and mission hooks | `missing_persons` | `GET /api/missing-persons` | DB table exists. Convert generators to query DB cases and write status changes through API/db_api. |
| `campaign_docs/rift_state.json` | Rift activity, effects, severity | Rift/news/mission context docs; DB API appears present | `rift_state` | `GET /api/rifts`, `PATCH /api/rifts/{id}` | Import any remaining file state. Ensure missions and bulletins use DB rift state. |
| `campaign_docs/player_listings.json` | Player market/listing data | Marketplace/dashboard routines | `player_listings` | `GET /api/player-listings` | DB table exists. Verify parity, then archive JSON. |
| `campaign_docs/towerbay.json` | TowerBay auction data | TowerBay/economy routines | `towerbay_auctions` | `GET /api/towerbay` | DB table exists. Import active auctions and close/archive old JSON. |
| `campaign_docs/tia.json` | TIA market entries | TIA/economy routines | `tia_market` | `GET /api/tia` | DB table exists. Import active entries and switch writers to DB. |
| `campaign_docs/used_parties.json` | Party usage/selection memory | `src/party_profiles.py` references old file plus DB profiles | `party_profiles`; usage/cooldown can live in `global_state` or new `party_usage_events` | `GET /api/parties`, `GET /api/party-usage` | Import as usage history. Future party selection should write DB events, not mutate a JSON list. |
| `campaign_docs/npc_appearances/*.json` | Per-NPC visual profile, SD prompt, portrait metadata | `src/npc_appearance.py`, `src/npc_lookup.py`, `src/news_feed.py`, `Webpage/app.py`, `cogs/images.py`, DDB import scripts | `npc_appearances`, `image_refs`, `npcs.appearance_json` where needed | `GET /api/npc-appearances`, `GET /api/npcs/{id}/appearance` | DB appears authoritative already. Import any remaining file-only records, keep image media files, remove JSON sidecar fallback when safe. |
| `campaign_docs/party_profiles/*.json` | Per-party profile, members, tone, mission fit | `src/party_profiles.py`, mission pipelines, `src/tower_economy.py`, `src/news_feed.py`, `src/npc_lifecycle.py`, dashboard parties routes | `party_profiles` | `GET /api/parties`, `GET /api/parties/{id}` | DB table exists. Import stale file profiles and remove runtime fallback. Use API for dashboard and mission selection. |
| `campaign_docs/char_snapshots/*.json` | DDB character snapshots and previous versions | `src/character_monitor.py`, `src/character_profiles.py`, character dashboard/API | `character_snapshots`, `player_characters` | `GET /api/characters`, `GET /api/characters/{id}/snapshots` | DB table exists. Import snapshots, including useful `_prev` history. Treat files as archival exports after migration. |
| `src/character_appearance/*.json` | Player character appearance/art preferences | `src/character_profiles.py`, `src/cogs/character.py` appearance commands | `player_characters.profile_json` or new `character_appearances` | `GET /api/characters/{id}/appearance`, `PATCH /api/characters/{id}/appearance` | Migrate into DB so Discord commands and dashboard see the same appearance settings. |
| `logs/learning/test_modules/*.json` | Learning-cycle generated module samples and grades | `src/module_quality_trainer.py` | Optional new `module_quality_samples`; otherwise logs stay file based | Optional admin/learning API | Low priority. If the learning loop needs historical analytics, migrate. If these are just artifacts, keep as logs and exclude from live state. |
| `logs/ddb_vtt_probe.json` | Diagnostic probe output | DDB/VTT probe/debug scripts | None | None | Keep as diagnostic file, not campaign state. |
| `scripts/npc_ddb_staging.json` | NPC DDB import staging | `scripts/npc_ddb_builder.py`, `scripts/import_npcs_to_ddb.py`, `scripts/enrich_creatures_ddb.py` | Optional `ddb_import_batches` / `ddb_import_rows` | Admin import status endpoint only if repeated often | Treat as staging. Do not move to live API unless imports become recurring workflow. |
| `scripts/creature_ddb_staging.json` | Creature DDB import staging | `scripts/build_creature_staging.py`, `scripts/enrich_creatures_ddb.py` | Optional `ddb_import_batches` / `ddb_import_rows` | Same as above | Same as above. |
| `campaign_docs/archives/*.json` and old generated archives | Historical snapshots/backups | Archive readers or manual inspection only | Optional archive tables if searchable history is needed | Usually none | Keep immutable unless there is a specific need to query them in dashboard/API. |

## Files That Should Stay File-Based

| File/family | Reason |
|---|---|
| `.mcp.json` | Local tool/MCP configuration, not campaign state. |
| `package.json`, `package-lock.json`, `src/docx_builder/package.json`, `src/docx_builder/package-lock.json` | Node dependency/build metadata. |
| `.codex/skills/**/package*.json` and skill metadata | Agent/tooling metadata. |
| Temporary browser/profile JSON | Runtime browser state, not app data. |

## Migration Architecture

Use DB as the only runtime authority. JSON files can remain as seed imports, archival exports, diagnostics, or staging artifacts, but Discord, dashboard port 5001, Mimir, mission pipelines, and learning agents should not make runtime decisions from JSON once a surface is migrated.

Suggested shared access layer:

| Data surface | DB/API access function family |
|---|---|
| Gazetteer/areas/tags | `db_api.get_gazetteer_places()`, `db_api.get_area_profile()`, `db_api.search_area_tags()` |
| NPCs | `db_api.get_npc()`, `db_api.search_npcs()`, `db_api.update_npc_status()` |
| NPC appearance | `db_api.get_npc_appearance()`, `db_api.upsert_npc_appearance()` |
| Party profiles | `db_api.get_party_profile()`, `db_api.search_party_profiles()`, `db_api.record_party_usage()` |
| Missions | `db_api.create_mission()`, `db_api.claim_mission()`, `db_api.complete_mission()`, `db_api.record_mission_outcome()` |
| Global generated types/state | `db_api.get_global_state(key)`, `db_api.set_global_state(key, value)` or typed template tables |
| Economy/weather/market state | typed `db_api` helpers backed by existing tables |

## API Endpoint Plan

These endpoints should be thin wrappers over the same `db_api` helpers used by Discord/Mimir/pipelines:

| API surface | Endpoints |
|---|---|
| Gazetteer and areas | `GET /api/gazetteer`, `GET /api/gazetteer/places`, `GET /api/areas`, `GET /api/areas/{id}` |
| NPCs | `GET /api/npcs`, `GET /api/npcs/{id}`, `PATCH /api/npcs/{id}` |
| NPC appearances | `GET /api/npc-appearances`, `GET /api/npcs/{id}/appearance`, `PATCH /api/npcs/{id}/appearance` |
| Parties | `GET /api/parties`, `GET /api/parties/{id}`, `POST /api/parties/{id}/usage` |
| Characters | `GET /api/characters`, `GET /api/characters/{id}`, `GET /api/characters/{id}/snapshots` |
| Missions | `GET /api/missions`, `GET /api/missions/{id}`, `POST /api/missions/{id}/claim`, `POST /api/missions/{id}/complete` |
| Mission/news types | `GET /api/mission-types`, `POST /api/mission-types`, `GET /api/news-types`, `POST /api/news-types` |
| Economy and markets | `GET /api/economy`, `GET /api/economy/exchange`, `GET /api/tia`, `GET /api/towerbay` |
| World state | `GET /api/weather`, `GET /api/rifts`, `GET /api/missing-persons`, `GET /api/council/rulings`, `GET /api/faction-calendar` |

## Migration Phases

### Phase 0: Freeze And Audit

- Snapshot current JSON files and record hashes.
- Add a grep/audit checklist for direct JSON access so new runtime file reads do not slip in during migration.
- Decide which files are seed, archive, staging, diagnostic, or live-state candidates.

### Phase 1: DB/API Contracts

- Add or verify typed `db_api` helpers for every live-state surface.
- Make dashboard/API routes call the same helpers as Discord, Mimir, and mission generation.
- Add parity checks that compare JSON source count/key coverage to DB rows before switching each surface.

### Phase 2: Singleton State Imports

- Import gazetteer, NPC roster, mission memory, generated mission/news types, faction state, economy/weather, markets, and council/arena data.
- Store source filename, source hash, import timestamp, and importer version where practical.
- Prefer explicit tables for data that needs searching/filtering; use `global_state` only for small scheduler/type blobs.

### Phase 3: Directory Family Imports

- Import `npc_appearances/*.json` into `npc_appearances`.
- Import `party_profiles/*.json` into `party_profiles`.
- Import `char_snapshots/*.json` into `character_snapshots`.
- Import `src/character_appearance/*.json` into character profile/appearance storage.

### Phase 4: Runtime Cutover

- Replace direct file reads in mission pipelines, news agents, Mimir sync, dashboard, and Discord cogs with DB/API helpers.
- Keep temporary read-only fallback behind an explicit environment flag while validating.
- Remove or quarantine fallback once the dashboard, Discord bot, Mimir, and mission generation all pass parity checks.

### Phase 5: Dashboard And Operational Validation

- Verify dashboard on port 5001 shows DB-backed state for each migrated surface.
- Verify Discord commands and scheduled posts use the same data.
- Verify Mimir world context pulls DB-backed gazetteer, factions, NPCs, and mission memory.
- Verify mission pipelines use DB area tags and map tags, not stale JSON data.

### Phase 6: Archive And Export

- Move migrated JSON files to an archive folder with date and source hash after parity.
- Keep export scripts so the DB can produce human-readable JSON backups.
- Update docs/skills/CLAUDE-style instructions so future agents do not revive file authority by following old JSON references.

## Priority Order

1. `city_gazetteer.json`: highest impact for area tags, map matching, missions, news, and Mimir.
2. `npc_roster.json`: highest identity/lifecycle risk.
3. `mission_memory.json` plus generated mission/news types: keeps mission rotation and story memory consistent.
4. Singleton state files: weather, economy, faction calendar, council rulings, arena venues, markets.
5. JSON families already partly migrated: NPC appearances, party profiles, character snapshots.
6. Staging/log/archive JSONs: migrate only if dashboard/API search or repeatable import tracking is valuable.

## Verification Checklist Per JSON Surface

- DB row count and unique keys match the JSON source.
- Discord reads DB-backed helpers.
- Dashboard/API reads DB-backed helpers.
- Mimir reads DB-backed helpers.
- Mission pipelines read DB-backed helpers.
- Existing scheduled jobs write through DB-backed helpers.
- File fallback is removed or explicitly disabled.
- Export/backup path exists so the DB can still produce inspectable JSON when needed.

## Live MySQL Cross-Check Notes

Checked against the live `tower_bot` MySQL schema on 2026-05-22. The live schema is materially ahead of `database_schema.sql` and `.codesight/schema.md`: it has 52 tables, including several migration targets that the checked-in schema does not fully describe.

Important correction: use live MySQL as the migration authority, not the checked-in schema docs. The checked-in `.codesight/schema.md` appears to conflate columns from multiple tables, and `database_schema.sql` is missing newer tables such as `gazetteer`, `gazetteer_places`, `global_state`, `mission_outcomes`, `battle_maps_library`, `battle_map_area_memory`, `mission_type_templates`, `news_memory`, and `bulletin_cache`.

### Existing Live Tables To Prefer

| Migration surface | Live MySQL status | Notes for migration plan |
|---|---:|---|
| Gazetteer root JSON | `gazetteer`: 1 row | `city_gazetteer.json` already has a DB home through `content_json`. Runtime code should stop reading the JSON file directly once parity is verified. |
| Gazetteer places | `gazetteer_places`: 312 rows | Strong target for place/shop/park/mall lookup. Area/map tagging should join or normalize against this instead of parsing the source JSON. |
| Area profiles | `area_profiles`: 27 rows | Use this for district-level generated profile/tag material. This is a real table, not a future suggestion. |
| Downloaded map library | `battle_maps_library`: 260 rows | The map migration target already exists and is populated. Current map type counts: street 72, dungeon 51, cave 33, office 33, temple 28, tavern 17, arena 13, warehouse 7, sewer 4, rooftop 2. |
| Area-to-map memory | `battle_map_area_memory`: 134 rows | The requested "remember what map was called for consistency" table already exists. Pipelines should write/read this instead of making new JSON memory. |
| NPC roster | `npcs`: 224 rows | Live table has `data_json`, `status`, `deceased_at`, virtual `species`, `rank`, `motivation`, `quote`, `oracle_notes`, `secret`, and `relationships`. Migration should use these fields rather than stuffing everything into `appearance_json`. |
| NPC appearances | `npc_appearances`: 227 rows | Live table includes `appearance_json` and `sd_prompt` in addition to prompt/style. JSON sidecars should become archive/export only after parity. |
| Party profiles | `party_profiles`: 131 rows | Live table includes `faction` and `profile_json`. This is the right target for `campaign_docs/party_profiles/*.json`. |
| Adventurer parties | `adventurer_parties`: 109 rows | This may be the better source for simple party-name inventory, while `party_profiles` holds richer profiles. |
| Missions | `missions`: 700 rows | Live table includes `status`, `tier`, `posted_at`, `mission_json`, and `module_slug`. `mission_memory.json` should migrate into this plus outcomes, not a brand-new generic memory table unless needed. |
| Mission outcomes | `mission_outcomes`: 486 rows | This table already exists and should be the primary home for completed mission consequences, loose threads, notable moments, and story memory. |
| Mission type templates | `mission_type_templates`: 34 rows | This is the active richer target for mission template diversity. Slugs include `strange-occurrences`, `infestation`, `investigation`, `heist`, `recovery`, `rescue`, `rift`, and others. Prefer this over the empty legacy `mission_types`. |
| Legacy mission types | `mission_types`: 0 rows | Do not target new work here unless code still requires it. Treat as legacy or compatibility. |
| News types | `news_types`: 0 rows | Empty legacy table. Generated news type state currently appears to live in `global_state.generated_news_types`. |
| News memory/cache | `news_memory`: 1621 rows; `bulletin_cache`: 2276 rows | News has substantial DB memory already. Flu/public-health arcs should likely use `global_state.public_health_arcs` plus `news_memory`/`news_entries`, not JSON files. |
| Generated/global state | `global_state`: 27 rows | Existing keys include `generated_mission_types`, `generated_news_types`, `used_parties`, `economy_cadence`, `council_rulings`, `public_health_arcs`, `world_active_tensions`, `world_gods`, `world_key_npcs`, and `world_setting`. Prefer existing keys before creating new tables for small state blobs. |
| Factions | `faction_reputation`: 46 rows; `faction_events`: 4 rows | `faction_reputation` has richer live columns: leader, location_name, description, motto, alignment. Faction calendar/event imports should go to `faction_events`. |
| Weather/economy | `weather_state`: 1 row; `economy_state`: 1 row | Singleton state is already represented. `dome_weather.json` and `ec_exchange.json` should be import/archive candidates only. |
| Council rulings | `global_state.council_rulings` exists | The original plan suggested a possible `council_rulings` table. Live DB currently uses `global_state`; keep that unless rulings need relational search/filtering. |
| Economy cadence | `global_state.economy_cadence` exists | Do not create `scheduler_state` just for this unless multiple schedulers need a common table. |
| Used parties | `global_state.used_parties` exists | Current DB already has a key for selection memory. If richer history is needed later, add a `party_usage_events` table, but do not duplicate the current state. |
| Arena state | `arena_seasons`: 1 row | No live `arena_venues` table was found. `arena_venues.json` still needs either a new reference table or a `global_state` key. |
| Missing persons | `missing_persons`: 15 rows | Existing table is populated. |
| Rift state | `rift_state`: 1 row | Existing singleton table is populated. |
| TIA market | `tia_market`: 8 rows | Live schema is richer than checked-in SQL, with `sector_name`, `value_json`, `state_json`, `prev_value`, and timestamps. |
| TowerBay | `towerbay_auctions`: 66 rows; `towerbay_bids`: 0 rows | Auctions are populated; bid history table exists but is empty. |
| Player listings | `player_listings`: 0 rows | Table exists but has no rows. Migrate only if JSON has active player listings worth preserving. |
| Character snapshots | `character_snapshots`: 29 rows; `latest_character_snapshots`: 8 rows | Snapshot migration target exists and view/table for latest snapshots is present. |
| Player characters | `player_characters`: 8 rows | Live table includes `oracle_notes`, `raw_block`, and virtual `race`. Character appearance JSON should probably land in `profile_json` unless a dedicated appearance table is later needed. |
| Image refs | `image_refs`: 332 rows | Live table includes `metadata_json` and `updated_at`; use it for map/NPC/module media references instead of new image sidecar JSON. |
| Resurrection/lifecycle | `resurrection_queue`: 30 rows; `lifecycle_daily_events`: 37 rows; `lifecycle_events`: 0 rows | Resurrection state exists and is populated. Daily lifecycle summaries exist; event-level lifecycle table is empty. |
| Mimir sync | `mimir_sync`: 947 rows | Mimir has substantial DB sync tracking. Migration work should update through DB/API so this table can remain consistent. |

### Plan Adjustments From Live Schema

1. Replace the earlier "possible new `mission_outcomes`" note with "use existing `mission_outcomes` first." It is already populated and is the right memory surface for completed missions.
2. Prefer `mission_type_templates` over `mission_types` for generated/curated mission diversity. `mission_types` is empty; `mission_type_templates` has 34 active slugs.
3. Prefer `global_state.generated_news_types` over `news_types` unless the code is deliberately moved to the typed table. `news_types` is empty.
4. Prefer `global_state.council_rulings`, `global_state.economy_cadence`, and `global_state.used_parties` over new tables for current singleton/list state.
5. Keep `arena_venues.json` as a real gap: no live `arena_venues` table was found. Either add a reference table later or store the venue catalog in `global_state`.
6. Treat maps as mostly migrated structurally. `battle_maps_library` and `battle_map_area_memory` exist and have data, so remaining work is pipeline usage, tagging quality, and API exposure rather than table creation.
7. Treat `city_gazetteer.json` as partially migrated, not unmigrated. The DB has the root JSON, normalized places, and area profiles. The risk is direct file reads and stale tags, not missing schema.
8. Treat NPC and party JSON migration as parity/fallback cleanup. Live row counts suggest the DB already has the bulk of the data.
9. Use `global_state.public_health_arcs` for multi-week outbreak/news arcs unless a later design needs relational outbreak tables. This directly supports long-running headlines like a magic-resistant flu arc.
10. Any future schema additions should be driven by query needs: add a table only when dashboard/API/pipelines need filtering, joins, history, ownership, or status transitions that JSON-in-`global_state` cannot handle cleanly.

## JSON Elimination Goal

Goal: remove as many runtime JSON files as possible. Campaign state should live in MySQL and move through `src/db_api.py` plus dashboard/API routes. JSON files should survive only when they are build metadata, local tool config, short-lived import staging, immutable archives, diagnostics, or DB exports.

The removal rule is simple:

1. If Discord, dashboard port 5001, Mimir, mission pipelines, learning agents, or scheduled news can read it, it belongs in MySQL/API.
2. If the value is queried, filtered, joined, counted, shown in dashboard lists, or used for mission selection, it needs real columns or a purpose-built table.
3. If the value is deeply nested LLM/module output that is mostly loaded as a whole, a JSON column is acceptable.
4. Once a file is imported and runtime readers are cut over, move the file to an archive/export folder or delete it after a backup.

## JSON Removal Matrix

| File/family | Current removal target | API/db_api surface needed | Removal condition |
|---|---|---|---|
| `campaign_docs/city_gazetteer.json` | Existing `gazetteer.content_json`, `gazetteer_places`, `area_profiles`; optionally split districts/edges later | `get_gazetteer()`, `get_gazetteer_places()`, `get_area_profile()`, `/api/gazetteer`, `/api/areas` | All direct file readers in mission locations, news agents, Mimir sync, and map seeding use DB helpers. Keep only DB export backup. |
| `campaign_docs/npc_roster.json` | Existing `npcs`, `npc_appearances`, `resurrection_queue`; use `npcs.data_json` only for low-query leftover fields | `get_npc()`, `search_npcs()`, `update_npc_status()`, `/api/npcs` | Every roster NPC is present in `npcs`; no runtime code reads the JSON; lifecycle/death/missing changes write DB only. |
| `campaign_docs/mission_memory.json` | Existing `missions.mission_json`, `mission_outcomes`, `module_generation_jobs` | `get_mission()`, `search_missions()`, `record_mission_outcome()`, `/api/missions`, `/api/mission-outcomes` | Historical useful entries imported or intentionally discarded; mission reuse/story memory reads `mission_outcomes` and `missions`, not file memory. |
| `campaign_docs/generated_mission_types.json` | Existing `global_state.generated_mission_types`; stronger long-term target is `mission_type_templates` | `get_mission_templates()`, `get_global_state("generated_mission_types")`, `/api/mission-types` | Learning cycle and mission board use DB; file is replaced by DB export only. |
| `campaign_docs/generated_news_types.json` | Existing `global_state.generated_news_types`; optional later move to typed `news_types` if needed | `get_global_state("generated_news_types")`, `/api/news-types` | News generation and dashboard use DB; file removed or archived. |
| `campaign_docs/faction_reputation.json` | Existing `faction_reputation` and `faction_events` | `get_faction_reputation()`, `upsert_faction_reputation()`, `/api/factions/reputation` | Faction keys/leader/location/motto/description parity verified; file archived. |
| `campaign_docs/faction_calendar.json` | Existing `faction_events` | `list_faction_events()`, `upsert_faction_event()`, `/api/faction-events` | Calendar events imported; scheduled posts query DB. |
| `campaign_docs/faction_leaders_to_add.json` | Existing `npcs`, `faction_reputation.leader`, `faction_events` | Admin import script or `/api/admin/import/faction-leaders` | One-time staging consumed. Delete/archive; should not be runtime state. |
| `campaign_docs/faction_leaders_new.json` | Existing `npcs`, `faction_reputation.leader`, `faction_events` | Same as above | Same as above. |
| `campaign_docs/ec_exchange.json` | Existing `economy_state` and `global_state.wealth_event_log` | `get_economy_state()`, `set_economy_state()`, `/api/economy` | Current rate/trend imported; all economy posts read DB. |
| `campaign_docs/economy_cadence.json` | Existing `global_state.economy_cadence` | `get_global_state("economy_cadence")`, `/api/system/cadence/economy` | Scheduler reads/writes DB key; file removed. |
| `campaign_docs/dome_weather.json` | Existing `weather_state` | `get_weather_state()`, `set_weather_state()`, `/api/weather` | Weather/news routines use DB only. |
| `campaign_docs/council_rulings.json` | Existing `global_state.council_rulings`; add table only if search/history grows | `get_global_state("council_rulings")`, `/api/council/rulings` | Rulings imported to global state; bulletin generation and dashboard read DB. |
| `campaign_docs/arena_venues.json` | Gap: no `arena_venues` table. Short-term `global_state.arena_venues`; better table if used for filtering | `/api/arena/venues`, `get_arena_venues()` | Create DB home, import venues, update arena/mission/news readers. This is one of the few true schema gaps. |
| `campaign_docs/bounty_board.json` | Existing `bounties` | `list_bounties()`, `claim_bounty()`, `/api/bounties` | Active bounties imported; claims/completions write DB. |
| `campaign_docs/missing_persons.json` | Existing `missing_persons` | `list_missing_persons()`, `/api/missing-persons` | File-only cases imported; missing/found state writes DB. |
| `campaign_docs/rift_state.json` | Existing `rift_state` | `get_rift_state()`, `/api/rifts` | Singleton imported; rift missions/news read DB. |
| `campaign_docs/player_listings.json` | Existing `player_listings` | `list_player_listings()`, `/api/player-listings` | If JSON has active listings, import; otherwise delete/archive. Live table currently has 0 rows. |
| `campaign_docs/towerbay.json` | Existing `towerbay_auctions`, `towerbay_bids` | `list_towerbay_auctions()`, `/api/towerbay` | Active auctions imported; bids/winners write DB. |
| `campaign_docs/tia.json` | Existing `tia_market` | `list_tia_market()`, `/api/tia` | Current sectors imported; market updates write DB. |
| `campaign_docs/used_parties.json` | Existing `global_state.used_parties`, `party_profiles`, `adventurer_parties` | `get_used_parties()`, `record_party_usage()`, `/api/party-usage` | Party selection writes DB/global state; file removed. Add `party_usage_events` only if history/cooldowns need queryable rows. |
| `campaign_docs/npc_appearances/*.json` | Existing `npc_appearances`, `image_refs`, `npcs.appearance_json` | `get_npc_appearance()`, `upsert_npc_appearance()`, `/api/npc-appearances` | Row count and NPC-name parity verified; image paths are in DB; JSON sidecars archived/export-only. |
| `campaign_docs/npc_appearances/_all_sd_prompts.json` | Existing `npc_appearances.sd_prompt` | Same as NPC appearances | Every prompt moved into DB rows; aggregate file removed because DB can generate the aggregate view. |
| `campaign_docs/party_profiles/*.json` | Existing `party_profiles`, `adventurer_parties` | `get_party_profile()`, `search_party_profiles()`, `/api/parties` | Party names and profiles imported; mission selection never scans files. |
| `campaign_docs/char_snapshots/*.json` | Existing `character_snapshots`, `latest_character_snapshots`, `player_characters` | `get_character_snapshots()`, `/api/characters/{id}/snapshots` | Snapshots imported; `_prev` history either imported or intentionally archived. |
| `src/character_appearance/*.json` | Existing `player_characters.profile_json`; optional `character_appearances` only if dashboard needs queryable appearance fields | `get_character_appearance()`, `set_character_appearance()`, `/api/characters/{id}/appearance` | Discord character appearance commands read/write DB. |
| `logs/learning/test_modules/*.json` | Optional `module_quality_samples` table; otherwise keep as logs, not runtime state | `/api/learning/samples` only if useful | If used by learning cycle decisions, migrate. If not, leave as logs and exclude from runtime cleanup. |
| `logs/ddb_vtt_probe.json` | None; diagnostic artifact | None | Keep or delete as diagnostic housekeeping. Not campaign state. |
| `scripts/npc_ddb_staging.json` | Optional `ddb_import_batches`/`ddb_import_rows`; otherwise staging file | Admin import status only if repeatable | Keep as short-lived import input, not runtime state. Delete after import batches complete. |
| `scripts/creature_ddb_staging.json` | Optional `ddb_import_batches`/`ddb_import_rows`; otherwise staging file | Same as above | Same as above. |
| `campaign_docs/archives/**/*.json` | Archive only; optional import to historical tables if queried | Usually none | Do not load at runtime. Keep immutable or compress/delete after backup policy. |
| `package.json`, `package-lock.json`, `src/docx_builder/package*.json` | Build/dependency metadata | None | Keep. Not campaign state. |
| `.mcp.json`, skill `metadata.json` files | Tool/agent metadata | None | Keep. Not campaign state. |

## Best Removal Order

1. **Cut file readers for already-migrated surfaces.** Start with files that already have populated tables: `dome_weather.json`, `ec_exchange.json`, `economy_cadence.json`, `used_parties.json`, `faction_reputation.json`, `bounty_board.json`, `missing_persons.json`, `rift_state.json`, `towerbay.json`, `tia.json`.
2. **Finish gazetteer cutover.** `city_gazetteer.json` has DB homes already, but it is high-impact. Replace direct file reads in mission locations, news, Mimir, and map tooling with `gazetteer`/`gazetteer_places`/`area_profiles`.
3. **Finish NPC/party sidecar cleanup.** Import and verify `npc_appearances/*.json`, `_all_sd_prompts.json`, `party_profiles/*.json`, and `npc_roster.json`. Remove fallback scans.
4. **Finish mission/news memory cleanup.** Migrate `mission_memory.json`, generated type JSONs, and learning state into `missions`, `mission_outcomes`, `mission_type_templates`, `news_memory`, `bulletin_cache`, and `global_state`.
5. **Handle true gaps.** `arena_venues.json` needs a DB home. Prefer a small `arena_venues` table if venues are selected/filtered; use `global_state.arena_venues` only if it stays a simple catalog.
6. **Classify leftovers.** Staging, diagnostic, package, MCP, and archive JSONs can remain file-based because they are not runtime campaign state.

## API Work Needed To Make Deletion Safe

| Needed API/helper | Why it matters |
|---|---|
| Gazetteer/area helper set | Stops `city_gazetteer.json` runtime reads and lets maps/missions/news share area tags. |
| NPC roster helper set | Lets lifecycle, news, appearances, Discord commands, and dashboard agree on one NPC record. |
| Party usage helper | Replaces `used_parties.json` and lets mission rotation avoid stale party selection. |
| Mission outcome/story memory helper | Replaces `mission_memory.json` and gives modules a reliable story-history source. |
| Generated type/template helper | Keeps learning cycle output in `global_state`/`mission_type_templates` instead of regenerated JSON files. |
| Arena venues helper | Covers the main live-schema gap. |
| DB export command | Lets humans inspect/backup JSON without letting JSON become runtime authority again. |

## Delete/Archive Criteria

Before deleting or archiving a campaign JSON file, verify:

- DB row/key parity has been checked.
- The relevant dashboard/API page reads DB.
- Discord command or scheduled job reads DB.
- Mimir sync reads DB where relevant.
- Mission pipelines read DB where relevant.
- Any import-only/staging file is not referenced by runtime code.
- A DB export or backup exists for human inspection.

After those checks pass, archive the old JSON under a dated migration archive or delete it if it is generated/staging noise.

## Deep Research Notes: Runtime Touch Points

This pass looked past the file inventory and into runtime callers. The main remaining JSON/text-file debt is concentrated in a few code paths, not evenly spread across the project.

### Highest-Risk Runtime Fallbacks

| Surface | Current code touch | Risk | Migration note |
|---|---|---|---|
| Gazetteer | `src/agents/news_agents.py:29-31`, `src/agents/news_agents.py:115-130` | Comment is stale: it still says `city_gazetteer.json` is the only permitted file read. Runtime tries DB first, then reads the file. | Remove file fallback once `gazetteer` row parity is confirmed. News fact-checking should fail soft to `{}` or cached DB data, not reopen JSON. |
| Gazetteer | `src/mission_builder/locations.py:20-21`, `src/mission_builder/locations.py:39-76` | Mission location selection reads DB first but falls back to `city_gazetteer.json`. This keeps the file alive. | Replace fallback with empty/default DB result plus clear warning. Since `gazetteer` has 1 row, file fallback should be unnecessary after smoke test. |
| Gazetteer places | `src/mission_builder/locations.py:500-558` | The one-time migration helper still describes loading from `city_gazetteer.json`, but it actually calls `load_gazetteer()`, which may load DB. | Convert this helper into a DB-to-DB normalizer or retire it after `gazetteer_places` parity. |
| Dungeon delve gazetteer | `src/mission_builder/dungeon_delve/__init__.py:73-99` | Dungeon location picker uses DB first, then reads `city_gazetteer.json`. | Use shared `src.mission_builder.locations.load_gazetteer()` or a db_api helper so there is only one gazetteer path. |
| Area map generation | `src/area_map_generator.py:47-49`, `src/area_map_generator.py:174-180` | This still directly opens `campaign_docs/city_gazetteer.json`. | Convert to query `gazetteer.content_json` plus `gazetteer_places`/`area_profiles`. Since maps are now downloaded/library-backed, this may become admin/backfill only. |
| NPC appearance lookup | `src/npc_lookup.py:31-32`, `src/npc_lookup.py:62-94` | DB first, then fallback to `campaign_docs/npc_appearances/<slug>.json`. | Remove fallback after `npc_appearances` parity. If a DB row is missing, return no appearance and queue regeneration/import. |
| News party lookup | `src/news_feed.py:4357-4377` | `_find_parties_in_text()` scans `campaign_docs/party_profiles/*.json` directly. | Replace with `SELECT party_name, profile_json FROM party_profiles` and match in memory. This is a concrete runtime blocker to deleting party profile JSON files. |
| Character memory | `src/character_monitor.py:491-573`, `src/cogs/character.py:119-138` | Character DB update is primary, but code writes through to `campaign_docs/character_memory.txt` as fallback/RAG source. | Move remaining Oracle/RAG character context into `player_characters`, `character_snapshots`, and `training_docs`/Mimir. Then remove write-through to text. |
| Tower RAG | `src/tower_rag.py:253-274` | On DB load failure, falls back to scanning `campaign_docs/**/*.txt`. | Decide if RAG fallback is allowed as emergency-only. If eliminating file state strictly, fail closed or use Mimir/training_docs only. |
| Weekly archive | `src/weekly_archive.py:1-28`, `src/weekly_archive.py:61-74` | Writes weekly archive JSON from DB rows. | This is not runtime authority, but it keeps JSON around. Convert to DB archive tables only if the goal is no JSON at all; otherwise classify as export/archive. |

### Existing Dashboard/API Coverage

These dashboard routes already support JSON elimination because they read DB-backed surfaces:

| Route | Backing data | Notes |
|---|---|---|
| `/api/districts` | `gazetteer`, `gazetteer_places`, `area_profiles`, `image_refs` | Good DB-backed replacement for gazetteer browsing. |
| `/api/districts/<name>/places` | `gazetteer_places`, `image_refs` | Good replacement for place lists. |
| `/api/districts/<name>/profile` | `area_profiles` | Good replacement for generated district profile state. |
| `/api/places` | `query_places_from_db()` | Good search surface for normalized gazetteer places. |
| `/api/npcs`, `/api/npcs/<name>` | `npcs`, `npc_appearances`/related DB reads | Good replacement for roster browsing, though fallback cleanup still needed in helper code. |
| `/api/factions` | `faction_reputation` | Good replacement for faction reputation JSON. |
| `/api/bulletins` | `bulletin_cache` | Good replacement for news cache JSON/text memory. |
| `/api/mission-types` | `mission_type_templates` | Confirms `mission_type_templates`, not `mission_types`, is the dashboard surface. |
| `/api/bounties` | `bounties` | Good replacement for bounty board JSON. |
| `/api/parties` | `party_profiles` | Exists, but returns only summary fields. Add detail/search if replacing all party-profile JSON workflows. |
| `/api/image-refs` | `image_refs` plus media files | Good replacement for image sidecar JSON where possible. |
| `/api/mission-maps`, `/api/modules` | generated module artifacts | These intentionally browse generated output, not campaign source state. |

### Dashboard/API Gaps For JSON Removal

| Needed route/surface | Current DB home | Why it matters |
|---|---|---|
| `/api/weather` | `weather_state` | Needed before deleting `dome_weather.json` confidently from dashboard/admin workflows. |
| `/api/economy` | `economy_state`, `global_state.economy_cadence`, `global_state.wealth_event_log` | Needed before deleting `ec_exchange.json` and `economy_cadence.json`. |
| `/api/tia` | `tia_market` | Needed before deleting `tia.json`. |
| `/api/towerbay` | `towerbay_auctions`, `towerbay_bids` | Needed before deleting `towerbay.json`. |
| `/api/player-listings` | `player_listings` | Needed before deleting `player_listings.json`; live table is empty, so parity decision may be "discard stale file." |
| `/api/missing-persons` | `missing_persons` | Needed before deleting `missing_persons.json` from dashboard-oriented workflows. |
| `/api/rifts` | `rift_state` | Needed before deleting `rift_state.json`. |
| `/api/global-state/<key>` or typed endpoints | `global_state` | Needed for generated types, used parties, council rulings, public health arcs, economy cadence. Prefer typed wrappers for important gameplay state. |
| `/api/mission-outcomes` | `mission_outcomes` | Needed before fully retiring `mission_memory.json` and archive outcome JSON as runtime lookup sources. |
| `/api/parties/<name>` | `party_profiles.profile_json`, `members_json` | Needed to replace party profile JSON consumers with detail-level API. |
| `/api/arena/venues` | missing table or `global_state.arena_venues` | Required before `arena_venues.json` can go away. |

### Runtime Versus Artifact JSON

Do not treat all `.json` files the same.

Runtime campaign state to eliminate:

- `campaign_docs/*.json` singleton state files.
- `campaign_docs/npc_appearances/*.json` sidecars.
- `campaign_docs/party_profiles/*.json` sidecars.
- `campaign_docs/char_snapshots/*.json` if DB snapshots are complete.
- `src/character_appearance/*.json` if any remain after DB character appearance migration.

Probably acceptable as files:

- `package*.json`, `.mcp.json`, skill metadata.
- `scripts/*_staging.json` while they are short-lived import inputs.
- `logs/ddb_vtt_probe.json` and other diagnostics.
- `generated_modules/**/maps_manifest.json`, `module_data.json`, `room_info.json`, and `*.vtt.json` because those are module deliverables/artifacts, not source-of-truth campaign state.
- `campaign_docs/archives/**/*.json` only if the archive policy remains "human-readable exports." If the goal becomes zero JSON, convert weekly archives to DB archive tables.

### Concrete Next Research Targets

1. Inspect `src/ec_exchange.py`, `src/dome_weather.py`, `src/tower_economy.py`, `src/faction_calendar.py`, `src/bounty_board.py`, `src/missing_persons.py`, and `src/player_listings.py` for direct file writes that the broad scan may have hidden behind helper names.
2. Compare each singleton JSON file's current keys against the live DB row/state key to identify any data that would be lost by deletion.
3. Build a direct-reference checklist: for every `campaign_docs/<name>.json`, record `rg` hits that are actual runtime reads/writes versus comments/docs.
4. Check whether `global_state.arena_venues` exists or if `arena_venues.json` is still wholly file-only. Live `global_state` did not list `arena_venues`, so this is likely still a real migration gap.
5. Check `src/mission_builder` pipelines for any direct JSON sidecar scans beyond gazetteer/NPC/party helpers, especially image/map manifests that might be incorrectly treated as source state.

## Deep Research Notes: Singleton Parity

Table existence is not the same as safe deletion. Some JSON files are clearly stale exports; others still contain richer data than the corresponding DB rows.

### File Shape Versus DB Shape

| File | File shape | Live DB/global_state shape | Deletion assessment |
|---|---:|---:|---|
| `ec_exchange.json` | dict with `rate`, `last_updated`, `history`, `last_event` | `economy_state`: 1 row | Likely safe after confirming current rate/trend. File has history that DB currently does not preserve except via `global_state.wealth_event_log`; archive if history matters. |
| `economy_cadence.json` | 4 keys | `global_state.economy_cadence`: object with 5 keys | DB appears richer/current. Safe candidate after scheduler read/write check. |
| `dome_weather.json` | 6 keys including districts/forecast | `weather_state`: 1 row | Needs key-level parity check. `src/dome_weather.py` is DB-backed, but file may contain richer per-district detail than `weather_state` depending on `effects_json`. |
| `council_rulings.json` | empty list | `global_state.council_rulings`: array length 56 | File is obsolete; DB is authoritative. |
| `generated_mission_types.json` | dict with `generated_date`, `types` | `global_state.generated_mission_types`: object length 2; `mission_type_templates`: 34 rows | DB has current home; prefer `mission_type_templates` for curated templates. |
| `generated_news_types.json` | dict with `generated_date`, `types` | `global_state.generated_news_types`: object length 2 | DB has current home. |
| `used_parties.json` | list length 98 | `global_state.used_parties`: array length 92 | Mismatch. Need compare members before deleting; DB may be newer filtered list or missing six names. |
| `arena_venues.json` | dict with `meta`, `venues`, `event_type_descriptions`, `notable_personalities` | No `arena_venues` table; no `global_state.arena_venues` key observed | Not safe. This is a real migration target. |
| `bounty_board.json` | list length 5 with rich body/reward/issuer text | `bounties`: 10 rows, but sample rows were `Untitled` with `reward_ec=0` | Not safe. DB table exists, but data quality/parity is suspect. Import rich JSON fields or add `body`/`bounty_json` before deletion. |
| `missing_persons.json` | list length 13 with rich notice bodies and status fields | `missing_persons`: 15 rows, sample rows have names/location/status only | Partially safe structurally, but body/circumstance text may be lost. Add `notice_body` or `record_json` if old notices matter. |
| `rift_state.json` | list length 7 historical rift records | `rift_state`: 1 singleton row with `effects_json` containing a `rifts` array | Need parse/compare rift IDs. DB may have newer rifts, but file is a historical list. Archive or import into `effects_json`/new `rift_events`. |
| `player_listings.json` | list length 2 with player auction history/bid logs | `player_listings`: 0 rows | Not safe if those listings matter. Either import as closed listings or intentionally archive/discard. |
| `towerbay.json` | list length 56 | `towerbay_auctions`: 66 rows | DB appears newer/richer. Still compare IDs/names before deletion. |
| `tia.json` | dict with `sectors`, `last_updated`, `last_event` | `tia_market`: 8 rows plus `global_state.tia_reaction_cooldown` | Likely migrated, but sector-level parity should be checked. |
| `faction_reputation.json` | 11 faction keys | `faction_reputation`: 46 rows | DB is much richer/newer. Safe candidate after confirming the 11 old factions exist in DB. |
| `faction_calendar.json` | list length 4 | `faction_events`: 4 rows | Likely one-to-one candidate, but compare event names/dates before deletion. |
| `mission_memory.json` | list length 333 | `missions`: 700 rows; `mission_outcomes`: 486 rows | Likely old partial memory. Needs import/compare by title/id before deletion. |
| `npc_roster.json` | list length 133 | `npcs`: 224 rows | DB is richer/newer, but compare unique names and special fields before deletion. |

### Singleton Module Runtime Findings

| Module | Finding |
|---|---|
| `src/ec_exchange.py` | Header says refactored to MySQL. Runtime uses `get_economy_state()` and `update_economy_state()`, no direct JSON file dependency found. |
| `src/dome_weather.py` | Header says refactored to MySQL. Runtime uses `get_weather_state()` and `update_weather_state()`, no direct JSON file dependency found in inspected top section. |
| `src/bounty_board.py` | Runtime loads/saves `bounties` table. However, DB sample quality looked poor compared with `bounty_board.json`; migration should backfill rich title/body/reward fields before deletion. |
| `src/missing_persons.py` | Runtime loads/saves `missing_persons` table. Existing DB table has minimal columns, while JSON contains rich notice body. Decide whether to preserve body text in a JSON/details column or archive old notices. |
| `src/faction_calendar.py` | Header says events persist to MySQL `faction_events`; no direct JSON file dependency found in inspected section. |
| `src/player_listings.py` | Runtime persists to `player_listings` with `listing_json`, but live table has 0 rows while file has 2 listings. Needs explicit import/archive decision. |
| `src/tower_economy.py` | Header says TowerBay and TIA persist to MySQL. TIA cooldown uses `global_state.tia_reaction_cooldown`; TowerBay/TIA files look like old state exports. |

### Updated Safety Ranking

Safest likely delete/archive after reference check:

- `council_rulings.json` because file is empty and DB has 56 rulings.
- `faction_reputation.json` because DB has 46 faction rows versus 11 file keys.
- `generated_mission_types.json` and `generated_news_types.json` because DB/global_state and mission templates exist.
- `economy_cadence.json` because DB/global_state appears richer.
- `ec_exchange.json` if losing local history is acceptable or `wealth_event_log` covers it.

Needs parity/import before deletion:

- `bounty_board.json` because DB sample rows appear low quality.
- `missing_persons.json` because DB has minimal columns and file has rich bodies.
- `player_listings.json` because DB is empty.
- `arena_venues.json` because no DB home exists.
- `used_parties.json` because file and DB lengths differ.
- `rift_state.json` because file is historical list while DB is singleton/effects blob.
- `mission_memory.json` because it has 333 entries that may or may not map to `missions`/`mission_outcomes`.
- `npc_roster.json` because it may contain fields not fully moved into `npcs.data_json`.

### Name/Key Set Comparisons

Set comparison gives a better deletion signal than row count alone.

| Surface | Comparison result | Meaning |
|---|---|---|
| NPC roster | File has 133 normalized NPC names; DB has 224; file-only names: 0; DB-only names: 91 | `npc_roster.json` appears to be a strict subset by name. Deletion is likely safe after field-level parity for those 133 names. |
| Party profiles | File has 110 party profile slugs; DB has 131 party names; file-only: 0; DB-only: 21 | `campaign_docs/party_profiles/*.json` appears to be a subset by party name. Main blocker is runtime file scan in `news_feed.py`, not missing DB rows. |
| Faction reputation | File has 11 factions; DB has 41 normalized faction names; file-only: 0; DB-only: 30 | `faction_reputation.json` is old subset data. Safe archive candidate after key field check. |
| Mission memory | File has 315 normalized mission titles; DB `missions` has 665; file-only titles: 0; DB-only: 350 | `mission_memory.json` appears to be subset by title. Use `mission_outcomes`/`missions` as authority after checking any unique outcome fields. |
| Used parties | File has 98 names; DB/global_state has 92; file-only: 13; DB-only: 7 | Not safe to delete blindly. Need merge/decide which list is current. |
| Missing persons | File has 13 parsed missing-person names; DB has 11; file-only: 12; DB-only: 10 | Not migrated one-to-one. File and DB are mostly different generations of notices. Archive/import decision required. |
| Bounties | File has 5 parsed wanted names; DB has 5 normalized names; file-only: 4; DB-only: 4 | Not migrated one-to-one. DB has newer/different names and at least one `Untitled` sample. Preserve or archive rich file bounty records before deleting. |

Sample only-file findings worth preserving/importing:

- `used_parties.json`: `cinder and clause`, `coldwatch advance`, `gravel court`, `remnant clause`, `sootmark brigade`, `the deliberate hours`, `the drifting verdict`, `the open account`, `the pale majority`, `the patient knife`, `the severed road`, `the slow petition`, `thorngate crew`.
- `bounty_board.json`: `zephyria the silent scribe`, `vespera the venomous`, `elysia shadowveil`, `sylas the venomous`.
- `missing_persons.json`: `eirlyn verian`, `malcolm patch thornton`, `lyrian rhone`, `rylith lanterne`, `kaelen voss`, `talon swiftwhisper`, and other older notices.

Updated conclusion: the easiest deletions are not necessarily the smallest files. The safest deletes are subset files whose names are fully covered by DB (`npc_roster`, `party_profiles`, `faction_reputation`, `mission_memory`) after field checks. The riskiest are files where DB and JSON represent different histories (`bounty_board`, `missing_persons`, `player_listings`, `rift_state`, `used_parties`).

## Deep Research Notes: Helper Coverage And Text Debt

The migration should not only remove `.json` files. Several `.txt` files in `campaign_docs` act like old campaign state and should be treated as the same class of debt when they influence Discord, Mimir, mission generation, or learning.

### `db_api.py` Coverage

`src/db_api.py` already provides direct helpers for major surfaces:

- NPCs: `get_npc`, `get_all_npcs`, `get_npcs_by_faction`, `get_npcs_by_status`, `get_living_npcs`, `add_npc`, `update_npc`.
- Missions: `get_mission`, `get_active_missions`, `get_missions_by_status`, `create_mission`, `claim_mission`, `complete_mission`.
- Weather/economy/rift: `get_weather_state`, `update_weather_state`, `get_economy_state`, `update_economy_state`, `get_rift_state`, `update_rift_state`.
- Factions: `get_faction_reputation`, `get_all_faction_reputations`, `set_faction_reputation`.
- Bounties: `get_active_bounties`, `add_bounty`, `claim_bounty`, `complete_bounty`.
- News/memory: `add_news_entry`, `get_news_memory`.
- Character context: `get_character_memory_text`, which reconstructs legacy `---CHARACTER---` text from `player_characters` DB rows and intentionally does not fall back to `campaign_docs/character_memory.txt`.
- Global state: `get_global_state`, `set_global_state`.

Missing typed helper families still worth adding:

- Gazetteer/area helpers around `gazetteer`, `gazetteer_places`, and `area_profiles`.
- Party usage helpers around `global_state.used_parties`.
- Party detail helpers around `party_profiles.profile_json` and `members_json`.
- TIA/TowerBay/player-listing helpers.
- Missing-person and bounty helpers that preserve rich notice body/details, not only title/status/reward.
- Mission outcome helpers around `mission_outcomes`.
- Arena venue helpers once the DB home is chosen.

### Learning Cycle Status

`src/self_learning.py` is mostly DB-aligned:

- `_study_news_memory()` reads `news_memory`.
- `_load_missions_from_db()` reads `missions.mission_json`.
- `_load_faction_rep_from_db()` reads `faction_reputation`.
- `_study_npc_roster()` reads `npcs`.
- Holistic world assessment reads character data through `db_api.get_character_memory_text()` and news through `news_memory`.

This means deleting old `news_memory.txt`, `mission_memory.json`, and `npc_roster.json` should not break the learning cycle if DB parity is handled. Old comments still mention file names, but core learning reads DB.

### Character/NPC Text Debt

| File/surface | Current code | Finding | Migration action |
|---|---|---|---|
| `campaign_docs/character_memory.txt` | `src/character_monitor.py:491-573`, `src/cogs/character.py:119-138` | DB is primary, but code still writes through to the text file as fallback/RAG compatibility. | Remove write-through once any consumers have switched to `db_api.get_character_memory_text()`. |
| `campaign_docs/npc_roster.txt` | `src/npc_lifecycle.py:23-25`, `src/npc_lifecycle.py:375-410` | Lifecycle saves NPCs to DB, then rebuilds `npc_roster.txt` for RAG compatibility. Comments still mention JSON/graveyard. | Replace RAG consumers with DB/Mimir context; stop rebuilding txt once verified. |
| Static NPC seed from txt | `src/npc_lifecycle.py:1273-1295` | First-run seed reads `npc_roster.txt` only if it is not auto-generated. | Keep as one-time import path or move to a DB seed script; it should not be runtime state. |
| CR/party level comments | `src/mission_builder/encounters.py:85-146` | Code now uses `player_characters` and `character_snapshots`; comments still mention `character_memory.txt` fallback. | Cleanup comments later. Not a blocker to JSON deletion. |

### Generated Module JSON Is Different

Do not delete generated module JSON as part of campaign-state migration unless the module browser/renderers no longer need it:

- `generated_modules/**/maps_manifest.json`
- `generated_modules/**/module_data.json`
- `generated_modules/**/room_info.json`
- `generated_modules/**/*.vtt.json`

These are deliverables/artifacts for completed modules, closer to compiled output than source-of-truth campaign state. The deletion target is `campaign_docs` runtime state, not module export packages.

### API/Helper Implication

The best next implementation move is not a giant import. It is to add a small set of DB helper functions and route wrappers so call sites stop needing raw SQL or fallback files:

1. `get_gazetteer_content()`, `list_gazetteer_places()`, `get_area_profile()`.
2. `list_party_profiles()`, `get_party_profile_detail()`, `get_used_parties()`, `set_used_parties()`.
3. `list_missing_persons(include_resolved=True)` with a detail/body field plan.
4. `list_bounties(include_resolved=True)` with a body/details field plan.
5. `list_tia_market()`, `list_towerbay_auctions()`, `list_player_listings()`.
6. `list_mission_outcomes()` and `get_mission_story_memory()`.
7. `get_arena_venues()` backed by either a new table or `global_state.arena_venues`.

Once these helpers exist, the migration becomes a sequence of small, verifiable cutovers rather than a risky sweep.

## Deep Research Notes: Schema Fit

Some existing tables are ready to absorb their old JSON files; others are too narrow and would lose data if we simply imported into current columns.

### Tables Ready For Rich Imports

| Table | Useful detail columns | JSON files it can absorb |
|---|---|---|
| `missions` | `mission_json`, `module_slug`, status/tier/faction columns | `mission_memory.json` for mission-level records after title/id matching. |
| `mission_outcomes` | `npcs_killed`, `key_decisions`, `location_changes`, `loose_threads`, `notable_moments`, `consequences_json` | Mission outcome/memory details, old outcome archives if needed. |
| `npcs` | `data_json`, `appearance_json`, `rank`, `motivation`, `quote`, `oracle_notes`, `secret`, `relationships`, status/deceased fields | `npc_roster.json`, graveyard/resurrection-related NPC state. |
| `npc_appearances` | `appearance_json`, `sd_prompt`, `appearance_prompt` | `npc_appearances/*.json`, `_all_sd_prompts.json`. |
| `party_profiles` | `members_json`, `profile_json`, `faction`, `reputation`, `status` | `party_profiles/*.json`. |
| `player_listings` | `listing_json`, bid/current price columns | `player_listings.json`, including bid logs. Live table is empty, but schema can preserve the file. |
| `towerbay_auctions` | `auction_json`, bid/current price columns | `towerbay.json`. |
| `tia_market` | `value_json`, `state_json`, value/trend columns | `tia.json`. |
| `rift_state` | `effects_json` | `rift_state.json`, though a proper `rift_events` table would be better if rift history needs querying. |
| `global_state` | `state_value` | Small blobs: generated types, used parties, economy cadence, council rulings, public health arcs, world state. |

### Tables Too Narrow For Lossless Import

| Table | Missing detail | Recommendation |
|---|---|---|
| `bounties` | No `body`, `issuer`, `proxy_faction`, `expires_at`, `bounty_json`, or target description columns. | Add `body TEXT`, `issuer VARCHAR`, `proxy_faction VARCHAR`, `expires_at DATETIME`, and/or `bounty_json JSON` before importing `bounty_board.json`; otherwise archive the file rather than pretending DB preserved it. |
| `missing_persons` | No `notice_body`, `filed_by`, `description`, `circumstances`, `expires_at`, or `record_json`. | Add `notice_body TEXT` and/or `record_json JSON` if old notices matter. Current table preserves only person/location/status/date. |
| `arena_seasons` | Season state exists, but no venue catalog table. | Add `arena_venues` table or store `arena_venues.json` in `global_state.arena_venues`. Table is preferred if filtering by district, prestige, event type, or faction. |
| `news_types` / `mission_types` | Legacy tables exist but are empty and less expressive than current state/templates. | Do not migrate generated type JSON into these blindly. Prefer `mission_type_templates` and `global_state.generated_news_types`. |

### Schema Docs Status

`docs/mysql_schema_reference.md` is also stale. It was generated on 2026-05-17 and lists 43 tables. Live MySQL on 2026-05-22 has 52 tables. Missing/newer live tables include:

- `battle_maps`
- `battle_maps_library`
- `battle_map_area_memory`
- `dashboard_claim_jobs`
- `module_generation_jobs`
- `epic_gear_pool`
- `faction_affiliations`
- plus newer columns on existing tables such as `npcs.data_json`, `npcs.rank`, `npc_appearances.appearance_json`, `player_listings.listing_json`, and richer `tia_market` fields.

Migration work should not use `docs/mysql_schema_reference.md`, `.codesight/schema.md`, or `database_schema.sql` as final authority. Use live `information_schema` or regenerate the schema reference first.

### Global State Contents Worth Keeping

Live `global_state` already has several keys that replace JSON files:

- `generated_mission_types`: object with `types`, `generated_date`.
- `generated_news_types`: object with `types`, `generated_date`.
- `used_parties`: array length 92.
- `economy_cadence`: object with `tia_last_post`, `exchange_last_post`, `towerbay_last_post`, `development_last_post`, `council_omen_last_post`.
- `council_rulings`: array length 56.
- `public_health_arcs`: object with `arcs`, `updated_at`.
- `world_active_tensions`: array length 10, including the magic-resistant fever arc.
- `world_setting`, `world_key_npcs`, `world_gods`: world context that can replace scattered lore text.

Missing key:

- `arena_venues` was not observed in `global_state`, so `arena_venues.json` still needs a DB destination.

### Schema-Driven Import Priority

1. **No schema needed, mostly helper/cutover:** `npc_roster.json`, `party_profiles/*.json`, `npc_appearances/*.json`, `mission_memory.json`, `faction_reputation.json`, `towerbay.json`, `tia.json`.
2. **No schema needed but merge required:** `used_parties.json`, `rift_state.json`, generated type JSONs.
3. **Schema or archive decision required:** `bounty_board.json`, `missing_persons.json`, `arena_venues.json`, `player_listings.json` if preserving closed listings in DB matters.

## Deep Research Notes: Direct Filename References

Direct filename search shows three kinds of references:

1. **Runtime blockers** that actually read/write files.
2. **Comments/docstrings** that are stale but do not execute.
3. **Skills/docs** that can mislead future agents into reintroducing JSON reads.

### Runtime Blockers Confirmed

| File | Confirmed runtime references |
|---|---|
| `city_gazetteer.json` | `src/area_map_generator.py`, `src/agents/news_agents.py`, `src/mimir_sync.py`, `scripts/seed_battle_maps.py`, `src/mission_builder/dungeon_delve/__init__.py`, `src/mission_builder/locations.py`; `src/news_feed.py` also says it can fall back to gazetteer file. |
| `character_memory.txt` | `src/character_monitor.py`, `src/cogs/character.py`; write-through compatibility still exists. |
| `npc_roster.txt` | `src/npc_lifecycle.py`; rebuilt for RAG compatibility and used as first-run seed if not auto-generated. |
| `news_memory.txt` | `src/memory_strip.py` CLI still reads/writes it; `weekly_archive.py` comments/snapshots mention it. Runtime news is DB-backed, but the utility remains file-oriented. |
| `party_profiles/*.json` | `src/news_feed.py:_find_parties_in_text()` scans the directory. This is a concrete blocker to removing party profile sidecars. |
| `npc_appearances/*.json` | `src/npc_lookup.py` can fall back to a sidecar file; Webpage media serving allows the directory for images/json. |

### Mostly Stale Comments/Docstrings

| File/reference | Current status |
|---|---|
| `src/mission_board.py` says storage is `campaign_docs/mission_memory.json` | Runtime is DB-backed with `missions` and `global_state`; comment is stale. |
| `src/module_quality_trainer.py` says "Update mission_memory.json" | Needs review, but appears likely comment/legacy objective. |
| `src/news_feed.py` has comments about `npc_roster.json` and `news_memory.txt` | Runtime around these areas is mostly DB-backed, but comments are stale and confusing. |
| `src/npc_consequence.py` says death moves `npc_roster.json` to `npc_graveyard.json` | Runtime uses `npcs` and `resurrection_queue`; comment is stale. |
| `src/mission_builder/encounters.py` comments mention `character_memory.txt` fallback | Code now uses DB and fixed fallback, not the text file. |
| `src/mission_builder/dungeon_delve/__init__.py` comments mention auto-detecting party level from `character_memory.txt` | Needs comment cleanup if party level is DB-backed through encounters/character helpers. |

### Skills/Docs That Will Reintroduce JSON Debt

These are not runtime blockers, but they matter because future agents read them:

| File | Stale guidance found |
|---|---|
| `skills/tower-bot/SKILL.md` | Lists `city_gazetteer.json`, `npc_roster.json`, `mission_memory.json`, `faction_reputation.json`, `news_memory.txt`, `character_memory.txt`, `tia.json`, `towerbay.json`, `used_parties.json`, and `economy_cadence.json` as data sources. |
| `skills/tower-bot-files/SKILL.md` | Similar stale file map, including `locations.py` pulling from `city_gazetteer.json` and `npcs.py` pulling from `npc_roster.json`. |
| `skills/dnd-mission-docx/SKILL.md` | Contains code examples loading `mission_memory.json`, `npc_roster.json`, and `faction_reputation.json` directly. |
| `skills/stepped-operations/SKILL.md` | Has old operation examples around editing `npc_roster.json`. |
| `skills/windows-mcp-access/SKILL.md` | References the absolute path to `npc_roster.json`. |

Migration task: after runtime cutover, update these skills/docs so future agents are told to query MySQL/API instead of JSON files. Otherwise the code can be clean and the process will still drift back toward files.

### Direct Reference Implication

The deletion plan should include two checklists per file:

- **Runtime checklist:** no imports, reads, writes, glob scans, or fallback paths remain.
- **Agent/docs checklist:** no skills, README-style docs, or project memory files instruct humans/agents to use the old JSON.

For this project, the second checklist matters because previous agents have followed stale skill docs and touched the wrong files.

## Deep Research Notes: Field-Level Parity

I cross-checked the large legacy JSON files against live MySQL rows by normalized names/titles and then compared non-empty file keys to DB columns plus JSON blob keys.

### NPC Roster Parity

`campaign_docs/npc_roster.json` matched as a subset of the DB by normalized NPC name. The top file keys are all represented by a live column, `data_json`, or `appearance_json`:

- `name`, `age`, `rank`, `role`, `secret`, `status`, `faction`, `history`, `species`, `location`
- `appearance`, `motivation`, `oracle_notes`, `relationships`, `revealed_secrets`
- `stats`, `level`, `dnd_class`, `last_event_at`, `created_at`, `style`, `equipment`, `sd_prompt`, `home_district`

Only `_db_id` appeared as a repeated missing field. That looks like an obsolete file-local/linkage field, not campaign content. Practical implication: `npc_roster.json` is close to deletion-safe once runtime readers and stale docs are cut over.

### Party Profile Parity

All 110 `campaign_docs/party_profiles/*.json` files matched live `party_profiles` rows by normalized party name.

Top file keys:

- `name`, `affiliation`, `specialty`, `members`, `visual`, `reputation_note`, `history`
- `missions_completed`, `missions_failed`, `tier`, `points`, `generated`

Only one file had an extra non-empty `oracle_notes` field (`unknown_party`). This can be merged into `profile_json` before deletion. The bigger blocker is not data coverage; it is code coverage: `src/news_feed.py:_find_parties_in_text()` still scans the JSON directory.

### Mission Memory Parity

All 333 legacy `campaign_docs/mission_memory.json` entries matched live `missions` rows by normalized title, but lifecycle fields are not fully preserved.

Fields that are covered:

- `reward`: present for all 333 through `missions.reward_ec`, though old file reward text is not an exact string match because DB stores integer EC.
- `body`: present for all 333 through `missions.description` and/or a small number of `mission_json.body` entries; 311 exact-ish matches to `description`.
- `message_id`: covered by `missions.message_id` or `mission_json.message_id`.
- `posted_at`, `claimed`, `completed`, `failed`, `player_claimer`: mostly represented by status/message/claimer columns or current mission flow.

Fields that are not covered enough to delete blindly:

| Legacy field | Non-empty file rows | Found in live DB/mission_json | Migration implication |
|---|---:|---:|---|
| `expires_at` | 333 | 4 | Backfill `missions.expires_at` from old JSON before archiving if expiry history matters. |
| `claim_message_id` | 244 | 0 | Add `claim_message_id` column or keep inside `mission_json`; useful for Discord claim/result traceability. |
| `npc_complete_at` | 196 | 0 | Add `npc_complete_at`/`scheduled_complete_at` or create an NPC claim table. |
| `npc_outcome` | 196 | 0 | Preserve as NPC lifecycle/result state; current outcome table is better for rich post-completion notes. |
| `opposing_faction` | 89 | 1 | Backfill into `mission_json.opposing_faction` or add a first-class column if commonly filtered. |
| `personal_for` | 57 | 2 | Backfill into `mission_json.personal_for` or existing `personal_missions` if that table is revived. |
| `claim_at` | 53 | 0 | Add to `mission_claims`/`mission_lifecycle_events`; do not overload `completed_at`. |
| `claim_party` | 53 | 0 | Add to `mission_json.claim_party` at minimum; scripts already expect it there. |
| `doppelganger_of` | 6 | 0 | Preserve in `mission_json` for strange occurrences continuity. |

This is now the highest-risk JSON deletion. The DB has the mission rows, but not all the old mission lifecycle/story-control fields that NPC parties, strange occurrences, dashboard history, and Discord result backfills care about.

### Mission Lifecycle Table Recommendation

Instead of adding every old key to `missions`, create a small claim/lifecycle companion table:

| Proposed table | Fields |
|---|---|
| `mission_claims` | `id`, `mission_id`, `claimant_type` (`player`/`npc_party`), `claimant_name`, `claim_message_id`, `claim_at`, `scheduled_complete_at`, `outcome_status`, `outcome_json`, `created_at`, `updated_at` |
| `mission_lifecycle_events` | `id`, `mission_id`, `event_type`, `actor_type`, `actor_name`, `discord_message_id`, `event_at`, `event_json` |

Use `mission_claims` for current state and `mission_lifecycle_events` for audit/history. Keep `missions.status`, `claimed_by`, `completed_at`, and `message_id` as the fast dashboard fields. This keeps Discord, dashboard 5001, Mimir, and MySQL aligned without turning `missions` into a junk drawer.

## Deep Research Notes: API Expectations Around Mission Fields

The dashboard serializer in `Webpage/app.py` reads:

- `missions.description` or `mission_json.body` for display body.
- `missions.reward_ec` or `mission_json.reward` for reward display.
- `missions.expires_at` or `mission_json.expires_at`.
- `mission_json.personal_for` and `mission_json.opposing_faction`.
- joined `mission_outcomes` for debrief/outcome display.

`scripts/backfill_npc_outcomes.py` expects completed/failed NPC missions to have:

- `mission_json.claim_party`
- `mission_json.opposing_faction`
- `mission_json.body`
- no `mission_json.personal_for` for NPC-party outcome backfills

That script is a concrete reason to preserve/backfill `claim_party`, `opposing_faction`, and `body` in DB JSON before deleting `mission_memory.json`. If those keys are absent, outcome backfills degrade to `Unknown Party` or lose faction context.

## Deep Research Notes: JSON Classes To Exclude From Campaign Migration

Not every `.json` in the repo should become MySQL data.

### Keep As Files

| JSON class | Reason |
|---|---|
| `package.json`, `package-lock.json`, `src/docx_builder/package*.json` | Build/dependency metadata. |
| `.mcp.json`, `.claude/settings*.json`, skill `metadata.json` | Tool/agent configuration, not campaign state. |
| `.venv/**`, `.chrome_ddb_profile/**` JSON | Dependency/browser cache internals. Do not scan for migration. |
| `generated_modules/**/maps_manifest.json` and `*.vtt.json` | Generated module artifacts. Keep with module output; optionally index metadata in DB, but do not migrate the artifact body as canonical campaign state. |
| `logs/learning/test_modules/*.json` | Learning/test output. Could be archived or summarized, but should not become operational state. |
| `logs/ddb_vtt_probe.json` | Probe/debug artifact. Keep or delete by log-retention policy, not DB migration. |

### Staging Files

| JSON file | Current role | Recommendation |
|---|---|---|
| `scripts/npc_ddb_staging.json` | DDB NPC import staging; used by `scripts/npc_ddb_builder.py`, `scripts/import_npcs_to_ddb.py`, and `scripts/enrich_creatures_ddb.py`. | Leave as short-lived staging unless DDB imports become a recurring admin workflow. If recurring, create `ddb_import_batches` and `ddb_import_rows`. |
| `scripts/creature_ddb_staging.json` | DDB creature import staging; used by `scripts/build_creature_staging.py` and `scripts/enrich_creatures_ddb.py`. | Same as above. |
| `campaign_docs/TrainingPDFS/*.json` | Extraction/intermediate training artifacts from PDFs. | Treat as corpus build artifacts. If learning should query them live, use `training_docs` or a `training_chunks` table, not raw JSON files. |

## Deep Research Notes: Character JSON Still Needs A Pass

Two character JSON families remain in the migration inventory:

- `campaign_docs/char_snapshots/*.json`
- `src/character_appearance/*.json`

The live DB has `character_snapshots`, `latest_character_snapshots`, and `player_characters`, so snapshots likely have a natural destination. `src/character_profiles.py` and `src/cogs/character.py` still need a focused read before declaring character JSON deletion-safe, because appearance commands may be using the file sidecars as the current write path.

### Character Pass Follow-Up

Focused read results:

- `src/character_profiles.py` is now DB-backed. It reads/writes `player_characters.profile_json` for profile text and appearance text.
- `src/cogs/character.py` uses `load_character_appearance()` / `save_character_appearance()`, so current appearance slash commands also hit DB through `character_profiles.py`.
- `src/character_monitor.py` saves snapshots through `save_character_snapshot()` and uses DB for previous/latest snapshots. It only falls back to `campaign_docs/character_memory.txt` if the DB update path cannot find/update a `player_characters` row.
- `src/db_api.py` has DB helpers for `character_snapshots` and cleanup of old snapshot rows.
- Many mission pipelines already read `latest_character_snapshots` and `player_characters`, so mission generation is largely DB-first for PC context.

Live DB check:

- `player_characters`: 8 rows.
- `character_snapshots`: 30 rows.
- `latest_character_snapshots`: 8 rows.
- All 8 `player_characters.profile_json` blobs have an `appearance` value.
- `src/character_appearance/*.json` has only 3 sidecar files: Eleanor Reed, Keta Fadeworth, and S'kree.

Important defect/risk found while researching: all live `player_characters.player_discord_id` values printed as `None`. `character_profiles.py` looks up by `player_discord_id`, so slash-command saves/loads by Discord user may fail to find the existing PC row and can create duplicate `Player_<id>` rows. Before deleting `src/character_appearance/*.json`, backfill `player_discord_id` for the eight known PCs, likely from `character_monitor.CAMPAIGN_CHARACTERS` / Discord roster mapping.

Character migration recommendation:

1. Backfill `player_discord_id` and any missing `player_name` values in `player_characters`.
2. Verify slash commands load existing DB rows by Discord ID.
3. Import or compare the three `src/character_appearance/*.json` sidecars against existing `profile_json.appearance`.
4. Delete/archive the sidecars only after the Discord-ID lookup path is stable.
5. Keep `character_memory.txt` only as a generated export/RAG compatibility artifact, not as writable source-of-truth.

## Revised High-Risk Order

1. **Mission memory:** backfill lifecycle fields or add `mission_claims`/`mission_lifecycle_events` before deleting `mission_memory.json`.
2. **Party profiles:** data mostly covered; replace the `news_feed.py` directory scan.
3. **NPC roster:** data mostly covered; remove stale file docs and any remaining first-run/file fallback behavior.
4. **Bounties/missing persons:** schema too narrow; add JSON/detail columns or archive old files intentionally.
5. **Character snapshots/appearance:** needs focused read of character helpers and dashboard/API routes.
6. **World/gazetteer/map files:** live DB is strong here, but remove direct gazetteer file readers from area map generation, Mimir sync, seed scripts, and mission fallback helpers.

## Deep Research Notes: Bounties, Missing Persons, And Markets

### Bounties

`src/bounty_board.py` is DB-backed for runtime loading/saving, but `_save_bounty()` intentionally drops most rich post data because the current `bounties` table only has:

- `title`
- `target_type`
- `target_name`
- `reward_ec`
- `status`
- `created_at`
- `claimed_by`

Legacy `campaign_docs/bounty_board.json` entries contain:

- full `body` notice text
- `issuer`
- `proxy_faction`
- `reward`
- `posted_at`
- `expires_at`
- `message_id`
- `resolved`

Live DB sample rows are poor quality for the old entries: several are `Untitled`, blank target, `reward_ec = 0`, `expired`. That confirms this is not just a stale-file problem; current persistence is lossy for bounty bulletins.

Recommendation before deleting `bounty_board.json`:

- Add `body TEXT`, `issuer VARCHAR(255)`, `proxy_faction VARCHAR(255)`, `posted_at DATETIME`, `expires_at DATETIME`, `message_id VARCHAR(50)`, and `bounty_json JSON`.
- Update `_save_bounty()` to persist the full generated `bounty_data`.
- Backfill old file entries into DB, using `bounty_json` for any fields that do not deserve first-class columns.

### Missing Persons

`src/missing_persons.py` is also DB-backed, but `_save_missing_record()` drops nearly all notice content. Current table has:

- `person_name`
- `last_seen_location`
- `reported_at`
- `status`
- `found_at`

Legacy `campaign_docs/missing_persons.json` entries contain:

- full `body` notice text
- `posted_at`
- `expires_at`
- `resolved`
- `found`

The generator has `filed_by`, district, urgency, description, and circumstances in prompt/runtime context, but the DB currently saves only name/district/status/time. This is enough for cooldown/resolution ticking but not enough for dashboard review, story continuity, or Mimir context.

Recommendation before deleting `missing_persons.json`:

- Add `notice_body TEXT`, `filed_by VARCHAR(255)`, `posted_at DATETIME`, `expires_at DATETIME`, `resolved_at DATETIME`, and `record_json JSON`.
- Update `_save_missing_record()` to persist the generated notice body and metadata.
- Preserve old `found`/resolution info in `record_json` during backfill.

### Player Listings

`campaign_docs/player_listings.json` has 2 rich historical listings with bid logs. Live `player_listings` is empty even though the table has a good `listing_json` column. This is an import gap, not a schema gap.

Recommendation:

- Import file rows into `player_listings.listing_json`.
- Map `player_id`, `player_name`, `item_name`, `asking_price`/`min_bid`, status, current/high bid fields where available.
- Preserve `bid_log`, final price, and sold timestamp inside `listing_json`.

### TowerBay

`campaign_docs/towerbay.json` has 56 old rows. Live `towerbay_auctions` has 66 rows and includes `auction_json`. The live rows preserve rich item description/category/condition/seller/current bid data. This table is structurally ready.

Migration caution:

- Do not blindly overwrite live auctions from the file. The file appears older than live DB.
- Use id/name/listed_at matching to import only file-only history, if any.
- Keep generated auction artifacts in DB `auction_json`; no API should need to read `towerbay.json`.

### TIA Market

`campaign_docs/tia.json` has a sector dictionary plus `last_updated` and `last_event`. Live `tia_market` has current sector rows with `value`, `prev_value`, `trend`, and timestamp columns, but `value_json`/`state_json` were empty in the sample.

Recommendation:

- Current sector values should stay row-based for charting/filtering.
- Store whole-market metadata like `last_event` in `global_state.tia_market_state` or in `tia_market.state_json` on a dedicated state row.
- Avoid leaving `tia.json` as the only place that remembers the last market event.

## Deep Research Notes: World, Gazetteer, And Map Memory

The live DB is strong enough to replace `campaign_docs/city_gazetteer.json` for most runtime uses:

- `gazetteer_places`: 312 rows across 27 districts.
- `area_profiles`: 27 rows, one per district.
- `battle_maps_library`: 260 downloaded/analyzed maps.
- `battle_map_area_memory`: 134 remembered area/mission/map choices.

District coverage in `gazetteer_places` and `area_profiles` lines up. Every district that appeared in the live gazetteer summary also had an area profile.

Map type coverage in `battle_maps_library`:

| Map type | Count | Current use count |
|---|---:|---:|
| `street` | 72 | 26 |
| `dungeon` | 51 | 13 |
| `cave` | 33 | 5 |
| `office` | 33 | 27 |
| `temple` | 28 | 6 |
| `tavern` | 17 | 13 |
| `arena` | 13 | 14 |
| `warehouse` | 7 | 2 |
| `sewer` | 4 | 0 |
| `rooftop` | 2 | 1 |

This supports the desired direction: mission pipelines should call `src.battle_map_library.get_battle_map(...)` or the mission-builder map wrapper and post/use downloaded images directly. They should not generate maps on the fly and should not scan downloads themselves.

### Remaining Gazetteer File Blockers

Confirmed direct/stale `city_gazetteer.json` references:

| File | Status |
|---|---|
| `src/area_map_generator.py` | Direct file constant and file-driven area extraction. Should query `gazetteer_places`/`area_profiles` instead. |
| `src/agents/news_agents.py` | Stale comment says gazetteer file is the only permitted file read; code now has arena venue DB/global_state logic. Comment should be fixed. |
| `src/mimir_sync.py` | Direct world overview from `city_gazetteer.json`; should bridge from `gazetteer_places`, `area_profiles`, and `global_state.world_setting`. |
| `src/mission_builder/locations.py` | Has a one-time migration from file plus DB query with JSON fallback. After migration, fallback should be removed or guarded behind explicit admin tooling. |
| `src/mission_builder/dungeon_delve/__init__.py` | Has gazetteer file fallback. Should use shared DB location helper only. |
| `src/news_feed.py` | Comment says DB falls back to `city_gazetteer.json`; verify exact fallback path before deletion. |
| `scripts/seed_battle_maps.py` | Uses gazetteer file for seeding/linking; should use DB districts/places if kept. |
| `src/mission_module_gen.py` | Stale comment says real location names come from `city_gazetteer.json`. Runtime may already be DB-backed elsewhere. |

### Map Memory Quality Notes

`battle_map_area_memory` is doing the right kind of thing, but sample rows show cleanup opportunities before relying on it as long-term canonical memory:

- Some rows have blank `district_slug`.
- Some rows have blank `map_type`.
- Several repeated generic areas like `confrontation site at the mission board` map to tavern/street across unrelated mission types.
- Area names can be very long generated phrases, e.g. escort route text, rather than stable place keys.

Recommendation:

1. Normalize area memory keys around `gazetteer_places.id` when a specific place is known.
2. Keep free-text `area_key` for generated/special scenes, but always store `district_slug` and `map_type`.
3. Add a confidence/source field if possible: `gazetteer_place`, `pipeline_scene`, `module_generated`, `manual`.
4. When a pipeline requests a map for the same `area_key + mission_type + map_type`, reuse memory first; otherwise pick from `battle_maps_library` and then record the choice.
5. Build a small cleanup script to fill blank `district_slug`/`map_type` from mission/module context where recoverable.

### Arena Venues

`src/agents/news_agents.py` already tries to load arena venues from `global_state.arena_venues`, but live `global_state` did not contain that key. `campaign_docs/arena_venues.json` still needs a destination.

Recommendation:

- Short term: import `arena_venues.json` into `global_state.arena_venues` so existing news-agent behavior works.
- Better long term: create `arena_venues` with columns like `name`, `district`, `venue_type`, `prestige`, `factions_json`, `event_types_json`, `venue_json`, `active`.

### Public Health / Long-Running News Arcs

The DB already has the right mechanism for the flu/magic-resistant-virus style story:

- `global_state.public_health_arcs`
- `global_state.world_active_tensions`
- `news_memory`
- `news_entries`
- mission posting hooks in `mission_board.py` for `PUBLIC_HEALTH_MISSION_TYPES`

So this should not need a new JSON file. The migration rule should be: long-running civic arcs live in `global_state` plus `news_entries`/`news_memory`, and mission generation reads those DB keys when selecting factions, affected populace, and mission type.
