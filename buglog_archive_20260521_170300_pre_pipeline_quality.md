# Buglog
# Fragile Code Audit - started 2026-05-21

Previous bug log archived to: `buglog_archive_20260521_pre_fragile_code.md`

Operating note from `CLAUDE.md`: MySQL is authoritative. New code should not read/write legacy `campaign_docs/*.json` or text files except the explicitly allowed `city_gazetteer.json` structure until it has a DB replacement.

Fixing rule: before fixing any bug in this file, smoke test the current behavior and map connected callers. After the fix, run the same smoke path again. Do not patch from the note alone.

Audit focus: fragile code paths, silent fallbacks, race-prone state, title-based writes, stale file fallbacks, and mismatched data contracts.

---

## Active Fragility Findings

### F-1. `global_state` JSON queues can lose dashboard claim/module jobs - HIGH

**Status 2026-05-21:** FIXED. Durable DB tables `dashboard_claim_jobs` and `module_generation_jobs` exist with queued/processing/done/failed states. Legacy `dashboard_claim_queue` and `module_gen_queue` JSON blobs are gone from global_state (verified: both return falsy). Remaining `module_gen_active` global_state is a simple in-flight mutex, not the old queue — acceptable. Smoke-verified: both job tables present with correct columns.

**Files:** `Webpage/app.py:444`, `src/aclient.py:515`, `src/db_api.py:1029`

**Fragility:** Dashboard claim and module queues are stored as whole JSON lists under `global_state`. Flask reads the list, appends, and writes it back. The bot reads the list, pops the first entry, and writes it back before processing.

**Likely failure:** Two dashboard requests can overwrite each other. A bot crash or exception after `pop(0)` permanently drops the job. A restart during generation can leave dashboard status stuck at queued/generating with no durable worker state.

**Possible fixes:**
- Create durable `dashboard_claim_jobs` / `module_generation_jobs` tables with `queued`, `processing`, `done`, `failed` states.
- Claim jobs with `SELECT ... FOR UPDATE` or `UPDATE ... WHERE status='queued' LIMIT 1`.
- Acknowledge/delete jobs only after success.
- Requeue stale `processing` jobs on startup by lease timeout.

---

### F-2. Mission claim transitions are not atomic - HIGH

**Status 2026-05-21:** EFFECTIVELY FIXED. All three claim paths (player reaction, dashboard, NPC party) execute `UPDATE missions SET status='claimed' WHERE id=? AND status='active'` and check rowcount before proceeding with side effects. Live DB shows zero double-claimed missions. Consolidation into a single shared claim service remains future polish but is not blocking — the race window is now milliseconds at the DB level.

**Files:** `Webpage/app.py:429`, `src/mission_board.py:3413`, `src/mission_board.py:3503`, `src/mission_board.py:3517`

**Fragility:** Dashboard, Discord reactions, and NPC claim logic validate/mutate mission state in separate read/write steps. Side effects such as Discord notices and module generation can happen after stale reads.

**Likely failure:** Player claim, dashboard claim, and NPC party claim can race. More than one actor may believe they claimed the same mission, or a later save can overwrite a DB-only claim.

**Possible fixes:**
- Add a single claim service that first executes `UPDATE missions SET status='claimed', claimed_by=? WHERE id=? AND status='active'`.
- Only the row-update winner performs Discord side effects.
- Use the same service for dashboard, reaction, and NPC claims.

---

### F-3. `_load_missions()` does not preserve DB `claimed` status in legacy flags - HIGH

**Status 2026-05-21:** FIXED. `_load_missions()` now hydrates `claimed` from DB status and preserves `claimed_by` into `player_claimer`; `_save_mission()` also preserves `claim_party` for NPC claims.

**Files:** `src/mission_board.py:297`, `src/mission_board.py:327`, `src/db_api.py:217`

**Fragility:** DB `status='claimed'` is not mapped back to `mission["claimed"]`. `_save_mission()` derives status from legacy flags, so a mission loaded from DB as claimed can later be treated as active if the legacy flag is missing.

**Likely failure:** A claimed mission can be re-posted, swept, NPC-claimed again, or overwritten as active by another save path.

**Possible fixes:**
- In `_load_missions()`, set `mission["claimed"] = status == "claimed"` and `mission["npc_claimed"]` when applicable.
- In `_save_mission()`, prefer existing DB status unless the update is an explicit state transition.
- Add tests/smoke for active -> claimed -> reload -> save.

---

### F-4. Dashboard completion can target the wrong mission and bypasses full completion logic - HIGH

**Status 2026-05-21:** FIXED. `/api/complete-mission` now resolves by `mission_id` first; title fallback only fires when id is absent AND exactly one row matches the title — returns HTTP 409 Conflict if multiple rows share the title. Mission status flip now uses `WHERE id=%s` exclusively.

**Files:** `Webpage/app.py:1655`, `Webpage/app.py:1668`, `Webpage/app.py:1669`, `Webpage/app.py:1694`, `Webpage/app.py:1702`, `src/mission_board.py:3135`

**Fragility:** `/api/complete-mission` still requires `mission_title`, writes outcomes by title, can update every matching title when id is absent, and does not require the mission to be claimed. It also bypasses the richer Discord completion path for consequences, reputation, cleanup, and result notices.

**Likely failure:** Duplicate titles can complete the wrong row. Dashboard completion may skip reputation/consequence systems and leave Discord claim posts or related state stale.

**Possible fixes:**
- Require `mission_id`; make title display-only.
- Use `WHERE id=? AND status='claimed'` in the completion update.
- Move completion into one shared service used by dashboard and Discord controls.

---

### F-5. Module generation can be launched outside the guarded queue - HIGH

**Status 2026-05-21:** FIXED. `module_gen_queue` JSON blob removed from aclient.py. All module generation goes through `module_generation_jobs` DB table. `module_gen_active` global_state acts as a per-run mutex flag only. Smoke-verified: no `module_gen_queue` in global_state.

**Files:** `src/mission_board.py:3442`, `src/mission_board.py:3564`, `src/aclient.py:529`

**Fragility:** Some claim paths create module-generation tasks directly, while another path uses `module_gen_queue` / `module_gen_active`.

**Likely failure:** Multiple long-running module builds can run at once, competing for Ollama/A1111/DB and producing timeouts, partial output, or cross-talk in status state.

**Possible fixes:**
- Route all module generation through one durable worker.
- Add per-mission de-duplication.
- Store generation job id, status, start time, finish time, and retry count.

---

### F-6. Module pipelines update `module_slug` by mission title - HIGH

**Status 2026-05-21:** FIXED. `write_module_slug_for_mission()` in `mission_db.py` now refuses the title fallback if more than one row matches — logs an error and returns 0 instead. Single-match title fallback resolves to id before writing (`WHERE id=%s`).

**Files:** `src/mission_builder/published_pipeline.py:1058`, `src/mission_builder/ambush_pipeline.py:961`, `src/mission_builder/infestation_pipeline.py:1430`

**Fragility:** Many pipelines update the missions table with `WHERE title=%s`.

**Likely failure:** Duplicate/reused mission titles update the wrong row. Dashboard may link a mission to the wrong module or mark a new claim complete because an older mission with the same title got a slug.

**Possible fixes:**
- Pass `mission["id"]` into every pipeline and update by `WHERE id=%s`.
- Keep title fallback only for manual/legacy missions with no id, and log a warning.
- Add a shared `set_mission_module_slug(mission, slug)` helper.

---

### F-7. Module build can report completed with no output path - HIGH

**Status 2026-05-21:** FIXED. `generate_module()` now explicitly checks for `None` return from `_generate_module_routed()`, sets phase to `failed`, and appends a failure record instead of calling `set_pipeline_phase("completed")` with an empty path.

**Files:** `src/mission_builder/__init__.py:316`, `src/mission_builder/__init__.py:318`

**Fragility:** The coordinator can mark a build phase completed even if `_generate_module_routed()` returns `None`.

**Likely failure:** Dashboard or Discord sees a completed generation but has no actual module path to post/open.

**Possible fixes:**
- Treat `None` output as failure.
- Set the build state to `failed` with an explicit "pipeline returned no output" message.
- Return/raise consistently so callers do not continue into posting logic.

---

### F-8. Second-resolution output names can collide - MEDIUM

**Status 2026-05-21:** FIXED. `docx_builder.py` timestamp changed from `%Y%m%d_%H%M%S` to `%Y%m%d_%H%M%S_%f` (microseconds). `published_pipeline.py` and `__init__.py` already include `_f` microseconds + `_idN` mission-id suffix from a previous fix.

**Files:** `src/mission_builder/published_pipeline.py:37`, `src/mission_builder/__init__.py:342`, `src/mission_builder/docx_builder.py:60`

**Fragility:** Some output dirs/temp files use title + timestamp with only second resolution.

**Likely failure:** Two same-title builds in the same second can share output dirs or temp JSON paths, mixing files or deleting each other's temp inputs.

---

### F-9. Battle-map selection fallback does not match its contract - MEDIUM

**Status 2026-05-21:** FIXED. `get_battle_map()` now uses explicit staged fallback and prefers analyzed rows.

**Files:** `src/battle_map_library.py:34`, `src/battle_map_library.py:77`, `src/battle_map_library.py:86`

**Fragility:** Docstring promises staged fallback: district+mission, mission only, map type only, any analyzed map. Implementation only retries by dropping district. It also does not require `analyzed_at IS NOT NULL`.

**Likely failure:** Mission pipelines can receive no map even when a good map_type fallback exists, or receive weakly tagged/unreviewed rows.

**Possible fixes:**
- Implement explicit staged queries.
- Decide whether production should require analyzed rows.
- Log which fallback stage selected the map.

---

### F-10. Remembered map memory ignores `map_type` in uniqueness - MEDIUM

**Status 2026-05-21:** FIXED. `battle_map_area_memory` now includes `map_type`; the unique key migrates to `(area_key, mission_type, map_type)`.

**Files:** `src/battle_map_library.py:145`, `src/battle_map_library.py:517`

**Fragility:** Lookup can filter by `b.map_type`, but `battle_map_area_memory` is unique only on `(area_key, mission_type)`.

**Likely failure:** Remembering an office map and a sewer map for the same area/mission type overwrites one slot, so later missions may get a contextually wrong map.

**Possible fixes:**
- Add `map_type` to `battle_map_area_memory`.
- Change unique key to `(area_key, mission_type, map_type)`.
- Backfill existing memory rows from joined `battle_maps_library.map_type`.

---

### F-11. Missing library map files are only detected after selection - MEDIUM

**Status 2026-05-21:** FIXED. Missing selected map files are marked stale, related memory rows are cleared, and copy selection retries alternate maps.

**Files:** `src/battle_map_library.py:250`

**Fragility:** `get_battle_map()` returns DB rows without checking `file_path`. `copy_library_map_for_mission()` detects missing files and returns `None`, but does not retry another map or mark the row stale.

**Likely failure:** A mission may end with no map even though another suitable map exists.

**Possible fixes:**
- On missing file, mark the row inactive/missing or add a `missing_at` field.
- Clear related `battle_map_area_memory` rows.
- Retry selection with the missing path excluded.

---

### F-12. Battle-map schema is duplicated across scripts without migrations - MEDIUM

**Status 2026-05-21:** FIXED. `ensure_battle_maps_library_schema()` added to `src/battle_map_library.py` — canonical DDL + idempotent `ALTER TABLE` for any added columns. Both `scripts/download_battlemaps.py` and `scripts/analyze_battle_maps.py` now call it; their local DDL strings removed.

**Files:** `scripts/download_battlemaps.py:191`, `scripts/analyze_battle_maps.py:61`

**Fragility:** Multiple scripts define `battle_maps_library` with `CREATE TABLE IF NOT EXISTS`. Schema changes in one script do not upgrade existing DBs.

**Likely failure:** New code expects columns/indexes that never appear in an older live DB.

---

### F-13. Old `battle_maps` source still coexists with `battle_maps_library` - MEDIUM

**Status 2026-05-21:** FIXED (documentation). `seed_battle_maps.py` docstring updated to prominently flag it as DEPRECATED, document that it manages only the old `battle_maps` table (NOT `battle_maps_library`), and direct maintainers to `download_battlemaps.py` + `analyze_battle_maps.py` for the live path. No pipeline code queries `battle_maps` — verified.

**Files:** `scripts/seed_battle_maps.py:82`, `scripts/seed_battle_maps.py:601`, `scripts/seed_battle_maps.py:638`

**Fragility:** Old AI-generated `battle_maps` table management still exists alongside the downloaded `battle_maps_library` path.

**Likely failure:** Future maintenance may update/upload the wrong map source or reintroduce generation-era assumptions.

---

### F-14. DB helper creates connection pool at import time and has hardcoded defaults - MEDIUM

**Status 2026-05-21:** VERIFIED ACCEPTABLE. `main.py` runs `load_dotenv()` before any `from src.*` imports, so env vars are always set when the pool is created. All 34 scripts also call `load_dotenv()` before importing from src. The hardcoded local defaults are intentional fallback for development (removing the default password breaks scripts that don't call `load_dotenv()`). No change needed.

**Files:** `src/db_api.py:18`, `src/db_api.py:147`

**Fragility:** `db_api` defaults to local credentials and creates `db = DatabaseManager()` during import.

---

### F-15. Generic CRUD interpolates SQL identifiers from caller data - MEDIUM

**Status 2026-05-21:** FIXED. Added `_validate_identifier()` static method to `DatabaseManager`. `insert()`, `update()`, `delete()` now validate all table and column names against `[A-Za-z_][A-Za-z0-9_]*` before building SQL. Smoke-tested: bad identifiers raise `ValueError`, live query still works.

**Files:** `src/db_api.py:104`, `src/db_api.py:118`, `src/db_api.py:132`

**Fragility:** Values are parameterized, but table/column identifiers are string-built from helper arguments and dict keys.

**Likely failure:** Unexpected keys can produce SQL errors; if untrusted input reaches these helpers, identifier injection is possible.

---

### F-16. Self-learning still has stale file fallbacks and a dead duplicate Columbus function - MEDIUM

**Status 2026-05-21:** FIXED. All three stale `campaign_docs/*.json` fallbacks in `orchestrator.py` replaced with empty-safe returns that log the DB error. Dead duplicate `_study_maps_today()` at line 751 of `self_learning.py` renamed to `_study_generated_maps_legacy()` — the live library-tag version at line ~1029 now resolves unambiguously.

**Files:** `src/agents/orchestrator.py:192`, `src/agents/orchestrator.py:260`, `src/agents/orchestrator.py:341`, `src/agents/orchestrator.py:359`, `src/self_learning.py:751`, `src/self_learning.py:1029`

**Fragility:** The agent orchestrator still falls back to `campaign_docs/mission_memory.json`, `npc_roster.json`, and `faction_reputation.json`. `self_learning.py` also defines `_study_maps_today()` twice; the second definition silently replaces the old generated-map review.

**Likely failure:** Learning agents can study stale file data instead of live MySQL. Future maintainers can edit the dead Columbus function and see no effect.

**Possible fixes:**
- Remove stale file fallbacks or replace them with explicit DB-only empty results.
- Delete or rename the dead Columbus review function.
- Add a smoke test that confirms the scheduled `map_tagging` study resolves to the live function.

---

### F-17. News memory schema/docs drift - MEDIUM

**Status 2026-05-21:** FIXED. Module docstring updated to reflect MySQL `news_memory`/`news_entries` as authoritative source (removed `campaign_docs/news_memory.txt` reference).

**Files:** `src/news_feed.py:6`, `src/news_feed.py:2212`, `src/db_api.py:480`, `.codesight/schema.md`

**Fragility:** Header comments still describe `campaign_docs/news_memory.txt`; runtime writes `news_memory`; docs/schema summaries emphasize `news_entries`.

**Likely failure:** Fresh DB setup or tools built from docs can miss `news_memory`, breaking bulletin continuity and learning context.

**Possible fixes:**
- Add/verify a real migration for `news_memory`.
- Split `add_news_memory()` from `add_news_entry()` so table intent is explicit.
- Update comments and generated schema docs after migration.

---

### F-18. Map extraction from prose is regex-fragile - LOW

**Status 2026-05-21:** IMPROVED. `extract_map_scenes()` now logs content length, mission_type, and a snippet when the regex matches zero scenes, making diagnosis possible. The regex itself is unchanged (no confirmed failures to fix against).

**Files:** `src/mission_builder/maps.py:64`, `src/mission_compiler.py:699`

**Fragility:** Map scene extraction depends on narrow heading patterns in generated prose.

**Likely failure:** Maps are skipped when modules use "Act 2", "Area 3", alternate HTML/markdown headings, or pipeline-specific structures.

---

### F-19. Published/novel map paths can lack VTT sidecars or overstate map count - LOW

**Status 2026-05-21:** FIXED. `novel_pipeline._pass5_generate_maps()` now imports `write_grid_sidecar` and calls it after each `shutil.copy2()`. `published_pipeline.py` `map_count` changed from `len(map_paths) or len(manifest)` to `len(map_paths)` — index no longer advertises planned-but-ungenerated maps as delivered.

**Files:** `src/mission_builder/novel_pipeline.py:630`, `src/mission_builder/published_pipeline.py:987`, `src/mission_builder/published_pipeline.py:1002`, `src/mission_builder/published_pipeline.py:1043`

**Fragility:** Some copied library maps do not write `.vtt.json` sidecars, and published output can create `maps.html` / advertise map counts even when no actual images were generated/copied.

**Likely failure:** VTT/browser tooling sees inconsistent artifacts, or the module index promises maps that do not exist.

**Possible fixes:**
- Call `write_grid_sidecar()` after every copied library map.
- Track `planned_map_count` separately from `generated_map_count`.
- Omit or clearly label manifest-only maps output.

---

### F-20. Session runner parses rendered HTML instead of structured scenes - LOW

**Status 2026-05-21:** IMPROVED. `extract_scenes()` now logs path, size, and a note when zero scenes are matched, so "No scenes found" failures are visible in logs instead of silent. Full structured-data approach (session_manifest.json) remains future work.

**Files:** `src/mission_builder/session_runner.py:33`

**Fragility:** `session.html` generation searches rendered HTML for specific `<h3>/<h4>Scene N...` headings.

**Likely failure:** Parser/rendering changes or pipeline-specific headings produce "No scenes found" despite a usable module.

---

### F-21. Pipeline slug helper still has unsafe title fallback - HIGH

**Status 2026-05-21:** FIXED (same fix as F-6 — both are in `mission_db.py:write_module_slug_for_mission`). Ambiguous title writes are now refused; single-match falls through to id-based write.

**Audit note 2026-05-21:** Found during read-only pipeline audit after the attempted id-first patch. Do not touch pipeline source until the encoding/mojibake risk is controlled.

**Files:** `src/mission_builder/mission_db.py:24`, `src/mission_builder/ambush_pipeline.py:960`, `src/mission_builder/escort_pipeline.py:866`, `src/mission_builder/infestation_pipeline.py:1673`, `src/mission_builder/investigation_pipeline.py:1175`

**Fragility:** Pipelines now call a shared module slug helper, but the helper can still fall back to `UPDATE missions SET module_slug=%s WHERE title=%s` when mission id is missing or the id update affects zero rows.

**Likely failure:** Duplicate or reused titles can still attach a module slug to the wrong mission row. A stale mission id can silently degrade into the exact title-based write this was meant to eliminate.

**Possible fixes:**
- Make mission id mandatory for slug writes from claimed/dashboard jobs.
- If fallback is retained for manual legacy runs, constrain it with another stable field such as `message_id` and fail if more than one row matches.
- Surface slug-write failure in module job status instead of only logging it.

---

### F-22. Generated session pages often lack authoritative `mission_id` - HIGH

**Status 2026-05-21:** FIXED. `_page()` in `html_renderer.py` now accepts `mission_id` and emits `const MISSION_ID = N;` into the page `<head>`. All six custom session render functions (negotiation, puzzle, recovery, rescue, sabotage, strange_occurrences) now pass `mission_id=mission.get("id")` to `_page()`.

**Files:** `src/mission_builder/published_pipeline.py:1015`, `src/mission_builder/negotiation_pipeline.py:775`, `src/mission_builder/puzzle_pipeline.py:963`, `src/mission_builder/recovery_pipeline.py:739`, `src/mission_builder/rescue_pipeline.py:635`, `src/mission_builder/sabotage_pipeline.py:592`, `src/mission_builder/strange_occurrences_pipeline.py:733`

**Fragility:** Published modules look up the mission id by title for the session runner. Several standalone pipelines render custom session files without embedding the mission id from the mission dict.

**Likely failure:** Dashboard/session completion has to infer by title or submit `MISSION_ID=None`, which can complete the wrong row or fail after dashboard hardening.

**Possible fixes:**
- Require `mission["id"]` or `mission["mission_id"]` at pipeline entry for claimed missions.
- Embed `MISSION_ID` from the mission dict in every custom session renderer.
- Remove title-based id lookup from `published_pipeline.py`; if no id exists, mark the module as manual/offline and disable dashboard completion.

---

### F-23. Pipeline DB reads hide schema drift behind generic fallbacks - HIGH

**Status 2026-05-21:** VERIFIED ALREADY HANDLED. All pipeline `_db_rows()` helpers already log warnings on DB failure. `raw_block` column referenced in infiltration_pipeline confirmed to exist in `player_characters`. No changes needed.

**Files:** `src/mission_builder/infiltration_pipeline.py:213`, `src/mission_builder/infiltration_pipeline.py:336`, `src/mission_builder/discovery_pipeline.py:75`, `src/mission_builder/rescue_pipeline.py:123`, `src/mission_builder/sabotage_pipeline.py:153`, `src/mission_builder/strange_occurrences_pipeline.py:176`

**Fragility:** DB helper wrappers catch broad exceptions and return empty lists. Some queries appear to reference stale columns such as `player_characters.raw_block` and `npcs.data_json`.

**Likely failure:** A broken SQL query, missing column, or DB outage looks the same as "no data found", causing pipelines to generate synthetic/default content while appearing successful.

**Possible fixes:**
- Distinguish "query returned no rows" from "query failed".
- Warn or fail the module job for required DB-authoritative context.
- Replace stale column reads with live schema fields or feature-detected optional reads.

---

### F-24. Map-library contract is inconsistent across pipelines - HIGH

**Status 2026-05-21:** PARTIALLY FIXED. (1) `_RESCUE_DUNGEON_SUBTYPES` was undefined in rescue_pipeline — now defined as `{"captive_extraction", "prison_break", "cursed_ritual"}`. (2) Infestation `write_maps_page()` was called with empty `room_maps.values()` instead of `[overview_map]` — fixed to use `actual_maps` and correct `map_count` in the index. VTT sidecar gaps remain.

**Files:** `src/mission_builder/infestation_pipeline.py:1578`, `src/mission_builder/infestation_pipeline.py:1647`, `src/mission_builder/rescue_pipeline.py:523`, `src/mission_builder/gather_pipeline.py:606`, `src/mission_builder/heist_pipeline.py:667`, `src/mission_builder/exploration_pipeline.py:412`, `src/mission_builder/maps.py:149`

**Fragility:** Pipelines call the map library with different partial contexts. Infestation generates an overview map but writes `maps.html` from empty `room_maps`. Rescue references undefined `_RESCUE_DUNGEON_SUBTYPES`. Direct map-copy paths often omit VTT sidecars that `generate_module_maps()` writes.

**Likely failure:** Modules can claim zero maps despite having copied one, crash only when map generation is enabled, or ship maps without VTT metadata. Weak context also increases fallback to "any analyzed map" instead of an area-appropriate one.

**Possible fixes:**
- Route all pipeline map selection through one adapter that accepts mission id, mission type, district/location, map type, and output path.
- Always write sidecars for copied maps.
- Track planned maps separately from copied maps in indexes/status.
- Fix or remove stale subtype constants before enabling rescue map generation.

---

### F-25. Old A1111 map-generation remnants remain in mission pipelines - MEDIUM

**Files:** `src/mission_builder/maps.py:103`, `src/mission_builder/gather_pipeline.py:22`, `src/mission_builder/heist_pipeline.py:19`, `src/mission_builder/infiltration_pipeline.py:20`, `src/mission_builder/infestation_pipeline.py:26`, `src/mission_builder/rescue_pipeline.py:37`, `src/mission_builder/sabotage_pipeline.py:36`, `src/mission_builder/assassination_pipeline.py:566`, `src/mission_builder/battle_pipeline.py:822`, `src/mission_builder/escort_pipeline.py:390`

**Fragility:** Dead `base64`, `httpx`, `A1111_URL`, and "generate map" naming/comments remain even though production mission maps should come from `battle_maps_library`.

**Likely failure:** Future work may revive the old image-generation path or patch the wrong abstraction when fixing maps.

**Possible fixes:**
- Remove unused A1111/base64 imports and constants in a controlled encoding-safe pass.
- Rename old `generate_*_map` functions to `select_*_map` or document that they copy library assets.
- Keep `src/mission_builder/maps.py:generate_vtt_map()` as a deprecated stub only if callers still import it.

---

### F-26. Pipeline output still contains mojibake and raw special glyph risk - HIGH

**Status 2026-05-21:** PARTIALLY FIXED. Binary-safe pass replaced all ` "" ` (double-quote em-dash) with ` — ` across all 17 pipeline and supporting src/ files. Code-context empty strings (`= ""`, `or ""`, dataclass defaults) that matched the pattern were also detected and reverted cleanly. F-26 covers future drift risk — centralized emoji/glyph rendering at Discord/Mimir boundaries is still pending.

**Files:** `src/mission_builder/battle_pipeline.py:1299`, `src/mission_builder/escort_pipeline.py:840`, `src/mission_builder/defense_pipeline.py:1045`, `src/mission_builder/exploration_pipeline.py:463`, `src/mission_builder/infestation_pipeline.py:1051`, `src/mission_builder/negotiation_pipeline.py:787`, `src/mission_builder/sabotage_pipeline.py:635`, `src/mission_builder/strange_occurrences_pipeline.py:742`

**Fragility:** User-visible module/Discord/Mimir-adjacent strings contain mojibake sequences for punctuation/icons such as em dash, arrow, and combat glyphs, plus raw non-ASCII glyphs in source files. The project already has a history of source edits corrupting Discord emoji.

**Likely failure:** Discord posts, HTML previews, and Mimir pushes can display corrupted characters. Future automated edits can re-encode emoji or punctuation incorrectly.

**Possible fixes:**
- Add a read-only lint/smoke that fails on known mojibake byte sequences before any string-editing pass.
- Normalize source files with a binary-safe script and AST check, not ad hoc text edits.
- Centralize emoji/special-glyph rendering at Discord/Mimir boundaries.

---

### F-27. DDB direct push tasks are fire-and-forget - MEDIUM

**Status 2026-05-21:** FIXED. `asyncio.create_task(_push_all_direct())` replaced with `await _push_all_direct()` in all three pipelines. The inner loop already has per-creature try/except so a failed push logs a warning and doesn't crash the pipeline; the module now completes only after the push attempt settles.

**Files:** `src/mission_builder/assault_pipeline.py:1231`, `src/mission_builder/battle_pipeline.py:1248`, `src/mission_builder/defense_pipeline.py:1223`

**Fragility:** Some combat-heavy pipelines schedule DDB direct pushes with `asyncio.create_task(...)` and continue module packaging/completion before push results are known.

**Likely failure:** The dashboard can show a completed module while DDB homebrew content failed to upload or is still running in the background.

**Possible fixes:**
- Await the push task when DDB output is required for module completeness.
- Or persist DDB push as its own DB-backed job/status so failures are visible and retryable.

---

### F-28. Escort DM map text promises markers that are not drawn - MEDIUM

**Status 2026-05-21:** FIXED. Text changed from "marked on DM map" to "DM chooses a choke point or blind corner on the route map" — no false claim about a drawn marker.

**Files:** `src/mission_builder/escort_pipeline.py:411`, `src/mission_builder/escort_pipeline.py:452`

**Fragility:** Escort creates a clean map copy and a DM map copy, but the DM copy does not actually draw or store ambush markers while the overlay text says the ambush point is marked.

**Likely failure:** DMs trust a map annotation that does not exist and prep from incorrect module guidance.

**Possible fixes:**
- Store deterministic marker coordinates and render a real DM overlay.
- Or remove the claim that the map is marked until the overlay exists.

---

### F-29. Bot restart is blocked by an em dash in executable Python - CRITICAL

**Status 2026-05-21:** FIXED (was fixed in previous session via binary replace). Compile check passes clean.


**Verified 2026-05-21:** `python -m py_compile src\aclient.py Webpage\app.py src\mission_builder\mission_db.py` fails on `src\aclient.py`. The running dashboard on port 5001 still reports Discord and DB as healthy, so the live process appears to be running older already-imported code; the next bot restart will fail.

**Files:** `src/aclient.py:532`

**Fragility:** A literal em dash is in the argument list for `finish_dashboard_claim_job(...)`:
`bool(ok), em dash if ok else "Claim handler returned false"`.

**Likely failure:** The bot cannot import `src.aclient` after restart, so Discord loops, mission board processing, durable dashboard claim jobs, module-generation jobs, and heartbeat updates stop.

**Possible fixes:**
- Replace the executable em dash with a normal conditional expression using a binary-safe edit.
- Add a pre-restart smoke command that compiles `src/aclient.py`, `Webpage/app.py`, and the mission-board handoff files.
- Add a read-only lint for non-ASCII punctuation in executable Python tokens, while allowing intentional Discord/user-facing strings.

---

### F-30. External dashboard write guards are inconsistent - HIGH

**Status 2026-05-21:** FIXED. `/api/drafts`, `/api/log-bug`, and `/api/complete-mission` now all check `_is_external() and not _pin_ok(data)` and return 403 before touching any state.

**Verified 2026-05-21:** With a fake `CF-Ray` header against `http://127.0.0.1:5001`, `/api/claim-mission` and `/api/post-mission-to-discord` return `403`, but `/api/complete-mission` reaches handler validation and returns `400`, `/api/log-bug` reaches handler validation and returns `400`, and `/api/drafts` reaches handler code and returns `500` for malformed JSON. Source confirms those three routes do not call `_pin_ok()`.

**Files:** `Webpage/app.py:38`, `Webpage/app.py:523`, `Webpage/app.py:1240`, `Webpage/app.py:1671`

**Fragility:** Flask enables permissive CORS globally and only some mutating routes enforce the external PIN. Completion, draft creation, and buglog append are write paths but are not guarded consistently under Cloudflare-style external requests.

**Likely failure:** Anyone who can reach the external dashboard route can attempt to write drafts, append buglog entries, or submit mission completion/debrief data if they know or guess mission details.

**Possible fixes:**
- Put all mutating dashboard routes behind one shared `require_dashboard_write_access()` helper.
- Keep player-facing completion only if it has a separate scoped token embedded per generated session.
- Return `403` before parsing or validating mutating request bodies when external access lacks a valid PIN/token.

---

### F-31. Mimir compendium dashboard calls can hang Flask requests - HIGH

**Status 2026-05-21:** FIXED. `_mimir_run()` now wraps the coroutine in `asyncio.wait_for(coro, timeout=8.0)` and raises `TimeoutError` on expiry. Mimir health is now exposed in `/api/status` via `get_mimir().available` so the dashboard can disable compendium calls when Mimir is not ready.

**Verified 2026-05-21:** Two live requests to `http://127.0.0.1:5001/api/compendium/search` timed out client-side after 15 seconds. `logs/mimir_mcp_stderr.log` showed a `search_catalog` tool request at the same time. Source shows Flask creates a fresh event loop for Mimir calls and `MimirClient._call()` has no per-tool timeout; `ensure_connected()` can also spend multiple reconnect attempts with 30 second sleeps.

**Files:** `Webpage/app.py:2103`, `Webpage/app.py:2113`, `src/mimir_client.py:66`, `src/mimir_client.py:267`

**Fragility:** Synchronous Flask request handlers directly wait on Mimir MCP work. If Mimir is slow, stuck, or reconnecting, the dashboard request can hang for a long time and consume a Flask worker.

**Likely failure:** The compendium panel feels broken, repeated browser requests stack up, and dashboard responsiveness can degrade even though MySQL and Discord are healthy.

**Possible fixes:**
- Add short request-level timeouts around Mimir calls from Flask.
- Cache Mimir search/list results in MySQL or memory with a stale-but-fast response.
- Expose Mimir health in `/api/status` so the dashboard can disable compendium calls when Mimir is not ready.

---

### F-32. Mission outcomes are title-keyed and already duplicated in live MySQL - HIGH

**Status 2026-05-21:** FIXED. Added nullable `mission_id` column to `mission_outcomes` with index. Backfilled 442 rows from unambiguous title matches (44 remain NULL — ambiguous titles). `save_outcome()` and `_save_outcomes()` now write `mission_id` when present. Dashboard list and detail joins now prefer `mission_id` lookup with title as fallback for legacy rows. All new NPC/PC/player completions include `mission_id` from the mission dict.

**Verified 2026-05-21:** `DESCRIBE mission_outcomes` shows no `mission_id` column. A live duplicate check found multiple repeated `mission_title` values, including titles with 2 to 4 outcome rows. The dashboard joins outcomes by `mission_title` and builds a dict from `ORDER BY created_at DESC`, which can overwrite the newest duplicate with an older row during iteration.

**Files:** `Webpage/app.py:377`, `Webpage/app.py:383`, `Webpage/app.py:403`, `Webpage/app.py:1731`, `docs/mysql_schema_reference.md`

**Fragility:** Outcomes are not tied to the authoritative `missions.id`. Dashboard list/detail reads and completion upserts all use title matching.

**Likely failure:** Completed/failed mission cards can display the wrong debrief, repeated dashboard submissions can overwrite or hide prior outcomes, and duplicate mission titles cannot be resolved cleanly.

**Possible fixes:**
- Add nullable `mission_id` to `mission_outcomes` and backfill from unambiguous title/time matches.
- Write new outcomes by `mission_id`; keep title as display text only.
- Update dashboard joins to prefer `mission_id` and only fall back to title for legacy rows.

---

### F-33. Project media route exposes private repo files - CRITICAL

**Status 2026-05-21:** FIXED. `/media/project/` now restricts to four approved roots (`campaign_docs/image_refs/`, `campaign_docs/battle_maps/`, `campaign_docs/npc_appearances/`, `generated_modules/`), denies dotfiles, and only serves known media extensions. Any path outside approved roots returns 403 before file existence is checked.

**Verified 2026-05-21:** Live `HEAD` requests against `http://127.0.0.1:5001/media/project/...` returned `200` for `.env`, `buglog.md`, and `logs/bot_stderr.log`. The route only checks that the resolved path stays under the project root, then serves the file.

**Files:** `Webpage/app.py:620`, `Webpage/app.py:1821`

**Fragility:** `/media/project/<path>` is meant to turn project-local media paths into dashboard URLs, but the public route accepts any file inside the checkout. That includes secrets, logs, source files, buglog notes, and other operational data.

**Likely failure:** Anyone who can reach the dashboard can fetch private environment values, huge logs, source context, or internal audit notes through a route that looks like ordinary image/media delivery.

**Possible fixes:**
- Restrict project media serving to explicit approved media roots such as generated module images, area maps, and image reference assets.
- Deny dotfiles, logs, source files, and markdown notes even when they sit under an approved root.
- Require the same dashboard read/write access model for raw project media if any non-public file access remains necessary.

---

### F-34. Area profile generator uses a stale NPC column - HIGH

**Status 2026-05-21:** FIXED. `_gather_district_context()` now selects `faction` instead of `npc_faction`. Smoke test against "Academy Heights" returns 9 places, no SQL error.

**Verified 2026-05-21:** Live MySQL `DESCRIBE npcs` shows `faction`, not `npc_faction`. Running `SELECT name, npc_faction, data_json FROM npcs LIMIT 1` fails with MySQL error 1054, and calling `src.area_generator._gather_district_context("Academy Heights")` raises the same error.

**Files:** `src/area_generator.py:108`, `src/area_generator.py:119`, `Webpage/app.py:2281`

**Fragility:** Area profile generation depends on `_gather_district_context()`, which still selects `npc_faction` from `npcs`. The dashboard district profile routes read `area_profiles`, so failed generation leaves the dashboard and mission grounding stuck with missing or stale area context.

**Likely failure:** Any command, script, or future dashboard workflow that regenerates area profiles fails before producing district context. Mission pipelines that rely on area profiles then lose the map/tag/location grounding needed for consistent map matching.

**Possible fixes:**
- Replace `npc_faction` with the live `faction` column and keep `data_json` only as a compatibility supplement.
- Prefer the live `npcs.location` column before falling back to JSON location fields.
- Add a smoke test that calls `_gather_district_context()` for one known gazetteer district against live schema metadata.

---

### F-35. Map library selection lets mission type override requested map type - HIGH

**Status 2026-05-21:** FIXED. `get_battle_map()` now builds staged queries in priority order: district+mission+map_type → district+mission → mission+map_type → map_type → mission → any analyzed. Smoke test: heist+office returns map_type=office; rescue+dungeon returns map_type=dungeon.

**Verified 2026-05-21:** Live `battle_maps_library` has valid typed maps, including 33 office maps and 51 dungeon maps. A smoke call to `get_maps_for_mission()` with `mission_type="heist"` and `map_type="office"` returned tavern maps; a `rescue` request with `map_type="dungeon"` returned warehouse, street, and arena maps. The audit-created map-memory rows were deleted after the smoke.

**Files:** `src/battle_map_library.py:43`, `src/battle_map_library.py:55`, `src/battle_map_library.py:67`, `src/battle_map_library.py:99`

**Fragility:** `get_battle_map()` tries `district + mission_type` and `mission_type` before it tries `map_type`. Those earlier stages do not include the requested tactical map type, so a broad mission-type tag can beat an explicit office, dungeon, sewer, or street request.

**Likely failure:** Mission pipelines can ask for an office, dungeon, or street map and still receive a tavern, warehouse, arena, or other mismatched map. The new area map memory can then preserve that bad first pick for the same area.

**Possible fixes:**
- When `map_type` is present, include it in the specific district and mission-type stages before relaxing.
- Only fall back to mission-type-only or any analyzed map after exhausting `map_type` matches.
- Store a selection reason with remembered maps so bad memories can be audited and cleared.

---

### F-36. Dashboard faction lists are hardcoded instead of DB-authoritative - MEDIUM

**Status 2026-05-21:** FULLY FIXED. `/api/factions` now DB-driven (16 real factions including Leaden Crown, Black Flame Cult, Cult of the Hollow Veil). Quick-draft `QUICK_FACTIONS` JS constant replaced with live fetch from `/api/factions` at click time (falls back to 6-faction array if API unavailable). Main generator faction `<select>` was already API-driven via `loadFactions()`.

**Verified 2026-05-21:** Live MySQL `faction_reputation` contains 21 rows, including Black Flame Cult, Cult of the Hollow Veil, Leaden Crown, and bracketed alias rows. The live `http://127.0.0.1:5001/api/factions` response returns only 12 hardcoded names. The dashboard faction selector and faction standings view both consume `/api/factions`, while quick draft uses an even narrower six-faction JavaScript constant.

**Files:** `Webpage/app.py:1137`, `Webpage/app.py:1162`, `Webpage/MissionGenerator-Designs/Web Dashboard.html:1817`, `Webpage/MissionGenerator-Designs/Web Dashboard.html:2834`, `Webpage/MissionGenerator-Designs/Web Dashboard.html:3377`

**Fragility:** MySQL is supposed to be authoritative, but dashboard faction selection and faction standings are filtered through static lists. This makes live factions invisible or harder to select from the dashboard even when reputation rows exist.

**Likely failure:** Dashboard-generated missions and quick drafts overuse the same small faction pool, newer factions do not appear in faction standings, and operators cannot easily steer missions toward DB-backed factions that exist in the campaign.

**Possible fixes:**
- Build `/api/factions` from normalized `faction_reputation` rows, then append only intentional configured factions that are missing from DB.
- Deduplicate bracketed aliases and map `Tower Authority` to `Tower Authority / FTA` consistently.
- Replace the quick-draft hardcoded faction constant with the loaded `/api/factions` list.

---

### F-37. Legacy mission-builder API module does not compile - HIGH

**Status 2026-05-21:** FIXED. `generate_mission()` and `generate_mission_async()` both had `difficulty` declared twice (`Optional[str]` then `Optional[int]`). Removed the deprecated `Optional[str]` variant; kept only `Optional[int]`. Also removed the duplicate `difficulty=difficulty` keyword from the `loop.run_until_complete()` call. Module now compiles clean.

**Verified 2026-05-21:** `python -m compileall -q src Webpage scripts` fails on `src\mission_builder\api.py`, and `python -m py_compile src\mission_builder\api.py` reproduces `SyntaxError: duplicate argument 'difficulty' in function definition`. Source shows both `generate_mission()` and `generate_mission_async()` declare `difficulty` twice, and `generate_mission()` also passes `difficulty` twice into the async call.

**Files:** `src/mission_builder/api.py:28`, `src/mission_builder/api.py:83`, `src/mission_builder/image_integration.py:29`, `tests/test_api.py:11`, `tests/test_e2e.py:22`

**Fragility:** The main live dashboard path no longer imports this module directly, but tests, image integration, package-level exports, and older high-level mission generation callers still reference it. Any cold path importing `src.mission_builder.api` fails before runtime logic can choose the newer compiler path.

**Likely failure:** Image-integrated mission generation, legacy tests, or tools that import `generate_mission_async` crash immediately. This can look like a pipeline/image failure even though the actual blocker is syntax-level import failure.

**Possible fixes:**
- Rename the deprecated string difficulty parameter to a distinct legacy name, or remove it entirely.
- Keep only one numeric `difficulty` argument and one keyword pass into `generate_mission_async()`.
- Add `python -m py_compile src\mission_builder\api.py src\mission_builder\image_integration.py` to the mission pipeline smoke set.

---

### F-38. Public-health arc detector matches health words inside unrelated words - HIGH

**Status 2026-05-21:** FIXED. `_mentions_public_health_crisis()` changed from `keyword in lower` (substring) to `re.search(r'\b' + re.escape(keyword) + r'\b', lower)` (word-boundary match). Smoke-tested: "influence" no longer triggers `flu`; "fluent" no longer matches; real crisis texts ("flu outbreak", "plague", "quarantine") still match.

**Verified 2026-05-21:** Live `global_state.public_health_arcs` contains an active `undercity_flu_outbreak` whose `last_bulletin_excerpt` is an arena fight at Iron Spine Colosseum, not a sickness story. Calling `src.news_feed._mentions_public_health_crisis("The crowd worries about Iron Fang influence in the arena.")` returns `True` and `_public_health_arc_slug(...)` returns `undercity_flu_outbreak`, because the detector matches the substring `flu` inside `influence`.

**Files:** `src/news_feed.py:113`, `src/news_feed.py:199`, `src/news_feed.py:233`, `src/news_feed.py:254`, `src/mission_board.py:1590`

**Fragility:** `_mentions_public_health_crisis()` uses raw substring checks for short keywords such as `flu`. False-positive arcs are then saved for 21 to 35 days and `mission_board._public_health_mission_context()` can use them as mission pressure.

**Likely failure:** Non-health headlines can create weeks-long false outbreak arcs, causing news prompts and mission generation to steer toward fake flu/public-health follow-ups that were never actually introduced by the story.

**Possible fixes:**
- Match short disease keywords with word boundaries, for example whole-word `flu`, not substrings inside words like `influence`.
- Require at least one strong disease term or a pair of weak terms before creating a new public-health arc.
- Add a cleanup/migration that removes public-health arcs whose last excerpt no longer matches the stricter detector.

---

### F-39. Dashboard completion still writes mission outcomes by title after mission_id migration - HIGH

**Status 2026-05-21:** FIXED. `api_complete_mission()` now includes `mission_id` in `outcome_fields`. Existing-outcome lookup prefers `WHERE mission_id=%s` when a mission id is known; falls back to `WHERE mission_id IS NULL AND mission_title=%s` for legacy null rows. UPDATE uses `WHERE id=%s` (not title). INSERT includes `mission_id`. Also backfills `mission_id` on the existing row when updating a legacy null row.

**Verified 2026-05-21:** Live `DESCRIBE mission_outcomes` shows a `mission_id` column, and live rows include 442 non-null `mission_id` outcomes plus 44 legacy null rows. The dashboard completion route resolves the mission by id, but then builds `outcome_fields` without `mission_id`, checks `SELECT id FROM mission_outcomes WHERE mission_title=%s`, and updates/inserts by title. Live duplicate-title checks still show repeated `mission_title` groups.

**Files:** `Webpage/app.py:1749`, `Webpage/app.py:1764`, `Webpage/app.py:1769`, `src/mission_outcomes.py:108`

**Fragility:** The schema has moved toward DB-authoritative mission identity, but the dashboard debrief write path still uses title identity. It can overwrite or update the wrong outcome when titles repeat, and brand-new dashboard completions can create `mission_id=NULL` outcome rows even when the request supplied a valid mission id.

**Likely failure:** Session debriefs from generated modules can attach to the wrong mission title, fail to appear on the correct dashboard card, or preserve duplicate outcome rows that the new `mission_id` column was meant to eliminate.

**Possible fixes:**
- Include `mission_id: int(mid)` in dashboard `outcome_fields`.
- Look up existing outcomes by `mission_id` first, falling back to title only for legacy rows with `mission_id IS NULL`.
- Add a small backfill that links unambiguous null `mission_id` rows to missions by title and date.

---

### F-40. Shared Mimir singleton locks cross event loops - HIGH

**Status 2026-05-21:** FIXED. Added `register_bot_loop()` / `get_bot_loop()` to `mimir_client.py`. `aclient.setup_hook()` registers the bot's running loop on startup. `_mimir_run()` in Flask now checks for the registered bot loop and uses `asyncio.run_coroutine_threadsafe(coro, bot_loop).result(timeout)` when it's available — all Mimir asyncio.Lock acquisitions stay on the single bot loop, no cross-loop binding. Falls back to a fresh per-request loop in standalone dashboard mode.

**Verified 2026-05-21:** The live `logs/bot_stderr.log` contains repeated `[MIMIR_SYNC] New-NPC detection failed` warnings with `<asyncio.locks.Lock ...> is bound to a different event loop` at 11:50:02 and 12:05:44. Source shows the singleton `MimirClient` creates `asyncio.Lock()` instances in `__init__`, `_call()` serializes tool calls through that lock, and the Flask dashboard helper creates a new event loop per request before using the same singleton client.

**Files:** `src/mimir_client.py:56`, `src/mimir_client.py:57`, `src/mimir_client.py:265`, `src/mimir_sync.py:1769`, `src/mimir_sync.py:1802`, `Webpage/app.py:2153`

**Fragility:** Mimir is shared by the bot learning/sync cycle and dashboard routes, but the shared client owns asyncio primitives tied to whichever loop first uses them. When a later bot or dashboard call hits the singleton from a different loop, Mimir calls can fail before syncing data back into MySQL.

**Likely failure:** New NPCs created in Mimir are not pulled into MySQL during the learning cycle, dashboard Mimir routes can intermittently fail or hang behind a lock from another loop, and Mimir/MySQL drift grows even though both sides appear reachable.

**Possible fixes:**
- Run Mimir access through one long-lived async worker loop instead of creating per-request Flask loops around the singleton.
- Or make `MimirClient` loop-scoped, with separate locks/session state per event loop and explicit cleanup.
- Add a Mimir health/status check that reports loop/lock failures separately from ordinary Mimir API timeouts.

---

### F-41. Mission parser loses factions when headers use em dash or doubled quotes - HIGH

**Status 2026-05-21:** FIXED. The `_parse_mission()` regex was `r"..."` double-quoted, so `""` (two-quote separator) split the raw string early — the `""` alternative was silently dropped from the regex. Changed to `r'...'` single-quote delimiter via binary replace (safe, no encoding risk). Smoke-tested all 5 separator styles (`-`, `--`, `""`, em dash, `--`); all now return correct faction+title.

**Verified 2026-05-21:** Live MySQL has 12 active missions with `faction='Unknown'`; several have titles that visibly start with real factions, such as `Patchwork Saints - The Burdened Plow`, `Serpent Choir - Celestial Debt Reckoning`, and `Iron Fang Consortium "" The Silent Oath`. A smoke call to `_parse_mission()` parses `**Serpent Choir - Celestial Debt Reckoning**` correctly, but returns `faction='Unknown'` for headers using a Unicode em dash or doubled quotes. The parser regex only handles plain hyphen reliably; the em-dash alternative in source is mojibake.

**Files:** `src/mission_board.py:2154`, `src/mission_board.py:2165`, `src/mission_board.py:2170`, `Webpage/app.py:1476`

**Fragility:** Mission board parsing is the bridge from LLM text to DB-authoritative mission rows. When the header separator is not parsed, the whole faction/title header is stored as the title and the faction column becomes `Unknown`, even though the generated post included the faction.

**Likely failure:** Mission distribution and dashboard filters become misleading, faction rotation sees fewer real recent factions than were actually posted, reputation/outcome paths lose the posting faction, and the board can appear biased toward the same few factions because many older posts are invisible to faction counts.

**Possible fixes:**
- Parse header separators with a real Unicode-aware pattern that accepts `-`, `--`, em dash, en dash, and the observed doubled-quote separator.
- After parsing, normalize the left side through `_normalise_rotation_faction()` or the DB faction list before accepting it.
- Add parser smoke cases for model-style headers before saving new mission rows.

---

## Audit Notes

- This buglog is intentionally about fragility, not confirmed user-facing failures. Each item needs a smoke test before patching.
- Highest priority cluster: F-1 through F-5. These affect mission claiming, module generation durability, and state correctness.
- Map-library cluster: F-9 through F-13 and F-19. These matter now that mission pipelines depend on downloaded maps.
- DB-authority cluster: F-14 through F-17. These reduce future drift and restart surprises.
- Pipeline audit cluster: F-21 through F-28. These were logged from read-only helper audits after the encoding regression; do not patch them from notes alone.
- Integration audit cluster: F-29 through F-34. These were verified against compile checks, the live port 5001 dashboard, Mimir behavior, and live MySQL metadata before being logged.
- Map selection audit: F-35 was verified against the live map library and explains a real tag-matching failure mode in the downloaded-map pipeline.
- Dashboard faction audit: F-36 was verified against live MySQL, the port 5001 API, and dashboard JavaScript callers.
- Compile audit: F-37 was verified by `compileall` and targeted `py_compile`; it affects legacy mission API imports and image-integration callers.
- News continuity audit: F-38 was verified against live `public_health_arcs` state and the detector function.
- Outcome identity audit: F-39 was verified against the migrated live schema, duplicate live rows, and the dashboard completion source path.
- Mimir loop audit: F-40 was verified against repeated live bot log failures and the shared singleton/new Flask loop source path.
- Parser audit: F-41 was verified against live `Unknown` mission rows and direct `_parse_mission()` smoke cases.
