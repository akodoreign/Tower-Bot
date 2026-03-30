"""
mission_builder — Modular mission module generator for Tower of Last Chance.

This package replaces the monolithic mission_module_gen.py with a cleaner architecture:
- locations.py: Gazetteer integration for real named places
- leads.py: Investigation leads system (replaces Read Aloud)
- encounters.py: Combat design and stat blocks
- npcs.py: NPC generation and dialogue
- rewards.py: Loot tables and consequences
- docx_builder.py: DOCX output generation

MAJOR CHANGES from original:
1. ❌ NO MORE "Read Aloud" sections — these are replaced by:
2. ✅ Investigation Leads with WHY to go there
3. ✅ Real location names from city_gazetteer.json
4. ✅ Multiple approach options (social/stealth/direct)
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

    # News memory for plot hooks
    news = _load_text(DOCS_DIR / "news_memory.txt", max_chars=6000)

    # Faction reputation
    rep = _load_json(DOCS_DIR / "faction_reputation.json")
    faction_rep = ""
    if isinstance(rep, dict):
        for fname, fdata in rep.items():
            if faction.lower() in fname.lower():
                faction_rep = f"{fname}: tier={fdata.get('tier', '?')}, points={fdata.get('points', 0)}"
                break

    # Character info (if personal mission)
    char_info = ""
    if personal_for:
        chars_text = _load_text(DOCS_DIR / "character_memory.txt", max_chars=3000)
        blocks = chars_text.split("---CHARACTER---")
        for block in blocks:
            if personal_for.lower() in block.lower():
                char_info = block.strip()
                break

    # Active rift state
    rifts = _load_json(DOCS_DIR / "rift_state.json")
    active_rifts = [r for r in rifts if not r.get("resolved")]
    rift_context = ""
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
    """Call Ollama and return the text response."""
    import httpx

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": messages,
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()

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
~2 hours (break down by act)

Output ONLY the sections above."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=180.0)


async def _gen_acts_1_2(ctx: dict, overview: str) -> str:
    """Generate Acts 1-2: Briefing and Investigation — WITH INVESTIGATION LEADS."""
    
    enc_guidelines = format_encounter_guidelines(ctx['cr'], ctx['tier'])
    quest_giver = format_quest_giver_guidance(ctx['faction'])
    
    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {ctx['cr']} | Tier: {ctx['tier']} | Faction: {ctx['faction']}

MODULE OVERVIEW (already written):
{overview[:2000]}

AVAILABLE LOCATIONS:
{ctx['establishments_context']}

{enc_guidelines}

{quest_giver}

Now write Acts 1 and 2:

## Act 1: The Briefing (~15 minutes)

Write a detailed scene where the quest-giver NPC briefs the players.

**Scene Description** (2-3 sentences for DM to paraphrase — NOT "Read Aloud"):
Describe the meeting location and the NPC's demeanor.

**NPC Dialogue**: Key information shared as actual dialogue lines (2-3 lines, then pause for questions)

**What the NPC withholds**: Info they won't share unless pressed
- Insight DC {ctx['cr']+8}: Notice they're holding back
- Persuasion DC {ctx['cr']+10}: Get them to reveal [specific info]

**Investigation Leads Given**: The NPC points players toward 2-3 leads:
For each lead, specify:
- WHERE to go (use real location names from the gazetteer)
- WHO to talk to
- WHY this lead matters

## Act 2: Investigation & Exploration (~30 minutes)

Design 3 investigation leads the players can pursue in any order.

{ctx['leads_prompt']}

For EACH lead, write:

### Lead [N]: [Location Name]

**Why go here**: [The specific reason this location matters to the mission]

**Scene Description** (2-3 sentences for DM — NOT "Read Aloud")

**The Contact**: [NPC Name]
- Who they are and why they matter
- Their motivation (why they might help)
- What they know

**Approach Options**:
- **Social** (Persuasion DC {ctx['cr']+8}): [approach and outcome]
- **Intimidation** (DC {ctx['cr']+10}): [approach and outcome]
- **Stealth/Investigation** (DC {ctx['cr']+9}): [alternative approach]
- **Bribe**: [cost and result]

**What Players Learn**: The clue or information gained

**Complication**: Something that makes this lead tricky

Include at least one encounter that can be resolved through roleplay OR combat.

Output ONLY Acts 1 and 2."""

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

MODULE OVERVIEW:
{overview[:1500]}

CONFRONTATION LOCATION: {loc_name}

{encounter_block}

Now write Acts 3 and 4:

## Act 3: The Complication (~15 minutes)

A twist that changes what players thought they knew.

**The Reveal**: What goes wrong or what new information surfaces

**Scene Description** (2-3 sentences for DM — NOT "Read Aloud"):
A dramatic moment description.

**Faction Politics**: How this ties to Undercity faction tensions

**Choice Point**: A meaningful decision affecting Act 4
- Option A: [choice and consequence]
- Option B: [choice and consequence]

**Time Pressure**: Why they can't walk away and come back later

## Act 4: The Confrontation (~45 minutes)

The main encounter. Combat-focused but allow creative solutions.

### Battlefield: {loc_name}

**Scene Description** (3-4 sentences describing the environment):

**Terrain Features** (at least 3):
- [Feature 1]: [cover type, tactical use]
- [Feature 2]: [hazard or advantage]
- [Feature 3]: [interactive element]

**Environmental Hazards**:
- [Hazard]: [trigger, effect, DC if applicable]

### Enemy Forces

Provide 2-3 enemy types with FULL 5e 2024 stat blocks.

For EACH enemy type, provide complete stat block:
- Name, AC, HP (with hit dice), Speed
- Ability Scores (all 6)
- Saving Throws, Skills
- Damage Resistances/Immunities
- Senses, Languages, CR, XP
- Traits
- Actions (full descriptions with attack bonus, damage, save DCs)
- Bonus Actions/Reactions if any
- Legendary Actions for boss (CR 8+)

### Tactical Notes
- How enemies fight (tactics, target priority)
- Retreat conditions
- What if players are losing (escape, mercy)
- What if players are winning easily (reinforcements, phase 2)

### Non-Combat Resolution
How can clever players avoid or shortcut this fight?
- Skill check option: [Skill] DC {ctx['cr']+12} to [outcome]
- Roleplay option: [what could convince the antagonist]
- Environmental option: [creative use of terrain]

Output ONLY Acts 3 and 4."""

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

MODULE OVERVIEW:
{overview[:1500]}

{rewards_block}

Now write Act 5 and the Rewards section:

## Act 5: Resolution (~15 minutes)

### Success Outcome
- What happens when players complete the mission
- How the {ctx['faction']} reacts
- What changes in the Undercity
- **Closing narration** (2-3 sentences for DM to paraphrase)

### Failure Outcome
- What happens if players fail or retreat
- Consequences for the faction and Undercity
- Personal consequences
- **Closing narration** (2-3 sentences)

### Partial Success
- Middle ground for creative solutions
- Mixed reactions

## Rewards & Consequences

### Faction Reputation
- Success: +5 {ctx['faction']}, +2 allied factions
- Partial: +2 {ctx['faction']}
- Failure: -3 {ctx['faction']}, +2 opposing factions

{loot_table}

### Future Hooks
Based on the outcome, what might come next? (1-2 sentences per outcome)

Output ONLY Act 5 and Rewards."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=180.0)


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
    faction = mission.get("faction", "Unknown")
    
    logger.info(f"Generating module for: {title}")
    
    # Gather context
    ctx = gather_context(mission)
    logger.info(f"Primary location: {ctx['primary_location']}")
    logger.info(f"CR: {ctx['cr']} | Tier: {ctx['tier']}")
    
    # Build list of forbidden names (player Discord names that should NOT be used as NPCs)
    # The player_name is passed in — we don't want it appearing as an NPC
    forbidden_names = []
    if player_name:
        forbidden_names.append(player_name)
    
    # Generate sections
    logger.info("Generating overview...")
    overview = await _gen_overview(ctx)
    if not overview:
        logger.error("Failed to generate overview")
        return None
    overview = _post_process_module_text(overview, forbidden_names)
    
    logger.info("Generating Acts 1-2 (briefing + investigation)...")
    acts_1_2 = await _gen_acts_1_2(ctx, overview)
    if not acts_1_2:
        logger.error("Failed to generate Acts 1-2")
        return None
    acts_1_2 = _post_process_module_text(acts_1_2, forbidden_names)
    
    logger.info("Generating Acts 3-4 (complication + confrontation)...")
    acts_3_4 = await _gen_acts_3_4(ctx, overview)
    if not acts_3_4:
        logger.error("Failed to generate Acts 3-4")
        return None
    acts_3_4 = _post_process_module_text(acts_3_4, forbidden_names)
    
    logger.info("Generating Act 5 + Rewards...")
    act_5_rewards = await _gen_act_5_rewards(ctx, overview)
    if not act_5_rewards:
        logger.error("Failed to generate Act 5")
        return None
    act_5_rewards = _post_process_module_text(act_5_rewards, forbidden_names)
    
    # Format for DOCX
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
    
    # Additional metadata for the JSON
    module_data["player_name"] = player_name
    module_data["max_pc_level"] = ctx['max_pc_level']
    module_data["player_level"] = ctx['max_pc_level'] if ctx['max_pc_level'] > 0 else CR_TO_LEVEL.get(ctx['cr'], ctx['cr'])
    module_data["reward"] = mission.get("reward", "Standard")
    module_data["generated_at"] = datetime.now().isoformat()
    
    # Validate
    if not validate_module_data(module_data):
        logger.warning("Module validation failed, attempting build anyway")
    
    # Build DOCX
    logger.info("Building DOCX file...")
    
    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:50]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    output_path = await build_docx(module_data, filename=f"{safe_title}_{timestamp}")
    
    if output_path:
        logger.info(f"Module generated: {output_path}")
        
        # Generate VTT maps for combat scenes
        # Maps use image_ref.py for iterative improvement
        try:
            map_paths = await generate_module_maps(
                module_data,
                output_subdir=output_path.stem,  # Use module filename as subdir
                max_maps=4,  # Limit to 4 maps per module
            )
            if map_paths:
                logger.info(f"Generated {len(map_paths)} VTT maps")
                # Store map paths in module_data for later posting
                module_data["map_paths"] = [str(p) for p in map_paths]
        except Exception as e:
            logger.warning(f"Map generation failed (non-fatal): {e}")
    else:
        logger.error("DOCX generation failed")
    
    return output_path


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
        
        # CRITICAL FIX: Generate and post maps
        # Extract module_data from docx_path parent directory context
        try:
            # Reconstruct minimal module_data for map generation
            module_data = {
                "title": title,
                "raw_content": mission.get("body", ""),
                "sections": mission.get("sections", {}),
                "metadata": {"primary_location": mission.get("location", "Unknown")},
            }
            
            output_subdir = docx_path.parent.name if docx_path.parent else "generated_modules"
            map_paths = await generate_module_maps(module_data, output_subdir=output_subdir, max_maps=5)
            
            if map_paths:
                success = await post_maps_to_channel(client, map_paths, module_data)
                if success:
                    logger.info(f"✅ Maps successfully posted for: {title}")
                else:
                    logger.warning(f"⚠️ Maps generated but failed to post for: {title}")
            else:
                logger.warning(f"⚠️ No maps generated (A1111 unavailable?) for: {title}")
        except Exception as e:
            logger.error(f"❌ Map generation failed for {title}: {e}")
            # Don't fail the entire post operation, just warn
        
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
