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

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
MISSION_MEMORY_FILE    = DOCS_DIR / "mission_memory.json"
CHARACTER_MEMORY_FILE  = DOCS_DIR / "character_memory.txt"
PERSONAL_MISSION_TRACKER = DOCS_DIR / "personal_mission_tracker.json"
PARTY_LIST_FILE        = DOCS_DIR / "adventurer_parties.txt"
USED_PARTIES_FILE      = DOCS_DIR / "used_parties.json"
MISSION_TYPES_FILE     = DOCS_DIR / "generated_mission_types.json"

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
CLAIM_DAYS_MAX     = 3

# Non-personal unclaimed missions older than this are swept from the board
# Must be > CLAIM_DAYS_MAX so claim-scheduled missions aren't swept before they fire
BOARD_MAX_AGE_DAYS = 5

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
    "local":       (1,   7),
    "patrol":      (1,   7),
    "escort":      (7,  30),
    "standard":    (7,  30),
    "investigation":(7, 30),
    "rift":        (30, 90),
    "dungeon":     (30, 90),
    "major":       (30, 90),
    "inter-guild": (30, 90),
    "epic":        (90, 190),
    "divine":      (90, 190),
    "tower":       (90, 190),
    "high-stakes": (60, 120),
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
KHARMA REWARDS: Kharma is rare and meaningful. Local/patrol missions: 20-50 Kharma. Standard/escort/investigation: 50-150 Kharma. Rift/dungeon/major: 150-500 Kharma. Epic/divine/tower: 500-2000 Kharma. Never award less than 20 Kharma on any mission that includes Kharma as a reward.

FACTIONS (use ONLY these — do not invent new factions under any circumstances):
Iron Fang Consortium (relics/smuggling, Serrik Dhal), Argent Blades (glory/arena, Lady Cerys Valemont),
Wardens of Ash (city defence, Captain Havel Korin), Serpent Choir (divine contracts, High Apostle Yzura),
Obsidian Lotus (black market, The Widow), Glass Sigil (arcane archivists, Senior Archivist Pell),
Patchwork Saints (Warrens protectors), Adventurers Guild (quest hub, Mari Fen),
Guild of Ashen Scrolls (fate archivists, Eir Velan), Tower Authority/FTA (oversight, Director Myra Kess),
Wizards Tower (arcane academy, Archmage Yaulderna Silverstreak).
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
    if not MISSION_MEMORY_FILE.exists():
        return []
    try:
        return json.loads(MISSION_MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_missions(missions: List[dict]) -> None:
    try:
        MISSION_MEMORY_FILE.write_text(
            json.dumps(missions, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _add_mission(mission: dict) -> None:
    missions = _load_missions()
    missions.append(mission)
    _save_missions(missions)


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
    missions = _load_missions()
    for m in missions:
        if m.get("message_id") == message_id:
            m.update(updates)
    _save_missions(missions)


# ---------------------------------------------------------------------------
# Expiry helpers
# ---------------------------------------------------------------------------

def _expiry_for_tier(tier: str) -> datetime:
    tier_key = tier.lower().strip()
    lo, hi = TIER_EXPIRY.get(tier_key, DEFAULT_EXPIRY)
    days = random.randint(lo, hi)
    return datetime.utcnow() + timedelta(days=days)


def _parse_tier(text: str) -> str:
    """Extract the tier label from generated mission text."""
    text_lower = text.lower()
    for key in TIER_EXPIRY:
        if key in text_lower:
            return key
    return "standard"


# ---------------------------------------------------------------------------
# Mission generation prompt
# ---------------------------------------------------------------------------

_MISSION_TYPES = [
    # Common — weighted heavily toward street-level and faction work
    "a local neighbourhood job (courier gone missing, minor theft, debt collection)",
    "a local neighbourhood job (courier gone missing, minor theft, debt collection)",
    "a local neighbourhood job (courier gone missing, minor theft, debt collection)",
    "a patrol contract (Warden-adjacent, district sweep, check on a suspicious location)",
    "a patrol contract (Warden-adjacent, district sweep, check on a suspicious location)",
    "an escort mission (protect a person or cargo through dangerous territory)",
    "an escort mission (protect a person or cargo through dangerous territory)",
    "an investigation (track corruption, missing person, unexplained event)",
    "an investigation (track corruption, missing person, unexplained event)",
    "an inter-guild conflict job (mediate, spy, or sabotage on behalf of a faction)",
    "an inter-guild conflict job (mediate, spy, or sabotage on behalf of a faction)",
    "a high-stakes contract (assassination, political black op, relic retrieval)",
    # Uncommon — dungeon work
    "a dungeon delve into an abandoned structure or sealed vault in the Warrens or Outer Wall",
    # Rare — Rifts are rare emergencies, NOT routine postings
    "a Rift clearance ONLY in the Warrens or near the Outer Wall — a tear that has grown for days. CRITICAL: location must be in the Warrens or Outer Wall, nowhere else",
    # Very rare — epic/divine events
    "an epic or divine-tier mission (Tower floor, god involvement, city-scale consequences)",
]

# ---------------------------------------------------------------------------
# Dynamic mission type generation (runs daily)
# ---------------------------------------------------------------------------

def _load_generated_mission_types() -> List[str]:
    """Load AI-generated mission types from disk."""
    if not MISSION_TYPES_FILE.exists():
        return []
    try:
        data = json.loads(MISSION_TYPES_FILE.read_text(encoding="utf-8"))
        return data.get("types", [])
    except Exception:
        return []


def _save_generated_mission_types(types: List[str], generated_date: str) -> None:
    try:
        MISSION_TYPES_FILE.write_text(
            json.dumps({"generated_date": generated_date, "types": types}, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass


def _needs_new_mission_types() -> bool:
    """Returns True if types file is missing or was generated on a previous UTC day."""
    if not MISSION_TYPES_FILE.exists():
        return True
    try:
        data = json.loads(MISSION_TYPES_FILE.read_text(encoding="utf-8"))
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


def _build_mission_prompt(recent_missions: List[dict]) -> str:
    from src.faction_reputation import rep_summary_block, is_hostile
    # Combine hardcoded types with today's AI-generated types
    all_types = _MISSION_TYPES + _load_generated_mission_types()
    mission_type = random.choice(all_types)

    recent_block = ""
    if recent_missions:
        summaries = [m.get("title", "unknown") + " — " + m.get("faction", "") for m in recent_missions[-5:]]
        recent_block = "\nRECENT MISSIONS POSTED (avoid repeating these):\n" + "\n".join(summaries)

    rep_block = "\n" + rep_summary_block()

    return f"""{_LORE}
{rep_block}
{recent_block}

---
You are the Undercity mission board. Generate ONE new mission contract posting.
When selecting which faction posts this mission, prefer factions at Friendly or above standing.
Avoid generating contracts from Detested or Hated factions — those factions are enemies, not employers.

REQUIRED FORMAT — output exactly this structure, nothing else:

**[FACTION NAME] — MISSION TITLE**
*Tier: [tier label] | Expires: TBD | Reward: [X EC + any extras]*
*Opposes: [faction name if this mission works AGAINST another faction, or "None"]*

[2-3 sentences describing the job. Specific location, named NPC contact, clear objective. Atmospheric but practical.]

*Contact: [named NPC], [location]*

RULES:
- Mission type to generate: {mission_type}
- Use exactly one tier label from: local, patrol, escort, standard, investigation, rift, dungeon, major, inter-guild, high-stakes, epic, divine, tower
- If you use tier "rift", the location MUST be in the Warrens or Outer Wall. No exceptions.
- Invent specific details — named NPCs, exact EC rewards, precise locations
- No preamble, no explanation, no sign-off. Output the mission post only.
- If your response contains anything other than the mission post, you have failed."""


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

    # Hostile missions always use red
    embed = discord.Embed(
        description=text,
        color=0xCC0000,  # dark red — hostile faction
    )
    embed.set_footer(
        text=f"⚠️ HOSTILE • {faction} • Active for {days_left} day{'s' if days_left != 1 else ''}"
    )
    msg = await channel.send(embed=embed)
    mission["message_id"] = msg.id
    _add_mission(mission)
    logger.info(f"⚠️ Hostile notice posted from {faction}: {mission['title']}")


# ---------------------------------------------------------------------------
# Ollama call
# ---------------------------------------------------------------------------

async def _generate(prompt: str) -> Optional[str]:
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()

        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()

        # Strip AI preamble
        lines = text.splitlines()
        skip = ("sure", "here's", "here is", "as requested", "certainly",
                "of course", "i hope", "below is", "absolutely")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        return "\n".join(lines).strip() or None

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"mission_board _generate error: {e}")
        return None


# ---------------------------------------------------------------------------
# Parse generated mission text into structured fields
# ---------------------------------------------------------------------------

def _parse_mission(text: str) -> dict:
    # Extract faction + title from first bold line
    title = "Unknown Contract"
    faction = "Unknown"
    title_match = re.search(r"\*\*(.+?)\*\*", text)
    if title_match:
        raw = title_match.group(1)
        if " — " in raw:
            parts = raw.split(" — ", 1)
            faction = parts[0].strip()
            title = parts[1].strip()
        else:
            title = raw.strip()

    tier = _parse_tier(text)

    # Extract reward
    reward_match = re.search(r"[Rr]eward:\s*([^\n\|*]+)", text)
    reward = reward_match.group(1).strip() if reward_match else "See posting"

    # Extract opposing faction
    opposing_faction = ""
    opposes_match = re.search(r"[Oo]pposes:\s*([^\n\|*]+)", text)
    if opposes_match:
        raw_opposes = opposes_match.group(1).strip().strip('*').strip()
        if raw_opposes.lower() not in ("none", "n/a", "", "none."):
            opposing_faction = raw_opposes

    return {
        "title": title,
        "faction": faction,
        "tier": tier,
        "reward": reward,
        "opposing_faction": opposing_faction,
        "body": text,
        "posted_at": datetime.utcnow().isoformat(),
        "expires_at": _expiry_for_tier(tier).isoformat(),
        "resolved": False,
        "message_id": None,
    }


# ---------------------------------------------------------------------------
# Character memory parser
# ---------------------------------------------------------------------------

def _load_characters() -> List[dict]:
    """Parse character_memory.txt into a list of character dicts."""
    if not CHARACTER_MEMORY_FILE.exists():
        return []
    try:
        text = CHARACTER_MEMORY_FILE.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    characters = []
    for block in re.split(r"---CHARACTER---", text):
        block = block.strip()
        if not block or block.startswith("#") or "---END" in block:
            continue
        char = {}
        for line in block.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                char[key.strip()] = value.strip()
        if "NAME" in char:
            characters.append(char)
    return characters


def _personal_expiry_for_tier(tier: str) -> datetime:
    tier_key = tier.lower().strip()
    lo, hi = PERSONAL_TIER_EXPIRY.get(tier_key, PERSONAL_DEFAULT_EXPIRY)
    days = random.randint(lo, hi)
    return datetime.utcnow() + timedelta(days=days)


# ---------------------------------------------------------------------------
# Personal mission tracker
# ---------------------------------------------------------------------------

def _load_personal_tracker() -> dict:
    if not PERSONAL_MISSION_TRACKER.exists():
        return {}
    try:
        return json.loads(PERSONAL_MISSION_TRACKER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_personal_tracker(tracker: dict) -> None:
    try:
        PERSONAL_MISSION_TRACKER.write_text(
            json.dumps(tracker, indent=2), encoding="utf-8"
        )
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
*Tier: [tier label] | Expires: TBD | Reward: [X EC + any extras]*
*Opposes: [faction name if this mission works AGAINST another faction, or "None"]*

[2-3 sentences. Name {name} as the requested contractor. Specific NPC contact, location, clear objective. Make it feel personal to who they are.]

*Contact: [named NPC], [location]*

RULES:
- Use exactly one tier label: local, patrol, escort, standard, investigation, dungeon, major, inter-guild, high-stakes, epic, divine, tower
- Do NOT use tier "rift" for personal missions — Rifts are city-wide emergencies, not personal contracts
- Weave {name}'s identity, class, species, or history into why they are specifically being asked
- Invent fresh named NPCs, exact EC rewards, precise locations
- Do NOT put {name} in the bold header line — save it for the body text
- No preamble, no sign-off. Output the mission post only.
- If your response contains anything other than the mission post, you have failed."""


async def post_personal_mission(channel, character: dict) -> None:
    """Generate and post a personal mission for one character."""
    import logging
    logger = logging.getLogger(__name__)

    name = character.get("NAME", "Unknown")

    active = _count_active_personal(name)
    if active >= MAX_ACTIVE_PERSONAL:
        logger.info(f"📌 Personal cap reached for {name} ({active}/{MAX_ACTIVE_PERSONAL}) — skipping")
        return

    recent = _load_missions()
    prompt = _build_personal_mission_prompt(character, recent)
    text = await _generate(prompt)

    if not text:
        logger.warning(f"📋 personal mission: generation returned None for {name}")
        return

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

    embed = discord.Embed(
        description=text,
        color=embed_color,
    )
    opposing = mission.get("opposing_faction", "")
    pfooter = [f"📌 Personal for {name}", f"Standing: {tier_label}", f"Expires in {days_left}d", "React ⚔️ to claim"]
    if opposing:
        pfooter.insert(2, f"⚠️ Opposes: {opposing}")
    embed.set_footer(text="  •  ".join(pfooter))

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


def next_personal_mission_seconds() -> int:
    """1 to 3 days between personal missions per character."""
    return random.randint(PERSONAL_MISSION_MIN, PERSONAL_MISSION_MAX)


# ---------------------------------------------------------------------------
# Adventurer party system
# ---------------------------------------------------------------------------

def _load_party_list() -> List[str]:
    """Load named parties from adventurer_parties.txt, skipping comments."""
    if not PARTY_LIST_FILE.exists():
        return []
    lines = PARTY_LIST_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


def _load_used_parties() -> List[str]:
    if not USED_PARTIES_FILE.exists():
        return []
    try:
        return json.loads(USED_PARTIES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_used_parties(used: List[str]) -> None:
    try:
        USED_PARTIES_FILE.write_text(json.dumps(used, indent=2), encoding="utf-8")
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
            # Append new names to the file
            existing_text = PARTY_LIST_FILE.read_text(encoding="utf-8") if PARTY_LIST_FILE.exists() else ""
            with open(PARTY_LIST_FILE, "a", encoding="utf-8") as f:
                for name in new_names:
                    if name not in existing_text:
                        f.write(f"\n{name}")
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

        # Each party in the sample rolls independently.
        # Sample a random subset of the full party list each cycle so different
        # parties get a shot across multiple cycles if no one claims immediately.
        all_parties = _load_party_list()
        if not all_parties:
            continue
        random.shuffle(all_parties)
        sample = all_parties[:CLAIM_PARTIES_PER_CHECK]

        winning_party = None
        for candidate in sample:
            if random.random() < CLAIM_PROBABILITY_PER_PARTY:
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

        prompt = _build_claim_prompt(mission, party_name)
        notice = await _generate(prompt)
        if not notice:
            notice = f"✅ **CONTRACT CLAIMED — {mission['title']}**\n*Taken by {party_name}. Contract is no longer available.*"

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
        mission["claim_message_id"]     = new_msg.id
        mission["npc_complete_at"]      = complete_dt.isoformat()
        mission["npc_outcome"]          = npc_outcome
        updated = True
        logger.info(f"🎟️ Mission claimed: {mission['title']} by {party_name} → {npc_outcome} at {complete_dt.strftime('%Y-%m-%d %H:%M')}")

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
        board_channel_id = int(os.getenv("MISSION_BOARD_CHANNEL_ID", 0))
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

        mission["completed"] = True
        mission["resolved"]  = True
        _save_missions(missions)
        logger.info(f"✅ Mission completed via debrief: {mission['title']}")

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

        # Show the questionnaire modal
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
        board_channel_id = int(os.getenv("MISSION_BOARD_CHANNEL_ID", 0))
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

    mission["claimed"]          = True
    mission["resolved"]         = False  # not resolved until DM marks outcome
    mission["player_claimer"]   = player_name
    mission["claim_message_id"] = new_msg.id
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
    prompt = _build_mission_prompt(recent)
    text = await _generate(prompt)
    if not text:
        logger.warning("mission_board: generation returned None")
        return

    mission = _parse_mission(text)
    expires_dt = datetime.fromisoformat(mission["expires_at"])
    days_left = (expires_dt - datetime.utcnow()).days

    # Build color-coded embed based on faction reputation
    from src.faction_reputation import get_faction_color, get_faction_tier_label
    faction = mission.get("faction", "")
    embed_color = get_faction_color(faction) if faction else 0xE6C300  # yellow default
    tier_label = get_faction_tier_label(faction) if faction else "😐 Neutral"

    embed = discord.Embed(
        description=text,
        color=embed_color,
    )
    opposing = mission.get("opposing_faction", "")
    footer_parts = [f"Standing: {tier_label}", f"Expires in {days_left}d", "React ⚔️ to claim"]
    if opposing:
        footer_parts.insert(1, f"⚠️ Opposes: {opposing}")
    embed.set_footer(text="  •  ".join(footer_parts))

    msg = await channel.send(embed=embed)
    mission["message_id"] = msg.id
    _add_mission(mission)

    # Add ⚔️ reaction so players see a visible claim button
    try:
        await msg.add_reaction(EMOJI_CLAIM)
    except Exception:
        pass

    opp_log = f", opposes {opposing}" if opposing else ""
    logger.info(f"📋 Mission posted: {mission['title']} (tier: {mission['tier']}, {days_left}d, {tier_label}{opp_log}) — open for party claims in {CLAIM_DAYS_MIN}d")


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
                posted_at = datetime.fromisoformat(mission["posted_at"])
                age_days  = (now - posted_at).total_seconds() / 86400
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
            expires_at = datetime.fromisoformat(mission["expires_at"])
        except Exception:
            continue

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
