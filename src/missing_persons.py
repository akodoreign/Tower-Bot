"""
missing_persons.py — Undercity Missing Persons Ticker
*** REFACTORED TO USE MySQL via db_api ***

Small human-interest bulletins. Missing persons notices posted by residents,
factions, or the city itself. Some are plot-relevant. Most are texture.
"""

from __future__ import annotations
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.log import logger
from src.db_api import raw_query, raw_execute, db

TOWER_YEAR_OFFSET = 10
MISSING_COOLDOWN_MIN = 2 * 24 * 3600
MISSING_COOLDOWN_MAX = 4 * 24 * 3600
MISSING_EXPIRY_MIN   = 14
MISSING_EXPIRY_MAX   = 30
FOUND_CHANCE = 0.20

_SUBJECT_POOLS = [
    ("a young courier who has not reported back in three days",              "Grand Forum",      "their employer at the Adventurers Guild",    "moderate"),
    ("an elderly herbalist who lives alone in the Warrens",                 "The Warrens",      "a neighbour",                                "low"),
    ("a Glass Sigil junior archivist who missed two shifts",                "Guild Spires",      "Senior Archivist Pell",                      "high"),
    ("a child last seen near Brother Thane's Cult House",                   "The Warrens",      "their parent",                               "urgent"),
    ("a Warden patrol member who did not return from a routine check",      "Outer Wall",       "Lieutenant Varen",                           "high"),
    ("a merchant whose stall in Markets Infinite has been empty for a week","Markets Infinite",  "Iron Fang Consortium debt officer",          "financial"),
    ("a Serpent Choir novice who was last seen signing a contract",         "Sanctum Quarter",  "the Choir — officially, quietly",            "uncertain"),
    ("a Scrapworks day-labourer, one of three who went down a sealed shaft","The Warrens",      "Mara the Scrapper",                          "grim"),
    ("an FTA field officer who did not submit their weekly report",         "Grand Forum",      "Director Myra Kess",                         "very high"),
    ("a street performer who has been a fixture of Cobbleway for years",    "Markets Infinite", "regular patrons",                            "low"),
    ("a Patchwork Saints volunteer, last seen heading toward Echo Alley",   "The Warrens",      "Pol Greaves",                                "personal"),
    ("an Obsidian Lotus client who attended a memory-erasure session",      "Night Pits",       "an anonymous third party",                   "unknown"),
]

_FOUND_OUTCOMES = [
    "They turned up alive and unwilling to explain where they had been.",
    "Found in the lower Warrens. Physically unharmed. Memory gaps reported.",
    "Located at a Serpent Choir hospice. Under voluntary contract terms.",
    "Returned on their own. Filed no report. Spoke to no one.",
    "Their belongings were found. The person has not been.",
    "A body matching the description was recovered near the Outer Wall.",
    "They were found working under a different name in Markets Infinite.",
    "Confirmed alive in FTA custody. Reason for detention not disclosed.",
    "Located by the Glass Sigil during a routine anomaly sweep.",
    "Found in good health. Claim they were never missing.",
]


def _load_missing() -> List[Dict]:
    """Load missing persons from database."""
    try:
        records = raw_query("SELECT * FROM missing_persons ORDER BY reported_at DESC")
        return records or []
    except Exception as e:
        logger.error(f"Missing persons load error: {e}")
        return []


def _save_missing_record(record: Dict) -> int:
    """Save a new missing person record."""
    try:
        return db.insert("missing_persons", {
            "person_name": record.get("name", "Unknown"),
            "last_seen_location": record.get("district", "Unknown"),
            "status": "missing" if not record.get("resolved") else "found",
            "reported_at": datetime.now(),
        })
    except Exception as e:
        logger.error(f"Missing persons save error: {e}")
        return 0


def _last_posted_at() -> Optional[datetime]:
    """Get timestamp of most recent missing person posting."""
    try:
        result = raw_query("SELECT MAX(reported_at) as last_post FROM missing_persons WHERE status = 'missing'")
        if result and result[0].get("last_post"):
            return result[0]["last_post"]
        return None
    except Exception:
        return None


def should_post_missing() -> bool:
    """True if cooldown elapsed and random roll passes."""
    last = _last_posted_at()
    if last:
        min_gap = random.randint(MISSING_COOLDOWN_MIN, MISSING_COOLDOWN_MAX)
        elapsed = (datetime.now() - last).total_seconds()
        if elapsed < min_gap:
            return False
    return random.random() < 0.25


async def generate_missing_bulletin() -> Optional[str]:
    """Generate a missing persons notice using KimiAgent."""
    from src.agents import generate_with_kimi

    desc, district, filed_by, urgency = random.choice(_SUBJECT_POOLS)
    now   = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    ts    = f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"

    prompt = f"""You are writing a missing persons notice for the Undercity Dispatch.
The Undercity is a sealed dark fantasy city under a Dome.

Generate ONE missing persons notice. Invent a specific named person.

Who is missing: {desc}
Last known district: {district}
Filed by: {filed_by}
Urgency: {urgency}

REQUIRED OUTPUT FORMAT — output exactly this, nothing else:

🔍 **MISSING PERSON — [FULL NAME]**
*Filed by: {filed_by}*

**Last seen:** [specific location in {district}], approximately [X] days ago
**Description:** [2 sentences — age, appearance, what they were wearing or carrying]
**Circumstances:** [1-2 sentences — what was normal before they disappeared]

*Anyone with information contact [appropriate faction contact or location].*

RULES:
- Invent a real-feeling specific person.
- Tone: human, grounded, specific. Not dramatic.
- No preamble, no sign-off. Output the notice only."""

    try:
        text = await generate_with_kimi(prompt, temperature=0.8)
        if not text:
            return None

        # Extract name from notice
        import re
        name_match = re.search(r"\*\*MISSING PERSON — (.+?)\*\*", text)
        name = name_match.group(1) if name_match else "Unknown"

        # Save to database
        _save_missing_record({
            "name": name,
            "district": district,
            "filed_by": filed_by,
            "body": text,
            "resolved": False,
        })

        return f"-# 🕰️ {ts}\n{text}"

    except Exception as e:
        logger.error(f"Missing persons generation error: {e}")
        return None


def tick_missing_resolutions() -> List[str]:
    """Check for expired missing persons. 20% get a 'found' bulletin."""
    now     = datetime.now()
    tower   = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    ts      = f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"
    outputs = []

    try:
        # Get missing persons older than 14 days
        cutoff = now - timedelta(days=MISSING_EXPIRY_MIN)
        records = raw_query(
            "SELECT * FROM missing_persons WHERE status = 'missing' AND reported_at < %s",
            (cutoff,)
        )

        if not records:
            return []

        for r in records:
            # Mark as resolved
            raw_execute(
                "UPDATE missing_persons SET status = 'found' WHERE id = %s",
                (r["id"],)
            )

            if random.random() < FOUND_CHANCE:
                outcome = random.choice(_FOUND_OUTCOMES)
                name = r.get("person_name", "The individual")
                outputs.append(
                    f"-# 🕰️ {ts}\n"
                    f"🔍 **UPDATE — MISSING PERSONS CASE**\n"
                    f"*{name}: {outcome}*"
                )

    except Exception as e:
        logger.error(f"Missing resolutions error: {e}")

    return outputs
