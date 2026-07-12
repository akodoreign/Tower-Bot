# Database Incident Postmortem: `player_listings` Flood

**Generated:** 2026-05-23  
**Previous buglog archived:** `buglog_archive_20260523_pre_player_listings_db_incident.md`  
**Scope:** Emergency cleanup of `tower_bot.player_listings`, source audit for database patterns that can lock or flood MySQL, and follow-up risks.

## Executive Summary

The bot/database stall was caused by `player_listings` growing to **1,865,951 rows**, all closed rows with `status='sold'`. The live code had paths that loaded the entire table with `SELECT * FROM player_listings ORDER BY created_at DESC`, then filtered active rows in Python. Once the duplicate row flood reached millions of rows, those full-table reads became enough to freeze bot flows and lock up MySQL under concurrent diagnostics.

Cleanup was completed in small primary-key windows. Final verification:

```text
SELECT COUNT(*) FROM player_listings;
0
```

## What Happened

`src/player_listings.py` stored listing state twice:

- typed columns such as `id`, `status`, `item_name`, `asking_price`
- a full `listing_json` copy that also contains an `"id"` field

The dangerous failure mode was:

1. `create_listing()` built a temporary timestamp-style id such as `pl_...`.
2. `_save_listing()` inserted a new DB row and then updated the in-memory listing id to the actual DB id, `pl_<new_id>`.
3. The originally inserted `listing_json` still contained the old timestamp id.
4. Future `_load_listings()` calls loaded `listing_json`, saw the old id, and `_save_listing()` could not find the row by id.
5. The fallback lookup only matched active listings by player/item/status, so once a listing became `sold`, it no longer matched.
6. Each tick could reinsert the same sold listing as a new sold row.
7. Restart/diagnostic loops amplified this until the table contained 1.8M closed duplicates.

Claude appears to have patched part of this during diagnosis:

- `src/player_listings.py:160` now writes corrected `listing_json` after insert.
- `src/player_listings.py:223` adds `_load_active_listings()`.
- `src/player_listings.py:262` makes `tick_player_listings()` load active rows only.
- `src/player_listings.py:177` adds pruning for completed player listings.

Those changes address the main flood vector for future ticks.

## Cleanup Performed

Initial state from MySQL:

```text
player_listings total: 1,865,951
status distribution: sold = 1,865,951
```

The first attempt used 50,000-row chunks and was too aggressive while other sessions were scanning the same table. After reboot/recovery, cleanup switched to small id-window deletes:

```sql
DELETE FROM player_listings
WHERE id BETWEEN <lo> AND <hi>
  AND status = 'sold';
```

Each window was 1,000 ids with a short pause between statements. This finished safely without another lockup. Final state:

```text
player_listings total: 0
```

## Confirmed Code Risks

### 1. Player listing display/autocomplete still uses full-table load

Files:

- `src/player_listings.py:555`
- `src/cogs/economy.py:263`
- `src/cogs/economy.py:348`

`format_player_listings_embed()` still calls `_load_listings()` and filters active rows in Python. The `/bid` and `/buynow` autocomplete handlers also import `_load_listings()` and iterate it.

Risk: if `player_listings` grows again, dashboard/admin display or Discord autocomplete can trigger full-table reads. The tick loop is safer now, but these callers remain dangerous.

Recommended fix: make these callers use `_load_active_listings()` or a public `get_active_player_listings()` helper. Avoid exposing `_load_listings()` to command handlers.

### 2. `_load_listings()` remains an unbounded table read

File: `src/player_listings.py:87`

```sql
SELECT * FROM player_listings ORDER BY created_at DESC
```

Risk: any future import/caller can accidentally revive the same failure pattern.

Recommended fix: rename it to `_load_all_listings_for_maintenance()` or add a required `limit`/`status` argument. Default app paths should never call it.

### 3. Completed listing prune can still delete too much in one statement

File: `src/player_listings.py:177`

The new prune is good directionally, but this statement can still delete a large number of rows at once if a future flood occurs:

```sql
DELETE FROM player_listings
WHERE status IN ('sold', 'unsold', 'retired')
  AND created_at < DATE_SUB(NOW(), INTERVAL %s DAY)
```

Recommended fix: delete old completed rows in bounded id chunks, or limit each maintenance pass to a small number of rows.

### 4. Weekly archive reads entire closed tables

File: `src/weekly_archive.py`

Unbounded archive reads:

- `missions` at line 98
- `towerbay_auctions` at line 116
- `player_listings` at line 134
- `bounties` at line 152
- `missing_persons` at line 170
- `mission_outcomes` at line 187
- `npcs` graveyard at line 204
- `news_memory` snapshot at line 222

Risk: archive jobs can reproduce the same memory/lock behavior if any historical table grows large. The archive functions append records but do not delete archived DB rows, so repeat runs can keep rereading the same data.

Recommended fix: add batch pagination by primary key, archive markers, and `LIMIT`. For very large history tables, write one batch per run.

### 5. Main TowerBay AI listings use full-table reads

File: `src/tower_economy.py:440`

```sql
SELECT * FROM towerbay_auctions ORDER BY id
```

Risk: less urgent than `player_listings` because the AI shop is intended to stay small, but if a similar duplicate bug happens, tick and formatting paths will read all historical auctions.

Recommended fix: load active rows plus a bounded recent closed set only when needed. Archive/prune closed AI auctions.

### 6. Mission board loads all missions

File: `src/mission_board.py:295`

```sql
SELECT * FROM missions ORDER BY id
```

Risk: mission volume is probably much lower, but this is a shared hot path imported by the bot. If generated/expired missions accumulate, bot startup or claim logic can slow down.

Recommended fix: introduce status-scoped loaders such as `load_active_missions()`, `load_recent_resolved_missions(limit=...)`, and reserve full loads for maintenance.

### 7. `ORDER BY RAND()` appears in runtime code

Examples:

- `src\tower_economy.py:568`
- `src\tower_economy.py:576`
- `src\towerbot_world_shop.py:479`
- `src\mission_builder\heist_pipeline.py:415`
- `src\mission_builder\heist_pipeline.py:420`

Risk: `ORDER BY RAND()` sorts candidate rows and gets expensive as tables grow. It is probably fine for small NPC/item tables, but it is unsafe on tables that can become historical logs or shops.

Recommended fix: for larger tables, sample by indexed id ranges or preselect a bounded candidate set, then choose randomly in Python.

## Index Notes

Indexes currently present for the incident table:

```text
player_listings.PRIMARY: id
player_listings.idx_player: player_id
player_listings.idx_status: status
```

Helpful additional indexes:

```sql
CREATE INDEX idx_player_listings_status_created
ON player_listings (status, created_at, id);

CREATE INDEX idx_player_listings_active_lookup
ON player_listings (player_id, item_name, status);
```

The first supports active-listing and prune queries. The second supports `_save_listing()` fallback lookup.

## Immediate Recommendations

1. Replace all runtime `_load_listings()` callers with `_load_active_listings()`.
2. Make `_load_listings()` hard to call accidentally: require explicit `include_closed=True` or add a default `LIMIT`.
3. Change `_prune_completed_listings()` to chunked deletes.
4. Add the composite `player_listings(status, created_at, id)` index.
5. Add a guardrail metric: log a warning if `player_listings` exceeds 1,000 rows or closed rows exceed 500.
6. Batch `weekly_archive.py` before the next archive run.

## Operational Notes

During cleanup, concurrent long-running queries made the database look locked:

- full `SELECT * FROM player_listings ORDER BY created_at DESC`
- dump-like `SELECT /*!40001 SQL_NO_CACHE */ * FROM player_listings`
- grouped status/count scan

Future emergency cleanup should first check:

```sql
SHOW FULL PROCESSLIST;
```

Then avoid large `DELETE ... LIMIT 50000` cleanup passes while the bot or diagnostic tools are still doing full scans. The safe pattern is primary-key windows of 500-1,000 rows with short sleeps.

## Wider Bot DB Risk Audit

This section looks beyond `player_listings` for code that can create the same class of outage: unbounded table growth, duplicate inserts during retry/restart loops, full-table reads in hot paths, and missing idempotency at the database layer.

### A. Schema lacks uniqueness guardrails on most append-heavy tables

Confirmed unique constraints from MySQL:

```text
bulletin_cache: UNIQUE bulletin_id
dashboard_claim_jobs: UNIQUE mission_id
module_generation_jobs: UNIQUE mission_id
```

Notably absent from the checked high-traffic tables:

- `missions`
- `bounties`
- `towerbay_auctions`
- `player_listings`
- `news_memory`
- `towerbot_world_items`
- `character_snapshots`
- `mission_outcomes`

Risk: the Python code must be perfectly idempotent. If a stale JSON id, failed Discord post, restart burst, or retry loop replays an operation, MySQL will accept duplicates.

Recommended fix: add narrow natural-key or idempotency-key columns for each generated object. Examples:

- `missions`: `source_key` or unique `message_id` when present
- `bounties`: generated `bounty_key` or unique `message_id`
- `towerbay_auctions`: active uniqueness on item/source where practical
- `player_listings`: unique `listing_uuid`
- `news_memory`: optional `event_key` for cadence/system events
- `mission_outcomes`: unique `mission_id` where only one debrief is intended

### B. Bot startup can create rows repeatedly

File: `src/aclient.py`

Risk areas:

- `process_messages()` starts every background loop unconditionally at lines 131-146.
- `mission_board_loop()` runs a startup burst at lines 527-533.
- `post_mission()` inserts a mission after Discord send at `src/mission_board.py:3971-3973`.

If the service restarts repeatedly, startup behavior can generate and post missions repeatedly. The board cap limits active normal missions, but `_count_active_normal()` calls `_load_missions()` and scans all missions, and the cap does not protect every append table.

Recommended fix:

- Add a process-level guard so `process_messages()` cannot be started twice in one process.
- Persist a startup-burst marker by date/boot window in `global_state`.
- Give generated missions an idempotency key before posting.

### C. Mission board uses full mission-table reads in hot hourly paths

Files:

- `src/mission_board.py:295`
- `src/mission_board.py:437`
- `src/mission_board.py:2806`
- `src/mission_board.py:2950`
- `src/mission_board.py:3929-3935`
- `src/mission_board.py:4126`
- `src/aclient.py:577-579`
- `src/aclient.py:595`

Pattern:

```sql
SELECT * FROM missions ORDER BY id
```

This is used for counting active missions, NPC claims, NPC completions, personal rescissions, prompt context, and module-generation lookup. It is not currently huge, but it is the same architecture that broke `player_listings`.

Current exact count checked on 2026-05-23:

```text
missions: 725
```

Recommended fix:

- Replace `_count_active_normal()` with `SELECT COUNT(*) WHERE status='active' ...`.
- Replace hourly check loops with SQL-scoped loaders for only eligible statuses/date windows.
- For prompt context, load the latest N relevant missions instead of all missions.

### D. `_save_missions(missions)` can magnify stale-id bugs

File: `src/mission_board.py:343-427`

`_save_missions()` loops every mission and calls `_save_mission()`. `_save_mission()` updates if `mission["id"]` exists, otherwise inserts.

This is not confirmed broken today, but it is structurally similar to the old `player_listings` issue: if a mission object loses its DB id or is reconstructed from stale JSON without `id`, a bulk save can insert duplicates.

Recommended fix:

- Stop bulk-saving full mission lists after hourly state changes.
- Update only touched mission ids.
- Require `_save_mission()` to refuse inserts unless explicitly called as `insert=True`.

### E. Bounty board has duplicate-write risk around generated bounties

Files:

- `src/bounty_board.py:90`
- `src/bounty_board.py:100`
- `src/bounty_board.py:129`
- `src/bounty_board.py:274-276`
- `src/aclient.py:711-723`

`generate_bounty_post()` already saves the bounty at `src/bounty_board.py:274-276`. Then `mission_board_loop()` appends that same dict to `_load_bounties()` and calls `_save_bounties()` at `src/aclient.py:720-722`.

It probably avoids a duplicate because `generate_bounty_post()` sets `db_id`, but it does not set `id`; `_save_bounties()` only skips if `id` or `_saved` exists. This deserves a direct patch because the intent is fragile and one shape change can duplicate bounties weekly.

Recommended fix:

- Set `bounty_data["id"] = bounty_id` when saving.
- Remove the `_load_bounties()` + `_save_bounties()` append in `aclient.py`; it is redundant after `generate_bounty_post()` persists the bounty.
- Add a unique generated `bounty_key`.

### F. TowerBot world shop deliberately clones rows

File: `src/towerbot_world_shop.py:365-389`

`_clone_existing_stock_to_target()` clones active stock rows into new DB rows whenever Mimir has too few unique rows or is unavailable.

This may be intentional for shelf-fill behavior, but it means a persistent Mimir outage can create repeated active duplicates over time, especially because `_existing_names()` includes `sold` forever and `restock_world_shop()` retires active rows randomly before filling.

Current exact count checked on 2026-05-23:

```text
towerbot_world_items: 122
```

Recommended fix:

- Track clone lineage and cap clones per source item.
- Prefer reactivating retired rows over inserting new cloned rows.
- Add a daily insert cap and log when fallback cloning is used.

### G. News memory and bulletin cache grow without a hard DB retention policy

Files:

- `src/news_feed.py:2212`
- `src/db_api.py:521`
- `src/expandable_bulletin.py:95`
- `src/expandable_bulletin.py:309`

`news_memory` is append-only for bulletin facts. Current exact count:

```text
news_memory: 1663
bulletin_cache: ~2033 estimated
```

`bulletin_cache` has a unique key and a cleanup loop, which is good. `news_memory` has no uniqueness/idempotency key and no hard retention. Weekly archive snapshots it but does not prune it.

Recommended fix:

- Keep `news_memory` bounded by age or max rows after archive.
- Add event keys for deterministic cadence entries like `[TIA market ticker posted]`.
- Consider compressing old facts into weekly summaries.

### H. Character snapshots are append-heavy but currently bounded

Files:

- `src/character_monitor.py:97-103`
- `src/db_api.py:1424`
- `src/db_api.py:1452`

Every detected character change inserts a `character_snapshots` row, then cleanup keeps the last 5 per character. Current exact count:

```text
character_snapshots: 30
```

Risk is low today. The main issue would be cleanup failure: inserts would continue and the self-healing monitor restarts forever after crashes.

Recommended fix:

- Log cleanup failures distinctly.
- Add an index on `(char_id, fetched_at, id)` if absent.
- Consider a scheduled DB-level cleanup job as a second line of defense.

### I. Job queue retry model can re-run failed work indefinitely by manual requeue

Files:

- `src/db_api.py:1256-1292`
- `src/db_api.py:1295-1320`
- `src/aclient.py:548-623`

Good news: dashboard/module queues use unique `mission_id`, atomic-ish claiming, and stale processing reset. This is much safer than list-in-JSON queues.

Remaining risk:

- `enqueue_module_generation_job()` resets any non-done job to queued on duplicate enqueue.
- `_claim_next_job()` increments `attempts`, but there is no max-attempt dead-letter check.

Recommended fix:

- Add `WHERE attempts < max_attempts` to claims.
- Mark jobs `dead` or `needs_manual_review` after repeated failures.
- Do not reset failed jobs to queued without an explicit user action.

### J. Cadence tick functions mutate DB every news cycle, even when not posting

Files:

- `src/news_feed.py:1095`
- `src/news_feed.py:1170`
- `src/news_feed.py:1205`
- `src/news_feed.py:1234`

TowerBay, EC exchange, TIA, and weather all mutate state on each bulletin cycle even if they do not post a bulletin. This is not automatically bad, but it means any restart loop or duplicated news loop can multiply DB writes and state transitions.

Recommended fix:

- Add per-tick idempotency guards keyed by hour/cycle.
- Store last successful tick timestamps per subsystem.
- Make startup catch-up explicit instead of relying on immediate repeated loop calls.

### K. InnoDB table statistics are stale after emergency delete

Exact row count:

```text
player_listings COUNT(*): 0
```

InnoDB estimate:

```text
information_schema.tables.TABLE_ROWS: 1255968
```

This is not live data, but the optimizer can make worse choices with stale stats.

Recommended fix when the bot is quiet:

```sql
ANALYZE TABLE player_listings;
```

## Highest Priority Fix List

1. Replace all runtime `_load_listings()` and `_load_missions()` full-table reads with scoped SQL loaders.
2. Add idempotency keys/unique constraints to generated rows.
3. Stop bulk-save patterns that re-save entire loaded lists.
4. Patch bounty double-save fragility.
5. Batch and prune weekly archives.
6. Add max attempts/dead-letter behavior to durable job queues.
7. Add DB row-count guardrails and warnings for append-heavy tables.

## Fixes Applied 2026-05-23

- `src/player_listings.py`: active listing paths now normalize loaded JSON back to the real DB id, bid/buy-now load one active listing by id, display uses active-only rows, and completed-row pruning uses bounded chunks.
- `src/cogs/economy.py`: `/bid` and `/buynow` autocomplete now use active player listings instead of scanning all player listings.
- `src/bounty_board.py` and `src/aclient.py`: generated bounties now carry the DB id as `id`, and the mission loop no longer re-loads/re-saves the whole bounty list after generation.
- `src/db_api.py`: dashboard/module job queues now preserve failed jobs on duplicate enqueue and stop claiming jobs after bounded attempts.
- `src/mission_board.py` and `src/aclient.py`: module-generation lookup now loads one mission by id, and active mission counts use SQL count queries before falling back to the legacy full load.
- `src/weekly_archive.py`: archive routines now page through DB rows in primary-key batches instead of issuing one unbounded `SELECT *` per table.


## Saturday module review fixes 2026-05-29

Reviewed the 4 modules generated 2026-05-24 (ids 1157, 1158, 1088, 1079) and fixed the
pipelines that produced them. Each fix was smoke-tested; all 5 edited files AST + import clean.

### Exploration pipeline (1079 Obsidian Lotus) - src/mission_builder/exploration_pipeline.py
- canon leak: `_mission_context` extracted capitalized words from metadata fields, so
  faction="Unknown", "Type", "Tier" leaked into briefing/endpoint prose. Now excludes
  metadata field values + a stopword set from canon_terms.
- repetition: `_fallback_plan` route_log emitted 6 identical survey points (same read-aloud,
  same dm-note). Now 6 distinct points (named zones, distinct read-alouds, non-colliding
  changes via random.sample). endpoint_revelation reworded to use the area name, not a
  comma-joined dump of title fragments.
- Note: the fallback fires whenever Ollama is deferred by the resource cop or returns nothing
  (common during big batches), which is why every exploration module looked static. Fallback
  is now genuinely varied/runnable; making the LLM path run under load is a separate follow-up.

### Battle pipeline (1157, 1158 Reckonings) - src/mission_builder/battle_pipeline.py
- same-location repetition: every pocket fight described "the central plaza of X". Each fight
  now gets a distinct zone fed into the prompt + fallbacks.
- hazard repetition: small local model echoed "unstable ground/void energy" across fights.
  Added BATTLE_FALLBACK_HAZARDS (mechanically distinct), steer the prompt per fight, and a
  cross-fight dedupe pass that swaps repeats for an unused hazard.
- CR swing: `_pick_void_creatures` returned bosses unsorted (13/13/9). Now sorted ascending
  so boss CR escalates with the ramping grunt counts (added `_cr_sort_key`).
- footer count: void/breakout boss was shown as "boss x14" (grunt count). Now x1 for single
  statted bosses.

### Mimir reference footer (shared) - src/mission_builder/mimir_module.py
- Encounter Monsters block showed "Construct Spirit xN" with blank CR/HP/AC: the renderer
  preferred the fuzzy Mimir catalog match over our DB-backed entry. `render_mimir_section`
  now prefers the entry's authoritative name/cr/hp/ac (mission_enemy_entry), using catalog
  data only to fill gaps; gate also accepts entries that carry their own stats. Benefits
  battle + defense + any pipeline using mission_enemy_entry.

### Map size guard (shared) - src/battle_map_library.py
- 1157 shipped a 442x665 thumbnail as its battle map. Added `_map_too_small` (header-only,
  fails open) in `copy_library_map_for_mission`; undersized maps are rejected, marked stale,
  and the next candidate is tried. Verified: rejects 442x665, accepts 2100x2100.

### Title mojibake (source + data) - src/mission_board.py
- Generator emits an em-dash between faction and title as two straight double-quotes; for
  ids 1078-1081 it survived into the stored title ('Faction "" Subtitle'). `_parse_mission`
  now normalizes any surviving double-quote artifact to a real em-dash (U+2014, written as a
  literal verified 0x2014). Repaired the 4 stored rows (title column + mission_json.title).

### Defense pipeline (1088) - no change
- Confirmed sound: uses mission_enemy_entry (DB-backed) and the shared map layer, so it
  inherits the footer + map-guard fixes. It was the most solid of the four.

### Gather pipeline (1095 Echoes of the Accursed) - src/mission_builder/gather_pipeline.py
- The gather phase emitted one identical "Gather Attempt" card per stock unit (10 clones,
  all "Religion DC 15 | Nature DC 17 | +1/-1"). Tedious and the "super bad" part; Scene 1
  prose and the between-check encounters were already good.
- Added GATHER_SPOTS (12 distinct micro-spots, several with a small mechanical wrinkle) and
  assign one per attempt via random.sample, so the gather sequence reads as varied spots
  instead of a wall of identical boxes. Verified: 10 attempts get 10 distinct spots.
- Enriched the flat Scene 2 fallback ("...items should be here somewhere") used when the
  LLM location description is empty.

## Meaningful dialog across all pipelines 2026-05-29

Diagnosis: the rich dialog generator (scene_dialogs.py) was only wired into
published_pipeline. Confirmed empirically that extract_scenes_from_html found 0
scenes in every bespoke module (battle/defense/exploration/gather) because it only
matches the published "<h3>Scene N" markup. So bespoke modules shipped with flat
faceless one-liners (exploration) or no dialog at all (battle/defense). Gather Scene 1
was the exception (its own named-contact scene), which is the quality bar to hit.

Fix (named-NPC dialog for ALL pipelines, via the dispatcher, layout-safe):
- src/mission_builder/scene_dialogs.py: added a module-level dialog system -
  _npc_context (looks up the mission's contact NPC name/role/quote + opposing faction
  from the DB), _build_module_dialog_prompt (voices a NAMED speaker, ties responses to
  stakes), _fallback_module_dialog (deterministic 10-trigger NPC-voiced set so dialog
  still appears when the resource cop defers Ollama under batch load),
  _render_dialog_inline (self-contained INLINE styles so it renders regardless of which
  pipeline's CSS is present and does not disturb bespoke grids), and inject_module_dialog
  (idempotent public entrypoint: skips modules that already have a per-scene dialog-block,
  inserts a "Table Talk -- Dialog & NPC Reactions" section before the Mimir footer / </body>).
- src/mission_builder/__init__.py: generate_module now calls inject_module_dialog on the
  built module.html for EVERY routed pipeline (non-fatal on error). One chokepoint covers
  all ~18 pipelines without editing each (respects pipeline independence).

Validated on the 4 real Saturday bespoke modules: section injected, voiced with the real
contact (Snake-Eyes Snigar where present), idempotent (no double-inject on re-run), HTML
stays valid. Published-format modules are correctly skipped (no duplicate dialog).

Scope note: this is one rich module-level Table Talk section per module (12 player
triggers + NPC reactions, visual clues, leaving-the-scene), not a per-scene re-cut into
each bespoke layout. Published keeps its per-scene dialog. Per-scene granularity for the
bespoke layouts (extending extract_scenes_from_html to each layout's markup) is a deeper
follow-up.

## NPC description + motivation in mission modules 2026-05-29

Scope: mission generation only. NPCs already carry descriptions everywhere else;
the generated modules just never surfaced them. The NPC knowledge cards (used only
by published_pipeline) showed Knows/May-know/Won't-say/Tone/Voice but NOT a general
description and NOT an explicit motivation.

Fix - src/mission_builder/npc_knowledge_cards.py:
- _lookup_npc now also selects data_json and pulls the general description from
  data_json.appearance (the same description shown on every other surface).
- _card_html now renders a "Description" row (who they are) and a "Motivation" row
  (why they care) at the top of each NPC card.
- New build_module_npc_cards(module_html, mission): builds cards for the mission
  contact (name cleaned of trailing ", Location" / " - role") plus any roster NPC
  named in the module HTML; capped at 6.

Fix - src/mission_builder/__init__.py:
- generate_module now injects the NPC knowledge cards into module.html for EVERY
  routed pipeline (after the dialog section), before the Mimir footer / </body>.
  Idempotent: skips modules that already contain "NPC Knowledge Reference"
  (published_pipeline) so nothing is doubled. Non-fatal on failure.

Validated on the real Saturday modules: contact + module-named roster NPCs resolve to
rich cards showing real Description (e.g. Snake-Eyes Snigar's serpent tattoos / yellow
eyes) and Motivation (e.g. "Unfinished business from before death. Driven by regret.").
Full end-to-end (dialog + NPC cards): both inject once, idempotent on re-run, HTML valid.

## Contextual skill-check setup + success/fail narration 2026-05-29

Skill checks were bare mechanics (e.g. gather "Religion DC 15 | +1 item / -1 stock",
exploration "Survival DC 14 | On Failure: route unstable") with no narration of what
the attempt looks like or what success/failure feels like at the table.

Part A - universal Skill Check Cues block (all pipelines, via dispatcher):
- src/mission_builder/scene_dialogs.py: _detect_skill_checks (scans the module text for
  18 skills + DCs with a context snippet), _SKILL_CUE deterministic per-skill narration,
  _build_skill_cues_prompt / _render_skill_cues, and inject_skill_check_cues (LLM-refined
  setup/success/failure with deterministic backfill; idempotent inline-styled block).
- src/mission_builder/__init__.py: generate_module now injects the Skill Check Cues block
  for every routed pipeline (after dialog + NPC cards). Validated: gather 8 checks,
  exploration 2, defense 8; battle 0 (no skill checks -> no block); idempotent; valid HTML.

Part B - inline Setup/Success/Failure in the check-heavy pipelines:
- gather_pipeline.py: each Gather Attempt card now carries item-aware Setup + varied
  Success/Failure narration (_GATHER_RESULTS cycled), on top of the mechanical +1/-1.
- exploration_pipeline.py: each survey point now has a Setup line and an On Success cell
  beside On Failure; 6 distinct setups + successes in the fallback, plus setup/success keys
  added to the LLM route_log spec (fallback backfills when the model omits them).

Scope note: inline narration done for gather + exploration (the two flagged pipelines).
Defense and the other check pipelines (puzzle, investigation, infiltration, recovery,
discovery) are covered by the universal Skill Check Cues block; per-pipeline inline for
those is a straightforward follow-up.

## Skill-check inline narration sweep + rogue execution layers 2026-05-29

Extended inline skill-check setup/success/failure across the check-driven pipelines.

Narration added to existing checks (Setup + On Success + On Failure surfaced inline):
- investigation_pipeline: clue web (Setup + On Success from proves + On Failure).
- rescue_pipeline: scene skill checks (Setup + On Success + On Failure from consequence).
- discovery_pipeline: identification steps gained a Setup column (already had success/failure).
- strange_occurrences_pipeline: evidence lanes gained Setup + relabelled clue=On Success, if_failed=On Failure.
- defense_pipeline: upgrade build checks gained an explicit On Failure (already had action=setup, If successful=success).
- puzzle_pipeline: research routes gained Setup + On Success (clue) + On Failure.
- negotiation_pipeline: leverage research table gained Setup + relabelled result=On Success, risk=On Failure.

Rogue execution layers ADDED where the pipeline rendered ZERO skill checks (the real gap):
heist, infiltration, sabotage were clock/track/scene-driven with no checks at all -- wrong for
the lockpicking/stealth fantasy. Each now has a 6-phase execution table (local _execution_checks
/_approach_checks + table render, DCs scaled to party avg level), rogue-leaning:
- heist: Stealth -> Thieves' Tools/Arcana -> Sleight of Hand/Thieves' Tools -> Sleight of Hand
  -> Deception -> Stealth/Athletics, each with setup + success + failure.
- infiltration: Stealth -> Deception -> Insight/Perception -> Thieves' Tools/Sleight of Hand
  -> Stealth -> Stealth/Deception; failures advance the alert track.
- sabotage: Stealth -> Thieves' Tools/Sleight of Hand -> Sleight of Hand -> Sleight of Hand/Deception
  -> Stealth/Athletics -> Dexterity(Initiative)/Acrobatics; failures feed progress/heat.

All 10 pipelines AST + import clean; execution layers smoke-tested (rogue skills, scaled DCs,
full setup/success/failure present). Combat pipelines (battle/assault/ambush/assassination) and
escort/first_contact/infestation remain prose/combat-driven; the universal Skill Check Cues block
still covers any checks they render.

## Party-support + Ocean's-Eleven caper layer (rogue pipelines) 2026-05-29

Added party-collaboration content to the rogue pipelines (D&D 5.5e / 2024 accurate, rules
verified against the 2024 PHB -- notably the Help action's Assist-an-Ability-Check now
REQUIRES the helper to be proficient in the same skill/tool).

Crew Support (heist, infiltration, sabotage): a "How the Rest of the Party Helps" section
with 6 options spanning ~8 classes -- Bardic Inspiration, Guidance (+1d4), Pass Without Trace
(+10 Stealth), Silence/Knock/Minor Illusion, Subtle Spell + Mage Hand/Charm Person, and the
Help action / staged diversions. Each cites accurate level, action, and effect.

Infiltration -> full Ocean's-Eleven caper (contextual to the mission's site/objective/mark):
- "The Play - Run It in Three Acts": Case & Plant -> The Switch (misdirection) -> The Getaway,
  plus a Complication beat and an optional high-level Twist (Seeming/Mislead). All text is woven
  with the actual site, objective, and opposing faction.
- "The Crew - Assign the Jobs": 8 Ocean's-Eleven roles (Mastermind, Face, Ghost, Box-Man,
  Wardbreaker, Showman, Eye-in-the-Sky, Muscle/Driver). Each is a REAL skill check with
  MULTIPLE skill options, a scaled DC, and Setup / On Success / On Failure, tied to this mark,
  plus a class-accurate Signature move (Detect/Dispel Magic, Message, Find Familiar, Clairvoyance,
  Disguise Self, Suggestion, etc.).

Validated: 8 jobs each multi-skill + setup/success/failure + DC; site/objective/mark present in
jobs and Play; class spread 9 classes. heist/infiltration/sabotage AST + import clean.

## Infiltration made scenic + cult variant 2026-05-29

Feedback: the infiltration additions were mechanically correct but robotic -- generic
"the site / the objective / the mark" with a faceless faction "contact". Rebuilt the
premise as an actual occasion.

src/mission_builder/infiltration_pipeline.py:
- INFILTRATION_EVENTS: concrete occasions (Masquerade Ball, Charity Gala/Auction, Art
  Unveiling, Investiture, Opera Premiere, Guild Banquet, High Wedding, Collectors' Exhibition)
  plus TWO cult occasions (Rite of Induction indoctrination ceremony, Vigil of the Faithful),
  each with dress code, weapon rule, and what access it grants.
- venue_kind drives the venue: society events pull high-wealth halls/galleries/manors;
  cult rites pull shrines/temples/undercrofts/crypts (VENUE_KINDS). _pick_location is now
  event-aware and wealth-biased per kind.
- Targets: item pool (jade falcon, signet, ledger...), intel pool (vault rotation, a heist
  floor plan -> seeds a follow-up heist), and a cult-specific pool (the rite's true purpose,
  the celebrant's identity, who really pulls the strings).
- _pick_contact: a NAMED handler from the hiring faction (prefers liaison/fixer/agent roles)
  delivers the briefing.
- _scenario assembles event + venue + district + date (within a week) + dress + weapons +
  target + named contact. _generate_briefing now feeds all of it to the model and, on
  fallback, produces a dynamic in-character handler speech ("The Grand Masquerade Ball at the
  Aurelian Hall, Gilded Tier -- 4 nights from tonight. I've gotten you all in. Dress the
  part... find X... gone before the last toast.").
- Module renders a "The Job - <contact> Briefs the Crew" card (voiced quote + an Occasion/
  Venue/When/Dress/Weapons/Looking-for/Contact/Host facts table). The Play and The Crew now
  key off the real event target/venue/host instead of placeholders.

Smoke-tested: society and cult scenarios both produce specific, voiced briefings; cult uses
robes/surrendered-focus rules and shrine venues; AST + import clean.

## Recon-chain + scenic cards for heist & assassination 2026-05-29

The chain: an infiltration scouts a target (floor plan, ward layout, guard rotation, the prize)
and that intel should drive the follow-up heist/assassination. Turned the gathered data into
mission cards for both pipelines and made them read as scenes.

heist_pipeline.py:
- Recon dossier (HEIST_PRIZE_SPOTS / LAYOUT / MUNDANE_SEC / ARCANE_SEC / BLIND_WINDOW / ENTRY /
  EXIT / RECON_GAPS) + _recon_dossier() builds the gathered intel (prize, where it's kept,
  layout, mundane + arcane security, blind window, best entry/exit, and what recon could NOT
  confirm), scaled to party.
- _heist_contact(): a NAMED fence/handler from the sponsor faction; _heist_brief(): a voiced
  in-character contract briefing naming the score, location, owner, and window.
- Render adds "The Contract - <fence> Lays Out the Score" (voiced) and "Recon Dossier - What
  the Scouting Turned Up" (facts table) before the casing -- so casing questions are largely
  pre-answered and the table plans the execution.

assassination_pipeline.py:
- Added the missing execution spine: _assassination_methods() + _method_table() -> a "Method
  Options - How the Hit Goes Down" card with 5 methods (Poison, Blade in the Dark, Staged
  Accident, Ranged Shot, Arcane), each a skill check with MULTIPLE skill options, a scaled DC,
  and setup/success/failure. 5.5e accurate (Constitution save vs poison, Advantage/Sneak Attack
  from hidden, Subtle Spell removes verbal/somatic tells).
- Sits alongside the existing LLM Approach Options, the routine/surveillance (which already act
  as the mark's recon dossier), and exfiltration.

Smoke-tested: heist recon+contract populate and the fence is a real NPC; assassination methods
are multi-skill with setup/success/failure and render the accurate rules. Both AST + import clean.

Follow-up (not done): literal mission-linking -- storing a specific infiltration's scouted data
and loading it when its follow-up heist is generated -- would make the hand-off concrete rather
than inferred. The recon dossier currently reconstructs that intel.

## Recon repository: infiltration results -> heist/assassination building blocks 2026-05-29

Persistence so the mission chain is real, not inferred. NPC (and player) parties running
infiltrations now build a repository of recon dossiers that follow-up jobs consume.

DB (MySQL, per project rules): new table recon_dossiers (real columns for the queried fields
-- host_faction, district, target_kind, outcome, consumed_by_mission_id -- plus dossier_json
for the schemaless scouted detail). Indexed on host/district/outcome/consumed/kind.

src/db_api.py helpers: ensure_recon_table, record_recon_dossier, set_recon_outcome,
record_recon_outcome_for_mission (upsert by mission_id), find_recon_for_followup (returns the
most recent UNCONSUMED success/partial dossier, host-faction match first then district),
mark_recon_consumed.

Write path:
- infiltration build records a rich 'scouted' dossier (event/venue/district/host/hiring/target
  + full scenario in dossier_json), outcome derived from mission status.
- NPC resolution hook (src/mission_board.py, both complete and fail branches): when an
  infiltration-type mission resolves, upsert the dossier outcome to success/failure with the
  party name and the posted notice as details -- this is the repo that fills "pretty quick" as
  NPC parties pull infiltrations.

Read path:
- heist build: find_recon_for_followup(host=target_owner, district) -> passes prior_recon to
  render; the Recon Dossier card shows a provenance banner ("Built on prior recon: <party>
  scouted <venue> during <event> (success/partial/failure)...") and seeds the score from the
  scouted target; marks the dossier consumed.
- assassination build: same lookup by the mark's faction -> a provenance banner above the
  Contract Briefing, with the outcome shading how trustworthy the intel is; marks consumed.

Tested end to end: record -> heist/assassination find usable (success/partial only) -> dossier
carried -> consume (one-shot) -> upsert-on-resolution. All 5 files AST + import clean.

Follow-up: outcomes 'partial' and richer scouted detail at resolution are supported but the NPC
hook currently records success/failure only; a 'partial' path could be added from mission flavor.

## Infiltration spawns its follow-up heist (hard parent link) 2026-05-29

Closed the loop: a successful infiltration that cased a steal-able score now SPAWNS its
follow-up heist on the board, carrying the recon dossier id forward as a hard link.

- src/db_api.py: get_recon_by_id(dossier_id) loads a specific dossier (ignores consumed flag --
  the spawned follow-up owns it).
- src/mission_board.py: _spawn_followup_heist(source_mission, dossier_id, party_name) inserts a
  new status='active' Heist via create_mission, with mission_json carrying type=Heist,
  faction=hiring, opposing_faction=host, body referencing the scout, parent_recon_id, and
  parent_mission_id. It only fires for heist-worthy scouts (target_kind item, or intel mentioning
  heist/vault/floor plan/prize/shipment/ledger/relic) -- cult vigils etc. don't spawn. The dossier
  is reserved (mark_recon_consumed with the new heist id) so no other job grabs it.
- NPC success hook calls _spawn_followup_heist right after recording the recon success.
- heist + assassination builds now prefer an explicit mission.parent_recon_id (get_recon_by_id),
  falling back to the generic find_recon_for_followup; both render the provenance banner.

Tested full cycle: scouted dossier -> NPC success upsert -> spawned 'The Jade Falcon Job'
(active, parent_recon_id set) -> dossier reserved (generic find returns none) -> heist loads the
exact dossier by id. All 4 files AST + import clean.

Follow-up: assassination spawning (person/identity intel -> spawn an Assassination instead of a
Heist) is an easy extension of _spawn_followup_heist; currently only heists spawn.

## Assassination targets baked in + faction-leader rule + lifecycle injury 2026-05-29

Assassination missions now carry an opposed NPC target, with consequences.

- src/mission_board.py _bake_assassination_target(mission): at generation (called from
  post_mission before the embed, and idempotently in _save_mission) an assassination mission
  gets target_npc_name. Prefers a real NPC from the opposing faction (target_is_real=True);
  if none, invents a name (_random_target_name, target_is_real=False). If the NPC is a faction
  LEADER (npc_lifecycle.is_faction_leader), difficulty jumps to 10 and tier -> high-stakes.
- NPC claim roll: success chance is 0.01 for a faction-leader target, else 0.80.
- NPC completion (success): a real-NPC target is injured via
  npc_lifecycle.injure_npc_by_name(name) -- sets status='injured' + history; the normal
  lifecycle tick then resolves recovery (~90%) or death/graveyard (~10%). Invented-name targets
  are not real NPCs, so no lifecycle change.
- src/npc_lifecycle.py injure_npc_by_name(name, cause): mirrors the wave-injury code
  (status=injured, last_event_at, _hist, _save_npcs); skips already-dead NPCs.
- build_assassination_module now seeds its target name hint from mission.target_npc_name so the
  generated module matches the baked target (and the prior-recon banner still applies).

Tested: real-NPC bake, leader bake (Serrik Dhal -> difficulty 10/high-stakes), fallback name,
idempotency, 1% claim roll path. AST + import clean. (Did not run a live injure to avoid
mutating real NPC data.)

## Butterfly Effect: cross-pipeline consequence engine 2026-05-30

Documented the a->b->c methodology in CLAUDE.md ("The Butterfly Effect" section) and built a
type-dispatched consequence engine so resolved missions ripple into the world.

- CLAUDE.md: new "The Butterfly Effect" section -- principle (persist results, read upstream,
  write downstream), the wired chains, where consequences fire, and guardrails.
- assassination_pipeline.py (user/linter edit, kept + confirmed wired): a FAILED infiltration
  recon of the mark's faction now HEIGHTENS the assassination's security (_failed_recon_heat ->
  _heighten_security -> rendered banner at build, lines ~816 / ~1036).
- mission_board.py: _adjust_faction_rep (get/set_faction_reputation), _spawn_followup (generic
  follow-up via create_mission, guarded by MAX_ACTIVE_NORMAL), and _apply_mission_consequences
  (type dispatch). Called from BOTH NPC resolution branches (success + failure).

Chains in the engine (faction-rep nudges always; spawns gated 30-45%):
- Heist success  -> robbed faction rep down, employer up; ~30% spawn Recovery (owner wants it back).
- Defense fail   -> defender down, attacker up; ~45% spawn Assault (press the advantage).
- Sabotage hit   -> victim rep down; ~35% spawn Investigation (who did this -> may point back at us).
- Investigation success -> ~35% spawn Assassination (silence the named culprit).
- Negotiation fail -> ~45% spawn Defense (talks collapsed, it came to force).
- Infestation fail -> ~45% spawn another Infestation (the nest spread).
- Escort/Rescue  -> rep up/down by outcome.
Infiltration (recon + spawn heist) and Assassination (target bake + injury) keep their own
dedicated hooks; the dispatcher covers the rest, so no double-handling.

Tested: all branches dispatch the right follow-up type; spawns guarded against board flood;
faction-rep nudges via real get/set. AST + import clean. Logged; CLAUDE.md updated.

## Emoji mojibake repair + Strange Occurrences illegal-return chain 2026-05-30

Mojibake: the church emoji rendered as 'â›ª' in live bulletins. Root cause: news_feed.py (and
mission_board.py, defense_pipeline.py) had Unicode symbols saved cp1252-misencoded. The project's
repair_mojibake() did not recognize these, so used a precise reversal (map each mojibake char back
to its cp1252/latin1 byte, decode UTF-8; legit single high chars fail the decode and are left
alone). Restored: ⛪ (4x), → ✓ ✗ ✅, and box-drawing ═ dividers -> plain '=' per CLAUDE.md.
All 3 files AST + import clean; 0 stray 'â' / box chars remain.

Strange Occurrences -> graveyard chain (per user: pull NPCs that returned ILLEGALLY -- undead or
doppelganger -- card HINTS at who, success lays them back to rest, PC or NPC party):
- mission_board._bake_strange_occurrence_subject(mission): at generation (post_mission before the
  embed + idempotently in _save_mission), a Strange Occurrence ties to a random NPC with status in
  ('undead','doppelganger'). Stores returned_npc_name (DM SECRET) + returned_npc_status; builds
  clues (look/role/faction + a doppelganger/undead tell) and appends a "Strange signs (who walks
  again?)" hint block to the public body -- WITHOUT the name. No status change (they're already out).
- _extract_returned_npc_name now prefers the baked returned_npc_name.
- Resolution (existing _resolve_strange_occurrence_subject) flips the returned NPC to status='dead'
  + deceased_at on completion; called from BOTH the NPC-party complete branch and the player
  complete path, so either clearing the mission sends them back to the graveyard.
- strange_occurrences_pipeline render: new "DM Secret - The Illegal Return" card (the name, status,
  the planted clues, and the auto-resolution note) shown only when a subject is baked in.

Tested: bake pulls a real undead/doppelganger (e.g. Seraphine Duskveil), 4 hints, name kept off the
card, extraction + idempotency + non-strange-ignored all pass. (No live resolve run, to avoid
mutating a real NPC.)

## Personal missions use real campaign data, not filler 2026-05-30

Personal missions produced silly invented titles/themes ("the Plow", "the Hound", "Feathers",
"the Axe") because _build_personal_mission_prompt fed only the character sheet and a rule that
literally said "Invent fresh named NPCs ... precise locations". No real campaign nouns were
provided, so the model made up filler.

Fix (src/mission_board.py):
- New _real_anchors_block(character): pulls REAL nouns from the DB -- NPCs (preferring the
  character's organization, then others; name/role/faction), factions (faction_reputation),
  locations (gazetteer_places name+district), and items (epic_gear_pool). Each query guarded.
- _build_personal_mission_prompt now injects that anchors block and changes the rules:
  * ANCHOR IN REAL DATA: contact must be one of the listed NPCs, at a listed location, with a
    listed faction; use exact names; do NOT invent new NPCs/factions/places when real ones exist.
  * NO GENERIC FILLER TITLES: never build around invented objects (The Plow/Hound/Feathers/Axe/
    Crown); the title references the real NPC, faction, place, or item involved.
  * (replaced the old "Invent fresh named NPCs ... precise locations" rule.)

Verified: anchors block pulls real org NPCs (Gavrik Ironshield, Varg Blackfist...), and the prompt
now carries REAL NPCs/FACTIONS/LOCATIONS + the anti-filler rule. AST + import clean.

Follow-up: the board (non-personal) prompt _build_mission_prompt likely has the same 'invent'
tendency; the same _real_anchors_block can be dropped in there if desired.


## Board missions use real campaign data, not filler 2026-05-30
Extended the personal-mission anti-filler fix to the board (non-personal) generator.
- Added _board_anchors_block() in src/mission_board.py: pulls REAL NAMED PLACES (gazetteer_places) + REAL ITEMS (epic_gear_pool WHERE enabled=1). NPCs/factions already supplied by _build_npc_context/rep_summary_block, so not duplicated.
- _build_mission_prompt: computes anchors_block, injects {anchors_block} after area_block.
- TITLE RULES: added "NO INVENTED FILLER OBJECTS" (no The Plow/Hound/Feathers/Axe/Crown).
- RULES: added "ANCHOR IN REAL DATA" (set mission at a real named place; real item if object-centered; exact names).
- Verified: prompt now carries real places + items + both rules. AST+import clean.


## Butterfly Effect extended to remaining mission types 2026-05-31
Extended the orchestration engine src/mission_board.py:_apply_mission_consequences (NOT the pipelines) to cover the 9 types that had no ripple, plus low-weight ones.
- New branches: Ambush, Assault, Battle, Gathering, Recovery, Puzzle, Discovery, Exploration, First Contact. Folded Theft into the heist branch; added light Delivery/Political rep.
- Levers: existing _adjust_faction_rep + gated _spawn_followup (MAX_ACTIVE_NORMAL guard) + NEW _district_wealth(mission, delta, reason) which resolves a REAL district via _mission_district() (matches mission text against area_generator.get_all_district_names, longest-first; returns "" -> no-op so it never writes a garbage district) and calls db_api.adjust_district_wealth.
- Chains (a->b->c): Assault win -> opp Retake the Ground (Assault); Assault fail -> opp counterpush (Defense). Ambush win -> opp counter-ambush. Battle ravages district wealth either way; win -> Clear the Field (Recovery); loss -> opp Rout the Survivors (Ambush). Gathering -> district supply up/down; fail -> guarded Escort. Recovery win -> opp Snatch It Back (Heist). Puzzle win -> Behind the Open Seal (Recovery). Discovery win -> Claim the Discovery (Recovery); fail -> rival Discovery. Exploration win -> Beyond the Charted Way (Discovery); fail -> Something Followed Them Back (Ambush). First Contact win -> Seal the Accord (Negotiation); fail -> Contact Turned Cold (Defense). Delivery fail -> The Delivery Never Arrived (Recovery).
- No data seeding needed (faction_reputation populated, district list present, create_mission works).
- Verified: AST clean; no smart-quotes/mojibake (CLAUDE.md); side-effect-free mock test drove all 20 types success+fail with zero exceptions and correct rep/spawn/wealth; previously-wired chains unchanged; district guard read-only-safe (resolves real district, empty otherwise).


## Battlefield casualties wired into Battle/Assault/Ambush butterfly 2026-05-31
Added a general combat-casualty path so violent missions ripple into the NPC lifecycle.
- src/npc_lifecycle.py: NEW wound_npc_in_combat(name, cause) -- general-purpose counterpart to the assassination-specific injure_npc_by_name; sets status='injured' with a COMBAT history line ('Wounded in the fighting -- <cause>'); refuses faction leaders (is_faction_leader guard) and only wounds the living; lifecycle tick then resolves ~90% recover / ~10% graveyard. NEW wound_random_faction_member(faction, cause) -- picks a random living, non-leader, non-Unknown-Party member of a faction and wounds them; returns the name or ''.
- src/mission_board.py: NEW _battlefield_casualty(faction, label, chance=0.40) in the consequence engine -- gated (40%) call to wound_random_faction_member on the LOSING side. Wired into Ambush (win->opp, fail->faction), Assault (win->opp, fail->faction), Battle (win->opp, fail->faction).
- Guardrail honored: leaders can never die from a random combat tick (only deliberate gated outcomes like assassination). Casualties gated so the roster is not decimated.
- Verified DB-safe (mocked _save_npcs/add_npc_history_event): leader wound refused; random member picker returned a real non-leader (Elara Ironclaw, Iron Fang); engine hook calls through with correct faction+cause. AST clean, no smart-quotes/mojibake. No live NPC mutated.


## Iron Fang Consortium split into two warring factions 2026-05-31
Split per user: Iron Fang Consortium (Orthodox, Serrik Dhal) vs Iron Fang Syndicate (Sera Voss). Ongoing civil war.
- DB (scripts/split_iron_fang.py, idempotent): faction_reputation -> Consortium Liked+1 (leader Serrik Dhal, relics+infrastructure, amenable to PCs), Syndicate NEW row Disliked-2 (leader Sera Voss, rackets/loan-sharking/TowerBay stock manipulation). 9 living NPCs moved to Syndicate (Sera, Varg, Korra, Grimthar, Kyrus, Tilda, Erynn, Isaac, Elara); 9 stay Consortium. Serrik(101) rank Guildmaster + Orthodox role; Sera(26) -> Syndicate Guildmaster. global_state.iron_fang_civil_war = active (no end). faction_events seeded: Consortium The Orthodox Hold, Syndicate The Voss Ascendancy.
- Code: npc_lifecycle FACTIONS + FACTION_RANKS (Syndicate ladder Runner..Guildmaster) + _FACTION_DISTRICTS + _LORE + FACTION_LEADERS (Sera Voss). mission_board _ROTATION_FACTIONS + FACTIONS lore (both factions, leaders, foci, civil war) + heist sponsor list + NEW gated (25%) civil-war injector in _build_mission_prompt that forces a cross-schism mission (sponsor one side, Opposes the other) and is injected as {iron_fang_war_block}. faction_reputation KNOWN_FACTIONS. faction_calendar _FACTION_EVENTS Syndicate pool.
- Both leaders are is_faction_leader=True -> protected from random battlefield/lifecycle death (only deliberate gated assassination), keeping the war going.
- Verified: AST+encoding clean; NO mojibake in any Discord-bound emoji/text (calendar 1F4B0/1F4C8/1F4B8/1FA99, faction_events 1F4B0/1F6E1+FE0F, rep text pure ASCII); rep tiers Liked+1/Disliked-2; 9/9 members; rotation+lists include Syndicate; war injector fired 7/40.
- NOTE: code changes need a bot RESTART to take effect (running process predates them); DB changes (rep, NPC factions, arc, events) are already live.


## NPC Party Lifecycle - design + foundation 2026-05-31 (IN PROGRESS)
Goal: parties are living entities (form, recruit/join, split, merge, contract/fire, disband/retire, casualties).
Decisions (user): party members BECOME real npcs-table NPCs; NPCs can JOIN parties; parties SIGN/END/get-FIRED from faction/guild contracts. Build order: SPLITTING + FORMATION first; casualties second.
Model: NEW link column npcs.party_name (VARCHAR120, indexed, NULL=world NPC) added 2026-05-31. party_profiles.status gains active/disbanded/destroyed/splintered/merged/hiatus. members stay listed in members_json but each is now a real npc row (party_name set). Patron = party_profiles.employer/faction; a contract is that link + faction_affiliations row + party_history + faction rep.
New module src/party_lifecycle.py (mirror of npc_lifecycle.py): link helpers, _ensure_npc, ensure_party_members_are_npcs (lazy promote embedded->real), recruit_npc_to_party (JOIN), form_party (FORMATION; reuses unused adventurer_parties names + recruits existing free-agent NPCs -> NO filler names), split_party (SPLIT; Iron Fang Orthodox/Syndicate aware; splinter carries grudge), merge_parties, sign_contract/end_contract(fired), disband_party, party_lifecycle_tick (gated ambient orchestration; floor MIN_ACTIVE_PARTIES; skip PROTECTED_PARTIES Unknown Party).
Anti-filler: formation reuses LLM-pre-generated unused party names and recruits EXISTING unaffiliated NPCs; skips rather than synthesize filler.
DEFERRED (next passes): mission-driven casualties/wipeouts (the 2nd-pass), party_lifecycle_tick loop wiring in aclient, and an npc_lifecycle guard so party-bound NPCs skip faction-defection/promotion ticks.


## NPC Party Lifecycle - slice 1 built + verified 2026-05-31
src/party_lifecycle.py created (mirror of npc_lifecycle.py). Members are real npcs rows linked via npcs.party_name.
Built + verified (safe reverting end-to-end test, then test script deleted):
- Foundation: _link_npc/_unlink_npc, _ensure_npc, ensure_party_members_are_npcs (lazy promote embedded->real).
- JOIN: recruit_npc_to_party (refuses dead / already-partied / faction leaders).
- FORMATION: form_party -> reuses unused adventurer_parties names (NO filler) + recruits free agents; _free_agent_npcs PREFERS Independent NPCs (ORDER BY faction Independent first) so forming a crew does not gut a faction roster; excludes leaders + Unknown Party.
- SPLIT: split_party -> splinter carries grudge (faction_hates); Iron-Fang crews split along Orthodox<->Syndicate; gutted original auto-disbands. MERGE: merge_parties.
- CONTRACTS: sign_contract (sets employer/faction + faction_affiliations row + faction rep +1 + history); end_contract(fired=) (clears to Independent, removes affiliation, fired -> party point -1).
- DISBAND: disband_party (members -> free agents).
- TICK: party_lifecycle_tick (gated: floor MIN_ACTIVE_PARTIES=60 forms crews; 15% split favouring Iron Fang; 10% merge of small crews; PROTECTED_PARTIES skip). Async replenish_party_name_pool(min_free=20) reuses mission_board._generate_party_names.
- Seeded the adventurer_parties name pool: +50 generated (net 35 unused) so formation/split have names (was 0 -> root cause of early form_party None).
Test PASS: form(5)->recruit->sign+fire contract->split(3/3 with leader promoted + grudge)->revert clean (131 parties, 0 linked npcs).
DEFERRED (next): wire party_lifecycle_tick into an async loop in aclient (call replenish then tick); mission-driven casualties/wipeouts at the NPC complete/fail chokepoint; npc_lifecycle guard so party-bound NPCs skip faction-defection/promotion ticks; consider creating fresh Independent NPCs when free agents are scarce. NOTE: code needs a bot RESTART to load; npcs.party_name column + name-pool seed are already live.


---

## 2026-06-09 — Discovery pipeline: label leak + premise-blind fallback (mission 1276 "Veyra Maw's Silent Ledger")

SYMPTOM: Saturday's Discovery module read like Mad Libs. Briefing literally said "...tied to Veyra Maw's Silent Ledger, Argent Blades, Type, Difficulty, Expires, TBD..." and the whole module was generic living-anomaly boilerplate ("it may be alive", "leaks heat", "cannot cross running water", "reacts to prayer") for what is a smuggling LEDGER. None of the real premise (Veyra Maw, the encrypted cipher, Iron Fang Syndicate) appeared.

SMOKE (before): extracted generated_modules/Veyra_Maws_Silent_Ledger_id1276_*.zip -> module.html confirmed the leak + boilerplate. DB: mission body carries a card stat line "*Type: Discovery | Difficulty: standard | Expires: TBD | Reward:...*". Ollama was down/deferred so the module came 100%% from _fallback_plan.

ROOT CAUSES (all in src/mission_builder/discovery_pipeline.py):
1. _mission_context canon-extractor mined card field labels (Type/Difficulty/Expires/TBD) as proper nouns and spliced them into prose.
2. canon regex swallowed sentence boundaries ("Iron Vein Forge. She").
3. _pick_type used random.choice as default; a ledger should be a "truth" discovery.
4. _fallback_plan used HANDLING_STATES random samples + hardcoded living-anomaly implications, ignoring object class.
5. _generate_plan shipped the fallback silently on a single empty LLM response (no retry).

FIX (generation only - did NOT regenerate the module, per user):
- _strip_card_meta() drops the Type/.../Reward stat line + Opposes line before extraction.
- _LABEL_STOPWORDS rejects label/junk terms; terms cut at first sentence boundary.
- _pick_type: deterministic semantic routing (ledger/record/cipher->truth; spores->biology; machine/device->machine; signal/hum->phenomenon; soul->memory; default object).
- dtype-aware banks IMAGERY/HANDLING/IMPLICATIONS/CONTAINMENT_BY_TYPE; fallback now object-appropriate.
- _anchored_claims/_anchored_dialogue lead with the mission's own factions + object word.
- _generate_plan retries the LLM 3x and logs before falling back.

SMOKE (after): canon = [Veyra Maw's Silent Ledger, Argent Blades, S'kree, Veyra Maw, Market Square Garden, Iron Vein Forge, ...] (no labels, no ". She"). dtype=truth. render_module OK; asserted leak strings absent and cipher/Veyra Maw/Iron Vein Forge/forgery present. Routing test 6/6. AST OK, module imports clean.

NOTE: needs a bot RESTART to load. Other 21 mission pipelines were NOT touched (no-refactor rule). The fix improves both the LLM path (clean canon in the prompt) and the fallback path.

FOLLOW-UP (same day): Defined ledgers as canon — the recorded history + trapped essence of a place the Tower recycled. Added a distinct "ledger" discovery sub-type with scope scaling (well -> street -> district -> city -> world -> star system) and value scaling calibrated to the economy (well ~40-150 EC curio ... star system ~250k-2M EC priceless). _ledger_scope honours explicit scale cues (largest wins) else deterministic-by-id biased small; _ledger_value seeds worth; "Scope & Worth" card added to the module + scope note in the LLM prompt; scope-parameterized {subject} imagery/implications. Lore saved to memory/world_ledgers.md. Verified across all six scopes; AST + imports clean. (Bug found+fixed in same pass: _card() escapes its title, so the Scope card title must be plain "Scope & Worth", not pre-escaped.)


---

## 2026-06-09 — General news (hourly bulletin) died: prompt outgrew num_ctx

SYMPTOM (user): "lost the news.py after about a day; general news dropped off a few days ago; maybe fixed by reboot an hour ago." Reboot was 16:52; it was NOT fixed — newest failure 18:05.

SMOKE (before): news_memory shows news_type='bulletin' written daily (event-driven arena/coroner/editorial news kept flowing, so the channel was never silent — that masked it). But the LEGACY hourly generator generate_bulletin() logged "generate_bulletin() returned None — legacy bulletin failed this cycle" EVERY cycle, 31x, from 06-08 09:56 through 06-09 18:05 (continuing past the reboot). Reason logged: "Bulletin failed validation (truncated) — repair also failed (truncated)".

ROOT CAUSE (captured by reproduction, not inferred): generate_bulletin()'s prompt from _build_prompt() had grown to ~46,660 chars (~11,700 tokens) as the world accumulated NPCs/factions/places, but the Ollama call used a fixed num_ctx=8192. An oversized prompt is silently truncated by Ollama and the model emitted exactly 1 char ("📺") with done_reason="length". After filtering, the "bulletin" was just "📺" + TNN signoff (74 chars), correctly rejected as truncated -> None. NOTE: the memory/history block is only ~158 tokens; the bulk is the static world-context blocks, so capping memory would NOT have helped. Confirmed fix: same prompt with num_ctx=16384 -> clean 533-char bulletin (done_reason="stop").

FIX (src/news_feed.py): added _fit_num_ctx(prompt, reply_tokens) that picks a context window (8192/12288/16384/24576/32768) large enough for prompt+reply+overhead, logs when it grows, warns if it ever exceeds 32k. Wired into the 3 bulletin-pipeline Ollama calls: main generation (was num_predict 900), fact-check (2048; its prompt embeds the full 224-NPC roster so it was also at risk), and editor (1200). Only RAISES ctx when needed (8192 floor) so small prompts are unchanged.

SMOKE (after): full generate_bulletin() (writes monkeypatched off) returns a valid 604-char bulletin. AST OK.

NEEDS BOT RESTART to load. WIDER RISK (not fixed here): same latent overflow in other fixed-num_ctx callers — news_feed daily-types (num_ctx 12288) and two other calls at 8192; and discovery_pipeline._ollama sets NO num_ctx at all (uses Ollama default). Consider _fit_num_ctx there too if those outputs go empty.

---

## 2026-07-11 - PLAN: Tier 1 pipeline hardening - num_ctx fit + LLM retry (all pipelines)

WHY: The news-bulletin failure class (prompt outgrew fixed/default num_ctx -> Ollama silently
truncates -> empty/1-char reply -> silent generic fallback) is latent in nearly every mission
pipeline. Only discovery_pipeline has _fit_ctx (2026-06-09 fix); published_pipeline has a fixed
8192; the other ~19 pipeline Ollama callers set NO num_ctx at all. Separately, 8 pipelines ship
the generic fallback after a SINGLE empty LLM response (the exact 2026-06-09 Discovery "Mad Libs"
bug, fixed only in Discovery).

PLAN (per-pipeline local changes only; no shared helper, per pipeline-independence rule):
A) Copy discovery's _fit_ctx(prompt, reply_tokens) locally into each file with an Ollama call and
   wire "num_ctx": _fit_ctx(...) into its options. Floor 8192, only raises, cap 32768.
   Files: ambush, assassination, assault, battle, defense, escort, exploration, first_contact,
   gather, heist, infestation (_ask), infiltration, investigation, negotiation, published
   (replace fixed 8192), puzzle, rescue, recovery, sabotage, strange_occurrences pipelines,
   plus module_council._call, scene_dialogs._ask, __init__._ollama_generate.
B) Add discovery-style 3-attempt retry (log each miss, 2s pause) around the plan-generation
   _ollama call in the 8 pipelines with no retry: rescue (:522), sabotage (:530),
   infiltration (:601), negotiation (:488), exploration (:444), recovery (:629),
   strange_occurrences (:468), first_contact (:242, also add import asyncio).

SMOKE: pre-edit payload capture (fake resource_cop/ollama_queue + httpx capture) to confirm
num_ctx absent; post-edit same harness asserts num_ctx floor 8192 on small prompts, 32768 on
huge prompts, and 3 _ollama attempts before fallback in the 8 retry pipelines. AST check every
edited file.

## 2026-07-11 - DONE: Tier 1 pipeline hardening - num_ctx fit + LLM retry + first_contact gate fix

SMOKE (before): payload-capture harness (fake resource_cop/ollama_queue/httpx, fake db_api since
MySQL creds are not loaded outside the bot) confirmed 21/22 Ollama call sites sent NO num_ctx
(only discovery correct at 8192 small / 32768 huge).

FIX A - _fit_ctx everywhere: copied discovery's _fit_ctx LOCALLY (no shared helper) into 22 more
files and wired "num_ctx": _fit_ctx(...) into each options dict, counting system+prompt where a
system message exists: ambush, assassination, assault, battle, defense, escort, exploration,
first_contact, gather, heist, infestation (_ask), infiltration, investigation, negotiation,
puzzle, rescue, recovery, sabotage, strange_occurrences pipelines; published_pipeline (fixed 8192
-> fitted); module_council._call; scene_dialogs._ask; __init__._ollama_generate.

FIX B - retry: discovery-style 3-attempt loop (warn per miss, 2s pause, warn on final fallback)
added around the plan-generation call in the 8 pipelines that shipped fallback after ONE empty
response: rescue, sabotage, infiltration (keeps contact_speech accept condition), negotiation
(retries parse failures only; generic-plan gate unchanged), exploration, recovery,
strange_occurrences, first_contact (+ import asyncio, was missing).

BONUS BUG FOUND during verification (first_contact_pipeline, pre-existing):
1. _is_generic_plan self-poisoned: TOWER_PRIMER (merged into EVERY plan as tower_primer) contains
   "new arrivals", which is in GENERIC_PLAN_MARKERS -> a single marker hit rejected plans even at
   specificity score 10 -> first_contact discarded virtually every LLM plan and always shipped
   the fallback. Likely why First Contact sat in the lowest bakeoff tier.
   FIX (negotiation-precedent): marker blob now excludes constant scaffold fields
   (tower_primer/panic_meter); a plan anchored in mission canon (score >= 3) can no longer be
   rejected by markers alone; unanchored plans still rejected.
2. Canon-term regex swallowed sentence boundaries ("Market Square Garden. Iron Fang") - same bug
   fixed in discovery 2026-06-09. FIX: terms cut at first ". " boundary.

SMOKE (after): all 22 runtime-tested sites return num_ctx 8192 (small prompt) / 32768 (huge);
retry loop present in all 8 files; first_contact end-to-end: dead LLM -> exactly 3 attempts ->
mission-faithful fallback; flaky LLM -> early break at attempt 2 and anchored partial plan now
ACCEPTED (was rejected before the gate fix); junk unanchored plan still rejected. AST clean on
all 23 edited files; inserted blocks verified pure ASCII (pre-existing emoji untouched);
src.mission_builder package + helpers import clean.

NEEDS BOT RESTART to load. Other pipelines' generic-plan checkers were NOT touched (no-refactor
rule) - if any other type shows constant-scaffold marker self-poisoning, apply the same local fix.

---

## 2026-07-11 - DONE: 2024 Monster Manual statblocks + Mimir enrichment rollout + escort/first_contact quality pass

Bot is DOWN for a while (user family circumstances); all changes load on next restart.

### 1. monster_stat_gen.py _SRD -> 2024 Monster Manual (XMM) data
The 39-monster _SRD table shipped 2014 SRD stats and 2014 attack phrasing ("Melee Weapon
Attack: +4 to hit") to DDB pushes (infestation + dungeon delve). Since the campaign is D&D
2024/5.5e, extracted the real 2024 stat blocks from the Mimir catalog: mimir-mcp only returns
search summaries, so read the Mimir SQLite directly READ-ONLY
(C:\Users\akodoreign\AppData\Roaming\com.mimir.app\data\mimir.db, `monsters` table, source XMM,
full 5etools JSON in `data`). Generated the replacement table with a 5etools-tag renderer
(scratchpad gen_srd_2024.py): AC/HP/dice/abilities/speed/languages/actions all from catalog,
2024 phrasing ("Melee Attack Roll: +4 ... Hit: ..."), signature traits included (Pack Tactics,
Undead Fortitude, Regeneration...), pure ASCII. Table KEYS unchanged (pipelines look up classic
names); 2024 renames noted inline: Goblin->Goblin Warrior (now FEY per 2024), Kobold->Kobold
Warrior, Bugbear->Bugbear Warrior, Hobgoblin->Hobgoblin Warrior, Minotaur->Minotaur of Baphomet.
Notable stat shifts: Lich AC 17/HP 135 -> AC 20/HP 315; Ogre 59 -> 68 HP; Troll gains Loathsome
Limbs. _cr_formula generic action phrasing also modernized. SMOKE: 39 entries load;
build_statblock("Goblin") -> ac15/hp10/fey with 2024 phrasing; "+1 Skeleton" normalization and
unknown-monster CR-formula paths intact; zero 2014 phrasing left in the table.

### 2. Mimir monster enrichment extended (was only assault/defense/battle/infestation)
- ambush_pipeline: DB-monster guard roster members (role "CR <n> <type>") now go through
  enrich_monsters -> real/homebrew stat blocks in the Mimir module + render_mimir_section shows
  them. Named faction NPC guards (people) are correctly skipped.
- escort_pipeline: NEW _fetch_ambushers() fetches the DB ambusher roster ONCE in the build fn;
  the same roster now feeds module HTML (_ambusher_roster_html/_dm_overlay accept prefetched
  list), Mimir enrichment (mission_enemy_entry), and the session view - no more mismatch between
  page and VTT.
- rescue_pipeline: captor forces from logical_enemy_roster_for_mission (2, void-aware) enriched;
  aftermath-mode subtypes skip (no active combatant).

### 3. Escort session HTML (open item from 2026-05-22 bakeoff: "route nodes and ambusher DCs
not surfaced")
render_escort_session gains: Route Progress card (ordered checkboxes: pickup -> one leg per
hazard with skill+DC inline -> delivery) and Ambush Response card (opposing faction, goal,
sprung/reinforcements/defeated checkboxes, per-ambusher stat lines from the shared roster, trap
checklist). New params all keyword-defaulted; build fn passes traps/locations/goal/ambushers.

### 4. First Contact quality pass (follow-on to the gate fix earlier today)
- _pick_location: ORDER BY id DESC LIMIT 12 (only the 12 NEWEST gazetteer places, heavy bias) ->
  ORDER BY RAND() LIMIT 12.
- Fallback enriched to match what the prompt promises: first_sight 4 -> 8 images, dialogue 6 ->
  16 lines (elder/child/party/faction/TNN/warden voices, canon-anchored via _first_term).
- Removed dead import: cr_scaling.party_strength was shadowed by the local _party_strength def.

SMOKE (end-to-end, side-effect-free: fake db_api/ollama/resource_cop AND fake mimir_client so
no real Mimir modules get created): built escort, ambush, rescue, first_contact modules to
scratchpad. Escort session.html contains Route Progress + Ambush Response + DCs + opposing
faction; ambush/rescue build clean through the new enrichment wiring with Mimir down (no-op);
first_contact module canon-anchored with rich fallback; rescue exercised the aftermath skip.
AST clean on all edited files.

DEFERRED: enrich_items() still has zero callers (loot -> real catalog items) - candidate for a
later pass; Discovery/Negotiation/Recovery bakeoff re-run once the bot is back up.

---

## 2026-07-11 - DONE: loot -> Mimir item enrichment (all 20 pipelines) + loot reroll consistency + guild_council ctx fit

### enrich_items() had ZERO callers - mission loot never reached the Mimir module
Design: treasure.loot_card() rolled a fresh package INSIDE render and threw it away, so the
items could never be attached to Mimir - and a second loot_card call on the same mission would
have rolled DIFFERENT loot (latent inconsistency).

FIX A (src/treasure.py): loot_card now rolls once and caches the package on the mission dict
(mission["_loot_pkg"]); repeated calls reuse it. Verified: two calls -> identical HTML.

FIX B (src/mission_builder/mimir_module.py): NEW enrich_mission_loot(module_id, mission) -
reads the cached package, sends only the slots with real item names ("magic" from
treasure_items magic_item rows + the 5%% "mimir" pull) through enrich_items() -> catalog match
-> add_item to the Mimir module. Store gadgets/food/elemental gems are campaign-custom and
intentionally skipped. No-ops cleanly with no package/no items/no module/Mimir down.

FIX C (all 20 pipelines + infestation): after render (loot_card has run by then),
`_loot_rewards = await _mel(_mimir_id or "", mission)` and the render_mimir_section second arg
[] -> _loot_rewards, so matched items show in the "D&D 5e Reference (via Mimir)" section with
rarity colors. Bulk-edited via script with per-file asserts (1 import + 1 call site each);
assassination + infestation parenthesized imports done by hand. Wiring check: 20/20 have
exactly one loot call, zero bare [] reward args left.

### Ollama num_ctx sweep - remaining callers outside mission_builder
ollama_queue already injects num_ctx = OLLAMA_NUM_CTX (8192) when a caller sets none, and does
NOT overwrite caller-set values, so the pipeline _fit_ctx values take precedence as intended.
area_generator (16384) / area_places (12288) / agents/base (env OLLAMA_AGENT_CTX) already set
env-tunable values - left alone. skills.py relies on the queue default - fine for its prompt
size. ONE fixed literal fixed: agents/guild_council.py had num_ctx: 8192 hardcoded with
think:True -> now fits prompt+reply over the 8192..32768 ladder.

SMOKE: unit - loot_card caches + repeat-identical; enrich_mission_loot with a fake AVAILABLE
Mimir matches "Flame Tongue Longsword" -> catalog "Flame Tongue", add_item called, no-op paths
clean, render_mimir_section shows the loot. End-to-end - heist, discovery, assassination
modules built with Mimir DOWN through the new wiring (no-op, no crash). AST clean x23
(20 pipelines + mimir_module + treasure + guild_council).

NEEDS BOT RESTART. Note: with Mimir UP, loot enrichment fires on every module where the 15%%
magic-item or 5%% mimir-pull slot hit - most modules still no-op (EC/store-item loot), which is
correct.

---

## 2026-07-11 - DONE: generic-gate self-poisoning was a BUG CLASS - 5 more pipelines fixed + LoRA trigger verification

### Self-poisoning audit (follow-up to the first_contact TOWER_PRIMER find)
All pipelines with a GENERIC_PLAN_MARKERS gate were audited two ways: static (marker strings
appearing elsewhere in the same file) then dynamic (build the real _fallback_plan across every
subtype, JSON-dump, check markers). Because every one of these gates runs on the MERGED plan
(fallback fields fill whatever the LLM omitted), a marker inside the fallback text rejects ANY
partial LLM plan.

CONFIRMED POISONED (fallback text contains own markers -> partial plans always discarded):
- discovery: "strange discovery"
- exploration: "old maps no longer match", "survey zone"
- recovery: "recovery target"
- rescue: "needs extraction"
- strange_occurrences: "strange occurrence", "the occurrence" (that phrase appears in
  essentially ALL strange-occurrence text, so even rich plans died here)

FIX (same local pattern as first_contact, applied per-pipeline): score >= 3 canon-anchor
override - a plan carrying >= 2 mission canon terms cannot be marker-rejected; unanchored
plans still reject. Verified 5/5: anchored partial plan kept, junk still rejected.

CLEAN (no fix needed): puzzle (0 fallback marker hits) and investigation (1 hit) use a
>= 2-hit threshold that protected them; negotiation was already fixed 2026-05-22 with the
canon-name check; the other 12 pipelines have no marker gate.

IMPACT NOTE: discovery/recovery/rescue/strange were exactly the types sitting in the lower
bakeoff tiers - this single bug class likely suppressed LLM output across SIX pipelines
(with first_contact). Fresh bakeoff after restart should show it.

### EnvyFluxDungeonMap01 trigger words - VERIFIED (open item since 2026-05-03)
Civitai model 746399 "Envy Flux Handdrawn RPG Map 01" v1.0 (Flux.1 D), file
EnvyFluxDungeonMap01.safetensors - filename in env config is CORRECT. The API shows NO
trainedWords: this LoRA has no strict activation token; it activates by weight and steers on
descriptive prompt words. The assumed "detailed, map, dungeon" prompt fragment is valid and
matches the model tags (hand drawn, dungeon, map, ink, black and white). No code change needed;
optional future tuning: add "hand drawn"/"top-down"/"ink" to A1111_MAP_DUNGEON_TRIGGERS env.
Town map LoRA (model 809483, v01c) triggers CONFIRMED exactly as configured: "detailed, map,
village". Sources: civitai.com/models/746399, civitai.com/models/809483.

AST clean x5. NEEDS BOT RESTART (with everything else from today).

---

## 2026-07-11/12 - FRESH BAKEOFF (post-fix validation) + scene_dialogs literal-"None" foe leak

MySQL was off (user re-enabled); Ollama up with qwen3-8b-slim. Ran the REAL bakeoff
(scripts/pipeline_bakeoff.py --runs 2) on the 7 pipelines touched this week. Results vs the
2026-05-22 baseline:

| Pipeline | 05-22 | Now | Note |
|---|---|---|---|
| first_contact | Usable 7-7.9 | 10.0 | de-poisoned gate: LLM plans finally survive |
| recovery | Usable 7-7.9 | 10.0 clean | same |
| escort | Strong 8-9.9 | 10.0 | Route Progress + Ambush Response session cards |
| rescue | Strong | 9.9 clean | |
| discovery | 7.4 | 7.9 | 5x "None" leak flagged (see below) |
| exploration | 10 | 8.8 | 5x "None" leak |
| strange_occurrences | Strong | 8.8 | 5x "None" leak |

REAL-WORLD RETRY PROOF: during the run Ollama timed out twice on first_contact; the new
3-attempt retry recovered both and the module still scored 10.0. That exact failure used to
silently ship the generic fallback.

### New bug found by the bakeoff: scene_dialogs renders the literal string "None" as the foe
SMOKE (before): all 3 flagged modules contained "Ask about None", "your contact admits None is
more involved...", "and None grows bolder" in the Table Talk / fallback dialog sections.
ROOT CAUSE: scene_dialogs._npc_context guarded `(mission.get("opposing_faction") or "").strip()`
- catches Python None and "", but NOT the literal STRING "None" that legacy board missions and
templates carry (same family as the 2026-05-22 published-fallback "None" bug).
FIX (scene_dialogs is a shared component like boxset_utils, so a central fix is allowed):
opposing_faction values in {"none","n/a","unknown","null","tbd"} (case-insensitive) are treated
as empty -> "the opposition". Unit-verified: all junk variants sanitize, real faction names
untouched, fallback dialog contains zero "None".
RE-VERIFY: single-run bakeoff rerun for discovery/exploration/strange_occurrences kicked off
to confirm the red flags clear (result to be appended).

Bakeoff artifacts: generated_modules/pipeline_bakeoff_20260711_175153/pipeline_bakeoff_report.md

RE-VERIFY RESULT (2026-07-12 08:00 rerun, --runs 1, post scene_dialogs fix):
| Pipeline | Before fix | After fix |
|---|---|---|
| discovery | 7.9 (5x None, 10 red flags) | 9.6, 0 None, clean |
| exploration | 8.8 (5x None, 10 red flags) | 10.0, 0 None, clean |
| strange_occurrences | 8.8 (5x None, 10 red flags) | 10.0, 0 None, clean |

All 7 re-baked pipelines now score 9.6-10.0. The three types that sat in the "Usable" tier
since 2026-05-22 (discovery 7.4, recovery, first_contact) are all >= 9.6. Uniqueness also went
to 10.0 on the rerun batch. Artifacts: generated_modules/pipeline_bakeoff_20260712_075247/.
Bakeoff work COMPLETE; bot restart still pending to load everything into the live process.

---

## 2026-07-12 - DONE: NPC party lifecycle fully wired (the 2026-05-31 deferred work)

The party lifecycle (src/party_lifecycle.py) was built + verified 2026-05-31 but NEVER wired
into the bot -- live DB confirms: 0 party-linked NPCs, 0 unused crew names (the seeded pool
drained with nothing replenishing). Crews never formed/split/merged in the live world.
All three deferred pieces are now done:

### 1. aclient.party_lifecycle_loop (NEW, wired at process_messages)
Daily-ish (20-28h jitter), 90-min boot offset so it never contends with the NPC lifecycle's
45-min head start. Order: replenish_party_name_pool(min_free=20) FIRST (pool is empty right
now), then party_lifecycle_tick(). Notable events (formed/split/merged) post one compact
"GUILD REGISTRY -- CREW MOVEMENTS" bulletin (Adventurers Guild Registry attribution) and are
written to news memory, so the world visibly moves.

### 2. npc_lifecycle guard for party-bound NPCs
- _load_npcs now SELECTs npcs.party_name (real column) into the npc dict; _save_npc strips it
  from the data_json copy so the link never leaks into the blob (CLAUDE.md JSON rule).
- apply_npc_event: party-bound NPCs reroll faction-career events (promotion, demotion,
  faction_defection, guild_hire/promotion/fired/poached) into personal events (revelation,
  new_secret, public_incident, alliance, betrayal, daily_generated) -- their career is the
  crew's story, driven by party_lifecycle contracts/splits. Death stays possible (existing
  _handle_party_member_death covers it).

### 3. Mission-driven crew casualties (the "second pass") at the butterfly chokepoint
NEW party_lifecycle.mission_party_casualties(party_name, mission, success) called from
mission_board._apply_mission_consequences (engine orchestration, not pipeline logic):
- violent types only (battle/assault/ambush/defense/assassination/infestation/rescue/extraction)
- protected parties (Unknown Party) always skipped
- ordinary blood price: ONE member wounded (fail 35% / success 12%) via wound_npc_in_combat --
  the NPC lifecycle then resolves ~90% recover / ~10% graveyard (no new death code paths)
- WIPEOUT (new destroy_party): 4%, ONLY on failed difficulty>=8 violence -- every member
  wounded + unlinked, crew status='destroyed', party/npc history written, news memory line;
  deaths emerge organically from each member's injury resolution
- guardrails intact: leaders can't be wounded (wound_npc_in_combat refuses), no direct kills.

VERIFIED (side-effect-free fakes): non-violent + protected no-ops; violent fail wounds exactly
one member; wipeout wounds all, unlinks, marks destroyed; success above gate unscathed;
party-bound NPC's forced faction_defection rerolled into personal events while an unaffiliated
NPC defects normally; mission_board seam passes correct args. Live read-only check: 166 active
parties (floor 60 ok). AST clean x4 (aclient, party_lifecycle, mission_board, npc_lifecycle).

NEEDS BOT RESTART (with everything else pending).

---

## 2026-07-12 - DONE: PC portraits removed + image loops slowed + weekday 4-9pm power gate

User request: "remove player character image generation (we have enough now)" and "slow down
NPC and Gazette image generation... especially during the 4pm-9pm range" (weekends exempt --
peak rate is 89c/kWh weekdays only).

MAPPED all image streams first: NPC portraits (aclient.npc_portrait_loop, ACTUALLY every
2.5-3.5h despite a 5-7h docstring), story/city scenes aka the gazette photos
(aclient.story_image_loop, every 2-4h; combined = an image every ~90min, hence "popping"),
towerbot item art (once daily -- left alone), ad_feed (no images), cogs/images (user-invoked
slash commands -- left alone, on-demand is fine).

CHANGES:
1. PC portraits OFF: news_feed.generate_npc_portrait had a 30% branch that drew a random
   player_characters row instead of an NPC. `_is_player_char = False` (branch kept intact,
   one-line re-enable later).
2. Slowed: story images 2-4h -> 5-8h (next_image_interval_seconds); NPC portraits
   2.5-3.5h -> 6-9h. Stale docstrings corrected.
3. NEW aclient._peak_power_delay_seconds(): Mon-Fri 16:00-21:00 returns time-until-21:00
   (+60-600s jitter so loops don't stampede at 21:00), Sat/Sun always 0. Both image loops
   check it at the top of each cycle and sleep the window out with a clear log line
   ("Peak-rate window (Mon-Fri 4-9pm) -- ... resume in Xm").

VERIFIED: helper unit-tested across Mon 3:59pm/5pm/9:01pm, Fri 8:30pm, Sat/Sun 5-6pm
(weekend exemption confirmed); PC flag asserted hard-off in source; AST clean x2.

NOTE (not done, needs admin): the "Tower Peak Saver" scheduled task still switches the CPU
scheme at 17:00 -- could move to 16:00 to match the user's stated window.
NEEDS BOT RESTART.

---

## 2026-07-12 - DONE: schema map refresh + RAG-debt audit closed + free-agent NPC minting

### CLAUDE.md live schema map refreshed (was 2026-05-22 / 57 tables; now 2026-07-12 / 62)
Six undocumented tables added to the map with owners: treasure_items (207; src/treasure.py loot
pools), towerbot_world_items (221) + towerbot_purchase_requests (2; TowerBot web shop),
dnd_classes (17) + dnd_subclasses (120) + npc_action_prompts (36; db_api-seeded reference data
for NPC/portrait generation). Note added that row counts are orientation-only
(information_schema estimates drift badly -- it reported monsters=255 vs COUNT(*)=348).

### Text-file "RAG debt" audit -- CLOSED AS NOT-DEBT
Traced every reader of campaign_docs character_memory.txt / npc_roster.txt / news_memory.txt:
- ALL live read paths are DB: tower_rag primary = training_docs table; Oracle character text =
  db_api.get_character_memory_text() (player_characters.raw_block); news agents + mission
  builder NPC rosters = npcs table queries; mission_board._load_characters = player_characters.
- The txt files are only (a) tower_rag's explicit DB-DOWN fallback, kept fresh by cheap
  write-throughs (npc_lifecycle._rebuild_txt, character_monitor sync), and (b) the manual
  memory_strip CLI. That is deliberate resilience, not migration debt -- KEPT.
- Note: training_docs contains only static lore/PHB docs (unchanged since 2026-04-10), which is
  correct -- dynamic world data reaches the Oracle through the dedicated DB paths, not RAG docs.

### Party lifecycle: free-agent minting (closes the last optional piece)
Live DB showed only 2 free Independent NPCs -- crew formation/splits would immediately start
pulling faction members (roster-gutting) once the new loop runs. Built:
- npc_lifecycle.generate_new_npc gains optional faction_override (default None = old behavior).
- NEW party_lifecycle.replenish_free_agents(min_free=6, batch=2): when free Independents < 6,
  mints up to 2 fully-LLM-generated Independent NPCs per tick (real name/secret/quote via the
  existing generator -- no filler), saves via _save_npc, npc_history "arrived looking for crew
  work". Slow city growth by design (max 2/day).
- aclient.party_lifecycle_loop calls it between the name-pool replenish and the tick.
VERIFIED: mints exactly 2 with faction_override="Independent" + save + history when pool short;
no-op at/above floor. AST clean x3. NEEDS BOT RESTART.

---

## 2026-07-12 - DONE: RESTART-READINESS AUDIT (read this before turning the bot back on)

The bot has been down for weeks while ~30 files changed. Full pre-flight run today:

### Boot will not crash
- py_compile: ALL 162 .py files compile clean.
- REAL import-chain test with live .env + MySQL: 27/27 core modules (bot, aclient, providers,
  mission_board, news_feed, both lifecycles, economy, rag, mimir, mission_builder, agents) and
  10/10 cogs import without error.

### Backlog measured (live DB, 2026-07-12)
- 26 NPC-claimed missions overdue -> ALL would have resolved on the FIRST hourly sweep
  (26 LLM notices + posts + follow-up spawns + new casualty rolls at once).
- 10 expired-but-active missions -> 10 LLM resolution notices + DM pings at once.
- Resurrection queue: 5 due (posts 5 bulletins over the first lifecycle pass - acceptable).
- Calendar pending spawns: 0. Open bounties past expiry: 0. Auctions: 10 active (normal).

### Storm caps added (mission_board.py; also protect against ANY future outage)
- check_npc_completions: NEW per-pass cap, env NPC_COMPLETIONS_PER_PASS (default 3) -> the 26
  overdue crews return over ~9 hours as a steady narrative stream. Verified: 6 due + cap 3 ->
  exactly 3 resolve pass 1, remainder pass 2.
- check_expirations: NEW cap on NOTICED expirations, env MISSION_EXPIRY_NOTICES_PER_PASS
  (default 5); the silent stale-board age sweep stays uncapped (posts nothing).

### What to EXPECT on restart day (normal, not bugs)
1. Mission board startup burst posts fresh missions (existing STARTUP_BURST behavior).
2. Over the first ~9h: a trickle of NPC crew completion/failure notices as the backlog drains,
   each with consequences (rep, follow-ups, possible wounds).
3. Up to 5 expiry notices per hour until the 10 stale contracts clear.
4. First NPC lifecycle tick ~45min after boot; NEW party lifecycle tick ~90min after boot
   (first run replenishes the empty crew-name pool via LLM, may mint up to 2 Independent NPCs,
   then may form/split crews and post the first GUILD REGISTRY bulletin).
5. Up to 5 resurrection-queue bulletins on the first lifecycle pass.
6. Images: story scenes 5-8h apart, NPC portraits 6-9h apart, none 4-9pm weekdays,
   NO player-character portraits.
7. Everything from the 2026-07-11/12 buglog entries loads for the first time on this boot.

---

## 2026-07-12 - DONE: outcomes feed the board (butterfly) + chat/agent num_ctx floors

### Mission outcomes now feed NEW mission generation
mission_outcomes (727 rows of story memory incl. loose_threads) was written by the resolution
hooks and read by 4 pipelines (investigation/negotiation/puzzle/sabotage) -- but the BOARD
prompt, where new missions are born, never saw it. NEW mission_board._recent_outcomes_block():
last ~8 outcomes with a loose thread or notable moment (max 5 lines, 220 chars each,
junk-opposing-faction filtered), injected into _build_mission_prompt as "RECENT MISSION
OUTCOMES (the world remembers -- you MAY build on one of these...)". Verified live read-only:
block renders real player history ("Silas Grimshaw's Silent Ledger" loose thread) and the full
prompt builds at ~18.2k chars.

### num_ctx: last two unfitted LLM paths closed
- providers.FreeProvider._fallback_ollama_chat (the PLAYER CHAT fallback) sent NO options at
  all -> now fits num_ctx to the conversation (8192..32768 ladder). RAG-heavy chats no longer
  silently truncate.
- agents/base.py: OLLAMA_AGENT_CTX (12288) is now a FLOOR that auto-raises on the same ladder
  when the messages outgrow it -- board mission prompts are ~4.6k tokens TODAY and grow with
  the world; this future-proofs every agent call (board gen, area gen, council).
- NOTE: providers.py has a pre-existing UTF-8 BOM; harmless to Python, left alone. Use
  encoding="utf-8-sig" when reading it in tooling.

### Test-pollution incident (fixed same session, lesson logged)
The earlier NPC-completion cap unit test faked _generate/_save_missions/rep functions but
missed the LAZY import of mission_outcomes.save_outcome inside check_npc_completions -> 6 fake
"Contract N" rows were written to LIVE mission_outcomes. Found while sampling the table
(fixtures showed up in the outcomes block preview), deleted surgically by id (728-733; table
back to 727 rows; no JSON file recreated). LESSON: when unit-testing bot functions against
fakes, stub EVERY lazily-imported writer (grep the function body for 'from src.' imports), or
fake the whole db_api module.

---

## 2026-07-12 - DONE: dashboard audit (last unverified boot surface)

- module_generation_jobs (6 rows) + dashboard_claim_jobs (4 rows): ALL status='done' -- no
  stale pending jobs, no module-generation storm on restart. (Feared 6 auto-fired 20-min
  generations; reality: clean queues from late May.)
- Webpage/app.py imports clean with live .env+MySQL: 43 routes registered. Read-only smoke via
  Flask test client: GET / , /api/status , /api/missions all 200 against the live DB.
- Restart-readiness picture is now COMPLETE: bot process, all cogs, all loops, and the
  dashboard thread are verified importable/serving; every queue and backlog measured and
  either clean or capped.
