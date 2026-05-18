"""
mission_board.py — Tower of Last Chance live mission board.

Posts AI-generated missions to a dedicated Discord channel.
Each mission has a tiered expiry (1-190 days based on type).
Expired missions get a resolution post. State persists across restarts.

Channel: MISSION_BOARD_CHANNEL_ID (set in .env)
Storage: campaign_docs/mission_memory.json
"""

from __future__ import annotations

import os
import re
import json
import random
import asyncio
import discord
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from src.log import logger
from src.db_api import raw_query, raw_execute, db

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"

# Per-party claim probability per hourly check during the claim window.
# Each party in the sample rolls independently — first success claims the mission.
# Lower = fewer claims per cycle, missions sit longer. Higher = missions get snapped up fast.
CLAIM_PROBABILITY_PER_PARTY = 0.25
# How many parties evaluate each eligible mission per hourly check.
# e.g. 4 parties × 25% each = ~68% chance some party claims per cycle.
CLAIM_PARTIES_PER_CHECK = 4
# Claim window: missions become eligible for NPC claims after CLAIM_DAYS_MIN days,
# and the window closes after CLAIM_DAYS_MAX days (then it just expires or gets swept).
CLAIM_DAYS_MIN     = 1
CLAIM_DAYS_MAX     = 4   # extended: board sweep is at day 5, keep the window open to day 4

# Urgency window — missions older than this (days) get a boosted claim probability.
# Simulates parties taking notice of contracts sitting unclaimed for too long.
CLAIM_URGENCY_THRESHOLD_DAYS = 2.0
CLAIM_URGENCY_MULTIPLIER     = 2.5   # probability × this for stale missions

# Non-personal unclaimed missions older than this are swept from the board
# Must be > CLAIM_DAYS_MAX so claim-scheduled missions aren't swept before they fire
BOARD_MAX_AGE_DAYS = 5

# Personal mission rescission — old unclaimed personal missions get withdrawn with a story reason
PERSONAL_RESCIND_AGE_DAYS = 4     # eligible after this many days sitting unclaimed
PERSONAL_RESCIND_CHANCE   = 0.12  # per hourly check (~3 rolls/day ≈ 32% daily chance)

# Board caps — bot will not post new missions if active count meets these
MAX_ACTIVE_NORMAL   = 30   # non-personal, unresolved missions
MAX_ACTIVE_PERSONAL = 3    # per-character personal missions active at once

# Reaction emojis for player/DM interaction
EMOJI_CLAIM    = "⚔️"   # any player reacts to claim a mission
EMOJI_COMPLETE = "✅"   # DM reacts to mark a mission completed
EMOJI_FAIL     = "❌"   # DM reacts to mark a mission failed


def _get_results_channel_id() -> int:
    """Channel ID for mission result messages (claims, completions, failures, expirations).
    Falls back to MISSION_BOARD_CHANNEL_ID if MISSION_RESULTS_CHANNEL_ID is not set."""
    results_id = int(os.getenv("MISSION_RESULTS_CHANNEL_ID", "0"))
    if results_id:
        return results_id

    board_id = int(os.getenv("MISSION_BOARD_CHANNEL_ID", "0"))
    if not board_id:
        logger.warning("❌ MISSION_RESULTS_CHANNEL_ID and MISSION_BOARD_CHANNEL_ID both unset")
    return board_id


async def _get_results_channel(client, fallback_channel=None):
    """
    Resolve the results channel, falling back to board channel or provided fallback.
    CRITICAL FIX: Actually validates channel is accessible before returning.
    """
    results_id = int(os.getenv("MISSION_RESULTS_CHANNEL_ID", "0"))
    board_id = int(os.getenv("MISSION_BOARD_CHANNEL_ID", "0"))
    ch = None

    # Try results channel first
    if results_id and client:
        ch = client.get_channel(results_id)
        if ch is None and results_id:
            try:
                ch = await client.fetch_channel(results_id)
                logger.info(f"📋 Results channel {results_id} fetched from API")
            except Exception as e:
                logger.warning(f"📋 Cannot access results channel {results_id}: {e}")
                ch = None

    # Verify send permissions on results channel
    if ch is not None:
        try:
            perms = ch.permissions_for(ch.guild.me) if hasattr(ch, 'guild') and ch.guild else None
            if perms and not perms.send_messages:
                logger.warning(f"📋 No send permission in results channel {results_id}, falling back")
                ch = None
        except Exception:
            pass

    # Fallback to board channel if results channel failed
    if ch is None and board_id and client:
        ch = client.get_channel(board_id)
        if ch is None and board_id:
            try:
                ch = await client.fetch_channel(board_id)
                logger.info(f"📋 Board channel {board_id} fetched from API (fallback)")
            except Exception as e:
                logger.warning(f"📋 Cannot access board channel {board_id}: {e}")
                ch = None

    # Final fallback to provided channel
    if ch is None:
        ch = fallback_channel
        if ch:
            logger.info(f"📋 Using provided fallback channel")
        else:
            logger.error(f"❌ No valid channel available for mission results")

    return ch

# ---------------------------------------------------------------------------
# Tier expiry ranges (days)
# ---------------------------------------------------------------------------

TIER_EXPIRY = {
    "local":        (1,   7),
    "patrol":       (1,   7),
    "escort":       (7,  30),
    "standard":     (7,  30),
    "investigation":(7, 30),
    "rift":         (30, 90),
    "dungeon":      (30, 90),
    "dungeon-delve":(30, 90),
    "major":        (30, 90),
    "inter-guild":  (30, 90),
    "epic":         (90, 190),
    "divine":       (90, 190),
    "tower":        (90, 190),
    "high-stakes":  (60, 120),
}

DEFAULT_EXPIRY = (7, 30)

# Personal mission expiry — longer to account for real-life scheduling
PERSONAL_TIER_EXPIRY = {
    "local":        (14,  30),
    "patrol":       (14,  30),
    "escort":       (30,  60),
    "standard":     (30,  60),
    "investigation":(30,  60),
    "rift":         (60,  90),
    "dungeon":      (60,  90),
    "dungeon-delve":(60,  90),
    "major":        (60,  90),
    "inter-guild":  (60,  90),
    "epic":         (90, 190),
    "divine":       (90, 190),
    "tower":        (90, 190),
    "high-stakes":  (60, 120),
}
PERSONAL_DEFAULT_EXPIRY = (30, 60)

# How long between personal mission cycles (seconds) — 1 to 3 days per character
PERSONAL_MISSION_MIN = 1 * 24 * 60 * 60
PERSONAL_MISSION_MAX = 3 * 24 * 60 * 60

# How often to trickle a new mission (seconds) — 6 to 12 hours
TRICKLE_MIN = 6 * 60 * 60
TRICKLE_MAX = 12 * 60 * 60

# Startup burst: 3 missions, this many seconds apart
STARTUP_BURST_COUNT = 3
STARTUP_BURST_GAP = 120  # 2 minutes

# ---------------------------------------------------------------------------
# World lore prompt (concise — same model as news feed)
# ---------------------------------------------------------------------------

_LORE = """\
SETTING: The Undercity — a sealed city under a Dome around the Tower of Last Chance.
Rifts tear reality constantly. Adventurers are a recognised economic class: ranked, taxed, watched.

CURRENCY: Essence Coins (EC), Kharma (faith energy), Legend Points (LP = heroic fame).

REWARD FORMULA: base 150 EC × 1.1^CR × 1.2^diff_level  (CR = party level + encounter modifier)
  Difficulty levels:  🟢 green = ×0.83  |  🟡 yellow = ×1.0  |  🟠 orange = ×1.2  |  🔴 red = ×1.44  |  🟣 purple = ×1.73

TYPICAL REWARD RANGES (at standard party CR for each tier):
  EC (Essence Coins — the main reward):
    local/patrol       (🟢 CR 2):  105–195 EC
    standard/escort    (🟡 CR 4):  155–285 EC
    investigation      (🟡 CR 4):  155–285 EC
    dungeon/rift/major (🟠 CR 6):  225–415 EC
    inter-guild        (🔴 CR 9):  430–800 EC
    high-stakes        (🔴 CR 11): 570–1050 EC
    epic               (🟣 CR 15): 1010–1880 EC
    divine/tower       (🟣 CR 19): 1490–2760 EC

  Kharma (faith energy — rare, most missions omit it entirely):
    local/patrol: none (do NOT award Kharma for small jobs)
    standard/escort: 15–38 Kharma (optional)
    investigation/dungeon/rift: 20–52 Kharma (optional)
    inter-guild/high-stakes: 57–106 Kharma
    epic/divine/tower: 135–280 Kharma
    HARD CEILING: 1200 Kharma maximum, ever.

  Legend Points (LP): epic/divine/tower only — 1–5 LP maximum.

FACTIONS (use ONLY these — do not invent new factions under any circumstances):
Iron Fang Consortium (relics/smuggling, Serrik Dhal), Argent Blades (glory/arena, Lady Cerys Valemont),
Wardens of Ash (city defence, Captain Havel Korin), Serpent Choir (divine contracts, High Apostle Yzura),
Obsidian Lotus (black market, The Widow), Glass Sigil (arcane archivists, Senior Archivist Pell),
Patchwork Saints (Warrens protectors), Adventurers Guild (quest hub, Mari Fen),
Guild of Ashen Scrolls (fate archivists, Eir Velan), Tower Authority / FTA (oversight, Director Myra Kess),
Wizards Tower (arcane academy, Archmage Yaulderna Silverstreak — research, containment, spellcraft),
Brother Thane's Cult (doomsday cult, deep Warrens — hires through proxies only; never appears as open sponsor; use only for covert/infiltration/strange occurrences missions where the employer is deliberately obscured).
FORBIDDEN: Never reference the Culinary Council, Hollow Waiter, or any faction not listed above. If you invent a faction name, you have failed.

DISTRICTS: Markets Infinite, Sanctum Quarter, Grand Forum, Guild Spires, The Warrens, Outer Wall.

MISSION TIERS (use exactly one of these tier labels in your output):
- local / patrol → small neighbourhood jobs, 1-7 day contracts
- escort / standard / investigation → district-level work, 7-30 days
- rift / dungeon / major / inter-guild → serious multi-district work, 30-90 days
- epic / divine / tower / high-stakes → city-shaking events, 90-190 days

RIFT RULES: Rifts are RARE and alarming. They occur ONLY in the Warrens or near the Outer Wall — NEVER in Markets Infinite, Grand Forum, Sanctum Quarter, or Guild Spires under any circumstances.
If the mission type is a Rift, the location MUST be in the Warrens or Outer Wall. This is non-negotiable.
A Rift mission should feel like an emergency, not a routine posting. Rift missions are serious multi-week contracts, not street-level jobs.\
"""

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_missions() -> List[dict]:
    """Load all missions from database."""
    try:
        rows = raw_query("SELECT * FROM missions ORDER BY id")
        missions = []
        for row in rows:
            mission_data = row.get("mission_json")
            # Handle NULL or empty mission_json
            if mission_data is None:
                mission_data = {}
            elif isinstance(mission_data, str):
                mission_data = json.loads(mission_data) if mission_data else {}
            # Merge DB columns with JSON data
            # message_id is VARCHAR(50) in DB → always cast to int so it matches
            # discord payload.message_id (which is always an int)
            _raw_mid = row.get("message_id") or mission_data.get("message_id")
            try:
                _msg_id = int(_raw_mid) if _raw_mid is not None else None
            except (ValueError, TypeError):
                _msg_id = _raw_mid
            _created_at = row.get("created_at")
            _posted_at  = row.get("posted_at") or mission_data.get("posted_at")
            mission = {
                **mission_data,
                "id": row.get("id"),
                "title": row.get("title") or mission_data.get("title", "Unknown"),
                "faction": row.get("faction") or mission_data.get("faction", ""),
                "tier": row.get("tier") or mission_data.get("tier", "standard"),
                "status": row.get("status") or "active",
                "message_id": _msg_id,
                "created_at": str(_created_at) if _created_at else mission_data.get("created_at"),
                "posted_at":  str(_posted_at)  if _posted_at  else mission_data.get("posted_at"),
            }
            # Map DB status to legacy flags
            status = row.get("status", "active")
            mission["resolved"] = status in ("resolved", "completed", "failed", "expired")
            mission["completed"] = status == "completed"
            mission["failed"] = status == "failed"
            missions.append(mission)
        return missions
    except Exception as e:
        logger.error(f"Mission load error: {e}")
        return []


def _save_missions(missions: List[dict]) -> None:
    """Save all missions to database."""
    try:
        for mission in missions:
            _save_mission(mission)
    except Exception as e:
        logger.error(f"Mission save error: {e}")


def _save_mission(mission: dict) -> None:
    """Save a single mission to database."""
    try:
        mission_id = mission.get("id")
        title = mission.get("title", "Unknown Contract")
        faction = mission.get("faction", "")
        tier = mission.get("tier", "standard")
        message_id = mission.get("message_id")

        # Determine status from legacy flags
        if mission.get("completed"):
            status = "completed"
        elif mission.get("failed"):
            status = "failed"
        elif mission.get("resolved"):
            status = "completed"
        elif mission.get("claimed") or mission.get("npc_claimed"):
            status = "claimed"
        else:
            status = "active"

        # Prepare mission_json (full mission data)
        mission_json = json.dumps(mission, ensure_ascii=False, default=str)

        # Parse dates for DB columns
        posted_at = None
        expires_at = None
        if mission.get("posted_at"):
            try:
                posted_at = datetime.fromisoformat(mission["posted_at"]).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                posted_at = None
        if mission.get("expires_at"):
            try:
                expires_at = datetime.fromisoformat(mission["expires_at"]).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                expires_at = None

        claimed_by = mission.get("player_claimer", "") or ""

        if mission_id:
            # Check if exists
            existing = raw_query("SELECT id FROM missions WHERE id = %s", (mission_id,))
            if existing:
                raw_execute(
                    "UPDATE missions SET title = %s, faction = %s, tier = %s, status = %s, "
                    "claimed_by = %s, message_id = %s, mission_json = %s, "
                    "posted_at = %s, expires_at = %s WHERE id = %s",
                    (title, faction, tier, status, claimed_by or None,
                     message_id, mission_json, posted_at, expires_at, mission_id)
                )
                return

        # Insert new
        new_id = db.insert("missions", {
            "title":        title,
            "faction":      faction,
            "tier":         tier,
            "status":       status,
            "claimed_by":   claimed_by or None,
            "message_id":   message_id,
            "mission_json": mission_json,
            "posted_at":    posted_at,
            "expires_at":   expires_at,
        })
        mission["id"] = new_id
    except Exception as e:
        logger.error(f"Mission save error for {mission.get('title', '?')}: {e}")


def _add_mission(mission: dict) -> None:
    """Add a new mission to database."""
    _save_mission(mission)


def _count_active_normal() -> int:
    """
    Count missions that are truly open on the board.
    Excludes: resolved, personal, NPC-claimed-pending-completion, player-claimed-pending-DM.
    NPC and player claimed missions are off the board visually — don't let them
    eat into the cap and starve new postings.
    """
    return sum(
        1 for m in _load_missions()
        if not m.get("resolved")
        and not m.get("personal_for")
        and not m.get("npc_claimed")    # NPC claimed — awaiting completion tick
        and not m.get("claimed")        # player claimed — awaiting DM resolution
    )


def _count_active_personal(character_name: str) -> int:
    """Count unresolved personal missions for a specific character."""
    return sum(
        1 for m in _load_missions()
        if not m.get("resolved")
        and m.get("personal_for", "").lower() == character_name.lower()
    )


def _update_mission(message_id: int, updates: dict) -> None:
    """Update a mission by its Discord message_id."""
    try:
        # Find the mission by message_id
        rows = raw_query("SELECT id, mission_json FROM missions WHERE message_id = %s", (message_id,))
        if not rows:
            return

        row = rows[0]
        mission_id = row.get("id")
        mission_data = row.get("mission_json", {})
        if isinstance(mission_data, str):
            mission_data = json.loads(mission_data) if mission_data else {}

        # Apply updates
        mission_data.update(updates)
        mission_data["id"] = mission_id
        mission_data["message_id"] = message_id

        # Save back
        _save_mission(mission_data)
    except Exception as e:
        logger.error(f"Mission update error for message_id {message_id}: {e}")


# ---------------------------------------------------------------------------
# Expiry helpers
# ---------------------------------------------------------------------------

def _expiry_for_tier(tier: str) -> datetime:
    tier_key = tier.lower().strip()
    lo, hi = TIER_EXPIRY.get(tier_key, DEFAULT_EXPIRY)
    days = random.randint(lo, hi)
    return datetime.utcnow() + timedelta(days=days)


def _parse_tier(text: str) -> str:
    """Extract the difficulty tier label from generated mission text.
    Looks in the Tier: field first to avoid matching type names (e.g. 'Investigation')."""
    # Try to match explicitly after "Tier:" label
    tier_match = re.search(r"[Tt]ier:\s*([a-z\-]+)", text)
    if tier_match:
        candidate = tier_match.group(1).strip().lower()
        if candidate in TIER_EXPIRY:
            return candidate
    # Fallback: scan full text (legacy missions without Type: line)
    text_lower = text.lower()
    for key in TIER_EXPIRY:
        if key in text_lower:
            return key
    return "standard"


def _difficulty_circle(tier: str) -> str:
    """Return a colored circle emoji indicating mission difficulty."""
    t = tier.lower().strip()
    if t in ("local", "patrol"):
        return "🟢"   # easy
    if t in ("escort", "standard", "investigation", "social", "bounty"):
        return "🟡"   # medium
    if t in ("rift", "dungeon", "dungeon-delve", "major", "combat", "heist"):
        return "🟠"   # hard
    if t in ("inter-guild", "high-stakes"):
        return "🔴"   # very hard
    if t in ("epic", "divine", "tower"):
        return "🟣"   # legendary
    return "⚪"        # unknown


def _format_mission_type(tier: str) -> str:
    """Return a human-readable mission type label from tier."""
    labels = {
        "local": "Local Contract", "patrol": "Patrol",
        "escort": "Escort", "standard": "Contract",
        "investigation": "Investigation", "social": "Diplomatic",
        "bounty": "Bounty Hunt", "combat": "Combat",
        "heist": "Heist", "rift": "Rift Response",
        "dungeon": "Dungeon Delve", "dungeon-delve": "Dungeon Delve",
        "major": "Major Operation", "inter-guild": "Inter-Guild",
        "high-stakes": "High Stakes", "epic": "Epic",
        "divine": "Divine", "tower": "Tower Crisis",
    }
    return labels.get(tier.lower().strip(), tier.title())


def _build_mission_embed(
    mission: dict,
    embed_color: int,
    tier_label: str,
    days_left: int,
    personal_for: str = "",
) -> "discord.Embed":
    """
    Build a clean, screen-reader-friendly Discord embed for a mission bulletin.

    Layout:
      Title:       Mission Title
      Author:      Faction Name
      Description: Pure story paragraph — no metadata, no pipes, no asterisks
      Fields:      Type | Tier | Reward  (inline)
                   Contact (if present)
                   Opposes (if present)
      Footer:      difficulty circle · standing · expires · claim prompt
    """
    import discord as _d

    title       = mission.get("title", "Unknown Mission")
    faction     = mission.get("faction", "")
    mtype       = mission.get("type") or _format_mission_type(mission.get("tier", "standard"))
    tier        = mission.get("tier", "standard").title()
    reward      = mission.get("reward", "See posting")
    opposing    = mission.get("opposing_faction", "")
    contact     = mission.get("contact", "")
    story_text  = mission.get("public_text", "") or mission.get("story_text", "") or mission.get("body", "")
    _circle     = _difficulty_circle(mission.get("tier", "standard"))

    # Clean story text of any residual markdown asterisks/pipes
    story_clean = re.sub(r'\*+', '', story_text).strip()
    story_clean = _public_story_from_text(story_clean)
    # Keep board posts compact; module-only notes stay in mission["body"].
    if len(story_clean) > 700:
        story_clean = story_clean[:697].rsplit(" ", 1)[0] + "..."

    embed = _d.Embed(
        title=title,
        description=story_clean,
        color=embed_color,
    )
    embed.set_author(name=faction)

    # Inline metadata fields — TTS reads these as "Type: Recovery. Tier: Standard. Reward: 200 EC."
    embed.add_field(name="Type",   value=mtype,  inline=True)
    embed.add_field(name="Tier",   value=tier,   inline=True)
    embed.add_field(name="Reward", value=reward, inline=True)

    if contact:
        embed.add_field(name="Contact", value=contact, inline=False)

    if opposing:
        embed.add_field(name="⚠️ Opposes", value=opposing, inline=False)

    footer_parts = []
    if personal_for:
        footer_parts.append(f"📌 Personal for {personal_for}")
    footer_parts += [
        f"{_circle} {mtype}",
        f"Standing: {tier_label}",
        f"Expires in {days_left}d",
        "React ⚔️ to claim",
    ]
    if opposing:
        footer_parts.append(f"Opposes: {opposing}")
    embed.set_footer(text="  •  ".join(footer_parts))

    return embed


# ---------------------------------------------------------------------------
# Mission generation prompt
# ---------------------------------------------------------------------------

_MISSION_TYPES = [
    # Legacy fallback list. Actual random selection uses _weighted_mission_types()
    # so finished standalone pipelines show up much more often than unfinished
    # generic types.
    "Escort",
    "Investigation",
    "Ambush",
    "Rescue",
    "Sabotage",
    "Infiltration",
    "Defense",
    "Puzzle",
    "Gathering",
    "Assault",
    "Heist",
    "Infestation",
    "Recovery",
    "Battle",
    "Negotiation",
    "First Contact",
    "Theft",
    "Exploration",
    "Discovery",
    "Delivery",
    "Assassination",
    "Political",
    "Strange Occurrences",
]

# Keep this list in step with src/mission_builder/*_pipeline.py. When a new
# pipeline is built, move its public board label here and give it a heavy
# weight. Anything not built stays in _UNBUILT_LOW_WEIGHT_TYPES.
_PIPELINE_MISSION_TYPE_WEIGHTS = {
    "Escort": 12,
    "Investigation": 12,
    "Ambush": 12,
    "Rescue": 12,
    "Sabotage": 12,
    "Infiltration": 12,
    "Defense": 12,
    "Puzzle": 12,
    "Gathering": 12,
    "Assault": 12,
    "Heist": 12,
    "Infestation": 12,
    "Negotiation": 12,
    "Exploration": 12,
    "Discovery": 12,
    "First Contact": 12,
    "Strange Occurrences": 12,
    "Recovery": 12,
}

_UNBUILT_LOW_WEIGHT_TYPES = {
    "Battle": 1,
    "Theft": 1,
    "Delivery": 1,
    "Assassination": 1,
    "Political": 1,
}


def _weighted_mission_types() -> List[str]:
    """Return board type labels weighted toward completed standalone pipelines."""
    weighted: List[str] = []
    for label, weight in _PIPELINE_MISSION_TYPE_WEIGHTS.items():
        weighted.extend([label] * max(1, int(weight)))
    for label, weight in _UNBUILT_LOW_WEIGHT_TYPES.items():
        weighted.extend([label] * max(1, int(weight)))
    for label in _load_generated_mission_types():
        # AI-generated/unimplemented labels are allowed as rare spice only.
        weighted.append(label)
    return weighted or list(_MISSION_TYPES)

# ---------------------------------------------------------------------------
# Mission type narrative templates (DB-backed)
# ---------------------------------------------------------------------------

_MISSION_TYPE_TEMPLATES = [
    {"slug": "neighbourhood", "display_name": "Neighbourhood Job",
     "who": "A local small-time employer — a shopkeeper, gang lieutenant, worried parent, or minor faction contact",
     "what": "A street-level task: deliver a package, collect a debt, track down a missing person, or deal with a local nuisance",
     "when_hint": "Urgency is personal and immediate — someone needs this done before nightfall or before things escalate further",
     "why": "The employer can't do it themselves — they lack muscle, connections, or the nerve to handle it",
     "where_hint": "The streets, back alleys, tenements, and markets of a specific district — grounded and concrete",
     "story_frame": "This is a neighbourhood story about ordinary people in desperate circumstances, a small wrong that needs righting, and the price of getting involved in someone else's trouble — themes of community, survival, and the cost of looking away.",
     "keywords": "neighbourhood,neighborhood,local,courier,debt,missing,street,district",
     "combat_posture": "RISKY",
     "combat_rep_cost": "You made a scene in someone's home district. Word spread through the streets. The community talks, and the faction that hired you has to manage the fallout. Quiet neighbourhood jobs stop coming your way."},
    {"slug": "patrol", "display_name": "Patrol Contract",
     "who": "A Warden-adjacent employer, district council, merchant guild, or faction with territorial interests",
     "what": "Sweep a district, investigate a suspicious location, or maintain visible presence to deter threats",
     "when_hint": "Scheduled or responding to a recent incident that has spooked the locals",
     "why": "The regular Wardens are stretched thin, compromised, or absent — someone needs boots on the ground",
     "where_hint": "A specific district with defined patrol routes, chokepoints, and known trouble spots",
     "story_frame": "This is a patrol story about authority's limits, a district holding its breath, and hired hands standing between order and chaos — themes of duty, tension, and what it costs to keep the peace.",
     "keywords": "patrol,warden,district,sweep,suspicious,check",
     "combat_posture": "PERMITTED",
     "combat_rep_cost": ""},
    {"slug": "escort", "display_name": "Escort Mission",
     "who": "A vulnerable principal — merchant, diplomat, witness, refugee, or valuable cargo — and a faction with reason to protect them",
     "what": "Move a person or cargo safely from one point to another through dangerous territory",
     "when_hint": "The window is specific — a departure time, a tide, or a rendezvous that cannot slip",
     "why": "The route is contested — enemies, rival factions, or environmental hazards make it deadly to travel alone",
     "where_hint": "The journey passes through at least one genuinely dangerous location — a contested district, the Outer Wall, Warrens tunnels",
     "story_frame": "This is a protection story about a vulnerable charge, a dangerous road, and whether hired loyalty holds when things go wrong — themes of trust, danger, and the weight of responsibility.",
     "keywords": "escort,protect,cargo,convoy,guard,safe passage",
     "combat_posture": "PERMITTED",
     "combat_rep_cost": ""},
    {"slug": "investigation", "display_name": "Investigation",
     "who": "A client who can't go to the Wardens — a faction, a grieving family, a frightened official, or someone with something to hide",
     "what": "Uncover the truth about a disappearance, an unexplained death, a pattern of corruption, or a secret powerful people want buried",
     "when_hint": "Evidence is fading — witnesses go quiet, scenes get cleaned up, trails go cold fast",
     "why": "The official channels are compromised, uninterested, or in on it",
     "where_hint": "Multiple locations across the city — witnesses to interview, sites to search, records to pull",
     "story_frame": "This is a mystery story about hidden truth, powerful people with things to hide, and investigators who have to decide how far they're willing to dig — themes of corruption, secrets, and the cost of knowing.",
     "keywords": "investigation,investigate,missing,corruption,track,unexplained,mystery",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "Going loud means witnesses scatter and leads go cold. You finished the job but the truth stays buried. Glass Sigil stops calling."},
    {"slug": "inter-guild", "display_name": "Inter-Guild Conflict",
     "who": "A faction with a rival and a job that needs deniability — spy on them, sabotage their operation, or broker an uneasy peace",
     "what": "Work on behalf of one faction to gain advantage over, neutralize, or negotiate with another",
     "when_hint": "A power struggle at a critical moment — an election, a territory dispute, a contract up for renewal",
     "why": "Factions can't be seen handling this themselves — deniability is the entire point",
     "where_hint": "The rival faction's operations — their turf, their buildings, their key people",
     "story_frame": "This is a political story about faction power, deniable operations, and hired hands caught between organizations that will sacrifice them without hesitation — themes of loyalty, betrayal, and the game of power.",
     "keywords": "guild,faction,rival,inter-guild,conflict,mediate,spy,sabotage",
     "combat_posture": "RISKY",
     "combat_rep_cost": "The deniability the faction paid for is gone. Both factions know who did it. The faction that hired you takes heat publicly and stops calling. You're flagged as a liability for sensitive work."},
    {"slug": "high-stakes", "display_name": "High-Stakes Contract",
     "who": "A powerful employer — a major faction leader, a Tower Authority figure, or a mysterious patron with deep pockets and deeper secrets",
     "what": "An assassination, a political black operation, the recovery of a critical relic, or an act that will reshape faction dynamics",
     "when_hint": "The moment is now — delay means someone else gets there first, or the window closes permanently",
     "why": "The stakes are too high for hesitation: this changes things at the city level",
     "where_hint": "A heavily secured or politically sensitive location — a faction headquarters, a Tower floor, a noble estate",
     "story_frame": "This is a high-stakes thriller about power, consequence, and the kind of job that changes everyone involved — themes of ambition, risk, and the point of no return.",
     "keywords": "high-stakes,assassination,political,relic,black op",
     "combat_posture": "PERMITTED",
     "combat_rep_cost": ""},
    {"slug": "dungeon", "display_name": "Dungeon Delve",
     "who": "A faction or scholar with interest in what's below — or a desperate crew chasing rumored riches",
     "what": "Enter an abandoned structure, sealed vault, or underground complex and bring back what's inside — or clear out what's living there",
     "when_hint": "Something has changed — a collapse opened a new passage, something started coming out, or a deadline makes waiting impossible",
     "why": "What's inside is valuable, dangerous, or both — and no one else is willing to go in after it",
     "where_hint": "Below the Warrens or within the Outer Wall — decayed infrastructure, sealed chambers, forgotten places",
     "story_frame": "This is a delve story about what was left behind, what's survived down there, and what a crew is willing to risk for what's buried in the dark — themes of greed, danger, and the weight of history.",
     "keywords": "dungeon,delve,abandoned,vault,warrens,underground,sealed",
     "combat_posture": "PERMITTED",
     "combat_rep_cost": ""},
    {"slug": "rift", "display_name": "Rift Clearance",
     "who": "The Wardens, the Tower Authority, or a faction whose territory is being consumed — whoever is desperate enough to hire outsiders",
     "what": "Enter the area affected by the Rift, clear or contain what's come through, and report on its current state",
     "when_hint": "The Rift has grown for days — it is now too large to ignore and too dangerous for standard Warden response",
     "why": "Standard forces have already failed or won't go in — this is a last resort",
     "where_hint": "The Warrens or the Outer Wall ONLY — remote, industrial, or abandoned enough that a Rift went unnoticed until it became a crisis",
     "story_frame": "This is a survival story about the thin line between the city and what lies beyond it, a tear in the world that shouldn't exist, and people who go in anyway — themes of horror, sacrifice, and the fragility of order.",
     "keywords": "rift,clearance,anomaly,containment,tear",
     "combat_posture": "EXPECTED",
     "combat_rep_cost": ""},
    {"slug": "epic", "display_name": "Epic / Divine Mission",
     "who": "A divine patron, the Tower Authority at its highest levels, or a faction whose very existence is at stake",
     "what": "An act of city-scale consequence — a ritual that must be completed or stopped, a divine compact violated, a Tower floor gone silent",
     "when_hint": "The crisis is already unfolding — every hour of delay makes it worse",
     "why": "Normal channels have failed completely; the stakes are existential",
     "where_hint": "The upper floors of the Tower, a site of divine significance, or anywhere the fabric of the city is at risk",
     "story_frame": "This is an epic story about power at its absolute limit, divine or arcane forces bleeding into city life, and who is willing to act when everything is on the line — themes of sacrifice, destiny, and consequence.",
     "keywords": "epic,divine,tower floor,god,city-scale,ritual",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "You forced a city-scale resolution through violence. Everyone watching remembers it. Subtle operations and diplomatic missions stop coming. Whatever compact you broke through force may not be repairable."},
    {"slug": "theft", "display_name": "Theft / Heist",
     "who": "A faction or private patron who wants something that belongs to someone else — or a crew with a tip on a score",
     "what": "Break in, take the target (object, documents, person, or information), and get out without being caught",
     "when_hint": "A window of opportunity that will close — a guard rotation, a transfer, or an event that creates cover",
     "why": "The target cannot be acquired through any legitimate means; someone with power has it locked away",
     "where_hint": "A secured location — a vault, a guarded warehouse, a private compound, a faction strongroom",
     "story_frame": "This is a heist story about a prize that's locked away, a crew that has to be better than the security protecting it, and the moment everything goes sideways — themes of planning, risk, greed, and improvisation.",
     "keywords": "theft,heist,steal,break in,vault,rob,score",
     "combat_posture": "RISKY",
     "combat_rep_cost": "Word got out the job was loud. Next score comes with a lower cut — the fence doesn't trust you with delicate work anymore. The mark's faction now knows what you look like."},
    {"slug": "heist", "display_name": "Heist",
     "who": "A shady sponsor — Obsidian Lotus, Iron Fang Consortium, Glass Sigil, Argent Blades, Serpent Choir, or Brother Thane's Cult — with a score that needs deniable hands",
     "what": "Acquire, swap, plant, copy, recover, or destroy a valuable target through planning, security bypass, controlled chaos, and escape",
     "when_hint": "A public event, guard rhythm, transfer, train schedule, auction, gallery opening, or vault window gives the crew a chance",
     "why": "The score cannot be bought cleanly and the sponsor cannot be seen reaching for it",
     "where_hint": "A secured but public-facing site — bank, underground vault, museum, auction house, casino, archive, train, hotel, or private gallery",
     "story_frame": "This is a caper story about casing the joint, moving the score, keeping heat manageable, and escaping before anyone can prove who did it — themes of style, pressure, greed, misdirection, and double-crosses.",
     "keywords": "heist,robbery,rob,score,bank,vault,museum,auction,jewel,train,caper",
     "combat_posture": "RISKY",
     "combat_rep_cost": "The job still pays if the score lands, but loud crews get worse cuts, more heat, and fewer delicate invitations. The target owner starts watching the party."},
    {"slug": "assassination", "display_name": "Assassination",
     "who": "A faction, a patron, or a wronged party with both the motivation and resources to pay for a kill",
     "what": "Locate and eliminate a specific target — cleanly, quietly, or with a deliberate message",
     "when_hint": "The target is vulnerable now, or soon — delay loses the window entirely",
     "why": "The target is too well-protected for a direct approach; precision and deniability are required",
     "where_hint": "The target's own territory — wherever they feel safest, which is exactly the problem",
     "story_frame": "This is a contract story about a target with powerful enemies, hired hands with a job to do, and the question of what it costs to take a life for money — themes of morality, precision, and consequence.",
     "keywords": "assassination,assassinate,eliminate,kill,target,contract killing",
     "combat_posture": "PERMITTED",
     "combat_rep_cost": ""},
    {"slug": "rescue", "display_name": "Rescue Operation",
     "who": "A desperate employer — a family, a faction, a partner — whose person is in someone else's hands",
     "what": "Locate a captive and extract them safely from a faction holding cell, a criminal operation, or somewhere worse",
     "when_hint": "Time is the enemy — the window before the captive is moved, harmed, or beyond reach is closing",
     "why": "Official channels are impossible — they're compromised, too slow, or the captors are the officials",
     "where_hint": "A location controlled by hostile forces — a rival faction's territory, a gang compound, a hidden site",
     "story_frame": "This is a rescue story about someone in danger, a crew racing against the clock, and what it means to bring someone home — themes of loyalty, urgency, and the cost of leaving no one behind.",
     "keywords": "rescue,captive,hostage,extract,save,prisoner",
     "combat_posture": "PERMITTED",
     "combat_rep_cost": ""},
    {"slug": "delivery", "display_name": "Courier / Delivery",
     "who": "A faction, merchant, or private client with something that absolutely must arrive — intact and unexamined",
     "what": "Transport a package, message, or cargo from one point to another without losing it, opening it, or being intercepted",
     "when_hint": "The recipient is waiting — there is a specific handoff window that cannot slip",
     "why": "The contents are too sensitive for normal channels; the route is known to be watched",
     "where_hint": "Across district boundaries through territory where interception is likely",
     "story_frame": "This is a courier story about cargo no one is supposed to know about, a route with eyes on it, and runners deciding how much they want to know about what they're carrying — themes of secrecy, trust, and the trouble that finds you anyway.",
     "keywords": "delivery,courier,transport,package,cargo,message",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "You fought your way through. The package arrived but word got out it existed. Someone else now knows what was being moved — and who moved it."},
    {"slug": "bounty", "display_name": "Bounty Hunt",
     "who": "A faction, Warden office, or private party with a target and a price on their head",
     "what": "Track, locate, and bring in — alive or dead, as specified — a fugitive, deserter, or wanted criminal",
     "when_hint": "The target has a head start but hasn't vanished completely — the trail is cold but not dead",
     "why": "The Wardens are compromised, outmatched, or politically unable to pursue",
     "where_hint": "Wherever the target has gone to ground — often the outer districts, the Warrens, or beyond the Wall",
     "story_frame": "This is a manhunt story about a target who doesn't want to be found, trackers who have to think like their quarry, and the fine line between justice and hired violence — themes of pursuit, desperation, and what it means to be hunted.",
     "keywords": "bounty,bounty hunt,track,fugitive,wanted,manhunt",
     "combat_posture": "PERMITTED",
     "combat_rep_cost": ""},
    {"slug": "espionage", "display_name": "Faction Espionage",
     "who": "A faction that needs to know what its rivals are planning — or to plant something without being detected",
     "what": "Infiltrate a rival faction's operation, steal intelligence, observe key meetings, or insert false information",
     "when_hint": "A decision is being made or finalized — the intelligence is only valuable if it arrives in time",
     "why": "The faction can't risk exposing its own operatives; deniable outside contractors are safer",
     "where_hint": "Inside the rival faction's sphere — their offices, meeting rooms, warehouses, communication channels",
     "story_frame": "This is a spy story about information as a weapon, deniable operatives inside enemy territory, and the paranoia that comes from not knowing who knows what — themes of deception, loyalty, and the cost of getting caught.",
     "keywords": "espionage,spy,infiltrat,intelligence,observe,plant,mole",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "You got the intel but left bodies. The faction that hired you wanted deniability — they'll pay but they'll hire someone else next time. The rival faction now knows an outside crew was used against them."},
    {"slug": "sabotage", "display_name": "Sabotage",
     "who": "A faction trying to hurt a rival's operations — economically, logistically, or politically",
     "what": "Destroy or disable a key asset: a shipment, a machine, a supply line, or an operation's critical infrastructure",
     "when_hint": "The target is at its most vulnerable — during a transfer, a major operation, or a moment of distraction",
     "why": "The faction wants to hurt its rival without open conflict; sabotage provides deniability",
     "where_hint": "The rival's operational territory — warehouses, work sites, transit points, key infrastructure",
     "story_frame": "This is a sabotage story about a faction's point of weakness, the precise moment to strike it, and hired hands who have to get out before the damage is discovered — themes of disruption, deniability, and the collateral cost of faction war.",
     "keywords": "sabotage,destroy,disable,disrupt,supply line,infrastructure",
     "combat_posture": "RISKY",
     "combat_rep_cost": "You left a trail. The deniability the faction paid for is gone — they distance themselves from you publicly, and other factions won't use you for sensitive work. The target's faction knows it was a hired job."},
    {"slug": "smuggling", "display_name": "Smuggling Run",
     "who": "A black market operator, desperate merchant, or faction that needs goods to move outside official channels",
     "what": "Move contraband through Warden-controlled territory — forbidden goods, unregistered magic, illegal weapons, restricted substances",
     "when_hint": "A shipment is ready, a contact is waiting, and the inspection cordon is about to tighten",
     "why": "The cargo is illegal, taxed into impossibility, or politically toxic — legitimate channels aren't available",
     "where_hint": "Checkpoints, patrol routes, and the spaces between — places the law thinks nothing can move through",
     "story_frame": "This is a smuggling story about contraband powerful people want moved, corridors the law thinks it controls, and the fine art of being somewhere you're not supposed to be — themes of risk, profit, and the economics of the underground.",
     "keywords": "smuggl,contraband,black market,illegal,forbidden",
     "combat_posture": "RISKY",
     "combat_rep_cost": "The cargo got moved but the route is burned. The black market contact won't use you for quiet work again — you're too loud, too flagged. Warden attention on the area increases."},
    {"slug": "political", "display_name": "Political Intrigue",
     "who": "A faction official, a candidate for power, or a patron who plays the long game",
     "what": "Gather compromising information, broker an arrangement, discredit a rival, or protect a political asset",
     "when_hint": "A vote is coming, a position is being contested, or an alliance is forming — timing is everything",
     "why": "Faction politics require deniability; the principals cannot be seen handling this themselves",
     "where_hint": "The corridors of faction power — council rooms, private dinners, the events where decisions actually get made",
     "story_frame": "This is a political story about power disguised as procedure, deals made in back rooms, and hired hands who know too much to be fully trusted — themes of ambition, compromise, and the machinery of control.",
     "keywords": "political,politics,council,election,alliance,blackmail,discredit",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "You solved it with violence. The council seat is secured but your patron's opponents know they can't trust the arrangement. Politics gets harder — your patron's leverage weakens, and the party becomes known as muscle, not strategy."},
    {"slug": "recovery", "display_name": "Recovery",
     "who": "A faction, guild, civic office, family, pet owner, scholar, or patron who lost a non-person target and needs it returned",
     "what": "Recover evidence, relics, lost expedition gear, memory or identity packets, data records, misplaced cargo, or missing pets — not living-person extraction",
     "when_hint": "The window is closing because the target is being moved, sold, altered, destroyed, misfiled, eaten, or claimed by someone else",
     "why": "The target has practical, legal, emotional, archival, sacred, or contractual value; payment is for return to the sponsor",
     "where_hint": "Wherever the target ended up — archives, alleys, warehouses, rooftops, vaults, markets, changed rooms, cargo depots, or failed expedition sites",
     "story_frame": "This is a recovery story about finding the thing, proving it is the right thing, learning what happened to it, and getting it back under strict contract terms — themes of custody, loss, evidence, sentimental value, and the price of return.",
     "keywords": "recovery,relic,artifact,retrieve,stolen,recover,evidence,lost gear,memory,identity,data,record,misdelivered,misplaced cargo,missing pet,lost pet",
     "combat_posture": "PERMITTED",
     "combat_rep_cost": ""},
    {"slug": "strange-occurrences", "display_name": "Strange Occurrences",
     "who": "Usually the coroner's office, death registry, morgue, cemetery authority, or a frightened civic contact — rarely a sketchy faction trying to keep the weird quiet",
     "what": "Handle a civic weird case: returned dead, ghosts, revenants, doppelgangers, haunted records, memory bleed, Tower glitches, or something everyone is misreading",
     "when_hint": "The report is fresh and getting stranger by the hour; witnesses, records, and public rumor are already disagreeing",
     "why": "Someone has to learn whether this is a threat, victim, witness, guardian, scam, or faction play before panic turns it into violence",
     "where_hint": "Morgues, graveyards, family homes, death registry offices, alleys, shrines, markets, or anywhere ordinary life has started contradicting itself",
     "story_frame": "This is a strange civic case about the city deciding what counts as dead, alive, copied, haunted, guilty, or protected — themes of identity, grief, paperwork, fear, and choosing the right answer over the paid answer.",
     "keywords": "strange occurrence,strange occurrences,returned dead,ghost,revenant,doppelganger,doppleganger,haunting,graveyard,coroner,morgue,impostor,duplicate,memory bleed,tower glitch",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "You treated the weird thing as a monster before proving it was one. The coroner's office, families, and vulnerable witnesses remember. Payment may vanish even if the scene is quiet."},
    {"slug": "protection", "display_name": "Protection Detail",
     "who": "A vulnerable principal who has made enemies — a merchant, a witness, a dissident, or a faction asset that cannot be hidden",
     "what": "Maintain active security for a person or location over a defined period — sustained protection, not a single journey",
     "when_hint": "A threat has been identified; attacks are expected; the principal cannot go underground",
     "why": "The principal's visibility is necessary — they can't hide, so they need guards who can keep them alive",
     "where_hint": "The principal's regular environment — their home, their workplace, the events they cannot avoid attending",
     "story_frame": "This is a bodyguard story about a principal with enemies, hired security that has to stay sharp, and the moment a threat becomes real — themes of vigilance, loyalty, and what it costs to keep someone alive.",
     "keywords": "protection,protect,guard,bodyguard,security,detail",
     "combat_posture": "PERMITTED",
     "combat_rep_cost": ""},
    {"slug": "battle", "display_name": "Battle",
     "who": "A faction, Warden unit, or desperate employer who needs fighters — not investigators",
     "what": "Engage a known enemy force directly: clear a position, break a siege, destroy a supply cache, or end a standoff through force",
     "when_hint": "The fight is imminent or already begun — there is no time for subtlety",
     "why": "The threat is armed, organised, and too large for the faction's own forces to handle alone",
     "where_hint": "A contested location — a district border, an occupied building, a critical chokepoint the enemy holds",
     "story_frame": "This is a combat story about a force that has to be broken, the cost of taking a defended position, and whether the hired crew is still standing when the dust settles — themes of courage, violence, and the ugly arithmetic of war.",
     "keywords": "battle,combat,fight,assault,attack,engage,clear,break,destroy",
     "combat_posture": "EXPECTED",
     "combat_rep_cost": ""},
    {"slug": "assault", "display_name": "Assault",
     "who": "A faction that needs a fixed position taken and gives the party faction-appropriate troops to lead",
     "what": "Lead one offensive push against a defended position, manage friendly morale, break defender morale, reach the objective, or neutralize the commander",
     "when_hint": "The assault window is open now — delay lets defenders reinforce, relocate, or harden the position",
     "why": "The sponsor cannot take the position without outside leadership and the defenders have home-field advantage",
     "where_hint": "A fixed position: gate, stronghold, checkpoint, warehouse, office, shrine, vault, safehouse, plaza, or defended building",
     "story_frame": "This is an offensive command story about leading people into danger, keeping them from breaking, and deciding whether to keep fighting when the faction force fails — themes of morale, pressure, leadership, and the cost of taking ground.",
     "keywords": "assault,attack,storm,breach,seize,capture,offensive,take position",
     "combat_posture": "EXPECTED",
     "combat_rep_cost": ""},
    {"slug": "infestation", "display_name": "Infestation",
     "who": "A faction, district contact, owner, or desperate local group with a place overrun by things that should not be nesting there",
     "what": "Identify, contain, clear, burn out, relocate, or seal an infestation before it spreads through a site or district",
     "when_hint": "The problem is spreading — eggs hatch, tunnels open, vermin migrate, rift-things multiply, or civilians start disappearing",
     "why": "Ordinary cleanup failed, the source is dangerous, and waiting lets the infestation claim more ground",
     "where_hint": "A contained but worsening site: cellar, sewer, warehouse, tenement, shrine crawlspace, market basement, tunnel, clinic, or sealed ruin",
     "story_frame": "This is a containment story about something multiplying in the dark, the source that keeps feeding it, and the difference between clearing symptoms and ending the nest — themes of disgust, urgency, containment, and collateral risk.",
     "keywords": "infestation,infested,nest,swarm,vermin,eggs,hive,plague,spawn",
     "combat_posture": "EXPECTED",
     "combat_rep_cost": ""},
    {"slug": "ambush", "display_name": "Ambush",
     "who": "A faction or desperate employer who needs a specific target stopped — or a crew that walked into something they didn't expect",
     "what": "Either set and spring a trap against a moving target, or respond to an ambush that has already been triggered",
     "when_hint": "Timing is everything — the target moves on a specific route, at a specific time, and the window is narrow",
     "why": "A direct confrontation is impossible; the target is too dangerous or too well-guarded except in transit",
     "where_hint": "A chokepoint — an alley, a bridge, a market crossing, a loading dock — somewhere that boxes a target in",
     "story_frame": "This is a tactical story about controlling the ground before the fight, the moment a plan meets reality, and who survives when a trap snaps shut — themes of preparation, surprise, and the chaos when everything goes wrong.",
     "keywords": "ambush,trap,intercept,waylay,chokepoint,transit",
     "combat_posture": "EXPECTED",
     "combat_rep_cost": ""},
    {"slug": "negotiation", "display_name": "Negotiation",
     "who": "A faction that needs an agreement — or a desperate party trying to stop a conflict before it starts",
     "what": "Broker a deal, secure a ceasefire, extract a concession, or represent one side in a high-stakes arrangement that cannot fail",
     "when_hint": "Both parties are at the table — or about to be — and the window for a deal is closing fast",
     "why": "The alternative to agreement is violence, and the people paying for this negotiation cannot afford what comes next",
     "where_hint": "A neutral space, or one side's territory if trust is already broken — a meeting room, a restaurant, a faction hall",
     "story_frame": "This is a social story about competing interests, what each side is willing to give up, and the fine art of making both parties feel like they won something — themes of diplomacy, leverage, and the thin line between a deal and a disaster.",
     "keywords": "negotiation,negotiate,broker,ceasefire,agreement,deal,mediation,diplomacy",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "You used force at the table. The deal got done — maybe — but both factions now know you're muscle, not a mediator. Negotiation jobs dry up. Combat jobs start appearing in their place."},
    {"slug": "first-contact", "display_name": "First Contact",
     "who": "A newly arrived people, scout group, refugee pocket, envoy, or community recycled into the Tower from somewhere that has never seen it",
     "what": "Prevent panic, establish communication, teach the basics of the Tower, protect them from exploitation, and learn what they need before factions close in",
     "when_hint": "The first hours matter — fear, rumor, TNN coverage, or faction curiosity can turn confusion into disaster",
     "why": "They do not understand EC, Kharma, factions, adventurers, the Dome, or why everyone wants to claim their story",
     "where_hint": "A new generated area, rift-replaced street, gate exit, Warrens pocket, shelter, or social venue if contact has already moved somewhere safe",
     "story_frame": "This is a first-contact story about culture shock, protection, language, and the responsibility of being the first people to explain the Tower to someone who never asked to arrive — themes of empathy, fear, teaching, and exploitation.",
     "keywords": "first contact,tower contact,new arrivals,new race,unknown people,refugees,recycled world",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "You turned first contact into violence. The new arrivals learn fear before trust, and every faction now frames the party as part of the threat."},
    {"slug": "exploration", "display_name": "Exploration",
     "who": "A faction, Warden contact, map office, scholar, survivor group, or neighborhood that needs an area understood before anyone else walks into it",
     "what": "Map, survey, mark gates/exits, verify stability, recover signs of what was lost, and report what the Tower replaced it with",
     "when_hint": "A rift collapse, sewer shift, gate opening, forgotten area, or newly generated district feature has made old maps unreliable",
     "why": "The Tower's recycling function has changed the city; the old place may now be historical, replaced, or unsafe for normal mission targeting",
     "where_hint": "Warrens sectors, shifted sewers, gate mouths, forgotten areas, rift-collapsed replacement zones, and newly generated places from the area system",
     "story_frame": "This is an exploration story about a city that rewrites itself, the people trying to map the rewrite, and what happens when the new terrain looks back — themes of curiosity, danger, memory, and survival.",
     "keywords": "exploration,explore,map,survey,unmapped,sealed,unknown,venture,warrens,sewer,gate,rift collapse,replaced",
     "combat_posture": "RISKY",
     "combat_rep_cost": "You made enough noise that whatever was in there knows someone found it. The area is now alert. Future exploration jobs into unmapped zones come with a warning attached to your name."},
    {"slug": "discovery", "display_name": "Discovery",
     "who": "Someone who found something they don't fully understand — a faction, local, scholar, survivor, or terrified witness who needs it identified before people panic",
     "what": "Identify, contain, test, transport, decide custody, and understand the implication of an object, anomaly, signal, biology, memory, machine, or impossible material",
     "when_hint": "The discovery is fresh — before anyone else hears about it, before the faction that would claim it arrives",
     "why": "The finder lacks the expertise, nerve, containment tools, or political protection to handle it alone",
     "where_hint": "Where the find was made — a shop backroom, construction site, cracked-open vault, replacement zone, generated area, lab, shrine, or sewer pocket",
     "story_frame": "This is a discovery story about something that should not exist yet does, the factions racing to name or own it, and whether the truth should be preserved, hidden, returned, or destroyed — themes of knowledge, custody, wonder, and public risk.",
     "keywords": "discovery,discover,found,anomaly,phenomenon,artifact,unknown,identify,contain,signal,specimen",
     "combat_posture": "RISKY",
     "combat_rep_cost": "You were loud enough that word got out something was found. Now everyone wants to know what it was. The finder is compromised. Quiet discovery work stops coming your way."},
    {"slug": "defense", "display_name": "Defense",
     "who": "A faction, merchant, or community that cannot abandon a position — and needs fighters to hold it",
     "what": "Hold a location against incoming threat — a building, a district boundary, a safe house, a route — and keep it standing when the attack ends",
     "when_hint": "The attack is expected and coming — the question is when, not if",
     "why": "The location cannot be evacuated, abandoned, or surrendered — something or someone inside is worth dying for",
     "where_hint": "The site itself — a building with fortifiable entries, a narrow street, a roof, a room with one door",
     "story_frame": "This is a siege story about a position that must not fall, a force coming to take it, and defenders who have to be smarter than the numbers — themes of sacrifice, fortitude, and what it means to hold the line.",
     "keywords": "defense,defend,hold,protect location,siege,fortify,stand",
     "combat_posture": "EXPECTED",
     "combat_rep_cost": ""},
    {"slug": "puzzle", "display_name": "Puzzle",
     "who": "Someone who needs a problem solved that can't be answered with a sword — a scholar, an official, a faction with a locked mechanism",
     "what": "Decode a cipher, bypass an arcane lock, reconstruct a broken sequence, or solve a logical trap that stands between the party and the objective",
     "when_hint": "Usually long-standing, not artificially urgent — the party may take the time they need, but the world keeps turning while they work",
     "why": "The answer exists but is hidden behind fair clues, research, symbols, history, art, faith, language, or mechanism logic — no cheap gotcha wording",
     "where_hint": "A specific puzzle source — ancient ruin, sealed shrine, locked mechanism, archive, public mural, scattered graffiti sequence, or hard-to-read art piece",
     "story_frame": "This is a puzzle story about a hard problem that scholars, patrons, or factions cannot crack alone, research that takes time, and the prestige of solving what has resisted everyone else — themes of patience, recognition, buried truths, and the satisfaction of a fair answer.",
     "keywords": "puzzle,cipher,decode,lock,mechanism,arcane,logic,solve,shrine,graffiti,mural,sequence,art",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "Smashing through the mechanism costs extra time and voids the elegant solution. The patron pays less. The mechanism's secrets may be lost. Puzzle-based contracts stop coming — you're flagged as 'breaks things'."},
    {"slug": "gathering", "display_name": "Gathering",
     "who": "A faction, a merchant, or a researcher who needs materials, information, or witnesses — and can't collect them alone",
     "what": "Acquire a specific set of items, testimonies, ingredients, or data points from multiple scattered sources and bring them back intact",
     "when_hint": "The components are available now — but they won't be for long; sources are moving, drying up, or being claimed by others",
     "why": "The required items are spread across dangerous or contested territory; collecting them all requires persistence and protection",
     "where_hint": "Multiple locations across the city — markets, faction holdings, independent contacts, locations only the party can access",
     "story_frame": "This is a logistics story about what it takes to get all the pieces in one place, who doesn't want that to happen, and the complications that emerge between the first collection and the last — themes of persistence, resource management, and the cost of acquisition.",
     "keywords": "gathering,gather,collect,acquire,harvest,retrieve,materials,components,sources",
     "combat_posture": "RISKY",
     "combat_rep_cost": "You burned a source. One of the contacts you needed won't deal with hired crews anymore — and their network hears about it. Gathering contracts dry up as word spreads you can't be subtle."},
    {"slug": "infiltration", "display_name": "Infiltration",
     "who": "A faction that needs to know what its rivals are planning — or needs to insert something without being detected",
     "what": "Enter a rival faction's operation under false pretense — observe, steal intelligence, plant evidence, or make contact with a hidden asset",
     "when_hint": "A decision is being made or finalized — the intelligence is only valuable if it arrives in time",
     "why": "The faction can't risk exposing its own operatives; deniable outside contractors are safer and more expendable",
     "where_hint": "Inside the rival faction's sphere — their offices, meeting rooms, warehouses, communication channels",
     "story_frame": "This is a spy story about information as a weapon, maintaining cover under pressure, and the paranoia that comes from not knowing who knows what — themes of deception, loyalty, and the cost of getting caught.",
     "keywords": "infiltration,infiltrate,spy,espionage,intelligence,observe,plant,undercover,false identity",
     "combat_posture": "CONSEQUENCE",
     "combat_rep_cost": "Your cover is blown. The job might still get done but everyone in that faction now has your face. You lose the quiet option — and every future infiltration job costs more, because the veil is thinner."},
    {"slug": "strange-occurrences", "display_name": "Strange Occurrences",
     "who": "A witness, a grieving faction contact, or a terrified community reporting something the Wardens refuse to log: a dead person is walking around again — and it isn't right",
     "what": "Track and deal with a dead NPC who has returned — either as a doppelganger wearing their face, or as an undead form still carrying their memories. The return was not a legitimate resurrection.",
     "when_hint": "Sightings started recently — the entity is newly active, still finding its footing, and has not yet gone fully dark",
     "why": "The Wardens don't believe the reports, or do and are covering it up. Someone who knew the original needs it handled quietly before it does more damage",
     "where_hint": "The returned entity gravitates to places the original person cared about — their faction hall, their home district, someone they loved or wronged",
     "story_frame": "This is a horror-adjacent story about something wearing a familiar face, the grief of people who knew the original, and the question of how much of the person survived the process — themes of identity, loss, the wrongness of return, and who gets to decide what happens to what came back.",
     "keywords": "strange,occurrences,doppelganger,undead,returned,dead,wrong,face,impostor,reanimated",
     "combat_posture": "RISKY",
     "combat_rep_cost": "You drew attention to something the Wardens were pretending didn't exist. Whatever was watching now knows someone is looking. The situation escalates — and you're attached to it."},
]

_templates_initialized = False


def _init_mission_type_templates() -> None:
    """Create mission_type_templates table and seed it if empty."""
    global _templates_initialized
    if _templates_initialized:
        return
    _templates_initialized = True
    try:
        raw_execute("""
            CREATE TABLE IF NOT EXISTS mission_type_templates (
                id INT AUTO_INCREMENT PRIMARY KEY,
                slug VARCHAR(64) UNIQUE NOT NULL,
                display_name VARCHAR(128) NOT NULL,
                who TEXT NOT NULL,
                what TEXT NOT NULL,
                when_hint TEXT NOT NULL,
                why TEXT NOT NULL,
                where_hint TEXT NOT NULL,
                story_frame TEXT NOT NULL,
                keywords VARCHAR(512) DEFAULT '',
                combat_posture VARCHAR(16) DEFAULT 'PERMITTED',
                combat_rep_cost TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Add columns if table already existed without them (migration)
        for col, defn in [
            ("combat_posture", "VARCHAR(16) DEFAULT 'PERMITTED'"),
            ("combat_rep_cost", "TEXT"),
        ]:
            try:
                exists = raw_query("SHOW COLUMNS FROM mission_type_templates LIKE %s", (col,))
                if not exists:
                    raw_execute(f"ALTER TABLE mission_type_templates ADD COLUMN {col} {defn}")
            except Exception:
                pass  # column already exists

        for t in _MISSION_TYPE_TEMPLATES:
            raw_execute(
                "INSERT INTO mission_type_templates "
                "(slug, display_name, who, what, when_hint, why, where_hint, story_frame, keywords, combat_posture, combat_rep_cost) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE "
                "display_name=VALUES(display_name), who=VALUES(who), what=VALUES(what), "
                "when_hint=VALUES(when_hint), why=VALUES(why), where_hint=VALUES(where_hint), "
                "story_frame=VALUES(story_frame), keywords=VALUES(keywords), "
                "combat_posture=VALUES(combat_posture), combat_rep_cost=VALUES(combat_rep_cost)",
                (t["slug"], t["display_name"], t["who"], t["what"],
                 t["when_hint"], t["why"], t["where_hint"], t["story_frame"], t["keywords"],
                 t.get("combat_posture", "PERMITTED"), t.get("combat_rep_cost", "")),
            )
        logger.info(f"📋 Mission type templates synced ({len(_MISSION_TYPE_TEMPLATES)} types)")
    except Exception as e:
        logger.warning(f"mission_type_templates init failed: {e}")


def _load_mission_type_template(slug: str) -> Optional[dict]:
    """Load a narrative template from DB by slug."""
    try:
        rows = raw_query(
            "SELECT * FROM mission_type_templates WHERE slug = %s LIMIT 1", (slug,)
        )
        return rows[0] if rows else None
    except Exception:
        return None


def _match_template_slug(mission_type_string: str) -> str:
    """Map a mission type name to the nearest template slug."""
    s = mission_type_string.lower().strip()
    checks = [
        # Exact new type names first
        ("strange-occurrences", ["strange occurrences", "strange occurrence", "doppelganger", "undead return"]),
        ("battle",        ["battle"]),
        ("ambush",        ["ambush"]),
        ("negotiation",   ["negotiation", "negotiate"]),
        ("first-contact", ["first contact", "tower contact", "new arrivals", "new race", "unknown race"]),
        ("exploration",   ["exploration", "explore"]),
        ("discovery",     ["discovery", "discover"]),
        ("defense",       ["defense", "defence"]),
        ("puzzle",        ["puzzle"]),
        ("gathering",     ["gathering", "gather"]),
        ("infiltration",  ["infiltration", "infiltrate", "espionage", "spy", "undercover"]),
        ("assault",       ["assault", "attack", "storm", "breach", "seize", "capture position"]),
        ("infestation",   ["infestation", "infested", "nest", "swarm", "vermin", "hive"]),
        ("heist",         ["heist", "robbery", "bank job", "vault heist", "museum heist", "score"]),
        # Existing types
        ("rift",          ["rift"]),
        ("epic",          ["epic", "divine", "tower floor", "city-scale"]),
        ("dungeon",       ["dungeon", "delve", "sealed vault", "abandoned structure"]),
        ("assassination", ["assassination", "assassinate", "eliminate"]),
        ("theft",         ["theft", "steal", "break in"]),
        ("rescue",        ["rescue", "captive", "hostage", "extract"]),
        ("sabotage",      ["sabotage", "destroy", "disable"]),
        ("smuggling",     ["smuggl", "contraband", "black market"]),
        ("bounty",        ["bounty", "fugitive", "wanted", "manhunt"]),
        ("delivery",      ["delivery", "courier", "transport", "package"]),
        ("recovery",      ["recovery", "relic retrieval", "artifact", "relic recover"]),
        ("political",     ["political", "blackmail", "council", "election"]),
        ("protection",    ["protection detail", "bodyguard", "protection"]),
        ("inter-guild",   ["inter-guild", "guild conflict", "mediate"]),
        ("investigation", ["investigation", "investigate", "missing person", "corruption", "unexplained"]),
        ("escort",        ["escort", "convoy"]),
        ("patrol",        ["patrol", "district sweep", "warden-adjacent"]),
        ("neighbourhood", ["neighbourhood", "neighborhood", "local", "street-level", "debt collection"]),
    ]
    for slug, keywords in checks:
        if any(kw in s for kw in keywords):
            return slug
    return "neighbourhood"


_POSTURE_RULES = {
    "EXPECTED": (
        "COMBAT POSTURE — EXPECTED: Violence is the point. "
        "This is a combat job. Terrain, tactics, and force of arms are the primary tools. "
        "Make the fight feel earned — describe the ground, the odds, the moment it tips."
    ),
    "PERMITTED": (
        "COMBAT POSTURE — PERMITTED: Combat is acceptable but not required. "
        "Skills and finesse are preferred. Force gets the job done with no reputation cost. "
        "Write the posting so both paths feel viable."
    ),
    "RISKY": (
        "COMBAT POSTURE — RISKY: Violence carries a reputation cost. "
        "Going loud gets the job done but word gets around. "
        "The posting should make clear that subtlety pays better — hint at what discretion is worth."
    ),
    "CONSEQUENCE": (
        "COMBAT POSTURE — CONSEQUENCE: Violence is a last resort that changes the story. "
        "The primary path is non-combat. Make the quiet approach obvious and rewarding. "
        "If violence happens anyway — it works, but the named reputation cost follows."
    ),
}


def _build_template_block(mission_type_string: str) -> str:
    """Return a narrative framework + combat posture block for injection into a mission prompt."""
    _init_mission_type_templates()
    slug = _match_template_slug(mission_type_string)
    tmpl = _load_mission_type_template(slug)
    if not tmpl:
        return ""

    posture = (tmpl.get("combat_posture") or "PERMITTED").upper()
    rep_cost = tmpl.get("combat_rep_cost") or ""
    posture_line = _POSTURE_RULES.get(posture, _POSTURE_RULES["PERMITTED"])
    if rep_cost:
        posture_line += f"\n  REP COST IF VIOLENT: {rep_cost}"

    return (
        f"\nNARRATIVE FRAMEWORK — use this as a skeleton, invent all the specifics yourself:\n"
        f"  Who:   {tmpl['who']}\n"
        f"  What:  {tmpl['what']}\n"
        f"  When:  {tmpl['when_hint']}\n"
        f"  Why:   {tmpl['why']}\n"
        f"  Where: {tmpl['where_hint']}\n"
        f"  Story: {tmpl['story_frame']}\n\n"
        f"{posture_line}"
    )


# ---------------------------------------------------------------------------
# Dynamic mission type generation (runs daily)
# ---------------------------------------------------------------------------

def _load_generated_mission_types() -> List[str]:
    """Load AI-generated mission types from database."""
    try:
        rows = raw_query(
            "SELECT state_value FROM global_state WHERE state_key = 'generated_mission_types'"
        )
        if rows and rows[0].get("state_value"):
            data = rows[0]["state_value"]
            if isinstance(data, str):
                data = json.loads(data)
            return data.get("types", [])
        return []
    except Exception:
        return []


def _save_generated_mission_types(types: List[str], generated_date: str) -> None:
    """Save AI-generated mission types to database."""
    try:
        data = json.dumps({"generated_date": generated_date, "types": types})
        existing = raw_query(
            "SELECT id FROM global_state WHERE state_key = 'generated_mission_types'"
        )
        if existing:
            raw_execute(
                "UPDATE global_state SET state_value = %s WHERE state_key = 'generated_mission_types'",
                (data,)
            )
        else:
            db.insert("global_state", {
                "state_key": "generated_mission_types",
                "state_value": data
            })
    except Exception:
        pass


def _needs_new_mission_types() -> bool:
    """Returns True if types are missing or were generated on a previous UTC day."""
    try:
        rows = raw_query(
            "SELECT state_value FROM global_state WHERE state_key = 'generated_mission_types'"
        )
        if not rows or not rows[0].get("state_value"):
            return True
        data = rows[0]["state_value"]
        if isinstance(data, str):
            data = json.loads(data)
        last = data.get("generated_date", "")
        return last != datetime.utcnow().strftime("%Y-%m-%d")
    except Exception:
        return True


async def refresh_mission_types_if_needed() -> None:
    """Called at bot startup and daily. Generates 10 new mission type strings if stale."""
    import logging
    logger = logging.getLogger(__name__)

    if not _needs_new_mission_types():
        return

    prompt = f"""{_LORE}

---
You are expanding the Undercity mission board's contract variety.
Generate exactly 10 new, specific mission type descriptions for the board.

These are SEEDS used to prompt an AI to write full mission posts — so each entry
should be a short, evocative description of a JOB TYPE, not a full mission.

RULES:
- Each entry must be 1-2 sentences describing the kind of contract
- Must be grounded in the Undercity setting (factions, districts, economy)
- CRITICAL — NO RIFT MISSIONS: Do NOT generate any Rift-related mission types. No Rift clearance, no Rift investigation, no Rift containment, no "anomaly" that is secretly a Rift. Rifts are handled by a separate system and are RARE events. If any entry mentions Rifts, you have FAILED.
- Must NOT repeat the common types (local jobs, patrol, escort, investigation, inter-guild, dungeon, high-stakes, epic)
- Should feel specific and fresh — think about what's happening in the city RIGHT NOW
- Good mission ideas: faction espionage, debt collection, missing persons, relic retrieval, political blackmail, guild rivalry, smuggling jobs, protection contracts, bounty hunting, sabotage, courier work, arena challenges, divine contract fulfillment, merchant disputes
- Vary tone: some gritty street-level, some political, some supernatural (but NOT Rifts), some economic
- No numbering, no bullet points, no preamble. Output exactly 10 lines, one per entry.
- If your output contains anything other than 10 plain-text lines, you have failed."""

    text = await _generate(prompt)
    if not text:
        logger.warning("mission_board: daily mission type generation failed")
        return

    new_types = [l.strip() for l in text.splitlines() if l.strip()][:10]
    if not new_types:
        return

    today = datetime.utcnow().strftime("%Y-%m-%d")
    _save_generated_mission_types(new_types, today)
    logger.info(f"📋 Generated {len(new_types)} new mission types for {today}")


def _build_npc_context() -> str:
    """Pull active NPCs from DB with rich detail — motivation, hidden allegiances, and role text.

    Always seeds one NPC from Wizards Tower and one from Brother Thane's Cult so those
    factions surface regularly in mission generation even though their rosters are smaller.
    """
    try:
        # Seed slots: 1 Wizards Tower, 1 Brother Thane's Cult, 6 random from the rest
        seeded = raw_query(
            "SELECT name, faction, role, location, status, data_json FROM npcs "
            "WHERE status NOT IN ('dead', 'missing', 'removed') "
            "AND faction IN ('Wizards Tower', \"Brother Thane's Cult\") "
            "ORDER BY RAND() LIMIT 2"
        ) or []
        seeded_names = tuple(r["name"] for r in seeded) or ("__none__",)
        placeholders = ",".join(["%s"] * len(seeded_names))
        rest = raw_query(
            f"SELECT name, faction, role, location, status, data_json FROM npcs "
            f"WHERE status NOT IN ('dead', 'missing', 'removed') "
            f"AND name NOT IN ({placeholders}) "
            f"ORDER BY RAND() LIMIT 6",
            seeded_names,
        ) or []
        rows = seeded + rest
        if not rows:
            return ""
        lines = ["ACTIVE NPCS — pick ONE as contact or antagonist. Give them the role description below as their voice:"]
        for r in rows:
            dj = {}
            if r.get("data_json"):
                try:
                    dj = json.loads(r["data_json"]) if isinstance(r["data_json"], str) else r["data_json"]
                except Exception:
                    dj = {}
            name    = r["name"]
            faction = r.get("faction") or dj.get("faction", "Independent")
            # Role: prefer data_json (often richer), fall back to top-level column
            role_raw = (dj.get("role") or r.get("role") or "")[:200]
            location = (r.get("location") or dj.get("location") or "")[:120]
            motivation = (dj.get("motivation") or "")[:100]

            # Extract hidden allegiance hints from role text ("secretly X")
            import re as _re
            secret_match = _re.search(r'secret(?:ly)?\s+([^\;\.\,\)]{5,60})', role_raw, _re.IGNORECASE)
            secret_hint = secret_match.group(0).strip() if secret_match else ""

            entry = f"• {name} ({faction})"
            if location:
                entry += f"\n  Location: {location}"
            if role_raw:
                # Trim to the meaningful part — first sentence
                role_short = role_raw.split(".")[0].strip()[:150]
                entry += f"\n  Role: {role_short}"
            if secret_hint:
                entry += f"\n  Hidden: {secret_hint}"
            if motivation:
                entry += f"\n  Wants: {motivation}"
            lines.append(entry)
        return "\n".join(lines)
    except Exception:
        return ""


def _load_strange_npc() -> str:
    """Pull a doppelganger or undead NPC from DB for Strange Occurrences missions."""
    try:
        rows = raw_query(
            "SELECT name, faction, role, location FROM npcs "
            "WHERE status IN ('doppelganger', 'undead', 'returned') "
            "ORDER BY RAND() LIMIT 1"
        ) or []
        if rows:
            r = rows[0]
            return (
                f"\nSTRANGE OCCURRENCES SUBJECT — this NPC has returned in altered form:\n"
                f"• {r['name']} — {r.get('role','')} ({r.get('faction','')}) — last known location: {r.get('location','unknown')}\n"
                f"Build the mission around THIS specific NPC. They are the anomaly."
            )
    except Exception:
        pass
    # Fallback: pick any dead NPC
    try:
        rows = raw_query(
            "SELECT name, faction, role, location FROM npcs "
            "WHERE status = 'dead' ORDER BY RAND() LIMIT 1"
        ) or []
        if rows:
            r = rows[0]
            return (
                f"\nSTRANGE OCCURRENCES SUBJECT — this NPC was confirmed dead but has been sighted:\n"
                f"• {r['name']} — {r.get('role','')} ({r.get('faction','')}) — last known location: {r.get('location','unknown')}\n"
                f"Build the mission around THIS specific NPC."
            )
    except Exception:
        pass
    return ""


def _load_area_context_block() -> str:
    """Pull 1-2 random district profiles from DB and format as mission setting lore."""
    try:
        from src.area_generator import get_all_district_names, get_area_profile
        districts = get_all_district_names()
        if not districts:
            return ""
        sampled = random.sample(districts, min(2, len(districts)))
        lines = ["\nKNOWN AREA PROFILES (use these to ground your mission's setting):"]
        for dist in sampled:
            p = get_area_profile(dist)
            if not p:
                continue
            atm = p.get("atmosphere", "")[:200]
            threats = p.get("active_threats", [])[:2]
            hooks = p.get("dm_hooks", [])[:2]
            threat_str = "; ".join(threats)
            hook_str = "; ".join(hooks)
            lines.append(
                f"\n[{dist}]\n"
                f"  Atmosphere: {atm}\n"
                + (f"  Active threats: {threat_str}\n" if threat_str else "")
                + (f"  Open hooks: {hook_str}\n" if hook_str else "")
                + "  If you set your mission here, introduce something NEW — don't repeat what's already listed."
            )
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception:
        return ""


_ROTATION_FACTIONS = [
    "Iron Fang Consortium",
    "Argent Blades",
    "Wardens of Ash",
    "Serpent Choir",
    "Obsidian Lotus",
    "Glass Sigil",
    "Patchwork Saints",
    "Adventurers Guild",
    "Guild of Ashen Scrolls",
    "Tower Authority / FTA",
    "Wizards Tower",
]


def _pick_rotation_faction(recent_missions: List[dict]) -> str:
    """
    Pick which faction should post the next autonomous mission.

    Counts faction appearances in the last 30 missions, excludes the two most
    recent posters, then picks randomly from the bottom third by count.
    This guarantees rotation without being perfectly round-robin.
    """
    recent_factions = []
    for m in recent_missions[-30:]:
        f = (m.get("faction") or "").strip()
        if f in _ROTATION_FACTIONS:
            recent_factions.append(f)

    counts = {f: 0 for f in _ROTATION_FACTIONS}
    for f in recent_factions:
        counts[f] += 1

    # Never repeat the last 2 factions immediately
    last_two = set(recent_factions[-2:]) if len(recent_factions) >= 2 else set()
    candidates = [(f, c) for f, c in counts.items() if f not in last_two]
    if not candidates:
        candidates = list(counts.items())

    # Sort by count ascending; pick randomly from the bottom third
    candidates.sort(key=lambda x: x[1])
    bottom_n = max(1, len(candidates) // 3)
    return random.choice(candidates[:bottom_n])[0]


def _build_mission_prompt(recent_missions: List[dict]) -> str:
    from src.faction_reputation import rep_summary_block, is_hostile
    # Prefer completed standalone pipelines. Unbuilt/generated types are rare.
    all_types = _weighted_mission_types()
    mission_type = random.choice(all_types)

    # Rotation — pick the faction explicitly so the LLM can't default to Serpent Choir
    rotation_faction = _pick_rotation_faction(recent_missions)

    recent_block = ""
    if recent_missions:
        summaries = [m.get("title", "unknown") + " — " + m.get("faction", "") for m in recent_missions[-5:]]
        recent_block = "\nRECENT MISSIONS POSTED (avoid repeating these):\n" + "\n".join(summaries)

    rep_block = "\n" + rep_summary_block()
    npc_block = "\n" + _build_npc_context()
    template_block = _build_template_block(mission_type)
    area_block = _load_area_context_block()

    # Strange Occurrences: inject a doppelganger/undead NPC from the DB
    strange_block = ""
    if mission_type == "Strange Occurrences":
        strange_block = _load_strange_npc()

    return f"""{_LORE}
{rep_block}
{npc_block}
{area_block}
{recent_block}
{strange_block}

---
You are the Undercity mission board. Generate ONE new mission contract posting.

SPONSORING FACTION FOR THIS MISSION: {rotation_faction}
This mission MUST be posted by {rotation_faction}. Use a named NPC from that faction as the contact.
Do not substitute a different faction — the board is balancing its posting rotation.
Exception: if the mission type is Heist, the true sponsor may be obscured but {rotation_faction} is still the posting entity.

REQUIRED FORMAT — output exactly this structure, nothing else:

**[FACTION NAME] — MISSION TITLE**
*Type: {mission_type} | Tier: [difficulty] | Expires: TBD | Reward: [X EC + any extras]*
*Opposes: [faction name if this mission works AGAINST another faction, or "None"]*

CRITICAL: Type must be ONE SHORT LABEL — e.g. "Recovery", "Dungeon Delve", "Investigation", "Escort".
NEVER write a sentence or description in the Type field. One to three words maximum.

Public Post: [1-2 sentences for players. Name the faction, objective, specific place, and known contact.
Do NOT include sensory read-aloud, hidden stakes, secret motives, twists, clues, solution steps, answer keys, puzzle mechanics, or "what really happened" here.
Bulletins are surface-level public contract notices only.]

GM Notes: [2-4 short private notes for the module builder only:
- sensory anchor for the first scene
- personal stakes if unresolved
- one odd clue or contradiction
- what the contact is hiding, if any
- for Puzzle missions, only note the public-facing puzzle type/source; never include the solution, answer key, solve path, or hidden truth in the bulletin]

*Contact: [named NPC from the list above], [their specific location]*

═══ TITLE RULES (mandatory) ═══
- Maximum 5 words. Must name the specific THING at stake: a person, object, place, action.
- GOOD: "Dust Market Strangler", "Warden's Forge Missing Three", "Bones in the Clockwork Spire"
- BANNED endings: Reckoning, Unraveling, Corruption, Awakening, Legacy, Revelation, Convergence, Resonance, Shadows, Darkness — too abstract
- Never "The" + abstract noun

═══ PROSE RULES (mandatory) ═══
Write like a noir dispatch from inside the city. Every word earns its place.
- Name SPECIFIC streets, rooms, people, objects. Never "a warehouse" or "some guards."
- SENSORY BEAT IS MANDATORY in GM Notes, not in the Public Post. Examples:
    GOOD: "The clinic still smells of iodine — someone left the instruments soaking."
    GOOD: "Somewhere in the Forge district, a door has been nailed shut from the inside."
    GOOD: "The counting room floor is sticky. No one will say with what."
    BAD: "The ominous shadows of the ancient tunnels..." (no tunnels exist — this is a CITY)
    BAD: "A dark presence fills the air..." (banned — this is not fantasy flavour text)
- CONTACT notes can include personality in GM Notes, but the Contact field should stay public and practical.
    GOOD: "— doesn't make eye contact when she mentions the Forge"
    GOOD: "— has been asking questions she doesn't want answered"
    GOOD: "— hasn't slept in four days and it shows"

═══ RULES ═══
- Mission type is already set to: {mission_type}{template_block}
- Difficulty label (use exactly one): local, patrol, standard, investigation, rift, dungeon, major, inter-guild, high-stakes, epic, divine, tower
- If Mission type is Heist, the posting faction must be a shady sponsor such as Obsidian Lotus, Iron Fang Consortium, Glass Sigil, Argent Blades, Serpent Choir, or Brother Thane's Cult.
- Rift missions ONLY in the Warrens or Outer Wall — never elsewhere
- Contact must be one of the listed NPCs — do not invent new faction leaders
- Rewards within hard limits. Never over 1200 Kharma.
- Mission board bulletins must stay brief and surface-level. Detailed mechanics, map plans, puzzle answers, hidden truths, and full module content belong only in generated modules after claim.
- No preamble. No sign-off. Output the mission post only. Nothing else."""


# ---------------------------------------------------------------------------
# Resolution generation
# ---------------------------------------------------------------------------

def _build_resolution_prompt(mission: dict) -> str:
    title = mission.get("title", "Unknown Contract")
    faction = mission.get("faction", "Unknown Faction")
    body = mission.get("body", "")
    tier = mission.get("tier", "standard")

    return f"""{_LORE}

---
A mission contract has expired without being completed by adventurers.
Generate a SHORT resolution notice (2-4 lines) explaining what happened as a result.

The expired mission was:
Title: {title}
Faction: {faction}
Tier: {tier}
Details: {body}

RULES:
- Write entirely in-character as a notice board update or Oracle observation.
- Use Discord markdown. Include a ❌ or 📋 emoji at the start.
- The outcome should feel like a natural consequence — the faction dealt with it another way,
  the situation worsened, someone else handled it, or the window simply closed.
- 2 to 4 lines maximum.
- No preamble, no sign-off. Output only the resolution post."""


# ---------------------------------------------------------------------------
# Hostile mission generator (Detested / Hated factions)
# ---------------------------------------------------------------------------

_HOSTILE_TYPES = [
    "an ambush on adventurers operating in their territory",
    "a bounty posted on a specific named adventurer",
    "sabotage of adventurer guild resources or safe houses",
    "a disinformation campaign framing adventurers for a crime",
    "hired muscle sent to shake down adventurers for past failures",
    "a trap disguised as a legitimate contract",
    "a public smear notice warning the city against working with these adventurers",
]


def _build_hostile_mission_prompt(faction: str, recent_missions: List[dict]) -> str:
    from src.faction_reputation import get_reputation, TIER_EMOJI
    entry   = get_reputation(faction)
    tier    = entry["tier"]
    emoji   = TIER_EMOJI.get(tier, "")
    hostile_type = random.choice(_HOSTILE_TYPES)

    recent_block = ""
    if recent_missions:
        summaries = [m.get("title", "") for m in recent_missions[-3:]]
        recent_block = "\nRECENT BOARD POSTS (avoid repeating):\n" + "\n".join(summaries)

    return f"""{_LORE}
{recent_block}

---
The faction "{faction}" is currently at {emoji} {tier} standing with the adventurers.
They are an ENEMY. Generate ONE hostile notice from them directed AT the adventurers.

Hostile action type: {hostile_type}

REQUIRED FORMAT — output exactly this, nothing else:

⚠️ **[{faction.upper()}] — HOSTILE NOTICE TITLE**
*Tier: [tier label] | Threat Level: [low/medium/high/critical]*

[2-3 sentences. Specific threat, named NPC issuing it, what the faction intends to do. Menacing but grounded.]

*Issued by: [named NPC], [{faction}]*

RULES:
- Tone is threatening, not a job offer
- Use exactly one tier label: local, patrol, standard, investigation, major, high-stakes, epic
- Invent a named NPC issuing the threat
- No preamble, no sign-off. Output the hostile notice only.
- If your response contains anything other than the notice, you have failed."""


async def post_hostile_mission(channel, faction: str) -> None:
    """Post a hostile notice from a Detested/Hated faction."""
    import logging
    logger = logging.getLogger(__name__)

    recent  = _load_missions()
    prompt  = _build_hostile_mission_prompt(faction, recent)
    text    = await _generate(prompt)
    if not text:
        logger.warning(f"⚠️ Hostile mission generation failed for {faction}")
        return

    mission = _parse_mission(text)
    mission["hostile_faction"] = faction
    mission["is_hostile"]      = True

    expires_dt = _expiry_for_tier(mission["tier"])
    mission["expires_at"] = expires_dt.isoformat()
    days_left = (expires_dt - datetime.utcnow()).days

    # Hostile missions — use same clean embed structure, red color
    embed = _build_mission_embed(mission, 0xCC0000, "⚠️ Hostile", days_left)
    embed.set_footer(
        text=f"⚠️ HOSTILE NOTICE  •  {faction}  •  Active for {days_left} day{'s' if days_left != 1 else ''}"
    )
    msg = await channel.send(embed=embed)
    mission["message_id"] = msg.id
    _add_mission(mission)
    logger.info(f"⚠️ Hostile notice posted from {faction}: {mission['title']}")


# ---------------------------------------------------------------------------
# Mission generation (uses KimiAgent)
# ---------------------------------------------------------------------------

async def _generate(prompt: str) -> Optional[str]:
    """
    Generate mission content using KimiAgent.

    REFACTORED: Now uses src.agents.generate_mission_text helper.
    """
    from src.agents import generate_mission_text
    import logging, time
    _log = logging.getLogger(__name__)

    _log.info(f"📋 [GENERATE] Sending {len(prompt.split())}w prompt to LLM ...")
    _t0 = time.monotonic()
    try:
        text = await generate_mission_text(prompt, temperature=0.9)
        _elapsed = time.monotonic() - _t0
        if text:
            _log.info(
                f"📋 [GENERATE] ✓ {len(text.split())}w / {len(text)} chars received "
                f"in {_elapsed:.1f}s | preview: {text[:100].replace(chr(10),' ')!r}"
            )
        else:
            _log.warning(f"📋 [GENERATE] LLM returned empty/None after {_elapsed:.1f}s")
        return text
    except Exception as e:
        _log.error(f"📋 [GENERATE] Error after {time.monotonic()-_t0:.1f}s: {e!r}")
        return None


# ---------------------------------------------------------------------------
# Type label normalisation
# ---------------------------------------------------------------------------

# Known short labels — what we want displayed
_TYPE_LABELS = {
    "neighbourhood job": "Neighbourhood Job",
    "neighbourhood": "Neighbourhood Job",
    "patrol": "Patrol",
    "patrol contract": "Patrol",
    "escort": "Escort",
    "investigation": "Investigation",
    "inter-guild": "Inter-Guild Conflict",
    "inter guild": "Inter-Guild Conflict",
    "high-stakes": "High-Stakes Contract",
    "high stakes": "High-Stakes Contract",
    "dungeon": "Dungeon Delve",
    "dungeon delve": "Dungeon Delve",
    "rift": "Rift Clearance",
    "rift clearance": "Rift Clearance",
    "epic": "Epic Mission",
    "divine": "Epic Mission",
    "theft": "Theft / Heist",
    "heist": "Heist",
    "robbery": "Heist",
    "bank job": "Heist",
    "vault heist": "Heist",
    "museum heist": "Heist",
    "assassination": "Assassination",
    "assault": "Assault",
    "attack": "Assault",
    "infestation": "Infestation",
    "infested": "Infestation",
    "rescue": "Rescue Operation",
    "delivery": "Courier / Delivery",
    "courier": "Courier / Delivery",
    "bounty": "Bounty Hunt",
    "bounty hunt": "Bounty Hunt",
    "espionage": "Faction Espionage",
    "sabotage": "Sabotage",
    "smuggling": "Smuggling Run",
    "political": "Political Intrigue",
    "recovery": "Recovery",
    "relic recovery": "Recovery",
    "artifact recovery": "Recovery",
    "evidence recovery": "Recovery",
    "data recovery": "Recovery",
    "record recovery": "Recovery",
    "memory recovery": "Recovery",
    "identity recovery": "Recovery",
    "missing pet": "Recovery",
    "lost pet": "Recovery",
    "protection": "Protection Detail",
    "battle": "Battle",
    "ambush": "Ambush",
    "negotiation": "Negotiation",
    "first contact": "First Contact",
    "tower contact": "First Contact",
    "exploration": "Exploration",
    "discovery": "Discovery",
    "defense": "Defense",
    "defence": "Defense",
    "puzzle": "Puzzle",
    "gathering": "Gathering",
    "infiltration": "Infiltration",
    "strange occurrences": "Strange Occurrences",
    "strange occurrence": "Strange Occurrences",
    "strange": "Strange Occurrences",
    "returned dead": "Strange Occurrences",
    "revenant": "Strange Occurrences",
    "ghost": "Strange Occurrences",
    "doppelganger": "Strange Occurrences",
    "doppleganger": "Strange Occurrences",
    "standard": "Contract",
    "contract": "Contract",
    "social": "Diplomatic",
    "combat": "Combat Contract",
}

# Keyword fragments that identify type when model writes a description
_TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("dungeon", "Dungeon Delve"),
    ("missing pet", "Recovery"),
    ("lost pet", "Recovery"),
    ("misdelivered", "Recovery"),
    ("misplaced cargo", "Recovery"),
    ("data recovery", "Recovery"),
    ("record recovery", "Recovery"),
    ("memory recovery", "Recovery"),
    ("identity recovery", "Recovery"),
    ("relic", "Recovery"),
    ("cursed", "Recovery"),
    ("artifact", "Recovery"),
    ("retrieve", "Recovery"),
    ("smuggl", "Smuggling Run"),
    ("contraband", "Smuggling Run"),
    ("assassin", "Assassination"),
    ("eliminate", "Assassination"),
    ("infiltrat", "Infiltration"),
    ("espionage", "Faction Espionage"),
    ("sabotage", "Sabotage"),
    ("rescue", "Rescue Operation"),
    ("hostage", "Rescue Operation"),
    ("captive", "Rescue Operation"),
    ("negotiat", "Negotiation"),
    ("diplomat", "Negotiation"),
    ("first contact", "First Contact"),
    ("tower contact", "First Contact"),
    ("new arrivals", "First Contact"),
    ("unknown race", "First Contact"),
    ("strange occurrence", "Strange Occurrences"),
    ("returned dead", "Strange Occurrences"),
    ("revenant", "Strange Occurrences"),
    ("doppelganger", "Strange Occurrences"),
    ("doppleganger", "Strange Occurrences"),
    ("impostor", "Strange Occurrences"),
    ("imposter", "Strange Occurrences"),
    ("haunting", "Strange Occurrences"),
    ("graveyard", "Strange Occurrences"),
    ("coroner", "Strange Occurrences"),
    ("morgue", "Strange Occurrences"),
    ("heist", "Heist"),
    ("robbery", "Heist"),
    ("bank job", "Heist"),
    ("vault heist", "Heist"),
    ("museum heist", "Heist"),
    ("steal", "Theft / Heist"),
    ("bounty", "Bounty Hunt"),
    ("fugitive", "Bounty Hunt"),
    ("escort", "Escort"),
    ("convoy", "Escort"),
    ("courier", "Courier / Delivery"),
    ("deliver", "Courier / Delivery"),
    ("patrol", "Patrol"),
    ("investigation", "Investigation"),
    ("mystery", "Investigation"),
    ("disappear", "Investigation"),
    ("rift", "Rift Clearance"),
    ("ambush", "Ambush"),
    ("defense", "Defense"),
    ("defend", "Defense"),
    ("battle", "Battle"),
    ("combat", "Battle"),
    ("assault", "Assault"),
    ("storm", "Assault"),
    ("breach", "Assault"),
    ("infestation", "Infestation"),
    ("infested", "Infestation"),
    ("swarm", "Infestation"),
    ("exploration", "Exploration"),
    ("survey", "Exploration"),
    ("gathering", "Gathering"),
    ("collect", "Gathering"),
    ("puzzle", "Puzzle"),
    ("protection", "Protection Detail"),
    ("bodyguard", "Protection Detail"),
    ("political", "Political Intrigue"),
    ("strange", "Strange Occurrences"),
]


def _snap_mission_type(raw: str) -> str:
    """
    Take whatever the AI wrote in the Type: field and snap it to a clean short label.
    If the AI wrote a full description sentence, extract the type from keywords.
    """
    if not raw:
        return ""
    # Strip markdown
    raw = re.sub(r'[*_`]', '', raw).strip()

    # Exact/prefix match against known labels first
    key = raw.lower()
    if key in _TYPE_LABELS:
        return _TYPE_LABELS[key]

    # Prefix match (e.g. "Investigation/Mystery" → "Investigation")
    for slug, label in _TYPE_LABELS.items():
        if key.startswith(slug):
            return label

    # Scan keyword fragments before falling back. This catches short phrases like
    # "storm the gate" or "infested cellar", not just long model rambles.
    key_lower = raw.lower()
    for fragment, label in _TYPE_KEYWORDS:
        if fragment in key_lower:
            return label

    # Too long — AI wrote a description. Truncate as a best-effort label.
    if len(raw) > 30:
        # Absolute fallback — truncate to first 3 words as a best-effort label
        words = raw.split()
        return " ".join(words[:3]).rstrip(".,;:").title()

    # Short enough — return title-cased as-is
    return raw.title()


def _public_story_from_text(text: str, max_sentences: int = 2) -> str:
    """
    Return the short player-facing mission pitch.

    Mission generation may include private GM/module-builder notes in the same
    stored body. Those are valuable for module generation but should not leak
    onto the public board.
    """
    if not text:
        return ""

    explicit_public = bool(re.match(r'(?is)^\s*(?:public\s+post|public\s+pitch|posting)\s*:', text))
    clean = re.sub(r'(?im)^\s*(?:public\s+post|public\s+pitch|posting)\s*:\s*', '', text).strip()
    clean = re.split(
        r'(?im)^\s*(?:gm\s+notes?|private\s+notes?|module\s+notes?|backend\s+notes?)\s*:',
        clean,
        maxsplit=1,
    )[0]
    clean = re.sub(r'\s+', ' ', clean).strip()

    sentence_limit = max_sentences if explicit_public else 1
    sentences = re.findall(r'[^.!?]+[.!?]', clean)
    if sentences:
        return " ".join(s.strip() for s in sentences[:sentence_limit]).strip()

    words = clean.split()
    if len(words) > 55:
        return " ".join(words[:55]).rstrip(" ,;:") + "."
    return clean


def _extract_story_contact_and_notes(body: str) -> tuple[str, str, str]:
    """Split the generated post into public pitch, contact line, and private notes."""
    contact = ""
    contact_match = re.search(r'\*?Contact:\s*([^\n]+)', body, re.IGNORECASE)
    if contact_match:
        contact = re.sub(r'[*_]', '', contact_match.group(1)).strip()

    private_notes = ""
    notes_match = re.search(
        r'(?is)(?:\*?\s*)?(?:GM\s+Notes?|Private\s+Notes?|Module\s+Notes?|Backend\s+Notes?)\s*:\s*(.+?)(?=\n\s*\*?Contact:|\Z)',
        body,
    )
    if notes_match:
        private_notes = re.sub(r'[*_]', '', notes_match.group(1)).strip()

    # Story is everything between the header metadata line and the Contact line
    # Strip the metadata line (*Type: ... | Tier: ... | ...*)
    story = re.sub(r'\*[^\n]*Type:[^\n]*\n?', '', body)
    story = re.sub(r'\*[^\n]*Opposes:[^\n]*\n?', '', story, flags=re.IGNORECASE)
    story = re.sub(
        r'(?is)(?:\*?\s*)?(?:GM\s+Notes?|Private\s+Notes?|Module\s+Notes?|Backend\s+Notes?)\s*:.+?(?=\n\s*\*?Contact:|\Z)',
        '',
        story,
    )
    story = re.sub(r'\*?Contact:[^\n]+', '', story, flags=re.IGNORECASE)
    # Strip the bold title line
    story = re.sub(r'\*\*[^\n]+\*\*\n?', '', story)
    # Strip legacy/plain title lines like "Glass Sigil - Codex in the Bone Market"
    story = re.sub(r'^\s*[^\n:]{2,80}\s+(?:-|--|—|–)\s+[^\n:]{2,120}\s*\n?', '', story)
    # Clean up remaining markdown asterisks and extra whitespace
    story = re.sub(r'\*+', '', story)
    story = re.sub(r'\n{3,}', '\n\n', story).strip()

    return _public_story_from_text(story), contact, private_notes


# ---------------------------------------------------------------------------
# Parse generated mission text into structured fields
# ---------------------------------------------------------------------------

def _parse_mission(text: str) -> dict:
    # Extract faction + title from first bold line
    title = "Unknown Contract"
    faction = "Unknown"
    title_match = re.search(r"\*\*(.+?)\*\*", text)
    raw = title_match.group(1).strip() if title_match else ""
    if not raw:
        for line in text.splitlines():
            candidate = re.sub(r'[*_`]', '', line).strip()
            if candidate:
                raw = candidate
                break
    if raw:
        header_match = re.match(r"\s*(.*?)\s+(?:-|--|—|–)\s+(.*?)\s*$", raw)
        if header_match:
            faction = header_match.group(1).strip()
            title = header_match.group(2).strip()
        else:
            title = raw.strip()

    # Extract mission type and snap to a clean short label
    mission_type = ""
    type_match = re.search(r"[Tt]ype:\s*([^\|\n\*]+)", text)
    if type_match:
        mission_type = _snap_mission_type(type_match.group(1).strip().rstrip("|").strip())

    tier = _parse_tier(text)

    # Extract reward and clamp any runaway values
    reward_match = re.search(r"[Rr]eward:\s*([^\n\|*]+)", text)
    reward = reward_match.group(1).strip() if reward_match else "See posting"
    # Sanity-check: replace absurd Kharma values (> 1500) with tier-appropriate cap
    _kharma_hit = re.search(r"(\d[\d,]*)\s*Kharma", reward, re.IGNORECASE)
    if _kharma_hit:
        _kval = int(_kharma_hit.group(1).replace(",", ""))
        _tier_kharma_caps = {
            "local": 0, "patrol": 0,                          # no Kharma on green tiers
            "standard": 40, "escort": 40, "bounty": 40,       # 🟡 optional
            "investigation": 55, "social": 55,                # 🟡 optional
            "dungeon": 55, "rift": 55, "major": 55,           # 🟠
            "combat": 55, "heist": 55,
            "inter-guild": 110, "high-stakes": 110,            # 🔴
            "epic": 285, "divine": 285, "tower": 285,          # 🟣 (scaled at CR19)
        }
        _cap = _tier_kharma_caps.get(tier, 600)
        if _kval > _cap:
            reward = re.sub(
                r"\d[\d,]*\s*Kharma",
                f"{_cap} Kharma",
                reward,
                flags=re.IGNORECASE,
            )
            logger.warning(f"⚠️ Reward clamped: {_kval} Kharma → {_cap} Kharma (tier={tier})")

    # Extract opposing faction
    opposing_faction = ""
    opposes_match = re.search(r"[Oo]pposes:\s*([^\n\|*]+)", text)
    if opposes_match:
        raw_opposes = opposes_match.group(1).strip().strip('*').strip()
        if raw_opposes.lower() not in ("none", "n/a", "", "none."):
            opposing_faction = raw_opposes

    # Strip beat labels the model might echo back ("BEAT 1 — SITUATION:", "HOOK —", etc.)
    clean_text = re.sub(
        r'\bBEAT\s+\d+\s*[—–-]\s*(?:SITUATION|SENSORY ANCHOR|STAKES|HOOK)?[:\s]*',
        '',
        text,
        flags=re.IGNORECASE,
    )
    clean_text = re.sub(r'\bHOOK\s*[—–-]\s*', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()

    # Extract clean story paragraph and contact line for embed display
    public_text, contact, private_notes = _extract_story_contact_and_notes(clean_text)
    if "public post:" not in clean_text.lower() and "public pitch:" not in clean_text.lower():
        contact_name = contact.split(",", 1)[0].split("—", 1)[0].split("-", 1)[0].strip()
        contact_suffix = f" Speak with {contact_name} for public details." if contact_name else ""
        public_text = f"{faction} is seeking a crew for **{title}**.{contact_suffix}"

    return {
        "title": title,
        "faction": faction,
        "type": mission_type,
        "tier": tier,
        "reward": reward,
        "opposing_faction": opposing_faction,
        "body": clean_text,
        "public_text": public_text,
        "story_text": public_text,
        "private_notes": private_notes,
        "contact": contact,          # "NPC Name, location — detail"
        "posted_at": datetime.utcnow().isoformat(),
        "expires_at": _expiry_for_tier(tier).isoformat(),
        "resolved": False,
        "message_id": None,
    }


# ---------------------------------------------------------------------------
# Character memory parser
# ---------------------------------------------------------------------------

def _load_characters() -> List[dict]:
    """Load player characters from MySQL player_characters table."""
    try:
        rows = raw_query(
            "SELECT name, class_name, species, player_name, oracle_notes, profile_json "
            "FROM player_characters ORDER BY name"
        ) or []
        characters = []
        for row in rows:
            pj = row.get("profile_json") or {}
            if isinstance(pj, str):
                try:
                    pj = json.loads(pj)
                except Exception:
                    pj = {}
            char = {**pj}
            char["NAME"] = row["name"]
            char["CLASS"] = row.get("class_name") or char.get("CLASS", "")
            char["SPECIES"] = row.get("species") or char.get("SPECIES", "")
            char["PLAYER"] = row.get("player_name") or char.get("PLAYER", "")
            char["ORACLE NOTES"] = row.get("oracle_notes") or char.get("ORACLE_NOTES", "")
            characters.append(char)
        if characters:
            return characters
    except Exception as e:
        logger.warning(f"_load_characters: DB query failed: {e}")
    return []


def _personal_expiry_for_tier(tier: str) -> datetime:
    tier_key = tier.lower().strip()
    lo, hi = PERSONAL_TIER_EXPIRY.get(tier_key, PERSONAL_DEFAULT_EXPIRY)
    days = random.randint(lo, hi)
    return datetime.utcnow() + timedelta(days=days)


# ---------------------------------------------------------------------------
# Personal mission tracker
# ---------------------------------------------------------------------------

def _load_personal_tracker() -> dict:
    """Load personal mission tracker from database."""
    try:
        rows = raw_query(
            "SELECT state_value FROM global_state WHERE state_key = 'personal_mission_tracker'"
        )
        if rows and rows[0].get("state_value"):
            data = rows[0]["state_value"]
            if isinstance(data, str):
                data = json.loads(data)
            return data
        return {}
    except Exception:
        return {}


def _save_personal_tracker(tracker: dict) -> None:
    """Save personal mission tracker to database."""
    try:
        data = json.dumps(tracker, ensure_ascii=False, default=str)
        existing = raw_query(
            "SELECT id FROM global_state WHERE state_key = 'personal_mission_tracker'"
        )
        if existing:
            raw_execute(
                "UPDATE global_state SET state_value = %s WHERE state_key = 'personal_mission_tracker'",
                (data,)
            )
        else:
            db.insert("global_state", {
                "state_key": "personal_mission_tracker",
                "state_value": data
            })
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Personal mission prompt
# ---------------------------------------------------------------------------

_PERSONAL_MISSION_ANGLES = [
    "something tied to their species or racial history",
    "something tied to their class abilities or specialisation",
    "a personal debt, reputation, or past action catching up with them",
    "a faction reaching out specifically because of their known skills",
    "a rumour about something that would matter deeply to someone like them",
    "an old enemy, rival, or contact from their background resurfacing",
    "an opportunity only someone with their specific capabilities could exploit",
    "a divine or cosmic thread connecting to their soul or legend",
]


def _build_personal_mission_prompt(character: dict, recent_missions: List[dict]) -> str:
    name = character.get("NAME", "Unknown")
    species = character.get("SPECIES", "Unknown")
    char_class = character.get("CLASS", "Unknown")
    alignment = character.get("ALIGNMENT", "Unknown")
    oracle_notes = character.get("ORACLE NOTES", "")
    personality = character.get("PERSONALITY", "")
    organizations = character.get("ORGANIZATIONS", "")
    notable_gear = character.get("NOTABLE GEAR", "")
    currency = character.get("CURRENCY", "")
    angle = random.choice(_PERSONAL_MISSION_ANGLES)
    # Pick a mission type — exclude Strange Occurrences for personal missions
    _personal_types = [t for t in _MISSION_TYPES if t != "Strange Occurrences"]
    personal_type = random.choice(_personal_types)

    recent_block = ""
    personal_past = [m for m in recent_missions
                     if name.lower() in m.get("title", "").lower() + m.get("body", "").lower()]
    if personal_past:
        recent_block = "\nRECENT PERSONAL MISSIONS FOR THIS CHARACTER (do not repeat):\n" + \
                       "\n".join(m.get("title", "") for m in personal_past[-3:])

    return f"""{_LORE}

TARGET CHARACTER:
Name: {name}
Species: {species}
Class: {char_class}
Alignment: {alignment}
Organizations: {organizations}
Notable Gear: {notable_gear}
Currency/Karma: {currency}
Personality: {personality}
Oracle Notes: {oracle_notes}
{recent_block}

---
You are the Undercity mission board. Generate ONE personal mission contract specifically for {name}.
Mission angle: {angle}

REQUIRED FORMAT — output exactly this, nothing else:

**[FACTION NAME] — MISSION TITLE**
*Type: {personal_type} | Tier: [difficulty] | Expires: TBD | Reward: [X EC + any extras]*
*Opposes: [faction name if this mission works AGAINST another faction, or "None"]*

CRITICAL: Type must be ONE SHORT LABEL — e.g. "Recovery", "Dungeon Delve", "Investigation".
NEVER write a sentence in the Type field. One to three words maximum.

[1-2 public sentences. Name {name} as the requested contractor. Include specific NPC contact, location, and clear objective. Do not reveal hidden twists.]

GM Notes: [1-3 private notes for the module builder: why this is personal, what the contact is hiding, and one complication.]

*Contact: [named NPC], [location]*

RULES:
- Mission type is already set to: {personal_type}
- For [difficulty] use exactly one label: local, patrol, standard, investigation, dungeon, major, inter-guild, high-stakes, epic, divine, tower
- Do NOT use difficulty "rift" for personal missions — Rifts are city-wide emergencies, not personal contracts
- Rewards MUST stay within the REWARD HARD LIMITS in the lore block above. Never write Kharma over 1200.
- Weave {name}'s identity, class, species, or history into why they are specifically being asked
- Invent fresh named NPCs, exact EC rewards, precise locations
- Do NOT put {name} in the bold header line — save it for the body text
- No preamble, no sign-off. Output the mission post only.
- If your response contains anything other than the mission post, you have failed."""


async def post_personal_mission(channel, character: dict) -> bool:
    """Generate and post a personal mission for one character.

    Returns True if the mission was posted or skipped for a non-error reason
    (cap reached, etc.), False if generation failed and the caller should retry soon.
    """
    import logging
    logger = logging.getLogger(__name__)

    name = character.get("NAME", "Unknown")

    active = _count_active_personal(name)
    if active >= MAX_ACTIVE_PERSONAL:
        logger.info(f"📌 Personal cap reached for {name} ({active}/{MAX_ACTIVE_PERSONAL}) — skipping")
        return True  # not a failure — use normal long timer

    recent = _load_missions()
    prompt = _build_personal_mission_prompt(character, recent)
    text = await _generate(prompt)

    if not text:
        logger.warning(f"📋 personal mission: generation returned None for {name}")
        return False  # generation failed — caller should retry soon

    mission = _parse_mission(text)
    mission["personal_for"] = name
    expires_dt = _personal_expiry_for_tier(mission["tier"])
    mission["expires_at"] = expires_dt.isoformat()
    days_left = (expires_dt - datetime.utcnow()).days

    # Build color-coded embed based on faction reputation
    from src.faction_reputation import get_faction_color, get_faction_tier_label
    faction = mission.get("faction", "")
    embed_color = get_faction_color(faction) if faction else 0xE6C300
    tier_label = get_faction_tier_label(faction) if faction else "😐 Neutral"

    embed = _build_mission_embed(mission, embed_color, tier_label, days_left,
                                 personal_for=name)

    msg = await channel.send(embed=embed)
    mission["message_id"] = msg.id
    _add_mission(mission)

    # Add ⚔️ reaction as a visible claim button
    try:
        await msg.add_reaction(EMOJI_CLAIM)
    except Exception:
        pass

    tracker = _load_personal_tracker()
    tracker[name] = datetime.utcnow().isoformat()
    _save_personal_tracker(tracker)

    logger.info(f"📋 Personal mission posted for {name}: {mission['title']} ({days_left}d expiry)")
    return True


def next_personal_mission_seconds() -> int:
    """1 to 3 days between personal missions per character."""
    return random.randint(PERSONAL_MISSION_MIN, PERSONAL_MISSION_MAX)


# ---------------------------------------------------------------------------
# Adventurer party system
# ---------------------------------------------------------------------------

def _load_party_list() -> List[str]:
    """Load named parties from MySQL (falls back to adventurer_parties.txt)."""
    try:
        rows = raw_query("SELECT party_name FROM adventurer_parties ORDER BY party_name") or []
        if rows:
            return [r["party_name"] for r in rows]
    except Exception as e:
        logger.warning(f"_load_party_list DB error: {e}")
    return []


def _load_used_parties() -> List[str]:
    """Load used parties list from database."""
    try:
        rows = raw_query(
            "SELECT state_value FROM global_state WHERE state_key = 'used_parties'"
        )
        if rows and rows[0].get("state_value"):
            data = rows[0]["state_value"]
            if isinstance(data, str):
                data = json.loads(data)
            return data if isinstance(data, list) else []
        return []
    except Exception:
        return []


def _save_used_parties(used: List[str]) -> None:
    """Save used parties list to database."""
    try:
        data = json.dumps(used, ensure_ascii=False)
        existing = raw_query(
            "SELECT id FROM global_state WHERE state_key = 'used_parties'"
        )
        if existing:
            raw_execute(
                "UPDATE global_state SET state_value = %s WHERE state_key = 'used_parties'",
                (data,)
            )
        else:
            db.insert("global_state", {
                "state_key": "used_parties",
                "state_value": data
            })
    except Exception:
        pass


async def _get_party_name() -> str:
    """
    Return a party name from the saved list.
    If fewer than 5 unused names remain, ask AI to generate 20 more and append them.
    Cycles through the list without repeating until exhausted, then resets.
    """
    all_parties  = _load_party_list()
    used_parties = _load_used_parties()

    available = [p for p in all_parties if p not in used_parties]

    # Refill via AI if running low
    if len(available) < 5:
        new_names = await _generate_party_names(20)
        if new_names:
            # Insert new names into DB (and file for fallback)
            existing_set = set(all_parties)
            try:
                for name in new_names:
                    if name not in existing_set:
                        raw_execute(
                            "INSERT IGNORE INTO adventurer_parties (party_name) VALUES (%s)", (name,)
                        )
            except Exception as _e:
                logger.warning(f"_get_party_name DB insert error: {_e}")
            # Reset used list so the full expanded list is available
            used_parties = []
            _save_used_parties([])
            all_parties  = _load_party_list()
            available    = [p for p in all_parties if p not in used_parties]

    # If somehow still empty, fall back to a hardcoded name
    if not available:
        return "The Unmarked"

    chosen = random.choice(available)
    used_parties.append(chosen)
    _save_used_parties(used_parties)
    return chosen


async def _generate_party_names(count: int = 20) -> List[str]:
    """Ask the AI to generate fresh adventurer party names."""
    prompt = f"""You are naming adventurer parties for a dark urban fantasy city called the Undercity.
Parties are gritty, professional, mercenary in tone. Names should feel like real guild or company names —
not heroic fantasy stereotypes. Think noir, worn, specific.

Generate exactly {count} unique adventurer party names.
Output ONLY the names, one per line, no numbers, no explanations, no punctuation except what’s part of the name.
If your response contains anything other than the list of names, you have failed."""
    text = await _generate(prompt)
    if not text:
        return []
    names = [l.strip() for l in text.splitlines() if l.strip() and not l.strip()[0].isdigit()]
    return names[:count]


def _build_claim_prompt(mission: dict, party_name: str) -> str:
    title   = mission.get("title",   "Unknown Contract")
    faction = mission.get("faction", "Unknown Faction")
    tier    = mission.get("tier",    "standard")
    body    = mission.get("body",    "")
    # Inject real party profile so the claim notice references actual members/identity
    try:
        from src.party_profiles import profile_summary
        party_block = "\n" + profile_summary(party_name)
    except Exception:
        party_block = f"\nParty: {party_name}"
    return f"""You are the Undercity mission board posting a claim notice.

A mission has just been accepted by an adventurer party.

Mission: {title}
Faction: {faction}
Tier: {tier}
Details: {body}
Claiming party: {party_name}{party_block}

Write a SHORT claim notice (2-3 lines) in the voice of the mission board.
Format:
✅ **CONTRACT CLAIMED — {title}**
*Taken by {party_name}. [1-2 sentences about what the party is known for or what they’re walking into.]*

RULES:
- Stay in-character, gritty, matter-of-fact
- Invent a brief flavour detail about the party (reputation, rumour, one known fact)
- No preamble, no sign-off. Output only the claim notice."""


def _load_recent_news(max_chars: int = 600) -> str:
    """Return a short snippet of recent news facts for injecting into prompts."""
    try:
        rows = raw_query("SELECT facts FROM news_memory ORDER BY id DESC LIMIT 5") or []
        return " | ".join(r.get("facts", "") for r in rows if r.get("facts"))[:max_chars]
    except Exception:
        return ""


def _build_urgent_claim_prompt(mission: dict, party_name: str, news_snippet: str) -> str:
    """Claim notice for missions that sat unclaimed long enough to trigger urgency pickup.

    The party is stepping up *now* because of something happening in the world —
    a news event, faction tension, or the job being too important to let lapse.
    """
    title   = mission.get("title",   "Unknown Contract")
    faction = mission.get("faction", "Unknown Faction")
    tier    = mission.get("tier",    "standard")
    body    = mission.get("body",    "")
    try:
        from src.party_profiles import profile_summary
        party_block = "\n" + profile_summary(party_name)
    except Exception:
        party_block = f"\nParty: {party_name}"

    news_line = f"\nRECENT UNDERCITY EVENTS:\n{news_snippet}" if news_snippet else ""

    return f"""You are the Undercity mission board posting a late claim notice.

This contract has been sitting on the board unclaimed for several days. An adventurer party
has now stepped forward — motivated by recent events or faction pressure — to finally take it.

Mission: {title}
Faction: {faction}
Tier: {tier}
Details: {body}
Claiming party: {party_name}{party_block}{news_line}

Write a SHORT claim notice (2-3 lines) in the voice of the mission board.
Format:
⚡ **CONTRACT CLAIMED (LATE) — {title}**
*Taken by {party_name}. [1 sentence: WHY they're taking it NOW — tie it to a recent event, faction
pressure, or the job's stakes becoming too urgent to ignore. Then 1 sentence about the party.]*

RULES:
- The reason they're taking it now must feel earned — connect to news, faction tension, or world events
- Stay in-character, gritty, matter-of-fact
- No preamble, no sign-off. Output only the claim notice."""


def _build_rescission_prompt(mission: dict, news_snippet: str) -> str:
    """Generate a story-driven withdrawal notice for an old personal mission."""
    title     = mission.get("title",      "Unknown Contract")
    faction   = mission.get("faction",    "Unknown Faction")
    character = mission.get("personal_for", "the intended recipient")
    body      = mission.get("body",       "")
    news_line = f"\nRECENT UNDERCITY EVENTS:\n{news_snippet}" if news_snippet else ""

    return f"""{_LORE}

A personal mission contract has been withdrawn. It was posted for {character} but never claimed.
The faction that posted it — {faction} — has pulled the offer.

Mission: {title}
Details: {body}{news_line}

Write a SHORT withdrawal notice (2-3 lines) in the voice of the mission board.

The withdrawal should have a STORY REASON tied to recent events, faction priorities shifting,
the opportunity closing, or the situation resolving itself without help.
Examples of reasons:
- The faction's circumstances changed because of [recent event]
- The contact went silent or was dealt with by other means
- The window of opportunity closed — the target moved, the evidence was destroyed, etc.
- A rival faction already handled it (in their own way)
- The original posting was recalled after [news event] changed priorities

Format:
🚫 **CONTRACT WITHDRAWN — {title}**
*Originally posted for {character}. [1-2 sentences: the specific story reason the offer was pulled,
tied to something real happening in the Undercity right now.]*

RULES:
- The reason must feel like a consequence of world events — not just "offer expired"
- Specific over generic. Name a faction, an event, a location if possible
- No preamble, no sign-off. Output only the withdrawal notice."""


# _schedule_claim removed — claims are now handled per-party in check_claims.
# Each party independently rolls during the claim window rather than one party
# being pre-assigned at post time.


async def check_claims(channel, client=None) -> None:
    """
    Called every hour alongside check_expirations.
    For each unclaimed mission in the claim window (CLAIM_DAYS_MIN–CLAIM_DAYS_MAX days old),
    a sample of NPC parties each independently roll to claim it.
    First party to succeed takes the contract.
    """
    import logging
    logger = logging.getLogger(__name__)

    missions = _load_missions()
    now      = datetime.utcnow()
    updated  = False

    for mission in missions:
        # Skip resolved, personal, already claimed, or hostile notices
        if mission.get("resolved"):
            continue
        if mission.get("personal_for"):
            continue
        if mission.get("claimed"):
            continue
        if mission.get("npc_claimed"):
            continue
        if mission.get("is_hostile"):
            continue

        # Check age — only evaluate missions inside the claim window
        try:
            posted_at = datetime.fromisoformat(mission["posted_at"])
            age_days  = (now - posted_at).total_seconds() / 86400
        except Exception:
            continue

        if age_days < CLAIM_DAYS_MIN:
            continue  # too fresh — parties haven't had time to read the board
        if age_days > CLAIM_DAYS_MAX:
            continue  # claim window closed — board sweep / expiry handles it

        # Urgency boost: missions sitting unclaimed past the threshold get a higher
        # claim probability and more parties evaluating them each cycle.
        is_urgent = age_days >= CLAIM_URGENCY_THRESHOLD_DAYS
        prob = CLAIM_PROBABILITY_PER_PARTY * (CLAIM_URGENCY_MULTIPLIER if is_urgent else 1.0)
        # Urgent missions draw more attention — give them an extra party slot
        parties_this_check = CLAIM_PARTIES_PER_CHECK + (2 if is_urgent else 0)

        # Each party in the sample rolls independently.
        # Sample a random subset of the full party list each cycle so different
        # parties get a shot across multiple cycles if no one claims immediately.
        all_parties = _load_party_list()
        if not all_parties:
            continue
        random.shuffle(all_parties)
        sample = all_parties[:parties_this_check]

        winning_party = None
        for candidate in sample:
            if random.random() < prob:
                winning_party = candidate
                break

        if not winning_party:
            continue  # nobody claimed this cycle — try again next hour

        # A party stepped up — mark them as used and proceed
        used = _load_used_parties()
        if winning_party not in used:
            used.append(winning_party)
            _save_used_parties(used)

        party_name = winning_party

        # Ensure profile exists before building the claim prompt
        try:
            from src.party_profiles import ensure_profile
            await ensure_profile(party_name)
        except Exception:
            pass
        try:
            msg = await channel.fetch_message(mission["message_id"])
            await msg.delete()
        except Exception:
            pass  # message already gone, that’s fine

        if is_urgent:
            news = _load_recent_news()
            prompt = _build_urgent_claim_prompt(mission, party_name, news)
            fallback_emoji = "⚡"
        else:
            prompt = _build_claim_prompt(mission, party_name)
            fallback_emoji = "✅"
        notice = await _generate(prompt)
        if not notice:
            notice = f"{fallback_emoji} **CONTRACT CLAIMED — {mission['title']}**\n*Taken by {party_name}. Contract is no longer available.*"

        # Post NPC claim notice to results channel (falls back to board if no access)
        results_ch = await _get_results_channel(client, fallback_channel=channel) if client else channel
        new_msg = await results_ch.send(notice)

        # Schedule NPC completion 1-3 days after claim
        complete_dt = datetime.utcnow() + timedelta(
            seconds=random.randint(1 * 24 * 3600, 3 * 24 * 3600)
        )
        # 80% chance they succeed, 20% they fail
        npc_outcome = "complete" if random.random() < 0.80 else "fail"

        mission["claimed"]              = True
        mission["resolved"]             = False   # NOT resolved yet — waiting for completion
        mission["npc_claimed"]          = True
        mission["claim_party"]          = party_name   # who actually claimed it
        mission["claim_message_id"]     = new_msg.id
        mission["npc_complete_at"]      = complete_dt.isoformat()
        mission["npc_outcome"]          = npc_outcome
        updated = True
        urgency_tag = " [URGENT PICKUP]" if is_urgent else ""
        logger.info(f"🎟️ Mission claimed{urgency_tag}: {mission['title']} by {party_name} → {npc_outcome} at {complete_dt.strftime('%Y-%m-%d %H:%M')}")

        # Notify DM
        if client:
            tier    = mission.get("tier", "?").upper()
            faction = mission.get("faction", "Unknown Faction")
            await _dm_notify(
                client,
                f"🎟️ NPC Party Claimed Mission — {mission['title']}",
                f"**Claimed by:** {party_name}\n"
                f"**Faction:** {faction} | **Tier:** {tier}\n"
                f"*Expected outcome: {npc_outcome} in ~{(complete_dt - datetime.utcnow()).days + 1} day(s)*\n\n"
                f"{mission.get('body', '').strip()}"
            )

    if updated:
        _save_missions(missions)


# ---------------------------------------------------------------------------
# NPC party completion checker
# ---------------------------------------------------------------------------

async def check_npc_completions(channel, client=None) -> None:
    """
    Called hourly. For any NPC-claimed mission whose npc_complete_at has passed,
    post a completion or failure notice and update faction + party rep.
    """
    import logging
    from src.faction_reputation import (
        on_npc_party_complete, on_npc_party_fail,
        TIER_EMOJI,
    )
    from src.party_profiles import format_party_rank_change, PARTY_POINTS_TO_SHIFT
    logger = logging.getLogger(__name__)

    missions = _load_missions()
    now      = datetime.utcnow()
    updated  = False

    for mission in missions:
        if mission.get("resolved"):
            continue
        if not mission.get("npc_claimed"):
            continue
        complete_at = mission.get("npc_complete_at")
        if not complete_at:
            continue
        try:
            complete_dt = datetime.fromisoformat(complete_at)
        except Exception:
            continue
        if now < complete_dt:
            continue

        party_name = mission.get("claim_party", "Unknown Party")
        faction    = mission.get("faction", "")
        tier       = mission.get("tier", "standard")
        outcome    = mission.get("npc_outcome", "complete")
        title      = mission.get("title", "Unknown Contract")

        if outcome == "complete":
            # Generate completion notice
            prompt = f"""You are the Undercity mission board posting an NPC party completion notice.

An adventurer party has returned from a contract.

Mission: {title}
Faction: {faction}
Tier: {tier}
Completed by: {party_name}

Write a SHORT completion notice (2-3 lines).
Format:
🏆 **CONTRACT COMPLETE — {title}**
*{party_name} has returned. [1-2 sentences: what they accomplished or what it cost them.]*

RULES:
- Gritty, matter-of-fact, earned
- No preamble, no sign-off. Output the notice only."""
            notice = await _generate(prompt)
            if not notice:
                notice = f"🏆 **CONTRACT COMPLETE — {title}**\n*{party_name} has returned. The contract is fulfilled.*"

            # NPC completions only affect the NPC party rank — NOT the player's faction reputation
            party_rep   = on_npc_party_complete(party_name, tier)
            emoji       = TIER_EMOJI.get(party_rep["new_tier"], "")
            rep_footer  = f"\n*{party_name}: {party_rep['old_tier']} → {party_rep['new_tier']} {emoji}*" if party_rep["shifted"] else ""
            # Post NPC completion to results channel (falls back to board if no access)
            results_ch = await _get_results_channel(client, fallback_channel=channel) if client else channel
            if results_ch:
                await results_ch.send(notice + rep_footer)
            logger.info(f"🏆 NPC completed: {title} by {party_name}")

            if client:
                party_line   = f"\n{format_party_rank_change(party_rep)}" if party_rep["shifted"] else f"\n📊 {party_name}: {party_rep['new_tier']} ({party_rep['points']:+d}/{PARTY_POINTS_TO_SHIFT})"
                await _dm_notify(
                    client,
                    f"🏆 NPC Party Completed — {title}",
                    f"**Party:** {party_name} | **Faction:** {faction} | **Tier:** {tier.upper()}"
                    f"{party_line}\n\n"
                    f"{mission.get('body', '').strip()}"
                )
        else:
            # Generate failure notice
            prompt = f"""You are the Undercity mission board posting an NPC party failure notice.

An adventurer party failed to complete a contract.

Mission: {title}
Faction: {faction}
Tier: {tier}
Failed by: {party_name}

Write a SHORT failure notice (2-3 lines).
Format:
💥 **CONTRACT FAILED — {title}**
*{party_name} did not complete the job. [1-2 sentences: what went wrong.]*

RULES:
- Gritty, terse, consequences feel real
- No preamble, no sign-off. Output the notice only."""
            notice = await _generate(prompt)
            if not notice:
                notice = f"💥 **CONTRACT FAILED — {title}**\n*{party_name} did not complete the job.*"

            # NPC failures only affect the NPC party rank — NOT the player's faction reputation
            party_rep   = on_npc_party_fail(party_name, tier)
            emoji       = TIER_EMOJI.get(party_rep["new_tier"], "")
            rep_footer  = f"\n*{party_name}: {party_rep['old_tier']} → {party_rep['new_tier']} {emoji}*" if party_rep["shifted"] else ""
            # Post NPC failure to results channel (falls back to board if no access)
            results_ch = await _get_results_channel(client, fallback_channel=channel) if client else channel
            if results_ch:
                await results_ch.send(notice + rep_footer)
            logger.info(f"💥 NPC failed: {title} by {party_name}")

            if client:
                party_line   = f"\n{format_party_rank_change(party_rep)}" if party_rep["shifted"] else f"\n📊 {party_name}: {party_rep['new_tier']} ({party_rep['points']:+d}/{PARTY_POINTS_TO_SHIFT})"
                await _dm_notify(
                    client,
                    f"💥 NPC Party Failed — {title}",
                    f"**Party:** {party_name} | **Faction:** {faction} | **Tier:** {tier.upper()}"
                    f"{party_line}\n\n"
                    f"{mission.get('body', '').strip()}"
                )

        mission["resolved"] = True
        updated = True

    if updated:
        _save_missions(missions)


# ---------------------------------------------------------------------------
# DM private message notifications
# ---------------------------------------------------------------------------

async def _dm_notify(client, subject: str, body: str) -> None:
    """Send a private message to the DM user summarising a mission event."""
    import logging
    logger = logging.getLogger(__name__)
    dm_id = int(os.getenv("DM_USER_ID", 0))
    if not dm_id:
        return
    try:
        user = await client.fetch_user(dm_id)
        await user.send(f"**{subject}**\n{body}")
    except Exception as e:
        logger.warning(f"DM notify failed: {e}")


# ---------------------------------------------------------------------------
# Module generation (background task after player claims)
# ---------------------------------------------------------------------------

async def _generate_and_post_module(client, mission: dict, player_name: str) -> None:
    """Background task: generate a full mission module .docx and post it."""
    try:
        from src.mission_module_gen import generate_module, post_module_to_channel
        docx_path = await generate_module(mission, player_name)
        if docx_path and docx_path.exists():
            await post_module_to_channel(client, docx_path, mission, player_name)
            # DM the DM that the module is ready
            dm_id = int(os.getenv("DM_USER_ID", 0))
            if dm_id:
                try:
                    import discord as _disc
                    dm_user = await client.fetch_user(dm_id)
                    await dm_user.send(
                        f"\U0001f4d6 **Module generated:** {mission.get('title', '?')}\n"
                        f"Claimed by **{player_name}** — .docx posted to the modules channel."
                    )
                except Exception:
                    pass
            logger.info(f"\U0001f4d6 Module pipeline complete: {mission.get('title', '?')}")
        else:
            logger.warning(f"\U0001f4d6 Module generation returned no file for: {mission.get('title', '?')}")
    except Exception as e:
        import traceback
        logger.error(f"\U0001f4d6 Module generation error: {e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Player claim / DM complete via reactions
# ---------------------------------------------------------------------------

def _build_player_claim_prompt(mission: dict, player_name: str) -> str:
    title   = mission.get("title",   "Unknown Contract")
    faction = mission.get("faction", "Unknown Faction")
    tier    = mission.get("tier",    "standard")
    personal_for = mission.get("personal_for", "")
    personal_line = f"\nThis was a personal contract issued specifically for {personal_for}." if personal_for else ""
    return f"""You are the Undercity mission board posting a claim notice.

An adventurer has just accepted a contract.

Mission title: {title}
Faction: {faction}
Tier: {tier}
Claiming adventurer: {player_name}{personal_line}

Write a SHORT in-character claim notice (2-3 lines).
Required output format — nothing else:
⚔️ **CONTRACT TAKEN — {title}**
*Claimed by {player_name}. [1 sentence about what they're walking into or what the faction expects.]*

RULES:
- The FIRST line must be exactly: ⚔️ **CONTRACT TAKEN — {title}**
- Do NOT repeat the title in the body text
- Gritty, matter-of-fact board-voice
- No preamble, no sign-off. Output the notice only."""


def _build_complete_prompt(mission: dict, player_name: str) -> str:
    title   = mission.get("title",   "Unknown Contract")
    faction = mission.get("faction", "Unknown Faction")
    tier    = mission.get("tier",    "standard")
    body    = mission.get("body",    "")
    claimer = mission.get("player_claimer", player_name)
    return f"""You are the Undercity mission board posting a completion notice.

An adventurer has successfully completed a contract.

Mission: {title}
Faction: {faction}
Tier: {tier}
Details: {body}
Completed by: {claimer}

Write a SHORT in-character completion notice (2-3 lines).
Format:
🏆 **CONTRACT COMPLETE — {title}**
*{claimer} has returned. [1-2 sentences: brief flavour on what they accomplished or what it cost them.]*

RULES:
- Gritty, earned, matter-of-fact
- Hint at consequence or reward without spelling everything out
- No preamble, no sign-off. Output the notice only."""


class _MissionQuestionnaireModal(discord.ui.Modal):
    """Post-mission questionnaire — captures what actually happened for world memory."""

    def __init__(self, mission_index: int, view: discord.ui.View):
        title_text = "Mission Debrief"
        super().__init__(title=title_text, timeout=600, custom_id=f"debrief_{mission_index}")
        self.mission_index = mission_index
        self.parent_view = view

        self.q_killed = discord.ui.TextInput(
            label="NPCs killed or permanently removed?",
            placeholder="Names separated by commas, or 'None'",
            style=discord.TextStyle.short,
            required=False,
            max_length=300,
            custom_id=f"q_killed_{mission_index}",
        )
        self.add_item(self.q_killed)

        self.q_decisions = discord.ui.TextInput(
            label="Key decisions, alliances formed/broken?",
            placeholder="What major choices did the party make?",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            custom_id=f"q_decisions_{mission_index}",
        )
        self.add_item(self.q_decisions)

        self.q_locations = discord.ui.TextInput(
            label="Locations damaged, destroyed, or changed?",
            placeholder="Warehouse burned, tunnel collapsed, etc. or 'None'",
            style=discord.TextStyle.short,
            required=False,
            max_length=300,
            custom_id=f"q_locations_{mission_index}",
        )
        self.add_item(self.q_locations)

        self.q_threads = discord.ui.TextInput(
            label="Loose threads or unresolved elements?",
            placeholder="Escaped enemies, mysteries, items not found, etc.",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            custom_id=f"q_threads_{mission_index}",
        )
        self.add_item(self.q_threads)

        self.q_notable = discord.ui.TextInput(
            label="Notable moments or unexpected actions?",
            placeholder="Anything memorable the party did, funny or dramatic",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            custom_id=f"q_notable_{mission_index}",
        )
        self.add_item(self.q_notable)

    async def on_submit(self, interaction: discord.Interaction):
        """Process the questionnaire answers and complete the mission."""
        import logging
        from src.faction_reputation import on_mission_complete, format_rep_change
        from src.mission_outcomes import save_outcome, process_outcome_consequences
        logger = logging.getLogger(__name__)

        await interaction.response.defer(ephemeral=True)

        missions = _load_missions()
        if self.mission_index >= len(missions):
            await interaction.followup.send("Mission not found.", ephemeral=True)
            return
        mission = missions[self.mission_index]
        if mission.get("completed") or mission.get("failed"):
            await interaction.followup.send("Already resolved.", ephemeral=True)
            return

        claimer = mission.get("player_claimer", "Unknown Adventurer")
        faction = mission.get("faction", "")

        # Build outcome record from questionnaire answers
        outcome = {
            "mission_title":     mission.get("title", "Unknown"),
            "faction":           faction,
            "opposing_faction":  mission.get("opposing_faction", ""),
            "tier":              mission.get("tier", "standard"),
            "completed_by":      claimer,
            "completed_at":      datetime.now().strftime("%Y-%m-%d"),
            "result":            "completed",
            "npcs_killed":       self.q_killed.value.strip() or "",
            "key_decisions":     self.q_decisions.value.strip() or "",
            "location_changes":  self.q_locations.value.strip() or "",
            "loose_threads":     self.q_threads.value.strip() or "",
            "notable_moments":   self.q_notable.value.strip() or "",
            "consequences":      [],
        }

        # Process consequences (NPC deaths, faction enmity, etc.)
        consequences = process_outcome_consequences(outcome)
        outcome["consequences"] = consequences

        # Save to persistent memory
        save_outcome(outcome)

        # Generate completion notice
        prompt = _build_complete_prompt(mission, claimer)
        notice = await _generate(prompt)
        if not notice:
            notice = f"🏆 **CONTRACT COMPLETE — {mission['title']}**\n*{claimer} has returned. The contract is fulfilled.*"

        # Delete the old claim post from the board
        board_channel_id = int(mission.get("claim_channel_id") or os.getenv("MISSION_BOARD_CHANNEL_ID", 0))
        board_channel = interaction.client.get_channel(board_channel_id)
        if board_channel:
            claim_msg_id = mission.get("claim_message_id")
            if claim_msg_id:
                try:
                    old = await board_channel.fetch_message(claim_msg_id)
                    await old.delete()
                except Exception:
                    pass

        # Post result to results channel
        results_channel = await _get_results_channel(interaction.client, fallback_channel=board_channel)
        if results_channel:
            await results_channel.send(notice)

        # Strange Occurrences: if the mission's contact NPC is undead/doppelganger/returned,
        # the party has dealt with them — send them back to the graveyard.
        _npc_giver_raw = (mission.get("npc_giver") or "").strip()
        if _npc_giver_raw:
            _returned_name = _npc_giver_raw.split(",")[0].strip()
            if _returned_name:
                try:
                    _returned_rows = raw_query(
                        "SELECT name, status FROM npcs WHERE name = %s "
                        "AND status IN ('undead', 'doppelganger', 'returned') LIMIT 1",
                        (_returned_name,),
                    ) or []
                    if _returned_rows:
                        _prev_status = _returned_rows[0]["status"]
                        raw_execute(
                            "UPDATE npcs SET status='dead', deceased_at=NOW() WHERE name=%s",
                            (_returned_name,),
                        )
                        consequences.append(
                            f"⚰️ {_returned_name} returned to the graveyard (was {_prev_status})"
                        )
                        logger.info(
                            f"Strange Occurrence resolved: {_returned_name} ({_prev_status} → dead)"
                        )
                        if results_channel:
                            await results_channel.send(
                                f"☠️ **{_returned_name}** has been returned to the grave.\n"
                                f"The {_prev_status} walks no more. May they rest this time."
                            )
                except Exception as _se:
                    logger.warning(f"Strange Occurrence graveyard update failed: {_se}")

        mission["completed"] = True
        mission["resolved"]  = True
        _save_missions(missions)
        logger.info(f"✅ Mission completed via debrief: {mission['title']}")

        # Async interview trigger — runs in background, won't block completion flow
        try:
            from src.party_interview import maybe_trigger_interview
            asyncio.get_event_loop().create_task(
                maybe_trigger_interview(outcome, mission, interaction.client)
            )
        except Exception as _ie:
            logger.warning(f"party_interview trigger failed: {_ie}")

        # Faction reputation — gain with posting faction
        rep_result = on_mission_complete(faction) if faction else None
        rep_line   = f"\n{format_rep_change(rep_result)}" if rep_result else ""

        # Opposing faction — lose rep if mission worked against them
        opposing = mission.get("opposing_faction", "")
        opposing_line = ""
        if opposing:
            from src.faction_reputation import on_mission_failed as _apply_negative
            opp_result = _apply_negative(opposing)
            opposing_line = f"\n{format_rep_change(opp_result)}  *(opposed)*"
            consequences.append(f"📉 {opposing} rep decreased — mission worked against them")

        # Build consequence summary for DM
        conseq_lines = "\n".join(f"  {c}" for c in consequences) if consequences else "  No world changes."

        self.parent_view.stop()
        if self.parent_view._original_message:
            try:
                await self.parent_view._original_message.edit(view=None)
            except Exception:
                pass
        await interaction.followup.send(
            f"🏆 **Mission Complete:** {mission['title']}{rep_line}{opposing_line}\n"
            f"\n**World Consequences:**\n{conseq_lines}\n"
            f"\n*Outcome saved to world memory.*",
            ephemeral=True,
        )


class _MissionOutcomeView(discord.ui.View):
    """Private DM buttons for DM to mark a player-claimed mission complete or failed."""

    def __init__(self, mission_index: int):
        super().__init__(timeout=None)  # persistent until clicked
        self.mission_index = mission_index
        self._original_message = None  # set in button callbacks so modals can clear it
        # Unique custom_ids per mission so Discord can route them correctly
        for item in self.children:
            item.custom_id = f"{item.custom_id}_{mission_index}"

    @discord.ui.button(label="✅ Complete", style=discord.ButtonStyle.success, custom_id="outcome_complete")
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Shows the mission debrief questionnaire instead of immediately completing."""
        missions = _load_missions()
        if self.mission_index >= len(missions):
            await interaction.response.send_message("Mission not found.", ephemeral=True)
            return
        mission = missions[self.mission_index]
        if mission.get("completed") or mission.get("failed"):
            await interaction.response.send_message("Already resolved.", ephemeral=True)
            return

        # Store so the modal can clear the buttons after resolving
        self._original_message = interaction.message
        modal = _MissionQuestionnaireModal(self.mission_index, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="💥 Failed", style=discord.ButtonStyle.danger, custom_id="outcome_fail")
    async def fail(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Shows a brief failure debrief then processes the failure."""
        missions = _load_missions()
        if self.mission_index >= len(missions):
            await interaction.response.send_message("Mission not found.", ephemeral=True)
            return
        mission = missions[self.mission_index]
        if mission.get("completed") or mission.get("failed"):
            await interaction.response.send_message("Already resolved.", ephemeral=True)
            return

        self._original_message = interaction.message
        modal = _MissionFailModal(self.mission_index, self)
        await interaction.response.send_modal(modal)


class _MissionFailModal(discord.ui.Modal):
    """Brief failure debrief — what went wrong and any consequences."""

    def __init__(self, mission_index: int, view: discord.ui.View):
        super().__init__(title="Mission Failed — Debrief", timeout=600, custom_id=f"fail_debrief_{mission_index}")
        self.mission_index = mission_index
        self.parent_view = view

        self.q_what_happened = discord.ui.TextInput(
            label="What went wrong?",
            placeholder="Party retreated, objective destroyed, betrayed, etc.",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            custom_id=f"qf_what_{mission_index}",
        )
        self.add_item(self.q_what_happened)

        self.q_killed = discord.ui.TextInput(
            label="Any NPCs killed or consequences?",
            placeholder="NPC names killed, locations destroyed, or 'None'",
            style=discord.TextStyle.short,
            required=False,
            max_length=300,
            custom_id=f"qf_killed_{mission_index}",
        )
        self.add_item(self.q_killed)

        self.q_loose = discord.ui.TextInput(
            label="What's left unresolved?",
            placeholder="The villain escaped, the artifact was lost, etc.",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            custom_id=f"qf_loose_{mission_index}",
        )
        self.add_item(self.q_loose)

    async def on_submit(self, interaction: discord.Interaction):
        import logging
        from src.faction_reputation import on_mission_failed, format_rep_change
        from src.mission_outcomes import save_outcome, process_outcome_consequences
        logger = logging.getLogger(__name__)

        await interaction.response.defer(ephemeral=True)

        missions = _load_missions()
        if self.mission_index >= len(missions):
            await interaction.followup.send("Mission not found.", ephemeral=True)
            return
        mission = missions[self.mission_index]
        if mission.get("completed") or mission.get("failed"):
            await interaction.followup.send("Already resolved.", ephemeral=True)
            return

        claimer = mission.get("player_claimer", "Unknown Adventurer")
        faction = mission.get("faction", "")

        # Build outcome record
        outcome = {
            "mission_title":   mission.get("title", "Unknown"),
            "faction":         faction,
            "tier":            mission.get("tier", "standard"),
            "completed_by":    claimer,
            "completed_at":    datetime.now().strftime("%Y-%m-%d"),
            "result":          "failed",
            "npcs_killed":     self.q_killed.value.strip() or "",
            "key_decisions":   self.q_what_happened.value.strip() or "",
            "location_changes":"",
            "loose_threads":   self.q_loose.value.strip() or "",
            "notable_moments": "",
            "consequences":    [],
        }

        consequences = process_outcome_consequences(outcome)
        outcome["consequences"] = consequences
        save_outcome(outcome)

        # Generate failure notice
        fail_prompt = f"""You are the Undercity mission board posting a failure notice.
Mission: {mission.get('title', 'Unknown')}
Faction: {faction}
Tier: {mission.get('tier', 'standard')}
Attempted by: {claimer}
Format:
💥 **CONTRACT FAILED — {mission.get('title', 'Unknown')}**
*{claimer} did not complete the job. [1-2 sentences: what went wrong.]*
RULES: Gritty, terse. No preamble, no sign-off."""
        notice = await _generate(fail_prompt)
        if not notice:
            notice = f"💥 **CONTRACT FAILED — {mission['title']}**\n*{claimer} did not complete the job. The faction is not pleased.*"

        # Delete old claim post
        board_channel_id = int(mission.get("claim_channel_id") or os.getenv("MISSION_BOARD_CHANNEL_ID", 0))
        board_channel = interaction.client.get_channel(board_channel_id)
        if board_channel:
            claim_msg_id = mission.get("claim_message_id")
            if claim_msg_id:
                try:
                    old = await board_channel.fetch_message(claim_msg_id)
                    await old.delete()
                except Exception:
                    pass

        results_channel = await _get_results_channel(interaction.client, fallback_channel=board_channel)
        if results_channel:
            await results_channel.send(notice)

        mission["failed"]   = True
        mission["resolved"] = True
        _save_missions(missions)
        logger.info(f"❌ Mission failed via debrief: {mission['title']}")

        rep_result = on_mission_failed(faction) if faction else None
        rep_line   = f"\n{format_rep_change(rep_result)}" if rep_result else ""

        conseq_lines = "\n".join(f"  {c}" for c in consequences) if consequences else "  No world changes."

        self.parent_view.stop()
        if self.parent_view._original_message:
            try:
                await self.parent_view._original_message.edit(view=None)
            except Exception:
                pass
        await interaction.followup.send(
            f"💥 **Mission Failed:** {mission['title']}{rep_line}\n"
            f"\n**World Consequences:**\n{conseq_lines}\n"
            f"\n*Outcome saved to world memory.*",
            ephemeral=True,
        )


async def handle_reaction_claim(reaction, user, dm_id: int, client=None) -> None:
    """
    Called when a player reacts with ⚔️ on a mission board post.
    Posts claim notice publicly, sends DM to game master with ✅/💥 buttons.
    """
    import logging
    import discord
    logger = logging.getLogger(__name__)

    message_id = reaction.message.id
    missions   = _load_missions()
    mission_index = next((i for i, m in enumerate(missions) if m.get("message_id") == message_id), None)

    if mission_index is None:
        return
    mission = missions[mission_index]
    if mission.get("resolved") or mission.get("claimed"):
        return

    player_name = user.display_name

    # Claim immediately so two fast reactions cannot both generate modules.
    mission["claimed"]          = True
    mission["resolved"]         = False
    mission["player_claimer"]   = player_name
    _save_missions(missions)

    # Delete original post from mission board
    try:
        await reaction.message.delete()
    except Exception:
        pass

    prompt = _build_player_claim_prompt(mission, player_name)
    notice = await _generate(prompt)
    if not notice:
        notice = (
            f"⚔️ **CONTRACT TAKEN — {mission['title']}**\n"
            f"*Claimed by {player_name}. The board has been updated.*"
        )

    # Post claim notice to the results channel (falls back to board if no access)
    results_channel = await _get_results_channel(client, fallback_channel=reaction.message.channel) if client else reaction.message.channel
    new_msg = await results_channel.send(notice)

    mission["claim_message_id"] = new_msg.id
    mission["claim_channel_id"] = new_msg.channel.id
    _save_missions(missions)
    logger.info(f"⚔️ Mission claimed by player: {mission['title']} → {player_name}")

    # Auto-generate mission module in background
    if client:
        try:
            from src.cogs.module_gen import generate_and_post_module
            asyncio.get_event_loop().create_task(
                generate_and_post_module(mission, player_name, client)
            )
            logger.info(f"📖 Module generation queued for '{mission['title']}'")
        except Exception as e:
            logger.warning(f"📖 Could not queue module generation: {e}")

    # Send DM to game master with outcome buttons
    if client:
        tier     = mission.get("tier", "?").upper()
        faction  = mission.get("faction", "Unknown Faction")
        personal = f" *(personal contract for {mission['personal_for']})*" if mission.get("personal_for") else ""
        try:
            dm_user = await client.fetch_user(dm_id)
            view    = _MissionOutcomeView(mission_index=mission_index)
            await dm_user.send(
                f"⚔️ **Mission Claimed — {mission['title']}**\n"
                f"**Claimer:** {player_name}{personal}\n"
                f"**Faction:** {faction} | **Tier:** {tier}\n"
                f"*When the mission resolves, press a button below.*",
                view=view
            )
        except Exception as e:
            logger.warning(f"DM button notify failed: {e}")


async def handle_dashboard_claim(mission_id: int, player_name: str = "DM Dashboard", client=None) -> bool:
    """
    Claim a mission from the web dashboard using the bot's live Discord client.

    The dashboard cannot safely "press" the Discord reaction itself: bot-authored
    reactions are ignored by our raw reaction handler and may not behave like a
    real player reaction. This mirrors handle_reaction_claim directly so the
    board post, claim notice, DM outcome buttons, and module generation all stay
    on the normal Discord path.
    """
    import logging
    logger = logging.getLogger(__name__)

    missions = _load_missions()
    mission_index = next((i for i, m in enumerate(missions) if int(m.get("id") or 0) == int(mission_id)), None)
    if mission_index is None:
        logger.warning(f"⚔️ Dashboard claim: mission ID {mission_id} not found")
        return False

    mission = missions[mission_index]
    if mission.get("resolved") or mission.get("claimed") or mission.get("status") == "claimed":
        logger.info(f"⚔️ Dashboard claim ignored; mission already claimed/resolved: {mission.get('title', '?')}")
        return False

    mission["claimed"] = True
    mission["resolved"] = False
    mission["player_claimer"] = player_name
    _save_missions(missions)

    board_channel = None
    original_msg = None
    if client:
        channel_id = int(os.getenv("MISSION_BOARD_CHANNEL_ID", 0))
        board_channel = client.get_channel(channel_id) if channel_id else None
        if board_channel is None and channel_id:
            try:
                board_channel = await client.fetch_channel(channel_id)
            except Exception as e:
                logger.warning(f"⚔️ Dashboard claim: board channel unavailable: {e}")
        if board_channel and mission.get("message_id"):
            try:
                original_msg = await board_channel.fetch_message(int(mission["message_id"]))
                await original_msg.delete()
            except Exception as e:
                logger.warning(f"⚔️ Dashboard claim: could not delete board post: {e}")

    prompt = _build_player_claim_prompt(mission, player_name)
    notice = await _generate(prompt)
    if not notice:
        notice = (
            f"⚔️ **CONTRACT TAKEN — {mission['title']}**\n"
            f"*Claimed by {player_name}. The board has been updated.*"
        )

    results_channel = await _get_results_channel(client, fallback_channel=board_channel) if client else board_channel
    if results_channel:
        try:
            new_msg = await results_channel.send(notice)
            mission["claim_message_id"] = new_msg.id
            mission["claim_channel_id"] = new_msg.channel.id
            _save_missions(missions)
        except Exception as e:
            logger.warning(f"⚔️ Dashboard claim: could not post claim notice: {e}")

    logger.info(f"⚔️ Mission claimed from dashboard: {mission['title']} → {player_name}")

    if client:
        try:
            from src.cogs.module_gen import generate_and_post_module
            asyncio.get_running_loop().create_task(
                generate_and_post_module(mission, player_name, client)
            )
            logger.info(f"📖 Module generation queued for dashboard claim '{mission['title']}'")
        except Exception as e:
            logger.warning(f"📖 Could not queue dashboard module generation: {e}")

        dm_id = int(os.getenv("DM_USER_ID", 0))
        if dm_id:
            tier = mission.get("tier", "?").upper()
            faction = mission.get("faction", "Unknown Faction")
            personal = f" *(personal contract for {mission['personal_for']})*" if mission.get("personal_for") else ""
            try:
                dm_user = await client.fetch_user(dm_id)
                view = _MissionOutcomeView(mission_index=mission_index)
                await dm_user.send(
                    f"⚔️ **Mission Claimed — {mission['title']}**\n"
                    f"**Claimer:** {player_name}{personal}\n"
                    f"**Faction:** {faction} | **Tier:** {tier}\n"
                    f"*When the mission resolves, press a button below.*",
                    view=view,
                )
            except Exception as e:
                logger.warning(f"Dashboard DM button notify failed: {e}")

    return True


async def handle_reaction_complete(reaction, user, dm_id: int, client=None) -> None:
    """
    Called when the DM reacts with ✅ on a mission board post.
    Only the DM (dm_id) can trigger completion.
    """
    import logging
    from src.faction_reputation import on_mission_complete, format_rep_change
    logger = logging.getLogger(__name__)

    if user.id != dm_id:
        return

    message_id = reaction.message.id
    missions   = _load_missions()
    mission    = next((m for m in missions if m.get("message_id") == message_id
                       or m.get("claim_message_id") == message_id), None)

    if not mission or mission.get("completed"):
        return

    claimer = mission.get("player_claimer", "Unknown Adventurer")
    faction = mission.get("faction", "")

    # Delete original post from mission board
    try:
        await reaction.message.delete()
    except Exception:
        pass

    # Resolve results channel (falls back to board if no access)
    results_channel = await _get_results_channel(client, fallback_channel=reaction.message.channel) if client else reaction.message.channel

    prompt = _build_complete_prompt(mission, claimer)
    notice = await _generate(prompt)
    if not notice:
        notice = (
            f"🏆 **CONTRACT COMPLETE — {mission['title']}**\n"
            f"*{claimer} has returned. The contract is fulfilled.*"
        )
    await results_channel.send(notice)

    mission["completed"] = True
    mission["resolved"]  = True
    _save_missions(missions)
    logger.info(f"✅ Mission completed: {mission['title']} (claimer: {claimer})")

    # Update faction reputation
    rep_result = on_mission_complete(faction) if faction else None

    # Notify DM
    if client:
        tier    = mission.get("tier", "?").upper()
        rep_line = f"\n{format_rep_change(rep_result)}" if rep_result else ""
        await _dm_notify(
            client,
            f"🏆 Mission Completed — {mission['title']}",
            f"**Completed by:** {claimer}\n"
            f"**Faction:** {faction} | **Tier:** {tier}"
            f"{rep_line}\n\n"
            f"{mission.get('body', '').strip()}"
        )


async def handle_reaction_fail(reaction, user, dm_id: int, client=None) -> None:
    """
    Called when the DM reacts with ❌ on a mission board post.
    Only the DM (dm_id) can trigger failure.
    """
    import logging
    from src.faction_reputation import on_mission_failed, format_rep_change
    logger = logging.getLogger(__name__)

    if user.id != dm_id:
        return

    message_id = reaction.message.id
    missions   = _load_missions()
    mission    = next((m for m in missions if m.get("message_id") == message_id
                       or m.get("claim_message_id") == message_id), None)

    if not mission or mission.get("failed") or mission.get("completed"):
        return

    claimer = mission.get("player_claimer", "Unknown Adventurer")
    faction = mission.get("faction", "")

    # Delete original post from mission board
    try:
        await reaction.message.delete()
    except Exception:
        pass

    # Resolve results channel (falls back to board if no access)
    results_channel = await _get_results_channel(client, fallback_channel=reaction.message.channel) if client else reaction.message.channel

    # Generate failure notice
    fail_prompt = f"""You are the Undercity mission board posting a failure notice.

A mission was attempted but failed.

Mission: {mission.get('title', 'Unknown')}
Faction: {faction}
Tier: {mission.get('tier', 'standard')}
Attempted by: {claimer}

Write a SHORT in-character failure notice (2-3 lines).
Format:
💥 **CONTRACT FAILED — {mission.get('title', 'Unknown')}**
*{claimer} did not complete the job. [1-2 sentences: what went wrong or what the faction's reaction is.]*

RULES:
- Gritty, terse, consequences feel real
- No preamble, no sign-off. Output the notice only."""

    notice = await _generate(fail_prompt)
    if not notice:
        notice = (
            f"💥 **CONTRACT FAILED — {mission['title']}**\n"
            f"*{claimer} did not complete the job. The faction is not pleased.*"
        )
    await results_channel.send(notice)

    mission["failed"]   = True
    mission["resolved"] = True
    _save_missions(missions)
    logger.info(f"❌ Mission failed: {mission['title']} (claimer: {claimer})")

    # Update faction reputation
    rep_result = on_mission_failed(faction) if faction else None

    # Notify DM
    if client:
        tier     = mission.get("tier", "?").upper()
        rep_line = f"\n{format_rep_change(rep_result)}" if rep_result else ""
        await _dm_notify(
            client,
            f"💥 Mission Failed — {mission['title']}",
            f"**Failed by:** {claimer}\n"
            f"**Faction:** {faction} | **Tier:** {tier}"
            f"{rep_line}\n\n"
            f"{mission.get('body', '').strip()}"
        )


# ---------------------------------------------------------------------------
# Main board manager (called from aclient.py)
# ---------------------------------------------------------------------------

async def post_mission(channel) -> None:
    """Generate and post one mission to the board channel."""
    import logging
    logger = logging.getLogger(__name__)

    from src.ollama_busy import is_available, get_busy_reason
    if not is_available():
        logger.info(f"📋 Ollama busy ({get_busy_reason()}) — skipping mission post this cycle")
        return

    active = _count_active_normal()
    if active >= MAX_ACTIVE_NORMAL:
        logger.info(f"📋 Board cap reached ({active}/{MAX_ACTIVE_NORMAL} normal missions active) — skipping post")
        return

    recent = _load_missions()
    logger.info(f"📋 [GEN] Building mission prompt ({len(recent)} recent missions in context) ...")
    prompt = _build_mission_prompt(recent)
    logger.info(f"📋 [GEN] Prompt ready ({len(prompt.split())}w) — calling LLM ...")
    text = await _generate(prompt)
    if not text:
        logger.warning("📋 [GEN] Generation returned None — mission skipped")
        return

    logger.info(f"📋 [GEN] LLM returned {len(text.split())}w — parsing mission ...")
    mission = _parse_mission(text)
    expires_dt = datetime.fromisoformat(mission["expires_at"])
    days_left = (expires_dt - datetime.utcnow()).days

    logger.info(
        f"📋 [GEN] Parsed: '{mission.get('title','?')}' | "
        f"type={mission.get('type','?')} | tier={mission.get('tier','?')} | "
        f"faction={mission.get('faction','?')} | reward={mission.get('reward','?')} | "
        f"expires={days_left}d"
    )

    # Build color-coded embed based on faction reputation
    from src.faction_reputation import get_faction_color, get_faction_tier_label
    faction = mission.get("faction", "")
    embed_color = get_faction_color(faction) if faction else 0xE6C300  # yellow default
    tier_label = get_faction_tier_label(faction) if faction else "😐 Neutral"

    embed = _build_mission_embed(mission, embed_color, tier_label, days_left)
    logger.info(f"📋 [GEN] Embed built — posting to channel ...")

    msg = await channel.send(embed=embed)
    mission["message_id"] = msg.id
    _add_mission(mission)

    # Add ⚔️ reaction so players see a visible claim button
    try:
        await msg.add_reaction(EMOJI_CLAIM)
    except Exception:
        pass

    opposing = mission.get("opposing_faction", "")
    opp_log = f", opposes {opposing}" if opposing else ""
    logger.info(f"📋 Mission posted: {mission['title']} (tier: {mission['tier']}, {days_left}d, {tier_label}{opp_log}) — open for party claims in {CLAIM_DAYS_MIN}d")


async def post_calendar_triggered_mission(channel, ev: dict) -> bool:
    """Generate and post a mission triggered by a resolved faction calendar event.

    Uses the event's entry in _EVENT_MISSION_MAP to build a targeted brief, then
    runs through the standard mission generation pipeline. Returns True if a mission
    was posted successfully.

    Caller is responsible for calling mark_mission_spawned(ev) on True.
    """
    from src.faction_calendar import get_mission_params
    from src.resource_cop import (
        wait_for_ollama_turn, start_pipeline, finish_pipeline, append_pipeline_failure,
    )
    from src.faction_reputation import get_faction_color, get_faction_tier_label

    mission_type, brief, faction, expires_days = get_mission_params(ev)
    event_name = ev.get("type", "unknown")
    label = "calendar_mission_spawn"

    # Resource cop — don't pile onto Ollama
    decision = await wait_for_ollama_turn(label, track="primary")
    if not decision.run_now:
        logger.warning(
            f"📅 [CAL-MISSION] Deferred by cop for '{event_name}': {decision.reason}"
        )
        return False

    # Board cap check — calendar missions still count against the normal cap
    active = _count_active_normal()
    if active >= MAX_ACTIVE_NORMAL:
        logger.info(
            f"📅 [CAL-MISSION] Board cap reached ({active}/{MAX_ACTIVE_NORMAL}) — "
            f"deferring '{event_name}' mission"
        )
        return False

    run = await start_pipeline(
        label,
        mission_title=f"[calendar] {event_name}",
        mission_type=mission_type,
        phase="generating",
    )
    try:
        npc_block  = _build_npc_context()
        area_block = _load_area_context_block()

        prompt = f"""{_LORE}

{npc_block}
{area_block}

---
You are the Undercity mission board. Generate ONE mission contract posting.

MISSION PARAMETERS:
- Faction: {faction}
- Mission type: {mission_type}
- Triggered by: {faction} — {event_name} (this event just concluded)
- Expires in: {expires_days} days (time-sensitive follow-up work)

DM BRIEF — write the mission from this seed:
{brief}

REQUIRED FORMAT — output exactly this structure, nothing else:

**[FACTION NAME] — MISSION TITLE**
*Type: {mission_type} | Tier: [tier label] | Expires: TBD | Reward: [X EC + optional Kharma]*
*Opposes: [faction name, or "None"]*

[1-2 brief surface-level sentences describing the public job. No hidden truths.]

*Contact: [NPC name from the list above], [location] — [one detail: what they lose if this fails]*

TITLE RULES:
- Maximum 6 words. Must contain at least one proper noun (district, NPC name, faction, object).
- BANNED patterns: "The [Adjective] [Abstract Noun]" — no "The Silent X", "The Dark X", "The Burning X"
- BANNED words: Harvest, Shadow, Darkness, Silence, Reckoning, Unraveling, Corruption, Awakening, Legacy, Void, Storm, Forgotten, Ancient, Flame, Crimson

PROSE RULES:
- Noir city dispatch. Every sentence names a specific place, person, or thing.
- STAKES must be personal: "Mira Kaelth will lose her position" beats "trade routes disrupted"
- CONTACT must have skin in the game — what they lose if the party fails
- Do NOT reveal hidden truths, solutions, or module-only details."""

        text = await _generate(prompt)
        if not text:
            logger.warning(f"📅 [CAL-MISSION] Generation empty for '{event_name}'")
            await finish_pipeline(run.run_id, status="empty")
            return False

        mission = _parse_mission(text)
        mission["faction"] = faction
        mission["type"] = mission_type
        # Override expiry with event-specific window
        mission["expires_at"] = (
            datetime.utcnow() + timedelta(days=expires_days)
        ).isoformat()
        mission["calendar_event"] = event_name  # tag for traceability

        expires_dt = datetime.fromisoformat(mission["expires_at"])
        days_left  = max(1, (expires_dt - datetime.utcnow()).days)

        embed_color = get_faction_color(faction) if faction else 0xE6C300
        tier_label  = get_faction_tier_label(faction) if faction else "😐 Neutral"
        embed = _build_mission_embed(mission, embed_color, tier_label, days_left)

        msg = await channel.send(embed=embed)
        mission["message_id"] = msg.id
        _add_mission(mission)

        try:
            await msg.add_reaction(EMOJI_CLAIM)
        except Exception:
            pass

        logger.info(
            f"📅 [CAL-MISSION] Posted '{mission.get('title','?')}' "
            f"({mission_type}, {faction}, {days_left}d) from event '{event_name}'"
        )
        await finish_pipeline(run.run_id, status="finished")
        return True

    except Exception as exc:
        await append_pipeline_failure(run.run_id, exc)
        await finish_pipeline(run.run_id, status="failed")
        logger.error(f"📅 [CAL-MISSION] Failed for '{event_name}': {exc}", exc_info=True)
        return False


async def check_personal_rescissions(channel, client=None) -> None:
    """Randomly withdraw old unclaimed personal missions with a story/news reason.

    Called hourly alongside check_expirations. Personal missions older than
    PERSONAL_RESCIND_AGE_DAYS that are still unclaimed roll a PERSONAL_RESCIND_CHANCE
    each cycle. On success the offer is withdrawn with a generated narrative reason
    tied to recent news or faction events — keeps the board fresh and the world alive.
    """
    import logging
    logger = logging.getLogger(__name__)

    missions = _load_missions()
    now      = datetime.utcnow()
    updated  = False
    news     = None  # lazy-load once only if we need it

    for mission in missions:
        # Only target unclaimed personal missions
        if mission.get("resolved"):
            continue
        if not mission.get("personal_for"):
            continue
        if mission.get("claimed") or mission.get("npc_claimed"):
            continue

        # Check age
        try:
            posted_at = datetime.fromisoformat(mission["posted_at"])
            age_days  = (now - posted_at).total_seconds() / 86400
        except Exception:
            continue

        if age_days < PERSONAL_RESCIND_AGE_DAYS:
            continue  # too fresh — give the player time to pick it up

        # Roll for rescission
        if random.random() > PERSONAL_RESCIND_CHANCE:
            continue

        # Lazy-load news once
        if news is None:
            news = _load_recent_news()

        character = mission.get("personal_for", "Unknown")
        title     = mission.get("title", "Unknown Contract")

        prompt  = _build_rescission_prompt(mission, news)
        notice  = await _generate(prompt)
        if not notice:
            notice = (
                f"🚫 **CONTRACT WITHDRAWN — {title}**\n"
                f"*Originally posted for {character}. "
                f"The posting faction has recalled this contract — circumstances have changed.*"
            )

        results_ch = await _get_results_channel(client, fallback_channel=channel) if client else channel
        if results_ch:
            await results_ch.send(notice)

        # Try to clean up the original board message
        if mission.get("message_id"):
            try:
                msg = await channel.fetch_message(mission["message_id"])
                await msg.delete()
            except Exception:
                pass

        mission["resolved"] = True
        updated = True
        logger.info(f"🚫 Personal mission rescinded: '{title}' (for {character}, age {age_days:.1f}d)")

        # Notify DM
        if client:
            await _dm_notify(
                client,
                f"🚫 Personal Mission Withdrawn — {title}",
                f"**For:** {character} | **Faction:** {mission.get('faction', '?')}\n"
                f"*Sat unclaimed for {age_days:.1f} days — story reason generated and posted.*"
            )

    if updated:
        _save_missions(missions)


async def check_expirations(channel, client=None) -> None:
    """Check all active missions and post resolution notices for expired ones."""
    import logging
    logger = logging.getLogger(__name__)

    missions = _load_missions()
    now = datetime.utcnow()
    updated = False

    for mission in missions:
        if mission.get("resolved"):
            continue

        # Sweep old non-personal unclaimed missions off the board after BOARD_MAX_AGE_DAYS
        if (
            not mission.get("personal_for")
            and not mission.get("claimed")
            and not mission.get("npc_claimed")
        ):
            try:
                ts = mission.get("posted_at") or mission.get("created_at")
                if ts:
                    posted_at = datetime.fromisoformat(str(ts).split(".")[0].replace(" ", "T"))
                    age_days  = (now - posted_at).total_seconds() / 86400
                else:
                    age_days = 0
            except Exception:
                age_days = 0
            if age_days >= BOARD_MAX_AGE_DAYS:
                # Don't sweep missions that have a pending NPC claim not yet fired
                if mission.get("claim_at"):
                    try:
                        claim_dt = datetime.fromisoformat(mission["claim_at"])
                        if now < claim_dt:
                            continue  # claim hasn't fired yet — leave it on the board
                    except Exception:
                        pass
                mission["resolved"] = True
                updated = True
                logger.info(f"📋 Board sweep: removed stale mission '{mission.get('title', '?')}' (age {age_days:.1f}d)")
                continue

        try:
            expires_at = datetime.fromisoformat(str(mission["expires_at"]).split(".")[0].replace(" ", "T"))
        except Exception:
            continue  # no expires_at — age sweep handles it above

        if now >= expires_at:
            from src.faction_reputation import on_mission_expired, format_rep_change
            faction = mission.get("faction", "")

            # Generate resolution notice
            prompt = _build_resolution_prompt(mission)
            resolution = await _generate(prompt)
            if not resolution:
                resolution = f"❌ **Contract Closed — {mission['title']}**\n*This contract has expired. The posting faction has withdrawn the offer.*"

            # Post resolution to results channel (falls back to board if no access)
            results_ch = await _get_results_channel(client, fallback_channel=channel) if client else channel
            if results_ch:
                await results_ch.send(resolution)
            mission["resolved"] = True
            updated = True
            logger.info(f"📋 Mission resolved: {mission['title']}")

            # Update faction reputation (only for player-claimable missions, not hostile)
            rep_result = None
            if faction and not mission.get("is_hostile"):
                rep_result = on_mission_expired(faction)

            # Notify DM
            if client:
                tier     = mission.get("tier", "?").upper()
                rep_line = f"\n{format_rep_change(rep_result)}" if rep_result else ""
                await _dm_notify(
                    client,
                    f"❌ Mission Expired — {mission['title']}",
                    f"**Faction:** {faction} | **Tier:** {tier}\n"
                    f"*No one took this contract in time.*"
                    f"{rep_line}\n\n"
                    f"{mission.get('body', '').strip()}"
                )

    if updated:
        _save_missions(missions)


# ---------------------------------------------------------------------------
# Interval
# ---------------------------------------------------------------------------

def next_trickle_seconds() -> int:
    """6 to 12 hours between new mission posts."""
    return random.randint(TRICKLE_MIN, TRICKLE_MAX)
