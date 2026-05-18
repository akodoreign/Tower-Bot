"""
test_mission_schema.py — Tests for mission JSON schema and builder.

Validates:
- Schema structure and type hints
- Builder functionality
- Validation logic
- JSON serialization/deserialization
"""

import json
import pytest
from pathlib import Path
from datetime import datetime

from src.mission_builder.schemas import (
    validate_mission_module,
    get_mission_schema,
    MissionMetadata,
    MissionContent,
    Encounter,
    NPC,
)
from src.mission_builder.mission_json_builder import (
    MissionJsonBuilder,
    create_mission_module,
)


class TestMissionBuilder:
    """Tests for MissionJsonBuilder."""
    
    def test_basic_creation(self):
        """Test creating a basic mission."""
        builder = create_mission_module(
            title="Test Mission",
            faction="Test Faction",
            tier="standard",
            cr=5,
            party_level=5,
        )
        module = builder.build()
        
        assert module["metadata"]["title"] == "Test Mission"
        assert module["metadata"]["faction"] == "Test Faction"
        assert module["metadata"]["tier"] == "standard"
        assert module["metadata"]["mission_type"] == "standard"
    
    def test_add_content(self):
        """Test adding content sections."""
        builder = create_mission_module(
            title="Content Test",
            faction="Test Faction",
            tier="standard",
        )
        
        builder.add_overview("This is the overview") \
               .add_acts(
                   act_1="Act 1 content",
                   act_2="Act 2 content",
                   act_3="Act 3 content",
               )
        
        module = builder.build()
        assert module["content"]["overview"] == "This is the overview"
        assert module["content"]["act_1"] == "Act 1 content"
        assert module["content"]["act_2"] == "Act 2 content"
        assert module["content"]["act_3"] == "Act 3 content"
    
    def test_add_encounters(self):
        """Test adding encounters."""
        builder = create_mission_module(
            title="Combat Test",
            faction="Test Faction",
            tier="dungeon",
        )
        
        builder.add_encounter(
            name="Goblin Ambush",
            encounter_type="combat",
            difficulty="easy",
            location="Forest Road",
            creatures=[
                {"name": "Goblin", "cr": 0.25, "hp": 7, "count": 3}
            ],
            xp=150,
        )
        
        module = builder.build()
        assert len(module["encounters"]) == 1
        assert module["encounters"][0]["name"] == "Goblin Ambush"
        assert module["encounters"][0]["type"] == "combat"
        assert len(module["encounters"][0]["creatures"]) == 1
    
    def test_add_npcs(self):
        """Test adding NPCs."""
        builder = create_mission_module(
            title="NPC Test",
            faction="Test Faction",
            tier="standard",
        )
        
        builder.add_npc(
            name="Captain Kess",
            role="quest_giver",
            faction="Test Faction",
            title="Guard Captain",
            description="A stern woman with piercing eyes",
            location="Guard House",
        )
        
        module = builder.build()
        assert len(module["npcs"]) == 1
        assert module["npcs"][0]["name"] == "Captain Kess"
        assert module["npcs"][0]["role"] == "quest_giver"
    
    def test_add_images(self):
        """Test adding image assets."""
        builder = create_mission_module(
            title="Image Test",
            faction="Test Faction",
            tier="standard",
        )
        
        builder.add_image(
            filename="images/battle_map.png",
            image_type="battle_map",
            title="Encounter Map",
            description="Battle map for the goblin encounter",
        )
        
        module = builder.build()
        assert len(module["images"]) == 1
        assert module["images"][0]["filename"] == "images/battle_map.png"
        assert module["images"][0]["type"] == "battle_map"
    
    def test_method_chaining(self):
        """Test method chaining."""
        module = (create_mission_module(
                title="Chain Test",
                faction="Test Faction",
                tier="standard",
            )
            .add_overview("Overview text")
            .add_acts(act_1="Act 1", act_2="Act 2")
            .add_npc("NPC 1", role="ally")
            .add_encounter("Combat", "combat", difficulty="medium")
            .add_image("map.png", "battle_map")
            .build()
        )
        
        assert module["content"]["overview"] == "Overview text"
        assert len(module["npcs"]) == 1
        assert len(module["encounters"]) == 1
        assert len(module["images"]) == 1
    
    def test_set_reward(self):
        """Test setting reward."""
        builder = create_mission_module(
            title="Reward Test",
            faction="Test Faction",
            tier="standard",
        )
        builder.set_reward("1000 EC + faction favor")
        
        module = builder.build()
        assert module["metadata"]["reward"] == "1000 EC + faction favor"
    
    def test_set_runtime(self):
        """Test setting runtime."""
        builder = create_mission_module(
            title="Runtime Test",
            faction="Test Faction",
            tier="standard",
        )
        builder.set_runtime(120)
        
        module = builder.build()
        assert module["metadata"]["runtime_minutes"] == 120


class TestValidation:
    """Tests for schema validation."""
    
    def test_valid_mission(self):
        """Test validation of a valid mission."""
        builder = create_mission_module(
            title="Valid Mission",
            faction="Test Faction",
            tier="standard",
        )
        builder.add_overview("This is an overview")
        module = builder.build(validate=False)  # Skip validation during build
        
        is_valid, errors = validate_mission_module(module)
        assert is_valid, f"Expected valid mission, got errors: {errors}"
    
    def test_missing_title(self):
        """Test validation fails without title."""
        module = {
            "metadata": {
                "faction": "Test",
                "tier": "standard",
                "mission_type": "standard",
                "cr": 5,
                "party_level": 5,
            },
            "content": {"overview": "Test"},
        }
        
        is_valid, errors = validate_mission_module(module)
        assert not is_valid
        assert any("title" in e for e in errors)
    
    def test_missing_overview(self):
        """Test validation fails without overview."""
        module = {
            "metadata": {
                "title": "Test",
                "faction": "Test",
                "tier": "standard",
                "mission_type": "standard",
                "cr": 5,
                "party_level": 5,
            },
            "content": {},
        }
        
        is_valid, errors = validate_mission_module(module)
        assert not is_valid
    
    def test_missing_metadata(self):
        """Test validation fails without metadata."""
        module = {
            "content": {"overview": "Test"},
        }
        
        is_valid, errors = validate_mission_module(module)
        assert not is_valid
        assert any("metadata" in e for e in errors)
    
    def test_dungeon_delve_without_rooms(self):
        """Test dungeon-delve validation requires rooms."""
        module = {
            "metadata": {
                "title": "Dungeon",
                "faction": "Test",
                "tier": "dungeon",
                "mission_type": "dungeon-delve",
                "cr": 5,
                "party_level": 5,
            },
            "content": {"overview": "Test"},
            "dungeon_delve": {},  # Missing rooms
        }
        
        is_valid, errors = validate_mission_module(module)
        assert not is_valid


class TestSerialization:
    """Tests for JSON serialization/deserialization."""
    
    def test_serialize_to_json(self, tmp_path):
        """Test serializing module to JSON."""
        builder = create_mission_module(
            title="Serialize Test",
            faction="Test Faction",
            tier="standard",
        )
        builder.add_overview("Test overview")
        
        output_file = builder.save_json(tmp_path, filename="test_mission")
        
        assert output_file.exists()
        assert output_file.suffix == ".json"
        
        # Verify it's valid JSON
        data = json.loads(output_file.read_text())
        assert data["metadata"]["title"] == "Serialize Test"
    
    def test_deserialize_json(self, tmp_path):
        """Test deserializing JSON back to module."""
        # Create and save
        builder = create_mission_module(
            title="Deserialize Test",
            faction="Test Faction",
            tier="standard",
        )
        builder.add_overview("Test overview")
        output_file = builder.save_json(tmp_path, filename="test_deser")
        
        # Load back
        loaded_data = json.loads(output_file.read_text())
        
        # Validate
        is_valid, errors = validate_mission_module(loaded_data)
        assert is_valid, f"Validation failed: {errors}"
        assert loaded_data["metadata"]["title"] == "Deserialize Test"
    
    def test_complex_module_serialization(self, tmp_path):
        """Test serializing a complex module with all features."""
        builder = create_mission_module(
            title="Complex Mission",
            faction="Glass Sigil",
            tier="high-stakes",
            cr=9,
            party_level=8,
        )
        
        builder.add_overview("This is a complex mission") \
               .add_acts(
                   act_1="Act 1",
                   act_2="Act 2",
                   act_3="Act 3",
               ) \
               .add_npc("NPC 1", role="quest_giver", faction="Glass Sigil") \
               .add_npc("NPC 2", role="ally", faction="Glass Sigil") \
               .add_encounter("Combat 1", "combat", difficulty="hard") \
               .add_encounter("Combat 2", "combat", difficulty="medium") \
               .add_image("map1.png", "battle_map") \
               .add_image("map2.png", "battle_map") \
               .add_location("The Vault", "dungeon") \
               .add_loot_table("Treasure", [{"name": "Gold", "count": 500}])
        
        output_file = builder.save_json(tmp_path, filename="complex")
        assert output_file.exists()
        
        loaded = json.loads(output_file.read_text())
        assert len(loaded["npcs"]) == 2
        assert len(loaded["encounters"]) == 2
        assert len(loaded["images"]) == 2
        assert len(loaded["locations"]) == 1
        assert len(loaded["loot_tables"]) == 1


class TestDungeonDelve:
    """Tests for dungeon-delve specific features."""
    
    def test_dungeon_delve_creation(self):
        """Test creating a dungeon delve mission."""
        builder = create_mission_module(
            title="Caverns of Doom",
            faction="Independent",
            tier="dungeon",
            mission_type="dungeon-delve",
        )
        
        rooms = [
            {
                "id": "room_01",
                "number": 1,
                "name": "Entrance",
                "type": "entrance",
                "description": "You enter a dark chamber",
                "features": ["rubble", "bones"],
                "exits": {"east": "room_02"},
            },
            {
                "id": "room_02",
                "number": 2,
                "name": "Boss",
                "type": "boss",
                "description": "The final boss awaits",
                "features": ["throne"],
                "exits": {"west": "room_01"},
            },
        ]
        
        builder.set_dungeon_delve_content(
            layout_name="5-room Dungeon",
            aesthetic="gothic",
            total_rooms=2,
            entrance_room_id="room_01",
            boss_room_id="room_02",
            rooms=rooms,
        )
        
        module = builder.build()
        assert module["metadata"]["mission_type"] == "dungeon-delve"
        assert module["dungeon_delve"]["total_rooms"] == 2
        assert len(module["dungeon_delve"]["rooms"]) == 2
    
    def test_dungeon_room_with_encounter(self):
        """Test dungeon room with encounter."""
        builder = create_mission_module(
            title="Dungeon with Combat",
            faction="Independent",
            tier="dungeon",
            mission_type="dungeon-delve",
        )
        
        encounter = {
            "id": "enc_boss",
            "name": "Dragon",
            "type": "combat",
            "creatures": [{"name": "Red Dragon", "cr": 17, "hp": 256}]
        }
        
        rooms = [
            {
                "id": "room_01",
                "number": 1,
                "name": "Dragon Lair",
                "type": "boss",
                "description": "A massive dragon rests here",
                "features": ["treasure pile"],
                "encounter": encounter,
            }
        ]
        
        builder.set_dungeon_delve_content(
            layout_name="Dragon's Lair",
            aesthetic="dragon",
            total_rooms=1,
            entrance_room_id="room_01",
            boss_room_id="room_01",
            rooms=rooms,
        )
        
        module = builder.build()
        room = module["dungeon_delve"]["rooms"][0]
        assert "encounter" in room
        assert room["encounter"]["name"] == "Dragon"


class TestBackwardCompat:
    """Tests for backward compatibility with DOCX format."""
    
    def test_docx_sections(self):
        """Test adding DOCX-compatible sections."""
        builder = create_mission_module(
            title="DOCX Compat Test",
            faction="Test",
            tier="standard",
        )
        
        builder.add_docx_sections(
            overview="Overview text",
            acts_1_2="Acts 1-2 text",
            acts_3_4="Acts 3-4 text",
            act_5_rewards="Act 5 text",
        )
        
        module = builder.build()
        assert "sections" in module
        assert module["sections"]["overview"] == "Overview text"
        assert module["sections"]["acts_1_2"] == "Acts 1-2 text"


class TestSchema:
    """Tests for schema reference."""
    
    def test_get_schema(self):
        """Test retrieving JSON schema."""
        schema = get_mission_schema()
        
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "properties" in schema
        assert "metadata" in schema["properties"]
        assert "content" in schema["properties"]
    
    def test_schema_structure(self):
        """Test schema has expected structure."""
        schema = get_mission_schema()
        
        # Check metadata properties
        meta_props = schema["properties"]["metadata"]["properties"]
        assert "title" in meta_props
        assert "faction" in meta_props
        assert "tier" in meta_props
        assert "cr" in meta_props
        
        # Check content properties
        content_props = schema["properties"]["content"]["properties"]
        assert "overview" in content_props
        assert "act_1" in content_props


# ─────────────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────────────

class TestIntegration:
    """Integration tests combining multiple features."""
    
    def test_full_mission_workflow(self, tmp_path):
        """Test complete mission creation workflow."""
        # Create mission
        builder = create_mission_module(
            title="The Silent Vault",
            faction="Glass Sigil",
            tier="high-stakes",
            cr=9,
            party_level=8,
        )
        
        # Add content
        builder.add_overview("Glass Sigil seeks brave adventurers...") \
               .add_acts(
                   act_1="The Meeting",
                   act_2="Investigation",
                   act_3="Infiltration",
                   act_4="Confrontation",
                   act_5="Resolution",
               ) \
               .set_reward("2000 EC + faction favor") \
               .set_runtime(180)
        
        # Add NPCs
        builder.add_npcs([
            {
                "name": "Grandmaster Vex",
                "role": "quest_giver",
                "faction": "Glass Sigil",
                "title": "Leader",
            },
            {
                "name": "Captain Kess",
                "role": "ally",
                "faction": "Glass Sigil",
                "title": "Guard Captain",
            },
        ])
        
        # Add encounters
        builder.add_encounters([
            {
                "name": "Vault Guardians",
                "type": "combat",
                "difficulty": "hard",
                "creatures": [
                    {"name": "Iron Golem", "cr": 7, "hp": 165, "count": 1}
                ],
                "party_xp": 1800,
            }
        ])
        
        # Add images
        builder.add_images([
            {
                "filename": "images/vault_chamber.png",
                "type": "battle_map",
                "title": "Grand Vault Chamber",
            }
        ])
        
        # Build and validate
        module = builder.build(validate=True)
        
        # Save
        output_file = builder.save_json(tmp_path)
        assert output_file.exists()
        
        # Verify all parts
        assert module["metadata"]["title"] == "The Silent Vault"
        assert len(module["content"]) == 6  # all acts + overview
        assert len(module["npcs"]) == 2
        assert len(module["encounters"]) == 1
        assert len(module["images"]) == 1
        
        # Validate saved JSON
        loaded = json.loads(output_file.read_text())
        is_valid, errors = validate_mission_module(loaded)
        assert is_valid, f"Loaded mission validation failed: {errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
