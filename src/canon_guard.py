"""Canon guard -- stop generated prose from rewriting the world's leadership.

A TNN bulletin on 2026-08-13 announced that "Senior Adventurer Aldric Vane" had
been SUSPENDED for smuggling. Aldric Vane is the Guildmaster of the Adventurers
Guild, he is alive, and he was suspended by nobody: the model invented both the
demotion and the crime. Hours earlier an obituary had called Mari Fen his
"spouse" -- the bond graph says Mari Fen's bond is `unrequited` and his actual
spouse is Sera Vane.

This matters more than a bad sentence. Bulletins are persisted to `news_memory`
and read back as context by later prompts (`_recent_memory`), so a single
confabulated demotion becomes world memory and every later bulletin builds on
it. The Adventurers Guild was already run by a corpse for two months because
nothing reconciled the story against the record.

The existing defence was one clause in the roster prompt -- "do NOT kill them in
bulletins" -- which covers exactly one of the many ways to depose someone.

So this module follows the pattern the statblock rewriter established: tell the
model the truth up front (`protected_block`), then GATE the output (`check`),
because instruction alone leaks. Leaders come from `faction_reputation`, the
authoritative record, never from a hardcoded map.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Iterable, Optional

from src.db_api import raw_query

logger = logging.getLogger(__name__)

_CACHE: dict[str, object] = {}
_CACHE_TTL = 600  # seconds; leadership changes are rare but they do happen


# ---------------------------------------------------------------------------
# Who is protected
# ---------------------------------------------------------------------------

def _split_leader(raw: str) -> tuple[str, str]:
    """'Aldric Vane (Guildmaster)' -> ('Aldric Vane', 'Guildmaster').

    Some rows carry no parenthetical ('Sera Voss', 'The Widow') and some carry a
    note rather than a rank ('Brother Thane (whereabouts unknown)'). Return the
    parenthetical as-is and let the caller present it; it is descriptive either
    way, and we never want to guess a title we were not given.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw, ""


def protected_people(force: bool = False) -> dict[str, dict]:
    """Everyone generated prose may not depose, arrest, demote, or bury.

    Keyed by lowercase name. Faction leaders come from `faction_reputation`
    (authoritative) joined to `npcs` for their real rank and status; the Unknown
    Party come from `npc_lifecycle.UNKNOWN_PARTY_MEMBERS`.
    """
    now = time.time()
    if not force and _CACHE.get("people") and now - float(_CACHE.get("people_at", 0)) < _CACHE_TTL:
        return _CACHE["people"]  # type: ignore[return-value]

    people: dict[str, dict] = {}

    try:
        rows = raw_query(
            "SELECT faction_name, leader FROM faction_reputation "
            "WHERE leader IS NOT NULL AND leader <> ''"
        ) or []
    except Exception as exc:
        logger.warning(f"[canon_guard] leader lookup failed: {exc}")
        rows = []

    for row in rows:
        name, paren = _split_leader(str(row.get("leader") or ""))
        if not name:
            continue
        people[name.lower()] = {
            "name": name,
            "title": paren,
            "faction": row.get("faction_name") or "",
            "kind": "leader",
        }

    # Real rank/status off the npcs row, so the prompt states the true title.
    # `rank` and `role` are MySQL 8 reserved words -- backtick or the error
    # points at the next column and reads like nonsense.
    if people:
        try:
            placeholders = ",".join(["%s"] * len(people))
            for row in raw_query(
                f"SELECT name, `rank`, status FROM npcs WHERE LOWER(name) IN ({placeholders})",
                tuple(people.keys()),
            ) or []:
                entry = people.get(str(row.get("name") or "").lower())
                if entry:
                    entry["rank"] = row.get("rank") or entry.get("title") or ""
                    entry["status"] = row.get("status") or "alive"
        except Exception as exc:
            logger.debug(f"[canon_guard] rank lookup failed: {exc}")

    try:
        from src.npc_lifecycle import UNKNOWN_PARTY_MEMBERS
        for name in UNKNOWN_PARTY_MEMBERS:
            people.setdefault(name.lower(), {
                "name": name,
                "title": "",
                "faction": "Unknown Party",
                "kind": "unknown_party",
            })
    except Exception as exc:
        logger.debug(f"[canon_guard] unknown party lookup failed: {exc}")

    _CACHE["people"] = people
    _CACHE["people_at"] = now
    return people


def is_protected(name: str) -> bool:
    return bool(name) and name.strip().lower() in protected_people()


# ---------------------------------------------------------------------------
# What the model is told
# ---------------------------------------------------------------------------

def protected_block(limit: int = 40) -> str:
    """Prompt text: the real titles, and what may not be done to them.

    Stating the true title is half the fix. The suspension bulletin called the
    Guildmaster a "Senior Adventurer" because the roster block never passed his
    rank -- it read `n.get("rank")` from a query that did not select it.
    """
    people = protected_people()
    if not people:
        return ""

    leaders = [p for p in people.values() if p.get("kind") == "leader"]
    leaders.sort(key=lambda p: p.get("faction") or "")
    lines = []
    for p in leaders[:limit]:
        title = p.get("rank") or p.get("title") or "leader"
        lines.append(f"- {p['name']} is the {title} of the {p['faction']} and is alive.")

    party = [p["name"] for p in people.values() if p.get("kind") == "unknown_party"]

    parts = ["STANDING (these people hold their posts RIGHT NOW -- do not contradict):"]
    parts.extend(lines)
    if party:
        parts.append(
            "- The Unknown Party (" + ", ".join(sorted(party)) + ") are the most capable "
            "operatives in the city. They do not lose, get arrested, or die in a news item."
        )
    parts.append(
        "You may NOT write that any person above was killed, died, was arrested, detained, "
        "suspended, expelled, demoted, deposed, replaced, stripped of rank, charged with or "
        "convicted of a crime, or that they are 'former' or 'the late' anything. Do not give "
        "them a rank other than the one listed. Do not marry them off or name a spouse. They "
        "may appear, speak, rule, argue, refuse, and be criticised -- their STANDING is fixed. "
        "If your story needs someone to fall, use a subordinate you invent generically "
        "('a dock supervisor', 'a junior archivist')."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

# Things done TO someone that change their standing. Kept narrow on purpose:
# a leader DOING these ("Captain Korin arrested a smuggler") must not trip.
_STATUS_VERBS = (
    r"suspend(?:ed|s)?|arrest(?:ed|s)?|detain(?:ed|s)?|expel(?:led|s)?|expulsion|"
    r"demot(?:ed|es|ion)|depos(?:ed|es)|oust(?:ed|s)?|remov(?:ed|es)\s+from|"
    r"replac(?:ed|es)|strip(?:ped|s)?\s+of|indict(?:ed|s)?|convict(?:ed|s)?|"
    r"charg(?:ed|es)\s+with|execut(?:ed|es)|assassinat(?:ed|es)|murder(?:ed|s)?|"
    r"kill(?:ed|s)?|die[sd]?|dead|deceas(?:ed|es)|slain|succumb(?:ed|s)?|"
    r"step(?:ped|s)?\s+down|resign(?:ed|s)?|found\s+guilty|stand(?:s)?\s+trial|"
    r"faces?\s+(?:expulsion|removal|charges|trial)"
)

_PASSIVE = re.compile(
    r"\b(?:has|have|had|was|were|is|are|been|being)\b[^.\n]{0,40}?\b(?:" + _STATUS_VERBS + r")\b",
    re.IGNORECASE,
)

# The subject changing state under their own steam -- no auxiliary to key off.
# Deliberately NARROW: the full verb list here would flag "Vane condemned the
# arrests", where the leader is commenting on someone else's downfall.
_INTRANSITIVE = re.compile(
    r"^\W*\b(?:stepped?\s+down|steps\s+down|resign(?:ed|s)?|abdicat(?:ed|es)|"
    r"died|dies|is\s+dead|lies\s+dead|was\s+buried|succumbed|has\s+fallen|"
    r"fled\s+the\s+city|awaits\s+trial|stands\s+trial|"
    r"faces?\s+(?:expulsion|removal|charges|trial|dismissal|the\s+noose))\b",
    re.IGNORECASE,
)

# The name as the OBJECT. Anchored to the end of the preceding text so the verb
# has to be adjacent -- otherwise "mourned the death of the guard, and Aldric
# Vane spoke" trips on a death that was never his.
_ACTIVE_TAIL = re.compile(
    r"\b(?:" + _STATUS_VERBS + r")\s+(?:the\s+|a\s+|an\s+)?$", re.IGNORECASE
)
_OF_TAIL = re.compile(
    r"\b(?:death|demise|passing|funeral|burial|obituary|murder|killing|arrest|"
    r"suspension|removal|expulsion|conviction|indictment)\s+of\s+$",
    re.IGNORECASE,
)

_FORMER = re.compile(r"\b(?:former|ex-|late|outgoing|disgraced|deposed)\b", re.IGNORECASE)
# Appositive demotion: "Aldric Vane, former Guildmaster and champion..."
_FORMER_APPOSITIVE = re.compile(r"^\W{0,3}\s*(?:former|ex-|late|outgoing|disgraced|deposed)\b", re.IGNORECASE)
_SPOUSE = re.compile(r"\b(?:spouse|husband|wife|widow|widower|married|wedding)\b", re.IGNORECASE)


_NAME_RE_CACHE: dict[str, re.Pattern] = {}


def _name_re(key: str) -> re.Pattern:
    """Whole-name match: 'The Ward' must not match 'The Wardens', nor 'Pell'
    match 'Pellar'. The trailing boundary rejects word characters only, so the
    possessive still matches -- "the late Aldric Vane's apprentice" is exactly
    the sentence we are hunting.
    """
    pat = _NAME_RE_CACHE.get(key)
    if pat is None:
        pat = re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)", re.IGNORECASE)
        _NAME_RE_CACHE[key] = pat
    return pat


def _sentences(text: str) -> Iterable[str]:
    for chunk in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        chunk = chunk.strip()
        if chunk:
            yield chunk


def check(text: str, allow: Optional[Iterable[str]] = None) -> list[str]:
    """Return human-readable violations; empty list means the text is safe.

    Sentence-scoped so a bulletin can still say "Guildmaster Vane condemned the
    arrests" without tripping -- the protected name and the status verb have to
    land in the same sentence, with the name on the receiving end.
    """
    if not text:
        return []

    people = protected_people()
    if not people:
        return []
    exempt = {a.strip().lower() for a in (allow or []) if a}

    violations: list[str] = []
    for sentence in _sentences(text):
        low = sentence.lower()
        for key, person in people.items():
            if key in exempt or key not in low:
                continue
            # Word-boundary match, or "The Ward" fires on "The Wardens are
            # investigating" -- an organisation doing its job, not a death.
            m = _name_re(key).search(sentence)
            if not m:
                continue
            name = person["name"]
            # Where does the name sit relative to the status change?
            before = sentence[:m.start()]
            after = sentence[m.end():]

            hit = None
            if _PASSIVE.search(after[:120]):
                hit = "passive status change after the name"
            elif _INTRANSITIVE.search(after[:80]):
                hit = "steps down / dies of their own accord"
            elif _ACTIVE_TAIL.search(before) or _OF_TAIL.search(before):
                # "...suspended Aldric Vane" / "the death of Aldric Vane"
                hit = "status change acting on the name"
            elif _FORMER.search(before[-40:]) or _FORMER_APPOSITIVE.search(after[:30]):
                hit = "written as former/late"
            elif _SPOUSE.search(after[:100]) or _SPOUSE.search(before[-60:]):
                hit = "asserts a marriage/spouse"

            if hit:
                violations.append(f"{name} ({person.get('faction') or 'protected'}): {hit} -- {sentence[:160]}")
                break  # one violation per sentence is enough to reject it

    return violations


def is_clean(text: str, allow: Optional[Iterable[str]] = None) -> bool:
    return not check(text, allow=allow)


def reject_reason(text: str, allow: Optional[Iterable[str]] = None) -> str:
    """Formatted for a retry prompt, so the model is told what it broke."""
    violations = check(text, allow=allow)
    if not violations:
        return ""
    return (
        "Your previous draft contradicted established canon:\n"
        + "\n".join(f"  - {v}" for v in violations[:5])
        + "\nRewrite it. These people keep their posts, their lives, and their titles."
    )
