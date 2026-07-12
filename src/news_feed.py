"""
news_feed.py — Tower of Last Chance AI-generated hourly bulletin.

Uses qwen3 locally via Ollama — OpenClaw/Pi compatible, fully local, no cloud tokens.

Every bulletin is saved to the `news_memory` MySQL table (DB is authoritative).
Bulletin entries go into `news_entries`. World memory builds continuity over time —
stories escalate, rumours contradict, NPCs react to past events.
"""

from __future__ import annotations

import os
import re
import json
import random
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict

from src.text_mojibake import repair_mojibake

logger = logging.getLogger(__name__)

# Global lock — A1111 can only handle one generation at a time
# Uses a wrapper so the lock auto-releases if A1111 hangs for more than 10 minutes
_a1111_lock = asyncio.Lock()
_A1111_LOCK_TIMEOUT = 600  # 10 minutes


class _TimedA1111Lock:
    """Context manager that acquires _a1111_lock with a timeout.
    If A1111 hangs and never releases, the lock auto-expires after _A1111_LOCK_TIMEOUT seconds."""

    def __init__(self):
        self._acquired = False
        self._lock_ref: asyncio.Lock = None  # exact lock object we acquired

    async def __aenter__(self):
        global _a1111_lock
        import logging
        logger = logging.getLogger(__name__)
        self._lock_ref = _a1111_lock
        try:
            await asyncio.wait_for(self._lock_ref.acquire(), timeout=_A1111_LOCK_TIMEOUT)
            self._acquired = True
            logger.info("🖼️ A1111 lock acquired")
        except asyncio.TimeoutError:
            logger.error(
                f"🖼️ A1111 lock timeout after {_A1111_LOCK_TIMEOUT}s — creating new lock and declaring old one dead"
            )
            # Replace the dead lock; update our reference so __aexit__ releases the right one
            _a1111_lock = asyncio.Lock()
            self._lock_ref = _a1111_lock
            try:
                await asyncio.wait_for(self._lock_ref.acquire(), timeout=10.0)
                self._acquired = True
                logger.warning("🖼️ Acquired fresh A1111 lock after timeout")
            except Exception as e:
                logger.error(f"🖼️ Could not acquire fresh A1111 lock: {e} — proceeding anyway (image will fail)")
                self._acquired = False
        return self

    async def __aexit__(self, *args):
        import logging
        if self._acquired and self._lock_ref is not None:
            try:
                self._lock_ref.release()  # release the exact lock we acquired, not the current module-level one
            except RuntimeError as e:
                logging.getLogger(__name__).warning(f"🖼️ A1111 lock release error: {e}")

    def locked(self) -> bool:
        """Return True if A1111 is currently busy generating an image."""
        return _a1111_lock.locked()


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
from src.bulletin_cleaner import clean_bulletin, validate_bulletin, strip_llm_reasoning, filter_ec_references, repair_incomplete_bulletin
from src.db_api import (
    raw_query, raw_execute, db, get_rift_state, update_rift_state,
    get_story_context, format_story_context_for_prompt,
    get_global_state, set_global_state, add_tension, get_npc_history_count, has_revealed_secrets,
)

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"

MAX_MEMORY_ENTRIES = 40   # total entries kept on disk
MEMORY_CONTEXT_ENTRIES = 5  # qwen3-8b-slim has 8k context — keep it lean

# ---------------------------------------------------------------------------
# Anti-repetition tracking — prevents same NPCs/topics appearing repeatedly
# ---------------------------------------------------------------------------

RECENT_NPC_COOLDOWN = 6  # NPCs featured in last N bulletins are deprioritized
RECENT_TYPE_COOLDOWN = 4  # Don't repeat same bulletin type category for N cycles

PUBLIC_HEALTH_ARC_STATE_KEY = "public_health_arcs"
PUBLIC_HEALTH_ARC_DAYS_MIN = 21
PUBLIC_HEALTH_ARC_DAYS_MAX = 35

_PUBLIC_HEALTH_KEYWORDS = (
    "flu", "outbreak", "virus", "viral", "plague", "fever", "contagion",
    "infection", "infected", "sickness", "illness", "quarantine",
    "epidemic", "clinic", "healer", "healers", "resistant virus",
    "magic-resistant", "magic resistant", "spell-resistant", "ward-resistant",
)

_PUBLIC_HEALTH_DISTRICT_HINTS = (
    "Shantytown Heights", "Dust Market", "Hearthstone District",
    "Lower Warrens", "Markets Infinite", "Outer Wall", "Gutterglass Row",
)

_PUBLIC_HEALTH_CARE_FACTIONS = (
    "Patchwork Saints",
    "Glass Sigil",
    "Wardens of Ash",
    "Adventurers Guild",
    "Sanctum Quarter healers",
    "Tower Authority quarantine office",
)


def _extract_npcs_from_text(text: str, roster_names: List[str]) -> List[str]:
    """Extract roster NPC names mentioned in a bulletin text."""
    found = []
    text_lower = text.lower()
    for name in roster_names:
        # Match whole word only (avoid partial matches)
        if re.search(rf'\b{re.escape(name.lower())}\b', text_lower):
            found.append(name)
    return found


def _get_recently_featured_npcs(memory_entries: List[str], roster_names: List[str]) -> List[str]:
    """
    Scan recent bulletin memory entries and extract which NPCs were featured.
    Returns list of NPC names that appeared in the last RECENT_NPC_COOLDOWN entries.
    """
    recent = memory_entries[-RECENT_NPC_COOLDOWN:] if len(memory_entries) >= RECENT_NPC_COOLDOWN else memory_entries
    featured = set()
    for entry in recent:
        names = _extract_npcs_from_text(entry, roster_names)
        featured.update(names)
    return list(featured)


def _dt_from_iso(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _public_health_active_arcs(include_expired: bool = False) -> List[dict]:
    """Return public-health arcs that should keep appearing in headlines/missions."""
    raw = get_global_state(PUBLIC_HEALTH_ARC_STATE_KEY)
    if isinstance(raw, dict):
        arcs = raw.get("arcs", [])
    elif isinstance(raw, list):
        arcs = raw
    else:
        arcs = []

    now = datetime.utcnow()
    active = []
    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        expires = _dt_from_iso(arc.get("expires_at"))
        if include_expired or not expires or expires >= now:
            active.append(arc)
    return active


def _save_public_health_arcs(arcs: List[dict]) -> None:
    # Preserve top-level canon (e.g. false_cures / snake-oil leads) across re-saves;
    # this writer otherwise replaces the whole blob and would silently drop it.
    existing = get_global_state(PUBLIC_HEALTH_ARC_STATE_KEY)
    payload = {
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "arcs": arcs,
    }
    if isinstance(existing, dict) and existing.get("false_cures"):
        payload["false_cures"] = existing["false_cures"]
    set_global_state(PUBLIC_HEALTH_ARC_STATE_KEY, payload)


def _mentions_public_health_crisis(text: str) -> bool:
    lower = (text or "").lower()
    return any(re.search(r'\b' + re.escape(keyword) + r'\b', lower) for keyword in _PUBLIC_HEALTH_KEYWORDS)


def _extract_public_health_districts(text: str) -> List[str]:
    lower = (text or "").lower()
    districts: List[str] = []

    for district in _PUBLIC_HEALTH_DISTRICT_HINTS:
        if district.lower() in lower:
            districts.append(district)

    try:
        rows = raw_query(
            "SELECT DISTINCT district FROM gazetteer_places "
            "WHERE district IS NOT NULL AND district <> '' LIMIT 200"
        ) or []
        for row in rows:
            district = str(row.get("district") or "").strip()
            if district and district.lower() in lower and district not in districts:
                districts.append(district)
    except Exception:
        pass

    if districts:
        return districts[:4]
    return random.sample(list(_PUBLIC_HEALTH_DISTRICT_HINTS), k=2)


def _public_health_arc_slug(text: str) -> str:
    lower = (text or "").lower()
    if "magic" in lower and ("resistant" in lower or "resist" in lower):
        return "magic_resistant_fever"
    if "flu" in lower:
        return "undercity_flu_outbreak"
    if "virus" in lower or "viral" in lower:
        return "undercity_viral_outbreak"
    if "plague" in lower:
        return "undercity_plague_watch"
    return "public_health_outbreak"


def _public_health_arc_name(slug: str) -> str:
    names = {
        "magic_resistant_fever": "magic-resistant fever",
        "undercity_flu_outbreak": "Undercity flu outbreak",
        "undercity_viral_outbreak": "Undercity viral outbreak",
        "undercity_plague_watch": "Undercity plague watch",
        "public_health_outbreak": "public-health outbreak",
    }
    return names.get(slug, slug.replace("_", " "))


def _upsert_public_health_arc_from_bulletin(bulletin: str) -> None:
    """Turn outbreak-style bulletins into weeks-long campaign pressure."""
    if not _mentions_public_health_crisis(bulletin):
        return

    now = datetime.utcnow()
    slug = _public_health_arc_slug(bulletin)
    all_arcs = _public_health_active_arcs(include_expired=True)
    active_arcs = _public_health_active_arcs(include_expired=False)
    arc = next((item for item in active_arcs if item.get("slug") == slug), None)

    if arc is None:
        duration = random.randint(PUBLIC_HEALTH_ARC_DAYS_MIN, PUBLIC_HEALTH_ARC_DAYS_MAX)
        arc = {
            "slug": slug,
            "name": _public_health_arc_name(slug),
            "status": "active",
            "started_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + timedelta(days=duration)).isoformat(timespec="seconds"),
            "headline_count": 0,
            "mission_seed_count": 0,
            "affected_districts": _extract_public_health_districts(bulletin),
            "affected_populace": [
                "families with sick elders",
                "night-shift laborers",
                "market runners",
                "clinic volunteers",
            ],
            "care_factions": list(_PUBLIC_HEALTH_CARE_FACTIONS),
            "mission_pressure": [
                "recover mundane reagents that magic cannot replace",
                "escort healers through frightened streets",
                "find patient-zero records before officials bury them",
                "protect quarantine lines and food deliveries",
                "investigate why healing magic fails on the fever",
            ],
        }
        all_arcs.append(arc)

    arc["last_seen_at"] = now.isoformat(timespec="seconds")
    arc["headline_count"] = int(arc.get("headline_count") or 0) + 1
    arc["last_bulletin_excerpt"] = _strip_to_facts(bulletin)[:280]
    current_districts = list(arc.get("affected_districts") or [])
    for district in _extract_public_health_districts(bulletin):
        if district not in current_districts:
            current_districts.append(district)
    arc["affected_districts"] = current_districts[:5]

    _save_public_health_arcs(all_arcs)

    district_text = ", ".join(arc.get("affected_districts") or ["the lower city"])
    add_tension(
        f"Public health crisis: {arc.get('name')} is active in {district_text}; "
        "ordinary curatives and healing magic are unreliable, and clinics, families, "
        "and care factions are asking for help."
    )


def _public_health_arc_prompt_block() -> str:
    arcs = _public_health_active_arcs()
    if not arcs:
        return ""

    lines = []
    for arc in arcs[:3]:
        districts = ", ".join(arc.get("affected_districts") or ["the lower city"])
        cares = ", ".join((arc.get("care_factions") or list(_PUBLIC_HEALTH_CARE_FACTIONS))[:4])
        expires = arc.get("expires_at", "ongoing")
        lines.append(
            f"- {arc.get('name', 'public-health outbreak')} in {districts}; "
            f"care pressure from {cares}; active until about {expires}."
        )

    raw = get_global_state(PUBLIC_HEALTH_ARC_STATE_KEY)
    false_cures = raw.get("false_cures", []) if isinstance(raw, dict) else []
    fraud_block = ""
    if false_cures:
        fc_lines = [
            f"- {fc.get('name', 'a street cure')}: {fc.get('truth', 'snake oil that does not work')}"
            for fc in false_cures[:3]
        ]
        fraud_block = (
            "\nKNOWN SNAKE-OIL / FRAUDULENT CURES — treat these as scams, NEVER report them as cures that work:\n"
            + "\n".join(fc_lines)
            + "\nIf such a 'cure' appears in a bulletin, frame it as a fraud preying on the desperate, a public "
              "warning, or a thread someone should investigate — never as a real remedy."
        )

    return (
        "\nONGOING PUBLIC-HEALTH ARC:\n"
        + "\n".join(lines)
        + "\nThis is not a one-night story. Keep it alive across weeks with follow-up headlines, "
          "clinic updates, quarantine politics, scarcity, grief, disputed cures, and public pressure. "
          "Healing magic should be unreliable against the sickness unless a later story resolves why."
        + fraud_block
    )


def _load_variety_state() -> Dict:
    """Load variety tracking state from database."""
    try:
        rows = raw_query(
            "SELECT state_value FROM global_state WHERE state_key = 'news_variety'"
        )
        if rows and rows[0].get("state_value"):
            data = rows[0]["state_value"]
            if isinstance(data, str):
                data = json.loads(data)
            return data
        return {"recent_types": [], "recent_npcs": [], "recent_districts": []}
    except Exception:
        return {"recent_types": [], "recent_npcs": [], "recent_districts": []}


def _save_variety_state(state: Dict) -> None:
    """Save variety tracking state to database."""
    try:
        json_str = json.dumps(state, ensure_ascii=False, default=str)
        existing = raw_query(
            "SELECT id FROM global_state WHERE state_key = 'news_variety'"
        )
        if existing:
            raw_execute(
                "UPDATE global_state SET state_value = %s WHERE state_key = 'news_variety'",
                (json_str,)
            )
        else:
            db.insert("global_state", {
                "state_key": "news_variety",
                "state_value": json_str
            })
    except Exception as e:
        logger.warning(f"📰 Could not save variety state: {e}")


def _categorize_bulletin_type(type_str: str) -> str:
    """
    Categorize a bulletin type string into a broad category.
    Used to avoid repeating the same category too often.
    ORDER MATTERS — human_interest must come before district because human
    interest types often name a district as their setting, not their subject.
    """
    type_lower = type_str.lower()

    # Human interest — MUST be checked before district/location so that
    # "human interest piece about a Warrens resident" doesn't get tagged as district
    if any(w in type_lower for w in [
        "human interest", "resident", "vendor", "heartwarming", "community notice",
        "letter to the dispatch", "letter to", "profile of a minor", "unnamed",
        "street performer", "beggar", "parent", "survivor", "craftsperson",
        "small story", "oddity", "curiosity", "weird", "strange", "community",
        "classified ad", "classified", "species", "species-specific",
        "coroner", "registry of the dead", "deceased", "morgue", "inquest",
        "found-object", "neighbourhood", "coming-of-age",
    ]):
        return "human_interest"
    # NPC/person focused
    if any(w in type_lower for w in ["npc", "roster", "party", "member", "altercation", "confrontation"]):
        return "npc_focused"
    # Crime/incident
    if any(w in type_lower for w in ["crime", "incident", "wanted", "bounty", "missing"]):
        return "crime"
    # Politics/faction
    if any(w in type_lower for w in ["political", "council", "faction", "guild", "authority", "fta"]):
        return "politics"
    # Economy/trade
    if any(w in type_lower for w in ["trade", "market", "price", "commerce", "black market"]):
        return "economy"
    # Divine/religious
    if any(w in type_lower for w in ["divine", "religious", "serpent choir", "god", "contract"]):
        return "divine"
    # Arena/combat
    if any(w in type_lower for w in ["arena", "argent blades", "duel", "combat"]):
        return "arena"
    # Rumour/gossip
    if any(w in type_lower for w in ["rumour", "gossip", "whisper", "overheard"]):
        return "rumour"
    # Weather/environment
    if any(w in type_lower for w in ["weather", "environmental", "hazard"]):
        return "environment"
    # District/location — checked last since it's the broadest fallback for place names
    if any(w in type_lower for w in ["warrens", "markets infinite", "grand forum", "sanctum", "guild spires", "outer wall"]):
        return "district"

    return "general"


def _pick_varied_bulletin_type(all_types: List[str]) -> tuple[str, str]:
    """
    Pick a bulletin type while avoiding recently used categories.
    Returns (chosen_type, category).
    """
    state = _load_variety_state()
    recent_categories = state.get("recent_types", [])[-RECENT_TYPE_COOLDOWN:]

    # Categorize all available types
    categorized = [(t, _categorize_bulletin_type(t)) for t in all_types]

    # Filter out types whose category was recently used
    available = [(t, c) for t, c in categorized if c not in recent_categories]

    # If all categories were recently used, reset and use full list
    if not available:
        available = categorized

    # Pick randomly from available
    chosen_type, chosen_cat = random.choice(available)

    # Update state
    recent_categories.append(chosen_cat)
    if len(recent_categories) > RECENT_TYPE_COOLDOWN * 2:
        recent_categories = recent_categories[-RECENT_TYPE_COOLDOWN:]
    state["recent_types"] = recent_categories
    _save_variety_state(state)

    return chosen_type, chosen_cat

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

# Spawn chance per bulletin tick by location type
# Rifts should still feel like major events, but injuries and near-misses need
# to appear often enough to feed exploration / discovery / first-contact jobs.
RIFT_SPAWN_CHANCE = {
    "warrens":    0.008,  # 0.8% per tick
    "outer_wall": 0.003,  # 0.3% per tick
    "other":      0.0006, # 0.06% per tick
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

RIFT_FACTION_AGENDAS = {
    "Wardens of Ash": [
        "seal it before civilians become leverage",
        "establish a cordon and protect the weak",
        "keep challengers and scavengers out until routes are marked",
    ],
    "Glass Sigil": [
        "catalogue readings before the site is disturbed",
        "claim archive rights over anything that came through",
        "suppress panic until the facts are publishable",
    ],
    "Wizards Tower": [
        "study Tower-world generation patterns",
        "test whether the replacement area obeys known arcane laws",
        "send scholars before merchants or cults contaminate evidence",
    ],
    "Iron Fang Consortium": [
        "secure salvage and contract rights",
        "insure or monetize safe routes through the changed area",
        "turn the collapse into exclusive access",
    ],
    "Obsidian Lotus": [
        "move quietly before official maps catch up",
        "extract people, memories, or contraband without attribution",
        "identify who benefits if the area stays unrecorded",
    ],
    "Patchwork Saints": [
        "find survivors and get families out first",
        "stop factions from treating new arrivals like resources",
        "turn replacement streets into shelter before speculators arrive",
    ],
    "Tower Authority": [
        "lock down jurisdiction and public safety records",
        "issue permits for access, study, and cleanup",
        "decide whether the old address is retired or legally continuous",
    ],
    "Serpent Choir": [
        "interpret the collapse as omen or contract breach",
        "claim ritual responsibility for what crossed over",
        "prevent profane handling of new dead, gods, or sacred signs",
    ],
    "Argent Blades": [
        "sell protection and escort contracts into the zone",
        "win public glory by being seen near the danger",
        "challenge anything dangerous enough to make a name",
    ],
    "Guild of Ashen Scrolls": [
        "record what was lost and what replaced it",
        "determine whether fate records still match the old place",
        "preserve histories before the new map overwrites memory",
    ],
}


def _rift_faction_agendas(rift: Dict) -> List[Dict[str, str]]:
    """Choose faction agendas for a rift so news and missions have fuel."""
    loc_type = rift.get("loc_type", "other")
    stage = rift.get("stage", "whisper")
    priority = ["Wardens of Ash", "Glass Sigil", "Tower Authority"]
    if loc_type == "warrens":
        priority.extend(["Patchwork Saints", "Obsidian Lotus"])
    if loc_type == "outer_wall":
        priority.extend(["Argent Blades", "Iron Fang Consortium"])
    if stage in ("crack", "open", "critical"):
        priority.extend(["Wizards Tower", "Serpent Choir", "Guild of Ashen Scrolls"])
    pool = []
    seen = set()
    for faction in priority + list(RIFT_FACTION_AGENDAS):
        if faction in seen:
            continue
        seen.add(faction)
        pool.append(faction)
    selected = pool[:4]
    if len(selected) < 5:
        selected.extend(random.sample([f for f in RIFT_FACTION_AGENDAS if f not in selected], min(5 - len(selected), len(RIFT_FACTION_AGENDAS))))
    agendas = []
    for faction in selected:
        agendas.append({
            "faction": faction,
            "goal": random.choice(RIFT_FACTION_AGENDAS[faction]),
            "posture": random.choice(["seal", "study", "exploit", "protect", "hide", "claim"]),
        })
    return agendas


def _ensure_rift_tracking(rift: Dict) -> Dict:
    """Backfill tracking fields so active rifts can be mined by missions."""
    rift.setdefault("faction_agendas", _rift_faction_agendas(rift))
    rift.setdefault("event_log", [])
    rift.setdefault("news_count", 0)
    rift.setdefault("mission_fuel", [])
    return rift


def _record_rift_event(rift: Dict, event: str, note: str = "") -> None:
    _ensure_rift_tracking(rift)
    rift["event_log"].append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "stage": rift.get("stage"),
        "note": note,
    })
    rift["event_log"] = rift["event_log"][-20:]


def get_rift_mission_fuel(limit: int = 5) -> List[Dict]:
    """
    Return tracked Rift situations that can seed Exploration, Discovery, and
    First Contact modules. Read-only helper for mission pipelines.
    """
    rifts = _load_rift_state()
    fuel = []
    for rift in rifts:
        _ensure_rift_tracking(rift)
        if rift.get("resolved") and not rift.get("replacement_needed"):
            continue
        fuel.append({
            "id": rift.get("id"),
            "location": rift.get("location"),
            "loc_type": rift.get("loc_type"),
            "stage": rift.get("stage"),
            "resolved": rift.get("resolved", False),
            "outcome": rift.get("outcome"),
            "replacement_needed": rift.get("replacement_needed", False),
            "collapsed_area_status": rift.get("collapsed_area_status"),
            "faction_agendas": rift.get("faction_agendas", []),
            "event_log": rift.get("event_log", [])[-6:],
            "mission_fuel": rift.get("mission_fuel", []),
            "last_news_at": rift.get("last_news_at"),
            "news_count": rift.get("news_count", 0),
        })
    fuel.sort(key=lambda r: (bool(r.get("replacement_needed")), r.get("last_news_at") or ""), reverse=True)
    return fuel[:limit]


def _load_rift_state() -> List[Dict]:
    """Load rift state from database."""
    try:
        state = get_rift_state()
        if not state:
            return []
        # Rifts are stored in effects_json field
        effects = state.get("effects_json", {})
        if isinstance(effects, str):
            effects = json.loads(effects) if effects else {}
        # effects_json contains {"rifts": [...]} or just the rifts list directly
        if isinstance(effects, dict):
            rifts = effects.get("rifts", [])
        elif isinstance(effects, list):
            rifts = effects
        else:
            rifts = []
        return rifts if isinstance(rifts, list) else []
    except Exception as e:
        logger.error(f"🌀 Rift state load error: {e}")
        return []


def _save_rift_state(rifts: List[Dict]) -> None:
    """Save rift state to database."""
    try:
        # Store rifts in effects_json column (JSON type)
        # Also update other columns for basic rift status
        active_rifts = [r for r in rifts if not r.get("resolved")]
        update_data = {
            "active": len(active_rifts) > 0,
            "intensity": len(active_rifts),
            "location": active_rifts[0].get("location") if active_rifts else None,
            "effects_json": {"rifts": rifts},  # Store full rifts list in effects_json
        }
        update_rift_state(update_data)
    except Exception as e:
        logger.error(f"🌀 Could not save rift state: {e} — Rifts may be lost on bot restart")


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
            } | {"faction_agendas": _rift_faction_agendas({"location": location, "loc_type": loc_type, "stage": "whisper"})}
    return None


# ---------------------------------------------------------------------------
# Rift auto-resolution — NPC parties and factions seal rifts over time
# ---------------------------------------------------------------------------
# Early stages can fizzle on their own. Later stages require faction response.
# The chance to auto-resolve is checked EACH TICK (hourly) once minimum
# stage time has passed. Higher stages = lower auto-seal chance but higher
# drama. If a rift reaches "critical" without being sealed, it either gets
# a last-ditch NPC seal or becomes a disaster.
#
# Players can always pre-empt this via /sealrift or by completing a rift mission.

# Per-tick auto-resolution chance BY STAGE (checked after min days elapsed)
RIFT_AUTO_RESOLVE_CHANCE = {
    "whisper":  0.25,   # 25% — most whispers just fizzle out naturally
    "tremor":   0.15,   # 15% — Glass Sigil containment sometimes works
    "crack":    0.10,   # 10% — needs real intervention, but NPC parties try
    "open":     0.08,   # 8%  — hard to seal, NPC parties take casualties
    "critical": 0.05,   # 5%  — last-ditch heroics, very unlikely without players
}

# Who seals it — flavour varies by stage and location
_RIFT_SEALERS = {
    "whisper": [
        ("fizzle",    "The anomaly dissipated on its own. Glass Sigil instruments confirm: readings normal. False alarm."),
        ("glass_sigil", "Glass Sigil containment team deployed a residue siphon near {location}. Readings stabilised within hours."),
        ("natural",   "Whatever was building near {location} has stopped. No explanation. The city moves on."),
    ],
    "tremor": [
        ("glass_sigil", "A Glass Sigil rapid-response unit sealed the micro-fracture near {location} before it could widen. Textbook containment."),
        ("wardens",   "Wardens of Ash cordoned {location} while Glass Sigil technicians ran a three-hour stabilisation protocol. Tremors ceased."),
        ("natural",   "The tremors near {location} stopped as suddenly as they started. Glass Sigil is calling it a pressure equalisation event. Nobody believes them."),
    ],
    "crack": [
        ("npc_party", "An NPC adventurer party — {party_name} — sealed the crack at {location} after a six-hour operation. Two members hospitalised."),
        ("wardens",   "Captain Korin deployed a full Warden containment squad to {location}. The crack was sealed with arcane cement and faith. Holding, for now."),
        ("glass_sigil", "Senior Archivist Pell personally oversaw the sealing at {location}. Three Glass Sigil instruments were sacrificed in the process."),
    ],
    "open": [
        ("npc_party", "{party_name} went into the open Rift at {location} and came back missing a member. But the Rift is sealed. Nobody's celebrating."),
        ("wardens",   "A combined Warden-Argent Blades strike team sealed the Rift at {location}. Casualties reported but not confirmed. The area remains cordoned."),
        ("faction_joint", "An unprecedented joint operation between the Wardens and the Serpent Choir sealed the Rift at {location}. The Choir's contract for the sealing is said to be... extensive."),
    ],
    "critical": [
        ("npc_party", "{party_name} made a suicide run into the critical Rift at {location}. Against all odds, they sealed it. The party is in critical condition. The city owes them everything."),
        ("wardens",   "Captain Korin led a last-stand operation at {location}. The Rift is sealed. Three Wardens did not come back. The Wall held."),
        ("sacrifice", "An unidentified mage walked into the critical Rift at {location} alone. The tear closed behind them. Nobody knows who they were. The Glass Sigil is looking into it."),
    ],
}

# NPC party names for auto-resolution flavour
_SEAL_PARTY_NAMES = [
    "Dustline Seven", "The Borrowed Hours", "Faultline Compact",
    "Gravelight Company", "Ironveil Syndicate", "The Pale Majority",
    "Remnant Clause", "Stormline Company", "The Weighted Verdict",
    "Thorngate Crew", "Ashveil Collective", "The Cracked Seal",
    "Six Feet Forward", "Ember Writ", "The Open Account",
    "Coldbrook Syndicate", "Warden's Folly", "Last Rites Collective",
]


def _tick_rifts(rifts: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    """
    Advance all active Rifts by one bulletin tick.
    Stage advancement is gated on REAL DAYS elapsed since stage_entered_at,
    not tick counts. Once the minimum days have passed, each tick rolls 20%
    to advance — so stages typically move within a few hours of becoming eligible.

    Auto-resolution is also checked each tick: NPC parties, factions, or
    natural fizzle can seal a rift before it escalates further.
    """
    events = []
    now = datetime.now()

    for rift in rifts:
        if rift.get("resolved"):
            continue
        _ensure_rift_tracking(rift)

        stage = rift["stage"]
        min_days = RIFT_MIN_DAYS.get(stage, 2)

        # Calculate real days elapsed at current stage
        try:
            entered = datetime.fromisoformat(rift["stage_entered_at"])
            days_elapsed = (now - entered).total_seconds() / 86400
        except (KeyError, ValueError) as date_err:
            logger.warning(f"🌀 Could not parse rift stage_entered_at: {date_err} — skipping this rift")
            days_elapsed = 0

        # Emit a bulletin if this stage hasn't been announced yet
        if rift.get("last_bulletin_stage") != stage:
            events.append({"rift": rift, "event": "stage_update"})
            rift["last_bulletin_stage"] = stage
            _record_rift_event(rift, "stage_update", f"Bulletin queued for {stage}.")

        # --- Auto-resolution check (once min days have passed) ---
        # Roll BEFORE advancement so a rift can be sealed at its current stage.
        # Skip if it was JUST announced this tick (give it at least one bulletin).
        if (days_elapsed >= min_days
                and rift.get("last_bulletin_stage") == stage
                and random.random() < RIFT_AUTO_RESOLVE_CHANCE.get(stage, 0)):
            # Sealed!
            seal_options = _RIFT_SEALERS.get(stage, _RIFT_SEALERS["crack"])
            sealer_type, seal_template = random.choice(seal_options)
            party_name = random.choice(_SEAL_PARTY_NAMES)
            seal_desc = seal_template.format(
                location=rift["location"],
                party_name=party_name,
            )
            rift["resolved"]    = True
            rift["outcome"]     = "sealed"
            rift["sealed_by"]   = sealer_type
            rift["sealed_at"]   = now.isoformat()
            rift["seal_desc"]   = seal_desc

            # Rift sealed — partial wealth recovery (cleanup and investment follow)
            if rift.get("location"):
                try:
                    from src.db_api import adjust_district_wealth
                    adjust_district_wealth(
                        rift["location"], +1,
                        f"Rift sealed by {sealer_type} — recovery begins"
                    )
                except Exception:
                    pass
            if sealer_type == "npc_party":
                rift["seal_party"] = party_name
            _record_rift_event(rift, "sealed", seal_desc)
            events.append({"rift": rift, "event": "sealed"})
            continue  # don't also try to advance

        # --- Try to advance once minimum real days have elapsed ---
        if days_elapsed >= min_days and random.random() < RIFT_ADVANCE_CHANCE:
            current_idx = RIFT_STAGES.index(stage)
            if current_idx < len(RIFT_STAGES) - 1:
                rift["stage"]            = RIFT_STAGES[current_idx + 1]
                rift["stage_entered_at"] = now.isoformat()  # reset timer for new stage
                if rift["stage"] in ("crack", "open", "critical"):
                    for fuel_type in ("Exploration", "Discovery", "First Contact", "Rescue"):
                        if fuel_type not in rift["mission_fuel"]:
                            rift["mission_fuel"].append(fuel_type)
                _record_rift_event(rift, "advanced", f"Advanced from {stage} to {rift['stage']}.")

                # Rift advancement damages local district wealth
                # The deeper the stage, the harder the hit
                stage_damage = {
                    "tremor": -1, "crack": -1, "tear": -2,
                    "breach": -2, "cascade": -3, "critical": -3,
                }
                dmg = stage_damage.get(rift["stage"], 0)
                if dmg and rift.get("location"):
                    try:
                        from src.db_api import adjust_district_wealth
                        adjust_district_wealth(
                            rift["location"], dmg,
                            f"Rift advanced to {rift['stage']} stage"
                        )
                    except Exception:
                        pass
            else:
                # Critical stage expired unaddressed — disaster
                rift["resolved"] = True
                rift["outcome"]  = "disaster"
                rift["collapsed_area_status"] = "historical"
                rift["replacement_needed"] = True
                for fuel_type in ("Exploration", "Discovery", "First Contact"):
                    if fuel_type not in rift["mission_fuel"]:
                        rift["mission_fuel"].append(fuel_type)
                _record_rift_event(rift, "disaster", "Unchecked cascade collapsed and replaced the local area.")
                events.append({"rift": rift, "event": "disaster"})
                # Disaster wipes district wealth
                if rift.get("location"):
                    try:
                        from src.db_api import adjust_district_wealth
                        adjust_district_wealth(
                            rift["location"], -4,
                            "Rift disaster — unchecked cascade"
                        )
                    except Exception:
                        pass

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
    """
    Generate a Rift-stage bulletin using KimiAgent.

    REFACTORED: Now uses src.agents.generate_bulletin helper.
    """
    from src.agents import generate_bulletin
    import logging
    logger = logging.getLogger(__name__)

    location  = rift["location"]
    stage     = rift["stage"]
    flavour   = RIFT_STAGE_FLAVOUR.get(stage, "").format(location=location)
    agendas = rift.get("faction_agendas") or _rift_faction_agendas(rift)
    agenda_lines = "; ".join(
        f"{a.get('faction')}: {a.get('goal')}"
        for a in agendas[:5]
    )

    if event == "disaster":
        instruction = (
            f"A Rift at {location} was never sealed and has collapsed into a disaster. "
            f"Write a 3-4 line emergency bulletin. Terse, grim, specific. "
            f"What happened to the immediate area. Who is responding. What is lost. "
            f"The old local area is now historical / retired and replacement survey work is needed. "
            f"Faction agendas in play: {agenda_lines}."
        )
    elif event == "sealed":
        seal_desc = rift.get("seal_desc", f"The Rift at {location} has been sealed.")
        seal_stage = stage  # the stage it was at when sealed
        instruction = (
            f"A Rift at {location} has been SEALED at the '{seal_stage}' stage. "
            f"Resolution: {seal_desc} "
            f"Write a 3-4 line Undercity bulletin reporting the successful sealing. "
            f"Tone depends on the stage it was sealed at: "
            f"whisper/tremor = brief, matter-of-fact, city barely noticed. "
            f"crack = relief, some concern about what could have been. "
            f"open/critical = dramatic, heroic, the city owes someone. "
            f"Include the specific resolution details above. Ground it in the location. "
            f"Mention one faction agenda only if it makes the bulletin sharper: {agenda_lines}."
        )
    else:
        instruction = (
            f"Write a 3-4 line Undercity bulletin about a Rift situation at {location}. "
            f"Current status: {flavour} "
            f"Tone matches the stage — early stages are rumour and unease, "
            f"later stages are alarm and urgency. "
            f"Do NOT over-dramatise early stages. A whisper is just a whisper. "
            f"Factions may be trying to seal, study, exploit, protect, hide, or claim the site. "
            f"Faction agendas in play: {agenda_lines}."
        )

    try:
        bulletin = await generate_bulletin(
            news_type="rift",
            instruction=instruction,
            max_lines=4,
        )
        return bulletin
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
        _ensure_rift_tracking(new_rift)
        for fuel_type in ("Exploration", "Discovery"):
            if fuel_type not in new_rift["mission_fuel"]:
                new_rift["mission_fuel"].append(fuel_type)
        _record_rift_event(new_rift, "spawned", f"Rift whisper began near {new_rift.get('location')}.")
        rifts.append(new_rift)

    # Tick all active Rifts
    rifts, events = _tick_rifts(rifts)
    _save_rift_state(rifts)

    # Generate a bulletin for the first notable event (don't spam multiple per tick)
    if events:
        ev       = events[0]
        bulletin = await _generate_rift_bulletin(ev["rift"], ev["event"])
        if bulletin:
            ev["rift"]["last_news_at"] = datetime.now().isoformat(timespec="seconds")
            ev["rift"]["news_count"] = int(ev["rift"].get("news_count", 0)) + 1
            _record_rift_event(ev["rift"], "news", f"Published {ev['event']} bulletin.")
            _write_rift_memory(bulletin, ev["rift"], ev["event"])
            _save_rift_state(rifts)
            output = f"-# 🕰️ {_dual_timestamp()}\n\n{bulletin}"

    return output


# ---------------------------------------------------------------------------
# TowerBay + TIA cadence tracking
# ---------------------------------------------------------------------------


def _load_cadence() -> Dict:
    """Load bulletin cadence tracking from database."""
    try:
        rows = raw_query(
            "SELECT state_value FROM global_state WHERE state_key = 'economy_cadence'"
        )
        if rows and rows[0].get("state_value"):
            data = rows[0]["state_value"]
            if isinstance(data, str):
                data = json.loads(data)
            return data
        return {}
    except Exception:
        return {}


def _save_cadence(data: Dict) -> None:
    """Save bulletin cadence tracking to database."""
    try:
        json_str = json.dumps(data, ensure_ascii=False, default=str)
        existing = raw_query(
            "SELECT id FROM global_state WHERE state_key = 'economy_cadence'"
        )
        if existing:
            raw_execute(
                "UPDATE global_state SET state_value = %s WHERE state_key = 'economy_cadence'",
                (json_str,)
            )
        else:
            db.insert("global_state", {
                "state_key": "economy_cadence",
                "state_value": json_str
            })
    except Exception as e:
        logger.error(f"📰 Could not save bulletin cadence: {e} — timing data may be lost")


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
    ai_sold, player_sold = await tick_towerbay()

    # Post sold notifications for player listings
    if player_sold and channel:
        for item in player_sold:
            try:
                embed = format_sold_notification(item)
                await channel.send(embed=embed)
            except Exception as e:
                import logging as _log
                _log.getLogger(__name__).warning(f"🏪 Could not post sold notification: {e}")

    # Post winning-bid bulletins for NPC/party Tower Bay wins (~1/day, low noise)
    if ai_sold and channel:
        for item in ai_sold:
            winner = item.get("npc_bidder_name") or item.get("highest_bidder_name")
            if not winner:
                continue
            faction = item.get("npc_bidder_faction") or ""
            item_name = item.get("name", "Unknown Item")
            final_bid = item.get("current_bid", 0)
            rarity = item.get("rarity", "")
            rarity_str = f" ({rarity.title()})" if rarity else ""
            faction_str = f" of {faction}" if faction and faction != winner else ""
            bulletin = (
                f"🏆 **TOWERBAY CLOSED: {item_name}**{rarity_str}\n"
                f"**{winner}**{faction_str} secured the lot at **{final_bid:,} EC**.\n"
                f"Item has left the board. Delivery arrangements are private."
            )
            try:
                from src.bulletin_embeds import wrap_bulletin
                from src.expandable_bulletin import make_bulletin_view
                embed = wrap_bulletin(bulletin, "news")
                view = make_bulletin_view(
                    bulletin, "news",
                    headline=f"TowerBay: {item_name} sold",
                    source_attribution="TowerBay Auction House",
                )
                await channel.send(embed=embed, view=view)
                _write_memory(f"TowerBay: {item_name} won by {winner}{faction_str} for {final_bid:,} EC.")
                logger.info(f"🏪 Posted sold bulletin: {item_name} → {winner}")
            except Exception as _e:
                logger.warning(f"🏪 Could not post win bulletin for {item_name}: {_e}")

    last_str = cadence.get("towerbay_last_post")
    if last_str:
        try:
            last = datetime.fromisoformat(last_str)
            if (now - last).total_seconds() < 23 * 3600:  # 23h gate
                return None
        except ValueError as e:
            logger.warning(f"🏪 Corrupted towerbay_last_post timestamp: {last_str} — {e}")

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
        except ValueError as e:
            logger.warning(f"💱 Corrupted exchange_last_post timestamp: {last_str} — {e}")

    cadence["exchange_last_post"] = now.isoformat()
    _save_cadence(cadence)

    bulletin = format_exchange_bulletin()
    _write_memory("[EC/Kharma exchange rate posted]")
    return f"-# 🕰️ {_dual_timestamp()}\n\n{bulletin}"


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
        except ValueError as e:
            logger.warning(f"📊 Corrupted tia_last_post timestamp: {last_str} — {e}")

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
    return f"-# \U0001f570\ufe0f {_dual_timestamp()}\n\n{bulletin}"


async def check_arena_tick() -> Optional[str]:
    """
    Called each bulletin cycle.
    Posts arena match result when one is due (every 2-3 days).
    """
    bulletin = await tick_arena()
    if bulletin:
        _write_memory("[Arena match result posted]")
        return f"-# 🕰️ {_dual_timestamp()}\n\n{bulletin}"
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
        outputs.append(f"-# 🕰️ {_dual_timestamp()}\n\n{text}")
    return outputs


async def check_development_tick() -> Optional[str]:
    """
    Called each bulletin cycle.
    Fires roughly every 2-3 days and generates a positive wealth event:
    new construction, major business opening, renovation, business relocation,
    or faction investment. Adjusts district wealth_level in DB and posts a bulletin.

    Counterweight to rift damage and disasters — the city rebuilds and grows too.
    """
    cadence = _load_cadence()
    now     = datetime.now()

    last_str = cadence.get("development_last_post")
    if last_str:
        try:
            last = datetime.fromisoformat(last_str)
            hours_since = (now - last).total_seconds() / 3600
            # Fire every 48-72 hours, with a 30% chance at the 48h mark
            if hours_since < 48:
                return None
            if hours_since < 72 and random.random() > 0.3:
                return None
        except ValueError:
            pass

    # Select a random positive event type with weighted probabilities
    event_types = [
        ("construction",       0.18),  # new building/structure going up
        ("business_open",      0.22),  # major business/venue opens
        ("renovation",         0.18),  # existing structure renovated
        ("relocation",         0.12),  # business moves district to district
        ("investment",         0.12),  # faction invests in a district
        ("charitable",         0.05),  # general aid/donations
        ("religious_outreach", 0.13),  # god/church charity, missions, recruiting
    ]
    roll = random.random()
    cumulative = 0.0
    event_type = "construction"
    for etype, prob in event_types:
        cumulative += prob
        if roll <= cumulative:
            event_type = etype
            break

    # Load districts with their current wealth levels from DB
    try:
        from src.db_api import raw_query as _rq, adjust_district_wealth
        district_rows = _rq(
            "SELECT district, AVG(wealth_level) as w "
            "FROM gazetteer_places "
            "GROUP BY district ORDER BY district"
        ) or []
        districts = {r["district"]: round(float(r["w"])) for r in district_rows}
    except Exception:
        return None

    if not districts:
        return None

    # Load faction names for flavor
    try:
        factions = [r["faction_name"] for r in (_rq("SELECT faction_name FROM faction_reputation") or [])]
    except Exception:
        factions = ["Iron Fang Consortium", "Argent Blades", "Serpent Choir",
                    "Glass Sigil", "Patchwork Saints", "Wardens of Ash"]

    # District selection — weighted by event type
    def pick_district(wealth_min=1, wealth_max=10, exclude=None):
        eligible = {d: w for d, w in districts.items()
                    if wealth_min <= w <= wealth_max and d != exclude}
        if not eligible:
            eligible = {d: w for d, w in districts.items() if d != exclude}
        return random.choice(list(eligible.keys())) if eligible else None

    bulletin_text = None
    district_a    = None
    district_b    = None
    delta_a       = 0
    delta_b       = 0
    reason        = ""

    faction = random.choice(factions)

    if event_type == "construction":
        district_a = pick_district(wealth_min=3, wealth_max=7)
        delta_a, reason = +1, f"{faction} new construction project"
        bulletin_text = (
            f"**🏗️ CONSTRUCTION NOTICE — {district_a.upper()}**\n"
            f"Ground has broken on a new {random.choice(['warehouse complex','transit hub','guild annex','residential block','market hall','medical station'])} "
            f"in the {district_a} district, funded by the {faction}. "
            f"The project is expected to bring work contracts and improve local infrastructure. "
            f"*District wealth index adjusted.*"
        )

    elif event_type == "business_open":
        # Wealthy districts attract premium venues; poor districts get aid-style openings
        district_a = pick_district(wealth_min=4, wealth_max=9)
        w = districts[district_a]
        if w >= 7:
            venue = random.choice(["luxury exchange house", "guild certification office",
                                   "high-end auction house", "arcane licensing bureau",
                                   "faction embassy annex", "premium healing parlour"])
        elif w >= 5:
            venue = random.choice(["trading post", "smithy and supply depot", "tavern and inn",
                                   "apothecary", "courier dispatch", "alchemist's shop"])
        else:
            venue = random.choice(["aid station", "community canteen", "salvage cooperative",
                                   "Patchwork Saints clinic extension", "basic supply depot"])
        delta_a, reason = +1, f"New {venue} opens in {district_a}"
        bulletin_text = (
            f"**🏪 NEW VENUE — {district_a.upper()}**\n"
            f"A new {venue} has opened its doors in the {district_a} district, "
            f"backed by the {faction}. "
            f"{random.choice(['Residents report cautious optimism.','Lines formed before opening.','Faction officials attended the ribbon-cutting.','The opening was marked by a brief ceremony.'])} "
            f"*District wealth index adjusted.*"
        )

    elif event_type == "renovation":
        district_a = pick_district(wealth_min=2, wealth_max=7)
        delta_a, reason = +1, f"District renovation — {faction} funded"
        bulletin_text = (
            f"**🔨 RENOVATION COMPLETE — {district_a.upper()}**\n"
            f"A {random.choice(['block of tenements','market section','transit walkway','public well system','faction hall','road surface'])} "
            f"in the {district_a} district has been renovated under {faction} funding. "
            f"Structural assessors have cleared the work for occupancy. "
            f"*District wealth index adjusted.*"
        )

    elif event_type == "relocation":
        # Business moves from one district to another — loser and winner
        district_a = pick_district(wealth_min=3, wealth_max=8)  # moving from
        district_b = pick_district(wealth_min=3, wealth_max=8, exclude=district_a)
        if not district_b:
            return None
        delta_a, delta_b = -1, +1
        reason = f"Major business relocates from {district_a} to {district_b}"
        biz = random.choice(["a Consortium trading house", "a Glass Sigil archive branch",
                              "a major healing collective", "an artificers workshop",
                              "a faction courier hub", "a large supply depot"])
        bulletin_text = (
            f"**📦 BUSINESS RELOCATION — DISTRICT IMPACT**\n"
            f"{biz.capitalize()} has announced it is closing its {district_a} location "
            f"and relocating operations to {district_b}. "
            f"{random.choice(['Lease disputes cited as the cause.','Better infrastructure cited.','The move follows recent development investment.','Faction pressure believed to be a factor.'])} "
            f"*Wealth index: {district_a} ↓ · {district_b} ↑*"
        )

    elif event_type == "investment":
        # Faction invests in a district — broader boost
        district_a = pick_district(wealth_min=3, wealth_max=7)
        delta_a, reason = +1, f"{faction} district investment pledge"
        bulletin_text = (
            f"**💰 FACTION INVESTMENT — {district_a.upper()}**\n"
            f"The {faction} has pledged a formal investment package for the {district_a} district, "
            f"covering {random.choice(['street maintenance and lighting','waste management and sanitation','expanded transit access','new faction-operated services','security patrols and emergency response'])}. "
            f"Implementation is expected over the next several weeks. "
            f"*District wealth index adjusted.*"
        )

    elif event_type == "charitable":
        # Aid targets the poorest districts
        district_a = pick_district(wealth_min=1, wealth_max=3)
        delta_a, reason = +1, "Charitable aid and reconstruction"
        bulletin_text = (
            f"**🤝 AID DEPLOYMENT — {district_a.upper()}**\n"
            f"The Patchwork Saints, with support from the {faction}, have deployed "
            f"an emergency reconstruction and aid package to {district_a}. "
            f"{random.choice(['Basic services restored to several blocks.','Temporary shelters replaced with permanent structures.','Food distribution and medical care established.','Structural repairs completed on priority buildings.'])} "
            f"*District wealth index adjusted.*"
        )

    elif event_type == "religious_outreach":
        # A god, church, or cult deploys a charity mission or recruiting drive.
        # Draw from the pantheon DB — low-risk gods target poor districts,
        # suspicious gods (Loki, Brother Thane) may have side effects.
        try:
            from src.db_api import get_charitable_gods
            # 70% chance pick a trustworthy god, 30% chance pick a suspicious one
            suspicious_roll = random.random() < 0.30
            gods = get_charitable_gods(
                suspicious=1 if suspicious_roll else 0,
                max_risk=95,
                limit=10,
            )
            if not gods:
                gods = get_charitable_gods(limit=10)
            god = random.choice(gods) if gods else None
        except Exception:
            god = None

        if not god:
            # Fallback to known setting religions
            god = {
                "name": random.choice(["Cathedral of the Eternal Flame",
                                       "Temple of the Silent Watch",
                                       "Patchwork Saints Healers"]),
                "domain": "Community aid",
                "charity_style": "healing_aid",
                "suspicious": 0,
                "notes": "",
            }

        god_name   = god["name"]
        god_domain = god.get("domain", "")
        is_susp    = god.get("suspicious", 0)
        style      = god.get("charity_style", "healing_aid")
        god_notes  = god.get("notes", "")

        # Target district based on charity style
        if style in ("healing_aid", "grief_aid") or is_susp:
            district_a = pick_district(wealth_min=1, wealth_max=4)
        elif style == "community_craft":
            district_a = pick_district(wealth_min=2, wealth_max=6)
        elif style == "protection_justice":
            district_a = pick_district(wealth_min=2, wealth_max=7)
        elif style == "education":
            district_a = pick_district(wealth_min=1, wealth_max=8)
        else:
            district_a = pick_district(wealth_min=1, wealth_max=5)

        delta_a = +1
        reason  = f"{god_name} religious outreach — {style}"

        # Event description based on charity style
        style_descriptions = {
            "healing_aid":               random.choice([
                "mobile healing stations established throughout the district",
                "free restoration services offered at the temple annexe",
                "medical supplies and healers deployed for three days",
                "clerics moving door to door offering lesser restoration at no cost",
            ]),
            "community_craft":           random.choice([
                "free forge time and materials offered to district artisans",
                "a new communal workshop opened under temple sponsorship",
                "skilled craftspeople donating time to repair district infrastructure",
                "tools and materials distributed to resident workers",
            ]),
            "protection_justice":        random.choice([
                "temple guards assigned to protect the district for the week",
                "free legal advocacy offered to district residents",
                "a justice tribunal held to resolve outstanding disputes",
                "shrine wardens patrolling alongside district residents",
            ]),
            "education":                 random.choice([
                "scribes and scholars offering free literacy sessions",
                "a temporary archive annex opened for public knowledge access",
                "open lectures on history and practical skills running for a week",
                "children's schooling organised and funded for the season",
            ]),
            "grief_aid":                 random.choice([
                "grief counsellors and mourning rites offered freely",
                "a memorial rite held for district residents lost to the last rift",
                "silent monks providing comfort and record-keeping for the bereaved",
                "the names of the district's dead added to the Temple of the Silent Watch registry",
            ]),
            "community_protection":      random.choice([
                # Thor-style: direct, physical, no ceremony
                "a figure matching the description of Thor Odinson was seen carrying debris from a collapsed section — then left without giving a name",
                "unannounced repairs completed overnight on three load-bearing walls that residents had flagged as dangerous",
                "a group of Iron Fang enforcers reportedly abandoned their post after a brief conversation with someone carrying a very large hammer",
                "food, tools, and blankets distributed door to door — the distributor refused to identify themselves or accept thanks",
                "structural inspections completed on every building in the district, repair work begun immediately, still ongoing",
            ]),
            "suspicious_redistribution": random.choice([
                # Loki-style: real help, theatrical, embarrassing to the powerful
                "a charity auction where bidders found their own donated goods returned to them — the proceeds went to residents",
                "an anonymous benefactor sent the district's outstanding FTA licensing fees directly to the FTA, marked 'paid in full, with their regards'",
                "food parcels arrived addressed to each household by name, containing exactly what each family had run out of",
                "the Iron Fang's district warehouse was found emptied overnight — contents redistributed to residents, no signs of forced entry",
                "a community feast held with food that could not be traced to any supplier — the Consortium is still asking questions",
            ]),
        }
        action = style_descriptions.get(style, "aid workers active in the district")

        if is_susp:
            # Suspicious god: aid is genuine, motive is complex.
            # Marvel Loki: chaotic good in practice, just never admits it.
            # Brother Thane: real food, real warmth, genuine recruitment underneath.
            # Vecna/Belial: aid exists but strings are attached — carefully.
            risk = god.get("recruit_risk", 50)
            if risk <= 50:
                # Low-medium risk suspicious god (Loki tier) — theatrical, embarrassing to the powerful
                tone = random.choice([
                    "Residents received the aid without incident. Nobody is quite sure where it came from or why.",
                    "Nobody claimed responsibility. The Consortium issued a statement saying the food was 'accounted for.'",
                    "The aid arrived. The paperwork documenting it mysteriously does not exist.",
                    "Three FTA officials attempted to investigate the source. They have since requested reassignment.",
                ])
                bulletin_text = (
                    f"**⛪ UNEXPLAINED OUTREACH — {district_a.upper()}**\n"
                    f"{action.capitalize()} in the {district_a} district. "
                    f"{tone} "
                    f"Witnesses describe a figure matching **{god_name}** leaving the scene, "
                    f"though no formal claim of credit has been made. "
                    f"*District wealth index adjusted.*"
                )
            else:
                # Higher risk suspicious god — the strings are visible
                susp_note = god_notes[:120] if god_notes else "Motivations remain unclear."
                bulletin_text = (
                    f"**⛪ RELIGIOUS OUTREACH — {district_a.upper()}**\n"
                    f"Followers of **{god_name}** ({god_domain[:60]}) have deployed {action} "
                    f"in the {district_a} district. Residents report genuine benefit. "
                    f"*Note: {susp_note}*\n"
                    f"The Patchwork Saints advise accepting the aid while remaining watchful. "
                    f"*District wealth index adjusted.*"
                )
            # Suspicious outreach also quietly recruits — may plant mission hooks later
            logger.info(
                f"⛪ Suspicious religious outreach: {god_name} in {district_a} "
                f"(recruit risk {god.get('recruit_risk',50)}%)"
            )
        else:
            bulletin_text = (
                f"**⛪ RELIGIOUS OUTREACH — {district_a.upper()}**\n"
                f"The faithful of **{god_name}** ({god_domain[:60]}) have {action} "
                f"in the {district_a} district. "
                f"{random.choice(['Turnout exceeded expectations.','Residents welcomed the presence warmly.','Several converts were welcomed into the faith.','No strings attached, according to temple representatives.'])} "
                f"*District wealth index adjusted.*"
            )

    if not bulletin_text or not district_a:
        return None

    # Apply wealth changes to DB
    new_w_a = adjust_district_wealth(district_a, delta_a, reason)
    logger.info(f"🏗️ Development event [{event_type}]: {district_a} {delta_a:+d} → {new_w_a}")
    if district_b and delta_b:
        new_w_b = adjust_district_wealth(district_b, delta_b, reason)
        logger.info(f"🏗️ Development event [{event_type}]: {district_b} {delta_b:+d} → {new_w_b}")

    cadence["development_last_post"] = now.isoformat()
    _save_cadence(cadence)
    _write_memory(f"[Development event: {event_type} — {district_a}]")

    return f"-# 🕰️ {_dual_timestamp()}\n\n{bulletin_text}"


async def check_council_omen_tick() -> Optional[str]:
    """
    Called each bulletin cycle.
    When party LP >= 7, occasionally posts an atmospheric Culinary Council omen bulletin.
    Frequency and intensity scale with LP tier.

    LP  7-9:  subtle hints, once every 4-6 days
    LP 10-12: recognisable omens, once every 3-4 days
    LP 13-15: personal omens (names, specific deeds), once every 2-3 days
    LP 16+:   direct divine interference, once every 1-2 days
    """
    import json as _json
    from src.db_api import get_legend_points, get_culinary_council

    lp = get_legend_points()
    if lp < 7:
        return None

    cadence = _load_cadence()
    now = datetime.now()

    last_str = cadence.get("council_omen_last_post")
    if last_str:
        try:
            last = datetime.fromisoformat(last_str)
            hours_since = (now - last).total_seconds() / 3600
            # Cadence by LP tier
            if lp >= 16:
                min_hours, chance_at_min = 24, 0.5
            elif lp >= 13:
                min_hours, chance_at_min = 48, 0.4
            elif lp >= 10:
                min_hours, chance_at_min = 72, 0.35
            else:
                min_hours, chance_at_min = 96, 0.25
            if hours_since < min_hours:
                return None
            if random.random() > chance_at_min:
                return None
        except ValueError:
            pass

    # Determine tier
    if lp >= 16:
        tier = "extreme"
    elif lp >= 13:
        tier = "high"
    elif lp >= 10:
        tier = "medium"
    else:
        tier = "low"

    # Pull council members and a member's current_moves for flavor
    council = get_culinary_council()
    member = random.choice(council) if council else None
    member_name = member["name"] if member else "the Culinary Council"
    member_data = {}
    if member:
        try:
            member_data = _json.loads(member["data_json"]) if isinstance(member["data_json"], str) else member["data_json"]
        except Exception:
            pass

    omens_at_lp = member_data.get("omens_at_15lp", [])
    current_moves = member_data.get("current_moves", [])

    # Select an omen template by tier
    low_omens = [
        "Citizens in {district} report an inexplicable craving for a specific meal they cannot describe — the feeling passes in minutes but leaves a sense of being watched.",
        "Several adventurers near {district} describe phantom applause following a recent street altercation. No crowd was present.",
        "A faint smell of roasting spices has been reported in the aftermath of at least three guild skirmishes this week. Investigators have found no source.",
        "A local restaurateur in {district} claims their reservation list has new names they didn't add — the names are written in an ink that smells faintly of cinnamon.",
        "A rift researcher catalogued an unusual energy signature near a recent heroic event — 'it tasted the scene,' she wrote in her notes, then struck the line out.",
    ]
    medium_omens = [
        "Multiple witnesses describe a formally dressed figure — tall, masked — observing a guild skirmish in {district} from across the street. When looked at directly, it was gone.",
        "Food has been spoiling in the vicinity of several notable adventurers at an anomalous rate. The FTA has logged seven separate complaints. No contamination source found.",
        "Three different herbalists in {district} and {district2} report the same unsolicited delivery: a sealed silver envelope, blank inside, smelling of saffron. Recipients describe mild unease.",
        "A Serpent Choir census-taker was observed recording not names but *deeds* — asking residents to recall the exact details of recent heroic acts witnessed. Purpose unclear.",
        "Guild Bulletin archives note an unusual pattern: the Argent Blades' three highest-commendation recipients over the last two months have all accepted 'private consulting arrangements' with an unnamed patron. None have been seen since.",
    ]
    high_omens = [
        "A sealed document found in {district} appears to be a formal banquet menu — with a courses section listing adventurers by name and deed rather than food. Investigators are treating it as a threat. The Choir has issued no statement.",
        "Several party-adjacent NPCs report vivid dreams of being slowly poured from one vessel into another. A cleric examined one dreamer and described finding 'a tasting mark on the soul — something sampled them without permission.'",
        "An Iron Fang Consortium shipping manifest leaked to the Scrolls includes reagents flagged by arcanists as components of a 'heroic essence capture ritual.' The manifest is dated three weeks ago. The Consortium denies the shipment.",
        "High Apostle Yzura of the Serpent Choir held an unscheduled private session with senior guild representatives. The agenda was not disclosed. Attendees describe being asked 'detailed questions about the party's recent movements.'",
        "A Warden of Ash priest was found near {district} distributing a pamphlet titled *'If You Are Invited to Dinner — A Survival Guide.'* The pamphlet advises recipients to never eat, drink, or sign anything at an unsolicited formal event. The Wardens have declined to comment on what prompted its distribution.",
    ]
    extreme_omens = [
        "A divine summons, sealed in bone-white wax bearing an unfamiliar crest, was delivered to the party's usual address. The courier — described as impossibly tall and formally dressed — was gone before a response could be given. The wax smells of cinnamon. The card inside is blank.",
        "The smell of roasting cinnamon and seared meat followed the party through their last three engagements. Several enemies reported smelling it too, moments before being struck. One surrendered citing 'the applause — I could hear applause and there was no one there.'",
        "A divine analyst contracted by the Ashen Scrolls examined ambient essence readings near the party and produced a four-word report before resigning her contract: *'They are being seasoned.'*",
        "Gourmand Prime, the Bone King — a figure previously known only from classified Warden of Ash intelligence reports — has been sighted in the Undercity. A skeletal figure wreathed in divine smoke was observed in the Sanctum Quarter for approximately six minutes before vanishing. He was, according to one witness, smiling.",
    ]

    tier_pools = {
        "low":    low_omens,
        "medium": medium_omens,
        "high":   high_omens,
        "extreme": extreme_omens,
    }
    pool = tier_pools.get(tier, low_omens)

    # Mix in a member-specific omen if available
    if omens_at_lp and random.random() < 0.35:
        pool = list(pool) + omens_at_lp

    omen_template = random.choice(pool)

    # Fill district placeholders
    try:
        from src.db_api import raw_query as _rq
        d_rows = _rq("SELECT DISTINCT district FROM gazetteer_places WHERE district IS NOT NULL") or []
        d_list = [r["district"] for r in d_rows if r["district"]]
    except Exception:
        d_list = ["the Bazaar", "the Warrens", "the Sanctum Quarter", "Rustside", "the Tangle"]

    d1 = random.choice(d_list) if d_list else "the Bazaar"
    d2 = random.choice([d for d in d_list if d != d1]) if len(d_list) > 1 else "the Warrens"
    omen_text = omen_template.format(district=d1, district2=d2)

    # Header varies by tier
    headers = {
        "low":     "**🍽️ UNUSUAL REPORTS**",
        "medium":  "**🍽️ CITY WATCH ADVISORY**",
        "high":    "**🍽️ WARDEN OF ASH BULLETIN**",
        "extreme": "**🍽️ SERPENT CHOIR ADVISORY — DIVINE SUMMONS ISSUED**",
    }
    header = headers.get(tier, "**🍽️ UNUSUAL REPORTS**")

    bulletin_text = f"{header}\n{omen_text}"

    # Log
    logger.info(
        f"🍽️ Council omen fired [LP={lp}, tier={tier}]: "
        f"{member_name} — {omen_text[:80]}..."
    )

    cadence["council_omen_last_post"] = now.isoformat()
    _save_cadence(cadence)
    _write_memory(f"[Council omen posted: LP={lp}, tier={tier}]")

    return f"-# 🕰️ {_dual_timestamp()}\n\n{bulletin_text}"


async def check_missing_tick() -> list:
    """
    Called each bulletin cycle.
    Posts a missing persons notice when due, and any resolution updates.
    Returns list of bulletin strings.

    REFACTORED: generate_missing_bulletin now uses KimiAgent internally.
    """
    outputs = []

    # Check resolutions first
    resolutions = tick_missing_resolutions()
    for r in resolutions:
        _write_memory("[Missing persons resolution]")
        outputs.append(r)

    # Maybe post a new notice
    if should_post_missing():
        bulletin = await generate_missing_bulletin()  # No longer needs ollama params
        if bulletin:
            _write_memory("[Missing persons notice posted]")
            outputs.append(bulletin)

    return outputs


# ---------------------------------------------------------------------------
# World lore — assembled live from the DB so the world can evolve without
# touching source code.  Falls back gracefully if any key is missing.
# ---------------------------------------------------------------------------

def _build_world_lore() -> str:
    """Build the world-lore context block entirely from the DB.

    Sources:
      global_state → world_setting, world_currency, world_gods, world_key_npcs,
                     world_active_tensions
      faction_reputation → live faction list with descriptions, leaders, rep tier
    Placeholders {LIVE_CITY_DISTRICTS} and {LIVE_ROSTER_NPCS} are left intact
    so _build_prompt() can inject them as before.
    """
    from src.db_api import raw_query as _rq
    lines: list[str] = []

    # --- Setting -----------------------------------------------------------
    try:
        rows = _rq("SELECT state_value FROM global_state WHERE state_key = 'world_setting'") or []
        if rows:
            d = rows[0]["state_value"]
            if isinstance(d, str):
                import json as _j; d = _j.loads(d)
            lines.append(f"SETTING: {d.get('overview', '')}")
            if d.get("rifts"):    lines.append(d["rifts"])
            if d.get("adventurers"): lines.append(d["adventurers"])
    except Exception:
        lines.append("SETTING: The Undercity — a sealed city under a Dome, built around the Tower of Last Chance.")

    lines.append("")

    # --- Currency ----------------------------------------------------------
    try:
        rows = _rq("SELECT state_value FROM global_state WHERE state_key = 'world_currency'") or []
        if rows:
            d = rows[0]["state_value"]
            if isinstance(d, str):
                import json as _j; d = _j.loads(d)
            parts = [f"{k} = {v}" for k, v in d.items()]
            lines.append("CURRENCY: " + "  ".join(parts))
    except Exception:
        lines.append("CURRENCY: Essence Coins (EC) = everyday money. Kharma = crystallised faith.")

    lines.append("")

    # --- Factions (live from DB with rep tier) -----------------------------
    try:
        factions = _rq(
            "SELECT faction_name, leader, location_name, description, motto, tier "
            "FROM faction_reputation ORDER BY faction_name"
        ) or []
        if factions:
            lines.append("FACTIONS:")
            for f in factions:
                name  = f["faction_name"]
                loc   = f.get("location_name") or ""
                lead  = f.get("leader") or ""
                desc  = f.get("description") or ""
                motto = f.get("motto") or ""
                tier  = f.get("tier") or ""
                parts = []
                if loc:   name = f"{name} ({loc})"
                if desc:  parts.append(desc.rstrip("."))
                if lead:  parts.append(lead)
                if motto: parts.append(motto)
                if tier and tier not in ("Neutral", "Friendly"):
                    parts.append(f"Rep: {tier}")
                lines.append(f"- {name} — " + ". ".join(parts) if parts else f"- {name}")
    except Exception as e:
        logger.warning(f"news_feed: factions DB read failed: {e}")

    lines.append("")

    # --- Gods --------------------------------------------------------------
    try:
        rows = _rq("SELECT state_value FROM global_state WHERE state_key = 'world_gods'") or []
        if rows:
            import json as _j
            gods = rows[0]["state_value"]
            if isinstance(gods, str): gods = _j.loads(gods)
            lines.append("GODS:")
            for g in gods:
                lines.append(f"- {g.get('name','?')} — {g.get('description','')}")
    except Exception:
        pass

    lines.append("")

    # --- City geography placeholder (filled later by _build_city_districts_block) ---
    lines.append("{LIVE_CITY_DISTRICTS}")
    lines.append("")

    # --- Key named NPCs ----------------------------------------------------
    try:
        rows = _rq("SELECT state_value FROM global_state WHERE state_key = 'world_key_npcs'") or []
        if rows:
            import json as _j
            npcs = rows[0]["state_value"]
            if isinstance(npcs, str): npcs = _j.loads(npcs)
            lines.append("KEY NPCs: " + ", ".join(npcs))
    except Exception:
        pass

    lines.append("")

    # --- Active tensions (from global_state — updated by lifecycle/events) ---
    try:
        rows = _rq("SELECT state_value FROM global_state WHERE state_key = 'world_active_tensions'") or []
        if rows:
            import json as _j
            tensions = rows[0]["state_value"]
            if isinstance(tensions, str): tensions = _j.loads(tensions)
            if tensions:
                lines.append("ACTIVE TENSIONS:")
                for t in tensions:
                    lines.append(f"- {t}")
    except Exception:
        pass

    lines.append("")

    # --- Live roster placeholder (filled later by _build_live_roster_block) ---
    lines.append("{LIVE_ROSTER_NPCS}")

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Mission board parser
# ---------------------------------------------------------------------------

def _load_commercial_context(bulletin_type: str) -> str:
    """
    Load businesses, arena ads, and party sponsorships from the gazetteer
    and return a context block for commercial-type bulletins.
    Only returns content if the bulletin type is commercial-flavoured.
    """
    _commercial_keywords = (
        "advertis", "business", "sponsor", "arena", "shop", "service",
        "stall", "vendor", "craftsperson", "paid", "alchemical", "front"
    )
    if not any(kw in bulletin_type.lower() for kw in _commercial_keywords):
        return ""

    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT content_json FROM gazetteer LIMIT 1") or []
        if not rows or not rows[0].get("content_json"):
            return ""
        data = rows[0]["content_json"]
        if isinstance(data, str):
            data = json.loads(data)
    except Exception as e:
        logger.debug(f"news_feed: _load_commercial_context failed: {e}")
        return ""

    lines = []

    # Businesses — sample a handful to keep prompt size manageable
    businesses = data.get("businesses", {})
    if businesses:
        biz_list = []
        for district, biz_entries in businesses.items():
            for b in biz_entries:
                biz_list.append(
                    f"  {b['name']} ({b['type']}, {district}) — owner: {b['owner']} [{b['faction_affiliation']}] — {b['description']}"
                )
        if biz_list:
            sample = random.sample(biz_list, min(6, len(biz_list)))
            lines.append("KNOWN UNDERCITY BUSINESSES (use these — do not invent conflicting shops):")
            lines.extend(sample)

    # Arena ads — always show if bulletin is arena-related
    arena_ads = data.get("arena_advertisements", [])
    if arena_ads and "arena" in bulletin_type.lower():
        ad = random.choice(arena_ads)
        lines.append(f"\nARENY AD REFERENCE: \"{ad['title']}\" — {ad['copy']}")

    # Sponsorships — show if bulletin is about sponsorship
    if "sponsor" in bulletin_type.lower():
        sponsorships = data.get("party_sponsorships", [])
        open_sponsors = [s for s in sponsorships if s.get("status") == "open"]
        if open_sponsors:
            sp = random.choice(open_sponsors)
            lines.append(
                f"\nSPONSORSHIP REFERENCE: {sp['sponsor']} is currently offering party sponsorship. "
                f"Terms: {sp['terms']} Contact: {sp['contact']}."
            )

    return "\n".join(lines) if lines else ""


def _parse_mission_board() -> str:
    """Build open-mission summary from the missions DB table."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq(
            "SELECT title, faction, tier FROM missions "
            "WHERE status IN ('active','claimed') ORDER BY faction, tier"
        ) or []
        if not rows:
            return ""
        missions = [
            f"- [{r.get('faction','?')}] {r.get('title','?')} ({r.get('tier','?')})"
            for r in rows
        ]
        return "OPEN MISSIONS:\n" + "\n".join(missions)
    except Exception as e:
        logger.warning(f"news_feed: _parse_mission_board DB failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Memory read / write
# ---------------------------------------------------------------------------

def _read_memory() -> List[str]:
    """Read news memory entries from database."""
    try:
        from src.db_api import get_news_memory
        entries = get_news_memory(limit=MAX_MEMORY_ENTRIES)
        # Format entries as [timestamp]\nfacts
        result = []
        for entry in entries:
            ts = entry.get("created_at", "")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            facts = entry.get("facts", "")
            result.append(f"[{ts}]\n{facts}")
        return result
    except Exception as e:
        logger.error(f"News memory read error: {e}")
        return []


def _fit_num_ctx(prompt: str, reply_tokens: int = 1024) -> int:
    """Choose an Ollama context window that actually fits this prompt plus the
    planned reply.

    An oversized prompt against a too-small num_ctx is silently truncated by
    Ollama and yields empty/garbage output. This is exactly what killed the
    hourly bulletin: as the world grew, the ~12k-token bulletin prompt was being
    sent against num_ctx=8192, so the model returned a 1-character reply
    (done_reason=length) every cycle. Fitting the window to the prompt restores
    real generation and prevents silent recurrence as context blocks grow.

    Grows in steps and is capped so we never blow up VRAM/compute.
    """
    needed = len(prompt) // 4 + reply_tokens + 768  # +overhead for system msg / chat template
    for cand in (8192, 12288, 16384, 24576, 32768):
        if cand >= needed:
            if cand > 8192:
                logger.info(f"📰 num_ctx fitted to {cand} (prompt ~{len(prompt)//4} tok + reply {reply_tokens})")
            return cand
    logger.warning(
        f"📰 bulletin prompt ~{len(prompt)//4} tok exceeds the 32k context budget — "
        f"output may truncate; trim the world-context blocks in _build_prompt"
    )
    return 32768


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
    return f"{real_str} | Tower: {tower_str}"


# ---------------------------------------------------------------------------
# Fact extractor — imported from src.memory_strip
# ---------------------------------------------------------------------------
from src.memory_strip import strip_to_facts as _strip_to_facts

# ---------------------------------------------------------------------------
# EC abuse sanitizer — post-processing to catch Qwen violations
# ---------------------------------------------------------------------------

_EC_ABUSE_PATTERNS = [
    # "X EC per person/life/soul/head" pattern
    re.compile(r'\d+\s*EC\s+per\s+(?:person|life|soul|head|body|victim)', re.IGNORECASE),
    # "X EC in [abstract]" like "47 EC in shattered glass"
    re.compile(r'\d+\s*EC\s+in\s+(?:shattered|broken|spilled|lost|scattered|wasted|burning|fading|dying)', re.IGNORECASE),
    # "X EC from [body part/abstract source]"
    re.compile(r'\d+\s*EC\s+from\s+(?:their|her|his|fingertips?|hands?|eyes?|tears?|blood)', re.IGNORECASE),
    # "bleeding EC" / "EC bleeds"
    re.compile(r'(?:bleeding|bleeds?)\s+(?:\d+\s*)?EC', re.IGNORECASE),
    re.compile(r'EC\s+(?:bleeds?|bleeding)', re.IGNORECASE),
    # "the weight of X EC" (metaphorical)
    re.compile(r'(?:the\s+)?weight\s+of\s+\d+\s*EC', re.IGNORECASE),
    # "X EC worth of [emotion/abstract]"
    re.compile(r'\d+\s*EC\s+worth\s+of\s+(?:despair|hope|fear|chaos|desperation|suffering|pain|sorrow)', re.IGNORECASE),
    # "holds the weight of X EC"
    re.compile(r'holds?\s+the\s+weight\s+of\s+\d+\s*EC', re.IGNORECASE),
    # EC counting people: "X EC per smuggled/trafficked"
    re.compile(r'\d+\s*EC\s+per\s+(?:smuggled|trafficked|stolen|lost)', re.IGNORECASE),
    # "X EC of [emotion]" like "47 EC of despair"
    re.compile(r'\d+\s*EC\s+of\s+(?:despair|hope|fear|chaos|desperation|suffering|pain|sorrow|silence|darkness)', re.IGNORECASE),

    # QWEN-SPECIFIC FILTERS (Qwen tends to treat EC like standard RPG currency):
    # "X EC reward/bounty for [info/evidence/shard]" — rewards should be Kharma or specific goods, NOT EC amounts
    re.compile(r'\d+\s*EC\s+(?:reward|bounty|incentive|fee|price)\s+for\s+(?:info|information|evidence|shard|ledger|details|answers?)', re.IGNORECASE),
    # "X EC increments" — treating EC as abstract counting units
    re.compile(r'\d+\s*EC\s+increments?', re.IGNORECASE),
    # "smuggled EC" or "smuggling EC" — EC as a commodity being moved
    re.compile(r'smuggle[ds]?\s+EC|smuggled?\s+(?:the\s+)?EC', re.IGNORECASE),
    # "drop point for smuggled EC" or "ledger with EC"
    re.compile(r'(?:drop\s+point|ledger)\s+(?:for|implicating|involving|holding)\s+(?:smuggled\s+)?EC', re.IGNORECASE),
    # "trading in EC" or "trading...EC" (sounds like currency exchange)
    re.compile(r'trading\s+(?:in\s+)?EC|trading\s+.*?\s+EC', re.IGNORECASE),
    # "recovery costs in EC" — abstract cost counting
    re.compile(r'recovery\s+costs?\s+in\s+\d+\s*EC', re.IGNORECASE),
    # Multiple EC amounts in close phrases (Qwen scattering prices) — catch standalone "X EC" that don't follow specific prices
    # This one is tricky; better handled by context — catch if EC appears with vague transaction words
    re.compile(r'\d+\s*EC\s+(?:to|for)\s+(?:the|a|their|his|her)\s+(?:shard|ledger|reward|bounty|mechanism)', re.IGNORECASE),
]


def _sanitize_ec_abuse(text: str) -> str:
    """
    Post-process bulletin text to remove EC abuse patterns that Qwen generates
    despite prompt instructions. These patterns use EC as metaphor/symbol
    rather than as actual currency.

    Returns cleaned text with offending phrases removed or rewritten.
    """
    original = text

    for pattern in _EC_ABUSE_PATTERNS:
        # Remove the offending phrase entirely
        text = pattern.sub('', text)

    # Clean up any double spaces or orphaned punctuation left behind
    # IMPORTANT: only collapse within-line whitespace — do NOT touch newlines
    text = re.sub(r'[^\S\n]+', ' ', text)
    text = re.sub(r'[^\S\n]+([,.])', r'\1', text)
    text = re.sub(r'([,.]){2,}', r'\1', text)
    text = re.sub(r'^\s*[,.]\s*', '', text, flags=re.MULTILINE)

    # Log if we sanitized anything
    if text != original:
        import logging
        logging.getLogger(__name__).info("📰 EC abuse pattern sanitized from bulletin")

    return text.strip()


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
    """Write a news bulletin to database memory."""
    try:
        from src.db_api import add_news_entry
        bulletin = repair_mojibake(bulletin or "")
        cleaned = _strip_to_facts(bulletin)
        if not cleaned or cleaned == ".":
            return  # nothing factual to store
        add_news_entry(
            bulletin_text=bulletin,
            facts=cleaned,
            news_type="bulletin"
        )
        try:
            _upsert_public_health_arc_from_bulletin(bulletin)
        except Exception as arc_error:
            logger.error(f"Public health arc update error: {arc_error}")
    except Exception as e:
        logger.error(f"News memory write error: {e}")


def _write_rift_memory(bulletin: str, rift: Dict, event: str) -> None:
    """Write Rift bulletins with structured facts for later mission fuel."""
    try:
        from src.db_api import add_news_entry
        bulletin = repair_mojibake(bulletin or "")
        cleaned = _strip_to_facts(bulletin)
        if not cleaned or cleaned == ".":
            return
        agendas = rift.get("faction_agendas") or _rift_faction_agendas(rift)
        agenda_facts = "; ".join(
            f"{a.get('faction')} wants to {a.get('goal')}"
            for a in agendas[:5]
        )
        facts = (
            f"{cleaned} Rift event={event}; id={rift.get('id')}; "
            f"location={rift.get('location')}; stage={rift.get('stage')}; "
            f"outcome={rift.get('outcome')}; replacement_needed={rift.get('replacement_needed', False)}; "
            f"faction_agendas={agenda_facts}."
        )
        add_news_entry(
            bulletin_text=bulletin,
            facts=facts,
            news_type="rift",
        )
    except Exception as e:
        logger.error(f"Rift memory write error: {e}")


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TNN / affiliate sign-off pool
# ---------------------------------------------------------------------------

_TNN_SIGN_OFFS = [
    "-# *— Talis Vore, TNN Evening Report*",
    "-# *— Talis Vore reporting. This is TNN.*",
    "-# *— TNN Evening Report. We'll have more on this story as it develops.*",
    "-# *— Talis Vore. Good evening, and stay informed.*",
    "-# *— Reporting for TNN. I'm Talis Vore.*",
    "-# *— This has been a TNN Evening Report. Talis Vore at the anchor desk.*",
    "-# *— TNN. The only broadcast cleared by the Grand Forum Public Record.*",
    "-# *— Filed by the TNN investigative desk. Talis Vore presenting.*",
    "-# *— A TNN Evening Report. Stay with us.*",
    "-# *— Talis Vore, TNN. Back after this.*",
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

    # ---- HUMAN INTEREST ----
    "a human interest piece about a struggling Warrens resident — a vendor, craftsperson, parent, or survivor with a specific small story",
    "a human interest piece about a strange or heartwarming moment witnessed in Markets Infinite or Grand Forum",
    "a community notice — a local event, a missing pet, a neighbourhood dispute, something small and real that affects ordinary people",
    "an oddity or curiosity — something weird found in the city that has no obvious explanation, treated as local colour not catastrophe",
    "a profile of a minor unnamed city figure — a street performer, a cook, a beggar with a reputation, a child who keeps showing up in the wrong places",
    "a letter to the Dispatch from an anonymous city resident with a complaint, observation, or plea",
    # Species-specific personal stories — the city has many peoples, each with their own texture
    "a species-specific human interest story: a human family trying to afford schooling in a district increasingly dominated by longer-lived species who hold the same job for decades",
    "a species-specific human interest story: a half-orc artisan whose work is exceptional but who can't get guild certification because the examiner assumes they can't read the forms",
    "a species-specific human interest story: an elderly gnome tinkerer whose workshop has been in the same building for 200 years and now faces eviction from a landlord who didn't exist when she moved in",
    "a species-specific human interest story: a tiefling street healer who charges nothing but is rumoured to take something else — and the neighbourhood is divided on whether to care",
    "a species-specific human interest story: a dhampir working the night shift at a legitimate bakery who is trying very hard to be boring and is mostly succeeding",
    "a species-specific human interest story: a human child who has grown up so fast compared to their elf and dwarf classmates that the teacher keeps forgetting they're still young",
    "a species-specific human interest story: a goblin merchant who underbids every contract and is genuinely baffled that the other merchants are angry about this",
    "a coming-of-age human interest moment — a young person of any species doing something quietly significant for the first time: a first contract, a first loss, a first time someone depended on them",
    "a neighbourhood noise complaint that escalates into a surprisingly moving story about two households who have been neighbours for years without speaking",
    "a found-object story — something turned in to a Watch station that reveals a life: a journal, a locket, a set of tools, a child's drawing, no owner ever claimed it",

    # ---- COMMERCIAL / GAZETTE ----
    "a paid advertisement from a named Undercity business — shop, service, or trade stall — with a specific offer, price, or hook",
    "a paid advertisement from a named Undercity business — shop, service, or trade stall — with a specific offer, price, or hook",
    "an Arena of Ascendance sponsored announcement: upcoming fight card, special event, or fighter profile — written in arena promoter voice",
    "an Arena of Ascendance sponsored announcement: upcoming fight card, special event, or fighter profile — written in arena promoter voice",
    "a faction or merchant house sponsoring a named adventuring party — announcing the deal, the terms, and what they expect in return",
    "a notice from a Warrens craftsperson, healer, or specialist advertising a unique service not available through the Guild",
    "a classified ad section: 3-4 short one-line postings (wanted, for sale, seeking, lost) from anonymous Undercity residents",
    "an Obsidian Lotus or Iron Fang business front advertising a 'legitimate' service that is obviously a front for something else",

    # ---- CORONER / REGISTRY OF THE DEAD ----
    # Standalone bulletin from the City Coroner's office — separate from the graveyard event cycle.
    # Appears in the news feed as in-world journalism about death, mortality, and the registry.
    "a brief city coroner's report: a terse bureaucratic notice listing the deceased registered this week, cause of death where known, next of kin sought where applicable — cold official tone with city-noir atmosphere",
    "a human interest angle on the coroner's office: the clerk who has worked there for decades, the strange things people leave behind, what the registry reveals about how the city actually works",
    "a notice from the Office of the City Coroner requesting information about an unidentified body — specific physical details, location found, estimated time of death, no foul play confirmed or denied",
    "a coroner's inquest report: the official findings on a recent notable death — carefully worded, politically aware, technically accurate but missing something obvious to anyone reading between the lines",

    "a punchy City Coroner notice: clipped, noir, and sharp-edged; names one dead person, one uncomfortable detail, and one sentence that sounds like a warning to the living",
    "a raise-dead registry update from the City Coroner: diamond purchased, spell scheduled or attempted, family or faction pressure visible, with a 1-3 day return window unless the Tower keeps the soul",
    "a coroner press-window after a public death: TNN cameras outside, a tired clerk refusing speculation, and one brutally memorable line about how the dead deserve better paperwork than the living",
    "a death registry discrepancy: the file says dead, a witness says walking, the coroner says bring proof or bring a shovel",

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
    """Load AI-generated bulletin types from database."""
    try:
        rows = raw_query(
            "SELECT state_value FROM global_state WHERE state_key = 'generated_news_types'"
        )
        if rows and rows[0].get("state_value"):
            data = rows[0]["state_value"]
            if isinstance(data, str):
                data = json.loads(data)
            return data.get("types", [])
        return []
    except Exception:
        return []


def _save_generated_news_types(types: List[str], generated_date: str) -> None:
    """Save AI-generated bulletin types to database."""
    try:
        data = json.dumps({"generated_date": generated_date, "types": types})
        existing = raw_query(
            "SELECT id FROM global_state WHERE state_key = 'generated_news_types'"
        )
        if existing:
            raw_execute(
                "UPDATE global_state SET state_value = %s WHERE state_key = 'generated_news_types'",
                (data,)
            )
        else:
            db.insert("global_state", {
                "state_key": "generated_news_types",
                "state_value": data
            })
    except Exception:
        pass


def _needs_new_news_types() -> bool:
    """Returns True if news types are missing or were generated on a previous day."""
    try:
        rows = raw_query(
            "SELECT state_value FROM global_state WHERE state_key = 'generated_news_types'"
        )
        if not rows or not rows[0].get("state_value"):
            return True
        data = rows[0]["state_value"]
        if isinstance(data, str):
            data = json.loads(data)
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

    # Inject live roster and city geography into world lore for news type generation
    world_lore = _build_world_lore().replace("{LIVE_ROSTER_NPCS}", _build_live_roster_block())
    world_lore = world_lore.replace("{LIVE_CITY_DISTRICTS}", _build_city_districts_block())
    prompt = f"""{world_lore}

---
You are expanding the TNN Evening Report's story roster for today's broadcast.
Generate exactly 10 new bulletin topic seeds for today's news cycle.

These are SEEDS that tell an AI what kind of story to write — not full bulletins.
Each should be a short description of a story TYPE or ANGLE, specific to today's feel.

RULES:
- Each entry is 1 sentence describing what the bulletin covers
- Must be grounded in the Undercity setting — factions, districts, economy, NPCs
- Do NOT generate Rift bulletins — Rifts are RARE events handled by a separate state machine. The news should NOT constantly mention Rifts.
- Do NOT generate TowerBay or TIA market bulletins (those have their own cadence)
- CRITICAL — RIFT BAN: Do NOT mention Rifts, Rift residue, Rift seams, Rift activity, Rift exploration, tears in reality, dimensional anomalies, or anything Rift-related in ANY of the 10 entries. Rifts are rare catastrophes, NOT daily news fodder. If even ONE of your entries mentions Rifts, you have FAILED.
- CRITICAL — EC RULES: EC (Essence Coins) is currency. Do NOT create seeds involving "X EC per person", "EC for lives", or EC used as a metaphor. EC appears only as prices for goods/services.
- Focus on: faction politics, street crime, human interest, religious drama, guild disputes, economic news, weird occurrences that are NOT Rift-related, missing persons, merchant disputes, adventurer drama, divine contract news, Warrens survival stories, arena results, guild promotions/demotions
- Vary the tone: some street-level, some political, some supernatural (but not Rift), some economic, some human interest
- Make them feel current — what would be on people's lips in the Undercity TODAY
- No numbering, no bullets, no preamble, no sign-off. Output exactly 10 plain-text lines, one per seed.
- If your output contains anything other than 10 lines, you have failed."""

    ollama_model = os.getenv("OLLAMA_FAST_MODEL", os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"))
    try:
        from src.ollama_queue import call_ollama, OllamaBusyError
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": 1024, "num_ctx": _fit_num_ctx(prompt, 1024), "think": True},
            },
            timeout=600.0,
            caller="news_types",
        )
        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()

        # Strip qwen3 <think>...</think> reasoning blocks before extracting lines
        import re as _re_nt
        text = _re_nt.sub(r"<think>.*?</think>", "", text, flags=_re_nt.DOTALL).strip()

        # Clean up any lines that are XML/HTML tags or pure reasoning artifacts
        raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
        clean_lines = []
        for ln in raw_lines:
            # Skip lines that are just tags or look like internal reasoning
            if ln.startswith("<") and ln.endswith(">"):
                continue
            # Strip leading numbering and bullets (model sometimes prefixes 1. 2. -)
            ln_clean = _re_nt.sub(r"^[\d]+[.)]\s*|^[-•*]\s*", "", ln).strip()
            if ln_clean:
                clean_lines.append(ln_clean)

        new_types = clean_lines[:10]
        if not new_types:
            logger.warning("news_feed: daily news type generation returned empty")
            return
        today = datetime.now().strftime("%Y-%m-%d")
        _save_generated_news_types(new_types, today)
        logger.info(f"📰 Generated {len(new_types)} new news types for {today}")
    except Exception as e:
        logger.error(f"refresh_news_types_if_needed error: {e}")


def _load_live_roster() -> List[Dict]:
    """Load all alive/injured NPCs from MySQL npcs table (falls back to file)."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT id, name, faction, role, status, location, data_json FROM npcs WHERE status IN ('alive','injured','undead','doppelganger') ORDER BY name") or []
        if rows:
            result = []
            for row in rows:
                dj = row.get("data_json") or {}
                if isinstance(dj, str):
                    try:
                        dj = json.loads(dj)
                    except Exception:
                        dj = {}
                npc = {**dj, "_db_id": row["id"], "name": row["name"], "faction": row["faction"],
                       "role": row["role"], "status": row["status"], "location": row["location"]}
                result.append(npc)
            return result
    except Exception as e:
        logger.warning(f"news_feed: _load_live_roster DB failed: {e}")
    return []


def _build_live_roster_block(max_npcs: int = 6, recently_featured: List[str] = None) -> str:
    """Build a dynamic ROSTER NPCs block from the live roster for prompt injection.
    Samples a mix: prioritise NPCs with secrets, alliances, or recent history,
    but DEPRIORITIZE NPCs that appeared in recent bulletins (recently_featured).
    Returns formatted string."""
    alive = _load_live_roster()
    if not alive:
        return "ROSTER NPCs: No active roster NPCs available."

    recently_featured = recently_featured or []
    recently_featured_lower = [n.lower() for n in recently_featured]

    # Categorize NPCs: interesting vs mundane, and fresh vs recently-featured
    interesting_fresh = []
    interesting_recent = []
    mundane_fresh = []
    mundane_recent = []

    for n in alive:
        name = n.get("name", "")
        is_recent = name.lower() in recently_featured_lower

        has_secret   = bool(n.get("secret"))
        has_revealed = has_revealed_secrets(n.get("_db_id") or 0)
        has_history  = get_npc_history_count(n.get("_db_id") or 0) > 2
        is_interesting = has_secret or has_revealed or has_history

        if is_interesting:
            if is_recent:
                interesting_recent.append(n)
            else:
                interesting_fresh.append(n)
        else:
            if is_recent:
                mundane_recent.append(n)
            else:
                mundane_fresh.append(n)

    # Shuffle each category
    random.shuffle(interesting_fresh)
    random.shuffle(interesting_recent)
    random.shuffle(mundane_fresh)
    random.shuffle(mundane_recent)

    # Priority order: interesting_fresh > mundane_fresh > interesting_recent > mundane_recent
    # This ensures fresh NPCs are selected first
    prioritized = interesting_fresh + mundane_fresh + interesting_recent + mundane_recent
    chosen = prioritized[:max_npcs]

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
    Pulls from npcs DB table so the AI never writes about dead NPCs as if alive,
    and can reference currently injured NPCs by name in dynamic bulletin types.
    """
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT name, status FROM npcs ORDER BY name") or []
        npcs = [{"name": r["name"], "status": r["status"]} for r in rows if r.get("name")]
    except Exception as e:
        logger.warning(f"news_feed: _load_npc_status_blocks DB failed: {e}")
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
        import json as _json
        profiles = []
        try:
            from src.db_api import raw_query as _rq
            rows = _rq("SELECT profile_json FROM party_profiles WHERE profile_json IS NOT NULL") or []
            for row in rows:
                pj = row.get("profile_json") or {}
                if isinstance(pj, str):
                    try:
                        pj = _json.loads(pj)
                    except Exception:
                        continue
                if pj.get("generated") and pj.get("name") and pj.get("members"):
                    profiles.append(pj)
        except Exception as e:
            logger.warning(f"news_feed: _load_party_bulletin_context DB failed: {e}")
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
    public_health_block = _public_health_arc_prompt_block()
    if public_health_block:
        all_types += [
            "a follow-up headline on the ongoing magic-resistant sickness and its impact on clinics, families, and district politics",
            "a public-health update about quarantine pressure, failed cures, or care factions responding to an active outbreak",
            "a street-level report from people affected by the ongoing outbreak, focusing on what help they need now",
        ] * 2

    # Get roster names and find recently featured NPCs
    roster_names = _get_alive_roster_names()
    recently_featured = _get_recently_featured_npcs(memory_entries, roster_names)
    if recently_featured:
        logger.info(f"📰 Recently featured NPCs (cooldown active): {', '.join(recently_featured[:5])}{'...' if len(recently_featured) > 5 else ''}")

    # Use variety-aware type picker instead of random.choice
    bulletin_type, type_category = _pick_varied_bulletin_type(all_types)
    logger.info(f"📰 Variety picker selected category '{type_category}' — type: {bulletin_type[:60]}...")

    try:
        live_rate = get_rate()
        economy_note = (
            f"\nCURRENT ECONOMY: 1 Kharma = {live_rate:.2f} EC (Kharma is a CHARACTER RESOURCE earned through deeds, NOT traded in bulletins). "
            f"EC is minted when players want to trade. Your job is to report what happened in the city, not the mechanics of minting.\n"
            f"CRITICAL RULES FOR THIS BULLETIN:\n"
            f"1. DO NOT include exchange rate tables, price comparisons, or rate conversations. Exchange rates are SEPARATE bulletins posted by the Exchange system.\n"
            f"2. DO NOT use EC as a reward, bounty, or abstract cost (e.g. 'recovery costs in EC increments' is FORBIDDEN).\n"
            f"3. DO NOT mention EC except for SPECIFIC TANGIBLE PRICES (e.g. 'a sword costs 150 EC' is OK, 'reward for info in 47 EC' is FORBIDDEN).\n"
            f"4. DO NOT treat EC as a commodity to be smuggled, traded, or moved between NPCs.\n"
            f"5. DO NOT mention Kharma in this bulletin unless specifically describing a character earning it through a deed.\n"
            f"6. If you mention ANY EC amount, it must be for a named good/service with a named NPC/vendor. No vague rewards or bounties.\n"
            f"Maximum one EC price per bulletin. If your bulletin contains multiple EC amounts or reward language, you have violated these rules."
        )
    except Exception:
        economy_note = ""

    recent_block = ""
    if memory_entries:
        recent = memory_entries[-MEMORY_CONTEXT_ENTRIES:]
        recent_block = "\nRECENT BULLETINS (you may follow up, escalate, or contradict these):\n" + "\n\n".join(recent)

    # Build anti-repetition guidance block
    anti_repetition_block = ""
    if recently_featured:
        anti_repetition_block = f"\nANTI-REPETITION: These NPCs appeared in recent bulletins and should be deprioritized (use sparingly unless following up): {', '.join(recently_featured[:6])}."

    deceased_block, injured_block, injured_names, dead_names = _load_npc_status_blocks()
    npc_status_block = ""
    if deceased_block:
        npc_status_block += f"\n{deceased_block}"
    if injured_block:
        npc_status_block += f"\n{injured_block}"

    # Add recently deceased context so bulletins can reference recent deaths
    try:
        from src.npc_consequence import get_recently_deceased_block
        recently_dead_block = get_recently_deceased_block(days=7)
        if recently_dead_block:
            npc_status_block += f"\n{recently_dead_block}"
    except Exception:
        pass

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

    # NOTE: bulletin_type was already set via _pick_varied_bulletin_type() at the top of this function.
    # DO NOT override it with random.choice(all_types) — that defeats the variety tracking!

    # Inject commercial context (businesses, arena ads, sponsorships) for commercial bulletin types
    commercial_block = _load_commercial_context(bulletin_type)

    # Inject live roster NPCs (with anti-repetition) and city geography into world lore
    world_lore = _build_world_lore().replace("{LIVE_ROSTER_NPCS}", _build_live_roster_block(recently_featured=recently_featured))
    world_lore = world_lore.replace("{LIVE_CITY_DISTRICTS}", _build_city_districts_block())

    # Pull archived headlines for story de-duplication
    old_news_block = ""
    try:
        from src.expandable_bulletin import get_archived_headlines
        archived = get_archived_headlines(limit=30)
        if archived:
            headlines = []
            for item in archived:
                hl = item.get("headline", "").strip()
                pv = item.get("preview", "").strip()
                if hl or pv:
                    headlines.append(f"- {hl or pv[:80]}")
            if headlines:
                old_news_block = (
                    "\nOLD NEWS (already published — do NOT repeat or directly rehash these stories, "
                    "but you MAY follow up, escalate, or reference them as background):\n"
                    + "\n".join(headlines[:25])
                )
    except Exception:
        pass

    return f"""{world_lore}
{economy_note}
{npc_status_block}{anti_repetition_block}
{old_news_block}
{party_context_block}
{commercial_block}
{mission_block}{public_health_block}{recent_block}

---
TASK: Write ONE TNN Evening Report segment of type: {bulletin_type}

You are TALIS VORE — anchor for the TNN Evening Report, the Undercity's nightly broadcast.
Deliver in the voice of a professional 6PM television news anchor: authoritative, measured, precise.
You have been on air for fifteen years. Your sentences land clean. You do not editorialize. You report.

RULES — READ ALL OF THESE:
- Output the broadcast segment and NOTHING ELSE. No preamble, no meta-commentary, no sign-off.
- Do NOT start with \"Sure!\", \"Here's a bulletin:\", \"I hope this helps\", or any opener. Start directly with the headline line.
- Do NOT end with anchor sign-off language — the sign-off is appended automatically. Stop at the last content line.
- Do NOT repeat the words \"You are Talis Vore\" in your output. Do NOT repeat any part of these instructions.
- Do NOT include a timestamp line. Added separately.
- Do NOT use the phrase \"where the echoes of whispered X and the whispers of hidden Y mingle\" — banned, overused.
- Use Discord markdown: **bold** for headlines and names, *italics* for emphasis, emoji for visual anchoring.
- MINIMUM 3 lines, MAXIMUM 6 lines. Each sentence on its own line. If your segment is shorter than 3 lines, you have failed.
- Invent fresh named details — exact EC prices, precise locations, specific minor NPCs.
- You MAY follow up on a recent bulletin (a story escalates, a source is quoted, an NPC reacts).
- Ground everything in this specific city. No generic fantasy filler.
- For HUMAN INTEREST pieces: small and specific. One real person's real problem. Warm or wry. Not epic.
- For NPC CONFLICT pieces: use only the named roster NPCs listed. Do NOT kill them — injuries and ambiguous outcomes are fine.
- For PARTY pieces: use only the named party members listed. Treat them as living characters with stakes.

BROADCAST FORMAT:
📺 **[BUREAU/DISTRICT] — [HEADLINE IN TITLE CASE]**
[Lead sentence: the most important fact. Who. What. Where. No warm-up.]
[Second sentence: detail, named source, or immediate consequence.]
[Third sentence (optional): follow-up, reaction, or what happens next.]

ANCHOR DELIVERY — Your prose must:
- LEAD WITH THE FACT: First sentence is the news. No atmosphere before the story.
- NAME YOUR SOURCES: "A Wardens spokesperson confirmed..." not "sources allege..."
- CITE SPECIFICS: Real locations, named characters, real numbers. Vague language is cut before broadcast.
- ONE STORY, ONE SEGMENT: One event. One consequence. End decisively.
- EVERY LINE EARNS ITS PLACE: Cut anything that adds atmosphere without adding information.
- ANCHOR DOES NOT EDITORIALIZE: Report facts. Let the facts carry the weight.
- SOMETHING HAPPENED: A story requires an event. Report who did what, where, and what it means.

===============================================================================
CRITICAL QWEN FILTERS — THESE ARE HARD RULES. VIOLATIONS WILL BE REJECTED.
===============================================================================

EC (ESSENCE COINS) USAGE — MANDATORY:
EC is ONLY used for actual TANGIBLE purchases of specific goods or services.
EC is NEVER used as a metaphor, symbol, poetic device, reward, bounty, or emotional weight.
EC is NEVER minted/traded as a commodity. Players mint EC when they want to trade; you don't describe that process.
Kharma is earned through deeds and stored on characters — it is NOT a traded currency and never mentioned in bulletins.

FORBIDDEN EC PATTERNS (your output will be REJECTED if it contains ANY of these):
✗ "X EC per person/life/soul/head" — FORBIDDEN (e.g. "120 EC per person smuggled" is WRONG)
✗ "X EC per [victim count/abstract]" — FORBIDDEN
✗ "X EC in [abstract]" — FORBIDDEN (e.g. "47 EC in shattered glass" is WRONG)
✗ "X EC worth of [emotion/chaos/despair]" — FORBIDDEN
✗ "bleeding EC" / "EC from fingertips" — FORBIDDEN
✗ "the weight of X EC" (when not literal) — FORBIDDEN
✗ EC as counting victims, smuggled people, or lives — ABSOLUTELY FORBIDDEN
✗ "X EC reward/bounty for [info/evidence]" — FORBIDDEN. Rewards are Kharma-based or specific goods, NOT abstract EC amounts.
✗ "X EC increments" — FORBIDDEN. Don't count things in EC units.
✗ "smuggled EC" / "trading EC" — FORBIDDEN. EC is not a commodity to be smuggled or traded between NPCs.
✗ "recovery costs in X EC" — FORBIDDEN. Don't use EC for abstract cost counting.
✗ "X EC for the shard/ledger/reward" — FORBIDDEN when the shard/ledger is not an actual good being purchased.

ALLOWED EC PATTERNS (ONLY these are acceptable):
✓ "a sword costs 150 EC" — selling a specific tangible good
✓ "she paid 75 EC for information" — paying a specific informant for a specific thing
✓ "the smithy wants 200 EC for repairs" — specific service with a named provider
✓ "stole 300 EC from the warehouse" — actual theft of currency itself
✓ "vials cost 30 EC each" — specific goods with a price

MINIMUM: Only mention EC if describing an ACTUAL TRANSACTION with a specific good/service and a named NPC/vendor.
MAXIMUM: One EC price mention per bulletin (two ONLY if the bulletin is specifically about commerce/prices).
If you are not describing a real PURCHASE of a NAMED GOOD/SERVICE, DO NOT MENTION EC AT ALL.

RIFT BAN:
Do NOT mention Rifts, Rift residue, tears in reality, or dimensional anomalies UNLESS the bulletin type EXPLICITLY asks for Rift news. Rifts are RARE. Regular bulletins should NOT mention Rifts at all.

FORMAT:
Each sentence should be on its own line. Do NOT run sentences together without line breaks.
===============================================================================

- If your response contains anything other than the bulletin itself, you have failed."""


# ---------------------------------------------------------------------------
# Editor agent — runs on every draft before it is saved or posted
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Fact-checker — validates faction assignments and NPC accuracy
# ---------------------------------------------------------------------------

_FACTCHECK_NEWS_SYS = """\
You are the fact-checker for the TNN Evening Report.

Your job is to CHECK a broadcast segment against the NPC ROSTER and CITY LOCATIONS provided,
fix any FACTION ASSIGNMENT ERRORS or LOCATION ERRORS, and return the corrected text.
CRITICAL: Your output must have the same number of lines as the input. Do NOT summarize or shorten.

CRITICAL CHECKS:
1. FACTION ASSIGNMENT: Every NPC mentioned MUST be assigned to their CORRECT faction
   as listed in the roster. If the bulletin says "Sera Voss of the Wardens" but the
   roster says she belongs to Iron Fang Consortium, you MUST fix it.
2. DEAD NPCs: If an NPC is listed as DECEASED, do NOT write about them as alive.
   Either remove the reference or add "the late" before their name.
3. NPC ROLES: If the bulletin gives an NPC a title or role that contradicts the
   roster (e.g. calling a grunt a "leader"), correct it.
4. FACTION NAMES: Only these factions exist: Iron Fang Consortium, Argent Blades,
   Wardens of Ash, Serpent Choir, Obsidian Lotus, Glass Sigil, Patchwork Saints,
   Adventurers Guild, Guild of Ashen Scrolls, Tower Authority, Wizards Tower,
   Independent, Brother Thane's Cult. Any other faction name is WRONG.
5. LOCATION NAMES: Only use locations that exist in the VALID LOCATIONS list provided.
   If a bulletin mentions a made-up location, replace it with a similar valid one.
   The city has 5 concentric rings - inner rings are for power/religion, outer rings
   are residential/industrial/Warrens. Match locations to appropriate rings.
6. TRANSPORT: Valid transit includes Train Tubes (Spine Line, Ring Express, Radial lines,
   Deep Line) and Canals (The Moat, Forum Canal, Sanctum Canal, The Flow, Residential Canal,
   The Trench). Invented transport names should be replaced with valid ones.

OUTPUT RULES:
- Output the CORRECTED broadcast segment only. No preamble, no commentary.
- If nothing needs fixing, output the segment UNCHANGED, line for line.
- Do NOT add new content. Only fix faction/NPC/location errors.
- Keep all formatting intact. Keep ALL lines — do not collapse multi-line segments into one line.
- Your output MUST have the same number of non-empty lines as the input.
"""


def _load_gazetteer_locations() -> tuple[list, list, list]:
    """
    Load valid locations from gazetteer DB table.
    Returns (districts, establishments, transit) lists.
    """
    data = None
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT content_json FROM gazetteer LIMIT 1") or []
        if rows and rows[0].get("content_json"):
            cj = rows[0]["content_json"]
            data = json.loads(cj) if isinstance(cj, str) else cj
    except Exception as e:
        logger.warning(f"news_feed: _load_gazetteer_locations DB failed: {e}")
    if data is None:
        return [], [], []

    # Extract district names
    districts = list(data.get("districts", {}).keys())

    # Extract establishment names from all districts
    establishments = []
    for district_data in data.get("districts", {}).values():
        for est in district_data.get("notable_establishments", []):
            if est.get("name"):
                establishments.append(est["name"])
        for sub in district_data.get("sub_areas", []):
            for loc in sub.get("locations", []):
                establishments.append(loc)

    # Extract transit hubs
    transit = []
    tubes = data.get("transportation", {}).get("train_tubes", {}).get("major_lines", [])
    for line in tubes:
        transit.append(line.get("name", ""))
        transit.extend(line.get("stations", []))

    return districts, establishments, transit


def _build_city_districts_block() -> str:
    """
    Build a concise city geography summary from the gazetteer for prompt injection.
    Replaces {LIVE_CITY_DISTRICTS} placeholder in _WORLD_LORE.
    """
    data = None
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT content_json FROM gazetteer LIMIT 1") or []
        if rows and rows[0].get("content_json"):
            cj = rows[0]["content_json"]
            data = json.loads(cj) if isinstance(cj, str) else cj
    except Exception as e:
        logger.warning(f"news_feed: _build_city_districts_block DB failed: {e}")
    if data is None:
        return "CITY DISTRICTS: No gazetteer data available."

    lines = ["CITY GEOGRAPHY (concentric rings around the Tower):"]

    # Ring structure summary
    rings = data.get("ring_structure", [])
    for ring in rings:
        ring_num = ring.get("ring", "?")
        name = ring.get("name", "Unknown")
        dist = ring.get("distance_from_tower", "")
        districts = ring.get("districts", [])
        if districts:
            lines.append(f"  Ring {ring_num} ({name}, {dist}): {', '.join(districts)}")

    # Key districts with sub-areas
    districts = data.get("districts", {})
    if districts:
        lines.append("KEY LOCATIONS:")
        for district_name, district_data in list(districts.items())[:8]:  # Top 8 districts
            sub_areas = district_data.get("sub_areas", [])
            sub_names = [s.get("name", "") for s in sub_areas[:4] if s.get("name")]
            if sub_names:
                lines.append(f"  {district_name}: {', '.join(sub_names)}")

    # Transport quick reference
    transport = data.get("transportation", {})
    tubes = transport.get("train_tubes", {}).get("major_lines", [])
    if tubes:
        tube_names = [t.get("name", "") for t in tubes[:5] if t.get("name")]
        lines.append(f"TRAIN TUBES: {', '.join(tube_names)}")

    canals = transport.get("canal_rings", [])
    if canals:
        canal_names = [c.get("name", "") for c in canals[:4] if c.get("name")]
        lines.append(f"CANALS: {', '.join(canal_names)}")

    # Warrens distribution
    warrens = data.get("warrens_distribution", [])
    if warrens:
        warren_names = [w.get("name", "") for w in warrens[:3] if w.get("name")]
        lines.append(f"WARRENS CLUSTERS: {', '.join(warren_names)} (scattered, not one district)")

    return "\n".join(lines)


async def _fact_check_bulletin(draft: str) -> str:
    """
    Validate a bulletin against the NPC roster and city gazetteer.
    Fix faction assignment errors and invalid location names.
    Returns the corrected bulletin text.
    """
    import httpx
    import logging
    logger = logging.getLogger(__name__)

    if not draft or len(draft.split()) < 10:
        return draft

    # Build NPC roster reference from MySQL (authoritative source)
    roster_lines = []
    dead_lines = []

    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT name, faction, role, status, data_json FROM npcs ORDER BY name")
        for row in rows:
            name    = row.get("name", "")
            faction = row.get("faction", "Independent") or "Independent"
            status  = row.get("status", "alive") or "alive"
            if not name:
                continue
            # Pull rank/role from data_json if available
            dj = row.get("data_json") or {}
            if isinstance(dj, str):
                try:
                    import json as _j; dj = _j.loads(dj)
                except Exception:
                    dj = {}
            rank = dj.get("rank", "") or row.get("role", "")
            role = dj.get("role", "") or row.get("role", "")

            if status == "dead":
                dead_lines.append(f"- {name} ({faction}) — DECEASED")
            else:
                line = f"- {name}: {faction}"
                if rank:
                    line += f", {rank}"
                if role and role != rank:
                    line += f" ({role})"
                if status == "injured":
                    line += " [INJURED]"
                roster_lines.append(line)
    except Exception as e:
        logger.warning(f"✏️ Fact-check: Could not load NPC roster from MySQL: {e}")

    # Load valid locations from gazetteer
    districts, establishments, transit = _load_gazetteer_locations()
    location_block = ""
    if districts or establishments:
        loc_parts = []
        if districts:
            loc_parts.append(f"Districts: {', '.join(districts[:20])}")
        if establishments:
            # Sample 30 establishments to keep prompt manageable
            sample = establishments[:30] if len(establishments) > 30 else establishments
            loc_parts.append(f"Establishments: {', '.join(sample)}")
        if transit:
            sample_transit = transit[:15] if len(transit) > 15 else transit
            loc_parts.append(f"Transit: {', '.join(sample_transit)}")
        location_block = "\n".join(loc_parts)
    else:
        location_block = "No location data available."

    roster_block = "\n".join(roster_lines) if roster_lines else "No roster data available."
    dead_block = "\n".join(dead_lines) if dead_lines else "None currently."

    from src.faction_reputation import KNOWN_FACTIONS
    faction_list = ", ".join(KNOWN_FACTIONS)

    prompt = f"""Check this bulletin against the NPC roster and city locations. Fix any errors.

VALID FACTIONS (ONLY these exist): {faction_list}, Independent, Brother Thane's Cult

NPC ROSTER (use these exact faction assignments):
{roster_block}

DECEASED NPCs (do NOT reference as alive):
{dead_block}

VALID LOCATIONS (use these or similar):
{location_block}

---BEGIN BULLETIN---
{draft}
---END BULLETIN---

Output the corrected bulletin only. No preamble."""

    ollama_model = os.getenv("OLLAMA_FAST_MODEL", os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"))

    try:
        from src.ollama_queue import call_ollama, OllamaBusyError
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [
                    {"role": "system", "content": _FACTCHECK_NEWS_SYS},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"num_predict": 2048, "num_ctx": _fit_num_ctx(prompt, 2048), "think": True},
            },
            timeout=600.0,
            caller="edit_bulletin",
        )

        result = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                result = msg.get("content", "").strip()

        # Strip any preamble
        lines = result.splitlines()
        skip = ("sure", "here's", "here is", "certainly", "of course",
                "below is", "corrected", "the corrected")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        result = "\n".join(lines).strip()

        orig_lines = len([l for l in draft.splitlines() if l.strip()])
        result_lines = len([l for l in result.splitlines() if l.strip()])
        words_ok = result and len(result.split()) >= len(draft.split()) * 0.7
        lines_ok = result_lines >= max(2, orig_lines - 1)

        if words_ok and lines_ok:
            logger.info("✅ Fact-check: bulletin validated/corrected")
            return result
        else:
            logger.warning(
                f"✏️ Fact-check: result truncated ({result_lines} lines from {orig_lines}), using original"
            )
            return draft

    except Exception as e:
        logger.warning(f"✏️ Fact-check failed: {type(e).__name__}: {e} — using original bulletin")
        return draft


async def _edit_bulletin(draft: str, memory_entries: List[str]) -> str:
    """
    Run a second Ollama pass acting as a copy-editor.
    Returns the corrected bulletin text only.
    If the edit call fails or returns garbage, returns the original draft unchanged.

    REFACTORED: Now uses bulletin_cleaner module for aggressive output cleaning.
    """
    import httpx
    import logging
    logger = logging.getLogger(__name__)

    # Save true original before fact-check may shorten or corrupt it.
    # If the editor pass also fails, we fall back to this — not the post-fact-check result.
    original_draft = draft

    # First, run fact-check for faction accuracy
    draft = await _fact_check_bulletin(draft)

    context_entries = memory_entries[-12:] if memory_entries else []
    context_block = ""
    if context_entries:
        context_block = (
            "RECENT BULLETIN HISTORY — read these carefully. "
            "Cross-check names, factions, locations, and ongoing events against them. "
            "Do NOT contradict or ignore established facts.\n\n"
            + "\n\n".join(context_entries)
        )

    editor_prompt = f"""You are a copy-editor for the Undercity Dispatch. Your ONLY job is to output a corrected version of the bulletin below.

{context_block}

BULLETIN TO CORRECT:
{draft}

RULES:
- Output the corrected bulletin text ONLY. Nothing else.
- Fix grammar, spelling, incomplete sentences, and factual errors vs. the history above.
- Do NOT change the tone, length, or structure.
- Do NOT list your changes. Do NOT explain anything. Do NOT add bullet points.
- If the bulletin is already correct, output it unchanged."""

    # Editor pass is a quick copy-edit — fast model is sufficient
    ollama_model = os.getenv("OLLAMA_FAST_MODEL", os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"))

    try:
        from src.ollama_queue import call_ollama, OllamaBusyError
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [{"role": "user", "content": editor_prompt}],
                "stream": False,
                "options": {"num_predict": 1200, "num_ctx": _fit_num_ctx(editor_prompt, 1200), "think": True},
            },
            timeout=300.0,
            caller="editor",
        )

        edited = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                edited = msg.get("content", "").strip()

        # Strip qwen3 thinking blocks before any processing
        import re as _re
        edited = _re.sub(r"<think>.*?</think>", "", edited, flags=_re.DOTALL).strip()

        # If the model returned commentary instead of a bulletin, silently use original
        _commentary_phrases = (
            "the bulletin is", "bulletin is correct", "bulletin looks", "no changes",
            "no corrections", "already correct", "looks good", "is good",
        )
        if len(edited) < 200 and any(p in edited.lower() for p in _commentary_phrases):
            return original_draft

        # Try to extract just the bulletin body (starts with 📺 or **HEADLINE**)
        _bulletin_match = _re.search(r'(📺\s*\*\*.*)', edited, _re.DOTALL)
        if _bulletin_match:
            edited = _bulletin_match.group(1).strip()
        else:
            edited = clean_bulletin(edited)

        # Validate the edited content; attempt repair before falling back
        is_valid, reason = validate_bulletin(edited)
        if not is_valid:
            if reason in ("incomplete sentence", "truncated"):
                repaired = repair_incomplete_bulletin(edited)
                re_valid, _ = validate_bulletin(repaired)
                if re_valid:
                    logger.info(f"✂️ Editor output repaired ({reason} → trimmed)")
                    return repaired
            logger.warning(f"✏️ Editor output invalid ({reason}) — using original draft")
            return original_draft

        if edited:
            logger.info("✏️ Editor agent: bulletin reviewed and corrected")
            return edited

    except Exception as e:
        logger.warning(f"✏️ Editor agent failed: {type(e).__name__}: {e} — using original draft")

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
    Saves result to news_memory DB table. Returns the bulletin string or None.
    """
    import re as _re
    memory = _read_memory()
    prompt = repair_mojibake(_build_prompt(memory))

    # Bulletins are short-form — use the fast model
    ollama_model = os.getenv("OLLAMA_FAST_MODEL", os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"))

    try:
        from src.ollama_queue import call_ollama, OllamaBusyError
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": 900, "num_ctx": _fit_num_ctx(prompt, 900), "think": False},
            },
            timeout=600.0,
            caller="generate_bulletin",
        )

        bulletin = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                bulletin = repair_mojibake(msg.get("content", "")).strip()

        if bulletin:
            lines = bulletin.splitlines()
            skip_phrases = ("sure", "here's", "here is", "as requested", "certainly", "of course", "i hope", "below is")
            while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip_phrases):
                lines.pop(0)


            # Single-line normalisation
            # Small models (Qwen3 etc.) often output headline + body as ONE
            # continuous line with no newlines.  Inject them so validate_bulletin
            # sees >=2 lines and does not discard the whole bulletin.
            if len(lines) == 1 and len(lines[0]) > 60:
                single = lines[0]
                import re as _re2
                # Case A: proper bold header  **Headline** Body text
                expanded = _re2.sub(r"(\*\*[^*]{3,}\*\*)\s+", lambda m: m.group(1) + chr(10), single, count=1)
                if chr(10) not in expanded:
                    # Case B: dangling bold opener **text Body (no closing **)
                    expanded = _re2.sub(
                        r"(\*\*.{20,80}?)\s+((?:The |A |An |In |On |At |By |Two|Three|Four|Several|No |After|Before|While|During|This|That|His|Her|Their|One |[A-Z][a-z]))",
                        lambda m: m.group(1) + chr(10) + m.group(2), single, count=1
                    )
                if chr(10) not in expanded:
                    # Case C: no bold at all — split at sentence boundaries
                    expanded = _re2.sub(r"(?<=[.!?])\s+(?=[A-Z*])", chr(10), single, count=3)
                lines = expanded.splitlines()
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
                r'\n\s*---\s*\n+(?:you are the undercity dispatch|you are talis vore|task:|write one undercity|write one tnn)',
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

        # Sanitize EC abuse patterns (Qwen tends to ignore prompt rules)
        if bulletin:
            bulletin = _sanitize_ec_abuse(bulletin)
            # Also apply the new aggressive filter
            bulletin = filter_ec_references(bulletin)

        if bulletin:
            bulletin = _apply_tnn_signoff(bulletin)

        if bulletin:
            bulletin = await _edit_bulletin(bulletin, memory)

            # Validate after editing; attempt repair before discarding
            is_valid, reason = validate_bulletin(bulletin)
            if not is_valid:
                if reason in ("incomplete sentence", "truncated"):
                    repaired = repair_incomplete_bulletin(bulletin)
                    re_valid, re_reason = validate_bulletin(repaired)
                    if re_valid:
                        logger.info(f"✂️ Bulletin repaired ({reason} → trimmed to last complete sentence)")
                        bulletin = repaired
                    else:
                        logger.warning(
                            f"📰 Bulletin failed validation ({reason}) — repair also failed ({re_reason}), discarding: {bulletin[:100]}..."
                        )
                        return None
                else:
                    logger.warning(
                        f"📰 Bulletin failed validation ({reason}) — discarding: {bulletin[:100]}..."
                    )
                    return None

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
            bulletin = repair_mojibake(bulletin)
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
            # Validate bulletin has proper content (not just a title)
            bulletin_lines = bulletin.strip().splitlines()
            if len(bulletin_lines) < 2 or len(bulletin.strip()) < 50:
                import logging
                logging.getLogger(__name__).warning(
                    f"📰 Bulletin too short ({len(bulletin_lines)} lines, {len(bulletin)} chars) — may be malformed: {bulletin[:100]}..."
                )
            # Ensure proper separation between timestamp and content
            # Use double-newline for better Discord embed rendering
            _write_memory(bulletin)
            return f"-# \U0001f570\ufe0f {_dual_timestamp()}\n\n{bulletin}"

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

_AESTHETIC_FALLBACK = ""  # signals: no district matched, let _prompt_agent pick from loc_key


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
    """Load NPC name → SD prompt lookup from MySQL npc_appearances (falls back to file)."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT npc_name, appearance_json FROM npc_appearances WHERE appearance_json IS NOT NULL") or []
        if rows:
            result = {}
            for r in rows:
                name = r.get("npc_name", "")
                aj = r.get("appearance_json") or {}
                if isinstance(aj, str):
                    try:
                        aj = json.loads(aj)
                    except Exception:
                        aj = {}
                sd = aj.get("sd_appearance", "")
                if name and sd:
                    result[name] = sd
            if result:
                return result
    except Exception as e:
        logger.warning(f"news_feed: _load_sd_prompts DB failed: {e}")
    return {}


async def _prompt_agent(
    bulletin_text: str,
    npc_names: list[str],
    loc_key: str,
    scene_action: str,
    quality_header: str,
    framing: str,
    district_aesthetic: str = "",
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
        "grand forum":        "wide marble-floored civic hall, white fluted columns, holographic notice boards, FTA security in black armour, bright recessed ceiling lights, officials and petitioners crossing polished floor",
        "central plaza":      "grand underground square, colonnaded arcade, ornamental fountain with faction crests, bright civic lighting, polished stone floors, mixed crowd of adventurers and clerks",
        "grand forum library":"barrel-vaulted library hall, white stone columns, floor-to-ceiling archive shelves, soft amber lighting, archivists in grey robes, holographic catalogue terminals, quiet and orderly",
        "adventurer's inn":   "tavern interior, rough wooden tables, low warm lantern light, stone hearth, adventurers planning over maps",
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
    # Use rich district_aesthetic when available (passed from _get_district_aesthetic).
    # Fall back to the simpler _LOC_TAG_MAP_LOCAL, then a minimal generic fallback.
    if district_aesthetic and district_aesthetic != _AESTHETIC_FALLBACK:
        loc_tags = district_aesthetic[:300]  # cap to avoid bloating the agent prompt
    else:
        loc_tags = "underground city district, lived-in space"
        loc_key_lower = loc_key.lower()
        for key, tags in _LOC_TAG_MAP_LOCAL.items():
            if key in loc_key_lower:
                loc_tags = tags
                break

    # Prompt agent generates short SD tag lists — fast model is fine
    ollama_model = os.getenv("OLLAMA_FAST_MODEL", os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"))
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    # Photorealistic models (Juggernaut XL, epicrealism) need natural English phrases in
    # environment-first order.  Anime models (AnimagineXL) still need Danbooru tags.
    image_style_local = os.getenv("IMAGE_STYLE", "photorealistic").lower().strip()
    is_anime_local = image_style_local == "anime"

    if is_anime_local:
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
    else:
        # Photorealistic system: STORY EVENT leads — it is the most important element.
        # Juggernaut XL v9 / epicrealism understand natural English phrases.
        # Tokens near the start of the prompt receive the most attention — the event goes first.
        agent_system = (
            "You are an expert Stable Diffusion XL prompt engineer for photorealistic models "
            "(Juggernaut XL, epiCRealism).\n"
            "These models understand natural English short phrases, NOT Danbooru tags.\n\n"
            "Your goal: generate a prompt that shows a SPECIFIC STORY EVENT happening.\n"
            "The image should feel like a moment caught mid-action, not a posed scene.\n"
            "Characters appear as small secondary figures in the midground — NOT the focus.\n\n"
            "OUTPUT FORMAT: comma-separated short English phrases on ONE line.\n\n"
            "STRICT ORDERING — write in this order:\n"
            "1. STORY EVENT first — the specific thing happening from the bulletin "
            "(e.g. 'patrol dragging a merchant through a crowded market', "
            "'faction herald nailing a notice to a door while a crowd gathers', "
            "'two figures exchanging a package in a doorway, one looking back nervously'). "
            "This MUST be the first phrase — it is the subject of the image.\n"
            "2. LOCATION — where specifically this is happening, what the space looks like. "
            "Match the actual place from the bulletin. Grand Forum = white marble, civic hall. "
            "Warrens = crumbling slum, graffiti. Floating Bazaar = lanterns on water. "
            "Arena = sand floor, tiered seating. NOT generic concrete unless the scene calls for it.\n"
            "3. ATMOSPHERE — lighting, time of day, air quality, colour mood.\n"
            "4. CHARACTERS LAST — one brief phrase only, e.g. 'two figures in the distance', "
            "'silhouetted figure watching from a doorway'. NO face details. NO close-up appearance.\n\n"
            "RULES:\n"
            "- 12–20 phrases total on ONE line\n"
            "- NO prose sentences. Short descriptive phrases only.\n"
            "- Do NOT include quality or framing tags — those are added separately.\n"
            "- Do NOT write: hair colour, eye colour, armour details, facial features.\n"
            "- If you write character appearance tags you have failed the brief.\n"
            "- If you write 'brutalist concrete' without a specific story reason, you have failed the brief."
        )
        char_hint = (
            f"Characters (show as distant/secondary only): {', '.join(npc_names)}"
            if npc_names else "no named characters — use anonymous crowd or lone figure"
        )
        agent_user = (
            f"Bulletin text (the story happening):\n{bulletin_text[:600]}\n\n"
            f"{char_hint}\n"
            f"Scene action: {scene_action}\n"
            f"Location context: {loc_tags}\n\n"
            f"Output ONLY the comma-separated phrases in the required order "
            f"(story event FIRST → location → atmosphere → characters last)."
        )

    mistral_tags = ""
    try:
        from src.ollama_queue import call_ollama, OllamaBusyError
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [
                    {"role": "system", "content": agent_system},
                    {"role": "user",   "content": agent_user},
                ],
                "stream": False,
                "options": {"num_predict": 256, "num_ctx": _fit_num_ctx(f"{agent_system}{agent_user}", 256), "think": True},
            },
            timeout=45.0,
            caller="image_tags",
        )
        raw = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                raw = msg.get("content", "").strip()

        import re as _re

        # Strip qwen3 thinking blocks (present even when think:False sometimes)
        raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
        # Strip markdown fences
        raw = _re.sub(r"```[a-z]*\n?", "", raw).replace("```", "").strip()

        # Find the best line — the one with the most commas is almost certainly the tag list.
        # This survives preamble sentences AND trailing explanation sentences.
        all_lines = [l.strip() for l in raw.splitlines() if l.strip()]
        tag_lines = [l for l in all_lines if l.count(",") >= 3]
        if tag_lines:
            raw = max(tag_lines, key=lambda l: l.count(","))
        elif all_lines:
            # Nothing comma-rich — fall through to the old join so we at least try
            skip = ("sure", "here", "certainly", "of course", "below", "i ", "as ")
            while all_lines and all_lines[0].lower().strip().rstrip(":!,.").startswith(skip):
                all_lines.pop(0)
            raw = " ".join(all_lines).strip()

        # Prose indicator check — relax for photorealistic mode because natural English
        # phrases like "in the dim corridor" and "a crowd with lanterns" are intentional.
        if is_anime_local:
            prose_check = _PROSE_INDICATORS  # strict: Danbooru tags have no prose
        else:
            prose_check = (" who ", " as they ", "stands ", "moves ", "wears ", "holds ", "carries ")

        if raw.count(",") >= 4 and not any(p in raw.lower() for p in prose_check):
            mistral_tags = raw
            logger.info(f"🤖 Prompt agent: {ollama_model} returned {raw.count(',') + 1} phrases")
        else:
            logger.warning(
                f"🤖 Prompt agent: {ollama_model} fallback "
                f"(commas={raw.count(',')}, sample={raw[:120]!r})"
            )

    except Exception as e:
        logger.warning(f"🤖 Prompt agent: {ollama_model} unavailable ({e}) — using self-lookup fallback")

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

        # Add atmospheric variety to fallback prompts for more diversity
        mood_options = [
            "tense atmosphere, shadows",
            "dramatic lighting, contrast",
            "dim underground lighting",
            "neon-lit scene, volumetric",
            "candlelit atmosphere, grim",
            "oppressive mood, foreboding",
            "electric tension, danger",
            "mysterious lighting, intrigue"
        ]
        parts.append(random.choice(mood_options))

        mistral_tags = ", ".join(p for p in parts if p)
        logger.info(f"🤖 Prompt agent: self-lookup fallback assembled {len(parts)} blocks + atmosphere")

    # Photorealistic: agent already ordered environment → story → character (brief).
    # Don't prepend char_tag — it would push character focus to the high-weight start position.
    # Anime: keep legacy order with char_tag up front (AnimagineXL expects that).
    if is_anime_local:
        final = ", ".join(p for p in [quality_header, char_tag, mistral_tags, framing] if p)
    else:
        final = ", ".join(p for p in [quality_header, mistral_tags, framing] if p)
    return final


def _extract_contextual_characters(text: str) -> list[str]:
    """
    Extract character type/role descriptors from bulletin text for prompts.
    Returns list of contextual character descriptions to use when NPCs aren't found by name.
    """
    descriptors = []
    text_lower = text.lower()

    # Look for role/type keywords
    if any(w in text_lower for w in ["adventurer", "party", "guild member", "hero"]):
        descriptors.append("adventurer in practical gear")
    if any(w in text_lower for w in ["faction", "warden", "guard", "soldier"]):
        descriptors.append("armed faction representative")
    if any(w in text_lower for w in ["merchant", "trader", "shopkeep", "vendor"]):
        descriptors.append("merchant in fine clothes")
    if any(w in text_lower for w in ["assassin", "rogue", "thief", "criminal"]):
        descriptors.append("figure in black leather, concealed face")
    if any(w in text_lower for w in ["priest", "cleric", "holy", "temple", "sanctum"]):
        descriptors.append("robed figure in ritual vestments")
    if any(w in text_lower for w in ["arcane", "mage", "wizard", "spell", "magical"]):
        descriptors.append("figure wearing enchanted robes, arcane symbols")
    if any(w in text_lower for w in ["oracle", "seer", "prophet"]):
        descriptors.append("mysteriously cloaked oracle figure")
    if any(w in text_lower for w in ["noble", "lord", "lady", "aristocrat", "elite"]):
        descriptors.append("figure in fine silks, noble bearing")
    if any(w in text_lower for w in ["crowd", "mass", "gathering", "assembly"]):
        descriptors.append("crowd of diverse figures")
    if any(w in text_lower for w in ["stranger", "unknown", "mysterious", "hooded"]):
        descriptors.append("mysterious figure, features hidden")

    return descriptors[:3]  # Limit to 3 contextual descriptors


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
    try:
        rows = raw_query("SELECT party_name, profile_json FROM party_profiles WHERE status='active'") or []
    except Exception:
        return []
    found = []
    text_lower = text.lower()
    for row in rows:
        name = row.get("party_name", "")
        if not name or name.lower() not in text_lower:
            continue
        pj = row.get("profile_json") or {}
        if isinstance(pj, str):
            try:
                pj = json.loads(pj)
            except Exception:
                pj = {}
        visual = pj.get("visual", "")
        home   = _get_party_home_district(pj)
        found.append((name, visual, home))
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
    """Extract a visual action phrase from bulletin text with better fallbacks."""
    text_lower = text.lower()
    for keyword, visual in _BULLETIN_ACTION_KEYWORDS:
        if keyword in text_lower:
            return visual

    # Enhanced fallback detection for common patterns
    if any(w in text_lower for w in ["dead", "killed", "death", "funeral"]):
        return "still figure on ground, onlookers gathered in grief"
    elif any(w in text_lower for w in ["injured", "wounded", "blade", "blood"]):
        return "figure slumped against wall, others tending wounds, tension"
    elif any(w in text_lower for w in ["post", "board", "notice", "announce"]):
        return "figure nailing notice to board, others gathering around"
    elif any(w in text_lower for w in ["transaction", "deal", "exchange", "barter"]):
        return "figures exchanging items in half-shadow, careful tension"
    elif any(w in text_lower for w in ["vote", "election", "decision", "council"]):
        return "figures gathered in serious discussion, hand raised to speak"
    elif any(w in text_lower for w in ["discovery", "found", "reveal", "uncovered"]):
        return "figure examining a new discovery, others watching intently"
    elif any(w in text_lower for w in ["rift", "tear", "anomaly", "void"]):
        return "figures surrounding a glowing rift, hand shielding eyes from light"
    elif any(w in text_lower for w in ["treasure", "loot", "relic", "artifact"]):
        return "figure holding up a glowing treasure, face lit from below, awe"
    elif any(w in text_lower for w in ["hunt", "track", "search", "seek"]):
        return "figure crouching, examining ground for clues, determined"
    elif any(w in text_lower for w in ["gather", "crowd", "mass", "assemble"]):
        return "crowd of figures assembled in hushed conversation, tension in air"

    return "figures engaged in dramatic business in the district"


async def _build_image_prompt(memory_entries: List[str]) -> tuple:
    """
    Build an SDXL image prompt directly.
    Now uses comprehensive story context from database for richer scene building.
    Returns (sd_prompt_str, npc_names_list, chosen_bulletin_str).
    """
    image_style = os.getenv("IMAGE_STYLE", "photorealistic").lower().strip()
    is_anime    = image_style == "anime"

    # Get comprehensive story context from database
    story_context = get_story_context(limit_news=5, limit_npcs=10, limit_missions=5)
    context_str = format_story_context_for_prompt(story_context, max_chars=1500)

    # Log what context sources are available
    logger.info(f"🖼️ Story context: {len(story_context.get('recent_news', []))} news, "
                f"{len(story_context.get('active_npcs', []))} npcs, "
                f"{len(story_context.get('active_missions', []))} missions, "
                f"{story_context.get('rift_state', {}).get('active_count', 0)} rifts")

    if not memory_entries:
        # Varied fallbacks so empty-memory images aren't always the same concrete corridor
        _empty_fallbacks = [
            "Iron Fang patrol moving through Cobbleway market, merchants stepping aside, lanterns swaying, tension in the air",
            "Warrens alley at night, bioluminescent fungus glowing on cracked walls, hooded figure watching a door, rain on stone",
            "Grand Forum balcony overlooking the underground city, faction banners hanging, a crowd gathered below listening to an announcement",
            "Floating Bazaar at dusk, paper lanterns reflected in the underground lake, gondola drifting, figures bartering at stalls",
            "Arena of Ascendance aftermath, scattered sand, a victor standing alone in the light, crowd noise dying down",
            "Adventurer's Inn common room, rough wooden tables, low lantern light, a group leaning over a map planning their next move",
        ]
        sd_prompt = random.choice(_empty_fallbacks)
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

    # Wider pool (last 15 entries) and randomize selection for more variety
    # This prevents repeating the same bulletins across image generations
    recent_pool = real_entries[-15:] if len(real_entries) >= 15 else real_entries
    random.shuffle(recent_pool)
    # Take only 10 to evaluate, then pick the first with characters or a random one
    eval_pool = recent_pool[:10]

    chosen        = None
    found_npcs    = []
    found_parties = []

    for entry in eval_pool:
        npcs    = find_npc_in_text(entry)
        parties = _find_parties_in_text(entry)
        if npcs or parties:
            chosen        = entry
            found_npcs    = npcs
            found_parties = parties
            break

    # If no NPCs/parties found in eval pool, pick from the full pool
    # instead of just from the last 5
    if not chosen:
        chosen        = random.choice(eval_pool) if eval_pool else random.choice(real_entries)
        found_npcs    = find_npc_in_text(chosen)
        found_parties = _find_parties_in_text(chosen)
        # If still no NPCs found, try to extract from database context or use contextual extraction
        if not found_npcs and not found_parties:
            logger.info(f"🖼️ No named NPCs found in chosen bulletin — checking database context")
            # Try to get NPCs from database context for richer scenes
            db_npcs = story_context.get("active_npcs", [])
            if db_npcs:
                # Pick 1-2 random NPCs from DB to potentially feature
                sample_npcs = random.sample(db_npcs, min(2, len(db_npcs)))
                for npc in sample_npcs:
                    npc_name = npc.get("name", "")
                    if npc_name:
                        try:
                            from src.npc_appearance import get_npc_appearance
                            appearance = get_npc_appearance(npc_name)
                            if appearance:
                                found_npcs.append((npc_name, appearance.get("sd_prompt", ""), ""))
                                logger.info(f"🖼️ Added DB NPC to scene: {npc_name}")
                        except Exception:
                            found_npcs.append((npc_name, "", ""))

    district_aesthetic = _get_district_aesthetic(chosen)
    if not district_aesthetic:
        # No district matched from bulletin text — try NPC/party home districts
        home_keys = (
            [home for _, _, home in found_npcs if home] +
            [home for _, _, home in found_parties if home]
        )
        if home_keys:
            from collections import Counter
            best = Counter(home_keys).most_common(1)[0][0]
            district_aesthetic = _DISTRICT_AESTHETICS.get(best, "")

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

    # If still not enough characters, use contextual extraction to add variety
    if len(char_parts) < MAX_CHARS:
        contextual = _extract_contextual_characters(chosen)
        for desc in contextual:
            if len(char_parts) < MAX_CHARS:
                char_parts.append(desc)

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
            "grand forum":        "white marble columns, bright civic hall, holographic boards, polished floor, FTA guards, busy with officials",
            "central plaza":      "grand colonnade square, ornamental fountain, bright stone floor, civic crowd",
            "grand forum library":"barrel vault library, white columns, bookshelves, warm amber light, quiet scholars",
            "adventurer's inn":   "tavern interior, warm hearth light, rough wooden tables, adventurers with maps",
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
        quality_header = "wide establishing shot, mid-action scene, story moment caught in frame"
        framing = (
            "camera far back, environment fills majority of frame, "
            "characters small relative to surroundings, "
            "no medieval castle architecture, no fantasy throne room"
        )

    sd_prompt = await _prompt_agent(
        bulletin_text=chosen,
        npc_names=npc_names,
        loc_key=chosen,
        scene_action=scene_action,
        quality_header=quality_header,
        framing=framing,
        district_aesthetic=district_aesthetic,
    )

    return sd_prompt, npc_names, chosen



# Old generate_story_image removed. Replaced by generate_city_scene() in src/city_scene.py



# ---------------------------------------------------------------------------
# NPC portrait generator — character bio card images
# ---------------------------------------------------------------------------

async def _generate_npc_action_ref(
    *,
    npc_name: str,
    npc_class: str,
    npc_faction: str,
    npc_role: str,
    npc_loc: str,
    npc_species: str,
    sd_appearance: str,
    portrait_bytes: bytes,
    base_payload: dict,
    base_negative: str,
    a1111_url: str,
    a1111_model: str,
    is_player_char: bool,
) -> None:
    """Generate one ref_002+ action shot from the canonical ref_001 portrait."""
    if os.getenv("NPC_ACTION_REFS_ENABLED", "1").lower() in {"0", "false", "no"}:
        return
    if not portrait_bytes:
        return

    import base64
    import io as _io
    import httpx

    try:
        from src.db_api import pick_npc_action_prompt
        action = pick_npc_action_prompt(npc_class or npc_role or "adventurer")
    except Exception as e:
        logger.warning(f"NPC action prompt pick failed for {npc_name}: {e}")
        return

    action_prompt = action.get("action_prompt") or ""
    action_label = action.get("action_label") or "action"
    class_key = action.get("class_name") or "adventurer"
    if not action_prompt:
        return

    prompt = (
        f"{sd_appearance}, {action_prompt}, "
        "same exact person as the reference image, same face, same eyes, same facial markings, "
        "same species anatomy, same recognizable outfit and faction colors, "
        f"{npc_faction} context, {npc_loc or 'the Undercity'} background, "
        "dynamic cinematic fantasy action scene, sharp focus, high detail"
    )
    negative = (
        f"{base_negative}, different person, changed face, changed identity, face swap, "
        "unrecognizable face, duplicate person, extra character, crowd focus, helmet covering face, "
        "mask covering face, text, watermark"
    )

    payload = dict(base_payload)
    payload.update({
        "prompt": prompt,
        "negative_prompt": negative,
        "seed": random.randint(1, 999999),
        "restore_faces": False,
    })

    try:
        from src.image_ref import to_img2img_payload, save_npc_action_ref
        from src.a1111_runtime import cool_down_a1111_after_generation, ensure_a1111_model

        img2img_payload = to_img2img_payload(
            payload,
            portrait_bytes,
            float(os.getenv("NPC_ACTION_REF_DENOISE", "0.72")),
        )

        async with a1111_lock:
            await ensure_a1111_model(a1111_model, label="NPC_ACTION_REF", url=a1111_url)
            async with httpx.AsyncClient(timeout=float(os.getenv("NPC_ACTION_REF_TIMEOUT", "600"))) as client:
                response = await client.post(f"{a1111_url}/sdapi/v1/img2img", json=img2img_payload)
                response.raise_for_status()
                action_bytes = base64.b64decode(response.json()["images"][0])
            await cool_down_a1111_after_generation()

        try:
            from PIL import Image as _PIL
            image = _PIL.open(_io.BytesIO(action_bytes))
            width, height = image.size
            if height > 80:
                image = image.crop((0, 0, width, height - 52))
            buf = _io.BytesIO()
            image.save(buf, format="PNG")
            action_bytes = buf.getvalue()
        except Exception:
            pass

        save_npc_action_ref(
            npc_name,
            action_bytes,
            metadata={
                "class_name": npc_class,
                "class_key": class_key,
                "action_label": action_label,
                "faction": npc_faction,
                "role": npc_role,
                "location": npc_loc,
                "species": npc_species,
                "is_player_char": is_player_char,
                "source": "npc_portrait_loop_action_ref",
                "base_ref": "ref_001.png",
            },
        )
        logger.info(f"NPC action ref generated: {npc_name} ({class_key}/{action_label})")
    except Exception as e:
        logger.warning(f"NPC action ref generation failed for {npc_name}: {e}")


async def generate_npc_portrait() -> tuple:
    """
    Generate a character portrait image for a random NPC from the DB.

    Returns (image_bytes, npc_data, caption) or (None, None, None) on failure.

    Image style: portrait orientation (768x1024), character-focused,
    upper body or 3/4 shot, Undercity city district background.
    """
    import httpx, base64, io as _io, re as _re, logging
    logger = logging.getLogger(__name__)

    # A1111 uses its own GPU context — separate from Ollama (llama.cpp).
    # 8B Ollama model (~5.2GB) + SDXL A1111 (~6-8GB) = ~13GB, well within 24GB pool.
    # No wait needed — portraits run in parallel with any Ollama task.

    A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")
    A1111_MODEL = os.getenv("A1111_MODEL", "sd_epicrealismXL_pureFix")
    _image_style = os.getenv("IMAGE_STYLE", "photorealistic").lower().strip()
    is_anime = _image_style == "anime"

    from src.db_api import raw_query
    import json as _json

    # Player-character portraits DISABLED 2026-07-12 (user: "we have enough now").
    # The PC branch below is kept intact so this is a one-line re-enable later.
    _is_player_char = False

    sd_appearance = ""
    npc_name = npc_faction = npc_rank = npc_role = npc_loc = npc_class = ""
    npc_species = "human"  # safe default for alt-universe species lookup
    _species_negative = ""

    if _is_player_char:
        # Try to pick a player character
        _pc_rows = raw_query(
            "SELECT name, species, class_name, profile_json, raw_block, oracle_notes FROM player_characters "
            "ORDER BY RAND() LIMIT 1"
        ) or []
        if _pc_rows:
            _pc = _pc_rows[0]
            npc_name = _pc.get("name", "Unknown Adventurer")
            npc_faction = "Adventurer"
            _pj = _pc.get("profile_json") or {}
            if isinstance(_pj, str):
                try:
                    _pj = _json.loads(_pj)
                except Exception:
                    _pj = {}
            # Use direct species column first, fall back to profile_json
            _race    = _pc.get("species") or _pj.get("race", _pj.get("species", "Human"))
            _classes = _pc.get("class_name") or _pj.get("classes", _pj.get("class", "Adventurer"))
            if isinstance(_classes, dict):
                _classes = ", ".join(f"{v} {k}" for k, v in _classes.items())
            _level   = _pj.get("level", _pj.get("total_level", ""))
            # Parse gender and height from raw_block (format: "GENDER: Female | AGE: 22 | HEIGHT: 5'7"")
            import re as _re2
            _raw = _pc.get("raw_block", "") or ""
            _gender_m = _re2.search(r"GENDER:\s*(\w+)", _raw, _re2.IGNORECASE)
            _height_m = _re2.search(r"HEIGHT:\s*([\d'\"]+)", _raw, _re2.IGNORECASE)
            _gender = _gender_m.group(1).lower() if _gender_m else ""
            _height = _height_m.group(1) if _height_m else ""
            _gender_tag = {"female": "female", "woman": "female", "male": "male", "man": "male"}.get(_gender, "")
            # Prefer appearance-specific fields; fall back to oracle_notes for description context
            _notes = (
                _pj.get("appearance", "") or
                _pj.get("description", "") or
                _pj.get("physical_description", "") or
                (_pc.get("oracle_notes", "") or "")[:120]
            )[:150].strip()
            npc_role    = str(_classes)
            npc_class   = str(_classes)
            npc_rank    = f"Level {_level}" if _level else ""
            npc_loc     = "the Undercity"
            npc_species = _race
            # Build SD appearance.
            # When the character has a concept description (_notes), it leads the prompt
            # so A1111 uses it as the primary subject. Species anatomy constraints follow
            # as secondary descriptors. Without notes, species anatomy leads (default for
            # standard humanoid races where accurate anatomy matters most).
            from src.npc_appearance import get_race_sd_traits, species_portrait_constraints, species_visual_guard
            _race_traits = get_race_sd_traits(_race)
            _species_positive, _species_negative = species_portrait_constraints(_race)
            _has_concept = bool(_notes and len(_notes) > 20)
            if _has_concept:
                _appearance_parts = [
                    _notes,
                    _gender_tag,
                    _race_traits,
                    str(_classes),
                    species_visual_guard(_race),
                    _species_positive,
                    "character portrait",
                ]
            else:
                _appearance_parts = [
                    species_visual_guard(_race),
                    _species_positive,
                    _gender_tag,
                    _race_traits,
                    str(_classes),
                    "adventurer",
                    "hero of the Undercity",
                ]
            if _height:
                _appearance_parts.append(f"{_height} tall")
            if _level:
                _appearance_parts.append(f"level {_level}")
            sd_appearance = ", ".join(p for p in _appearance_parts if p).strip(", ")
            logger.info(f"🎨 Player char portrait: {npc_name} ({_gender or '?'} {_race} {_classes})")
        else:
            _is_player_char = False  # fall through to NPC

    if not _is_player_char or not sd_appearance:
        _is_player_char = False  # guarantee false if we're using NPC path
        # Pick a random NPC with a proper SD appearance prompt
        # Only select top-level DB columns — rank/species/motivation live in data_json
        _rows = raw_query(
            "SELECT n.name, n.faction, n.role, n.location, n.species, n.data_json, "
            "       na.appearance_json "
            "FROM npcs n "
            "JOIN npc_appearances na ON n.name = na.npc_name "
            "WHERE n.status IN ('alive','injured','undead','doppelganger') AND na.appearance_json IS NOT NULL "
            "AND na.appearance_json LIKE '%sd_appearance%' "
            "ORDER BY RAND() LIMIT 1"
        ) or []

        if not _rows:
            logger.warning("🎨 NPC portrait: no NPCs with appearance profiles found")
            return None, None, None

        _row = _rows[0]
        _dj = _row.get("data_json") or {}
        if isinstance(_dj, str):
            try:
                _dj = _json.loads(_dj)
            except Exception:
                _dj = {}
        npc_name    = _row.get("name", "Unknown")
        npc_faction = _row.get("faction", "Independent")
        npc_rank    = _dj.get("rank", "")
        npc_role    = _row.get("role", "") or _dj.get("role", "")
        npc_loc     = _row.get("location", "the Undercity") or _dj.get("location", "the Undercity")
        npc_species = _row.get("species") or _dj.get("species", "human")
        _stats = _dj.get("stats") or {}
        if not isinstance(_stats, dict):
            _stats = {}
        npc_class = (
            str(_stats.get("class") or _dj.get("dnd_class") or _dj.get("class") or npc_role or "Adventurer")
        )

        _app_json = _row.get("appearance_json") or {}
        if isinstance(_app_json, str):
            try:
                _app_json = _json.loads(_app_json)
            except Exception:
                _app_json = {}
        sd_appearance = _app_json.get("sd_appearance", "")

        if not sd_appearance:
            logger.warning(f"🎨 NPC portrait: {npc_name} has no sd_appearance")
            return None, None, None

        from src.npc_appearance import (
            get_race_sd_traits as _race_traits_for,
            species_portrait_constraints as _species_constraints,
            species_visual_guard as _species_guard,
        )
        _species_traits = _race_traits_for(npc_species)
        _species_positive, _species_negative = _species_constraints(npc_species)
        sd_appearance = f"{_species_guard(npc_species)}, {_species_positive}, {_species_traits}, {sd_appearance}"

        # Prepend gender if inferable from description and not already in the prompt
        from src.npc_appearance import infer_gender_tag as _infer_gender
        _desc_text = _dj.get("appearance", "") or _dj.get("description", "") or ""
        _gender_inferred = _infer_gender(_desc_text + " " + sd_appearance)
        if _gender_inferred and _gender_inferred not in sd_appearance.lower():
            sd_appearance = f"{_gender_inferred}, {sd_appearance}"

    # Build portrait prompt
    _bg_options = [
        "undercity city street background, dome sky above, faction banners",
        "crowded market district background, lantern light, city architecture",
        "faction headquarters exterior background, guards, city life",
        "rain-slick cobblestone street background, moody city lighting",
        "undercity plaza background, tower spire visible, artificial sky",
    ]
    _bg = random.choice(_bg_options)

    # 1-in-5 chance: alt-universe furry version of the NPC.
    # Tabaxi already have a strict humanoid catfolk anatomy target; sending them
    # through the generic anthro branch tends to produce literal animal heads.
    from src.npc_appearance import current_visual_species as _current_visual_species_for_alt
    _current_species_for_alt = _current_visual_species_for_alt(npc_species).lower() if npc_species else ""
    _is_alt_universe = random.random() < 0.20 and "tabaxi" not in _current_species_for_alt

    if _is_alt_universe:
        A1111_MODEL = "sd_novaFurryXL_ilV160"
        _quality = "masterpiece, best quality, detailed fur, anthro character, upper body portrait, expressive eyes"
        _neg = (
            "nsfw, explicit, nude, worst quality, lowres, bad anatomy, bad hands, "
            "poorly drawn face, poorly drawn hands, mutation, deformed, ugly, blurry, "
            "text, watermark, signature, human only, realistic photo"
        )
        if _species_negative:
            _neg = f"{_neg}, {_species_negative}"
        # Build anthro version — keep faction/personality, swap appearance to anthro animal
        _species_hints = {
            # PHB core
            "human":          "anthro wolf",
            "elf":            "anthro cat",
            "high elf":       "anthro cat",
            "wood elf":       "anthro lynx",
            "drow":           "anthro cat",
            "eladrin":        "anthro cat",
            "sea elf":        "anthro otter",
            "shadar-kai":     "anthro cat",
            "dwarf":          "anthro bear",
            "hill dwarf":     "anthro bear",
            "mountain dwarf": "anthro bear",
            "halfling":       "anthro rabbit",
            "lightfoot":      "anthro rabbit",
            "stout":          "anthro rabbit",
            "gnome":          "anthro fox",
            "forest gnome":   "anthro fox",
            "rock gnome":     "anthro fox",
            "deep gnome":     "anthro mole",
            "orc":            "anthro boar",
            "half-orc":       "anthro boar",
            "tiefling":       "anthro ram",
            "aasimar":        "anthro deer",
            "dragonborn":     "anthro dragon",
            "half-elf":       "anthro fox",
            # Martial / nature
            "goliath":        "anthro bear",
            "firbolg":        "anthro deer",
            "satyr":          "anthro goat",
            "centaur":        "anthro horse",
            "minotaur":       "anthro bull",
            "leonin":         "anthro lion",
            "loxodon":        "anthro elephant",
            # Feline / avian / reptile
            "tabaxi":         "anthro cat",
            "aarakocra":      "anthro eagle",
            "kenku":          "anthro crow",
            "owlin":          "anthro owl",
            "lizardfolk":     "anthro lizard",
            "kobold":         "anthro lizard",
            "tortle":         "anthro turtle",
            "yuan-ti":        "anthro snake",
            "grung":          "anthro frog",
            "locathah":       "anthro fish",
            "triton":         "anthro otter",
            # Elemental genasi
            "genasi":         "anthro fox",
            "fire genasi":    "anthro fox",
            "water genasi":   "anthro otter",
            "air genasi":     "anthro hawk",
            "earth genasi":   "anthro badger",
            # Planar / exotic
            "githyanki":      "anthro lizard",
            "githzerai":      "anthro cat",
            "changeling":     "anthro fox",
            "shifter":        "anthro wolf",
            "kalashtar":      "anthro deer",
            "harengon":       "anthro rabbit",
            "fairy":          "anthro fox",
            "giff":           "anthro hippopotamus",
            "hadozee":        "anthro monkey",
            "thri-kreen":     "anthro mantis",
            "plasmoid":       "anthro jellyfish",
            "astral elf":     "anthro cat",
            "autognome":      "anthro robot wolf",
            "warforged":      "anthro robot wolf",
            # Monstrous
            "hobgoblin":      "anthro wolf",
            "bugbear":        "anthro bear",
            "goblin":         "anthro rat",
            "vedalken":       "anthro cat",
            "simic hybrid":   "anthro shark",
            "minotaur":       "anthro bull",
            "specter":         "anthro ghost",
            "ghost":           "anthro ghost",
            "revenant":        "undead anthro wolf",
            "wight":           "undead anthro wolf",
            "lich":            "undead anthro jackal",
            "shade":           "shadow anthro cat",
            "skeleton":        "skeletal anthro wolf",
            "zombie":          "undead anthro dog",
            "vampire":         "vampire anthro bat",
            "dhampir":         "vampire anthro bat",
        }
        from src.npc_appearance import current_visual_species as _current_visual_species
        _npc_species = _current_visual_species(npc_species).lower() if npc_species else "human"
        _anthro = next((v for k, v in _species_hints.items() if k in _npc_species), "anthro wolf")
        # Filter sd_appearance down to parts that transfer to anthro:
        # keep clothing, armor, accessories, scars, expression cues — drop pure skin/hair color terms
        _SKIP_TERMS = {
            "skin", "complexion", "tan", "pale", "dark skin", "light skin",
            "hair", "brunette", "blonde", "redhead", "bald",
            "human", "realistic photo", "photograph",
        }
        _appearance_parts = []
        for _part in (sd_appearance or "").split(","):
            _p = _part.strip()
            if _p and not any(_s in _p.lower() for _s in _SKIP_TERMS):
                _appearance_parts.append(_p)
        _anthro_appearance = ", ".join(_appearance_parts[:6])  # cap to avoid prompt bloat
        portrait_prompt = (
            f"{_anthro}, {_anthro_appearance + ', ' if _anthro_appearance else ''}"
            f"{npc_faction.lower()} faction colours, {_bg}, "
            f"upper body portrait, looking at viewer, confident expression, "
            f"faction appropriate clothing and equipment, {_quality}"
        )
        logger.info(f"🎨 Alt-universe portrait: {npc_name} as {_anthro}")
    else:
        if is_anime:
            _quality = "masterpiece, best quality, very aesthetic, absurdres, detailed face, upper body"
            _neg = (
                "nsfw, worst quality, lowres, bad anatomy, bad hands, error, missing fingers, "
                "extra digit, fewer digits, cropped, worst quality, low quality, jpeg artifacts, "
                "signature, watermark, username, blurry, bad feet, text, logo"
            )
        else:
            _quality = "cinematic portrait photography, 85mm lens, f/2.8, sharp focus, detailed face, 8k uhd"
            _neg = (
                "text, watermark, signature, blurry, low quality, deformed, ugly, "
                "bad anatomy, extra limbs, sewer, tunnel, cave, dungeon, underground, "
                "cartoon, anime, painting, illustration, full body, feet, shoes, "
                "familiar, pet, companion creature, slime, floating creature, cute creature, chibi creature"
            )
        if _species_negative:
            _neg = f"{_neg}, {_species_negative}"
        portrait_prompt = (
            f"{sd_appearance}, "
            f"upper body portrait, {_bg}, "
            f"looking at camera, confident expression, "
            f"{_quality}"
        )

    # Generate portrait (portrait orientation)
    _payload = {
        "prompt": portrait_prompt,
        "negative_prompt": _neg,
        "steps": 30,
        "cfg_scale": 7.0,
        "width": 768,
        "height": 1024,
        "sampler_name": "DPM++ 2M SDE Karras",
        "seed": random.randint(1, 999999),
        "batch_size": 1,
        "n_iter": 1,
        "restore_faces": False,
    }

    img_bytes = None
    from src.resource_cop import wait_for_a1111_turn
    _decision = await wait_for_a1111_turn("npc_portrait", model_hint=A1111_MODEL)
    if not _decision.run_now:
        logger.warning("🎨 Portrait skipped because A1111 stayed busy: %s", _decision.reason)
        from src.a1111_health import record_a1111_failure
        await record_a1111_failure("npc_portrait", f"busy after traffic-cop wait: {_decision.reason}", url=A1111_URL)
        return None, None, None
    _last_a1111_error = ""
    async with a1111_lock:
        from src.a1111_runtime import cool_down_a1111_after_generation, ensure_a1111_model
        await ensure_a1111_model(A1111_MODEL, label="PORTRAIT", url=A1111_URL)
        for _att in range(2):
            try:
                async with httpx.AsyncClient(timeout=600.0) as _c:
                    _r = await _c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=_payload)
                    _r.raise_for_status()
                    img_bytes = base64.b64decode(_r.json()["images"][0])
                    from src.a1111_health import record_a1111_success
                    await record_a1111_success("npc_portrait")
                    await cool_down_a1111_after_generation()
                    break
            except Exception as _ae:
                _last_a1111_error = repr(_ae)
                logger.warning(f"🎨 Portrait attempt {_att+1}/2: {_ae}")
                if _att == 0:
                    await asyncio.sleep(10)

    if not img_bytes:
        from src.a1111_health import record_a1111_failure
        await record_a1111_failure(
            "npc_portrait",
            _last_a1111_error or "no image after portrait attempts",
            url=A1111_URL,
        )
        return None, None, None

    # Crop watermark strip
    try:
        from PIL import Image as _PIL
        _img = _PIL.open(_io.BytesIO(img_bytes))
        _w, _h = _img.size
        _img = _img.crop((0, 0, _w, _h - 52))
        _buf = _io.BytesIO()
        _img.save(_buf, format="PNG")
        img_bytes = _buf.getvalue()
    except Exception:
        pass

    npc_data = {
        "name": npc_name,
        "faction": npc_faction,
        "rank": npc_rank,
        "role": npc_role,
        "class_name": npc_class,
        "location": npc_loc,
        "alt_universe": _is_alt_universe,
        "is_player_char": _is_player_char,
    }
    try:
        from src.image_ref import save_npc_alt_ref, save_npc_ref
        saver = save_npc_alt_ref if _is_alt_universe else save_npc_ref
        saver(
            npc_name,
            img_bytes,
            metadata={
                "faction": npc_faction,
                "rank": npc_rank,
                "role": npc_role,
                "class_name": npc_class,
                "location": npc_loc,
                "alt_universe": _is_alt_universe,
                "is_player_char": _is_player_char,
                "source": "npc_portrait_loop",
            },
        )
    except Exception as e:
        logger.warning(f"NPC portrait ref save failed for {npc_name}: {e}")

    if not _is_alt_universe:
        await _generate_npc_action_ref(
            npc_name=npc_name,
            npc_class=npc_class,
            npc_faction=npc_faction,
            npc_role=npc_role,
            npc_loc=npc_loc,
            npc_species=npc_species,
            sd_appearance=sd_appearance,
            portrait_bytes=img_bytes,
            base_payload=_payload,
            base_negative=_neg,
            a1111_url=A1111_URL,
            a1111_model=A1111_MODEL,
            is_player_char=_is_player_char,
        )

    if _is_alt_universe:
        caption = f"[Alt Universe] {npc_name} — {npc_faction}"
    else:
        caption = f"{npc_name} — {npc_rank or npc_role}, {npc_faction}" if (npc_rank or npc_role) else f"{npc_name} — {npc_faction}"

    # Free VRAM after portrait so Ollama can use the GPU
    try:
        async with httpx.AsyncClient(timeout=15.0) as _uc:
            await _uc.post(f"{A1111_URL}/sdapi/v1/unload-checkpoint")
    except Exception:
        pass

    logger.info(f"🎨 Portrait generated: {npc_name} ({npc_faction}){' [ALT UNIVERSE]' if _is_alt_universe else ''}")
    return img_bytes, npc_data, caption


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
    prompt = repair_mojibake(_build_prompt(memory))

    ollama_model = os.getenv("OLLAMA_FAST_MODEL", os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"))

    try:
        import re as _re
        from src.ollama_queue import call_ollama, OllamaBusyError
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": 2048, "num_ctx": _fit_num_ctx(prompt, 2048), "think": True},
            },
            timeout=600.0,
            caller="bulletin_draft",
        )

        bulletin = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                bulletin = repair_mojibake(msg.get("content", "")).strip()

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
                r'\n\s*---\s*\n+(?:you are the undercity dispatch|you are talis vore|task:|write one undercity|write one tnn)',
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

        # Validate the final bulletin before returning
        if bulletin:
            is_valid, reason = validate_bulletin(bulletin)
            if not is_valid:
                import logging
                logging.getLogger(__name__).warning(
                    f"\U0001f4f0 Draft bulletin failed validation ({reason}) \u2014 discarding"
                )
                return None, None

        if bulletin:
            bulletin = repair_mojibake(bulletin)
            # Use double-newline for better Discord embed rendering
            formatted = f"-# \U0001f570\ufe0f {_dual_timestamp()}\n\n{bulletin}"
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
    """Randomised 5-8 hour interval between story images.
    Slowed from 2-4h on 2026-07-12 -- images were posting too fast and the
    A1111 GPU draw adds up (peak power pricing on weekdays)."""
    return random.randint(5 * 60 * 60, 8 * 60 * 60)
