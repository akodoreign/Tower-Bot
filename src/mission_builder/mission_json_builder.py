"""
mission_json_builder.py — Build standardized mission JSON output.

Converts generated mission content into MissionModule schema format.
Handles both standard missions and dungeon delves.

Exported:
    MissionJsonBuilder — Main builder class
    create_mission_module() — Convenience function
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import uuid4

from .schemas import (
    MissionModule, MissionMetadata, MissionContent,
    Encounter, NPC, LootTable, LocationInfo, ImageAsset,
    DungeonDelveContent, DungeonRoom,
    validate_mission_module, log_validation_results
)

logger = logging.getLogger(__name__)


class MissionJsonBuilder:
    """Builder for constructing MissionModule objects."""
    
    def __init__(
        self,
        title: str,
        faction: str,
        tier: str,
        mission_type: str = "standard",
        cr: int = 5,
        party_level: int = 5,
        player_name: str = "Unclaimed",
        player_count: int = 4,
    ):
        """Initialize builder with metadata."""
        self.module: MissionModule = {
            "metadata": {
                "id": str(uuid4()),
                "title": title,
                "faction": faction,
                "tier": tier,
                "mission_type": mission_type,
                "cr": cr,
                "party_level": party_level,
                "player_name": player_name,
                "player_count": player_count,
                "runtime_minutes": self._estimate_runtime(mission_type, cr),
                "reward": "Standard",
                "generated_at": datetime.now().isoformat(),
                "version": "1.0",
            },
            "content": {},
            "encounters": [],
            "npcs": [],
            "loot_tables": [],
            "images": [],
            "locations": [],
        }
    
    def _estimate_runtime(self, mission_type: str, cr: int) -> int:
        """Estimate mission runtime in minutes."""
        base_times = {
            "standard": 120,
            "dungeon-delve": 150,
            "investigation": 90,
            "combat": 60,
            "social": 45,
            "heist": 120,
        }
        base = base_times.get(mission_type, 120)
        # Adjust by CR
        return base + (cr - 5) * 10
    
    def set_metadata(self, **kwargs) -> MissionJsonBuilder:
        """Update metadata fields."""
        self.module["metadata"].update(kwargs)
        return self
    
    def set_reward(self, reward: str) -> MissionJsonBuilder:
        """Set mission reward."""
        self.module["metadata"]["reward"] = reward
        return self
    
    def set_runtime(self, minutes: int) -> MissionJsonBuilder:
        """Set expected runtime."""
        self.module["metadata"]["runtime_minutes"] = minutes
        return self
    
    # ─────────────────────────────────────────────────────────────────────
    # Content
    # ─────────────────────────────────────────────────────────────────────
    
    def add_overview(self, overview: str) -> MissionJsonBuilder:
        """Add overview section."""
        if "content" not in self.module:
            self.module["content"] = {}
        self.module["content"]["overview"] = overview
        return self
    
    def add_briefing(self, briefing: str) -> MissionJsonBuilder:
        """Add briefing section."""
        if "content" not in self.module:
            self.module["content"] = {}
        self.module["content"]["briefing"] = briefing
        return self
    
    def add_acts(
        self,
        act_1: Optional[str] = None,
        act_2: Optional[str] = None,
        act_3: Optional[str] = None,
        act_4: Optional[str] = None,
        act_5: Optional[str] = None,
    ) -> MissionJsonBuilder:
        """Add act sections."""
        if "content" not in self.module:
            self.module["content"] = {}
        if act_1:
            self.module["content"]["act_1"] = act_1
        if act_2:
            self.module["content"]["act_2"] = act_2
        if act_3:
            self.module["content"]["act_3"] = act_3
        if act_4:
            self.module["content"]["act_4"] = act_4
        if act_5:
            self.module["content"]["act_5"] = act_5
        return self
    
    def add_rewards_summary(self, rewards: str) -> MissionJsonBuilder:
        """Add rewards summary."""
        if "content" not in self.module:
            self.module["content"] = {}
        self.module["content"]["rewards_summary"] = rewards
        return self
    
    # ─────────────────────────────────────────────────────────────────────
    # Encounters
    # ─────────────────────────────────────────────────────────────────────
    
    def add_encounter(
        self,
        name: str,
        encounter_type: str,
        description: str = "",
        difficulty: str = "medium",
        location: str = "",
        creatures: Optional[List[Dict]] = None,
        xp: int = 0,
        **kwargs
    ) -> MissionJsonBuilder:
        """Add a combat or social encounter."""
        encounter: Encounter = {
            "id": f"enc_{len(self.module['encounters'])}",
            "name": name,
            "type": encounter_type,
            "description": description,
            "difficulty": difficulty,
            "location": location,
            "creatures": creatures or [],
            "party_xp": xp,
        }
        encounter.update(kwargs)
        self.module["encounters"].append(encounter)
        return self
    
    def add_encounters(self, encounters: List[Dict]) -> MissionJsonBuilder:
        """Add multiple encounters."""
        for i, enc in enumerate(encounters):
            enc_data: Encounter = {
                "id": enc.get("id", f"enc_{len(self.module['encounters']) + i}"),
                "name": enc.get("name", "Unknown Encounter"),
                "type": enc.get("type", "combat"),
                "description": enc.get("description", ""),
                "difficulty": enc.get("difficulty", "medium"),
                "location": enc.get("location", ""),
                "creatures": enc.get("creatures", []),
                "party_xp": enc.get("party_xp", 0),
            }
            self.module["encounters"].append(enc_data)
        return self
    
    # ─────────────────────────────────────────────────────────────────────
    # NPCs
    # ─────────────────────────────────────────────────────────────────────
    
    def add_npc(
        self,
        name: str,
        role: str = "neutral",
        faction: str = "",
        title: str = "",
        description: str = "",
        location: str = "",
        **kwargs
    ) -> MissionJsonBuilder:
        """Add an NPC."""
        npc: NPC = {
            "id": f"npc_{len(self.module['npcs'])}",
            "name": name,
            "role": role,
            "faction": faction,
            "title": title,
            "description": description,
            "location": location,
        }
        npc.update(kwargs)
        self.module["npcs"].append(npc)
        return self
    
    def add_npcs(self, npcs: List[Dict]) -> MissionJsonBuilder:
        """Add multiple NPCs."""
        for i, npc_data in enumerate(npcs):
            npc: NPC = {
                "id": npc_data.get("id", f"npc_{len(self.module['npcs']) + i}"),
                "name": npc_data.get("name", "Unknown NPC"),
                "role": npc_data.get("role", "neutral"),
                "faction": npc_data.get("faction", ""),
                "title": npc_data.get("title", ""),
                "description": npc_data.get("description", ""),
                "location": npc_data.get("location", ""),
            }
            self.module["npcs"].append(npc)
        return self
    
    # ─────────────────────────────────────────────────────────────────────
    # Locations
    # ─────────────────────────────────────────────────────────────────────
    
    def add_location(
        self,
        name: str,
        location_type: str = "unknown",
        district: str = "",
        description: str = "",
        danger_level: str = "moderate",
        **kwargs
    ) -> MissionJsonBuilder:
        """Add a location."""
        location: LocationInfo = {
            "name": name,
            "type": location_type,
            "district": district,
            "description": description,
            "danger_level": danger_level,
        }
        location.update(kwargs)
        if "locations" not in self.module:
            self.module["locations"] = []
        self.module["locations"].append(location)
        return self
    
    # ─────────────────────────────────────────────────────────────────────
    # Loot Tables
    # ─────────────────────────────────────────────────────────────────────
    
    def add_loot_table(
        self,
        name: str,
        items: List[Dict],
        description: str = "",
        rolls: int = 1,
    ) -> MissionJsonBuilder:
        """Add a loot table."""
        table: LootTable = {
            "id": f"loot_{len(self.module['loot_tables'])}",
            "name": name,
            "description": description,
            "rolls": rolls,
            "items": items,
        }
        self.module["loot_tables"].append(table)
        return self
    
    # ─────────────────────────────────────────────────────────────────────
    # Images
    # ─────────────────────────────────────────────────────────────────────
    
    def add_image(
        self,
        filename: str,
        image_type: str,
        title: str = "",
        description: str = "",
        associated_encounter: Optional[str] = None,
    ) -> MissionJsonBuilder:
        """Add an image asset reference."""
        image: ImageAsset = {
            "id": f"img_{len(self.module['images'])}",
            "filename": filename,
            "type": image_type,
            "title": title,
            "description": description,
        }
        if associated_encounter:
            image["associated_encounter"] = associated_encounter
        self.module["images"].append(image)
        return self
    
    def add_images(self, images: List[Dict]) -> MissionJsonBuilder:
        """Add multiple image references."""
        for img in images:
            self.add_image(
                filename=img.get("filename", ""),
                image_type=img.get("type", ""),
                title=img.get("title", ""),
                description=img.get("description", ""),
                associated_encounter=img.get("associated_encounter"),
            )
        return self
    
    # ─────────────────────────────────────────────────────────────────────
    # Dungeon Delve Specific
    # ─────────────────────────────────────────────────────────────────────
    
    def set_dungeon_delve_content(
        self,
        layout_name: str,
        aesthetic: str,
        total_rooms: int,
        entrance_room_id: str,
        boss_room_id: str,
        rooms: List[DungeonRoom],
        composite_map: Optional[ImageAsset] = None,
    ) -> MissionJsonBuilder:
        """Set dungeon delve specific content."""
        self.module["dungeon_delve"] = {
            "layout_name": layout_name,
            "aesthetic": aesthetic,
            "total_rooms": total_rooms,
            "entrance_room_id": entrance_room_id,
            "boss_room_id": boss_room_id,
            "rooms": rooms,
        }
        if composite_map:
            self.module["dungeon_delve"]["composite_map"] = composite_map
        
        # Update mission type if not already set
        if self.module["metadata"].get("mission_type") != "dungeon-delve":
            self.module["metadata"]["mission_type"] = "dungeon-delve"
        
        return self
    
    # ─────────────────────────────────────────────────────────────────────
    # Backward Compatibility (DOCX)
    # ─────────────────────────────────────────────────────────────────────
    
    def add_docx_sections(
        self,
        overview: Optional[str] = None,
        acts_1_2: Optional[str] = None,
        acts_3_4: Optional[str] = None,
        act_5_rewards: Optional[str] = None,
    ) -> MissionJsonBuilder:
        """
        Add DOCX-compatible sections for backward compatibility.
        These are separate from the structured content.
        """
        if "sections" not in self.module:
            self.module["sections"] = {}
        
        if overview:
            self.module["sections"]["overview"] = overview
        if acts_1_2:
            self.module["sections"]["acts_1_2"] = acts_1_2
        if acts_3_4:
            self.module["sections"]["acts_3_4"] = acts_3_4
        if act_5_rewards:
            self.module["sections"]["act_5_rewards"] = act_5_rewards
        
        return self
    
    # ─────────────────────────────────────────────────────────────────────
    # Build & Validate
    # ─────────────────────────────────────────────────────────────────────
    
    def build(self, validate: bool = True) -> MissionModule:
        """Build and optionally validate the module."""
        if validate:
            is_valid, errors = validate_mission_module(self.module)
            log_validation_results(
                is_valid,
                errors,
                self.module["metadata"].get("title", "Unknown")
            )
            if not is_valid:
                logger.warning("⚠️ Module validation failed but continuing")
        
        return self.module
    
    def save_json(
        self,
        output_dir: Path,
        filename: Optional[str] = None,
        validate: bool = True,
    ) -> Path:
        """
        Save the module as JSON.
        
        Args:
            output_dir: Directory to save to
            filename: Optional filename (without .json extension)
            validate: Whether to validate before saving
        
        Returns:
            Path to saved file
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        module = self.build(validate=validate)
        
        if not filename:
            title = module["metadata"].get("title", "mission")
            safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
            safe_title = safe_title.replace(" ", "_")[:50]
            filename = safe_title
        
        filename = filename.rstrip(".json")
        filepath = output_dir / f"{filename}.json"
        
        try:
            filepath.write_text(json.dumps(module, indent=2), encoding="utf-8")
            logger.info(f"✅ Mission JSON saved: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"❌ Failed to save mission JSON: {e}")
            raise


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

def create_mission_module(
    title: str,
    faction: str,
    tier: str,
    mission_type: str = "standard",
    **metadata_kwargs
) -> MissionJsonBuilder:
    """
    Convenience function to create a new mission builder.
    
    Usage:
        builder = create_mission_module(
            title="The Silent Vault",
            faction="Glass Sigil",
            tier="high-stakes",
            cr=9,
            party_level=8,
        )
        builder.add_overview("...").add_acts(act_1="...").add_npcs([...])
        module = builder.build()
    """
    return MissionJsonBuilder(
        title=title,
        faction=faction,
        tier=tier,
        mission_type=mission_type,
        **metadata_kwargs
    )


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "MissionJsonBuilder",
    "create_mission_module",
]
