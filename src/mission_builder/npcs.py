"""
npcs.py — NPC generation patterns and dialogue helpers.

Provides:
- NPC roster loading and filtering
- Faction leader lookup
- NPC context formatting for prompts
- Dialogue template generation
- Secret and motivation patterns
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List, Dict, Optional

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "campaign_docs"

# Canonical faction leader names — used as fallback if not in roster
FACTION_LEADERS = {
    "iron fang consortium": "Serrik Dhal",
    "iron fang": "Serrik Dhal",
    "consortium": "Serrik Dhal",
    "argent blades": "Lady Cerys Valemont",
    "wardens of ash": "Captain Havel Korin",
    "wardens": "Captain Havel Korin",
    "serpent choir": "High Apostle Yzura",
    "choir": "High Apostle Yzura",
    "obsidian lotus": "The Widow",
    "lotus": "The Widow",
    "glass sigil": "Senior Archivist Pell",
    "sigil": "Senior Archivist Pell",
    "adventurers guild": "Mari Fen",
    "adventurers' guild": "Mari Fen",
    "guild of ashen scrolls": "Eir Velan",
    "ashen scrolls": "Eir Velan",
    "tower authority": "Director Myra Kess",
    "fta": "Director Myra Kess",
    "fulcrum tower authority": "Director Myra Kess",
    "wizards tower": "Archmage Yaulderna Silverstreak",
    "wizard tower": "Archmage Yaulderna Silverstreak",
    "patchwork saints": "Pol Greaves",  # Field Captain, closest to leader
    "saints": "Pol Greaves",
    "brother thane's cult": "Brother Thane",
    "thane's cult": "Brother Thane",
    "the returned": "Brother Thane",
}

# Leadership rank keywords — used to identify leaders in roster
LEADER_RANKS = [
    "guildmaster", "commander", "captain", "director", "archmage",
    "high apostle", "mastermind", "senior archivist", "archivist first class",
    "prophet", "head of", "leader",
]


def load_npc_roster() -> List[dict]:
    """Load the NPC roster from MySQL (falls back to npc_roster.json)."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq(
            "SELECT name, faction, role, location, status, data_json FROM npcs "
            "WHERE status IN ('alive','injured') ORDER BY name"
        ) or []
        if rows:
            npcs = []
            for row in rows:
                npc = {"name": row["name"], "faction": row["faction"],
                       "role": row["role"], "location": row["location"], "status": row["status"]}
                dj = row.get("data_json") or {}
                if isinstance(dj, str):
                    try: dj = json.loads(dj)
                    except: dj = {}
                npc.update(dj)
                npcs.append(npc)
            return npcs
    except Exception:
        pass
    # Fallback
    roster_file = DOCS_DIR / "npc_roster.json"
    if not roster_file.exists():
        return []
    try:
        return json.loads(roster_file.read_text(encoding="utf-8"))
    except Exception:
        return []


def get_faction_leader(faction: str) -> Optional[dict]:
    """
    Get the faction leader NPC from the roster.
    
    Tries multiple methods:
    1. Look for known leader name in roster
    2. Look for leadership rank keywords
    3. Return None if not found (caller should use fallback name)
    """
    roster = load_npc_roster()
    faction_lower = faction.lower().strip()
    
    # Get canonical leader name
    canonical_name = None
    for key, name in FACTION_LEADERS.items():
        if key in faction_lower or faction_lower in key:
            canonical_name = name.lower()
            break
    
    # Search roster for faction members
    faction_npcs = []
    for npc in roster:
        npc_faction = npc.get("faction", "").lower()
        if faction_lower in npc_faction or any(k in npc_faction for k in [faction_lower]):
            if npc.get("status") == "alive":
                faction_npcs.append(npc)
    
    # First: look for canonical leader by name
    if canonical_name:
        for npc in faction_npcs:
            if canonical_name in npc.get("name", "").lower():
                return npc
    
    # Second: look for leadership rank keywords
    for npc in faction_npcs:
        rank = npc.get("rank", "").lower()
        for keyword in LEADER_RANKS:
            if keyword in rank:
                return npc
    
    # Third: look in full roster by canonical name (leader might have faction listed differently)
    if canonical_name:
        for npc in roster:
            if canonical_name in npc.get("name", "").lower():
                if npc.get("status") == "alive":
                    return npc
    
    return None


def get_faction_leader_name(faction: str) -> str:
    """
    Get the faction leader's name, from roster or fallback.
    
    Always returns a name — uses canonical fallback if not in roster.
    """
    leader = get_faction_leader(faction)
    if leader:
        return leader.get("name", "Unknown Leader")
    
    # Fallback to canonical names
    faction_lower = faction.lower().strip()
    for key, name in FACTION_LEADERS.items():
        if key in faction_lower or faction_lower in key:
            return name
    
    return f"the {faction} leader"


def get_npcs_by_faction(faction: str, alive_only: bool = True) -> List[dict]:
    """Get all NPCs belonging to a faction."""
    roster = load_npc_roster()
    faction_lower = faction.lower()
    
    matches = []
    for npc in roster:
        if faction_lower in npc.get("faction", "").lower():
            if alive_only and npc.get("status") != "alive":
                continue
            matches.append(npc)
    
    return matches


def get_npc_by_name(name: str) -> Optional[dict]:
    """Find a specific NPC by name."""
    roster = load_npc_roster()
    name_lower = name.lower()
    
    for npc in roster:
        if name_lower in npc.get("name", "").lower():
            return npc
    
    return None


def get_npcs_by_location(location: str) -> List[dict]:
    """Get NPCs at a specific location."""
    roster = load_npc_roster()
    location_lower = location.lower()
    
    matches = []
    for npc in roster:
        npc_location = npc.get("location", "").lower()
        if location_lower in npc_location or npc_location in location_lower:
            matches.append(npc)
    
    return matches


def format_npc_summary(npc: dict) -> str:
    """Format a single NPC as a summary line."""
    name = npc.get("name", "Unknown")
    species = npc.get("species", "?")
    faction = npc.get("faction", "?")
    rank = npc.get("rank", "?")
    motivation = npc.get("motivation", "Unknown motivation")
    location = npc.get("location", "Unknown")
    secret = npc.get("secret", "None known")
    
    return (
        f"- **{name}** ({species}, {faction}, {rank}): {motivation}. "
        f"Location: {location}. Secret: {secret}."
    )


def format_npc_block(npcs: List[dict]) -> str:
    """Format a list of NPCs as a context block for prompts."""
    if not npcs:
        return "(No roster NPCs available.)"
    
    return "\n".join(format_npc_summary(npc) for npc in npcs)


def get_relevant_npcs(
    faction: str,
    faction_count: int = 3,
    other_count: int = 2,
) -> List[dict]:
    """
    Get relevant NPCs for a mission context.
    
    Prioritizes:
    1. Faction leader (always included if exists)
    2. Other NPCs from the posting faction
    3. Some NPCs from other factions
    """
    roster = load_npc_roster()
    faction_lower = faction.lower()
    
    # Get faction leader first
    leader = get_faction_leader(faction)
    
    faction_npcs = []
    other_npcs = []
    
    for npc in roster:
        if npc.get("status") != "alive":
            continue
        
        # Skip leader — we'll add them first
        if leader and npc.get("name") == leader.get("name"):
            continue
        
        if faction_lower in npc.get("faction", "").lower():
            faction_npcs.append(npc)
        else:
            other_npcs.append(npc)
    
    # Randomize selection within limits
    random.shuffle(faction_npcs)
    random.shuffle(other_npcs)
    
    # Build result: leader first, then faction NPCs, then others
    result = []
    if leader:
        result.append(leader)
        faction_count -= 1  # Leader counts toward faction count
    
    result.extend(faction_npcs[:faction_count])
    result.extend(other_npcs[:other_count])
    
    return result


# NPC personality trait templates
PERSONALITY_TRAITS = {
    "aggressive": ["hostile", "confrontational", "impatient", "territorial"],
    "cautious": ["nervous", "paranoid", "calculating", "reserved"],
    "friendly": ["welcoming", "talkative", "curious", "helpful"],
    "deceptive": ["smooth-talking", "evasive", "charming", "two-faced"],
    "professional": ["businesslike", "efficient", "formal", "detached"],
    "desperate": ["pleading", "frantic", "reckless", "unstable"],
}

# Dialogue style templates
DIALOGUE_STYLES = {
    "formal": {
        "greetings": ["Good day.", "You are expected.", "State your business."],
        "refusals": ["I cannot discuss that.", "That is not my concern.", "You overstep."],
        "agreements": ["Very well.", "It shall be done.", "Consider it arranged."],
    },
    "street": {
        "greetings": ["Yeah?", "What d'you want?", "Make it quick."],
        "refusals": ["Not my problem.", "Get lost.", "I don't know nothin'."],
        "agreements": ["Fine, whatever.", "You got it.", "Deal."],
    },
    "scholarly": {
        "greetings": ["Ah, a visitor.", "How may I assist?", "Fascinating timing."],
        "refusals": ["That knowledge is restricted.", "I cannot verify that claim.", "Insufficient evidence."],
        "agreements": ["An acceptable arrangement.", "Your logic is sound.", "Proceed as discussed."],
    },
    "religious": {
        "greetings": ["Blessings upon you.", "The gods see your arrival.", "Peace be with you."],
        "refusals": ["That path leads to darkness.", "I am bound by my vows.", "The faith forbids it."],
        "agreements": ["May it be so.", "The divine will guides us.", "Your devotion is noted."],
    },
    "criminal": {
        "greetings": ["You weren't followed?", "Speak freely.", "I know why you're here."],
        "refusals": ["Too hot right now.", "That's suicide.", "Not for any price."],
        "agreements": ["Consider it handled.", "You didn't hear this from me.", "We have an understanding."],
    },
}


def get_dialogue_samples(style: str = "formal") -> dict:
    """Get sample dialogue lines for an NPC style."""
    return DIALOGUE_STYLES.get(style.lower(), DIALOGUE_STYLES["formal"])


def get_personality_descriptors(personality_type: str, count: int = 2) -> List[str]:
    """Get personality descriptor words."""
    traits = PERSONALITY_TRAITS.get(personality_type.lower(), PERSONALITY_TRAITS["professional"])
    return random.sample(traits, min(count, len(traits)))


# Secret templates for mission-related NPCs
SECRET_TEMPLATES = [
    "is secretly working for {opposing_faction}",
    "knows more than they're telling about {mission_subject}",
    "has a personal stake in the outcome — they're {connection}",
    "is being blackmailed by {antagonist}",
    "used to be {past_role} before their current position",
    "is planning to betray {faction} once they get what they need",
    "witnessed {crime} but fears for their life",
    "has a family member involved with {complication}",
    "is actually {disguised_identity} in disguise",
    "owes a debt to {creditor} that could be leveraged",
]


def generate_npc_secret(
    opposing_faction: str = "an enemy faction",
    mission_subject: str = "the mission objective",
    connection: str = "related to the victim",
    antagonist: str = "the antagonist",
    past_role: str = "a criminal",
    faction: str = "their faction",
    crime: str = "the original crime",
    complication: str = "the complication",
    disguised_identity: str = "someone else entirely",
    creditor: str = "a crime boss",
) -> str:
    """Generate a random NPC secret using templates."""
    template = random.choice(SECRET_TEMPLATES)
    
    return template.format(
        opposing_faction=opposing_faction,
        mission_subject=mission_subject,
        connection=connection,
        antagonist=antagonist,
        past_role=past_role,
        faction=faction,
        crime=crime,
        complication=complication,
        disguised_identity=disguised_identity,
        creditor=creditor,
    )


# Motivation templates
MOTIVATION_TEMPLATES = {
    "greed": ["wants money", "seeks profit", "looking for the big score"],
    "power": ["wants influence", "seeks control", "building their power base"],
    "revenge": ["wants payback", "seeking justice", "has a score to settle"],
    "protection": ["protecting family", "safeguarding secrets", "covering for someone"],
    "ideology": ["true believer", "devoted to the cause", "zealot"],
    "survival": ["just trying to get by", "in over their head", "desperate"],
    "loyalty": ["faithful to their boss", "devoted to the faction", "honor-bound"],
    "ambition": ["climbing the ladder", "proving themselves", "seeking recognition"],
}


def get_motivation_descriptors(motivation_type: str) -> List[str]:
    """Get motivation descriptor phrases."""
    return MOTIVATION_TEMPLATES.get(motivation_type.lower(), MOTIVATION_TEMPLATES["survival"])


def build_npc_prompt_block(
    faction: str,
    mission_type: str,
    include_antagonist: bool = True,
) -> str:
    """
    Build an NPC context block for AI prompts.
    
    Includes relevant roster NPCs and guidance for creating new ones.
    """
    relevant = get_relevant_npcs(faction)
    npc_block = format_npc_block(relevant)
    
    # Get faction leader name for reference
    leader_name = get_faction_leader_name(faction)
    
    lines = [
        f"FACTION LEADER: {leader_name}",
        "",
        "AVAILABLE ROSTER NPCs (use these if appropriate):",
        npc_block,
        "",
        "NPC DESIGN GUIDELINES:",
        "- Maximum 4-5 named NPCs in a module",
        "- Each NPC must serve a MECHANICAL purpose:",
        "  - Quest-giver: briefs the party, provides mission details",
        "  - Informant: knows something useful, requires convincing",
        "  - Ally: can help in combat or provide resources",
        "  - Obstacle: blocks progress unless dealt with",
        "  - Antagonist: the opposition, may be reasoned with or fought",
        "",
        "NPC FORMAT:",
        "- **Name** (Species, Faction, Role)",
        "- **Motivation**: What they want",
        "- **Secret**: What they're hiding (if any)",
        "- **Personality**: 2-3 descriptors",
        "- **Key Dialogue**: 2-3 sample lines (NO monologues)",
        "",
    ]
    
    if include_antagonist:
        lines.extend([
            "ANTAGONIST REQUIREMENTS:",
            "- Clear motivation (not 'evil for evil's sake')",
            "- Connection to faction politics or recent events",
            "- At least one non-combat resolution option",
            "- Full stat block if combat is possible",
        ])
    
    return "\n".join(lines)


def format_quest_giver_guidance(faction: str) -> str:
    """
    Generate quest-giver roleplay guidance.
    
    Prioritizes faction leader, falls back to other faction NPCs.
    """
    # Try to get faction leader first
    leader = get_faction_leader(faction)
    
    if leader:
        name = leader.get("name", "The contact")
        rank = leader.get("rank", "leader")
        appearance = leader.get("appearance", "")
        motivation = leader.get("motivation", "")
        
        # Extract first sentence of appearance for brief description
        brief_appearance = appearance.split(".")[0] if appearance else "a commanding presence"
        
        return f"""QUEST-GIVER ROLEPLAY:
Contact: {name} ({rank})
Appearance: {brief_appearance}
Motivation: {motivation[:100]}...

IMPORTANT: {name} is the faction leader. Use this name consistently.

DIALOGUE RULES:
- 2-3 lines of actual dialogue, then pause for player questions
- DO NOT monologue — let players ask
- Share critical info, hold back 1-2 details for Insight checks
- If players ask something the contact doesn't know, say so

SAMPLE OPENING:
"{name} looks up as you approach. {brief_appearance}. 
'You're the ones who took the job? Good. Here's what you need to know.'"

Then bullet the key facts, not a speech.
"""
    
    # Fallback: try other faction NPCs
    faction_npcs = get_npcs_by_faction(faction, alive_only=True)
    if faction_npcs:
        giver = faction_npcs[0]
        name = giver.get("name", "The contact")
        
        return f"""QUEST-GIVER ROLEPLAY:
Contact: {name}

DIALOGUE RULES:
- 2-3 lines of actual dialogue, then pause for player questions
- DO NOT monologue — let players ask
- Share critical info, hold back 1-2 details for Insight checks
- If players ask something the contact doesn't know, say so

SAMPLE OPENING:
"{name} looks up as you approach. [brief physical description]. 
'You're the ones who took the job? Good. Here's what you need to know.'"

Then bullet the key facts, not a speech.
"""
    
    # Ultimate fallback: use canonical leader name
    leader_name = get_faction_leader_name(faction)
    return f"""QUEST-GIVER ROLEPLAY:
Contact: {leader_name} (faction leader)

DIALOGUE RULES:
- 2-3 lines of actual dialogue, then pause for player questions
- DO NOT monologue — let players ask
- Share critical info, hold back 1-2 details for Insight checks
- If players ask something the contact doesn't know, say so

SAMPLE OPENING:
"{leader_name} looks up as you approach. [brief physical description]. 
'You're the ones who took the job? Good. Here's what you need to know.'"

Then bullet the key facts, not a speech.
"""
