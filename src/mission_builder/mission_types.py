"""
mission_types.py — Dynamic mission type definitions and difficulty scaling.

Defines all available mission types with characteristics, DM guidance, and
difficulty-to-tier mappings. Integrates with creative writing skills for
dynamic title and description generation.

Exported:
    MISSION_TYPES — All 18+ mission type definitions
    get_mission_type() — Get a mission type by name
    map_difficulty_to_tier() — Convert ease rating (1-10) to tier/CR
    generate_dynamic_title() — Generate title with mission type + creative skills
    get_difficulty_description() — Human-readable difficulty description
    
Mission Types:
    - Escort: Protect and transport target
    - Recovery: Find and retrieve something
    - Investigation: Uncover mystery or gather info
    - Battle: Combat-focused confrontation
    - Ambush: Respond to surprise attack
    - Negotiation: Resolve conflict diplomatically
    - Theft: Acquire target without detection
    - Rescue: Save someone/something from danger
    - Exploration: Discover new areas and threats
    - Discovery: Find clues or map locations
    - Delivery: Transport safely to destination
    - Sabotage: Disable/destroy target
    - Infiltration: Enter restricted area secretly
    - Assassination: Eliminate target (morally complex)
    - Defense: Protect location from attack
    - Puzzle: Solve complex mystery/trap
    - Gathering: Collect resources or information
    - Political: Navigate faction/social dynamics
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Difficulty Scale (1-10: Easy to Epic)
# ─────────────────────────────────────────────────────────────────────────

class DifficultyRating(Enum):
    """Standard difficulty scale for missions (1-10)."""
    TRIVIAL = 1               # Obstacle, not really a mission
    EASY = 2                  # Can be solved with basic effort
    MODERATE = 3              # Requires planning/skill but achievable
    CHALLENGING = 4           # Fair challenge for appropriate-level party
    HARD = 5                  # Serious threat, meaningful stakes
    DANGEROUS = 6             # High risk of character death
    DEADLY = 7                # Likely kill a PC
    EXTREME = 8               # Extreme danger, character death likely
    CATASTROPHIC = 9          # Near-impossible odds
    EPIC = 10                 # Campaign-defining moment

# Mappings to game mechanics
DIFFICULTY_TO_TIER: Dict[int, str] = {
    1: "local",           # Trivial
    2: "patrol",          # Easy
    3: "standard",        # Moderate
    4: "investigation",   # Challenging
    5: "rift",            # Hard
    6: "dungeon",         # Dangerous
    7: "major",           # Deadly
    8: "inter-guild",     # Extreme
    9: "high-stakes",     # Catastrophic
    10: "epic",           # Epic
}

DIFFICULTY_TO_5E: Dict[int, str] = {
    1: "easy",            # Trivial/Easy
    2: "easy",            #
    3: "medium",          # Moderate
    4: "medium",          # Challenging
    5: "hard",            # Hard
    6: "hard",            # Dangerous
    7: "deadly",          # Deadly+
    8: "deadly",          # Extreme
    9: "deadly",          # Catastrophic
    10: "deadly",         # Epic
}

DIFFICULTY_DESCRIPTION: Dict[int, str] = {
    1: "Trivial — Minor obstacle, barely merits attention",
    2: "Easy — Simple task, predictable challenges",
    3: "Moderate — Requires tactics and resources",
    4: "Challenging — Fair fight for the party level",
    5: "Hard — Serious threat, real chance of failure",
    6: "Dangerous — High risk, character death possible",
    7: "Deadly — PC likely to die, retreat recommended",
    8: "Extreme — Overwhelming odds even for prepared party",
    9: "Catastrophic — Near-impossible, victory uncertain",
    10: "Epic — Campaign-defining, legendary challenge",
}


# ─────────────────────────────────────────────────────────────────────────
# Mission Type Definitions
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class MissionType:
    """Definition of a mission type with characteristics."""
    
    name: str                    # "escort", "investigation", etc.
    display_name: str            # "Escort Mission", "Investigation"
    description: str             # What this mission type is about
    dm_guidance: str             # Tips for running this type
    typical_act_structure: List[str]  # Act breakdown
    resolution_keywords: List[str]    # Words/phrases for resolutions
    combat_intensity: str        # "low", "medium", "high"
    roleplay_intensity: str      # "low", "medium", "high"
    skill_checks: List[str]      # Common skill checks needed
    suggested_skills: List[str]  # Skills path (creative writing focus areas)


# All mission types
MISSION_TYPES: Dict[str, MissionType] = {
    
    "escort": MissionType(
        name="escort",
        display_name="Escort",
        description="Protect and transport a valuable target from point A to B.",
        dm_guidance=(
            "Provide multiple routes with different hazards. Layer threats: "
            "initial pursuit, ambushes, environmental dangers. The protected "
            "target should have personality and agency—not a static object. "
            "Success condition: target reaches destination alive."
        ),
        typical_act_structure=[
            "Act 1: Meet and brief target, learn obstacles",
            "Act 2: First threat emerges, party responds",
            "Act 3: Major encounter or decision point (go around/push through)",
            "Act 4: Final leg and climactic encounter or social choice",
        ],
        resolution_keywords=[
            "arrival", "safe harbor", "destination reached",
            "protected arrival", "target delivered", "sanctuary"
        ],
        combat_intensity="medium",
        roleplay_intensity="medium",
        skill_checks=["Stealth", "Insight", "Perception", "Deception"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),

    "recovery": MissionType(
        name="recovery",
        display_name="Recovery",
        description="Find and retrieve something valuable that was lost or stolen.",
        dm_guidance=(
            "Split the mission: first part is detective work (following clues, "
            "asking questions), second is retrieval (getting past obstacles, "
            "negotiating with possessor). The item has location, current owner, "
            "and complications. Provide false leads. Make the recovery interesting—"
            "maybe the current holder has legitimate claim."
        ),
        typical_act_structure=[
            "Act 1: Learn what was taken and basic leads",
            "Act 2: Investigation and social encounters",
            "Act 3: Discovering real location/owner",
            "Act 4: Retrieval or negotiation",
        ],
        resolution_keywords=[
            "recovered", "retrieved", "claimed", "acquired",
            "located", "secured", "in hand", "back home"
        ],
        combat_intensity="low",
        roleplay_intensity="high",
        skill_checks=["Investigation", "Insight", "Stealth", "Deception"],
        suggested_skills=["mission-gen", "prose-writing", "dnd5e-srd"],
    ),

    "investigation": MissionType(
        name="investigation",
        display_name="Investigation",
        description="Uncover a mystery by gathering clues and interrogating suspects.",
        dm_guidance=(
            "This is detective work. Provide 3-4 clue locations, each with "
            "multiple approaches (social, stealth, direct). Link clues together—"
            "each revelation should open new questions. Provide red herrings. "
            "The truth should be complex: multiple guilty parties, moral ambiguity, "
            "unexpected angles."
        ),
        typical_act_structure=[
            "Act 1: Crime scene and initial evidence",
            "Act 2: Suspect interviews and clue-gathering",
            "Act 3: Revelation (plot twist or hidden connection)",
            "Act 4: Confrontation and resolution",
        ],
        resolution_keywords=[
            "solved", "uncovered", "revealed", "discovered truth",
            "case closed", "mystery unraveled", "culprit identified"
        ],
        combat_intensity="low",
        roleplay_intensity="high",
        skill_checks=["Investigation", "Insight", "Perception", "Arcana/Religion"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),

    "battle": MissionType(
        name="battle",
        display_name="Battle",
        description="Direct combat confrontation against a meaningful threat.",
        dm_guidance=(
            "Combat should have stakes beyond 'kill the monster.' Who is this enemy? "
            "Why do they need to die? Battlefield terrain should matter—provide cover, "
            "hazards, elevation changes. Consider enemy morale/retreat conditions. "
            "Include 2-3 waves or reinforcements to extend the encounter."
        ),
        typical_act_structure=[
            "Act 1: Encounter the enemy, learn their intentions",
            "Act 2: First combat exchange, tactical reveal",
            "Act 3: Escalation (reinforcements or terrain shift)",
            "Act 4: Climax and aftermath",
        ],
        resolution_keywords=[
            "defeated", "vanquished", "slain", "routed", "driven off",
            "fallen", "destroyed", "battle won"
        ],
        combat_intensity="high",
        roleplay_intensity="low",
        skill_checks=["Attack rolls", "Initiative", "Insight (tactics)"],
        suggested_skills=["mission-gen", "dnd5e-srd"],
    ),

    "ambush": MissionType(
        name="ambush",
        display_name="Ambush",
        description="React and survive a surprise attack or trap.",
        dm_guidance=(
            "This mission starts with surprise. Use dynamic initiative. Enemies have "
            "advantage from positioning. But the party are the heroes—give them at least "
            "one option to dramatically turn the tables (good Perception check, creative "
            "use of environment). Aftermath includes intel about who attacked and why."
        ),
        typical_act_structure=[
            "Act 0: Ambush happens (surprise round)",
            "Act 1: Combat and adaptation",
            "Act 2: Victory or tactical retreat",
            "Act 3: Investigation and consequences",
        ],
        resolution_keywords=[
            "survived", "ambush repelled", "attackers routed", "turned tables",
            "escaped trap", "survived ambush", "counter-attacked"
        ],
        combat_intensity="high",
        roleplay_intensity="low",
        skill_checks=["Initiative", "Perception", "Acrobatics/Athletics"],
        suggested_skills=["mission-gen", "dnd5e-srd"],
    ),

    "negotiation": MissionType(
        name="negotiation",
        display_name="Negotiation",
        description="Resolve conflict through diplomacy, persuasion, and deal-making.",
        dm_guidance=(
            "This mission should have competing interests and no obvious 'right answer.' "
            "Each party should have valid reasons for their position. Provide multiple "
            "compromise solutions. Use skill checks (Insight, Persuasion, Deception) to "
            "gate information and success. Success is a deal both parties can live with."
        ),
        typical_act_structure=[
            "Act 1: Meet disputants, learn their positions",
            "Act 2: Gather info (what each side really wants)",
            "Act 3: Propose solutions, negotiate",
            "Act 4: Agreement reached or breakdown + conflict",
        ],
        resolution_keywords=[
            "negotiated", "brokered deal", "peace achieved", "compromise found",
            "agreement reached", "settlement negotiated", "pact sealed"
        ],
        combat_intensity="low",
        roleplay_intensity="high",
        skill_checks=["Insight", "Persuasion", "Deception", "Intimidation"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),

    "theft": MissionType(
        name="theft",
        display_name="Theft",
        description="Steal something guarded or secured without getting caught.",
        dm_guidance=(
            "This is a heist. Provide the target location, security (guards, traps, "
            "magic), and escape routes. The party needs to plan: they should have at "
            "least 2-3 viable approaches. Provide intel checks to learn security details. "
            "Success is getting the item AND escaping cleanly—or dealing with consequences."
        ),
        typical_act_structure=[
            "Act 1: Target briefing and scouting",
            "Act 2: Preparation and planning",
            "Act 3: The heist (in-game sneaking/deception)",
            "Act 4: Escape or confrontation",
        ],
        resolution_keywords=[
            "stolen", "heist successful", "got away clean", "acquired by theft",
            "liberated", "claim staked", "in the wind"
        ],
        combat_intensity="low",
        roleplay_intensity="medium",
        skill_checks=["Stealth", "Deception", "Sleight of Hand", "Ability checks"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),

    "rescue": MissionType(
        name="rescue",
        display_name="Rescue",
        description="Save a person or people from immediate danger or captivity.",
        dm_guidance=(
            "This has urgency. Provide a location (fortress, dungeon, ship), captors, "
            "and a time limit (unless they convince captors otherwise). The victim should "
            "have personality—they might resist rescue, have trauma, or become a liability. "
            "Success: victim reaches safety. Complications: victim harmed, betrayal, "
            "pursuing enemies."
        ),
        typical_act_structure=[
            "Act 1: Learn victim's location and captor",
            "Act 2: Journey to location, infiltration/direct approach choice",
            "Act 3: Encounter with captor(s) and rescue attempt",
            "Act 4: Escape with victim under fire",
        ],
        resolution_keywords=[
            "rescued", "recovered", "freed", "liberated", "saved",
            "escaped captivity", "justice done", "victim safe"
        ],
        combat_intensity="medium",
        roleplay_intensity="medium",
        skill_checks=["Perception", "Stealth", "Insight", "Combat"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),

    "exploration": MissionType(
        name="exploration",
        display_name="Exploration",
        description="Navigate unmapped territory and discover what's there.",
        dm_guidance=(
            "This is about discovery. Provide a region with 3+ areas of interest. "
            "Each area has encounters (monster, NPC, hazard, treasure). Use random "
            "elements—skill checks determine what they discover. The map reveals "
            "gradually. Tie discoveries to larger world (faction interests, coming threats)."
        ),
        typical_act_structure=[
            "Act 1: Enter region, basic orientation",
            "Act 2: Discover Point A + encounter",
            "Act 3: Discover Point B + choice",
            "Act 4: Discover Point C + major revelation",
        ],
        resolution_keywords=[
            "explored", "mapped", "surveyed", "charted", "discovered",
            "territory secured", "findings reported", "secrets unveiled"
        ],
        combat_intensity="medium",
        roleplay_intensity="low",
        skill_checks=["Survival", "Perception", "Arcana", "Combat"],
        suggested_skills=["mission-gen", "dnd5e-srd"],
    ),

    "discovery": MissionType(
        name="discovery",
        display_name="Discovery",
        description="Find clues, map locations, or uncover hidden knowledge.",
        dm_guidance=(
            "Similar to investigation but broader scope. The party seeks a location, "
            "magical knowledge, or historical facts. Provide multiple information sources: "
            "libraries, NPCs, ruins, ancient records. Skill checks gate access. False leads "
            "exist. The discovery should be significant to the larger world/campaign."
        ),
        typical_act_structure=[
            "Act 1: Learn what to seek and initial leads",
            "Act 2: Research/travel to information source",
            "Act 3: Access guarded knowledge",
            "Act 4: Revelation and implications",
        ],
        resolution_keywords=[
            "discovered", "uncovered", "found", "learned secrets",
            "knowledge acquired", "location found", "truth revealed"
        ],
        combat_intensity="low",
        roleplay_intensity="medium",
        skill_checks=["Arcana", "History", "Religion", "Investigation"],
        suggested_skills=["mission-gen", "dnd5e-srd"],
    ),

    "delivery": MissionType(
        name="delivery",
        display_name="Delivery",
        description="Transport something (person, message, item) to a destination.",
        dm_guidance=(
            "Like escort but the 'cargo' is non-living or less complex. Provide route, "
            "obstacles, and complications from weather/terrain/pursuit. The delivery must "
            "be pristine or intact—not just 'get there.' Example: deliver magical item "
            "without it being corrupted by radiation."
        ),
        typical_act_structure=[
            "Act 1: Acquire cargo, learn destination and constraints",
            "Act 2: Begin journey, first obstacle",
            "Act 3: Mid-journey complication (cargo damaged/stolen/compromised)",
            "Act 4: Final push to destination",
        ],
        resolution_keywords=[
            "delivered", "arrival confirmed", "cargo intact", "mission complete",
            "handoff successful", "destination reached", "task accomplished"
        ],
        combat_intensity="low",
        roleplay_intensity="low",
        skill_checks=["Survival", "Stealth", "Perception", "Arcana"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),

    "sabotage": MissionType(
        name="sabotage",
        display_name="Sabotage",
        description="Disable, destroy, or compromise a target structure/operation.",
        dm_guidance=(
            "This is focused destruction. Provide a location and target system. Security "
            "exists but isn't insurmountable with planning. Consider: guards, traps, "
            "magical wards, guards that return periodically. Collateral damage may affect "
            "innocents. Escape after sabotage is part of the mission."
        ),
        typical_act_structure=[
            "Act 1: Learn target and planning",
            "Act 2: Infiltration",
            "Act 3: Sabotage attempt + complications",
            "Act 4: Escape before response",
        ],
        resolution_keywords=[
            "sabotaged", "destroyed", "disabled", "compromised", "ruined",
            "operation halted", "system destroyed", "mission sabotaged"
        ],
        combat_intensity="medium",
        roleplay_intensity="low",
        skill_checks=["Stealth", "Arcana/Sleight of Hand", "Demolitions-like checks"],
        suggested_skills=["mission-gen", "dnd5e-srd"],
    ),

    "infiltration": MissionType(
        name="infiltration",
        display_name="Infiltration",
        description="Enter a restricted area while avoiding or neutralizing security.",
        dm_guidance=(
            "Provide a location with tiered security: outer, middle, inner access. "
            "Each tier has a bypass method: pass, persuade, sneak, or disable. The party "
            "must choose their approach and commit to consequences. Success is reaching "
            "their objective and ideally exiting undetected."
        ),
        typical_act_structure=[
            "Act 1: Target briefing, security assessment",
            "Act 2: Outer perimeter bypass",
            "Act 3: Middle security, potential combat or compromise",
            "Act 4: Inner sanctum and objective",
        ],
        resolution_keywords=[
            "infiltrated", "penetrated defenses", "reached objective",
            "security breached", "in place", "extraction complete", "mission secured"
        ],
        combat_intensity="low",
        roleplay_intensity="medium",
        skill_checks=["Stealth", "Deception", "Arcana/Technology", "Acrobatics"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),

    "assassination": MissionType(
        name="assassination",
        display_name="Assassination",
        description="Eliminate a specific target, usually a person of significance.",
        dm_guidance=(
            "Morally complex mission. The target should be characterized—why are they "
            "marked? Do the party agree with the contract? Provide information about "
            "target's location, habits, security. Multiple approaches viable (social, "
            "stealth, direct). After success: consequences and potential pursuit."
        ),
        typical_act_structure=[
            "Act 1: Target briefing, reconnaissance",
            "Act 2: Planning and preparation",
            "Act 3: Execution",
            "Act 4: Escape and fallout",
        ],
        resolution_keywords=[
            "eliminated", "target neutralized", "contract complete", "justice served",
            "debt paid", "enemy fell", "contract fulfilled", "objective secured"
        ],
        combat_intensity="high",
        roleplay_intensity="medium",
        skill_checks=["Stealth", "Perception", "Investigation", "Combat"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),

    "defense": MissionType(
        name="defense",
        display_name="Defense",
        description="Protect a location or people from an imminent or ongoing attack.",
        dm_guidance=(
            "This is a siege/holdout mission. Provide a location and its defenses "
            "(walls, choke points, resources). Enemies attack in waves. Party must "
            "organize NPCs, position defenses, and hold for X rounds/hours. Success "
            "is survival until reinforcements or enemy retreat."
        ),
        typical_act_structure=[
            "Act 1: Arrive and evaluate defenses",
            "Act 2: Prepare (fortify, organize NPCs, set traps)",
            "Act 3: First wave attack",
            "Act 4: Final assault and victory/evacuation",
        ],
        resolution_keywords=[
            "defended", "position held", "attack repelled", "survived siege",
            "enemies routed", "landmark saved", "victory achieved", "reinforcements arrived"
        ],
        combat_intensity="high",
        roleplay_intensity="low",
        skill_checks=["Initiative", "Leadership (ideally)", "Combat", "Tactics"],
        suggested_skills=["mission-gen", "dnd5e-srd"],
    ),

    "puzzle": MissionType(
        name="puzzle",
        display_name="Puzzle",
        description="Solve a complex mystery, riddle, or trap to progress.",
        dm_guidance=(
            "This mission's core is a solvable puzzle (magic lock, riddle, dungeon trap). "
            "Provide clues available through exploration/interaction. Multiple solutions "
            "exist (brute force, teleport past, find key, solve riddle). Consequences for "
            "wrong choices should be recoverable."
        ),
        typical_act_structure=[
            "Act 1: Encounter the puzzle",
            "Act 2: Investigation and clue-gathering",
            "Act 3: Puzzle-solving attempts",
            "Act 4: Success and progression/reward",
        ],
        resolution_keywords=[
            "solved", "deciphered", "cracked", "unraveled", "decoded",
            "mystery solved", "passage opened", "riddle answered"
        ],
        combat_intensity="low",
        roleplay_intensity="medium",
        skill_checks=["Arcana", "Investigation", "Insight", "Ability checks"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),

    "gathering": MissionType(
        name="gathering",
        display_name="Gathering",
        description="Collect specific resources, materials, or information.",
        dm_guidance=(
            "Collection mission. Provide multiple sources for the target resource. "
            "Each source has complications: guarded location, owned by hostile NPC, "
            "endangered creature, difficult terrain. Party chooses which sources to hit. "
            "Total collected should match mission goal."
        ),
        typical_act_structure=[
            "Act 1: Learn target resource and sources",
            "Act 2: Visit Source A and obtain",
            "Act 3: Visit Source B and deal with complication",
            "Act 4: Final source and completion",
        ],
        resolution_keywords=[
            "collected", "gathered", "acquired", "stockpiled", "harvested",
            "resources secured", "quota met", "supplies obtained"
        ],
        combat_intensity="low",
        roleplay_intensity="low",
        skill_checks=["Survival", "Perception", "Nature/Arcana", "Negotiation"],
        suggested_skills=["mission-gen", "dnd5e-srd"],
    ),

    "political": MissionType(
        name="political",
        display_name="Political",
        description="Navigate faction dynamics, alliances, and social power plays.",
        dm_guidance=(
            "Social mission focused on influence and relationships. Provide multiple "
            "NPCs/factions with competing interests. Actions have social consequences. "
            "Success is shifting the political landscape to the employer's advantage. "
            "Combat is possible but not primary."
        ),
        typical_act_structure=[
            "Act 1: Meet influencers and learn dynamics",
            "Act 2: Gather information and build relationship",
            "Act 3: Critical social test (persuade, intimidate, deceive)",
            "Act 4: Consequences and new status quo",
        ],
        resolution_keywords=[
            "influenced", "alliance brokered", "political victory", "favor won",
            "faction swayed", "dynamics shifted", "power secured", "politics shifted"
        ],
        combat_intensity="low",
        roleplay_intensity="high",
        skill_checks=["Persuasion", "Deception", "Insight", "Investigation"],
        suggested_skills=["mission-gen", "prose-writing"],
    ),
}


# ─────────────────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────────────────

def get_mission_type(name: str) -> Optional[MissionType]:
    """Get a mission type by name (case-insensitive)."""
    return MISSION_TYPES.get(name.lower())


def list_mission_types() -> List[str]:
    """List all available mission type names."""
    return sorted(MISSION_TYPES.keys())


def map_difficulty_to_tier(difficulty: int) -> str:
    """Convert difficulty rating (1-10) to tier string."""
    difficulty = max(1, min(10, difficulty))  # Clamp to 1-10
    return DIFFICULTY_TO_TIER.get(difficulty, "standard")


def map_difficulty_to_5e(difficulty: int) -> str:
    """Convert difficulty rating (1-10) to D&D 5e difficulty."""
    difficulty = max(1, min(10, difficulty))
    return DIFFICULTY_TO_5E.get(difficulty, "medium")


def get_difficulty_description(difficulty: int) -> str:
    """Get human-readable description of difficulty rating."""
    difficulty = max(1, min(10, difficulty))
    return DIFFICULTY_DESCRIPTION.get(difficulty, "Unknown")


async def generate_dynamic_title(
    mission_type: str,
    faction: str,
    theme_or_subject: str,
    difficulty: int = 5,
    use_skills: bool = False,
) -> str:
    """
    Generate a dynamic mission title incorporating mission type.
    
    Optionally uses creative writing skills for more varied titles.
    
    Args:
        mission_type: Mission type (e.g., "escort", "investigation")
        faction: Associated faction
        theme_or_subject: What the mission is about
        difficulty: Difficulty rating (1-10)
        use_skills: Whether to use creative writing skills
    
    Returns:
        Generated mission title
    
    Example:
        >>> title = await generate_dynamic_title(
        ...     "investigation",
        ...     "Iron Fang Consortium",
        ...     "counting house discrepancy",
        ...     difficulty=4,
        ... )
        >>> print(title)
        # "Investigation: The Counting House Discrepancy"
    """
    mission = get_mission_type(mission_type)
    
    if not mission:
        # Fallback to generic title
        return f"{theme_or_subject.title()}"
    
    # Get difficulty descriptor
    diff_word = {
        1: "Minor",
        2: "Local",
        3: "Standard",
        4: "Significant",
        5: "Serious",
        6: "Urgent",
        7: "Critical",
        8: "Extreme",
        9: "Catastrophic",
        10: "Epic",
    }.get(difficulty, "")
    
    # Format: [DIFFICULTY] [TYPE]: [SUBJECT]
    # Some types omit difficulty at lower levels for brevity
    
    if use_skills:
        try:
            from src.skills import enhance_generation_with_skills
            
            prompt = (
                f"Create a compelling D&D mission title.\n"
                f"Type: {mission.display_name}\n"
                f"Faction: {faction}\n"
                f"Subject: {theme_or_subject}\n"
                f"Difficulty: {get_difficulty_description(difficulty)}\n\n"
                f"Format: [DIFFICULTY] {mission.display_name.upper()}: [SUBJECT]\n"
                f"Keep it under 70 characters. Be specific and intriguing."
            )
            
            enhanced = enhance_generation_with_skills(prompt, "prose-writing")
            
            # Use LLM to generate title
            from src.mission_builder import _ollama_generate
            title_prompt = (
                f"{enhanced}\n\n"
                f"Generate ONE mission title only. No quotes, no explanation."
            )
            
            # Try to get async loop, with fallback
            try:
                title = await _ollama_generate(title_prompt, max_tokens=20)
            except Exception:
                title = None
            
            if title and title.strip():
                return title.strip().strip('"\'')
        
        except Exception as e:
            logger.debug(f"Could not use skills for title generation: {e}")
    
    # Fallback to template-based title
    if diff_word and difficulty >= 3:
        return f"{diff_word} {mission.display_name}: {theme_or_subject}"
    else:
        return f"{mission.display_name}: {theme_or_subject}"


# ─────────────────────────────────────────────────────────────────────────
# Constants for templates and patterns
# ─────────────────────────────────────────────────────────────────────────

GENERIC_TITLES_BY_TYPE: Dict[str, List[str]] = {
    "escort": [
        "{subject} Escort",
        "Protecting {subject}",
        "Safe Passage for {subject}",
    ],
    "investigation": [
        "{subject} Investigation",
        "Uncovering {subject}",
        "The {subject} Mystery",
    ],
    "theft": [
        "Steal the {subject}",
        "Acquiring {subject}",
        "The {subject} Heist",
    ],
    "rescue": [
        "Rescue {subject}",
        "Saving {subject}",
        "Free {subject}",
    ],
    "battle": [
        "Face the {subject}",
        "Battle Against {subject}",
        "The {subject} Conflict",
    ],
}
