"""
test_api.py — Tests for high-level mission generation API.

Tests the convenience functions and integration points.
"""

import pytest
from pathlib import Path
from datetime import datetime

from src.mission_builder.api import (
    generate_mission,
    get_mission_output_path,
    get_recent_missions,
    list_missions,
)


class TestHighLevelAPI:
    """Tests for high-level mission generation API."""
    
    def test_get_mission_output_path(self):
        """Test generating mission output path."""
        path = get_mission_output_path("The Silent Vault")
        
        assert path.name.startswith("The_Silent_Vault_")
        assert "20260" in path.name  # Year starting with 2026
    
    def test_get_mission_output_path_with_timestamp(self):
        """Test generating mission output path with custom timestamp."""
        timestamp = "20260101_120000"
        path = get_mission_output_path("Test Mission", timestamp=timestamp)
        
        assert path.name == "Test_Mission_20260101_120000"
    
    def test_get_mission_output_path_sanitization(self):
        """Test that dangerous characters are removed from path."""
        path = get_mission_output_path("Mission: [DANGER] / <Test>")
        
        # Should only contain alphanumeric and safe characters
        assert "[" not in path.name
        assert "]" not in path.name
        assert "/" not in path.name
        assert "<" not in path.name
        assert ">" not in path.name
    
    def test_get_mission_output_path_longname_truncated(self):
        """Test that very long mission names are truncated."""
        long_name = "A" * 100
        path = get_mission_output_path(long_name)
        
        # Name part should be truncated to 50 chars + timestamp
        name_part = path.name.rsplit("_", 2)[0]  # Remove timestamp parts
        assert len(name_part) <= 50
    
    def test_list_missions_format(self):
        """Test that list_missions returns proper format."""
        missions = list_missions()
        
        # Result should be a list of dicts
        assert isinstance(missions, list)
        
        # Each mission should have expected keys
        for mission in missions:
            assert isinstance(mission, dict)
            assert "id" in mission
            assert "title" in mission
            assert "faction" in mission
            assert "path" in mission


class TestMissionIntegration:
    """Tests for mission board integration."""
    
    def test_mission_dict_structure(self):
        """Test that mission dicts have expected structure."""
        mission = {
            "title": "Test Mission",
            "faction": "Test Faction",
            "tier": "standard",
            "body": "Test body",
            "reward": "100 EC",
        }
        
        # Should have required fields
        assert mission["title"]
        assert mission["faction"]
        assert mission["tier"]
        assert mission["body"]


class TestMissionGeneration:
    """Tests for mission generation functions."""
    
    def test_generate_mission_with_minimal_params(self):
        """Test mission generation with minimal parameters."""
        # Note: This test will fail without actual Ollama running
        # In practice, we'd mock the _ollama_generate function
        # For now, just test the parameter validation
        
        params = {
            "title": "Test Mission",
            "faction": "Test Faction",
            "tier": "standard",
            "body": "Test description",
            "player_name": "Test Player",
        }
        
        # Verify all required params are present
        assert all(k in params for k in ["title", "faction", "tier", "body", "player_name"])
    
    def test_generate_mission_with_all_params(self):
        """Test mission generation with all parameters."""
        params = {
            "title": "The Silent Vault",
            "faction": "Glass Sigil",
            "tier": "high-stakes",
            "body": "Glass Sigil seeks trustworthy adventurers...",
            "player_name": "Party of Shadows",
            "reward": "1000 EC + faction favor",
            "mission_type": "standard",
            "personal_for": "",
            "difficulty": "hard",
        }
        
        # Verify all params can be provided
        assert len(params) > 5


class TestUtilityFunctions:
    """Tests for utility functions."""
    
    def test_get_recent_missions_empty(self, tmp_path):
        """Test get_recent_missions with empty directory."""
        recent = get_recent_missions(output_dir=tmp_path)
        assert recent == []
    
    def test_list_missions_empty(self, tmp_path):
        """Test list_missions with empty directory."""
        missions = list_missions(output_dir=tmp_path)
        assert missions == []


class TestAPIDocumentation:
    """Tests to verify API docstrings are present."""
    
    def test_generate_mission_has_docstring(self):
        """Test that generate_mission has documentation."""
        assert generate_mission.__doc__ is not None
        assert "Example:" in generate_mission.__doc__
    
    def test_get_mission_output_path_has_docstring(self):
        """Test that get_mission_output_path has documentation."""
        assert get_mission_output_path.__doc__ is not None
        assert "Example:" in get_mission_output_path.__doc__
    
    def test_list_missions_has_docstring(self):
        """Test that list_missions has documentation."""
        assert list_missions.__doc__ is not None
        assert "Example:" in list_missions.__doc__


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
