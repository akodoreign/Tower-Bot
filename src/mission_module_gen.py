"""
mission_module_gen.py — Compatibility wrapper for mission_builder package.

This file now delegates to the modular mission_builder package.
The original monolithic implementation has been refactored into:
  src/mission_builder/
    ├── __init__.py      — Orchestrator + main entry points
    ├── locations.py     — Gazetteer integration for real named places
    ├── leads.py         — Investigation leads system
    ├── encounters.py    — Combat design and stat blocks
    ├── npcs.py          — NPC generation and dialogue
    ├── rewards.py       — Loot tables and consequences
    └── docx_builder.py  — DOCX output generation

MAJOR CHANGES from the original:
1. ❌ NO MORE "Read Aloud" sections
2. ✅ Investigation Leads with WHY to go there
3. ✅ Real location names from city_gazetteer.json
4. ✅ Multiple approach options (social/stealth/direct)

Backup of the original file: backups/mission_module_gen_before_leads_20260327.py
"""

from __future__ import annotations

# Re-export everything from the new package for backward compatibility
from src.mission_builder import (
    generate_module,
    post_module_to_channel,
    gather_context,
    get_cr,
    get_max_pc_level,
    get_output_dir,
)

__all__ = [
    "generate_module",
    "post_module_to_channel",
    "gather_context",
    "get_cr",
    "get_max_pc_level",
    "get_output_dir",
]
