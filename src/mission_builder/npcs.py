"""
npcs.py — NPC generation patterns and dialogue helpers.

Provides:
- NPC roster loading and filtering
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


def load_npc_roster() -> List[dict]:
    """Load the NPC roster from disk."""
    roster_file = DOCS_DIR / "npc_roster.json"
    if not roster_file.exists():
        return []
    try:
        return json.loads(roster_file.read_text(encoding="utf-8"))
    except Exception:
        return []


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
    
    Prioritizes NPCs from the posting faction, adds some from other factions.
    """
    roster = load_npc_roster()
    faction_lower = faction.lower()
    
    faction_npcs = []
    other_npcs = []
    
    for npc in roster:
        if npc.get("status") != "alive":
            continue
        
        if faction_lower in npc.get("faction", "").lower():
            faction_npcs.append(npc)
        else:
            other_npcs.append(npc)
    
    # Randomize selection within limits
    random.shuffle(faction_npcs)
    random.shuffle(other_npcs)
    
    return faction_npcs[:faction_count] + other_npcs[:other_count]


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
    
    lines = [
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
    """Generate quest-giver roleplay guidance."""
    faction_npcs = get_npcs_by_faction(faction, alive_only=True)
    
    if faction_npcs:
        giver = faction_npcs[0]
        name = giver.get("name", "The contact")
        personality = giver.get("personality", "professional")
        
        return f"""QUEST-GIVER ROLEPLAY:
Contact: {name}
Personality: {personality}

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
    
    return """QUEST-GIVER ROLEPLAY:
Create a contact NPC appropriate for the posting faction.
- 2-3 lines of actual dialogue, then pause for player questions
- DO NOT monologue — let players ask
- Share critical info, hold back 1-2 details for Insight checks
"""
