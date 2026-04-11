"""
faction_calendar.py — Undercity Faction Event Calendar

Scheduled real-world dates where factions hold events:
auctions, trials, tournaments, holy days, council sessions, black markets.

- Events are generated 30-90 days into the future on a rolling basis
- Bot announces each event 48h in advance
- Bot posts a follow-up result bulletin when the event date passes
- Events persist to MySQL faction_events table
- Max 8 upcoming events at once; new ones generated when below 4

Posts announcements and results to the news channel.
"""

from __future__ import annotations
import json
import random, logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.db_api import raw_query, raw_execute, db

logger = logging.getLogger(__name__)
TOWER_YEAR_OFFSET = 10


def _dual_ts() -> str:
    now   = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    return f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"


def _tower_date(dt: datetime) -> str:
    t = dt.replace(year=dt.year + TOWER_YEAR_OFFSET)
    return t.strftime("%d %b %Y")


# ---------------------------------------------------------------------------
# Event type pools per faction
# ---------------------------------------------------------------------------

_FACTION_EVENTS = {
    "Iron Fang Consortium": [
        ("Sealed Relic Auction",         "🔨", "Private auction of confiscated and acquired relics. Invitation only. Bidding starts at 50,000 EC."),
        ("Debt Collection Assembly",     "💼", "Consortium agents convene to process outstanding debts. Some debtors attend voluntarily."),
        ("Surplus Clearance Sale",       "🏷️",  "Overstock moved through Crimson Alley. First come, first priced."),
        ("Black Ledger Review",          "📒", "Internal review of the season's acquisition records. Closed doors. Two agents did not return from the last one."),
    ],
    "Argent Blades": [
        ("Season Rankings Ceremony",     "🏆", "Official ranking updates announced at the Arena. Fame points re-calibrated. Some names move up. Some don't."),
        ("Open Challenge Night",         "⚔️",  "Any ranked adventurer may challenge a Blade above their standing. Three bouts. No rules against spectators."),
        ("Recruitment Drive",            "📋", "Argent Blades accepting new members. Standards have not dropped. Many will try. Fewer will pass."),
        ("Memorial Bout",                "🕯️",  "A match held in honour of a fallen Blade. Results are never disputed. Tradition demands respect."),
    ],
    "Wardens of Ash": [
        ("District Safety Inspection",   "🛡️",  "Full sweep of one district. Unlicensed operations suspended for 24 hours. Residents advised to cooperate."),
        ("Warden Oath Ceremony",         "🔥", "New recruits receive their commissions under the Outer Wall's fire. Captain Korin presides."),
        ("After-Action Review",          "📊", "Internal assessment of recent Rift incidents. Not public. Lieutenant Varen is presenting. Corvin Thale is attending uninvited."),
        ("Checkpoint Expansion",         "🚧", "New checkpoint established at a district boundary. Three week notice period. Locals unimpressed."),
    ],
    "Serpent Choir": [
        ("Open Contract Day",            "📜", "Serpent Choir opens divine contract negotiations to walk-ins. Read the terms before you sign. Read them again."),
        ("Holy Observation — Silence",   "🤫", "Day of ritual silence in the Sanctum Quarter. No commerce. No noise. Violations are noted."),
        ("Kharma Tithe Collection",      "✨", "Monthly Kharma harvest from standing contract holders. Those who cannot pay meet with a mediator."),
        ("Yzura's Public Sermon",        "🙏", "High Apostle Yzura speaks in the Hall of Echoes. Attendance voluntary. Memory of attendance not voluntary."),
    ],
    "Obsidian Lotus": [
        ("Memory Market",                "💜", "Underground bazaar for memory vials, bottled experiences, and identity fragments. Location announced 6 hours prior."),
        ("Contract Dissolution Fair",    "🗑️",  "Unwanted contracts, obligations, and memories accepted for dissolution. Discretion guaranteed. FTA is watching anyway."),
        ("The Widow's Audience",         "🕸️",  "The Widow holds appointments — one per petitioner, one hour each. Waiting list: eight months."),
    ],
    "Glass Sigil": [
        ("Anomaly Symposium",            "🔬", "Glass Sigil presents recent Rift residue findings to interested parties. Academic. Dense. Three people will fall asleep."),
        ("Archive Access Day",           "📚", "Public access to non-restricted Glass Sigil records for 24 hours. Dova will be managing the queue."),
        ("Calibration Event",            "📡", "City-wide instrument recalibration. Minor arcane disruptions expected. Don't panic. Probably."),
    ],
    "Patchwork Saints": [
        ("Warrens Community Mend",       "🧵", "Saints coordinate free repairs — equipment, housing, injuries. Mara the Scrapper donating materials this cycle."),
        ("Vigil for the Lost",           "🕯️",  "Night vigil in Collapsed Plaza for adventurers and residents who didn't make it out of the Warrens this season."),
        ("Resource Allocation Meeting",  "📋", "Saints publicly distribute surplus supplies. Open to Warrens residents. No faction affiliation required."),
    ],
    "Adventurers Guild": [
        ("Contract Board Refresh",       "📋", "New high-tier contracts posted simultaneously. Mari Fen will be at the desk. Line forms at dawn."),
        ("Rank Advancement Testing",     "🎖️",  "Adventurers seeking rank promotion submit for assessment. Three pass. Many don't."),
        ("Guild Mixer",                  "🍺",  "Informal gathering at the Adventurer's Inn. Networking. Gossip. Someone always leaves with a new contract or a new enemy."),
    ],
    "Guild of Ashen Scrolls": [
        ("Fate Archive Submission Day",  "📖", "Adventurers may submit records of notable deeds for archival. Eir Velan reviews all submissions personally."),
        ("Thesaurus Observation Night",  "⭐", "A rare night when the god Thesaurus is said to read the Archive actively. The building feels watched."),
        ("Tessaly's Research Briefing",  "📊", "Tessaly Orin presents nine years of narrative resonance data to a small invited audience. Someone will try to steal the notes."),
    ],
    "Tower Authority / FTA": [
        ("Compliance Review Session",    "📋", "FTA conducts public compliance reviews. Calix Drenn presiding. Bring your paperwork."),
        ("License Renewal Window",       "🪪",  "Annual adventurer license renewal opens. 30-day window. Late fees apply. Calix Drenn will not waive the fees."),
        ("Director's Address",           "🎙️",  "Director Myra Kess delivers a city-wide status report. Usually sanitised. Usually."),
    ],
}


# ---------------------------------------------------------------------------
# Persistence — MySQL via db_api
# ---------------------------------------------------------------------------

def _load_calendar() -> List[Dict]:
    """Load all faction events from database."""
    try:
        rows = raw_query("SELECT * FROM faction_events ORDER BY event_date ASC")
        events = []
        for row in rows:
            # Map event_type -> type for compatibility
            ev = dict(row)
            if "event_type" in ev:
                ev["type"] = ev.pop("event_type")
            if ev.get("event_date") and isinstance(ev["event_date"], datetime):
                ev["event_date"] = ev["event_date"].isoformat()
            
            # Extract metadata from description if present
            desc = ev.get("description", "")
            if "<!--META:" in desc and "-->" in desc:
                try:
                    meta_start = desc.index("<!--META:") + 9
                    meta_end = desc.index("-->", meta_start)
                    meta_json = desc[meta_start:meta_end]
                    meta = json.loads(meta_json)
                    ev["emoji"] = meta.get("emoji", "")
                    ev["announced"] = meta.get("announced", False)
                    ev["resolved"] = meta.get("resolved", False)
                    ev["description"] = meta.get("original_desc", desc[:desc.index("<!--META:")].strip())
                except (ValueError, json.JSONDecodeError):
                    # If metadata parsing fails, use defaults
                    ev["emoji"] = ""
                    ev["announced"] = False
                    ev["resolved"] = False
            else:
                # No metadata, use defaults
                ev["emoji"] = ""
                ev["announced"] = False
                ev["resolved"] = False
            
            events.append(ev)
        return events
    except Exception as e:
        logger.error(f"Calendar load error: {e}")
        return []


def _save_event(ev: Dict) -> None:
    """Insert or update a single event in the database.
    Note: Only using columns that exist in schema: id, faction, event_type, event_date, description
    Extra data (emoji, announced, resolved) is stored in description as JSON suffix.
    """
    try:
        # Encode extra state in description field since schema is limited
        extra_data = {
            "emoji": ev.get("emoji", ""),
            "announced": ev.get("announced", False),
            "resolved": ev.get("resolved", False),
            "original_desc": ev.get("description", ""),
        }
        # Store original description + JSON suffix
        description_with_meta = ev.get("description", "") + "\n<!--META:" + json.dumps(extra_data) + "-->"
        
        # Check if event already exists by id (use faction + event_type + event_date as composite key)
        existing = raw_query(
            "SELECT id FROM faction_events WHERE faction = %s AND event_type = %s AND event_date = %s",
            (ev.get("faction"), ev.get("type"), ev.get("event_date"))
        )
        if existing:
            # Update existing event
            raw_execute(
                """UPDATE faction_events 
                   SET description = %s
                   WHERE faction = %s AND event_type = %s AND event_date = %s""",
                (
                    description_with_meta,
                    ev.get("faction"),
                    ev.get("type"),
                    ev.get("event_date"),
                )
            )
        else:
            # Insert new event
            db.insert("faction_events", {
                "faction": ev.get("faction"),
                "event_type": ev.get("type"),
                "event_date": ev.get("event_date"),
                "description": description_with_meta,
            })
    except Exception as e:
        logger.error(f"Calendar save event error: {e}")


# ---------------------------------------------------------------------------
# Event generation
# ---------------------------------------------------------------------------

def _generate_event() -> Dict:
    """Generate one new upcoming faction event."""
    faction = random.choice(list(_FACTION_EVENTS.keys()))
    ev_type, emoji, desc = random.choice(_FACTION_EVENTS[faction])
    days_ahead = random.randint(30, 90)
    event_dt   = datetime.now() + timedelta(days=days_ahead)

    return {
        "id":           f"ev_{int(datetime.now().timestamp())}_{random.randint(100,999)}",
        "faction":      faction,
        "type":         ev_type,
        "emoji":        emoji,
        "description":  desc,
        "event_date":   event_dt.isoformat(),
        "announced":    False,   # 48h advance notice posted
        "resolved":     False,   # result posted
        "created_at":   datetime.now().isoformat(),
    }


def _top_up_calendar(events: List[Dict]) -> List[Dict]:
    """Ensure at least 4 upcoming unresolved events exist. Add up to 8 total."""
    upcoming = [e for e in events if not e.get("resolved")]
    while len(upcoming) < 4 and len(events) < 20:
        new_ev = _generate_event()
        _save_event(new_ev)  # Persist new event to DB
        events.append(new_ev)
        upcoming.append(new_ev)
    return events


# ---------------------------------------------------------------------------
# Tick — called each bulletin cycle
# ---------------------------------------------------------------------------

def tick_calendar() -> List[Dict]:
    """
    Process the event calendar.
    Returns list of bulletin dicts: {type: 'announce'|'result', event: {...}}
    """
    events  = _load_calendar()
    events  = _top_up_calendar(events)
    now     = datetime.now()
    outputs = []

    for ev in events:
        if ev.get("resolved"):
            continue

        try:
            event_dt = datetime.fromisoformat(ev["event_date"])
        except (ValueError, KeyError) as e:
            logger.warning(f"🗓️ Could not parse event date {ev.get('event_date', 'MISSING')}: {e}")
            continue
        
        hours_until = (event_dt - now).total_seconds() / 3600
        changed = False

        # 48h advance announcement
        if not ev.get("announced") and 0 < hours_until <= 48:
            ev["announced"] = True
            outputs.append({"type": "announce", "event": ev})
            changed = True

        # Event has passed — post result
        if now >= event_dt and ev.get("announced"):
            ev["resolved"] = True
            outputs.append({"type": "result", "event": ev})
            changed = True

        # Save only if event state changed
        if changed:
            _save_event(ev)

    return outputs


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_event_announce(ev: Dict) -> str:
    event_dt   = datetime.fromisoformat(ev["event_date"])
    tower_date = _tower_date(event_dt)
    hours_left = max(1, int((event_dt - datetime.now()).total_seconds() / 3600))

    lines = [
        f"{ev['emoji']} **UPCOMING EVENT — {ev['type'].upper()}** {ev['emoji']}",
        f"-# {_dual_ts()}",
        "",
        f"**Faction:** {ev['faction']}",
        f"**Event:** {ev['type']}",
        f"*{ev['description']}*",
        "",
        f"📅 **Date:** {tower_date}  ·  ⏳ In approximately {hours_left} hours",
        "",
        "-# Faction calendar maintained by the Guild of Ashen Scrolls.",
    ]
    return "\n".join(lines)


def format_event_result(ev: Dict) -> str:
    # Generic result — AI can elaborate but this is the fallback
    outcomes = [
        "The event concluded without major incident. Attendees are tight-lipped.",
        "Results are being processed. Early reports suggest things went roughly as expected.",
        "The event ran long. Three people left early. Nobody is explaining why.",
        "Outcome pending official confirmation from the hosting faction.",
        "Word from those present: it happened. Details are filtering through slowly.",
        "The event is done. Whether it achieved its goals is a matter of perspective.",
    ]
    lines = [
        f"{ev['emoji']} **EVENT CONCLUDED — {ev['type'].upper()}**",
        f"-# {_dual_ts()}",
        "",
        f"**Faction:** {ev['faction']}",
        f"*{random.choice(outcomes)}*",
        "",
        "-# Follow-up details may emerge in subsequent bulletins.",
    ]
    return "\n".join(lines)
