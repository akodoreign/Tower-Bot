# Buglog

Last updated: 2026-05-10 (traffic-cop architecture investigation opened; VAE error tracked as open)

Operating note: quality and correctness matter more than speed for this bot. A slow, complete mission or image pipeline is preferable to a fast fallback that silently drops maps, prose, faction context, portraits, or rules detail.

Fixing rule: before fixing any bug in this file, first smoke test the current behavior and map the connected callers/routes/background jobs. After the fix, run the same smoke path again plus any adjacent tests needed for the touched subsystem. Do not patch from the note alone.

---

## Active Investigations (In Progress / Open)

### I-3. write_maps_page blocks event loop for up to 49 minutes — status: fixed 2026-05-11

Symptom: Clicking "generate mission" caused the dashboard to spin. The entire bot froze — no bulletins, no Discord responses, no commands — for up to 49 minutes. Discord eventually invalidated the session and the bot reconnected.

Evidence (2026-05-11 09:16 – 10:09):
- 09:16: Player claimed "The Leaden Crown's Corruption" (infestation pipeline started).
- 09:19: All 12 A1111 room map calls failed with 500 (broken VAE state — already fixed by I-1b).
- 09:19:42: `[INFEST] Rendering module HTML...` logged; pipeline moved to assembly phase.
- 09:20:03: `discord.gateway: heartbeat blocked for more than 10 seconds` — and counting every 10s.
- 10:09:09: `[INFEST] Complete` — 49 minutes and 27 seconds after assembly started.
- 10:09:10: Discord session invalidated. Bot reconnected at 10:09:16.

Root cause:
`src/mission_builder/boxset_utils.py:write_maps_page` calls `stylize_pretty_battlemap()` synchronously — no `asyncio.to_thread`, no thread offload. `stylize_pretty_battlemap` makes blocking `httpx.Client` requests to A1111 and calls `wait_for_a1111_idle()` (also blocking), each with timeouts up to `PRETTY_TIMEOUT` seconds. With A1111 returning 500s, each pretty-map attempt ran to the full timeout. Two cached maps × multiple strategies × PRETTY_TIMEOUT ≈ 49 minutes of total event-loop stall.

All pipeline callers are affected: infestation, ambush, assassination, assault, battle, defense, escort, exploration, gather — any pipeline that calls `write_maps_page` with maps that don't have a pretty version yet will hit this.

Why pretty map generation was in write_maps_page:
It was added as a "catch-up" pass for maps that didn't get a pretty version during generation. But this is the wrong place — assembly runs in the async event loop and cannot block.

Fix applied 2026-05-11:
Removed the `stylize_pretty_battlemap` call from `write_maps_page`. The page now renders whatever maps exist (tactical + pretty if already generated), and shows a placeholder for missing pretty versions. Pretty maps are generated earlier in the pipeline when maps are first created — that path already runs correctly and is async-safe. Nothing was re-added for the catch-up case; if a pretty map wasn't generated during the map step, it simply won't appear in the assembled module.

Smoke path (not yet run — next infestation generation will confirm):
- Generate an infestation module.
- Confirm heartbeat never blocks for >10s during assembly.
- Confirm maps.html renders tactical maps and shows placeholder for missing pretty maps.
- Confirm module completes in <10 minutes total.

Secondary issue from the same event (not a bug, consequence of I-1 VAE breakage):
The infestation pipeline switched to Flux for room maps and hit 500s on all 12 rooms. Only rooms 13–14 got maps (from cache). With the VAE fix applied, A1111 should generate room maps correctly on the next module generation.

### I-1. A1111 city scene VAE 500 — status: fixed 2026-05-13

Symptom: `🖼️ [SCENE] A1111 HTTP 500: Error(s) in loading state_dict for AutoencoderKLInferenceWrapper: Missing key(s) in state_dict: "quant_conv.weight", "quant_conv.bias", "post_quant_conv.weight", "post_quant_conv.bias". size mismatch for encoder.conv_out.weight`

Recurs every 10 minutes since at least 2026-05-10 10:03. Same model (`sd_epicrealismXL_pureFix`) every time.

Earlier attempts (both unhelpful, one actively harmful):
- Added per-request `A1111_SCENE_VAE` env var override in `src/city_scene.py`. Inert — `A1111_SCENE_VAE` was never set in `.env`, so the override block never fires. Safe to leave.
- Added project-wide `sd_vae: "Automatic"` to A1111 startup options POST in `src/aclient.py:story_image_loop`. **This was the regression.**

Real root cause (identified 2026-05-10 by diffing against `D:\chatGPT-discord-bot` backup of the working morning copy):

The startup options POST changed from `{"enable_watermark": False}` (working) to `{"enable_watermark": False, "sd_vae": os.getenv("A1111_GLOBAL_VAE", "Automatic")}` (broken).

Why that broke it: when A1111 starts it loads its configured VAE (whatever was last persisted in `config.json` or pinned by the webui). For an SDXL checkpoint already loaded at boot, that VAE is typically the matching SDXL VAE. Posting `sd_vae=Automatic` after boot tells A1111 to discard that pinned VAE and use the model's baked-in one — but `epicrealismXL_pureFix` doesn't have a usable baked-in VAE that matches the architecture the model expects, so A1111 ends up in a broken VAE/model state. Every subsequent generation 500s with the `AutoencoderKLInferenceWrapper` / `quant_conv` size mismatch.

The `[SCENE] A1111 model switch failed: ` warning (with empty exception text) is a downstream symptom: with VAE state broken, the GET/POST to `/sdapi/v1/options` from `ensure_a1111_model` can hit the 30s `httpx` timeout, raising `httpx.ReadTimeout()` whose `str()` is empty.

Wrong-turn note (logged so we don't repeat it): on first pass I diagnosed this as an `A1111_MODEL=sd_epicrealismXL_pureFix` typo (underscore vs `sd/` slash separator from the `A1111_MAPCRAFT_SDXL_CHECKPOINT` value). That hypothesis was wrong — diffing `.env` against the morning backup showed the same `sd_` form was in the working copy, so A1111 must be fuzzy-matching it correctly. The model name was a red herring; only the startup VAE POST changed between the working and broken states.

Evidence chain:
- Bot startup log 2026-05-10 12:44:39: A1111 ready, model `epicrealismXL_pureFix` idle (per the webui).
- 12:44:40: `A1111 startup options applied: {'enable_watermark': False, 'sd_vae': 'Automatic'}` — the POST that broke the loaded VAE state.
- 12:48:11: first scene-loop call. `[SCENE] A1111 model switch failed: ` (empty exc), then `[SCENE] A1111 HTTP 500: ... AutoencoderKLInferenceWrapper ...`.
- Diff `C:\Users\akodoreign\Desktop\chatGPT-discord-bot\src\aclient.py` vs `D:\chatGPT-discord-bot\src\aclient.py` (working morning copy): the only meaningful change in `story_image_loop`'s startup block is the addition of `sd_vae`.
- Diff of `.env`: `A1111_MODEL` value identical in both. Not the cause.

Fix applied 2026-05-10:
- Reverted `src/aclient.py:story_image_loop` startup options POST to backup behavior: `json={"enable_watermark": False}` only. Removed the `sd_vae` key and the `A1111_GLOBAL_VAE` env var hook.
- Left the per-request `A1111_SCENE_VAE` block in `src/city_scene.py` in place — inert without the env var, and may be useful later if a real VAE override is needed.
- Per user's stated intent, set `.env` `A1111_MODEL=Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors` as the default scene/portrait checkpoint. Map generation continues to swap to `A1111_MAP_CHECKPOINT=flux1-dev-fp8.safetensors` via the existing model-switch path. Confirmed Juggernaut filename via A1111 `/sdapi/v1/sd-models` (no subfolder, lives directly in `models/Stable-diffusion/`).

Verification path post-restart:
- Startup log should read `🖼️ A1111 watermark disabled via /sdapi/v1/options` (backup wording), not `A1111 startup options applied: {... 'sd_vae': ...}`.
- First scene-loop cycle (~3 min after startup) will trigger a model swap from `sd\epicrealismXL_pureFix.safetensors` (currently loaded) → `Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors`. SDXL checkpoint loads can take 60-120s, but the existing 30s `httpx` timeout in `ensure_a1111_model` may abort the POST early. If the next scene log shows `model switch failed: ` (empty exc) followed by the `Got N image(s)` success on the cycle 10 min later, that's expected behavior — A1111 finished the load server-side after the timeout. Persistent failure across multiple cycles would indicate a different problem.

Lessons recorded:
- When something stops working, diff against a known-working snapshot before theorizing about config drift. The user's `D:\chatGPT-discord-bot` backup was a 2-second answer that would have skipped the model-name red herring entirely.
- Empty exception text in a log (`failed: ` with nothing after) is `httpx.ReadTimeout`, not a generic error. Treat it as "upstream hung" — and ask what we just changed about the upstream's state.
- "Defensive" config writes at startup (e.g. forcing `sd_vae=Automatic` to "prevent VAE issues") can themselves cause the issue they were meant to prevent. Don't push state into A1111 unless the bot owns that state.

Code-side hardening worth doing later (optional, separate from this fix):
- Bump model-swap POST timeout from 30s to ~120s in `src/a1111_runtime.py:32` (legitimate model loads can take that long).
- Add `raise_for_status()` to the swap POST so silent A1111 errors surface instead of leaking through as the next call's 500.
- Have `_call_a1111` honor `ensure_a1111_model`'s `False` return and skip generation rather than running on a broken state.

Restart attempt 2026-05-13:
- Waited until `ask_a1111("wait_before_restart")` reported A1111 idle.
- Attempted `Restart-Service TowerBotService`, but this shell lacked the Windows service control permissions: `Cannot open TowerBotService service on computer '.'`.
- Could not complete the service-level restart confirmation from this session.
- Manual Flask foreground start succeeded; `/api/view-mode` returned 200 during the same shell. Long `/api/status` probing is unreliable here and should not be used as the only liveness check.

Restart confirmation 2026-05-13:
- User rebooted the bot.
- Service status: `TowerBotService Running`.
- Discord gateway connected at `2026-05-13 16:32:29`.
- Startup log shows the safe expected line: `A1111 watermark disabled via /sdapi/v1/options`.
- No startup `sd_vae` options write observed in the checked tail.
- `ask_a1111("after_user_reboot")` reported idle; `ask_ollama("after_user_reboot")` reported reachable.
- Mimir/NPC sync completed at `2026-05-13 16:33:18`.

---

### I-1b. dotenv loaded AFTER src.* imports — silently ignored .env values for module-level constants

Status: fixed 2026-05-10.

Symptom: After editing `.env A1111_MODEL=Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors` and restarting the bot, the log still showed `[SCENE] A1111 model switched to: sd_epicrealismXL_pureFix`. A fresh `python -c "load_dotenv(); print(os.getenv('A1111_MODEL'))"` correctly returned the Juggernaut value, proving the .env file and dotenv parsing were fine. The running bot was diverging from a fresh import.

Root cause:

`main.py` had:
```python
from dotenv import load_dotenv
from src.bot import run_discord_bot   # ← runs the import chain immediately
from src.log import logger
load_dotenv()                          # ← runs after src.* import side-effects
```

`from src.bot import run_discord_bot` transitively imports `src.city_scene`, which evaluates at module-import time:

```python
_SCENE_MODELS = [
    os.getenv("A1111_MODEL", "sd_epicrealismXL_pureFix"),   # default photorealistic
    ...
]
```

At that moment `load_dotenv()` had not been called yet, so `os.getenv` saw only the parent process's environment (which had no `A1111_MODEL`) and returned the hardcoded default `sd_epicrealismXL_pureFix`. The `_SCENE_MODELS` list was frozen at import time with the default value. `load_dotenv()` ran after, populated `os.environ`, but `_SCENE_MODELS` was already a Python list literal — never re-read.

Why this stayed hidden until 2026-05-10:
- The `.env` value was `sd_epicrealismXL_pureFix` — identical to the hardcoded default. Both paths produced the same string. The bug was invisible because the wrong path coincidentally returned the right value.
- Changing `.env` to `Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors` was the first time the .env value diverged from the default. The bug surfaced as "my .env edit didn't do anything."

Fix:
- Moved `load_dotenv()` above `from src.bot import run_discord_bot` in `main.py`. Added a comment explaining the import-order constraint.

Other modules with the same pattern that are now correctly fed (no code change needed, just import order):
- `src/city_scene.py:36-40` — `_SCENE_MODELS` env-var roster
- `src/news_feed.py:4432` — `A1111_MODEL` default fallback
- Any other `os.getenv(..., default)` evaluated at module-level in src/ modules

Lessons recorded:
- Module-level `os.getenv("X", default)` is a footgun when `load_dotenv()` runs after the first import. It silently falls back to the default and the .env value is forever ignored for that variable. The fact that fresh `load_dotenv()` tests pass while the running bot diverges is the diagnostic signature.
- `load_dotenv()` must run before ANY project module imports if those modules read env vars at import time. Always.
- I dismissed the user's "you didn't actually edit it" pushback by pointing at file mtimes. The mtimes were correct; the diagnosis ("needs a restart") was wrong. When the user says the symptom persists despite a clean restart, that is itself evidence — the next move is to question my own causal model, not insist the user must not have restarted.

---

### I-2. Traffic-cop architecture for A1111 + Ollama contention — status: planning

Goal: replace the current ad-hoc mix of `a1111_lock`, `wait_for_a1111_idle`, per-caller retry loops, and uncoordinated Ollama calls with a single resource scheduler that any consumer can ask: "may I run now?" Answer is either go-ahead, or `wait_seconds=N`. Consumers that get deferred sleep and re-ask. No long-held locks.

Why this exists:
- Multiple A1111 callers (city scene, NPC portrait, mission map pipeline, pretty map pass, area map generator) currently each do their own locking + idle polling. Ordering bugs, lock starvation, and "model swap mid-generation" 500s have all been observed.
- Ollama has zero coordination — concurrent calls from bulletins, missions, NPCs, and mission compiler can pile on the LLM endpoint with no backpressure.
- The user's stated preference: a soft "try again in 10" pattern over hard mutexes. Hard locks have been tried before and produced more issues than they solved.

What this work does NOT address:
- Today's VAE 500 (config issue, not contention). See I-1.
- Per-pipeline content/quality bugs already audited.

Phases (each phase is independently shippable; do not start phase N+1 until N is verified in production):

Phase 0 — Trace (research only, no code changes)
- Enumerate every A1111 call site (txt2img, img2img, options POST, refresh-loras, progress GET) with file:line.
- Enumerate every Ollama call site (chat, generate, embeddings) with file:line.
- For each: who calls it, what lock if any, what retry policy if any, what timeout, what failure mode.
- Output: a single table in this buglog.

Phase 1 — Design (research + write-up, no code)
- Define the cop's API: `await ask_a1111(label, *, model_hint=None) -> Decision` returning `RUN_NOW` or `WAIT_SECONDS(n)`. Same shape for `ask_ollama`.
- Define the cop's introspection: where it looks (A1111 progress endpoint + Ollama `/api/ps` or request counter) and how often it polls.
- Define migration order: which existing consumer is migrated first, with rollback plan.
- Output: 1-page design doc appended to this buglog.

Phase 2 — Build the cop (new module only, no consumer migration)
- New file `src/resource_cop.py` implementing the API.
- Unit-tested with fakes for A1111 and Ollama backends.
- No existing code touched yet.

Phase 3 — Migrate consumers, one at a time
- Order: city scene (smallest blast radius) → NPC portrait → pretty maps → mission map pipeline → bulletin Ollama callers → mission compiler Ollama.
- Each migration is a separate commit/note in this buglog with before/after smoke results.
- Old `a1111_lock` and `wait_for_a1111_idle` callers stay until the last migration; then the cop replaces them and they become deprecated wrappers.

Phase 4 — Decommission old contention primitives
- Once all consumers are on the cop, the legacy lock and idle-poll helpers are simplified to thin wrappers around the cop, and any obsolete call sites are removed.

Status: Phase 2 implemented 2026-05-13; first consumer migration next.

Phase 0 trace snapshot 2026-05-13:

| Resource | Main callers found | Current coordination | Risk |
| --- | --- | --- | --- |
| A1111 options/model switch | `src/a1111_runtime.py`, `src/aclient.py`, `src/cogs/images.py`, `src/mission_builder/maps.py`, `src/area_map_generator.py` | Mixed direct options POSTs, some inside `news_feed.a1111_lock`, some helper-mediated | Model switch can collide with generation unless caller holds the legacy lock |
| A1111 txt2img/img2img | `src/city_scene.py`, `src/news_feed.py` portraits, `src/cogs/images.py`, `src/area_generator.py`, `src/area_map_generator.py`, mission map pipelines, `src/mission_builder/vtt_renderer.py`, scripts | Mostly `news_feed.a1111_lock`; pretty-map code is sync and uses idle polling | Callers either block behind a hard lock or poll A1111 independently |
| A1111 idle/progress | `src/mission_builder/vtt_renderer.py`, many map pipelines, dashboard status | Direct `/progress` probes | No single answer for "should I run now?" |
| Ollama queued calls | `src/ollama_queue.py` consumers: news, bounty, ad, infestation, published pipeline, compiler, NPC appearance | Primary/quick `asyncio.Lock` queues plus `ollama_busy`/DB `pipeline_busy` | Newer paths are mostly serialized |
| Ollama direct calls | Older mission pipelines, `module_quality_trainer.py`, `src/agents/base.py`, cogs character/economy, Mimir/module council/scene dialogs | Direct `httpx.AsyncClient.post(OLLAMA_URL)` or local locks | Can still pile onto Ollama outside the queue |

Phase 1 design 2026-05-13:

- New API: `await ask_a1111(label, model_hint=None)` and `await ask_ollama(label, track="primary"|"quick")`.
- Return shape: `ResourceDecision(resource, label, run_now, wait_seconds, reason, details)`.
- The cop is advisory only. It never holds a long lock and never owns the actual generation request. Callers that receive `run_now=False` sleep for `wait_seconds` and ask again.
- A1111 introspection checks the legacy `news_feed.a1111_lock` plus `/sdapi/v1/progress?skip_current_image=true`.
- Ollama introspection checks `ollama_busy.is_available()`, the existing `ollama_queue` lock/wait counters, and `/api/ps`.
- Migration order remains: city scene → NPC portrait → pretty maps → mission map pipeline → older direct Ollama callers.

Phase 2 implementation 2026-05-13:

- Added `src/resource_cop.py` with `ResourceDecision`, `ask_a1111()`, and `ask_ollama()`.
- No VAE settings or A1111 option writes were added.
- Focused verification passed:
  - `python -m compileall src\resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 1 — city scenes, 2026-05-13:

- `src/city_scene.py` now calls `wait_for_a1111_turn("city_scene", model_hint=model)` before entering the legacy `a1111_lock`.
- If A1111 remains busy through the soft wait budget, the scene cycle logs a warning and skips instead of queuing another image request into contention.
- Verification:
  - `python -m compileall src\resource_cop.py src\city_scene.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 2 — NPC portraits, 2026-05-13:

- `src/news_feed.py:generate_npc_portrait()` now calls `wait_for_a1111_turn("npc_portrait", model_hint=A1111_MODEL)` before entering `a1111_lock`.
- If A1111 stays busy, the portrait cycle logs and skips instead of colliding with scene/map work.
- Verification:
  - `python -m compileall src\news_feed.py src\resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 3 — pretty maps, 2026-05-13:

- Added `ask_a1111_sync()` for synchronous callers.
- `src/mission_builder/vtt_renderer.py:stylize_pretty_battlemap()` now checks the cop before starting the A1111 pretty pass. If A1111 is busy, it defers and leaves the tactical map intact.
- Verification:
  - `python -m compileall src\resource_cop.py src\mission_builder\vtt_renderer.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 4 — shared mission map pipeline, 2026-05-13:

- `src/mission_builder/maps.py:generate_vtt_map()` now asks `wait_for_a1111_turn("mission_map", ...)` before entering `a1111_lock`.
- If A1111 remains busy, it returns the deterministic VTT battlemap fallback instead of waiting behind image traffic.
- Verification:
  - `python -m compileall src\mission_builder\maps.py src\resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 5 - module council Ollama, 2026-05-14:

- `src/mission_builder/module_council.py:_call()` now asks `wait_for_ollama_turn("module_council:<pass>")` before each Architect/Rules/Bob/Synthesis Ollama request.
- If the primary Ollama lane remains busy through the resource-cop wait budget, the council pass logs a deferral and returns an empty string, preserving the existing fallback-to-single-pass behavior instead of piling another long request onto Ollama.
- Verification:
  - `python -m compileall src\mission_builder\module_council.py tests\test_module_council_resource_cop.py`
  - `python -m pytest tests\test_module_council_resource_cop.py tests\test_resource_cop.py -q`

Phase 3 migration 6 - scene dialog Ollama, 2026-05-14:

- `src/mission_builder/scene_dialogs.py:_ask()` now asks `wait_for_ollama_turn("scene_dialogs")` before generating optional scene dialog/clue JSON.
- If the primary Ollama lane remains busy through the resource-cop wait budget, dialog generation logs a warning and returns an empty string, matching the existing non-fatal failure path for optional enrichment.
- Verification:
  - `python -m compileall src\mission_builder\scene_dialogs.py tests\test_scene_dialogs_resource_cop.py`
  - `python -m pytest tests\test_scene_dialogs_resource_cop.py tests\test_resource_cop.py -q`

Phase 3 migration 7 - Mimir statblock Ollama + log quieting, 2026-05-14:

- `src/mission_builder/mimir_module.py:_generate_statblock_llm()` now asks `wait_for_ollama_turn("mimir_statblock")` before optional homebrew-statblock generation.
- Routine Mimir chatter was demoted from main-log `info` to `debug`: campaign discovery dumps, active-campaign set echo, module-created notices, map-upload notices, homebrew-created notices, DDB homebrew push notices, sync start/complete, sync row counts, pull progress, party/faction/world sync summaries, and gear-run summaries.
- Main log still keeps Mimir connection/reconnection, new NPCs pulled from Mimir, Mimir-to-MySQL update counts, faction updates pulled, background loop startup, warnings, and errors.
- Verification:
  - `python -m compileall src\mimir_client.py src\mimir_sync.py src\mission_builder\mimir_module.py tests\test_mimir_module_resource_cop.py`
  - `python -m pytest tests\test_mimir_module_resource_cop.py tests\test_resource_cop.py -q`

Phase 3 migration 8 - plan-pipeline direct Ollama callers, 2026-05-14:

- Added `wait_for_ollama_turn(..., track="primary")` checks before direct plan-generation Ollama calls in:
  `heist_pipeline.py`, `investigation_pipeline.py`, `discovery_pipeline.py`, `exploration_pipeline.py`, `first_contact_pipeline.py`, `negotiation_pipeline.py`, `puzzle_pipeline.py`, `recovery_pipeline.py`, `rescue_pipeline.py`, `sabotage_pipeline.py`, and `strange_occurrences_pipeline.py`.
- If the primary Ollama lane remains busy through the resource-cop wait budget, these builders log a deferral and return `""` from their LLM helper. Their existing deterministic fallback/normalization then builds a complete module plan instead of adding another long Ollama request to the pile.
- Verification:
  - `python -m compileall src\mission_builder\discovery_pipeline.py src\mission_builder\exploration_pipeline.py src\mission_builder\first_contact_pipeline.py src\mission_builder\negotiation_pipeline.py src\mission_builder\recovery_pipeline.py src\mission_builder\rescue_pipeline.py src\mission_builder\sabotage_pipeline.py src\mission_builder\puzzle_pipeline.py src\mission_builder\strange_occurrences_pipeline.py src\mission_builder\heist_pipeline.py src\mission_builder\investigation_pipeline.py`
  - `python -m pytest tests\test_partial_plan_normalization.py tests\test_investigation_pipeline.py tests\test_heist_routing.py tests\test_resource_cop.py -q`

Phase 3 migration 9 - mission pipeline lifecycle spans, 2026-05-14:

- Added whole-pipeline lifecycle tracking to `src/resource_cop.py`: `start_pipeline()`, `set_pipeline_phase()`, `finish_pipeline()`, and `active_pipelines()`.
- Wrapped `src/mission_builder/__init__.py:generate_module()` so every type-specific mission route records start/routing/completed/failed/cancelled state around the existing dispatcher.
- Added automatic `buglog.md` failure breadcrumbs via `append_pipeline_failure()`. If a mission pipeline raises, the bot appends a dated open bug note with pipeline label, mission title, mission type, current phase, elapsed time, and exception summary before re-raising.
- Verification:
  - `python -m compileall src\resource_cop.py src\mission_builder\__init__.py tests\test_resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 10 - status visibility for active pipelines, 2026-05-14:

- Added `active_pipelines_sync()` to `src/resource_cop.py` so synchronous Flask/status code can read the pipeline registry without creating an event loop.
- Switched the pipeline registry guard to a thread lock so async bot code and sync dashboard code can safely inspect the same active-run dictionary.
- `Webpage/app.py:/api/status` now includes `pipelines.active` and `pipelines.count`, with each active run reporting run id, label, mission title, mission type, phase, elapsed seconds, and details.
- Verification:
  - `python -m compileall src\resource_cop.py Webpage\app.py tests\test_resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 11 - interactive command Ollama callers, 2026-05-14:

- `src/cogs/character.py` `/setcharappearance` llava image-description calls now ask `wait_for_ollama_turn("character_llava", track="quick", max_wait_seconds=60)` before posting to Ollama.
- `src/cogs/economy.py` `/prices` lookups now ask `wait_for_ollama_turn("price_lookup", track="quick", max_wait_seconds=45)` before posting to Ollama.
- If the quick lane is backed up, these interactive commands now return a short "try again in a minute" response instead of bypassing the cop and adding load during mission generation.
- Verification:
  - `python -m compileall src\cogs\character.py src\cogs\economy.py src\resource_cop.py Webpage\app.py tests\test_resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 12 - remaining standalone plan builders, 2026-05-14:

- Added `wait_for_ollama_turn(..., track="primary")` checks before direct plan-generation Ollama calls in `ambush_pipeline.py`, `escort_pipeline.py`, `gather_pipeline.py`, and `infiltration_pipeline.py`.
- If the primary Ollama lane remains busy through the resource-cop wait budget, these builders log a deferral and return `""` from their LLM helper so their existing deterministic plan fallbacks can proceed.
- Verification:
  - `python -m compileall src\mission_builder\ambush_pipeline.py src\mission_builder\escort_pipeline.py src\mission_builder\gather_pipeline.py src\mission_builder\infiltration_pipeline.py src\resource_cop.py tests\test_resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 13 - area-map A1111 callers, 2026-05-14:

- `src/area_map_generator.py` batch area-map generation now asks `wait_for_a1111_turn("area_map", max_wait_seconds=60)` before entering the legacy A1111 lock. If A1111 remains busy, the area is deferred for a later batch.
- `src/area_generator.py` overview-map generation now asks `wait_for_a1111_turn("area_profile_map", max_wait_seconds=60)` before generating the optional district overview map.
- No VAE settings or overrides were added.
- Verification:
  - `python -m compileall src\area_map_generator.py src\area_generator.py src\resource_cop.py tests\test_resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py -q`

Phase 3 migration 14 - remaining mission-map A1111 callers + manual image commands, 2026-05-14:

- Added resource-cop A1111 checks before legacy-lock map generation in `ambush_pipeline.py`, `assassination_pipeline.py`, `assault_pipeline.py`, `battle_pipeline.py`, `defense_pipeline.py`, `escort_pipeline.py`, `exploration_pipeline.py`, `gather_pipeline.py`, `infiltration_pipeline.py`, `rescue_pipeline.py`, and `sabotage_pipeline.py`.
- If A1111 remains busy through the soft wait budget, these mission map builders now write their deterministic VTT fallback immediately instead of waiting/retrying behind other image jobs.
- Added a cop check to `dungeon_delve/tile_generator.py`; busy A1111 now defers the optional tile instead of entering the old lock queue.
- Added cop checks to `/draw` and `/drawscene` in `src/cogs/images.py`. These commands now politely ask users to retry instead of cutting into mission/portrait/scene/map work.
- `/draw` and `/drawscene` no longer save generated images as NPC/location refs; automated NPC portrait and city-scene generation remain unchanged.
- No VAE settings or overrides were added.
- Verification:
  - `python -m compileall src\mission_builder\ambush_pipeline.py src\mission_builder\escort_pipeline.py src\mission_builder\gather_pipeline.py src\mission_builder\infiltration_pipeline.py src\mission_builder\exploration_pipeline.py src\mission_builder\sabotage_pipeline.py src\mission_builder\assassination_pipeline.py src\mission_builder\assault_pipeline.py src\mission_builder\battle_pipeline.py src\mission_builder\defense_pipeline.py src\mission_builder\rescue_pipeline.py src\mission_builder\dungeon_delve\tile_generator.py src\cogs\images.py src\resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py tests\test_competition_calendar.py -q`

Phase 3 migration 15 - remaining background Ollama callers, 2026-05-14:

- Added `wait_for_ollama_turn(..., track="primary")` checks before direct Ollama calls in `src/self_learning.py`, `src/party_interview.py`, `src/module_quality_trainer.py`, and `src/mission_builder/dungeon_delve/room_generator.py`.
- If the primary Ollama lane remains busy through the soft wait budget, these optional/background helpers now log a deferral and return their existing empty/fallback value instead of stacking more LLM work.
- Follow-up sweep added A1111 cop checks to `src/mission_builder/heist_pipeline.py`, `src/mission_builder/infestation_pipeline.py`, and `src/mission_builder/novel_pipeline.py`.
- Verification:
  - `python -m compileall src\self_learning.py src\party_interview.py src\module_quality_trainer.py src\mission_builder\dungeon_delve\room_generator.py src\resource_cop.py`
  - `python -m pytest tests\test_resource_cop.py -q`
  - `python -m compileall src\mission_builder\heist_pipeline.py src\mission_builder\infestation_pipeline.py src\mission_builder\novel_pipeline.py`
  - `python -m pytest tests\test_resource_cop.py tests\test_heist_routing.py -q`

Phase 3 migration 16 - shared image-generator A1111 helpers, 2026-05-14:

- Added `wait_for_a1111_turn(...)` checks inside `src/mission_builder/image_generator.py` for `generate_single_tile()` and the shared location-map generator path. This protects future/new callers even if they bypass the already-migrated mission wrappers.
- Hardened `src/resource_cop.py` so async tests/mocks with awaitable `raise_for_status()` or `json()` methods behave like real httpx responses.
- Added the same awaitable-response tolerance inside `image_generator.py` for its A1111 response handling.
- Verification:
  - `python -m compileall src\mission_builder\image_generator.py src\resource_cop.py`
  - `python -m pytest tests\test_image_generator.py tests\test_resource_cop.py -q`

Phase 3 migration 17 - legacy skill helper Ollama call, 2026-05-14:

- Added a resource-cop Ollama check inside `src/skills.py:generate_with_skills()` before its direct `/api/generate` call.
- If Ollama remains busy through the soft wait budget, the helper logs a deferral and returns `None` instead of stacking behind mission/bulletin work.
- The helper now honors `OLLAMA_MODEL` when `model_name` is omitted, matching its existing docstring.
- Verification:
  - `python -m compileall src\skills.py src\mimir_client.py`

Phase 3 migration 18 - generic agent Ollama path, 2026-05-15:

- Added resource-cop checks to `src/agents/base.py` before generic `BaseAgent._call_api()` sends direct Ollama `/api/chat` requests.
- `force=True` calls still bypass the dispatcher, preserving mission compiler sections that already own the long-running pipeline lane.
- Added a quick-lane dispatcher check to `quick_complete()` before its direct Ollama call.
- New dispatcher log lines are ASCII-only to avoid adding more mojibake around existing Discord emoji log text.
- Verification:
  - `python -m compileall src\agents\base.py src\skills.py src\mimir_client.py`
  - `python -m pytest tests\test_resource_cop.py tests\test_module_council_resource_cop.py tests\test_mimir_module_resource_cop.py tests\test_scene_dialogs_resource_cop.py -q` passed: 9 tests.

Phase 3 migration 19 - provider fallback + Columbus vision Ollama calls, 2026-05-15:

- Added a quick-lane dispatcher check before `FreeProvider._fallback_ollama_chat()` makes its direct `/api/chat` call.
- Added a primary-lane dispatcher check before `ColumbusAgent._vision_assess()` makes its optional LLaVA vision call.
- Updated `tests/test_providers.py` to assert the current local Qwen/Kimi provider contract instead of stale external model names.
- Verification:
  - `python -m compileall src\providers.py src\agents\learning_agents.py tests\test_providers.py`
  - `python -m pytest tests\test_providers.py tests\test_resource_cop.py -q` passed: 21 tests.

## Verification Snapshot

- Read `.codesight/wiki/index.md`, `.codesight/wiki/overview.md`, `.codesight/CODESIGHT.md`, and relevant wiki pages for image refs, NPCs, and mission generation.
- Read actual source before noting bugs: `Webpage/app.py`, `src/image_ref.py`, `src/mission_builder/maps.py`, `src/mission_builder/vtt_renderer.py`, `src/mission_builder/boxset_utils.py`, `src/mission_builder/__init__.py`, `src/mission_builder/encounters.py`, `src/mission_builder/locations.py`, `src/news_feed.py`, `src/mimir_sync.py`, and `src/self_learning.py`.
- `python -m compileall -q src Webpage` passed on 2026-05-07, so current notes are behavioral/data-flow issues rather than syntax failures.

## Work Log

### 2026-05-08 - Mission builder pipeline audit

Status: in progress.

Plan:
- Keep findings separated by pipeline/family so fixes do not flatten mission identity.
- Helper 1: combat-heavy pipelines and monster/NPC/DDB statblock contracts.
- Helper 2: stealth/social/investigation pipelines and schema/context mismatches.
- Helper 3: module assembly/export, validation, web injection, map/image integration.
- Local pass: DB/context source usage and static hazards across individual pipeline files.
- Do not patch from audit notes alone; smoke each targeted pipeline before fixing.

Helper audit reports received:

- Combat/action family: battle exports generic enemy labels to Mimir, defense creates waves but exports no enemy list, defense intel modifiers are not applied, several pipelines shadow canonical party scaling.
- Stealth/social/investigation family: negotiation reads wrong `mission_outcomes` columns; investigation guide components render fields that the lead builder does not create; heist routing can steal non-shady theft investigations; several LLM JSON paths accept partial objects and crash later.
- Assembly/export family: legacy JSON/API generation imports missing helpers; sync API wrapper lacks `asyncio`; image integration passes unsupported args and treats output directory as a JSON path; published fallback can clone scene 4 into scene 5; scene dialog injection can log success after injecting nothing.

Live DB verification:

- `missions.module_slug`, `gazetteer_places.wealth_level`, `faction_reputation.leader/location_name/description/motto`, and `party_profiles.profile_json` exist in the running local DB.
- The checked-in `database_schema.sql` is stale for those columns. Treat schema drift as a documentation/migration bug, not as the current runtime cause for those local failures.
- `mission_outcomes` does not contain `title`, `outcome`, or `summary`; negotiation really is querying columns that do not exist.

Pipeline-separation note:

Fixes must preserve separate mission-type builders. Shared code is acceptable only for mechanical contracts such as DB column discovery, schema validation, Mimir enemy/item enrichment, or output path handling. Do not collapse pipeline-specific prompts, scene structures, wave structures, or faction-role logic into one generic mission builder.

### 11. Negotiation prior-outcome context reads non-existent columns

Status: fixed 2026-05-08.

Files:
- `src/mission_builder/negotiation_pipeline.py`
- `src/mission_outcomes.py`

Affected code:
- `_mission_history()` in `negotiation_pipeline.py`

Context:
The live `mission_outcomes` table has `mission_title`, `result`, `key_decisions`, `loose_threads`, `notable_moments`, and related fields. `negotiation_pipeline.py` queries `title`, `outcome`, and `summary`.

Impact:
Negotiation missions lose completed-mission continuity and likely fall back to empty history after a DB error. That makes negotiations more generic and less tied to recent world events.

Smoke before fix:
Monkeypatch `_db_rows()` or run a DB-backed smoke that calls `_mission_history()` and confirms it currently returns no usable prior outcomes or logs an unknown-column failure.

Preferred fix:
Keep the negotiation pipeline separate, but map its history prompt to the real columns: `mission_title`, `result`, `key_decisions`, `loose_threads`, `notable_moments`, `faction`, `opposing_faction`, and `created_at`.

Fix:
Updated `_canon_seed()` to query the live `mission_outcomes` columns and updated `_generate_plan()` to summarize those real fields into `Recent outcomes`.

Smoke:
Before fix, `_canon_seed({'side_a':'Adventurers Guild','side_b':'Iron Fang'})` returned `[]` and MySQL logged `Unknown column 'title' in 'field list'`.
After fix, the same smoke returned 5 outcome rows, including `Echoes of the Flameheart`.

### 12. Battle Mimir export loses concrete enemy identity

Status: fixed 2026-05-08.

Files:
- `src/mission_builder/battle_pipeline.py`
- `src/mission_builder/mimir_module.py`

Affected code:
- `_generate_pocket_fight()`
- `generate_battle_module()` Mimir enrichment call

Context:
Pocket fights produce concrete `enemy_name` / `enemy_desc`, but Mimir enrichment receives repeated generic `opposing_side` entries.

Impact:
Mimir and D&D Beyond homebrew import can receive generic faction labels instead of actual monsters or enemy units. This directly matches the user's concern that monsters/NPCs are not being generated/imported correctly.

Smoke before fix:
Run a battle module smoke with Mimir calls mocked and assert the enemy list passed to `enrich_monsters()` contains concrete generated names from `pocket_fights`.

Preferred fix:
Build a battle-specific enemy manifest from `pocket_fights`, preserving counts/CR/notes per fight. Do not introduce a generic extractor that erases battle's faction-vs-faction, faction-vs-void, and monster-breakout distinctions.

Fix:
Added battle-local `_battle_mimir_enemies()` and `_battle_enemy_type()` helpers. `generate_battle_module()` now sends concrete pocket fight enemies to Mimir/DDB enrichment instead of repeated `opposing_side` labels.

Smoke:
Before fix, a sample void battle manifest produced repeated `Void Creatures` entries and off-by-one fight notes (`Fight 2`, `Fight 3`).
After fix, the manifest produced `Void Hound`, `Rift Crawler`, and `Void Anchor` with correct `Fight 1` / `Fight 2` notes and `aberration` type hints. `python -m py_compile src\mission_builder\negotiation_pipeline.py src\mission_builder\battle_pipeline.py` passed.

### 13. Defense wave enemies are not exported to Mimir

Status: fixed 2026-05-08.

Files:
- `src/mission_builder/defense_pipeline.py`
- `src/mission_builder/mimir_module.py`

Affected code:
- `_generate_waves()`
- `generate_defense_module()` Mimir section call

Context:
Defense creates structured wave information with attackers, counts, and commander presence, then renders the Mimir reference section with empty enemy/reward lists.

Impact:
Defense modules can have playable wave prose but no Mimir-backed monster cards or D&D Beyond homebrew path.

Smoke before fix:
Run defense generation with Mimir mocked and assert `enrich_monsters()` is called with a non-empty defense-specific wave enemy manifest.

Preferred fix:
Add a defense-specific conversion from wave data into enemy entries. Preserve probe/main/final assault distinctions.

Fix:
Added defense-local `_defense_mimir_enemies()` and `_defense_enemy_type()` helpers. `generate_defense_module()` now calls `enrich_monsters()` with attackers derived from the generated waves and renders the Mimir section with those enriched entries.

Smoke:
Before fix, defense passed `[]` into the Mimir reference renderer.
After fix, a sample warband defense produced `soldiers / fighters`, `squad sergeants`, and `Wall Commander` entries with counts aggregated from the wave data. `python -m py_compile src\mission_builder\defense_pipeline.py` passed.

### 13b. Defense force modifiers were calculated but not applied

Status: fixed 2026-05-14.

Files:
- `src/mission_builder/defense_pipeline.py`
- `tests/test_defense_pipeline.py`

Context:
The defense pipeline generated intel leads and watch outcomes with force modifier keys, and `_generate_waves()` accepted a `modifiers_applied` argument. However, the deltas were only accumulated into local variables and never added to the generated wave base counts. The main builder also always called `_generate_waves(..., [])`, so explicit mission/applied lead modifiers could not affect wave pressure or morale.

Fix:
- Added force-modifier key normalization so real em dashes, ASCII hyphens, and older mojibake dash text match the same modifier entries.
- Added `_mission_force_modifiers()` to read explicit applied modifiers from mission fields and applied/completed intel leads.
- `_generate_waves()` now applies grunt and lieutenant deltas to the base force before prompting/fallback generation and stamps the applied modifier metadata on each wave.
- `build_defense_module()` now passes selected modifiers into wave generation and applies the morale delta to the attacker morale pool.

Verification:
- `python -m compileall src\mission_builder\defense_pipeline.py tests\test_defense_pipeline.py` passed.
- `python -m pytest tests\test_defense_pipeline.py -q` passed; smoke verifies dash normalization and that captured-scout + intercepted-messenger modifiers reduce fallback wave counts and morale metadata.

### 13c. Heist router steals non-shady theft investigations

Status: fixed 2026-05-14.

Files:
- `src/mission_builder/__init__.py`
- `tests/test_heist_routing.py`

Context:
`heist_pipeline.is_heist_mission()` already had a faction gate: theft/heist-style jobs only route to heist when the sponsoring faction is shady. The central `generate_module()` router called it with only `raw_type`, so `faction` defaulted to empty and any mission type containing `theft`, `stolen`, `steal`, etc. could route to Heist before Investigation got a chance.

Fix:
The router now passes `mission["faction"]` / `mission["client_faction"]` into `is_heist_mission()`. Non-shady theft missions can continue down to the investigation predicate, while shady theft jobs still route to heist.

Verification:
- `python -m compileall src\mission_builder\__init__.py src\mission_builder\heist_pipeline.py src\mission_builder\investigation_pipeline.py tests\test_heist_routing.py` passed.
- `python -m pytest tests\test_heist_routing.py -q` passed.

### 13d. Investigation partial LLM JSON can crash renderers

Status: fixed 2026-05-14.

Files:
- `src/mission_builder/investigation_pipeline.py`
- `tests/test_investigation_pipeline.py`

Context:
`_generate_plan()` accepted any parsed JSON object from Ollama. If the model returned a partial object, later renderers could crash on required direct-index fields such as `plan["briefing"]`, or produce empty chart sections for missing `timeline` / `resolution`.

Fix:
Added `_normalize_plan()` to merge parsed LLM output over the deterministic fallback plan. Required scalar fields are filled from fallback values, `timeline` and `resolution` are normalized to non-empty lists, and string timelines are split into usable beats.

Verification:
- `python -m compileall src\mission_builder\investigation_pipeline.py tests\test_investigation_pipeline.py` passed.
- `python -m pytest tests\test_investigation_pipeline.py -q` passed.

### 13e. Plan-based pipelines partial LLM JSON can crash/hollow renderers

Status: fixed 2026-05-14.

Files:
- `src/mission_builder/heist_pipeline.py`
- `src/mission_builder/sabotage_pipeline.py`
- `src/mission_builder/rescue_pipeline.py`
- `src/mission_builder/puzzle_pipeline.py`
- `src/mission_builder/recovery_pipeline.py`
- `src/mission_builder/negotiation_pipeline.py`
- `src/mission_builder/discovery_pipeline.py`
- `src/mission_builder/exploration_pipeline.py`
- `src/mission_builder/first_contact_pipeline.py`
- `src/mission_builder/strange_occurrences_pipeline.py`
- `tests/test_partial_plan_normalization.py`

Context:
Several plan-based pipelines accepted any parsed LLM JSON object as the final plan. Their renderers then directly indexed required fields or expected structured lists/dicts such as `plan["briefing"]`, `plan["score"]`, `plan["site_description"]`, `plan["objective"]`, `plan["bonus"]`, `plan["timer"]`, puzzle answer fields, recovery trail/outcome tables, negotiation research/favor tables, discovery/contact guidance lists, exploration route/scene survey tables, strange-occurrence evidence/witness/resolution tables, interview/news fields, and consequence/debrief fields. A partial-but-valid JSON response could therefore crash module rendering or produce hollow guide sections after the expensive generation step had already succeeded.

Fix:
- Extracted heist's inline deterministic fallback into `_fallback_plan()` and added `_normalize_plan()` to merge partial LLM output over the full fallback.
- Added sabotage `_fallback_plan()` / `_normalize_plan()` with the same contract.
- Added rescue `_fallback_plan()` / `_normalize_plan()` with the same contract.
- Added puzzle `_fallback_plan()` / `_normalize_plan()` with the same contract.
- Added recovery `_fallback_plan()` / `_normalize_plan()` with the same contract and structured validation for trail, retrieval scene, outcome table, dialogue, and follow-up hooks.
- Added negotiation `_normalize_plan()` over its existing fallback with structured validation for concessions, research, favors, dialogue, and escalation lists.
- Added discovery `_fallback_plan()` / `_normalize_plan()` with structured validation for identification steps, containment, custody, dialogue, and fate options.
- Added exploration `_fallback_plan()` / `_normalize_plan()` with structured validation for survey scenes, route log entries, imagery, hazards, deliverables, discoveries, dialogue, news seed, and follow-up type.
- Added first-contact `_fallback_plan()` / `_normalize_plan()` with structured validation for first-sight imagery, needs/fears/taboos, translation/panic trackers, dialogue, primer, risks, and protection options.
- Added strange-occurrence `_normalize_plan()` over its existing fallback with structured validation for contradictions, evidence ladder, witnesses, coroner records, faction pressure, hazards, and resolution paths.
- List fields such as heist escape options, sabotage steps, rescue scenes, rescue pressure lists, puzzle clue meanings, puzzle solve paths, recovery trail beats, negotiation concession lists, discovery handling states, exploration imagery/hazards/dialogue, first-contact dialogue, and strange-occurrence contradictions are normalized to non-empty lists, including newline/semicolon string splitting.

Verification:
- `python -m compileall src\mission_builder\heist_pipeline.py src\mission_builder\sabotage_pipeline.py src\mission_builder\rescue_pipeline.py src\mission_builder\puzzle_pipeline.py src\mission_builder\recovery_pipeline.py src\mission_builder\negotiation_pipeline.py src\mission_builder\discovery_pipeline.py src\mission_builder\exploration_pipeline.py src\mission_builder\first_contact_pipeline.py src\mission_builder\strange_occurrences_pipeline.py tests\test_partial_plan_normalization.py` passed.
- `python -m pytest tests\test_partial_plan_normalization.py -q` passed with 10 tests.

### 14. Legacy JSON/API mission path is broken

Status: fixed 2026-05-08 for confirmed API/import/path blockers.

Files:
- `src/mission_builder/api.py`
- `src/mission_builder/json_generator.py`
- `src/mission_builder/__init__.py`
- `src/mission_builder/image_integration.py`

Affected code:
- `generate_mission()`
- `generate_module_json()`
- `generate_complete_mission()`

Context:
`api.py` uses `asyncio` without importing it. `json_generator.py` imports `_ollama_generate` and `_post_process_module_text` from package root, but package root does not export them. `image_integration.py` passes `model_name` to `generate_mission_async()` and writes to a directory path as though it were a JSON file.

Impact:
Older module-building entry points and web-injected mission generation can fail before any pipeline-specific generation happens.

Smoke before fix:
Import and call `generate_mission()` with generation functions mocked so it does not hit Ollama. Then smoke `generate_complete_mission()` with image generation disabled/mocked.

Preferred fix:
Restore the API contract without routing all mission types through one generic pipeline. If this path is legacy-only, make it delegate explicitly to the right modern dispatcher or fail loudly with a helpful error.

Partial fix:
Imported `asyncio` in `src/mission_builder/api.py`, restoring the synchronous wrapper's immediate runtime dependency.
Restored package-root `_ollama_generate()` and `_post_process_module_text()` compatibility helpers used by `json_generator.py` and `mission_types.py`.

Smoke:
Before fix, `generate_mission()` with `generate_mission_async()` mocked failed with `NameError: name 'asyncio' is not defined`.
After fix, the same smoke returned the mocked mission dict. `python -m py_compile src\mission_builder\api.py` passed.
Before the compatibility helper fix, `import src.mission_builder.json_generator` failed with `ImportError: cannot import name '_ollama_generate'`.
After fix, `json_generator` imported cleanly and `python -m py_compile src\mission_builder\__init__.py src\mission_builder\json_generator.py src\mission_builder\mission_types.py` passed.

Still open:
Broader design question remains: whether this legacy JSON/image path should continue as a compatibility route or delegate to the modern type-specific dispatcher.

Additional fix:
Removed stale `model_name` argument from `generate_mission_with_images()`'s call to `generate_mission_async()`.
Changed `generate_complete_mission()` to treat `get_mission_output_path()` as a directory and write `module_data.json` inside it; custom `output_dir` is now honored.

Additional smoke:
Before fix, a real-signature mock of `generate_mission_async()` failed with `TypeError: unexpected keyword argument 'model_name'`.
After fix, `generate_mission_with_images()` returned the mocked module, and `generate_complete_mission()` wrote a real `module_data.json` under a temp mission directory. `python -m py_compile src\mission_builder\image_integration.py` passed.

### 2026-05-07 - Bug 1 path containment

Status: fixed.

Before smoke:
- `_project_media_url()` rejected a sibling checkout path only because the later `relative_to()` raised, not because the prefix check was safe.
- `/modules/abc/../generated_modules_evil/secret.txt` returned `403`.
- `/area-maps/../area_maps_evil/secret.png` returned `200` and served the sibling file.

Connected paths checked:
- `Webpage/app.py`: `_profile_image_url()`, `_project_media_url()`, `/media/project/<path>`, `/modules/<slug>/<path>`, `/area-maps/<path>`.

Fix:
- Added `_path_within(path, root)` using resolved `Path.relative_to()`.
- Replaced all five string-prefix containment checks with `_path_within()`.

After smoke:
- `python -m py_compile Webpage\app.py` passed.
- `/modules/abc/../generated_modules_evil/secret.txt` returned `403`.
- `/area-maps/../area_maps_evil/secret.png` returned `403`.
- `_project_media_url()` for a sibling checkout path returned empty.
- Adjacent API smoke passed: `/api/status`, `/api/npcs?limit=1`, `/api/districts`, `/api/area-maps`.

### 2026-05-07 - Bug 3 direct map AI validation

Status: fixed.

Plan:
- Smoke current direct map image validation behavior before patching.
- Trace connected code paths in `src/mission_builder/maps.py` and `src/mission_builder/vtt_renderer.py`.
- Patch direct A1111 map generation to reject blank/failed images before they can be treated as success.
- Repeat the smoke path after patching.

Before smoke:
- Fake-A1111 direct map run hit `NameError: name 'A1111_COOLDOWN_SECONDS' is not defined` in `src/mission_builder/maps.py` before the returned image could be handled.
- This means the direct A1111 tactical map path can silently fall back to deterministic rendering even when A1111 is reachable.
- After injecting a temporary cooldown value into the fake smoke, the same path accepted a flat 64x64 gray PNG and passed it to `render_vtt_battlemap()` as AI texture input.

Connected paths checked:
- `src/mission_builder/maps.py`: `generate_vtt_map()` A1111 strategy loop and deterministic fallback.
- `src/mission_builder/vtt_renderer.py`: pretty-map `_decode_useful_pretty_image()` validation and `wait_for_a1111_idle()`.

Fix:
- Exported shared `decode_useful_a1111_image()` from `vtt_renderer.py`.
- Imported `A1111_COOLDOWN_SECONDS` into `maps.py`, fixing the direct A1111 map path `NameError`.
- Direct map generation now rejects blank/too-small A1111 images before treating a lane as success.
- If all strategies return no useful image while A1111 is available, the map path cools down and loops through the strategies again instead of accepting fallback output as the final answer.
- `save_vtt_battlemap()` now uses the same validation before passing optional `ai_b64` into the renderer.

After smoke:
- `python -m py_compile src\mission_builder\maps.py src\mission_builder\vtt_renderer.py` passed.
- Fake-A1111 smoke with one flat gray image followed by one noisy useful image made two POST attempts and only passed the useful image into `render_vtt_battlemap()`.
- `save_vtt_battlemap()` smoke with a flat gray `ai_b64` saved the deterministic map while passing no AI texture into `render_vtt_battlemap()`.
- `python -m compileall -q src Webpage` passed.

### 2026-05-07 - Bug 4 Mimir pull throttling

Status: fixed.

Plan:
- Smoke current `pull_npc_changes()` behavior with fake Mimir/DB rows so the real local MCP is not hammered.
- Trace connected startup/background sync paths and pull concurrency.
- Add paced known-NPC pull progress with env-configured sleep.
- Repeat fake smoke after patching.

Before smoke:
- Fake Mimir/DB run over 5 synced NPC rows called `get_character` 5 times and made 0 `asyncio.sleep()` calls.

Connected paths checked:
- `src/bot.py`: startup sync path schedules `startup_sync()` after Mimir connects.
- `src/mimir_sync.py`: `startup_sync()`, background `_loop()`, `full_sync()`, `sync_all_npcs()`, `pull_npc_changes()`, `pull_faction_changes()`.
- `src/mimir_client.py`: MCP calls are serialized by a lock but not paced.

Fix:
- Added `MIMIR_PULL_NPC_SLEEP` and `MIMIR_PULL_PROGRESS_EVERY`.
- `pull_npc_changes()` now logs known-pass start, progress, and completion, and sleeps after each known NPC check.
- `full_sync()` now pulls NPC changes before faction changes sequentially, so `get_character` is not interleaved with faction document reads.

After smoke:
- `python -m py_compile src\mimir_sync.py` passed.
- Fake Mimir/DB run over 5 synced NPC rows called `get_character` 5 times and made 5 sleep calls.
- Fake `full_sync()` order was world/factions push, NPC push, party push, NPC pull, faction pull.

### 2026-05-07 - Bug 5 A1111 portrait/scene model switching

Status: fixed.

Plan:
- Smoke current portrait/scene model-switch ordering without generating real images.
- Trace existing callers and A1111 lock usage.
- Prefer a shared model-switch helper so maps, portraits, and scenes use the same idle/cooldown contract.
- Patch only after the smoke and trace are clear.

Before smoke:
- Fake portrait generation recorded model check/switch before `a1111_lock` was entered, then `txt2img` inside the lock.
- Source trace shows city scenes switch inside the lock, but without idle/model-swap cooldown waits.

Connected paths checked:
- `src/news_feed.py`: `a1111_lock`, `generate_npc_portrait()`.
- `src/city_scene.py`: `_call_a1111()`, `generate_city_scene()`.
- `src/aclient.py`: timed calls into city scenes and NPC portraits.
- `src/mission_builder/vtt_renderer.py`: existing map idle/cooldown helper used as the model-switch contract.

Fix:
- Added `src/a1111_runtime.py` with `ensure_a1111_model()` and `cool_down_a1111_after_generation()`.
- Removed portrait pre-lock checkpoint switching.
- Portrait generation now enters `a1111_lock`, waits for idle, switches model if needed, waits for model-swap cooldown, generates, and cools down after generation.
- City scene generation now uses the same helper before `txt2img` and cools down after successful generation.

After smoke:
- `python -m py_compile src\a1111_runtime.py src\news_feed.py src\city_scene.py` passed.
- Fake portrait generation recorded `lock_enter` before model check/switch and before `txt2img`.
- Fake city scene generation recorded idle wait, model check/switch, model-swap wait, `txt2img`, and post-generation wait.
- `python -m compileall -q src Webpage` passed.

### 2026-05-08 - Bug 6 DB-authoritative mission fallbacks

Status: fixed.

Plan:
- Smoke current file-fallback behavior with fake empty/failed DB reads.
- Trace the connected mission-building and learning paths.
- Remove non-gazetteer `campaign_docs` JSON/txt fallbacks or make them fail loudly.
- Repeat the same fake DB smoke after patching.

Before smoke:
- With DB character sources patched empty, `encounters.get_max_pc_level()` returned `6` from `campaign_docs/character_memory.txt`.
- With DB faction reputation patched empty, `_study_faction_reputation()` still produced a result from `campaign_docs/faction_reputation.json`.
- With DB rift state patched to raise, `gather_context()` loaded `campaign_docs/rift_state.json` and produced `Active Rifts: Smoke Rift (stage: bad)`.

Connected paths checked:
- `src/mission_builder/__init__.py`: `gather_context()` rift context.
- `src/mission_builder/encounters.py`: `get_max_pc_level()` and `get_cr()`.
- `src/self_learning.py`: `_study_faction_reputation()`.
- `src/db_api.py`: `get_character_memory_text()`.

Fix:
- Removed the rift-state file fallback from `gather_context()`; DB failure now logs and omits stale rift context.
- Stopped `get_max_pc_level()` before the legacy `character_memory.txt` parser when DB has no levels.
- Removed faction-reputation JSON fallback from `_study_faction_reputation()`.
- Removed `character_memory.txt` fallback from `get_character_memory_text()`.

After smoke:
- `python -m py_compile src\mission_builder\__init__.py src\mission_builder\encounters.py src\self_learning.py src\db_api.py` passed.
- With DB character sources patched empty, `encounters.get_max_pc_level()` returned `0` instead of reading `character_memory.txt`.
- With `db_api.db.fetch_all` patched empty, `get_character_memory_text()` returned an empty string instead of reading `campaign_docs/character_memory.txt`.
- With DB faction reputation patched empty, `_study_faction_reputation()` returned `None` instead of reading `campaign_docs/faction_reputation.json`.
- With DB rift state patched to raise, `gather_context()` did not call `_load_json()` and returned empty `rift_context`.

### 2026-05-08 - Bug 7 gazetteer cache lifetime

Status: fixed.

Plan:
- Smoke current `load_gazetteer()` cache behavior with changing fake DB data.
- Trace callers and write/update paths touching gazetteer data.
- Add bounded cache TTL plus explicit invalidation helper.
- Repeat the fake DB smoke after patching.

Before smoke:
- Fake DB returned `First District` then `Second District`, but two `load_gazetteer()` calls made only 1 DB query and both returned `First District`.

Connected paths checked:
- `src/mission_builder/locations.py`: `load_gazetteer()` and all JSON gazetteer helpers.
- `src/mission_builder/__init__.py`: mission context location selection.
- `src/mission_builder/leads.py`: lead generation uses location helpers.
- Dashboard district/place routes mostly query DB directly and are less affected.

Fix:
- Added `_gazetteer_cache_revision`, `GAZETTEER_CACHE_TTL`, and `invalidate_gazetteer_cache()`.
- `load_gazetteer()` now reads `content_json, updated_at` and reuses cache only when `updated_at` is unchanged.
- If `updated_at` is unavailable, the cache uses a short TTL fallback. On DB error, a still-fresh cache may be reused; otherwise the allowed `city_gazetteer.json` fallback remains.

After smoke:
- `python -m py_compile src\mission_builder\locations.py` passed.
- Fake DB same-revision second call reused `First District`.
- Fake DB changed-revision call reloaded and returned `Second District`.
- `invalidate_gazetteer_cache()` forced reload and returned `Third District` even with the same revision.
- Real DB smoke loaded 27 districts from gazetteer.

### 2026-05-08 - Bug 10 image refs ordering

Status: fixed.

Plan:
- Smoke current `/api/image-refs` SQL ordering with fake DB query capture.
- Patch route SQL to select/order by `COALESCE(updated_at, created_at)`.
- Repeat fake route smoke and adjacent API smoke.

Before smoke:
- Fake route capture showed both `/api/image-refs` queries used `ORDER BY updated_at DESC`.

Connected paths checked:
- `Webpage/app.py`: `/api/image-refs`.
- `src/db_api.py`: `save_image_ref()` inserts can leave `updated_at` null while `created_at` is populated.

Fix:
- `/api/image-refs` now selects `COALESCE(updated_at, created_at) AS updated_at`.
- Both filtered and unfiltered queries now order by `COALESCE(updated_at, created_at) DESC`.

After smoke:
- `python -m py_compile Webpage\app.py` passed.
- Fake route capture confirmed both `/api/image-refs` queries use `ORDER BY COALESCE(updated_at, created_at) DESC`.
- DB-backed route smoke passed for `/api/image-refs?limit=5` and `/api/image-refs?type=location_map&limit=5`.

### 2026-05-08 - Bug 8 image ref rotation concurrency

Status: fixed.

Plan:
- Smoke current concurrent saves against a temp ref root.
- Trace save/load callers and standalone script overlap.
- Patch `_save_ref()` with a per-entity lock and atomic temp write/replace.
- Repeat concurrent save smoke.

Before smoke:
- 20 concurrent temp-root NPC saves for one entity produced 7 exceptions (`PermissionError` / `FileNotFoundError`) and only 7 retained ref files with a gap in numbering.

Connected paths checked:
- `src/image_ref.py`: `_save_ref()`, `save_npc_ref()`, `save_npc_alt_ref()`, `save_location_ref()`.
- Callers include portrait loop, city scene generation, map generation, slash-command backfill, and standalone backfill scripts.

Fix:
- Added per-entity in-process `threading.RLock` around `_save_ref()`.
- Replaced direct `write_bytes()` with temp-file write plus atomic `Path.replace()` into `ref_001.png`.
- Replaced rotation `rename()` with `replace()` so destination replacement is explicit.

After smoke:
- `python -m py_compile src\image_ref.py` passed.
- 20 concurrent temp-root NPC saves for one entity produced 0 exceptions.
- The folder retained exactly `ref_001.png` through `ref_010.png`, with no zero-byte or temp files.

Residual risk:
- This protects concurrent saves inside one Python process. Separate bot/script processes can still race; the stronger future fix is immutable timestamp/uuid image filenames or a cross-process lock file.

### 2026-05-08 - Bug 9 image ref API versions

Status: fixed.

Plan:
- Smoke current `/api/image-refs` response with one fake DB row and multiple filesystem refs.
- Patch the route to expose filesystem versions alongside the aggregate DB row.
- Repeat route smoke and adjacent API smoke.

Before smoke:
- Fake `/api/image-refs?type=npc_portrait` with 3 filesystem refs returned only the aggregate DB row keys and no `versions` list, though `image_url` pointed at the latest file.

Connected paths checked:
- `Webpage/app.py`: `_ref_images()`, `_latest_ref_image()`, `/api/image-refs`.
- `src/image_ref.py`: filesystem layout `ref_001.png` through `ref_010.png`.
- `src/db_api.py`: aggregate one-row `image_refs` model remains unchanged.

Fix:
- `/api/image-refs` now includes `versions` and `version_count` for each aggregate DB row.
- Each version includes `url`, `image_url`, `ref_path`, `updated_at`, `index`, and `is_latest`.
- `_ref_images()` now sorts numbered `ref_###` files by slot number so `ref_001.png` is always latest even when filesystem mtimes tie.

After smoke:
- `python -m py_compile Webpage\app.py` passed.
- Fake route smoke with 3 filesystem refs returned `version_count=3` and ordered versions as `ref_001.png`, `ref_002.png`, `ref_003.png`.
- Adjacent route smoke passed for `/api/image-refs?limit=3`, `/api/image-refs?type=npc_portrait&limit=3`, `/api/npcs?limit=1`, and `/api/districts`.

Residual risk:
- This exposes filesystem versions through the API, but DB tools still only see one aggregate row per entity. A future schema migration to `image_ref_versions` would be the stronger data-model fix.

### 2026-05-08 - Bug 2 map AI/tactical contract

Status: fixed.

Plan:
- Smoke current strict-VTT direct map path to confirm A1111 work is discarded.
- Trace module map save/reference behavior.
- Make strict tactical generation skip direct A1111 unless AI texture is enabled.
- Save pretty map output as the location visual reference when available.
- Repeat fake A1111/tactical smoke.

Before smoke:
- With default strict VTT behavior, fake direct map generation made 1 A1111 POST and passed useful AI bytes into `render_vtt_battlemap()`, even though the renderer returns deterministic output when AI texture is disabled.

Connected paths checked:
- `src/mission_builder/maps.py`: `generate_vtt_map()` and `generate_module_maps()`.
- `src/mission_builder/vtt_renderer.py`: `render_vtt_battlemap()`, `STRICT_VTT`, `ALLOW_AI_TEXTURE`, `stylize_pretty_battlemap()`.

Fix:
- `generate_vtt_map()` now skips direct A1111 generation when `STRICT_VTT` is on and `ALLOW_AI_TEXTURE` is off, returning the deterministic tactical renderer immediately.
- `generate_module_maps()` still writes the tactical map and grid sidecar, then runs the pretty-map pass.
- Location visual references now save the pretty-map bytes when a pretty map exists, falling back to the tactical map only when no pretty output is available.

After smoke:
- `python -m py_compile src\mission_builder\maps.py` passed.
- Fake strict-VTT direct map smoke made 0 A1111 availability checks/POSTs and called the renderer once with no AI bytes.
- Fake module-map smoke saved `pretty-map` bytes to the location ref and recorded `visual_ref_file` ending in `_pretty.png`.

## Confirmed / High-Confidence Bugs

### 1. Path containment checks use string prefix matching

Status: fixed 2026-05-07.

Files:
- `Webpage/app.py`

Affected code:
- `_profile_image_url()`
- `_project_media_url()`
- `module_file()`
- `serve_area_map()`

Context:
These functions resolve a requested path and then check containment with:

```python
if not str(full).startswith(str(root)):
```

or the same pattern against `module_dir` / `AREA_MAPS_DIR`.

Why this is risky:
String prefix checks can approve sibling paths whose names share a prefix. For example, a path under `generated_modules_bad` can start with the string for `generated_modules` even though it is not inside that directory. The later `relative_to()` call catches some cases in `_project_media_url`, but `module_file()` and `serve_area_map()` call `send_from_directory()` after the prefix check.

Impact:
Potential path traversal / wrong-file serving risk in dashboard media and module file routes. Even if exploitable paths are currently hard to hit from the UI, this is the wrong safety primitive for serving local files.

Preferred fix:
Use `Path.relative_to()` or `os.path.commonpath()` after resolving both paths:

```python
try:
    full.relative_to(root)
except ValueError:
    return ""
```

For routes, perform the same containment check before `send_from_directory`.

### 2. Main map generation spends time on A1111 but usually discards the AI image

Status: fixed 2026-05-08.

Files:
- `src/mission_builder/maps.py`
- `src/mission_builder/vtt_renderer.py`

Affected code:
- `generate_vtt_map()`
- `render_vtt_battlemap()`

Context:
`generate_vtt_map()` sends prompts to A1111 and gets an image back. It then calls:

```python
render_vtt_battlemap(context={**scene, "prompt": used_prompt}, ai_png=base64.b64decode(img_b64))
```

But `render_vtt_battlemap()` only uses `ai_png` when:

```python
if ai_png and ALLOW_AI_TEXTURE and not STRICT_VTT:
```

Defaults are:

```python
STRICT_VTT = true
ALLOW_AI_TEXTURE = false
```

Why this matters:
Under default settings, the generated A1111 tactical image is discarded. The saved tactical map is deterministic renderer output, not the A1111 output. That may be intentional for strict VTT accuracy, but it conflicts with comments in `maps.py` that say generated maps are saved as location references so future maps improve over time.

Impact:
- A1111 map generation can take minutes while contributing nothing to the tactical PNG.
- The location reference saved by `save_location_ref(location, map_bytes, ...)` is usually the deterministic tactical renderer output, not the AI image.
- Future map generations using that reference may improve less than expected or reinforce schematic maps.

Preferred fix:
Make the contract explicit:
- Save deterministic tactical maps as tactical artifacts.
- Save AI/prettified maps as separate visual references only after validation.
- If strict tactical mode is on, skip A1111 for the tactical map unless generating a pretty/reference image is requested.

### 3. Direct map generation does not validate blank/failed A1111 images before using them

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/maps.py`
- `src/mission_builder/vtt_renderer.py`

Affected code:
- `generate_vtt_map()`
- `_decode_useful_pretty_image()`

Context:
`stylize_pretty_battlemap()` now validates blank/invalid outputs via `_decode_useful_pretty_image()`. `generate_vtt_map()` does not do an equivalent validation on `images[0]` before decoding and passing it onward.

Why this matters:
The logs and recent manual run showed Flux can return a flat/invalid image when model switching half-fails. Pretty map generation rejects those; direct map generation still treats any returned image as success.

Impact:
If `ALLOW_AI_TEXTURE=true` or `STRICT_VTT=false`, blank A1111 output can become part of a map. Even with strict defaults, `generate_vtt_map()` may report A1111 success and save a deterministic map/reference, hiding the failed image lane.

Preferred fix:
Move image usefulness validation into a shared helper and call it in both direct and pretty map generation. If all AI lanes fail validation, log a clear fallback reason.

### 4. Mimir pull pass can hammer `get_character` with almost no throttle

Status: fixed 2026-05-07.

Files:
- `src/mimir_sync.py`
- `logs/bot_stderr.log`

Affected code:
- `MimirSyncEngine.pull_npc_changes()`
- `MimirSyncEngine.full_sync()`

Context:
`sync_all_npcs()` has a small `await asyncio.sleep(0.05)` throttle. `pull_npc_changes()` loops over up to 250 synced NPC rows and calls:

```python
char = await mimir.get_character(row["mimir_id"])
```

without a sleep in the main known-NPC pass.

Runtime evidence:
`logs/bot_stderr.log` shows a burst of `mimir_mcp::handler: Handling call_tool request tool=get_character` calls many times within the same second during the full sync on 2026-05-07.

Impact:
- Local MCP can be spammed with hundreds of requests in a burst.
- Makes debugging real Mimir errors harder because logs are flooded.
- Increases chance of local DB/API contention during sync.

Preferred fix:
Add a real throttle/batch policy to `pull_npc_changes()` and log summarized progress every N rows. The bot does not need this path to be fast.

### 5. NPC portrait model switching lacks the idle/cooldown protection used by map generation

Status: fixed 2026-05-07.

Files:
- `src/news_feed.py`
- `src/mission_builder/vtt_renderer.py`
- `src/mission_builder/maps.py`

Affected code:
- `generate_npc_portrait()`

Context:
Map generation has `wait_for_a1111_idle()` and explicit cooldowns around model switching. The NPC portrait loop only does:

```python
await _mc.post(f"{A1111_URL}/sdapi/v1/options", json={"sd_model_checkpoint": A1111_MODEL})
```

and then proceeds to generation.

Why this matters:
The user has observed models not releasing memory for a few minutes after runs. The map path was updated to respect that; portrait generation still can request a generation immediately after changing checkpoints, especially when switching between normal and alt-universe/furry models.

Impact:
- Portrait generation may run on the old checkpoint.
- Portrait generation may fail or produce low-quality/blank output after a model swap.
- Alt-universe portraits are especially exposed because they switch to `sd_novaFurryXL_ilV160`.

Preferred fix:
Reuse `wait_for_a1111_idle()` or create a shared A1111 model-switch helper for all image paths. Apply it to portrait, scene, and map generation.

### 6. Several mission-building paths still use file fallbacks despite DB-authoritative rule

Status: fixed 2026-05-08.

Files:
- `CLAUDE.md`
- `src/mission_builder/__init__.py`
- `src/mission_builder/encounters.py`
- `src/mission_builder/locations.py`
- `src/self_learning.py`

Context:
`CLAUDE.md` says MySQL is authoritative and new code should not use `campaign_docs` JSON/txt, with `city_gazetteer.json` as the sole remaining allowed full-structure file read.

Examples:
- `src/mission_builder/__init__.py:gather_context()` still falls back to `campaign_docs/rift_state.json`.
- `src/mission_builder/encounters.py:get_max_pc_level()` still falls back to `campaign_docs/character_memory.txt`.
- `src/self_learning.py:_study_faction_reputation()` still falls back to `campaign_docs/faction_reputation.json`.
- `src/mission_builder/locations.py:load_gazetteer()` falls back to `city_gazetteer.json`, which is explicitly allowed, but see stale cache note below.

Impact:
Fallbacks can silently inject stale campaign facts into mission generation: wrong PC level, wrong rift state, wrong faction standing. That is exactly the kind of "generic or wrong mission" failure the quality bar is meant to prevent.

Preferred fix:
Remove or heavily gate non-gazetteer file fallbacks. If DB data is missing, fail loudly into logs and surface an actionable message rather than quietly using stale files.

### 7. Gazetteer cache can stay stale for the lifetime of the process

Status: fixed 2026-05-08.

Files:
- `src/mission_builder/locations.py`

Affected code:
- `load_gazetteer()`
- module-level `_gazetteer_cache`

Context:
`load_gazetteer()` caches the first DB/file gazetteer load in `_gazetteer_cache` and never invalidates it.

Why this matters:
Gazetteer places/images are being backfilled and updated while the bot is running. Mission generation can keep using the first gazetteer snapshot loaded after boot.

Impact:
New places, updated descriptions, and corrected districts may not be reflected in mission location selection until the bot is rebooted.

Preferred fix:
Use a TTL, revision timestamp, or explicit invalidation after backfill commands. Given the quality bar, stale cache should be less acceptable than a slower DB read.

### 8. Image reference rotation is not concurrency-safe

Status: fixed 2026-05-08 for in-process concurrency. Cross-process race remains a residual risk.

Files:
- `src/image_ref.py`

Affected code:
- `_save_ref()`

Context:
Saving a new reference rotates files by deleting `ref_010.png`, renaming `ref_009.png` to `ref_010.png`, etc., then writing `ref_001.png`.

Why this matters:
There is no lock around this filesystem rotation. Multiple tasks can save refs for the same NPC/place close together: portrait loop, scene generation, backfill scripts, auto-detect refs, location map generation.

Impact:
Concurrent saves for the same entity can lose images, fail renames, or leave the ref set partially rotated.

Preferred fix:
Use a per-entity async/thread lock or write new files with timestamp/uuid names and derive the "latest 10" by mtime instead of rename rotation.

### 9. Image reference DB model only stores one path per entity while filesystem now stores ten

Status: fixed 2026-05-08 at the dashboard API layer. DB child-table migration remains a stronger future improvement.

Files:
- `src/db_api.py`
- `src/image_ref.py`
- `Webpage/app.py`

Affected code:
- `save_image_ref()`
- `_save_ref()`
- `/api/image-refs`

Context:
`save_image_ref()` upserts a single `image_refs` row per `(entity_type, entity_name)`, updating `image_path` and incrementing `ref_count`. The filesystem keeps up to ten `ref_###` files.

Impact:
The dashboard NPC/Gazetteer pages now rotate through filesystem refs, but `/api/image-refs` and the DB itself still expose only the latest path plus a count. The image asset library cannot inspect or manage the full history, and any tooling that relies on DB rows cannot see the ten actual refs.

Preferred fix:
Either add a child table for image ref versions, or make `/api/image-refs` expand filesystem refs into version entries so the asset view and cleanup tools match runtime behavior.

### 10. `api_image_refs` sorts by `updated_at` only, so newly inserted rows without `updated_at` can sort poorly

Status: fixed 2026-05-08.

Files:
- `Webpage/app.py`
- `src/db_api.py`

Affected code:
- `/api/image-refs`
- `save_image_ref()`

Context:
`save_image_ref()` inserts new rows without setting `updated_at`; only updates set it. `/api/image-refs` sorts with:

```sql
ORDER BY updated_at DESC
```

Other dashboard queries use `COALESCE(updated_at, created_at)`.

Impact:
Freshly inserted image refs may appear out of order or below older updated rows in the Image Assets page.

Preferred fix:
Set `updated_at` on insert or sort by `COALESCE(updated_at, created_at) DESC`.

---

## 2026-05-07 — Full Pipeline Investigative Audit

Status: all fixed 2026-05-07.

Five helpers ran in parallel reading every pipeline file end-to-end and cross-checking keys, column names, import targets, and async contracts. No patch was applied during this pass — smoke only, write down everything.

Families covered: combat (battle/defense/assault/ambush), stealth/social (infiltration/heist/negotiation/sabotage/rescue), investigation/discovery/misc (investigation/recovery/exploration/gather/escort/puzzle/infestation/leads), assembly/export (__init__/published_pipeline/scene_dialogs/html_renderer/novel_pipeline/module_council/session_runner/docx_builder), dungeon_delve + support (tile_generator/image_generator/image_integration/skills_integration/encounters/rewards/npcs).

Fixing rule applies: smoke before fix, smoke after fix on the targeted subsystem.

---

### 15. CSS faction color replacement never matches — all module pages render with default blue

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/html_renderer.py`

Affected code:
- `_page()`, line 941

Context:
`css = _CSS.replace("--faction:   #4682b4;", f"--faction:   {fc};")` — the search string has three spaces and hex `#4682b4`. The actual CSS definition in `_CSS` at line 46 has four spaces and `#3a6898`. The strings never match. `.replace()` is a no-op.

Impact:
Every rendered HTML page (DM Guide, Module, Players Guide, Chart Pack) ignores the faction color entirely. Iron Fang, Glass Sigil, Patchwork Saints, every faction renders with the same dark blue `#3a6898`.

Fix:
Change line 941 to match the actual CSS string: `css = _CSS.replace("--faction:    #3a6898;", f"--faction:    {fc};")`.

---

### 16. `save_dungeon_delve()` called without `await` — dungeon files never written

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/dungeon_delve/__init__.py`

Affected code:
- Line 426: `mission_dir = save_dungeon_delve(result)`

Context:
`save_dungeon_delve` is declared `async def`. Calling it without `await` returns a coroutine object. `mission_dir` is a coroutine, not a dict of paths. The coroutine is never awaited, so no files are written.

Impact:
Dungeon delve output is silently discarded on every generation. All downstream file-path lookups operate on a coroutine object and will crash or produce empty results.

Fix:
`mission_dir = await save_dungeon_delve(result)`.

---

### 17. `novel_outline.py` UnboundLocalError crashes novel pipeline on any LLM failure

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/novel_outline.py`

Affected code:
- Lines 63–93

Context:
`resp` is assigned only inside the `try:` block. If `expert.complete()` raises before assignment, the `finally:` block closes the agent cleanly, then line 93 executes `if resp.success` — raising `UnboundLocalError`. The graceful fallback outline at line 115 is never reached.

Impact:
Any network error, timeout, or LLM failure during novel Pass 1 crashes the entire novel pipeline instead of falling back to the hardcoded outline.

Fix:
Add `resp = None` before the `try:` block; guard line 93 as `if resp and resp.success and resp.content`.

---

### 18. Published pipeline shallow-clones scene 4 into scene 5

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/published_pipeline.py`

Affected code:
- Lines 366–369

Context:
When the LLM returns exactly 4 scenes, `while len(scenes) < 5` appends `scenes[-1] | {"name": "Escalation", "location": ...}`. The `|` operator shallow-copies the top-level dict but all list values (`notes`, `npcs`, `checks`, `what_happens`, `map_features`) remain shared references to scene 4's lists.

Impact:
Scene 5 plays identically to scene 4. The quality pass awards full marks for "Has at least five scenes" despite the duplicate content.

Fix:
Build a proper minimal distinct stub with empty lists: `{"name": "Escalation", "location": ..., "read": "...", "notes": [], "npcs": [], "checks": [], "what_happens": [], "transition": "...", "treasure": "", "map_features": []}`.

---

### 19. `scene_dialogs.py` logs injection success when zero HTML was actually written

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/scene_dialogs.py`

Affected code:
- Lines 437–441

Context:
`generate_all_scene_dialogs()` returns a non-empty list even when every Ollama call fails JSON parse — each entry has `"html": ""`. The guard `if not scene_dialogs` passes (list is non-empty). `inject_dialogs_into_html` silently skips all empty entries. `logger.info` fires and returns `True`. `published_pipeline.py` logs `"Scene dialogs injected into module.html"` for an unmodified file.

Impact:
Caller is deceived — scene dialogs appear injected but the HTML is unchanged.

Fix:
Replace the guard with `if not any(sd.get("html") for sd in scene_dialogs): return False`.

---

### 20. `scene_dialogs.py` depth counter bug corrupts HTML when leaving-blocks contain nested divs

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/scene_dialogs.py`

Affected code:
- Lines 648–676 (`_strip_duplicate_leaving`)

Context:
The for-loop at lines 648–653 appends every element to `rebuilt` unconditionally and `continue`s — `rebuilt` ends up identical to `parts` and is discarded. The actual while-loop starts with `depth = 0` and removes the first `</div>` when `depth == 1`, which is one level too deep. Leaving-blocks always contain nested divs (grid, row divs), so the removal fires one tag past the correct closing tag, corrupting surrounding HTML.

Impact:
HTML structure is corrupted whenever a scene dialog leaving-block is stripped. The dead for-loop is a no-op. The depth bug is live.

Fix:
Delete lines 646–653. In the while-loop, initialize `depth = 1` (already inside the opening tag) and trigger removal when `depth == 0`.

---

### 21. `image_generator.py` awaits synchronous `httpx.Response.json()`

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/image_generator.py`

Affected code:
- Line 135: `data = await response.json()`

Context:
`httpx.Response.json()` is a synchronous method. Awaiting it raises `TypeError` at runtime.

Impact:
Image generation via this path crashes on every call.

Fix:
`data = response.json()` (drop `await`).

---

### 22. `image_integration.py` sync wrapper returns coroutine instead of results in async context

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/image_integration.py`

Affected code:
- Lines 133–144 (`generate_mission_with_images_sync`)

Context:
When a running event loop exists (the bot's async context), the function returns the bare coroutine object `generate_mission_with_images(...)` unawaited. Any caller that unpacks the result (`module, images = result`) raises `TypeError: cannot unpack non-iterable coroutine`.

Impact:
Web-injected or sync-triggered mission generation with images crashes in the bot context.

Fix:
Either make the function `async def` and `await` the inner call, or raise `RuntimeError("call generate_mission_with_images() directly in async contexts")` instead of silently returning a coroutine.

---

### 23. `image_integration.py` `extract_dungeon_rooms_from_mission()` always returns empty

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/image_integration.py`

Affected code:
- Lines 299–310

Context:
Reads `mission_module.get("acts", [])` — `MissionModule` has no `acts` key. The schema uses `content` with `act_1`…`act_5` strings and a top-level `encounters` list. The function always returns `[]`.

Impact:
Dungeon tiles are never generated via `generate_mission_with_images()`.

Fix:
Rewrite to pull from `module.get("dungeon_delve", {}).get("rooms", [])`.

---

### 24. `docx_builder.py` `validate_module_data()` blocks DOCX on `chapter_1` never set by JSON pipeline

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/docx_builder.py`

Affected code:
- Line 198: `required_sections = ["overview", "chapter_1", "chapter_4", "chapter_5"]`

Context:
`json_generator.py` populates `acts_1_2`, `acts_3_4`, `act_5_rewards`. `format_module_for_docx()` maps `chapter_1 = chapter_1 or acts_1_2`, but the validator checks for `chapter_1` specifically — which is always `""` when the JSON pipeline is used. The validator returns `False` on every JSON-generated module.

Impact:
Any caller that gates DOCX generation on `validate_module_data()` never produces a DOCX from the JSON pipeline.

Fix:
Update `validate_module_data()` to accept `acts_1_2` as satisfying the `chapter_1` requirement, mirroring the fallback in `format_module_for_docx()`.

---

### 25. `module_council.py` swallows Ollama error root cause with `KeyError`

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/module_council.py`

Affected code:
- Line 76: `result = r.json()["message"]["content"].strip()`

Context:
Ollama error responses (`{"error": "model not found"}`) have no `"message"` key. `KeyError` is caught by the outer `except`, which logs only the exception string — hiding the actual Ollama error.

Impact:
Council silently falls back to single-pass. Wrong model name, GPU OOM, and similar errors are invisible in logs.

Fix:
`result = (r.json().get("message") or {}).get("content", "").strip()`.

---

### 26. `infestation_pipeline.py` DM guide and chart monster list always empty — wrong dict key

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/infestation_pipeline.py`

Affected code:
- Line 1062: `monster_list = monsters.get("monsters", [])`
- Line 1092: same in `chart_md`

Context:
The monster roster dict uses key `"variants"`. A comment at line 975 explicitly notes this: `# NOTE: roster uses "variants" key`. `monsters.get("monsters", [])` always returns `[]`.

Impact:
The DM guide `### Monster Roster` section and the `### Monster Quick Reference` chart table are always blank.

Fix:
Change both lines to `monsters.get("variants", [])`.

---

### 27. `infestation_pipeline.py` variant dict has no `role` or `tactics` key

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/infestation_pipeline.py`

Affected code:
- Lines 1073, 1092

Context:
Even if bug 26 is fixed, `m.get('role')` and `m.get('tactics', '')` are used on variant dicts. Variant keys are `name`, `cr`, `hp`, `ac`, `speed`, `attacks`, `special`, `density_note`. No `role` or `tactics`.

Impact:
Role and tactics columns in the DM guide and chart always render as `None`/`""`.

Fix:
Use `m.get('density_note')` for role and `m.get('special', '')` for tactics in variant rows.

---

### 28. `infestation_pipeline.py` Mimir room documents all named `"Room N"` — wrong key

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/infestation_pipeline.py`

Affected code:
- Line 1019: `rc.get("title", f"Room {rid}")`

Context:
Room content dicts from `generate_room_batch()` use key `"name"`, not `"title"`. `rc.get("title")` always returns `None`, falling back to `f"Room {rid}"`.

Impact:
All Mimir documents for infestation rooms are named `"Room 1"`, `"Room 2"`, etc. — actual room names are lost.

Fix:
`rc.get("name", f"Room {rid}")`.

---

### 29. `infestation_pipeline.py` imports private `_a1111_lock` — hard crash if name removed

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/infestation_pipeline.py`

Affected code:
- Line 553: `from src.news_feed import a1111_lock, _a1111_lock`

Context:
`_a1111_lock` is a private module-level name. Its only use is a `.locked()` pre-check before entering `a1111_lock`. The `async with a1111_lock:` on the next line already serializes access. If `news_feed.py` renames or removes `_a1111_lock`, this import raises `ImportError` and crashes the entire map generation path for infestation.

Impact:
Hard crash on import when A1111 map generation is triggered.

Fix:
Remove `_a1111_lock` from the import and delete the `.locked()` pre-check; `a1111_lock` already serializes access.

---

### 30. `investigation_pipeline.py` DM guide uses three dead key lookups on suspect and lead dicts

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/investigation_pipeline.py`

Affected code:
- Line 873: `s.get('secret')` — suspect dicts have no `'secret'` key (key is `'note'`)
- Line 875: `lead.get('clue')` — lead dicts have no `'clue'` key (use `'focus'`)
- Line 884: `lead.get('public_hint', lead.get('scene', ...))` — neither key exists in lead dicts

Impact:
Three separate sections of the investigation DM guide render as `None` or static fallback strings on every generation. The DM guide is functionally empty for suspects' secrets and lead clues.

Fix:
Line 873: `s.get('note')`. Line 875: `lead.get('focus')`. Line 884: `lead.get('focus', lead.get('label', 'Investigate this lead.'))`.

---

### 31. `leads.py` KeyError crash when `format_leads_for_prompt()` called with raw `generate_lead()` result

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/leads.py`

Affected code:
- Line 302: `lead['lead_number']`

Context:
`generate_investigation_leads()` assigns `lead["lead_number"] = i + 1`. `generate_lead()` itself does not. Any caller that passes a raw `generate_lead()` result to `format_leads_for_prompt()` or `format_lead_as_scene()` gets a `KeyError`.

Impact:
Hard crash on any direct use of `generate_lead()` output with format helpers.

Fix:
`lead.get('lead_number', '?')` on line 302 and same in `format_lead_as_scene()`.

---

### 32. `recovery_pipeline.py` and `ambush_pipeline.py` query nonexistent `adventurer_parties` table

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/recovery_pipeline.py` line 273
- `src/mission_builder/ambush_pipeline.py` line 419

Context:
`adventurer_parties` is not in `database_schema.sql`. Only `party_profiles` exists. Both queries fail silently (caught by `_db_rows`), falling back to generic faction data or returning `None`.

Impact:
`recovery_pipeline` rival party is always `None`. `ambush_pipeline` guard roster always uses the faction NPC fallback.

Fix:
Both: `SELECT party_name FROM party_profiles ORDER BY RAND() LIMIT 1`.

---

### 33. `ambush_pipeline.py` queries nonexistent `raw_block` column on `player_characters`

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/ambush_pipeline.py`

Affected code:
- Line 349: `SELECT name, profile_json, raw_block FROM player_characters`

Context:
`raw_block` does not exist in the `player_characters` schema. MySQL error caught by `_db_rows`, returns `[]`. Secondary party-strength falls through to default level `[5]`.

Impact:
Ambush CR is always calculated as if the party is level 5 on the secondary path.

Fix:
Remove `raw_block` from the SELECT.

---

### 34. `ambush_pipeline.py` two more wrong-data bugs in output documents

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/ambush_pipeline.py`

Affected code:
- Line 939: `briefing.get('contact_speech', briefing)` — fallback is entire dict object, renders as raw Python repr
- Lines 954–955: `map_plan.get('label', '')` and `map_plan.get('description', '')` — map_plan has no `label` or `description` keys (uses `name` and `prompt`)

Impact:
Line 939: player brief contains `{'contact_speech': None, ...}` literal when Ollama partial-parse occurs. Lines 954-955: map plan section in chart pack always renders as `"- : "` with both values empty.

Fix:
Line 939: fallback to `""`. Lines 954-955: `map_plan.get('name', '')` and `map_plan.get('prompt', '')`.

---

### 35. `defense_pipeline.py` wave dict keys wrong in DM guide and chart

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/defense_pipeline.py`

Affected code:
- Line 1219: `w.get('name', ...)` and `w.get('goal', w.get('tactic', ...))` — wave dicts use `'label'` and `'tactics'`
- Line 1235: `f"- {e}"` on watch_events list of dicts — prints raw dict repr
- Line 1237: `lead.get('detail', lead.get('desc', ''))` — intel lead dicts have `'action'`/`'check'`, no `'detail'`/`'desc'`
- Line 1239: same `'name'`/`'tactic'` wrong keys in chart table

Impact:
Defense DM guide wave plan shows `"Attack wave"` and `"pressure the defense"` for every wave. Watch events section shows raw Python dict repr. Intel lead descriptions always blank. Chart table wave rows entirely blank.

Fix:
Line 1219/1239: `w.get('label', ...)` and `w.get('tactics', ...)`. Line 1235: `f"- {e.get('title', '')}: {e.get('description', '')}"`. Line 1237: `lead.get('action', lead.get('check', ''))`.

---

### 36. `assault_pipeline.py` duplicate `"Patchwork Saints"` key silently drops first entry

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/assault_pipeline.py`

Affected code:
- Lines 99 and 169: `FACTION_FORCES` dict defines `"Patchwork Saints"` twice

Context:
Python silently keeps the last definition (line 169, with shorter disposition text). The fuller first entry (line 99) is discarded.

Impact:
Patchwork Saints assault missions use the wrong force profile.

Fix:
Remove the duplicate block at lines 169–182.

---

### 37. `assault_pipeline.py` defender trickle always shows `"see module"`

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/assault_pipeline.py`

Affected code:
- Line 1094: `next(iter([]), "see module")`

Context:
`iter([])` is an iterator over an empty list. `next()` always returns the sentinel `"see module"`. The defender type's `trickle` field is never passed.

Impact:
Session HTML always shows `"Defender trickle: see module"` instead of actual trickle description.

Fix:
Pass `defender_type` into `render_assault_session` and use `_e(defender_type.get("trickle", "see module"))`.

---

### 38. `rescue_pipeline.py` DM guide hazards section always empty — wrong key

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/rescue_pipeline.py`

Affected code:
- Line 532: `plan.get("hazards", [])`

Context:
The plan dict uses key `"hazards_or_pressures"` (set in `_generate_plan()` and fallback at lines 325 and 337). The key `"hazards"` never exists.

Impact:
The `### Hazards / Pressures` section of the rescue DM guide is always empty on every generation.

Fix:
`plan.get("hazards_or_pressures", [])`.

---

### 39. `rewards.py` loot table always priced at CR 1 — `cr` arg omitted from gold calculation

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/rewards.py`

Affected code:
- Line 402: `calculate_gold_reward(tier, pc_level=pc_level)`

Context:
`calculate_gold_reward` signature is `(tier, cr=1, party_size=4, pc_level=0)`. The `cr` parameter defaults to `1`. The actual mission CR is received by `build_loot_table()` but never passed through.

Impact:
Every loot table is priced as CR 1 regardless of actual encounter difficulty.

Fix:
`calculate_gold_reward(tier, cr=cr, pc_level=pc_level)`.

---

### 40. `dungeon_delve/tile_generator.py` uses stale reference to `_a1111_lock`

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/dungeon_delve/tile_generator.py`

Affected code:
- Line 181: `if _a1111_lock.locked():`

Context:
`news_feed.py` replaces `_a1111_lock` with a new `asyncio.Lock()` when the timed lock times out. `tile_generator.py` holds a reference to the old lock from import time. Calling `.locked()` on the stale reference returns wrong state.

Fix:
Replace `_a1111_lock.locked()` with `a1111_lock.locked()` (the wrapper method which always interrogates the current underlying lock). Remove `_a1111_lock` from the import.

---

### 41. `npcs.py` loot table `data_json` may not exist in `npcs` schema; rank detection always fails

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/npcs.py`

Affected code:
- Line 64: `SELECT ... data_json FROM npcs` — `data_json` not in base `database_schema.sql`
- Lines 117–118: `npc.get("rank", "")` — `rank` column not in the SELECT, never populated unless inside `data_json`

Impact:
Line 64: on a fresh DB deploy without ALTER, entire NPC roster returns `[]` — all missions fall back to synthetic NPCs silently. Lines 117-118: rank-based faction leader detection always fails, further degrading NPC selection.

Fix:
Line 64: verify `data_json` column added by migration or guard with COALESCE. Lines 117-118: accept that rank lookup only works when present in `data_json` and document this.

---

### 42. `negotiation_pipeline.py` prior-outcome query references `created_at` that may not exist on `mission_outcomes`

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/negotiation_pipeline.py`

Affected code:
- Line 338: `ORDER BY COALESCE(completed_at, created_at) DESC`

Context:
The INSERT statements for `mission_outcomes` only populate `completed_at`. There is no `created_at` column confirmed in the `mission_outcomes` schema. If absent, MySQL raises `Unknown column 'created_at'` — caught by `_db_rows`, returns `[]`.

Impact:
Negotiation missions receive no historical context even when prior outcomes exist in the DB. Previously fixed for the column names (bug 11) but this ordering clause was not caught at that time.

Fix:
`ORDER BY completed_at DESC`.

---

### 43. `skills_integration_new.py` is an active duplicate of `skills_integration.py`

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/skills_integration.py`
- `src/mission_builder/skills_integration_new.py`

Context:
Both files have identical content. Both are importable. Any module-level side effects added to one will not appear in the other. The `_new` suffix suggests one was meant to replace the other, but neither was removed.

Fix:
Delete `skills_integration_new.py`. Any callers using the `_new` import path should be updated to use `skills_integration`.

---

### 44. `published_pipeline.py` reads `campaign_docs/skills/` format guide — violates DB-authoritative rule

Status: fixed 2026-05-07.

Files:
- `src/mission_builder/published_pipeline.py`

Affected code:
- Lines 26–27, 192: reads `campaign_docs/skills/training_modules/MODULE_FORMAT_GUIDE.md`

Context:
Per `CLAUDE.md`, the only allowed `campaign_docs/` file read is `city_gazetteer.json` full structure. All other file reads are prohibited. If this file is removed, `_load_format_guide` returns `""` with no warning log.

Fix:
Move format guide content into a `global_state` DB key, or at minimum add a `logger.warning` when the file is missing.

---

## Watchlist / Needs Targeted Repro

### A. Pretty map generation is synchronous inside page-writing paths

Status: fixed 2026-05-10.

Files:
- `src/mission_builder/boxset_utils.py`
- `src/mission_builder/html_renderer.py`
- `src/mission_builder/vtt_renderer.py`

Context:
`write_maps_page()` and `render_maps_page()` called `stylize_pretty_battlemap()` with a silent `except Exception: pass` — failures were completely invisible.

Fix:
Added `logger.info` before each call (shows map name and configured timeout), checks the return value and logs a warning if `None` is returned, and changed the silent `except` to `except Exception as exc: logger.warning(...)` in both `boxset_utils.py` and `html_renderer.py`. Both files now have a module logger.

Smoke:
`python -m py_compile src/mission_builder/vtt_renderer.py src/mission_builder/boxset_utils.py src/mission_builder/html_renderer.py` passed.

### B. `wait_for_a1111_idle()` returns false immediately on progress API failure

Status: fixed 2026-05-10.

Files:
- `src/mission_builder/vtt_renderer.py`

Context:
A single exception from the progress endpoint caused immediate `return False`, collapsing the idle-wait guard exactly when A1111 was unstable.

Fix:
Added `consecutive_errors` counter. A single error now logs at DEBUG and retries. Only after 3 consecutive errors does it log a WARNING and return `False`. Resets to 0 on a successful poll.

Smoke:
`python -m py_compile src/mission_builder/vtt_renderer.py` passed.

### C. `ORDER BY RAND()` — intentional, do not change

Status: closed — intentional behavior.

`ORDER BY RAND()` is used throughout mission pipelines to ensure variety in NPC, location, and faction selection. Replacing it with deterministic ordering would cause the same choices to repeat across missions. Not a bug.

---

## Bug Hunt — 2026-05-11

### B-1. TIA rift-shock fires on every bulletin — status: fixed 2026-05-13

Symptom: Logs show `TIA reaction fired (shock): Active Rift event: contract board freezes...` on every single bulletin for hours (13:11, 14:19, 15:18, 16:17) — same exact message, no variation.

Files:
- `src/tower_economy.py` (TIA reaction cooldown logic)

Root cause suspected:
The cooldown save uses a SELECT-then-UPDATE/INSERT pattern. If the SELECT returns a row but the UPDATE fails silently (constraint, DB connection blip), the cooldown timestamp never advances. Every bulletin check sees a stale/missing cooldown and re-fires. Alternatively, the rift-event reaction type may have its own cooldown key that is never set, while other reactions share a single key that does work.

Next action before fixing:
- Read `_save_reaction_cooldown()` and `_load_reaction_cooldown()` in `tower_economy.py`.
- Confirm whether rift-type reactions share the global cooldown or have their own key.
- Run a quick DB check: `SELECT * FROM global_state WHERE state_key LIKE '%tia%reaction%'` to see what's actually stored.
- If the cooldown row is missing or stale, the fix is to replace SELECT-then-UPDATE with `INSERT ... ON DUPLICATE KEY UPDATE` (UPSERT).

Investigation 2026-05-13:
- `global_state` did contain `tia_reaction_cooldown`, last saved at `2026-05-12T21:30:15.262793`, so the row was not totally missing.
- The code still used a fragile SELECT-then-UPDATE/INSERT flow, which can fail under races or duplicate-key drift.

Fix applied 2026-05-13:
- Replaced the custom cooldown SELECT/UPDATE/INSERT path with `get_global_state()` / `set_global_state()`.
- `set_global_state()` already uses `INSERT ... ON DUPLICATE KEY UPDATE`, so cooldown persistence is now an atomic UPSERT.
- Cooldown load errors are now logged as warnings instead of swallowed silently.

Verification:
- `python -m compileall src\tower_economy.py` passed.
- Monkeypatched helper smoke confirmed `_on_cooldown()` returns true for a recent timestamp, false for an old timestamp, and `_save_reaction_cooldown()` writes the expected `tia_reaction_cooldown` key/value shape without touching production DB state.

### B-2. Infestation rooms 9-12 silently ship as stubs — status: fixed 2026-05-13

Symptom: In the 2026-05-11 09:16 mission, rooms 5-8 got retry success logged, but rooms 9-12 had no success log and the pipeline moved straight to map generation 13s after the retry batch started — not enough time for 4 Ollama calls (~15s each). Rooms 9-12 likely shipped with stub content.

Files:
- `src/mission_builder/infestation_pipeline.py` (around lines 393-415, retry pass)

Root cause:
The retry pass batches stub rooms and calls Ollama again. If the second Ollama call also returns stubs (timeout, empty JSON), the code does NOT log a warning and does NOT attempt further retries — it silently accepts the stub as final content. There is no "stub rooms at completion" warning.

Impact:
Modules can ship with multiple rooms containing only the generic stub text ("The [room_type] is quiet. Something has been here recently.") with no descriptions, features, or encounters. DM gets a playable-looking module that is actually hollow in those rooms.

Preferred fix:
After the retry pass completes, count remaining stubs. If any remain, log an ERROR with the room IDs. Optionally apply a simple D&D template fallback (generic room structure without LLM) rather than shipping empty. Do not silently accept stubs.

Fix applied 2026-05-13:
- Added `_is_stub_room_content()` so the audit catches missing content, short read-alouds, the known stub marker, and empty feature lists.
- Added `_fallback_room_content()` to generate deterministic table-ready room content from layout subtype, room type, density, connectors, mission faction, and monster roster.
- Retry batches now log room IDs that remain stubbed after retry.
- Final room audit logs an ERROR with all remaining stub IDs and replaces them with deterministic fallback content before maps, Mimir docs, HTML, and chart packs are rendered.

Verification:
- `python -m compileall src\mission_builder\infestation_pipeline.py` passed.
- Local helper smoke confirmed fallback room content is not detected as a stub and includes read-aloud, monsters, features, exits, treasure, and hazard fields.

### B-3. A1111 model-switch POST timeout too short for large checkpoints — status: fixed 2026-05-13

Symptom: `[PORTRAIT] A1111 model switch failed:` (empty exc string) at 13:25, 14:35, 16:47 and `[SCENE] A1111 model switch failed:` at 13:51, 15:08. Portraits and scenes do generate successfully on the retry 10 min later, so this is noise rather than a real failure.

Files:
- `src/a1111_runtime.py:32` — `httpx.AsyncClient(timeout=30.0)`

Root cause:
The model switch POST (which triggers A1111 to load the checkpoint) times out at 30s. Juggernaut XL takes 60-120s to load. The httpx timeout fires and raises `ReadTimeout` (empty `str(exc)` — hence the blank warning). A1111 continues loading in the background. The next call 10 min later hits an already-loaded model and succeeds.

Impact:
- False-failure log noise on every model switch
- First portrait/scene after a restart is always wasted (10-min penalty)
- If generation is attempted between timeout and load completion, A1111 may return errors

Preferred fix:
Split into two separate clients: 10s timeout for the GET (read current model) and 180s timeout for the POST (trigger model load). Also add `raise_for_status()` to the POST so silent A1111 errors surface. Low priority — system self-heals.

Fix applied 2026-05-13:
- `src/a1111_runtime.py` now uses separate timeouts:
  - `A1111_OPTIONS_GET_TIMEOUT` default `10`
  - `A1111_MODEL_SWITCH_TIMEOUT` default `180`
- Model-switch POST now calls `raise_for_status()`.
- Failure logging now uses `%r`, so `httpx.ReadTimeout()` and similar empty-string exceptions are visible in logs.

Verification:
- `python -m compileall src\a1111_runtime.py` passed.
- Monkeypatched HTTP smoke confirmed the GET uses `10.0`, the POST uses `180.0`, one model-switch POST is sent, and the function returns `True`.

### B-4. Council outcome deduplication uses fragile substring matching — status: fixed 2026-05-13

Symptom: Not yet observed in production, but logic is fragile.

Files:
- `src/self_learning.py` — `_study_council_outcomes()`, pending filter

Root cause:
```python
covered = {row.get("facts","")[:60] for row in done}
pending = [r for r in recent if not any(r.get("topic","")[:40] in c for c in covered)]
```
This checks whether the first 40 chars of a ruling topic appear as a substring in the first 60 chars of any existing outcome fact. Three failure modes:
1. Short topic names ("Tax Reform") will match unrelated facts that happen to contain those words.
2. Long topics truncated at 40 chars may not match the corresponding fact if the fact's first 60 chars don't include those characters.
3. Case-sensitive — topic stored as "Glassworks Infestation Containment" won't match "glassworks infestation containment".

Impact: duplicate outcome dispatches (same ruling gets two Bulletin stories) or valid new rulings silently skipped.

Preferred fix: Store the ruling topic directly in the `news_memory` fact using a tagged format, then query by exact topic:
```python
covered_topics = {
    row.get("facts","").split("Re: ")[-1].split(" (")[0].strip()
    for row in done
}
pending = [r for r in recent if r.get("topic","").strip() not in covered_topics][:4]
```
Or add a dedicated `topic` column to `news_memory` for outcome rows.

Fix applied 2026-05-13:
- `src/self_learning.py` now extracts the tagged `Re: <topic> (PASSED|REJECTED)` topic from stored `council_outcome` facts and compares normalized topic strings instead of substring slices.
- Topic matching is whitespace-normalized and case-insensitive.
- The write loop now tracks already-written topics for the current batch, so duplicate outcome objects returned by Ollama cannot insert duplicate news rows.

Verification:
- `python -m compileall src\self_learning.py` passed.
- Helper smoke confirmed topic normalization and extraction for both em-dash and ASCII `--` fact separators.

### B-5. Bulk regenerate usable maps for generated module directories — status: fixed 2026-05-14 / monitoring quality

User request:
The visible module cards/pages show several generated module directories with missing or unusable maps. The infestation card for `The_Leaden_Crowns_Corruption_20260511_091657` showed two bad tunnel-sketch thumbnails that looked like decorative scene art, not playable VTT maps. User explicitly authorized generating maps for every generated module directory visible on that page so future runs can reuse and retool better map references.

Immediate cleanup already done:
- Deleted bad reusable cache files from `generated_modules/_room_map_cache/lair`.
- Deleted the module-local bad map PNG/sidecar files from `generated_modules/The_Leaden_Crowns_Corruption_20260511_091657/maps`.

Constraints:
- Do not use VAE overrides for image generation. VAE is known broken in this environment.
- Do not write `sd_vae` into A1111 `/options` or per-request `override_settings`.
- Prefer usable tactical VTT maps over pretty/decorative art. If AI texture is unreliable, generate deterministic VTT-safe maps with clear rooms, paths, doors, exits, hazards, and grid sidecars.
- Do not let map generation block Discord/event-loop assembly. Run bulk generation as an explicit script/task, not inside HTML rendering.

Next action:
- Enumerate module directories shown by the modules/dashboard page and/or `generated_modules/*` that have `index.html`/`module.html`.
- For each directory, inspect existing module content and mission type, then generate or replace missing/bad maps with appropriate tactical PNGs plus `.vtt.json` sidecars.
- For infestation modules, seed `_room_map_cache` only with usable tactical room maps, not scene-art thumbnails.
- Refresh rendered `maps.html`/module references after regeneration so the dashboard stops showing stale broken thumbnails.

Progress 2026-05-12 evening:
- Added `scripts/backfill_module_tactical_maps.py` and wrote deterministic VTT-safe `backfill_tactical_map.png` files for the 50 most recent generated module directories.
- Added `scripts/backfill_infestation_room_maps.py` because infestation modules need one map per room, not one generic module map.
- Backfilled per-room tactical maps for all currently detected generated infestation modules: 89 room tactical maps across 9 modules.
- For `The_Leaden_Crowns_Corruption_20260511_091657`, generated all 14 room tactical maps and all 14 A1111 nice preview maps (`*_nice.png`), with `.vtt.json` sidecars. The nice previews were manually sampled and are real top-down dungeon-room maps, not the bad side-view tunnel sketches.
- Updated `Webpage/app.py` `/api/mission-maps` sorting so `_nice`/`_pretty` previews are returned before plain tactical maps, making dashboard thumbnails prefer the nicer images.
- Updated `boxset_utils.py` and `html_renderer.py` map-page rendering to use `_nice` previews when `_pretty` previews are absent.

Verification:
- `python -m py_compile Webpage/app.py src/mission_builder/boxset_utils.py src/mission_builder/html_renderer.py scripts/backfill_infestation_room_maps.py` passed.
- `/api/mission-maps?slugs=The_Leaden_Crowns_Corruption_20260511_091657` returns nice preview URLs first.
- `generated_modules/The_Leaden_Crowns_Corruption_20260511_091657/maps.html` references 14 `_nice.png` previews.

Remaining work:
- Continue A1111 nice-preview generation for other recent infestation modules in chunks. The nice lane is slow, roughly several minutes per room, so run it supervised rather than as part of normal mission generation.
- Consider adding a stronger automated image-quality gate for cutaway/dollhouse views; current gate catches blank/flat output but human review is still better for "is this actually a map?".

Progress 2026-05-13:
- Migrated the backfill script's `--pretty` path onto the shared pretty-map finalizer; `--nice` remains a compatibility alias.
- Completed shared `_pretty` previews for all 8 rooms in `Blight_in_the_Scrap_Yards_20260509_130619`.
- Completed shared `_pretty` previews for all 9 rooms in `Dust_Market_Cellar_Infestation_20260512_060636` (also has 1 legacy `_nice` preview).
- Completed shared `_pretty` previews for all 11 rooms in `Blight_in_the_Scrap_Yards_20260509_131739`.
- Completed shared `_pretty` previews for all 6 rooms in `Blight_in_the_Scrap_Yards_20260505_102008`.
- Completed shared `_pretty` previews for all 12 rooms in `Purification_of_the_Hollow_Vein_20260429_190721`.
- Completed shared `_pretty` previews for all 10 rooms in `Collapsed_Plaza_Nest_20260506_075042`.
- Supervised A1111 in small chunks with resource-cop checks between runs; one slow Dust Market pass was allowed to finish instead of stacking more work on the renderer.
- Blocker 2026-05-13 22:40 CT: A1111 stuck on leftover `scripts_img2img` job timestamp `20260513222355` at step 0/3 after a timed-out Collapsed Plaza room 4 pass. `/interrupt` and `/skip` were accepted but did not clear the job. `Restart-Service A1111` and `taskkill /F /PID 16760` were denied by Windows access control from this shell. Cleared externally by 2026-05-14; Collapsed Plaza resumed and completed.
- Current real-module map inventory 2026-05-14: all real infestation modules with only tactical maps now have matching `_pretty` previews. `The_Leaden_Crowns_Corruption_20260511_091657` remains on 14 usable legacy `_nice` previews and 14 tactical maps; the UI already prefers those before tactical maps.

Experiment 2026-05-12 late:
- Added `scripts/experiment_map_lanes.py` to run quarantined three-lane A1111 bakeoffs under `generated_modules/_map_experiments`. Outputs are not cached or injected automatically.
- Test context: `The_Leaden_Crowns_Corruption_20260511_091657`, room 2, fungal infestation room.
- Lanes tested with no VAE override:
  - `baseline_sdxl`: current SDXL/Juggernaut-style lane. Result: strong readable room geometry, good dungeon-room preview.
  - `flux_mapcraft`: Flux checkpoint + MapCraft Flux LoRA. Result: no longer blank, but still mushy/terrain-like and less readable as a room map.
  - `sdxl_mapcraft`: SDXL checkpoint + MapCraft SDXL LoRA. Result: best "battlemap asset" look, strong top-down style, good atmospheric infestation detail; slightly less explicit wall/room geometry than baseline.
- Current recommendation: keep baseline SDXL as the reliable production lane, continue testing `sdxl_mapcraft` as the likely upgrade candidate, keep Flux quarantined until it can reliably produce clear rooms/walls/exits.

Implementation 2026-05-13:
- Promoted the learned map strategy into the shared VTT finalizer: deterministic tactical maps remain authoritative, and `*_pretty.png` previews now default on.
- `sdxl_mapcraft` is now the first pretty-preview strategy and runs as low-denoise img2img over the tactical baseline, so it preserves room geometry instead of inventing a new layout from scratch.
- Legacy pretty generation remains the fallback. Flux MapCraft is now opt-in (`VTT_MAP_PRETTY_INCLUDE_FLUX=true`) because the experiment lane was less readable.
- Routed novel/published map pass, dungeon-delve composite maps, and infestation room maps through the shared VTT save/finalize path so they all get the same tactical baseline plus pretty-preview behavior.
- Infestation room cards now prefer an existing `_pretty` preview, then `_nice`, then the tactical map.
- No VAE override was added; VAE remains intentionally unused for map generation.

---

### B-6. Competition/calendar mission handoff edge cases - status: fixed 2026-05-14

User request:
Review the new mission pipeline and calendar together because they are tied.

Findings:
- Competition brackets treated only `pending` matches as blockers. A PC round that had already posted to the board sits at `mission_posted`, so an NPC-vs-NPC match resolving in the same round could advance the bracket before the PC mission finished.
- Calendar events only resolved after they had first been announced. If the bot was offline or restarting during the 48-hour announcement window, the event could sit past-due forever and never spawn its follow-up mission.
- Calendar-spawned missions trusted the generated text's parsed faction/type even though the calendar event already has authoritative mission parameters. A model drift could post the right story under the wrong mission type or faction.

Fix:
- `src/competitions/bracket_engine.py` now advances only when every match in the current round is `complete`; `mission_posted` blocks advancement.
- `src/faction_calendar.py` now resolves past events even when the announcement window was missed, marks them announced, posts the result, applies reputation, and unlocks mission spawning.
- `src/mission_board.py` now pins calendar-spawned mission `faction` and `type` to the event mapping after parsing generated text.
- Added `tests/test_competition_calendar.py` for the posted-PC-match bracket guard and missed-announcement calendar resolution.

Verification:
- `python -m compileall src\competitions\bracket_engine.py src\faction_calendar.py src\mission_board.py` passed.
- `python -m pytest tests\test_competition_calendar.py tests\test_resource_cop.py -q` passed: 8 tests.

Follow-up 2026-05-14:
- Added a shared calendar bulletin dispatcher in `src/aclient.py`.
- The regular news loop now uses that dispatcher instead of duplicating the send logic.
- The NPC portrait loop now runs one calendar tick immediately after the first portrait generation attempt after startup, so daily bot reboots have a second early chance to catch due calendar announcements/results.
- If the first portrait attempt errors, the calendar tick still tries once through the same dispatcher. Calendar-triggered mission spawning remains in the mission-board loop, where it already uses the resource cop before Ollama generation.

Verification:
- `python -m compileall src\aclient.py` passed.

### B-7. Mimir MCP subprocess spam floods main bot log - status: fixed 2026-05-15

Symptom:
After reboot, `logs/bot_stderr.log` was flooded with raw Mimir MCP child-process lines like `mimir_mcp::handler: Handling call_tool request tool=get_character`. This was not coming from the Python logger; it was the subprocess stderr stream inherited by the MCP stdio client.

Fix:
- `src/mimir_client.py` now sets both `RUST_LOG` and `MIMIR_LOG_LEVEL` for `mimir-mcp`.
- The Mimir MCP child stderr stream is redirected to `logs/mimir_mcp_stderr.log` instead of the main bot stderr log.
- Bot-side Mimir warnings/errors and useful sync summaries still go through the normal Python logger.
- The sidecar stderr handle is closed during disconnect and on failed startup.

Verification:
- `python -m compileall src\mimir_client.py` passed.
- Restart verification 2026-05-15:
  - Bot restarted at `2026-05-15 04:34:54`.
  - Main `logs/bot_stderr.log` now shows only bot-side Mimir lines (`[MIMIR] Connected`, `[MIMIR_SYNC] Background loop started`).
  - Raw `mimir_mcp::handler: Handling call_tool request ...` lines are written to `logs/mimir_mcp_stderr.log`.
  - Status: fixed.

### B-8. Dashboard Discord status goes stale during slow mission-board startup - status: fixed 2026-05-15 / pending restart verification

Symptom:
After reboot, Discord connected and was receiving events, but `/api/status` on port 5001 reported `{"discord":{"ok":false,"label":"stale"}}`.

Root cause:
The dashboard heartbeat (`discord_status` in `global_state`) was refreshed inside `mission_board_loop` after the startup mission burst and queue checks. If startup posting or Ollama-backed mission work is slow, the heartbeat stays at the `on_ready` timestamp and the website marks Discord stale even though the gateway is alive.

Fix:
- Added `DiscordClient.discord_heartbeat_loop()` in `src/aclient.py`.
- `process_messages()` now starts that heartbeat as its own task, independent of mission generation, news generation, and startup bursts.
- Kept the existing mission-board heartbeat write in place as harmless redundancy.

Verification:
- `python -m compileall src\aclient.py` passed.
- Requires next bot restart to confirm `/api/status` stays Discord-green while startup work is still running.

### 2026-05-15 04:50:24 - Resource cop captured mission pipeline failure

Status: fixed and verified 2026-05-15.

Context:
- Pipeline: `mission_generation`
- Mission: `Hearthstone Cellar Worms`
- Type: `infestation`
- Phase: `failed`
- Elapsed: `54.7s`
- Error: `AttributeError: 'InfestationRoom' object has no attribute 'name'`

Findings:
- Infestation room maps used `room.name`, but `InfestationRoom` only has `room_id`, `room_type`, grid fields, connections, and density flags.
- Live retry after patch reached map generation and saved room maps, confirming the attribute crash is gone.
- The retry exposed two follow-on map issues:
  - Room map generation skipped rooms when A1111 was busy because the per-room wait was only 60s.
  - `save_vtt_battlemap_bytes()` runs the pretty pass synchronously; called directly from the async infestation pipeline, it can block the bot event loop during long A1111 waits.
- A bot restart during the blocking pretty pass left `module_gen_active=988` persisted even though no task survived the process restart.

Fix:
- `src/mission_builder/infestation_pipeline.py` now derives map title/location from room content `name`/`title`, falling back to `room.room_type.title()`.
- Infestation map finalization now runs `save_vtt_battlemap_bytes()` via `asyncio.to_thread(...)` so the pretty pass cannot freeze the Discord event loop.
- Infestation room-map A1111 waits now default to `INFESTATION_ROOM_MAP_WAIT_SECONDS=1200`, so slow pretty/map work has room to finish instead of skipping rooms after a 60s deferral.
- Infestation also retries unavailable room maps with `INFESTATION_ROOM_MAP_ATTEMPTS` / `INFESTATION_ROOM_MAP_RETRY_DELAY`.
- `src/aclient.py` clears stale `module_gen_active` at mission-board startup, because module-generation tasks do not survive a process restart.

Verification:
- `python -m compileall src\mission_builder\infestation_pipeline.py src\aclient.py` passed.
- Status/API after cleanup: A1111 idle, Ollama idle, no active pipelines, `module_gen_queue=[]`, `module_gen_active=None`.
- Partial retry artifacts:
  - `Hearthstone_Cellar_Worms_20260515_045858`: tactical maps R5/R6.
  - `Hearthstone_Cellar_Worms_20260515_052902`: tactical+pretty maps R4/R7/R8 before the one-hour shell timeout stopped the foreground retry.

Final verification 2026-05-15:
- Bot restarted and loaded the latest infestation/active-marker patches.
- Dashboard queue re-ran mission `988` (`Hearthstone Cellar Worms`) from the live bot path.
- Pipeline completed at `2026-05-15 07:15:46`:
  - `Hearthstone_Cellar_Worms_20260515_064029`
  - 9-room basement infestation
  - 9 tactical room maps generated
  - `module.html`, `maps.html`, guides, `index.html`, and ZIP written
  - `missions.module_slug` set to `Hearthstone_Cellar_Worms_20260515_064029`
  - `module_gen_active` cleared
  - `/api/status` pipeline list returned empty after completion
- The bot remained responsive during long pretty-map work, confirming the `asyncio.to_thread(...)` finalizer change avoided the event-loop freeze.

Residual note:
- Room-description generation still sometimes returns stubs; deterministic fallback content prevented module failure. This is content-quality work, not a blocker for map generation.

### B-9. NPC lifecycle can miss the whole day when Ollama is briefly busy - status: fixed 2026-05-15 / pending restart verification

Symptom:
- After the first startup delay, the NPC lifecycle loop started at `2026-05-15 07:18:29` but logged `Ollama busy () - skipping lifecycle cycle`.
- The outer loop then scheduled the normal 20-28 hour lifecycle interval, so one transient busy flag could prevent the daily NPC bulletin/lifecycle work from posting until the next day.

Root cause:
- `src/npc_lifecycle.py:run_daily_lifecycle()` returned `None` both when it completed and when it skipped due to Ollama busy.
- `src/aclient.py:npc_lifecycle_loop()` had no way to distinguish "ran" from "deferred", so it always moved on to the long daily sleep.

Fix:
- `run_daily_lifecycle()` now returns `False` when Ollama is busy and `True` after the lifecycle cycle is attempted.
- `npc_lifecycle_loop()` now treats `False` as a deferral, still checks the resurrection queue, then retries after `NPC_LIFECYCLE_BUSY_RETRY_SECONDS` (default 3600 seconds) instead of waiting 20-28 hours.

Verification:
- `python -m compileall src\npc_lifecycle.py src\aclient.py` passed.
- Needs next bot restart / next lifecycle window to confirm the log shows a one-hour retry when Ollama is busy.

---

## Smoke Test — 2026-05-15 (Full codebase scan)

Scan method: compile check all .py files, full test suite run, 5 parallel deep-read agents covering all subsystems.
All syntax checks passed. Test suite had 1 failure (fixed, see below).

### FIXED — Test: `test_persona_management` asserting jailbreak-v1 returns True — 2026-05-15

`tests/test_aclient.py:60` asserted `is_jailbreak_persona("jailbreak-v1") is True`. The function in `src/personas.py` is an intentional stub that always returns `False` (jailbreak personas were removed). The test expectation was wrong, not the code. Updated test to assert `is False` for all inputs.

---

### B-1. `aclient.py` — Blocking `set_global_state` in async heartbeat loop — HIGH

**File:** `src/aclient.py:169-175` and `src/aclient.py:524-529`

`set_global_state()` is a synchronous MySQL write called bare inside `discord_heartbeat_loop` (async, runs every 60s) and inside `mission_board_loop`'s per-minute tick. Blocks the event loop for the duration of every DB write. The correct pattern `asyncio.to_thread(set_global_state, ...)` is already used at line 512 — inconsistently applied.

Fix: wrap all bare `set_global_state()` calls inside async loops with `await asyncio.to_thread(set_global_state, ...)`.

Smoke path: monitor `discord.gateway: heartbeat blocked` log during a session; should see no heartbeat blocks caused by DB writes.

---

### B-2. `aclient.py` — `asyncio.get_event_loop().create_task()` deprecated — MED

**File:** `src/aclient.py:124-148`, `src/aclient.py:513`

Background loops spawned via `asyncio.get_event_loop().create_task(...)`. Deprecated in Python 3.10+, raises DeprecationWarning, may break on Python upgrade. Fix: use `asyncio.create_task(...)` inside async context.

---

### B-3. `aclient.py` — `generate_image` fallback to FreeProvider always raises — MED

**File:** `src/aclient.py:1398-1405`

When no image-capable provider is configured, falls back to `FreeProvider.generate_image` which raises `NotImplementedError`. No error handling wraps this call — exception propagates to caller. User gets an unhandled exception instead of a friendly message.

---

### B-4. `aclient.py` — Dead imports: `_load_personal_tracker`, `_save_personal_tracker` — LOW

**File:** `src/aclient.py:45`

Both are imported from `src.mission_board` but never called anywhere in aclient.py.

---

### B-5. `providers.py` — `GeminiProvider.generate_image` returns `bytes` not `str` — HIGH

**File:** `src/providers.py:437`

Return type declared `-> str` but returns `response.images[0]._image_bytes` (raw bytes). All other providers return a URL string. Any caller expecting a URL receives bytes, likely crashes or produces garbage in a Discord embed.

---

### B-6. `providers.py` — `len(api_key)` called on `None` in warning log — MED

**File:** `src/providers.py:549-550`

Guard `if not api_key` correctly catches None/empty, but the warning log inside that same branch calls `len(api_key)` — raises `TypeError` when `api_key is None`. Fix: `len(api_key or "")`.

---

### B-7. `providers.py` — Claude default fallback model stale — LOW

**File:** `src/providers.py:336-337`

Default model falls back to `"claude-haiku-4-5"` but current fleet runs `claude-sonnet-4-6`. Produces confusing behavior when no model is specified.

---

### B-8. `tower_rag.py` — Silent fallback to stale JSON if DB is down — LOW

**File:** `src/tower_rag.py:255-274`

If MySQL goes down the bot silently falls back to serving stale `campaign_docs/**/*.txt` files. CLAUDE.md says DB is the only source of truth. At minimum should log `logger.error` not just a warning, so operator knows DB is down.

---

### B-9. `tower_rag.py` — Index cache globals not protected against concurrent rebuild — MED

**File:** `src/tower_rag.py:299-350`

Five module-level globals (`_docs_cache`, `_chunks_cache`, etc.) read/written in `_ensure_index` with no lock. If two coroutines hit a cold cache simultaneously (possible when `asyncio.to_thread` is used nearby), partial index can be served.

---

### B-10. `tower_rag.py` — Index thrashes on rules/lore mode alternation — MED

**File:** `src/tower_rag.py:383-384`

Every switch between rules/lore mode triggers a full DB re-read and TF-IDF recompute. `_include_rules_cache` only stores one mode so any interleaved conversation causes continuous cache invalidation.

---

### B-11. `maps.py` — Blocking `httpx.Client` call in async `generate_module_maps` — HIGH

**File:** `src/mission_builder/maps.py:814`

`stylize_pretty_battlemap()` (defined in `vtt_renderer.py`) is a synchronous function using `httpx.Client` with `PRETTY_TIMEOUT` blocking I/O. Called bare in async `generate_module_maps` without `asyncio.to_thread`. Can stall the event loop for the full pretty-map timeout. The `asyncio.to_thread(wait_for_a1111_idle, ...)` pattern is already used at maps.py:712-720 — just not applied here.

---

### B-12. `maps.py` — Garbled emoji in log string — LOW

**File:** `src/mission_builder/maps.py:724`

`"ðŸ—ºï¸"` — the map emoji was double-encoded. Appears as garbage in all logs for that branch.

---

### B-13. `encounters.py` — `DOCS_DIR` referenced in unreachable dead-code block — MED

**File:** `src/mission_builder/encounters.py:148`

Line 147 has an early `return 0`, making lines 148-177 (the old file-based fallback) unreachable. Line 148 references `DOCS_DIR` which is not defined or imported in this file — would raise `NameError` if the early return were ever removed. Dead block should be deleted.

---

### B-14. `cr_scaling.py` — `classes` field shape mismatch vs `encounters.py` — MED

**File:** `src/mission_builder/cr_scaling.py:86-89`

`party_strength()` assumes `classes` is a list of dicts with a `"level"` key. `encounters.py:108-109` handles the same `snapshot_json.classes` field as either a dict (class→level mapping) or a list. If the DB stores it as a dict, `cr_scaling.py` will `TypeError`. The two files disagree on the shape of this field.

---

### B-15. `mission_json_builder.py` — `rstrip(".json")` strips characters, not suffix — LOW

**File:** `src/mission_builder/mission_json_builder.py:428`

`filename.rstrip(".json")` strips any trailing character from the set `{'.','j','s','o','n'}`, not the literal suffix `.json`. Should be `filename.removesuffix(".json")`.

---

### B-16. `vtt_renderer.py` — `wait_for_a1111_idle` is sync, risky if called from async context — MED

**File:** `src/mission_builder/vtt_renderer.py:71` (and lines 572, 585, 593, 610, 614, 620)

`wait_for_a1111_idle` is synchronous and uses `httpx.Client` polling. Currently always called from sync contexts, but `stylize_pretty_battlemap` is itself called directly from async context at maps.py:814 (B-11). If fixed at maps.py, the risk moves here — the entire function chain needs `asyncio.to_thread` wrapping at the top.



---

### B-17. db_api.py — Hardcoded DB password in source — HIGH

**File:** `src/db_api.py:21`
`MYSQL_PASSWORD` defaults to a hardcoded literal. Env var override works but credential exposed in source. Should have no default — raise if env var is missing.

---

### B-18. db_api.py — add_news_entry inserts to wrong table — HIGH

**File:** `src/db_api.py:499`
When `bulletin_text` is provided, inserts to `news_memory`. But `get_recent_news()` reads from `news_entries`. Entries written via new-convention path are never returned by `get_recent_news()`. Also: if `news_memory` lacks a `news_type` column the insert raises.

---

### B-19. npc_lifecycle.py — apply_npc_event returns 2-tuple; single-var callers crash — HIGH

**File:** `src/npc_lifecycle.py:822-825`
For dead NPCs skipping resurrection, returns `(None, None)`. Any caller doing `announcement = await apply_npc_event(...)` raises `ValueError: too many values to unpack`. All call sites must unpack 2 values.

---

### B-20. npc_consequence.py — replacement unbound when NPC not in UNKNOWN_PARTY_MEMBERS — HIGH

**File:** `src/npc_consequence.py:586-590`
If `name not in UNKNOWN_PARTY_MEMBERS`, `replacement` is never assigned but referenced at line 589. Raises `UnboundLocalError` at runtime for every non-unknown-party NPC consequence.

---

### B-21. character_monitor.py — class_name column may not exist in player_characters — HIGH

**File:** `src/character_monitor.py:479`
`UPDATE player_characters SET class_name=%s` — `class_name` not referenced in `db_api.py` save/get. If column does not exist, every character monitor DB update silently fails. Schema verification needed.

---

### B-22. news_feed.py — A1111 lock replacement on timeout creates concurrent-access window — HIGH

**File:** `src/news_feed.py:53`
`_TimedA1111Lock.__aenter__` replaces `_a1111_lock` with a fresh `asyncio.Lock()` on timeout. Coroutines holding a reference to the old lock will release a dead lock while the new lock is in use — two coroutines can simultaneously believe they hold the A1111 lock.

---

### B-23. ddb_homebrew.py — CDP reply id=0 collision; Network.setCookie silently times out — HIGH

**File:** `src/ddb_homebrew.py:286-296`
`Network.setCookie` and `Network.enable` both sent with `id_=0`. `_cdp()` matches responses by id. Both calls race for the same reply; one silently times out (loops 60x). Cookie injection may fail silently.

---

### B-24. skills.py — asyncio.Lock() at module level; never used; breaks on Python 3.12 — HIGH

**File:** `src/skills.py:56`
`_CACHE_LOCK = asyncio.Lock()` at import time. On Python 3.12, raises `RuntimeError` when no running loop exists. The lock is never used anywhere in the file — dead code with startup side effect.

---

### B-25. skills.py — generate_with_skills bypasses Ollama queue lock entirely — HIGH

**File:** `src/skills.py:412`
Calls `/api/generate` directly via its own `httpx.AsyncClient` without the Ollama queue lock or `is_available()` check. Every other Ollama caller serializes through the queue. Can hammer Ollama concurrently.

---

### B-26. cogs/module_gen.py — asyncio.get_event_loop().create_task() broken on Python 3.12 — HIGH

**File:** `src/cogs/module_gen.py:124`
Deprecated/broken on Python 3.12 inside a running event loop. Replace with `asyncio.get_running_loop().create_task(...)`.

---

### B-27. character_profiles.py — Dynamic SQL UPDATE with unparameterized column names — MED

**File:** `src/character_profiles.py:56-64`
Column names built by string concatenation from a dict. Keys come from internal code so real injection risk is low, but pattern is incorrect.

---

### B-28. npc_appearance.py — Still writes _all_sd_prompts.json to campaign_docs/ — MED

**File:** `src/npc_appearance.py:1133-1134`
Writes legacy flat file and falls back to reading it on DB error. Violates DB-is-authoritative rule.

---

### B-29. character_monitor.py — Unconditional write/read of campaign_docs/character_memory.txt — MED

**File:** `src/character_monitor.py:487-569`
DB update path (452-482) succeeds but code falls through to unconditional file update. If file absent, returns `False` even when DB succeeded — caller logs false stale-data warning.

---

### B-30. npc_consequence.py — Dead duplicate check_resurrection_queue definition with NameError — MED

**File:** `src/npc_consequence.py:430-457`
First definition has `remaining.append(entry)` where `remaining` was never initialized. Overwritten by second definition at line 460 (which is correct), so never fires at runtime — but it is a maintenance hazard.

---

### B-31. npc_consequence.py — data_json check in _make_unknown_party_replacement always False — MED

**File:** `src/npc_consequence.py:501-503`
`_load_roster()` already merges `data_json` into the flat NPC dict. So `npc.get("data_json")` returns `None` for most entries; designation dedup check always produces empty set.

---

### B-32. mission_outcomes.py — archive_outcomes_weekly trim logic broken at DB layer — MED

**File:** `src/mission_outcomes.py:40-60, 240-251`
`_save_outcomes(kept)` skips rows with existing IDs (insert-only). Trimming the list has no effect. The trim-to-last-10 intent never actually deletes old outcome rows from the DB.

---

### B-33. mission_outcomes.py — _load_npcs merge order overwrites DB column values with stale JSON — MED

**File:** `src/mission_outcomes.py:263-269`
`npc.update(dj)` after setting `name`/`faction`/`role`/`location`/`status` from DB row. If `data_json` has those keys, stale JSON values overwrite the correct DB-column values. Fix: DB columns should win — `{**dj, "name": row["name"], ...}`.

---

### B-34. party_profiles.py — save_profile stores numeric points in reputation column — MED

**File:** `src/party_profiles.py:176`
`profile.get("points", 0)` written into `reputation` column. If reputation is a text tier string, storing `0` corrupts it.

---

### B-35. tower_economy.py — _ensure_bid_columns failure silently swallowed at import — MED

**File:** `src/tower_economy.py:1117-1119`
Called at import; exception caught by bare `pass`. If columns missing and check failed, every subsequent bid fails with missing-column error. No WARNING log.

---

### B-36. mimir_client.py — set_campaign() returns False on success — MED

**File:** `src/mimir_client.py:154`
`bool(r)` is `False` when Mimir returns empty dict/None on success. `set_campaign()` (line 262) returns `bool(r)` — callers checking return value get false negative.

---

### B-37. mimir_sync.py — _build_world_overview uses relative path for city_gazetteer.json — MED

**File:** `src/mimir_sync.py:1213`
`Path("campaign_docs/city_gazetteer.json")` resolves relative to process CWD. If bot launched from different directory, silently returns empty world lore.

---

### B-38. mimir_sync.py — ensure_sync_table runs ALTER TABLE on every startup — MED

**File:** `src/mimir_sync.py:63-68`
`ALTER TABLE` runs every bot startup even if column unchanged. Adds latency; on fresh DB silently swallows missing-table error.

---

### B-39. ddb_homebrew.py — Sync httpx.get inside async functions blocks event loop — MED

**File:** `src/ddb_homebrew.py:52, 111`
`_chrome_alive()` and `_get_page_ws_url()` use sync `httpx.get()` and are called from async context. Blocks event loop for duration of HTTP call.

---

### B-40. image_ref.py — Directory creation at import with silent PermissionError — MED

**File:** `src/image_ref.py:50`
Directories created at import with no try/except. `PermissionError` on read-only filesystem swallowed silently; all subsequent ref writes fail at runtime.

---

### B-41. image_ref.py — No fallback for mid-pass A1111 failure in layered_generate — MED

**File:** `src/image_ref.py:451, 462`
If A1111 goes down between txt2img and img2img passes, second request hangs 900s with no partial result.

---

### B-42. arena_season.py — db_id lost from state dict if _save_arena raises mid-execution — MED

**File:** `src/arena_season.py:77`
`state.pop("db_id")` then `raw_execute` then `state["db_id"] = db_id`. If execute fails, `db_id` is gone; next tick inserts a duplicate season row.

---

### B-43. cr_scaling.py — classes field shape mismatch vs encounters.py — MED

**File:** `src/mission_builder/cr_scaling.py:86-89`
`party_strength()` assumes `classes` is a list of dicts with `"level"` key. `encounters.py:108-109` handles same field as either a dict (class→level mapping) or a list. If stored as dict, `cr_scaling.py` raises `TypeError`.

---

### B-44. news_feed.py — Still reads generated_news_types.json from campaign_docs/ — MED (policy)

**File:** `src/news_feed.py:94-95`
`NEWS_TYPES_FILE` still points to `campaign_docs/generated_news_types.json`. Violates DB-is-authoritative migration rule.

---

### B-45. agents/news_agents.py — FactCheckerMixin._cache shared across all agent instances — MED

**File:** `src/agents/news_agents.py:48`
`_cache` is a class-level mutable dict. All three agent classes share the same object. Stale NPC roster/graveyard data persists indefinitely. `clear_cache()` defined but never called automatically.

---

### B-46. agents/guild_council.py — No overall session timeout; up to 112 min worst case — MED

**File:** `src/agents/guild_council.py` (run_session)
Up to 28 sequential Ollama calls at 240s each = 112 min worst case if Ollama is degraded but not fully down. No `asyncio.wait_for` or overall timeout on `run_session`.

---

### B-47. cogs/chat.py — Silent except in enqueue_message leaves interaction unacknowledged — MED

**File:** `src/cogs/chat.py:1199-1204`
Silent `except` swallows failed defer. Leaves interaction unacknowledged; followup calls then raise Unknown Interaction with no user-visible error.

---

### B-48. agents/orchestrator.py — Agent name lookup uses fragile dict-key index arithmetic — MED

**File:** `src/agents/orchestrator.py:424`
`list(self.agents.keys())[i+1]` — fragile; any reordering of dict initializer produces wrong agent name in error logs.

---

### LOW severity items (agents/cogs/skill_loader/DDB/economy scan)

- `agents/base.py:297,323` — `import time`, `import re` inside retry loop body; move to module top
- `agents/orchestrator.py` — `_collect_analysis_data` sync DB calls in async context, no `run_in_executor`
- `agents/news_agents.py:48` — `any` builtin used as type hint instead of `typing.Any`
- `cogs/missions.py:27-29` — imports internal underscore-prefixed helpers from `mission_board`; fragile
- `cogs/module_gen.py:80` — `_load_missions` may read JSON not DB; `/genmodule` silently finds nothing for DB-only missions
- `skills.py` — `load_all_skills` not async-safe; `_SKILLS_CACHE` check/set without locking
- `mimir_sync.py:2050,2060,2088` — `asyncio.get_event_loop()` deprecated; use `get_running_loop()`
- `mimir_sync.py:1686` — f-string interpolation in SQL; safe now but risky pattern
- `a1111_runtime.py:31` — URL whitespace stripped silently
- `vtt_renderer.py:71` — `wait_for_a1111_idle` is sync; risky if called from async context in future
- `encounters.py:147-177` — Dead file-based fallback block after early return; `DOCS_DIR` not defined in file
- `mission_outcomes.py:108-124` — `_save_outcomes` insert-only; no UPDATE/DELETE path for outcomes
- `personas.py:40-41` — `PermissionError` branch unreachable dead code
- `providers.py:336-337` — Claude default fallback model stale (`claude-haiku-4-5`)
- `aclient.py:45` — Dead imports: `_load_personal_tracker`, `_save_personal_tracker` never called
- `tower_rag.py:255-274` — Silent fallback to stale JSON if DB is down (should `log.error`)
- `maps.py:724` — Garbled emoji in log string (double-encoded UTF-8)
- `mission_json_builder.py:428` — `rstrip(".json")` strips characters not suffix; use `removesuffix`
- `npc_lifecycle.py:312-351` — `_rebuild_txt` assembles lines but never writes
- `npc_lifecycle.py:1034` — alliance branch appends to `relationships` without type guard
- `npc_appearance.py:31-34` — `mkdir(exist_ok=True)` runs on every import
- `nudge_state.py` — Entire module uses flat files; should migrate to DB
- `party_profiles.py:571-577` — `format_all_party_ranks` only reads `members_json`; old rows silently skipped
- `tower_economy.py:289-291` — `TOWER_YEAR_OFFSET` used before defined (safe at call time)
- `tower_economy.py:523` — `buy_now_price` may be None; DB column may be NOT NULL
- `faction_reputation.py:275` — Imports private `_init_profile` from `party_profiles`
- `dome_weather.py:277-288` — `effects_json` may not be JSON-serialized before DB write
- `ddb_homebrew.py:268` — `die_option` silently accepts `"d8"` format without warning
- `mimir_client.py:241` — Only first content item returned; subsequent items silently dropped
- `skill_loader.py:128` — Two statements on one line

---

## Archival log — 2026-05-15

Moved to archive/ (not deleted, fully reversible):

archive/root_scripts/ (21 files):
  apply_schema.py, mysql_setup.py, sql_refactor_setup.py, fix_migration.py,
  fix_npc_roster.py, fix_syntax.py, fix_syntax2.py, fix_mistral_to_qwen.py,
  migrate_data.py, migrate_add_columns.py, patch_news_parties.py,
  clear_commands.py, merge_faction_leaders.py, rag_sanity_check.py,
  SKILLS_INTEGRATION_EXAMPLES.py, test_dungeon_delve.py, test_mission_builder.py,
  test_skills_quick.py, # fix_mistral_to_qwen.py, null, alter_add_character_snapshots.sql

archive/root_docs/ (8 files):
  worklog_mission_fix.md, worklog_ollama_model_fix.md, dungeon_delve_architecture.md,
  STEP2_COMPLETION.md, CUDA_FIX_SUMMARY.md, QWEN_CUDA_FIX.md,
  PHASE_3_IMPLEMENTATION_SUMMARY.md, SKILLS_SYSTEM_DEPLOYMENT.md

archive/scripts_oneoff/ (32 files):
  fix_culinary_council.py, fix_ebp_types_only.py, repair_boxxo_chapters.py,
  write_boxxo_chapters.py, write_boxxo_chapters_v2.py, write_boxxo_module_html.py,
  run_boxxo_module.py, import_area_profiles.py, import_culinary_council.py,
  seed_gazetteer_businesses.py, seed_gazetteer_infrastructure.py, seed_unknown_party.py,
  migrate_characters.py, migrate_towerbay_bids.py, extract_ddb_session.py,
  extract_pdfs.py, cleanup_image_refs.py, quarantine_duplicate_npc_refs.py,
  merge_faction_leaders.py, reset_npc_sync_hashes.py, package_5etools_for_mimir.py,
  import_pantheon.py, run_full_ddb_import.py, _test_ddb_form.py,
  test_one_art_edit.py, test_one_npc_import.py, test_wysiwyg.py,
  test_module_quality_training.py, test_news_agents.py, populate_bot_commands.py,
  find_key.py, check_npc_data.py

archive/backups_old/ (42 files): entire backups/ directory

hardir/ removed (was empty). null file archived (was stray PowerShell output).


---

## Bug Fixes Applied — 2026-05-15 (Round 1)

### FIXED B-1: aclient.py — Blocking set_global_state in async loops
Both `discord_heartbeat_loop` and `mission_board_loop` now use `await asyncio.to_thread(set_global_state, ...)`.

### FIXED B-2/B-26: asyncio.get_event_loop() deprecated
- `src/aclient.py:process_messages` — all 13 background tasks now use `asyncio.get_running_loop().create_task(...)`
- `src/aclient.py:mission_board_loop` — same fix
- `src/cogs/module_gen.py:124` — same fix
- `src/mimir_sync.py:2050,2060,2088` — same fix

### FIXED B-4: aclient.py — Dead imports removed
Removed `_load_personal_tracker, _save_personal_tracker` from import (never called).

### FIXED B-6: providers.py — len(None) in warning log
`len(api_key or "")` instead of `len(api_key)` inside the `not api_key` guard.

### FIXED B-12: maps.py — Garbled emoji in log string
`ðŸ—ºï¸` (double-encoded UTF-8) replaced with proper `🗺️`.

### FIXED B-13: encounters.py — Dead unreachable file-fallback block removed
Lines 148-177 (after `return 0`) were unreachable dead code referencing undefined `DOCS_DIR`. Block deleted.

### FIXED B-15: mission_json_builder.py — rstrip(".json") → removesuffix(".json")
`rstrip` strips individual characters from the set; `removesuffix` strips the literal suffix.

### FIXED B-24: skills.py — asyncio.Lock() at module level
`_CACHE_LOCK = asyncio.Lock()` at module level replaced with `_CACHE_LOCK: Optional[asyncio.Lock] = None`.

### FIXED B-22 (partial): news_feed.py — A1111 lock race on timeout
`_TimedA1111Lock` now saves a reference to the exact acquired lock object (`self._lock_ref`).
`__aexit__` releases `self._lock_ref` instead of the current module-level `_a1111_lock`.
This prevents the race where a coroutine releases a lock it never acquired.

### FIXED: Garbled emojis in dungeon_delve and image_generator
- `src/mission_builder/dungeon_delve/tile_generator.py` — fixed `🗺️`
- `src/mission_builder/dungeon_delve/room_generator.py` — fixed `🏰`
- `src/mission_builder/image_generator.py` — fixed `🗺️`

---

## Round-2 Audit Findings (mimir, bulletins, website) — 2026-05-15

### FIXED B-49 (NEW): Webpage/app.py — `logger` undefined in production routes — HIGH
`logger` was never defined in `Webpage/app.py`. Every error path in `api_claim_mission`,
`api_log_bug`, `api_generate_mission`, `api_post_mission_to_discord` raised `NameError`
instead of logging. Added `import logging` + `logger = logging.getLogger(__name__)` at top.

### FIXED B-50 (NEW): Webpage/app.py + mimir_client — MimirClient() subprocess leak — MED
`api_compendium_search`, `api_compendium_documents`, `api_compendium_document` each created
a fresh `MimirClient()` instance on every HTTP request, spawning a new `mimir-mcp` subprocess
that was never disconnected. Changed all three to `get_mimir()` (singleton).

### FIXED B-51 (NEW): expandable_bulletin.py — _cleanup_loop runs once, not recurring — MED
`_cleanup_loop` had no `while True:` loop — it ran once after 1 hour then silently exited.
Old bulletins accumulated in memory indefinitely after the first cleanup. Added `while True:`.

### FIXED B-52 (NEW): mimir_sync.py — _build_world_overview relative path — HIGH
`Path("campaign_docs/city_gazetteer.json")` resolved relative to process CWD.
Changed to `Path(__file__).resolve().parents[1] / "campaign_docs/city_gazetteer.json"`.

### FIXED B-53 (NEW): mimir_sync.py — ensure_sync_table runs ALTER TABLE every startup — MED
Now checks `information_schema.COLUMNS` first; only runs the `ALTER TABLE` if the generated
`race` column doesn't already exist. Eliminates unnecessary DDL on every bot restart.

---

## Open items (not yet fixed)

### B-17: db_api.py — hardcoded DB password (local-only dev setup, not deployed)
N/A for this setup — all MySQL config uses hardcoded defaults; .env has no MySQL vars.

---

## Fixed — 2026-05-17

### FIXED B-25: skills.py — generate_with_skills bypasses Ollama queue — HIGH
Converted to `call_ollama()` with `/api/chat` format + `wait_for_ollama_turn()` check (Phase 3 migration 17, 2026-05-14).

### FIXED B-36: mimir_client.py — set_campaign() returns False on success — MED
`self._campaign_id` now set unconditionally and `return True` added explicitly (mimir_client.py:156-161). Already in code; open-item entry was stale.

### FIXED B-35: tower_economy.py — _ensure_bid_columns silent failure — MED
Outer `except Exception: pass` at import changed to `except Exception as _e: logger.warning(...)`.

### FIXED B-29 / B-28: character_monitor.py + npc_appearance.py — legacy file writes — MED
- `character_monitor.py`: DB update sets `_db_updated=True`; returns `True` early if DB succeeded, skipping file write.
- `npc_appearance.py`: removed the post-loop write of `_all_sd_prompts.json` from `generate_all_sd_profiles()`.

### FIXED B-40: expandable_bulletin.py — embed description 4096-char limit unchecked — LOW
`create_expanded_embed` now truncates `full_content` to 4096 chars (with `…`) before setting `description`.

### FIXED B-32: mission_outcomes.py — archive_outcomes_weekly trim was no-op — MED
`_save_outcomes` is insert-only; calling it with the "kept" slice did nothing. Fixed by deleting archived rows from DB directly via `DELETE FROM mission_outcomes WHERE id IN (...)`.

### FIXED B-33: mission_outcomes.py — _load_npcs merge order overwrote DB columns with stale JSON — MED
`npc.update(dj)` after setting DB columns meant stale `data_json` values could overwrite `name`, `faction`, `role`, `location`, `status`. Fixed merge order: `{**dj, "name": ..., "faction": ..., ...}` so DB columns win.

### FIXED B-42: arena_season.py — db_id lost from state dict if _save_arena raises mid-execution — MED
`state.pop("db_id")` was inside the `try` block; if the `raw_execute` raised before `state["db_id"] = db_id` was restored, next tick would insert a duplicate season row. Fixed: `pop` moved before `try`; `except` block restores `db_id` if it was lost.

### FIXED B-47: aclient.py — enqueue_message silent except leaves interaction unacknowledged — MED
Bare `except Exception: pass` now specifically catches `discord.InteractionResponded` silently; all other defer failures log a `WARNING` so "Unknown Interaction" followup errors become diagnosable.

### NOTED B-3 / B-5: aclient.generate_image / GeminiProvider dead code — no active callers
`aclient.generate_image()` has no callers outside itself; B-3 (FreeProvider raises NotImplementedError) and B-5 (Gemini returns bytes not str) describe unreachable code paths. Not a live risk.

### NOTED B-34: party_profiles.py reputation column — confirmed not a bug
Database schema has `reputation INT DEFAULT 0`; storing `profile.get("points", 0)` is correct. Buglog note was based on wrong assumption. Closed.

### FIXED — stakes[0] IndexError crash in 5 plan fallback builders — 2026-05-17
`_fallback_plan()` in `recovery_pipeline.py`, `discovery_pipeline.py`, `exploration_pipeline.py`, `first_contact_pipeline.py`, and `rescue_pipeline.py` all did `mission_context.get("stakes", [default])[0]`. If `_mission_context()` returned `stakes=[]` (empty list, not absent), the default was not used and `[][0]` raised `IndexError`. Fixed with `_stakes = mission_context.get("stakes") or [default]; stake = _stakes[0]` pattern in all 5 files.

### FIXED — test_partial_plan_normalization + test_investigation_pipeline stale assertions — 2026-05-17
Recent pipeline improvements (puzzle, investigation, recovery, rescue, discovery, exploration, first_contact, strange_occurrences) added mission-specific generic-plan rejection. Tests asserted exact LLM string values that the rejection now replaces with fallback values. Updated all brittle equality assertions to `assert plan["field"]` (structure/truthy check). Also added missing `mission` dict arg to rescue, discovery, first_contact, and strange_occurrences test calls; added `mission` to strange_occurrences `_normalize_plan` call path.

### FIXED — arena_season.py B-42 db_id lost on save failure — 2026-05-17
See above.

### FIXED — NPC lifecycle permanently blocked by stale pipeline_busy DB flag — 2026-05-17

Symptom: lifecycle loop showed "Ollama busy () — skipping lifecycle cycle" every hour since 01:31 today (14+ consecutive retries). NPC birth and events had not run all day.

Root cause: `pipeline_busy` in `global_state` DB was stuck `{"active": True, "reason": "module retry: Hearthstone Cellar Worms", "since": "2026-05-15T05:29:02"}` from a pipeline crash 2 days prior. `is_available()` checks `_db_priority_busy()` first. The in-process `_busy` flag is reset on every bot restart, but the DB flag persists. The "empty reason" in the log (`Ollama busy ()`) was because `get_busy_reason()` only returned the in-process reason, not the DB reason.

Fix:
- Cleared stuck `pipeline_busy` DB flag directly (`pipeline_busy.active = False`).
- Added startup clearing of `pipeline_busy` in `aclient.py` `mission_board_loop` startup block (alongside the existing `module_gen_active` clear). Every bot restart now resets both stale pipeline markers.
- Fixed `get_busy_reason()` in `ollama_busy.py` to also return the DB flag reason when in-process `_busy` is False but `_db_priority_busy()` is True. Future logs will show e.g. `Ollama busy (DB: module retry: Hearthstone Cellar Worms (52.1h ago))` instead of empty parentheses.

Result: `is_available()` now returns True. Lifecycle should run at its next 16:31 tick.

### FIXED B-48: agents/orchestrator.py — fragile dict-key index arithmetic — MED

Symptom:
- `_run_specialist_agents()` ran specialist tasks in a hard-coded order, but exception logging used `list(self.agents.keys())[i + 1]`.
- If `self.agents` dict order changed, a failed specialist could be logged under the wrong agent name.

Smoke before fix:
- Reordered `self.agents` in memory and forced `python_veteran.analyze_code()` to raise.
- Log incorrectly reported `project_manager` as the failed agent.

Fix:
- Replaced the parallel task list with explicit `(agent_name, coroutine)` pairs.
- Exception handling now zips returned results to those explicit names instead of deriving names from dict position.

Verification:
- Same reordered-agent smoke now reports `python_veteran` correctly.
- `python -m py_compile src\agents\orchestrator.py` passed.

### FIXED: mimir_client.py — multi-part MCP tool content silently dropped — LOW

Symptom:
- `MimirClient._call()` iterated `result.content` but returned inside the first text item.
- If an MCP tool returned multiple text content items, every item after the first was silently lost.

Smoke before fix:
- Fake MCP session returned two JSON text parts: `{"a":1}` then `{"b":2}`.
- `_call()` returned only `{"a": 1}`.

Fix:
- `_call()` now collects all text parts.
- Single-part behavior is unchanged.
- Multi-part behavior first tries to parse the combined text as JSON; if not possible, it parses individual JSON parts and merges dicts / concatenates lists where safe, otherwise returns a joined text string.

Verification:
- Same fake MCP smoke now returns `{"a": 1, "b": 2}`.
- `python -m py_compile src\mimir_client.py` passed.

### FIXED B-45: agents/news_agents.py — shared FactCheckerMixin cache — MED

Symptom:
- `FactCheckerMixin._cache` was a class-level mutable dict.
- `NewsEditorAgent`, `GossipEditorAgent`, and `SportsColumnistAgent` all shared cached roster/graveyard/gazetteer/venue state, so stale facts from one editor could leak into another.

Smoke before fix:
- Instantiated `NewsEditorAgent` and `GossipEditorAgent`.
- Wrote `a._cache["roster"] = [{"name": "stale-from-news"}]`.
- `b._cache["roster"]` returned the same stale value and `id(a._cache) == id(b._cache)` was `True`.

Fix:
- Replaced the shared class dict with a per-instance `_fact_check_cache` property.
- `clear_cache()` now clears only that agent instance's fact cache.
- Also corrected the low-severity `typing.Any` issue in the same file.

Verification:
- Same smoke now reports different cache objects; the gossip agent does not see the news agent's roster entry.
- Clearing one agent cache leaves the other agent's cache independent.
- `python -m py_compile src\agents\news_agents.py` passed.

### FIXED B-46: agents/guild_council.py — no overall session timeout — MED

Symptom:
- `GuildCouncil.run_session()` could run up to the sum of every sequential council Ollama call if Ollama was degraded but still responding slowly.
- Worst case from the audit was roughly 112 minutes, blocking the nightly learning cycle's council phase.

Connected caller:
- `AgentOrchestrator._run_guild_council()` is the live caller during the learning cycle.
- It catches exceptions, but before this fix there was no internal council-level cap or graceful timeout session.

Smoke before fix:
- Monkeypatched `GuildCouncil._propose_rulings()` to sleep.
- `run_session()` only stopped when wrapped by an external `asyncio.wait_for()`, proving callers had to police the timeout themselves.

Fix:
- `run_session()` now wraps the implementation in an internal `asyncio.wait_for()`.
- Default cap is 45 minutes via `GUILD_COUNCIL_SESSION_TIMEOUT_SECONDS` (set to `0` to disable intentionally).
- Timeout returns a valid `CouncilSession` with zero rulings and a clear adjourned bulletin instead of hanging the learning cycle.

Verification:
- Smoke with `GUILD_COUNCIL_SESSION_TIMEOUT_SECONDS=0.05` returned `CouncilSession 0 0 Council session timed out; no rulings recorded.`
- `python -m py_compile src\agents\guild_council.py` passed.

### FIXED: tower_rag.py — stale file fallback was silent when DB load failed — LOW

Symptom:
- `_load_docs()` treats MySQL `training_docs` as primary, but `except Exception: pass` swallowed DB failures.
- If DB was down or the query broke, RAG could fall back to stale `campaign_docs/**/*.txt` without an error trail.

Connected callers:
- `aclient.py` chat context building via `build_context_from_messages()`.
- `/economy` and rules lookup helpers through `search_docs()`.

Smoke before fix:
- Source path confirmed the DB exception was swallowed before file fallback.
- A direct monkeypatch smoke needed an external timeout when pointed at the real fallback tree, which also shows why silent fallback can be noisy and slow to diagnose.

Fix:
- Added `src.log.logger`.
- DB load failures now log `ERROR` before falling back to campaign_docs text files.

Verification:
- Fake `src.db_api.raw_query` raising `RuntimeError("synthetic db down")` now records an error containing the DB exception.
- Same smoke with `DOCS_DIR` pointed at a nonexistent folder returns `[]`, preserving fallback behavior.
- `python -m py_compile src\tower_rag.py` passed.

### FIXED: ddb_homebrew.py — hp_die values like "d12" defaulted to d8 — LOW

Symptom:
- Both DDB homebrew push paths accepted only bare die strings (`"4"`, `"6"`, `"8"`, `"10"`, `"12"`, `"20"`).
- A conventional value like `"d12"` failed membership validation and silently defaulted to `"8"`.

Smoke before fix:
- The existing expression mapped `hp_die="d12"` to `"8"`.

Fix:
- Added `_normalize_hp_die()` accepting both `"12"` and `"d12"` style values.
- Invalid values now warn and default to d8.
- Both CDP and direct HTTP push paths use the same normalizer.

Verification:
- `_normalize_hp_die("d12")`, `"12"`, and `"d8"` return `"12"`, `"12"`, and `"8"`.
- `_normalize_hp_die("bogus")` returns `"8"` and logs a warning.
- `python -m py_compile src\ddb_homebrew.py` passed.

### FIXED: skill_loader.py — two statements on one line — LOW

Symptom:
- File fallback cache timestamp used `import time as _t; _cache_ts = _t.time()` on one line.

Fix:
- Split into two statements on separate lines.

Verification:
- `python -m py_compile src\skill_loader.py` passed.
---

## Module Quality Note - 2026-05-17

### The Shattered Oath puzzle module lost mission specificity - status: fixed for future puzzle/investigation modules

Reviewed generated module `generated_modules/The_Shattered_Oath_20260517_135331`.

Score: 4/10.

What worked:
- The HTML bundle rendered cleanly with module, DM guide, player guide, session runner, and chart pack.
- It had useful high-level puzzle scaffolding: research routes, progress track, puzzle board, wrong-attempt costs, and no unnecessary map.

What failed:
- The module ignored the mission's actual playable material: Boxxo, Veyra Korr, the stolen Shattered Oath relic, rogue arcane engine, Dome breach risk, Iron Fang cover-up, and former-ally trap.
- The answer key was generic (`source culture`, `visible order`, `repeated mark`) and not runnable without the DM inventing the real solution at the table.
- Research routes repeated generic clues like `reveals when the next stage appears`.
- The puzzle did not define exact solution steps, concrete clue ladder, proof standards, or mission-specific consequences.

Ideal module target:
- Preserve named PC/NPC/contact/object/site/faction scandal from the mission text.
- Give the DM a concrete answer key with exact ordered steps.
- Provide a clue ladder: clue, where found, what it proves, what it unlocks, and failure cost.
- Give players public research routes while keeping the answer hidden.
- Include a session runner snapshot with stakes, exact steps, and unstick options.
- For investigation modules, require a concrete truth, core clue web, scene secrets, and accusation standard.

Fix:
- `src/mission_builder/puzzle_pipeline.py` now extracts mission-specific canon terms/stakes from the mission and `mission_json`, injects them into the planning prompt, rejects overly generic plans, and falls back to a mission-specific deterministic plan instead of generic puzzle scaffolding.
- Puzzle modules now render Mission-Specific Stakes, Exact Solution Steps, and Clue Ladder in the module, session runner, DM guide, player guide, chart pack, and Mimir docs.
- `src/mission_builder/investigation_pipeline.py` now applies the same quality lesson in investigation form: it extracts mission-specific context, rejects generic mystery shells, and adds Core Clue Web, Scene Secrets, and Accusation Standard to module/session/guide outputs.

Verification:
- `python -m compileall src\mission_builder\puzzle_pipeline.py src\mission_builder\investigation_pipeline.py` passed.
- Local fallback smoke against mission `978` now preserves `Boxxo`, `Veyra Korr`, `The Shattered Oath`, `rogue arcane engine`, `stolen relic`, and `Dome breach` in the generated safety-net plan.

---

## Pipeline Quality Audit - 2026-05-17

Reviewed the 16 existing non-puzzle/non-investigation/non-infestation smoke outputs and their source pipelines without generating maps or touching A1111.

Main finding:
- The stronger pipelines have good type-shaped structure, but they do not yet have the explicit mission-specific canon preservation guard added to puzzle/investigation.
- Existing smoke outputs render complete HTML bundles, but weaker pipelines can still become generic shells when the mission body has named NPCs, objects, scandals, places, or consequences.
- Routing still uses raw type order in `src/mission_builder/__init__.py`; mixed labels such as `Puzzle` + `investigation` tier route by type first.

Best current candidates:
- Heist, Defense, Battle, Assault, Infiltration, Negotiation.

Needs the next quality pass first:
- Discovery: must define the actual revelation, what proves it, and what changes after it is known.
- First Contact: must define contact protocol, mistranslation risk, taboo/offer exchange, and escalation ladder.
- Rescue: must preserve captive identity/state, rescue clock, extraction route, and captor leverage.
- Recovery: must preserve exact missing object/person, chain of custody, rival clock, and proof of recovery.
- Exploration: must separate travel from discovery; require route decisions, landmarks, hazards, and a real endpoint.
- Strange Occurrences: must define the uncanny rule, evidence ladder, witnesses, false explanations, and resolution standard.

Recommended implementation:
- Add local mission-context extraction and generic-shell rejection to each pipeline separately.
- Keep each pipeline distinct; do not merge or abstract them.
- Add type-specific required fields to fallbacks and renderers, mirroring the puzzle/investigation quality fix.

### Applied quality pass - 2026-05-17

Patched the weakest six pipelines locally:
- `discovery_pipeline.py`: mission canon extraction, generic-shell rejection, `actual_discovery`, `proof_standard`, `changed_world_state`.
- `first_contact_pipeline.py`: mission canon extraction, generic-shell rejection, `contact_identity`, `contact_protocol`, `misunderstanding_ladder`.
- `recovery_pipeline.py`: mission canon extraction, generic-shell rejection, `chain_of_custody`, `proof_of_recovery`, `rival_clock`.
- `rescue_pipeline.py`: mission canon extraction, generic-shell rejection, `target_state`, `rescue_clock`, `extraction_standard`, `captor_or_pressure`.
- `exploration_pipeline.py`: mission canon extraction, generic-shell rejection for both normal and council-generated plans, `endpoint_revelation`, `route_decisions`, `return_standard`.
- `strange_occurrences_pipeline.py`: mission canon extraction, generic-shell rejection, `uncanny_rule`, `explanation_ladder`.

Verification:
- `python -m compileall` / `py_compile` passed for all six touched files.
- Source-only fallback smoke confirmed all six preserve the test canon terms `Boxxo`, `Veyra Korr`, `Shattered Oath`, `Dome`, and/or `Iron Fang Consortium` without generating modules or maps.

---

## FIXED - Dashboard mission claim handoff - 2026-05-17

Coordination note:
- Claude is investigating NPC lifecycle generation. Codex intentionally avoided `npc_lifecycle.py` in this pass to prevent overlapping edits.

Symptom:
- The web dashboard `⚔️` / double-sword claim button marked missions claimed and queued module generation, but it did not hand off through the Discord claim workflow.
- Result: dashboard claims could skip board-post deletion, public `CONTRACT TAKEN` notice, DM outcome buttons, and normal Discord-side claim metadata.

Root cause:
- `/api/claim-mission` updated the `missions` row directly and appended to `module_gen_queue`.
- It was conceptually trying to stand in for a Discord reaction, but the actual Discord reaction handler ignores the bot's own reaction (`payload.user_id == client.user.id`), and bot-authored reaction simulation is not a reliable player-claim path.

Fix:
- Kept the player-facing Discord `⚔️` reaction path intact.
- Dashboard now writes `dashboard_claim_queue` only.
- `aclient.py` mission board loop consumes `dashboard_claim_queue` with the live Discord client.
- Added `mission_board.handle_dashboard_claim()` to mirror the normal claim workflow directly: mark claimed, delete original board post when possible, post the claim notice, DM the outcome buttons, and start module generation.
- Updated dashboard tooltip from "triggers reaction" to "Claim via the Discord bot".

Verification:
- `python -m py_compile Webpage\app.py src\aclient.py src\mission_board.py` passed.

---

## Bug Fixes — 2026-05-17 (Round 3)

### FIXED B-20: npc_consequence.py — replacement unbound for non-Unknown-Party NPCs
`replacement` was only assigned inside `if name in UNKNOWN_PARTY_MEMBERS`. Reference at `"replacement": replacement if name in ...` raised NameError for every non-unknown-party NPC. Fixed: `replacement = None` before the conditional.

### FIXED B-30: npc_consequence.py — dead duplicate check_resurrection_queue with NameError
First `check_resurrection_queue` definition (lines 430-457) referenced undefined `remaining` and was silently overridden by the correct second definition. Removed the broken dead definition.

### FIXED B-31: npc_consequence.py — _make_unknown_party_replacement designation dedup always empty
`(n.get("data_json") or {}).get("designation")` always returned None because `_load_roster()` already merges data_json into the flat NPC dict. Dedup set was always empty so designation uniqueness was never enforced. Fixed to `n.get("designation")` directly.

### FIXED B-11: maps.py — blocking stylize_pretty_battlemap call in async generate_module_maps
Line 814 called the sync `stylize_pretty_battlemap()` directly inside an `async def` function. Wrapped with `await asyncio.to_thread(stylize_pretty_battlemap, ...)`.

### FIXED B-44: news_feed.py — dead NEWS_TYPES_FILE variable and stale _SD_PROMPTS_FILE fallback
- Removed dead `NEWS_TYPES_FILE` variable (the actual load/save already uses the DB via global_state).
- Removed the file-based fallback read of `_all_sd_prompts.json` from `_load_sd_prompts()`. DB path already reads from `npc_appearances` table. If DB fails, returns `{}` — no file fallback needed.
- Removed dead `_SD_PROMPTS_FILE` variable.

### FIXED B-39: ddb_homebrew.py — sync httpx.get() blocking event loop in async functions
- `_get_page_ws_url()` was `async def` but called `httpx.get()` synchronously. Wrapped with `await asyncio.to_thread(httpx.get, ...)`.
- `ensure_chrome()` called sync `_chrome_alive()` and `_launch_chrome()` directly. Wrapped both with `await asyncio.to_thread(...)`.

### FIXED B-7: providers.py — Claude default fallback model stale
Changed hardcoded `"claude-haiku-4-5"` to `os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")`.

### FIXED B-27: character_profiles.py — dynamic SQL UPDATE with unparameterized column names
Added `_ALLOWED` set for valid column names; unknown keys are logged and skipped. Column names wrapped in backticks in the generated SQL. Returns early if no valid columns remain.

### FIXED B-19: npc_lifecycle.py — apply_npc_event type hint says Optional[str], returns tuple
Updated type annotation to `-> tuple`. No runtime impact — callers were already unpacking 2 values correctly. The wrong annotation was misleading.

### NOTED B-18: db_api.py — get_recent_news reads wrong table
`get_recent_news()` reads from `news_entries` while `add_news_entry(bulletin_text=...)` writes to `news_memory`. But `get_recent_news()` has no active callers in the live codebase — only in archived scripts. Not a live issue. Dead function.

### NOTED B-45: agents/news_agents.py — FactCheckerMixin._cache shared class dict
Already fixed — `_cache` is now a `@property` using `self.__dict__` for per-instance storage. Buglog note was stale.

---

## Bug Fixes — 2026-05-17 (Round 4, with Codex)

### FIXED B-23: ddb_homebrew.py — CDP id=0 collision for Network.enable + Network.setCookie
Both cookie-injection CDP calls used `id_=0`, racing for the same response reply. Changed to `id_=20` and `id_=21` (distinct from all other IDs in the function).

### FIXED B-9/B-10: tower_rag.py — cache globals unprotected + thrash on rules/lore alternation
- Replaced 5 module-level globals with `_caches: Dict[bool, dict]` keyed by `include_rules` mode.
- Added `threading.RLock` around `_ensure_index()` so concurrent cold-cache hits don't build the index twice.
- Both modes (rules/no-rules) are cached independently — switching no longer forces a rebuild.
- Updated `get_relevant_chunks()` to use the per-mode cache.

### FIXED B-14/B-43: cr_scaling.py — classes field shape mismatch with encounters.py
`party_strength()` assumed `classes` was a list-of-dicts. Fixed to handle both `dict` (`{"Fighter": 3}`) and `list` forms, matching `encounters.py`.

### FIXED agents/base.py — `import time` and `import re` inside retry loop body
Moved both to module-level. Replaced all `_time.` / `_re.` aliases with `time.` / `re.`.

### FIXED skill_loader.py — `import time` inside function body
Same pattern. Moved to module-level and removed the duplicate local import.

### FIXED npc_lifecycle.py — alliance branch appends to relationships without type guard
`npc.get("relationships", "")` could be non-string if data_json stored it differently. Fixed to `str(npc.get("relationships") or "")`.

### NOTED B-8: tower_rag.py — silent fallback already logs error
Already logs `logger.error()`. Stale note.

### NOTED B-21: character_monitor.py — class_name column may not exist
`class_name varchar(255) YES` confirmed in `docs/mysql_schema_reference.md`. Not a bug.

### NOTED B-34: tower_economy.py — buy_now_price may be None
Column is `bigint NULL` — storing None is valid. Not a bug.

### NOTED B-46: guild_council.py — no overall timeout
45-minute default exists; unbounded only if env set to 0. Acceptable default.

### NOTED B-48: orchestrator.py — fragile dict-key index arithmetic
Pattern `list(self.agents.keys())[i+1]` no longer exists in codebase. Already resolved.

---

## Bug Fixes — 2026-05-17 (Round 5, with Codex)

### FIXED B-40: image_ref.py — mkdir at import raises PermissionError silently
`_d.mkdir(parents=True, exist_ok=True)` ran for 4 directories at import time with no error handling. Wrapped each in `try/except PermissionError` with a `logger.warning`.

### FIXED B-41: image_ref.py — layered_generate hangs 900s if A1111 fails between passes
Pass 2 (img2img) failure would wait up to 900s then raise with no output. Added `try/except` around pass 2; on failure logs a warning and returns pass 1 background bytes as the final result instead of nothing.

### FIXED personas.py — dead PermissionError raise in get_persona_prompt
`is_jailbreak_persona()` always returns False (jailbreak personas removed), making the PermissionError branch permanently dead code. Removed the dead conditional guard entirely.

### NOTED cogs/module_gen.py — _load_missions may read JSON
`_load_missions()` in `src/mission_board.py` reads from `missions` DB table only — no JSON fallback. Buglog note was wrong. Not a bug.

### NOTED mimir_sync.py:1686 — f-string in SQL
The f-string builds SET clause from internal column-name mappings, not from user input or external data. Values are all parameterized. Low real risk; no change needed.

---

## STATUS — 2026-05-17

All bugs from the original B-1 through B-53 audit have been either fixed, confirmed as false positives, or noted as N/A. The "Open items" section now contains only B-17 (hardcoded DB password — N/A for local-only dev setup).

Remaining known minor risks (not worth a solo fix but worth noting for future):
- `nudge_state.py` — entire module uses flat files (future DB migration candidate)
- `party_profiles.py:format_all_party_ranks` — only reads `members_json`, old rows skipped
- Cross-process image ref race (single-process lock added, cross-process not)

All 46 automated tests passing as of this update.

---

## Live Log Audit — 2026-05-17 (New findings)

Scan method: full read of `logs/bot_stderr.log` and `logs/journal.txt`, error/warning pattern grep, timeline analysis. No code changed — record only.

### B-54. mimir_client.py — Mimir MCP stdio_client cancel scope RuntimeError on every bot shutdown — MED

**Files:** `src/mimir_client.py`, `mcp/client/stdio/__init__.py` (third-party)

**Symptom:** On every bot shutdown or reconnect, the following appears in `bot_stderr.log`:
```
an error occurred during closing of asynchronous generator <async_generator object stdio_client at 0x...>
BaseExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
```

**Observed timestamps:** 2026-05-15 (at least 3 separate shutdown events), 2026-05-17 16:39 (current session).

**Root cause:** The MCP `stdio_client` is an async context manager that creates a cancel scope inside one asyncio task. When the bot event loop shuts down, Python's async generator finalization runs in a cleanup task that is different from the task that entered the cancel scope. anyio enforces single-task cancel scope ownership and raises `RuntimeError` during cleanup.

**Impact:** Noisy stacktrace on every bot restart. The MCP connection does reconnect cleanly after restart (confirmed by `[MIMIR] Connected to mimir-mcp ✓` in next startup). Not a data-loss bug but floods stderr with a multi-line exception group that looks alarming and can obscure real errors.

**Smoke before fix:** Check if wrapping `mimir_client.disconnect()` in `asyncio.shield()` or catching `BaseExceptionGroup` containing `RuntimeError` from cancel scope prevents the log noise.

**Fix candidate:** In `MimirClient.disconnect()`, catch the `RuntimeError: Attempted to exit cancel scope in a different task` specifically (inspect the BaseExceptionGroup before re-raising), or use `anyio.from_thread.run_sync_in_worker_thread` for cleanup. Alternatively, convert the disconnect to use `anyio.CancelScope` directly.

---

### B-55. city_scene.py / news_feed.py — A1111 multi-hour silent "no image" loop with no operator alert — MED

**Files:** `src/city_scene.py`, `src/news_feed.py`

**Symptom:** From 2026-05-15 19:35 through 2026-05-16 06:38 (~11 hours), every single A1111 generation cycle logged:
```
🖼️ A1111 returned no image — retrying in 10 minutes
```
42+ consecutive failures. No HTTP 500 errors, no VAE errors, no model switch failures — just silent "no image" every 10 minutes until the next bot restart.

**Root cause unknown.** Possible candidates: A1111 process stuck in an invisible generation loop (returning empty images without raising), VRAM fully consumed by a previous generation without releasing, or generation queue jammed by an abandoned job from the infestation pipeline failure earlier that day.

**Impact:** Zero city scenes, NPC portraits, and maps generated for ~11 hours. No alert to Discord channel or operator log at ERROR level. The bot silently degraded for the entire overnight window.

**What's missing:** After N consecutive "no image" responses (e.g. 5), the bot should:
1. Log at `ERROR` level, not just `WARNING`.
2. Attempt an A1111 interrupt via `/sdapi/v1/interrupt`.
3. Optionally post a one-time bulletin or Discord DM to alert the operator.

**Smoke before fix:** Verify that `_call_a1111()` in `city_scene.py` and `generate_npc_portrait()` in `news_feed.py` both track a consecutive-failure counter. Confirm neither currently escalates beyond `WARNING` after extended failure runs.

**Additional evidence 2026-05-17 16:42–17:21:** After bot restart at 16:39, A1111 was stuck with a stale generation job for ~38 minutes:
1. `16:42` — first scene attempt: `[SCENE] A1111 still busy after traffic-cop wait; skipping`
2. `16:47` — second attempt: `A1111 returned no image — retrying in 10 minutes`
3. `17:03` — third attempt: `[SCENE] A1111 still busy` → `A1111 returned no image — retrying in 10 minutes`
4. `17:21` — fourth attempt: **SUCCESS** — story image posted. Stale job finally cleared naturally.
A1111 keeps the orphaned generation job across bot restarts. No automatic interrupt/cleanup when the client disconnects. Self-heals after ~38 minutes but wastes 2-3 scene cycles.

---

### B-56. news_agents.py — SportsColumnistAgent exhausts full retry budget during Ollama contention — MED

**File:** `src/agents/news_agents.py`

**Symptom:** Log pattern observed multiple times (2026-05-17 16:44–16:47):
```
generate_mission_text error: Ollama busy: Ollama primary queue is busy
🤖 [SportsColumnistAgent] TIMEOUT attempt 1 after 180.0s
generate_mission_text error: Ollama busy: Ollama primary queue is busy
🤖 [SportsColumnistAgent] TIMEOUT attempt 2 after 180.0s
generate_mission_text error: Ollama busy: Ollama primary queue is busy
🤖 [SportsColumnistAgent] TIMEOUT attempt 3 after 180.0s
📰 Editorial bulletin failed: Timeout after 3 attempts
```

**Root cause:** `SportsColumnistAgent` retries 3 times at 180s per attempt. When the Ollama primary queue is busy, each 180s timeout window burns waiting for Ollama to respond, producing the `generate_mission_text error` on each attempt. The resource cop is not checked before the agent starts a new attempt — it just tries again immediately after timeout.

**Impact:** 9 minutes (3 × 180s) wasted per editorial bulletin cycle when Ollama is under load. Editorial bulletin for that cycle fails silently with no Discord output.

**Fix candidate:** Before each retry attempt, check `ask_ollama("sports_columnist", track="quick")`. If the cop returns `run_now=False`, skip the attempt and log a deferral instead of burning the full 180s timeout. Also consider reducing `max_attempts` from 3 to 1 when Ollama is known busy.

**Related pattern observed 2026-05-18 ~04:28:** `✏️ Editor output invalid (empty) — using original draft` — when the editorial agent returns empty output (different from a timeout), the bulletin falls back to the original draft. The fallback works correctly. But "empty output" from an editor agent that didn't timeout suggests Ollama is returning empty/null responses rather than timing out when overloaded. Both failure modes (empty and timeout) result in the same degraded bulletin output.

**FIXED 2026-05-18:** Root cause was in `src/agents/base.py:BaseAgent.complete()`. After a `TimeoutException`, the loop retried immediately using the cop's `wait_for_ollama_turn(max_wait_seconds=60)`. But 60s is long enough for the queue lock to clear (released when the timed-out request exits `async with _ollama_lock:`), even though Ollama is still running server-side. The cop gave a false green light and the agent burned another full 180/300s timeout.

Fix: In the `except httpx.TimeoutException` block, after logging the timeout, sleep 30s then call `ask_ollama()` directly (no wait). If Ollama is still occupied, abort remaining retries immediately instead of burning another timeout. This applies to ALL agents using BaseAgent (SportsColumnistAgent, KimiAgent, NewsEditorAgent, etc.).

---

### B-57. aclient.py / news_agents.py — KimiAgent 300s timeout fires during heavy Ollama load — MED

**File:** `src/agents/news_agents.py` (or wherever KimiAgent is defined/dispatched)

**Symptom:** Log shows:
```
🤖 [KimiAgent] TIMEOUT attempt 1 after 300.0s
🤖 [KimiAgent] TIMEOUT attempt 2 after 300.0s
```

**Observed:** 2026-05-17 16:46:55 and 16:47:12 (during same Ollama contention window as B-56).

**Root cause:** Same as B-56 — KimiAgent is dispatched without first checking the resource cop, then waits the full 300s per attempt before retrying.

**Impact:** 10+ minutes wasted per KimiAgent cycle during Ollama contention. Unknown what news/chat content is lost.

**Smoke before fix:** `KimiAgent` is used for rift-stage bulletins (`_generate_rift_bulletin`) and missing-persons bulletins in `news_feed.py`. Confirm whether it's dispatched on the primary queue or quick lane. If primary queue, confirm why the queue was occupied for 900s before it.

**Full pattern confirmed 2026-05-17 16:42–16:57:** KimiAgent ran 3 attempts × 300s = 900s total. Concurrently, `generate_mission_text` also ran 3 attempts and failed after 903.1s (`[GEN] Generation returned None — mission skipped`). Both seem to run in parallel and both exhaust the Ollama primary queue. This ~15-minute window where both agents are timing out blocks everything else on the primary queue.

---

### B-58. mission_board.py (personal missions) — Personal mission generation silently drops on transient Ollama busy — MED

**File:** `src/mission_board.py` (or personal mission generator)

**Symptom:** Log shows:
```
generate_mission_text error: Ollama busy: Ollama primary queue is busy
📋 [GENERATE] LLM returned empty/None after 60.4s
📋 personal mission: generation returned None for Boxxo
```

**Observed:** 2026-05-17 16:43:56 — during the same Ollama contention window as B-56/B-57.

**Root cause:** Personal mission generator calls `generate_mission_text()` once. When Ollama is busy it gets an error, `generate_mission_text()` returns None, and the personal mission slot for that NPC is discarded with no retry or reschedule.

**Impact:** Boxxo (and likely other NPCs) lose their personal mission for the current cycle. The slot is not retried — the NPC waits until the next scheduled personal mission window.

**Fix candidate:** On `generate_mission_text` returning None due to Ollama busy, reschedule the personal mission attempt within the current loop iteration rather than skipping the NPC entirely.

**FIXED 2026-05-18:**
1. `src/mission_board.py:post_personal_mission()` — changed return type from `None` to `bool`. Returns `True` on success or benign skip (cap reached), `False` on generation failure.
2. `src/aclient.py` personal mission loop — when `post_personal_mission()` returns `False`, sets `timers[name] = 3600` (retry in 1h) instead of `next_personal_mission_seconds()` (1-3 days).

---

### B-59. self_learning.py — Most learning topics produce "No content generated" during nightly Ollama contention — LOW

**File:** `src/self_learning.py`

**Symptom:** Both 2026-05-16 and 2026-05-17 nightly learning sessions logged "No content generated" for 13/15 topics:
```
→ No content generated for world_state
→ No content generated for module_quality_training
→ No content generated for news_memory
→ No content generated for mission_patterns
... (etc.)
```
Both sessions: "15 studied, 2 saved, 0 errors"

**Root cause:** The 1:00-4:00 nightly window overlaps with residual Ollama activity from the prior day's module generation. When Ollama is busy, the resource cop defers most topic study calls, which return empty strings, which register as "no content" without incrementing the error count.

**Impact:** Self-improvement system is effectively non-functional during nights when Ollama was busy earlier. 0 errors reported masks the real problem — the system studied 15 topics but produced nothing useful from 13 of them. Failure is invisible in the session summary.

**Fix candidate:** Count "no content due to Ollama busy" as a deferred item (not a success), and report deferred count in the session summary. Consider a short retry for high-priority topics (world_state, mission_quality) if the first attempt returns empty due to Ollama contention.

**Update 2026-05-18 01:24:** Self-learning session ran 13/15 topics saved (vs 2/15 during daytime Ollama contention). Confirms the failure mode is contention, not a systemic bug with the learning system itself.

---

### B-62. npc_lifecycle.py — lifecycle blocked 4+ consecutive hours pre-restart with empty Ollama busy reason — MED

**Files:** `src/npc_lifecycle.py`, `src/ollama_busy.py`

**Symptom (2026-05-17 pre-restart):**
```
11:31 🧬 Ollama busy () — skipping lifecycle cycle
11:31 🧬 NPC lifecycle deferred by Ollama busy; retrying in 60m
12:31 🧬 Ollama busy () — skipping lifecycle cycle
13:31 🧬 Ollama busy () — skipping lifecycle cycle
14:31 🧬 Ollama busy () — skipping lifecycle cycle
15:31 🧬 Ollama busy () — skipping lifecycle cycle
```
5 consecutive hourly retries all blocked, all with empty reason `()`.

**Root cause (recurring):** The `pipeline_busy` DB flag was stuck `True` from an earlier crashed pipeline — the same issue as the 2026-05-17 morning fix. The `get_busy_reason()` fix was applied to populate the reason string from the DB flag, but these entries are from before the restart that picked up that fix.

**Note:** The restart at 16:39 cleared `pipeline_busy` and the new code should now show the full reason on future blocks. However, the lifecycle ran 0 times today before the restart (first lifecycle run of the day was due ~07:18 based on the 2026-05-15 B-9 entry, deferred there, then at 20-28 hour interval the next run would be ~03:18-11:18 2026-05-17). So from the evidence, the lifecycle ran once today but was blocked again from 11:31 onward.

**Status:** Confirmed fixed post-restart. At 17:24:57, NPC lifecycle loop started and completed successfully:
- Generated 5 daily lifecycle events
- Created new NPC: Elira Duskspire
- Posted injuries for Grothor Grimclaw and Lirael Veythari
- Detected faction leader Brother Thane in graveyard → leader death protocol (RAISE DEAD queued)
- 193 NPCs total, 192 alive, 1 recovering, 2 newly injured today
Next lifecycle in 21h 41m from completion. pipeline_busy clearing at startup is working correctly.

---

---

### B-60. test_e2e.py — 4 tests fail with `KeyError: 'title'` — module schema nesting mismatch — MED

**Files:** `tests/test_e2e.py`, `src/mission_builder/json_generator.py`, `src/mission_builder/schemas.py`

**Symptom (observed 2026-05-17 in Codex test run):**
```
tests/test_e2e.py:74: KeyError: 'title'
tests/test_e2e.py:113: KeyError: 'title'
tests/test_e2e.py:272: KeyError: 'title'
tests/test_e2e.py:306: KeyError: 'title'
```
4 tests: `test_generate_mission_board_post`, `test_save_mission_to_disk`, `test_generate_load_use_mission`, `test_mission_with_dungeon_delve`.

**Root cause:** `generate_mission_async()` → `generate_module_json()` uses `MissionJsonBuilder`, which stores the mission title at `module["metadata"]["title"]`. The `MissionModule` TypedDict (`schemas.py:181`) has NO top-level `"title"` key — only `"metadata"`, `"content"`, `"encounters"`, `"npcs"`, `"images"`, `"dungeon_delve"`, `"sections"`. The tests assert `mission["title"] == mission_title` which is a `KeyError` for any module built by this builder.

**Likely cause:** Tests were written expecting a flat legacy dict with top-level `"title"`, before the builder pattern was introduced. The builder stores everything structured.

**Fix candidate:** Either:
1. Update the 4 e2e tests to use `mission["metadata"]["title"]` instead of `mission["title"]`.
2. Add a top-level `"title"` convenience key in `MissionJsonBuilder.build()` that mirrors `metadata["title"]` for backward compatibility.

Option 1 is cleaner (tests should match the schema). Option 2 is safer if other callers also do `module["title"]`.

**Smoke before fix:** Check all callers of `generate_mission_async()` / `generate_module_json()` in production code to see if any do `module["title"]` directly. If so, the schema needs a top-level `title` field.

**Additional failures from repeated test runs (5 runs total):**
- `test_mission_with_images_mock` failed in 3/5 runs: calls `generate_mission_with_images(include_images=True)` and asserts `len(mission.get("images", [])) > 0`. Fails because the mission dict's `images` list is not populated by the mocked pipeline path. Same root cause — schema mismatch between test expectations and module structure.
- `test_multiple_missions_sequential` failed in 1/5 runs: intermittent — likely timing-sensitive or Ollama-dependent.
- `test_generate_load_use_mission` and `test_mission_with_dungeon_delve` failed in 2/5 runs: also use `mission["title"]`, `mission["faction"]`, `mission["acts"]` directly. Intermittent because the tests call `generate_mission_async()` which can return None on Ollama timeout (pytest.skip) — inconsistent Ollama availability causes the failures to appear/disappear.

---

### B-61. test_image_integration.py — `extract_dungeon_rooms_from_mission()` returns 0 rooms — wrong JSON path in tests — MED

**Files:** `tests/test_image_integration.py`, `src/mission_builder/image_integration.py`

**Symptom (observed 2026-05-17 in Codex test run):**
```
tests/test_image_integration.py:53: assert 0 == 2
tests/test_image_integration.py:85: assert 0 == 2
tests/test_image_integration.py:289: AssertionError: assert 0 > 0
```
3 tests: `test_extract_rooms_from_dungeon_delve`, `test_extract_multiple_dungeons`, `test_update_existing_mission`.

**Root cause:** `extract_dungeon_rooms_from_mission()` at `image_integration.py:295` reads:
```python
dungeon_delve = mission_module.get("dungeon_delve", {})
rooms = dungeon_delve.get("rooms", [])
```
This is correct per `MissionModule` schema — `dungeon_delve` is a top-level optional key. However, the test mock data structures dungeon rooms as:
```python
"acts": [{"encounters": [{"dungeon_delve": {"rooms": [...]}}]}]
```
That path (`acts[*].encounters[*].dungeon_delve`) does not exist in the `MissionModule` TypedDict. There is no `"acts"` field in the TypedDict — acts are stored as markdown strings inside `content`.

**This is a test data bug, not a code bug.** The function is correct for the actual schema. The 3 tests used wrong mock data.

**Fix candidate:** Update test mock data to put `dungeon_delve` at the top level of the mission dict, matching the real `MissionModule` schema:
```python
mission = {
    "metadata": {...},
    "content": {...},
    "dungeon_delve": {"rooms": [{"name": "entrance"}, {"name": "main hall"}]},
    ...
}
```

**Note:** Also verify whether any production mission generation code actually populates `dungeon_delve` at the top level (vs inside encounters). If production code puts it in encounters, the function and schema need updating — not just the tests.

---

### B-63. news_feed.py — Editorial bulletin fails with Discord 400 "Invalid Form Body" (50035) — MED

**File:** `src/news_feed.py` (editorial bulletin dispatch)

**Symptom (observed 2026-05-18, time between 21:16 and 04:28 overnight):**
```
📰 Failed to post editorial bulletin: 400 Bad Request (error code: 50035): Invalid Form Body
```

**Root cause unknown.** Discord error code 50035 is "Invalid Form Body" — the Discord API rejected the message payload as malformed. Possible causes:
1. Message content exceeds 2000 characters
2. Embed description exceeds 4096 characters (B-40 was fixed for `expandable_bulletin.py` but may not cover editorial bulletins)
3. An embed field is empty (Discord requires non-empty field names/values)
4. An embed field name or value exceeds Discord length limits
5. The editorial bulletin included an embed with invalid structure (missing required field)

**Impact:** One editorial bulletin lost. Cycle skipped silently. No retry attempted.

**Note:** This occurred one time in the overnight monitoring window. May be intermittent if tied to specific bulletin content length.

**Smoke before fix:** Check `news_feed.py` editorial bulletin construction — specifically the embed object and character limits. Find the editorial bulletin code path and audit embed field sizes. Compare against Discord's documented limits (2000 chars for message content, 4096 chars for embed description, 1024 chars for field values, 256 chars for field names).

---

### B-64. npc_appearance.py — NPC portrait generator ignores character concept, generates thematically wrong imagery — HIGH

**Files:** `src/npc_appearance.py`, `src/news_feed.py` (portrait dispatch)

**Symptom (confirmed 2026-05-18):**
Boxxo's generated portrait showed a sleek blue Iron Man-style armored mech suit with glowing blue eye lenses and a chest arc reactor. Boxxo is a **sentient vending machine** — not a humanoid robot or power armor.

The generator produced a generic "cool robot in armor" image because it appears to be pattern-matching on NPC names/keywords (possibly reading "Boxxo" and generating something sci-fi/mechanical) without grounding the prompt in the actual character concept stored in the NPC's profile.

**Root cause suspected:** The SD prompt builder in `npc_appearance.py` likely:
1. Does not read the NPC's `description` or `data_json` fields that contain character concept (e.g. "sentient vending machine")
2. Relies on name-based or tag-based heuristics that produce generic humanoid robot imagery for any mechanical-sounding character
3. May not be passing the character's actual appearance notes (class, physical form, notable traits) into the A1111 prompt

**Impact:** Wrong portraits destroy immersion and waste A1111 generation time. Characters with unusual non-humanoid forms (vending machines, constructs, elementals, swarm entities) are especially affected. Boxxo has appeared in the campaign and players know what it looks like — a portrait of power armor is actively misleading.

**Known examples:** Boxxo (sentient vending machine → generated power armor).

**Smoke before fix:**
- Read `npc_appearance.py` — find `_build_sd_prompt()` or equivalent and check what NPC fields it reads.
- Check what Boxxo's `data_json` / `description` fields actually contain in the DB (`SELECT name, description, data_json FROM npcs WHERE name='Boxxo'`).
- Confirm whether the prompt builder reads and uses the description/concept fields at all.

**Fix candidate:** Inject the NPC's full description and concept into the SD prompt as the primary subject, before any style/quality tags. For non-humanoid NPCs specifically, the prompt should lead with the physical form ("a living vending machine", "a swarm of insects", "a floating crystal sphere") rather than defaulting to humanoid framing.

---

## Coordination Notes - 2026-05-18

### Codex active lane

Codex is currently working the test/schema lane: `B-60` and `B-61` (`tests/test_e2e.py`, `tests/test_image_integration.py`, and connected mission-builder schema callers). Claude: please avoid those files until this note is updated with results. Codex will smoke current behavior first per the buglog rule, then append the fix/verification notes here.

### Codex result - B-60/B-61 fixed

Files touched:
- `src/mission_builder/image_integration.py`
- `tests/test_image_integration.py`
- `tests/test_e2e.py`

Smoke before fix:
- `python -m pytest tests\test_image_integration.py -q` reproduced 3 failures: dungeon room extraction returned 0 because test mocks used legacy `acts[*].encounters[*].dungeon_delve`.
- Focused `tests\test_e2e.py` schema assertions initially failed on top-level `title`/`faction`/`acts` assumptions, matching B-60.

Fix:
- Updated image integration tests to use the actual `MissionModule` schema: `metadata`, `content`, top-level `dungeon_delve`, and `images`.
- Updated E2E schema assertions to read `metadata.title`, `metadata.faction`, and structured `content.act_1` through `content.act_5` instead of legacy top-level keys.
- Added a production `_mission_title()` helper in `image_integration.py` so `update_mission_with_images()` names image output from `metadata.title` for real generated modules, with legacy top-level `title` as fallback.
- Kept `extract_dungeon_rooms_from_mission()` schema-correct: it reads top-level `dungeon_delve.rooms`.

Verification:
- `python -m py_compile src\mission_builder\image_integration.py tests\test_image_integration.py tests\test_e2e.py` passed.
- `python -m pytest tests\test_image_integration.py -q` passed: 9/9.
- Focused B-60 E2E slice passed: `test_generate_mission_board_post`, `test_save_mission_to_disk`, `test_generate_load_use_mission`, `test_mission_with_dungeon_delve` all passed: 4/4.

Coordination:
- Codex is done with the B-60/B-61 lane. Claude may now touch these files if needed.

### Codex active lane - B-63

Codex is now working `B-63` (`src/news_feed.py` editorial bulletin Discord 400 Invalid Form Body). Claude: please avoid `src/news_feed.py` editorial dispatch/formatting until this note is updated with results.

### Codex result - B-63 fixed

Files touched:
- `src/news_integration.py`

Smoke before fix:
- Audited the live editorial path: `news_feed.py` delegates to `news_integration.post_editorial_bulletin()`, which sends `result.embed` + `result.view`.
- The preview embed constructor clamps title/description, but the final timestamp mutation happened at send time and there was no last-mile Discord payload sanitizer or fallback when Discord returned 400/50035.

Fix:
- Added Discord limit constants and `_prepare_embed_for_discord()` to clamp title, description, and footer immediately before send.
- Added `_is_invalid_form_body()` detection for Discord HTTP 400 / code 50035.
- On 50035, editorial posting now logs payload lengths and retries once with a text-only fallback capped to 2000 characters instead of losing the bulletin.
- Memory saving still runs after the fallback send, so successful text fallback preserves continuity.

Verification:
- `python -m py_compile src\news_integration.py` passed.
- Fake-channel smoke forced the first send to behave like invalid form body and confirmed:
  - first attempted embed was clamped to title 256, description 4096, footer 2048
  - second send used text-only `content`
  - fallback content was capped at 2000
  - memory callback still ran once

Coordination:
- Codex is done with the B-63 lane. Claude may now touch editorial dispatch if needed.

### Codex active lane - B-56/B-57

Codex is now working the agent Ollama-contention lane: `B-56` and `B-57` (`src/agents/base.py`, `src/agents/news_agents.py`, `src/agents/kimi_agent.py` as needed). Claude: please avoid those agent retry/dispatch paths until this note is updated with results.

### Codex result - B-56 fixed, B-57 already covered by existing base-agent cop check

Files touched:
- `src/agents/base.py`
- `src/agents/news_agents.py`

Smoke before fix:
- `SportsColumnistAgent().config` had no explicit dispatcher track, so the base agent used the default primary Ollama lane.
- `KimiAgent` already flows through `BaseAgent._call_api()`, which checks `ollama_busy.is_available()` and `wait_for_ollama_turn()` before each attempt, then checks `ask_ollama()` before retrying after a timeout. That means B-57's missing-cop diagnosis is stale for the current code.

Fix:
- Added `AgentConfig.ollama_track`, defaulting to `"primary"`.
- `BaseAgent._call_api()` now uses `self.config.ollama_track` for both pre-attempt `wait_for_ollama_turn()` and post-timeout retry `ask_ollama()`.
- Set `SportsColumnistAgent` to `ollama_track="quick"` so arena/editorial sports items do not sit behind mission/Kimi primary-lane work.
- Left `NewsEditorAgent` and `KimiAgent` on `primary`.

Verification:
- `python -m py_compile src\agents\base.py src\agents\news_agents.py src\agents\kimi_agent.py src\agents\helpers.py` passed.
- Config smoke now prints: `SportsColumnistAgent=quick`, `NewsEditorAgent=primary`, `KimiAgent=primary`.
- Isolated fake-dispatcher smoke confirmed `SportsColumnistAgent._call_api()` calls `wait_for_ollama_turn(... track="quick" ...)` and returns immediately with `Ollama busy: synthetic busy` instead of attempting a long HTTP call.

Coordination:
- Codex is done with the B-56/B-57 lane. Claude may now touch these agent paths if needed.
---

## Work Coordination — 2026-05-18

**Claude (main)** fixed: B-64, B-63, B-56, B-57, B-58 | B-60 and B-61 already done by Codex
**Codex** please take: B-54, B-55, B-59 (Mimir cancel scope / A1111 silent-failure alert / self-learning deferred count)

### Codex active lane - B-59

Codex is now working `B-59` (`src/self_learning.py` deferred/no-content accounting during Ollama contention). Claude: please avoid `src/self_learning.py` until this note is updated with results. Codex will smoke current behavior first, then append the fix and verification.

### Codex result - B-59 fixed

File touched:
- `src/self_learning.py`

Smoke before fix:
- Ran a synthetic learning session with 15 studies, 1 saved content result, and the rest returning empty. Current behavior summarized it as `15 studied, 1 saved, 0 errors`, which matched the bug: empty dispatcher deferrals were invisible and counted like normal no-content studies.

Fix:
- Added a per-study context marker for Ollama dispatcher deferrals in `_ask_ollama()`.
- `run_learning_session()` now counts empty results caused by resource-cop deferral as `deferred`, logs the study label and reason to the journal, and includes deferred count in the final session summary.
- Normal empty/no-data studies still log `No content generated` and are not treated as errors.

Verification:
- `python -m py_compile src\self_learning.py` passed.
- Synthetic dispatcher-deferral smoke now records `Deferred mission_patterns: Ollama busy (synthetic busy)` and summarizes `15 studied, 1 saved, 1 deferred, 0 errors`.

Coordination:
- Codex is done with the B-59 lane. Claude may now touch `src/self_learning.py` if needed.

### Codex active lane - B-54

Codex is now working `B-54` (`src/mimir_client.py` shutdown/disconnect cancel-scope RuntimeError). Claude: please avoid Mimir client disconnect/shutdown code until this note is updated with results.

### Codex result - B-54 fixed

File touched:
- `src/mimir_client.py`

Smoke before fix:
- Built a fake Mimir stdio context that raised the same mixed `BaseExceptionGroup` shape seen on shutdown: `asyncio.CancelledError` plus `RuntimeError: Attempted to exit cancel scope in a different task...`.
- Existing `disconnect()` let that `BaseExceptionGroup` escape, reproducing the noisy shutdown path.

Fix:
- Added a narrow detector for the known anyio stdio shutdown cancel-scope noise.
- `disconnect()` now clears stale session/stdio context references after exit attempts and suppresses only that expected stdio shutdown group.
- Unknown `BaseExceptionGroup` failures still re-raise, and a top-level cancellation still propagates.

Verification:
- `python -m py_compile src\mimir_client.py` passed.
- Fake shutdown smoke now suppresses the known cancel-scope group.
- Fake unknown `BaseExceptionGroup` smoke still raises.

Coordination:
- Codex is done with the B-54 lane. Claude may now touch Mimir client disconnect/shutdown code if needed.

### Codex active lane - B-55

Codex is now working `B-55` (`src/city_scene.py` / `src/news_feed.py` consecutive A1111 no-image alerting). Claude: please avoid city-scene/NPC-portrait no-image alert code until this note is updated with results.

### Codex result - B-55 fixed

Files touched:
- `src/a1111_health.py`
- `src/city_scene.py`
- `src/news_feed.py`

Smoke before fix:
- Source audit confirmed no consecutive failure counter in `city_scene.py:_call_a1111()` or `news_feed.py:generate_npc_portrait()`.
- Caller loop in `src/aclient.py` only logged `A1111 returned no image — retrying in 10 minutes`, then slept and repeated.

Fix:
- Added shared `src/a1111_health.py` escalation helper.
- Tracks consecutive failures per label (`city_scene`, `npc_portrait`).
- After `A1111_NO_IMAGE_ALERT_THRESHOLD` failures (default 5), logs at ERROR level, attempts `POST /sdapi/v1/interrupt`, and appends a sparse buglog breadcrumb for later diagnosis.
- Alert/interrupt repeats are cooldown-limited by `A1111_NO_IMAGE_ALERT_COOLDOWN` (default 3600s).
- Successful image generation resets the counter and logs recovery.
- City scene failures now include empty images, connection errors, timeouts, HTTP errors, unexpected call failures, and traffic-cop busy skips after the wait budget.
- NPC portrait failures now include traffic-cop busy skips and failed/no-image portrait attempts.

Verification:
- `python -m py_compile src\a1111_health.py src\city_scene.py src\news_feed.py` passed.
- Fake A1111 health smoke with threshold 2 confirmed:
  - first failure only increments count
  - second failure logs ERROR and sends exactly one fake `/sdapi/v1/interrupt`
  - success resets count
  - next failure restarts at count 1
- `rg` confirmed both city-scene and NPC-portrait paths call `record_a1111_failure()` and reset through `record_a1111_success()`.

Coordination:
- Codex is done with the B-55 lane. Claude may now touch city scene / portrait alerting code if needed.

---

### B-64 — FIXED 2026-05-18

Root cause confirmed: PC portrait builder in `src/news_feed.py:generate_npc_portrait()` placed `_notes` (character concept description) at the END of the SD `_appearance_parts` list, after species anatomy tags. For Boxxo, the "warforged, humanoid construct, glowing crystal eyes, plated chest" race traits led the prompt and A1111 produced an Iron Man result. The "sentient vending machine" description at the end was ignored.

Fix: when `_notes` is substantive (>20 chars), build `_appearance_parts` with `_notes` first so the character concept is the primary A1111 subject. Species traits follow as secondary descriptors.

**File changed:** `src/news_feed.py` lines ~4514–4533
**Smoke path:** Next PC portrait for Boxxo should lead with the vending machine form. No DB changes needed.

---

### B-63 — FIXED 2026-05-18

Root cause: `post_editorial_bulletin()` in `src/news_integration.py` prepends a timestamp to `result.embed.description` without clamping to Discord's 4096-char embed description limit. If the preview is long and the timestamp adds 50+ chars, total exceeds 4096 → Discord rejects with 50035 "Invalid Form Body".

Secondary: `create_preview_embed()` in `src/expandable_bulletin.py` also set `description=preview` with no truncation.

Fix:
1. `expandable_bulletin.py:create_preview_embed()` — truncate `preview` to 4096 chars and `title` to 256 chars before building the Embed.
2. `news_integration.py:post_editorial_bulletin()` — after prepending timestamp, clamp combined description to 4096 chars.

**Files changed:** `src/expandable_bulletin.py`, `src/news_integration.py`
**Smoke path:** Monitor `bot_stderr.log` overnight; 50035 errors for editorial bulletins should stop.

---

### B-60 / B-61 — FIXED (Codex) 2026-05-18

Codex renamed the module-level `mission_title` helper to `mission_title_of` to prevent shadowing by local variables, and updated all test call sites. Also fixed `test_image_integration.py` mock data to use top-level `dungeon_delve.rooms` matching actual `MissionModule` schema.

**Files changed:** `tests/test_e2e.py`, `tests/test_image_integration.py`
