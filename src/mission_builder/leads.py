"""
leads.py — Investigation leads system for mission modules.

This replaces the old "Read Aloud" approach with actionable leads that give
players specific places to go and reasons to go there.

Each lead has:
- Location (from gazetteer)
- Contact NPC
- What they know
- WHY the players should go there
- How to approach (social/stealth/direct options)
"""

from __future__ import annotations

import random
import logging
from typing import List, Dict, Optional
from .locations import (
    load_gazetteer,
    get_establishments_for_leads,
    get_district_info,
    get_sub_areas,
    build_location_context,
)

logger = logging.getLogger(__name__)


# Lead types and their characteristics
LEAD_TYPES = {
    "informant": {
        "description": "Someone who has information about the target or situation",
        "approach_options": ["bribe", "persuade", "intimidate", "trade favors"],
        "typical_locations": ["tavern", "market", "info_broker"],
    },
    "witness": {
        "description": "Someone who saw something relevant",
        "approach_options": ["sympathize", "jog memory", "protect", "convince safety"],
        "typical_locations": ["residential", "shop", "workplace"],
    },
    "contact": {
        "description": "A faction representative or professional connection",
        "approach_options": ["official request", "call in favor", "negotiate", "formal meeting"],
        "typical_locations": ["office", "guild_hall", "faction_hq"],
    },
    "trail": {
        "description": "Physical evidence or a trail to follow",
        "approach_options": ["track", "investigate scene", "gather samples", "reconstruct events"],
        "typical_locations": ["crime_scene", "last_known_location", "transit_point"],
    },
    "expert": {
        "description": "Someone with specialized knowledge needed",
        "approach_options": ["consult", "hire", "trade knowledge", "demonstrate need"],
        "typical_locations": ["academy", "library", "workshop", "temple"],
    },
    "fence": {
        "description": "Black market contact who moves goods or information",
        "approach_options": ["buy info", "trace goods", "make deal", "threaten exposure"],
        "typical_locations": ["black_market", "underground", "shady_establishment"],
    },
}


# NPC motivation templates for generating convincing "why they'd help"
NPC_MOTIVATIONS = [
    "owes a debt to the posting faction",
    "has a grudge against the target",
    "needs protection the party can provide",
    "wants payment the party can offer",
    "is being blackmailed and wants out",
    "seeks revenge for a personal slight",
    "has romantic interest in someone involved",
    "is a former associate who was betrayed",
    "needs a favor in return",
    "is secretly working both sides",
    "wants the truth to come out",
    "fears what happens if they don't talk",
    "is loyal to someone the party knows",
    "wants to destabilize a rival",
    "is idealistic and believes in justice",
]


# Reasons WHY players should go to a location (the key improvement over "Read Aloud")
LOCATION_REASONS = {
    "tavern": [
        "The target was seen drinking here three nights ago",
        "A known associate runs a card game in the back room",
        "The bartender trades in rumours and owes the posting faction",
        "Workers from the target's operation come here after shifts",
        "A meeting was overheard being scheduled for this location",
    ],
    "shop": [
        "The target made a suspicious purchase here recently",
        "The shopkeeper has a side business in information",
        "Stolen goods from the case were traced to this vendor",
        "An employee witnessed something but is afraid to come forward",
        "The shop is a known dead drop for the involved faction",
    ],
    "office": [
        "Records here might show the target's movements",
        "A bureaucrat can be bribed to reveal protected information",
        "The official in charge owes the posting faction a favour",
        "Permits and licenses would reveal the target's real operation",
        "Someone here processed paperwork that connects the dots",
    ],
    "underground": [
        "The target has been hiding in the tunnels",
        "Smuggler routes lead directly to the operation",
        "A fence here has been moving stolen goods from the case",
        "Witnesses saw suspicious activity near this entrance",
        "The target's people use this route to avoid patrols",
    ],
    "temple": [
        "The target sought sanctuary or confession here",
        "A priest overheard something during a ritual",
        "Divine records might reveal contracts or oaths involved",
        "The target's family has historical ties to this faith",
        "Someone here can perform divination to locate the target",
    ],
    "market": [
        "The target's operation requires supplies bought here",
        "A merchant saw unusual transactions recently",
        "Cargo manifests here would reveal the distribution network",
        "Street vendors keep eyes on everything in this area",
        "Someone here knows everyone's business and can be bought",
    ],
    "guild_hall": [
        "The guild has records of members involved",
        "A ranking member has information but needs political cover",
        "The target has enemies within the guild who might help",
        "Guild contracts reveal the operation's financing",
        "An apprentice saw something they shouldn't have",
    ],
}


def generate_lead(
    lead_type: str,
    faction: Optional[str] = None,
    district: Optional[str] = None,
    mission_context: Optional[str] = None,
) -> dict:
    """
    Generate a single investigation lead.
    
    Returns a dict with:
    - location: Where to go
    - contact_name: NPC to find (placeholder to be filled by AI)
    - what_they_know: Information they have
    - why_go_there: The reason players should investigate this lead
    - approach_options: Ways to handle the encounter
    - lead_type: The type of lead
    """
    lead_info = LEAD_TYPES.get(lead_type, LEAD_TYPES["informant"])
    
    # Get a real establishment from the gazetteer
    establishments = get_establishments_for_leads(
        faction=faction,
        district=district,
        count=3
    )
    
    if establishments:
        est = random.choice(establishments)
        location_name = f"{est['name']} in {est['district']}"
        location_type = est.get("type", "tavern")
        location_desc = est.get("description", "A notable establishment")
    else:
        # Fallback to generic
        location_name = f"A {lead_type} contact point"
        location_type = random.choice(lead_info["typical_locations"])
        location_desc = "A place where information changes hands"
        logger.warning(f"🔗 Lead generation: no establishments found for {faction} in {district} — using fallback")
    
    # Get a reason why the players should go there
    reasons = LOCATION_REASONS.get(location_type, LOCATION_REASONS.get("tavern", []))
    if not reasons:
        logger.warning(f"🔗 Lead generation: no location reasons for type '{location_type}' — using generic")
        reasons = ["This location is relevant to the investigation"]
    why_go = random.choice(reasons)
    
    # Get NPC motivation
    if not NPC_MOTIVATIONS:
        logger.error(f"🔗 Lead generation: NPC_MOTIVATIONS list is empty!")
        motivation = "unknown motivation"
    else:
        motivation = random.choice(NPC_MOTIVATIONS)
    
    return {
        "lead_type": lead_type,
        "location": location_name,
        "location_type": location_type,
        "location_description": location_desc,
        "contact_name": "[NPC NAME]",  # To be filled by AI
        "contact_description": lead_info["description"],
        "why_go_there": why_go,
        "contact_motivation": motivation,
        "what_they_know": "[INFORMATION]",  # To be filled by AI
        "approach_options": lead_info["approach_options"],
        "skill_checks": _generate_skill_checks(lead_type),
    }


def _generate_skill_checks(lead_type: str) -> List[dict]:
    """Generate appropriate skill checks for a lead type."""
    checks = {
        "informant": [
            {"skill": "Persuasion", "dc_modifier": 0, "success": "They share what they know", "failure": "They clam up and become suspicious"},
            {"skill": "Insight", "dc_modifier": -2, "success": "You sense they're holding back", "failure": "You miss signs of deception"},
            {"skill": "Intimidation", "dc_modifier": 2, "success": "Fear loosens their tongue", "failure": "They call for help or flee"},
        ],
        "witness": [
            {"skill": "Persuasion", "dc_modifier": -2, "success": "They agree to tell you what they saw", "failure": "They're too scared to talk"},
            {"skill": "Investigation", "dc_modifier": 0, "success": "You piece together their fragmented account", "failure": "The details don't add up"},
        ],
        "contact": [
            {"skill": "Persuasion", "dc_modifier": 0, "success": "They agree to help officially", "failure": "They cite protocol and refuse"},
            {"skill": "History/Society", "dc_modifier": -2, "success": "You invoke the right precedent or favor", "failure": "Your approach offends faction sensibilities"},
        ],
        "trail": [
            {"skill": "Investigation", "dc_modifier": 0, "success": "You find clear evidence", "failure": "The trail has gone cold"},
            {"skill": "Perception", "dc_modifier": -2, "success": "You notice something others missed", "failure": "You overlook a crucial detail"},
            {"skill": "Survival", "dc_modifier": 0, "success": "You can follow the physical trail", "failure": "You lose the trail at a junction"},
        ],
        "expert": [
            {"skill": "Persuasion", "dc_modifier": 0, "success": "They share their expertise", "failure": "They demand unreasonable payment"},
            {"skill": "Arcana/Religion/Nature", "dc_modifier": -2, "success": "You speak their language and earn respect", "failure": "Your ignorance annoys them"},
        ],
        "fence": [
            {"skill": "Deception", "dc_modifier": 0, "success": "They believe your cover story", "failure": "They suspect you're law enforcement"},
            {"skill": "Intimidation", "dc_modifier": 2, "success": "They fear consequences more than profit", "failure": "They have protection and aren't afraid"},
            {"skill": "Sleight of Hand", "dc_modifier": 2, "success": "You plant a tracker or steal evidence", "failure": "They notice and the deal goes sour"},
        ],
    }
    return checks.get(lead_type, checks["informant"])


def generate_investigation_leads(
    faction: str,
    tier: str,
    mission_type: str,
    count: int = 3,
) -> List[dict]:
    """
    Generate multiple investigation leads for a mission.
    
    Ensures variety in lead types and locations.
    """
    # Determine appropriate lead types based on mission type
    type_weights = {
        "investigation": ["informant", "witness", "trail", "contact"],
        "escort": ["contact", "informant", "trail"],
        "local": ["witness", "informant", "trail"],
        "patrol": ["trail", "witness", "contact"],
        "dungeon": ["expert", "informant", "trail"],
        "rift": ["expert", "trail", "contact"],
        "inter-guild": ["contact", "informant", "fence"],
        "high-stakes": ["informant", "fence", "contact", "expert"],
        "standard": ["informant", "witness", "contact"],
    }
    
    available_types = type_weights.get(mission_type.lower(), ["informant", "witness", "contact"])
    
    leads = []
    used_types = set()
    
    for i in range(count):
        # Pick a type we haven't used yet if possible
        remaining_types = [t for t in available_types if t not in used_types]
        if not remaining_types:
            remaining_types = available_types
        
        lead_type = random.choice(remaining_types)
        used_types.add(lead_type)
        
        lead = generate_lead(
            lead_type=lead_type,
            faction=faction,
        )
        lead["lead_number"] = i + 1
        leads.append(lead)
    
    return leads


def format_leads_for_prompt(leads: List[dict], cr: int) -> str:
    """
    Format leads into a prompt block for AI generation.
    
    The AI will fill in the [NPC NAME] and [INFORMATION] placeholders.
    """
    lines = [
        "INVESTIGATION LEADS (fill in [bracketed] placeholders):",
        f"Base DC for skill checks: {10 + (cr // 2)} (moderate), {12 + (cr // 2)} (hard)",
        "",
    ]
    
    for lead in leads:
        lines.append(f"### Lead {lead['lead_number']}: {lead['lead_type'].title()}")
        lines.append(f"**Location:** {lead['location']}")
        lines.append(f"**Why go here:** {lead['why_go_there']}")
        lines.append(f"**Contact:** {lead['contact_name']} — {lead['contact_description']}")
        lines.append(f"**Their motivation:** {lead['contact_motivation']}")
        lines.append(f"**What they know:** {lead['what_they_know']}")
        lines.append(f"**Approach options:** {', '.join(lead['approach_options'])}")
        
        lines.append("**Skill checks:**")
        for check in lead["skill_checks"]:
            dc = 10 + (cr // 2) + check["dc_modifier"]
            lines.append(f"  - {check['skill']} DC {dc}: Success = {check['success']}; Failure = {check['failure']}")
        
        lines.append("")
    
    return "\n".join(lines)


def format_lead_as_scene(lead: dict, cr: int) -> str:
    """
    Format a single lead as a scene description for the final module.
    """
    dc_base = 10 + (cr // 2)
    
    lines = [
        f"### {lead['location']}",
        "",
        f"**Why the party comes here:** {lead['why_go_there']}",
        "",
        f"**The Contact:** {lead['contact_name']}",
        f"_{lead['contact_description']}. {lead['contact_motivation'].capitalize()}._",
        "",
        "**What they know:**",
        f"{lead['what_they_know']}",
        "",
        "**Approach Options:**",
    ]
    
    for approach in lead["approach_options"]:
        lines.append(f"- **{approach.title()}**: [specific guidance]")
    
    lines.append("")
    lines.append("**Skill Checks:**")
    
    for check in lead["skill_checks"]:
        dc = dc_base + check["dc_modifier"]
        lines.append(f"- **{check['skill']} DC {dc}**")
        lines.append(f"  - _Success:_ {check['success']}")
        lines.append(f"  - _Failure:_ {check['failure']}")
    
    return "\n".join(lines)


# Approach templates for different playstyles
APPROACH_TEMPLATES = {
    "social": {
        "description": "Talk your way through",
        "key_skills": ["Persuasion", "Deception", "Insight"],
        "advantages": "Non-violent, maintains relationships, can gain allies",
        "risks": "Takes longer, might not work on hostiles, leaves witnesses",
    },
    "stealth": {
        "description": "Observe and infiltrate",
        "key_skills": ["Stealth", "Sleight of Hand", "Perception"],
        "advantages": "Avoids combat, gathers intel, element of surprise",
        "risks": "Discovery means trouble, limited direct info, time-consuming",
    },
    "direct": {
        "description": "Confront directly",
        "key_skills": ["Intimidation", "Athletics", "Combat"],
        "advantages": "Fast, effective on weak opposition, sends a message",
        "risks": "Makes enemies, draws attention, collateral damage",
    },
    "investigation": {
        "description": "Follow the evidence",
        "key_skills": ["Investigation", "Perception", "History"],
        "advantages": "Builds solid case, finds hidden connections, thorough",
        "risks": "Slow, requires patience, evidence can be destroyed",
    },
}


def get_approach_guidance(lead_type: str) -> dict:
    """Get guidance on different approaches for a lead type."""
    # Map lead types to recommended approaches
    recommendations = {
        "informant": ["social", "direct"],
        "witness": ["social", "investigation"],
        "contact": ["social"],
        "trail": ["investigation", "stealth"],
        "expert": ["social", "investigation"],
        "fence": ["social", "stealth", "direct"],
    }
    
    rec_approaches = recommendations.get(lead_type, ["social"])
    
    guidance = {}
    for approach in rec_approaches:
        guidance[approach] = APPROACH_TEMPLATES.get(approach, APPROACH_TEMPLATES["social"])
    
    return guidance
