"""
npc_dossier.py -- cast real NPCs into missions and hand the model everything
that makes them a person.

The problem this solves: module dialog was dry because the generator knew almost
nothing about the person speaking. `scene_dialogs._npc_context()` read four thin
fields (name, rank, a 160-char quote, faction) and dropped motivation, secret,
oracle_notes, relationships, lived history, faction standing, and every downstream
consequence the world had already recorded. Worse, missions carry a free-text
`contact` string like "Guild Liaison Varek at Ironhold Outpost", and `get_npc()` is
an exact-name lookup, so it resolved to nothing at all -- the module invented a
stranger and asked a model to improvise for a person with no past.

Meanwhile the database holds 854 npc_history events, 109 NPCs with relationships,
105 with secrets, and 761 mission_outcomes. Nothing was reaching the prompt.

Two jobs here:

  cast_mission_contact()  resolve the mission's free-text contact to a REAL npcs
                          row (titles and "at <place>" suffixes stripped, faction
                          preferred), and persist the casting in `mission_cast` so
                          the same face recurs across sessions.

  dossier_block()         assemble the actor's dossier: who they are, what they
                          want, what they are hiding, who they are tied to, what
                          they have lived through, where their faction stands, and
                          what the world just did to them.

This is the butterfly effect reaching the dialog layer. Per CLAUDE.md, dialog beats
worth remembering go back into `npc_history` via add_npc_history_event() rather than
into a new table -- prefer existing world systems.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from src.db_api import raw_query, raw_execute
from src.log import logger

# Honorifics and job titles that get glued onto a contact string. Stripping these
# is what turns "Guild Liaison Varek at Ironhold Outpost" into "Varek".
_TITLES = (
    "guild liaison", "liaison", "quartermaster", "foreman", "overseer", "warden",
    "sergeant", "captain", "commander", "lieutenant", "marshal", "inspector",
    "magistrate", "councillor", "councilor", "archivist", "curator", "broker",
    "handler", "envoy", "emissary", "ambassador", "high priest", "priest",
    "brother", "sister", "father", "mother", "doctor", "dr", "professor",
    "master", "mistress", "lord", "lady", "chief", "boss", "elder", "scribe",
    "steward", "sentinel", "keeper", "agent", "operative", "contact",
)

_STOP_TOKENS = {"the", "of", "at", "in", "on", "and", "a", "an"}


def _plain(text: Any, limit: int = 0) -> str:
    """Strip Discord presentation out of stored world text.

    `mission_outcomes.notable_moments` holds the bulletin as it was POSTED --
    emoji, **bold**, *italics*, headers. That is presentation, not character
    material, and feeding it to a model teaches it to write press releases.
    """
    s = str(text or "")
    s = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", s)  # emoji
    s = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", s)                    # bold/italic
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.MULTILINE)              # headers
    s = re.sub(r"[`_~>]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" -—:|")
    return s[:limit].strip() if limit else s


def _strip_contact_string(raw: str) -> str:
    """'Guild Liaison Varek at Ironhold Outpost' -> 'Varek'."""
    text = (raw or "").strip()
    if not text:
        return ""

    # Drop a trailing location clause: " at X", " of X", " in X", " from X".
    text = re.split(r"\s+(?:at|of|in|from|with)\s+", text, maxsplit=1)[0].strip()

    low = text.lower()
    for title in sorted(_TITLES, key=len, reverse=True):
        if low.startswith(title + " "):
            text = text[len(title):].strip()
            low = text.lower()
            break

    return text.strip(" ,.-")


def _name_tokens(text: str) -> set[str]:
    return {
        t for t in re.split(r"[^A-Za-z']+", (text or "").lower())
        if t and t not in _STOP_TOKENS and t not in _TITLES and len(t) > 2
    }


def resolve_npc(contact: str, faction: str = "") -> Optional[dict[str, Any]]:
    """Best real `npcs` row for a free-text contact string, or None.

    Tries exact name, then case-insensitive, then a stripped name, then token
    overlap. Living NPCs and same-faction NPCs win ties -- a dead contact should
    not be handing out contracts.
    """
    contact = (contact or "").strip()
    if not contact or contact.lower() in ("your contact", "unknown", "none", "n/a"):
        return None

    def _q(sql: str, params: tuple) -> list[dict]:
        try:
            return raw_query(sql, params) or []
        except Exception as exc:
            logger.debug(f"[dossier] lookup failed: {exc}")
            return []

    rows = _q("SELECT * FROM npcs WHERE name = %s LIMIT 1", (contact,))
    if rows:
        return rows[0]

    rows = _q("SELECT * FROM npcs WHERE LOWER(name) = LOWER(%s) LIMIT 1", (contact,))
    if rows:
        return rows[0]

    stripped = _strip_contact_string(contact)
    if stripped and stripped.lower() != contact.lower():
        rows = _q("SELECT * FROM npcs WHERE LOWER(name) = LOWER(%s) LIMIT 1", (stripped,))
        if rows:
            return rows[0]
        rows = _q("SELECT * FROM npcs WHERE name LIKE %s LIMIT 5", (f"%{stripped}%",))
        if rows:
            return rows[0]

    # Token overlap across the roster: "Varek" should find "Varek Thorne".
    wanted = _name_tokens(stripped or contact)
    if not wanted:
        return None

    candidates = _q(
        "SELECT * FROM npcs WHERE status = %s ORDER BY name", ("alive",)
    )
    best, best_score = None, 0
    for row in candidates:
        score = len(wanted & _name_tokens(row.get("name", "")))
        if not score:
            continue
        if faction and str(row.get("faction") or "").lower() == faction.lower():
            score += 1
        if score > best_score:
            best, best_score = row, score

    # A single shared token is usually just a shared surname. "Jax Ironclaw"
    # matching "Elara Ironclaw" of a different faction is a DIFFERENT person, and
    # silently casting them is worse than falling back to the employing faction.
    # Demand either two name tokens or one token plus a faction agreement.
    return best if best_score >= 2 else None


_SCHEMA_READY = False


def cast_mission_contact(mission: dict) -> Optional[dict[str, Any]]:
    """Resolve (and remember) which real NPC is this mission's contact.

    A previously recorded casting always wins, so the same face shows up whenever
    the mission is regenerated or revisited.
    """
    global _SCHEMA_READY
    if not _SCHEMA_READY:
        # Nothing else calls ensure_schema(), so a fresh install would silently
        # fail every casting write until someone noticed.
        ensure_schema()
        _SCHEMA_READY = True

    mission_id = mission.get("id")

    if mission_id:
        rows = raw_query(
            "SELECT n.* FROM mission_cast c JOIN npcs n ON n.id = c.npc_id "
            "WHERE c.mission_id = %s AND c.role_in_mission = %s LIMIT 1",
            (int(mission_id), "contact"),
        ) or []
        if rows:
            return rows[0]

    npc = resolve_npc(
        str(mission.get("contact") or ""),
        str(mission.get("faction") or ""),
    )

    # Nothing matched: cast a living member of the employing faction instead of
    # inventing a stranger with no history.
    if not npc and mission.get("faction"):
        rows = raw_query(
            "SELECT * FROM npcs WHERE faction = %s AND status = %s "
            "ORDER BY RAND() LIMIT 1",
            (str(mission["faction"]), "alive"),
        ) or []
        npc = rows[0] if rows else None

    if npc and mission_id:
        try:
            raw_execute(
                "INSERT INTO mission_cast (mission_id, npc_id, role_in_mission) "
                "VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE npc_id = VALUES(npc_id)",
                (int(mission_id), int(npc["id"]), "contact"),
            )
        except Exception as exc:
            logger.debug(f"[dossier] could not record casting: {exc}")

    return npc


# ---------------------------------------------------------------------------
# The dossier
# ---------------------------------------------------------------------------

def _history(npc_id: int, limit: int = 6) -> list[dict]:
    return raw_query(
        "SELECT event_date, event_type, body FROM npc_history "
        "WHERE npc_id = %s ORDER BY event_date DESC, id DESC LIMIT %s",
        (int(npc_id), int(limit)),
    ) or []


def _revealed(npc_id: int) -> list[str]:
    rows = raw_query(
        "SELECT secret FROM npc_revealed_secrets WHERE npc_id = %s", (int(npc_id),)
    ) or []
    return [str(r["secret"]) for r in rows if r.get("secret")]


def _bonds_summary(npc_id: int) -> str:
    try:
        from src.npc_bonds import bonds_block
        return bonds_block(int(npc_id))
    except Exception:
        return ""


def _open_losses(npc_id: int) -> list[dict]:
    """Deaths this person has NOT finished grieving.

    A death is only provisional here, so a mourning bond is live material: they
    are hoping, bargaining, or making sure the grave holds. That belongs in the
    scene, not in a footnote.
    """
    try:
        return raw_query(
            "SELECT b.bond_type, b.stance, d.name "
            "FROM npc_bonds b JOIN npcs d ON d.id = b.npc_a_id "
            "WHERE b.npc_b_id = %s AND b.status = 'mourning' "
            "ORDER BY b.strength DESC LIMIT 3",
            (int(npc_id),),
        ) or []
    except Exception:
        return []


def _faction_standing(faction: str) -> Optional[dict]:
    if not faction:
        return None
    rows = raw_query(
        "SELECT faction_name, reputation_score, tier, leader, motto, alignment, "
        "description FROM faction_reputation WHERE faction_name = %s LIMIT 1",
        (faction,),
    ) or []
    return rows[0] if rows else None


def _recent_consequences(faction: str, limit: int = 3) -> list[dict]:
    """What the world has recently done to (or because of) this faction.

    `notable_moments` and `loose_threads` are the useful columns here -- they are
    where the resolution hooks record the human detail, which is exactly the
    material a person would still be carrying around.
    """
    if not faction:
        return []
    return raw_query(
        "SELECT mission_title, result, notable_moments, key_decisions, "
        "loose_threads, npcs_killed FROM mission_outcomes "
        "WHERE faction = %s OR opposing_faction = %s ORDER BY id DESC LIMIT %s",
        (faction, faction, int(limit)),
    ) or []


def build_dossier(npc: dict, mission: Optional[dict] = None) -> dict[str, Any]:
    """Everything known about this person, assembled for performance."""
    npc_id = int(npc.get("id") or 0)
    faction = str(npc.get("faction") or "")

    return {
        "name":          str(npc.get("name") or "Unknown"),
        "faction":       faction,
        "rank":          str(npc.get("rank") or ""),
        "role":          str(npc.get("role") or ""),
        "species":       str(npc.get("species") or ""),
        "quote":         str(npc.get("quote") or ""),
        "motivation":    str(npc.get("motivation") or ""),
        "secret":        str(npc.get("secret") or ""),
        "oracle_notes":  str(npc.get("oracle_notes") or ""),
        "relationships": str(npc.get("relationships") or ""),
        "party_name":    str(npc.get("party_name") or ""),
        "history":       _history(npc_id) if npc_id else [],
        "revealed":      _revealed(npc_id) if npc_id else [],
        "bonds":         _bonds_summary(npc_id) if npc_id else "",
        "grieving":      _open_losses(npc_id) if npc_id else [],
        "standing":      _faction_standing(faction),
        "consequences":  _recent_consequences(faction),
    }


def dossier_block(mission: dict, npc: Optional[dict] = None) -> str:
    """Prompt-ready character brief. Empty string when nobody could be cast."""
    npc = npc or cast_mission_contact(mission)
    if not npc:
        return ""

    d = build_dossier(npc, mission)
    lines: list[str] = []

    who = d["name"]
    if d["rank"]:
        who += f", {d['rank']}"
    if d["faction"]:
        who += f" of the {d['faction']}"
    lines.append(f"WHO THEY ARE: {who}.")
    if d["species"]:
        lines.append(f"  Species: {d['species']}")
    if d["role"]:
        lines.append(f"  Day to day: {d['role']}")

    if d["quote"]:
        lines.append(f'VOICE (match this cadence, do not quote it back): "{d["quote"]}"')
    if d["motivation"]:
        lines.append(f"WHAT THEY WANT: {d['motivation']}")
    if d["oracle_notes"]:
        lines.append(f"WHAT THEY FEEL UNDERNEATH: {d['oracle_notes']}")

    if d["secret"]:
        lines.append(f"WHAT THEY ARE HIDING (never say outright; it leaks under "
                     f"pressure): {d['secret']}")
    if d["revealed"]:
        lines.append("ALREADY PUBLIC (they know the party may know): "
                     + "; ".join(d["revealed"]))

    if d["relationships"]:
        lines.append(f"TIED TO: {d['relationships']}")
    if d["bonds"]:
        lines.append(f"PEOPLE IN THEIR LIFE: {d['bonds']}")
    for loss in d["grieving"]:
        who, kind, stance = loss["name"], loss["bond_type"], loss.get("stance")
        if stance == "seeking_return":
            lines.append(f"GRIEF (this is live, not backstory): their {kind} {who} is dead "
                         f"and NOT yet lost to the Tower. They want them back and will "
                         f"talk about it, bargain for it, or refuse to discuss it.")
        elif stance == "wants_them_gone":
            lines.append(f"UNFINISHED: their {kind} {who} is dead. They would rather the "
                         f"grave held. If someone is raising {who}, that is a threat.")
        else:
            lines.append(f"UNRESOLVED: {who} ({kind}) died with things unsettled between them.")
    if d["party_name"]:
        lines.append(f"CREW: runs with {d['party_name']}")

    if d["history"]:
        lines.append("WHAT THEY HAVE LIVED THROUGH (draw on these, do not recite them):")
        for event in d["history"]:
            body = _plain(event.get("body"), 200)
            if body:
                lines.append(f"  - [{event.get('event_date')}] "
                             f"{event.get('event_type')}: {body}")

    standing = d["standing"]
    if standing:
        bits = []
        if standing.get("leader"):
            bits.append(f"led by {standing['leader']}")
        if standing.get("motto"):
            bits.append(f'motto "{standing["motto"]}"')
        if standing.get("alignment"):
            bits.append(str(standing["alignment"]))
        if standing.get("reputation_score") is not None:
            bits.append(f"standing with the party: {standing['reputation_score']}"
                        + (f" ({standing['tier']})" if standing.get("tier") else ""))
        if bits:
            lines.append(f"THEIR FACTION: {', '.join(bits)}")

    if d["consequences"]:
        lines.append("WHAT THE WORLD JUST DID TO THEM (they have opinions about this):")
        for c in d["consequences"]:
            title = _plain(c.get("mission_title"), 90) or "a recent job"
            result = _plain(c.get("result"), 30)
            lines.append(f"  - {title}" + (f" [{result}]" if result else ""))
            for label, key in (("what stuck", "notable_moments"),
                               ("choices made", "key_decisions"),
                               ("still unresolved", "loose_threads")):
                val = _plain(c.get(key), 190)
                if val:
                    lines.append(f"    {label}: {val}")
            dead = _plain(c.get("npcs_killed"), 150)
            if dead:
                lines.append(f"    dead: {dead}")

    return "\n".join(lines)


def ensure_schema() -> None:
    """Create `mission_cast` if it does not exist.

    Real table, not a JSON blob: casting is queried and joined (which NPC is in
    which mission, which missions has this NPC fronted), so the JSON reflex rule
    in CLAUDE.md says it gets real columns.
    """
    try:
        raw_execute(
            """
            CREATE TABLE IF NOT EXISTS mission_cast (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                mission_id      INT NOT NULL,
                npc_id          INT NOT NULL,
                role_in_mission VARCHAR(32) NOT NULL DEFAULT 'contact',
                cast_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_mission_role (mission_id, role_in_mission),
                KEY idx_npc (npc_id),
                KEY idx_mission (mission_id)
            )
            """,
            (),
        )
    except Exception as exc:
        logger.warning(f"[dossier] mission_cast init failed: {exc}")
