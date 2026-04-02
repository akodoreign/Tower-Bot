"""
json_generator.py — Generate mission modules as JSON output (replacing DOCX).

Uses the same multi-pass Ollama generation as module_generator.py but outputs
structured JSON + images instead of DOCX files.

Can optionally use skills from /skills folder for enhanced creative output (OpenClaw).

Exported:
    generate_module_json()           — Main generation function (async)
    generate_module_json_with_skills() — Generation with skill context
    save_module_json()               — Save module to disk
    set_use_skills()                 — Enable/disable skills usage
"""

from __future__ import annotations

import os
import json
import asyncio
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.log import logger
from . import _ollama_generate
from .mission_json_builder import (
    MissionJsonBuilder,
    create_mission_module,
)
from .schemas import validate_mission_module
from .encounters import get_cr, get_max_pc_level
from .mission_types import (
    get_mission_type,
    map_difficulty_to_tier,
    map_difficulty_to_5e,
    get_difficulty_description,
    generate_dynamic_title,
)

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "generated_modules"

# Global flag for skill usage
_USE_SKILLS = False
_SKILLS_CACHE = None

# ─────────────────────────────────────────────────────────────────────────
# System Prompt (reused from mission_builder)
# ─────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
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


# ─────────────────────────────────────────────────────────────────────────
# Mission Type Integration
# ─────────────────────────────────────────────────────────────────────────

def _get_system_prompt_for_mission_type(mission_type_name: str) -> str:
    """Get additional system prompt context for specific mission type."""
    mission_type = get_mission_type(mission_type_name)
    if not mission_type:
        return ""
    
    return f"""
MISSION TYPE: {mission_type.display_name.upper()}
{mission_type.description}

DM GUIDANCE FOR THIS TYPE:
{mission_type.dm_guidance}

Typical Structure for This Mission Type:
{chr(10).join(f"  - {act}" for act in mission_type.typical_act_structure)}

Common Skill Checks: {", ".join(mission_type.skill_checks)}
Combat Intensity: {mission_type.combat_intensity.title()}
Roleplay Intensity: {mission_type.roleplay_intensity.title()}
"""


async def _ensure_mission_type_in_title(
    title: str,
    mission_type: Optional[str],
    faction: str,
    difficulty: int = 5,
) -> str:
    """
    Ensure mission type is incorporated into the title.
    If title doesn't already contain mission type keywords, generate a new one.
    
    Args:
        title: Original title
        mission_type: Mission type name
        faction: Associated faction
        difficulty: Difficulty rating (1-10)
    
    Returns:
        Updated title with mission type incorporated
    """
    if not mission_type:
        return title
    
    mission = get_mission_type(mission_type)
    if not mission:
        return title
    
    # Check if title already contains the mission type name or display name
    title_lower = title.lower()
    if mission_type.lower() in title_lower or mission.display_name.lower() in title_lower:
        return title  # Already includes mission type
    
    # Try to generate a dynamic title
    try:
        new_title = await generate_dynamic_title(
            mission_type=mission_type,
            faction=faction,
            theme_or_subject=title,
            difficulty=difficulty,
            use_skills=_USE_SKILLS,
        )
        if new_title and len(new_title) > 5:
            logger.debug(f"Generated dynamic title: {new_title}")
            return new_title
    except Exception as e:
        logger.debug(f"Could not generate dynamic title: {e}")
    
    # Fallback: add mission type prefix
    return f"{mission.display_name}: {title}"


# ─────────────────────────────────────────────────────────────────────────
# Skills Integration
# ─────────────────────────────────────────────────────────────────────────


def set_use_skills(enabled: bool) -> None:
    """Enable or disable skills usage in generation."""
    global _USE_SKILLS
    _USE_SKILLS = enabled
    logger.info(f"Skills usage: {'enabled' if enabled else 'disabled'}")


async def _get_system_prompt_with_skills() -> str:
    """Get system prompt enhanced with creative writing skills."""
    if not _USE_SKILLS:
        return SYSTEM_PROMPT

    try:
        from src.skills import load_all_skills, build_system_prompt_with_skills

        skills = load_all_skills()
        enhanced = build_system_prompt_with_skills(
            SYSTEM_PROMPT,
            "mission generation",
            skills,
            use_multiple=True,
        )
        logger.debug(f"Using skills-enhanced prompt ({len(enhanced)} chars)")
        return enhanced

    except Exception as e:
        logger.warning(f"Failed to load skills, using base prompt: {e}")
        return SYSTEM_PROMPT


# ─────────────────────────────────────────────────────────────────────────
# Generation Functions
# ─────────────────────────────────────────────────────────────────────────

async def _gen_overview(ctx: Dict) -> str:
    """Generate module overview."""
    system_prompt = await _get_system_prompt_with_skills()
    
    prompt = f"""Create a DM-facing module overview for this D&D 5e 2024 mission.

MISSION: {ctx['title']}
FACTION: {ctx['faction']}
TIER: {ctx['tier']} (Challenge Rating: {ctx['cr']})
PARTY INFO: Highest PC level is {ctx['max_pc_level']}. Design for a party of 4.
MISSION DETAILS: {ctx['body']}

Write the following sections:

## Module Overview
A 3-4 sentence summary: what this mission is about, the real stakes, and the hidden complication.

## Background
What's really going on behind the scenes — faction politics, NPC motivations, the truth players don't know. 4-6 sentences.

## Adventure Hook
How players get involved. Reference the mission board and contact NPC. 2-3 sentences.

Output ONLY the sections above. Use markdown format."""

    return await _ollama_generate(prompt, system=system_prompt, timeout=180.0)


async def _gen_acts_1_2(ctx: Dict, overview: str) -> str:
    """Generate Acts 1-2: Briefing and Investigation."""
    system_prompt = await _get_system_prompt_with_skills()
    
    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {ctx['cr']} | Tier: {ctx['tier']} | Faction: {ctx['faction']}

MODULE OVERVIEW (already written):
{overview[:2000]}

Now write Acts 1 and 2:

## Act 1: The Briefing (~15 minutes)

Write a detailed scene where the quest-giver NPC briefs the players.

**Scene Description** (2-3 sentences for DM to paraphrase):
Describe the meeting location and the NPC's demeanor.

**NPC Dialogue**: Key information shared as actual dialogue lines (2-3 lines)

## Act 2: Investigation & Exploration (~30 minutes)

Design 3 investigation leads the players can pursue in any order.

### Lead 1: [Location Name]
- Why go here
- The Contact NPC
- Approach options (Social, Intimidation, Stealth, Bribe)
- What Players Learn

(Repeat for Leads 2 and 3)

Output ONLY Acts 1 and 2."""

    return await _ollama_generate(prompt, system=system_prompt, timeout=200.0)


async def _gen_acts_3_4(ctx: Dict, overview: str) -> str:
    """Generate Acts 3-4: Complication and Confrontation."""
    system_prompt = await _get_system_prompt_with_skills()
    
    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {ctx['cr']} | Tier: {ctx['tier']} | Faction: {ctx['faction']}

MODULE OVERVIEW:
{overview[:1500]}

Now write Acts 3 and 4:

## Act 3: The Complication (~15 minutes)

A twist that changes what players thought they knew.

**The Reveal**: What goes wrong or what new information surfaces

**Choice Point**: A meaningful decision affecting Act 4
- Option A: [choice and consequence]
- Option B: [choice and consequence]

## Act 4: The Confrontation (~45 minutes)

The main encounter. Combat-focused but allow creative solutions.

### Battlefield Description

Provide 2-3 terrain features with tactical uses.

### Enemy Forces

Provide 2-3 enemy types with FULL stat blocks (AC, HP, Abilities, Actions, etc.)

### Non-Combat Resolution

How can clever players avoid or shortcut this fight?

Output ONLY Acts 3 and 4."""

    system_prompt = await _get_system_prompt_with_skills()
    return await _ollama_generate(prompt, system=system_prompt, timeout=240.0)


async def _gen_act_5_rewards(ctx: Dict, overview: str) -> str:
    """Generate Act 5: Resolution and Rewards."""
    system_prompt = await _get_system_prompt_with_skills()
    
    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {ctx['cr']} | Tier: {ctx['tier']} | Faction: {ctx['faction']}

Now write Act 5 and Rewards:

## Act 5: Resolution (~15 minutes)

### Success Outcome
- What happens when players complete the mission
- How the {ctx['faction']} reacts
- What changes in the Undercity

### Failure Outcome
- What happens if players fail
- Consequences for the faction and Undercity

### Partial Success
- Middle ground for creative solutions

## Rewards & Consequences

### Faction Reputation
- Success: +5 {ctx['faction']}, +2 allied factions
- Partial: +2 {ctx['faction']}
- Failure: -3 {ctx['faction']}, +2 opposing factions

### Treasure
Roll on standard loot tables for CR {ctx['cr']} encounters.

Output ONLY Act 5 and Rewards."""

    return await _ollama_generate(prompt, system=system_prompt, timeout=180.0)


# ─────────────────────────────────────────────────────────────────────────
# Main Generation
# ─────────────────────────────────────────────────────────────────────────

async def generate_module_json(
    mission: Dict,
    player_name: str = "Unclaimed",
) -> Optional[Dict]:
    """
    Generate a complete mission module as JSON.
    
    Args:
        mission: Dict with mission data (title, body, faction, tier, etc.)
        player_name: Name of player claiming the mission
    
    Returns:
        Dict containing structured mission data, or None on failure
    """
    # Import here to avoid circular dependency
    from . import gather_context, _post_process_module_text
    
    title = mission.get("title", "Unknown Mission")
    faction = mission.get("faction", "Unknown")
    tier = mission.get("tier", "standard")
    mission_type = mission.get("type", mission.get("mission_type", tier))
    difficulty_rating = mission.get("difficulty_rating", 5)  # Default: Challenging
    
    logger.info(f"📋 ════════════════════════════════════════")
    logger.info(f"📋 JSON MODULE GENERATION STARTED")
    logger.info(f"📋   Mission: {title}")
    logger.info(f"📋   Type: {mission_type} | Difficulty: {get_difficulty_description(difficulty_rating)}")
    logger.info(f"📋   Faction: {faction} | Tier: {tier}")
    logger.info(f"📋   Player: {player_name}")
    logger.info(f"📋 ════════════════════════════════════════")
    
    start_time = datetime.now()
    
    # Gather context
    logger.info("📋 Gathering campaign context...")
    ctx = gather_context(mission)
    logger.info(f"📋   CR: {ctx['cr']} | Party Level: {ctx['max_pc_level']}")
    
    # Enhance title with mission type if not already present
    logger.info("📋 Enhancing title with mission type...")
    try:
        title = await _ensure_mission_type_in_title(
            title=title,
            mission_type=mission_type,
            faction=faction,
            difficulty=difficulty_rating,
        )
        logger.info(f"📋   Updated title: {title}")
    except Exception as e:
        logger.debug(f"Could not enhance title: {e}")
        # Keep original title on error
    
    # Add mission type context to generation
    ctx["mission_type"] = mission_type
    ctx["difficulty_rating"] = difficulty_rating
    ctx["title"] = title  # Use enhanced title
    
    # Build forbidden names list
    forbidden_names = [player_name] if player_name else []
    
    # ── SEQUENTIAL GENERATION ──
    
    # Pass 1: Overview
    logger.info("📋 ├─ Pass 1/4: Overview")
    t = datetime.now()
    overview = await _gen_overview(ctx)
    elapsed = (datetime.now() - t).total_seconds()
    logger.info(f"📋 │   {len(overview.split()) if overview else 0} words in {elapsed:.0f}s")
    
    if not overview:
        logger.error("📋 └─ Overview generation failed — aborting")
        return None
    
    overview = _post_process_module_text(overview, forbidden_names)
    
    # Pass 2: Acts 1-2
    logger.info("📋 ├─ Pass 2/4: Acts 1-2 (Briefing + Investigation)")
    t = datetime.now()
    acts_1_2 = await _gen_acts_1_2(ctx, overview)
    elapsed = (datetime.now() - t).total_seconds()
    logger.info(f"📋 │   {len(acts_1_2.split()) if acts_1_2 else 0} words in {elapsed:.0f}s")
    
    acts_1_2 = _post_process_module_text(acts_1_2, forbidden_names)
    
    # Pass 3: Acts 3-4
    logger.info("📋 ├─ Pass 3/4: Acts 3-4 (Complication + Confrontation)")
    t = datetime.now()
    acts_3_4 = await _gen_acts_3_4(ctx, overview)
    elapsed = (datetime.now() - t).total_seconds()
    logger.info(f"📋 │   {len(acts_3_4.split()) if acts_3_4 else 0} words in {elapsed:.0f}s")
    
    acts_3_4 = _post_process_module_text(acts_3_4, forbidden_names)
    
    # Pass 4: Act 5 + Rewards
    logger.info("📋 ├─ Pass 4/4: Act 5 (Resolution + Rewards)")
    t = datetime.now()
    act_5_rewards = await _gen_act_5_rewards(ctx, overview)
    elapsed = (datetime.now() - t).total_seconds()
    logger.info(f"📋 │   {len(act_5_rewards.split()) if act_5_rewards else 0} words in {elapsed:.0f}s")
    
    act_5_rewards = _post_process_module_text(act_5_rewards, forbidden_names)
    
    # ── BUILD STRUCTURED JSON ──
    
    logger.info("📋 └─ Building structured JSON...")
    
    builder = create_mission_module(
        title=title,
        faction=faction,
        tier=tier,
        mission_type=mission_type,  # Use actual mission type
        cr=ctx['cr'],
        party_level=ctx['max_pc_level'],
        player_name=player_name,
        player_count=4,
    )
    
    # Add difficulty rating to metadata
    builder.set_metadata(
        difficulty_rating=difficulty_rating,
        mission_type=mission_type,
    )
    
    # Add content sections
    builder.add_overview(overview) \
           .add_acts(
               act_1=_extract_section(acts_1_2, "## Act 1"),
               act_2=_extract_section(acts_1_2, "## Act 2"),
               act_3=_extract_section(acts_3_4, "## Act 3"),
               act_4=_extract_section(acts_3_4, "## Act 4"),
               act_5=_extract_section(act_5_rewards, "## Act 5"),
           ) \
           .add_rewards_summary(_extract_section(act_5_rewards, "## Rewards"))
    
    # Add DOCX sections for backward compatibility
    builder.add_docx_sections(
        overview=overview,
        acts_1_2=acts_1_2,
        acts_3_4=acts_3_4,
        act_5_rewards=act_5_rewards,
    )
    
    # Set reward and runtime
    reward = mission.get("reward", "Standard mission reward")
    builder.set_reward(reward)
    builder.set_runtime(120)  # Standard 2-hour mission
    
    # Build and validate
    module = builder.build(validate=True)
    
    total_time = (datetime.now() - start_time).total_seconds()
    total_words = len(f"{overview} {acts_1_2} {acts_3_4} {act_5_rewards}".split())
    
    logger.info(f"📋 ════════════════════════════════════════")
    logger.info(f"📋 JSON generation complete: {total_words} words in {total_time:.0f}s")
    logger.info(f"📋 ════════════════════════════════════════")
    
    return module


def _extract_section(text: str, section_header: str) -> str:
    """Extract a section from markdown text by header."""
    if not text or section_header not in text:
        return ""
    
    lines = text.split("\n")
    start_idx = None
    end_idx = None
    
    # Find section start
    for i, line in enumerate(lines):
        if section_header in line:
            start_idx = i
            break
    
    if start_idx is None:
        return ""
    
    # Find next section (starts with ##) or end
    for i in range(start_idx + 1, len(lines)):
        if lines[i].startswith("##"):
            end_idx = i
            break
    
    if end_idx is None:
        end_idx = len(lines)
    
    return "\n".join(lines[start_idx:end_idx]).strip()


def save_module_json(
    module: Dict,
    mission_id: Optional[str] = None,
) -> Optional[Path]:
    """
    Save a mission module to JSON files.
    
    Args:
        module: Mission module dict
        mission_id: Optional mission ID (uses title if not provided)
    
    Returns:
        Path to output directory, or None on failure
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Generate mission ID if not provided
    if not mission_id:
        title = module.get("metadata", {}).get("title", "mission")
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
        safe_title = safe_title.replace(" ", "_")[:50]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mission_id = f"{safe_title}_{timestamp}"
    
    # Create mission directory
    mission_dir = OUTPUT_DIR / mission_id
    mission_dir.mkdir(parents=True, exist_ok=True)
    
    # Save module JSON
    json_path = mission_dir / "module_data.json"
    try:
        json_path.write_text(json.dumps(module, indent=2), encoding="utf-8")
        logger.info(f"✅ Mission JSON saved: {json_path}")
    except Exception as e:
        logger.error(f"❌ Failed to save mission JSON: {e}")
        return None
    
    # Create images directory
    images_dir = mission_dir / "images"
    images_dir.mkdir(exist_ok=True)
    
    logger.info(f"✅ Mission saved to: {mission_dir}")
    
    return mission_dir


# ─────────────────────────────────────────────────────────────────────────
# Exports
# ─────────────────────────────────────────────────────────────────────────

__all__ = [
    "generate_module_json",
    "save_module_json",
]
