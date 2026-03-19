# character_profiles.py
from pathlib import Path

CHAR_PROFILE_DIR = Path(__file__).resolve().parent / "character_memory"
CHAR_PROFILE_DIR.mkdir(exist_ok=True)


def _profile_path(user_id: int) -> Path:
    return CHAR_PROFILE_DIR / f"{user_id}.txt"


def load_character_profile(user_id: int) -> str | None:
    """
    Returns the saved profile text for this Discord user, or None if none exists.
    """
    p = _profile_path(user_id)
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="ignore").strip()
        return text or None
    except Exception:
        return None


def save_character_profile(user_id: int, profile_text: str) -> None:
    """
    Saves/replaces the profile text for this Discord user.
    """
    p = _profile_path(user_id)
    profile_text = profile_text.strip()
    p.write_text(profile_text, encoding="utf-8")

def has_character_profile(user_id: int) -> bool:
    return load_character_profile(user_id) is not None


# ---------------------------------------------------------------------------
# Appearance storage (separate file so profile text stays clean)
# ---------------------------------------------------------------------------

APPEARANCE_DIR = Path(__file__).resolve().parent / "character_appearance"
APPEARANCE_DIR.mkdir(exist_ok=True)


def _appearance_path(user_id: int) -> Path:
    return APPEARANCE_DIR / f"{user_id}.json"


def _appearance_path_legacy(user_id: int) -> Path:
    """Old plain-text path — checked for migration."""
    return APPEARANCE_DIR / f"{user_id}.txt"


def _load_appearance_data(user_id: int) -> dict:
    """
    Internal: returns the full appearance record as a dict.
    Migrates legacy plain-text files to JSON on first read.
    Returns {} if nothing exists.
    """
    import json
    json_path   = _appearance_path(user_id)
    legacy_path = _appearance_path_legacy(user_id)

    if json_path.exists():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    # Migrate legacy plain-text file
    if legacy_path.exists():
        try:
            text = legacy_path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                data = {"character_name": "", "appearance": text}
                json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                legacy_path.unlink(missing_ok=True)
                return data
        except Exception:
            pass

    return {}


def load_character_appearance(user_id: int) -> str | None:
    """Returns the appearance description text, or None if not set."""
    data = _load_appearance_data(user_id)
    text = data.get("appearance", "").strip()
    return text or None


def load_character_name(user_id: int) -> str | None:
    """Returns the character name tied to this Discord user, or None if not set."""
    data = _load_appearance_data(user_id)
    name = data.get("character_name", "").strip()
    return name or None


def save_character_appearance(
    user_id: int, appearance_text: str, character_name: str = ""
) -> None:
    """Save appearance text and optional character name for a Discord user."""
    import json
    # Load existing data so we don't clobber a name that was already set
    existing = _load_appearance_data(user_id)
    data = {
        "character_name": character_name.strip() or existing.get("character_name", ""),
        "appearance":     appearance_text.strip(),
    }
    _appearance_path(user_id).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_all_appearances() -> dict[int, str]:
    """Returns {user_id: appearance_text} for all characters with saved appearances."""
    result = {}
    for f in APPEARANCE_DIR.glob("*.json"):
        try:
            uid  = int(f.stem)
            data = _load_appearance_data(uid)
            text = data.get("appearance", "").strip()
            if text:
                result[uid] = text
        except Exception:
            pass
    # Also catch any un-migrated legacy .txt files
    for f in APPEARANCE_DIR.glob("*.txt"):
        try:
            uid = int(f.stem)
            if uid not in result:
                data = _load_appearance_data(uid)
                text = data.get("appearance", "").strip()
                if text:
                    result[uid] = text
        except Exception:
            pass
    return result


def get_character_roster() -> dict[int, dict]:
    """
    Returns {user_id: {"character_name": str, "appearance": str}}
    for all users who have an appearance saved.
    Useful for the bot to know which Discord user plays which character.
    """
    result = {}
    for f in APPEARANCE_DIR.glob("*.json"):
        try:
            uid  = int(f.stem)
            data = _load_appearance_data(uid)
            if data.get("appearance"):
                result[uid] = data
        except Exception:
            pass
    return result
