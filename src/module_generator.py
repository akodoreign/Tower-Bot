"""
module_generator.py — Generates full D&D 5e 2024 mission modules as .docx files.

MULTI-PASS GENERATION:
Instead of 6 thin parallel calls, we use 10-14 sequential Ollama calls
that chain together. Each act gets multiple passes:
  Pass 1: Narrative — scenes, descriptions, NPC dialogue, read-aloud blocks
  Pass 2: Mechanics — stat blocks, DCs, encounter design, skill challenges
These are concatenated into rich, detailed sections before docx assembly.

The result is a full 15-25 page adventure module with dense read-aloud text,
NPC personalities, environmental descriptions, and tactical encounters.
"""

from __future__ import annotations

import os
import json
import asyncio
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from src.log import logger
from src.ollama_busy import mark_busy, mark_available

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
BUILDER_SCRIPT = Path(__file__).resolve().parent / "docx_builder" / "build_module.js"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "generated_modules"

# ---------------------------------------------------------------------------
# Tier → CR mapping
# ---------------------------------------------------------------------------

TIER_CR_MAP = {
    "local":        4,
    "patrol":       4,
    "escort":       5,
    "standard":     6,
    "investigation":6,
    "rift":         8,
    "dungeon":      8,
    "major":        8,
    "inter-guild": 10,
    "high-stakes": 10,
    "epic":        12,
    "divine":      12,
    "tower":       12,
}
DEFAULT_CR = 6

TIER_RUNTIME = {
    "local":        "1.5–2 hours",
    "patrol":       "1.5–2 hours",
    "escort":       "2 hours",
    "standard":     "2 hours",
    "investigation":"2–2.5 hours",
    "rift":         "2–2.5 hours",
    "dungeon":      "2.5–3 hours",
    "major":        "2.5–3 hours",
    "inter-guild":  "2.5–3 hours",
    "high-stakes":  "2.5–3 hours",
    "epic":         "3–4 hours",
    "divine":       "3–4 hours",
    "tower":        "3–4 hours",
}

FACTION_COLORS = {
    "Iron Fang Consortium": "8B4513",
    "Argent Blades":        "808080",
    "Wardens of Ash":       "A0522D",
    "Serpent Choir":        "DAA520",
    "Obsidian Lotus":       "4B0082",
    "Glass Sigil":          "4682B4",
    "Patchwork Saints":     "8B0000",
    "Adventurers' Guild":   "228B22",
    "Guild of Ashen Scrolls":"D2B48C",
    "Tower Authority":      "2F4F4F",
    "Independent":          "696969",
    "Brother Thane's Cult": "800000",
}


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------

def _load_json(path: Path):
    if not path.exists():
        return []
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


def _format_npc_block(npc: dict) -> str:
    """Format an NPC roster entry into a compact reference string."""
    lines = [f"**{npc.get('name','?')}** ({npc.get('species','?')}, {npc.get('faction','?')})"]
    if npc.get("rank"):
        lines[0] += f" — {npc['rank']}"
    if npc.get("appearance"):
        lines.append(f"  Appearance: {npc['appearance']}")
    if npc.get("motivation"):
        lines.append(f"  Motivation: {npc['motivation']}")
    if npc.get("role"):
        lines.append(f"  Role: {npc['role']}")
    if npc.get("location"):
        lines.append(f"  Location: {npc['location']}")
    if npc.get("relationships"):
        lines.append(f"  Relationships: {npc['relationships']}")
    if npc.get("secret"):
        lines.append(f"  Secret: {npc['secret']}")
    return "\n".join(lines)


def gather_context(mission: Dict, player_name: str) -> Dict:
    """Gather all relevant campaign context for module generation."""

    faction = mission.get("faction", "Independent")
    tier = mission.get("tier", "standard")
    cr = TIER_CR_MAP.get(tier, DEFAULT_CR)
    personal_for = mission.get("personal_for", "")

    news_memory = _load_text(DOCS_DIR / "news_memory.txt", max_chars=6000)

    full_roster = _load_json(DOCS_DIR / "npc_roster.json")
    faction_npcs = [n for n in full_roster
                    if n.get("faction", "").lower() == faction.lower()
                    and n.get("status") == "alive"]
    key_npcs = [n for n in full_roster if n.get("status") == "alive"][:15]

    faction_rep = _load_json(DOCS_DIR / "faction_reputation.json")
    char_memory = _load_text(DOCS_DIR / "character_memory.txt", max_chars=4000)

    player_char_block = ""
    if personal_for:
        for block in char_memory.split("---CHARACTER---"):
            if personal_for in block:
                player_char_block = block.strip()
                break

    rift_state = _load_json(DOCS_DIR / "rift_state.json")
    active_rifts = [r for r in rift_state if not r.get("resolved")]

    all_missions = _load_json(DOCS_DIR / "mission_memory.json")
    recent_resolved = [m for m in all_missions if m.get("resolved")][-5:]

    # Build rich NPC reference blocks
    faction_npc_details = "\n\n".join(_format_npc_block(n) for n in faction_npcs[:6])
    key_npc_details = "\n\n".join(_format_npc_block(n) for n in key_npcs[:10])

    return {
        "mission": mission,
        "faction": faction,
        "tier": tier,
        "cr": cr,
        "runtime": TIER_RUNTIME.get(tier, "2 hours"),
        "player_name": player_name,
        "personal_for": personal_for,
        "player_char_block": player_char_block,
        "news_memory": news_memory,
        "faction_npcs": faction_npcs,
        "faction_npc_details": faction_npc_details,
        "key_npc_details": key_npc_details,
        "key_npcs": key_npcs,
        "faction_rep": faction_rep,
        "char_memory": char_memory,
        "active_rifts": active_rifts,
        "recent_resolved": recent_resolved,
        "faction_color": FACTION_COLORS.get(faction, "696969"),
    }


# ---------------------------------------------------------------------------
# Ollama generation
# ---------------------------------------------------------------------------

async def _ollama_generate(prompt: str, system: str = "", timeout: float = 420.0,
                          retries: int = 2) -> str:
    """Call Ollama and return the text response.
    Retries on timeout — module prompts are large and Ollama can be slow."""
    import httpx

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    prompt_words = len(prompt.split())
    system_words = len(system.split()) if system else 0
    logger.info(f"📖 └─ Ollama call: {prompt_words}w prompt + {system_words}w system → {ollama_model} (timeout {timeout:.0f}s)")

    last_err = None
    for attempt in range(1, retries + 1):
        call_start = datetime.now()
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

            lines = text.splitlines()
            skip = ("sure", "here's", "here is", "certainly", "of course",
                    "below is", "i'd be happy", "absolutely")
            while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
                lines.pop(0)
            result = "\n".join(lines).strip()

            elapsed = (datetime.now() - call_start).total_seconds()
            word_count = len(result.split()) if result else 0
            logger.info(f"📖 └─ Ollama responded: {word_count} words in {elapsed:.0f}s{' (attempt ' + str(attempt) + ')' if attempt > 1 else ''}")
            return result

        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout) as e:
            elapsed = (datetime.now() - call_start).total_seconds()
            last_err = e
            logger.warning(f"📖 └─ Ollama TIMEOUT after {elapsed:.0f}s (attempt {attempt}/{retries}): {type(e).__name__}")
            if attempt < retries:
                logger.info(f"📖 └─ Retrying in 5s...")
                await asyncio.sleep(5)
        except Exception as e:
            elapsed = (datetime.now() - call_start).total_seconds()
            logger.error(f"📖 └─ Ollama ERROR after {elapsed:.0f}s: {type(e).__name__}: {e}")
            return ""

    logger.error(f"📖 └─ Ollama FAILED after {retries} attempts — giving up on this section")
    return ""


# ---------------------------------------------------------------------------
# Shared system prompt — injected into every call
# ---------------------------------------------------------------------------

_SYS = """\
You are an expert D&D 5e 2024 adventure module writer for the Tower of Last Chance campaign.

SETTING: The Undercity — a sealed underground city beneath a Dome, built around the Tower of Last Chance.
SYSTEM: D&D 5e 2024 rules (2024 Player's Handbook, 2024 Monster Manual).
TONE: Dark urban fantasy. Gritty, specific, grounded. Not grimdark — hope and humour exist, but stakes are real.

FACTIONS: Iron Fang Consortium (smugglers/relic cartel), Argent Blades (glory-hunters), Wardens of Ash (city guard),
Serpent Choir (divine contracts), Obsidian Lotus (black market), Glass Sigil (arcane archivists),
Patchwork Saints (protectors of forgotten), Adventurers' Guild, Guild of Ashen Scrolls (fate archivists),
Tower Authority/FTA (oversight), Brother Thane's Cult.

CURRENCY: Essence Coins (EC). Kharma = crystallised faith. Legend Points (LP) = heroic fame.

DISTRICTS: Markets Infinite (Neon Row, Cobbleway Market, Floating Bazaar, Crimson Alley, Taste of Worlds),
Sanctum Quarter (Pantheon Walk, Hall of Echoes, Divine Garden),
Grand Forum (Central Plaza, Adventurer's Inn, Fountain of Echoes),
Guild Spires (Arena of Ascendance), The Warrens (Scrapworks, Night Pits, Echo Alley, Shantytown Heights, Collapsed Plaza),
Outer Wall & Gates.

WRITING RULES:
- Write DENSE, DETAILED prose. Every scene needs sensory details — sights, sounds, smells, textures.
- BOXED READ-ALOUD TEXT: Wrap all read-aloud text in italic markers: *text here*
  These are paragraphs the DM reads aloud to players. They MUST be vivid, atmospheric, 3-6 sentences each.
  Include at least 2-3 read-aloud blocks per scene.
- Give every NPC a distinctive voice, mannerism, and motivation. Include sample dialogue lines.
- Name every location specifically — no "a tavern" but "The Soot & Cinder, a cramped bar beneath the Outer Wall."
- Include environmental storytelling: graffiti, old bloodstains, discarded objects that tell a story.
- DM Notes should be practical: "If the party tries X, then Y."
- All DCs use 2024 rules. Provide specific skill names and DCs for every check.
- Write at MINIMUM 1200 words per section. More is better. This is a professional module, not a summary.

OUTPUT: Clean markdown. ## for sections, ### for subsections. *italic* for read-aloud.
No code blocks. No preamble. No sign-off. Just the module content."""


# ---------------------------------------------------------------------------
# PASS 1: Overview + Background (1 call)
# ---------------------------------------------------------------------------

async def _gen_overview(ctx: Dict) -> str:
    mission = ctx["mission"]

    # Pre-compute conditional blocks (Python 3.11 can't have backslashes in f-string expressions)
    personal_line = f"PERSONAL MISSION FOR: {ctx['personal_for']}" if ctx['personal_for'] else ""
    char_line = f"PLAYER CHARACTER SHEET:\n{ctx['player_char_block']}" if ctx['player_char_block'] else ""
    rift_list = json.dumps([r.get('location', '') + ' (' + r.get('stage', '') + ')' for r in ctx['active_rifts']]) if ctx['active_rifts'] else 'None active'
    resolved_list = json.dumps([m.get('title', '') + ' (' + m.get('faction', '') + ')' for m in ctx['recent_resolved']])

    prompt = f"""Write the ADVENTURE OVERVIEW for this mission module. This is DM-only background material.

MISSION: {mission.get('title', 'Unknown')}
FACTION: {ctx['faction']}
TIER: {ctx['tier'].upper()} | CR {ctx['cr']} | Runtime: {ctx['runtime']}
DESCRIPTION:
{mission.get('body', '')}

CLAIMED BY: {ctx['player_name']}
{personal_line}
{char_line}

FACTION NPCs (use these by name where possible):
{ctx['faction_npc_details'] or 'No specific faction NPCs available — create appropriate ones.'}

RECENT UNDERCITY NEWS (weave 1-2 of these into the plot as background or complications):
{ctx['news_memory'][:3000]}

ACTIVE RIFTS: {rift_list}

RECENTLY RESOLVED MISSIONS (for continuity):
{resolved_list}

Write ALL of the following:

## Adventure Overview

### Synopsis
Write a 3-4 paragraph detailed summary of the entire adventure from start to finish.
Include the inciting incident, the investigation, the twist/complication, the climax, and the resolution.
Name specific locations, NPCs, and events. This should read like a short story outline.

### Adventure Hook
How does the party get involved? They've claimed this contract from the mission board.
Write the exact moment they pick up the job — who contacts them, where, what's said.
Include a read-aloud block for the initial contact moment:
*The read-aloud text here, 3-5 vivid sentences about the moment the party takes the job.*

### Background: What's Really Going On
DM-only information. The FULL truth behind this mission:
- Who is really pulling the strings and why
- What happened before the party got involved
- The real stakes (beyond what the faction says)
- Connections to Undercity politics and recent events
- At least one secret that changes the mission's meaning if discovered

### Key NPCs
For EACH NPC (minimum 4-5):
- **Name** — Species, role, faction affiliation
- Physical description (2-3 vivid details)
- Personality and speech pattern (include a sample dialogue line in quotes)
- What they know, what they want, and what they'll do
- Secret motivation or hidden agenda

### Timeline: If The Party Does Nothing
Day-by-day breakdown of what happens if the party ignores this mission:
- Day 1: [specific consequence]
- Day 3: [escalation]
- Day 7: [crisis point]
- Long-term: [permanent change to the Undercity]

MINIMUM 1500 words. Be specific, not generic."""

    return await _ollama_generate(prompt, system=_SYS)


# ---------------------------------------------------------------------------
# PASS 2: Act 1 — Narrative scenes + read-aloud (1 call)
# ---------------------------------------------------------------------------

async def _gen_act1_narrative(ctx: Dict, overview: str) -> str:
    mission = ctx["mission"]
    faction_npc_names = ", ".join(n.get("name", "?") for n in ctx["faction_npcs"][:5])

    prompt = f"""You are continuing to write a mission module. Here is the overview you already wrote:

---BEGIN OVERVIEW---
{overview[:3000]}
---END OVERVIEW---

Now write ACT 1: THE BRIEFING — the narrative and scene descriptions.
Focus on ATMOSPHERE, NPC DIALOGUE, and READ-ALOUD BLOCKS.

MISSION: {mission.get('title', '')}
FACTION: {ctx['faction']}
FACTION NPCs: {faction_npc_names or 'Create appropriate ones'}

Write ALL of the following:

## Act 1: The Briefing (~30 minutes)

### Scene 1: The Summons

Write a read-aloud block for how the party is contacted/summoned:
*3-5 sentences describing the messenger, the note, the knock at the door — whatever starts the mission. Sensory details: what time of day, what the air smells like, background sounds of the Undercity.*

Then describe what the party knows at this point and any preparations they might make.

### Scene 2: The Meeting

Write the full meeting scene with the faction contact NPC:

*A detailed read-aloud block (4-6 sentences) describing the meeting location. Name the specific venue. Describe the lighting, the furniture, other patrons, background sounds, the smell of the place.*

Then write:
- The NPC's entrance/appearance (vivid physical description, 3+ details)
- Their opening dialogue (write actual quoted lines, not summaries). Example:
  The NPC leans forward. "Listen carefully, because I won't say this twice..."
- What they tell the party (the official version of the mission)
- What they deliberately withhold (noted for the DM)
- Body language cues that something is off
- NPC reactions to likely player questions (list 4-5 questions and answers)

*Another read-aloud block for a key dramatic moment in the conversation — perhaps a threat, a revelation, or an ominous warning. 3-4 sentences.*

### Scene 3: Gathering Intel

Before heading out, the party can investigate. Write:
- 2-3 specific locations they can visit for information, with vivid one-paragraph descriptions of each
- An NPC at each location with a name, description, and dialogue
- A d6 Rumour Table:

| d6 | Rumour | True/False |
|----|--------|------------|
(fill all 6 with specific, interesting rumours — half true, half false or misleading)

*A read-aloud block for the most atmospheric of these locations. 3-5 sentences.*

### Shopping & Preparation
- List 4-6 specific Undercity items available for purchase with EC prices
- At least 1 item is specifically useful for this mission (hint without spoiling)
- A vendor NPC with personality and dialogue

### DM Notes: Act 1
- Pacing: How long to spend here, when to push forward
- If players skip the briefing entirely, what happens
- Foreshadowing moments to plant (list 3 specific details)
- Alternate meeting scenarios if players are suspicious or hostile

MINIMUM 1500 words. Every scene needs at least one read-aloud block."""

    return await _ollama_generate(prompt, system=_SYS)


# ---------------------------------------------------------------------------
# PASS 3: Act 2 — Investigation narrative (1 call)
# ---------------------------------------------------------------------------

async def _gen_act2_narrative(ctx: Dict, overview: str) -> str:
    mission = ctx["mission"]
    cr = ctx["cr"]

    prompt = f"""You are continuing to write a mission module. Here is the overview:

---BEGIN OVERVIEW---
{overview[:2000]}
---END OVERVIEW---

Now write ACT 2: THE INVESTIGATION — full narrative with scenes, descriptions, and read-aloud.

MISSION: {mission.get('title', '')} | CR {cr} | TIER: {ctx['tier'].upper()}

Write ALL of the following:

## Act 2: The Investigation (~30 minutes)

### Scene 4: Entering the Area

*A long read-aloud block (5-7 sentences) describing the party arriving at the investigation area. This is a KEY atmospheric moment. Describe the district: the architecture, the lighting, the people, the sounds, the feeling of the place. Make it feel like a real location in the Undercity.*

Describe what the party sees, hears, and smells on arrival. Environmental storytelling — what details hint at the danger ahead? A discarded weapon, fresh bloodstains, nervous locals who won't make eye contact.

### Scene 5: The Search

Write a detailed investigation sequence with:
- 3 specific clue locations, each with a vivid 2-3 sentence description
- For each clue: what skill check reveals it, the DC, and what it tells the party
  - Perception DC {10 + cr // 2}: [what they find]
  - Investigation DC {11 + cr // 2}: [what they deduce]
  - Persuasion/Intimidation DC {12 + cr // 2}: [what someone tells them]
- A false lead that wastes time but is interesting
- A hidden clue that rewards creative play (no fixed DC — reward good ideas)

*Read-aloud block for the moment the party finds the most important clue. 3-4 sentences. Make it dramatic — this changes their understanding of the mission.*

### Scene 6: The Complication

An unexpected obstacle or twist appears:

*Read-aloud block introducing the complication. 4-6 sentences. Something visible, audible, tangible — not just narration. Maybe a scream from an alley, a building collapsing, a figure watching from a rooftop.*

Then write the full complication:
- What happens and why
- How it connects to the larger plot
- A moral choice or dilemma the party faces (not simple good/evil — make it grey)
- 2-3 ways the party might resolve it, each with different consequences
- If this involves minor combat: enemies with names, descriptions, and tactics

### Scene 7: The Informant

A key NPC who has vital information:

*Read-aloud block introducing this NPC in their environment. 3-5 sentences. Describe how they look, what they're doing, the space around them.*

Write:
- Full NPC description: name, species, appearance (4+ vivid details), mannerisms
- Their opening line of dialogue (in quotes)
- What they know and what they want in exchange
- 3 different approaches the party can take:
  - Persuasion path (DC {11 + cr // 2}): what they need to say/offer
  - Intimidation path (DC {13 + cr // 2}): risks and consequences
  - Deception/creative path: reward clever ideas
- The NPC's key piece of information that points to Act 3
- A parting line of dialogue that foreshadows danger

### DM Notes: Act 2
- Which clues are ESSENTIAL (party must find them) vs OPTIONAL (enhance the story)
- How to handle parties that go off-track (redirect techniques)
- Time pressure: is there a ticking clock? How to communicate urgency
- If the party threatens or attacks the informant, what happens

MINIMUM 1500 words. Emphasize atmosphere and NPC interaction."""

    return await _ollama_generate(prompt, system=_SYS)


# ---------------------------------------------------------------------------
# PASS 4: Act 2 — Mechanics supplement (1 call)
# ---------------------------------------------------------------------------

async def _gen_act2_mechanics(ctx: Dict, act2_narrative: str) -> str:
    cr = ctx["cr"]

    prompt = f"""You already wrote the Act 2 narrative. Now add MECHANICAL SUPPLEMENTS for the DM.

Here is the Act 2 narrative you wrote:
---BEGIN ACT 2---
{act2_narrative[:2500]}
---END ACT 2---

Write these additional sections to append to Act 2:

### Skill Challenge: The Investigation
Design a formal skill challenge for the investigation phase:
- **Goal**: [what the party needs to achieve]
- **Complexity**: {2 + cr // 4} successes before 3 failures
- **Primary Skills** (DC {10 + cr // 2}): Investigation, Perception, Persuasion
- **Secondary Skills** (DC {12 + cr // 2}): Stealth, Arcana, Survival, Insight
- **On Success**: The party has a clear trail + advantage on first Act 3 encounter
- **On Failure**: The trail goes cold — they stumble into Act 3 unprepared (enemies have surprise)

### Trap or Hazard
If the complication involves a trap or environmental hazard:
- **Detection**: Perception DC {12 + cr // 2}
- **Disarm/Avoid**: Thieves' Tools DC {13 + cr // 2} or Dexterity save DC {11 + cr // 2}
- **Effect**: [damage and consequences, scaled to CR {cr}]
- **Triggered**: What happens if they fail

### Minor Combat (if applicable)
If Scene 6 involves a fight:
- Enemy list with HP, AC, and attack bonuses (no full stat blocks — those go in the appendix)
- Initiative order suggestions
- Tactical notes: how these enemies fight, when they flee
- Environment: what terrain features matter in this fight

Write 400-600 words of pure mechanics. No atmosphere — that's already written."""

    return await _ollama_generate(prompt, system=_SYS)


# ---------------------------------------------------------------------------
# PASS 5: Act 3 — Combat narrative + atmosphere (1 call)
# ---------------------------------------------------------------------------

async def _gen_act3_narrative(ctx: Dict, overview: str) -> str:
    mission = ctx["mission"]
    cr = ctx["cr"]

    prompt = f"""You are continuing the module. Here is the overview:

---BEGIN OVERVIEW---
{overview[:2000]}
---END OVERVIEW---

Now write ACT 3: THE CONFRONTATION — the climactic action sequence.
This is the LONGEST and MOST DETAILED section. Focus on vivid scenes and read-aloud.

MISSION: {mission.get('title', '')} | CR {cr} | TIER: {ctx['tier'].upper()}

Write ALL of the following:

## Act 3: The Confrontation (~45 minutes)

### Scene 8: The Approach

*A LONG read-aloud block (6-8 sentences) for approaching the final location. This is the most atmospheric moment in the module. Describe the architecture, the weather/Dome conditions, signs of danger, the growing tension. Use all five senses. Make the players feel the dread.*

Then describe:
- The tactical layout: rooms/areas, doors, corridors, cover, elevation
- Lighting conditions (bright, dim, dark — affects mechanics)
- Environmental hazards (Rift residue, unstable floor, toxic fumes, etc.)
- What the party can observe from outside (Perception DC {10 + cr // 2})
- Possible entry points (front door, window, roof, sewer access, etc.)

### Scene 9: The Gauntlet

The first combat encounter — a warm-up before the boss:

*Read-aloud block (4-5 sentences) for the moment combat begins. Something triggers it — a tripwire, a guard spotting them, a sudden ambush. Make it visceral.*

Write the full encounter:
- **Enemies**: 3-5 creatures with names/descriptions (not just "3 thugs" — give them scars, weapons, attitudes)
- **Tactics**: How they fight, where they position, when they call for help
- **Terrain**: Specific features the enemies use (overturned tables, high ground, choke points)
- **Dynamic element**: Something that changes mid-fight (reinforcements, environment shifts, a hostage)
- **Surrender/capture**: What happens if the party takes prisoners — dialogue and intel they share

*Read-aloud block for a dramatic mid-combat moment: a wall collapsing, a enemy leader shouting orders, a terrible sound from deeper in the building. 3-4 sentences.*

### Scene 10: The Reckoning (Boss Encounter)

*The biggest read-aloud block in the module (6-10 sentences). The party enters the final room/arena and sees the boss for the first time. Describe everything: the space, the lighting, the boss's appearance and posture, what they're doing when interrupted, the objects in the room, the mood.*

The boss NPC:
- Full physical description (5+ vivid details — scars, clothing, weapons, posture, eyes)
- Opening dialogue line (in quotes) — they don't just attack, they TALK
- What they want and why they're doing this
- Their fighting style described in narrative terms
- A moment of vulnerability or humanity (they're not a cartoon villain)

The fight itself:
- How it begins: does the boss attack first, or try to negotiate?
- Phase 1: Boss at full power — describe their signature move narratively
- Phase 2: When bloodied (half HP) — behaviour change, new tactic, desperate move
- A non-combat victory path: what would the party need to say/do to end this without killing?

*Read-aloud block for the climax moment — when the fight turns, when the boss uses their signature ability, when something dramatic happens. 4-5 sentences.*

### DM Notes: Act 3
- Encounter balance: what to do if the party is overmatched or breezing through
- Reinforcement timing: when to add more enemies, when to stop
- Dramatic descriptions for critical hits, near-death moments, and killing blows
- Retreat rules: what happens if the party runs
- Environmental destruction: what can be broken, burned, or collapsed

MINIMUM 1800 words. This section should be the richest in the entire module."""

    return await _ollama_generate(prompt, system=_SYS)


# ---------------------------------------------------------------------------
# PASS 6: Act 3 — Stat blocks + encounter mechanics (1 call)
# ---------------------------------------------------------------------------

async def _gen_act3_mechanics(ctx: Dict, act3_narrative: str) -> str:
    cr = ctx["cr"]

    prompt = f"""You wrote the Act 3 narrative. Now write the FULL MECHANICAL DETAILS.

Here is your Act 3 narrative:
---BEGIN ACT 3---
{act3_narrative[:3000]}
---END ACT 3---

Write these sections to append to Act 3:

### Encounter 1: The Gauntlet — Stat Blocks

For each enemy in the gauntlet encounter, provide a FULL D&D 5e 2024 stat block:

**[Creature Name]** *(Medium/Large [type], [alignment])*
- **Armor Class** [AC] ([armor type])
- **Hit Points** [HP] ([hit dice])
- **Speed** [speed]
- **STR** [score] ([mod]) | **DEX** [score] ([mod]) | **CON** [score] ([mod]) | **INT** [score] ([mod]) | **WIS** [score] ([mod]) | **CHA** [score] ([mod])
- **Saving Throws** [if any]
- **Skills** [list with bonuses]
- **Senses** [darkvision, passive Perception, etc.]
- **Languages** [languages]
- **Challenge** {max(1, cr - 2)} ([XP] XP)
- **Traits**: [1-2 traits]
- **Actions**:
  - **[Attack Name]** *Melee Weapon Attack:* +[bonus] to hit, reach [ft], one target. *Hit:* [damage] [type] damage.
  - **[Second Attack/Ability]** [description]

(Write stat blocks for ALL gauntlet enemies — typically 2-3 creature types)

### Encounter 2: The Reckoning — Boss Stat Block

**[Boss Name]** *(Medium/Large [type], [alignment])*
Full stat block as above, PLUS:
- **Legendary Resistance** (1/Day): If the boss fails a saving throw, they can choose to succeed instead.
- **Signature Ability**: [Name] — [full mechanical description with damage, save DC {8 + cr // 2 + 3}, range, area]
- **Reaction**: [A reactive ability that triggers when hit or when an ally drops]
- **Lair Actions** (on initiative 20): [1-2 lair actions that affect the environment]
- **Ideal/Bond/Flaw**: For roleplay if negotiation occurs

Scale the boss to CR {cr}. HP should be approximately {50 + cr * 15}. AC should be {12 + cr // 2}.

### Environment Mechanics
- Difficult terrain areas and their effects
- Cover positions (half/three-quarters) and locations
- Hazard: [name] — triggered by [condition], DC {12 + cr // 2} [save type], [damage] on failure
- Visibility: [lighting conditions and effects on combat]
- Destructible objects: [what can be broken and what happens]

### Treasure in the Encounter Area
- Items found on enemies
- Hidden cache: [location], [Perception/Investigation DC to find], [contents]
- Boss's personal effects (may include plot-relevant documents or keys)

Write 800-1200 words of pure game mechanics."""

    return await _ollama_generate(prompt, system=_SYS)


# ---------------------------------------------------------------------------
# PASS 7: Act 4 — Resolution (1 call)
# ---------------------------------------------------------------------------

async def _gen_act4(ctx: Dict, overview: str) -> str:
    mission = ctx["mission"]

    prompt = f"""You are finishing the module. Here is the overview:

---BEGIN OVERVIEW---
{overview[:2000]}
---END OVERVIEW---

Write ACT 4: RESOLUTION — the aftermath and consequences.

MISSION: {mission.get('title', '')}
FACTION: {ctx['faction']} | CR {ctx['cr']}
REWARD: {mission.get('reward', 'Standard reward')}

Write ALL of the following:

## Act 4: Resolution (~15 minutes)

### Scene 11: The Dust Settles

*A long read-aloud block (5-7 sentences) for the moment after the climax. The adrenaline fades. Describe the scene: the aftermath of the fight, the state of the location, the silence or sounds that remain. What do the party members see when they catch their breath? Is there relief, or a new worry?*

Describe:
- What the party finds in the aftermath (documents, bodies, evidence, escape routes)
- Wounded NPCs who need help or can give information
- Environmental changes (structural damage, Rift effects fading, etc.)

### Scene 12: The Report

The party returns to their faction contact:

*Read-aloud block (4-5 sentences) for the return. Is the contact waiting anxiously? Are they surprised the party survived? Describe the location and the NPC's reaction.*

Write:
- The contact's dialogue for SUCCESS (full paragraph, in quotes, in-character)
- The contact's dialogue for FAILURE (full paragraph, in quotes, in-character)
- The contact's dialogue for PARTIAL SUCCESS (full paragraph, in quotes, in-character)
- Questions the contact asks and follow-up dialogue

### Rewards

**Standard Completion:**
- **Payment**: {mission.get('reward', 'As posted')}
- **Bonus**: [extra EC or item for exceptional play]
- **Faction Reputation**: +1 with {ctx['faction']}

**Bonus Loot** (found during the adventure):
- [Magic item 1: name, rarity, brief description, and mechanical effect]
- [Magic item 2: name, rarity, brief description, and mechanical effect]
- [Interesting non-magical item with Undercity flavour]

**Kharma Awards:**
- +1 for completing the mission
- +1 for [specific bonus condition]
- +1 for [specific bonus condition]

### Consequences

**On Full Success:**
- [Specific change #1 to the Undercity — name NPCs and locations affected]
- [Specific change #2]
- [How {ctx['faction']} benefits and what they do next]
- [How opposing factions react]

**On Failure:**
- [Specific consequence #1 — be harsh but fair]
- [Specific consequence #2]
- [What the villain/antagonist does with their victory]
- [Faction reputation loss and political fallout]

**On Partial Success:**
- [Mixed outcome — some goals achieved, some lost]
- [Lingering threat that wasn't fully resolved]

### Future Hooks
Write 3-4 detailed adventure hooks that emerge from this mission:
1. **[Hook Title]**: [2-3 sentences describing the next adventure opportunity]
2. **[Hook Title]**: [2-3 sentences]
3. **[Hook Title]**: [2-3 sentences]
4. **[Hook Title]** (if the party failed): [2-3 sentences]

### DM Notes: Resolution
- How to handle partial success (some objectives completed, some failed)
- Downtime activities that connect to this mission
- NPCs who become recurring contacts or enemies
- Long-term faction consequences (tracked between sessions)

MINIMUM 1200 words. Every interaction needs read-aloud text."""

    return await _ollama_generate(prompt, system=_SYS)


# ---------------------------------------------------------------------------
# PASS 8: Appendix (1 call)
# ---------------------------------------------------------------------------

async def _gen_appendix(ctx: Dict, overview: str) -> str:
    cr = ctx["cr"]
    mission = ctx["mission"]

    prompt = f"""You are writing the appendix for the mission module "{mission.get('title','')}".

CR: {cr} | TIER: {ctx['tier'].upper()} | FACTION: {ctx['faction']}

Write ALL of the following:

## Appendix A: Additional Stat Blocks

Write 2 additional stat blocks NOT already covered in Act 3 — supporting creatures, environmental monsters, or faction agents the party might encounter:

For each, full D&D 5e 2024 stat block format:
**[Name]** *(Size Type, Alignment)*
- AC, HP, Speed
- All six ability scores with modifiers
- Skills, Senses, Languages, CR
- Traits (1-2)
- Actions (2-3 including at least one melee and one ranged or special)

### Faction Agent Template
A generic stat block for {ctx['faction']} rank-and-file agents (CR {max(1, cr - 3)}):
- Represents the common operatives the party might encounter in the Undercity
- Include faction-specific flavour in abilities and equipment

## Appendix B: Loot Table

| d8 | Item | Value | Description |
|----|------|-------|-------------|
(fill 8 rows with items appropriate for CR {cr}. At least 2 should be magical or unusual. All priced in EC. Include a 1-sentence description for each.)

## Appendix C: Random Encounters (d8)

For travel to/from the mission site through the Undercity:

| d8 | Encounter | Type |
|----|-----------|------|
(fill 8 encounters — mix of combat, social, environmental, and weird. Each gets a 2-3 sentence description including NPCs, setting, and resolution options.)

## Appendix D: Handouts

### Handout 1: [Document Title]
Write the FULL TEXT of an in-game document the DM can give to players.
This could be: a letter, a contract, a journal entry, a wanted poster, a map description, a coded message.
Make it flavourful and in-character. 150-250 words.

### Handout 2: [Document Title]
A second handout — different type from the first.
150-250 words, fully in-character.

## Appendix E: Location Descriptions

For each major location in the module (minimum 3):
- **[Location Name]**: 3-4 sentence atmospheric description
- Key features, exits, notable objects
- Possible perception checks and what they reveal

MINIMUM 1200 words."""

    return await _ollama_generate(prompt, system=_SYS)


# ---------------------------------------------------------------------------
# FACT-CHECK AGENT — validates generated content against world state
# ---------------------------------------------------------------------------

_FACTCHECK_SYS = """\
You are a continuity editor for a D&D campaign called Tower of Last Chance.

Your job is to CHECK a generated mission section against the WORLD STATE provided,
fix any errors, adjust NPC attitudes based on faction standing, and return the corrected text.

CHECK FOR:
1. DEAD NPCs mentioned as alive or active — replace with alive NPCs or remove.
2. Wrong faction assignments — NPCs must belong to their correct faction.
3. Locations that don't exist in the setting — replace with real Undercity locations.
4. Faction names that don't exist — only use the listed factions.
5. NPCs doing things inconsistent with their known role/motivation.
6. Any reference to NPCs or events that contradict completed mission outcomes.

ATTITUDE ADJUSTMENTS (based on FACTION STANDING):
7. NPCs from DETESTED factions: openly hostile. They sneer, threaten, refuse to help,
   demand payment upfront, insult the party, or set traps. Rewrite their dialogue
   to reflect active contempt. They do NOT cooperate willingly.
8. NPCs from HATED factions: cold and antagonistic. Short answers, veiled threats,
   doors slammed, information withheld. They help only if forced or bribed.
9. NPCs from DISLIKED factions: reluctant and suspicious. They cooperate but with
   visible distrust — side-eyes, clipped speech, unfriendly body language.
10. NPCs from NEUTRAL factions: professional, transactional. No warmth, no hostility.
11. NPCs from FRIENDLY or above: cooperative, warm, may offer extra help or tips.
    The warmer the standing, the more generous they are.

When adjusting dialogue, change the NPC's TONE and BODY LANGUAGE, not the information
they provide (unless they would realistically withhold it at that standing level).
A Hated faction NPC might still give the quest briefing but through gritted teeth.
A Detested faction NPC might refuse to speak directly and send a messenger instead.

CRITICAL RULES:
- Output the CORRECTED section. Not a list of changes, not commentary.
- If nothing needs fixing, output the section unchanged.
- Do NOT add new content beyond brief attitude adjustments to existing dialogue.
- Keep all formatting intact.
- No preamble, no commentary. Output only the corrected text."""


async def _fact_check_section(section_name: str, content: str, ctx: Dict) -> str:
    """Validate a generated section against current world state and fix errors."""
    if not content or len(content.split()) < 50:
        return content

    # Build world state reference
    dead_npcs = []
    alive_npcs = []
    try:
        npc_file = DOCS_DIR / "npc_roster.json"
        graveyard_file = DOCS_DIR / "npc_graveyard.json"
        if npc_file.exists():
            roster = json.loads(npc_file.read_text(encoding="utf-8"))
            alive_npcs = [f"{n['name']} ({n.get('faction', '?')})" for n in roster
                         if n.get('status') in ('alive', 'injured')]
        if graveyard_file.exists():
            graveyard = json.loads(graveyard_file.read_text(encoding="utf-8"))
            dead_npcs = [f"{n['name']} ({n.get('faction', '?')}) — {n.get('cause_of_death', 'deceased')}"
                        for n in graveyard]
    except Exception:
        pass

    # Build recent outcomes reference
    outcomes_ref = ""
    try:
        outcomes_file = DOCS_DIR / "mission_outcomes.json"
        if outcomes_file.exists():
            outcomes = json.loads(outcomes_file.read_text(encoding="utf-8"))[-5:]
            if outcomes:
                lines = []
                for o in outcomes:
                    lines.append(f"- {o.get('mission_title', '?')} ({o.get('result', '?')}): "
                                f"killed={o.get('npcs_killed', 'none')}, "
                                f"decisions={o.get('key_decisions', 'none')}")
                outcomes_ref = "RECENT MISSION OUTCOMES:\n" + "\n".join(lines)
    except Exception:
        pass

    # Detect opposing faction from mission data
    mission = ctx.get("mission", {})
    opposing = mission.get("opposing_faction", "")
    opposing_note = ""
    if opposing:
        opposing_note = f"\nNOTE: This mission OPPOSES {opposing}. Ensure the content reflects tension with this faction."

    from src.faction_reputation import KNOWN_FACTIONS, get_all_reputations, TIER_EMOJI
    faction_list = ", ".join(KNOWN_FACTIONS)

    # Build faction standing block for attitude adjustments
    standings = get_all_reputations()
    standing_lines = []
    for fname, fdata in sorted(standings.items()):
        tier = fdata.get("tier", "Neutral")
        emoji = TIER_EMOJI.get(tier, "")
        standing_lines.append(f"  {emoji} {fname}: {tier}")
    standing_block = "\n".join(standing_lines)

    world_state = f"""WORLD STATE REFERENCE:

VALID FACTIONS (ONLY these exist): {faction_list}

FACTION STANDINGS (party reputation — use for NPC attitude adjustments):
{standing_block}

DEAD NPCs (do NOT reference as alive):
{chr(10).join(dead_npcs) if dead_npcs else 'None currently.'}

ALIVE NPCs (available for use):
{chr(10).join(alive_npcs[:30]) if alive_npcs else 'Roster empty.'}

{outcomes_ref}
{opposing_note}"""

    prompt = f"""Check this {section_name} against the world state. Fix any errors.

{world_state}

---BEGIN SECTION---
{content[:6000]}
---END SECTION---

Output the corrected section. No preamble."""

    result = await _ollama_generate(prompt, system=_FACTCHECK_SYS, timeout=300.0)
    if not result or len(result.split()) < len(content.split()) * 0.7:
        logger.warning(f"📖 Fact-check for {section_name} lost content — using original")
        return content
    return result


# ---------------------------------------------------------------------------
# FLOW EDITOR — restructures content for DM reading order
# ---------------------------------------------------------------------------

_FLOW_SYS = """\
You are a professional D&D module editor. Your job is to restructure a raw draft
so a DM can read it straight through at the table, scene by scene, without
flipping back and forth.

THINK IN SCENES AND LOCATIONS.
Each scene is a COMPLETE UNIT built around ONE place or ONE encounter.
Everything the DM needs for that scene stays together in this order:

  SCENE UNIT ORDER (repeat for each scene):
  1. SCENE HEADING (### Scene N: Title)
  2. READ-ALOUD block — the DM reads this to players as they arrive/enter.
     (*italic text* = read-aloud. It comes FIRST so the DM sets the scene
     before doing anything else.)
  3. WHAT THE DM KNOWS — background context for this specific scene only.
  4. NPCs PRESENT — name, appearance, personality, opening dialogue.
     Introduce each NPC BEFORE any dialogue from them.
  5. WHAT HAPPENS — the events, conversations, and choices in this scene.
     Include NPC dialogue in natural order within the events.
  6. SKILL CHECKS & MECHANICS — DCs, saves, skill challenges for this scene.
     These come AFTER the narrative they support, not before.
  7. TABLES — rumour tables, loot, random encounters stay with their scene.
  8. DM NOTES — contingencies, "if the party does X", pacing tips.
     These come LAST in the scene.
  9. TRANSITION — one sentence bridging to the next scene/location.
     "When the party leaves the tavern..." or "The trail leads to..."

BRANCHING:
If a scene has multiple paths (e.g. three NPCs to visit, or sneak vs. fight),
structure each branch as a sub-section within the scene:
  ### Scene 5: Gathering Intel
  #### Option A: The Soot & Cinder Tavern
  [complete unit for this option]
  #### Option B: The Scrapworks
  [complete unit for this option]

STAT BLOCKS:
- Minor stat references (HP, AC, attack) stay inline with their encounter.
- Full stat blocks go AFTER the scene narrative, before DM Notes.
- Boss stat blocks go after the boss encounter narrative.

CRITICAL RULES:
- Do NOT rewrite, shorten, or remove ANY content. Keep ALL text, dialogue,
  stats, details, and tables. Just reorganise them.
- Do NOT add new content beyond brief 1-sentence transition bridges between scenes.
- Do NOT change voice, tone, or style.
- Keep all markdown formatting (##, ###, **bold**, *italic*, tables, lists) intact.
- Output the COMPLETE restructured section. If you omit content, you have failed.
- No preamble, no commentary. Output only the restructured section."""


async def _flow_edit_section(section_name: str, content: str) -> str:
    """Restructure a section for DM reading flow without changing content."""
    if not content or len(content.split()) < 100:
        return content  # too short to need flow editing

    # Trim to fit 8K context — send at most ~5000 words
    words = content.split()
    if len(words) > 5000:
        content = " ".join(words[:5000])

    prompt = f"""Restructure this {section_name} for optimal DM reading flow.

ORGANISE BY SCENE/LOCATION:
Group everything that happens in ONE place into ONE complete scene unit.
Within each scene: read-aloud → DM context → NPCs → events → checks → DM notes → transition.
If a scene has branches (multiple options), use sub-sections for each branch.
Ensure natural transitions between scenes: "The party heads to..." or "Following the lead..."

Keep ALL content — just reorganise it into scene units.

---BEGIN SECTION---
{content}
---END SECTION---

Output the restructured section now. No preamble."""

    result = await _ollama_generate(prompt, system=_FLOW_SYS, timeout=420.0)
    if not result or len(result.split()) < len(words) * 0.7:
        # Flow edit lost too much content — use original
        logger.warning(f"📖 Flow edit for {section_name} lost content ({len(result.split())}w vs {len(words)}w) — using original")
        return content
    return result


# ---------------------------------------------------------------------------
# Full module generation — sequential multi-pass
# ---------------------------------------------------------------------------

async def generate_module(mission: Dict, player_name: str) -> Optional[Path]:
    """
    Generate a complete D&D 5e 2024 mission module as a .docx file.
    Uses 8-10 sequential Ollama calls that build on each other.
    Returns the path to the generated file, or None on failure.
    """
    title_str = mission.get('title', '?')
    faction_str = mission.get('faction', '?')
    tier_str = mission.get('tier', '?').upper()
    cr_val = TIER_CR_MAP.get(mission.get('tier', 'standard'), DEFAULT_CR)
    logger.info(f"📖 ════════════════════════════════════════")
    logger.info(f"📖 MODULE GENERATION STARTED")
    logger.info(f"📖   Mission: {title_str}")
    logger.info(f"📖   Faction: {faction_str} | Tier: {tier_str} | CR: {cr_val}")
    logger.info(f"📖   Claimed by: {player_name}")
    logger.info(f"📖   Method: 8 content + 5 fact-check + 4 flow editing passes")
    logger.info(f"📖 ════════════════════════════════════════")
    start_time = datetime.now()

    OUTPUT_DIR.mkdir(exist_ok=True)

    logger.info("📖 Gathering campaign context...")
    ctx = gather_context(mission, player_name)
    n_faction_npcs = len(ctx['faction_npcs'])
    n_key_npcs = len(ctx['key_npcs'])
    n_rifts = len(ctx['active_rifts'])
    n_resolved = len(ctx['recent_resolved'])
    news_len = len(ctx['news_memory'])
    logger.info(
        f"📖 Context loaded: {n_faction_npcs} faction NPCs, {n_key_npcs} key NPCs, "
        f"{n_rifts} active rifts, {n_resolved} recent missions, {news_len} chars news"
    )

    # ── SEQUENTIAL GENERATION ──
    # Each pass builds on previous passes for coherent, detailed content.
    total_words = 0
    section_stats = []  # (name, words, seconds)

    def _log_pass(name: str, text: str, pass_start):
        nonlocal total_words
        elapsed = (datetime.now() - pass_start).total_seconds()
        words = len(text.split()) if text else 0
        total_words += words
        status = f"{words} words" if text else "EMPTY"
        section_stats.append((name, words, elapsed))
        overall = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"📖 │ {name}: {status} in {elapsed:.0f}s "
            f"(total: {total_words} words, {overall:.0f}s elapsed)"
        )

    # Pass 1: Overview (everything else depends on this)
    logger.info("📖 ┌─ Pass 1/8: Overview + Background")
    t = datetime.now()
    overview = await _gen_overview(ctx)
    _log_pass("Overview", overview, t)
    if not overview:
        logger.error("📖 └─ Overview generation failed — aborting module")
        return None

    # Pass 2: Act 1 narrative (depends on overview)
    logger.info("📖 ├─ Pass 2/8: Act 1 — Briefing scenes & dialogue")
    t = datetime.now()
    act1 = await _gen_act1_narrative(ctx, overview)
    _log_pass("Act 1 narrative", act1, t)

    # Pass 3: Act 2 narrative (depends on overview)
    logger.info("📖 ├─ Pass 3/8: Act 2 — Investigation scenes & NPCs")
    t = datetime.now()
    act2_narr = await _gen_act2_narrative(ctx, overview)
    _log_pass("Act 2 narrative", act2_narr, t)

    # Pass 4: Act 2 mechanics (depends on act 2 narrative)
    logger.info("📖 ├─ Pass 4/8: Act 2 — Skill challenges & traps")
    t = datetime.now()
    act2_mech = await _gen_act2_mechanics(ctx, act2_narr)
    _log_pass("Act 2 mechanics", act2_mech, t)

    # Combine act 2
    act2 = (act2_narr or "") + "\n\n" + (act2_mech or "")

    # Pass 5: Act 3 narrative (depends on overview)
    logger.info("📖 ├─ Pass 5/8: Act 3 — Combat scenes & boss encounter")
    t = datetime.now()
    act3_narr = await _gen_act3_narrative(ctx, overview)
    _log_pass("Act 3 narrative", act3_narr, t)

    # Pass 6: Act 3 mechanics (depends on act 3 narrative)
    logger.info("📖 ├─ Pass 6/8: Act 3 — Stat blocks & encounter balance")
    t = datetime.now()
    act3_mech = await _gen_act3_mechanics(ctx, act3_narr)
    _log_pass("Act 3 mechanics", act3_mech, t)

    # Combine act 3
    act3 = (act3_narr or "") + "\n\n" + (act3_mech or "")

    # Pass 7: Act 4 (depends on overview)
    logger.info("📖 ├─ Pass 7/8: Act 4 — Resolution & consequences")
    t = datetime.now()
    act4 = await _gen_act4(ctx, overview)
    _log_pass("Act 4 resolution", act4, t)

    # Pass 8: Appendix (depends on overview)
    logger.info("📖 ├─ Pass 8/8: Appendix — Stat blocks, loot, handouts")
    t = datetime.now()
    appendix = await _gen_appendix(ctx, overview)
    _log_pass("Appendix", appendix, t)

    if not any([act1, act2, act3, act4]):
        logger.error("📖 └─ All act generations returned empty — aborting")
        return None

    elapsed_gen = (datetime.now() - start_time).total_seconds()
    # Summary table
    logger.info(f"📖 ────────────────────────────────────────")
    logger.info(f"📖 CONTENT GENERATION COMPLETE")
    logger.info(f"📖   Total: {total_words} words in {elapsed_gen:.0f}s ({elapsed_gen/60:.1f} min)")
    for sname, swords, ssec in section_stats:
        marker = "✅" if swords > 0 else "❌"
        logger.info(f"📖   {marker} {sname}: {swords}w / {ssec:.0f}s")
    logger.info(f"📖 ────────────────────────────────────────")

    # ── FACT-CHECK PASS ──
    # Validate content against world state: dead NPCs, wrong factions, contradictions
    logger.info(f"📖 ══ FACT-CHECK PASS ══")
    logger.info(f"📖 Validating against world state (dead NPCs, factions, outcomes)...")

    fc_sections = [
        ("Overview", overview),
        ("Act 1", act1),
        ("Act 2", act2),
        ("Act 3", act3),
        ("Act 4", act4),
    ]
    fc_results = []
    for idx, (name, content) in enumerate(fc_sections, 1):
        if not content:
            fc_results.append(content)
            continue
        logger.info(f"📖 ├─ Fact-check {idx}/5: {name}")
        t = datetime.now()
        checked = await _fact_check_section(name, content, ctx)
        elapsed = (datetime.now() - t).total_seconds()
        orig_words = len(content.split())
        new_words = len(checked.split()) if checked else 0
        changed = "(corrections applied)" if checked != content else "(no changes)"
        logger.info(f"📖 │ {name} fact-check: {orig_words}w → {new_words}w in {elapsed:.0f}s {changed}")
        fc_results.append(checked)

    overview, act1, act2, act3, act4 = fc_results
    logger.info(f"📖 Fact-check complete")
    logger.info(f"📖 ────────────────────────────────────────")

    # Save raw pre-flow content for comparison
    raw_dir = OUTPUT_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    title_safe = "".join(c if c.isalnum() or c in " -_" else "" for c in mission.get("title", "Unknown")).strip().replace(" ", "_")
    raw_ts = datetime.now().strftime("%Y%m%d_%H%M")
    try:
        (raw_dir / f"RAW_{title_safe}_{raw_ts}.md").write_text(
            f"# {mission.get('title', '?')} (RAW — pre-flow)\n\n"
            f"## Overview\n{overview}\n\n"
            f"## Act 1\n{act1}\n\n"
            f"## Act 2\n{act2}\n\n"
            f"## Act 3\n{act3}\n\n"
            f"## Act 4\n{act4}\n\n"
            f"## Appendix\n{appendix}\n",
            encoding="utf-8"
        )
        logger.info(f"📖 Raw content saved to generated_modules/raw/")
    except Exception as e:
        logger.warning(f"📖 Could not save raw content: {e}")

    # ── FLOW EDITING ──
    # Restructure each act for DM reading order: read-aloud → scene → mechanics → DM notes
    logger.info(f"📖 ══ FLOW EDITING PASS ══")
    logger.info(f"📖 Restructuring acts for DM reading flow...")

    flow_sections = [
        ("Act 1", act1),
        ("Act 2", act2),
        ("Act 3", act3),
        ("Act 4", act4),
    ]
    flow_results = []
    for idx, (name, content) in enumerate(flow_sections, 1):
        if not content:
            flow_results.append(content)
            continue
        logger.info(f"📖 ├─ Flow pass {idx}/4: {name}")
        t = datetime.now()
        flowed = await _flow_edit_section(name, content)
        elapsed = (datetime.now() - t).total_seconds()
        orig_words = len(content.split())
        new_words = len(flowed.split()) if flowed else 0
        logger.info(f"📖 │ {name} flow: {orig_words}w → {new_words}w in {elapsed:.0f}s")
        flow_results.append(flowed)

    act1, act2, act3, act4 = flow_results

    elapsed_flow = (datetime.now() - start_time).total_seconds()
    logger.info(f"📖 Flow editing complete — {elapsed_flow:.0f}s total elapsed")
    logger.info(f"📖 ────────────────────────────────────────")
    logger.info(f"📖 Building .docx file...")

    # ── Build .docx ──
    title = mission.get("title", "Unknown Mission")
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip().replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"MODULE_{safe_title}_{timestamp}.docx"
    output_path = OUTPUT_DIR / filename

    payload = {
        "title": title,
        "faction": ctx["faction"],
        "tier": ctx["tier"],
        "cr": ctx["cr"],
        "runtime": ctx["runtime"],
        "player_name": player_name,
        "personal_for": ctx["personal_for"],
        "reward": mission.get("reward", "As posted"),
        "faction_color": ctx["faction_color"],
        "sections": {
            "overview": overview or "*(Generation failed — fill in manually)*",
            "act1": act1 or "*(Generation failed — fill in manually)*",
            "act2": act2 or "*(Generation failed — fill in manually)*",
            "act3": act3 or "*(Generation failed — fill in manually)*",
            "act4": act4 or "*(Generation failed — fill in manually)*",
            "appendix": appendix or "*(Generation failed — fill in manually)*",
        },
        "output_path": str(output_path),
    }

    payload_path = OUTPUT_DIR / f"_payload_{timestamp}.json"
    try:
        payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.error(f"📖 Failed to write payload JSON: {e}")
        return None

    try:
        result = subprocess.run(
            ["node", str(BUILDER_SCRIPT), str(payload_path)],
            capture_output=True, text=True, timeout=60,
            cwd=str(BUILDER_SCRIPT.parent),
        )
        if result.returncode != 0:
            logger.error(f"📖 Node.js builder failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
            return None
        logger.info(f"📖 .docx built: {output_path.name}")
    except subprocess.TimeoutExpired:
        logger.error("📖 Node.js builder timed out (60s)")
        return None
    except FileNotFoundError:
        logger.error("📖 Node.js not found — is it installed and on PATH?")
        return None
    except Exception as e:
        logger.error(f"📖 Node.js builder error: {e}")
        return None
    finally:
        try:
            payload_path.unlink(missing_ok=True)
        except Exception:
            pass

    if not output_path.exists():
        logger.error(f"📖 Expected output file not found: {output_path}")
        return None

    total_time = (datetime.now() - start_time).total_seconds()
    size_kb = output_path.stat().st_size // 1024
    logger.info(f"📖 Module complete: {output_path.name} ({size_kb}KB) in {total_time:.0f}s")

    # Copy to missions archive folder
    missions_dir = OUTPUT_DIR / "missions"
    missions_dir.mkdir(exist_ok=True)
    try:
        import shutil
        archive_path = missions_dir / output_path.name
        shutil.copy2(str(output_path), str(archive_path))
        logger.info(f"📖 Archived to missions/{output_path.name}")
    except Exception as e:
        logger.warning(f"📖 Could not archive to missions folder: {e}")

    return output_path
