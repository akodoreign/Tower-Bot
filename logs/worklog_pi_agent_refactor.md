# Pi Agent Refactor Worklog
Created: 2026-04-02T11:00:00Z
Operation: Refactor Ollama usage to Pi/OpenClaw stack with kimi + qwen models

## Status: IN_PROGRESS

## Architecture Summary
**Current Stack:**
- Direct httpx calls to `http://localhost:11434/api/chat`
- Single model: mistral (env: OLLAMA_MODEL)
- Files using Ollama: providers.py, rules_agent.py, style_agent.py, news_feed.py, mission_board.py, etc.

**Target Stack:**
- Pi agent framework with pi-subagents
- Two models: kimi-k2.5:cloud (complex reasoning/subagents), qwen (fast local)
- OpenAI-compatible API at `http://localhost:11434/v1`
- Subagent orchestration for complex multi-step tasks

## Phase 1: Create Agent Infrastructure (THIS PHASE)
- [x] Step 1.1 — Read all Ollama usage patterns in codebase — DONE
- [x] Step 1.2 — Create src/agents/ directory structure — DONE
- [x] Step 1.3 — Create base PiAgent class with kimi/qwen support — DONE
- [x] Step 1.4 — Create KimiAgent (complex reasoning, subagents) — DONE
- [x] Step 1.5 — Create QwenAgent (fast local inference) — DONE
- [x] Step 1.6 — Update skill mapping documentation — DONE

## Phase 2: Refactor Existing Agents
- [x] Step 2.1 — Refactor rules_agent.py to use QwenAgent — DONE
- [x] Step 2.2 — Refactor style_agent.py to use QwenAgent — DONE
- [ ] Step 2.3 — Create tests for refactored agents

## Phase 3: Refactor Core Systems — COMPLETE
- [x] Step 3.1 — Refactor FreeProvider to use new agents — DONE
- [x] Step 3.2 — Refactor news_feed.py Ollama calls — DONE
- [x] Step 3.3 — Refactor mission_board.py Ollama calls — DONE
- [x] Step 3.4 — Update ollama_busy.py for multi-model awareness — DONE

## Phase 4: Advanced Features
- [ ] Step 4.1 — Implement subagent orchestration for complex tasks
- [ ] Step 4.2 — Add model fallback logic (kimi → qwen on failure)
- [ ] Step 4.3 — Integration testing

## Completed Steps
- [x] Step 1.1 — Read all Ollama usage patterns — DONE at 11:05
  - providers.py: FreeProvider uses httpx → http://localhost:11434/api/chat
  - rules_agent.py: Direct httpx calls with OLLAMA_MODEL/OLLAMA_URL env vars
  - style_agent.py: Same pattern as rules_agent
  - news_feed.py: Many async functions use same httpx pattern
  - ollama_busy.py: Global busy flag to prevent overlaps

- [x] Step 1.2 — Create src/agents/ directory structure — DONE at 11:10
  - Created C:\Users\akodoreign\Desktop\chatGPT-discord-bot\src\agents\

- [x] Step 1.3 — Create base PiAgent class — DONE at 11:12
  - Created src/agents/__init__.py (exports)
  - Created src/agents/base.py (BaseAgent, AgentConfig, AgentResponse)

- [x] Step 1.4 — Create KimiAgent — DONE at 11:15
  - Created src/agents/kimi_agent.py
  - Methods: complete(), generate_bulletin(), generate_mission(), orchestrate()

- [x] Step 1.5 — Create QwenAgent — DONE at 11:18
  - Created src/agents/qwen_agent.py
  - Methods: complete(), rules_query(), style_description(), format_text()

- [x] Step 1.6 — Update skill mapping documentation — DONE at 11:22
  - Created src/agents/AGENTS.md (architecture guide)
  - Updated .env.example with QWEN_MODEL, KIMI_MODEL, KIMI_ENABLE_SUBAGENTS

- [x] Step 2.1 — Refactor rules_agent.py — DONE at 11:30
  - Replaced direct httpx calls with QwenAgent.rules_query()
  - Preserved RulesAnswer dataclass and existing interface
  - Added lazy-loaded _qwen_agent singleton

- [x] Step 2.2 — Refactor style_agent.py — DONE at 11:35
  - Replaced direct httpx calls with QwenAgent.style_description() and complete()
  - Preserved existing interface (describe_character_style, enrich_appearance_prompt)
  - Added lazy-loaded _qwen_agent singleton

- [x] Step 3.1 — Refactor FreeProvider — DONE at 11:40
  - Updated providers.py FreeProvider to use QwenAgent/KimiAgent
  - Added model routing (kimi* → KimiAgent, else → QwenAgent)
  - Added fallback to direct Ollama if agents fail

- [x] Step 3.2 — Refactor news_feed.py — DONE at 11:45
  - Created src/agents/helpers.py with generate_with_kimi, generate_bulletin
  - Updated _generate_rift_bulletin() to use generate_bulletin
  - Updated check_missing_tick() — no longer passes ollama params
  - Refactored missing_persons.py generate_missing_bulletin() to use generate_with_kimi

- [x] Step 3.3 — Refactor mission_board.py — DONE at 11:50
  - Updated _generate() to use generate_mission_text helper
  - All mission generation now flows through KimiAgent

- [x] Step 3.4 — Update ollama_busy.py — DONE at 11:55
  - Added model tracking (_busy_model) for debugging
  - Added get_busy_duration() helper
  - Updated documentation for local-only operation
  - Both QwenAgent and KimiAgent share busy state (same Ollama instance)

- [x] Step 3.5 — Convert to 100% local operation — DONE at 12:00
  - Updated KimiAgent to default to qwen:32b (local)
  - Disabled subagents by default (require cloud)
  - Updated .env.example and AGENTS.md for local-only
  - All models now run locally via Ollama

## Last Checkpoint
Step: Phase 3 COMPLETE — 100% local operation
Time: 2026-04-02T12:00:00Z

## Resume Instructions
Phase 3 complete! All agents now run locally via Ollama.
- QwenAgent: fast tasks (default: qwen)
- KimiAgent: complex tasks (default: qwen:32b)

To test: ensure you have the models pulled:
  ollama pull qwen
  ollama pull qwen:32b  # or mistral, llama3:70b
