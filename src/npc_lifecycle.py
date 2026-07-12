"""
npc_lifecycle.py — Living NPC ecosystem for Tower of Last Chance.

NPCs are born, promoted, betrayed, revealed, and killed based on world events.
One new NPC injected per day minimum. Existing NPCs evolve via daily lifecycle events.
All changes persist in MySQL npcs table and related tables.
"""

from __future__ import annotations

import os
import re
import json
import random
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.log import logger
from src.db_api import raw_query, raw_execute, db, add_npc_history_event, get_npc_history, get_npc_history_count, add_party_history_event, add_revealed_secret, get_revealed_secrets, has_revealed_secrets

# Keep txt file path for RAG system compatibility
DOCS_DIR          = Path(__file__).resolve().parent.parent / "campaign_docs"
NPC_TXT_FILE      = DOCS_DIR / "npc_roster.txt"

# Module-level force flag — True while run_daily_lifecycle is active so all
# _generate() calls bypass the Ollama busy check. Cleared in the finally block.
_lifecycle_force: bool = False

# ---------------------------------------------------------------------------
# Factions and ranks
# ---------------------------------------------------------------------------

# Major factions — used for new NPC generation and defection targets
FACTIONS = [
    "Iron Fang Consortium",
    "Iron Fang Syndicate",
    "Argent Blades",
    "Wardens of Ash",
    "Serpent Choir",
    "Obsidian Lotus",
    "Glass Sigil",
    "Patchwork Saints",
    "Adventurers Guild",
    "Guild of Ashen Scrolls",
    "Tower Authority",
    "Independent",
    "Brother Thane's Cult",
    "Wizards Tower",
]

# Generic corporate rank ladder applied to any (Guild) faction
GUILD_RANKS = [
    "Contracted Operative",
    "Senior Operative",
    "Department Lead",
    "Division Manager",
    "Guild Director",
    "Guild Executive",
]

FACTION_RANKS = {
    "Iron Fang Consortium":   ["Street Runner", "Acquisition Agent", "Senior Agent", "Floor Boss", "Underboss", "Guildmaster"],
    "Iron Fang Syndicate":    ["Runner", "Earner", "Collector", "Enforcer", "Capo", "Underboss", "Guildmaster"],
    "Argent Blades":          ["Prospect", "Blade", "Senior Blade", "Champion", "Vanguard", "Guildmaster"],
    "Wardens of Ash":         ["Recruit", "Warden", "Sergeant", "Lieutenant", "Captain", "Commander"],
    "Serpent Choir":          ["Petitioner", "Acolyte", "Contract Scribe", "Mediator", "High Scribe", "High Apostle"],
    "Obsidian Lotus":         ["Ghost", "Operative", "Specialist", "Handler", "Shadow Director", "The Widow"],
    "Glass Sigil":            ["Junior Archivist", "Archivist", "Senior Archivist", "Sigil Master"],
    "Patchwork Saints":       ["Volunteer", "Saint", "Field Lead", "Field Captain", "Coordinator"],
    "Adventurers Guild":      ["Unranked", "F-Rank", "E-Rank", "D-Rank", "C-Rank", "B-Rank", "A-Rank", "S-Rank", "SS-Rank"],
    "Guild of Ashen Scrolls": ["Initiate", "Scribe", "Archivist Second Class", "Archivist First Class", "Senior Archivist", "Head Archivist"],
    "Tower Authority":        ["Compliance Intern", "Field Compliance Officer", "Senior Officer", "Magister", "Director"],
    "Independent":            ["Street Level", "Known Operator", "Respected Freelance", "City Legend"],
    "Brother Thane's Cult":   ["Follower", "Devoted", "Speaker", "Inner Circle", "Second", "Thane"],
    "Wizards Tower":          ["Apprentice", "Journeyman", "Researcher", "Senior Researcher", "Magister", "Archmage"],
}


def _get_guild_factions() -> list:
    """Return all (Guild) faction names from DB. Cached per-process after first call."""
    try:
        rows = raw_query(
            "SELECT faction_name FROM faction_reputation "
            "WHERE faction_name LIKE '%(Guild)%' ORDER BY faction_name"
        )
        return [r["faction_name"] for r in rows] if rows else []
    except Exception:
        return []


def _ranks_for_faction(faction: str) -> list:
    """Return the rank ladder for a faction, using GUILD_RANKS for (Guild) factions."""
    if "(Guild)" in (faction or ""):
        return GUILD_RANKS
    return FACTION_RANKS.get(faction, ["Member"])

SPECIES_LIST = [
    "Human", "Half-Elf", "Dwarf", "Tiefling", "Halfling", "Gnome",
    "Orc", "Half-Orc", "Dragonborn", "Elf", "Tabaxi", "Warforged",
    "Goblin", "Kobold", "Aasimar", "Genasi",
]

NPC_EVENTS = [
    "promotion",
    "demotion",
    "faction_defection",
    "revelation",
    "death",
    "resurrection",
    "alliance",
    "betrayal",
    "new_secret",
    "public_incident",
    "daily_generated",      # fresh AI-generated event scenario
    "guild_hire",           # independent/faction NPC picked up by a (Guild)
    "guild_promotion",      # promoted within a (Guild) — better title, more pay
    "guild_fired",          # terminated from (Guild) — voluntary, forced, or "accidental"
    "guild_poached",        # rival (Guild) offers more and NPC jumps ship
]

# Weights must sum to 1.0 — guild events sit at ~10% combined weight
EVENT_WEIGHTS = [0.12, 0.07, 0.08, 0.12, 0.07, 0.02, 0.09, 0.08, 0.09, 0.07, 0.09,
                 0.03, 0.03, 0.02, 0.02]

# ---------------------------------------------------------------------------
# Daily generated event system — stored in DB lifecycle_daily_events
# ---------------------------------------------------------------------------

def _ensure_daily_events_table():
    """Ensure the daily events table exists."""
    try:
        raw_execute("""
            CREATE TABLE IF NOT EXISTS lifecycle_daily_events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                event_date DATE UNIQUE NOT NULL,
                events_json JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    except Exception as e:
        logger.debug(f"Daily events table check: {e}")

# Ensure table exists on module load
try:
    _ensure_daily_events_table()
except Exception:
    pass


def _load_daily_events() -> dict:
    """Load today's daily events from database."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        rows = raw_query(
            "SELECT events_json FROM lifecycle_daily_events WHERE event_date = %s",
            (today,)
        )
        if rows and rows[0].get("events_json"):
            events_data = rows[0]["events_json"]
            if isinstance(events_data, str):
                events_data = json.loads(events_data)
            return {"date": today, "events": events_data}
        return {}
    except Exception as e:
        logger.error(f"Daily events load error: {e}")
        return {}


def _save_daily_events(data: dict) -> None:
    """Save daily events to database."""
    try:
        date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
        events = data.get("events", [])
        events_json = json.dumps(events, ensure_ascii=False)

        # Upsert
        existing = raw_query(
            "SELECT id FROM lifecycle_daily_events WHERE event_date = %s",
            (date_str,)
        )
        if existing:
            raw_execute(
                "UPDATE lifecycle_daily_events SET events_json = %s WHERE event_date = %s",
                (events_json, date_str)
            )
        else:
            db.insert("lifecycle_daily_events", {
                "event_date": date_str,
                "events_json": events_json
            })
    except Exception as e:
        logger.error(f"Daily events save error: {e}")


def _needs_new_daily_events() -> bool:
    data = _load_daily_events()
    return data.get("date") != datetime.now().strftime("%Y-%m-%d")


async def refresh_daily_events_if_needed() -> None:
    """Generate 5 fresh, specific lifecycle event scenarios for today.
    Called at lifecycle startup. No-op if already generated today."""
    if not _needs_new_daily_events():
        return

    prompt = f"""{_LORE}

You are generating SPECIFIC lifecycle event scenarios for NPCs in the Undercity.
These are one-time events that happen to individual NPCs today.

Generate exactly 5 unique event scenarios. Each should be:
- A specific, dramatic situation (not generic like "gets promoted")
- Grounded in the Undercity setting — factions, districts, economy, Rifts
- Something that changes an NPC's status, relationships, or reputation
- 1-2 sentences describing WHAT HAPPENS (the lifecycle system will pick an NPC to apply it to)

Examples of good events:
- "Caught smuggling Rift residue samples to an outside buyer. Faction is deciding whether to cover it up or make an example."
- "Saved three children from a collapsing Warrens building. Suddenly famous in a district where fame is dangerous."
- "Received a sealed letter from a dead faction member — contents unknown, but they've been acting strange since."
- "Publicly accused a senior faction member of skimming funds. Either very brave or very stupid."
- "Found unconscious near a sealed Rift zone with no memory of the last 48 hours."

RULES:
- Output exactly 5 lines, one event per line.
- No numbering, no bullets, no preamble.
- Each event should be usable for ANY NPC regardless of faction.
- Vary the tone: some dangerous, some political, some personal, some supernatural.
- If your output contains anything other than 5 lines, you have failed."""

    text = await _generate(prompt)
    if not text:
        logger.warning("🧬 Daily event generation failed")
        return

    events = [l.strip() for l in text.splitlines() if l.strip()][:5]
    if not events:
        return

    today = datetime.now().strftime("%Y-%m-%d")
    _save_daily_events({"date": today, "events": events})
    logger.info(f"🧬 Generated {len(events)} daily lifecycle events for {today}")


def _get_random_daily_event() -> Optional[str]:
    """Return one random event from today's generated list, or None."""
    data = _load_daily_events()
    events = data.get("events", [])
    return random.choice(events) if events else None


# ---------------------------------------------------------------------------
# Persistence — MySQL via db_api
# ---------------------------------------------------------------------------

def _load_npcs() -> List[dict]:
    """Load all NPCs from database (excluding dead ones in graveyard)."""
    try:
        rows = raw_query(
            "SELECT id, name, faction, role, location, status, species, "
            "`rank`, motivation, quote, oracle_notes, secret, relationships, party_name, data_json "
            "FROM npcs WHERE status != 'dead' OR status IS NULL"
        )
        npcs = []
        for row in rows:
            # Parse data_json for remaining non-promoted fields
            npc_data = row.get("data_json") or {}
            if isinstance(npc_data, str):
                try:
                    npc_data = json.loads(npc_data) if npc_data else {}
                except json.JSONDecodeError:
                    npc_data = {}
            elif not isinstance(npc_data, dict):
                npc_data = {}
            # Real columns take precedence over data_json for promoted fields
            npc = {
                **npc_data,
                "name":         row.get("name") or npc_data.get("name", "Unknown"),
                "faction":      row.get("faction") or npc_data.get("faction", "Independent"),
                "role":         row.get("role") or npc_data.get("role", ""),
                "location":     row.get("location") or npc_data.get("location", ""),
                "status":       row.get("status") or npc_data.get("status", "alive"),
                "species":      row.get("species") or npc_data.get("species", "Human"),
                "rank":         row.get("rank") or npc_data.get("rank", ""),
                "motivation":   row.get("motivation") or npc_data.get("motivation", ""),
                "quote":        row.get("quote") or npc_data.get("quote", ""),
                "oracle_notes": row.get("oracle_notes") or npc_data.get("oracle_notes", ""),
                "secret":       row.get("secret") or npc_data.get("secret", ""),
                "relationships":row.get("relationships") or npc_data.get("relationships", ""),
                "party_name":   row.get("party_name") or "",
                "_db_id":       row.get("id"),
            }
            # Ensure history is always a list (fixes KeyError: 'history')
            if "history" not in npc or not isinstance(npc.get("history"), list):
                npc["history"] = []
            # Ensure revealed_secrets is always a list
            if "revealed_secrets" not in npc or not isinstance(npc.get("revealed_secrets"), list):
                npc["revealed_secrets"] = []
            npcs.append(npc)
        return npcs
    except Exception as e:
        logger.error(f"NPC load error: {e}")
        return []


def _hist(npc: dict, body: str) -> None:
    """Append one history event for npc to npc_history table."""
    npc_id = npc.get("_db_id") or npc.get("id")
    if npc_id:
        add_npc_history_event(int(npc_id), body)
    # Also keep in-memory list so same-session reads still work
    if isinstance(npc.get("history"), list):
        npc["history"].append(body)


def _scalar(value) -> str | None:
    """Coerce a value to a plain string for VARCHAR/TEXT columns.
    Dicts and lists (which arrive from data_json blobs) are JSON-serialized
    rather than passed raw, which would cause 'Python type dict cannot be
    converted' errors from the MySQL connector."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        s = json.dumps(value, ensure_ascii=False, default=str)
        return s or None
    s = str(value).strip()
    return s or None


def _save_npc(npc: dict) -> None:
    """Save a single NPC to database (insert or update)."""
    try:
        name = npc.get("name", "Unknown")
        # Prepare data_json — strip runtime-only keys and fields now in real columns
        npc_copy = {k: v for k, v in npc.items() if k not in ("_db_id", "history", "revealed_secrets", "death_cause", "cause_of_death", "tower_absorbed", "party_name")}
        data_json = json.dumps(npc_copy, ensure_ascii=False, default=str)

        # Check if exists by name
        existing = raw_query("SELECT id FROM npcs WHERE name = %s", (name,))

        if existing:
            raw_execute(
                """UPDATE npcs SET
                   faction        = %s,
                   role           = %s,
                   location       = %s,
                   status         = %s,
                   `rank`         = %s,
                   motivation     = %s,
                   quote          = %s,
                   oracle_notes   = %s,
                   secret         = %s,
                   relationships  = %s,
                   death_cause    = %s,
                   tower_absorbed = %s,
                   data_json      = %s
                   WHERE name = %s""",
                (
                    npc.get("faction") or "Independent",
                    npc.get("role") or "",
                    npc.get("location") or "",
                    npc.get("status") or "alive",
                    _scalar(npc.get("rank")),
                    _scalar(npc.get("motivation")),
                    _scalar(npc.get("quote")),
                    _scalar(npc.get("oracle_notes")),
                    _scalar(npc.get("secret")),
                    _scalar(npc.get("relationships")),
                    _scalar(npc.get("death_cause") or npc.get("cause_of_death")),
                    1 if npc.get("tower_absorbed") else 0,
                    data_json,
                    name,
                )
            )
        else:
            db.insert("npcs", {
                "name":          name,
                "faction":       npc.get("faction") or "Independent",
                "role":          npc.get("role") or "",
                "location":      npc.get("location") or "",
                "status":        npc.get("status") or "alive",
                "rank":          _scalar(npc.get("rank")),
                "motivation":    _scalar(npc.get("motivation")),
                "quote":         _scalar(npc.get("quote")),
                "oracle_notes":  _scalar(npc.get("oracle_notes")),
                "secret":        _scalar(npc.get("secret")),
                "relationships": _scalar(npc.get("relationships")),
                "death_cause":   _scalar(npc.get("death_cause") or npc.get("cause_of_death")),
                "tower_absorbed": 1 if npc.get("tower_absorbed") else 0,
                "data_json":      data_json,
            })
            # Write any founding history events that were in the dict before it was stripped
            founding = npc.get("history") or []
            if founding:
                row = raw_query("SELECT id FROM npcs WHERE name=%s", (name,))
                if row:
                    for entry in (founding if isinstance(founding, list) else []):
                        if entry:
                            add_npc_history_event(row[0]["id"], str(entry))
    except Exception as e:
        logger.error(f"NPC save error for {npc.get('name', '?')}: {e}")
        return

    # Trigger Mimir sync for this NPC (fire-and-forget, safe if Mimir is down)
    try:
        rows = raw_query("SELECT id FROM npcs WHERE name=%s", (npc.get("name", ""),))
        if rows:
            from src.mimir_sync import trigger_npc_sync
            trigger_npc_sync(rows[0]["id"])
    except Exception:
        pass


def _save_npcs(npcs: List[dict]) -> None:
    """Save all NPCs and rebuild the txt file for RAG."""
    for npc in npcs:
        _save_npc(npc)
    _rebuild_txt(npcs)


def _rebuild_txt(npcs: List[dict]) -> None:
    """Rewrite npc_roster.txt from current JSON so RAG stays in sync.
    Dead NPCs are excluded — they live in npc_graveyard.json instead."""
    lines = [
        "# NPC ROSTER — TOWER OF LAST CHANCE",
        "# Auto-generated from npc_lifecycle system. Do not edit manually.",
        f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"# Active NPCs: {len([n for n in npcs if n.get('status') != 'dead'])}",
        "",
    ]
    for npc in npcs:
        # Skip dead NPCs — they should be in the graveyard, not the active RAG context
        if npc.get("status") == "dead":
            continue
        lines.append("---NPC---")
        lines.append(f"NAME: {npc.get('name', 'Unknown')}")
        lines.append(f"STATUS: {npc.get('status', 'alive')}")
        lines.append(f"FACTION: {npc.get('faction', 'Independent')}")
        lines.append(f"RANK: {npc.get('rank', 'Unknown')}")
        lines.append(f"SPECIES: {npc.get('species', 'Human')}")
        lines.append(f"AGE: {npc.get('age', 'Unknown')}")
        if npc.get("appearance"):
            lines.append(f"APPEARANCE: {npc['appearance']}")
        if npc.get("location"):
            lines.append(f"LOCATION: {npc['location']}")
        lines.append(f"MOTIVATION: {npc.get('motivation', '')}")
        lines.append(f"ROLE: {npc.get('role', '')}")
        if npc.get("secret"):
            lines.append(f"SECRET: {npc['secret']}")
        _revealed = npc.get("revealed_secrets") or []
        if not _revealed:
            _nid = npc.get("_db_id") or npc.get("id")
            if _nid:
                _revealed = get_revealed_secrets(int(_nid))
        if _revealed:
            lines.append(f"REVEALED: {' | '.join(_revealed)}")
        if npc.get("relationships"):
            lines.append(f"RELATIONSHIPS: {npc['relationships']}")
        if npc.get("oracle_notes"):
            lines.append(f"ORACLE NOTES: {npc['oracle_notes']}")
        hist_in_mem = npc.get("history") or []
        if not hist_in_mem:
            npc_id = npc.get("_db_id") or npc.get("id")
            if npc_id:
                hist_in_mem = [r["body"] for r in get_npc_history(int(npc_id), limit=10)]
        if hist_in_mem:
            lines.append(f"HISTORY: {' | '.join(hist_in_mem[-5:])}")
        lines.append("---END NPC---")
        lines.append("")
    # DB is the source of truth — no file write-back needed


# ---------------------------------------------------------------------------
# Graveyard — dead NPCs are queried by status='dead'
# ---------------------------------------------------------------------------

def _load_graveyard() -> List[dict]:
    """Load all dead NPCs from database."""
    try:
        rows = raw_query("SELECT * FROM npcs WHERE status = 'dead'")
        graveyard = []
        for row in rows:
            npc_data = row.get("data_json", {})
            if isinstance(npc_data, str):
                npc_data = json.loads(npc_data) if npc_data else {}
            npc = {
                **npc_data,
                "name": row.get("name") or npc_data.get("name", "Unknown"),
                "faction": row.get("faction") or npc_data.get("faction", "Independent"),
                "status": "dead",
                "_db_id": row.get("id"),
            }
            graveyard.append(npc)
        return graveyard
    except Exception as e:
        logger.error(f"Graveyard load error: {e}")
        return []


def _save_graveyard(graveyard: List[dict]) -> None:
    """Save graveyard NPCs (just updates their records in npcs table)."""
    for npc in graveyard:
        _save_npc(npc)


def _move_to_graveyard(npc: dict, npcs: List[dict]) -> None:
    """Mark an NPC as dead (moves them to graveyard status).
    Removes from the npcs list in-place."""
    now = datetime.now()
    npc["status"] = "dead"
    npc["moved_to_graveyard_at"] = now.isoformat()
    npc["death_date"] = now.strftime("%Y-%m-%d %H:%M")  # consistent format for recently_deceased_block
    _save_npc(npc)
    # Also stamp deceased_at on the DB row directly
    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE npcs SET deceased_at=%s WHERE name=%s", (now, npc.get("name")))
    except Exception as _e:
        logger.warning(f"💀 Could not set deceased_at for {npc.get('name')}: {_e}")
    logger.info(f"💀 {npc.get('name')} moved to graveyard")

    # Remove from active roster list
    try:
        npcs.remove(npc)
    except ValueError:
        pass


def _sweep_dead_to_graveyard(npcs: List[dict]) -> int:
    """Mark any dead NPCs in the active roster as graveyard status.
    With DB storage, this just ensures status is set correctly.
    Returns count of NPCs updated."""
    dead = [n for n in npcs if n.get("status") == "dead"]
    if not dead:
        return 0

    for npc in dead:
        if not npc.get("moved_to_graveyard_at"):
            npc["moved_to_graveyard_at"] = datetime.now().isoformat()
        _save_npc(npc)
        try:
            npcs.remove(npc)
        except ValueError:
            pass

    if dead:
        logger.info(f"💀 Graveyard sweep: updated {len(dead)} dead NPCs")

    return len(dead)


# ---------------------------------------------------------------------------
# Ollama generation helper
# ---------------------------------------------------------------------------

async def _generate(prompt: str, timeout: float = 300.0, retries: int = 3,
                    num_predict: int = 900, fast=None) -> Optional[str]:
    """Call Ollama and return the text response. Queued via ollama_queue FIFO lock.

    fast=True  -> uses OLLAMA_FAST_MODEL with small context. For short texts.
    fast=False -> uses OLLAMA_MODEL with larger context. For quality generation.
    """
    import asyncio
    from src.ollama_queue import call_ollama, OllamaBusyError
    from src.ollama_busy import is_priority_busy

    # Auto-route: short outputs -> the fast path; long/complex outputs -> more context.
    # Callers can override by passing fast=True/False explicitly.
    if fast is None:
        fast = num_predict < 1800  # short announcements/events/bulletins -> fast
    if fast:
        ollama_model = os.getenv("OLLAMA_FAST_MODEL", "qwen3-8b-slim:latest")
        num_ctx = 4096
    else:
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
        num_ctx = 8192

    # Even in lifecycle-force mode, yield immediately if mission building claimed priority.
    if _lifecycle_force and is_priority_busy():
        logger.info("🧬 Lifecycle yielding to high-priority task (mission building)")
        return None

    for attempt in range(1, retries + 1):
        try:
            data = await call_ollama(
                payload={
                    "model": ollama_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_predict": num_predict, "think": True, "num_ctx": num_ctx},
                },
                timeout=timeout,
                caller="npc_lifecycle",
                force=_lifecycle_force,
            )
            break  # success — exit retry loop
        except OllamaBusyError:
            if attempt < retries:
                logger.info(f"🧬 Ollama busy (attempt {attempt}/{retries}), retrying in 5s…")
                await asyncio.sleep(5)
                continue
            logger.warning("🧬 Ollama busy after all retries — skipping")
            return None
        except Exception as e:
            if attempt < retries:
                logger.info(f"🧬 _generate error attempt {attempt}/{retries} ({type(e).__name__}), retrying in 5s…")
                await asyncio.sleep(5)
                continue
            logger.warning(f"🧬 npc_lifecycle _generate error: {type(e).__name__}: {e}")
            return None
    else:
        return None

    text = ""
    if isinstance(data, dict):
        msg = data.get("message", {})
        if isinstance(msg, dict):
            text = msg.get("content", "").strip()

    # Strip qwen3 thinking blocks before any processing
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    lines = text.splitlines()
    skip = ("sure", "here's", "here is", "as requested", "certainly",
            "of course", "i hope", "below is", "absolutely")
    while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
        lines.pop(0)
    return "\n".join(lines).strip() or None


# ---------------------------------------------------------------------------
# World lore reference
# ---------------------------------------------------------------------------

_LORE = """\
SETTING: The Undercity — a vast city under a Dome around the Tower of Last Chance.
Rifts tear reality constantly. Adventurers are an economic class. Gods harvest heroic souls.
The city has sunny plazas, neon-lit markets, grim warrens, and everything in between.
MAJOR FACTIONS: Iron Fang Consortium (Serrik Dhal -- orthodox relics + infrastructure) and its breakaway rival the Iron Fang Syndicate (Sera Voss -- rackets + stock manipulation), now openly at civil war; Argent Blades, Wardens of Ash, Serpent Choir,
Obsidian Lotus, Glass Sigil, Patchwork Saints, Adventurers Guild, Guild of Ashen Scrolls,
Tower Authority, Wizards Tower, Leaden Crown, Brother Thane's Cult.
MEGA-GUILDS (big corporate employers): Flying Fleet, Ironworks Combine, Crystal Lens Syndicate,
Tidecrest Exchange, Hearthwall Builders, Aurelius Medicant, The Long Plate, Silkthread Market,
Deepvein Extractors, Arclight Engineers, Wayfarer's Congress, Clearwater Authority,
The Grand Register, Brightfire Entertainers, Thornwall Security, Ashcraft Reclamation,
Goldenleaf Hospitality, Mirrorgate Communications, Spellwright Collective,
The Stonecrown Council, Verdant Gardens, Irondraft Logistics, The Polished Seal, Runemark Academy.
Guild NPCs hold corporate titles: Contracted Operative up through Guild Executive.
Jobs come and go — NPCs get hired, promoted, fired, or poached by rival guilds.
TONE: Cyberpunk-fantasy mix. Specific and grounded. Match the district wealth tier.\
"""


# ---------------------------------------------------------------------------
# Home district logic
# ---------------------------------------------------------------------------

# Faction -> tiered district lists: index 0 = elite, 1 = senior, 2 = standard, 3 = junior
_FACTION_DISTRICTS = {
    "Iron Fang Consortium": [
        ["Markets Infinite"],              # elite (Floor Boss / Underboss / Guildmaster)
        ["Markets Infinite", "Hearthstone District"],  # senior (Senior Agent)
        ["Markets Infinite", "Coppergate"],            # standard (Acquisition Agent)
        ["Ironworks", "Shantytown Heights"],            # junior (Street Runner)
    ],
    "Iron Fang Syndicate": [
        ["Markets Infinite"],                          # elite (Capo / Underboss / Guildmaster)
        ["Markets Infinite", "Coppergate"],            # senior (Enforcer)
        ["Markets Infinite", "Ironworks"],             # standard (Collector / Earner)
        ["Shantytown Heights", "Ironworks"],            # junior (Runner)
    ],
    "Argent Blades": [
        ["Guild Spires"],
        ["Guild Spires", "Hearthstone District"],
        ["Hearthstone District", "Coppergate"],
        ["Coppergate", "Ember Ward"],
    ],
    "Wardens of Ash": [
        ["Outer Wall"],
        ["Outer Wall", "Ember Ward"],
        ["Outer Wall", "Ember Ward"],
        ["Outer Wall", "Shantytown Heights"],
    ],
    "Serpent Choir": [
        ["Sanctum Quarter"],
        ["Sanctum Quarter", "Temple Row"],
        ["Temple Row"],
        ["Temple Row", "Cult Corners"],
    ],
    "Obsidian Lotus": [
        ["Duskhollow"],
        ["Duskhollow", "Neon Row"],
        ["Neon Row", "Duskhollow"],
        ["Neon Row", "Collapsed Plaza"],
    ],
    "Glass Sigil": [
        ["Archive Row"],
        ["Archive Row", "Academy Heights"],
        ["Archive Row", "Artisan Quarter"],
        ["Artisan Quarter", "Coppergate"],
    ],
    "Patchwork Saints": [
        ["Ember Ward"],
        ["Ember Ward", "Shantytown Heights"],
        ["Shantytown Heights", "Ember Ward"],
        ["Shantytown Heights", "Collapsed Plaza"],
    ],
    "Adventurers Guild": [
        ["Guild Spires"],
        ["Guild Spires", "Hearthstone District"],
        ["Hearthstone District", "Coppergate"],
        ["Coppergate", "Ember Ward"],
    ],
    "Guild of Ashen Scrolls": [
        ["Archive Row"],
        ["Archive Row", "Artisan Quarter"],
        ["Artisan Quarter"],
        ["Artisan Quarter", "Coppergate"],
    ],
    "Tower Authority": [
        ["Grand Forum"],
        ["Grand Forum", "Guild Spires"],
        ["Hearthstone District", "Coppergate"],
        ["Coppergate", "Ember Ward"],
    ],
    "Independent": [
        ["Grand Forum", "Floating Bazaar"],
        ["Cobbleway Market", "Neon Row"],
        ["Hearthstone District", "Coppergate"],
        ["Ember Ward", "Shantytown Heights"],
    ],
    "Brother Thane's Cult": [
        ["Cult Corners"],
        ["Cult Corners", "Collapsed Plaza"],
        ["Collapsed Plaza", "Cult Corners"],
        ["Collapsed Plaza", "Shantytown Heights"],
    ],
    "Wizards Tower": [
        ["Academy Heights"],
        ["Academy Heights"],
        ["Academy Heights", "Hearthstone District"],
        ["Academy Heights", "Coppergate"],
    ],
}

# Rank keywords mapped to prestige tier index (0=elite, 1=senior, 2=standard, 3=junior)
_RANK_TIER_MAP = {
    0: {  # elite
        "leader", "guildmaster", "director", "archmaster", "high apostle", "archmage",
        "grand archivist", "commander", "the widow", "thane", "head archivist",
        "shadow director", "magister",
    },
    1: {  # senior
        "captain", "lieutenant", "senior", "master", "elder", "vanguard",
        "champion", "underboss", "high scribe", "coordinator", "sigil master",
        "field captain", "archivist first class", "senior officer", "second",
        "specialist", "handler",
    },
    2: {  # standard
        "member", "agent", "soldier", "archivist", "mage", "blade",
        "warden", "saint", "mediator", "operative", "scribe", "researcher",
        "floor boss", "sergeant", "field lead", "acquisition agent", "contract scribe",
        "compliance officer", "city legend", "respected freelance",
        "archivist second class", "senior blade",
    },
    3: {  # junior
        "junior", "prospect", "initiate", "apprentice", "recruit", "volunteer",
        "ghost", "petitioner", "follower", "devoted", "unranked",
        "street runner", "street level", "known operator",
        "compliance intern", "journeyman", "f-rank", "e-rank", "d-rank",
    },
}


def _rank_to_tier(rank: str) -> int:
    """Map a rank string to a prestige tier (0=elite, 1=senior, 2=standard, 3=junior)."""
    rank_lower = rank.lower()
    for tier, keywords in _RANK_TIER_MAP.items():
        for kw in keywords:
            if kw in rank_lower:
                return tier
    # Default to standard if no match
    return 2


def get_home_district(faction: str, rank: str, species: str = "") -> str:
    """
    Return the most logical home district for an NPC based on faction, rank, and species.

    Species overrides:
    - undead / shade / revenant -> Duskhollow
    - golem / construct -> Scrapworks
    """
    species_lower = species.lower()
    if any(k in species_lower for k in ("undead", "shade", "revenant")):
        return "Duskhollow"
    if any(k in species_lower for k in ("golem", "construct")):
        return "Scrapworks"

    tier = _rank_to_tier(rank)
    district_options = _FACTION_DISTRICTS.get(faction, [
        ["Grand Forum"],
        ["Cobbleway Market"],
        ["Hearthstone District"],
        ["Ember Ward"],
    ])

    # Clamp tier index to available options
    tier = min(tier, len(district_options) - 1)
    choices = district_options[tier]
    return random.choice(choices)


# ---------------------------------------------------------------------------
# Generate a brand new NPC
# ---------------------------------------------------------------------------

async def generate_new_npc(existing_npcs: List[dict], faction_override: Optional[str] = None) -> Optional[dict]:
    faction  = faction_override or random.choice(FACTIONS)
    ranks    = _ranks_for_faction(faction)
    rank     = ranks[random.randint(0, min(2, len(ranks) - 1))]
    species  = random.choice(SPECIES_LIST)

    # Determine home district based on faction, rank, and species
    home_district = get_home_district(faction, rank, species)

    existing_names = [n.get("name", "") for n in existing_npcs]
    names_block    = ", ".join(existing_names[-20:]) if existing_names else "none yet"

    prompt = f"""{_LORE}

Existing NPC names (do NOT reuse these): {names_block}

Generate ONE new NPC for the Undercity. They should feel like a real person, not a plot device.
Rank-and-file level — not a faction leader, not a legendary hero.

Required faction: {faction}
Required rank: {rank}
Required species: {species}

Output ONLY a JSON object with these exact keys, nothing else:
{{
  "name": "Full name",
  "faction": "{faction}",
  "rank": "{rank}",
  "species": "{species}",
  "age": "number or range like 30s",
  "appearance": "2 sentences — specific physical details, how they carry themselves, one distinctive visual mark",
  "location": "specific district and sub-location in the city",
  "home_district": "specific district where they live",
  "motivation": "2 sentences — what they actually want and the real reason why",
  "role": "1 sentence — what they do day to day in the city",
  "equipment": "weapons they carry and armour or clothing type — faction-appropriate and specific",
  "style": "1 sentence — their visual style, how they're immediately recognizable in a crowd",
  "secret": "1-2 sentences — something hidden that could change everything if revealed",
  "relationships": "1-2 sentences — notable connections to other people or factions",
  "oracle_notes": "1-2 sentences — what the Oracle would sense about this person beyond the obvious",
  "quote": "1 sentence in their own voice — something they'd actually say on the street or at work. Specific to this person, not generic Undercity wisdom. No quotation marks."
}}

RULES:
- Be specific. Invent a real name, real location, real secret.
- Equipment and style must fit their faction ({faction}) and rank ({rank}).
- Secret should be genuinely interesting — hidden identity, crime, loyalty, supernatural fact.
- home_district should be "{home_district}" (their residential neighbourhood — can differ from work location).
- Do NOT output anything except the JSON object.
- Do NOT use markdown code fences."""

    text = await _generate(prompt, timeout=600.0, num_predict=2500, retries=2)
    if not text:
        return None

    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

    data = None

    # 1. Try clean parse
    try:
        data = json.loads(text)
    except Exception:
        pass

    # 2. Try extracting a complete {...} block
    if data is None:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except Exception:
                pass

    # 3. Truncation recovery — JSON was cut off mid-string.
    #    Find the last fully-completed key-value pair and close the object.
    if data is None:
        obj_start = text.find("{")
        if obj_start >= 0:
            partial = text[obj_start:]
            # Try appending progressively heavier closers
            for closer in ('"}', '"', '}'):
                candidate = partial.rstrip().rstrip(',') + closer + "}"
                try:
                    recovered = json.loads(candidate)
                    if isinstance(recovered, dict) and recovered.get("name"):
                        data = recovered
                        logger.info(
                            f"🧬 NPC JSON was truncated — recovered partial record for "
                            f"\"{recovered.get('name','?')}\" (missing fields will use defaults)"
                        )
                        break
                except Exception:
                    pass

        if data is None:
            logger.warning(f"🧬 NPC generation: could not parse JSON:\n{text[:300]}")
            return None

    return {
        "name":             data.get("name", "Unknown"),
        "faction":          data.get("faction", faction),
        "rank":             data.get("rank", rank),
        "species":          data.get("species", species),
        "age":              str(data.get("age", "unknown")),
        "appearance":       data.get("appearance", ""),
        "location":         data.get("location", ""),
        "home_district":    data.get("home_district", home_district),
        "motivation":       data.get("motivation", ""),
        "role":             data.get("role", ""),
        "equipment":        data.get("equipment", ""),
        "style":            data.get("style", ""),
        "secret":           data.get("secret", ""),
        "relationships":    data.get("relationships", ""),
        "oracle_notes":     data.get("oracle_notes", ""),
        "quote":            data.get("quote", ""),
        "status":           "alive",
        "stats":            {},   # filled in after appearance profile runs
        "sd_prompt":        "",   # filled in after appearance profile runs
        "revealed_secrets": [],
        "history":          [f"[{datetime.now().strftime('%Y-%m-%d')}] Introduced to the Undercity roster."],
        "created_at":       datetime.now().isoformat(),
        "last_event_at":    datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Apply a lifecycle event to an existing NPC
# ---------------------------------------------------------------------------

async def apply_npc_event(npc: dict, all_npcs: List[dict]) -> tuple:
    # ── Injured NPCs: resolve before anything else ────────────────────────────
    # 90% recover, 10% die. Either way generate a bulletin explaining the outcome.
    if npc.get("status") == "injured":
        event = "injury_recovery" if random.random() < 0.90 else "injury_death"

    # ── Dead NPCs: only resurrection (5% chance), otherwise skip ─────────────
    elif npc.get("status") == "dead":
        if random.random() < 0.05:
            event = "resurrection"
        else:
            return None, None

    else:
        event = random.choices(NPC_EVENTS, weights=EVENT_WEIGHTS, k=1)[0]

        # Protect faction leaders from random death — they can only die via DM action
        if event == "death" and is_faction_leader(npc.get("name", "")):
            logger.info(f"\U0001f451 Protected leader {npc.get('name')} from random death — rerolling event")
            event = random.choice(["promotion", "public_incident", "new_secret", "revelation"])

        # Party-bound NPCs (npcs.party_name) live their career through their crew:
        # party_lifecycle drives contracts/splits/merges, so ambient faction-career
        # events would contradict it. Reroll those into personal events.
        _CREW_CAREER_EVENTS = {"promotion", "demotion", "faction_defection",
                               "guild_hire", "guild_promotion", "guild_fired", "guild_poached"}
        if npc.get("party_name") and event in _CREW_CAREER_EVENTS:
            event = random.choice(["revelation", "new_secret", "public_incident",
                                   "alliance", "betrayal", "daily_generated"])

    name    = npc.get("name", "Unknown")
    faction = npc.get("faction", "Independent")
    rank    = npc.get("rank", "Member")
    species = npc.get("species", "Human")
    today   = datetime.now().strftime("%Y-%m-%d")
    announcement = None

    if event == "promotion":
        ranks       = _ranks_for_faction(faction)
        current_idx = ranks.index(rank) if rank in ranks else 0
        if current_idx < len(ranks) - 1:
            new_rank    = ranks[current_idx + 1]
            npc["rank"] = new_rank
            _hist(npc, f"[{today}] Promoted from {rank} to {new_rank} within {faction}.")
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {species}, {faction}.\n"
                f"Event: Promoted from {rank} to {new_rank}.\n"
                f"Write a 2-3 line in-character Undercity bulletin. Gritty, specific, real consequences implied.\n"
                f"No preamble. Output only the bulletin."
            )

    elif event == "demotion":
        ranks       = _ranks_for_faction(faction)
        current_idx = ranks.index(rank) if rank in ranks else 0
        if current_idx > 0:
            new_rank    = ranks[current_idx - 1]
            npc["rank"] = new_rank
            _hist(npc, f"[{today}] Demoted from {rank} to {new_rank} within {faction}.")
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {faction}.\n"
                f"Event: Demoted from {rank} to {new_rank}. Imply something went wrong.\n"
                f"Write a 2-3 line Undercity bulletin. No preamble. Output only the bulletin."
            )

    elif event == "faction_defection":
        # Can defect to a major faction OR a guild — whichever pays or believes more
        all_targets = FACTIONS + _get_guild_factions()
        new_faction    = random.choice([f for f in all_targets if f != faction])
        new_rank       = _ranks_for_faction(new_faction)[0]
        old_faction    = faction
        npc["faction"] = new_faction
        npc["rank"]    = new_rank
        _hist(npc, f"[{today}] Defected from {old_faction} to {new_faction} (rank: {new_rank}).")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}.\n"
            f"Event: Defected from {old_faction} to {new_faction}. Now ranked {new_rank}.\n"
            f"Write a 2-3 line Undercity bulletin. Imply motivation without explaining fully.\n"
            f"No preamble. Output only the bulletin."
        )

    elif event == "guild_hire":
        # Independent or faction NPC gets a corporate contract offer
        guilds = _get_guild_factions()
        if not guilds:
            return None, None
        new_guild   = random.choice([g for g in guilds if g != faction] or guilds)
        new_rank    = GUILD_RANKS[0]
        old_faction = faction
        npc["faction"] = new_guild
        npc["rank"]    = new_rank
        _hist(npc, f"[{today}] Hired by {new_guild} from {old_faction} as {new_rank}.")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {species}. Previously: {old_faction}.\n"
            f"Event: Contracted by {new_guild} as {new_rank}.\n"
            f"Write a 2-3 line Undercity bulletin — new hire notice, corporate tone mixed with city grit.\n"
            f"No preamble. Output only the bulletin."
        )

    elif event == "guild_promotion":
        # Existing guild NPC moves up the corporate ladder
        if "(Guild)" not in (faction or ""):
            return None, None
        ranks       = GUILD_RANKS
        current_idx = ranks.index(rank) if rank in ranks else 0
        if current_idx >= len(ranks) - 1:
            return None, None
        new_rank    = ranks[current_idx + 1]
        npc["rank"] = new_rank
        _hist(npc, f"[{today}] Promoted within {faction}: {rank} -> {new_rank}.")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {species}, {faction}.\n"
            f"Event: Internal promotion from {rank} to {new_rank}.\n"
            f"Write a 2-3 line Undercity bulletin — corporate announcement with implied city politics.\n"
            f"No preamble. Output only the bulletin."
        )

    elif event == "guild_fired":
        # Terminated from guild — could be voluntary, forced, or permanently 'resolved'
        if "(Guild)" not in (faction or ""):
            return None, None
        guilds = _get_guild_factions()
        termination_type = random.choice(["resigned", "terminated", "disappeared quietly"])
        old_guild   = faction
        npc["faction"] = "Independent"
        npc["rank"]    = FACTION_RANKS["Independent"][0]
        _hist(npc, f"[{today}] {termination_type.capitalize()} from {old_guild}. Now independent.")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {species}.\n"
            f"Event: {termination_type.capitalize()} from {old_guild}. Now at street level.\n"
            f"Write a 2-3 line Undercity bulletin. Tone matches termination type — resigned is neutral, "
            f"terminated implies conflict, disappeared quietly implies something darker.\n"
            f"No preamble. Output only the bulletin."
        )

    elif event == "guild_poached":
        # A rival guild makes a better offer — NPC jumps ship mid-contract
        guilds = _get_guild_factions()
        if "(Guild)" not in (faction or "") or not guilds:
            return None, None
        rival_guild = random.choice([g for g in guilds if g != faction] or guilds)
        old_guild   = faction
        # Poaching usually comes with a rank bump
        ranks       = GUILD_RANKS
        current_idx = ranks.index(rank) if rank in ranks else 0
        new_rank    = ranks[min(current_idx + 1, len(ranks) - 1)]
        npc["faction"] = rival_guild
        npc["rank"]    = new_rank
        _hist(npc, f"[{today}] Poached from {old_guild} by {rival_guild} at {new_rank}.")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {species}.\n"
            f"Event: Poached from {old_guild} by {rival_guild}. New rank: {new_rank}. Better pay implied.\n"
            f"Write a 2-3 line Undercity bulletin — inter-guild rivalry, corporate poaching drama.\n"
            f"No preamble. Output only the bulletin."
        )

    elif event == "revelation":
        secret = npc.get("secret", "")
        npc_id = npc.get("_db_id") or npc.get("id")
        if secret and npc_id:
            existing = get_revealed_secrets(int(npc_id))
            if secret not in existing:
                add_revealed_secret(int(npc_id), secret)
                npc.setdefault("revealed_secrets", []).append(secret)
                npc["secret"] = ""
                _hist(npc, f"[{today}] Secret revealed: {secret[:60]}...")
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
                f"Their secret was: {secret}\n"
                f"Write a 2-3 line Undercity bulletin announcing the revelation as city gossip.\n"
                f"Do NOT just restate the secret. No preamble. Output only the bulletin."
            )

    elif event == "death":
        npc["status"] = "dead"
        _hist(npc, f"[{today}] Killed. Faction: {faction}, Rank: {rank}.")
        _death_cause = random.choice([  # noqa: saved to npc["death_cause"] below
            # Faction violence
            "assassinated by a faction rival — clean job, no witnesses",
            "killed in a turf war between two factions over a market lane",
            "executed by their own faction for a betrayal, real or suspected",
            "found in the canal with weights on their ankles — Iron Fang message",
            "taken out by an Obsidian Lotus contract, cause of payment unknown",
            "throat cut during a faction meeting gone wrong",
            "disappeared after crossing the wrong underboss — body found three days later",
            # Street / criminal violence
            "killed in a street brawl that got out of hand — wrong weapon drawn",
            "shot dead during an armed robbery of a market stall",
            "stabbed in a debt dispute that escalated beyond anyone's intention",
            "beaten to death by a crew who mistook them for someone else",
            "killed by a bounty hunter acting on a contract that wasn't even accurate",
            # Transport and industrial
            "run down by a cargo hauler at a Warrens crossroads, driver fled",
            "fell under a tube train at the outer platform during rush hour",
            "crushed in a Scrapworks crane accident — safety record already poor",
            "killed in a Scrapworks explosion caused by improperly stored fuel",
            "fell from the upper level of a Spires construction site",
            "buried in a Warrens structural collapse they were warned about",
            # Dungeon / mission
            "didn't come back from a dungeon contract — party returned without them",
            "killed inside a Rift incursion zone, remains partially recovered",
            "monster encounter on a dungeon run — outmatched and alone",
            "trap in an unexplored sublevel — no one saw it trigger",
            # Occupational / consequence
            "poisoned — slow enough that they didn't know until too late",
            "kneecapped and left in the cold, bled out before anyone found them",
            "died in custody after Warden arrest — official cause listed as natural",
            "overdose — deliberate or otherwise, city isn't sure",
            # Rift (rare, not default)
            "killed in a full Rift breach event in the Outer Wall district",
            "consumed by a Rift tear — no body, just a scorch mark",
        ])
        npc["death_cause"] = _death_cause
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Cause of death: {_death_cause}.\n"
            f"Write a 2-3 line Undercity death notice. Terse. Real. Use the specific cause above.\n"
            f"Do NOT default to 'Rift exposure' or generic fantasy causes.\n"
            f"No preamble. Output only the notice."
        )

    # --- INJURY RECOVERY ---
    elif event == "injury_recovery":
        npc["status"] = "alive"
        _hist(npc, f"[{today}] Recovered from injuries.")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Event: Was injured. Has now recovered and is back on their feet.\n"
            f"Write a 2-3 line Undercity bulletin. Terse, specific — what happened, how they got through it.\n"
            f"Imply the experience may have changed them. No preamble. Output only the bulletin."
        )

    # --- INJURY -> DEATH ---
    elif event == "injury_death":
        npc["status"] = "dead"
        _hist(npc, f"[{today}] Succumbed to injuries. Faction: {faction}, Rank: {rank}.")
        _complication = random.choice([
            "infection set in and Patchwork Saints couldn't hold it",
            "internal bleeding that wasn't caught in time",
            "lost too much blood before help arrived",
            "the wound was deeper than it looked — organ damage",
            "no credits for a proper healer, Saints clinic did what they could",
            "fever took hold on the third day, didn't break",
            "complications from surgery in an underfunded Warrens clinic",
            "second attack on them in the clinic finished the job",
            "they refused treatment until it was too late",
            "head injury that seemed minor turned out not to be",
        ])
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Event: Was injured and did not recover. Complication: {_complication}.\n"
            f"Write a 2-3 line Undercity death notice. Terse. Real.\n"
            f"Imply the complication — don't write 'Rift exposure' as the cause.\n"
            f"No preamble. Output only the notice."
        )

    elif event == "resurrection":
        # Three return paths: 40% Tower Fund Me (legit), 30% doppelganger, 30% undead
        _return_roll = random.random()
        if _return_roll < 0.40:
            # Legitimate Tower Fund Me resurrection
            npc["status"] = "alive"
            _hist(npc, f"[{today}] Returned from death via Tower Fund Me. Alive again, for a price.")
            new_secret = await _generate(
                f"NPC {name} was crowdfunded back to life via the Tower's resurrection service.\n"
                f"Generate ONE secret about what they had to give up or what changed in them.\n"
                f"Output ONLY the secret in 1-2 sentences. No preamble."
            )
            if new_secret:
                npc["secret"] = new_secret
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, previously of {faction}.\n"
                f"Event: Has returned via a Tower Fund Me — publicly funded resurrection through the Tower's services.\n"
                f"Write a 2-3 line Undercity bulletin. Bittersweet. Debts owed. Something is different.\n"
                f"No preamble. Output only the bulletin."
            )
        elif _return_roll < 0.70:
            # Doppelganger — something is wearing their face
            npc["status"] = "doppelganger"
            _hist(npc, f"[{today}] A doppelganger wearing {name}'s face has appeared. The original is still dead.")
            new_secret = await _generate(
                f"Something is wearing the face of {name}, {rank} of {faction}, who died in the Undercity.\n"
                f"Generate ONE secret about what this imposter wants or what it is hiding.\n"
                f"Output ONLY the secret in 1-2 sentences. No preamble."
            )
            if new_secret:
                npc["secret"] = new_secret
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {rank} of {faction} — confirmed dead.\n"
                f"Event: Someone matching their description has been seen alive. Multiple witnesses. Something is wrong.\n"
                f"Write a 2-3 line Undercity rumour bulletin. Disturbing. Wrong details. Nobody can explain it.\n"
                f"No preamble. Output only the bulletin."
            )
        else:
            # Undead return — reanimated, wrong
            npc["status"] = "undead"
            _hist(npc, f"[{today}] Returned as undead. Reanimated. Not the same.")
            new_secret = await _generate(
                f"NPC {name} has returned as an undead form in the Undercity.\n"
                f"Generate ONE secret about what drives them now — what fragment of memory or purpose survived.\n"
                f"Output ONLY the secret in 1-2 sentences. No preamble."
            )
            if new_secret:
                npc["secret"] = new_secret
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {rank} of {faction} — died, confirmed.\n"
                f"Event: Has returned — but wrong. Moving wrong. Speaking wrong. Looking through people, not at them.\n"
                f"Write a 2-3 line Undercity bulletin. Horror-adjacent. Real fear in the district.\n"
                f"No preamble. Output only the bulletin."
            )

    elif event == "alliance":
        candidates = [n for n in all_npcs if n.get("name") != name and n.get("status") in ("alive","undead","doppelganger")]
        if candidates:
            ally         = random.choice(candidates)
            ally_name    = ally.get("name", "Unknown")
            ally_faction = ally.get("faction", "Unknown")
            _hist(npc, f"[{today}] Formed alliance with {ally_name} ({ally_faction}).")
            npc["relationships"] = str(npc.get("relationships") or "") + f" | Alliance with {ally_name} ({ally_faction})."
            announcement = await _generate(
                f"{_LORE}\nNPC: {name} ({faction}) has formed a notable alliance with {ally_name} ({ally_faction}).\n"
                f"Write a 2-3 line Undercity bulletin. What does it mean for the balance of power?\n"
                f"No preamble. Output only the bulletin."
            )

    elif event == "betrayal":
        _hist(npc, f"[{today}] Committed a significant betrayal within {faction}.")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Event: Has betrayed someone within their faction. Details not fully known.\n"
            f"Write a 2-3 line Undercity rumour bulletin. Something happened. Nobody saying exactly what.\n"
            f"No preamble. Output only the bulletin."
        )

    elif event == "new_secret":
        new_secret = await _generate(
            f"NPC {name} is a {rank} in {faction} in a dark fantasy underground city.\n"
            f"Generate ONE new secret — hidden identity, unexpected loyalty, supernatural fact, crime.\n"
            f"Example: 'Is secretly a werecoyote who has not yet transformed in the Undercity.'\n"
            f"Output ONLY the secret in 1-2 sentences. No preamble."
        )
        if new_secret:
            npc["secret"] = new_secret
            _hist(npc, f"[{today}] New secret acquired.")
        return None, "new_secret"  # no public announcement

    elif event == "public_incident":
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Event: Involved in a public incident — confrontation, accident, spectacle, or arrest.\n"
            f"Write a 2-3 line Undercity bulletin. Specific. Atmospheric.\n"
            f"No preamble. Output only the bulletin."
        )
        if announcement:
            _hist(npc, f"[{today}] Public incident.")

    elif event == "daily_generated":
        scenario = _get_random_daily_event()
        if scenario:
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {species}, {faction}, {rank}.\n"
                f"Location: {npc.get('location', 'the Undercity')}.\n"
                f"Role: {npc.get('role', 'active in their faction')}.\n"
                f"TODAY'S EVENT: {scenario}\n\n"
                f"Write a 2-3 line Undercity bulletin about this event happening to {name}.\n"
                f"Ground it in their specific faction, rank, and role. Make it feel personal.\n"
                f"Tone: gritty, specific, consequential.\n"
                f"No preamble. Output only the bulletin."
            )
            if announcement:
                _hist(npc, f"[{today}] {scenario[:80]}{'...' if len(scenario) > 80 else ''}")
                logger.info(f"🧬 Daily event for {name}: {scenario[:60]}")
        else:
            # No daily events available — fall back to public incident
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
                f"Event: Involved in a public incident.\n"
                f"Write a 2-3 line Undercity bulletin. No preamble. Output only the bulletin."
            )
            if announcement:
                _hist(npc, f"[{today}] Public incident.")

    npc["last_event_at"] = datetime.now().isoformat()

    # If the NPC just died, move them to the graveyard
    if npc.get("status") == "dead":
        _move_to_graveyard(npc, all_npcs)

    return announcement, event


# ---------------------------------------------------------------------------
# Seed from static npc_roster.txt (first run only)
# ---------------------------------------------------------------------------

def _seed_from_txt() -> List[dict]:
    if not NPC_TXT_FILE.exists():
        return []
    header = NPC_TXT_FILE.read_text(encoding="utf-8", errors="ignore")[:200]
    if "Auto-generated" in header:
        return []
    npcs = []
    text = NPC_TXT_FILE.read_text(encoding="utf-8", errors="ignore")
    for block in re.split(r"---NPC---", text):
        block = block.strip()
        if not block or "---END NPC---" not in block:
            continue
        block = block.split("---END NPC---")[0].strip()
        npc = {}
        for line in block.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                npc[key.strip().lower().replace(" ", "_")] = value.strip()
        if "name" not in npc:
            continue
        npcs.append({
            "name":             npc.get("name", "Unknown"),
            "faction":          npc.get("faction", "Independent"),
            "rank":             npc.get("rank", "Member"),
            "species":          npc.get("species", "Human"),
            "age":              npc.get("age", "unknown"),
            "appearance":       npc.get("appearance", ""),
            "location":         npc.get("location", ""),
            "motivation":       npc.get("motivation", ""),
            "role":             npc.get("role", ""),
            "secret":           npc.get("secret", ""),
            "relationships":    npc.get("relationships", ""),
            "oracle_notes":     npc.get("oracle_notes", ""),
            "status":           "alive",
            "revealed_secrets": [],
            "history":          [f"[{datetime.now().strftime('%Y-%m-%d')}] Entered roster from static file."],
            "created_at":       datetime.now().isoformat(),
            "last_event_at":    datetime.now().isoformat(),
        })
    return npcs


# ---------------------------------------------------------------------------
# Quote generation — backfill existing NPCs that pre-date the quote field
# ---------------------------------------------------------------------------

async def _generate_npc_quote(npc: dict) -> str:
    """
    Generate a unique in-character quote for one NPC based on their full
    context. Returns the quote string, or — on failure.
    """
    name       = npc.get("name", "Unknown")
    faction    = npc.get("faction", "Independent")
    rank       = npc.get("rank", "Member")
    role       = npc.get("role", "")
    motivation = npc.get("motivation", "")
    appearance = npc.get("description", "") or npc.get("appearance", "")
    species    = npc.get("species", "Human")

    prompt = f"""Write ONE in-character quote for this NPC from the Undercity — a sealed dome city mixing dark fantasy and cyberpunk.

NPC:
- Name: {name}
- Faction: {faction} ({rank})
- Species: {species}
- Role: {role}
- Appearance: {appearance[:120] if appearance else 'not described'}
- What they want: {motivation[:120] if motivation else 'not known'}

RULES:
- Exactly 1 sentence. First person. Their actual voice — gruff, formal, weary, sharp, devout, or sly depending on who they are.
- Specific to this character. Not generic Undercity wisdom that any NPC could say.
- No quotation marks. No preamble. Output the sentence only."""

    text = await _generate(prompt, timeout=90.0, num_predict=120, retries=1)
    if not text:
        return ""
    # Strip any accidental quotation marks or leading/trailing noise
    quote = text.strip().strip('"').strip("'").strip()
    # If the model returned multiple sentences take only the first
    first = re.split(r'(?<=[.!?])\s', quote, maxsplit=1)[0].strip()
    return first


async def _backfill_npc_quotes(npcs: list, max_per_run: int = 3) -> int:
    """
    Generate and persist quotes for alive NPCs that don't have one yet.
    Capped at max_per_run per lifecycle cycle so it doesn't hammer Ollama.
    Returns the number of quotes generated.
    """
    from src.resource_cop import wait_for_ollama_turn
    missing = [n for n in npcs if not n.get("quote") and n.get("status") == "alive"]
    if not missing:
        return 0
    logger.info(f"🗣️ Backfilling quotes for {min(len(missing), max_per_run)}/{len(missing)} NPCs without one")
    generated = 0
    for npc in missing[:max_per_run]:
        decision = await wait_for_ollama_turn("npc_quote_backfill", track="quick")
        if not decision.run_now:
            logger.info(f"🗣️ Ollama busy — stopping quote backfill at {generated} (will resume next cycle)")
            break
        quote = await _generate_npc_quote(npc)
        if quote:
            npc["quote"] = quote
            _save_npc(npc)
            logger.info(f"🗣️ Quote saved for {npc['name']}: {quote[:60]}…")
            generated += 1
    return generated


# ---------------------------------------------------------------------------
# Main daily lifecycle tick
# ---------------------------------------------------------------------------

async def run_daily_lifecycle(channel) -> bool:
    """Run one NPC lifecycle cycle.

    Returns False when the cycle was deferred because Ollama was busy, so the
    caller can retry soon instead of losing the daily lifecycle window.
    """
    global _lifecycle_force
    from src.ollama_busy import is_available, get_busy_reason, mark_busy, mark_available

    if not is_available():
        logger.info(f"🧬 Ollama busy ({get_busy_reason()}) — skipping lifecycle cycle")
        return False

    mark_busy("npc lifecycle cycle")
    _lifecycle_force = True
    try:
        await _lifecycle_cycle(channel)
    except Exception as e:
        logger.exception(f"🧬 Lifecycle cycle error — cleanup still running: {e}")
    finally:
        _lifecycle_force = False
        mark_available()
    return True


async def _lifecycle_cycle(channel) -> None:
    """Inner lifecycle body — always called inside run_daily_lifecycle's try/finally."""
    import discord

    # Generate fresh daily event scenarios if stale
    try:
        await refresh_daily_events_if_needed()
    except Exception as e:
        logger.warning(f"🧬 Daily event refresh failed: {e}")

    # Seed on first run
    npcs = _load_npcs()

    # Sweep any dead NPCs still in the active roster to the graveyard.
    # On first run after this update, this catches the 5 existing dead NPCs.
    # After that, deaths are moved instantly by apply_npc_event.
    swept = _sweep_dead_to_graveyard(npcs)
    if swept:
        npcs = _load_npcs()  # reload — sweep modified and saved the list

    if not npcs:
        logger.info("🧬 Seeding NPC roster from static file...")
        npcs = _seed_from_txt()
        if npcs:
            _save_npcs(npcs)
            logger.info(f"🧬 Seeded {len(npcs)} NPCs from static roster.")

    # Generate 1 new NPC
    new_npc = await generate_new_npc(npcs)
    if not new_npc:
        logger.warning("🧬 generate_new_npc returned None — Ollama may be unavailable")
    if new_npc:
        npcs.append(new_npc)
        _save_npcs(npcs)
        logger.info(f"🧬 New NPC: {new_npc['name']} ({new_npc['faction']}, {new_npc['rank']})")

        # Auto-generate appearance profile (stats, equipment, style, SD prompt)
        # and merge it back into the NPC's data_json so it's visible everywhere.
        _app_profile: dict = {}
        try:
            from src.npc_appearance import _generate_npc_profile, _save_npc_appearance, get_all_sd_prompts, NPC_APP_DIR
            import json as _json
            _app_profile = await _generate_npc_profile(new_npc, force=True)
            _save_npc_appearance(new_npc["name"], _app_profile)
            # Merge stats / equipment / style back into the NPC's own record
            new_npc["stats"]     = _app_profile.get("dnd_stats", {})
            new_npc["equipment"] = _app_profile.get("equipment", {})
            new_npc["style"]     = _app_profile.get("style_note", "")
            new_npc["sd_prompt"] = _app_profile.get("sd_appearance", "")
            _save_npcs(npcs)
            # Also update flat lookup file for legacy compatibility
            logger.info(f"🎨 Appearance profile generated for new NPC: {new_npc['name']}")
        except Exception as _ae:
            logger.warning(f"🎨 Appearance profile failed for {new_npc['name']}: {_ae}")

        # Generate quote for the new NPC if the generation prompt didn't produce one
        if not new_npc.get("quote"):
            try:
                _q = await _generate_npc_quote(new_npc)
                if _q:
                    new_npc["quote"] = _q
                    _save_npc(new_npc)
                    logger.info(f"🗣️ Quote generated for new NPC {new_npc['name']}: {_q[:60]}…")
            except Exception as _qe:
                logger.warning(f"🗣️ Quote generation failed for {new_npc['name']}: {_qe}")

        # Backfill quotes for existing NPCs that pre-date this feature (3 per cycle)
        try:
            _backfilled = await _backfill_npc_quotes(npcs, max_per_run=3)
            if _backfilled:
                logger.info(f"🗣️ Backfilled {_backfilled} NPC quote(s) this cycle")
        except Exception as _be:
            logger.warning(f"🗣️ Quote backfill error: {_be}")

        # Build the intro announcement with full NPC context
        _npc_appearance  = new_npc.get("appearance", "")
        _npc_motivation  = new_npc.get("motivation", "")
        _npc_role        = new_npc.get("role", "")
        _npc_location    = new_npc.get("location", "")
        _npc_relations   = new_npc.get("relationships", "")
        _npc_equip       = _app_profile.get("equipment", {}) if _app_profile else {}
        # Fall back to the LLM-generated string field if appearance profile didn't run
        _equip_str       = new_npc.get("equipment", "")
        if _npc_equip and isinstance(_npc_equip, dict):
            _equip_line = f"Carries: {_npc_equip.get('weapons','')}, wears {_npc_equip.get('armour','')}."
        elif _equip_str:
            _equip_line = f"Equipment: {_equip_str}."
        else:
            _equip_line = ""
        _style_line      = _app_profile.get("style_note", "") if _app_profile else new_npc.get("style", "")

        intro = await _generate(
            f"{_LORE}\n\n"
            f"Write a city bulletin announcing a new person now operating in the Undercity.\n"
            f"Vary your opener — options include: 'Word is out:', 'A new face in the Undercity:', "
            f"'The city is talking about:', 'Making rounds in the {new_npc['faction']} circles:', "
            f"'Fresh blood in the {new_npc['faction']}:', or any similar gritty opening that fits.\n\n"
            f"NPC PROFILE:\n"
            f"Name: {new_npc['name']}\n"
            f"Species: {new_npc['species']}\n"
            f"Faction: {new_npc['faction']}\n"
            f"Rank: {new_npc['rank']}\n"
            f"Role: {_npc_role}\n"
            f"Location: {_npc_location}\n"
            f"Appearance: {_npc_appearance}\n"
            f"Motivation: {_npc_motivation}\n"
            f"Known connections: {_npc_relations}\n"
            f"{_equip_line}\n"
            f"Style: {_style_line}\n\n"
            f"REQUIREMENTS:\n"
            f"- 4-6 sentences. A Read More button handles overflow so be generous.\n"
            f"- First sentence: who they are and what they do day-to-day\n"
            f"- Second sentence: their faction affiliation and rank\n"
            f"- Third sentence: something distinctive — appearance, equipment, how they carry themselves\n"
            f"- Fourth+ sentences: rumours, tensions, hooks, known associates (not their secret)\n"
            f"- Gritty, specific. Reads like city gossip or a posted notice.\n"
            f"- Do NOT reveal their secret. No preamble. Output only the bulletin text."
        )
        if intro and channel:
            logger.info(f"🧬 Posting new NPC intro: {new_npc['name']}")
            try:
                _dnd   = _app_profile.get("dnd_stats", new_npc.get("stats", {}))
                _cls   = _dnd.get("class", "")
                _sub   = _dnd.get("subclass", "")
                _lv    = _dnd.get("level", "")
                _hp    = _dnd.get("HP", "")
                _ac    = _dnd.get("AC", "")
                _class_str = f"{_cls}/{_sub}" if _sub else _cls
                _level_str = f"{_class_str} {_lv}" if _cls and _lv else ""
                _statline = (
                    f"STR {_dnd.get('STR','?')} · DEX {_dnd.get('DEX','?')} · CON {_dnd.get('CON','?')}"
                    f" · INT {_dnd.get('INT','?')} · WIS {_dnd.get('WIS','?')} · CHA {_dnd.get('CHA','?')}"
                ) if _dnd.get("STR") else ""
                embed = discord.Embed(
                    title=f"👤 New Face — {new_npc['name']}",
                    description=intro,
                    color=discord.Color.teal()
                )
                embed.add_field(name="Faction", value=f"{new_npc['rank']} · {new_npc['faction']}", inline=True)
                embed.add_field(name="Species", value=new_npc["species"], inline=True)
                if _level_str:
                    embed.add_field(name="Class", value=_level_str, inline=True)
                if _npc_location:
                    embed.add_field(name="Location", value=_npc_location, inline=True)
                if _npc_equip:
                    embed.add_field(
                        name="Equipment",
                        value=f"**Weapons:** {_npc_equip.get('weapons','?')}\n**Armour:** {_npc_equip.get('armour','?')}",
                        inline=True
                    )
                if _hp and _ac:
                    embed.add_field(name="HP / AC", value=f"HP {_hp} · AC {_ac}", inline=True)
                elif _hp:
                    embed.add_field(name="HP", value=str(_hp), inline=True)
                if _statline:
                    embed.add_field(name="Stats", value=_statline, inline=False)
                try:
                    from src.expandable_bulletin import make_bulletin_view
                    _npc_view = make_bulletin_view(
                        intro, "news",
                        headline=f"New Face — {new_npc['name']}",
                        source_attribution="TNN City Desk",
                    )
                    await channel.send(embed=embed, view=_npc_view)
                except Exception:
                    await channel.send(embed=embed)
            except Exception as _de:
                logger.warning(f"🧬 Discord send failed (new NPC intro): {_de}")
        elif not intro:
            logger.warning(f"🧬 New NPC intro generation returned None — posting minimal announcement")
            if channel:
                try:
                    _fallback_embed = discord.Embed(
                        title=f"👤 New Face — {new_npc['name']}",
                        description=(
                            f"A new contact has surfaced in the Undercity. "
                            f"Details are still coming in."
                        ),
                        color=discord.Color.teal(),
                    )
                    _fallback_embed.add_field(name="Faction", value=f"{new_npc.get('rank','')} · {new_npc.get('faction','')}", inline=True)
                    _fallback_embed.add_field(name="Species", value=new_npc.get("species", "Unknown"), inline=True)
                    if new_npc.get("location"):
                        _fallback_embed.add_field(name="Location", value=new_npc["location"], inline=True)
                    await channel.send(embed=_fallback_embed)
                except Exception as _fe:
                    logger.warning(f"🧬 Fallback NPC announce failed: {_fe}")

    # Roll events for 1-3 existing NPCs
    # Include injured NPCs — they MUST resolve on the next cycle
    alive_npcs       = [n for n in npcs if n.get("status") in ("alive","undead","doppelganger")]
    injured_npcs     = [n for n in npcs if n.get("status") == "injured"]
    # Injured NPCs are always included; sample from alive for the remainder
    sample_count     = max(0, random.randint(1, 3) - len(injured_npcs))
    sampled_alive    = random.sample(alive_npcs, min(sample_count, len(alive_npcs)))
    event_candidates = injured_npcs + sampled_alive

    for npc in event_candidates:
        # Injured NPCs ALWAYS resolve — skip the cooldown check for them.
        # Alive NPCs respect the 3-day cooldown so we don't spam the same person.
        if npc.get("status") != "injured":
            last_event = npc.get("last_event_at", "")
            if last_event:
                try:
                    if (datetime.now() - datetime.fromisoformat(last_event)).days < 3:
                        continue
                except Exception:
                    pass

        announcement, event_type = await apply_npc_event(npc, npcs)
        _save_npcs(npcs)

        if announcement and channel:
            # Event-specific embed colors — each event type is visually distinct
            _EVENT_COLORS = {
                "promotion":        0x55AA44,
                "demotion":         0xBB6622,
                "faction_defection": 0x9944CC,
                "revelation":       0xCCAA33,
                "death":            0x992222,
                "injury_recovery":  0x55BB77,
                "injury_death":     0x992222,
                "resurrection":     0xAA33CC,
                "alliance":         0x3366BB,
                "betrayal":         0xCC3344,
                "public_incident":  0x667788,
                "daily_generated":  0x338899,
            }
            _EVENT_EMOJI = {
                "promotion":        "📈",
                "demotion":         "📉",
                "faction_defection": "🔄",
                "revelation":       "👁",
                "death":            "💀",
                "injury_recovery":  "💪",
                "injury_death":     "💀",
                "resurrection":     "✨",
                "alliance":         "🤝",
                "betrayal":         "🗡",
                "public_incident":  "📰",
                "daily_generated":  "🧬",
            }
            evt = event_type or "public_incident"
            color = _EVENT_COLORS.get(evt, 0x667788)
            emoji = _EVENT_EMOJI.get(evt, "📰")
            logger.info(f"🧬 Posting event ({evt}) for {npc['name']}")
            try:
                embed = discord.Embed(description=announcement, color=color)
                embed.set_footer(
                    text=f"{emoji} {npc['name']} · {npc.get('faction','?')} · {npc.get('rank','?')}"
                )
                await channel.send(embed=embed)
            except Exception as _de:
                logger.warning(f"🧬 Discord send failed (event {evt} for {npc['name']}): {_de}")

        await asyncio.sleep(5)

    # --- Daily Injury Wave: 1-2 NPCs get injured each cycle ---
    # Capped at MAX_CONCURRENT_INJURED so injuries don't pile up between reboots.
    # Separate from the main event loop — picks from alive NPCs not already processed this run.
    # Uses a 1-day cooldown (not 3) so fresh NPCs can be injured sooner.
    MAX_CONCURRENT_INJURED = 3
    currently_injured = len([n for n in npcs if n.get("status") == "injured"])
    injury_slots = max(0, MAX_CONCURRENT_INJURED - currently_injured)

    already_processed_ids = {id(n) for n in event_candidates}
    injury_pool = [
        n for n in alive_npcs
        if id(n) not in already_processed_ids
        and (
            not n.get("last_event_at")
            or (datetime.now() - datetime.fromisoformat(n["last_event_at"])).total_seconds() > 86400
        )
    ]
    random.shuffle(injury_pool)
    wave_count = min(random.randint(1, 2), injury_slots)
    injury_targets = injury_pool[:wave_count]
    today_str = datetime.now().strftime("%Y-%m-%d")

    for npc in injury_targets:
        npc["status"]        = "injured"
        npc["last_event_at"] = datetime.now().isoformat()
        _hist(npc, f"[{today_str}] Injured.")
        _save_npcs(npcs)

        _injury_cause = random.choice([
            # Street violence
            "stabbed in a street fight over a debt or territory dispute",
            "jumped by a rival faction crew in an alley, beaten badly",
            "knifed outside a Night Pits bout — wrong person, wrong moment",
            "took a bolt from a crossbow during a Crimson Alley ambush",
            "glassed in a bar fight at the Adventurer's Inn",
            "caught in crossfire between two faction crews settling a score",
            "shot with an illegal firearm during a market dispute that escalated",
            "beaten by Warden enforcers during a raid, no charges filed",
            "shanked by a contract killer — survived, barely",
            "brawl at the Arena spilled into the street, took the worst of it",
            # Transport accidents (the Undercity has vehicles)
            "hit by a cargo hauler truck barreling through a market lane",
            "struck by a delivery van running a red on a Warrens intersection",
            "fell from a moving freight cart while trying to board it",
            "clipped by a fast-moving cargo bike and thrown into a concrete pillar",
            "hit by an underground tube train — stepped too close to the platform edge",
            "knocked off a loading platform by a reversing transport truck",
            "crushed between two freight containers during a docking accident",
            "fell off the back of a moving faction vehicle during a chase",
            "struck by a runaway electric cart that lost its brakes on a ramp",
            "dragged under a slow-moving ore hauler in the Scrapworks",
            # Industrial / environmental
            "industrial accident at the Scrapworks — crane cable snapped",
            "scalded by a burst steam pipe in the maintenance tunnels",
            "fell through a rusted grate in the Warrens into the level below",
            "buried under a partial ceiling collapse in the Outer Wall sector",
            "electrical burn from an illegal junction box they were tapping",
            "caught in a Scrapworks welding explosion",
            "fell from scaffolding in the mid-construction area of a Spires tower",
            "chemical burn from improperly stored reagents in a market stall",
            "trapped in a structural collapse in the older Sanctum Quarter tunnels",
            "crushed by a falling market stall during a crowd panic",
            # Dungeon incursion / mission gone wrong
            "returned from a dungeon run missing two fingers — won't say which level",
            "mauled by something in the lower corridors of a Rift incursion zone",
            "took a floor trap to the leg on a contracted delve",
            "burned by a dungeon guardian's breath weapon inside a Rift boundary",
            "fell into a spiked pit trap in an unexplored Undercity sublevel",
            "came back from a dungeon contract half-conscious, gear destroyed",
            "bitten by an unknown creature encountered in an unmapped tunnel",
            # Occupational hazards
            "assaulted during a collection run for the Iron Fang Consortium",
            "kneecapped for missing a payment deadline",
            "poisoned by a business rival — slow-acting, they nearly didn't notice",
            "broke both arms falling from a Warrens rooftop while fleeing Wardens",
            "throat-cut by a competitor, bled out in an alley — found by Saints volunteers",
            # Rift exposure (now just one possibility among many)
            "too close when a micro-Rift opened — partial reality burn",
            "Rift residue exposure from an inadequately sealed sample",
            "caught in a Rift surge in the Outer Wall sector, minor warping",
        ])
        injury_bulletin = await _generate(
            f"{_LORE}\nNPC: {npc['name']}, {npc.get('faction', 'Independent')}, {npc.get('rank', 'Member')}.\n"
            f"Injury cause: {_injury_cause}.\n"
            f"Write a 2-3 line Undercity bulletin reporting this injury. Terse. Real. Outcome uncertain.\n"
            f"Use the specific cause above — do not default to 'Rift exposure' or generic fantasy.\n"
            f"No preamble. Output only the bulletin."
        )

        if injury_bulletin and channel:
            logger.info(f"🧬 Posting injury bulletin for {npc['name']}")
            try:
                embed = discord.Embed(
                    description=injury_bulletin,
                    color=discord.Color.orange()
                )
                embed.set_footer(text=f"🩹 {npc['name']} · {npc.get('faction', '?')} · {npc.get('rank', '?')}")
                await channel.send(embed=embed)
            except Exception as _de:
                logger.warning(f"🧬 Discord send failed (injury bulletin for {npc['name']}): {_de}")
        elif not injury_bulletin:
            logger.warning(f"🧬 Injury bulletin generation returned None for {npc['name']}")

        await asyncio.sleep(5)

    logger.info(
        f"🧬 Lifecycle complete. {len(npcs)} NPCs total, {len(alive_npcs)} alive, "
        f"{len(injured_npcs)} recovering, {len(injury_targets)} newly injured today."
    )

    # --- Graveyard Events: super rare resurrection / undead / doppelganger ---
    # Always run so a coroner's report posts even on quiet cycles.
    try:
        await _check_graveyard_events(channel)
    except Exception as e:
        logger.warning(f"🪦 Graveyard event error: {e}")

    # --- Party guild contract events: one party per cycle ---
    try:
        await _run_party_guild_event(channel)
    except Exception as e:
        logger.warning(f"🏢 Party guild event error: {e}")

    # --- Stat block backfill: background task, waits for Ollama slot ---
    async def _backfill_task():
        try:
            from src.npc_statblock_backfill import run_statblock_backfill
            _sb_filled = await run_statblock_backfill(n=2)
            if _sb_filled:
                logger.info(f"📋 Stat block backfill: filled {_sb_filled} NPC(s)")
        except Exception as e:
            logger.warning(f"📋 Stat block backfill error: {e}")
    asyncio.create_task(_backfill_task())

    # Cleanup is handled by run_daily_lifecycle's finally block — do not call here.


# ---------------------------------------------------------------------------
# Graveyard Events — super rare events for dead NPCs
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Faction Leaders — tagged for special death handling
# ---------------------------------------------------------------------------

FACTION_LEADERS = {
    "Iron Fang Consortium":   "Serrik Dhal",
    "Iron Fang Syndicate":    "Sera Voss",
    "Argent Blades":          "Lady Cerys Valemont",
    "Wardens of Ash":         "Captain Havel Korin",
    "Serpent Choir":          "High Apostle Yzura",
    "Obsidian Lotus":         "The Widow",
    "Glass Sigil":            "Senior Archivist Pell",
    "Patchwork Saints":       "Pol Greaves",       # informal leader
    "Adventurers Guild":      "Mari Fen",
    "Guild of Ashen Scrolls": "Archivist Eir Velan",
    "Tower Authority":        "Director Myra Kess",
    "Wizards Tower":          "Yaulderna Silverstreak",
    "Brother Thane's Cult":   "Brother Thane",
}

# Reverse lookup: leader name -> faction
_LEADER_NAMES = {v.lower(): k for k, v in FACTION_LEADERS.items()}


def is_faction_leader(npc_name: str) -> bool:
    """Check if an NPC is a faction leader."""
    return npc_name.lower() in _LEADER_NAMES


def get_leader_faction(npc_name: str) -> Optional[str]:
    """Return the faction a leader leads, or None."""
    return _LEADER_NAMES.get(npc_name.lower())


def injure_npc_by_name(name: str, cause: str = "") -> bool:
    """Mark a specific NPC as injured (e.g. survived an assassination attempt).
    The normal lifecycle tick then resolves injured NPCs (~90% recover, ~10% die
    and move to the graveyard). Returns True if an NPC was found and injured."""
    if not name:
        return False
    try:
        npcs = _load_npcs()
    except Exception as e:
        logger.warning(f"injure_npc_by_name load failed: {e}")
        return False
    target = next((n for n in npcs if str(n.get("name", "")).lower() == name.lower()), None)
    if not target:
        return False
    if str(target.get("status", "")).lower() in ("dead", "deceased"):
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    target["status"] = "injured"
    target["last_event_at"] = datetime.now().isoformat()
    _hist(target, f"[{today}] Injured in an assassination attempt{(' -- ' + cause) if cause else ''}.")
    try:
        _save_npcs(npcs)
    except Exception as e:
        logger.warning(f"injure_npc_by_name save failed: {e}")
        return False
    logger.info(f"\U0001fa78 {name} injured by an assassination attempt -- lifecycle will resolve recovery or death")
    return True


def wound_npc_in_combat(name: str, cause: str = "") -> bool:
    """Wound a specific NPC in combat (battle/assault/ambush) -- the general-purpose
    counterpart to the assassination-specific injure_npc_by_name. Sets status='injured'
    with a combat history line; the normal lifecycle tick then resolves recovery (~90%)
    or a move to the graveyard (~10%). Refuses faction leaders (a random combat tick must
    never kill a leader -- only deliberate, gated outcomes can) and only wounds the living.
    Returns True if an NPC was found and wounded."""
    if not name:
        return False
    if is_faction_leader(name):
        return False
    try:
        npcs = _load_npcs()
    except Exception as e:
        logger.warning(f"wound_npc_in_combat load failed: {e}")
        return False
    target = next((n for n in npcs if str(n.get("name", "")).lower() == name.lower()), None)
    if not target:
        return False
    if str(target.get("status", "")).lower() not in ("alive", "", "active"):
        return False  # only wound the living -- skip injured/undead/doppelganger/dead
    today = datetime.now().strftime("%Y-%m-%d")
    target["status"] = "injured"
    target["last_event_at"] = datetime.now().isoformat()
    _hist(target, f"[{today}] Wounded in the fighting{(' -- ' + cause) if cause else ''}.")
    try:
        _save_npcs(npcs)
    except Exception as e:
        logger.warning(f"wound_npc_in_combat save failed: {e}")
        return False
    logger.info(f"\U0001fa78 {name} wounded in combat ({cause or 'fighting'}) -- lifecycle will resolve recovery or death")
    return True


def wound_random_faction_member(faction: str, cause: str = "") -> str:
    """Pick a random LIVING, non-leader member of a faction and wound them in combat.
    Used by battle/assault/ambush butterfly consequences so violence has real casualties
    without ever random-killing a faction leader. Returns the wounded NPC's name, or ''."""
    if not faction:
        return ""
    f = faction.strip().lower()
    try:
        npcs = _load_npcs()
    except Exception as e:
        logger.warning(f"wound_random_faction_member load failed: {e}")
        return ""
    candidates = []
    for n in npcs:
        nf = str(n.get("faction", "")).strip().lower()
        if not nf or not (f in nf or nf in f):
            continue
        if str(n.get("status", "")).lower() not in ("alive", "", "active"):
            continue
        nm = str(n.get("name", "")).strip()
        if not nm or is_faction_leader(nm) or is_unknown_party_member(nm):
            continue
        candidates.append(nm)
    if not candidates:
        return ""
    chosen = random.choice(candidates)
    return chosen if wound_npc_in_combat(chosen, cause=cause) else ""


# ---------------------------------------------------------------------------
# Unknown Party — members receive special graveyard handling identical in
# weight to faction leaders (automatic, not random chance).
# ---------------------------------------------------------------------------

UNKNOWN_PARTY_MEMBERS = {
    "The Ward":  {"true_faction": "Tower Authority",        "designation": "WARD",    "cover": "Independent enforcer"},
    "Carrion":   {"true_faction": "Iron Fang Consortium",   "designation": "CARRION", "cover": "Independent scavenger"},
    "Sable":     {"true_faction": "Glass Sigil",            "designation": "SABLE",   "cover": "Serpent Choir (disputed)"},
    "Locket":    {"true_faction": "Obsidian Lotus",         "designation": "LOCKET",  "cover": "Independent"},
    "The Mute":  {"true_faction": "Wardens of Ash",         "designation": "VIGIL",   "cover": "Independent"},
}

_PARTY_MEMBER_NAMES = {k.lower(): v for k, v in UNKNOWN_PARTY_MEMBERS.items()}


def is_unknown_party_member(npc_name: str) -> bool:
    """Check if an NPC is a known Unknown Party member."""
    return npc_name.lower() in _PARTY_MEMBER_NAMES


def get_party_member_data(npc_name: str) -> Optional[dict]:
    """Return Unknown Party metadata for the NPC, or None."""
    return _PARTY_MEMBER_NAMES.get(npc_name.lower())


# Leader death outcomes and weights
LEADER_DEATH_OUTCOMES = {
    "raise_dead":       0.40,  # 40% — comes back, same person, weakened
    "resurrection":     0.30,  # 30% — comes back changed (race/gender/personality shift)
    "tower_absorbed":   0.30,  # 30% — permanently gone, successor promoted
}


async def _handle_leader_death(dead_npc: dict, npcs: List[dict], channel) -> str:
    """Special handling when a faction leader dies.
    Returns the outcome type: 'raise_dead', 'resurrection', or 'tower_absorbed'."""
    import discord

    name    = dead_npc.get("name", "Unknown")
    faction = dead_npc.get("faction", "Independent")
    species = dead_npc.get("species", "Human")
    today   = datetime.now().strftime("%Y-%m-%d")

    # Roll for outcome
    roll = random.random()
    cumulative = 0.0
    outcome = "tower_absorbed"  # default fallback
    for otype, chance in LEADER_DEATH_OUTCOMES.items():
        cumulative += chance
        if roll <= cumulative:
            outcome = otype
            break

    graveyard = _load_graveyard()

    if outcome == "raise_dead":
        # === RAISE DEAD — comes back as themselves, weakened ===
        logger.info(f"\U0001f451 Leader death: {name} ({faction}) — RAISE DEAD")

        bulletin = await _generate(
            f"{_LORE}\n"
            f"FACTION LEADER: {name}, {species}, head of {faction}.\n"
            f"{name} was killed but the faction immediately invoked an emergency "
            f"resurrection contract with the Serpent Choir. Cost was enormous.\n"
            f"Write a 3-4 line urgent news bulletin. {name} is alive but visibly shaken.\n"
            f"The faction spent a fortune. Rivals are circling. {name} is not the same.\n"
            f"Tone: relief mixed with dread. Coming back from death has a price.\n"
            f"No preamble. Output only the bulletin."
        )

        dead_npc["status"] = "injured"
        _hist(dead_npc, f"[{today}] KILLED AND RAISED. Faction emergency resurrection. Weakened.")
        dead_npc.pop("cause_of_death", None)
        dead_npc.pop("moved_to_graveyard_at", None)
        dead_npc["last_event_at"] = datetime.now().isoformat()
        dead_npc["oracle_notes"] = (
            dead_npc.get("oracle_notes", "") +
            " Died and was raised. Carries death-trauma. The faction paid dearly. Rivals smell weakness."
        ).strip()

        npcs.append(dead_npc)
        _save_npcs(npcs)
        graveyard = [g for g in graveyard if g.get("name") != name]
        _save_graveyard(graveyard)

        if bulletin and channel:
            embed = discord.Embed(description=bulletin, color=0x33CC77)
            embed.set_footer(text=f"\U0001f451 Raise Dead \u00b7 {name} \u00b7 {faction} Leader \u00b7 RESTORED")
            await channel.send(embed=embed)

    elif outcome == "resurrection":
        # === RESURRECTION — comes back CHANGED (different race/gender/personality) ===
        logger.info(f"\U0001f451 Leader death: {name} ({faction}) — RESURRECTION (changed)")

        new_species = random.choice([s for s in SPECIES_LIST if s != species])
        gender_flip = random.random() < 0.4  # 40% chance gender changes too
        personality_shift = random.choice([
            "quieter, more cautious, haunted by what they experienced",
            "harder, colder, ruthlessly pragmatic where they were once measured",
            "erratic, prone to strange decisions, as if listening to something no one else hears",
            "warmer, more empathetic, as if death showed them what mattered",
            "paranoid, trusting no one, convinced someone arranged their death",
        ])

        gender_note = ""
        if gender_flip:
            old_gender = "male" if random.random() < 0.5 else "female"
            new_gender = "female" if old_gender == "male" else "male"
            gender_note = f" Their gender has shifted from {old_gender} to {new_gender} \u2014 the magic was imperfect."

        bulletin = await _generate(
            f"{_LORE}\n"
            f"FACTION LEADER: {name}, formerly {species}, head of {faction}.\n"
            f"{name} was killed and resurrected, but the magic was imperfect.\n"
            f"They returned as {new_species} instead of {species}.{gender_note}\n"
            f"Their personality has shifted: {personality_shift}\n"
            f"Write a 3-4 line unsettling news bulletin. The city recognises them but "
            f"something is clearly different. Their faction is divided on whether this "
            f"is really {name}.\n"
            f"Tone: uncanny, specific, grounded.\n"
            f"No preamble. Output only the bulletin."
        )

        dead_npc["status"] = "alive"
        dead_npc["species"] = f"{new_species} (formerly {species})"
        _hist(dead_npc,
            f"[{today}] KILLED AND RESURRECTED \u2014 returned as {new_species}. "
            f"Personality shifted: {personality_shift}.{' Gender changed.' if gender_flip else ''}"
        )
        dead_npc.pop("cause_of_death", None)
        dead_npc.pop("moved_to_graveyard_at", None)
        dead_npc["last_event_at"] = datetime.now().isoformat()
        dead_npc["oracle_notes"] = (
            dead_npc.get("oracle_notes", "") +
            f" Resurrected imperfectly. Now {new_species}. {personality_shift.capitalize()}. "
            f"The Oracle questions whether this is truly the same soul."
        ).strip()
        dead_npc["motivation"] = (
            dead_npc.get("motivation", "") +
            f" Since resurrection: {personality_shift}."
        ).strip()

        npcs.append(dead_npc)
        _save_npcs(npcs)
        graveyard = [g for g in graveyard if g.get("name") != name]
        _save_graveyard(graveyard)

        if bulletin and channel:
            embed = discord.Embed(description=bulletin, color=0xCC6600)
            embed.set_footer(text=f"\U0001f451 Imperfect Resurrection \u00b7 {name} \u00b7 Now {new_species} \u00b7 CHANGED")
            await channel.send(embed=embed)

    else:
        # === TOWER ABSORBED — permanently gone, successor promoted ===
        logger.info(f"\U0001f451 Leader death: {name} ({faction}) \u2014 TOWER ABSORBED (permanent)")

        # Find the highest-ranked same-faction NPC to promote
        faction_members = [
            n for n in npcs
            if n.get("faction") == faction
            and n.get("status") in ("alive", "injured", "undead", "doppelganger")
            and n.get("name") != name
        ]

        successor = None
        successor_name = "no one"
        if faction_members:
            ranks = _ranks_for_faction(faction)
            rank_order = {r: i for i, r in enumerate(ranks)}

            def rank_score(npc):
                return rank_order.get(npc.get("rank", ""), -1)

            faction_members.sort(key=rank_score, reverse=True)
            successor = faction_members[0]
            successor_name = successor.get("name", "Unknown")

            # Promote successor to top rank
            old_rank = successor.get("rank", "?")
            top_rank = ranks[-1] if ranks else "Leader"
            successor["rank"] = top_rank
            _hist(successor,
                f"[{today}] PROMOTED to {top_rank} of {faction} following the permanent loss of {name}."
            )
            successor["oracle_notes"] = (
                successor.get("oracle_notes", "") +
                f" Suddenly thrust into leadership after {name}'s permanent death. The faction is in transition."
            ).strip()
            successor["last_event_at"] = datetime.now().isoformat()
            _save_npcs(npcs)

            # Update FACTION_LEADERS
            FACTION_LEADERS[faction] = successor_name
            _LEADER_NAMES[successor_name.lower()] = faction

            logger.info(f"\U0001f451 {successor_name} promoted to lead {faction} (was {old_rank})")

        successor_line = (
            f"Successor: {successor_name} has been elevated to lead {faction}."
            if successor else
            "The faction has no clear successor. Internal power struggle imminent."
        )
        successor_detail = (
            f"Mention {successor_name} stepping up \u2014 are they ready? Does the faction trust them?"
            if successor else
            "Multiple candidates are already positioning. This could get ugly."
        )
        bulletin = await _generate(
            f"{_LORE}\n"
            f"FACTION LEADER: {name}, {species}, head of {faction}. PERMANENTLY DEAD.\n"
            f"The Tower has absorbed {name}'s soul. There is no coming back.\n"
            f"{successor_line}\n"
            f"Write a 4-5 line solemn, significant news bulletin. This is a major city event.\n"
            f"The faction is shaken. Rivals see opportunity. The city holds its breath.\n"
            f"{successor_detail}\n"
            f"Tone: grave, consequential, specific. A power vacuum just opened.\n"
            f"No preamble. Output only the bulletin."
        )

        # Mark as permanently absorbed in graveyard
        _hist(dead_npc, f"[{today}] TOWER ABSORBED \u2014 soul claimed permanently. No resurrection possible.")
        dead_npc["tower_absorbed"] = True
        npc_id = dead_npc.get("_db_id") or dead_npc.get("id")
        if npc_id:
            raw_execute("UPDATE npcs SET tower_absorbed=1 WHERE id=%s", (npc_id,))
        _save_graveyard(graveyard)

        if bulletin and channel:
            embed = discord.Embed(description=bulletin, color=0x1a1a2e)
            footer_text = f"\U0001f480 Tower Absorbed \u00b7 {name} \u00b7 PERMANENTLY LOST"
            if successor:
                footer_text += f" \u00b7 {successor_name} now leads {faction}"
            embed.set_footer(text=footer_text)
            await channel.send(embed=embed)

    return outcome


# Per dead NPC per lifecycle tick. These are VERY rare.
GRAVEYARD_EVENT_CHANCES = {
    "tower_fund_me":  0.01,   # 1% — community raises funds, NPC resurrected properly
    "undead_return":  0.01,   # 1% — comes back wrong (undead, changed, dangerous)
    "doppelganger":   0.02,   # 2% — someone is impersonating the dead NPC
}


async def _handle_party_member_death(dead_npc: dict, npcs: List[dict], channel) -> None:
    """
    Special graveyard processing for Unknown Party member deaths.
    Unlike faction leaders (who have public power), party members are covert —
    their death is significant because it risks exposing the whole cell.
    Always fires (no random roll), once per cycle.
    """
    import discord

    name       = dead_npc.get("name", "Unknown")
    faction    = dead_npc.get("faction", "Independent")
    species    = dead_npc.get("species", "Human")
    today      = datetime.now().strftime("%Y-%m-%d")
    party_data = get_party_member_data(name)
    true_faction  = party_data["true_faction"] if party_data else "Unknown"
    designation   = party_data["designation"]  if party_data else "UNKNOWN"
    cover         = party_data["cover"]         if party_data else "Independent"

    # Remaining alive party members
    alive_members = [
        m for m in UNKNOWN_PARTY_MEMBERS
        if m != name and any(n.get("name") == m and n.get("status") in ("alive","injured","undead","doppelganger") for n in npcs)
    ]
    member_count_line = (
        f"Remaining active designations: {', '.join(alive_members)}." if alive_members
        else "No remaining active designations confirmed."
    )

    bulletin = await _generate(
        f"{_LORE}\n\n"
        f"CLASSIFIED CONTEXT (do NOT reveal explicitly in the bulletin):\n"
        f"'{name}' was designation {designation}, a covert operative of {true_faction} "
        f"embedded in an anonymous adventuring cell called the Unknown Party. "
        f"Their public cover was: {cover}.\n"
        f"{member_count_line}\n\n"
        f"Write TWO short items:\n\n"
        f"ITEM 1 — A public city notice (2-3 lines): announce the death of '{name}' as the city "
        f"would see it — as a {cover}, with no mention of their true allegiance. "
        f"Terse, grim. The city barely knew them.\n\n"
        f"ITEM 2 — An intercepted internal dispatch (2-3 lines): a fragment of a coded message "
        f"between {true_faction} handlers. Uses the designation {designation}. "
        f"Implies the cell's cover may be compromised. Does not name the Unknown Party directly. "
        f"Reads like a bureaucratic warning with an edge of controlled panic.\n\n"
        f"Format:\n"
        f"PUBLIC: [bulletin text]\n"
        f"INTERCEPTED: [dispatch text]\n\n"
        f"No preamble. Output only those two labeled blocks."
    )

    # Update the dead NPC's history
    _hist(dead_npc,
        f"[{today}] Unknown Party member. Designation {designation} ({true_faction}). "
        f"Special graveyard protocol triggered."
    )
    _save_graveyard([dead_npc])

    logger.info(f"🎭 Unknown Party death protocol for {name} (designation {designation})")

    if bulletin and channel:
        try:
            embed = discord.Embed(
                title=f"🎭 Designation {designation} — Lost",
                description=bulletin,
                color=0x2a2a3a,  # near-black — covert, heavy
            )
            embed.set_footer(text=f"Unknown Party · {name} · {true_faction} (classified)")
            await channel.send(embed=embed)
        except Exception as _de:
            logger.warning(f"🎭 Unknown Party death Discord send failed: {_de}")


_CORONER_QUIET = [
    "Nothing to report from the city morgue today. The dead are staying dead. For now.",
    "Status check: all registered deceased remain accounted for. No anomalies. No movement. No sightings.",
    "The Serpent Choir reports quiet from the other side. No disturbances logged at the boundary.",
    "Graveyard sweep complete. No incidents. No resurrections. No doppelganger sightings. The records stand.",
    "All current cases in the morgue register are closed. The Undercity's dead are, at present, cooperating.",
    "No new reports from the Registry of the Deceased. The graveyard holds. The city sleeps a little easier.",
    "Morgue dispatch: quiet night. No unusual activity among known deceased. File updated. Nothing to act on.",
    "The dead were checked on today. They had nothing new to say. This is, officially, a good sign.",
    "Registry of the Dead — cycle check complete. {n} cases on file. All at rest. No further action required.",
    "The Wardens of Ash confirm: no graveyard anomalies this cycle. The wards are holding. The dead remain still.",
    "Coroner's note: {n} files closed, {n} bodies quiet. Anyone claiming otherwise should bring evidence or stop wasting oxygen.",
    "Morgue window statement: no walking dead, no duplicate corpses, no unauthorized miracles. The office will not be taking questions from TNN today.",
    "Registry check complete. The dead did their part. The living are advised to try matching that level of cooperation.",
    "City Coroner dispatch: diamonds remain expensive, grief remains louder, and every body on file stayed where the tag says it belongs.",
]


async def _check_graveyard_events(channel) -> None:
    """Roll for rare events involving dead NPCs in the graveyard.
    At most ONE event fires per lifecycle cycle to keep things special.
    Always posts a coroner's report — either an event or a quiet notice."""
    import discord

    graveyard = _load_graveyard()
    n_dead = len(graveyard)
    npcs = _load_npcs()
    today = datetime.now().strftime("%Y-%m-%d")
    event_fired = False

    # Shuffle so it's not always the first dead NPC that gets checked first
    random.shuffle(graveyard)

    for dead_npc in graveyard:
        if event_fired:
            break

        name    = dead_npc.get("name", "Unknown")
        faction = dead_npc.get("faction", "Independent")
        species = dead_npc.get("species", "Human")

        # Skip tower-absorbed NPCs — they're permanently gone
        if dead_npc.get("tower_absorbed"):
            continue

        # Skip NPCs that died very recently (give them at least 3 days in the ground)
        moved_at = dead_npc.get("moved_to_graveyard_at", "")
        if moved_at:
            try:
                days_dead = (datetime.now() - datetime.fromisoformat(moved_at)).total_seconds() / 86400
                if days_dead < 3:
                    continue
            except Exception:
                pass

        # LEADERS get special handling — automatic, not random
        if is_faction_leader(name):
            logger.info(f"\U0001f451 Faction leader {name} found in graveyard — triggering leader death protocol")
            try:
                await _handle_leader_death(dead_npc, npcs, channel)
            except Exception as e:
                logger.error(f"\U0001f451 Leader death handling failed for {name}: {e}")
            event_fired = True
            break

        # UNKNOWN PARTY MEMBERS get special handling — automatic, covert bulletin
        if is_unknown_party_member(name):
            logger.info(f"🎭 Unknown Party member {name} found in graveyard — triggering party death protocol")
            try:
                await _handle_party_member_death(dead_npc, npcs, channel)
            except Exception as e:
                logger.error(f"🎭 Party member death handling failed for {name}: {e}")
            event_fired = True
            break

        # Roll for each event type (normal NPCs)
        roll = random.random()
        cumulative = 0.0

        for event_type, chance in GRAVEYARD_EVENT_CHANCES.items():
            cumulative += chance
            if roll > cumulative:
                continue

            # === TOWER FUND ME — Community resurrection ===
            if event_type == "tower_fund_me":
                logger.info(f"💰 GRAVEYARD EVENT: Tower Fund Me for {name}!")

                bulletin = await _generate(
                    f"{_LORE}\n"
                    f"DEAD NPC: {name}, {species}, formerly {faction}.\n"
                    f"A community fundraising campaign called 'Tower Fund Me' has raised enough "
                    f"Kharma and EC to hire a Serpent Choir resurrection contract for {name}.\n"
                    f"Write a 3-4 line news bulletin about the successful resurrection. "
                    f"Include: who organized it, how much it cost (between 800 and 3000 Kharma — a major communal effort), "
                    f"the Serpent Choir's involvement, and {name}'s confused first words.\n"
                    f"{name} is alive but weakened — they'll need time to recover.\n"
                    f"Tone: hopeful but with an edge. Resurrection has consequences in this world.\n"
                    f"No preamble. Output only the bulletin."
                )

                # Move NPC back to active roster
                dead_npc["status"] = "injured"  # comes back weak
                _hist(dead_npc, f"[{today}] RESURRECTED via Tower Fund Me campaign. Weakened but alive.")
                dead_npc.pop("cause_of_death", None)
                dead_npc.pop("moved_to_graveyard_at", None)
                dead_npc["last_event_at"] = datetime.now().isoformat()
                dead_npc["oracle_notes"] = (
                    dead_npc.get("oracle_notes", "") +
                    " Recently resurrected — disoriented, weakened, and carrying the weight of what they saw on the other side."
                ).strip()

                npcs.append(dead_npc)
                _save_npcs(npcs)

                # Remove from graveyard
                graveyard = [g for g in graveyard if g.get("name") != name]
                _save_graveyard(graveyard)

                if bulletin and channel:
                    embed = discord.Embed(
                        description=bulletin,
                        color=0x33CC77,  # green — good news
                    )
                    embed.set_footer(text=f"💰 Tower Fund Me · {name} · RESURRECTED")
                    await channel.send(embed=embed)

                event_fired = True

            # === UNDEAD RETURN — Comes back wrong ===
            elif event_type == "undead_return":
                logger.info(f"🧟 GRAVEYARD EVENT: Undead return for {name}!")

                # Pick a transformation type — weighted toward the more interesting kinds
                undead_pool = [
                    # Soul-bound / purpose-driven
                    ("Revenant", "burning with singular purpose, hollow-eyed, capable of speech — back to finish what was left undone"),
                    ("Banshee", "wailing keening grief given form — her scream alone can stop a heart, and she remembers everyone she loved"),
                    ("Specter", "drained of color and warmth, phases through walls, drains life from anyone who lingers too close"),
                    ("Wraith", "shadow without a body, visible only as a silhouette of cold — it has already started draining the life from nearby streets"),
                    # Cunning / social undead
                    ("Vampire Spawn", "pale, fast, hungry — still has their personality but the thirst colors everything now, and they're trying to hide it"),
                    ("Shadow Demon (NPC-bound)", "the shadow detached from the corpse and walks on its own — it knows every secret they knew"),
                    ("Lich (nascent)", "the ritual was incomplete but partial — they hold together through sheer willpower and dark knowledge, crumbling slowly"),
                    ("Death Knight", "armored in shadow, wielding dark echoes of their former skills — their oath twisted into something darker"),
                    # Corporeal but changed
                    ("Wight", "cold, calculating, remembers everything but feels nothing — already gathering followers from the desperate and the damned"),
                    ("Mummy (cursed)", "wrapped in shroud-cloth, preserved wrong, carrying a curse tied to the cause of their death"),
                    ("Ghast", "more lucid than a ghoul, faster, crueler — the smell of them makes people flee before they even see the face"),
                    ("Allip", "driven mad by violent death, babbling fragments of their final moments — those who listen too long start forgetting themselves"),
                    # Rare / dramatic
                    ("Dullahan (headless herald)", "rides through the Undercity at midnight, calls a name at each stop — the name is always someone who will die soon"),
                    ("Hollow (soul-eaten)", "the body walks but something else is wearing it — their face moves wrong, their words are someone else's words"),
                    ("Deathlock", "a warlock whose patron refused to let them rest — bound to service in undeath, still casting, still dangerous"),
                ]
                undead_type = random.choice(undead_pool)
                utype, udesc = undead_type

                faction_reaction = random.choice([
                    f"{faction} has issued a formal denial that the figure is connected to them",
                    f"senior {faction} members are said to be in private contact with the entity",
                    f"{faction} has placed a bounty on confirming the sighting — or ending it",
                    f"former allies in {faction} refuse to discuss it publicly",
                    f"{faction} leadership is rumored to be attempting to make contact and negotiate",
                    f"rank-and-file {faction} members are reportedly terrified and avoiding the area",
                ])

                bulletin = await _generate(
                    f"{_LORE}\n"
                    f"DEAD NPC: {name}, formerly {species}, {faction}. Confirmed dead.\n"
                    f"{name} has returned from death as a {utype}: {udesc}.\n"
                    f"Write a 3-4 line news bulletin about {name} being sighted in the Undercity.\n"
                    f"Include: where they were sighted, what they did or said, one witness reaction.\n"
                    f"Also include: {faction_reaction}.\n"
                    f"The bulletin should feel specific to the nature of a {utype} — use what makes this type of undead distinct.\n"
                    f"Tone: unsettling, urgent, specific. Make it feel like breaking news.\n"
                    f"No preamble. Output only the bulletin."
                )

                # Move back to roster as an undead NPC (status='undead' for DB queries)
                dead_npc["status"] = "undead"
                dead_npc["species"] = f"{utype} (formerly {species})"
                _hist(dead_npc, f"[{today}] RETURNED FROM DEATH as {utype}. {udesc}.")
                dead_npc.pop("cause_of_death", None)
                dead_npc.pop("moved_to_graveyard_at", None)
                dead_npc["last_event_at"] = datetime.now().isoformat()
                dead_npc["oracle_notes"] = (
                    dead_npc.get("oracle_notes", "") +
                    f" Returned from death as {utype}. Changed. Dangerous. The Oracle watches with great interest."
                ).strip()
                dead_npc["motivation"] = f"Unfinished business from before death. Driven by {random.choice(['vengeance', 'regret', 'a promise they never kept', 'something they saw on the other side', 'hunger for what they lost'])}."

                npcs.append(dead_npc)
                _save_npcs(npcs)

                graveyard = [g for g in graveyard if g.get("name") != name]
                _save_graveyard(graveyard)

                if bulletin and channel:
                    embed = discord.Embed(
                        description=bulletin,
                        color=0x660066,  # dark purple — supernatural
                    )
                    embed.set_footer(text=f"🧟 {name} · {utype} · RETURNED FROM DEATH")
                    await channel.send(embed=embed)

                # Generate a Strange Occurrence mission for the undead return
                try:
                    from src.mission_board import _generate as _gen_mission, _parse_mission, _add_mission, _expiry_for_tier

                    undead_mission_prompt = f"""{_LORE}

---
MISSION TYPE: Strange Occurrence (Undead Return)
Generate ONE mission posting about {name}, formerly {species} of {faction}, who has returned from death as a {utype}.
{udesc}
{name} is now somewhere in the Undercity. They were confirmed dead — now they are something else entirely.
The posting faction should be {faction} (alarmed by the return) or the Adventurers Guild.

This is a Strange Occurrence mission — heavily weighted toward roleplay and investigation, with possible combat.
The mission is NOT just "go destroy the undead." The party must investigate WHAT {name} has been doing since returning,
and WHY — what unfinished business, what hunger, what purpose drives a {utype}.
Focus: track {name}'s movements, interview witnesses who have encountered them, understand what they want.
The resolution may be combat, a ritual, a bargain, or something no one expected.

REQUIRED FORMAT:

**[FACTION NAME] — MISSION TITLE**
*Type: Strange Occurrences | Tier: investigation | Expires: TBD | Reward: [X EC + any extras]*
*Opposes: None*

[3-4 sentences. Name specific locations where {name} has been sighted, describe one specific unsettling thing
they were seen doing — something that reflects the nature of a {utype}. Be specific to this undead type.
End with the objective: find {name}, understand what they have become and what they want, and resolve it.]

*Contact: [named NPC], [location]*

RULES:
- Tier must be investigation
- The mission title should feel eerie and specific to this kind of undead return — not generic
- Do NOT give the party a simple kill order — the posting should leave open whether destruction or something else is right
- No preamble, no sign-off. Output the mission post only."""

                    mission_text = await _gen_mission(undead_mission_prompt)
                    if mission_text:
                        mission = _parse_mission(mission_text)
                        mission["undead_return_of"] = name
                        mission["undead_type"] = utype
                        mission["type"] = "Strange Occurrences"
                        mission["mission_type"] = "strange_occurrence"
                        _add_mission(mission)
                        logger.info(f"🧟 Strange Occurrence (undead return) mission created: {mission.get('title', '?')}")
                except Exception as e:
                    logger.warning(f"🧟 Undead return mission creation failed: {e}")

                event_fired = True

            # === DOPPELGANGER — Someone is impersonating the dead NPC ===
            elif event_type == "doppelganger":
                logger.info(f"🎭 GRAVEYARD EVENT: Doppelganger of {name}!")

                bulletin = await _generate(
                    f"{_LORE}\n"
                    f"DEAD NPC: {name}, formerly {species}, {faction}. CONFIRMED DEAD.\n"
                    f"Multiple witnesses have reported seeing someone who looks exactly like {name} "
                    f"in the Undercity. But {name} is dead.\n"
                    f"Write a 3-4 line disturbing news bulletin about these sightings.\n"
                    f"Include: where they were seen, who reported it, and why people are unsettled.\n"
                    f"The impersonator was seen doing something {name} used to do — "
                    f"visiting their old haunts, talking to their old contacts.\n"
                    f"Is it a shapeshifter? A twin? A Rift echo? Nobody knows.\n"
                    f"Tone: creepy, specific, grounded. No resolution — just the unsettling report.\n"
                    f"No preamble. Output only the bulletin."
                )

                # Move to active roster as doppelganger — status='doppelganger' makes it queryable
                # by Strange Occurrences mission logic. Original NPC is still "dead" conceptually
                # but this entry represents the impostor now operating in the city.
                dead_npc["status"] = "doppelganger"
                _hist(dead_npc, f"[{today}] DOPPELGANGER active — something is impersonating {name} in the Undercity.")
                dead_npc["oracle_notes"] = (
                    dead_npc.get("oracle_notes", "") +
                    f" A doppelganger is wearing {name}'s face. The original is dead. This entity has its own agenda."
                ).strip()
                dead_npc.pop("moved_to_graveyard_at", None)
                dead_npc["last_event_at"] = datetime.now().isoformat()

                npcs.append(dead_npc)
                _save_npcs(npcs)

                graveyard = [g for g in graveyard if g.get("name") != name]
                _save_graveyard(graveyard)

                if bulletin and channel:
                    embed = discord.Embed(
                        description=bulletin,
                        color=0xAA6633,  # brown — mystery
                    )
                    embed.set_footer(text=f"🎭 Doppelganger · {name} · IDENTITY UNKNOWN")
                    await channel.send(embed=embed)

                # Generate a Strange Occurrence mission for the doppelganger
                try:
                    from src.mission_board import _generate as _gen_mission, _parse_mission, _add_mission, _expiry_for_tier

                    mission_prompt = f"""{_LORE}

---
MISSION TYPE: Strange Occurrence (Doppelganger)
Generate ONE mission posting about a doppelganger impersonating the deceased {name} ({species}, {faction}).
{name} was confirmed dead. Something or someone is now wearing their face and moving through the Undercity.
The posting faction should be {faction} (they want answers) or the Adventurers Guild.

This is a Strange Occurrence mission — heavily weighted toward roleplay and investigation, with possible combat at the end.
The mission is NOT just "kill the impersonator." The party must first figure out WHAT it is and WHY it is here.
Focus: witness interviews, tracking the entity's movements, uncovering its purpose.
The resolution may be combat, a confrontation, an unmasking, or something stranger.

REQUIRED FORMAT:

**[FACTION NAME] — MISSION TITLE**
*Type: Strange Occurrences | Tier: investigation | Expires: TBD | Reward: [X EC + any extras]*
*Opposes: None*

[3-4 sentences. Name specific sighting locations, name a witness or two, describe what the entity was doing —
NOT just "it looked like them" but something specific and unsettling it did or said. End with the clear objective:
find out what it is, what it wants, and deal with it.]

*Contact: [named NPC], [location]*

RULES:
- Tier must be investigation
- The mission title should feel eerie and personal — this is someone wearing a dead person's face
- Do NOT resolve the mystery in the posting — leave it open and unsettling
- No preamble, no sign-off. Output the mission post only."""

                    mission_text = await _gen_mission(mission_prompt)
                    if mission_text:
                        mission = _parse_mission(mission_text)
                        mission["doppelganger_of"] = name
                        mission["type"] = "Strange Occurrences"
                        mission["mission_type"] = "strange_occurrence"
                        _add_mission(mission)
                        logger.info(f"🎭 Strange Occurrence (doppelganger) mission created: {mission.get('title', '?')}")
                except Exception as e:
                    logger.warning(f"🎭 Doppelganger mission creation failed: {e}")

                event_fired = True

            break  # Only one event type per NPC per cycle

    # Always post a coroner's report — either as the main event or as a brief addendum
    if not channel:
        logger.info("🪦 Graveyard event processed this cycle" if event_fired else "🪦 Graveyard quiet this cycle (no channel)")
        return

    if event_fired:
        # After an event fires, post a brief one-line coroner's tally as a footer follow-up
        logger.info("🪦 Graveyard event processed this cycle — posting case-count addendum")
        try:
            tally_lines = [
                f"The Office of the City Coroner notes {n_dead} cases currently on file.",
                f"City Coroner files updated. Active cases: {n_dead}. Cycle closed.",
                f"Coroner's addendum: {n_dead} deceased on the registry following this cycle's proceedings.",
                f"Registry updated. {n_dead} cases on file. The Coroner's office has no further comment at this time.",
                f"One case processed this cycle. {n_dead} total remain on record with the Office of the City Coroner.",
            ]
            tally = random.choice(tally_lines)
            names_on_file = ", ".join(g.get("name", "?") for g in graveyard[:10])
            if n_dead > 10:
                names_on_file += f" (and {n_dead - 10} more)"
            embed = discord.Embed(
                title="🪦 Coroner's Office — Case Update",
                description=tally,
                color=0x445566,
            )
            embed.add_field(name=f"Registry ({n_dead} on file)", value=names_on_file or "None", inline=False)
            embed.set_footer(text="Office of the City Coroner — Filed this cycle")
            await channel.send(embed=embed)
        except Exception as _de:
            logger.warning(f"🪦 Coroner's addendum Discord send failed: {_de}")
        return

    # No event fired — post the full quiet coroner's report
    quiet_msg = random.choice(_CORONER_QUIET).replace("{n}", str(n_dead))
    if n_dead == 0:
        quiet_msg = "Registry of the Dead is empty — no deceased on file. A remarkably peaceful record."

    logger.info(f"🪦 Graveyard quiet this cycle — posting coroner's report ({n_dead} on file)")
    try:
        embed = discord.Embed(
            title="🪦 Coroner's Report",
            description=quiet_msg,
            color=0x445566,
        )
        if n_dead > 0:
            names_on_file = ", ".join(g.get("name", "?") for g in graveyard[:10])
            if n_dead > 10:
                names_on_file += f" (and {n_dead - 10} more)"
            embed.add_field(name=f"Deceased on file ({n_dead})", value=names_on_file, inline=False)
        embed.set_footer(text="Office of the City Coroner — Filed this cycle")
        await channel.send(embed=embed)
    except Exception as _de:
        logger.warning(f"🪦 Coroner's report Discord send failed: {_de}")


# ---------------------------------------------------------------------------
# Party guild contract events — runs once per lifecycle cycle
# ---------------------------------------------------------------------------

async def _run_party_guild_event(channel) -> None:
    """Once per lifecycle cycle, roll a guild contract event for one NPC party.

    Possible outcomes:
    - contract_awarded  : unaffiliated party picked up by a guild
    - contract_ended    : party loses guild contract, goes independent
    - poached_to_guild  : party jumps from one guild to a higher-paying rival
    - promotion_in_guild: party's faction rank bumps up within their current guild
    """
    import discord as _discord

    try:
        guilds = _get_guild_factions()
        if not guilds:
            return

        # Pick a random party to affect
        all_parties = raw_query(
            "SELECT id, party_name, faction, profile_json FROM party_profiles "
            "WHERE status='active' ORDER BY RAND() LIMIT 20"
        ) or []
        if not all_parties:
            return

        party = random.choice(all_parties)
        pname   = party["party_name"]
        current = (party.get("faction") or "").strip()

        pj = party.get("profile_json") or {}
        if isinstance(pj, str):
            try: pj = json.loads(pj)
            except: pj = {}

        today = datetime.now().strftime("%Y-%m-%d")
        guild_affiliated = "(Guild)" in current

        # Weight: 50% contract events for guild parties, 50% for independents
        if guild_affiliated:
            outcome = random.choice([
                "contract_ended", "contract_ended",
                "poached_to_guild",
                "promotion_in_guild", "promotion_in_guild",
            ])
        else:
            outcome = "contract_awarded"

        announcement = None
        embed_color  = 0x4a90d9

        if outcome == "contract_awarded":
            new_guild = random.choice(guilds)
            pj["faction"]  = new_guild
            pj["employer"] = new_guild
            add_party_history_event(party["id"], f"[{today}] Contracted by {new_guild}.")
            raw_execute(
                "UPDATE party_profiles SET faction=%s, employer=%s, profile_json=%s WHERE id=%s",
                (new_guild, new_guild, json.dumps({k:v for k,v in pj.items() if k!="history"}, ensure_ascii=False), party["id"])
            )
            announcement = await _generate(
                f"{_LORE}\nParty: {pname} (previously independent or minor faction).\n"
                f"Event: Awarded a contract by {new_guild}. First posting as Contracted Operatives.\n"
                f"Write a 2-3 line Undercity bulletin — job board tone, corporate meets gritty city.\n"
                f"No preamble. Output only the bulletin."
            )
            embed_color = 0x2ecc71

        elif outcome == "contract_ended":
            old_guild = current
            pj["faction"]  = "Independent"
            pj["employer"] = ""
            add_party_history_event(party["id"], f"[{today}] Contract with {old_guild} ended.")
            raw_execute(
                "UPDATE party_profiles SET faction=%s, employer=%s, profile_json=%s WHERE id=%s",
                ("Independent", None, json.dumps({k:v for k,v in pj.items() if k!="history"}, ensure_ascii=False), party["id"])
            )
            reason = random.choice([
                "contract term expired",
                "terminated for cause",
                "mutual parting of ways",
                "guild restructuring — position eliminated",
                "party declined renewal",
            ])
            announcement = await _generate(
                f"{_LORE}\nParty: {pname}. Previously under {old_guild}.\n"
                f"Event: Contract ended ({reason}). Now independent.\n"
                f"Write a 2-3 line Undercity notice. Neutral tone — could be mundane or imply conflict.\n"
                f"No preamble. Output only the bulletin."
            )
            embed_color = 0xe67e22

        elif outcome == "poached_to_guild":
            rival = random.choice([g for g in guilds if g != current] or guilds)
            old_guild = current
            pj["faction"]  = rival
            pj["employer"] = rival
            add_party_history_event(party["id"], f"[{today}] Poached from {old_guild} to {rival}.")
            raw_execute(
                "UPDATE party_profiles SET faction=%s, employer=%s, profile_json=%s WHERE id=%s",
                (rival, rival, json.dumps({k:v for k,v in pj.items() if k!="history"}, ensure_ascii=False), party["id"])
            )
            announcement = await _generate(
                f"{_LORE}\nParty: {pname}. Previously under {old_guild}.\n"
                f"Event: Poached by {rival} at better terms. {old_guild} not pleased.\n"
                f"Write a 2-3 line Undercity bulletin — inter-guild rivalry, implied backstory.\n"
                f"No preamble. Output only the bulletin."
            )
            embed_color = 0x9b59b6

        elif outcome == "promotion_in_guild":
            tier = pj.get("tier", "Unknown")
            tiers = ["Unknown", "Recognized", "Established", "Trusted", "Elite"]
            idx = tiers.index(tier) if tier in tiers else 0
            if idx < len(tiers) - 1:
                new_tier = tiers[idx + 1]
                pj["tier"] = new_tier
                add_party_history_event(party["id"], f"[{today}] Promoted within {current}: tier {tier} -> {new_tier}.")
                raw_execute(
                    "UPDATE party_profiles SET tier=%s, profile_json=%s WHERE id=%s",
                    (new_tier, json.dumps({k:v for k,v in pj.items() if k!="history"}, ensure_ascii=False), party["id"])
                )
                announcement = await _generate(
                    f"{_LORE}\nParty: {pname}, contracted to {current}.\n"
                    f"Event: Internal promotion — tier {tier} to {new_tier}. More responsibility, better pay.\n"
                    f"Write a 2-3 line Undercity notice — guild internal bulletin, slightly corporate.\n"
                    f"No preamble. Output only the bulletin."
                )
                embed_color = 0x1abc9c
            else:
                return  # already at top tier, skip

        if announcement and channel:
            try:
                embed = _discord.Embed(description=announcement, color=embed_color)
                embed.set_footer(text=f"Party Contract Notice: {pname}")
                await channel.send(embed=embed)
                logger.info(f"Party guild event [{outcome}]: {pname}")
            except Exception as _e:
                logger.warning(f"Party guild event Discord send failed: {_e}")

    except Exception as e:
        logger.warning(f"_run_party_guild_event error: {e}")


# ---------------------------------------------------------------------------
# Interval
# ---------------------------------------------------------------------------

def next_lifecycle_seconds() -> int:
    """20-28 hours so it doesn't fire at the exact same time every day."""
    return random.randint(20 * 3600, 28 * 3600)
