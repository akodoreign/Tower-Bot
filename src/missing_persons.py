"""
missing_persons.py — Undercity Missing Persons Ticker

Small human-interest bulletins. Missing persons notices posted by residents,
factions, or the city itself. Some are plot-relevant. Most are texture.

- 2-4 new notices per week, posted as news bulletins
- Notices persist for 14-30 days, then quietly expire (resolved, ran away, or just gone)
- Occasionally a missing person is "found" — good or bad
- Some tie back to roster NPCs or faction events

Persists to campaign_docs/missing_persons.json
"""

from __future__ import annotations
import json, os, random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.log import logger

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
MISSING_FILE = DOCS_DIR / "missing_persons.json"
TOWER_YEAR_OFFSET = 10

MISSING_COOLDOWN_MIN = 2 * 24 * 3600   # at least 2 days between notices
MISSING_COOLDOWN_MAX = 4 * 24 * 3600   # at most 4 days
MISSING_EXPIRY_MIN   = 14
MISSING_EXPIRY_MAX   = 30

# 20% of missing persons will get a "found" resolution
FOUND_CHANCE = 0.20

_SUBJECT_POOLS = [
    # (description_hint, district, filed_by, urgency)
    ("a young courier who has not reported back in three days",              "Grand Forum",      "their employer at the Adventurers Guild",    "moderate"),
    ("an elderly herbalist who lives alone in the Warrens",                 "The Warrens",      "a neighbour",                                "low — they go missing occasionally"),
    ("a Glass Sigil junior archivist who missed two shifts",                "Guild Spires",      "Senior Archivist Pell",                      "high"),
    ("a child last seen near Brother Thane's Cult House",                   "The Warrens",      "their parent",                               "urgent"),
    ("a Warden patrol member who did not return from a routine check",      "Outer Wall",       "Lieutenant Varen",                           "high — not publicly disclosed"),
    ("a merchant whose stall in Markets Infinite has been empty for a week","Markets Infinite",  "Iron Fang Consortium debt officer",          "financial — not welfare"),
    ("a Serpent Choir novice who was last seen signing a contract",         "Sanctum Quarter",  "the Choir — officially, quietly",            "uncertain"),
    ("a Scrapworks day-labourer, one of three who went down a sealed shaft","The Warrens",      "Mara the Scrapper",                          "grim"),
    ("an FTA field officer who did not submit their weekly report",         "Grand Forum",      "Director Myra Kess — via internal memo only","very high, not public"),
    ("a street performer who has been a fixture of Cobbleway for years",    "Markets Infinite", "regular patrons of the stall",               "low — but people noticed"),
    ("a Patchwork Saints volunteer, last seen heading toward Echo Alley",   "The Warrens",      "Pol Greaves",                                "personal — Greaves is not sleeping"),
    ("an Obsidian Lotus client who attended a memory-erasure session",      "Night Pits",       "an anonymous third party",                   "the Lotus has not commented"),
]

_FOUND_OUTCOMES = [
    "They turned up alive and unwilling to explain where they had been.",
    "Found in the lower Warrens. Physically unharmed. Memory gaps reported.",
    "Located at a Serpent Choir hospice. Under voluntary contract terms.",
    "Returned on their own. Filed no report. Spoke to no one.",
    "Their belongings were found. The person has not been.",
    "A body matching the description was recovered near the Outer Wall. Wardens are investigating.",
    "They were found working under a different name in Markets Infinite.",
    "Confirmed alive in FTA custody. Reason for detention not disclosed.",
    "Located by the Glass Sigil during a routine anomaly sweep. Circumstances classified.",
    "Found in good health. Claim they were never missing. Records suggest otherwise.",
]


def _load_missing() -> List[Dict]:
    if not MISSING_FILE.exists():
        return []
    try:
        return json.loads(MISSING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_missing(records: List[Dict]) -> None:
    try:
        MISSING_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"Missing persons save error: {e}")


def _last_posted_at() -> Optional[datetime]:
    records = _load_missing()
    posted  = [r for r in records if r.get("posted_at") and not r.get("is_resolution")]
    if not posted:
        return None
    try:
        return max(datetime.fromisoformat(r["posted_at"]) for r in posted)
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
    return random.random() < 0.25   # 25% chance per bulletin tick when eligible


async def generate_missing_bulletin() -> Optional[str]:
    """
    Generate a missing persons notice using KimiAgent.
    
    REFACTORED: Now uses src.agents.generate_with_kimi helper.
    """
    from src.agents import generate_with_kimi

    desc, district, filed_by, urgency = random.choice(_SUBJECT_POOLS)
    days     = random.randint(MISSING_EXPIRY_MIN, MISSING_EXPIRY_MAX)
    expires  = datetime.now() + timedelta(days=days)
    now      = datetime.now()
    tower    = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    ts       = f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"

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
**Circumstances:** [1-2 sentences — what was normal before they disappeared, any last contact]

*Anyone with information contact [appropriate faction contact or location].*

RULES:
- Invent a real-feeling specific person. Give them texture.
- The notice should feel like someone actually filed it — worried, terse, or bureaucratic depending on who filed it.
- Tone: human, grounded, specific. Not dramatic. Not epic. A real person is missing.
- No preamble, no sign-off. Output the notice only.
- If your response contains anything other than the notice, you have failed."""

    try:
        text = await generate_with_kimi(prompt, temperature=0.8)
        
        if not text:
            return None

        # Save to persistence
        records = _load_missing()
        records.append({
            "id":         f"mp_{int(datetime.now().timestamp())}",
            "body":       text,
            "posted_at":  datetime.now().isoformat(),
            "expires_at": expires.isoformat(),
            "resolved":   False,
            "found":      False,
        })
        _save_missing(records)

        return f"-# 🕰️ {ts}\n{text}"

    except Exception as e:
        logger.error(f"Missing persons generation error: {e}")
        return None


def tick_missing_resolutions() -> List[str]:
    """
    Check for expired missing persons. 20% get a 'found' bulletin.
    Returns list of resolution bulletin strings.
    """
    records  = _load_missing()
    now      = datetime.now()
    tower    = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    ts       = f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"
    outputs  = []
    updated  = False

    for r in records:
        if r.get("resolved"):
            continue
        try:
            exp = datetime.fromisoformat(r["expires_at"])
        except Exception:
            continue
        if now < exp:
            continue

        r["resolved"] = True
        updated       = True

        if random.random() < FOUND_CHANCE:
            outcome = random.choice(_FOUND_OUTCOMES)
            # Extract name from first bold text if possible
            import re
            name_match = re.search(r"\*\*MISSING PERSON — (.+?)\*\*", r.get("body", ""))
            name = name_match.group(1) if name_match else "The individual"
            outputs.append(
                f"-# 🕰️ {ts}\n"
                f"🔍 **UPDATE — MISSING PERSONS CASE**\n"
                f"*{name}: {outcome}*"
            )
        # Else: quietly expires — no resolution notice, they're just gone

    if updated:
        _save_missing(records)

    return outputs
