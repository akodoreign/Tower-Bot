"""
cr_scaling.py — Central party-level and challenge-rating helpers.

All mission builder pipelines import from here. Single source of truth
for dynamic CR calculation so every pipeline scales consistently.

Current CR rule: standard missions target party average level + 4.
Each numeric difficulty step below 5 subtracts 1 CR; each step above 5 adds 1 CR.

CR formula: max(1, min(30, avg_party_level + TIER_CR_OFFSET[tier]))

Tier offsets range from -8 (easy tutorial) to +10 (Tower-level epic),
giving a full ±10 window around the party's current level.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Tier → CR offset  (party_avg_level + offset = encounter CR target)
# ---------------------------------------------------------------------------

TIER_CR_OFFSET: Dict[str, int] = {
    "tutorial":      -4,
    "trivial":       -3,
    "easy":          -2,
    "local":         -1,
    "patrol":        -1,
    "standard":       0,
    "escort":         0,
    "investigation":  0,
    "courier":        0,
    "negotiation":    0,
    "seasoned":      +1,
    "rift":          +1,
    "dungeon":       +1,
    "dungeon-delve": +2,
    "major":         +2,
    "inter-guild":   +2,
    "elite":         +3,
    "high-stakes":   +3,
    "legend":        +4,
    "epic":          +4,
    "divine":        +5,
    "tower":         +6,
}

_DEFAULT_OFFSET = 0  # fallback for unknown tiers
_BASE_PARTY_CR_BONUS = 4


# ---------------------------------------------------------------------------
# Party strength — canonical, replaces all per-pipeline _party_strength()
# ---------------------------------------------------------------------------

def party_strength() -> Dict[str, Any]:
    """
    Return live party stats from the latest character snapshots DB view.

    All pipelines should import and call this instead of defining a local
    _party_strength(). Falls back to a level-5 party of 4 if DB is unavailable.
    """
    try:
        from src.db_api import raw_query as _rq
        rows = _rq(
            "SELECT char_name, snapshot_json "
            "FROM latest_character_snapshots "
            "ORDER BY fetched_at DESC"
        ) or []
    except Exception:
        rows = []

    pcs: List[Dict[str, Any]] = []
    for row in rows:
        snap = row.get("snapshot_json") or {}
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except Exception:
                continue
        lvl = (
            snap.get("total_level")
            or snap.get("level")
            or snap.get("classes_level")
        )
        if not lvl:
            classes = snap.get("classes")
            if isinstance(classes, dict):
                lvl = sum(int(v) for v in classes.values() if v)
            elif isinstance(classes, list):
                lvl = sum(c.get("level", 0) for c in classes if isinstance(c, dict))
            else:
                lvl = 0
        if lvl:
            pcs.append({
                "name":  row.get("char_name", "Unknown"),
                "level": int(lvl),
                "class": snap.get("class") or snap.get("primary_class") or "",
            })

    levels = [p["level"] for p in pcs] or [5]
    avg    = round(sum(levels) / len(levels), 1)
    return {
        "party_size": len(pcs) or 4,
        "avg_level":  avg,
        "max_level":  max(levels),
        "min_level":  min(levels),
        "pcs":        pcs,
    }


# ---------------------------------------------------------------------------
# Mission CR — the one function every pipeline calls
# ---------------------------------------------------------------------------

def mission_cr(mission: dict) -> int:
    """
    Return the target encounter CR for this mission.

    Baseline: party average level + 4. A numeric difficulty of 5 is standard;
    each point below 5 subtracts 1 CR, and each point above 5 adds 1 CR.
    Named tiers map to the same easier/harder offsets.

    Priority:
      1. Explicit mission["cr"] if set (DM override — always respected).
      2. avg_party_level + TIER_CR_OFFSET[tier], clamped 1–30.

    Examples at party avg level 5:
      tier="local"       → CR 3   (5 − 2)
      tier="standard"    → CR 5   (5 + 0)
      tier="rift"        → CR 8   (5 + 3)
      tier="major"       → CR 10  (5 + 5)
      tier="epic"        → CR 13  (5 + 8)
      tier="tower"       → CR 15  (5 + 10)
    """
    explicit = mission.get("cr")
    if explicit:
        try:
            return max(1, min(30, int(explicit)))
        except (ValueError, TypeError):
            pass

    strength = party_strength()
    avg      = int(strength["avg_level"])
    tier     = (mission.get("tier") or mission.get("difficulty_label") or "standard").lower().strip()
    offset   = TIER_CR_OFFSET.get(tier, _DEFAULT_OFFSET)
    numeric_difficulty = mission.get("difficulty") or mission.get("diff")
    try:
        if numeric_difficulty not in (None, ""):
            offset = int(numeric_difficulty) - 5
    except (TypeError, ValueError):
        pass

    return max(1, min(30, avg + _BASE_PARTY_CR_BONUS + offset))
