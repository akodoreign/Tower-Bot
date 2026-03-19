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
    print(f"[Tower] Saved profile for {user_id} to {p}")  # TEMP DEBUG

def has_character_profile(user_id: int) -> bool:
    return load_character_profile(user_id) is not None
