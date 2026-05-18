"""
cr_scaling.py — Central party-level and challenge-rating helpers.

All mission builder pipelines import from here. Single source of truth
for dynamic CR calculation so every pipeline scales consistently.

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
    # Easy / learning
    "tutorial":       -8,
    "trivial":        -6,
    "easy":           -4,
    # Neighbourhood / low-stakes
    "local":          -2,
    "patrol":         -1,
    # Standard adventuring (baseline)
    "standard":        0,
    "escort":         +1,
    "investigation":  +1,
    "courier":        +1,
    "negotiation":    +1,
    # Elevated danger
    "rift":           +3,
    "dungeon":        +3,
    "dungeon-delve":  +4,
    "major":          +5,
    "inter-guild":    +5,
    # Deadly / legendary
    "high-stakes":    +7,
    "epic":           +8,
    "divine":         +9,
    "tower":         +10,
}

_DEFAULT_OFFSET = 0  # fallback for unknown tiers


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
    tier     = (mission.get("tier") or "standard").lower().strip()
    offset   = TIER_CR_OFFSET.get(tier, _DEFAULT_OFFSET)

    return max(1, min(30, avg + offset))
