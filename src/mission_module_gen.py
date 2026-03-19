"""
mission_module_gen.py — Generates full D&D 5e 2024 mission modules as .docx files.

When a player claims a mission, this module:
1. Gathers campaign context (news memory, NPC roster, faction data)
2. Uses Ollama to generate a full 2-hour session module in sections
3. Calls a Node.js script (docx-js) to build the .docx file
4. Returns the file path for posting to Discord

CR scaling by mission tier:
  local/patrol       → CR 4
  escort/standard    → CR 5
  investigation      → CR 6
  rift/dungeon       → CR 7-8
  major/inter-guild  → CR 9-10
  high-stakes        → CR 10-11
  epic/divine/tower  → CR 12
"""

from __future__ import annotations

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "generated_modules"

# ---------------------------------------------------------------------------
# CR scaling
# ---------------------------------------------------------------------------

TIER_CR: Dict[str, int] = {
    "local":         4,
    "patrol":        4,
    "escort":        5,
    "standard":      5,
    "investigation": 6,
    "rift":          8,
    "dungeon":       8,
    "major":         9,
    "inter-guild":   10,
    "high-stakes":   11,
    "epic":          12,
    "divine":        12,
    "tower":         12,
}
DEFAULT_CR = 5

# Approximate player level for the CR (assumes 4-player party)
CR_TO_LEVEL = {4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10, 11: 11, 12: 12}

# Encounter difficulty multipliers for 5e 2024
# These guide how many monsters / what mix to suggest
ENCOUNTER_BUDGET = {
    4:  {"easy": 250, "medium": 500, "hard": 750, "deadly": 1000},
    5:  {"easy": 500, "medium": 1000, "hard": 1500, "deadly": 2000},
    6:  {"easy": 600, "medium": 1200, "hard": 1800, "deadly": 2400},
    7:  {"easy": 750, "medium": 1500, "hard": 2100, "deadly": 2800},
    8:  {"easy": 1000, "medium": 1800, "hard": 2400, "deadly": 3200},
    9:  {"easy": 1100, "medium": 2200, "hard": 3000, "deadly": 3900},
    10: {"easy": 1200, "medium": 2500, "hard": 3800, "deadly": 5000},
    11: {"easy": 1600, "medium": 3200, "hard": 4800, "deadly": 6400},
    12: {"easy": 2000, "medium": 3900, "hard": 5900, "deadly": 7800},
}


def _get_cr(tier: str) -> int:
    return TIER_CR.get(tier.lower(), DEFAULT_CR)


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


def _gather_context(mission: dict) -> dict:
    """Pull all relevant campaign context for module generation."""
    faction = mission.get("faction", "")
    tier = mission.get("tier", "standard")
    title = mission.get("title", "")
    body = mission.get("body", "")
    personal_for = mission.get("personal_for", "")

    # NPC roster — focus on same faction + a few from opposing factions
    roster = _load_json(DOCS_DIR / "npc_roster.json")
    faction_npcs = [n for n in roster if n.get("faction", "").lower() == faction.lower()
                    and n.get("status") == "alive"]
    other_npcs = [n for n in roster if n.get("faction", "").lower() != faction.lower()
                  and n.get("status") == "alive"]
    # Pick up to 3 faction NPCs and 2 others for variety
    relevant_npcs = faction_npcs[:3] + other_npcs[:2]

    # Format NPC summaries
    npc_summaries = []
    for n in relevant_npcs:
        npc_summaries.append(
            f"- {n['name']} ({n.get('species', '?')}, {n.get('faction', '?')}, "
            f"{n.get('rank', '?')}): {n.get('motivation', 'Unknown motivation')}. "
            f"Location: {n.get('location', 'Unknown')}. "
            f"Secret: {n.get('secret', 'None known')}."
        )
    npc_block = "\n".join(npc_summaries) if npc_summaries else "(No roster NPCs available.)"

    # News memory — recent events for plot hooks
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
        # Find the character block
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

    return {
        "mission": mission,
        "faction": faction,
        "tier": tier,
        "cr": _get_cr(tier),
        "title": title,
        "body": body,
        "personal_for": personal_for,
        "char_info": char_info,
        "npc_block": npc_block,
        "relevant_npcs": relevant_npcs,
        "news_memory": news,
        "faction_rep": faction_rep,
        "rift_context": rift_context,
    }


# ---------------------------------------------------------------------------
# Ollama generation helpers
# ---------------------------------------------------------------------------

async def _ollama_generate(prompt: str, system: str = "", timeout: float = 180.0) -> str:
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


# ---------------------------------------------------------------------------
# Module section generators
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert D&D 5e 2024 module designer creating content for the Tower of Last Chance campaign.
The setting is the Undercity — a sealed underground city under a Dome, with factions, Rifts, and dark urban fantasy themes.
All content must be D&D 5e 2024 (5.5e) compatible.
Your modules should provide approximately 2 hours of real-time gameplay.
Write for the DM — be specific, actionable, and include DC values, skill checks, and tactical notes.
Do NOT use flowery prose or filler. Be direct and useful.
Output ONLY the requested content. No meta-commentary."""


async def _gen_overview(ctx: dict) -> str:
    """Generate the module overview / DM summary."""
    prompt = f"""Create a DM-facing module overview for this D&D 5e 2024 mission.

MISSION: {ctx['title']}
FACTION: {ctx['faction']}
TIER: {ctx['tier']} (Challenge Rating: {ctx['cr']})
MISSION DETAILS: {ctx['body']}

RECENT NEWS EVENTS (use 1-2 as plot hooks or background):
{ctx['news_memory'][:3000]}

RELEVANT NPCs:
{ctx['npc_block']}

{f"PERSONAL FOR: {ctx['personal_for']}" if ctx['personal_for'] else ""}
{f"CHARACTER INFO: {ctx['char_info'][:1000]}" if ctx['char_info'] else ""}
{ctx['rift_context']}

Write the following sections (use markdown headers):

## Module Overview
A 3-4 sentence summary of what this module is about, what the real stakes are, and the hidden complication.

## Background
What's really going on behind the scenes — faction politics, NPC motivations, the truth the players don't know yet. 4-6 sentences.

## Adventure Hook
How the players get involved. Reference the mission board posting and the contact NPC. 2-3 sentences.

## Key NPCs
For each NPC in this module (3-5 NPCs total), provide:
- **Name** (Species, Faction, Role)
- **Motivation**: What they want
- **Secret**: What they're hiding
- **Personality**: 2-3 adjective description for roleplay
Include at least one NPC from the mission faction and one antagonist/complication NPC.

## Estimated Runtime
~2 hours (break down by act)

Output ONLY the sections above. No preamble."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=180.0)


async def _gen_acts_1_2(ctx: dict, overview: str) -> str:
    """Generate Acts 1-2: Briefing and Investigation."""
    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {ctx['cr']} | Tier: {ctx['tier']} | Faction: {ctx['faction']}

MODULE OVERVIEW (already written):
{overview[:2000]}

Now write Acts 1 and 2:

## Act 1: The Briefing (~15 minutes)
Write a detailed scene where the quest-giver NPC briefs the players.
Include:
- **Read-aloud text** (boxed text for the DM to read to players — 3-4 sentences describing the scene)
- **NPC Dialogue**: Key information the NPC shares, written as actual dialogue lines
- **What the NPC withholds**: Information they won't share unless pressed (with DC values for Insight/Persuasion)
- **Skill Checks**: Any checks the players might make here (DC values, what success/failure reveals)

## Act 2: Investigation & Exploration (~30 minutes)
Design 3-4 locations or scenes the players will explore.
For each location:
- **Name and Description** (2-3 sentences)
- **What's Here**: Clues, NPCs, environmental details
- **Skill Challenges**: Specific checks with DCs (Investigation DC {ctx['cr']+8}, Perception DC {ctx['cr']+7}, etc.)
- **Social Encounters**: NPCs to talk to, what they know, what convinces them (Persuasion/Intimidation DCs)
- **Complication**: Something that makes this location dangerous or tricky
- **Clue**: What the players learn that points them toward Act 3

Include at least one encounter that can be resolved through roleplay OR combat (player choice).

Make DCs appropriate for CR {ctx['cr']} (moderate DC = {ctx['cr']+8}, hard DC = {ctx['cr']+10}).
Output ONLY the two acts. No preamble."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=180.0)


async def _gen_acts_3_4(ctx: dict, overview: str) -> str:
    """Generate Acts 3-4: Complication and Confrontation."""
    cr = ctx['cr']
    budget = ENCOUNTER_BUDGET.get(cr, ENCOUNTER_BUDGET[5])

    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {cr} | Tier: {ctx['tier']} | Faction: {ctx['faction']}

MODULE OVERVIEW (already written):
{overview[:2000]}

Now write Acts 3 and 4:

## Act 3: The Complication (~15 minutes)
A twist that changes what the players thought they knew.
Include:
- **The Reveal**: What goes wrong or what new information surfaces
- **Read-aloud text**: A dramatic moment for the DM to narrate (3-4 sentences)
- **Faction Politics**: How this complication ties to Undercity faction tensions
- **Choice Point**: A meaningful decision the players must make that affects Act 4
- **Time Pressure**: Why they can't just walk away and come back later

## Act 4: The Confrontation (~45 minutes)
The main encounter of the module. This should be combat-focused but allow creative solutions.

### Encounter Design (D&D 5e 2024)
- **Challenge Rating**: CR {cr} encounter for a party of 4 level-{CR_TO_LEVEL.get(cr, cr)} characters
- **XP Budget**: Medium={budget['medium']} XP, Hard={budget['hard']} XP (target a Hard encounter)
- **Environment**: Detailed battlefield description with at least 3 interactive terrain features
  (cover, elevation, hazards, chokepoints, etc.)

### Enemy Forces
Provide 2-3 enemy types with FULL 5e 2024 stat blocks:

For EACH enemy, provide:
- **Name** and description
- **AC**, **HP** (with hit dice), **Speed**
- **Ability Scores**: STR, DEX, CON, INT, WIS, CHA
- **Saving Throws** (proficient ones)
- **Skills** (proficient ones with bonuses)
- **Damage Resistances/Immunities** (if any)
- **Senses** (darkvision, passive Perception)
- **Languages**
- **Challenge Rating** and XP
- **Actions**: Full action descriptions with attack bonuses, damage dice, save DCs
- **Bonus Actions / Reactions** (if any)
- **Lair Actions or Legendary Actions** (only for boss-type enemies CR 8+)

### Tactical Notes
- How the enemies fight (tactics, target priority, retreat conditions)
- Environmental hazards and how they interact with combat
- What happens if the players are losing (escape route, reinforcements, mercy)
- What happens if the players are winning easily (reinforcement wave, boss phase 2)

Output ONLY Acts 3 and 4. No preamble."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=240.0)


async def _gen_act_5_rewards(ctx: dict, overview: str) -> str:
    """Generate Act 5: Resolution, rewards, and consequences."""
    prompt = f"""Continue building the D&D 5e 2024 module for: {ctx['title']}
CR: {ctx['cr']} | Tier: {ctx['tier']} | Faction: {ctx['faction']}
Mission Reward: {ctx['mission'].get('reward', 'Standard')}

MODULE OVERVIEW (already written):
{overview[:1500]}

Now write Act 5 and the Rewards section:

## Act 5: Resolution (~15 minutes)
- **Success Outcome**: What happens if the players complete the mission. How does the faction react? What changes in the Undercity?
- **Failure Outcome**: What happens if the players fail or retreat. Consequences for the faction, the Undercity, and personally.
- **Partial Success**: A middle ground outcome for creative solutions.
- **Read-aloud text**: A closing narration for the DM (3-4 sentences for success, 3-4 for failure).
- **Story Hooks**: 2-3 plot threads this mission leaves dangling for future adventures.

## Rewards

### On Success
- **Currency**: {ctx['mission'].get('reward', 'Standard tier reward')}
- **Items**: 1-2 items appropriate for CR {ctx['cr']} (use D&D 5e 2024 items — name, rarity, brief description)
- **Faction Standing**: How this affects reputation with {ctx['faction']} and any other factions
- **Information**: Any secrets or knowledge gained
- **Contacts**: New NPC relationships established

### On Failure
- **Reduced Reward**: What they still get (if anything)
- **Consequences**: Specific negative effects (faction rep loss, NPC attitude changes, Undercity effects)

## Loot Table
A table of treasure found during the adventure (not just final reward):
| Location | Item | Value |
| --- | --- | --- |
(Include 5-8 items scattered through the module — some mundane, some useful, one significant)

Output ONLY Act 5 and Rewards. No preamble."""

    return await _ollama_generate(prompt, system=_SYSTEM_PROMPT, timeout=180.0)


# ---------------------------------------------------------------------------
# Full module generation pipeline
# ---------------------------------------------------------------------------

async def generate_module(mission: dict, player_name: str) -> Optional[Path]:
    """
    Generate a complete D&D 5e 2024 module for a claimed mission.
    Returns the path to the generated .docx file, or None on failure.
    """
    title = mission.get("title", "Unknown Mission")
    tier = mission.get("tier", "standard")
    faction = mission.get("faction", "Unknown")
    cr = _get_cr(tier)
    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:50]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info(f"📖 Module generation starting: '{title}' for {player_name} (CR {cr})")

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Gather context
    ctx = _gather_context(mission)

    # 2. Generate sections (sequential — each builds on the previous)
    logger.info("📖 Generating overview...")
    overview = await _gen_overview(ctx)
    if not overview:
        logger.error("📖 Overview generation failed — aborting module")
        return None

    logger.info("📖 Generating Acts 1-2...")
    acts_1_2 = await _gen_acts_1_2(ctx, overview)

    logger.info("📖 Generating Acts 3-4...")
    acts_3_4 = await _gen_acts_3_4(ctx, overview)

    logger.info("📖 Generating Act 5 + Rewards...")
    act_5 = await _gen_act_5_rewards(ctx, overview)

    # 3. Assemble the full module JSON for the docx builder
    module_data = {
        "title": title,
        "faction": faction,
        "tier": tier,
        "cr": cr,
        "player_level": CR_TO_LEVEL.get(cr, cr),
        "player_name": player_name,
        "reward": mission.get("reward", "Standard"),
        "generated_at": datetime.now().isoformat(),
        "sections": {
            "overview": overview or "(Generation failed — fill manually)",
            "acts_1_2": acts_1_2 or "(Generation failed — fill manually)",
            "acts_3_4": acts_3_4 or "(Generation failed — fill manually)",
            "act_5_rewards": act_5 or "(Generation failed — fill manually)",
        },
    }

    # 4. Write JSON for the Node.js builder
    json_path = OUTPUT_DIR / f"{safe_title}_{timestamp}.json"
    json_path.write_text(json.dumps(module_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # 5. Build the .docx
    docx_path = OUTPUT_DIR / f"{safe_title}_{timestamp}.docx"

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", str(SCRIPTS_DIR / "build_module_docx.js"),
            str(json_path), str(docx_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)

        if proc.returncode != 0:
            logger.error(f"📖 docx build failed: {stderr.decode()}")
            return None

        logger.info(f"📖 Module .docx built: {docx_path} ({docx_path.stat().st_size // 1024}KB)")
        return docx_path

    except Exception as e:
        logger.error(f"📖 docx build error: {e}")
        return None


# ---------------------------------------------------------------------------
# Discord posting helper
# ---------------------------------------------------------------------------

async def post_module_to_channel(client, docx_path: Path, mission: dict, player_name: str) -> bool:
    """Post the generated module .docx to the module output channel."""
    import discord

    channel_id = int(os.getenv("MODULE_OUTPUT_CHANNEL_ID", "0"))
    if not channel_id:
        logger.warning("📖 MODULE_OUTPUT_CHANNEL_ID not set — cannot post module")
        return False

    channel = client.get_channel(channel_id)
    if not channel:
        logger.warning(f"📖 Module output channel {channel_id} not found")
        return False

    title = mission.get("title", "Unknown Mission")
    tier = mission.get("tier", "standard").upper()
    cr = _get_cr(mission.get("tier", "standard"))
    faction = mission.get("faction", "Unknown")

    embed = discord.Embed(
        title=f"📖 Mission Module: {title}",
        description=(
            f"**Claimed by:** {player_name}\n"
            f"**Faction:** {faction}\n"
            f"**Tier:** {tier} | **CR:** {cr}\n"
            f"**Estimated Runtime:** ~2 hours\n\n"
            f"*Full module document attached below. Print or share with your DM.*"
        ),
        color=discord.Color.dark_gold(),
    )
    embed.set_footer(text="Generated by Tower of Last Chance | D&D 5e 2024 Compatible")

    try:
        file = discord.File(str(docx_path), filename=f"{title[:60]}.docx")
        await channel.send(embed=embed, file=file)
        logger.info(f"📖 Module posted to channel {channel_id}: {title}")
        return True
    except Exception as e:
        logger.error(f"📖 Failed to post module: {e}")
        return False
