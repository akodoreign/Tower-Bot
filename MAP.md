# Codebase Map — chatGPT-discord-bot
Last updated: 2026-05-22

## Architecture Overview
Discord bot running on Python 3.11 + discord.py. MySQL is authoritative for all campaign data. Cogs handle slash commands. Background tasks handle world simulation. Mission pipelines generate D&D adventure modules.

**Entry point:** `main.py` → loads `.env`, starts `src/bot.py` + optional Webpage dashboard

---

## src/ — Core Modules

### Bot Infrastructure
| File | Purpose | Status |
|------|---------|--------|
| `bot.py` | Discord bot, loads cogs, event loop | ACTIVE |
| `aclient.py` | Async client, message processing, RAG, skill dispatch | ACTIVE |
| `providers.py` | Multi-LLM abstraction (OpenAI, Claude, Gemini, Grok, Ollama) | ACTIVE |
| `personas.py` | NPC/bot personality templates | ACTIVE |
| `log.py` | Centralized logging | ACTIVE |
| `db_api.py` | MySQL pool; raw_query, raw_execute, get/set_global_state; NPC/party history helpers; revealed_secrets helpers; treasure_items helper | ACTIVE |
| `db_backup.py` | MySQL backup utility | ACTIVE |
| `memory_strip.py` | Context window trimming | ACTIVE |

### Image & Art
| File | Purpose | Status |
|------|---------|--------|
| `a1111_runtime.py` | A1111 Stable Diffusion API wrapper | ACTIVE |
| `art.py` | ASCII/visual formatting | ACTIVE |
| `image_ref.py` | Image reference DB management | ACTIVE |
| `tts_engine.py` | Text-to-speech | ACTIVE |

### Mission System
| File | Purpose | Status |
|------|---------|--------|
| `mission_compiler.py` | Main pipeline coordinator (replaced module_generator) | ACTIVE |
| `mission_board.py` | Mission display/UI | ACTIVE |
| `mission_module_gen.py` | Mission→module bridge | ACTIVE |
| `mission_outcomes.py` | Post-mission result processing | ACTIVE |
| `module_quality_trainer.py` | Self-learning quality loop | ACTIVE |
| `module_generator.py` | **DEPRECATED** — raises ImportError, points to mission_compiler | DEPRECATED |

### Economy & World
| File | Purpose | Status |
|------|---------|--------|
| `tower_economy.py` | Tower Bay auction/economy | ACTIVE |
| `arena_season.py` | Arena bracket competitions | ACTIVE |
| `faction_reputation.py` | Faction rep tracking | ACTIVE |
| `faction_calendar.py` | World event calendar | ACTIVE |
| `ec_exchange.py` | Currency conversion | ACTIVE |
| `dome_weather.py` | Dynamic weather simulation (44 types) | ACTIVE |
| `city_scene.py` | Procedural city scene generation | ACTIVE |
| `area_generator.py` | Area/location builder | ACTIVE |
| `area_map_generator.py` | Area map generator | ACTIVE |
| `area_places.py` | POI/place builder | ACTIVE |

### NPCs & Characters
| File | Purpose | Status |
|------|---------|--------|
| `npc_lifecycle.py` | NPC lifecycle events (death, injury, retirement); writes history via `_hist()` → `npc_history` table | ACTIVE |
| `npc_appearance.py` | NPC visual description gen; handles multiclass blending | ACTIVE |
| `npc_consequence.py` | Post-bulletin NPC consequence scanner; writes history via `_hist()` | ACTIVE |
| `npc_lookup.py` | NPC name→context for chat; reads revealed_secrets from DB | ACTIVE |
| `npc_statblock_backfill.py` | D&D stat block backfill | ACTIVE |
| `character_profiles.py` | PC profile; reads/writes `profile_text` and `appearance` real columns (not profile_json) | ACTIVE |
| `character_monitor.py` | Memory + consequence polling (uses character_memory/ dir) | ACTIVE |
| `party_profiles.py` | Party info; `employer`/`tier` are real columns; history via `_hist_party()` → `party_history` | ACTIVE |
| `party_interview.py` | Interactive party questionnaire | ACTIVE |
| `fallen_adventurers.py` | Mortality tracking | ACTIVE |
| `missing_persons.py` | Missing NPC tracker | ACTIVE |
| `nudge_state.py` | Quest nudge state (uses nudge_state/ dir) | ACTIVE |

### Content Feeds
| File | Purpose | Status |
|------|---------|--------|
| `news_feed.py` | World news bulletin generation | ACTIVE |
| `news_integration.py` | News feed integration layer | ACTIVE |
| `ad_feed.py` | Advertisement/job posting generation | ACTIVE |
| `bounty_board.py` | Bounty/contract postings | ACTIVE |
| `bulletin_embeds.py` | Discord embed formatting | ACTIVE |
| `bulletin_cleaner.py` | Stale bulletin cleanup | ACTIVE |
| `expandable_bulletin.py` | Long bulletin pagination | ACTIVE |
| `player_listings.py` | Player listing display | ACTIVE |

### Knowledge & Skills
| File | Purpose | Status |
|------|---------|--------|
| `tower_rag.py` | RAG from campaign docs + DB | ACTIVE |
| `rag_sanity_check.py` | RAG quality audit | ACTIVE |
| `rules_agent.py` | D&D 5e rules lookup | ACTIVE |
| `skills.py` | Skill system core | ACTIVE |
| `skill_loader.py` | Dynamic skill loading from skills/ dir | ACTIVE |
| `self_learning.py` | Nightly self-improvement loop | ACTIVE |

### Integrations
| File | Purpose | Status |
|------|---------|--------|
| `mimir_client.py` | Mimir campaign API client | ACTIVE |
| `mimir_sync.py` | Local ↔ Mimir sync | ACTIVE |
| `ddb_homebrew.py` | D&D Beyond homebrew HTTP pipeline | ACTIVE |
| `patch_approval.py` | Patch approval workflow | ACTIVE |

### System
| File | Purpose | Status |
|------|---------|--------|
| `resource_cop.py` | Resource/token usage cop | ACTIVE |
| `ollama_queue.py` | Ollama request queue | ACTIVE |
| `ollama_busy.py` | Ollama busy-state tracker | ACTIVE |
| `weekly_archive.py` | Weekly log archival | ACTIVE |
| `archive_logs.py` | Log file archiver | ACTIVE |
| `text_mojibake.py` | Unicode/encoding fixer | ACTIVE |
| `style_agent.py` | Narrative style consistency | ACTIVE |

---

## src/cogs/ — Discord Slash Commands

| File | Commands | Status |
|------|----------|--------|
| `admin.py` | /restart, /status, /purge, admin tools | ACTIVE |
| `character.py` | /character create/level/inventory | ACTIVE |
| `chat.py` | /chat — RAG-enhanced conversation | ACTIVE |
| `economy.py` | /economy, Tower Bay, auctions | ACTIVE |
| `images.py` | /image generate, A1111 integration | ACTIVE |
| `missions.py` | /mission list/claim/complete | ACTIVE |
| `module_gen.py` | /generate module → calls mission_compiler | ACTIVE |
| `rules_lookup.py` | /rules — D&D 5e rules lookup | ACTIVE |
| `skills.py` | /skill commands | ACTIVE |
| `world.py` | /world, /weather, /location | ACTIVE |

---

## src/agents/ — LLM Orchestration

| File | Purpose | Status |
|------|---------|--------|
| `base.py` | Abstract Agent class; tool-use loop | ACTIVE |
| `orchestrator.py` | Multi-agent routing + coordination | ACTIVE |
| `guild_council.py` | Guild NPC council agents | ACTIVE |
| `news_agents.py` | News bulletin generation agents | ACTIVE |
| `learning_agents.py` | Self-learning improvement agents | ACTIVE |
| `kimi_agent.py` | Kimi (Chinese LLM) agent | ACTIVE |
| `qwen_agent.py` | Qwen local model agent | ACTIVE |
| `helpers.py` | Shared agent utilities | ACTIVE |

---

## src/mission_builder/ — Mission Pipelines

### Core Infrastructure
| File | Purpose |
|------|---------|
| `api.py` | REST API for mission generation |
| `mission_json_builder.py` | Intent → mission JSON |
| `json_generator.py` | JSON generation utilities |
| `schemas.py` | Mission JSON schema definitions |
| `encounters.py` | Combat encounter builders |
| `monster_stat_gen.py` | Monster stat block generation |
| `npcs.py` | NPC generation for missions |
| `locations.py` | Location/dungeon builders |
| `maps.py` | Tactical map generation |
| `scene_dialogs.py` | Dialog/scene scripting |
| `leads.py` | Adventure hooks/plot leads |
| `rewards.py` | Loot & reward tables |
| `cr_scaling.py` | CR scaling utilities |
| `boxset_utils.py` | Boxset content utilities |
| `module_council.py` | Multi-agent module review |
| `session_runner.py` | Live session execution |
| `skills_integration.py` | Skills system integration |
| `docx_builder.py` | .docx export |
| `html_renderer.py` | HTML export |
| `vtt_renderer.py` | VTT (Foundry/Roll20) export |
| `image_generator.py` | AI image gen for encounters |
| `image_integration.py` | Image embedding |
| `infestation_layout.py` | Infestation-specific map layout |

### Mission Type Pipelines (each intentionally distinct)
| File | Type |
|------|------|
| `ambush_pipeline.py` | Ambush encounters |
| `assassination_pipeline.py` | Assassination contracts |
| `assault_pipeline.py` | Military assault |
| `battle_pipeline.py` | Large-scale battles |
| `defense_pipeline.py` | Defense missions |
| `discovery_pipeline.py` | Exploration & discovery |
| `escort_pipeline.py` | Escort/protection |
| `exploration_pipeline.py` | Wilderness exploration |
| `first_contact_pipeline.py` | First contact |
| `gather_pipeline.py` | Resource gathering |
| `heist_pipeline.py` | Heist scenarios |
| `infiltration_pipeline.py` | Stealth infiltration |
| `infestation_pipeline.py` | Monster infestation |
| `investigation_pipeline.py` | Mystery investigation |
| `negotiation_pipeline.py` | Diplomacy/negotiation |
| `novel_pipeline.py` | Novel/story missions |
| `puzzle_pipeline.py` | Puzzle encounters |
| `recovery_pipeline.py` | Recovery/rescue |
| `rescue_pipeline.py` | NPC rescue |
| `sabotage_pipeline.py` | Sabotage operations |
| `strange_occurrences_pipeline.py` | Unexplained events |
| `published_pipeline.py` | Pre-published module processing |

---

## scripts/ — Utilities

### Active (regularly used)
- `build_creature_staging.py` — Extract creatures from modules → DDB staging
- `build_modules_saturday.py` — Weekly module batch builder
- `enrich_creatures_ddb.py` — Add portraits/stats to DDB creatures + NPC portrait fill
- `npc_ddb_builder.py` — Build NPC stat blocks for DDB import
- `import_npcs_to_ddb.py` — Bulk NPC importer (accepts --staging/--log/--art-dir args)
- `import_ebp_to_ddb.py` — EBP monster importer
- `update_ebp_content.py` — Enrich EBP content on DDB
- `survey_mission_creatures.py` — Audit creature data in modules
- `survey_ddb_import_candidates.py` — Survey DDB import queue
- `check_mimir.py` — Verify Mimir connectivity

### One-off / Completed (archivable)
- `fix_culinary_council.py`, `fix_ebp_types_only.py`, `fix_ebp_types_and_art.py`
- `repair_boxxo_chapters.py`, `write_boxxo_chapters.py`, `write_boxxo_chapters_v2.py`
- `write_boxxo_module_html.py`, `run_boxxo_module.py`
- `import_area_profiles.py`, `import_culinary_council.py`
- `seed_gazetteer_businesses.py`, `seed_gazetteer_infrastructure.py`, `seed_unknown_party.py`
- `migrate_characters.py`, `migrate_towerbay_bids.py`
- `extract_ddb_session.py`, `extract_pdfs.py`
- `cleanup_image_refs.py`, `quarantine_duplicate_npc_refs.py`
- `merge_faction_leaders.py`, `reset_npc_sync_hashes.py`
- `package_5etools_for_mimir.py`, `import_pantheon.py`
- `run_full_ddb_import.py` (superseded by --staging arg)
- `_test_ddb_form.py`, `test_one_art_edit.py`, `test_one_npc_import.py`
- `test_wysiwyg.py`, `test_module_quality_training.py`, `test_news_agents.py`

### Diagnostic (keep for now)
- `probe_ddb_edit.py`, `probe_ddb_fields.py`, `probe_mimir_npc.py`
- `gearrun_mimir.py`, `experiment_map_lanes.py`
- `retry_map_pretty.py`, `retry_module_gen.py`
- `backfill_*.py` (4 files) — May still be needed
- `ebp_enriched_data.py` — Data file for EBP enrichment

---

## Root-level Files

### Active
- `main.py` — Entry point
- `requirements.txt` — Dependencies
- `pytest.ini` — Test config
- `CLAUDE.md` — This project's AI instructions
- `buglog.md` — Running bug log (ACTIVE)
- `codex.md` — Game world lore
- `README.md` — Project overview
- `database_schema.sql` — Current schema reference
- `start_tower.ps1`, `stop_tower.ps1` — Bot start/stop scripts

### Archivable (one-off scripts, done)
- `apply_schema.py`, `mysql_setup.py`, `sql_refactor_setup.py`
- `fix_migration.py`, `fix_npc_roster.py`, `fix_syntax.py`, `fix_syntax2.py`
- `fix_mistral_to_qwen.py`, `# fix_mistral_to_qwen.py` (duplicate with # prefix)
- `migrate_data.py`, `migrate_add_columns.py`, `patch_news_parties.py`
- `clear_commands.py`, `merge_faction_leaders.py`, `rag_sanity_check.py`
- `null` (stray PowerShell artifact file)
- `hardir/` (empty directory)
- `backups/` (42 files — all old backups)
- `worklog_mission_fix.md`, `worklog_ollama_model_fix.md`
- `dungeon_delve_architecture.md`, `STEP2_COMPLETION.md`
- `CUDA_FIX_SUMMARY.md`, `QWEN_CUDA_FIX.md`
- `PHASE_3_IMPLEMENTATION_SUMMARY.md`, `SKILLS_SYSTEM_DEPLOYMENT.md`
- `SKILLS_INTEGRATION_EXAMPLES.py`
- `alter_add_character_snapshots.sql` (already applied)
- `test_dungeon_delve.py`, `test_mission_builder.py`, `test_skills_quick.py` (root-level, superseded by tests/)

### Live Docs (keep)
- `AGENTS.md`, `AGENT_SYSTEM.md` — Agent architecture docs
- `MISSION_JSON_SCHEMA.md` — Schema reference
- `QUICKSTART_AGENTS.md` — Agent quickstart
- `SKILLS_INTEGRATION_GUIDE.md` — Skills guide
- `MISSION_BUILDER_REFACTOR.md` — Refactor history reference

---

## Data Directories
- `campaign_docs/` — Legacy JSON (read-only archive; DB is authoritative; all runtime code reads DB only)
- `generated_modules/` — Output from mission pipelines
- `logs/` — Bot logs, import logs, debug logs
- `skills/` — Skill definition files loaded by skill_loader.py
- `nudge_state/` — Live nudge state per player (party ID .flag files)
- `character_memory/` — Live character memory per player (party ID .txt files)
- `Webpage/` — Flask dashboard (app.py)
- `auto_login/` — AutoLogin utility
- `docs/` — Additional documentation
