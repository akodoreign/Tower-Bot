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
    return f"{now.strftime('%Y-%m-%d %H:%M')} | Tower: {tower.strftime('%d %b %Y, %H:%M')}"


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
    "Iron Fang Syndicate": [
        ("Protection Rounds",            "💰", "Sera Voss's collectors make their rounds through the lower Markets. Tribute is no longer optional. Receipts not provided."),
        ("TowerBay Position Call",       "📈", "The Syndicate moves on a block of auction lots. Prices do what Voss needs them to. Ask no questions about the volume."),
        ("Debtors' Reckoning",           "💸", "Outstanding loans come due across Crimson Alley. The vig has changed, and so has the collateral."),
        ("Turf Line Notice",             "🪙", "The Syndicate marks new ground taken from the orthodox Consortium. Old Iron Fang signage is being painted over."),
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
    "Wizards Tower": [
        ("Spellcraft Exhibition",        "🔮", "Wizards Tower researchers demonstrate new spell developments and experimental techniques in the Arcanum District. Yaulderna Silverstreak rarely descends — tonight she has."),
        ("Arcane Duel Circuit",          "⚡", "Sanctioned spell duels in a warded ring beneath the Tower. Ranked by technique, not just outcome. Judges from the Tower and Glass Sigil both scoring."),
        ("Open Scroll Reading",          "📜", "The Tower opens a curated selection of its archive to vetted visitors for one day. Varys Thornspire managing access. Not everything on the shelves is safe to read."),
        ("Containment Audit",            "🔒", "Internal review of all unstable artefacts and phenomena currently held in the Tower's vaults. Lirael Moonshadow leading. Two items from last quarter's log are unaccounted for."),
        ("Apprentice Assessment Day",    "🎓", "The Tower evaluates candidates for apprenticeship. High attrition rate. Those who pass tend not to discuss what the final test involved."),
    ],
}


# ---------------------------------------------------------------------------
# Reputation shifts — applied when an event resolves
# ---------------------------------------------------------------------------

_REP_SHIFTS: Dict[str, int] = {
    # Positive public events
    "Warden Oath Ceremony":           3,
    "Open Challenge Night":           2,
    "Season Rankings Ceremony":       2,
    "Anomaly Symposium":              2,
    "Warrens Community Mend":         3,
    "Vigil for the Lost":             2,
    "Resource Allocation Meeting":    2,
    "Contract Board Refresh":         2,
    "Rank Advancement Testing":       1,
    "Fate Archive Submission Day":    2,
    "Yzura's Public Sermon":          2,
    "Guild Mixer":                    1,
    "Archive Access Day":             1,
    "Open Contract Day":              1,
    "License Renewal Window":         1,
    "Director's Address":             1,
    "Memorial Bout":                  1,
    "Recruitment Drive":              1,
    "Thesaurus Observation Night":    2,
    "Tessaly's Research Briefing":    1,
    "Sealed Relic Auction":           1,
    "Surplus Clearance Sale":         1,
    "Calibration Event":              1,
    # Neutral or mildly negative
    "District Safety Inspection":     1,
    "Holy Observation — Silence":     1,
    "Checkpoint Expansion":          -1,
    "After-Action Review":            0,
    "Debt Collection Assembly":      -1,
    "Kharma Tithe Collection":       -1,
    "Memory Market":                 -1,
    "Contract Dissolution Fair":      0,
    "The Widow's Audience":          -1,
    "Black Ledger Review":           -2,
    "Compliance Review Session":     -1,
    # Wizards Tower
    "Spellcraft Exhibition":          2,
    "Arcane Duel Circuit":            2,
    "Open Scroll Reading":            1,
    "Containment Audit":             -1,
    "Apprentice Assessment Day":      1,
}


# ---------------------------------------------------------------------------
# Event → mission mapping
# (mission_type, dm_brief, faction_override_or_None, expires_days)
# ---------------------------------------------------------------------------

_EVENT_MISSION_MAP: Dict[str, tuple] = {
    "Sealed Relic Auction": (
        "theft",
        "{faction} is auctioning confiscated relics. A private buyer needs one specific lot "
        "before it disappears into a sealed vault — quietly, before the auction clears.",
        None, 4,
    ),
    "Debt Collection Assembly": (
        "investigation",
        "A debtor at {faction}'s assembly claims the ledger was altered before their debt "
        "was filed. The original record needs to surface before the review window closes.",
        None, 3,
    ),
    "Black Ledger Review": (
        "infiltration",
        "{faction} is reviewing its acquisition records behind closed doors. Someone on the "
        "outside needs to know which names appear in that ledger.",
        None, 3,
    ),
    "Open Challenge Night": (
        "escort",
        "A ranked fighter heading to the Argent Blades' Open Challenge Night received an "
        "anonymous threat this morning. They need eyes in the crowd and someone at their back.",
        "Argent Blades", 2,
    ),
    "Memorial Bout": (
        "investigation",
        "The fighter being honoured at the Argent Blades' Memorial Bout did not die in the "
        "ring. The official story has gaps. Someone wants those gaps filled before the ceremony.",
        "Argent Blades", 3,
    ),
    "Recruitment Drive": (
        "investigation",
        "One of the candidates presenting for Argent Blades recruitment is not who they claim "
        "to be. The Guild wants to know who sent them before the assessment closes.",
        "Argent Blades", 2,
    ),
    "Season Rankings Ceremony": (
        "investigation",
        "The Argent Blades' ranking adjustments were altered before the ceremony. Numbers moved "
        "that no registered official touched. Someone had access to the ledger they should not have.",
        "Argent Blades", 3,
    ),
    "District Safety Inspection": (
        "delivery",
        "The Wardens are running a full sweep. A licensed merchant needs three crates moved to "
        "a bonded warehouse before the checkpoint activates — nothing illegal, just inconveniently timed.",
        "Wardens of Ash", 1,
    ),
    "After-Action Review": (
        "theft",
        "Corvin Thale has turned up uninvited at the Wardens' After-Action Review. He is looking "
        "for something specific in the incident reports. Find out what before he does.",
        "Wardens of Ash", 3,
    ),
    "Checkpoint Expansion": (
        "negotiation",
        "The Wardens' new checkpoint sits on a boundary three local businesses share. One of them "
        "needs help getting their objection on record before the three-week notice window closes.",
        "Wardens of Ash", 3,
    ),
    "Open Contract Day": (
        "investigation",
        "A contract on the Serpent Choir's open table has a planted clause that binds the signatory "
        "to terms they have not read. It needs to be flagged before the window closes.",
        None, 2,
    ),
    "Kharma Tithe Collection": (
        "recovery",
        "A tithe holder claims the Serpent Choir collected double this cycle. Their receipt is "
        "missing. Recover the original before the mediator meeting or the debt stands.",
        None, 3,
    ),
    "Memory Market": (
        "recovery",
        "A buyer at the Obsidian Lotus' Memory Market walked off with a vial that was not theirs. "
        "The original owner wants it back before the memory degrades. Discretion required.",
        None, 3,
    ),
    "Contract Dissolution Fair": (
        "theft",
        "Something being dissolved at the Obsidian Lotus' fair belongs to a third party who was "
        "not consulted. Retrieve it before the process completes.",
        None, 2,
    ),
    "Anomaly Symposium": (
        "investigation",
        "A finding being presented at the Glass Sigil's Symposium has been altered since the "
        "original field report. The lead researcher does not know. Find who swapped the data.",
        None, 4,
    ),
    "Archive Access Day": (
        "theft",
        "The Glass Sigil has opened its non-restricted records for 24 hours. A specific document "
        "needs to leave the archive in that window — quietly, before access closes.",
        None, 1,
    ),
    "Calibration Event": (
        "investigation",
        "The Glass Sigil's city-wide calibration is being used as cover. A second instrument "
        "signature has appeared in three districts that does not belong to any registered device.",
        None, 3,
    ),
    "Warrens Community Mend": (
        "escort",
        "Supplies donated to the Patchwork Saints' Mend event are being intercepted before "
        "they reach the Warrens. Find who is diverting them and where the materials are going.",
        None, 3,
    ),
    "Vigil for the Lost": (
        "investigation",
        "A name on the Patchwork Saints' vigil list does not belong there — that person was "
        "seen alive three days ago. Someone added a living person to the roll of the dead.",
        None, 3,
    ),
    "Contract Board Refresh": (
        "investigation",
        "A contract just posted during the Adventurers Guild's board refresh has a planted "
        "brief. It leads somewhere it should not. The Guild wants the plant identified before "
        "someone takes the job.",
        None, 2,
    ),
    "Rank Advancement Testing": (
        "investigation",
        "One of the candidates presenting for Guild rank advancement has been set up to fail. "
        "Evidence of interference has turned up in the assessors' notes. Find who arranged it.",
        None, 3,
    ),
    "Guild Mixer": (
        "recovery",
        "A confidential job offer changed hands at the Adventurers Guild mixer last night. "
        "The recipient is now missing. The contract needs to be recovered before someone else reads it.",
        None, 2,
    ),
    "Fate Archive Submission Day": (
        "investigation",
        "A deed submitted to the Guild of Ashen Scrolls' archive has been fabricated. "
        "Eir Velan flagged it before accepting it. Track down who submitted the false record and why.",
        None, 4,
    ),
    "Tessaly's Research Briefing": (
        "theft",
        "Tessaly Orin's nine-year dataset is being presented to a small audience tonight. "
        "Someone in that room intends to leave with the notes. Stop them before the briefing ends.",
        None, 1,
    ),
    "Compliance Review Session": (
        "investigation",
        "A business under FTA compliance review was tipped off in advance. Someone inside "
        "the Tower Authority sold the warning. Find the source before the review closes.",
        None, 3,
    ),
    "Director's Address": (
        "investigation",
        "Something was cut from Director Myra Kess' address at the last moment. The "
        "undelivered section was removed from the teleprompter twenty minutes before she spoke. "
        "Recover it.",
        None, 3,
    ),
    # Wizards Tower
    "Spellcraft Exhibition": (
        "investigation",
        "A technique demonstrated at the Wizards Tower's Spellcraft Exhibition was not original. "
        "Yaulderna Silverstreak knows it — she isn't saying who stole it or from whom.",
        "Wizards Tower", 4,
    ),
    "Arcane Duel Circuit": (
        "investigation",
        "One of the duellists in the Wizards Tower's Arcane Circuit had their spell profile "
        "altered before the match. The Glass Sigil judge noticed the discrepancy. "
        "Find who tampered with the registration ledger.",
        "Wizards Tower", 3,
    ),
    "Open Scroll Reading": (
        "theft",
        "Something on the Wizards Tower's open shelves should not have been accessible today. "
        "Varys Thornspire pulled the item the moment he saw who was reading it — too late. "
        "Track the reader down before they transcribe what they saw.",
        "Wizards Tower", 1,
    ),
    "Containment Audit": (
        "recovery",
        "Two items from the Wizards Tower's vault log are unaccounted for after Lirael "
        "Moonshadow's audit. One is inert. The other is not. Recover the active one first.",
        "Wizards Tower", 3,
    ),
    "Apprentice Assessment Day": (
        "investigation",
        "One of the Wizards Tower's assessment candidates passed the final test in a way "
        "that should not have been possible. Grimble Scorchbeak saw something. "
        "Find out what was substituted before the results are ratified.",
        "Wizards Tower", 2,
    ),
}


def _apply_reputation_shift(faction: str, event_type: str) -> None:
    """Write a small rep delta to faction_reputation when an event resolves."""
    delta = _REP_SHIFTS.get(event_type, 0)
    if delta == 0:
        return
    try:
        raw_execute(
            "UPDATE faction_reputation "
            "SET reputation_score = LEAST(100, GREATEST(0, reputation_score + %s)) "
            "WHERE faction_name = %s",
            (delta, faction),
        )
        logger.debug(f"🗓️ Rep shift {delta:+d} applied to {faction} for '{event_type}'")
    except Exception as e:
        logger.warning(f"🗓️ Rep shift failed for {faction}: {e}")


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
                    ev["emoji"]           = meta.get("emoji", "")
                    ev["announced"]       = meta.get("announced", False)
                    ev["resolved"]        = meta.get("resolved", False)
                    ev["mission_spawned"] = meta.get("mission_spawned", False)
                    ev["description"]     = meta.get("original_desc", desc[:desc.index("<!--META:")].strip())
                except (ValueError, json.JSONDecodeError):
                    ev["emoji"]           = ""
                    ev["announced"]       = False
                    ev["resolved"]        = False
                    ev["mission_spawned"] = False
            else:
                ev["emoji"]           = ""
                ev["announced"]       = False
                ev["resolved"]        = False
                ev["mission_spawned"] = False
            
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
            "emoji":           ev.get("emoji", ""),
            "announced":       ev.get("announced", False),
            "resolved":        ev.get("resolved", False),
            "mission_spawned": ev.get("mission_spawned", False),
            "original_desc":   ev.get("description", ""),
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

        # Event has passed — post result and apply rep shift. Resolve even if
        # the bot missed the 48h announcement window while offline/restarting.
        if now >= event_dt:
            if not ev.get("announced"):
                ev["announced"] = True
            ev["resolved"] = True
            outputs.append({"type": "result", "event": ev})
            _apply_reputation_shift(ev.get("faction", ""), ev.get("type", ""))
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


def get_pending_mission_spawns() -> List[Dict]:
    """Return resolved events that have a mission mapping but no mission spawned yet."""
    events = _load_calendar()
    return [
        ev for ev in events
        if ev.get("resolved")
        and not ev.get("mission_spawned")
        and ev.get("type") in _EVENT_MISSION_MAP
    ]


def mark_mission_spawned(ev: Dict) -> None:
    """Persist mission_spawned=True for this event so it doesn't spawn again."""
    ev["mission_spawned"] = True
    _save_event(ev)


def get_mission_params(ev: Dict) -> tuple:
    """Return (mission_type, brief, faction, expires_days) for a calendar event."""
    mission_type, brief_tpl, faction_override, expires_days = _EVENT_MISSION_MAP[ev["type"]]
    faction = faction_override or ev.get("faction", "Adventurers Guild")
    brief   = brief_tpl.format(faction=faction)
    return mission_type, brief, faction, expires_days


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
