"""
tower_news_voices.py -- give the world a voice that isn't the narrator's.

The news feed had exactly one register. 2383 rows of `bulletin`, 108
`council_ruling`, 20 `rift` -- all of it reported ABOUT the Undercity, none of it
spoken BY anyone who lives there. Meanwhile the roster carries motivations,
secrets, grudges, marriages and fresh graves that nobody ever hears about.

This module turns world state into people talking:

    obituary()      someone is dead. The person who loved them most speaks. In
                    the Undercity that is not a closing statement -- the body is
                    still raisable, and the widow knows it.
    interview()     TTN puts a microphone in front of an NPC about a mission
                    outcome that hit their faction.
    forum_thread()  two NPCs who disagree, arguing in public, in character.
    union_notice()  courtship, partnership, marriage -- the good news.

Every one is voiced from `npc_dossier.build_dossier()`, so what a character says
is constrained by who they actually are and what has actually happened to them.
Nothing here invents biography; it performs the biography the world already holds.

All generation runs through `agents.generate_bulletin` (the existing rail, which
already handles the model, the busy-check and the context floor) and is persisted
with `add_news_entry(news_type=...)` so these become searchable world memory and
feed back into later prompts.
"""
from __future__ import annotations

import random
from typing import Any, Optional

from src.db_api import raw_query, add_news_entry
from src.log import logger

# News types this module introduces. Kept distinct so the feed can be filtered,
# and so `_pick_varied_bulletin_type` style variety logic can see them.
TYPE_OBITUARY = "obituary"
TYPE_INTERVIEW = "interview"
TYPE_FORUM = "forum"
TYPE_UNION = "union"


def _dossier_for(npc: dict) -> str:
    try:
        from src.npc_dossier import build_dossier, dossier_block
        return dossier_block({"id": 0, "faction": npc.get("faction") or ""}, npc)
    except Exception as exc:
        logger.debug(f"[voices] dossier unavailable: {exc}")
        return ""


_CANON_CACHE: dict[str, str] = {}


def canon_anchor() -> str:
    """The real factions and districts, so the model stops making them up.

    An ungrounded obituary invented a 'Drowned Ledger' tavern, a smuggler named
    Kael Vey, the 'Bloodstone Arena' and an entire faction called the 'Deliberate
    Few'. None exist. Naming a place or a faction that is not in the gazetteer
    poisons world memory, because these bulletins are persisted and read back as
    context by later prompts.
    """
    if "block" in _CANON_CACHE:
        return _CANON_CACHE["block"]

    factions = [r["faction_name"] for r in (raw_query(
        "SELECT faction_name FROM faction_reputation ORDER BY faction_name") or [])
        if r.get("faction_name")]
    districts = [r["district"] for r in (raw_query(
        "SELECT DISTINCT district FROM area_profiles "
        "WHERE district IS NOT NULL AND district <> '' ORDER BY district LIMIT 40") or [])
        if r.get("district")]

    parts = []
    if factions:
        parts.append("The ONLY factions that exist: " + ", ".join(factions) + ".")
    if districts:
        parts.append("The ONLY districts/areas that exist: " + ", ".join(districts) + ".")
    parts.append(
        "Do NOT invent factions, districts, taverns, arenas, or named people. If you "
        "need a place or a person who is not given to you, refer to it generically "
        "('a tenement stairwell', 'her second', 'the contact') rather than naming it."
    )
    block = "\n".join(parts)
    _CANON_CACHE["block"] = block
    return block


def _recent_memory(limit: int = 6) -> str:
    rows = raw_query(
        "SELECT bulletin_text FROM news_memory ORDER BY id DESC LIMIT %s", (int(limit),)
    ) or []
    return "\n".join(str(r.get("bulletin_text") or "")[:220] for r in rows)


async def _write(news_type: str, instruction: str, context: str, max_lines: int = 6) -> Optional[str]:
    from src.agents import generate_bulletin

    text = await generate_bulletin(
        news_type=news_type,
        instruction=instruction + "\n\nCANON (do not contradict, do not extend):\n"
                    + canon_anchor(),
        memory_context=_recent_memory(),
        additional_context=context,
        max_lines=max_lines,
    )
    if not text:
        return None
    try:
        add_news_entry(bulletin_text=text, facts=context[:2000], news_type=news_type)
    except Exception as exc:
        logger.warning(f"[voices] could not persist {news_type}: {exc}")
    return text


# ---------------------------------------------------------------------------
# Obituary -- and in this city an obituary is a question, not a full stop
# ---------------------------------------------------------------------------

async def obituary(dead: dict, mourners: list[dict]) -> Optional[str]:
    """Death notice voiced by whoever was closest to them.

    `npc_bonds.bereave()` already ranked the mourners, so the spouse speaks
    before the rival. Crucially the piece must NOT read as final: until the Tower
    absorbs the soul this person can be raised, reincarnated, or come back wrong,
    and the people who loved them know exactly that.
    """
    name = str(dead.get("name") or "Someone")
    speaker = mourners[0] if mourners else None
    others = ", ".join(f"{m['name']} ({m['bond_type']})" for m in mourners[1:4])

    if speaker:
        speaker_row = raw_query(
            "SELECT * FROM npcs WHERE id=%s LIMIT 1", (int(speaker["npc_id"]),)
        ) or []
        voice = _dossier_for(speaker_row[0]) if speaker_row else ""
        wants_back = speaker.get("stance") == "seeking_return"
        stance_line = (
            f"{speaker['name']} wants them back and is not hiding it. The piece should "
            f"carry that as need, not as a press release."
            if wants_back else
            f"{speaker['name']} is not sorry, and is careful about how they say so."
        )
        instruction = (
            f"Tower News Network death notice for {name}"
            + (f", {dead.get('rank')} of the {dead.get('faction')}" if dead.get("faction") else "")
            + f". Cause: {dead.get('death_cause') or 'unclear'}.\n"
            f"The notice is carried by {speaker['name']}, their {speaker['bond_type']}. "
            f"Quote {speaker['name']} directly at least twice, in their own cadence.\n"
            f"{stance_line}\n"
            f"IMPORTANT: in the Undercity the dead are not finished. The body is still "
            f"within reach of a raising, and everyone reading this knows it. End on what "
            f"{speaker['name']} intends to do about that -- petition, pay, pray, or refuse. "
            f"Do not write a tidy eulogy; write a person who has not accepted it yet.\n"
            + (f"Also grieving: {others}.\n" if others else "")
            + "Two short paragraphs. Specific over sentimental. No emoji."
        )
        context = f"THE BEREAVED:\n{voice}\n\nTHE DEAD: {name}. {dead.get('description') or ''}"
    else:
        instruction = (
            f"Tower News Network death notice for {name}"
            + (f" of the {dead.get('faction')}" if dead.get("faction") else "")
            + f". Cause: {dead.get('death_cause') or 'unclear'}.\n"
            f"Nobody has come forward to claim the body. Write that plainly -- an "
            f"unclaimed death in a city where the dead can still be bought back is its "
            f"own kind of verdict. Two short paragraphs. No emoji."
        )
        context = f"THE DEAD: {name}. {dead.get('description') or ''}"

    return await _write(TYPE_OBITUARY, instruction, context)


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------

async def interview(npc: dict, outcome: Optional[dict] = None) -> Optional[str]:
    """TTN puts a microphone in front of someone about something that hit them."""
    name = str(npc.get("name") or "the subject")
    voice = _dossier_for(npc)

    if outcome:
        subject = (
            f"the recent contract '{outcome.get('mission_title')}' "
            f"({outcome.get('result')}). What stuck: "
            f"{str(outcome.get('notable_moments') or '')[:300]}. "
            f"Unresolved: {str(outcome.get('loose_threads') or '')[:200]}."
        )
    else:
        subject = "their work, their faction, and what the Undercity is getting wrong."

    instruction = (
        f"Tower News Network interview with {name}"
        + (f", {npc.get('rank')} of the {npc.get('faction')}" if npc.get("faction") else "")
        + f". Subject: {subject}\n"
        f"Format: 3 to 4 exchanges. The reporter's questions are short and a little "
        f"impertinent. {name}'s answers are in THEIR voice, using the dossier -- they "
        f"should dodge at least one question, and let one answer get away from them and "
        f"reveal more than they meant.\n"
        f"They must never state their secret outright, but the interview should feel like "
        f"it is circling something.\n"
        f"Label speakers as 'TTN:' and '{name}:'. No emoji."
    )
    return await _write(TYPE_INTERVIEW, instruction, f"THE SUBJECT:\n{voice}", max_lines=14)


# ---------------------------------------------------------------------------
# Forum -- the Undercity argues with itself
# ---------------------------------------------------------------------------

async def forum_thread(a: dict, b: dict, topic: str) -> Optional[str]:
    """Two NPCs who genuinely disagree, arguing in public."""
    voice_a, voice_b = _dossier_for(a), _dossier_for(b)
    instruction = (
        f"A public forum thread on the Tower boards. Topic: {topic}\n"
        f"{a.get('name')} ({a.get('faction')}) and {b.get('name')} ({b.get('faction')}) "
        f"disagree, and they have history.\n"
        f"Format: 4 to 6 posts, alternating, each prefixed with the poster's handle. "
        f"They talk past each other at least once. One of them lands a real point. "
        f"Nobody is converted. Somebody gets personal and immediately regrets it, or "
        f"doubles down.\n"
        f"Keep each post to a few lines. Write it like people on a board, not like "
        f"speeches. No emoji."
    )
    context = f"POSTER A:\n{voice_a}\n\nPOSTER B:\n{voice_b}"
    return await _write(TYPE_FORUM, instruction, context, max_lines=16)


# ---------------------------------------------------------------------------
# The good news
# ---------------------------------------------------------------------------

async def union_notice(a: dict, b: dict, kind: str = "partner") -> Optional[str]:
    """Courtship, partnership, or marriage. The world needs some of this."""
    headline = {
        "courting": "have been seen keeping company",
        "partner": "are together",
        "spouse": "were married",
    }.get(kind, "are together")

    instruction = (
        f"A short Tower News Network social notice: {a.get('name')} "
        f"({a.get('faction')}) and {b.get('name')} ({b.get('faction')}) {headline}.\n"
        f"Write it warm but not saccharine -- this is a hard city and that is precisely "
        f"why it is worth reporting. One concrete detail about how they met or where they "
        f"are seen. If their factions make this awkward or dangerous, say so lightly.\n"
        f"Two or three lines. No emoji."
    )
    context = f"A:\n{_dossier_for(a)}\n\nB:\n{_dossier_for(b)}"
    return await _write(TYPE_UNION, instruction, context, max_lines=4)


# ---------------------------------------------------------------------------
# Choosing what the world talks about today
# ---------------------------------------------------------------------------

def _fresh_unmourned_dead(limit: int = 3) -> list[dict]:
    """Recently dead who have not had a notice, newest first."""
    return raw_query(
        "SELECT n.* FROM npcs n WHERE n.status = 'dead' "
        "AND n.deceased_at IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM news_memory m "
        "                WHERE m.news_type = %s AND m.facts LIKE CONCAT('%%', n.name, '%%')) "
        "ORDER BY n.deceased_at DESC LIMIT %s",
        (TYPE_OBITUARY, int(limit)),
    ) or []


def _interview_candidate() -> tuple[Optional[dict], Optional[dict]]:
    rows = raw_query(
        "SELECT * FROM mission_outcomes ORDER BY id DESC LIMIT 12"
    ) or []
    random.shuffle(rows)
    for outcome in rows:
        faction = outcome.get("faction")
        if not faction:
            continue
        npcs = raw_query(
            "SELECT * FROM npcs WHERE faction=%s AND status='alive' ORDER BY RAND() LIMIT 1",
            (faction,),
        ) or []
        if npcs:
            return npcs[0], outcome
    return None, None


def _forum_pair() -> tuple[Optional[dict], Optional[dict], str]:
    """Prefer people who actually have a grudge on the books."""
    hostile = raw_query(
        "SELECT b.npc_a_id, b.npc_b_id FROM npc_bonds b "
        "JOIN npcs a ON a.id=b.npc_a_id JOIN npcs c ON c.id=b.npc_b_id "
        "WHERE b.bond_type IN ('rival','enemy') AND b.status='active' "
        "AND a.status='alive' AND c.status='alive' ORDER BY RAND() LIMIT 1"
    ) or []
    if hostile:
        a = (raw_query("SELECT * FROM npcs WHERE id=%s", (hostile[0]["npc_a_id"],)) or [None])[0]
        b = (raw_query("SELECT * FROM npcs WHERE id=%s", (hostile[0]["npc_b_id"],)) or [None])[0]
    else:
        pair = raw_query(
            "SELECT * FROM npcs WHERE status='alive' ORDER BY RAND() LIMIT 2"
        ) or []
        a, b = (pair + [None, None])[:2]

    if not a or not b:
        return None, None, ""

    threads = raw_query(
        "SELECT mission_title, loose_threads FROM mission_outcomes "
        "WHERE loose_threads IS NOT NULL AND loose_threads <> '' "
        "ORDER BY id DESC LIMIT 8"
    ) or []
    if threads:
        pick = random.choice(threads)
        topic = f"{pick['mission_title']} -- {str(pick['loose_threads'])[:180]}"
    else:
        topic = "who is actually responsible for the state of the lower districts"
    return a, b, topic


async def daily_voices(max_items: int = 2) -> list[tuple[str, str]]:
    """Produce today's human-interest items. Returns [(news_type, text), ...].

    Capped per pass so a long outage drains as a stream rather than a storm, per
    the outage-backlog rule. Obituaries always win the slot -- a death that goes
    unremarked is the thing that made the world feel dead in the first place.
    """
    out: list[tuple[str, str]] = []

    for dead in _fresh_unmourned_dead(limit=max_items):
        try:
            from src.npc_bonds import get_bonds
            mourners = [
                {"npc_id": b["npc_b_id"], "name": b["other_name"],
                 "bond_type": b["bond_type"], "stance": b.get("stance"),
                 "strength": b.get("strength") or 0}
                for b in get_bonds(int(dead["id"]), active_only=False)
                if b.get("status") in ("mourning", "active")
            ]
        except Exception:
            mourners = []
        text = await obituary(dead, mourners)
        if text:
            out.append((TYPE_OBITUARY, text))
        if len(out) >= max_items:
            return out

    # Nobody newly dead: let the living talk.
    choice = random.choice(["interview", "forum", "union"])

    if choice == "interview":
        npc, outcome = _interview_candidate()
        if npc:
            text = await interview(npc, outcome)
            if text:
                out.append((TYPE_INTERVIEW, text))
    elif choice == "forum":
        a, b, topic = _forum_pair()
        if a and b:
            text = await forum_thread(a, b, topic)
            if text:
                out.append((TYPE_FORUM, text))
    else:
        pairs = raw_query(
            "SELECT b.npc_a_id, b.npc_b_id, b.bond_type FROM npc_bonds b "
            "WHERE b.bond_type IN ('courting','partner','spouse') AND b.status='active' "
            "AND b.started_at > DATE_SUB(NOW(), INTERVAL 7 DAY) ORDER BY RAND() LIMIT 1"
        ) or []
        if pairs:
            a = (raw_query("SELECT * FROM npcs WHERE id=%s", (pairs[0]["npc_a_id"],)) or [None])[0]
            b = (raw_query("SELECT * FROM npcs WHERE id=%s", (pairs[0]["npc_b_id"],)) or [None])[0]
            if a and b:
                text = await union_notice(a, b, pairs[0]["bond_type"])
                if text:
                    out.append((TYPE_UNION, text))

    return out
