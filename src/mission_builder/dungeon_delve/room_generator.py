"""
dungeon_delve/room_generator.py — LLM-based room content generation.

Uses Ollama/Mistral to generate:
- Room names and descriptions
- Read-aloud text
- Room features
- Encounters with monsters
- Treasure
- Traps and hazards

Exported:
    generate_room_content(room, dungeon_context) -> dict
    generate_all_rooms(layout, dungeon_context) -> Dict[str, dict]
"""

from __future__ import annotations

import os
import json
import random
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import httpx

from .layouts import DungeonLayout, RoomPosition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_TIMEOUT = 120.0

# Encounter probability by room type
ENCOUNTER_CHANCE: Dict[str, float] = {
    "entry": 0.5,
    "corridor": 0.3,
    "chamber": 0.6,
    "lair": 1.0,
    "vault": 0.8,
    "shrine": 0.7,
    "workshop": 0.5,
    "prison": 0.6,
    "flooded": 0.8,
    "boss": 1.0,
}

# Monster groups by CR range
MONSTER_TABLES: Dict[str, List[Dict[str, Any]]] = {
    "low": [  # CR 1/4 - 2
        {"name": "Giant Rat", "cr": "1/4", "hp": 7},
        {"name": "Skeleton", "cr": "1/4", "hp": 13},
        {"name": "Zombie", "cr": "1/4", "hp": 22},
        {"name": "Goblin", "cr": "1/4", "hp": 7},
        {"name": "Kobold", "cr": "1/8", "hp": 5},
        {"name": "Giant Spider", "cr": "1", "hp": 26},
        {"name": "Ghoul", "cr": "1", "hp": 22},
        {"name": "Specter", "cr": "1", "hp": 22},
        {"name": "Bugbear", "cr": "1", "hp": 27},
        {"name": "Hobgoblin", "cr": "1/2", "hp": 11},
        {"name": "Gray Ooze", "cr": "1/2", "hp": 22},
        {"name": "Ogre", "cr": "2", "hp": 59},
        {"name": "Ghast", "cr": "2", "hp": 36},
        {"name": "Mimic", "cr": "2", "hp": 58},
    ],
    "medium": [  # CR 3-5
        {"name": "Owlbear", "cr": "3", "hp": 59},
        {"name": "Minotaur", "cr": "3", "hp": 76},
        {"name": "Wight", "cr": "3", "hp": 45},
        {"name": "Phase Spider", "cr": "3", "hp": 32},
        {"name": "Wraith", "cr": "5", "hp": 67},
        {"name": "Troll", "cr": "5", "hp": 84},
        {"name": "Shambling Mound", "cr": "5", "hp": 136},
        {"name": "Flesh Golem", "cr": "5", "hp": 93},
        {"name": "Salamander", "cr": "5", "hp": 90},
        {"name": "Otyugh", "cr": "5", "hp": 114},
    ],
    "high": [  # CR 6-10
        {"name": "Young White Dragon", "cr": "6", "hp": 133},
        {"name": "Medusa", "cr": "6", "hp": 127},
        {"name": "Cloaker", "cr": "8", "hp": 78},
        {"name": "Spirit Naga", "cr": "8", "hp": 75},
        {"name": "Hydra", "cr": "8", "hp": 172},
        {"name": "Clay Golem", "cr": "9", "hp": 133},
        {"name": "Stone Golem", "cr": "10", "hp": 178},
        {"name": "Young Red Dragon", "cr": "10", "hp": 178},
        {"name": "Aboleth", "cr": "10", "hp": 135},
    ],
    "extreme": [  # CR 11+
        {"name": "Beholder", "cr": "13", "hp": 180},
        {"name": "Adult Black Dragon", "cr": "14", "hp": 195},
        {"name": "Mummy Lord", "cr": "15", "hp": 97},
        {"name": "Adult Blue Dragon", "cr": "16", "hp": 225},
        {"name": "Death Knight", "cr": "17", "hp": 180},
        {"name": "Lich", "cr": "21", "hp": 135},
    ],
}

# Treasure by tier
TREASURE_TABLES: Dict[str, List[str]] = {
    "low": [
        "A pouch containing 2d6 gold pieces",
        "A tarnished silver ring worth 10 gp",
        "A healing potion",
        "A small gemstone worth 25 gp",
        "An old but serviceable weapon",
    ],
    "medium": [
        "A chest containing 4d6 x 10 gold pieces",
        "A +1 weapon",
        "2 healing potions",
        "A scroll of a 2nd-level spell",
        "A piece of jewelry worth 100 gp",
    ],
    "high": [
        "A locked strongbox with 2d4 x 100 gold pieces",
        "A +2 weapon or +1 armor",
        "A rare magic item",
        "A potion of greater healing",
        "A spellbook with 1d4 spells",
    ],
    "extreme": [
        "A hoard of 3d6 x 100 gold pieces and gems",
        "A very rare magic item",
        "An artifact fragment",
        "A legendary weapon component",
    ],
}


# ---------------------------------------------------------------------------
# Dungeon Context
# ---------------------------------------------------------------------------

@dataclass
class DungeonContext:
    """Context for generating dungeon room content."""
    dungeon_name: str
    location_description: str
    faction: str
    aesthetic: str
    party_level: int
    cr_target: int
    history: str = ""
    objective: str = "Clear the dungeon and defeat its master"
    
    def get_cr_tier(self) -> str:
        """Get the CR tier for monster selection."""
        if self.cr_target <= 2:
            return "low"
        elif self.cr_target <= 5:
            return "medium"
        elif self.cr_target <= 10:
            return "high"
        else:
            return "extreme"


# ---------------------------------------------------------------------------
# Room Content Generation
# ---------------------------------------------------------------------------

def _get_encounter(room: RoomPosition, context: DungeonContext) -> Optional[Dict]:
    """Generate an encounter for a room based on type and CR."""
    # Check if this room has an encounter
    chance = ENCOUNTER_CHANCE.get(room.room_type, 0.5)
    if room.room_type != "boss" and random.random() > chance:
        return None
    
    tier = context.get_cr_tier()
    monsters = MONSTER_TABLES.get(tier, MONSTER_TABLES["low"])
    
    # Boss rooms get stronger single monsters
    if room.room_type == "boss":
        # Pick a higher-tier monster if possible
        higher_tiers = {"low": "medium", "medium": "high", "high": "extreme", "extreme": "extreme"}
        boss_tier = higher_tiers.get(tier, tier)
        boss_monsters = MONSTER_TABLES.get(boss_tier, monsters)
        monster = random.choice(boss_monsters)
        count = 1
        description = f"The dungeon's master: a fearsome {monster['name']}"
    else:
        monster = random.choice(monsters)
        # Scale count by room type
        if room.room_type in ("lair", "chamber"):
            count = random.randint(2, 4)
        elif room.room_type == "corridor":
            count = random.randint(1, 2)
        else:
            count = random.randint(1, 3)
        
        description = f"{count} {monster['name']}{'s' if count > 1 else ''} lurking in the {room.room_type}"
    
    return {
        "description": description,
        "creatures": [
            {
                "name": monster["name"],
                "count": count,
                "cr": monster["cr"],
                "hp": monster["hp"],
                "notes": "Boss" if room.room_type == "boss" else "",
            }
        ],
    }


def _get_treasure(room: RoomPosition, context: DungeonContext) -> Optional[str]:
    """Generate treasure for a room."""
    # Treasure more likely in vaults, boss rooms, lairs
    treasure_chance = {
        "vault": 1.0,
        "boss": 0.9,
        "lair": 0.6,
        "shrine": 0.4,
        "chamber": 0.3,
    }.get(room.room_type, 0.2)
    
    if random.random() > treasure_chance:
        return None
    
    tier = context.get_cr_tier()
    treasures = TREASURE_TABLES.get(tier, TREASURE_TABLES["low"])
    
    # Boss rooms get better treasure
    if room.room_type == "boss":
        higher_tiers = {"low": "medium", "medium": "high", "high": "extreme", "extreme": "extreme"}
        boss_tier = higher_tiers.get(tier, tier)
        treasures = TREASURE_TABLES.get(boss_tier, treasures)
    
    return random.choice(treasures)


def _get_traps(room: RoomPosition, context: DungeonContext) -> Optional[str]:
    """Generate traps/hazards for a room."""
    trap_chance = {
        "vault": 0.8,
        "corridor": 0.4,
        "entry": 0.5,
        "shrine": 0.3,
    }.get(room.room_type, 0.2)
    
    if random.random() > trap_chance:
        return None
    
    dc = 10 + (context.party_level // 2)
    damage = f"{context.party_level // 2 + 1}d6"
    
    traps = [
        f"Pressure plate triggers poison darts (DC {dc} Dex, {damage} poison)",
        f"Tripwire releases swinging blade (DC {dc} Dex, {damage} slashing)",
        f"Hidden pit trap (DC {dc} Perception to notice, {damage} falling)",
        f"Glyph of warding on door (DC {dc} Int to notice, {damage} force)",
        f"Collapsing ceiling section (DC {dc} Dex, {damage} bludgeoning)",
        f"Poisoned needle in lock (DC {dc} Con, {damage} poison)",
    ]
    
    return random.choice(traps)


# ---------------------------------------------------------------------------
# LLM Generation
# ---------------------------------------------------------------------------

_ROOM_PROMPT_TEMPLATE = """You are generating content for a D&D 5e dungeon room.

DUNGEON: {dungeon_name}
LOCATION: {location_description}
AESTHETIC: {aesthetic}
FACTION: {faction}

ROOM TYPE: {room_type}
ROOM NUMBER: {room_num} of {total_rooms}
ROOM POSITION: {position_desc}

Generate the following for this room in JSON format:
{{
    "name": "A short evocative name for the room (3-5 words)",
    "read_aloud": "A 2-3 sentence read-aloud description for players (what they see, hear, smell)",
    "features": ["Feature 1", "Feature 2", "Feature 3"],
    "dm_notes": "Brief DM notes about this room's purpose or secrets"
}}

RULES:
- Name should be evocative but short
- Read-aloud should be immersive, second person ("You see...")
- Features are physical things in the room that could be interacted with
- Keep it concise but evocative
- Match the {aesthetic} aesthetic

Respond with ONLY the JSON, no other text."""


async def _generate_room_llm(
    room: RoomPosition,
    room_num: int,
    total_rooms: int,
    context: DungeonContext,
) -> Optional[Dict]:
    """Generate room content using LLM."""
    
    # Determine position description
    if room_num == 1:
        position_desc = "Entry room - where adventurers enter the dungeon"
    elif room_num == total_rooms:
        position_desc = "Final room - the dungeon's heart/boss chamber"
    else:
        position_desc = f"Middle room {room_num} - connecting chambers"
    
    prompt = _ROOM_PROMPT_TEMPLATE.format(
        dungeon_name=context.dungeon_name,
        location_description=context.location_description,
        aesthetic=context.aesthetic,
        faction=context.faction,
        room_type=room.room_type,
        room_num=room_num,
        total_rooms=total_rooms,
        position_desc=position_desc,
    )
    
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        
        content = data.get("message", {}).get("content", "").strip()
        
        # Extract JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        return json.loads(content)
        
    except json.JSONDecodeError as e:
        logger.warning(f"🏰 Failed to parse LLM response for {room.room_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"🏰 LLM generation failed for {room.room_id}: {e}")
        return None


def _generate_room_fallback(
    room: RoomPosition,
    room_num: int,
    context: DungeonContext,
) -> Dict:
    """Generate basic room content without LLM (fallback)."""
    
    # Room name templates by type
    name_templates = {
        "entry": ["Entrance Hall", "Gate Chamber", "Entry Passage", "Threshold"],
        "corridor": ["Dark Corridor", "Connecting Passage", "Narrow Hall", "Side Tunnel"],
        "chamber": ["Main Chamber", "Central Room", "Open Hall", "Wide Chamber"],
        "lair": ["Creature's Den", "Monster Nest", "Beast's Lair", "Hunting Ground"],
        "vault": ["Treasure Vault", "Locked Chamber", "Hidden Cache", "Strongroom"],
        "shrine": ["Dark Shrine", "Altar Room", "Sacred Chamber", "Prayer Hall"],
        "workshop": ["Old Workshop", "Forge Room", "Crafting Chamber", "Work Hall"],
        "prison": ["Cell Block", "Prisoner Cells", "Dungeon Cells", "Holding Area"],
        "flooded": ["Flooded Chamber", "Drowned Hall", "Water Room", "Submerged Area"],
        "boss": ["Throne Room", "Master's Chamber", "Final Hall", "Heart of Darkness"],
    }
    
    # Read-aloud templates
    read_aloud_templates = {
        "entry": "You step through the threshold into a cold, dark space. The air is stale and carries hints of decay. Shadows dance at the edge of your torchlight.",
        "corridor": "A narrow passage stretches before you, its walls close and oppressive. Your footsteps echo off the stone. Something skitters in the darkness ahead.",
        "chamber": "You enter a larger room, your torchlight barely reaching the far walls. Debris litters the floor. The ceiling disappears into shadow above.",
        "lair": "A foul smell hits you as you enter. Bones and refuse are scattered across the floor. Something has been living here—something large.",
        "vault": "You find what appears to be a secured chamber. The door was once locked, and traces of protective measures remain. Something valuable may be hidden here.",
        "shrine": "Religious symbols mark the walls of this chamber. A stone altar dominates the center, stained with age. An oppressive presence lingers here.",
        "workshop": "Workbenches line the walls, covered with rusted tools and strange apparatus. Half-finished projects lie abandoned. The air smells of old chemicals.",
        "prison": "Iron bars divide this room into cells. Chains hang from the walls. The echo of past suffering seems to linger in the cold air.",
        "flooded": "Water covers the floor to ankle depth, black and still. The smell of stagnation fills your nostrils. Something ripples beneath the surface.",
        "boss": "You enter the heart of this place. The room is larger, grander, with a commanding presence at its center. This is where the master dwells.",
    }
    
    # Features by type
    feature_templates = {
        "entry": ["Heavy iron door", "Fallen torch sconce", "Carved warning symbols", "Cobwebs in corners"],
        "corridor": ["Torch brackets (empty)", "Cracked floor tiles", "Side alcoves", "Low ceiling"],
        "chamber": ["Stone pillars", "Broken furniture", "Collapsed section", "Faded murals"],
        "lair": ["Bone pile", "Nest of debris", "Claw marks on walls", "Half-eaten remains"],
        "vault": ["Reinforced door", "Locked chest", "Hidden compartment", "Protective runes"],
        "shrine": ["Stone altar", "Religious icons", "Offering bowls", "Devotional candles"],
        "workshop": ["Workbenches", "Tool racks", "Arcane apparatus", "Unfinished projects"],
        "prison": ["Iron-barred cells", "Wall chains", "Jailer's station", "Prisoner effects"],
        "flooded": ["Standing water", "Submerged objects", "Wet footprints", "Dripping ceiling"],
        "boss": ["Raised platform", "Ornate throne", "Trophy display", "Ominous lighting"],
    }
    
    room_type = room.room_type
    name = random.choice(name_templates.get(room_type, ["Chamber"]))
    
    return {
        "name": name,
        "read_aloud": read_aloud_templates.get(room_type, "You enter a dark chamber."),
        "features": random.sample(feature_templates.get(room_type, ["Stone walls"]), min(3, len(feature_templates.get(room_type, [])))),
        "dm_notes": f"Standard {room_type} room in a {context.aesthetic} dungeon.",
    }


# ---------------------------------------------------------------------------
# Main Generation Functions
# ---------------------------------------------------------------------------

async def generate_room_content(
    room: RoomPosition,
    room_num: int,
    total_rooms: int,
    context: DungeonContext,
    use_llm: bool = True,
) -> Dict:
    """
    Generate complete content for a single room.
    
    Args:
        room: Room position with type and exits
        room_num: Room number (1-indexed)
        total_rooms: Total number of rooms in dungeon
        context: Dungeon context for generation
        use_llm: Whether to use LLM for descriptions
    
    Returns:
        Dict with name, read_aloud, features, encounter, treasure, traps
    """
    logger.info(f"🏰 Generating content for {room.room_id} ({room.room_type})")
    
    # Generate descriptions (LLM or fallback)
    if use_llm:
        llm_content = await _generate_room_llm(room, room_num, total_rooms, context)
        if llm_content:
            content = llm_content
        else:
            content = _generate_room_fallback(room, room_num, context)
    else:
        content = _generate_room_fallback(room, room_num, context)
    
    # Add encounter, treasure, traps
    content["encounter"] = _get_encounter(room, context)
    content["treasure"] = _get_treasure(room, context)
    content["traps"] = _get_traps(room, context)
    content["type"] = room.room_type
    
    return content


async def generate_all_rooms(
    layout: DungeonLayout,
    context: DungeonContext,
    use_llm: bool = True,
    delay_between: float = 1.0,
) -> Dict[str, Dict]:
    """
    Generate content for all rooms in a dungeon layout.
    
    Args:
        layout: The dungeon layout
        context: Dungeon context for generation
        use_llm: Whether to use LLM for descriptions
        delay_between: Seconds between LLM calls
    
    Returns:
        Dict mapping room_id → room content dict
    """
    logger.info(f"🏰 Generating content for {len(layout.rooms)} rooms")
    
    room_content: Dict[str, Dict] = {}
    total = len(layout.rooms)
    
    for i, room in enumerate(layout.rooms, 1):
        content = await generate_room_content(room, i, total, context, use_llm)
        room_content[room.room_id] = content
        
        # Delay between LLM calls
        if use_llm and i < total:
            await asyncio.sleep(delay_between)
    
    logger.info(f"🏰 Generated content for {len(room_content)} rooms")
    return room_content


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "DungeonContext",
    "generate_room_content",
    "generate_all_rooms",
    "MONSTER_TABLES",
    "TREASURE_TABLES",
]
