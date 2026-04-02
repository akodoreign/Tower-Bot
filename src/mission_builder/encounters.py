"""
encounters.py — Combat encounter design and stat block generation.

Provides:
- CR scaling based on PC levels
- Encounter budget calculations
- Stat block formatting
- Tactical environment generation
"""

from __future__ import annotations

import re
import random
import logging
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "campaign_docs"

# ---------------------------------------------------------------------------
# CR Scaling — dynamic, based on actual PC levels
# ---------------------------------------------------------------------------

TIER_OFFSET: Dict[str, int] = {
    "local":         1,
    "patrol":        1,
    "escort":        2,
    "standard":      2,
    "investigation": 2,
    "rift":          3,
    "dungeon":       3,
    "dungeon-delve": 3,
    "major":         4,
    "inter-guild":   4,
    "high-stakes":   5,
    "epic":          5,
    "divine":        5,
    "tower":         5,
}
DEFAULT_OFFSET = 2

LEGACY_TIER_CR: Dict[str, int] = {
    "local": 4, "patrol": 4, "escort": 5, "standard": 5,
    "investigation": 6, "rift": 8, "dungeon": 8, "major": 9,
    "inter-guild": 10, "high-stakes": 11, "epic": 12, "divine": 12, "tower": 12,
}
DEFAULT_CR = 5

# Encounter difficulty XP budgets for 5e 2024
ENCOUNTER_BUDGET = {
    1:  {"easy": 25, "medium": 50, "hard": 75, "deadly": 100},
    2:  {"easy": 50, "medium": 100, "hard": 150, "deadly": 200},
    3:  {"easy": 75, "medium": 150, "hard": 225, "deadly": 300},
    4:  {"easy": 250, "medium": 500, "hard": 750, "deadly": 1000},
    5:  {"easy": 500, "medium": 1000, "hard": 1500, "deadly": 2000},
    6:  {"easy": 600, "medium": 1200, "hard": 1800, "deadly": 2400},
    7:  {"easy": 750, "medium": 1500, "hard": 2100, "deadly": 2800},
    8:  {"easy": 1000, "medium": 1800, "hard": 2400, "deadly": 3200},
    9:  {"easy": 1100, "medium": 2200, "hard": 3000, "deadly": 3900},
    10: {"easy": 1200, "medium": 2500, "hard": 3800, "deadly": 5000},
    11: {"easy": 1600, "medium": 3200, "hard": 4800, "deadly": 6400},
    12: {"easy": 2000, "medium": 3900, "hard": 5900, "deadly": 7800},
    13: {"easy": 2200, "medium": 4500, "hard": 6800, "deadly": 9000},
    14: {"easy": 2500, "medium": 5100, "hard": 7700, "deadly": 10200},
    15: {"easy": 2800, "medium": 5700, "hard": 8600, "deadly": 11400},
    16: {"easy": 3200, "medium": 6400, "hard": 9600, "deadly": 12800},
    17: {"easy": 3900, "medium": 7800, "hard": 11700, "deadly": 15600},
    18: {"easy": 4200, "medium": 8400, "hard": 12600, "deadly": 16800},
    19: {"easy": 4900, "medium": 9800, "hard": 14700, "deadly": 19600},
    20: {"easy": 5700, "medium": 11300, "hard": 17000, "deadly": 22600},
}

# XP by CR for encounter building
CR_XP = {
    0: 10, 0.125: 25, 0.25: 50, 0.5: 100,
    1: 200, 2: 450, 3: 700, 4: 1100, 5: 1800,
    6: 2300, 7: 2900, 8: 3900, 9: 5000, 10: 5900,
    11: 7200, 12: 8400, 13: 10000, 14: 11500, 15: 13000,
    16: 15000, 17: 18000, 18: 20000, 19: 22000, 20: 25000,
    21: 33000, 22: 41000, 23: 50000, 24: 62000, 25: 75000,
    26: 90000, 27: 105000, 28: 120000, 29: 135000, 30: 155000,
}


def get_max_pc_level() -> int:
    """Parse character_memory.txt and return the highest total class level."""
    char_file = DOCS_DIR / "character_memory.txt"
    if not char_file.exists():
        logger.warning("📖 character_memory.txt not found — returning CR 0")
        return 0
    try:
        text = char_file.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"📖 Could not read character_memory.txt: {e}")
        return 0

    max_level = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.upper().startswith("CLASS:"):
            continue
        class_text = line.split(":", 1)[1].strip()
        
        # Parse multi-class like "Fighter/Monk (5/3)" or "Fighter 5/Monk 3" or "Fighter (5)" or "Fighter 5"
        # Extract all numbers and sum them
        level_matches = re.findall(r'\((\d+)(?:/(\d+))*\)|\s(\d+)(?:/\s*(\d+))?', class_text)
        
        if level_matches:
            total = 0
            for match in level_matches:
                # Each match is a tuple from the regex groups
                for group in match:
                    if group:
                        total += int(group)
            
            if total > max_level:
                max_level = total
                logger.debug(f"📖 Found character level {total} from: {class_text}")
        else:
            logger.debug(f"📖 Could not parse class levels from: {class_text}")

    if max_level <= 0:
        logger.warning("📖 No valid character levels found in character_memory.txt")
        return 0
        
    logger.info(f"📖 Max PC level detected: {max_level}")
    return max_level


def get_cr(tier: str) -> int:
    """
    Calculate CR dynamically from max PC level + tier offset.
    
    CR = max_pc_level + tier_offset, clamped to [max_pc_level + 1, max_pc_level + 5].
    Falls back to legacy fixed table if character_memory.txt is unreadable.
    
    Returns CR clamped to valid range [1, 30].
    """
    max_level = get_max_pc_level()

    if max_level <= 0:
        cr = LEGACY_TIER_CR.get(tier.lower(), DEFAULT_CR)
        logger.warning(f"⚠️ CR FALLBACK: No PC levels found in character_memory.txt. Using legacy tier={tier} → CR {cr}")
        return cr

    offset = TIER_OFFSET.get(tier.lower(), DEFAULT_OFFSET)
    cr = max_level + offset

    # Clamp
    cr = max(cr, max_level + 1)
    cr = min(cr, max_level + 5)
    cr = max(1, min(cr, 30))

    # BALANCE WARNINGS
    if cr >= 28:
        logger.warning(f"⚠️ DEADLY ENCOUNTER: CR {cr} for max_pc_level={max_level}, tier={tier}. Consider reducing threat level.")
    elif cr >= 25:
        logger.warning(f"⚠️ EPIC ENCOUNTER: CR {cr}. Ensure party has proper resources and healing.")
    elif max_level + offset > 30:
        logger.warning(f"⚠️ CR OVERFLOW: Calculation resulted in CR {max_level + offset} (clamped to 30). Party may be overleveled.")
    
    logger.info(
        f"📖 CR: max_pc_level={max_level}, tier={tier}, offset=+{offset} → CR {cr}"
    )
    return cr


def get_encounter_budget(cr: int) -> dict:
    """Get XP budget thresholds for a given CR."""
    return ENCOUNTER_BUDGET.get(cr, ENCOUNTER_BUDGET.get(5))


def get_cr_xp(cr: int) -> int:
    """Get XP value for a single creature of given CR."""
    return CR_XP.get(cr, 200)


def calculate_skill_dcs(cr: int) -> dict:
    """
    Calculate appropriate DCs for skill checks based on CR.
    
    Returns dict with easy, moderate, hard, very_hard DCs.
    """
    base = 8 + (cr // 2)
    
    return {
        "easy": max(8, base - 3),
        "moderate": base,
        "hard": base + 3,
        "very_hard": base + 5,
        "nearly_impossible": base + 8,
    }


def format_encounter_guidelines(cr: int, tier: str) -> str:
    """
    Generate encounter design guidelines for AI prompts.
    
    Returns formatted text block with XP budgets, DC guidelines, etc.
    """
    budget = get_encounter_budget(cr)
    dcs = calculate_skill_dcs(cr)
    max_level = get_max_pc_level()
    
    return f"""ENCOUNTER DESIGN PARAMETERS:
Target CR: {cr} | Tier: {tier} | Party Level: ~{max_level if max_level > 0 else cr}

XP BUDGET (4 players):
- Easy: {budget['easy']} XP
- Medium: {budget['medium']} XP (recommended for Act 2 encounters)
- Hard: {budget['hard']} XP (recommended for Act 4 main encounter)
- Deadly: {budget['deadly']} XP (use sparingly, with escape options)

SKILL CHECK DCs:
- Easy: DC {dcs['easy']} (should usually succeed)
- Moderate: DC {dcs['moderate']} (fair challenge)
- Hard: DC {dcs['hard']} (significant challenge)
- Very Hard: DC {dcs['very_hard']} (expert-level difficulty)

BOSS STAT GUIDELINES (CR {cr}):
- HP: ~{15 * cr} (range {12 * cr}-{18 * cr})
- AC: {13 + (cr // 4)} (range 13-18)
- Attack Bonus: +{4 + (cr // 2)} (proficiency + ability)
- Save DC: {8 + 4 + (cr // 2)} (8 + prof + ability)
- Damage per round: ~{4 + cr * 3} (medium), ~{6 + cr * 4} (high)

MINION GUIDELINES (CR {max(1, cr - 2)} to CR {cr - 1}):
- HP: {8 * max(1, cr - 2)} to {12 * max(1, cr - 1)}
- AC: {12 + ((cr - 1) // 4)}
- 2-4 minions creates an interesting action economy
"""


# Terrain and hazard suggestions by environment type
TERRAIN_FEATURES = {
    "urban": [
        "Overturned merchant carts (half cover)",
        "Narrow alleyways (difficult terrain, advantage to smaller creatures)",
        "Rooftop access (15 ft above, requires Athletics DC 12 to climb)",
        "Sewer grates (can be opened to create difficult terrain or escape)",
        "Market stalls (can be collapsed, cover or hazard)",
        "Hanging signs (can be cut to swing across or drop on enemies)",
    ],
    "underground": [
        "Stalagmites and rubble (half cover, difficult terrain)",
        "Unstable ceiling (can be collapsed with 20+ damage, DC 15 DEX save)",
        "Flooded sections (difficult terrain, extinguishes fire)",
        "Phosphorescent fungi (dim light, hallucinogenic spores DC 13 CON)",
        "Narrow passages (squeeze, disadvantage on attacks)",
        "Elevation changes (high ground +2 to ranged, fall damage risk)",
    ],
    "industrial": [
        "Heavy machinery (cover, can be activated as hazard)",
        "Conveyor belts (forced movement at start of turn)",
        "Steam vents (2d6 fire damage, DC 14 DEX to avoid)",
        "Catwalks (elevated, 20 ft fall if knocked prone)",
        "Cargo crates (full cover, can be climbed or pushed)",
        "Chemical spills (difficult terrain, 1d6 acid damage if prone)",
    ],
    "sanctum": [
        "Altar (full cover, desecration triggers effects)",
        "Pews/benches (half cover, difficult terrain)",
        "Holy symbols (undead/fiends disadvantage within 10 ft)",
        "Stained glass windows (can be shattered for dramatic entry/exit)",
        "Elevated choir loft (15 ft up, ranged advantage)",
        "Consecrated ground (healing spells +2, necrotic -2)",
    ],
    "warrens": [
        "Makeshift barricades (half cover, flammable)",
        "Rope bridges (DEX check to cross quickly, can be cut)",
        "Trash heaps (difficult terrain, concealment)",
        "Vertical shafts (climbing required, fall hazard)",
        "Dead ends (tactical retreats blocked)",
        "Hidden alcoves (surprise round opportunity, Perception DC 15)",
    ],
}


def get_terrain_suggestions(location_type: str, count: int = 3) -> List[str]:
    """Get terrain feature suggestions for a location type."""
    features = TERRAIN_FEATURES.get(location_type.lower(), TERRAIN_FEATURES["urban"])
    return random.sample(features, min(count, len(features)))


def format_stat_block_template(cr: int, creature_type: str = "humanoid") -> str:
    """
    Generate a stat block template for AI to fill in.
    
    Returns a template with appropriate values for the CR.
    """
    hp = 15 * cr
    ac = 13 + (cr // 4)
    atk = 4 + (cr // 2)
    save_dc = 8 + 4 + (cr // 2)
    
    return f"""**[CREATURE NAME]**
*Medium {creature_type}, [alignment]*

**Armor Class** {ac} ([armor type])
**Hit Points** {hp} ({cr * 2}d8 + {cr * 2})
**Speed** 30 ft.

| STR | DEX | CON | INT | WIS | CHA |
|-----|-----|-----|-----|-----|-----|
| [##] ([+#]) | [##] ([+#]) | [##] ([+#]) | [##] ([+#]) | [##] ([+#]) | [##] ([+#]) |

**Saving Throws** [proficient saves]
**Skills** [proficient skills with bonuses]
**Damage Resistances** [if any]
**Damage Immunities** [if any]
**Condition Immunities** [if any]
**Senses** darkvision 60 ft., passive Perception {10 + (cr // 2)}
**Languages** Common, [others]
**Challenge** {cr} ({get_cr_xp(cr):,} XP)

**[Trait Name].** [Trait description]

### Actions
**Multiattack.** [Creature name] makes [number] attacks with its [weapon].

**[Weapon Name].** *Melee Weapon Attack:* +{atk} to hit, reach 5 ft., one target. *Hit:* {cr + 4} ({2 + (cr // 4)}d6 + {(cr // 2) + 1}) [damage type] damage.

**[Special Action] (Recharge 5-6).** [Description]. DC {save_dc} [ability] save or [effect].

### Bonus Actions
[If applicable]

### Reactions
**[Reaction Name].** [Description]
"""


def build_encounter_prompt_block(
    cr: int,
    tier: str,
    location_type: str = "urban",
    encounter_difficulty: str = "hard",
) -> str:
    """
    Build a complete encounter design prompt block for AI generation.
    
    Includes guidelines, terrain suggestions, and stat block templates.
    """
    budget = get_encounter_budget(cr)
    terrain = get_terrain_suggestions(location_type, count=4)
    target_xp = budget.get(encounter_difficulty, budget["hard"])
    
    lines = [
        format_encounter_guidelines(cr, tier),
        "",
        f"TARGET ENCOUNTER: {encounter_difficulty.upper()} ({target_xp} XP)",
        "",
        f"SUGGESTED TERRAIN FEATURES ({location_type.upper()}):",
    ]
    
    for feature in terrain:
        lines.append(f"  - {feature}")
    
    lines.extend([
        "",
        "ENEMY COMPOSITION OPTIONS:",
        f"  A) 1 boss (CR {cr}) + 2-3 minions (CR {max(1, cr - 3)})",
        f"  B) 2 lieutenants (CR {max(1, cr - 1)}) + 4-5 minions (CR {max(1, cr - 4)})",
        f"  C) Swarm: 6-8 enemies (CR {max(1, cr - 2)} each)",
        "",
        "STAT BLOCK REQUIREMENTS:",
        "  - FULL 5e 2024 stat blocks for each unique enemy type",
        "  - Include HP, AC, attacks, special abilities",
        "  - Tactical notes: how they fight, retreat conditions",
        "  - Non-combat resolution option if appropriate",
    ])
    
    return "\n".join(lines)
