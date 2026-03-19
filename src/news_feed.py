"""
news_feed.py — Tower of Last Chance AI-generated hourly bulletin.

Uses mistral locally via Ollama — best prose quality, fully local, no cloud tokens.

Every bulletin is saved to campaign_docs/news_memory.txt so the world
builds continuity over time — stories escalate, rumours contradict,
NPCs react to past events.
"""

from __future__ import annotations

import os
import re
import json
import random
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict

# Global lock — A1111 can only handle one generation at a time
# Uses a wrapper so the lock auto-releases if A1111 hangs for more than 10 minutes
_a1111_lock = asyncio.Lock()
_A1111_LOCK_TIMEOUT = 600  # 10 minutes


class _TimedA1111Lock:
    """Context manager that acquires _a1111_lock with a timeout.
    If A1111 hangs and never releases, the lock auto-expires after _A1111_LOCK_TIMEOUT seconds."""

    async def __aenter__(self):
        try:
            await asyncio.wait_for(_a1111_lock.acquire(), timeout=_A1111_LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            import logging
            logging.getLogger(__name__).error(
                f"🖼️ A1111 lock timed out after {_A1111_LOCK_TIMEOUT}s — forcing release"
            )
            # Force-release the stuck lock so future requests can proceed
            try:
                _a1111_lock.release()
            except RuntimeError:
                pass
            # Now acquire cleanly
            await _a1111_lock.acquire()
        return self

    async def __aexit__(self, *args):
        try:
            _a1111_lock.release()
        except RuntimeError:
            pass  # Already released somehow


a1111_lock = _TimedA1111Lock()  # use this everywhere instead of _a1111_lock directly

from src.tower_economy import (
    tick_towerbay, format_towerbay_bulletin,
    tick_tia, format_tia_bulletin,
)
from src.ec_exchange import tick_exchange, format_exchange_bulletin, format_exchange_line, apply_event_shock, get_rate
from src.dome_weather import tick_weather, format_weather_bulletin, should_post_weather, mark_weather_posted
from src.arena_season import tick_arena
from src.faction_calendar import tick_calendar, format_event_announce, format_event_result
from src.missing_persons import should_post_missing, generate_missing_bulletin, tick_missing_resolutions

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
MISSION_BOARD_FILE = DOCS_DIR / "MISSION_BOARD_DM.txt"
MEMORY_FILE        = DOCS_DIR / "news_memory.txt"
RIFT_STATE_FILE    = DOCS_DIR / "rift_state.json"
NEWS_TYPES_FILE    = DOCS_DIR / "generated_news_types.json"

MAX_MEMORY_ENTRIES = 40   # total entries kept on disk
MEMORY_CONTEXT_ENTRIES = 10  # mistral handles larger context — more history = better continuity

# ---------------------------------------------------------------------------
# Rift state machine
# ---------------------------------------------------------------------------
#
# A Rift goes through stages over many real days:
#   whisper -> tremor -> crack -> open -> critical -> sealed/disaster
#
# Spawn odds per bulletin tick (these are PER TICK, not per day):
#   Warrens:    1.5% chance a new Rift whisper starts
#   Outer Wall: 0.4% chance
#   Anywhere else: 0.1% chance (extremely rare)
#
# Each stage lasts a minimum number of bulletin ticks before it can advance.
# Advancement per tick: 20% chance once minimum ticks are met.
# If no adventurers address it by "open" stage, it advances to critical automatically.
#
# The state file stores all active Rifts. The bulletin system checks it each tick.
# ---------------------------------------------------------------------------

RIFT_STAGES = ["whisper", "tremor", "crack", "open", "critical"]

# Minimum REAL DAYS at each stage before it can advance
# Each stage stores spawned_at / stage_entered_at as ISO timestamps
RIFT_MIN_DAYS = {
    "whisper":  2,   # 2 days of vague unease before anyone notices a pattern
    "tremor":   2,   # 2 days of tremors and Glass Sigil readings
    "crack":    2,   # 2 days of a visible confirmed tear
    "open":     1,   # 1 day — open Rift is urgent, escalates faster
    "critical": 1,   # 1 day — must be sealed or it becomes a disaster
}

# Chance per bulletin tick to advance AFTER minimum days have elapsed
# ~20% per hour-ish tick = typically advances within a few hours of becoming eligible
RIFT_ADVANCE_CHANCE = 0.20

# Spawn chance per bulletin tick by location type (unchanged — these are hourly rolls)
RIFT_SPAWN_CHANCE = {
    "warrens":    0.015,  # 1.5% per tick — Warrens are structurally weak
    "outer_wall": 0.004,  # 0.4% per tick
    "other":      0.001,  # 0.1% per tick — anywhere else is extremely rare
}

# Location pools by type
RIFT_LOCATIONS = {
    "warrens": [
        "Collapsed Plaza", "Echo Alley", "Shantytown Heights",
        "Scrapworks", "Night Pits", "Brother Thane's Cult House area",
    ],
    "outer_wall": [
        "Outer Wall Gate District", "Wall Quadrant C", "Wall Quadrant A",
    ],
    "other": [
        "Cobbleway Market undercroft", "Grand Forum basement level",
        "Sanctum Quarter catacombs", "Guild Spires maintenance tunnels",
    ],
}


def _load_rift_state() -> List[Dict]:
    if not RIFT_STATE_FILE.exists():
        return []
    try:
        return json.loads(RIFT_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_rift_state(rifts: List[Dict]) -> None:
    try:
        RIFT_STATE_FILE.write_text(json.dumps(rifts, indent=2), encoding="utf-8")
    except Exception:
        pass


def _maybe_spawn_rift(rifts: List[Dict]) -> Optional[Dict]:
    """Roll to see if a new Rift whisper starts this tick. Returns new Rift dict or None."""
    # Don't spawn if there are already 2+ active Rifts — the city can only handle so much
    active = [r for r in rifts if not r.get("resolved")]
    if len(active) >= 2:
        return None

    # Roll each location type
    for loc_type, chance in RIFT_SPAWN_CHANCE.items():
        if random.random() < chance:
            location = random.choice(RIFT_LOCATIONS[loc_type])
            # Don't spawn in a location that already has an active Rift
            if any(r.get("location") == location and not r.get("resolved") for r in rifts):
                continue
            return {
                "id":               f"rift_{int(datetime.now().timestamp())}",
                "location":         location,
                "loc_type":         loc_type,
                "stage":            "whisper",
                "stage_entered_at": datetime.now().isoformat(),  # when current stage started
                "resolved":         False,
                "spawned_at":       datetime.now().isoformat(),
                "last_bulletin_stage": None,
            }
    return None


def _tick_rifts(rifts: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    """
    Advance all active Rifts by one bulletin tick.
    Stage advancement is gated on REAL DAYS elapsed since stage_entered_at,
    not tick counts. Once the minimum days have passed, each tick rolls 20%
    to advance — so stages typically move within a few hours of becoming eligible.
    """
    events = []
    now = datetime.now()

    for rift in rifts:
        if rift.get("resolved"):
            continue

        stage = rift["stage"]
        min_days = RIFT_MIN_DAYS.get(stage, 2)

        # Calculate real days elapsed at current stage
        try:
            entered = datetime.fromisoformat(rift["stage_entered_at"])
            days_elapsed = (now - entered).total_seconds() / 86400
        except Exception:
            days_elapsed = 0

        # Emit a bulletin if this stage hasn't been announced yet
        if rift.get("last_bulletin_stage") != stage:
            events.append({"rift": rift, "event": "stage_update"})
            rift["last_bulletin_stage"] = stage

        # Try to advance once minimum real days have elapsed
        if days_elapsed >= min_days and random.random() < RIFT_ADVANCE_CHANCE:
            current_idx = RIFT_STAGES.index(stage)
            if current_idx < len(RIFT_STAGES) - 1:
                rift["stage"]            = RIFT_STAGES[current_idx + 1]
                rift["stage_entered_at"] = now.isoformat()  # reset timer for new stage
            else:
                # Critical stage expired unaddressed — disaster
                rift["resolved"] = True
                rift["outcome"]  = "disaster"
                events.append({"rift": rift, "event": "disaster"})

    return rifts, events


# Stage descriptions for the AI prompt — what the city actually sees/feels
RIFT_STAGE_FLAVOUR = {
    "whisper": (
        "vague unease — animals acting strange, a faint smell of ozone, "
        "one or two residents reporting bad dreams near {location}. "
        "Nothing confirmed. Could be nothing."
    ),
    "tremor": (
        "minor tremors and odd sounds near {location}. "
        "Glass Sigil instruments show faint residue spikes. "
        "A few locals are asking questions. No official response yet."
    ),
    "crack": (
        "a visible hairline tear in reality has appeared near {location}. "
        "Faint light bleeds through it. The Glass Sigil has confirmed it. "
        "Wardens are watching. Nobody's panicking yet but they should be."
    ),
    "open": (
        "an open Rift at {location}. Small monsters have been seen emerging. "
        "The surrounding area is being evacuated. Multiple factions are responding. "
        "This needs adventurers — now."
    ),
    "critical": (
        "a critical, rapidly-expanding Rift at {location}. "
        "The tear is widening. Containment is failing. "
        "If it isn't sealed in the next few hours, the surrounding district will be lost."
    ),
}


async def _generate_rift_bulletin(rift: Dict, event: str) -> Optional[str]:
    """Ask Ollama to write a Rift-stage bulletin grounded in current state."""
    import httpx, logging
    logger = logging.getLogger(__name__)

    from src.ollama_busy import is_available, get_busy_reason
    if not is_available():
        logger.info(f"🌀 Ollama busy ({get_busy_reason()}) — skipping rift bulletin")
        return None

    location  = rift["location"]
    stage     = rift["stage"]
    flavour   = RIFT_STAGE_FLAVOUR.get(stage, "").format(location=location)

    if event == "disaster":
        instruction = (
            f"A Rift at {location} was never sealed and has collapsed into a disaster. "
            f"Write a 3-4 line emergency bulletin. Terse, grim, specific. "
            f"What happened to the immediate area. Who is responding. What is lost."
        )
    else:
        instruction = (
            f"Write a 3-4 line Undercity bulletin about a Rift situation at {location}. "
            f"Current status: {flavour} "
            f"Tone matches the stage — early stages are rumour and unease, "
            f"later stages are alarm and urgency. "
            f"Do NOT over-dramatise early stages. A whisper is just a whisper."
        )

    prompt = f"""{_WORLD_LORE_BRIEF}

{instruction}

RULES:
- Output ONLY the bulletin. No preamble, no sign-off.
- Use Discord markdown. 3-4 lines max.
- Ground it in the specific location and current faction responses appropriate to that stage.
- If your response contains anything other than the bulletin, you have failed."""

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
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
        lines = text.splitlines()
        skip  = ("sure", "here's", "here is", "certainly", "of course", "below is")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        return "\n".join(lines).strip() or None
    except Exception as e:
        logger.error(f"Rift bulletin generation error: {e}")
        return None


def _mark_rift_resolved(rift_id: str, outcome: str = "sealed") -> None:
    """Called externally (e.g. by DM command) when adventurers seal a Rift."""
    rifts = _load_rift_state()
    for r in rifts:
        if r["id"] == rift_id:
            r["resolved"] = True
            r["outcome"]  = outcome
    _save_rift_state(rifts)


_WORLD_LORE_BRIEF = """\
SETTING: The Undercity — a sealed city under a Dome around the Tower of Last Chance.
Rifts are rare tears in reality. Most common in the Warrens (structurally weak districts).
Extremely rare in other districts. They start tiny and escalate over days if ignored.
FACTIONS: Iron Fang Consortium, Argent Blades, Wardens of Ash, Serpent Choir,
Obsidian Lotus, Glass Sigil, Patchwork Saints, Adventurers Guild,
Guild of Ashen Scrolls, Tower Authority, Independent, Brother Thane's Cult.
TONE: Dark urban fantasy. Gritty, specific, grounded."""


async def check_rift_tick(channel=None) -> Optional[str]:
    """
    Called once per bulletin cycle.
    - Rolls for new Rift spawn
    - Advances active Rift stages
    - Returns a bulletin string if a Rift event happened (to be posted alongside or instead of normal bulletin)
    - Returns None if no Rift event this tick
    """
    rifts  = _load_rift_state()
    output = None

    # Maybe spawn a new Rift
    new_rift = _maybe_spawn_rift(rifts)
    if new_rift:
        rifts.append(new_rift)

    # Tick all active Rifts
    rifts, events = _tick_rifts(rifts)
    _save_rift_state(rifts)

    # Generate a bulletin for the first notable event (don't spam multiple per tick)
    if events:
        ev       = events[0]
        bulletin = await _generate_rift_bulletin(ev["rift"], ev["event"])
        if bulletin:
            _write_memory(bulletin)
            output = f"-# 🕰️ {_dual_timestamp()}\n{bulletin}"

    return output


# ---------------------------------------------------------------------------
# TowerBay + TIA cadence tracking
# ---------------------------------------------------------------------------
# We track last-post times in a small JSON sidecar so restarts don't re-flood.

_CADENCE_FILE = DOCS_DIR / "economy_cadence.json"


def _load_cadence() -> Dict:
    if not _CADENCE_FILE.exists():
        return {}
    try:
        return json.loads(_CADENCE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cadence(data: Dict) -> None:
    try:
        _CADENCE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


async def check_towerbay_tick(channel=None) -> Optional[str]:
    """
    Called each bulletin cycle.
    - Always ticks AI bids, player bids, and replaces sold AI items.
    - Posts sold notifications to channel for any player listings that just closed.
    - Posts TowerBay listing board once every 24 hours.
    Returns the board bulletin string if it's time to post, else None.
    """
    from src.player_listings import format_sold_notification

    cadence = _load_cadence()
    now     = datetime.now()

    # Always tick — returns (ai_sold, player_sold)
    _ai_sold, player_sold = await tick_towerbay()

    # Post sold notifications for player listings
    if player_sold and channel:
        for item in player_sold:
            try:
                embed = format_sold_notification(item)
                await channel.send(embed=embed)
            except Exception as e:
                import logging as _log
                _log.getLogger(__name__).warning(f"🏪 Could not post sold notification: {e}")

    last_str = cadence.get("towerbay_last_post")
    if last_str:
        try:
            last = datetime.fromisoformat(last_str)
            if (now - last).total_seconds() < 23 * 3600:  # 23h gate
                return None
        except Exception:
            pass

    cadence["towerbay_last_post"] = now.isoformat()
    _save_cadence(cadence)

    bulletin = format_towerbay_bulletin()
    _write_memory("[TowerBay listing board posted]")
    return bulletin


def check_exchange_tick() -> Optional[str]:
    """
    Called each bulletin cycle.
    - Always ticks the rate (tiny inflation drift).
    - Posts a rate bulletin ONCE per day around midday (11:00-13:00 window).
      Never posts more than once per 20 hours regardless of timing.
    """
    cadence = _load_cadence()
    now     = datetime.now()

    # Always tick the rate every cycle
    tick_exchange()

    # Only post during the midday window (11:00–13:00)
    if not (11 <= now.hour < 13):
        return None

    # Hard gate: never post twice within 20 hours
    last_str = cadence.get("exchange_last_post")
    if last_str:
        try:
            last = datetime.fromisoformat(last_str)
            if (now - last).total_seconds() < 20 * 3600:
                return None
        except Exception:
            pass

    cadence["exchange_last_post"] = now.isoformat()
    _save_cadence(cadence)

    bulletin = format_exchange_bulletin()
    _write_memory("[EC/Kharma exchange rate posted]")
    return f"-# 🕰️ {_dual_timestamp()}\n{bulletin}"


def check_tia_tick() -> Optional[str]:
    """
    Called each bulletin cycle.
    Posts TIA ticker every 4 hours.
    Always ticks sector values regardless of post cadence.
    """
    cadence = _load_cadence()
    now     = datetime.now()

    # Always tick values
    state, event_desc = tick_tia()

    last_str = cadence.get("tia_last_post")
    if last_str:
        try:
            last = datetime.fromisoformat(last_str)
            if (now - last).total_seconds() < 4 * 3600:  # 4h gate
                return None
        except Exception:
            pass

    cadence["tia_last_post"] = now.isoformat()
    _save_cadence(cadence)

    bulletin = format_tia_bulletin(event_desc)
    _write_memory("[TIA market ticker posted]")
    return bulletin


def check_weather_tick() -> Optional[str]:
    """
    Called each bulletin cycle.
    Posts Dome weather report once per 24h.
    Always ticks weather state.
    """
    tick_weather()  # always advance state
    if not should_post_weather():
        return None
    mark_weather_posted()
    bulletin = format_weather_bulletin()
    _write_memory("[Dome weather report posted]")
    # Prepend dual timestamp consistent with all other bulletins
    return f"-# \U0001f570\ufe0f {_dual_timestamp()}\n{bulletin}"


async def check_arena_tick() -> Optional[str]:
    """
    Called each bulletin cycle.
    Posts arena match result when one is due (every 2-3 days).
    """
    bulletin = await tick_arena()
    if bulletin:
        _write_memory("[Arena match result posted]")
        return f"-# 🕰️ {_dual_timestamp()}\n{bulletin}"
    return None


def check_calendar_tick() -> list:
    """
    Called each bulletin cycle.
    Returns list of announcement/result bulletin strings for any due calendar events.
    """
    outputs  = []
    due = tick_calendar()
    for item in due:
        ev = item["event"]
        if item["type"] == "announce":
            text = format_event_announce(ev)
        else:
            text = format_event_result(ev)
        _write_memory(f"[Faction calendar: {item['type']} — {ev['type']}]")
        outputs.append(f"-# 🕰️ {_dual_timestamp()}\n{text}")
    return outputs


async def check_missing_tick() -> list:
    """
    Called each bulletin cycle.
    Posts a missing persons notice when due, and any resolution updates.
    Returns list of bulletin strings.
    """
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    outputs = []

    # Check resolutions first
    resolutions = tick_missing_resolutions()
    for r in resolutions:
        _write_memory("[Missing persons resolution]")
        outputs.append(r)

    # Maybe post a new notice
    if should_post_missing():
        bulletin = await generate_missing_bulletin(ollama_model, ollama_url)
        if bulletin:
            _write_memory("[Missing persons notice posted]")
            outputs.append(bulletin)

    return outputs


# ---------------------------------------------------------------------------
# World lore — concise enough for 3b, rich enough for good output
# ---------------------------------------------------------------------------

_WORLD_LORE = """\
SETTING: The Undercity — a sealed city under a Dome, built around the Tower of Last Chance.
Rifts are rare tears in reality that spawn monsters and warp physics. They are feared events, not routine occurrences.
Adventurers are a recognised economic class: ranked, taxed, tracked, and occasionally harvested by gods.

CURRENCY: Essence Coins (EC) = everyday money. Kharma = crystallised faith, traded and stolen.
Legend Points (LP) = heroic fame. High LP attracts divine attention — and the Culinary Council's hunger.

FACTIONS:
- Iron Fang Consortium (Markets Infinite) — relic/smuggling cartel. Guildmaster Serrik Dhal. Profit is virtue.
- Argent Blades (Guild Spires) — glory adventurer guild. Lady Cerys Valemont. Fame is currency. Arena duels, Rift showcases.
- Wardens of Ash (Outer Wall) — city defenders. Captain Havel Korin. Creed: Hold the Line.
- Serpent Choir (Sanctum Quarter) — divine contract brokers. High Apostle Yzura. Every miracle has a clause.
- Obsidian Lotus (The Warrens) — black-market syndicate. The Widow. Memory erasure, bottled souls, god-tongue ink.
- Glass Sigil — arcane archivists. Senior Archivist Pell. Tracks Rift residue anomalies.
- Patchwork Saints (Warrens) — failed adventurers protecting Warrens residents. Minimal resources, pure principle.
- Adventurers' Guild — quest hub, Rift assignments. Front desk: Mari Fen.
- Guild of Ashen Scrolls (Grand Forum Library) — fate archivists sworn to Thesaurus. Leader: Archivist Eir Velan.
- Tower Authority / FTA — external oversight. Director Myra Kess. Treats adventurers as data points.
- Wizards Tower — arcane academy and research institution. Archmage Yaulderna Silverstreak. Knowledge preservation, responsible magic use, arcane licensing.

GODS:
- Culinary Council — predator deities harvesting heroic souls. Members: Gourmand Prime the Bone King, Mother Mire, The Hollow Waiter.
- Thesaurus — archives all legends. Wants the perfect heroic story.
- Ashara the Phoenix Marshal — war/fire god. Wardens' secret patron. Opposes the Culinary Council.
- Veha the Silent Bloom — god of forgetting. Obsidian Lotus patron.

KEY NPCs: Mara the Scrapper (Scrapworks boss), Brother Thane (cult leader, building something in the Warrens),
Sable (Night Pits boss), Aric Veyne (SS-Rank adventurer, Silver Spire), Magister Liora (FTA Tower liaison),
Kessan & Mira (Grand Forum info brokers, twins), Elune (apothecary owner), Kiva (Hermes shrine scout),
Wex (courier, currently in trouble), Dova (Glass Sigil junior archivist), Lieutenant Varen (Wardens).

DISTRICTS: Markets Infinite (Neon Row, Cobbleway Market, Floating Bazaar, Crimson Alley, Taste of Worlds),
Sanctum Quarter (Pantheon Walk, Hall of Echoes, Divine Garden), Grand Forum (Central Plaza, Adventurer's Inn,
Fountain of Echoes, Rift Bulletin Board), Guild Spires (Arena of Ascendance), The Warrens (Scrapworks,
Brother Thane's Cult House, Night Pits, Echo Alley, Shantytown Heights, Collapsed Plaza), Outer Wall & Gates.

ACTIVE TENSIONS:
- Brother Thane is recruiting aggressively near the Collapsed Plaza. The Saints and Wardens are both watching.
- Serpent Choir internal corruption: financial officer Sevas went missing with a tithe ledger implicating Brother Enn.
- Obsidian Lotus memory-erasure contracts are under FTA scrutiny.
- An independent researcher named Elara Mound has been secretly harvesting a stable Rift seam outside the city.

{LIVE_ROSTER_NPCS}\
"""

# ---------------------------------------------------------------------------
# Mission board parser
# ---------------------------------------------------------------------------

def _parse_mission_board() -> str:
    if not MISSION_BOARD_FILE.exists():
        return ""
    try:
        text = MISSION_BOARD_FILE.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    missions = []
    current_faction = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = re.match(
            r"^(THE GLASS SIGIL|WARDENS OF ASH|PATCHWORK SAINTS|IRON FANG CONSORTIUM"
            r"|ARGENT BLADES|OBSIDIAN LOTUS|SERPENT CHOIR|ADVENTURERS' GUILD"
            r"|NEUTRAL FACTIONS)$", line,
        )
        if m:
            current_faction = line.title()
        h = re.match(r"^---\s*(?:PERSONAL MISSION|MISSION):\s*(.+?)\s*---$", line)
        if h:
            name = h.group(1).strip()
            loc = ""
            for j in range(i + 1, min(i + 12, len(lines))):
                l = lines[j].strip()
                if l.startswith("Location:"):
                    loc = l[9:].strip()
                    break
            missions.append(f"- [{current_faction}] {name}" + (f" @ {loc}" if loc else ""))
        i += 1

    return ("OPEN MISSIONS:\n" + "\n".join(missions)) if missions else ""


# ---------------------------------------------------------------------------
# Memory read / write
# ---------------------------------------------------------------------------

def _read_memory() -> List[str]:
    if not MEMORY_FILE.exists():
        return []
    try:
        text = MEMORY_FILE.read_text(encoding="utf-8", errors="ignore")
        entries = [e.strip() for e in text.split("\n---ENTRY---\n") if e.strip()]
        return entries[-MAX_MEMORY_ENTRIES:]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Dual timestamp: real-world date + Tower time (year offset +10 from 2026 = 2036)
# ---------------------------------------------------------------------------

TOWER_YEAR_OFFSET = 10  # 2026 real = 2036 Tower


def _dual_timestamp() -> str:
    """Returns a dual timestamp string: real date alongside Tower calendar date."""
    now = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    real_str  = now.strftime("%Y-%m-%d %H:%M")
    tower_str = tower.strftime("%d %b %Y, %H:%M")
    return f"{real_str} │ Tower: {tower_str}"


# ---------------------------------------------------------------------------
# Fact extractor — imported from src.memory_strip
# ---------------------------------------------------------------------------
from src.memory_strip import strip_to_facts as _strip_to_facts

# ---------------------------------------------------------------------------
# LEGACY — Fact extractor — strips emojis, decorative markdown, and narrative fluff
# from bulletin text before storing in memory.  The memory file is read back
# as context for future bulletin generation, so keeping it lean and factual
# improves continuity and prevents the model from echoing filler phrases.
# ---------------------------------------------------------------------------

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"  # dingbats
    "\U000024C2-\U0001F251"
    "\U0000FE0F"             # variation selector
    "\U0000200D"             # zero width joiner
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002B50-\U00002B55"
    "\U0000231A-\U0000231B"
    "\U000023CF"
    "\U000023E9-\U000023F3"
    "\U000023F8-\U000023FA"
    "]+", flags=re.UNICODE
)

_FLUFF_PATTERNS = [
    # Rhetorical question closers
    re.compile(r"Will\s+.{10,120}\?", re.IGNORECASE),
    # "The city watches" / "The people watch/whisper" family
    re.compile(r"The city watches[,.]?\s*", re.IGNORECASE),
    re.compile(r"The people (?:watch|whisper)[^.]*\.\s*", re.IGNORECASE),
    # "whispers of X ripple/mingle/fill"
    re.compile(r"[Ww]hispers of [^.]{5,80}(?:ripple|mingle|fill)[^.]*\.\s*"),
    # "a (tense|hushed|eerie) (hush|silence|pall) (descends|falls|hangs)"
    re.compile(r"[Aa]\s+(?:tense|hushed|eerie|chilling)\s+(?:hush|silence|pall)\s+(?:descends|falls|hangs)[^.]*\.\s*"),
    # eye-reflecting / flickering / narrowing filler
    re.compile(r",?\s*(?:their|her|his) eyes (?:reflecting|flickering|narrowing)[^.]*", re.IGNORECASE),
    # casting eerie shadows
    re.compile(r",?\s*casting\s+(?:eerie|long|dark)\s+shadows[^.]*", re.IGNORECASE),
    # "a frown creasing his/her brow"
    re.compile(r",?\s*a frown creasing (?:his|her) brow", re.IGNORECASE),
    # TNN sign-offs
    re.compile(r"-#\s*\*.*?(?:TNN|Undercity source|Ashen Scrolls|Grand Forum).*?\*\s*$", re.MULTILINE),
    # Decorator lines: "**Undercity Dispatch**" etc.
    re.compile(r"^\*\*(?:Undercity Dispatch|Tower Authority Alert|Mystic's Mysteries)[^*]*\*\*\s*$", re.MULTILINE),
    # Standalone bold lines (leftover location headers after emoji strip)
    re.compile(r"^\*\*[^*]{3,60}\*\*\s*$", re.MULTILINE),
    # Standalone italic lines (leftover titles)
    re.compile(r"^\*[^*]{5,100}\*\s*$", re.MULTILINE),
    # "As the sun sets / As dawn breaks" openers
    re.compile(r"As the (?:sun|moon|dawn|dusk)[^,]{5,60},\s*", re.IGNORECASE),
    # "A (loud|deafening|heated) X echoes/erupts"
    re.compile(r"A (?:loud|deafening)\s+\w+\s+echoes[^.]*\.\s*", re.IGNORECASE),
]


def _strip_to_facts_legacy(text: str) -> str:
    """LEGACY — superseded by src.memory_strip.strip_to_facts (imported above).
    Kept for reference only. Not called."""

    # Short-circuit for system tags like [TowerBay listing board posted]
    stripped = text.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped

    # 1. Strip emojis
    text = _EMOJI_RE.sub("", text)

    # 2. Strip fluff patterns
    for pat in _FLUFF_PATTERNS:
        text = pat.sub("", text)

    # 3. Clean up leftover whitespace / empty lines
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line in ("**", "*", "---", "\u2014"):
            continue
        line = re.sub(r"  +", " ", line)
        lines.append(line)

    result = " ".join(lines).strip()
    result = re.sub(r"  +", " ", result)
    # Remove orphaned leading commas/periods
    result = re.sub(r"^[,.\s]+", "", result)
    if result and not result.endswith("."):
        result += "."
    return result


def _write_memory(bulletin: str) -> None:
    entries = _read_memory()
    cleaned = _strip_to_facts(bulletin)
    if not cleaned or cleaned == ".":
        return  # nothing factual to store
    entries.append(f"[{_dual_timestamp()}]\n{cleaned}")
    entries = entries[-MAX_MEMORY_ENTRIES:]
    try:
        MEMORY_FILE.write_text("\n---ENTRY---\n".join(entries), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TNN / affiliate sign-off pool
# ---------------------------------------------------------------------------

_TNN_SIGN_OFFS = [
    "-# *— Tower News Network (TNN)*",
    "-# *— Filed by TNN, your Undercity source*",
    "-# *— A TNN Undercity Report*",
    "-# *— TNN Field Correspondent*",
    "-# *— In association with the Grand Forum Public Record*",
    "-# *— Certified accurate by the Guild of Ashen Scrolls*",
    "-# *— A joint report: TNN & the Adventurers' Guild Dispatch*",
    "-# *— Undercity Dispatch, powered by TNN*",
    "-# *— Paid notice — Grand Forum Public Affairs Office*",
    "-# *— TNN investigative desk*",
]


def _apply_tnn_signoff(bulletin: str) -> str:
    """
    Append a random TNN/affiliate sign-off line to the bulletin
    if one is not already present.
    """
    lower = bulletin.lower()
    if any(tag in lower for tag in ("tnn", "tower news network", "undercity dispatch", "ashen scrolls", "grand forum public")):
        return bulletin  # model already added one — leave it
    return bulletin + "\n" + random.choice(_TNN_SIGN_OFFS)


_BULLETIN_TYPES = [
    # ---- HARD NEWS (common) ----
    "a breaking news story or district happening",
    "a breaking news story or district happening",
    "guild political gossip or High Council drama",
    "guild political gossip or High Council drama",
    "a crime report or public incident in a specific district",
    "a crime report or public incident in a specific district",
    "a street-level rumour overheard in the Warrens or Markets Infinite",
    "a street-level rumour overheard in the Warrens or Markets Infinite",
    "a street trader's complaint about prices or scarcity of a specific Undercity good",
    "a report on how a faction's recent decisions are affecting Undercity commerce",

    # ---- FACTION / GUILD NEWS ----
    "a Tower Authority notice or FTA bureaucratic update",
    "a trade or black market price update from the Obsidian Lotus or Iron Fang",
    "a religious or divine contract announcement from the Serpent Choir",
    "a divine rumour or god-related observation",
    "an arena result or Argent Blades event update",
    "a wanted notice or bounty posting",
    "a spotlight on one of the open mission board contracts",
    "a weather or environmental hazard report affecting a specific district",

    # ---- HUMAN INTEREST (new) ----
    "a human interest piece about a struggling Warrens resident — a vendor, craftsperson, parent, or survivor with a specific small story",
    "a human interest piece about a strange or heartwarming moment witnessed in Markets Infinite or Grand Forum",
    "a community notice — a local event, a missing pet, a neighbourhood dispute, something small and real",
    "an oddity or curiosity — something weird found in the city that has no obvious explanation, treated as local colour not catastrophe",
    "a profile of a minor unnamed Undercity figure — a street performer, a cook, a beggar with a reputation, a child who keeps showing up in the wrong places",
    "a letter to the Dispatch from an anonymous Undercity resident with a complaint, observation, or plea",

    # ---- INTER-NPC CONFLICT ----
    # IMPORTANT: These are NOT added here. They are built dynamically in _build_prompt()
    # using only currently ALIVE roster NPCs, so dead NPCs are never named in conflict prompts.
    # See _build_prompt() for the dynamic injection logic.
    # NOTE: Rift bulletins are NOT generated from this list.
    # They are driven entirely by the Rift state machine in check_rift_tick().
    # TowerBay and TIA are also NOT in this list — they have their own cadence.
    # Do not add Rift/TowerBay/TIA types here.
]


# ---------------------------------------------------------------------------
# Dynamic news type generation (runs daily)
# ---------------------------------------------------------------------------

def _load_generated_news_types() -> List[str]:
    """Load AI-generated bulletin types from disk."""
    if not NEWS_TYPES_FILE.exists():
        return []
    try:
        data = json.loads(NEWS_TYPES_FILE.read_text(encoding="utf-8"))
        return data.get("types", [])
    except Exception:
        return []


def _save_generated_news_types(types: List[str], generated_date: str) -> None:
    try:
        NEWS_TYPES_FILE.write_text(
            json.dumps({"generated_date": generated_date, "types": types}, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass


def _needs_new_news_types() -> bool:
    """Returns True if news types file is missing or was generated on a previous UTC day."""
    if not NEWS_TYPES_FILE.exists():
        return True
    try:
        data = json.loads(NEWS_TYPES_FILE.read_text(encoding="utf-8"))
        last = data.get("generated_date", "")
        return last != datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return True


async def refresh_news_types_if_needed() -> None:
    """Called at startup and hourly. Generates 10 new bulletin type seeds if stale."""
    import httpx, logging
    logger = logging.getLogger(__name__)

    if not _needs_new_news_types():
        return

    # Inject live roster into world lore for news type generation too
    world_lore = _WORLD_LORE.replace("{LIVE_ROSTER_NPCS}", _build_live_roster_block())
    prompt = f"""{world_lore}

---
You are expanding the Undercity Dispatch's bulletin variety.
Generate exactly 10 new bulletin topic seeds for today's news cycle.

These are SEEDS that tell an AI what kind of story to write — not full bulletins.
Each should be a short description of a story TYPE or ANGLE, specific to today's feel.

RULES:
- Each entry is 1 sentence describing what the bulletin covers
- Must be grounded in the Undercity setting — factions, districts, economy, NPCs
- Do NOT generate Rift bulletins (handled separately by the Rift state machine)
- Do NOT generate TowerBay or TIA market bulletins (those have their own cadence)
- Vary the tone: some street-level, some political, some supernatural, some economic, some human interest
- Make them feel current — what would be on people's lips in the Undercity TODAY
- No numbering, no bullets, no preamble, no sign-off. Output exactly 10 plain-text lines, one per seed.
- If your output contains anything other than 10 lines, you have failed."""

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
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
        new_types = [l.strip() for l in text.splitlines() if l.strip()][:10]
        if not new_types:
            logger.warning("news_feed: daily news type generation returned empty")
            return
        today = datetime.now().strftime("%Y-%m-%d")
        _save_generated_news_types(new_types, today)
        logger.info(f"📰 Generated {len(new_types)} new news types for {today}")
    except Exception as e:
        logger.error(f"refresh_news_types_if_needed error: {e}")


NPC_ROSTER_FILE = DOCS_DIR / "npc_roster.json"


def _load_live_roster() -> List[Dict]:
    """Load all alive/injured NPCs from npc_roster.json.
    Dead NPCs are excluded (they live in npc_graveyard.json)."""
    if not NPC_ROSTER_FILE.exists():
        return []
    try:
        npcs = json.loads(NPC_ROSTER_FILE.read_text(encoding="utf-8"))
        return [n for n in npcs if n.get("status") in ("alive", "injured")]
    except Exception:
        return []


def _build_live_roster_block(max_npcs: int = 12) -> str:
    """Build a dynamic ROSTER NPCs block from the live roster for prompt injection.
    Samples a mix: prioritise NPCs with secrets, alliances, or recent history,
    then fill remaining slots randomly. Returns formatted string."""
    alive = _load_live_roster()
    if not alive:
        return "ROSTER NPCs: No active roster NPCs available."

    # Prioritise interesting NPCs (have secrets, revealed secrets, or recent events)
    interesting = []
    mundane = []
    for n in alive:
        has_secret   = bool(n.get("secret"))
        has_revealed = bool(n.get("revealed_secrets"))
        has_history  = len(n.get("history", [])) > 2
        if has_secret or has_revealed or has_history:
            interesting.append(n)
        else:
            mundane.append(n)

    random.shuffle(interesting)
    random.shuffle(mundane)
    chosen = (interesting + mundane)[:max_npcs]

    lines = ["ROSTER NPCs (LIVE from city records — use for conflict/drama pieces — do NOT kill them in bulletins):"]
    for n in chosen:
        name    = n.get("name", "Unknown")
        species = n.get("species", "?")
        faction = n.get("faction", "Independent")
        rank    = n.get("rank", "")
        loc     = n.get("location", "")
        role    = n.get("role", "")
        status  = n.get("status", "alive")
        # Build a one-liner like the old hardcoded format
        desc_parts = []
        if role:
            desc_parts.append(role.rstrip("."))
        if n.get("motivation"):
            # Just the first sentence of motivation
            mot = n["motivation"].split(".")[0].strip()
            if mot:
                desc_parts.append(mot)
        desc = "; ".join(desc_parts) if desc_parts else "active in the city"
        status_tag = " [INJURED]" if status == "injured" else ""
        loc_tag    = f", {loc.split(',')[0].strip()}" if loc else ""
        lines.append(
            f"- {name} ({species}, {faction}, {rank}{loc_tag}){status_tag} — {desc}"
        )
    return "\n".join(lines)


def _get_alive_roster_names() -> List[str]:
    """Return just the names of all alive NPCs from the live roster."""
    return [n.get("name", "") for n in _load_live_roster() if n.get("name")]


def _load_npc_status_blocks() -> tuple[str, str, list, list]:
    """
    Returns (deceased_block, injured_block, injured_names, dead_names) for bulletin prompt injection.
    Pulls from npc_roster.json so the AI never writes about dead NPCs as if alive,
    and can reference currently injured NPCs by name in dynamic bulletin types.
    """
    npc_file = DOCS_DIR / "npc_roster.json"
    if not npc_file.exists():
        return "", "", [], []
    try:
        npcs = json.loads(npc_file.read_text(encoding="utf-8"))
    except Exception:
        return "", "", [], []
    dead    = [n["name"] for n in npcs if n.get("status") == "dead"    and n.get("name")]
    injured = [n["name"] for n in npcs if n.get("status") == "injured" and n.get("name")]
    deceased_block = (
        f"CRITICAL — DECEASED NPCs. These people are DEAD. DO NOT write about them as if alive, present, "
        f"or active in any way. Do not quote them, do not have sources 'close to' them, "
        f"do not reference their current actions or opinions. They are gone: {', '.join(dead)}"
        if dead else ""
    )
    injured_block = (
        f"INJURED — These NPCs are currently injured and out of action: {', '.join(injured)}"
        if injured else ""
    )
    return deceased_block, injured_block, injured, dead


def _load_party_bulletin_context() -> tuple:
    """
    Load 1-3 random generated party profiles for bulletin prompt injection.
    Returns (party_context_block: str, parties: list[dict]).
    Only uses profiles where generated=True so the AI always has real names/members.
    """
    try:
        from src.party_profiles import PARTY_PROFILE_DIR
        import json as _json
        profiles = []
        for f in PARTY_PROFILE_DIR.glob("*.json"):
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                if data.get("generated") and data.get("name") and data.get("members"):
                    profiles.append(data)
            except Exception:
                pass
        if not profiles:
            return "", []
        chosen = random.sample(profiles, min(3, len(profiles)))
        lines = ["KNOWN ADVENTURER PARTIES (real parties -- use for party-focused bulletins):"]
        for p in chosen:
            tier    = p.get("tier", "Unknown")
            affil   = p.get("affiliation", "No Affiliation")
            spec    = p.get("specialty", "")
            rep     = p.get("reputation_note", "")
            members = p.get("members", [])
            mline   = " | ".join(
                f"{m['name']} ({m.get('role','?')}, {m.get('species','?')})"
                for m in members
            )
            lines.append(f"  PARTY: {p['name']}  [{tier} rank | {affil}]")
            if spec:
                lines.append(f"    Specialty: {spec}")
            if mline:
                lines.append(f"    Members: {mline}")
            for m in members:
                if m.get("note"):
                    lines.append(f"    {m['name']}: {m['note']}")
            if rep:
                lines.append(f"    City reputation: {rep}")
        return "\n".join(lines), chosen
    except Exception:
        return "", []


def _build_prompt(memory_entries: List[str]) -> str:
    # Combine hardcoded types with today's AI-generated types
    all_types = _BULLETIN_TYPES + _load_generated_news_types()
    mission_block = _parse_mission_board()

    try:
        live_rate = get_rate()
        economy_note = (
            f"\nCURRENT ECONOMY: 1 Kharma = {live_rate:.2f} EC (Kharma is the premium currency — very valuable). "
            f"CRITICAL RULE: Do NOT include any exchange rate listing in this bulletin. "
            f"DO NOT write lines like '1 EC: X Kharma', '1 Kharma = X EC', 'New Essence Coin prices', or any rate table. "
            f"Exchange rates are posted as a SEPARATE bulletin. Your bulletin must not contain them AT ALL. "
            f"If you mention prices, use specific EC amounts for goods only (e.g. '50 EC for a potion'). "
            f"NEVER write a rate table or rate block. If your output contains a rate table, you have failed."
        )
    except Exception:
        economy_note = ""

    recent_block = ""
    if memory_entries:
        recent = memory_entries[-MEMORY_CONTEXT_ENTRIES:]
        recent_block = "\nRECENT BULLETINS (you may follow up, escalate, or contradict these):\n" + "\n\n".join(recent)

    deceased_block, injured_block, injured_names, dead_names = _load_npc_status_blocks()
    npc_status_block = ""
    if deceased_block:
        npc_status_block += f"\n{deceased_block}"
    if injured_block:
        npc_status_block += f"\n{injured_block}"

    if injured_names:
        name_list = ", ".join(injured_names)
        spotlight = random.choice(injured_names)
        all_types += [
            f"a street-level update on the condition of an injured Undercity figure — "
            f"pick one of these currently injured people: {name_list} — "
            f"rumours about whether they'll recover, who's visiting, what faction politics swirl around their injury",
            f"a follow-up on {spotlight}, who was recently injured — "
            f"someone saw them, heard something, or their faction is making moves because of their absence",
            f"a recovery notice or setback report for one of these injured individuals: {name_list} — "
            f"could be good news or bad, keep it ambiguous and grounded",
        ]

    alive_roster = _get_alive_roster_names()
    if len(alive_roster) >= 2:
        # Pick a random subset for conflict bulletin types (don't always use the same NPCs)
        conflict_pool = random.sample(alive_roster, min(8, len(alive_roster)))
        roster_list = ", ".join(conflict_pool)
        risky_roster = random.sample(conflict_pool, min(4, len(conflict_pool)))
        risky_list = ", ".join(risky_roster) if risky_roster else roster_list
        all_types += [
            f"an altercation or public dispute involving one of these specific NPCs (pick one who fits): "
            f"{roster_list} — the dispute should be faction-relevant and could leave them shaken, "
            f"embarrassed, or lightly injured",
            f"a rumour or witnessed confrontation between two of these NPCs (pick two who have reason to clash): "
            f"{roster_list} — make it specific, grounded in their faction tensions, and leave the outcome ambiguous",
            f"a report that one of these NPCs was involved in something dangerous and may have been hurt: "
            f"{risky_list} — keep it ambiguous enough that their actual status (injured/fine) is unclear until confirmed",
        ]

    party_context_block, party_list = _load_party_bulletin_context()
    if party_list:
        for p in party_list:
            pname   = p.get("name", "a party")
            affil   = p.get("affiliation", "No Affiliation")
            spec    = p.get("specialty", "their work")
            members = p.get("members", [])
            named   = [m["name"] for m in members[:2]] if members else []
            named_str = named[0] if len(named) == 1 else (
                f"{named[0]} or {named[1]}" if len(named) >= 2 else pname
            )
            member_roles = {m["name"]: m.get("role", "member") for m in members}
            all_types += [
                f"a street sighting or overheard off-duty moment involving a member of {pname} "
                f"({affil}) — something personal or out of character for their reputation. "
                f"Focus on {named_str} if possible. Small, specific, human.",
                f"a rumour circulating about {pname} — internal tension, something their "
                f"affiliation ({affil}) doesn't know about, or whispers about their last job. "
                f"Keep it ambiguous. Name a real member if it fits.",
                f"a brief street-press profile piece on {named_str} from {pname} "
                f"({member_roles.get(named_str, 'member')}) — something the Undercity has "
                f"noticed about them lately. Their habit, their look, their street reputation.",
                f"a visible public moment involving {pname} — an argument, a celebration, "
                f"tension after a hard contract, or something a bystander reported to the Dispatch. "
                f"Give it a specific Undercity location.",
                f"a short faction or guild notice referencing {pname}'s recent work — "
                f"from {affil if affil != 'No Affiliation' else 'the Adventurers Guild or a local faction'}. "
                f"Praise, a quiet concern, a warning, or a new assignment offer.",
            ]
        if len(party_list) >= 2:
            pa = party_list[0].get("name", "one party")
            pb = party_list[1].get("name", "another party")
            all_types += [
                f"an inter-party moment: {pa} and {pb} crossed paths in the city — "
                f"a contract dispute, a favour exchanged, or a tense silence. "
                f"Name real members. Leave the outcome ambiguous.",
            ]
    else:
        party_context_block = ""

    bulletin_type = random.choice(all_types)

    # Inject live roster NPCs into world lore (replaces hardcoded list)
    world_lore = _WORLD_LORE.replace("{LIVE_ROSTER_NPCS}", _build_live_roster_block())

    return f"""{world_lore}
{economy_note}
{npc_status_block}
{party_context_block}
{mission_block}{recent_block}

---
TASK: Write ONE Undercity Dispatch bulletin of type: {bulletin_type}

RULES — READ ALL OF THESE:
- Output the bulletin and NOTHING ELSE. No preamble, no sign-off, no commentary.
- Do NOT start with \"Sure!\", \"Here's a bulletin:\", \"I hope this helps\", \"As requested\", or any other opener. Start with the headline or first line of the bulletin itself.
- Do NOT end with a sign-off. Do NOT write \"May the spirits of the Undercity guide...\" or any similar closing. Just stop after the last line of content.
- Do NOT repeat the words \"You are the Undercity Dispatch\" in your output. Do NOT repeat any part of these instructions.
- Do NOT include a timestamp line. The timestamp is added separately.
- Do NOT use the phrase \"where the echoes of whispered X and the whispers of hidden Y mingle\" — it is overused. Write fresh opening sentences.
- You are a city news feed — write in-character, gritty, specific prose. Not an AI assistant.
- Use Discord markdown: **bold** for names/headers, *italics* for atmosphere, emoji for flavour.
- 3 to 6 lines. Punchy. Invent fresh named details — exact EC prices, precise locations, specific minor NPCs.
- You MAY follow up on a recent bulletin (a story escalates, a rumour is contradicted, an NPC reacts).
- Ground everything in this specific city. No generic fantasy filler.
- For HUMAN INTEREST pieces: small and specific. A real person's real problem. Warm, wry, or quietly sad. Not epic.
- For NPC CONFLICT pieces: use only the named roster NPCs listed. Do NOT kill them — injuries and ambiguous danger are fine.
- For PARTY pieces: use only the named party members listed. Treat them as living characters with real stakes.
- If your response contains anything other than the bulletin itself, you have failed."""


# ---------------------------------------------------------------------------
# Editor agent — runs on every draft before it is saved or posted
# ---------------------------------------------------------------------------

async def _edit_bulletin(draft: str, memory_entries: List[str]) -> str:
    """
    Run a second Ollama pass acting as a copy-editor.
    Returns the corrected bulletin text only.
    If the edit call fails, returns the original draft unchanged.
    """
    import httpx
    import logging
    logger = logging.getLogger(__name__)

    context_entries = memory_entries[-6:] if memory_entries else []
    context_block   = ""
    if context_entries:
        context_block = "RECENT BULLETIN HISTORY (for continuity checking):\n" + "\n\n".join(context_entries)

    editor_prompt = f"""You are the copy-editor for the Undercity Dispatch, a dark fantasy city news feed.

Your job is to review and correct a bulletin draft before it is published.

CHECK FOR:
1. Grammar and spelling errors — fix them silently.
2. Voice / tone — the Dispatch is gritty, specific, in-world. Remove any AI assistant phrasing
   (e.g. "It is worth noting", "In conclusion", "I hope this helps", sign-offs, preambles).
3. Continuity errors — check against the RECENT BULLETIN HISTORY below.
   If the draft contradicts a recent established fact (e.g. an NPC is dead, a location is sealed,
   an event already resolved), rewrite that sentence to avoid the contradiction.
   If a named NPC from history is mentioned differently (wrong faction, wrong role), correct it.
4. Formatting — the bulletin should use Discord markdown: **bold** for names/headers,
   *italics* for atmosphere, emoji on the headline. Do not add or remove emojis unnecessarily.
5. Length — the bulletin should be 3-6 lines. If it is shorter or longer, lightly trim or expand
   to fit, but do not change the core story.

{context_block}

DRAFT TO REVIEW:
{draft}

INSTRUCTIONS:
- Output ONLY the corrected bulletin. No preamble, no explanation, no sign-off, no commentary.
- If the draft is already correct, output it unchanged.
- Do NOT change the story or invent new facts. Only fix errors and voice issues.
- Do NOT add a timestamp line.
- If your output contains anything other than the corrected bulletin, you have failed."""

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": [{"role": "user", "content": editor_prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()

        edited = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                edited = msg.get("content", "").strip()

        lines = edited.splitlines()
        skip  = ("sure", "here's", "here is", "certainly", "of course",
                 "below is", "as requested", "i hope", "absolutely")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        while lines and lines[-1].lower().strip().startswith(("note:", "changes", "edits", "i ")):
            lines.pop()
        edited = "\n".join(lines).strip()

        if edited:
            logger.info("✏️ Editor agent: bulletin reviewed and corrected")
            return edited

    except Exception as e:
        logger.warning(f"✏️ Editor agent failed: {e} — using original draft")

    return draft  # fallback: original unchanged


# ---------------------------------------------------------------------------
# Death honorific post-processor
# ---------------------------------------------------------------------------

_DEATH_CONTEXT = re.compile(
    r'\b(?:the\s+late|fallen|deceased|dead|death\s+of|memory\s+of|late|passed|killed|murdered|gone|lost)\b',
    re.IGNORECASE,
)


def _apply_death_honorifics(bulletin: str, dead_names: list) -> str:
    """
    For any dead NPC whose name appears in a bulletin without nearby death context,
    prepend 'the late' before their name (first occurrence only).
    """
    for name in sorted(dead_names, key=len, reverse=True):  # longest first avoids partial matches
        if name not in bulletin:
            continue
        def _replace(m: re.Match) -> str:
            start   = max(0, m.start() - 60)
            context = bulletin[start:m.start()]
            if _DEATH_CONTEXT.search(context):
                return m.group(0)
            return f"the late {name}"
        bulletin = re.sub(re.escape(name), _replace, bulletin, count=1)
    return bulletin


# ---------------------------------------------------------------------------
# Main async generator
# ---------------------------------------------------------------------------

async def generate_bulletin() -> Optional[str]:
    """
    Generate a fresh bulletin via local Ollama.
    Saves result to news_memory.txt. Returns the bulletin string or None.
    """
    memory = _read_memory()
    prompt = _build_prompt(memory)

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    try:
        import httpx, re as _re
        payload = {
            "model": ollama_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(ollama_url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        bulletin = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                bulletin = msg.get("content", "").strip()

        if bulletin:
            lines = bulletin.splitlines()
            skip_phrases = ("sure", "here's", "here is", "as requested", "certainly", "of course", "i hope", "below is")
            while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip_phrases):
                lines.pop(0)

            _rate_patterns = [
                r'^\**new essence coin prices',
                r'^\d+\s*(kharma|ec)\s*[=:]',
                r'^`\d+\s*(kharma|ec)',
                r'kharma\s*=\s*[\d,.]+\s*ec',
                r'[\d,.]+\s*ec\s*[=:]\s*[\d,.]+\s*kharma',
                r'^-#.*exchange rate',
                r'^\d[\d,.]*(\s*ec|\s*essence coins?)\s+(for|to|gets?|buys?)',
                r'(for only|costs?|price:|pay)\s+\d[\d,.]*\s*(ec|essence coins?)',
            ]
            filtered = []
            for ln in lines:
                ln_lower = ln.lower().strip()
                if any(_re.search(pat, ln_lower) for pat in _rate_patterns):
                    continue
                filtered.append(ln)
            while filtered and not filtered[-1].strip():
                filtered.pop()
            bulletin = "\n".join(filtered).strip()

        if bulletin:
            bulletin = _re.sub(
                r'[,.]?\s*\d[\d,.]*\s*(?:ec|essence coins?)\s+(?:for|to|gets?|buys?)[^.\n]*',
                '',
                bulletin,
                flags=_re.IGNORECASE,
            ).strip()

        if bulletin:
            echo_cut = _re.search(
                r'\n\s*---\s*\n+(?:you are the undercity dispatch|task:|write one undercity)',
                bulletin, _re.IGNORECASE
            )
            if echo_cut:
                bulletin = bulletin[:echo_cut.start()].strip()

            _ts_lines = bulletin.splitlines()
            while _ts_lines and _re.match(
                r'^-?#?\s*\d{4}-\d{2}-\d{2} \d{2}:\d{2}', _ts_lines[0].strip()
            ):
                _ts_lines.pop(0)
            bulletin = '\n'.join(_ts_lines).strip()

            bulletin = _re.sub(r'(\w[\w\s\']{0,40}?)\(#\)', r'\1', bulletin)
            bulletin = _re.sub(r'\[([^\]\[]{1,80})\]\((?!https?://)[^)]*\)', r'\1', bulletin)
            bulletin = _re.sub(
                r'\[([^\]\[]{1,80})\](?!\()',
                lambda m: m.group(1) if not _re.match(r'\d{4}-\d{2}-\d{2}', m.group(1)) else m.group(0),
                bulletin
            )

        if bulletin:
            _, _, _, dead_names = _load_npc_status_blocks()
            if dead_names:
                bulletin = _apply_death_honorifics(bulletin, dead_names)

        if bulletin:
            bulletin = _apply_tnn_signoff(bulletin)

        if bulletin:
            bulletin = await _edit_bulletin(bulletin, memory)

        if bulletin:
            _cta_pats = [
                r'(?i)^.*(?:awaits you|await you|join us|come find us|seek us|look for us)',
                r'(?i)^.*(?:the undercity awaits|the city awaits|the tower awaits)',
                r'(?i)^.*(?:may the (?:spirits|gods|shadows|city)|may fortune|may your path)',
            ]
            _bl = bulletin.splitlines()
            _bl = [ln for ln in _bl if not any(_re.match(p, ln.strip()) for p in _cta_pats)]
            while _bl and not _bl[-1].strip():
                _bl.pop()
            bulletin = '\n'.join(_bl).strip()

        if bulletin:
            _bl = bulletin.splitlines()
            _content_lns, _footer = [], None
            for ln in _bl:
                if ln.strip().startswith('-#'):
                    _footer = ln
                else:
                    _content_lns.append(ln)
            _content_lns = _content_lns[:8]
            while _content_lns and not _content_lns[-1].strip():
                _content_lns.pop()
            if _footer:
                _content_lns.append(_footer)
            bulletin = '\n'.join(_content_lns).strip()

        if bulletin:
            _write_memory(bulletin)
            return f"-# \U0001f570\ufe0f {_dual_timestamp()}\n{bulletin}"

    except Exception as e:
        import logging, traceback
        logging.getLogger(__name__).error(
            f"\U0001f4f0 news_feed error: {type(e).__name__}: {e}\n{traceback.format_exc()}"
        )

    return None


# ---------------------------------------------------------------------------
# Story image generation via A1111
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# District aesthetic descriptions — used by the image prompt builder.
# The Undercity is a MODERN underground city, not a medieval dungeon.
# ---------------------------------------------------------------------------

_DISTRICT_AESTHETICS = {

    "neon row": (
        "narrow underground commercial street absolutely choked with competing signage — "
        "neon tubes in a dozen scripts, holographic price-boards flickering over vendor stalls, "
        "corrugated awnings layered so thick they block the ceiling entirely, "
        "LED strip lights strung between exposed copper pipe runs, "
        "vendor carts wheel-to-wheel on cracked asphalt, "
        "steam from food stalls mixing with incense smoke, faction recruiters working the crowd, "
        "every column plastered in overlapping handbills and faction stickers"
    ),
    "cobbleway market": (
        "wide underground market boulevard, old cobblestones half-buried under poured asphalt patches, "
        "two-storey market stalls built from salvaged scaffolding and corrugated sheeting, "
        "fluorescent tube banks bolted to the low concrete ceiling casting cool white light, "
        "faction graffiti tags covering every pillar from floor to ceiling in layers, "
        "hawkers shouting prices, couriers weaving between shoppers on electric cargo bikes, "
        "apothecary signs and pawn shop neon sitting side by side"
    ),
    "floating bazaar": (
        "underground market built entirely on connected wooden platforms and suspension bridges "
        "over a vast still black lake, concrete dome ceiling above invisible in the dark, "
        "paper lanterns and waterproof LED buoys strung between platform poles, "
        "their light reflecting in broken ripples on the water below, "
        "market stalls crammed between concrete support pylons rising from the lake, "
        "mist drifting off the water surface, the creak of rope bridges underfoot, "
        "smell of river fish and hot metal, gondola traders pulling between platforms"
    ),
    "crimson alley": (
        "tight underground back-alley, three storeys of crumbling brick and concrete on either side "
        "covered floor-to-ceiling in overlapping faction tags and illicit advertisements, "
        "red neon signage from basement gambling dens bleeding upward through iron grate floors, "
        "heavy steam from underground vents filling the upper half of the alley in red-tinted fog, "
        "rusted fire-escape ladders bolted to the walls, broken pavement, "
        "Iron Fang Consortium enforcers visible at both ends watching who passes"
    ),
    "taste of worlds": (
        "underground food district, ceiling hung with hundreds of paper lanterns and neon signs "
        "in scripts from a dozen cultures, stalls representing cuisines from before and after the Dome, "
        "long communal eating benches in the open aisles, smoke from woks and open grills, "
        "the most diverse crowd in the Undercity, factions temporarily ignored over shared food, "
        "one of the few places in the city that feels warm"
    ),
    "markets infinite": (
        "vast underground commercial district, the ceiling so high it disappears into darkness "
        "above a forest of brutalist concrete columns wrapped in pipe and cable, "
        "neon signage on every surface competing for attention, "
        "holographic faction advertisements projected onto bare concrete walls thirty feet high, "
        "dense crowd of every species and culture in the city, "
        "noise like a continuous roar, gas lamp posts standing between modern LED towers"
    ),
    "grand forum": (
        "enormous underground civic district built in the style of ancient Greek public architecture — "
        "wide colonnaded boulevards with fluted marble-composite columns supporting carved pediments, "
        "touch-screen information kiosks built flush into column bases, "
        "holographic city maps and faction notice boards floating between pillars, "
        "high-resolution LED panels inset into the carved friezes showing live news feeds, "
        "FTA security guards in sleek full-face helmets and black composite armour "
        "standing at intervals between the columns, "
        "the ceiling a vast domed fresco lit from below by recessed lighting, "
        "bronze statues of civic founders repurposed with glowing faction insignia projected onto them, "
        "wide marble-effect floors polished to a mirror shine, busy with officials, adventurers, petitioners"
    ),
    "central plaza": (
        "grand underground public square in Greek civic style — "
        "colonnaded arcade running around all four sides, carved stone frieze above the columns "
        "depicting historical scenes now half-obscured by mounted LED display panels, "
        "a large ornamental fountain at the centre with faction crests worked into the basin stonework, "
        "touch-screen bulletin kiosks clustered near the fountain replacing the old notice boards, "
        "FTA security in composite black armour visible at every arcade entrance, "
        "the ceiling a painted dome with recessed spotlights following the original fresco patterns, "
        "crowds of adventurers, clerks, and faction representatives crossing the polished floor"
    ),
    "grand forum library": (
        "vast underground library built inside a repurposed Greek-style civic hall — "
        "rows of carved columns support a high barrel-vaulted ceiling, "
        "but the space between columns is filled with floor-to-ceiling modular archive shelving, "
        "holographic catalogue terminals replacing card indexes at every reading table, "
        "soft amber library lighting from recessed fixtures in the vault above, "
        "archivists in grey robes moving between stacks with handheld scanning devices, "
        "the original carved stone dedication frieze still visible above the main arch, "
        "quiet and watchful, the most orderly space in the Undercity"
    ),
    "fountain of echoes": (
        "large ornamental fountain in the Grand Forum's central square, "
        "the basin carved from pale composite stone with faction histories worked into relief panels, "
        "water cycling through a quiet recirculating pump system, "
        "the sound carrying strangely in the vaulted underground space, "
        "holographic notice boards floating above the rim displaying current mission postings, "
        "people sitting on the wide stone lip eating, reading, or waiting"
    ),
    "rift bulletin board": (
        "a large dedicated wall in the Grand Forum fitted with a floor-to-ceiling "
        "multi-panel holographic display system showing active Rift alerts, mission postings, and city warnings, "
        "the frame built into the original carved stone wall of the forum arcade, "
        "adventurers and civilians clustered in front reading, "
        "a Glass Sigil monitoring terminal mounted below updating residue readings in real time"
    ),
    "adventurer's inn": (
        "underground tavern occupying a converted Greek civic building — "
        "the original column entrance still intact but the interior stripped and rebuilt, "
        "exposed stone walls hung with mission flyers, trophies, salvaged weapons and faction patches, "
        "long communal tables under low-hanging Edison-style bulbs on industrial conduit, "
        "a bar along one wall backed with salvaged glass shelving lit from below, "
        "adventurers of every species in various states of gear, noise and warmth"
    ),
    "guild spires": (
        "underground district of towering post-modern guild headquarters, each one a different "
        "architectural language — a glass-and-steel ziggurat echoing Babylonian step-towers, "
        "a brutalist concrete obelisk with LED rune-script crawling up its faces, "
        "a spiralling pagoda-form structure in dark ceramic tile and steel, "
        "a squat Mesoamerican pyramid shape clad in polished black composite panels, "
        "wide paved plazas between the towers with faction crests inlaid in the floor, "
        "smartglass lobbies visible through ground-floor facades, "
        "guild banners hanging from upper-floor gantries, "
        "security in faction-specific uniforms at every entrance, "
        "the cleanest and most orderly district in the city"
    ),
    "adventurers guild": (
        "a mid-rise post-modern tower built in the silhouette of a medieval battlement-topped mage tower — "
        "lower floors clad in rough-faced stone aggregate panels giving a fortress feel, "
        "upper floors transitioning to glass curtain wall with the guild crest etched into each pane, "
        "a smartglass lobby at street level with holographic mission board displays, "
        "adventurers of every tier moving in and out, "
        "Mari Fen visible through the reception glass, "
        "queue of prospective members stretching out the door"
    ),
    "glass sigil": (
        "a tall narrow tower in blackened glass and brushed steel, "
        "built in the elongated silhouette of an alchemical minaret — "
        "a single thin column rising to a domed observation room at the top "
        "ringed in sensor arrays and Rift residue monitoring equipment, "
        "the tower exterior covered in a fine grid of etched arcane measurement notation "
        "that doubles as structural reinforcement, "
        "cool blue lighting inside visible through the dark glass skin, "
        "the quietest building in the Spires, few people enter or leave"
    ),
    "argent blades": (
        "a sweeping post-modern arc tower in polished silver-grey composite panels "
        "built in the silhouette of a great curved horn or crescent — "
        "referencing both the scimitar tradition and the curved tower forms of Islamic mage schools, "
        "the concave face covered in LED matrix panels showing live arena rankings and match schedules, "
        "a wide public atrium at the base open to the plaza, trophy cases visible behind glass, "
        "Lady Cerys Valemont's personal suite visible as a lit office high above"
    ),
    "serpent choir spire": (
        "a tower built in the silhouette of a Hindu shikhara temple spire — "
        "the lower body a wide carved stone base covered in relief panels of divine contract text, "
        "transitioning to a narrowing stack of curved concrete rings rising to a pointed apex, "
        "the entire surface lit in warm amber uplighting that gives it a gold appearance, "
        "incense burners at the base venting fragrant smoke into the plaza, "
        "contract mediators in Serpent Choir robes moving through the arched entrance"
    ),
    "ashen scrolls tower": (
        "a low wide building shaped like a Japanese castle turret — "
        "broad stone-effect base tapering in graceful curves to a traditional tiered roof silhouette "
        "reproduced in dark steel and glass, "
        "the interior lit in warm gold visible through narrow vertical window slits, "
        "archivists barely visible inside, "
        "the building feels older than it is, deliberately so"
    ),
    "arena of ascendance": (
        "large underground arena complex attached to the Argent Blades tower, "
        "tiered concrete seating rising steeply around a central sand-and-stone fighting floor, "
        "electric arc lights blazing over the pit on articulated gantry arms, "
        "Argent Blades silver banners hanging from the ceiling girders, "
        "a scoreboard LED panel dominating one end wall showing fighter rankings, "
        "the crowd a packed mass of faces, the smell of scorched sand and blood"
    ),
    "sanctum quarter": (
        "the oldest district in the Undercity, architecture a sediment of centuries — "
        "original carved stone temple facades with column porticos now braced with steel I-beams, "
        "ancient pediment carvings of gods partially obscured by modern HVAC ducting bolted across them, "
        "electric votive candle banks installed in original stone niches beside actual flame offerings, "
        "faction shrines built into every archway, some ancient stone, some modern fabricated composite, "
        "incense smoke perpetually drifting through the corridors, "
        "priests in traditional robes using handheld devices to manage contract queues"
    ),
    "pantheon walk": (
        "a long processional corridor lined with carved stone columns from different religious traditions — "
        "Doric, Ionic, lotus-capital Egyptian columns standing side by side, "
        "the spaces between them filled with illuminated shrine alcoves, "
        "some ancient stone carved with pre-Dome iconography, "
        "some modern fabricated panels with backlit faction god-symbols, "
        "electric votive flames in brass holders mounted to the original stone bases, "
        "the corridor always half-full of worshippers, contract seekers, and Serpent Choir representatives"
    ),
    "hall of echoes": (
        "a large domed chamber in the Sanctum Quarter, the dome itself ancient carved stone "
        "now fitted with modern acoustic panels to control the extraordinary resonance, "
        "used for divine contract readings and public declarations, "
        "a central speaking platform in old stone surrounded by concentric ring seating, "
        "factions represented by banners hung from the dome ring above, "
        "every sound echoing three times before fading"
    ),
    "divine garden": (
        "a rare open space in the Undercity, a large enclosed atrium in the Sanctum Quarter "
        "with a ceiling of engineered grow-lights simulating sky, "
        "faction-specific plants and sacred trees growing in raised stone beds, "
        "the only green space most Undercity residents have ever seen, "
        "wooden benches worn smooth, people sitting quietly, "
        "Serpent Choir attendants tending the beds in grey work robes"
    ),
    "shantytown heights": (
        "cramped underground shantytown stacked four and five levels high against the cavern wall, "
        "each dwelling built from whatever was available — "
        "corrugated tin sheets, salvaged wood pallets, cracked concrete blocks, actual straw thatch "
        "sitting incongruously under spray-painted slogans and faction tags in full colour, "
        "illegal LED strips and bioluminescent fungus cultures the only light source, "
        "narrow mud-and-concrete paths between structures barely shoulder-width, "
        "community cook fires at path intersections surrounded by mismatched seating, "
        "laundry lines strung between every structure at every height, "
        "children visible on improvised balconies, "
        "the sound of a dozen families audible through paper-thin walls"
    ),
    "scrapworks": (
        "vast underground industrial salvage yard, ceiling twenty metres overhead lost in shadow, "
        "mountains of sorted and unsorted scrap — broken machinery, vehicle hulks, pipe sections, "
        "structural steel — organised into rough aisles by the Patchwork Saints, "
        "welding arcs and acetylene cutting torches throwing orange and white light across the yard, "
        "workers in heavy leather aprons, face shields, and thick gloves, "
        "overhead crane tracks bolted to the cavern ceiling, chains hanging into the work zones, "
        "diesel and ozone smell, the noise of cutting and hammering constant, "
        "faction graffiti on every wall visible above the scrap piles, "
        "the Saints' white-hand symbol prominent"
    ),
    "night pits": (
        "a series of connected underground fight pits in a converted industrial basement, "
        "low concrete ceilings hung with cage-protected light fixtures, "
        "neon signs advertising fighter names, odds, and Obsidian Lotus services "
        "bolted to every wall in overlapping layers, "
        "crowds packed three deep around each sunken pit, "
        "Lotus syndicate enforcers in dark clothing visible at every door, "
        "a single brutal spotlight over the active fighting area, "
        "everything beyond it in cigarette-smoke shadow"
    ),
    "echo alley": (
        "a long underground alley in the heart of the Warrens, "
        "walls of crumbling concrete and salvaged brick buried under decades of overlapping graffiti — "
        "faction tags, personal marks, memorial names, illicit ads — "
        "illegal vendors crouching over canvas sheets of goods covering the path, "
        "bioluminescent moss growing thick in the wall cracks providing faint blue-green ambient light, "
        "a single surviving fluorescent tube at the far end flickering on its mounting, "
        "the alley barely two people wide, always busy"
    ),
    "collapsed plaza": (
        "an open underground space in the Warrens where a section of ceiling came down years ago, "
        "the rubble pushed to the edges forming rough irregular walls now used as shelter foundations, "
        "Thane's cult symbols spray-painted in white and red over older faction tags on every surface, "
        "makeshift shelters built into the larger rubble pieces, "
        "bioluminescent growth colonising the fallen concrete providing dim ambient green light, "
        "the air still and quiet compared to the surrounding Warrens, "
        "cult followers visible in doorways watching"
    ),
    "brother thane": (
        "a converted industrial building in the Warrens repurposed as a cult compound — "
        "the exterior original concrete heavily marked with Thane's cult symbols "
        "spray-painted over underlying faction graffiti in successive layers, "
        "narrow barred windows with candlelight visible inside, "
        "followers in worn homespun robes moving between outbuildings, "
        "the entrance guarded by Brother Aldric's people, no faction markings visible, "
        "the building feels sealed and inward-facing"
    ),
    "warrens": (
        "dense underground slum built in the cavern's oldest and least-maintained sections, "
        "structures of corrugated tin, salvaged concrete blocks, and scavenged timber "
        "stacked to the cavern ceiling in places without any planning or permission, "
        "every flat surface covered in spray-paint faction tags and personal murals in full colour, "
        "illegal electrical hookups running on exposed wire from junction boxes to individual dwellings, "
        "bioluminescent fungus cultivated on walls and ceilings supplementing the stolen power, "
        "alleys barely shoulder-width, puddles of grey water, "
        "the sound of the whole district living at close quarters"
    ),
    "outer wall": (
        "the Undercity's outermost defensive district, a zone of raw engineering — "
        "massive reinforced concrete walls two metres thick with blast door intervals, "
        "Warden patrol routes lit by industrial halogen floodlights on articulated mounts, "
        "hazard-stripe markings on every floor, warning signage in multiple languages, "
        "the low continuous hum and vibration of Dome infrastructure running through the walls, "
        "the air colder here, cleaner, smelling faintly of ozone and metal, "
        "no civilian presence, Wardens only, the feeling of standing at the city's last line"
    ),
    "wall quadrant c": (
        "a section of the Outer Wall perimeter, blast-proof concrete corridors "
        "with Warden monitoring stations at regular intervals — "
        "banks of screens showing Rift residue readings, wall-stress sensors, "
        "and exterior cameras pointed at nothing, "
        "emergency equipment lockers in yellow-painted alcoves, "
        "the floor grated steel over drainage channels, "
        "Wardens in full kit moving with purpose, no one loitering"
    ),
    "wall quadrant a": (
        "Outer Wall sector near the primary gate district, "
        "the only section with any civilian access — a processing zone of "
        "heavy blast doors, biometric scanner arches, and Warden checkpoints, "
        "queues of cargo handlers and credentialed workers moving through inspection lanes, "
        "overhead announcement boards cycling safety warnings, "
        "the architecture raw concrete and steel with zero aesthetic consideration"
    ),
    "outer wall gate district": (
        "the Undercity's primary access point — a wide concrete processing hall "
        "with multiple layers of blast doors, Warden checkpoints at every threshold, "
        "biometric arches and cargo scanners blocking the lanes, "
        "the ceiling high and industrial with bright work lighting, "
        "faction representatives waiting in a glass-fronted observation room above, "
        "the only place in the city where things come in from outside"
    ),
    "silver spire": (
        "a private high-rise residential tower in the Guild Spires district, "
        "the most exclusive address in the Undercity — "
        "the exterior a seamless skin of mirror-polished silver composite panels "
        "rising to a tapered point, no visible seams, no signage, "
        "a single understated entrance with private security in plain clothes, "
        "the upper floors rumoured to be Aric Veyne's residence"
    ),
    "iron fang": (
        "Iron Fang Consortium territory in Markets Infinite — "
        "a cluster of connected buildings that have been bought, connected, and fortified over years, "
        "exterior walls freshly painted with the Consortium's iron-fang emblem "
        "over older faction graffiti below, "
        "warehouse loading bays with heavy roller doors, "
        "Consortium enforcers in matched grey jackets at every entrance, "
        "the buildings deliberately unmarked beyond the crest"
    ),
    "obsidian lotus": (
        "Obsidian Lotus territory in the Night Pits area of the Warrens — "
        "a series of unmarked basement-level rooms connected by locked passage doors, "
        "black lotus sigils stencilled in the corners near the floor where only those who know look, "
        "the lighting dim and deliberate, walls sound-dampened with hanging fabric, "
        "the Widow's people visible only as silhouettes in doorways"
    ),
    "patchwork saints": (
        "Patchwork Saints operation centre in the Scrapworks, "
        "a cleared section of the salvage yard converted to a community hub — "
        "long folding tables set up as a soup kitchen, medical station in a curtained-off corner, "
        "the Saints' white-hand symbol painted large on the back wall, "
        "Pol Greaves visible at a makeshift desk surrounded by paperwork and supply ledgers, "
        "the space worn and underfunded but functioning"
    ),
}

_AESTHETIC_FALLBACK = (
    "underground city district, brutalist concrete columns and exposed pipe infrastructure, "
    "neon signage competing with gas lamp posts, faction graffiti on every wall, "
    "fog and steam at ground level, a crowd of various species going about their business, "
    "the ceiling lost in darkness above, gritty and lived-in and permanent"
)


def _get_district_aesthetic(text: str) -> str:
    """Match bulletin text against district names and return the correct aesthetic."""
    text_lower = text.lower()
    for district, aesthetic in sorted(_DISTRICT_AESTHETICS.items(), key=lambda x: -len(x[0])):
        if district in text_lower:
            return aesthetic
    return _AESTHETIC_FALLBACK


# ---------------------------------------------------------------------------
# Party home district helpers
# ---------------------------------------------------------------------------

_PARTY_SPECIALTY_TO_DISTRICT: list[tuple[list[str], str]] = [
    (["rift", "containment", "outer wall"],      "outer wall"),
    (["salvage", "scrap", "industrial"],          "scrapworks"),
    (["arena", "combat", "fighting", "pit"],      "arena of ascendance"),
    (["market", "trade", "merchant", "smuggl"],   "markets infinite"),
    (["information", "intel", "espionage"],       "grand forum"),
    (["cult", "thane", "returned"],               "brother thane"),
    (["religious", "divine", "contract"],         "sanctum quarter"),
]
_PARTY_DEFAULT_DISTRICT = "adventurer's inn"


# ---------------------------------------------------------------------------
# Prompt agent — translates context into AnimagineXL Danbooru tags.
# ---------------------------------------------------------------------------

_SD_PROMPTS_FILE = DOCS_DIR / "npc_appearances" / "_all_sd_prompts.json"

_PROSE_INDICATORS = (
    " who ", " with ", " and the ", " in the ", " as they ",
    "stands ", "moves ", "wears ", "holds ", "carries ",
)


def _prose_to_tags(prose: str) -> str:
    """
    Converts an NPC prose description into compact Danbooru-style tags.
    """
    prose_lower = prose.lower()
    tags: list[str] = []

    race_map = {
        "dwarf":     "dwarf",
        "halfling":  "halfling",
        "gnome":     "gnome",
        "half-orc":  "half-orc",
        "orc":       "orc",
        "tiefling":  "tiefling, horns, pointed tail",
        "aasimar":   "aasimar, radiant skin",
        "dragonborn":"dragonborn, scales",
        "goblin":    "goblin, large ears",
        "kobold":    "kobold, reptilian",
        "elf":       "elf, pointed ears",
        "half-elf":  "half-elf, pointed ears",
    }
    for race_key, race_tag in race_map.items():
        if race_key in prose_lower:
            tags.append(race_tag)
            break

    for colour in ("silver", "grey", "gray", "white", "black", "dark", "red",
                   "auburn", "brown", "blonde", "golden"):
        if colour + " hair" in prose_lower:
            tags.append(f"{colour} hair")
            break
    for length in ("short hair", "long hair", "shoulder-length hair",
                   "braided hair", "braid", "shaved head"):
        if length in prose_lower:
            tags.append(length)
            break

    for colour in ("blue", "grey", "gray", "green", "amber", "red",
                   "yellow", "golden", "silver", "ice", "black", "brown",
                   "purple", "violet"):
        if colour + " eye" in prose_lower or colour + "-eye" in prose_lower:
            tags.append(f"{colour} eyes")
            break

    for tone in ("pale", "dark", "weathered", "green", "grey", "lavender",
                 "brown", "tan", "bronze", "ashen", "scarred"):
        if tone + " skin" in prose_lower:
            tags.append(f"{tone} skin")
            break

    for colour in ("burgundy", "indigo", "jade", "crimson", "black",
                   "silver", "white", "grey", "gray", "ash", "blue",
                   "red", "green"):
        for garment in ("coat", "robe", "jacket", "armour", "armor",
                        "vest", "cloak", "uniform", "shirt"):
            if colour in prose_lower and garment in prose_lower:
                tags.append(f"{colour} {garment}")
                break

    for armour in ("plate armor", "scale mail", "chain mail", "leather armor",
                   "padded vest", "robes"):
        if armour in prose_lower:
            tags.append(armour)
            break

    for weapon in ("longsword", "shortsword", "dagger", "crossbow",
                   "warhammer", "battle axe", "battleaxe", "staff",
                   "spear", "mace", "bow", "rapier"):
        if weapon in prose_lower:
            tags.append(weapon)

    for feature in ("scar", "eye patch", "eyepatch", "missing finger",
                    "tattoo", "goggles", "gloves", "spectacles", "glasses",
                    "hood", "mask", "amulet", "medallion"):
        if feature in prose_lower:
            tags.append(feature)

    return ", ".join(tags) if tags else ""


def _load_sd_prompts() -> dict:
    """Load the flat NPC name → SD prompt lookup."""
    if not _SD_PROMPTS_FILE.exists():
        return {}
    try:
        return json.loads(_SD_PROMPTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def _prompt_agent(
    bulletin_text: str,
    npc_names: list[str],
    loc_key: str,
    scene_action: str,
    quality_header: str,
    framing: str,
) -> str:
    """
    Translate bulletin context into a clean AnimagineXL Danbooru-tag prompt.
    Falls back to structured self-lookup if Mistral is unavailable or returns prose.
    """
    import httpx
    import logging as _log
    logger = _log.getLogger(__name__)

    sd_prompts = _load_sd_prompts()
    npc_tag_parts: list[str] = []
    for name in npc_names:
        prose = sd_prompts.get(name, "")
        if prose:
            extracted = _prose_to_tags(prose)
            if extracted:
                npc_tag_parts.append(f"({name}: {extracted})")

    npc_block = "; ".join(npc_tag_parts) if npc_tag_parts else ""
    char_count = len(npc_names)
    char_tag = f"{char_count}characters" if char_count > 1 else ("1character" if char_count == 1 else "2characters")

    _LOC_TAG_MAP_LOCAL = {
        "neon row":           "neon lights, underground street, crowded alleyway, neon signs",
        "cobbleway market":   "market stall, underground street, neon signs, concrete pillars",
        "floating bazaar":    "underground lake, lanterns on water, floating platform, mist",
        "crimson alley":      "dark alley, red neon lights, steam vents, graffiti walls",
        "taste of worlds":    "food stall, paper lanterns, underground market, warm lighting",
        "markets infinite":   "underground city, neon signs, brutalist pillars, crowded",
        "grand forum":        "greek columns, marble floor, holographic display, underground civic hall",
        "central plaza":      "stone plaza, ornamental fountain, underground city",
        "grand forum library":"library interior, arched ceiling, bookshelves, amber lighting",
        "adventurer's inn":   "tavern interior, stone walls, dim lighting, wooden tables",
        "guild spires":       "brutalist tower, glass facade, underground city",
        "arena of ascendance":"fighting arena, stadium lights, tiered seating, sand floor",
        "sanctum quarter":    "ancient temple, stone columns, candles, incense smoke",
        "pantheon walk":      "stone colonnade, shrine alcoves, candlelight",
        "hall of echoes":     "domed chamber, stone architecture, torchlight",
        "shantytown heights": "shantytown, corrugated tin walls, hanging laundry, narrow alley",
        "scrapworks":         "industrial salvage yard, metal scrap piles, welding sparks",
        "night pits":         "underground fight pit, neon signs, spotlight, dark concrete",
        "echo alley":         "dark alley, graffiti walls, bioluminescent moss, dim lighting",
        "collapsed plaza":    "rubble field, cave interior, dim green light, graffiti",
        "brother thane":      "cult compound, candlelit interior, stone walls",
        "outer wall":         "brutalist concrete wall, industrial floodlights, military",
        "wall quadrant":      "concrete corridor, blast door, industrial lighting",
        "warrens":            "underground slum, graffiti walls, bioluminescent fungus, alley",
        "silver spire":       "luxury tower interior, polished surfaces, private security",
        "iron fang":          "warehouse interior, industrial lighting, faction insignia",
    }
    loc_tags = "underground city, dark fantasy setting, gritty atmosphere"
    loc_key_lower = loc_key.lower()
    for key, tags in _LOC_TAG_MAP_LOCAL.items():
        if key in loc_key_lower:
            loc_tags = tags
            break

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    agent_system = (
        "You are an expert Stable Diffusion XL prompt engineer specialising in AnimagineXL 3.1.\n"
        "AnimagineXL uses Danbooru tag vocabulary. It does NOT understand prose sentences.\n"
        "Your ONLY output must be comma-separated Danbooru tags — nothing else.\n\n"
        "RULES:\n"
        "- Tags are short phrases: 'grey hair', 'plate armor', 'red eyes', 'dramatic lighting'\n"
        "- NO sentences. NO 'a figure who...'. NO 'standing in...'. Just tags.\n"
        "- Character tags come before location tags.\n"
        "- Include: character appearance tags, action/pose tags, location/background tags.\n"
        "- Do NOT include quality tags (masterpiece, best quality) — those are added separately.\n"
        "- Do NOT include framing tags (cowboy shot, wide shot) — those are added separately.\n"
        "- Output 10–25 tags total, comma-separated, on ONE line.\n"
        "- If you output anything other than comma-separated tags, you have failed."
    )

    agent_user = (
        f"Bulletin text:\n{bulletin_text[:600]}\n\n"
        f"Characters in scene: {', '.join(npc_names) if npc_names else 'unnamed figures'}\n"
        f"Known character details: {npc_block if npc_block else 'none available'}\n"
        f"Scene action: {scene_action}\n"
        f"Location: {loc_key} ({loc_tags})\n\n"
        f"Output ONLY the comma-separated Danbooru tags for this scene."
    )

    mistral_tags = ""
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": [
                    {"role": "system", "content": agent_system},
                    {"role": "user",   "content": agent_user},
                ],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()
        raw = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                raw = msg.get("content", "").strip()

        lines = raw.splitlines()
        skip = ("sure", "here", "certainly", "of course", "below", "i ", "as ")
        while lines and lines[0].lower().strip().rstrip(":!,.").startswith(skip):
            lines.pop(0)
        raw = " ".join(lines).strip()

        if raw.count(",") >= 5 and not any(p in raw.lower() for p in _PROSE_INDICATORS):
            mistral_tags = raw
            logger.info(f"🤖 Prompt agent: Mistral returned {raw.count(',') + 1} tags")
        else:
            logger.warning(f"🤖 Prompt agent: Mistral returned prose or too few tags — using self-lookup fallback")

    except Exception as e:
        logger.warning(f"🤖 Prompt agent: Mistral unavailable ({e}) — using self-lookup fallback")

    if not mistral_tags:
        parts: list[str] = []
        if npc_tag_parts:
            flat_npc = ", ".join(
                tags for _, tags in (
                    part.split(": ", 1) if ": " in part else ("", part)
                    for part in npc_tag_parts
                ) if tags
            )
            if flat_npc:
                parts.append(flat_npc)
        else:
            parts.append(char_tag)
        parts.append(scene_action)
        parts.append(loc_tags)
        mistral_tags = ", ".join(p for p in parts if p)
        logger.info(f"🤖 Prompt agent: self-lookup fallback assembled {len(parts)} blocks")

    final = ", ".join(p for p in [quality_header, char_tag, mistral_tags, framing] if p)
    return final


def _get_party_home_district(party_profile: dict) -> str:
    """Derive a home district key from a party profile JSON."""
    text = ((party_profile.get("specialty") or "") + " " +
            (party_profile.get("affiliation") or "")).lower()
    for keywords, district_key in _PARTY_SPECIALTY_TO_DISTRICT:
        if any(kw in text for kw in keywords):
            return district_key
    return _PARTY_DEFAULT_DISTRICT


def _find_parties_in_text(text: str) -> list[tuple[str, str, str]]:
    """
    Scan text for known party names.
    Returns list of (party_name, visual_description, home_district_key).
    """
    profiles_dir = Path(__file__).resolve().parent.parent / "campaign_docs" / "party_profiles"
    if not profiles_dir.exists():
        return []
    found = []
    text_lower = text.lower()
    for path in profiles_dir.glob("*.json"):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
            name = profile.get("name", "")
            if name and name.lower() in text_lower:
                visual = profile.get("visual", "")
                home   = _get_party_home_district(profile)
                found.append((name, visual, home))
        except Exception:
            continue
    return found


# ---------------------------------------------------------------------------
# Image prompt builder
# ---------------------------------------------------------------------------

_BULLETIN_ACTION_KEYWORDS: list[tuple[str, str]] = [
    ("confrontation",  "two figures facing each other in tense standoff"),
    ("fight",          "figures in mid-combat, dynamic poses"),
    ("ambush",         "figures emerging from shadows, weapons drawn"),
    ("chase",          "figures running through the district"),
    ("meeting",        "figures gathered in hushed conversation"),
    ("negotiation",    "figures at a table in careful discussion"),
    ("celebration",    "figures raising drinks, festive atmosphere"),
    ("funeral",        "figures bowed in mourning around a body"),
    ("announcement",   "figure addressing a gathered crowd"),
    ("investigation",  "figure crouching over evidence, examining clues"),
    ("arrest",         "armoured figures restraining a struggling target"),
    ("escape",         "figure vaulting over obstacle, others in pursuit"),
    ("discovery",      "figure holding up a glowing relic, face lit from below"),
    ("explosion",      "smoke and debris billowing, figures thrown back"),
    ("ceremony",       "robed figures in ritual formation, candles lit"),
    ("deal",           "figures exchanging items in half-shadow"),
    ("injured",        "figure slumped against wall, others tending wounds"),
    ("dead",           "still figure on ground, onlookers gathered"),
    ("brawl",          "chaotic melee, multiple figures in close combat"),
    ("surveillance",   "figure watching from elevated position, unseen"),
    ("market",         "bustling stalls, figures browsing wares"),
    ("sermon",         "figure at podium, crowd listening intently"),
    ("auction",        "auctioneer at front, bidders with raised hands"),
    ("bounty",         "wanted poster on wall, figures studying it"),
    ("heist",          "figures moving stealthily through secured area"),
    ("protest",        "crowd pressing forward, signs and torches raised"),
    ("riot",           "overturned stalls, figures clashing with guards"),
]


def _extract_scene_action(text: str) -> str:
    """Extract a visual action phrase from bulletin text."""
    text_lower = text.lower()
    for keyword, visual in _BULLETIN_ACTION_KEYWORDS:
        if keyword in text_lower:
            return visual
    return "figures going about tense business in the district"


async def _build_image_prompt(memory_entries: List[str]) -> tuple:
    """
    Build an SDXL image prompt directly.
    Returns (sd_prompt_str, npc_names_list, chosen_bulletin_str).
    """
    image_style = os.getenv("IMAGE_STYLE", "photorealistic").lower().strip()
    is_anime    = image_style == "anime"

    if not memory_entries:
        sd_prompt = (
            "wide establishing shot, underground city street, brutalist concrete pillars, "
            "neon signs, bioluminescent fungus on walls, crowd of figures at mid-distance"
        )
        return sd_prompt, [], ""

    try:
        from src.npc_appearance import find_npc_in_text
    except Exception:
        find_npc_in_text = lambda t: []

    _system_tags = (
        "[towerbay", "[tia ", "[ec/kharma", "[dome weather",
        "[arena match", "[faction calendar", "[missing persons",
        "[rift bulletin",
    )
    real_entries = [
        e for e in memory_entries
        if not any(tag in e.lower() for tag in _system_tags)
    ]
    if not real_entries:
        real_entries = memory_entries

    recent_pool = real_entries[-8:]
    random.shuffle(recent_pool)

    chosen        = None
    found_npcs    = []
    found_parties = []

    for entry in recent_pool:
        npcs    = find_npc_in_text(entry)
        parties = _find_parties_in_text(entry)
        if npcs or parties:
            chosen        = entry
            found_npcs    = npcs
            found_parties = parties
            break

    if not chosen:
        chosen        = random.choice(real_entries[-5:])
        found_npcs    = find_npc_in_text(chosen)
        found_parties = _find_parties_in_text(chosen)

    district_aesthetic = _get_district_aesthetic(chosen)
    if district_aesthetic is _AESTHETIC_FALLBACK:
        home_keys = (
            [home for _, _, home in found_npcs if home] +
            [home for _, _, home in found_parties if home]
        )
        if home_keys:
            from collections import Counter
            best = Counter(home_keys).most_common(1)[0][0]
            district_aesthetic = _DISTRICT_AESTHETICS.get(best, _AESTHETIC_FALLBACK)

    scene_action = _extract_scene_action(chosen)

    MAX_CHARS = 4
    npc_names = []
    char_parts = []

    for npc_name, npc_sd, _ in found_npcs[:MAX_CHARS]:
        npc_names.append(npc_name)
        if npc_sd:
            first_sentence = npc_sd.split('.')[0].strip()
            char_parts.append(first_sentence)

    remaining = MAX_CHARS - len(char_parts)
    for party_name, party_visual, _ in found_parties[:remaining]:
        if party_visual:
            first_sentence = party_visual.split('.')[0].strip()
            char_parts.append(first_sentence)

    image_style = os.getenv("IMAGE_STYLE", "photorealistic").lower().strip()
    is_anime    = image_style == "anime"

    if is_anime:
        quality_header = (
            "masterpiece, best quality, very aesthetic, absurdres"
        )
        char_block = ", ".join(char_parts) if char_parts else "2characters"
        action_tags = scene_action

        _LOC_TAG_MAP = {
            "neon row":           "neon lights, underground street, crowded alleyway",
            "cobbleway market":   "market stall, underground street, neon signs",
            "floating bazaar":    "underground lake, lanterns reflecting on water, floating platform",
            "crimson alley":      "neon lights, dark alley, steam, red lighting",
            "taste of worlds":    "food stall, lanterns, underground market",
            "markets infinite":   "underground city, neon signs, brutalist pillars, crowd",
            "grand forum":        "greek columns, marble floor, holographic display, underground civic hall",
            "central plaza":      "stone plaza, fountain, underground city, neon signage",
            "grand forum library":"library, arched ceiling, bookshelves, amber lighting",
            "adventurer's inn":   "tavern, stone walls, low lighting, rough tables",
            "guild spires":       "brutalist tower, glass facade, underground city skyline",
            "arena of ascendance":"fighting arena, stadium lighting, tiered seating, sand floor",
            "sanctum quarter":    "ancient temple, stone columns, candles, incense smoke",
            "pantheon walk":      "stone colonnade, shrine alcoves, candlelight",
            "shantytown heights": "slum, corrugated tin walls, hanging laundry, narrow path",
            "scrapworks":         "industrial salvage yard, welding sparks, metal scrap piles",
            "night pits":         "underground fight pit, neon signs, dark concrete, spotlight",
            "echo alley":         "dark alley, graffiti walls, bioluminescent moss",
            "collapsed plaza":    "rubble, cave, dim green light, abandoned space",
            "outer wall":         "brutalist concrete wall, floodlights, military checkpoint",
            "warrens":            "slum alley, graffiti, illegal wiring, bioluminescent fungus",
        }
        chosen_lower = chosen.lower()
        loc_tags = "underground city, dark fantasy setting"
        for key, tags in _LOC_TAG_MAP.items():
            if key in chosen_lower:
                loc_tags = tags
                break

        framing = (
            "cowboy shot, 2characters, dynamic pose, "
            "characters in foreground, environment background, "
            "dramatic lighting, volumetric lighting, lens flare, "
            "dynamic shadow, english text, latin alphabet"
        )
    else:
        quality_header = "wide establishing shot, multiple figures visible in mid-ground"
        framing = (
            "camera far back, environment fills majority of frame, "
            "characters small relative to surroundings, "
            "brutalist concrete and neon atmosphere, no medieval architecture"
        )

    sd_prompt = await _prompt_agent(
        bulletin_text=chosen,
        npc_names=npc_names,
        loc_key=chosen,
        scene_action=scene_action,
        quality_header=quality_header,
        framing=framing,
    )

    return sd_prompt, npc_names, chosen


async def generate_story_image() -> tuple:
    """
    Generate a story image via local A1111 SDXL API based on the current story arc.
    Returns (image_bytes, image_prompt, caption) or (None, image_prompt, None) on failure.
    """
    import httpx
    import logging
    logger = logging.getLogger(__name__)

    A1111_URL  = os.getenv("A1111_URL", "http://127.0.0.1:7860")
    _image_style = os.getenv("IMAGE_STYLE", "photorealistic").lower().strip()
    if _image_style == "anime":
        A1111_MODEL = os.getenv("A1111_ANIME_MODEL", os.getenv("A1111_MODEL", "sd_epicrealismXL_pureFix"))
    else:
        A1111_MODEL = os.getenv("A1111_MODEL", "sd_epicrealismXL_pureFix")

    memory = _read_memory()
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    image_prompt, npc_names, chosen_bulletin = await _build_image_prompt(memory)
    logger.info(f"🖼️ SD prompt built: {image_prompt[:120]}")

    image_style = os.getenv("IMAGE_STYLE", "photorealistic").lower().strip()
    is_anime    = image_style == "anime"

    if is_anime:
        _style_suffix = (
            ", masterpiece, best quality, very aesthetic, absurdres, "
            "dramatic lighting, volumetric lighting, lens flare, particle effects, "
            "intricate background, detailed environment, "
            "cinematic composition, cowboy shot, 2characters, dynamic pose, "
            "characters in foreground, environment background, "
            "english text, latin alphabet, legible english signage, "
            "glowing eyes, dynamic shadow, high contrast"
        )
        negative_prompt = (
            "nsfw, lowres, (bad), text overlay, watermark, logo, copyright, "
            "error, fewer, extra, missing, "
            "worst quality, jpeg artifacts, low quality, unfinished, "
            "displeasing, oldest, early, chromatic aberration, "
            "signature, username, scan, (abstract), "
            "chinese text, japanese text, korean text, arabic text, "
            "cyrillic text, foreign script, illegible text, "
            "flat color, simple background, retro anime, 80s anime, "
            "chibi, super deformed, sketch, lineart only, "
            "portrait, face close-up, headshot, cropped, close up, "
            "photorealistic, 3d render, western cartoon"
        )
    else:
        _style_suffix = (
            ", RAW photo, wide angle lens, 24mm, f/5.6, "
            "environmental wide shot, multiple figures in frame, "
            "cinematic lighting, highly detailed, sharp focus, 8k"
        )
        negative_prompt = (
            "text, watermark, signature, blurry, low quality, ugly, deformed, "
            "cartoon, anime, painting, illustration, drawing, sketch, "
            "cgi, render, 3d, plastic, oversaturated, game screenshot, "
            "portrait, close-up, headshot, face only, cropped, "
            "medieval castle, stone dungeon, fantasy castle interior, torch sconces"
        )

    if not is_anime:
        image_prompt += _style_suffix

    caption = None
    if npc_names and chosen_bulletin:
        names_str = " and ".join(npc_names)
        caption_prompt = (
            f"Write exactly ONE sentence (under 15 words) describing what {names_str} "
            f"is doing in this scene, based on this bulletin:\n\n{chosen_bulletin}\n\n"
            f"Format like: 'Sera Voss poring over stolen ledgers in a Crimson Alley safehouse.'\n"
            f"Output ONLY the sentence. No preamble. No quotation marks."
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(ollama_url, json={
                    "model": ollama_model,
                    "messages": [{"role": "user", "content": caption_prompt}],
                    "stream": False,
                })
                resp.raise_for_status()
                cdata = resp.json()
            raw = ""
            if isinstance(cdata, dict):
                cmsg = cdata.get("message", {})
                if isinstance(cmsg, dict):
                    raw = cmsg.get("content", "").strip()
            raw = raw.strip('"\'')
            clines = raw.splitlines()
            skip_cap = ("sure", "here's", "here is", "certainly", "of course")
            while clines and clines[0].lower().strip().rstrip("!:,.").startswith(skip_cap):
                clines.pop(0)
            if clines:
                caption = clines[0].strip('"\'').strip()
        except Exception as ce:
            logger.warning(f"🖼️ Caption generation failed: {ce}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{A1111_URL}/sdapi/v1/options")
            current = r.json().get("sd_model_checkpoint", "")
            if A1111_MODEL not in current:
                logger.info(f"🖼️ Switching A1111 model to {A1111_MODEL}")
                await client.post(f"{A1111_URL}/sdapi/v1/options", json={
                    "sd_model_checkpoint": A1111_MODEL
                })
    except Exception as e:
        logger.warning(f"🖼️ Could not switch A1111 model: {e}")

    payload = {
        "prompt": image_prompt,
        "negative_prompt": negative_prompt,
        "steps": 40,
        "cfg_scale": 5.0,
        "width": 896,
        "height": 512,
        "sampler_name": "Euler a",
        "batch_size": 1,
        "n_iter": 1,
        "seed": random.randint(1, 999999),
        "restore_faces": False,
        "tiling": False,
    }

    # Check for reference images to use as img2img base
    from src.image_ref import (
        get_best_ref_for_scene, to_img2img_payload,
        detect_and_save_refs, SCENE_DENOISE,
    )
    ref_bytes, denoise, ref_source = get_best_ref_for_scene(
        chosen_bulletin if chosen_bulletin else image_prompt
    )
    if ref_bytes:
        api_payload = to_img2img_payload(payload, ref_bytes, denoise)
        endpoint = f"{A1111_URL}/sdapi/v1/img2img"
        logger.info(f"🖼️ Story image using img2img ref: {ref_source} (denoise={denoise})")
    else:
        api_payload = payload
        endpoint = f"{A1111_URL}/sdapi/v1/txt2img"

    async with a1111_lock:
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=900.0) as client:
                    r = await client.post(endpoint, json=api_payload)
                    r.raise_for_status()
                    result = r.json()

                import base64
                from PIL import Image
                import io as _io
                img_b64 = result["images"][0]
                img_bytes = base64.b64decode(img_b64)

                try:
                    img = Image.open(_io.BytesIO(img_bytes))
                    w, h = img.size
                    crop_px = 52
                    img = img.crop((0, 0, w, h - crop_px))
                    buf = _io.BytesIO()
                    img.save(buf, format="PNG")
                    img_bytes = buf.getvalue()
                    logger.info(f"🖼️ Cropped {crop_px}px watermark strip ({len(img_bytes)//1024}KB)")
                except Exception as _crop_err:
                    logger.warning(f"🖼️ Watermark crop failed: {_crop_err} — using uncropped image")

                # Auto-save as reference for detected NPCs/locations
                scene_text = chosen_bulletin if chosen_bulletin else image_prompt
                detect_and_save_refs(scene_text, img_bytes)

                logger.info(f"🖼️ A1111 image generated successfully ({len(img_bytes)//1024}KB)")
                return img_bytes, image_prompt, caption

            except Exception as e:
                import traceback
                logger.warning(f"🖼️ A1111 attempt {attempt+1}/3 failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                if attempt < 2:
                    await asyncio.sleep(15)

        logger.error("🖼️ All A1111 attempts failed — skipping image this cycle")
        return None, image_prompt, None


# ---------------------------------------------------------------------------
# Draft bulletin (no auto-save — caller decides whether to post)
# ---------------------------------------------------------------------------

async def generate_bulletin_draft() -> tuple:
    """
    Generate a bulletin without saving to memory.
    Returns (formatted_str, raw_bulletin) or (None, None) on failure.
    """
    from src.ollama_busy import is_available, get_busy_reason
    if not is_available():
        import logging as _log
        _log.getLogger("src.log").info(f"📰 Ollama busy ({get_busy_reason()}) — skipping bulletin this cycle")
        return None, None

    memory = _read_memory()
    prompt = _build_prompt(memory)

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    try:
        import httpx, re as _re
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()

        bulletin = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                bulletin = msg.get("content", "").strip()

        if bulletin:
            lines = bulletin.splitlines()
            skip_phrases = ("sure", "here's", "here is", "as requested", "certainly", "of course", "i hope", "below is")
            while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip_phrases):
                lines.pop(0)

            _rate_patterns = [
                r'^\**new essence coin prices',
                r'^\d+\s*(kharma|ec)\s*[=:]',
                r'^`\d+\s*(kharma|ec)',
                r'kharma\s*=\s*[\d,.]+\s*ec',
                r'[\d,.]+\s*ec\s*[=:]\s*[\d,.]+\s*kharma',
                r'^-#.*exchange rate',
                r'^\d[\d,.]*(\s*ec|\s*essence coins?)\s+(for|to|gets?|buys?)',
                r'(for only|costs?|price:|pay)\s+\d[\d,.]*\s*(ec|essence coins?)',
            ]
            filtered = []
            for ln in lines:
                ln_lower = ln.lower().strip()
                if any(_re.search(pat, ln_lower) for pat in _rate_patterns):
                    continue
                filtered.append(ln)
            while filtered and not filtered[-1].strip():
                filtered.pop()
            bulletin = "\n".join(filtered).strip()

        if bulletin:
            bulletin = _re.sub(
                r'[,.]?\s*\d[\d,.]*\s*(?:ec|essence coins?)\s+(?:for|to|gets?|buys?)[^.\n]*',
                '',
                bulletin,
                flags=_re.IGNORECASE,
            ).strip()

        if bulletin:
            echo_cut = _re.search(
                r'\n\s*---\s*\n+(?:you are the undercity dispatch|task:|write one undercity)',
                bulletin, _re.IGNORECASE
            )
            if echo_cut:
                bulletin = bulletin[:echo_cut.start()].strip()

            _ts_lines = bulletin.splitlines()
            while _ts_lines and _re.match(r'^-?#?\s*\d{4}-\d{2}-\d{2} \d{2}:\d{2}', _ts_lines[0].strip()):
                _ts_lines.pop(0)
            bulletin = '\n'.join(_ts_lines).strip()

            bulletin = _re.sub(r'(\w[\w\s\']{0,40}?)\(#\)', r'\1', bulletin)
            bulletin = _re.sub(r'\[([^\]\[]{1,80})\]\((?!https?://)[^)]*\)', r'\1', bulletin)
            bulletin = _re.sub(
                r'\[([^\]\[]{1,80})\](?!\()',
                lambda m: m.group(1) if not _re.match(r'\d{4}-\d{2}-\d{2}', m.group(1)) else m.group(0),
                bulletin
            )

        if bulletin:
            _, _, _, dead_names = _load_npc_status_blocks()
            if dead_names:
                bulletin = _apply_death_honorifics(bulletin, dead_names)

        if bulletin:
            bulletin = _apply_tnn_signoff(bulletin)

        if bulletin:
            bulletin = await _edit_bulletin(bulletin, memory)

        if bulletin:
            formatted = f"-# \U0001f570\ufe0f {_dual_timestamp()}\n{bulletin}"
            return formatted, bulletin

    except Exception as e:
        import logging, traceback
        logging.getLogger(__name__).error(
            f"\U0001f4f0 generate_bulletin_draft error: {type(e).__name__}: {e}\n{traceback.format_exc()}"
        )

    return None, None


# ---------------------------------------------------------------------------
# Interval
# ---------------------------------------------------------------------------

def next_interval_seconds() -> int:
    """Randomised 50–70 minute interval so bulletins feel organic, not clockwork."""
    return random.randint(50 * 60, 70 * 60)


def next_image_interval_seconds() -> int:
    """Randomised 2–4 hour interval between story images."""
    return random.randint(2 * 60 * 60, 4 * 60 * 60)
