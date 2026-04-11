# Tower Bot — Debug Log
**Created:** 2026-04-10  
**Purpose:** Track all spotted bugs, investigations, and resolutions. Add new entries at the top of each section. Mark status: `ACTIVE`, `INVESTIGATING`, `FIXED`, `WONTFIX`.

---

## Active Bugs

---

### BUG-008 — mission_compiler.py `generate_vtt_map()` called with wrong kwargs
**Status:** FIXED — 2026-04-10  
**Severity:** Medium (map generation silently failed on every mission compile)  
**Fix:** Replaced broken `generate_vtt_map(scene_description=..., location_type=..., output_subdir=...)` call with `generate_module_maps(module_data, output_subdir=safe_title, max_maps=4)` which has the correct signature.  
**File:** `src/mission_compiler.py` line ~697

---

### BUG-007 — Editor agent returns empty output
**Status:** ACTIVE  
**Severity:** Low (graceful fallback in place)  
**First seen:** 2026-04-10 (recurring in bot_stderr.log)  
**Log pattern:**
```
✏️ Editor output invalid (empty) — using original draft
```
**What happens:** The editor agent (in `news_feed.py`) calls an LLM to polish the bulletin draft. The agent returns an empty string, so the original draft is used unchanged. Bulletins still post — quality just doesn't get the editorial pass.  
**Likely cause:** Ollama/Mistral timeout or empty response on the editorial pass. Agent prompt may not be returning structured output.  
**Where to look:** `src/news_feed.py` — search for `"Editor output invalid"`. Check the editor agent call; add logging for the raw response before the validity check.  
**Related:** BUG-006 (fact-checker has same pattern). Both are editorial pipeline agents.

---

### BUG-006 — Fact-check agent returns result too short
**Status:** ACTIVE  
**Severity:** Low (graceful fallback in place)  
**First seen:** 2026-04-10 (recurring in bot_stderr.log)  
**Log pattern:**
```
✏️ Fact-check: result too short, using original
```
**What happens:** The fact-check step in the bulletin pipeline receives a response that's shorter than the minimum expected length and falls back to the original. Bulletin still posts.  
**Likely cause:** Same root cause as BUG-007 — Mistral/Ollama returning minimal output under load. The fact-check prompt may be too long, causing the model to truncate.  
**Where to look:** `src/news_feed.py` — search for `"result too short"`. Check the fact-check agent's prompt and minimum-length threshold.  
**Fix candidate:** Add `"stream": False` explicitly, increase timeout, or simplify the fact-check prompt.

---

### BUG-005 — Bulletin validation failing: too few lines or truncated
**Status:** ACTIVE  
**Severity:** Medium (wastes a generation cycle + delays bulletin)  
**First seen:** 2026-04-10  
**Log patterns:**
```
📰 Bulletin failed validation (truncated) — discarding: Vendredi...
📰 Bulletin failed validation (too few lines (1)) — discarding: **Blackthorn Syndicate...
```
**What happens:** `generate_bulletin()` generates a bulletin then runs validation. Two failure modes seen:
1. **Truncated** — bulletin ends mid-sentence or is cut off. 
2. **Too few lines** — the full bulletin is on a single line (missing newlines).  
After discard, `generate_bulletin()` returns `None`, which triggers BUG-001.  
**Likely cause:** Ollama model (`qwen3-8b-slim`) hitting context/token limits and truncating output, or response not being streamed correctly. The "too few lines" variant suggests the model is summarizing instead of expanding.  
**Where to look:** `src/news_feed.py` `generate_bulletin()` — check the generation parameters (`max_tokens`, temperature), the validation logic, and whether the prompt is too prescriptive.  
**Fix candidate:** Add retry logic (1-2 retries on validation failure before returning None). Check if `max_tokens` is too low.

---

### BUG-004 — Mistral prompt agent returns prose instead of tags
**Status:** ACTIVE  
**Severity:** Low (self-lookup fallback works)  
**First seen:** 2026-04-10 (recurring in bot_stderr.log)  
**Log pattern:**
```
🤖 Prompt agent: Mistral returned prose or too few tags — using self-lookup fallback
```
**What happens:** The image prompt agent calls Mistral to generate structured SD tags (comma-separated). Mistral returns a prose sentence or too few tags, so the system falls back to building the prompt from its own NPC/location lookup. Images still generate fine.  
**Likely cause:** Mistral model not following the structured tag format in the prompt. The system message or few-shot examples may not be strong enough.  
**Where to look:** `src/npc_appearance.py` or `src/news_feed.py` — the image prompt builder that calls the "Mistral" agent. Check the prompt format and the tag-count threshold.  
**Fix candidate:** Add explicit few-shot examples like `"Output ONLY comma-separated tags. Example: black hair, red cloak, sword, standing, city street"`. Also consider switching to Qwen for this task since it follows instructions better.

---

### ~~BUG-005~~ FIXED-009 — Bulletin validation failing: too few lines (single-line output)
**Status:** FIXED — 2026-04-10  
**Root cause:** Qwen3-8b-slim outputs entire bulletin as one continuous line with no newlines. `validate_bulletin()` saw 1 line → discarded.  
**Fix:** Inserted newline-normalisation block in `generate_bulletin()` in `src/news_feed.py`. Injects `\n` after bold headers (Case A), dangling bold openers (Case B), or sentence boundaries (Case C). Also added `think: False` and bumped `num_predict` 512→1024.  
**See:** `logs/worklog_session_20260410b.md`

---

### ~~BUG-003~~ FIXED-007 — NPC lifecycle load error: NoneType not a mapping
**Status:** FIXED — 2026-04-10  
**Root cause found:** MySQL `npcs.data_json` column was NULL for 115 of 119 rows. `_load_npcs()` did `**None` (unpacking NULL) which crashed and returned `[]`, so lifecycle ran on an empty roster every cycle.  
**Fixes applied:**
1. `src/npc_lifecycle.py` `_load_npcs()`: added `or {}` guard + `not isinstance(npc_data, dict)` check
2. DB migration: populated `data_json` for all 115 NULL rows from DB columns (name, faction, role, location, status, appearance)
**See:** `logs/worklog_bug_fixes_20260410.md`

---

### ~~BUG-REACTION~~ FIXED-008 — ⚔️ reaction not triggering mission claim
**Status:** FIXED — 2026-04-10  
**Root cause found (2 issues):**
1. `missions.message_id` is `VARCHAR(50)` in MySQL → loaded as Python string. `handle_reaction_claim()` compared `str == int` → always False, mission never found, function returned immediately.
2. Discord may strip `\ufe0f` (variation selector) from emoji payloads, so `"⚔️" != "⚔"`.
**Fixes applied:**
1. `src/mission_board.py` `_load_missions()`: cast `message_id` to `int` after loading from DB
2. `src/cogs/missions.py` `on_raw_reaction_add`: strip `\ufe0f` before comparing emoji
**See:** `logs/worklog_bug_fixes_20260410.md`

---

### BUG-002 — generate_bulletin() returns None — mission board may be missing
**Status:** ACTIVE  
**Severity:** Medium (mission board bulletin not generated, warning spams log)  
**First seen:** 2026-04-10 (multiple times per hour)  
**Log pattern:**
```
WARNING src.log -> 📰 generate_bulletin() returned None — mission board may be missing.
```
**What happens:** In the news feed loop, after posting the main agent bulletin, a second call to `generate_bulletin()` returns `None`. The WARNING suggests this is supposed to include a mission board state summary. Fired after EVERY successful agent bulletin post.  
**Likely cause:** This is a downstream effect of BUG-005. When `generate_bulletin()` fails validation it returns `None`. The calling code in `news_feed_loop` warns but continues — so bulletins still post, just without the mission board section.  
**But also:** The pattern is 100% consistent — it fires after EVERY bulletin. This could mean the `generate_bulletin()` call for the mission board section is always hitting a code path that returns `None` regardless of validation.  
**Where to look:** `src/news_feed.py` — the `news_feed_loop` function. Find the call to `generate_bulletin()` that produces this warning. Check if there's a mission-board-specific code path that always returns early.  
**Fix candidate:** Add a `logger.debug()` call showing the exact input to the failing `generate_bulletin()` call to narrow down whether it's always the same call.

---

### BUG-001 — Discord gateway RESUME events (low priority)
**Status:** ACTIVE (expected behavior)  
**Severity:** Info only  
**First seen:** 2026-04-10  
**Log pattern:**
```
[INFO] discord.gateway: Shard ID None has successfully RESUMED session ...
```
**What happens:** Discord drops and re-establishes the WebSocket connection. The bot handles this gracefully with a RESUME.  
**Likely cause:** Normal Discord network behavior. The bot's server (Windows desktop) may have intermittent connectivity. Sessions resume correctly.  
**Action needed:** None unless RESUME events become RECONNECT/DISCONNECT events. Monitor for escalation.

---

## Fixed Bugs

---

### FIXED-006 — CommandAlreadyRegistered crash on startup
**Fixed:** 2026-03-11  
**Was:** `/generatenpcs` and `/npcprofile` defined twice in `bot.py`  
**Fix:** Removed the duplicate block (between /spell and /style)  
**File:** `src/bot.py`

---

### FIXED-005 — EC rate appearing inside story bulletins
**Fixed:** 2026-03-11  
**Was:** AI appended exchange rate table to story bulletins  
**Fix:** `economy_note` in `news_feed.py _build_prompt()` now explicitly bans rate tables with hard fail language; added post-gen regex filter stripping rate-pattern lines  
**File:** `src/news_feed.py`

---

### FIXED-004 — Story images were background-focused, not NPC-focused
**Fixed:** 2026-03-11  
**Was:** `_build_image_prompt()` generated background/location prompts  
**Fix:** Rewrote to scan last 6 bulletins for NPC mentions, build NPC appearance block, instruct Ollama that NPC is central subject  
**File:** `src/news_feed.py`

---

### FIXED-003 — Slash commands not appearing after /sync
**Fixed:** 2026-03-11  
**Was:** Sync was in `on_ready` (fires after bot appears online — too late for Discord)  
**Fix:** Moved sync to `setup_hook()` in `aclient.py` (fires before gateway connection). `self.tree` created in `__init__`. `setup_hook()` does `copy_global_to + tree.sync` using `_sync_guild_id`.  
**Files:** `src/aclient.py`, `src/bot.py`, `.env` (added `DISCORD_GUILD_ID`)

---

### FIXED-002 — mission_builder/__init__.py corrupted by regex edit
**Fixed:** 2026-03-28  
**Was:** `filesystem:edit_file` with regex corrupted file — duplicated content, broke `_post_process_module_text()`  
**Fix:** Read corrupted file, reconstructed complete module from scratch, wrote full replacement  
**File:** `src/mission_builder/__init__.py`  
**Lesson:** NEVER use regex-based editing for multi-line code. Always read-full → edit in memory → write-full.

---

### FIXED-001 — Unicode SyntaxError in clear_commands.py (Windows paths)
**Fixed:** 2026-03-11  
**Was:** Windows path backslashes in triple-quoted docstring caused SyntaxError  
**Fix:** Escaped backslashes or used raw strings  
**File:** `clear_commands.py`

---

## Investigation Queue

These are anomalies noticed but not yet diagnosed:

| # | Observation | Where Spotted | Priority |
|---|-------------|---------------|----------|
| # | Observation | Where Spotted | Priority |
|---|-------------|---------------|----------|
| I-001 | RESOLVED — false `generate_bulletin() returned None` warning fixed with `bulletin_posted` flag in `aclient.py` | — | — |
| I-002 | RESOLVED — "Mistral" label was hardcoded in prompt agent; replaced with `{ollama_model}` variable | — | — |
| I-003 | RESOLVED — NPC roster was resetting because 115/119 DB rows had NULL data_json; fixed + migrated | — | — |
| I-004 | Self-learning session shows `→ No content generated for conversation_logs` — conversation logs may be empty or path wrong | logs/journal.txt | Low |
| I-005 | `bot_stdout.log` appears empty — stdout logging may not be wired up | logs/bot_stdout.log | Low |
| I-006 | `FactCheckerMixin.get_npc_graveyard()` was reading stale `npc_graveyard.json`; FIXED — now queries MySQL | — | — |
| I-007 | `npc_consequence.py` all four I/O functions read/wrote JSON files; FIXED — all now use MySQL with file fallback | — | — |

---

## How to Add a Bug Entry

```markdown
### BUG-XXX — Short description
**Status:** ACTIVE | INVESTIGATING | FIXED | WONTFIX
**Severity:** Critical | High | Medium | Low
**First seen:** YYYY-MM-DD HH:MM
**Log pattern:**
```
exact log line that indicates the bug
```
**What happens:** Plain description of the observable behavior.
**Likely cause:** Hypothesis about root cause.
**Where to look:** Specific files, functions, line ranges.
**Fix candidate:** Proposed fix or next step.
```
