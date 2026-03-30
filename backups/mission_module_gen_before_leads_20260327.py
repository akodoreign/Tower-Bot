"""
mission_module_gen.py — Generates full D&D 5e 2024 mission modules as .docx files.

When a player claims a mission, this module:
1. Gathers campaign context (news memory, NPC roster, faction data)
2. Uses Ollama to generate a full 2-hour session module in sections
3. Calls a Node.js script (docx-js) to build the .docx file
4. Returns the file path for posting to Discord

CR scaling is DYNAMIC based on actual PC levels from character_memory.txt:
  CR = max_pc_level + tier_offset, clamped to [max_level+1, max_level+5]
  Tier offsets: local/patrol +1, escort/standard/investigation +2,
                rift/dungeon +3, major/inter-guild +4, high-stakes/epic/divine/tower +5
  Falls back to a fixed table if character_memory.txt is unreadable.

BACKUP created: 2026-03-27 before investigation leads refactor
"""

from __future__ import annotations

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "generated_modules"

# ---------------------------------------------------------------------------
# CR scaling — dynamic, based on actual PC levels
# ---------------------------------------------------------------------------

TIER_OFFSET: Dict[str, int] = {
    "local":         1,
    "patrol":        1,
    "escort":        2,
    "standard":      2,
    "investigation": 2,
    "rift":          3,
    "dungeon":       3,
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

CR_TO_LEVEL = {i: i for i in range(1, 21)}


def _get_max_pc_level() -> int:
    char_file = DOCS_DIR / "character_memory.txt"
    if not char_file.exists():
        return 0
    try:
        text = char_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0

    max_level = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.upper().startswith("CLASS:"):
            continue
        class_text = line.split(":", 1)[1].strip()
        level_matches = re.findall(r'(?:^|/)\s*\w+\s+(\d+)', class_text)
        if level_matches:
            total = sum(int(lv) for lv in level_matches)
            if total > max_level:
                max_level = total

    return max_level


ENCOUNTER_BUDGET = {
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


def _get_cr(tier: str) -> int:
    max_level = _get_max_pc_level()

    if max_level <= 0:
        cr = LEGACY_TIER_CR.get(tier.lower(), DEFAULT_CR)
        logger.info(f"📖 CR fallback (no PC levels found): tier={tier} → CR {cr}")
        return cr

    offset = TIER_OFFSET.get(tier.lower(), DEFAULT_OFFSET)
    cr = max_level + offset
    cr = max(cr, max_level + 1)
    cr = min(cr, max_level + 5)
    cr = max(1, min(cr, 30))

    logger.info(f"📖 Dynamic CR: max_pc_level={max_level}, tier={tier}, offset=+{offset} → CR {cr}")
    return cr
