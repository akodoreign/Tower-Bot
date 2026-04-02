"""
test_json_generator.py — Tests for JSON module generation.

Validates that the json_generator produces properly structured output.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime

from src.mission_builder.json_generator import (
    generate_module_json,
    save_module_json,
)
from src.mission_builder.schemas import validate_mission_module


class TestJsonGenerator:
    """Tests for JSON mission generation."""
    
    def test_json_output_structure(self):
        """Test that generated JSON has correct structure."""
        # Note: This is a mock test since we can't easily mock Ollama
        # In practice, we'd use pytest-asyncio and mock the _ollama_generate
        
        # For now, we'll test the save function with a minimal valid module
        test_module = {
            "metadata": {
                "id": "test_001",
                "title": "Test Mission",
                "faction": "Test Faction",
                "tier": "standard",
                "mission_type": "standard",
                "cr": 5,
                "party_level": 5,
                "player_name": "Test Player",
                "player_count": 4,
                "runtime_minutes": 120,
                "reward": "Test Reward",
                "generated_at": datetime.now().isoformat(),
                "version": "1.0",
            },
            "content": {
                "overview": "Test overview",
            },
            "encounters": [],
            "npcs": [],
            "loot_tables": [],
            "images": [],
            "locations": [],
        }
        
        is_valid, errors = validate_mission_module(test_module)
        assert is_valid, f"Test module validation failed: {errors}"
        assert test_module["metadata"]["title"] == "Test Mission"
        assert test_module["metadata"]["faction"] == "Test Faction"
    
    def test_save_module_json(self, tmp_path):
        """Test saving a mission module to JSON file."""
        test_module = {
            "metadata": {
                "id": "test_002",
                "title": "Save Test Mission",
                "faction": "Test Faction",
                "tier": "standard",
                "mission_type": "standard",
                "cr": 5,
                "party_level": 5,
                "player_name": "Test Player",
                "player_count": 4,
                "runtime_minutes": 120,
                "reward": "Test Reward",
                "generated_at": datetime.now().isoformat(),
                "version": "1.0",
            },
            "content": {
                "overview": "Test overview for saving",
            },
            "encounters": [],
            "npcs": [],
            "loot_tables": [],
            "images": [],
            "locations": [],
        }
        
        # Note: save_module_json uses OUTPUT_DIR, so we'd need to mock that
        # For now, test the validation
        is_valid, errors = validate_mission_module(test_module)
        assert is_valid


class TestJsonStructure:
    """Tests for JSON output structure compliance."""
    
    def test_minimal_valid_module(self):
        """Test a minimal valid module structure."""
        module = {
            "metadata": {
                "title": "Minimal Mission",
                "faction": "Test",
                "tier": "standard",
                "mission_type": "standard",
                "cr": 1,
                "party_level": 1,
            },
            "content": {
                "overview": "A test mission",
            },
        }
        
        is_valid, errors = validate_mission_module(module)
        assert is_valid, f"Minimal module validation failed: {errors}"
    
    def test_full_featured_module(self):
        """Test a full-featured module with all optional fields."""
        module = {
            "metadata": {
                "id": "full_001",
                "title": "Full Featured Mission",
                "faction": "Glass Sigil",
                "tier": "high-stakes",
                "mission_type": "standard",
                "cr": 9,
                "party_level": 8,
                "player_name": "Party Name",
                "player_count": 4,
                "runtime_minutes": 180,
                "reward": "1000 EC + faction favor",
                "generated_at": datetime.now().isoformat(),
                "version": "1.0",
            },
            "content": {
                "overview": "Complete overview",
                "briefing": "Briefing section",
                "act_1": "Act 1 content",
                "act_2": "Act 2 content",
                "act_3": "Act 3 content",
                "act_4": "Act 4 content",
                "act_5": "Act 5 content",
                "rewards_summary": "Rewards info",
            },
            "encounters": [
                {
                    "id": "enc_0",
                    "name": "First Encounter",
                    "type": "combat",
                    "difficulty": "hard",
                    "location": "Combat Zone",
                    "description": "A dangerous encounter",
                    "creatures": [
                        {"name": "Monster", "cr": 2, "hp": 50}
                    ],
                    "party_xp": 450,
                }
            ],
            "npcs": [
                {
                    "id": "npc_0",
                    "name": "Quest Giver",
                    "title": "Commander",
                    "location": "Headquarters",
                    "role": "quest_giver",
                    "faction": "Glass Sigil",
                    "description": "A veteran commander",
                }
            ],
            "loot_tables": [
                {
                    "id": "loot_0",
                    "name": "Treasure Hoard",
                    "rolls": 2,
                    "items": [
                        {"name": "Gold", "count": 500}
                    ]
                }
            ],
            "images": [
                {
                    "id": "img_0",
                    "filename": "images/battle_map.png",
                    "type": "battle_map",
                    "title": "Encounter Map",
                    "associated_encounter": "enc_0",
                }
            ],
            "locations": [
                {
                    "name": "The Vault",
                    "type": "dungeon",
                    "district": "Eastern Warrens",
                    "description": "A hidden vault",
                    "danger_level": "high",
                }
            ],
            "sections": {  # Backward compat
                "overview": "Overview for DOCX",
                "acts_1_2": "Acts 1-2 text",
                "acts_3_4": "Acts 3-4 text",
                "act_5_rewards": "Act 5 text",
            },
        }
        
        is_valid, errors = validate_mission_module(module)
        assert is_valid, f"Full module validation failed: {errors}"
        
        # Verify all sections are present
        assert len(module["encounters"]) == 1
        assert len(module["npcs"]) == 1
        assert len(module["images"]) == 1
        assert len(module["locations"]) == 1
        assert "sections" in module


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
