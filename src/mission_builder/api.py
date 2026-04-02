"""
api.py — High-level API for mission generation.

Provides convenient functions for mission generation, wrapping the lower-level
json_generator and handling common use cases.

Exported:
    generate_mission() — High-level mission generation
    generate_mission_async() — Async version
    generate_and_save_mission() — Generate and save in one step
    get_mission_output_path() — Get path to generated mission
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Dict, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────
# Synchronous API (wrapper)
# ─────────────────────────────────────────────────────────────────────────

def generate_mission(
    title: str,
    faction: str,
    tier: str,
    body: str,
    player_name: str = "Unclaimed",
    reward: str = "",
    mission_type: str = "",
    personal_for: str = "",
    difficulty: Optional[str] = None,
    difficulty_rating: Optional[int] = None,
) -> Optional[Dict]:
    """
    Generate a mission module synchronously.
    
    This is a wrapper around the async generator for simple use cases.
    For advanced usage, use generate_mission_async() directly.
    
    Args:
        title: Mission title
        faction: Associated faction
        tier: Mission tier (local, patrol, standard, dungeon, etc.)
        body: Mission description
        player_name: Name of claiming player/party
        reward: Reward description
        mission_type: Mission type (escort, recovery, investigation, battle, etc.)
        personal_for: Character name if personal mission
        difficulty: DEPRECATED - use difficulty_rating instead
        difficulty_rating: Difficulty 1-10 (easy to epic). Default: 5 (Challenging)
    
    Returns:
        Dict with mission module data, or None on failure
    
    Example:
        >>> module = generate_mission(
        ...     title="The Silent Vault",
        ...     faction="Glass Sigil",
        ...     tier="high-stakes",
        ...     body="Glass Sigil needs trustworthy adventurers...",
        ...     mission_type="theft",
        ...     player_name="Party of Shadows",
        ...     reward="1000 EC + faction favor",
        ...     difficulty_rating=7,
        ... )
        >>> module["metadata"]["title"]
        'Theft: The Silent Vault'
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        return loop.run_until_complete(
            generate_mission_async(
                title=title,
                faction=faction,
                tier=tier,
                body=body,
                player_name=player_name,
                reward=reward,
                mission_type=mission_type,
                personal_for=personal_for,
                difficulty=difficulty,
                difficulty_rating=difficulty_rating,
            )
        )
    except Exception as e:
        logger.error(f"❌ Mission generation failed: {e}")
        return None


async def generate_mission_async(
    title: str,
    faction: str,
    tier: str,
    body: str,
    player_name: str = "Unclaimed",
    reward: str = "",
    mission_type: str = "",
    personal_for: str = "",
    difficulty: Optional[str] = None,
    difficulty_rating: Optional[int] = None,
) -> Optional[Dict]:
    """
    Generate a mission module asynchronously.
    
    Args:
        title: Mission title
        faction: Associated faction
        tier: Mission tier
        body: Mission description
        player_name: Name of claiming player/party
        reward: Reward description
        mission_type: Mission type (escort, recovery, investigation, etc.)
        personal_for: Character name if personal mission
        difficulty: DEPRECATED - use difficulty_rating
        difficulty_rating: Difficulty 1-10 scale (easy to epic)
    
    Returns:
        Dict with mission module data, or None on failure
    """
    from .json_generator import generate_module_json
    
    # Build mission dict
    mission = {
        "title": title,
        "faction": faction,
        "tier": tier,
        "body": body,
        "reward": reward,
        "personal_for": personal_for,
        "type": mission_type or tier,
        "mission_type": mission_type,
    }
    
    # Add difficulty rating if provided
    if difficulty_rating is not None:
        mission["difficulty_rating"] = max(1, min(10, difficulty_rating))  # Clamp to 1-10
    else:
        mission["difficulty_rating"] = 5  # Default: Challenging
    
    logger.info(f"🎲 Generating mission: {title}")
    if mission_type:
        logger.info(f"   Type: {mission_type} | Difficulty: {mission['difficulty_rating']}/10")
    
    try:
        module = await generate_module_json(mission, player_name=player_name)
        if module:
            logger.info(f"✅ Mission generated: {title}")
        else:
            logger.error(f"❌ Module generation returned None")
        return module
    except Exception as e:
        logger.error(f"❌ Mission generation error: {e}", exc_info=True)
        return None


async def generate_and_save_mission(
    title: str,
    faction: str,
    tier: str,
    body: str,
    player_name: str = "Unclaimed",
    reward: str = "",
    mission_type: str = "",
    output_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Generate a mission module and save it to disk.
    
    Args:
        title: Mission title
        faction: Associated faction
        tier: Mission tier
        body: Mission description
        player_name: Name of claiming player/party
        reward: Reward description
        mission_type: Override mission type
        output_dir: Optional custom output directory
    
    Returns:
        Path to mission directory, or None on failure
    
    Example:
        >>> mission_dir = await generate_and_save_mission(
        ...     title="The Silent Vault",
        ...     faction="Glass Sigil",
        ...     tier="high-stakes",
        ...     body="...",
        ...     player_name="Party of Shadows",
        ... )
        >>> print(mission_dir / "module_data.json")
        generated_modules/Silent_Vault_20260402_143000/module_data.json
    """
    from .json_generator import save_module_json
    
    # Generate module
    module = await generate_mission_async(
        title=title,
        faction=faction,
        tier=tier,
        body=body,
        player_name=player_name,
        reward=reward,
        mission_type=mission_type,
    )
    
    if not module:
        return None
    
    # Save to disk
    try:
        mission_dir = save_module_json(module, mission_id=None)
        if mission_dir:
            logger.info(f"💾 Mission saved: {mission_dir}")
        return mission_dir
    except Exception as e:
        logger.error(f"❌ Failed to save mission: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────────────────

def get_mission_output_path(
    mission_title: str,
    timestamp: Optional[str] = None,
) -> Path:
    """
    Get the path where a mission will be saved.
    
    Args:
        mission_title: Title of the mission
        timestamp: Optional timestamp (uses current if None)
    
    Returns:
        Path to mission directory
    
    Example:
        >>> path = get_mission_output_path("The Silent Vault")
        >>> path
        PosixPath('generated_modules/The_Silent_Vault_20260402_143000')
    """
    from pathlib import Path
    
    OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "generated_modules"
    
    if not timestamp:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    safe_title = "".join(c for c in mission_title if c.isalnum() or c in " -_").strip()
    safe_title = safe_title.replace(" ", "_")[:50]
    
    mission_id = f"{safe_title}_{timestamp}"
    return OUTPUT_DIR / mission_id


def get_recent_missions(
    count: int = 5,
    output_dir: Optional[Path] = None,
) -> list[Path]:
    """
    Get recently generated missions.
    
    Args:
        count: Number of recent missions to return
        output_dir: Optional custom output directory
    
    Returns:
        List of paths to recent mission directories (newest first)
    """
    from pathlib import Path
    
    if not output_dir:
        output_dir = Path(__file__).resolve().parent.parent.parent / "generated_modules"
    
    if not output_dir.exists():
        return []
    
    # Get all mission directories sorted by modification time
    missions = sorted(
        output_dir.iterdir(),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    
    return missions[:count]


def list_missions(
    output_dir: Optional[Path] = None,
) -> list[Dict]:
    """
    List all generated missions with metadata.
    
    Args:
        output_dir: Optional custom output directory
    
    Returns:
        List of dicts with mission info
    
    Example:
        >>> missions = list_missions()
        >>> for m in missions:
        ...     print(f"{m['title']} ({m['generated_at']})")
    """
    import json
    from pathlib import Path
    
    if not output_dir:
        output_dir = Path(__file__).resolve().parent.parent.parent / "generated_modules"
    
    if not output_dir.exists():
        return []
    
    missions = []
    for mission_dir in sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if mission_dir.is_dir():
            json_file = mission_dir / "module_data.json"
            if json_file.exists():
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    missions.append({
                        "id": mission_dir.name,
                        "title": data.get("metadata", {}).get("title", "Unknown"),
                        "faction": data.get("metadata", {}).get("faction", "Unknown"),
                        "tier": data.get("metadata", {}).get("tier", "Unknown"),
                        "generated_at": data.get("metadata", {}).get("generated_at", ""),
                        "path": mission_dir,
                    })
                except Exception:
                    pass
    
    return missions


# ─────────────────────────────────────────────────────────────────────────
# Mission Board Integration
# ─────────────────────────────────────────────────────────────────────────

async def generate_mission_for_board(
    mission: Dict,
    player_name: str,
) -> Optional[Path]:
    """
    Generate a mission module when claimed from the mission board.
    
    This function is designed to be called from mission_board.py to replace
    the old docx generation.
    
    Args:
        mission: Mission dict from mission board
        player_name: Name of player claiming the mission
    
    Returns:
        Path to mission output directory, or None on failure
    
    Example:
        >>> mission = {
        ...     "title": "The Silent Vault",
        ...     "faction": "Glass Sigil",
        ...     "tier": "high-stakes",
        ...     "body": "...",
        ... }
        >>> path = await generate_mission_for_board(mission, "Party Name")
        >>> (path / "module_data.json").exists()
        True
    """
    mission_dir = await generate_and_save_mission(
        title=mission.get("title", "Unknown"),
        faction=mission.get("faction", "Unknown"),
        tier=mission.get("tier", "standard"),
        body=mission.get("body", ""),
        player_name=player_name,
        reward=mission.get("reward", ""),
        mission_type=mission.get("type", ""),
    )
    
    return mission_dir


async def generate_dungeon_delve_mission(
    location_name: Optional[str] = None,
    faction: str = "Independent",
    party_level: Optional[int] = None,
    player_name: str = "Unclaimed",
    reward: str = "500 EC + 100 Kharma",
) -> Optional[Path]:
    """
    Generate a dungeon delve mission (if dungeon_delve module is available).
    
    Args:
        location_name: Optional specific location
        faction: Sponsoring faction
        party_level: Target party level (auto-detected if None)
        player_name: Claiming player/party
        reward: Reward string
    
    Returns:
        Path to mission output directory, or None if dungeon_delve not available
    """
    try:
        from .dungeon_delve import generate_dungeon_delve, save_dungeon_delve
        
        logger.info(f"🏰 Generating dungeon delve mission...")
        
        result = await generate_dungeon_delve(
            location_name=location_name,
            faction=faction,
            party_level=party_level,
            player_name=player_name,
            reward=reward,
        )
        
        # Save to disk
        mission_dir = save_dungeon_delve(result)
        
        if mission_dir:
            logger.info(f"🏰 Dungeon delve saved: {mission_dir}")
        
        return mission_dir
    except ImportError:
        logger.warning("⚠️ Dungeon delve module not available")
        return None
    except Exception as e:
        logger.error(f"❌ Dungeon delve generation failed: {e}", exc_info=True)
        return None


# ─────────────────────────────────────────────────────────────────────────
# Exports
# ─────────────────────────────────────────────────────────────────────────

__all__ = [
    # High-level generation
    "generate_mission",
    "generate_mission_async",
    "generate_and_save_mission",
    
    # Utility
    "get_mission_output_path",
    "get_recent_missions",
    "list_missions",
    
    # Integration
    "generate_mission_for_board",
    "generate_dungeon_delve_mission",
]
