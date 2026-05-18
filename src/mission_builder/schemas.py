"""
schemas.py — Mission JSON schema definitions and validators.

Provides comprehensive schema for mission module generation output.
Supports both standard missions and dungeon delves.

Schema hierarchy:
- MissionModule (root)
  - metadata: MissionMetadata
  - content: MissionContent
  - encounters: List[Encounter]
  - npcs: List[NPC]
  - images: List[ImageAsset]
  - loot_tables: List[LootTable]

Exported:
  - MissionModule, MissionMetadata, MissionContent, etc. (TypedDicts)
  - validate_mission_module() - Full schema validator
  - get_mission_schema() - Complete JSON schema for reference
"""

from __future__ import annotations

import json
import logging
from typing import TypedDict, Optional, List, Dict, Any, Literal
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TypedDict Definitions (for type hints)
# ---------------------------------------------------------------------------

class MissionMetadata(TypedDict, total=False):
    """Mission metadata and tracking."""
    id: str  # Unique mission ID (UUID or hash)
    title: str
    faction: str
    tier: str  # "local", "patrol", "escort", "standard", "investigation", "rift", "dungeon", "major", "inter-guild", "high-stakes", "epic", "divine", "tower"
    mission_type: str  # "escort", "recovery", "investigation", "battle", "ambush", "negotiation", "theft", "rescue", "exploration", "discovery", "delivery", "sabotage", "infiltration", "assassination", "defense", "puzzle", "gathering", "political"
    cr: int  # Challenge Rating
    party_level: int  # Target party level
    player_name: str  # Claiming player/party name
    player_count: int  # Expected party size
    runtime_minutes: int  # Expected duration
    reward: str  # Reward description
    difficulty_rating: int  # NEW: Difficulty 1-10 (easy to epic). Use this instead of difficulty.
    generated_at: str  # ISO8601 timestamp
    version: str  # Schema version (e.g., "1.0")


class MissionContent(TypedDict, total=False):
    """Mission narrative and structural content."""
    overview: str  # Mission overview/background
    briefing: str  # Player briefing section
    act_1: str  # Act 1 content
    act_2: str  # Act 2 content
    act_3: str  # Act 3 content
    act_4: str  # Act 4 content
    act_5: str  # Act 5/resolution content
    rewards_summary: str  # Rewards and consequences


class LocationInfo(TypedDict, total=False):
    """Information about a location involved in the mission."""
    name: str
    district: str
    type: str  # "dungeon", "tavern", "hideout", "temple", "merchant_hall", etc.
    description: str
    history: str
    key_features: List[str]  # ["fountain", "statue", "alcove", ...]
    danger_level: str  # "low", "moderate", "high", "extreme"
    npcs: List[str]  # NPC names found here


class CreatureStats(TypedDict, total=False):
    """D&D 5e creature statistics."""
    name: str
    cr: float  # Challenge Rating
    hp: int
    ac: int  # Armor Class
    size: str  # "tiny", "small", "medium", "large", "huge", "gargantuan"
    type: str  # "humanoid", "beast", "undead", "abomination", etc.
    alignment: str
    resistances: List[str]
    immunities: List[str]
    vulnerabilities: List[str]
    speed: Dict[str, str]  # {"walk": "30 ft.", "fly": "60 ft.", ...}
    skills: Dict[str, str]  # Skill modifiers
    senses: Dict[str, str]  # Passive perception, etc.
    languages: List[str]
    traits: List[Dict[str, str]]  # [{"name": "...", "description": "..."}]
    actions: List[Dict[str, str]]
    legendary_actions: List[Dict[str, str]]
    reactions: List[Dict[str, str]]


class Encounter(TypedDict, total=False):
    """Combat or social encounter."""
    id: str  # Unique encounter ID
    name: str
    type: str  # "combat", "social", "exploration", "trap", "skill_challenge"
    difficulty: str  # DEPRECATED: "easy", "medium", "hard", "deadly" — use difficulty_rating instead
    difficulty_rating: int  # NEW: Difficulty 1-10 scale (easy to epic)
    location: str  # Where it takes place
    description: str  # What happens
    creatures: List[CreatureStats]  # Creatures involved
    party_xp: int  # XP reward for victory
    loot: List[str]  # Item references or descriptions
    tactics: str  # Combat tactics for monsters


class NPC(TypedDict, total=False):
    """Non-Player Character."""
    id: str  # Unique NPC ID
    name: str
    title: str  # "Captain", "Grove Master", etc.
    location: str  # Where usually found
    role: str  # "quest_giver", "ally", "enemy", "neutral", "information_broker"
    race: str
    class_name: str
    faction: str
    alignment: str
    description: str  # Physical description
    personality: List[str]  # Key traits
    goals: List[str]
    quotes: List[str]  # Example dialogue
    relationships: Dict[str, str]  # {"other_npc_id": "relationship_type"}
    statblock: Optional[CreatureStats]


class LootTable(TypedDict, total=False):
    """Treasure/loot generation table."""
    id: str
    name: str
    description: str
    rolls: int  # Number of rolls to make
    items: List[Dict[str, Any]]  # [{"name": "...", "rarity": "...", "price": "...", "count": "..."}]


class ImageAsset(TypedDict, total=False):
    """Reference to an image asset (map, creature art, location, etc.)."""
    id: str  # Unique asset ID
    filename: str  # Relative path to image file
    type: str  # "battle_map", "location", "creature", "item", "npc_portrait"
    title: str
    description: str
    associated_encounter: Optional[str]  # Encounter ID if linked


class DungeonRoom(TypedDict, total=False):
    """Room in a dungeon delve."""
    id: str
    number: int  # 1-indexed room number
    name: str
    type: str  # "entrance", "corridor", "chamber", "treasure", "boss", etc.
    description: str  # Detailed room description
    features: List[str]  # ["fountain", "statue", "concealed door", ...]
    exits: Dict[str, str]  # {"north": "room_id", "east": "room_id", ...}
    encounter: Optional[Encounter]
    treasure: Optional[LootTable]
    traps: List[Dict[str, Any]]  # [{"name": "...", "trigger": "...", "dc": ..., ...}]
    secrets: List[str]  # Hidden things to discover
    map_tile: Optional[ImageAsset]  # Reference to room tile image


class DungeonDelveContent(TypedDict, total=False):
    """Dungeon-delve-specific content."""
    layout_name: str
    aesthetic: str  # "gothic", "natural", "arcane", "industrial", etc.
    total_rooms: int
    entrance_room_id: str
    boss_room_id: str
    rooms: List[DungeonRoom]
    composite_map: Optional[ImageAsset]  # Reference to full dungeon map


class MissionModule(TypedDict, total=False):
    """
    Complete mission module data.
    Top-level structure for all generated missions.
    """
    # Core
    metadata: MissionMetadata
    content: MissionContent
    
    # Encounters, NPCs, rewards
    encounters: List[Encounter]
    npcs: List[NPC]
    loot_tables: List[LootTable]
    
    # Assets
    images: List[ImageAsset]
    
    # Optional mission-type-specific content
    locations: List[LocationInfo]
    dungeon_delve: Optional[DungeonDelveContent]
    
    # For DOCX compatibility (temporary, for backward compat)
    sections: Optional[Dict[str, str]]  # {"overview": "...", "acts_1_2": "..."}


# ---------------------------------------------------------------------------
# Schema Validation
# ---------------------------------------------------------------------------

def validate_mission_module(data: Dict[str, Any]) -> tuple[bool, List[str]]:
    """
    Validate mission module data against schema.
    
    Args:
        data: Mission module dict to validate
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    # Check required top-level keys
    required_keys = ["metadata", "content"]
    for key in required_keys:
        if key not in data:
            errors.append(f"Missing required key: {key}")
    
    # Validate metadata
    if "metadata" in data:
        meta = data["metadata"]
        required_meta = ["title", "faction", "tier", "mission_type", "cr", "party_level"]
        for key in required_meta:
            if key not in meta or not meta[key]:
                errors.append(f"metadata missing/empty: {key}")
    
    # Validate content
    if "content" in data:
        content = data["content"]
        required_content = ["overview"]
        for key in required_content:
            if key not in content or not content[key]:
                errors.append(f"content missing/empty: {key}")
    
    # Validate encounters if present
    if "encounters" in data and isinstance(data["encounters"], list):
        for i, enc in enumerate(data["encounters"]):
            if not enc.get("name"):
                errors.append(f"encounters[{i}] missing name")
            if not enc.get("type"):
                errors.append(f"encounters[{i}] missing type")
    
    # Validate NPCs if present
    if "npcs" in data and isinstance(data["npcs"], list):
        for i, npc in enumerate(data["npcs"]):
            if not npc.get("name"):
                errors.append(f"npcs[{i}] missing name")
    
    # Validate images if present
    if "images" in data and isinstance(data["images"], list):
        for i, img in enumerate(data["images"]):
            if not img.get("filename"):
                errors.append(f"images[{i}] missing filename")
            if not img.get("type"):
                errors.append(f"images[{i}] missing type")
    
    # Dungeon delve specific validation
    if data.get("metadata", {}).get("mission_type") == "dungeon-delve":
        if "dungeon_delve" not in data or not data["dungeon_delve"]:
            errors.append("dungeon-delve mission missing dungeon_delve content")
        elif "rooms" not in data["dungeon_delve"]:
            errors.append("dungeon_delve missing rooms list")
    
    return len(errors) == 0, errors


def log_validation_results(is_valid: bool, errors: List[str], mission_title: str = "Unknown"):
    """Log validation results."""
    if is_valid:
        logger.info(f"✅ Mission '{mission_title}' schema valid")
    else:
        logger.error(f"❌ Mission '{mission_title}' schema validation failed:")
        for error in errors:
            logger.error(f"   - {error}")


# ---------------------------------------------------------------------------
# JSON Schema Reference (for external tools)
# ---------------------------------------------------------------------------

def get_mission_schema() -> Dict[str, Any]:
    """
    Return full JSON schema for mission modules.
    Useful for external validation tools, documentation, etc.
    """
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Tower of Last Chance - Mission Module Schema",
        "description": "Complete schema for generated D&D 5e mission modules",
        "type": "object",
        "required": ["metadata", "content"],
        "properties": {
            "metadata": {
                "type": "object",
                "required": ["title", "faction", "tier", "mission_type", "cr", "party_level"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "faction": {"type": "string"},
                    "tier": {
                        "type": "string",
                        "enum": [
                            "local", "patrol", "escort", "standard", "investigation",
                            "rift", "dungeon", "major", "inter-guild", "high-stakes",
                            "epic", "divine", "tower"
                        ]
                    },
                    "mission_type": {
                        "type": "string",
                        "enum": ["standard", "dungeon-delve", "investigation", "combat", "social", "heist"]
                    },
                    "cr": {"type": "integer", "minimum": 0},
                    "party_level": {"type": "integer", "minimum": 1, "maximum": 20},
                    "player_name": {"type": "string"},
                    "player_count": {"type": "integer", "minimum": 1},
                    "runtime_minutes": {"type": "integer", "minimum": 15},
                    "reward": {"type": "string"},
                    "generated_at": {"type": "string", "format": "date-time"},
                    "version": {"type": "string"},
                }
            },
            "content": {
                "type": "object",
                "required": ["overview"],
                "properties": {
                    "overview": {"type": "string"},
                    "briefing": {"type": "string"},
                    "act_1": {"type": "string"},
                    "act_2": {"type": "string"},
                    "act_3": {"type": "string"},
                    "act_4": {"type": "string"},
                    "act_5": {"type": "string"},
                    "rewards_summary": {"type": "string"},
                }
            },
            "encounters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "type"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "difficulty": {"type": "string"},
                        "location": {"type": "string"},
                        "description": {"type": "string"},
                        "creatures": {"type": "array"},
                        "party_xp": {"type": "integer"},
                    }
                }
            },
            "npcs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "title": {"type": "string"},
                        "location": {"type": "string"},
                        "role": {"type": "string"},
                        "faction": {"type": "string"},
                        "description": {"type": "string"},
                    }
                }
            },
            "loot_tables": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name"],
                }
            },
            "images": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["filename", "type"],
                    "properties": {
                        "id": {"type": "string"},
                        "filename": {"type": "string"},
                        "type": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                    }
                }
            },
            "locations": {
                "type": "array",
                "items": {"type": "object"}
            },
            "dungeon_delve": {
                "type": "object",
                "properties": {
                    "layout_name": {"type": "string"},
                    "aesthetic": {"type": "string"},
                    "total_rooms": {"type": "integer"},
                    "rooms": {"type": "array"}
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    # TypedDicts
    "MissionMetadata",
    "MissionContent",
    "LocationInfo",
    "CreatureStats",
    "Encounter",
    "NPC",
    "LootTable",
    "ImageAsset",
    "DungeonRoom",
    "DungeonDelveContent",
    "MissionModule",
    
    # Functions
    "validate_mission_module",
    "log_validation_results",
    "get_mission_schema",
]
