"""
character_profiles.py — Player Character Profile Storage

Stores character profile text and appearance data for Discord users.
Data persists to MySQL player_characters table.
"""

import json
import logging
from typing import Optional

from src.db_api import raw_query, raw_execute, db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: get/save player character by Discord ID
# ---------------------------------------------------------------------------

def _get_player_by_discord_id(user_id: int) -> Optional[dict]:
    """Get player character record by Discord user ID."""
    try:
        rows = raw_query(
            "SELECT * FROM player_characters WHERE player_discord_id = %s LIMIT 1",
            (str(user_id),)
        )
        if rows:
            row = rows[0]
            # Parse profile_json if present
            if row.get("profile_json"):
                if isinstance(row["profile_json"], str):
                    row["profile_json"] = json.loads(row["profile_json"])
            else:
                row["profile_json"] = {}
            return row
        return None
    except Exception as e:
        logger.error(f"Error loading player by discord_id {user_id}: {e}")
        return None


def _save_player_record(user_id: int, data: dict) -> bool:
    """Insert or update player character record by Discord ID."""
    try:
        discord_id = str(user_id)
        existing = _get_player_by_discord_id(user_id)
        
        # Ensure profile_json is serialized
        if "profile_json" in data and isinstance(data["profile_json"], dict):
            data["profile_json"] = json.dumps(data["profile_json"])
        
        if existing:
            # Update existing record
            set_parts = []
            params = []
            for k, v in data.items():
                set_parts.append(f"{k} = %s")
                params.append(v)
            params.append(discord_id)
            raw_execute(
                f"UPDATE player_characters SET {', '.join(set_parts)} WHERE player_discord_id = %s",
                tuple(params)
            )
        else:
            # Insert new record
            data["player_discord_id"] = discord_id
            if "name" not in data:
                data["name"] = f"Player_{user_id}"  # Placeholder name
            db.insert("player_characters", data)
        return True
    except Exception as e:
        logger.error(f"Error saving player record for {user_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Profile text (backstory, notes, etc.)
# ---------------------------------------------------------------------------


def load_character_profile(user_id: int) -> str | None:
    """
    Returns the saved profile text for this Discord user, or None if none exists.
    """
    record = _get_player_by_discord_id(user_id)
    if not record:
        return None
    profile_data = record.get("profile_json", {})
    text = profile_data.get("profile_text", "").strip()
    return text or None


def save_character_profile(user_id: int, profile_text: str) -> None:
    """
    Saves/replaces the profile text for this Discord user.
    """
    record = _get_player_by_discord_id(user_id)
    profile_data = record.get("profile_json", {}) if record else {}
    profile_data["profile_text"] = profile_text.strip()
    _save_player_record(user_id, {"profile_json": profile_data})


def has_character_profile(user_id: int) -> bool:
    return load_character_profile(user_id) is not None


# ---------------------------------------------------------------------------
# Appearance storage (in profile_json)
# ---------------------------------------------------------------------------

def _get_appearance_data(user_id: int) -> dict:
    """
    Internal: returns appearance data from profile_json.
    Returns {} if nothing exists.
    """
    record = _get_player_by_discord_id(user_id)
    if not record:
        return {}
    profile_data = record.get("profile_json", {})
    return {
        "character_name": record.get("name", "") or profile_data.get("character_name", ""),
        "appearance": profile_data.get("appearance", "")
    }


def load_character_appearance(user_id: int) -> str | None:
    """Returns the appearance description text, or None if not set."""
    data = _get_appearance_data(user_id)
    text = data.get("appearance", "").strip()
    return text or None


def load_character_name(user_id: int) -> str | None:
    """Returns the character name tied to this Discord user, or None if not set."""
    data = _get_appearance_data(user_id)
    name = data.get("character_name", "").strip()
    return name or None


def save_character_appearance(
    user_id: int, appearance_text: str, character_name: str = ""
) -> None:
    """Save appearance text and optional character name for a Discord user."""
    record = _get_player_by_discord_id(user_id)
    profile_data = record.get("profile_json", {}) if record else {}
    
    # Update appearance in profile_json
    profile_data["appearance"] = appearance_text.strip()
    if character_name.strip():
        profile_data["character_name"] = character_name.strip()
    
    # Build update data
    update_data = {"profile_json": profile_data}
    
    # Also update the name column if provided
    if character_name.strip():
        update_data["name"] = character_name.strip()
    
    _save_player_record(user_id, update_data)


def load_all_appearances() -> dict[int, str]:
    """Returns {user_id: appearance_text} for all characters with saved appearances."""
    try:
        rows = raw_query("SELECT player_discord_id, profile_json FROM player_characters")
        result = {}
        for row in rows:
            try:
                uid = int(row.get("player_discord_id", 0))
                if not uid:
                    continue
                profile_data = row.get("profile_json", {})
                if isinstance(profile_data, str):
                    profile_data = json.loads(profile_data)
                text = profile_data.get("appearance", "").strip()
                if text:
                    result[uid] = text
            except Exception:
                pass
        return result
    except Exception as e:
        logger.error(f"Error loading all appearances: {e}")
        return {}


def get_character_roster() -> dict[int, dict]:
    """
    Returns {user_id: {"character_name": str, "appearance": str}}
    for all users who have an appearance saved.
    Useful for the bot to know which Discord user plays which character.
    """
    try:
        rows = raw_query("SELECT player_discord_id, name, profile_json FROM player_characters")
        result = {}
        for row in rows:
            try:
                uid = int(row.get("player_discord_id", 0))
                if not uid:
                    continue
                profile_data = row.get("profile_json", {})
                if isinstance(profile_data, str):
                    profile_data = json.loads(profile_data)
                appearance = profile_data.get("appearance", "").strip()
                if appearance:
                    result[uid] = {
                        "character_name": row.get("name", "") or profile_data.get("character_name", ""),
                        "appearance": appearance
                    }
            except Exception:
                pass
        return result
    except Exception as e:
        logger.error(f"Error loading character roster: {e}")
        return {}
