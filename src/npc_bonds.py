"""
npc_bonds.py -- the relationship graph the world was missing.

Everything the lifecycle recorded about a person was violence or career: injury
225, recovery 204, death 128, resurrection 67, promotion 12, defection 9. No love,
no friendship, no grief, no reconciliation. 128 NPCs had died and nobody had ever
mourned one of them, because there was nothing in the schema that could say who
would miss them.

`npcs.relationships` exists but is free prose -- unqueryable, so no system could
act on it. This module makes ties first-class:

    bonds are DIRECTED rows (mentor->protege is not the same as protege->mentor),
    reciprocal where the tie is mutual (partners, siblings, friends, rivals).

The point is not the table. It is that a death can now find the people it hurts,
courtship can find the unattached, and `npc_dossier` can hand all of it to a model
so grief and affection show up in what characters SAY. That is the butterfly effect
applied to the heart rather than to the mission board.

Per CLAUDE.md this is a real table with real columns, not a JSON blob: bonds are
queried and joined constantly (who mourns X, who is unattached, who feuds).
"""
from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Any, Optional

from src.db_api import raw_query, raw_execute
from src.log import logger

# Mutual ties get a reciprocal row; one-sided ties do not.
# NOTE: "unrequited" is deliberately absent -- that is the entire point of it.
# It is the one bond that must never be mirrored back.
RECIPROCAL = {
    "spouse": "spouse",
    "partner": "partner",
    "courting": "courting",
    "friend": "friend",
    "sibling": "sibling",
    "rival": "rival",
    "enemy": "enemy",
    "parent": "child",
    "child": "parent",
    "mentor": "protege",
    "protege": "mentor",
}

ROMANTIC = ("courting", "partner", "spouse")

# What a survivor WANTS once the body is cold. Death is provisional in the
# Undercity, so grief is a motive, not an ending.
STANCE_SEEK = "seeking_return"     # raise them, whatever it costs
STANCE_GONE = "wants_them_gone"    # let the queue run out; make the grave hold
STANCE_OPEN = "unfinished"         # owed, owing, or simply unresolved

# D&D gives several doors back, and they are NOT the same reunion. Only the soul
# being gone ends a bond for good.
RETURN_KINDS = {
    # kind            (bond status,  how it feels)
    "raise":          ("active",   "came back whole"),
    "resurrection":   ("active",   "came back whole"),
    "true_resurrection": ("active", "came back whole, body and all"),
    # A stranger's face on the person you love. The bond survives; the ease does not.
    "reincarnation":  ("changed",  "came back wearing a different body"),
    # They walk, but it is not them. This is the one where someone who loved them
    # has to decide whether to put them back in the grave.
    "undead":         ("haunted",  "came back wrong"),
    # The bond is being worn by something else; the real person never returned.
    "doppelganger":   ("impostor", "something is wearing their face"),
}

# How a free-text relationships line maps onto a bond type. Ordered: first hit wins.
_TEXT_HINTS = (
    (r"\b(wife|husband|spouse|married to|wed)\b", "spouse"),
    (r"\b(lover|partner|sweetheart|betrothed|engaged to)\b", "partner"),
    (r"\b(courting|courts|smitten|infatuated|pining)\b", "courting"),
    (r"\b(brother|sister|sibling|twin)\b", "sibling"),
    (r"\b(mother|father|parent|daughter|son|child of)\b", "parent"),
    (r"\b(mentor|mentors|taught|trained|apprentice|protege|protégé|student)\b", "mentor"),
    (r"\b(enem(y|ies)|hates|feud|nemesis|sworn against|ousted|deposed|removed him|"
     r"removed her|removed them|betrayed|at war with|purged)\b", "enemy"),
    (r"\b(rival|rivalry|competes|distrusts|suspects|resents|undermines)\b", "rival"),
    (r"\b(owes|debt|indebted|beholden)\b", "debt"),
    (r"\b(friend|ally|allies|allied|alliance|confidant|trusts|close to|drinks with|"
     r"protects|loyal to)\b", "friend"),
)

# No hint matched: record that they KNOW each other and nothing more. Defaulting to
# "friend" invented warmth that is not in the text -- it read "she removed him from
# leadership cleanly" (the Iron Fang civil war) and filed it as a friendship.
_UNCLASSIFIED = "acquaintance"


def ensure_schema() -> None:
    try:
        raw_execute(
            """
            CREATE TABLE IF NOT EXISTS npc_bonds (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                npc_a_id    INT NOT NULL,
                npc_b_id    INT NOT NULL,
                bond_type   VARCHAR(24) NOT NULL,
                strength    INT NOT NULL DEFAULT 50,
                status      VARCHAR(16) NOT NULL DEFAULT 'active',
                stance      VARCHAR(24) NULL,
                note        VARCHAR(400) NULL,
                started_at  DATETIME NOT NULL,
                ended_at    DATETIME NULL,
                UNIQUE KEY uniq_bond (npc_a_id, npc_b_id, bond_type),
                KEY idx_a (npc_a_id, status),
                KEY idx_b (npc_b_id, status),
                KEY idx_type (bond_type, status)
            )
            """,
            (),
        )
        # Older installs predate `stance`. Check before altering -- a blind ALTER
        # logs a duplicate-column error on every single call even when caught.
        have = raw_query(
            "SELECT COUNT(*) c FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'npc_bonds' "
            "AND COLUMN_NAME = 'stance'"
        ) or [{"c": 1}]
        if not int(have[0]["c"]):
            raw_execute("ALTER TABLE npc_bonds ADD COLUMN stance VARCHAR(24) NULL", ())
    except Exception as exc:
        logger.warning(f"[bonds] schema init failed: {exc}")


# ---------------------------------------------------------------------------
# Writing bonds
# ---------------------------------------------------------------------------

def add_bond(
    a_id: int,
    b_id: int,
    bond_type: str,
    *,
    strength: int = 50,
    note: str = "",
    reciprocal: bool = True,
) -> bool:
    """Create (or refresh) a bond. Returns True if anything was written."""
    if not a_id or not b_id or int(a_id) == int(b_id):
        return False

    now = datetime.now()
    rows = [(int(a_id), int(b_id), bond_type, int(strength), note or None, now)]

    if reciprocal and bond_type in RECIPROCAL:
        rows.append((int(b_id), int(a_id), RECIPROCAL[bond_type],
                     int(strength), note or None, now))

    wrote = False
    for row in rows:
        try:
            raw_execute(
                "INSERT INTO npc_bonds "
                "(npc_a_id, npc_b_id, bond_type, strength, note, started_at, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'active') "
                "ON DUPLICATE KEY UPDATE strength = VALUES(strength), "
                "status = 'active', ended_at = NULL, "
                "note = COALESCE(VALUES(note), note)",
                row,
            )
            wrote = True
        except Exception as exc:
            logger.debug(f"[bonds] write failed: {exc}")
    return wrote


def end_bond(a_id: int, b_id: int, bond_type: str, status: str = "ended") -> None:
    try:
        raw_execute(
            "UPDATE npc_bonds SET status=%s, ended_at=NOW() "
            "WHERE ((npc_a_id=%s AND npc_b_id=%s) OR (npc_a_id=%s AND npc_b_id=%s)) "
            "AND bond_type IN (%s, %s) AND status='active'",
            (status, int(a_id), int(b_id), int(b_id), int(a_id),
             bond_type, RECIPROCAL.get(bond_type, bond_type)),
        )
    except Exception as exc:
        logger.debug(f"[bonds] end_bond failed: {exc}")


# ---------------------------------------------------------------------------
# Reading bonds
# ---------------------------------------------------------------------------

def get_bonds(npc_id: int, *, active_only: bool = True) -> list[dict[str, Any]]:
    """Bonds radiating from this NPC, with the other person's name attached."""
    sql = (
        "SELECT b.*, n.name AS other_name, n.faction AS other_faction, "
        "n.status AS other_status "
        "FROM npc_bonds b JOIN npcs n ON n.id = b.npc_b_id "
        "WHERE b.npc_a_id = %s"
    )
    params: list[Any] = [int(npc_id)]
    if active_only:
        sql += " AND b.status = 'active'"
    sql += " ORDER BY b.strength DESC, b.id"
    try:
        return raw_query(sql, tuple(params)) or []
    except Exception as exc:
        logger.debug(f"[bonds] get_bonds failed: {exc}")
        return []


def is_attached(npc_id: int) -> bool:
    rows = raw_query(
        "SELECT 1 FROM npc_bonds WHERE npc_a_id=%s AND status='active' "
        "AND bond_type IN ('courting','partner','spouse') LIMIT 1",
        (int(npc_id),),
    ) or []
    return bool(rows)


# ---------------------------------------------------------------------------
# Bereavement -- the thing that was completely missing
# ---------------------------------------------------------------------------

def bereave(dead_npc_id: int, dead_name: str, cause: str = "") -> list[dict[str, Any]]:
    """Record grief and give every survivor a STANCE on the death.

    In the Undercity a corpse is not a conclusion. Until the Tower absorbs someone
    they are only provisionally dead -- `resurrection_queue` already resolves to
    'raised' or 'lost_to_tower', and 30 of the dead are sitting in that limbo right
    now. So a death must NOT close the bond. It converts it into a motive:

        those who loved them  -> 'seeking_return'   (they want them back)
        those who feared them -> 'wants_them_gone'  (they want the grave to hold)
        those owed or owing   -> 'unfinished'       (it cuts both ways)

    That stance is the hook a mission can hang off: a widow petitioning for a
    raising, a rival paying to make sure the queue times out. Bonds only truly
    close in `sever_on_tower_loss()`.

    Grief goes to `npc_history` -- prefer existing world systems -- so it flows
    into `npc_dossier` and changes how the survivor talks in their next scene.
    """
    mourners = get_bonds(int(dead_npc_id))
    if not mourners:
        return []

    try:
        from src.db_api import add_npc_history_event
    except Exception:
        add_npc_history_event = None  # type: ignore

    today = datetime.now().strftime("%Y-%m-%d")
    out: list[dict[str, Any]] = []

    for bond in mourners:
        survivor_id = int(bond["npc_b_id"])
        bond_type = str(bond["bond_type"])
        # The dead do not grieve.
        if str(bond.get("other_status") or "").lower() == "dead":
            continue

        grief = _grief_line(bond_type, dead_name, cause)
        if add_npc_history_event:
            try:
                add_npc_history_event(survivor_id, grief, today, "grief")
            except Exception as exc:
                logger.debug(f"[bonds] grief event failed: {exc}")

        stance = _stance_for(bond_type)
        # Mark the bond as mourning, NOT ended -- the soul is still in play.
        try:
            raw_execute(
                "UPDATE npc_bonds SET status='mourning', stance=%s "
                "WHERE (npc_a_id=%s AND npc_b_id=%s) OR (npc_a_id=%s AND npc_b_id=%s)",
                (stance, int(dead_npc_id), survivor_id, survivor_id, int(dead_npc_id)),
            )
        except Exception as exc:
            logger.debug(f"[bonds] mourning mark failed: {exc}")

        out.append({
            "npc_id": survivor_id,
            "name": bond.get("other_name"),
            "bond_type": bond_type,
            "strength": int(bond.get("strength") or 0),
            "stance": stance,
            "grief": grief,
        })

    out.sort(key=lambda m: (-_grief_weight(m["bond_type"]), -m["strength"]))
    seekers = [m["name"] for m in out if m["stance"] == STANCE_SEEK]
    logger.info(
        f"[bonds] {dead_name} is mourned by {len(out)}"
        + (f"; {len(seekers)} want them back ({', '.join(seekers[:4])})" if seekers else "")
    )
    return out


def _stance_for(bond_type: str) -> str:
    if bond_type in ("enemy", "rival"):
        return STANCE_GONE
    # An acquaintance or a creditor does not move heaven and earth for a raising.
    # They have something unfinished, which is a different and quieter story.
    if bond_type in ("debt", "acquaintance"):
        return STANCE_OPEN
    return STANCE_SEEK


def mourners_seeking_return(limit: int = 20) -> list[dict[str, Any]]:
    """Survivors actively wanting someone raised -- ready-made mission hooks."""
    return raw_query(
        "SELECT b.npc_a_id AS dead_id, d.name AS dead_name, "
        "b.npc_b_id AS mourner_id, m.name AS mourner_name, "
        "b.bond_type, b.strength, b.stance "
        "FROM npc_bonds b "
        "JOIN npcs d ON d.id = b.npc_a_id "
        "JOIN npcs m ON m.id = b.npc_b_id "
        "WHERE b.status = 'mourning' AND b.stance = %s "
        "AND d.status = 'dead' AND m.status = 'alive' "
        "ORDER BY b.strength DESC LIMIT %s",
        (STANCE_SEEK, int(limit)),
    ) or []


def restore_on_return(npc_id: int, name: str, kind: str = "raise") -> list[str]:
    """Someone came back. HOW they came back decides what the bond becomes.

    Raise/Resurrection restores the tie. Reincarnation keeps the love and takes
    the face. Undead and doppelganger are not reunions at all -- they are the
    setup for someone who loved them having to decide what to do about it.
    """
    status, feeling = RETURN_KINDS.get(kind, RETURN_KINDS["raise"])
    notes: list[str] = []

    bonds = raw_query(
        "SELECT b.*, n.name AS other_name FROM npc_bonds b "
        "JOIN npcs n ON n.id = b.npc_b_id "
        "WHERE b.npc_a_id = %s AND b.status = 'mourning'",
        (int(npc_id),),
    ) or []

    try:
        from src.db_api import add_npc_history_event
    except Exception:
        add_npc_history_event = None  # type: ignore
    today = datetime.now().strftime("%Y-%m-%d")

    for bond in bonds:
        try:
            raw_execute(
                "UPDATE npc_bonds SET status=%s, stance=NULL, ended_at=NULL "
                "WHERE (npc_a_id=%s AND npc_b_id=%s) OR (npc_a_id=%s AND npc_b_id=%s)",
                (status, int(npc_id), int(bond["npc_b_id"]),
                 int(bond["npc_b_id"]), int(npc_id)),
            )
        except Exception as exc:
            logger.debug(f"[bonds] restore failed: {exc}")

        line = _return_line(str(bond["bond_type"]), name, kind, feeling)
        if add_npc_history_event:
            try:
                add_npc_history_event(int(bond["npc_b_id"]), line, today, "return")
            except Exception:
                pass
        notes.append(f"{bond.get('other_name')}: {line}")

    if notes:
        logger.info(f"[bonds] {name} returned ({kind}); {len(notes)} ties reopened")
    return notes


def _return_line(bond_type: str, name: str, kind: str, feeling: str) -> str:
    close = bond_type in ("spouse", "partner", "courting", "sibling", "parent", "child")
    if kind == "undead":
        return (f"{name} walks again, but {feeling}. "
                + ("They have to decide whether to put them back in the grave."
                   if close else "They are not what they were."))
    if kind == "doppelganger":
        return (f"Something wearing {name}'s face has been seen. "
                f"If it is not {name}, then {name} is still out there -- or still gone.")
    if kind == "reincarnation":
        return (f"{name} {feeling}. "
                + ("They have to learn a stranger's face and call it beloved."
                   if close else "They answer to the same name in a body that is not theirs."))
    return f"{name} {feeling}." + (" They got them back." if close else "")


def sever_on_tower_loss(npc_id: int, name: str) -> list[str]:
    """The Tower took them. THIS is the ending -- the soul is gone.

    Only here do bonds actually close. Everything before this was hope.
    """
    bonds = raw_query(
        "SELECT b.npc_b_id, b.bond_type, n.name AS other_name FROM npc_bonds b "
        "JOIN npcs n ON n.id = b.npc_b_id "
        "WHERE b.npc_a_id = %s AND b.status IN ('mourning','active')",
        (int(npc_id),),
    ) or []

    try:
        from src.db_api import add_npc_history_event
    except Exception:
        add_npc_history_event = None  # type: ignore
    today = datetime.now().strftime("%Y-%m-%d")

    notes: list[str] = []
    for bond in bonds:
        line = (f"The Tower absorbed {name}. No raising, no reincarnation, no body. "
                f"Whatever they were is not coming back.")
        if add_npc_history_event:
            try:
                add_npc_history_event(int(bond["npc_b_id"]), line, today, "soul_lost")
            except Exception:
                pass
        notes.append(f"{bond.get('other_name')} ({bond['bond_type']})")

    try:
        raw_execute(
            "UPDATE npc_bonds SET status='severed', stance=NULL, ended_at=NOW() "
            "WHERE npc_a_id=%s OR npc_b_id=%s",
            (int(npc_id), int(npc_id)),
        )
        raw_execute("UPDATE npcs SET tower_absorbed=1 WHERE id=%s", (int(npc_id),))
    except Exception as exc:
        logger.debug(f"[bonds] sever failed: {exc}")

    if notes:
        logger.info(f"[bonds] {name} lost to the Tower; severed {len(notes)} ties")
    return notes


_GRIEF_WEIGHT = {"spouse": 100, "partner": 90, "child": 85, "parent": 80,
                 "sibling": 75, "courting": 70, "protege": 60, "mentor": 60,
                 "friend": 50, "debt": 20, "rival": 15, "enemy": 5}


def _grief_weight(bond_type: str) -> int:
    return _GRIEF_WEIGHT.get(bond_type, 30)


def _grief_line(bond_type: str, dead_name: str, cause: str = "") -> str:
    """A plain factual grief record. The prose comes later, from a model that
    reads this; what matters here is that the FACT is durable and specific."""
    how = f" ({cause})" if cause else ""
    match bond_type:
        case "spouse" | "partner":
            return f"Lost their partner {dead_name}{how}. Widowed."
        case "courting":
            return f"{dead_name}, whom they were courting, died{how}."
        case "child":
            return f"Buried their parent {dead_name}{how}."
        case "parent":
            return f"Buried their child {dead_name}{how}. No parent should."
        case "sibling":
            return f"Buried their sibling {dead_name}{how}."
        case "mentor":
            return f"Their student {dead_name} died{how}."
        case "protege":
            return f"Their mentor {dead_name} died{how}."
        case "friend":
            return f"Lost their friend {dead_name}{how}."
        case "rival":
            return (f"Their rival {dead_name} died{how}. "
                    f"There is nobody left to prove it to.")
        case "enemy":
            return f"Their enemy {dead_name} died{how}. It did not feel like winning."
        case "debt":
            return f"{dead_name} died{how}; the debt between them will never be settled."
        case _:
            return f"{dead_name} died{how}."


# ---------------------------------------------------------------------------
# Seeding the graph from the prose that already exists
# ---------------------------------------------------------------------------

def _roster() -> list[dict]:
    """Everyone, living AND dead.

    The dead must be included or nobody can mourn them: their relationships prose
    is still the record of who they mattered to, and in a city where the grave is
    negotiable those ties are the live ones.
    """
    return raw_query(
        "SELECT id, name, faction, relationships, status FROM npcs"
    ) or []


def seed_from_relationships(dry_run: bool = True) -> list[dict]:
    """Mine `npcs.relationships` prose for ties to real roster members.

    109 NPCs carry lines like "Maintains a tense rivalry with Warden Jax Ironclaw,
    who suspects Kree of spying". The names in there are real people; the graph
    should start from what the world already believes rather than from nothing.
    """
    people = _roster()
    by_name = {str(p["name"]): p for p in people if p.get("name")}
    found: list[dict] = []

    for person in people:
        text = str(person.get("relationships") or "")
        if not text:
            continue

        # `relationships` is sometimes a JSON map {name: description} rather than
        # prose. Read the structure when it is there: a character window across a
        # JSON blob spills into the NEXT entry, which is how "Mari Fen: cordial,
        # occasional visitor" picked up "husband" from the adjacent Aldric Vane
        # entry and invented a marriage.
        structured: dict[str, str] = {}
        if text.lstrip().startswith("{"):
            try:
                import json as _json
                parsed = _json.loads(text)
                if isinstance(parsed, dict):
                    structured = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                structured = {}

        for other_name, other in by_name.items():
            if other["id"] == person["id"]:
                continue
            if not re.search(rf"\b{re.escape(other_name)}\b", text):
                continue

            if structured:
                if other_name not in structured:
                    continue
                window = structured[other_name].lower()
                idx = text.find(other_name)
            else:
                # Read the bond type from the clause mentioning them.
                idx = text.find(other_name)
                window = text[max(0, idx - 90): idx + 90].lower()
            bond_type = _UNCLASSIFIED
            for pattern, kind in _TEXT_HINTS:
                if re.search(pattern, window):
                    bond_type = kind
                    break
            else:
                bond_type = _UNCLASSIFIED

            found.append({
                "a": person["name"], "a_id": person["id"],
                "b": other_name, "b_id": other["id"],
                "bond_type": bond_type,
                "evidence": text[max(0, idx - 60): idx + 60].strip(),
            })
            if not dry_run:
                add_bond(person["id"], other["id"], bond_type,
                         strength=60, note=f"from roster prose: {other_name}")

    return found


# ---------------------------------------------------------------------------
# The social tick -- people find each other
# ---------------------------------------------------------------------------

def backfill_grief(limit: int = 40) -> list[dict[str, Any]]:
    """Retro-mourn the dead who are still inside the resurrection window.

    128 people had died with nobody grieving, and 30 of them are still sitting in
    `resurrection_queue` limbo -- not absorbed, therefore still recoverable. Those
    are exactly the graves someone should be trying to open or trying to keep shut,
    so give their survivors the grief and the stance now.

    Deliberately skips anyone the Tower already took: that ship has sailed.
    """
    ensure_schema()
    dead = raw_query(
        "SELECT id, name, death_cause FROM npcs "
        "WHERE status='dead' AND (tower_absorbed IS NULL OR tower_absorbed = 0) "
        "ORDER BY deceased_at DESC LIMIT %s",
        (int(limit),),
    ) or []

    touched: list[dict[str, Any]] = []
    for person in dead:
        # Skip anyone already mourned so a re-run does not duplicate grief.
        existing = raw_query(
            "SELECT 1 FROM npc_bonds WHERE npc_a_id=%s AND status='mourning' LIMIT 1",
            (int(person["id"]),),
        ) or []
        if existing:
            continue
        mourners = bereave(int(person["id"]), str(person["name"]),
                           str(person.get("death_cause") or ""))
        if mourners:
            touched.append({"dead": person["name"], "mourners": mourners})
    return touched


def social_tick(max_new: int = 2) -> list[str]:
    """Advance the affections of the living. Pure DB, no model, no GPU.

    Courting deepens into partnership, partnership into marriage, and a few
    unattached people find each other. Deliberately slow: this should feel like a
    world where things happen, not a dating app.
    """
    ensure_schema()
    notes: list[str] = []

    try:
        from src.db_api import add_npc_history_event
    except Exception:
        add_npc_history_event = None  # type: ignore

    today = datetime.now().strftime("%Y-%m-%d")

    def _hist(npc_id: int, kind: str, body: str) -> None:
        if add_npc_history_event:
            try:
                add_npc_history_event(int(npc_id), body, today, kind)
            except Exception:
                pass

    # 1. Deepen existing romances.
    ripening = raw_query(
        "SELECT b.*, a.name AS a_name, bn.name AS b_name "
        "FROM npc_bonds b JOIN npcs a ON a.id=b.npc_a_id JOIN npcs bn ON bn.id=b.npc_b_id "
        "WHERE b.status='active' AND b.bond_type IN ('courting','partner') "
        "AND a.status='alive' AND bn.status='alive' "
        "AND b.started_at < DATE_SUB(NOW(), INTERVAL 14 DAY) "
        "ORDER BY RAND() LIMIT 3"
    ) or []

    for bond in ripening:
        if random.random() > 0.35:
            continue
        a_id, b_id = int(bond["npc_a_id"]), int(bond["npc_b_id"])
        a_name, b_name = bond["a_name"], bond["b_name"]
        if bond["bond_type"] == "courting":
            end_bond(a_id, b_id, "courting")
            add_bond(a_id, b_id, "partner", strength=75)
            note = f"{a_name} and {b_name} are together now."
            _hist(a_id, "romance", f"Became partners with {b_name}.")
            _hist(b_id, "romance", f"Became partners with {a_name}.")
        else:
            end_bond(a_id, b_id, "partner")
            add_bond(a_id, b_id, "spouse", strength=90)
            note = f"{a_name} and {b_name} were married."
            _hist(a_id, "marriage", f"Married {b_name}.")
            _hist(b_id, "marriage", f"Married {a_name}.")
        notes.append(note)

    # 2. New courtships among the unattached.
    singles = raw_query(
        "SELECT n.id, n.name, n.faction FROM npcs n WHERE n.status='alive' "
        "AND NOT EXISTS (SELECT 1 FROM npc_bonds b WHERE b.npc_a_id=n.id "
        "  AND b.status='active' AND b.bond_type IN ('courting','partner','spouse')) "
        "ORDER BY RAND() LIMIT 40"
    ) or []

    random.shuffle(singles)
    made = 0
    used: set[int] = set()
    for a in singles:
        if made >= max_new:
            break
        if a["id"] in used:
            continue
        # Prefer someone from the same faction -- proximity breeds attachment.
        pool = [b for b in singles
                if b["id"] not in used and b["id"] != a["id"]]
        same = [b for b in pool if b.get("faction") == a.get("faction")]
        candidates = same or pool
        if not candidates:
            continue
        b = random.choice(candidates)
        if random.random() > 0.5:
            continue
        add_bond(a["id"], b["id"], "courting", strength=40)
        used.update({a["id"], b["id"]})
        made += 1
        _hist(a["id"], "romance", f"Started seeing {b['name']}.")
        _hist(b["id"], "romance", f"Started seeing {a['name']}.")
        notes.append(f"{a['name']} and {b['name']} have started seeing each other.")

    if notes:
        logger.info("[bonds] social tick: " + " | ".join(notes))
    return notes


# ---------------------------------------------------------------------------
# For the dossier
# ---------------------------------------------------------------------------

def bonds_block(npc_id: int) -> str:
    """Human-readable tie summary for an NPC dossier."""
    bonds = get_bonds(int(npc_id))
    if not bonds:
        return ""
    parts = []
    for b in bonds[:8]:
        label = str(b["bond_type"])
        name = b.get("other_name")
        if str(b.get("other_status") or "").lower() == "dead":
            parts.append(f"{label}: {name} (dead)")
        else:
            parts.append(f"{label}: {name}")
    return "; ".join(parts)
