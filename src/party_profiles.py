"""
party_profiles.py — Persistent adventurer party profiles for Tower of Last Chance.

Each NPC party that takes a mission gets a full profile generated on first use:
  - Named members (2-4) with roles, species, and personality notes
  - Affiliation (faction or No Affiliation)
  - Specialty / what they're known for
  - Visual identity hook
  - Reputation note (what the city says about them)

Rank ladder (slowest in the game — takes sustained performance to shift):
  Unknown → Recognized → Established → Respected → Notable → Renowned → Legendary

Data persists to MySQL party_profiles table.
"""

from __future__ import annotations

import os
import json
import random
import asyncio
import re
from datetime import datetime
from typing import Optional, List

from src.log import logger
from src.db_api import raw_query, raw_execute, db

# ---------------------------------------------------------------------------
# Rank ladder
# ---------------------------------------------------------------------------

PARTY_TIERS = [
    "Unknown",
    "Recognized",
    "Established",
    "Respected",
    "Notable",
    "Renowned",
    "Legendary",
]

PARTY_TIER_INDEX  = {t: i for i, t in enumerate(PARTY_TIERS)}
PARTY_DEFAULT_TIER = "Unknown"
PARTY_POINTS_TO_SHIFT = 5   # slow — requires sustained performance

PARTY_TIER_EMOJI = {
    "Unknown":     "❓",
    "Recognized":  "🔰",
    "Established": "🛡️",
    "Respected":   "⚔️",
    "Notable":     "🌟",
    "Renowned":    "🔥",
    "Legendary":   "👑",
}

# Points awarded per mission tier (success positive, failure negative)
MISSION_TIER_DELTA = {
    "local":         1,
    "patrol":        1,
    "escort":        1,
    "standard":      1,
    "investigation": 1,
    "major":         2,
    "inter-guild":   2,
    "dungeon":       2,
    "high-stakes":   2,
    "rift":          3,
    "epic":          3,
    "divine":        3,
    "tower":         3,
}

# ---------------------------------------------------------------------------
# Lore reference (same world as mission_board)
# ---------------------------------------------------------------------------

_LORE = """\
SETTING: The Undercity — a sealed city under a Dome around the Tower of Last Chance.
Rifts tear reality constantly. Adventurers are a recognised economic class: ranked, taxed, watched.
FACTIONS: Iron Fang Consortium, Argent Blades, Wardens of Ash, Serpent Choir, Obsidian Lotus,
Glass Sigil, Patchwork Saints, Adventurers Guild, Guild of Ashen Scrolls, Tower Authority.
DISTRICTS: Markets Infinite, Sanctum Quarter, Grand Forum, Guild Spires, The Warrens, Outer Wall.
TONE: Dark urban fantasy. Gritty, specific, noir. These are working professionals, not heroes.\
"""

AFFILIATIONS = [
    "No Affiliation",
    "No Affiliation",          # weighted — most parties are independent
    "No Affiliation",
    "Adventurers Guild",       # registered but unaligned
    "Adventurers Guild",
    "Iron Fang Consortium",
    "Argent Blades",
    "Wardens of Ash",
    "Serpent Choir",
    "Obsidian Lotus",
    "Glass Sigil",
    "Patchwork Saints",
    "Guild of Ashen Scrolls",
    "Tower Authority",
]

SPECIES_LIST = [
    "Human", "Half-Elf", "Dwarf", "Tiefling", "Halfling",
    "Gnome", "Orc", "Half-Orc", "Dragonborn", "Elf",
    "Tabaxi", "Warforged", "Goblin", "Aasimar",
]

# ---------------------------------------------------------------------------
# Slug helper (for backward compatibility / identification)
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Convert party name to a safe identifier slug."""
    return re.sub(r"[^\w\-]", "_", name.lower().strip())


# ---------------------------------------------------------------------------
# Persistence — MySQL via db_api
# ---------------------------------------------------------------------------

def _parse_json_col(raw) -> dict:
    """Safely parse a DB JSON column — handles str, dict, list, None."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {}  # old list-only format — treat as empty, regenerate
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def load_profile(name: str) -> Optional[dict]:
    """Load party profile from database."""
    try:
        rows = raw_query(
            "SELECT * FROM party_profiles WHERE party_name = %s LIMIT 1",
            (name,)
        )
        if not rows:
            return None
        row = rows[0]
        # Prefer profile_json (full profile), fall back to members_json
        profile_data = _parse_json_col(row.get("profile_json")) or _parse_json_col(row.get("members_json"))
        profile_data["name"] = row.get("party_name", name)
        if row.get("formed_at"):
            profile_data.setdefault(
                "created_at",
                row["formed_at"].isoformat() if hasattr(row["formed_at"], "isoformat") else str(row["formed_at"])
            )
        return profile_data
    except Exception as e:
        logger.error(f"party_profiles load error for {name}: {e}")
        return None


def save_profile(profile: dict) -> None:
    """Save party profile to database (writes both columns for compatibility)."""
    name = profile.get("name", "unknown")
    try:
        blob = json.dumps(profile, ensure_ascii=False, default=str)
        existing = raw_query(
            "SELECT id FROM party_profiles WHERE party_name = %s LIMIT 1",
            (name,)
        )
        if existing:
            raw_execute(
                "UPDATE party_profiles SET members_json = %s, profile_json = %s, reputation = %s WHERE party_name = %s",
                (blob, blob, profile.get("points", 0), name)
            )
        else:
            db.insert("party_profiles", {
                "party_name":  name,
                "members_json": blob,
                "profile_json": blob,
                "reputation":  profile.get("points", 0),
                "status":      "active",
            })
    except Exception as e:
        logger.error(f"party_profiles save error for {name}: {e}")


def _init_profile(name: str) -> dict:
    """Return a blank profile with all required keys."""
    return {
        "name":               name,
        "affiliation":        "No Affiliation",
        "sponsor":            None,
        "specialty":          "General contracts",
        "aligned_objective":  "",
        "faction_loves":      [],
        "faction_hates":      [],
        "members":            [],
        "visual":             "",
        "reputation_note":    "",
        "history":            [f"[{datetime.now().strftime('%Y-%m-%d')}] Party first logged."],
        "missions_completed": 0,
        "missions_failed":    0,
        "tier":               PARTY_DEFAULT_TIER,
        "points":             0,
        "generated":          False,
    }


# ---------------------------------------------------------------------------
# Ollama generation
# ---------------------------------------------------------------------------

async def _generate(prompt: str) -> Optional[str]:
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
    try:
        from src.ollama_queue import call_ollama, OllamaBusyError
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=120.0,
            caller="party_profiles",
        )
        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()
        import re
        lines = text.splitlines()
        skip = ("sure", "here's", "here is", "as requested", "certainly",
                "of course", "i hope", "below is", "absolutely")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        return "\n".join(lines).strip() or None
    except Exception as e:
        logger.error(f"party_profiles _generate error: {e}")
        return None


async def generate_profile(name: str, force: bool = False) -> dict:
    """
    Generate a full party profile for the given name.
    Parties have 4-8 members with balanced roles, aligned objectives,
    a sponsor, and explicit faction love/hate relationships.
    """
    existing = load_profile(name)
    if existing and existing.get("generated") and not force:
        return existing

    # Always start from a complete defaults dict, then layer existing data on top.
    # This prevents KeyError when old profiles are missing keys.
    profile = _init_profile(name)
    if existing:
        profile.update(existing)

    affiliation   = profile.get("affiliation") if (existing and existing.get("generated")) else random.choice(AFFILIATIONS)
    member_count  = random.randint(4, 8)
    other_factions = [f for f in [
        "Iron Fang Consortium", "Argent Blades", "Wardens of Ash", "Serpent Choir",
        "Obsidian Lotus", "Glass Sigil", "Patchwork Saints", "Adventurers Guild",
        "Guild of Ashen Scrolls", "Tower Authority",
    ] if f != affiliation]

    prompt = f"""{_LORE}

Generate a full adventurer party profile for "{name}" operating in the Undercity.
Working professionals — gritty, specific, not heroes.

Affiliation: {affiliation}
Member count: exactly {member_count}

Output ONLY a valid JSON object — no markdown, no code fences:

{{
  "aligned_objective": "1 sentence — the specific shared goal, debt, or circumstance that formed this party and keeps them together",
  "specialty": "1 sentence — the type of contracts they take and what makes them technically distinct",
  "sponsor": "A faction name OR a specific patron NPC name that backs them, or null if truly independent",
  "faction_loves": ["up to 2 faction names from the factions list that trust or regularly hire this party"],
  "faction_hates": ["up to 2 faction names from the factions list that are hostile to or avoid this party"],
  "members": [
    {{
      "name": "Full name",
      "role": "Leader | Tracker | Arcanist | Muscle | Face | Medic | Thief | Scout | Support",
      "species": "Human | Half-Elf | Dwarf | Tiefling | Halfling | Gnome | Orc | Half-Orc | Dragonborn | Elf | Tabaxi | Warforged | Goblin | Aasimar",
      "note": "1 sentence — something specific: a scar, a habit, a personal history, or a tension with another member"
    }}
  ],
  "visual": "2 sentences — how they look as a group: clothing, gear, identifying marks, how they carry themselves",
  "reputation_note": "1-2 sentences — what people in the Undercity say about this party"
}}

RULES:
- Exactly {member_count} members. No more, no less.
- Roles must be balanced — include at least one support/healer and one ranged/caster type.
- No more than 2 members may share the same role.
- faction_loves and faction_hates must not include the party's own affiliation and must not overlap each other.
- sponsor can be null, a faction name, or an invented NPC patron name.
- aligned_objective must explain WHY these specific people formed THIS party."""

    text = await _generate(prompt)

    if text:
        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        try:
            data = json.loads(text)
        except Exception:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            data = {}
            if match:
                try:
                    data = json.loads(match.group())
                except Exception:
                    pass

        if data:
            profile["affiliation"]       = affiliation
            profile["aligned_objective"] = data.get("aligned_objective", "")
            profile["specialty"]         = data.get("specialty", profile["specialty"])
            profile["sponsor"]           = data.get("sponsor")
            profile["faction_loves"]     = data.get("faction_loves", [])
            profile["faction_hates"]     = data.get("faction_hates", [])
            profile["members"]           = data.get("members", [])
            profile["visual"]            = data.get("visual", "")
            profile["reputation_note"]   = data.get("reputation_note", "")
            profile["generated"]         = True
            logger.info(
                f"🎖️ Party profile generated: {name} ({affiliation}, {len(profile['members'])} members)"
            )
        else:
            logger.warning(f"🎖️ Party profile generation failed for {name} — saving stub")
    else:
        logger.warning(f"🎖️ Party profile: Ollama returned nothing for {name}")

    save_profile(profile)
    return profile


async def ensure_profile(name: str) -> dict:
    """Load profile if it exists, generate if not. Non-blocking stub returned immediately if needed."""
    existing = load_profile(name)
    if existing and existing.get("generated"):
        return existing
    return await generate_profile(name)


# ---------------------------------------------------------------------------
# Gear run — generate profiles for all known parties
# ---------------------------------------------------------------------------

async def generate_all_party_profiles(force: bool = False) -> dict:
    """
    Iterate over all party names from used_parties.json + existing DB profiles.
    Generate profiles for any that don't have one (or all if force=True).
    Returns {total, done, skipped, failed}.
    """
    from src.mission_board import _load_party_list, _load_used_parties

    # Collect all known party names from:
    # 1. adventurer_parties table (master list)
    # 2. used_parties (global_state table)
    # 3. existing profiles in party_profiles table
    all_names = set(_load_party_list())
    all_names.update(_load_used_parties())

    # Get party names from database
    try:
        db_rows = raw_query("SELECT party_name FROM party_profiles")
        for row in db_rows:
            if row.get("party_name"):
                all_names.add(row["party_name"])
    except Exception:
        pass

    total   = len(all_names)
    done    = 0
    skipped = 0
    failed  = 0

    for name in sorted(all_names):
        existing = load_profile(name)
        if existing and existing.get("generated") and not force:
            skipped += 1
            continue
        try:
            profile = await generate_profile(name, force=force)
            if profile.get("generated"):
                done += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"🎖️ Gear run failed for party {name}: {e}")
            failed += 1
        await asyncio.sleep(1)

    logger.info(f"🎖️ Party gear run complete: {done} generated, {skipped} skipped, {failed} failed / {total} total")
    return {"total": total, "done": done, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# Rank system
# ---------------------------------------------------------------------------

def get_party_delta(mission_tier: str) -> int:
    """Return point delta magnitude for a given mission tier."""
    return MISSION_TIER_DELTA.get(mission_tier.lower().strip(), 1)


def apply_party_outcome(name: str, mission_tier: str, success: bool) -> dict:
    """
    Apply a mission outcome to a party's rank.
    Returns result dict: {name, old_tier, new_tier, points, shifted, delta}.
    """
    profile = load_profile(name)
    if not profile:
        profile = _init_profile(name)

    old_tier  = profile.get("tier", PARTY_DEFAULT_TIER)
    old_index = PARTY_TIER_INDEX.get(old_tier, 0)
    delta     = get_party_delta(mission_tier)
    if not success:
        delta = -delta

    profile["points"] = profile.get("points", 0) + delta
    if success:
        profile["missions_completed"] = profile.get("missions_completed", 0) + 1
    else:
        profile["missions_failed"] = profile.get("missions_failed", 0) + 1

    shifted  = False
    new_tier = old_tier

    if profile["points"] >= PARTY_POINTS_TO_SHIFT:
        new_index = min(old_index + 1, len(PARTY_TIERS) - 1)
        new_tier  = PARTY_TIERS[new_index]
        profile["points"] = 0
        shifted = True
    elif profile["points"] <= -PARTY_POINTS_TO_SHIFT:
        new_index = max(old_index - 1, 0)
        new_tier  = PARTY_TIERS[new_index]
        profile["points"] = 0
        shifted = True

    profile["tier"] = new_tier
    today = datetime.now().strftime("%Y-%m-%d")
    verb  = "completed" if success else "failed"
    profile.setdefault("history", []).append(
        f"[{today}] {verb.capitalize()} a {mission_tier}-tier contract. "
        f"Rank: {old_tier}{' → ' + new_tier if shifted else ''} ({profile['points']:+d}/{PARTY_POINTS_TO_SHIFT})"
    )
    # Keep history trimmed to last 20 entries
    profile["history"] = profile["history"][-20:]
    save_profile(profile)

    return {
        "name":      name,
        "old_tier":  old_tier,
        "new_tier":  new_tier,
        "points":    profile["points"],
        "shifted":   shifted,
        "delta":     delta,
    }


def is_exceptional_outcome(mission_tier: str, success: bool, party_tier: str) -> bool:
    """
    Returns True if this outcome is worth a special narrative callout.
    Exceptional = high-tier mission + success by low-ranked party, OR
                  any failure on epic/divine/tower (catastrophic).
    """
    tier_delta = get_party_delta(mission_tier)
    if tier_delta >= 3:
        return True   # rift/epic/divine/tower always exceptional either way
    # Also exceptional if a low-ranked party punches above their weight
    party_idx   = PARTY_TIER_INDEX.get(party_tier, 0)
    mission_map = {"major": 2, "inter-guild": 2, "dungeon": 2, "high-stakes": 2}
    if tier_delta >= 2 and party_idx <= 2 and success:
        return True
    return False


# ---------------------------------------------------------------------------
# Profile summary for prompt injection
# ---------------------------------------------------------------------------

def profile_summary(name: str) -> str:
    """Short string injected into mission prompts to ground the party in reality."""
    profile = load_profile(name)
    if not profile or not profile.get("generated"):
        return f"Party: {name} (no profile on file)"

    affil     = profile.get("affiliation", "No Affiliation")
    sponsor   = profile.get("sponsor")
    spec      = profile.get("specialty", "")
    objective = profile.get("aligned_objective", "")
    visual    = profile.get("visual", "")
    rep       = profile.get("reputation_note", "")
    tier      = profile.get("tier", "Unknown")
    emoji     = PARTY_TIER_EMOJI.get(tier, "")
    loves     = profile.get("faction_loves", [])
    hates     = profile.get("faction_hates", [])
    members   = profile.get("members", [])
    member_lines = " | ".join(
        f"{m['name']} ({m.get('role','?')})" for m in members
    ) if members else "unknown roster"

    lines = [
        f"PARTY: {name}",
        f"Rank: {emoji} {tier} | Affiliation: {affil}",
    ]
    if sponsor:
        lines.append(f"Sponsor: {sponsor}")
    lines.append(f"Specialty: {spec}")
    if objective:
        lines.append(f"Bond: {objective}")
    lines.append(f"Members ({len(members)}): {member_lines}")
    if loves:
        lines.append(f"Trusted by: {', '.join(loves)}")
    if hates:
        lines.append(f"Hostile with: {', '.join(hates)}")
    if visual:
        lines.append(f"Appearance: {visual}")
    if rep:
        lines.append(f"Reputation: {rep}")
    return "\n".join(lines)


def format_party_rank_change(result: dict) -> str:
    """Format a rank change result for DM notifications."""
    name     = result["name"]
    old_tier = result["old_tier"]
    new_tier = result["new_tier"]
    pts      = result["points"]
    shifted  = result["shifted"]
    delta    = result["delta"]
    emoji    = PARTY_TIER_EMOJI.get(new_tier, "")
    sign     = "+" if delta > 0 else ""

    if shifted:
        direction = "▲ advanced" if PARTY_TIER_INDEX[new_tier] > PARTY_TIER_INDEX[old_tier] else "▼ fell"
        return (
            f"🎖️ **{name}** rank {direction}: **{old_tier} → {new_tier}** {emoji}"
        )
    else:
        bar = _rank_bar(pts)
        return (
            f"🎖️ **{name}**: {emoji} {new_tier} {bar} ({sign}{delta} this mission)"
        )


def _rank_bar(pts: int) -> str:
    filled    = abs(pts)
    empty     = PARTY_POINTS_TO_SHIFT - filled
    direction = "▲" if pts >= 0 else "▼"
    return f"`{'█' * filled}{'░' * empty}` {direction}"


# ---------------------------------------------------------------------------
# /partyranks display helper
# ---------------------------------------------------------------------------

def format_all_party_ranks() -> str:
    """Formatted string for a /partyranks command embed."""
    try:
        rows = raw_query("SELECT party_name, members_json FROM party_profiles")
        profiles = []
        for row in rows:
            try:
                data = row.get("members_json", {})
                if isinstance(data, str):
                    data = json.loads(data)
                if data.get("name") or row.get("party_name"):
                    data["name"] = data.get("name") or row.get("party_name")
                    profiles.append(data)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error loading party ranks: {e}")
        profiles = []

    if not profiles:
        return "*No party records yet.*"

    # Sort by tier descending, then by name
    profiles.sort(
        key=lambda p: (-PARTY_TIER_INDEX.get(p.get("tier", "Unknown"), 0), p.get("name", ""))
    )

    lines = []
    for p in profiles:
        tier    = p.get("tier", "Unknown")
        pts     = p.get("points", 0)
        emoji   = PARTY_TIER_EMOJI.get(tier, "")
        done    = p.get("missions_completed", 0)
        fail    = p.get("missions_failed", 0)
        affil   = p.get("affiliation", "No Affiliation")
        bar     = _rank_bar(pts)
        lines.append(
            f"{emoji} **{p['name']}** — {tier} {bar}\n"
            f"  ✅ {done}  💥 {fail}  |  {affil}"
        )

    return "\n".join(lines)
