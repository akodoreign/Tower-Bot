from pathlib import Path

NUDGE_STATE_DIR = Path(__file__).resolve().parent / "nudge_state"
NUDGE_STATE_DIR.mkdir(exist_ok=True)


def _path(user_id: int) -> Path:
    return NUDGE_STATE_DIR / f"{user_id}.flag"


def has_been_nudged(user_id: int) -> bool:
    return _path(user_id).exists()


def mark_nudged(user_id: int):
    _path(user_id).write_text("1", encoding="utf-8")
