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
         └── Uses: ProAuthorAgent + DNDExpertAgent + DNDVeteranAgent + AICriticAgent
         └── Injects: Skills based on mission type (module-quality ALWAYS first)
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

### Agent Enhancement Pipeline (4 Agents)

Agents enhance content in this sequence:

1. **ProAuthorAgent** — FIRST PASS: Transforms raw sections into vivid narrative prose
   - Anti-patterns enforcement (purple prose, hedging, echo chamber)
   - Undercity voice and atmosphere
   - Dialogue and NPC characterization

2. **DNDExpertAgent** — Validates mechanics, CR, encounter balance, D&D 5e 2024 compliance
   - Also generates creature appendix with full stat blocks

3. **DNDVeteranAgent** — Enhances narrative, NPC dialogue, atmosphere, world consistency
   - Also generates location appendix, rumor tables, encounter charts

4. **AICriticAgent** — Final quality check, identifies gaps, outputs quality score (1-10)

**Important:** Agents use `force=True` to bypass the `ollama_busy` check since they're called *during* compilation.

### Skill Injection

Skills are auto-selected based on mission type. **module-quality is ALWAYS first** to set quality standards:

```python
MISSION_TYPE_SKILLS = {
    "standard": ["module-quality", "cw-mission-gen", "tower-bot"],
    "dungeon-delve": ["module-quality", "cw-mission-gen", "dnd5e-srd", "tower-bot"],
    "investigation": ["module-quality", "cw-mission-gen", "tower-bot"],
    "combat": ["module-quality", "cw-mission-gen", "dnd5e-srd"],
    "social": ["module-quality", "cw-mission-gen", "tower-bot"],
    "heist": ["module-quality", "cw-mission-gen", "tower-bot"],
    "rift": ["module-quality", "cw-mission-gen", "tower-bot"],
}
```

Skill context is injected at 4000 chars max into section generation prompts.

### Module Quality Standards

The section generation system prompt enforces:

**Anti-Patterns (NEVER USE):**
- Purple prose ("ethereal glow", "otherworldly pallor")
- Echo chamber (saying the same thing multiple ways)
- Hedging ("seemed to", "appeared to", "might be")
- Adjective avalanche (more than one adjective per noun)
- Generic locations ("a warehouse" → name it specifically)
- Banned phrases: "It is worth noting", "Needless to say", "A sense of"

**Required Patterns:**
- Specific names, numbers, times, locations
- Sensory grounding (sight, sound, smell, texture)
- Read-aloud text in present tense, second person
- Short sentences for action, varied length for description
- NPCs have: Appearance (2-3 details), Voice, Knows, Wants
- Encounters have: Setup, Terrain, Morale, Loot

## Compilation Flow

1. `mark_busy()` — Prevent other systems from using Ollama
2. Load skills based on mission type (module-quality first)
3. Load campaign context (NPCs, factions, news)
4. Generate sections: overview → act_1 → act_2 → act_3 → rewards
5. **Agent pass 0: ProAuthor** — Narrative transformation (with `force=True`) ← NEW
6. Agent pass 1: DNDExpert — Mechanics enhancement + creature appendix (with `force=True`)
7. Agent pass 2: DNDVeteran — Narrative enhancement + location appendix (with `force=True`)
8. Agent pass 3: AICritic — Quality check (with `force=True`)
9. Build .docx via `docx_builder.build_docx()`
10. Generate VTT maps for locations (if location_names available)
11. Post to Discord channel 1484147249637359769
12. Save JSON to `generated_modules/completed/`
13. `mark_available()`

## Directory Structure

```
generated_modules/
├── pending/     # Stage 1 output (mission JSONs waiting for compilation)
├── completed/   # Compiled mission JSONs (with compilation metadata)
├── missions/    # Final .docx files
└── raw/         # Raw markdown outputs (legacy)
```

## Output Channels

- Module .docx: Channel `1484147249637359769` (MODULE_OUTPUT_CHANNEL_ID)
- VTT Maps: Channel `MAPS_CHANNEL_ID` (falls back to MODULE_OUTPUT_CHANNEL_ID)
- Fallback: DM to `DM_USER_ID`

## Quality Metadata

Each compiled module includes metadata:

```json
{
  "compilation": {
    "compiled_at": "2026-04-03T...",
    "player_name": "Adventurer Name",
    "quality_score": 8,
    "agents_used": ["ProAuthor", "DNDExpert", "DNDVeteran", "AICritic"],
    "skills_used": ["module-quality", "cw-mission-gen", "tower-bot"],
    "location_names": ["Cobbleway Market", "Consortium Warehouse #3"]
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
| `src/mission_builder/maps.py` | VTT battlemap generation via A1111 |
| `src/agents/base.py` | BaseAgent with `force` parameter |
| `src/agents/learning_agents.py` | ProAuthor, DNDExpert, DNDVeteran, AICritic agents |
| `skills/module-quality/SKILL.md` | Quality patterns skill (injected first) |
| `skills/cw-mission-gen/SKILL.md` | Mission content generation patterns |
| `skills/cw-prose-writing/SKILL.md` | Prose anti-patterns (referenced by ProAuthor) |

## Troubleshooting

**Agents returning empty content?**
- Check that `force=True` is passed to `agent.complete()`
- Agents check `ollama_busy` flag; without `force=True` they skip during compilation

**DOCX build fails?**
- Verify Node.js is installed
- Check `scripts/build_module_docx.js` exists
- Review `logs/bot_stderr.log`

**Purple prose still appearing?**
- ProAuthorAgent should run FIRST (agent pass 0)
- Check that module-quality skill is being loaded
- Verify skill context injection (4000 chars limit)

**Channel not found?**
- Verify `MODULE_OUTPUT_CHANNEL_ID` (1484147249637359769) is accessible
- Bot falls back to DM if channel unavailable
