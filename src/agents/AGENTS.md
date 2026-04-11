# Tower Bot Agent Architecture

## Overview

The Tower bot uses a two-agent architecture running 100% locally via Ollama:

| Agent | Model | Use Case | Cost |
|-------|-------|----------|------|
| **QwenAgent** | `qwen` (fast, small) | Fast, simple tasks | $0 |
| **KimiAgent** | `qwen:32b` or larger | Complex reasoning | $0 |

**All models run locally — no cloud required.**

## Quick Reference

```python
from src.agents import QwenAgent, KimiAgent

# Fast local inference
qwen = QwenAgent()
result = await qwen.complete("What are the rules for opportunity attacks?")

# Complex reasoning (larger local model)
kimi = KimiAgent()
result = await kimi.generate_bulletin(news_type="rumour", memory_context=...)
```

## Agent Selection Guide

### Use QwenAgent for:
- **Rules lookups** (`rules_agent.py` → `qwen.rules_query()`)
- **Style descriptions** (`style_agent.py` → `qwen.style_description()`)
- **Quick formatting** (text cleanup, summarization)
- **Single-shot questions** (faction info, NPC lookup)
- Any task where **speed > reasoning depth**

### Use KimiAgent for:
- **News bulletin generation** (needs world state + continuity)
- **Mission generation** (multiple interconnected elements)
- **Multi-step reasoning** (analysis, planning)
- Any task where **quality > speed**

## File Mapping (COMPLETE)

| File | Migration Status |
|------|-----------------|
| `src/rules_agent.py` | ✅ Uses `QwenAgent.rules_query()` |
| `src/style_agent.py` | ✅ Uses `QwenAgent.style_description()` |
| `src/news_feed.py` | ✅ Uses `generate_bulletin()` |
| `src/mission_board.py` | ✅ Uses `generate_mission_text()` |
| `src/missing_persons.py` | ✅ Uses `generate_with_kimi()` |
| `src/providers.py` | ✅ `FreeProvider` uses agents |

## Environment Variables

```bash
# Ollama base URL (agents auto-append /v1 for OpenAI-compat API)
OLLAMA_URL=http://localhost:11434

# QwenAgent model (fast, small)
QWEN_MODEL=qwen              # or qwen:7b, mistral:7b, phi3

# KimiAgent model (complex tasks, larger)
KIMI_MODEL=qwen:32b          # or mistral, llama3:70b, mixtral
KIMI_ENABLE_SUBAGENTS=false  # Disabled for local-only setup

# Legacy (still supported)
OLLAMA_MODEL=qwen3-8b-slim:latest         # Fallback model
```

**Recommended Local Models:**
- Fast (QwenAgent): `qwen`, `qwen:7b`, `qwen3-8b-slim:latest`, `phi3`
- Complex (KimiAgent): `qwen:32b`, `qwen3-8b-slim:latest`, `llama3:70b`

## API Endpoints

The agents use the OpenAI-compatible API:
- **Base URL:** `http://localhost:11434/v1`
- **Endpoint:** `/v1/chat/completions`

## Response Structure

All agents return `AgentResponse`:

```python
@dataclass
class AgentResponse:
    content: str              # The response text
    model: str                # Model that generated it
    success: bool             # Whether the call succeeded
    error: Optional[str]      # Error message if failed
    usage: Dict[str, int]     # Token usage stats
```

## Helper Functions

For quick generation without instantiating agents:

```python
from src.agents import generate_with_kimi, generate_with_qwen, generate_bulletin

# Quick Kimi generation
text = await generate_with_kimi(prompt, temperature=0.8)

# Quick Qwen generation
text = await generate_with_qwen(prompt, temperature=0.7)

# News bulletin generation
bulletin = await generate_bulletin(news_type="rift", instruction="...")
```

## Busy Flag Integration

Agents respect the `ollama_busy.py` flag:

```python
from src.ollama_busy import is_available, mark_busy, mark_available

# Agents automatically check is_available() before calling
# Long-running tasks should use:
mark_busy("generating mission module", model="qwen:32b")
try:
    # ... long task ...
finally:
    mark_available()
```
