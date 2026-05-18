"""
fallen_adventurers.py — Day of the Fallen bulletin

Fires once per year during the Jul 8-16 window (anchor: July 15).
Captain Havel Korin of the Wardens of Ash reads the names of adventurers
and wardens who have died since the last reading at the Sorrow Wall,
Grand Forum.

Tracks last firing year via global_state key 'fallen_day_year'.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from src.db_api import get_global_state, set_global_state, raw_query

logger = logging.getLogger(__name__)

TOWER_YEAR_OFFSET = 10

_WINDOW_START = (7,  8)   # July 8
_WINDOW_END   = (7, 16)   # July 16


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _in_fallen_day_window() -> bool:
    today = datetime.now()
    pos   = (today.month, today.day)
    return _WINDOW_START <= pos <= _WINDOW_END


def _already_fired_this_year() -> bool:
    try:
        val = get_global_state("fallen_day_year")
        if val:
            return str(val).strip() == str(datetime.now().year)
    except Exception:
        pass
    return False


def _mark_fired() -> None:
    try:
        set_global_state("fallen_day_year", str(datetime.now().year))
    except Exception as e:
        logger.warning(f"🕯️ [FALLEN] Could not mark fired: {e}")


# ---------------------------------------------------------------------------
# Data pull — dead NPCs
# ---------------------------------------------------------------------------

def _get_fallen(since_year: Optional[int] = None) -> list[dict]:
    """
    Return dead NPCs from the DB.
    If since_year is given, only returns those with deceased_at in that year
    or later; otherwise returns all dead NPCs.
    """
    try:
        if since_year:
            rows = raw_query(
                "SELECT name, faction, role, deceased_at, data_json "
                "FROM npcs WHERE status = 'dead' AND "
                "(deceased_at IS NULL OR YEAR(deceased_at) >= %s) "
                "ORDER BY deceased_at ASC",
                (since_year,),
            ) or []
        else:
            rows = raw_query(
                "SELECT name, faction, role, deceased_at, data_json "
                "FROM npcs WHERE status = 'dead' "
                "ORDER BY deceased_at ASC"
            ) or []

        result = []
        for r in rows:
            dj = {}
            if r.get("data_json"):
                try:
                    dj = json.loads(r["data_json"])
                except Exception:
                    pass
            result.append({
                "name":        r["name"],
                "faction":     r.get("faction") or "Independent",
                "role":        (r.get("role") or "").split(".")[0].strip()[:80],
                "deceased_at": r.get("deceased_at"),
                "cause":       dj.get("death_cause") or dj.get("cause_of_death") or "",
            })
        return result
    except Exception as e:
        logger.error(f"🕯️ [FALLEN] DB query failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Bulletin generation
# ---------------------------------------------------------------------------

async def generate_fallen_bulletin() -> Optional[str]:
    """
    Generate the Day of the Fallen bulletin in Havel Korin's voice.
    Uses KimiAgent for prose quality. Returns formatted Discord text or None.
    """
    from src.agents import generate_with_kimi

    # Pull the last year we fired to decide which names are "new" this reading
    last_year_val = get_global_state("fallen_day_year")
    if last_year_val:
        try:
            since_year = int(str(last_year_val).strip())
        except ValueError:
            since_year = None
    else:
        since_year = None   # first ever reading — include everyone

    fallen = _get_fallen(since_year=since_year)

    if not fallen:
        # No new dead since last reading — Havel notes the silence is the good news
        fallen_lines = "(none recorded since the last reading — a rare mercy)"
    else:
        fallen_lines = "\n".join(
            f"- **{f['name']}** — {f['faction']}"
            + (f", *{f['role'][:60]}*" if f["role"] else "")
            for f in fallen
        )

    now   = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    ts    = f"{now.strftime('%Y-%m-%d %H:%M')} | Tower: {tower.strftime('%d %b %Y, %H:%M')}"
    tower_year = tower.year

    prompt = f"""You are writing an in-world bulletin for the Undercity Dispatch.

CONTEXT:
The Undercity is a sealed city under a Dome. There is no real sky. The city is dense,
mixed-species, dark fantasy / cyberpunk in tone. It is NOT grimdark for its own sake —
it has community, pride, and dark humour alongside real danger.

TODAY IS the Day of the Fallen — an annual civic observance (Tower year {tower_year}).
Captain Havel Korin of the Wardens of Ash stands at the Sorrow Wall in the Grand Forum
and reads aloud the names of those lost since the last reading.

The Sorrow Wall: a long marble wall in the Grand Forum etched with the name of every
citizen lost to Rift events and duty. The Adventurers Guild memorial wall at Guild Spires
records fallen adventurers specifically. Both are referenced today.

NAMES TO BE READ THIS YEAR:
{fallen_lines}

CAPTAIN HAVEL KORIN — character notes:
- Weathered, grey-streaked hair, old scars he never explains
- Gruff but genuinely cares about those under his command
- Commands the Outer Wall Warden garrison
- Works closely with the Adventurers Guild on joint ops
- A man of few words — when he speaks formally it carries weight

WRITE A BULLETIN formatted as a Warden of Ash public notice.
Structure:
1. Brief header / dateline — Captain Korin, Day of the Fallen, location (Sorrow Wall, Grand Forum)
2. Short opening statement from Korin (2-3 sentences, his voice — gruff, respectful, no flourish)
3. The names — list them clearly with faction
4. A brief closing from Korin (1-2 sentences — not sentimental, but real)
5. A one-line civic notice that the Sorrow Wall has been updated and the Guild memorial wall
   will be updated at Guild Spires before sundown

FORMAT RULES:
- Use Discord markdown: **bold**, *italic*, -# for subtext lines
- Total length: 300-500 words
- No preamble in your response — output the bulletin text only
- Tone: civic, honest, measured. Not a speech. A duty performed.
- Do NOT invent additional deaths or names beyond what is listed above."""

    try:
        from src.resource_cop import wait_for_ollama_turn
        decision = await wait_for_ollama_turn("fallen_day_bulletin", track="primary")
        if not decision.run_now:
            logger.warning(f"🕯️ [FALLEN] Ollama deferred by resource cop: {decision.reason}")
            return None

        text = await generate_with_kimi(prompt, temperature=0.7)
        if not text:
            logger.warning("🕯️ [FALLEN] KimiAgent returned empty response")
            return None
        return f"-# 🕰️ {ts}\n{text}"
    except Exception as e:
        logger.error(f"🕯️ [FALLEN] Generation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Tick — called from aclient news_feed_loop
# ---------------------------------------------------------------------------

async def check_fallen_day_tick() -> Optional[str]:
    """
    Returns the Day of the Fallen bulletin text if today is in the Jul 8-16
    window and it hasn't fired yet this calendar year. Returns None otherwise.
    """
    if not _in_fallen_day_window():
        return None
    if _already_fired_this_year():
        logger.debug("🕯️ [FALLEN] Already fired this year — skipping")
        return None

    logger.info("🕯️ [FALLEN] Day of the Fallen window active — generating bulletin")
    from src.resource_cop import start_pipeline, finish_pipeline
    run = await start_pipeline("fallen_day_bulletin", phase="generating")
    try:
        bulletin = await generate_fallen_bulletin()
    except Exception as e:
        await finish_pipeline(run.run_id, status="failed")
        logger.error(f"🕯️ [FALLEN] Unexpected error: {e}")
        return None
    await finish_pipeline(run.run_id, status="finished" if bulletin else "empty")
    if bulletin:
        _mark_fired()
        logger.info("🕯️ [FALLEN] Bulletin generated and year marked")
    return bulletin
