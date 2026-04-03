# Mission Compiler Skill

## IMPORTANT: Old System Deprecated

As of 2026-04-02, the old 14-pass `module_generator.py` system is **DEPRECATED**.

All mission types (including "standard") now use the new MissionCompiler pipeline:
- JSON generation → Agent enhancement → docx output
- Archived code: `backups/archived_module_generator/`

Importing `src.module_generator` will now raise an ImportError.

## Overview

The **Mission Compiler** (`src/mission_compiler.py`) is Stage 2 of the Tower of Last Chance mission pipeline. It transforms mission JSON into full playable .docx modules using agents and skills.

## Pipeline Architecture

```
Stage 1: Mission Board generates mission JSON
         └── src/mission_builder/mission_json_builder.py
         └── Saves to: generated_modules/pending/

Stage 2: Mission Compiler processes JSON
         └── src/mission_compiler.py
         └── Uses: DNDExpertAgent + DNDVeteranAgent + AICriticAgent
         └── Injects: Skills based on mission type
         └── Outputs: .docx → posts to Discord channel 1484147249637359769
         └── Archives to: generated_modules/completed/
```

## Key Components

### MissionCompiler Class

Main orchestrator for Stage 2. Initialized with Discord client:

```python
from src.mission_compiler import MissionCompiler, build_mission_json

compiler = MissionCompiler(client)
docx_path = await compiler.compile_and_post(mission_json, player_name, client)
```

### Agent Enhancement Passes

Three agents enhance content in sequence:

1. **DNDExpertAgent** — Validates mechanics, CR, encounter balance, D&D 5e 2024 compliance
2. **DNDVeteranAgent** — Enhances narrative, NPC dialogue, atmosphere, world consistency
3. **AICriticAgent** — Final quality check, identifies gaps, outputs quality score (1-10)

**Important:** Agents use `force=True` to bypass the `ollama_busy` check since they're called *during* compilation (after we've already marked busy).

### Skill Injection

Skills are auto-selected based on mission type:

```python
MISSION_TYPE_SKILLS = {
    "standard": ["cw-mission-gen", "tower-bot"],
    "dungeon-delve": ["cw-mission-gen", "dnd5e-srd", "tower-bot"],
    "investigation": ["cw-mission-gen", "tower-bot"],
    "combat": ["cw-mission-gen", "dnd5e-srd"],
    "social": ["cw-mission-gen", "tower-bot"],
    "heist": ["cw-mission-gen", "tower-bot"],
    "rift": ["cw-mission-gen", "tower-bot"],
}
```

Skills are loaded via `src/skills.py` and injected into generation prompts.

## Integration Point: module_gen.py Cog

The `src/cogs/module_gen.py` cog now uses the compiler:

```python
from src.mission_compiler import MissionCompiler, build_mission_json

async def generate_and_post_module(mission: dict, player_name: str, client):
    # Build mission JSON from mission board dict
    mission_json = build_mission_json(
        title=mission.get("title"),
        faction=mission.get("faction"),
        tier=mission.get("tier"),
        mission_type=mission.get("mission_type", "standard"),
        cr=mission.get("cr", 6),
        ...
    )
    
    compiler = MissionCompiler(client)
    await compiler.compile_and_post(mission_json, player_name, client)
```

## Compilation Flow

1. `mark_busy()` — Prevent other systems from using Ollama
2. Load skills based on mission type
3. Load campaign context (NPCs, factions, news)
4. Generate sections: overview → act_1 → act_2 → act_3 → rewards
5. Agent pass 1: DNDExpert enhances mechanics (with `force=True`)
6. Agent pass 2: DNDVeteran enhances narrative (with `force=True`)
7. Agent pass 3: AICritic quality check (with `force=True`)
8. Build .docx via `docx_builder.build_docx()`
9. Post to Discord channel 1484147249637359769
10. Save JSON to `generated_modules/completed/`
11. `mark_available()`

## Directory Structure

```
generated_modules/
├── pending/     # Stage 1 output (mission JSONs waiting for compilation)
├── completed/   # Compiled mission JSONs (with compilation metadata)
├── missions/    # Final .docx files
└── raw/         # Raw markdown outputs (legacy)
```

## Output Channel

Module .docx files post to:
- Channel ID: `1484147249637359769`
- Fallback: DM to `DM_USER_ID`

## Quality Metadata

Each compiled module includes metadata:

```json
{
  "compilation": {
    "compiled_at": "2026-04-02T...",
    "player_name": "Adventurer Name",
    "quality_score": 8,
    "agents_used": ["DNDExpert", "DNDVeteran", "AICritic"],
    "skills_used": ["cw-mission-gen", "dnd5e-srd", "tower-bot"]
  }
}
```

## Key Files

| File | Purpose |
|------|---------|
| `src/mission_compiler.py` | Main compiler module |
| `src/cogs/module_gen.py` | Discord cog, triggers compilation on claim |
| `src/mission_builder/mission_json_builder.py` | Builds MissionModule JSON |
| `src/mission_builder/docx_builder.py` | Wraps Node.js docx generation |
| `src/agents/base.py` | BaseAgent with `force` parameter |
| `src/agents/learning_agents.py` | DNDExpert, DNDVeteran, AICritic agents |

## Troubleshooting

**Agents returning empty content?**
- Check that `force=True` is passed to `agent.complete()`
- Agents check `ollama_busy` flag; without `force=True` they skip during compilation

**DOCX build fails?**
- Verify Node.js is installed
- Check `scripts/build_module_docx.js` exists
- Review `logs/bot_stderr.log`

**Channel not found?**
- Verify `MODULE_CHANNEL_ID` (1484147249637359769) is accessible
- Bot falls back to DM if channel unavailable
