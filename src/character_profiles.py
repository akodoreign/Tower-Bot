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
            # Update existing record — only allow known columns in the SET clause
            _ALLOWED = {"profile_json", "name", "class_name", "updated_at", "profile_text", "appearance"}
            set_parts = []
            params = []
            for k, v in data.items():
                if k not in _ALLOWED:
                    logger.warning("character_profiles: ignoring unknown column %r in update", k)
                    continue
                set_parts.append(f"`{k}` = %s")
                params.append(v)
            if not set_parts:
                return True  # nothing valid to update
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
    """Returns the saved profile text for this Discord user, or None if none exists."""
    rows = raw_query(
        "SELECT profile_text, profile_json FROM player_characters WHERE player_discord_id=%s LIMIT 1",
        (str(user_id),)
    )
    if not rows:
        return None
    row = rows[0]
    # Real column first, fall back to blob for migration
    text = (row.get("profile_text") or "").strip()
    if not text:
        pj = row.get("profile_json") or {}
        if isinstance(pj, str):
            try: pj = json.loads(pj)
            except: pj = {}
        text = pj.get("profile_text", "").strip()
    return text or None


def save_character_profile(user_id: int, profile_text: str) -> None:
    """Saves/replaces the profile text for this Discord user."""
    text = profile_text.strip()
    existing = _get_player_by_discord_id(user_id)
    if existing:
        raw_execute(
            "UPDATE player_characters SET profile_text=%s WHERE player_discord_id=%s",
            (text, str(user_id))
        )
    else:
        db.insert("player_characters", {
            "player_discord_id": str(user_id),
            "name": f"Player_{user_id}",
            "profile_text": text,
        })


def has_character_profile(user_id: int) -> bool:
    return load_character_profile(user_id) is not None


# ---------------------------------------------------------------------------
# Appearance storage
# ---------------------------------------------------------------------------

def load_character_appearance(user_id: int) -> str | None:
    """Returns the appearance description text, or None if not set."""
    rows = raw_query(
        "SELECT appearance, name, profile_json FROM player_characters WHERE player_discord_id=%s LIMIT 1",
        (str(user_id),)
    )
    if not rows:
        return None
    row = rows[0]
    text = (row.get("appearance") or "").strip()
    if not text:
        pj = row.get("profile_json") or {}
        if isinstance(pj, str):
            try: pj = json.loads(pj)
            except: pj = {}
        text = pj.get("appearance", "").strip()
    return text or None


def load_character_name(user_id: int) -> str | None:
    """Returns the character name tied to this Discord user, or None if not set."""
    rows = raw_query(
        "SELECT name FROM player_characters WHERE player_discord_id=%s LIMIT 1",
        (str(user_id),)
    )
    if not rows:
        return None
    return (rows[0].get("name") or "").strip() or None


def save_character_appearance(
    user_id: int, appearance_text: str, character_name: str = ""
) -> None:
    """Save appearance text and optional character name for a Discord user."""
    text = appearance_text.strip()
    cname = character_name.strip()
    existing = _get_player_by_discord_id(user_id)
    if existing:
        if cname:
            raw_execute(
                "UPDATE player_characters SET appearance=%s, name=%s WHERE player_discord_id=%s",
                (text, cname, str(user_id))
            )
        else:
            raw_execute(
                "UPDATE player_characters SET appearance=%s WHERE player_discord_id=%s",
                (text, str(user_id))
            )
    else:
        db.insert("player_characters", {
            "player_discord_id": str(user_id),
            "name": cname or f"Player_{user_id}",
            "appearance": text,
        })


def load_all_appearances() -> dict[int, str]:
    """Returns {user_id: appearance_text} for all characters with saved appearances."""
    try:
        rows = raw_query(
            "SELECT player_discord_id, appearance, profile_json FROM player_characters "
            "WHERE appearance IS NOT NULL AND appearance != ''"
        )
        result = {}
        for row in rows:
            try:
                uid = int(row.get("player_discord_id", 0))
                if not uid:
                    continue
                text = (row.get("appearance") or "").strip()
                if not text:
                    pj = row.get("profile_json") or {}
                    if isinstance(pj, str):
                        try: pj = json.loads(pj)
                        except: pj = {}
                    text = pj.get("appearance", "").strip()
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
    """
    try:
        rows = raw_query(
            "SELECT player_discord_id, name, appearance FROM player_characters "
            "WHERE appearance IS NOT NULL AND appearance != ''"
        )
        result = {}
        for row in rows:
            try:
                uid = int(row.get("player_discord_id", 0))
                if not uid:
                    continue
                appearance = (row.get("appearance") or "").strip()
                if appearance:
                    result[uid] = {
                        "character_name": row.get("name", ""),
                        "appearance": appearance
                    }
            except Exception:
                pass
        return result
    except Exception as e:
        logger.error(f"Error loading character roster: {e}")
        return {}
