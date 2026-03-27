"""
rewards.py — Mission rewards, loot tables, and consequence generation.

Provides:
- Treasure by CR/tier
- Faction reputation effects
- Success/failure consequences
- Magic item suggestions
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

# Gold ranges by tier
GOLD_BY_TIER: Dict[str, Tuple[int, int]] = {
    "local":         (50, 150),
    "patrol":        (75, 200),
    "escort":        (100, 300),
    "standard":      (150, 400),
    "investigation": (200, 500),
    "rift":          (300, 800),
    "dungeon":       (400, 1000),
    "major":         (500, 1500),
    "inter-guild":   (750, 2000),
    "high-stakes":   (1000, 3000),
    "epic":          (2000, 5000),
    "divine":        (2500, 6000),
    "tower":         (3000, 8000),
}

# Reputation changes by outcome
REP_CHANGES: Dict[str, Dict[str, int]] = {
    "success": {
        "posting_faction": 5,
        "allied_factions": 2,
        "neutral_factions": 1,
        "opposed_factions": -1,
    },
    "partial_success": {
        "posting_faction": 2,
        "allied_factions": 1,
        "neutral_factions": 0,
        "opposed_factions": 0,
    },
    "failure": {
        "posting_faction": -3,
        "allied_factions": -1,
        "neutral_factions": 0,
        "opposed_factions": 2,
    },
    "betrayal": {
        "posting_faction": -10,
        "allied_factions": -5,
        "neutral_factions": -2,
        "opposed_factions": 5,
    },
}

# Magic item tiers by CR
MAGIC_ITEM_TIERS = {
    range(1, 5): "common",
    range(5, 9): "uncommon",
    range(9, 13): "rare",
    range(13, 17): "very_rare",
    range(17, 31): "legendary",
}


def get_magic_item_tier(cr: int) -> str:
    """Get appropriate magic item rarity for a CR."""
    for cr_range, tier in MAGIC_ITEM_TIERS.items():
        if cr in cr_range:
            return tier
    return "uncommon"


# Sample magic items by tier (5e 2024 compatible)
MAGIC_ITEMS: Dict[str, List[str]] = {
    "common": [
        "Potion of Healing",
        "Scroll of a 1st-level spell",
        "Driftglobe",
        "Cloak of Billowing",
        "Hat of Wizardry",
        "Moon-Touched Sword",
        "Tankard of Sobriety",
    ],
    "uncommon": [
        "Potion of Greater Healing",
        "+1 Weapon",
        "+1 Shield",
        "Bag of Holding",
        "Cloak of Protection",
        "Goggles of Night",
        "Sending Stones",
        "Wand of Magic Missiles",
        "Immovable Rod",
        "Boots of Elvenkind",
    ],
    "rare": [
        "Potion of Superior Healing",
        "+2 Weapon",
        "+1 Armor",
        "Cloak of Displacement",
        "Ring of Protection",
        "Flame Tongue",
        "Wand of Fireballs",
        "Amulet of Health",
        "Belt of Dwarvenkind",
        "Ring of Spell Storing",
    ],
    "very_rare": [
        "Potion of Supreme Healing",
        "+3 Weapon",
        "+2 Armor",
        "Ring of Regeneration",
        "Staff of Power",
        "Cloak of Invisibility",
        "Manual of Bodily Health",
        "Dancing Sword",
        "Ioun Stone (various)",
    ],
    "legendary": [
        "Potion of Storm Giant Strength",
        "+3 Armor",
        "Vorpal Sword",
        "Ring of Three Wishes",
        "Staff of the Magi",
        "Holy Avenger",
        "Luck Blade",
        "Robe of the Archmagi",
    ],
}


def get_random_magic_item(cr: int, count: int = 1) -> List[str]:
    """Get random magic items appropriate for CR."""
    tier = get_magic_item_tier(cr)
    items = MAGIC_ITEMS.get(tier, MAGIC_ITEMS["uncommon"])
    return random.sample(items, min(count, len(items)))


def calculate_gold_reward(tier: str, party_size: int = 4) -> Tuple[int, int]:
    """
    Calculate gold reward range for a mission.
    
    Returns (min, max) gold per player.
    """
    base_min, base_max = GOLD_BY_TIER.get(tier.lower(), (150, 400))
    
    # Adjust slightly for party size
    multiplier = 4 / max(party_size, 1)
    
    return (int(base_min * multiplier), int(base_max * multiplier))


def format_rewards_block(
    tier: str,
    cr: int,
    faction: str,
    mission_reward_text: str = "",
) -> str:
    """
    Generate a rewards section for the module.
    
    Returns formatted text block for AI prompts.
    """
    gold_min, gold_max = calculate_gold_reward(tier)
    item_tier = get_magic_item_tier(cr)
    sample_items = get_random_magic_item(cr, count=3)
    
    lines = [
        "## Rewards",
        "",
        f"**Mission Payment**: {gold_min}-{gold_max} gp per party member",
        f"**Magic Item Tier**: {item_tier.replace('_', ' ').title()}",
        "",
        "### Treasure Options (pick 1-2):",
    ]
    
    for item in sample_items:
        lines.append(f"  - {item}")
    
    lines.extend([
        "",
        "### Faction Reputation",
        f"**{faction}** (posting faction):",
        "  - Success: +5 reputation",
        "  - Partial Success: +2 reputation",
        "  - Failure: -3 reputation",
        "",
        "### Bonus Rewards (for exceptional play)",
        "  - Discovering hidden information: +50-100 gp",
        "  - Saving innocent lives: +1 faction rep, possible contact NPC",
        "  - Exposing faction corruption: Variable (could be positive or negative)",
        "  - Creative non-combat solution: +1 rep, DM inspiration award",
    ])
    
    if mission_reward_text:
        lines.extend([
            "",
            "### Mission-Specific Rewards",
            mission_reward_text,
        ])
    
    return "\n".join(lines)


# Consequence templates
SUCCESS_CONSEQUENCES = [
    "The posting faction's influence in {location} grows stronger.",
    "A new contact NPC becomes available: {npc_name} owes the party a favor.",
    "The party gains access to {resource} through faction connections.",
    "News of the party's success spreads — +1 reputation with {allied_faction}.",
    "The antagonist's organization is weakened. Related missions may be affected.",
    "The party discovers a lead on {future_plot_hook}.",
]

FAILURE_CONSEQUENCES = [
    "The posting faction's plans in {location} are set back significantly.",
    "An innocent NPC ({npc_name}) suffers consequences for the party's failure.",
    "The antagonist's influence grows. {opposed_faction} gains +2 reputation.",
    "Resources are lost — future missions in this area have -1 to relevant checks.",
    "The party gains a new enemy: {antagonist_name} remembers them.",
    "A rift activity in the area intensifies (if applicable).",
]

PARTIAL_SUCCESS_CONSEQUENCES = [
    "The objective is met, but at a cost. {sacrifice} is lost or damaged.",
    "The posting faction is satisfied but not impressed. Normal reputation gain.",
    "The antagonist escapes but their operation is disrupted.",
    "Collateral damage creates complications: {complication}.",
    "A new lead emerges, but so does a new threat.",
]


def generate_consequence_template(
    outcome: str,
    location: str = "the district",
    npc_name: str = "a local contact",
    resource: str = "useful equipment",
    allied_faction: str = "an allied faction",
    opposed_faction: str = "an opposing faction",
    future_plot_hook: str = "a larger conspiracy",
    antagonist_name: str = "the antagonist",
    sacrifice: str = "something valuable",
    complication: str = "angry locals",
) -> str:
    """Generate a consequence description from templates."""
    if outcome == "success":
        templates = SUCCESS_CONSEQUENCES
    elif outcome == "failure":
        templates = FAILURE_CONSEQUENCES
    else:
        templates = PARTIAL_SUCCESS_CONSEQUENCES
    
    template = random.choice(templates)
    
    return template.format(
        location=location,
        npc_name=npc_name,
        resource=resource,
        allied_faction=allied_faction,
        opposed_faction=opposed_faction,
        future_plot_hook=future_plot_hook,
        antagonist_name=antagonist_name,
        sacrifice=sacrifice,
        complication=complication,
    )


def format_consequences_prompt(tier: str, faction: str) -> str:
    """Generate the consequences section guidance for AI prompts."""
    return f"""## Act 5: Resolution & Consequences

Write outcomes for:

### Success
- How the {faction} rewards and recognizes the party
- What changes in the Undercity as a result
- Any new opportunities that open up
- Closing narration (2-3 sentences, NO "Read Aloud" label)

### Failure
- Consequences for the {faction} and the Undercity
- What the antagonist gains from the party's failure
- Future complications this creates
- Closing narration for failure (2-3 sentences)

### Partial Success (creative solutions)
- What the party achieved vs. what they missed
- Mixed reactions from the {faction}
- Both opportunities and complications

### Reputation Effects
- Success: +5 {faction}, +2 allied factions
- Partial: +2 {faction}
- Failure: -3 {faction}, +2 opposing factions

### Loot Table
Provide a treasure table with:
- Guaranteed rewards (mission payment)
- Possible rewards (based on thoroughness)
- Bonus rewards (exceptional play)
- At least one {get_magic_item_tier(8)} magic item option
"""


def build_loot_table(
    cr: int,
    tier: str,
    guaranteed_gold: bool = True,
    magic_item_chance: float = 0.5,
) -> str:
    """Build a formatted loot table."""
    gold_min, gold_max = calculate_gold_reward(tier)
    item_tier = get_magic_item_tier(cr)
    
    lines = [
        "### Loot Table",
        "",
        "**Guaranteed Rewards:**",
        f"- Mission payment: {gold_min}-{gold_max} gp per party member",
        "- Faction favor token (can be spent for one small faction service)",
        "",
        "**Possible Rewards (d6):**",
    ]
    
    items = get_random_magic_item(cr, count=4)
    lines.extend([
        f"- 1-2: Additional {gold_min // 2} gp from recovered valuables",
        f"- 3-4: {items[0] if len(items) > 0 else 'Potion of Healing'}",
        f"- 5: {items[1] if len(items) > 1 else '+1 Weapon'}",
        f"- 6: {items[2] if len(items) > 2 else 'Uncommon magic item (DM choice)'}",
    ])
    
    lines.extend([
        "",
        "**Bonus Rewards:**",
        f"- Exceptional roleplay: {items[3] if len(items) > 3 else 'Rare consumable'}",
        "- Discovering hidden objective: +100 gp, +1 additional faction rep",
        "- Saving all innocents: NPC contact becomes available for future missions",
    ])
    
    return "\n".join(lines)
