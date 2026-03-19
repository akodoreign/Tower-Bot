"""
faction_reputation.py — Faction favorability tracking for Tower of Last Chance.

Tiers (low to high):
  Detested → Hated → Disliked → Neutral → Friendly → Liked → Associated → Partner

Each faction starts at Neutral.
Points accumulate per event: +1 complete, -1 failed, -1 expired (unclaimed).
3 points = move one tier up or down. Points reset on tier change.

Detested/Hated factions generate hostile missions AGAINST players instead of contracts FOR them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

DOCS_DIR        = Path(__file__).resolve().parent.parent / "campaign_docs"
REP_FILE        = DOCS_DIR / "faction_reputation.json"

# ---------------------------------------------------------------------------
# Reputation tiers — ordered lowest to highest
# ---------------------------------------------------------------------------

TIERS = [
    "Detested",
    "Hated",
    "Disliked",
    "Neutral",
    "Friendly",
    "Liked",
    "Associated",
    "Partner",
]

TIER_INDEX = {t: i for i, t in enumerate(TIERS)}
DEFAULT_TIER  = "Neutral"
POINTS_TO_SHIFT = 3          # events needed to move one tier

# Tier display with emoji
TIER_EMOJI = {
    "Detested":   "💀",
    "Hated":      "😠",
    "Disliked":   "👎",
    "Neutral":    "😐",
    "Friendly":   "🤝",
    "Liked":      "👍",
    "Associated": "🔗",
    "Partner":    "⭐",
}

# Discord embed colors per tier — Red → Yellow → Green gradient
TIER_COLOR = {
    "Detested":   0xCC0000,  # dark red
    "Hated":      0xE63300,  # red
    "Disliked":   0xE67300,  # orange
    "Neutral":    0xE6C300,  # yellow
    "Friendly":   0x99CC00,  # yellow-green
    "Liked":      0x66CC00,  # light green
    "Associated": 0x33AA33,  # green
    "Partner":    0x009933,  # deep green
}


def get_faction_color(faction: str) -> int:
    """Return the Discord embed color (int) for a faction based on current reputation tier."""
    rep = get_reputation(faction)
    return TIER_COLOR.get(rep.get("tier", DEFAULT_TIER), TIER_COLOR[DEFAULT_TIER])


def get_faction_tier_label(faction: str) -> str:
    """Return 'emoji Tier' string for a faction, e.g. '🤝 Friendly'."""
    rep = get_reputation(faction)
    tier = rep.get("tier", DEFAULT_TIER)
    emoji = TIER_EMOJI.get(tier, "")
    return f"{emoji} {tier}"


# Known factions (for auto-initialisation)
KNOWN_FACTIONS = [
    "Iron Fang Consortium",
    "Argent Blades",
    "Wardens of Ash",
    "Serpent Choir",
    "Obsidian Lotus",
    "Glass Sigil",
    "Patchwork Saints",
    "Adventurers Guild",
    "Guild of Ashen Scrolls",
    "Tower Authority",
    "Wizards Tower",
]

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_rep() -> Dict[str, dict]:
    """Returns {faction_name: {tier, points}}"""
    if not REP_FILE.exists():
        return {}
    try:
        return json.loads(REP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_rep(data: Dict[str, dict]) -> None:
    try:
        REP_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _ensure_faction(data: Dict[str, dict], faction: str) -> None:
    """Initialise a faction entry if it doesn't exist yet."""
    if faction not in data:
        data[faction] = {"tier": DEFAULT_TIER, "points": 0}


def get_all_reputations() -> Dict[str, dict]:
    data = _load_rep()
    # Ensure all known factions are present
    for f in KNOWN_FACTIONS:
        _ensure_faction(data, f)
    return data


def get_reputation(faction: str) -> dict:
    data = _load_rep()
    _ensure_faction(data, faction)
    return data[faction]


# ---------------------------------------------------------------------------
# Core update logic
# ---------------------------------------------------------------------------

def _apply_event(faction: str, delta: int) -> dict:
    """
    Apply +1 (complete) or -1 (fail/expire) to a faction.
    Returns a result dict: {faction, old_tier, new_tier, points, shifted}.
    """
    data = _load_rep()
    _ensure_faction(data, faction)
    entry = data[faction]

    old_tier   = entry["tier"]
    old_index  = TIER_INDEX.get(old_tier, TIER_INDEX[DEFAULT_TIER])
    entry["points"] += delta

    shifted   = False
    new_tier  = old_tier
    new_index = old_index

    # Check for upward shift
    if entry["points"] >= POINTS_TO_SHIFT:
        new_index = min(old_index + 1, len(TIERS) - 1)
        new_tier  = TIERS[new_index]
        entry["points"] = 0
        shifted = True

    # Check for downward shift
    elif entry["points"] <= -POINTS_TO_SHIFT:
        new_index = max(old_index - 1, 0)
        new_tier  = TIERS[new_index]
        entry["points"] = 0
        shifted = True

    entry["tier"] = new_tier
    data[faction] = entry
    _save_rep(data)

    return {
        "faction":  faction,
        "old_tier": old_tier,
        "new_tier": new_tier,
        "points":   entry["points"],
        "shifted":  shifted,
    }


def on_mission_complete(faction: str) -> dict:
    return _apply_event(faction, +1)


def on_mission_failed(faction: str) -> dict:
    return _apply_event(faction, -1)


def on_mission_expired(faction: str) -> dict:
    # Expired = nobody claimed it. No reputation penalty — only failure earns that.
    return {"faction": faction, "old_tier": get_reputation(faction)["tier"],
            "new_tier": get_reputation(faction)["tier"], "points": get_reputation(faction)["points"],
            "shifted": False}


# ---------------------------------------------------------------------------
# Queries used by mission generator
# ---------------------------------------------------------------------------

def is_hostile(faction: str) -> bool:
    """Detested or Hated — faction generates threats, not contracts."""
    tier = get_reputation(faction)["tier"]
    return tier in ("Detested", "Hated")


def rep_flavour(faction: str) -> str:
    """Short flavour line injected into mission prompts based on standing."""
    entry = get_reputation(faction)
    tier  = entry["tier"]
    pts   = entry["points"]
    emoji = TIER_EMOJI.get(tier, "")
    return f"{emoji} {tier} ({pts:+d} toward next shift)"


def rep_summary_block() -> str:
    """All factions and their current standing — injected into mission prompts."""
    data = get_all_reputations()
    lines = ["FACTION REPUTATION STANDINGS:"]
    for faction, entry in sorted(data.items()):
        tier  = entry["tier"]
        pts   = entry["points"]
        emoji = TIER_EMOJI.get(tier, "")
        lines.append(f"  {faction}: {emoji} {tier} ({pts:+d})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Format reputation change for DM notification
# ---------------------------------------------------------------------------

def format_rep_change(result: dict) -> str:
    faction  = result["faction"]
    old_tier = result["old_tier"]
    new_tier = result["new_tier"]
    pts      = result["points"]
    shifted  = result["shifted"]
    emoji    = TIER_EMOJI.get(new_tier, "")

    if shifted:
        direction = "▲ improved" if TIER_INDEX[new_tier] > TIER_INDEX[old_tier] else "▼ dropped"
        return (
            f"📊 **{faction}** reputation {direction}: "
            f"**{old_tier} → {new_tier}** {emoji}"
        )
    else:
        return (
            f"📊 **{faction}**: {emoji} {new_tier} "
            f"({pts:+d} / {POINTS_TO_SHIFT} toward next shift)"
        )


# ---------------------------------------------------------------------------
# NPC party rank — delegates to party_profiles.py
# ---------------------------------------------------------------------------

def on_npc_party_complete(party: str, mission_tier: str = "standard") -> dict:
    """Record a completion for an NPC party. Delegates to party_profiles rank system."""
    from src.party_profiles import apply_party_outcome
    return apply_party_outcome(party, mission_tier, success=True)


def on_npc_party_fail(party: str, mission_tier: str = "standard") -> dict:
    """Record a failure for an NPC party. Delegates to party_profiles rank system."""
    from src.party_profiles import apply_party_outcome
    return apply_party_outcome(party, mission_tier, success=False)


def get_npc_party_rep(party: str) -> dict:
    """Get current rank info for a party."""
    from src.party_profiles import load_profile, _init_profile
    profile = load_profile(party) or _init_profile(party)
    return {
        "completed": profile.get("missions_completed", 0),
        "failed":    profile.get("missions_failed", 0),
        "tier":      profile.get("tier", "Unknown"),
        "points":    profile.get("points", 0),
    }


def format_npc_rep_for_display() -> str:
    """For a /partyranks command — delegates to party_profiles display helper."""
    from src.party_profiles import format_all_party_ranks
    return format_all_party_ranks()


# ---------------------------------------------------------------------------
# /factionrep slash command data helper
# ---------------------------------------------------------------------------

def format_full_rep_for_display() -> str:
    """Formatted string for the /factionrep command embed."""
    data = get_all_reputations()
    lines = []
    for faction, entry in sorted(data.items()):
        tier  = entry["tier"]
        pts   = entry["points"]
        emoji = TIER_EMOJI.get(tier, "")
        bar   = _points_bar(pts)
        lines.append(f"{emoji} **{faction}**\n  {tier} {bar}")
    return "\n".join(lines)


def _points_bar(pts: int) -> str:
    """Visual progress bar toward next tier shift."""
    filled = abs(pts)
    empty  = POINTS_TO_SHIFT - filled
    direction = "▲" if pts >= 0 else "▼"
    return f"`{'█' * filled}{'░' * empty}` {direction} ({pts:+d}/{POINTS_TO_SHIFT})"
