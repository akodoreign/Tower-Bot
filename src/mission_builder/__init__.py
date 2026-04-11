"""
mission_builder — Complete D&D mission generation system with JSON + images.

Refactored system (Steps 1-4) providing structured JSON output with full image support.

High-level API exports for easy integration:
    generate_mission()                  - Sync mission generation
    generate_mission_async()            - Async mission generation
    generate_mission_with_images()      - Mission + battle maps (async)
    generate_mission_with_images_sync() - Mission + battle maps (sync)
    generate_complete_mission()         - Full generation to disk
    
For advanced usage:
    MissionJsonBuilder                  - Fluent mission builder
    generate_module_json()              - Raw 4-pass Ollama generation
    generate_dungeon_tiles_for_rooms()  - Tile generation
    stitch_dungeon_map()                - Map composite stitching
    
Schemas and validation:
    MissionModule, ImageAsset, DungeonRoom, NPC, etc.

SKILLS SYSTEM (project-wide):
    Skills are now centralized in src.skills and exposed here for convenience.
    Use from src or from here:
        from src.mission_builder import (
            load_all_skills,
            set_use_skills,
            build_system_prompt_with_skills,
        )
    Or better: use from src directly:
        from src import load_all_skills, set_use_skills

LEGACY MODULES (still available):
- locations.py: Gazetteer integration for real named places
- leads.py: Investigation leads system
- encounters.py: Combat design and stat blocks
- npcs.py: NPC generation and dialogue
"""

from __future__ import annotations

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

# Skills system — re-exported for convenience
from src.skills import (
    load_all_skills,
    set_use_skills,
    get_skill_for_task,
    build_system_prompt_with_skills,
    list_available_skills,
    get_skill_content,
    enhance_generation_with_skills,
)

from .locations import (
    load_gazetteer,
    build_location_context,
    find_location_for_mission,
    get_establishments_for_leads,
    format_lead_locations,
)
from .leads import (
    generate_investigation_leads,
    format_leads_for_prompt,
)
from .encounters import (
    get_cr,
    get_max_pc_level,
    get_encounter_budget,
    format_encounter_guidelines,
    build_encounter_prompt_block,
)
from .npcs import (
    get_relevant_npcs,
    format_npc_block,
    build_npc_prompt_block,
    format_quest_giver_guidance,
)
from .rewards import (
    format_rewards_block,
    format_consequences_prompt,
    build_loot_table,
)
from .docx_builder import (
    build_docx,
    format_module_for_docx,
    validate_module_data,
    get_output_dir,
)
from .maps import (
    extract_map_scenes,
    generate_vtt_map,
    generate_module_maps,
    post_maps_to_channel,
)
from .schemas import (
    validate_mission_module,
    MissionModule,
)
from .mission_json_builder import (
    MissionJsonBuilder,
    create_mission_module,
)

# json_generator is imported on-demand to avoid circular imports

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "campaign_docs"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "generated_modules"

CR_TO_LEVEL = {i: i for i in range(1, 21)}

# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> list | dict:
    if not path.exists():
        return [] if path.suffix == ".json" else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _load_text(path: Path, max_chars: int = 8000) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text[:max_chars]
    except Exception:
        return ""


def gather_context(mission: dict) -> dict:
    """Pull all relevant campaign context for module generation."""
    faction = mission.get("faction", "")
    tier = mission.get("tier", "standard")
    title = mission.get("title", "")
    body = mission.get("body", "")
    personal_for = mission.get("personal_for", "")
    mission_type = mission.get("type", tier)

    # Get relevant NPCs
    relevant_npcs = get_relevant_npcs(faction)
    npc_block = format_npc_block(relevant_npcs)

    # News memory for plot hooks — from MySQL
    news = ""
    try:
        from src.db_api import raw_query as _rq_news
        _rows = _rq_news(
            "SELECT facts FROM news_memory ORDER BY id DESC LIMIT 10"
        ) or []
        news = "\n".join(r.get("facts") or "" for r in _rows if r.get("facts"))[:6000]
    except Exception:
        pass
    if not news:
        news = _load_text(DOCS_DIR / "news_memory.txt", max_chars=6000)

    # Faction reputation — from MySQL
    faction_rep = ""
    try:
        from src.db_api import get_all_faction_reputations as _get_rep
        for r in (_get_rep() or []):
            if faction.lower() in r["faction_name"].lower():
                faction_rep = f"{r['faction_name']}: tier={r['tier']}, points={r['reputation_score']}"
                break
    except Exception:
        pass  # faction_reputation.json file fallback removed — DB is authoritative

    # Character info (if personal mission) — from MySQL player_characters
    char_info = ""
    if personal_for:
        try:
            from src.db_api import get_character_memory_text as _gcmt
            chars_text = (_gcmt() or "")[:3000]
        except Exception:
            chars_text = _load_text(DOCS_DIR / "character_memory.txt", max_chars=3000)
        blocks = chars_text.split("---CHARACTER---")
        for block in blocks:
            if personal_for.lower() in block.lower():
                char_info = block.strip()
                break

    # Active rift state — from MySQL
    rift_context = ""
    try:
        from src.db_api import get_rift_state as _get_rift
        rift_state = _get_rift()
        if rift_state and rift_state.get("active"):
            effects = rift_state.get("effects_json") or {}
            if isinstance(effects, str):
                import json as _j
                effects = _j.loads(effects)
            rifts = effects.get("rifts", []) if isinstance(effects, dict) else []
            active_rifts = [r for r in rifts if not r.get("resolved")]
            if active_rifts:
                rift_context = "Active Rifts: " + "; ".join(
                    f"{r.get('location', '?')} (stage: {r.get('stage', '?')})"
                    for r in active_rifts
                )
    except Exception:
        # fallback to file
        rifts = _load_json(DOCS_DIR / "rift_state.json")
        active_rifts = [r for r in rifts if not r.get("resolved")]
        if active_rifts:
            rift_context = "Active Rifts: " + "; ".join(
                f"{r['location']} (stage: {r['stage']})" for r in active_rifts
            )

    cr = get_cr(tier)
    max_pc_level = get_max_pc_level()

    # NEW: Get location context from gazetteer
    primary_location, location_info = find_location_for_mission(
        faction=faction,
        tier=tier,
    )
    location_context = build_location_context(primary_location, include_underground=True)

    # NEW: Generate investigation leads
    leads = generate_investigation_leads(
        faction=faction,
        tier=tier,
        mission_type=mission_type,
        count=3,
    )
    leads_prompt = format_leads_for_prompt(leads, cr)

    # Get establishments for leads
    establishments = get_establishments_for_leads(faction=faction, count=4)
    establishments_context = format_lead_locations(establishments)

    return {
        "mission": mission,
        "faction": faction,
        "tier": tier,
        "mission_type": mission_type,
        "cr": cr,
        "max_pc_level": max_pc_level if max_pc_level > 0 else cr,
        "title": title,
        "body": body,
        "personal_for": personal_for,
        "char_info": char_info,
        "npc_block": npc_block,
        "relevant_npcs": relevant_npcs,
        "news_memory": news,
        "faction_rep": faction_rep,
        "rift_context": rift_context,
        # NEW context
        "primary_location": primary_location,
        "location_context": location_context,
        "leads": leads,
        "leads_prompt": leads_prompt,
        "establishments_context": establishments_context,
    }


# ---------------------------------------------------------------------------
# Ollama generation helpers
# ---------------------------------------------------------------------------

async def _ollama_generate(prompt: str, system: str = "", timeout: float = 300.0) -> str:
    """Call Ollama and return the text response. Queued via ollama_queue FIFO lock."""
    from src.ollama_queue import call_ollama, OllamaBusyError

    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": messages,
                "stream": False,
            },
            timeout=timeout,
            caller="mission_builder",
        )

        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()

        # Strip common preamble
        lines = text.splitlines()
        skip = ("sure", "here's", "here is", "certainly", "of course", "below is", "absolutely")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        return "\n".join(lines).strip()
    except Exception as e:
        logger.error(f"Ollama generation error: {e}")
        return ""


def _post_process_module_text(text: str, forbidden_names: list = None) -> str:
    """
    Post-process generated module text to fix common issues:
    1. Strip/convert READ ALOUD blocks to Scene Description
    2. Remove placeholder text
    3. Remove forbidden names (player Discord names used as NPCs)
    """
    if not text:
        return text
    
    forbidden_names = forbidden_names or []
    
    # Convert READ ALOUD headers to Scene Description
    # Handles: > ***READ ALOUD:***  **READ ALOUD:**  ***READ ALOUD***  etc.
    read_aloud_pattern = r'[>\s]*\*{2,3}\s*[^\w]*READ\s*ALOUD:?\s*[^\w]*\*{2,3}'
    text = re.sub(read_aloud_pattern, '**Scene Description:**', text, flags=re.IGNORECASE)
    
    # Remove standalone READ ALOUD markers on their own line
    text = re.sub(r'^\s*[^\w]*READ\s*ALOUD:?\s*$', '', text, flags=re.IGNORECASE | re.MULTILINE)
    
    # Replace placeholder text
    text = text.replace('Read-aloud for this location.', '[Describe the atmosphere and key features of this location]')
    text = text.replace('Read-aloud for this location', '[Describe the atmosphere and key features of this location]')
    
    # Remove "No specific location or read-aloud provided" placeholders
    text = re.sub(r'No specific (?:location|read-aloud)(?: or read-aloud)? provided\.?', '', text, flags=re.IGNORECASE)
    
    # Replace forbidden names with generic placeholders
    for name in forbidden_names:
        if name and len(name) > 2:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(name) + r'\b'
            text = re.sub(pattern, '[FACTION_LEADER]', text, flags=re.IGNORECASE)
    
    # Log warning if READ ALOUD still present
    if 'READ ALOUD' in text.upper():
        logger.warning("Post-processing: READ ALOUD still present after cleanup")
    
    return text


# ---------------------------------------------------------------------------
# System prompt — UPDATED: No Read Aloud, emphasize investigation leads
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert D&D 5e 2024 module designer creating content for the Tower of Last Chance campaign.
The setting is the Undercity — a sealed underground city under a Dome, with factions, Rifts, and dark urban fantasy themes.
All content must be D&D 5e 2024 (5.5e) compatible.

CRITICAL FORBIDDEN PATTERNS — AUTOMATIC FAILURE IF YOU USE THESE:

- NEVER write "Read Aloud", "READ ALOUD", or any boxed text for the DM to read verbatim
- NEVER use the player's name (the person who claimed the mission) as an NPC name
- NEVER use the same NPC name in narrative text with a different name in the stat block
- NEVER write placeholder text like "Read-aloud for this location."
- NEVER put DM guidance, mechanics, or tactical notes inside "READ ALOUD" blocks

If you write "READ ALOUD" anywhere in your output, you have FAILED the task.

WHAT TO WRITE INSTEAD:

Use these section types:

**Scene Description** (2-3 sentences): Atmospheric notes the DM paraphrases. NOT read verbatim.
**NPC Appearance**: Physical description the DM uses to describe the NPC.
**DM Note**: Mechanical info, DCs, hidden info, tactical guidance — DM-only content.
**Dialogue**: Actual NPC speech in quotes that the DM can voice.

INVESTIGATION LEADS (the core structure):
- Each lead gives players a SPECIFIC PLACE to go AND a REASON to go there
- Include: Location -> Contact NPC -> What they know -> WHY go there -> Approach options
- Always provide multiple valid approaches (social, stealth, direct, investigation)
- Skill checks with DCs for each approach

OTHER RULES:
- Every NPC name MUST be identical between narrative text and stat block
- Maximum 5-7 scenes for a 2-hour session
- Every creature the party fights MUST have a complete stat block inline
- Keep plots simple: One Goal + One Complication + Climax
- Maximum 3-4 named NPCs. Each must serve a mechanical purpose
- Every combat encounter MUST include battlefield description with cover, terrain, hazards
- Never make the Tower of Last Chance the dungeon. It is the party's home base
- Do NOT give quest-givers monologues. 2-3 dialogue lines, then let players ask questions
- Include at least one non-combat resolution option for the climax

Your modules should provide approximately 2 hours of real-time gameplay.
Write for the DM — be specific, actionable, and include DC values, skill checks, and tactical notes.
Output ONLY the requested content. No meta-commentary."""


# ---------------------------------------------------------------------------
# Module section generators — UPDATED prompts
# ---------------------------------------------------------------------------

async def _gen_overview(ctx: dict) -> str:
    """Generate the module overview / DM summary."""
    prompt = f"""Create a DM-facing module overview for this D&D 5e 2024 mission.

MISSION: {ctx['title']}
FACTION: {ctx['faction']}
TIER: {ctx['tier']} (Challenge Rating: {ctx['cr']})
PARTY INFO: Highest PC level is {ctx['max_pc_level']}. Design for a party of 4.
MISSION DETAILS: {ctx['body']}

PRIMARY LOCATION:
{ctx['location_context']}

RECENT NEWS EVENTS (use 1-2 as plot hooks):
{ctx['news_memory'][:2500]}

RELEVANT NPCs:
{ctx['npc_block']}

{f"PERSONAL FOR: {ctx['personal_for']}" if ctx['personal_for'] else ""}
{ctx['rift_context']}

Write the following sections (use markdown headers):

## Module Overview
A 3-4 sentence summary: what this module is about, the real stakes, and the hidden complication.

## Background
What's really going on behind the scenes — faction politics, NPC motivations, the truth players don't know. 4-6 sentences.

## Adventure Hook
How players get involved. Reference the mission board and contact NPC. 2-3 sentences.

## Key NPCs
For each NPC (3-4 total):
- **Name** (Species, Faction, Role)
- **Motivation**: What they want
- **Secret**: What they're hiding
- **Personality**: 2-3 descriptors
Include one from the mission faction and one antagonist.

## Estimated Runtime
~2 hours (Chapter 1: ~15 min, Chapter 2: ~30 min, Chapter 3: ~75 min)

Output ONLY the sections above."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=180.0)


async def _gen_acts_1_2(ctx: dict, overview: str) -> str:
    """Generate Acts 1-2: Briefing and Investigation — WITH INVESTIGATION LEADS."""
    
    enc_guidelines = format_encounter_guidelines(ctx['cr'], ctx['tier'])
    quest_giver = format_quest_giver_guidance(ctx['faction'])
    
    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {ctx['cr']} | Tier: {ctx['tier']} | Faction: {ctx['faction']}

STORY OUTLINE (already written):
{overview[:2000]}

AVAILABLE LOCATIONS:
{ctx['establishments_context']}

{enc_guidelines}

{quest_giver}

Write Chapters 1 and 2 of this narrative module:

## Chapter 1: The Hook (~15 minutes)

The opening scene where the quest-giver meets the party.

**Setting** (2-3 sentences for DM to paraphrase — not a read-aloud box):
Describe the meeting location and the NPC's demeanor.

**NPC Dialogue**: Key information as actual speech (2-3 lines, then pause for questions)

**What the NPC holds back**: Info they won't share unless the party presses
- Insight DC {ctx['cr']+8}: Notice they're withholding something
- Persuasion DC {ctx['cr']+10}: Get them to reveal [specific info]

**Where to start**: The NPC points the party toward 2-3 specific leads:
- WHERE to go (use real location names)
- WHO to talk to
- WHY it matters

## Chapter 2: The Investigation (~30 minutes)

Three scenes the party can pursue in any order.

{ctx['leads_prompt']}

For EACH scene, write:

### Scene [N]: [Location Name]

**Why go here**: [The specific reason this location matters]

**Setting** (2-3 sentences for DM)

**The Contact**: [NPC Name]
- Who they are and why they matter
- What they want (their motivation for helping or not)
- What they know

**How to approach**:
- **Social** (Persuasion DC {ctx['cr']+8}): [approach and outcome]
- **Intimidation** (DC {ctx['cr']+10}): [approach and outcome]
- **Stealth/Investigation** (DC {ctx['cr']+9}): [alternative approach]
- **Bribe**: [cost and result]

**What the party learns**: The clue or information gained

**What goes wrong**: The complication in this scene

Include at least one scene that can be resolved through roleplay OR combat.

Output ONLY Chapters 1 and 2."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=200.0)


async def _gen_acts_3_4(ctx: dict, overview: str) -> str:
    """Generate Acts 3-4: Complication and Confrontation."""
    
    loc_name, loc_info = find_location_for_mission(
        faction=ctx['faction'],
        tier=ctx['tier'],
        location_type="underground" if ctx['tier'] in ["dungeon", "rift"] else None,
    )
    
    encounter_block = build_encounter_prompt_block(
        cr=ctx['cr'],
        tier=ctx['tier'],
        location_type="underground" if ctx['tier'] in ["dungeon", "rift"] else "urban",
        encounter_difficulty="hard",
    )
    
    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {ctx['cr']} | Tier: {ctx['tier']} | Faction: {ctx['faction']}

STORY OUTLINE:
{overview[:1500]}

CONFRONTATION LOCATION: {loc_name}

{encounter_block}

Write Chapter 3 of this narrative module — the turn and the climax:

## Chapter 3, Part A: The Turn (~15 minutes)

The moment the story shifts — what the party thought they knew is wrong.

**The Reveal**: What they discover (be specific — a name, a body, a document, a betrayal)

**Setting** (2-3 sentences for DM)

**Faction angle**: How this ties to Undercity faction tensions

**The choice**: Two paths forward
- Path A: [choice and consequence]
- Path B: [choice and consequence]

**Why they can't leave**: What forces their hand right now

## Chapter 3, Part B: The Confrontation (~45 minutes)

The story's climax — combat-focused but with a non-combat path.

### Location: {loc_name}

**Setting** (3-4 sentences describing the environment)

**Terrain** (at least 3 features):
- [Feature 1]: [cover type, tactical use]
- [Feature 2]: [hazard or advantage]
- [Feature 3]: [interactive element]

**Environmental Hazard**:
- [Hazard]: [trigger, effect, DC if applicable]

### Who's Here

Provide 2-3 enemy types with FULL 5e 2024 stat blocks.

For EACH enemy type, provide the complete stat block:
- Name, AC, HP (with hit dice), Speed
- Ability Scores (all 6)
- Saving Throws, Skills
- Damage Resistances/Immunities
- Senses, Languages, CR, XP
- Traits
- Actions (full descriptions with attack bonus, damage, save DCs)
- Bonus Actions/Reactions if any
- Legendary Actions for boss (CR 8+)

### How They Fight
- Opening move and target priority
- When they retreat or surrender
- If the party is losing (escape route, mercy offer)
- If the party is winning easily (reinforcements, second phase)

### How to End This Without a Fight
- Skill check (DC {ctx['cr']+12}): [what the party does, what changes]
- Roleplay path: [what could convince the antagonist]
- Environmental path: [creative use of the location]

Output ONLY Chapter 3."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=240.0)


async def _gen_act_5_rewards(ctx: dict, overview: str) -> str:
    """Generate Act 5: Resolution, rewards, and consequences."""
    
    # Get PC level for loot scaling
    pc_level = get_max_pc_level()
    
    rewards_block = format_rewards_block(
        tier=ctx['tier'],
        cr=ctx['cr'],
        faction=ctx['faction'],
        mission_reward_text=ctx['mission'].get('reward', ''),
        pc_level=pc_level,
    )
    
    loot_table = build_loot_table(ctx['cr'], ctx['tier'], pc_level=pc_level)
    
    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {ctx['cr']} | Tier: {ctx['tier']} | Faction: {ctx['faction']}

STORY OUTLINE:
{overview[:1500]}

{rewards_block}

Write the aftermath and rewards — this is how the story ends:

## Aftermath

### If the Party Succeeds
- What concretely changes in the Undercity (faction balance, NPC fate, location status)
- How {ctx['faction']} responds (specific reward or reaction)
- **Closing moment** (2-3 sentences for DM to describe)

### If the Party Fails
- What the antagonist achieves
- Consequences for {ctx['faction']} and the Undercity
- **Closing moment** (2-3 sentences)

### Partial Success
One realistic middle-ground for creative or mixed results.

## Rewards

### Faction Standing
- Success: +5 {ctx['faction']}, +2 allied factions
- Partial: +2 {ctx['faction']}
- Failure: -3 {ctx['faction']}, +2 opposing factions

{loot_table}

### What Comes Next
One follow-up hook per outcome — tied directly to how this story ended.

Output ONLY the Aftermath and Rewards sections."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=180.0)


# ---------------------------------------------------------------------------
# Standard mission: story-first pipeline
# ---------------------------------------------------------------------------

def _story_structure_for_type(mission_type: str) -> str:
    """Return type-specific Chapter 1/2/3 beat guidance for the story outline prompt."""
    mt = (mission_type or "standard").lower()

    structures = {
        "dungeon": """\
TYPE: Dungeon Delve — the party is hired to clear or explore a specific dungeon.
Chapter 1: The party receives the contract. A faction rep, survivor, or scholar briefs them on the dungeon — its entrance, what's inside, and what must be retrieved or eliminated.
Chapter 2: The party enters and progresses through distinct areas. Each area has different threats — encounters, traps, environmental hazards, and one puzzle or branching path that complicates the route.
Chapter 3: The deepest chamber — the boss room. The main threat is here. A secondary twist complicates extraction (the target is guarded behind a puzzle, the dungeon is collapsing, a trapped NPC needs saving).""",

        "escort": """\
TYPE: Escort Mission — the party must protect a specific target and get them safely to a destination.
Chapter 1: The party meets the target (a courier, VIP, witness, or defector). The route is explained. Faction agents are already watching — the first threat makes itself known before they leave.
Chapter 2: The journey. Two ambush points — one anticipated from intel, one a surprise. The target is not what they seem: carrying something dangerous, lying about identity, or attracting a second threat.
Chapter 3: The final gauntlet — a blockade, locked safe house, or faction checkpoint to bluff through. The primary threat makes their decisive move. The party must deliver the target while dealing with whatever the target's secret brought down on them.""",

        "rift": """\
TYPE: Rift Emergency — a supernatural Rift is destabilizing the Undercity.
Chapter 1: A rift disturbance is reported — strange phenomena, panicked civilians, scouts who didn't return. The party is tasked with investigating and containing it before it spreads.
Chapter 2: The party traces the rift's source. The corruption is worse than reported — creatures emerging, warped environment, and a faction angle (someone opened the rift intentionally or is harvesting its energy).
Chapter 3: The rift's anchor point — a ritual site, corrupted creature, or active caster. Closing the rift requires a specific action (destroy the anchor, complete a counter-ritual, kill the caster). The antagonist fights to keep it open.""",

        "patrol": """\
TYPE: Patrol Assignment — a routine patrol that goes badly wrong.
Chapter 1: Standard patrol briefing. The route is clear and objective simple (watch for faction activity, check on a contact). Something small and wrong is noticed immediately — a body, a missing checkpoint guard, unusual foot traffic.
Chapter 2: The wrong thing is a symptom of something bigger. The patrol encounters escalating threats — first a skirmish, then evidence of a coordinated operation. The party must decide: report back or press further.
Chapter 3: The source of the problem — an ambush site, a faction operation in progress, a threat that can't wait for backup. The party must neutralize it with what they have.""",

        "combat": """\
TYPE: Combat Contract — direct armed conflict, no subtlety required.
Chapter 1: Mission briefing with full tactical intel. The party knows the target, location, and opposition strength. A preliminary skirmish tests their capabilities and reveals one thing the intel got wrong.
Chapter 2: The approach — two routes with different hazards. Skirmishes with advance forces. One opportunity for a significant tactical advantage if the party thinks creatively.
Chapter 3: The main engagement. The primary target is here with full support. The battle has distinct phases — the opening line, a mid-fight complication (reinforcements, a hostage, environmental collapse), and a final resolution.""",

        "battle": """\
TYPE: Combat Contract — direct armed conflict, no subtlety required.
Chapter 1: Mission briefing with full tactical intel. The party knows the target, location, and opposition strength. A preliminary skirmish tests their capabilities and reveals one thing the intel got wrong.
Chapter 2: The approach — two routes with different hazards. Skirmishes with advance forces. One opportunity for a significant tactical advantage if the party thinks creatively.
Chapter 3: The main engagement. The primary target is here with full support. The battle has distinct phases — the opening line, a mid-fight complication (reinforcements, a hostage, environmental collapse), and a final resolution.""",

        "social": """\
TYPE: Social/Political Mission — negotiation, diplomacy, or intrigue is the primary tool.
Chapter 1: Faction representatives are introduced. The party is positioned as intermediaries, investigators, or power brokers. The surface agenda is stated — but each faction wants something different from what they're saying.
Chapter 2: Negotiation scenes across multiple locations. The party gathers leverage, uncovers hidden agendas, and faces a social challenge that can't be solved by talking alone (coercion, a forged document, a faction acting in bad faith).
Chapter 3: The final meeting. The truth about each faction's real agenda is on the table. The party must broker a deal, expose the bad actor, or choose a side — with concrete Undercity consequences either way.""",

        "political": """\
TYPE: Social/Political Mission — negotiation, diplomacy, or intrigue is the primary tool.
Chapter 1: Faction representatives are introduced. The party is positioned as intermediaries, investigators, or power brokers. The surface agenda is stated — but each faction wants something different from what they're saying.
Chapter 2: Negotiation scenes across multiple locations. The party gathers leverage, uncovers hidden agendas, and faces a social challenge that can't be solved by talking alone (coercion, a forged document, a faction acting in bad faith).
Chapter 3: The final meeting. The truth about each faction's real agenda is on the table. The party must broker a deal, expose the bad actor, or choose a side — with concrete Undercity consequences either way.""",

        "heist": """\
TYPE: Heist — the party must infiltrate a location and acquire or destroy a specific target.
Chapter 1: The job is explained. Target location, the mark, and the window of opportunity are detailed. The party cases the location or receives intel — they learn the layout, guards, and one major complication that wasn't in the briefing.
Chapter 2: The infiltration. Two entry routes with different risk profiles. Inside, complications compound: a guard on alert, the target moved, a third party here for the same prize. The party must improvise.
Chapter 3: The extraction. They have what they came for — now they must get out. The alarm is raised. A final obstacle stands between them and the exit, and the antagonist makes their move.""",

        "bounty": """\
TYPE: Bounty Hunt — track down and bring in (or eliminate) a specific target.
Chapter 1: The contract. The target is described — last known location, known associates, reason for the bounty. A contact with partial information sets the party on the trail.
Chapter 2: The hunt. The target knows someone is looking. They've set traps, used proxies, and are moving between safe houses. Two encounters — one with the target's associates, one with a rival faction who also wants the target.
Chapter 3: The target is cornered. They make their stand — or try to negotiate. The party must choose: bring them in as contracted, let them go, or take a deal that changes the original mission parameters.""",

        "hunt": """\
TYPE: Bounty Hunt — track down and bring in (or eliminate) a specific target.
Chapter 1: The contract. The target is described — last known location, known associates, reason for the bounty. A contact with partial information sets the party on the trail.
Chapter 2: The hunt. The target knows someone is looking. They've set traps, used proxies, and are moving between safe houses. Two encounters — one with the target's associates, one with a rival faction who also wants the target.
Chapter 3: The target is cornered. They make their stand — or try to negotiate. The party must choose: bring them in as contracted, let them go, or take a deal that changes the original mission parameters.""",

        "rescue": """\
TYPE: Rescue Mission — someone is held against their will and must be extracted.
Chapter 1: The party learns someone is missing — taken by a faction, a monster, or a criminal element. Who took them and why is the first mystery. A contact knows where to start looking but not where the captive is held.
Chapter 2: The search. Two locations must be checked — one a dead end, one revealing the actual holding site and how it's defended. The captive's situation complicates things (injured, knows something dangerous, captor has leverage over them).
Chapter 3: The extraction. The holding site is defended. The party must get in, get the captive, and get out — with a final confrontation against whoever ordered the kidnapping.""",

        "investigation": """\
TYPE: Investigation/Mystery — the party must solve a crime or uncover a hidden truth.
Chapter 1: The crime or mystery is presented — a body, a theft, a disappearance, a threat. The party is hired to find the truth. The crime scene yields initial clues and introduces 2-3 suspects, each with motive and opportunity.
Chapter 2: The clue trail. Following leads takes the party across the Undercity. Each location reveals new information — and one lead is a red herring deliberately planted to misdirect. The true culprit begins to feel the investigation closing in and makes a move.
Chapter 3: The reveal. The party confronts the culprit with the evidence they've gathered. The confrontation can be an arrest, a fight, a confession under pressure, or a twist that recontextualizes everything. The truth has Undercity-wide consequences.""",
    }

    return structures.get(mt, """\
TYPE: Standard Urban Mission — the party takes on a contract in the Undercity.
Chapter 1: The quest-giver presents the mission. The surface goal is clear, the hidden complication is not. The party gets a starting lead and a reason to move quickly.
Chapter 2: Investigation uncovers the real situation — a faction angle, a hidden actor, a complication the quest-giver didn't mention or didn't know. The antagonist becomes apparent.
Chapter 3: The confrontation with the real threat. The party must resolve the hidden problem, not just the surface mission. The outcome affects the Undercity's faction balance.""")


async def _gen_story_outline(ctx: dict) -> str:
    """
    Pass 0 of the standard pipeline: generate a 3-chapter story outline.

    This is a compact narrative treatment (~400-600 words) — not acts.
    Subsequent agents expand it into a full module.
    """
    type_structure = _story_structure_for_type(ctx.get("mission_type", "standard"))

    prompt = f"""Write a 3-chapter story outline for a D&D mission set in the Undercity.

MISSION: {ctx['title']}
FACTION: {ctx['faction']}
TIER: {ctx['tier']} (Challenge Rating: {ctx['cr']})
MISSION DETAILS: {ctx['body']}

{type_structure}

PRIMARY LOCATION: {ctx['primary_location']}

RELEVANT NPCs (choose 2-3 to feature):
{ctx['npc_block']}

RECENT EVENTS (use ONE as a background plot hook):
{ctx['news_memory'][:1200]}

Write the following sections:

## Chapter 1: The Hook
- **Opening scene**: Where does the story begin? What do the players see and hear the moment they arrive?
- **Quest-giver**: Who approaches them, where, and how? What do they ask for — and what are they NOT saying?
- **The surface goal**: What the party is hired to do (1-2 sentences)
- **First lead**: One specific place or person to start with

## Chapter 2: The Complication
- **What investigation uncovers**: The real situation, different from what they were told
- **Hidden angle**: Which other faction is involved, and why do they want the party to succeed or fail?
- **The antagonist**: Who is actually behind this? What do they want and why?
- **The turning point**: The specific moment when everything shifts (a betrayal, a discovery, a body)

## Chapter 3: The Confrontation
- **The location**: Where the climax happens — a specific named place in the Undercity
- **The stakes**: What happens to the Undercity if the party fails?
- **The final face-off**: Who or what do they face? Is it just combat, or is there a choice?
- **Resolution paths**: One through force, one through guile or negotiation
- **Consequence**: One thing that changes in the Undercity no matter the outcome

## Key NPCs
List exactly 3 NPCs (may include existing ones from the roster above):
- **Name** | Role | What they want | What they're hiding

## Key Locations
List exactly 2-3 named locations from the Undercity (use real district/establishment names):
- **Name** | Why it matters in the story

Keep this outline tight and specific. No fluff. Each beat should be a concrete event, not a vague direction.
Output ONLY the sections above."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=180.0)


async def _generate_story_pipeline(mission: dict, player_name: str = "") -> Optional[Path]:
    """
    Universal story-first pipeline: story outline → agent expansion → DOCX.

    Works for all mission types. Type-aware beats are injected via _story_structure_for_type().

    Flow:
      1. _gen_story_outline()     → 3-chapter type-specific story treatment
      2. ProAuthorAgent           → Chapters 1-2 as playable scenes
      3. ProAuthorAgent           → Chapter 3 as climax scenes
      4. DNDExpertAgent           → Encounter mechanics + full stat blocks
      5. DNDVeteranAgent          → Rewards + complication table
    """
    from src.agents.learning_agents import ProAuthorAgent, DNDExpertAgent, DNDVeteranAgent

    title = mission.get("title", "Unknown Mission")
    tier = mission.get("tier", "standard")
    faction = mission.get("faction", "Unknown")
    forbidden_names = [player_name] if player_name else []

    mission_type = mission.get("type", tier)
    logger.info(f"[Story Pipeline] type={mission_type!r} — generating outline for: {title}")
    ctx = gather_context(mission)

    # ── Pass 1: Story outline ──────────────────────────────────────────────
    story_outline = await _gen_story_outline(ctx)
    if not story_outline:
        logger.error("[Story Pipeline] Story outline generation failed")
        return None
    story_outline = _post_process_module_text(story_outline, forbidden_names)
    logger.info(f"[Story Pipeline] Story outline: {len(story_outline)} chars")

    mission_meta = {
        "metadata": {
            "title": title, "faction": faction, "tier": tier,
            "mission_type": ctx["mission_type"], "cr": ctx["cr"],
        }
    }
    campaign_ctx = {
        "npcs": ctx["relevant_npcs"],
        "faction": faction,
        "tier": tier,
        "news": ctx["news_memory"][:800],
    }

    # ── Pass 2: ProAuthorAgent — Chapters 1-2 (overview + briefing + investigation) ──
    logger.info("[Story Pipeline] ProAuthorAgent → Chapters 1-2...")
    pro_author = ProAuthorAgent()
    acts_1_2 = ""
    try:
        ch12_prompt = f"""Expand Chapters 1 and 2 of this story outline into playable DM content.

STORY OUTLINE:
{story_outline}

MISSION: {title} | FACTION: {faction} | TIER: {tier} | CR: {ctx['cr']}

Write two chapters of a narrative module:

## Chapter 1: The Hook (~15 min)
The opening scene where the quest-giver meets the party.
- **Scene** (2-3 sentences for DM to paraphrase — no read-aloud boxes)
- **NPC Dialogue**: 2-3 lines of actual speech, then the NPC waits for questions
- **What the NPC holds back**: Something they won't say unless pressed (Insight DC {ctx['cr']+8} to notice)
- **Where to start**: 2 specific places or people the NPC points the party toward

## Chapter 2: The Investigation (~30 min)
Three scenes the party can pursue in any order — each one a piece of the puzzle.

{ctx['leads_prompt']}

For EACH scene write:
### Scene [N]: [Location Name]
**Why go here**: [specific reason tied to the story]
**Setting** (2-3 sentences)
**The Contact**: [name, what they know, why they might help]
**How to approach**:
- Social (Persuasion DC {ctx['cr']+8}): [outcome]
- Stealth/Investigation (DC {ctx['cr']+9}): [outcome]
- Bribe or leverage: [cost and result]
**What the party learns**: [the specific clue or information]
**What goes wrong**: [the complication in this scene]

Keep all mechanical notes. Write atmosphere, not novels.
Output ONLY Chapters 1 and 2."""

        ch12_response = await pro_author.complete(ch12_prompt, force=True)
        if ch12_response.success and ch12_response.content:
            acts_1_2 = _post_process_module_text(ch12_response.content, forbidden_names)
            logger.info(f"[Story Pipeline] Acts 1-2: {len(acts_1_2)} chars")
    except Exception as e:
        logger.warning(f"[Story Pipeline] ProAuthorAgent Ch1-2 failed: {e}")
    finally:
        await pro_author.close()

    if not acts_1_2:
        # Fall back to the standard generator for this section
        acts_1_2 = await _gen_acts_1_2(ctx, story_outline)
        acts_1_2 = _post_process_module_text(acts_1_2, forbidden_names)

    # ── Pass 3: ProAuthorAgent — Chapter 3 (complication + climax) ────────
    logger.info("[Story Pipeline] ProAuthorAgent → Chapter 3 (climax)...")
    pro_author_2 = ProAuthorAgent()
    acts_3_raw = ""
    try:
        loc_name, _ = find_location_for_mission(
            faction=faction, tier=tier,
            location_type="underground" if tier in ("dungeon", "rift") else None,
        )
        enc_block = build_encounter_prompt_block(
            cr=ctx['cr'], tier=tier,
            location_type="underground" if tier in ("dungeon", "rift") else "urban",
            encounter_difficulty="hard",
        )
        ch3_prompt = f"""Expand Chapter 3 of this story outline into the climax of the narrative.

STORY OUTLINE (focus on Chapter 3):
{story_outline}

CONFRONTATION LOCATION: {loc_name}

{enc_block}

Write Chapter 3 as two beats — the turn and the climax:

## Chapter 3, Part A: The Turn (~15 min)
The moment the story shifts — what the party thought they knew is wrong.
- **The Reveal**: What they discover (be specific — a name, a body, a document, a betrayal)
- **Setting** (2-3 sentences)
- **Faction angle**: Which other faction's fingerprints are on this, and why
- **The choice**: Two paths forward, each with a real consequence
- **Why they can't leave**: What forces their hand right now

## Chapter 3, Part B: The Confrontation (~45 min)

### Location: {loc_name}
**Setting** (3-4 sentences — what the party sees when they arrive)
**Terrain** (3 features — cover, hazards, interactive elements)
**Hazard** (1 environmental danger with trigger and DC)

### Who's Here
Describe the antagonist and any allies — what they're doing when the party arrives,
their first move, when they break or surrender. Full stat blocks come in the mechanics pass.

### How to End This Without a Fight
One realistic non-combat path (DC {ctx['cr']+12}) — what the party does and how the antagonist responds.

Output ONLY Chapter 3."""

        ch3_response = await pro_author_2.complete(ch3_prompt, force=True)
        if ch3_response.success and ch3_response.content:
            acts_3_raw = _post_process_module_text(ch3_response.content, forbidden_names)
            logger.info(f"[Story Pipeline] Acts 3-4 narrative: {len(acts_3_raw)} chars")
    except Exception as e:
        logger.warning(f"[Story Pipeline] ProAuthorAgent Ch3 failed: {e}")
    finally:
        await pro_author_2.close()

    if not acts_3_raw:
        acts_3_raw = await _gen_acts_3_4(ctx, story_outline)
        acts_3_raw = _post_process_module_text(acts_3_raw, forbidden_names)

    # ── Pass 4: DNDExpertAgent — full stat blocks + encounter mechanics ───
    logger.info("[Story Pipeline] DNDExpertAgent → stat blocks + mechanics...")
    dnd_expert = DNDExpertAgent()
    encounter_content = ""
    try:
        stats_prompt = f"""Add complete D&D 5e 2024 encounter mechanics for this mission.

STORY OUTLINE (for context on who the enemies are):
{story_outline[:1800]}

MISSION: {title} | FACTION: {faction} | CR: {ctx['cr']} | TIER: {tier}

Write:

## Enemy Stat Blocks
For the main antagonist AND 1-2 supporting enemy types, provide FULL 5e 2024 stat blocks.
Each stat block MUST include every field:
**[NAME]** — [Type, Alignment]
**AC** [value] ([source]) | **HP** [value] ([hit dice]) | **Speed** [speeds]
**STR** [mod] | **DEX** [mod] | **CON** [mod] | **INT** [mod] | **WIS** [mod] | **CHA** [mod]
**Saving Throws** [if any] | **Skills** [if any]
**Damage Resistances/Immunities** [if any] | **Condition Immunities** [if any]
**Senses** [values] | **Languages** [languages] | **CR** [CR] ([XP] XP)
**Proficiency Bonus** +[value]
**TRAITS** [list all passive traits]
**ACTIONS** [list all actions with attack bonus, damage dice, save DCs]
**BONUS ACTIONS** [if any]
**REACTIONS** [if any]
**LEGENDARY ACTIONS** [if CR 8+]
**Tactical Notes**: Opening move / Target priority / Retreat conditions

## Skill Check Reference
All DCs for this mission at CR {ctx['cr']}:
| Skill | DC | What success achieves |
|-------|----|-----------------------|
[fill in all relevant checks from the module]

Output ONLY the stat blocks and skill check table."""

        stats_response = await dnd_expert.complete(stats_prompt, force=True)
        if stats_response.success and stats_response.content:
            encounter_content = stats_response.content
            logger.info(f"[Story Pipeline] Encounter content: {len(encounter_content)} chars")
    except Exception as e:
        logger.warning(f"[Story Pipeline] DNDExpertAgent failed: {e}")
    finally:
        await dnd_expert.close()

    acts_3_4 = acts_3_raw
    if encounter_content:
        acts_3_4 = f"{acts_3_raw}\n\n---\n\n{encounter_content}"

    # ── Pass 5: DNDVeteranAgent — investigation leads + rewards + complications ──
    logger.info("[Story Pipeline] DNDVeteranAgent → rewards + complication table...")
    dnd_veteran = DNDVeteranAgent()
    act_5_rewards = ""
    try:
        pc_level = get_max_pc_level()
        rewards_block = format_rewards_block(
            tier=tier, cr=ctx['cr'], faction=faction,
            mission_reward_text=mission.get('reward', ''),
            pc_level=pc_level,
        )
        loot_table = build_loot_table(ctx['cr'], tier, pc_level=pc_level)

        veteran_prompt = f"""Write the aftermath and rewards for this story.

STORY OUTLINE:
{story_outline[:1500]}

MISSION: {title} | FACTION: {faction} | TIER: {tier}

{rewards_block}

Write:

## Aftermath

### If the Party Succeeds
- What concretely changes in the Undercity (faction balance, NPC fate, location status)
- How {faction} responds (specific reward or reaction)
- **Closing moment** (2-3 sentences for DM to describe)

### If the Party Fails
- What the antagonist achieves
- Consequences for {faction} and the Undercity
- **Closing moment** (2-3 sentences)

### Partial Success
One realistic middle-ground outcome for creative or mixed results.

## Rewards

{loot_table}

### Faction Standing
- Success: +5 {faction} reputation
- Failure: -3 {faction} reputation
- Any other faction changes tied to this story

### What Comes Next (1 seed per outcome)
One follow-up hook tied directly to how this story ended.

## DM Complication Table (d6)
Roll when things go sideways — all 6 entries must be specific to THIS story:

| d6 | Complication |
|----|--------------|
| 1  | [story-specific complication] |
| 2  | [NPC complication] |
| 3  | [faction complication] |
| 4  | [environmental complication] |
| 5  | [resource or timing complication] |
| 6  | [escalation — raises the stakes] |

Output ONLY the sections above."""

        vet_response = await dnd_veteran.complete(veteran_prompt, force=True)
        if vet_response.success and vet_response.content:
            act_5_rewards = _post_process_module_text(vet_response.content, forbidden_names)
            logger.info(f"[Story Pipeline] Act 5 + rewards: {len(act_5_rewards)} chars")
    except Exception as e:
        logger.warning(f"[Story Pipeline] DNDVeteranAgent failed: {e}")
    finally:
        await dnd_veteran.close()

    if not act_5_rewards:
        act_5_rewards = await _gen_act_5_rewards(ctx, story_outline)
        act_5_rewards = _post_process_module_text(act_5_rewards, forbidden_names)

    # ── Assemble and build DOCX ────────────────────────────────────────────
    # Overview = story outline itself (the 3-chapter treatment + key NPCs)
    overview = story_outline

    module_data = format_module_for_docx(
        title=title,
        overview=overview,
        acts_1_2=acts_1_2,
        acts_3_4=acts_3_4,
        act_5_rewards=act_5_rewards,
        metadata={
            "faction": faction,
            "tier": tier,
            "cr": ctx['cr'],
            "primary_location": ctx['primary_location'],
            "player_name": player_name,
        },
    )
    module_data["player_name"] = player_name
    module_data["max_pc_level"] = ctx['max_pc_level']
    module_data["player_level"] = ctx['max_pc_level'] if ctx['max_pc_level'] > 0 else CR_TO_LEVEL.get(ctx['cr'], ctx['cr'])
    module_data["reward"] = mission.get("reward", "Standard")
    module_data["generated_at"] = datetime.now().isoformat()
    module_data["pipeline"] = "story_pipeline"

    if not validate_module_data(module_data):
        logger.warning("[Story Pipeline] Module validation failed, attempting build anyway")

    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:50]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("[Story Pipeline] Building DOCX...")
    output_path = await build_docx(module_data, filename=f"{safe_title}_{timestamp}")

    if output_path:
        logger.info(f"[Story Pipeline] Module generated: {output_path}")
        # Save sidecar JSON so post_module_to_channel can extract real scene text for maps
        try:
            sidecar_path = output_path.with_name(output_path.stem + "_mapdata.json")
            sidecar_data = {
                "title": title,
                "metadata": module_data.get("metadata", {}),
                "sections": module_data.get("sections", {}),
            }
            sidecar_path.write_text(
                json.dumps(sidecar_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info(f"[Story Pipeline] Sidecar saved: {sidecar_path.name}")
        except Exception as e:
            logger.warning(f"[Story Pipeline] Sidecar save failed (non-fatal): {e}")
    else:
        logger.error("[Story Pipeline] DOCX generation failed")

    return output_path


# ---------------------------------------------------------------------------
# Investigation pipeline (mystery / whodunit)
# ---------------------------------------------------------------------------

async def _generate_investigation_pipeline(mission: dict, player_name: str = "") -> Optional[Path]:
    """
    Mystery-focused pipeline: crime scene → clue trail → reveal scene.

    Flow:
      1. _gen_story_outline()    → investigation-type 3-chapter treatment
      2. ProAuthorAgent          → crime scene, suspects, clue trail (Chapters 1-2)
      3. ProAuthorAgent          → reveal scene + confrontation (Chapter 3)
      4. DNDExpertAgent          → stat blocks
      5. DNDVeteranAgent         → clue trail reference table + red herring callout + aftermath
    """
    from src.agents.learning_agents import ProAuthorAgent, DNDExpertAgent, DNDVeteranAgent

    title = mission.get("title", "Unknown Mission")
    tier = mission.get("tier", "investigation")
    faction = mission.get("faction", "Unknown")
    forbidden_names = [player_name] if player_name else []

    logger.info(f"[Investigation Pipeline] Generating mystery outline for: {title}")
    ctx = gather_context(mission)

    # ── Pass 1: Story outline (investigation type) ─────────────────────────
    story_outline = await _gen_story_outline(ctx)
    if not story_outline:
        logger.error("[Investigation Pipeline] Story outline failed")
        return None
    story_outline = _post_process_module_text(story_outline, forbidden_names)
    logger.info(f"[Investigation Pipeline] Outline: {len(story_outline)} chars")

    # ── Pass 2: ProAuthorAgent — crime scene + suspects + clue trail ───────
    logger.info("[Investigation Pipeline] ProAuthorAgent → crime scene + clue trail...")
    pro_author = ProAuthorAgent()
    acts_1_2 = ""
    try:
        ch12_prompt = f"""Expand Chapters 1 and 2 of this mystery outline into playable DM content.

STORY OUTLINE:
{story_outline}

MISSION: {title} | FACTION: {faction} | TIER: {tier} | CR: {ctx['cr']}

Write two chapters of a mystery module:

## Chapter 1: The Case (~15 min)
The party receives the case — a crime, a disappearance, or a threat with no obvious culprit.
- **The scene** (2-3 sentences for DM to paraphrase — no read-aloud boxes)
- **The client**: Who hired them, what they're asking for, what they're NOT saying (Insight DC {ctx['cr']+8})
- **The crime scene**: 3 specific clues the party can find with Investigation/Perception DC {ctx['cr']+7}
- **The suspects**: Exactly 3 — Name, connection to the victim, and one reason they could have done it

## Chapter 2: The Investigation (~35 min)
Three scenes across the Undercity — one per suspect lead. One of these leads is a RED HERRING.

{ctx['leads_prompt']}

For EACH scene write:
### Scene [N]: [Location Name] — [Suspect or Contact]
**Why go here**: [what the party expects to find]
**Setting** (2-3 sentences)
**The contact or suspect**: [who they are, what they know, why they might lie]
**What the party finds**:
- Social approach (Persuasion DC {ctx['cr']+8}): [what they learn if they succeed]
- Investigation/Deception (DC {ctx['cr']+9}): [what they find if they dig deeper]
- The lie or misdirection: [what this person is hiding, and why]
**What this clue means**: [how it connects to the real culprit — OR label RED HERRING if applicable]

⚠ Mark one scene explicitly as: **[RED HERRING]** — a lead that looks compelling but points away from the truth.

Output ONLY Chapters 1 and 2."""

        ch12_response = await pro_author.complete(ch12_prompt, force=True)
        if ch12_response.success and ch12_response.content:
            acts_1_2 = _post_process_module_text(ch12_response.content, forbidden_names)
            logger.info(f"[Investigation Pipeline] Acts 1-2: {len(acts_1_2)} chars")
    except Exception as e:
        logger.warning(f"[Investigation Pipeline] ProAuthorAgent Ch1-2 failed: {e}")
    finally:
        await pro_author.close()

    if not acts_1_2:
        acts_1_2 = await _gen_acts_1_2(ctx, story_outline)
        acts_1_2 = _post_process_module_text(acts_1_2, forbidden_names)

    # ── Pass 3: ProAuthorAgent — the reveal scene ──────────────────────────
    logger.info("[Investigation Pipeline] ProAuthorAgent → reveal scene + confrontation...")
    pro_author_2 = ProAuthorAgent()
    acts_3_raw = ""
    try:
        loc_name, _ = find_location_for_mission(faction=faction, tier=tier)
        enc_block = build_encounter_prompt_block(
            cr=ctx['cr'], tier=tier,
            location_type="urban",
            encounter_difficulty="hard",
        )
        ch3_prompt = f"""Expand Chapter 3 of this mystery outline into the reveal and confrontation.

STORY OUTLINE (focus on Chapter 3):
{story_outline}

CONFRONTATION LOCATION: {loc_name}

{enc_block}

Write Chapter 3 as the mystery's climax:

## Chapter 3, Part A: The Reveal (~10 min)
The moment all the clues converge and the truth becomes clear.
- **The realization**: How the party puts it together — what specific clue clinches it
- **Setting** (2-3 sentences — where the party is when they figure it out)
- **The culprit's move**: How the antagonist responds to being figured out (flee, attack, try to bargain)
- **The twist** (optional but encouraged): One thing that recontextualizes what the party thought they knew

## Chapter 3, Part B: The Confrontation (~40 min)

### Location: {loc_name}
**Setting** (3-4 sentences — what the space looks like and why it matters to the antagonist)
**Terrain** (3 features — cover, hazards, anything interactable)
**Hazard** (1 environmental danger with trigger and DC)

### The Antagonist
What they're doing when the party arrives. Their first move. When they break.

### Paths to Resolution
- **Force**: Combat path — what happens if the party fights
- **Negotiation**: DC {ctx['cr']+12} — what the culprit wants, what they'll offer, what they won't accept
- **Evidence**: If the party has enough proof, they can force a confession without fighting (3 key clues required)

Output ONLY Chapter 3."""

        ch3_response = await pro_author_2.complete(ch3_prompt, force=True)
        if ch3_response.success and ch3_response.content:
            acts_3_raw = _post_process_module_text(ch3_response.content, forbidden_names)
            logger.info(f"[Investigation Pipeline] Chapter 3: {len(acts_3_raw)} chars")
    except Exception as e:
        logger.warning(f"[Investigation Pipeline] ProAuthorAgent Ch3 failed: {e}")
    finally:
        await pro_author_2.close()

    if not acts_3_raw:
        acts_3_raw = await _gen_acts_3_4(ctx, story_outline)
        acts_3_raw = _post_process_module_text(acts_3_raw, forbidden_names)

    # ── Pass 4: DNDExpertAgent — stat blocks ───────────────────────────────
    logger.info("[Investigation Pipeline] DNDExpertAgent → stat blocks...")
    dnd_expert = DNDExpertAgent()
    encounter_content = ""
    try:
        stats_prompt = f"""Add complete D&D 5e 2024 encounter mechanics for this investigation module.

STORY OUTLINE (for context on who the enemies are):
{story_outline[:1800]}

MISSION: {title} | FACTION: {faction} | CR: {ctx['cr']} | TIER: {tier}

Write:

## Enemy Stat Blocks
For the antagonist and any bodyguards/enforcers, provide FULL 5e 2024 stat blocks.
**[NAME]** — [Type, Alignment]
**AC** [value] | **HP** [value] ([hit dice]) | **Speed** [speeds]
**STR/DEX/CON/INT/WIS/CHA** [all 6 scores and modifiers]
**Saving Throws** | **Skills** | **Resistances/Immunities** | **Senses** | **Languages** | **CR** | **XP**
**TRAITS** | **ACTIONS** | **BONUS ACTIONS** | **REACTIONS**
**Tactical Notes**: Opening move / Target priority / Surrender conditions

## Skill Check Reference
All DCs used in this module at CR {ctx['cr']}:
| Skill | DC | What success achieves |
|-------|----|-----------------------|
[fill in every relevant check from the investigation]

Output ONLY the stat blocks and skill check table."""

        stats_response = await dnd_expert.complete(stats_prompt, force=True)
        if stats_response.success and stats_response.content:
            encounter_content = stats_response.content
    except Exception as e:
        logger.warning(f"[Investigation Pipeline] DNDExpertAgent failed: {e}")
    finally:
        await dnd_expert.close()

    acts_3_4 = acts_3_raw
    if encounter_content:
        acts_3_4 = f"{acts_3_raw}\n\n---\n\n{encounter_content}"

    # ── Pass 5: DNDVeteranAgent — clue trail + red herring + aftermath ─────
    logger.info("[Investigation Pipeline] DNDVeteranAgent → clue trail + aftermath...")
    dnd_veteran = DNDVeteranAgent()
    act_5_rewards = ""
    try:
        pc_level = get_max_pc_level()
        rewards_block = format_rewards_block(
            tier=tier, cr=ctx['cr'], faction=faction,
            mission_reward_text=mission.get('reward', ''),
            pc_level=pc_level,
        )
        loot_table = build_loot_table(ctx['cr'], tier, pc_level=pc_level)

        veteran_prompt = f"""Write the DM reference materials, aftermath, and rewards for this mystery module.

STORY OUTLINE:
{story_outline[:1500]}

MISSION: {title} | FACTION: {faction} | TIER: {tier}

{rewards_block}

Write:

## Clue Trail Reference (DM Tool)
A quick-reference table so the DM can track what the party knows.

| Clue | Found Where | What It Proves | If Missed |
|------|-------------|----------------|-----------|
[list all 5-7 clues from the mystery — mark any as RED HERRING where applicable]

## Red Herring Reveal
When the party figures out the planted lead is false:
- What exposes it as misdirection
- Whether the person who planted it is guilty of something ELSE
- How the real culprit reacts when their misdirection is unraveled

## Aftermath

### If the Party Solves It
- Who is held accountable and how
- What concretely changes in the Undercity (faction balance, NPC fate, location status)
- **Closing moment** (2-3 sentences for DM to describe)

### If the Party Fails or Accuses the Wrong Person
- What the real culprit achieves
- Consequences — who suffers, what truth stays buried
- **Closing moment** (2-3 sentences)

### Partial Success
One realistic middle-ground for creative or mixed results.

## Rewards
{loot_table}
### Faction Standing
- Solve it correctly: +5 {faction} reputation
- Wrong accusation: -3 {faction} reputation, +2 opposing faction

### What Comes Next
One follow-up hook per outcome — tied directly to the mystery's resolution.

## DM Complication Table (d6)
Roll when the investigation stalls or things go sideways:

| d6 | Complication |
|----|--------------|
| 1  | [a witness recants their statement] |
| 2  | [the culprit destroys or moves evidence] |
| 3  | [a faction pressures the party to drop the case] |
| 4  | [an innocent suspect goes into hiding, looking guilty] |
| 5  | [a second crime occurs while they investigate the first] |
| 6  | [the client is implicated by the evidence] |
Make all 6 entries specific to THIS mystery.

Output ONLY the sections above."""

        vet_response = await dnd_veteran.complete(veteran_prompt, force=True)
        if vet_response.success and vet_response.content:
            act_5_rewards = _post_process_module_text(vet_response.content, forbidden_names)
            logger.info(f"[Investigation Pipeline] Aftermath: {len(act_5_rewards)} chars")
    except Exception as e:
        logger.warning(f"[Investigation Pipeline] DNDVeteranAgent failed: {e}")
    finally:
        await dnd_veteran.close()

    if not act_5_rewards:
        act_5_rewards = await _gen_act_5_rewards(ctx, story_outline)
        act_5_rewards = _post_process_module_text(act_5_rewards, forbidden_names)

    # ── Assemble and build DOCX ────────────────────────────────────────────
    module_data = format_module_for_docx(
        title=title,
        overview=story_outline,
        acts_1_2=acts_1_2,
        acts_3_4=acts_3_4,
        act_5_rewards=act_5_rewards,
        metadata={
            "faction": faction,
            "tier": tier,
            "cr": ctx['cr'],
            "primary_location": ctx['primary_location'],
            "player_name": player_name,
        },
    )
    module_data["player_name"] = player_name
    module_data["max_pc_level"] = ctx['max_pc_level']
    module_data["player_level"] = ctx['max_pc_level'] if ctx['max_pc_level'] > 0 else CR_TO_LEVEL.get(ctx['cr'], ctx['cr'])
    module_data["reward"] = mission.get("reward", "Standard")
    module_data["generated_at"] = datetime.now().isoformat()
    module_data["pipeline"] = "investigation"

    if not validate_module_data(module_data):
        logger.warning("[Investigation Pipeline] Module validation failed, attempting build anyway")

    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:50]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("[Investigation Pipeline] Building DOCX...")
    output_path = await build_docx(module_data, filename=f"{safe_title}_{timestamp}")

    if output_path:
        logger.info(f"[Investigation Pipeline] Module generated: {output_path}")
        # Save sidecar JSON so post_module_to_channel can extract real scene text for maps
        try:
            sidecar_path = output_path.with_name(output_path.stem + "_mapdata.json")
            sidecar_data = {
                "title": title,
                "metadata": module_data.get("metadata", {}),
                "sections": module_data.get("sections", {}),
            }
            sidecar_path.write_text(
                json.dumps(sidecar_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info(f"[Investigation Pipeline] Sidecar saved: {sidecar_path.name}")
        except Exception as e:
            logger.warning(f"[Investigation Pipeline] Sidecar save failed (non-fatal): {e}")
    else:
        logger.error("[Investigation Pipeline] DOCX generation failed")

    return output_path


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

async def generate_module(mission: dict, player_name: str = "") -> Optional[Path]:
    """
    Generate a complete mission module as a .docx file.
    
    Args:
        mission: Dict with mission data (title, body, faction, tier, etc.)
        player_name: Name of the player who claimed the mission
    
    Returns:
        Path to the generated .docx file, or None on failure
    """
    title = mission.get("title", "Unknown Mission")
    tier = mission.get("tier", "standard")
    mission_type = mission.get("type", tier)

    logger.info(f"Generating module: {title!r} | tier={tier} | type={mission_type}")

    # Investigation type: mystery-focused pipeline with clue trail + red herring
    if mission_type == "investigation":
        return await _generate_investigation_pipeline(mission, player_name)

    # All other types: story-first pipeline with type-aware beats
    return await _generate_story_pipeline(mission, player_name)


async def post_module_to_channel(client, docx_path: Path, mission: dict, player_name: str) -> bool:
    """Post the generated module .docx to the module output channel."""
    import discord

    channel_id = int(os.getenv("MODULE_OUTPUT_CHANNEL_ID", "0"))
    if not channel_id:
        logger.warning("MODULE_OUTPUT_CHANNEL_ID not set — cannot post module")
        return False

    channel = client.get_channel(channel_id)
    if not channel:
        logger.warning(f"Module output channel {channel_id} not found")
        return False

    title = mission.get("title", "Unknown Mission")
    tier = mission.get("tier", "standard").upper()
    cr = get_cr(mission.get("tier", "standard"))
    faction = mission.get("faction", "Unknown")

    max_level = get_max_pc_level()
    level_note = f" (party max level {max_level})" if max_level > 0 else ""

    embed = discord.Embed(
        title=f"Mission Module: {title}",
        description=(
            f"**Claimed by:** {player_name}\n"
            f"**Faction:** {faction}\n"
            f"**Tier:** {tier} | **CR:** {cr}{level_note}\n"
            f"**Estimated Runtime:** ~2 hours\n\n"
            f"*Full module document attached below. Print or share with your DM.*"
        ),
        color=discord.Color.dark_gold(),
    )
    embed.set_footer(text="Generated by Tower of Last Chance | D&D 5e 2024 Compatible")

    try:
        file = discord.File(str(docx_path), filename=f"{title[:60]}.docx")
        await channel.send(embed=embed, file=file)
        logger.info(f"Module posted to channel {channel_id}: {title}")

        # Generate and post maps to the SAME channel as the DOCX
        try:
            # Load sidecar JSON saved by the pipeline (has real chapter text for scene extraction)
            sidecar_path = docx_path.with_name(docx_path.stem + "_mapdata.json")
            if sidecar_path.exists():
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                map_module_data = {
                    "title": sidecar.get("title", title),
                    "metadata": sidecar.get("metadata", {"primary_location": mission.get("location", "Unknown")}),
                    "sections": sidecar.get("sections", {}),
                    "raw_content": "",
                }
                logger.info(f"📄 Loaded map sidecar for: {title}")
            else:
                # Sidecar missing — build minimal fallback
                logger.warning(f"⚠️ No map sidecar found for {title} — scene extraction may miss scenes")
                map_module_data = {
                    "title": title,
                    "metadata": {"primary_location": mission.get("location", "Unknown")},
                    "sections": {},
                    "raw_content": mission.get("body", ""),
                }

            output_subdir = docx_path.stem
            map_paths = await generate_module_maps(map_module_data, output_subdir=output_subdir, max_maps=5)

            if map_paths:
                # Post maps to this same channel (not MAPS_CHANNEL_ID)
                success = await post_maps_to_channel(client, map_paths, map_module_data, channel=channel)
                if success:
                    logger.info(f"✅ Maps posted for: {title}")
                else:
                    logger.warning(f"⚠️ Maps generated but failed to post for: {title}")
            else:
                logger.warning(f"⚠️ No maps generated (A1111 unavailable or no scenes found) for: {title}")
        except Exception as e:
            logger.error(f"❌ Map generation failed for {title}: {e}")
            # Don't fail the entire post operation

        return True
    except Exception as e:
        logger.error(f"Failed to post module: {e}")
        return False


# Convenience exports
__all__ = [
    "generate_module",
    "post_module_to_channel",
    "gather_context",
    "get_cr",
    "get_max_pc_level",
    "get_output_dir",
    # Map generation
    "extract_map_scenes",
    "generate_vtt_map",
    "generate_module_maps",
    "post_maps_to_channel",
]
