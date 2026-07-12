"""party_lifecycle.py -- NPC adventurer parties as living entities.

Parties form, recruit existing NPCs, split (schism), merge, sign/end faction
contracts (or get fired), disband, and retire. Party MEMBERS are real rows in
the `npcs` table, linked by the `npcs.party_name` column (NULL = unaffiliated
world NPC). This mirrors src/npc_lifecycle.py for individual NPCs.

Design notes / guardrails:
- Anti-filler: formation reuses unused, previously-LLM-generated names from
  `adventurer_parties` and recruits EXISTING free-agent NPCs. If neither is
  available it SKIPS rather than synthesising filler.
- Protected crews (the Unknown Party) are never auto-split/merged/disbanded.
- A minimum active-party floor keeps enough crews around to claim board missions.
- Mission-driven casualties/wipeouts are a separate, later pass.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from typing import List, Optional, Dict

from src.db_api import (
    raw_query, raw_execute, db,
    add_party_history_event, add_npc_history_event,
    get_faction_reputation, set_faction_reputation,
)
from src import party_profiles as pp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables / guardrails
# ---------------------------------------------------------------------------
PROTECTED_PARTIES = {"unknown party"}     # never auto-split/merge/disband
MIN_ACTIVE_PARTIES = 60                   # keep enough crews to claim missions
MIN_CREW_SIZE = 2                         # a crew below this disbands
SPLIT_MIN_MEMBERS = 4                     # only parties this big can splinter
DEFAULT_FORM_SIZE = 4

_IRON_FANG = {"iron fang consortium", "iron fang syndicate"}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _is_protected(name: str) -> bool:
    return (name or "").strip().lower() in PROTECTED_PARTIES


# ---------------------------------------------------------------------------
# Low-level party / npc helpers
# ---------------------------------------------------------------------------

def _party_id(name: str) -> Optional[int]:
    row = raw_query("SELECT id FROM party_profiles WHERE party_name=%s", (name,))
    return row[0]["id"] if row else None


def _phist(name: str, body: str) -> None:
    pid = _party_id(name)
    if pid:
        add_party_history_event(pid, body)


def _npc_hist(npc_name: str, body: str) -> None:
    row = raw_query("SELECT id FROM npcs WHERE name=%s", (npc_name,))
    if row:
        add_npc_history_event(int(row[0]["id"]), body)


def _set_party_columns(name: str, **cols) -> None:
    """Update real party_profiles columns (status, faction, employer, tier...)."""
    if not cols:
        return
    sets = ", ".join(f"{k}=%s" for k in cols)
    raw_execute(f"UPDATE party_profiles SET {sets} WHERE party_name=%s",
                tuple(list(cols.values()) + [name]))


def _affiliation(profile: dict) -> str:
    return (profile.get("affiliation") or profile.get("faction")
            or profile.get("employer") or "Independent")


def _unused_party_name() -> Optional[str]:
    """An adventurer_parties name with no party_profiles row yet (pre-generated, no filler)."""
    rows = raw_query(
        "SELECT ap.party_name FROM adventurer_parties ap "
        "LEFT JOIN party_profiles pp ON pp.party_name = ap.party_name "
        "WHERE pp.id IS NULL ORDER BY RAND() LIMIT 1"
    ) or []
    return rows[0]["party_name"] if rows else None


def _free_agent_npcs(limit: int = 6, exclude: Optional[set] = None) -> List[dict]:
    """Living, unaffiliated-to-a-party NPCs that can be recruited. Excludes faction
    leaders and Unknown Party members (they have their own handling)."""
    exclude = {e.lower() for e in (exclude or set())}
    # Prefer unaffiliated free agents so forming a crew does not quietly gut a
    # faction's named roster; faction NPCs can still be recruited, just not first.
    rows = raw_query(
        "SELECT name, species, faction FROM npcs "
        "WHERE (party_name IS NULL OR party_name='') AND status='alive' "
        "ORDER BY (faction IS NULL OR faction='' OR faction='Independent') DESC, RAND() "
        "LIMIT 40"
    ) or []
    out = []
    try:
        from src.npc_lifecycle import is_faction_leader, is_unknown_party_member
    except Exception:
        is_faction_leader = lambda n: False
        is_unknown_party_member = lambda n: False
    for r in rows:
        nm = (r.get("name") or "").strip()
        if not nm or nm.lower() in exclude:
            continue
        if is_faction_leader(nm) or is_unknown_party_member(nm):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _link_npc(npc_name: str, party_name: str, role: str = "Member") -> None:
    """Point an existing NPC at a party (also records party_role in data_json)."""
    row = raw_query("SELECT data_json FROM npcs WHERE name=%s", (npc_name,))
    if not row:
        return
    dj = row[0].get("data_json") or {}
    if isinstance(dj, str):
        try:
            dj = json.loads(dj) if dj else {}
        except Exception:
            dj = {}
    if not isinstance(dj, dict):
        dj = {}
    dj["party_role"] = role
    raw_execute("UPDATE npcs SET party_name=%s, data_json=%s WHERE name=%s",
                (party_name, json.dumps(dj, ensure_ascii=False, default=str), npc_name))


def _unlink_npc(npc_name: str) -> None:
    raw_execute("UPDATE npcs SET party_name=NULL WHERE name=%s", (npc_name,))


def _ensure_npc(name: str, faction: str, role: str, species: str = "Human",
                party_name: Optional[str] = None, note: str = "") -> Optional[int]:
    """Create or update a real npc row for a party member. Returns the npc id."""
    existing = raw_query("SELECT id FROM npcs WHERE name=%s", (name,))
    if existing:
        _link_npc(name, party_name, role) if party_name else None
        return int(existing[0]["id"])
    new_id = db.insert("npcs", {
        "name": name,
        "faction": faction or "Independent",
        "role": role or "Adventurer",
        "status": "alive",
        "species": species or "Human",
        "party_name": party_name,
        "data_json": json.dumps({"party_role": role, "note": note, "species": species,
                                 "generated_by": "party_lifecycle"}, ensure_ascii=False),
    })
    if new_id and party_name:
        _npc_hist(name, f"[{_today()}] Joined the crew {party_name} as {role}.")
    return new_id


def ensure_party_members_are_npcs(party_name: str) -> List[str]:
    """Promote a party's embedded members to real npc rows + link them. Idempotent.
    Returns the list of member names now backed by npc rows."""
    prof = pp.load_profile(party_name)
    if not prof:
        return []
    faction = _affiliation(prof)
    realized = []
    for m in (prof.get("members") or []):
        nm = (m.get("name") or "").strip()
        if not nm:
            continue
        _ensure_npc(nm, faction, m.get("role") or "Member",
                    m.get("species") or "Human", party_name, m.get("note") or "")
        realized.append(nm)
    return realized


# ---------------------------------------------------------------------------
# JOIN -- an existing NPC joins a party
# ---------------------------------------------------------------------------

def recruit_npc_to_party(npc_name: str, party_name: str, role: str = "Member") -> bool:
    """An existing world NPC joins a party. Sets the link, adds to the roster,
    logs both sides. Refuses dead NPCs, NPCs already in a party, and faction leaders."""
    npc = raw_query(
        "SELECT name, species, status, party_name FROM npcs WHERE name=%s", (npc_name,))
    if not npc:
        return False
    npc = npc[0]
    if str(npc.get("status", "")).lower() in ("dead", "deceased"):
        return False
    if (npc.get("party_name") or "").strip():
        return False
    try:
        from src.npc_lifecycle import is_faction_leader
        if is_faction_leader(npc_name):
            return False
    except Exception:
        pass
    prof = pp.load_profile(party_name)
    if not prof or str(_party_status(party_name)).lower() != "active":
        return False
    members = prof.get("members") or []
    if any((mm.get("name") or "").lower() == npc_name.lower() for mm in members):
        return False
    members.append({"name": npc_name, "role": role,
                    "species": npc.get("species") or "Human",
                    "note": f"Recruited {_today()}"})
    prof["members"] = members
    pp.save_profile(prof)
    _link_npc(npc_name, party_name, role)
    _phist(party_name, f"[{_today()}] {npc_name} joined the crew as {role}.")
    _npc_hist(npc_name, f"[{_today()}] Joined the adventurer party {party_name} as {role}.")
    logger.info(f"\U0001f9d1‍\U0001f91d‍\U0001f9d1 {npc_name} joined party {party_name}")
    return True


def _party_status(name: str) -> str:
    row = raw_query("SELECT status FROM party_profiles WHERE party_name=%s", (name,))
    return (row[0]["status"] if row else "") or ""


# ---------------------------------------------------------------------------
# FORMATION -- a new crew forms
# ---------------------------------------------------------------------------

def form_party(affiliation: str = "Independent", size: int = DEFAULT_FORM_SIZE,
               name: Optional[str] = None) -> Optional[str]:
    """Form a brand-new party from existing free-agent NPCs under a pre-generated
    (non-filler) name. Returns the party name, or None if it could not form."""
    name = name or _unused_party_name()
    if not name:
        logger.debug("form_party: no unused party name available -- skipping")
        return None
    recruits = _free_agent_npcs(limit=max(2, size))
    if len(recruits) < MIN_CREW_SIZE:
        logger.debug("form_party: not enough free-agent NPCs to form a crew -- skipping")
        return None

    members = []
    for i, r in enumerate(recruits):
        role = "Leader" if i == 0 else "Member"
        members.append({"name": r["name"], "role": role,
                        "species": r.get("species") or "Human",
                        "note": f"Founding member ({_today()})"})

    prof = pp._init_profile(name)
    prof["generated"] = True
    prof["affiliation"] = affiliation
    prof["faction"] = affiliation
    prof["employer"] = None if affiliation == "Independent" else affiliation
    prof["members"] = members
    prof["specialty"] = "A newly-formed crew still finding its footing."
    prof["reputation_note"] = f"Formed {_today()} from unaffiliated hands."
    pp.save_profile(prof)
    _set_party_columns(name, status="active", faction=affiliation)

    leader = members[0]["name"]
    for m in members:
        _link_npc(m["name"], name, m["role"])
        _npc_hist(m["name"], f"[{_today()}] Founding {m['role'].lower()} of the new party {name}.")
    _phist(name, f"[{_today()}] Party formed with {len(members)} members, led by {leader}.")
    logger.info(f"\U0001f195 Party formed: {name} ({len(members)} members, leader {leader})")
    return name


# ---------------------------------------------------------------------------
# SPLIT -- a faction within the crew breaks away
# ---------------------------------------------------------------------------

def _iron_fang_other_side(affiliation: str) -> Optional[str]:
    a = (affiliation or "").strip().lower()
    if a == "iron fang consortium":
        return "Iron Fang Syndicate"
    if a == "iron fang syndicate":
        return "Iron Fang Consortium"
    return None


def split_party(party_name: str, reason: str = "") -> Optional[str]:
    """A subset of the crew breaks away to form a new party carrying a grudge.
    Iron-Fang-affiliated crews split along the Orthodox/Syndicate schism.
    Returns the new splinter party's name, or None if it could not split."""
    if _is_protected(party_name):
        return None
    if str(_party_status(party_name)).lower() != "active":
        return None
    prof = pp.load_profile(party_name)
    if not prof:
        return None
    ensure_party_members_are_npcs(party_name)
    members = prof.get("members") or []
    if len(members) < SPLIT_MIN_MEMBERS:
        return None

    new_name = _unused_party_name()
    if not new_name:
        return None

    affiliation = _affiliation(prof)
    other = _iron_fang_other_side(affiliation)
    split_affiliation = other or "Independent"
    reason = reason or ("the Iron Fang civil war" if other else "an internal schism")

    # leave at least MIN_CREW_SIZE in the original; the splinter is the back half
    k = max(2, len(members) // 2)
    k = min(k, len(members) - MIN_CREW_SIZE)
    if k < 2:
        return None
    breakaway = members[-k:]
    remaining = members[:-k]
    # the splinter's leader is the first breakaway member, freshly promoted
    breakaway = [dict(m) for m in breakaway]
    breakaway[0]["role"] = "Leader"
    leader2 = breakaway[0]["name"]

    splinter = pp._init_profile(new_name)
    splinter["generated"] = True
    splinter["affiliation"] = split_affiliation
    splinter["faction"] = split_affiliation
    splinter["employer"] = None if split_affiliation == "Independent" else split_affiliation
    splinter["members"] = breakaway
    splinter["faction_hates"] = [party_name] + ([affiliation] if other else [])
    splinter["specialty"] = f"A breakaway crew, splintered from {party_name}."
    splinter["reputation_note"] = (
        f"Split from {party_name} over {reason}. Bad blood remains.")
    pp.save_profile(splinter)
    _set_party_columns(new_name, status="active", faction=split_affiliation)

    # reassign the breakaway members to the splinter
    for m in breakaway:
        _link_npc(m["name"], new_name, m.get("role") or "Member")
        _npc_hist(m["name"], f"[{_today()}] Broke away from {party_name} to form {new_name} over {reason}.")

    # update the original roster
    prof["members"] = remaining
    pp.save_profile(prof)
    _phist(party_name, f"[{_today()}] {leader2} broke away with {len(breakaway)} members to form {new_name} over {reason}.")
    _phist(new_name, f"[{_today()}] Splintered from {party_name} over {reason}; led by {leader2}.")
    logger.info(f"\U0001fa93 Party split: {leader2} took {len(breakaway)} from {party_name} -> {new_name} ({split_affiliation})")

    if len(remaining) < MIN_CREW_SIZE:
        disband_party(party_name, reason=f"gutted by the schism that formed {new_name}")
    return new_name


# ---------------------------------------------------------------------------
# MERGE -- two depleted crews combine
# ---------------------------------------------------------------------------

def merge_parties(into_name: str, from_name: str, reason: str = "") -> bool:
    """Fold `from_name`'s members into `into_name`; `from_name` becomes 'merged'."""
    if _is_protected(from_name) or _is_protected(into_name) or into_name == from_name:
        return False
    a = pp.load_profile(into_name)
    b = pp.load_profile(from_name)
    if not a or not b:
        return False
    if str(_party_status(into_name)).lower() != "active" or str(_party_status(from_name)).lower() != "active":
        return False
    reason = reason or "mutual survival"
    a_members = a.get("members") or []
    a_names = {(m.get("name") or "").lower() for m in a_members}
    moved = 0
    for m in (b.get("members") or []):
        nm = (m.get("name") or "").strip()
        if not nm or nm.lower() in a_names:
            continue
        m2 = dict(m)
        m2["role"] = "Member"
        m2["note"] = f"Joined via merge of {from_name} ({_today()})"
        a_members.append(m2)
        a_names.add(nm.lower())
        _link_npc(nm, into_name, "Member")
        _npc_hist(nm, f"[{_today()}] {from_name} merged into {into_name} over {reason}.")
        moved += 1
    a["members"] = a_members
    pp.save_profile(a)
    _set_party_columns(from_name, status="merged")
    _phist(into_name, f"[{_today()}] Absorbed {moved} members as {from_name} merged in over {reason}.")
    _phist(from_name, f"[{_today()}] Merged into {into_name} over {reason}. The crew name is retired.")
    logger.info(f"\U0001f91d Party merge: {from_name} -> {into_name} ({moved} members)")
    return True


# ---------------------------------------------------------------------------
# CONTRACTS -- sign with / get fired by a faction or guild
# ---------------------------------------------------------------------------

def sign_contract(party_name: str, faction: str, notes: str = "") -> bool:
    """A party signs an employment contract with a faction/guild."""
    prof = pp.load_profile(party_name)
    if not prof or not faction:
        return False
    prof["employer"] = faction
    prof["affiliation"] = faction
    prof["faction"] = faction
    pp.save_profile(prof)
    _set_party_columns(party_name, employer=faction, faction=faction)
    try:
        exists = raw_query(
            "SELECT id FROM faction_affiliations WHERE guild_name=%s AND faction_name=%s",
            (party_name, faction))
        if not exists:
            db.insert("faction_affiliations", {
                "guild_name": party_name, "faction_name": faction,
                "affiliation_type": "employment", "strength": 3,
                "notes": notes or f"Signed {_today()}",
            })
    except Exception as e:
        logger.debug(f"sign_contract affiliation row skipped: {e}")
    _phist(party_name, f"[{_today()}] Signed a contract with {faction}.")
    try:
        rep = get_faction_reputation(faction) or {}
        set_faction_reputation(faction, int(rep.get("reputation_score") or 0) + 1)
    except Exception:
        pass
    logger.info(f"\U0001f4dd Contract signed: {party_name} <- {faction}")
    return True


def end_contract(party_name: str, reason: str = "", fired: bool = False) -> bool:
    """A party's contract ends -- voluntarily, or they get fired."""
    prof = pp.load_profile(party_name)
    if not prof:
        return False
    old = prof.get("employer") or prof.get("faction") or ""
    if not old or old == "Independent":
        return False
    prof["employer"] = None
    prof["affiliation"] = "Independent"
    prof["faction"] = "Independent"
    pp.save_profile(prof)
    _set_party_columns(party_name, employer=None, faction="Independent")
    try:
        raw_execute("DELETE FROM faction_affiliations WHERE guild_name=%s AND faction_name=%s",
                    (party_name, old))
    except Exception:
        pass
    verb = "was fired by" if fired else "ended its contract with"
    tail = f" -- {reason}" if reason else ""
    _phist(party_name, f"[{_today()}] {party_name} {verb} {old}{tail}.")
    if fired:
        prof["points"] = prof.get("points", 0) - 1
        pp.save_profile(prof)
    logger.info(f"\U0001f4c4 Contract ended ({'fired' if fired else 'mutual'}): {party_name} x {old}")
    return True


# ---------------------------------------------------------------------------
# DISBAND
# ---------------------------------------------------------------------------

def disband_party(party_name: str, reason: str = "") -> bool:
    """The crew breaks up. Members become free agents (party_name cleared)."""
    if _is_protected(party_name):
        return False
    prof = pp.load_profile(party_name)
    if not prof:
        return False
    for m in (prof.get("members") or []):
        nm = (m.get("name") or "").strip()
        if nm:
            _unlink_npc(nm)
            _npc_hist(nm, f"[{_today()}] {party_name} disbanded{(' -- ' + reason) if reason else ''}. Now a free agent.")
    _set_party_columns(party_name, status="disbanded")
    _phist(party_name, f"[{_today()}] The crew disbanded{(' -- ' + reason) if reason else ''}.")
    logger.info(f"\U0001f4a8 Party disbanded: {party_name}{(' (' + reason + ')') if reason else ''}")
    return True


# ---------------------------------------------------------------------------
# MISSION CASUALTIES (called from mission_board._apply_mission_consequences)
# ---------------------------------------------------------------------------

VIOLENT_MISSION_TYPES = ("battle", "assault", "ambush", "defense", "defend",
                         "assassination", "infestation", "rescue", "extraction")


def _living_members(party_name: str) -> List[str]:
    rows = raw_query(
        "SELECT name FROM npcs WHERE party_name=%s "
        "AND (status IS NULL OR status NOT IN ('dead','deceased'))",
        (party_name,)) or []
    return [r["name"] for r in rows]


def destroy_party(party_name: str, cause: str = "") -> List[str]:
    """WIPEOUT: the crew is shattered in the field. Every living member is
    wounded (the NPC lifecycle then resolves each: ~90% recover as scattered
    survivors, ~10% die -- no direct killing here, deaths emerge organically)
    and the crew is struck from the registry. Never touches protected parties.
    Returns the wounded member names."""
    if _is_protected(party_name):
        return []
    from src.npc_lifecycle import wound_npc_in_combat
    wounded = []
    for nm in _living_members(party_name):
        try:
            if wound_npc_in_combat(nm, cause or f"the destruction of {party_name}"):
                wounded.append(nm)
        except Exception:
            pass
        _unlink_npc(nm)
        _npc_hist(nm, f"[{_today()}] {party_name} was destroyed in the field{(' -- ' + cause) if cause else ''}. A survivor, if the wounds allow.")
    _set_party_columns(party_name, status="destroyed")
    _phist(party_name, f"[{_today()}] The crew was destroyed in the field{(' -- ' + cause) if cause else ''}.")
    logger.info(f"\U0001f480 Party destroyed: {party_name} ({len(wounded)} wounded, lifecycle resolves their fates)")
    return wounded


def mission_party_casualties(party_name: str, mission: dict, success: bool) -> dict:
    """Butterfly: violent missions cost the claiming NPC crew blood.

    Gates/guardrails: only VIOLENT_MISSION_TYPES; protected parties skipped;
    ordinary outcome is ONE wounded member (fail 35%, success 12%) which the
    NPC lifecycle resolves (~90% recover / ~10% graveyard); a full wipeout is
    rare (4%) and only on FAILED difficulty>=8 violence. Returns
    {"wounded": [names], "destroyed": bool}."""
    out = {"wounded": [], "destroyed": False}
    mtype = str(mission.get("type") or mission.get("mission_type") or "").lower()
    if not party_name or _is_protected(party_name):
        return out
    if not any(v in mtype for v in VIOLENT_MISSION_TYPES):
        return out
    try:
        difficulty = int(mission.get("difficulty") or 5)
    except Exception:
        difficulty = 5
    try:
        from src.npc_lifecycle import wound_npc_in_combat
        title = mission.get("title") or "a violent contract"
        members = _living_members(party_name)
        if not members:
            return out
        # WIPEOUT: rare, and only when a hard fight was lost badly.
        if not success and difficulty >= 8 and random.random() < 0.04:
            out["wounded"] = destroy_party(party_name, f"wiped out during '{title}'")
            out["destroyed"] = True
            return out
        # The ordinary blood price: one member wounded.
        if random.random() < (0.35 if not success else 0.12):
            nm = random.choice(members)
            if wound_npc_in_combat(nm, f"{'the failed ' if not success else ''}mission '{title}'"):
                out["wounded"].append(nm)
                _phist(party_name, f"[{_today()}] {nm} was wounded during '{title}'.")
    except Exception as e:
        logger.warning(f"mission_party_casualties error: {e}")
    return out


# ---------------------------------------------------------------------------
# Ambient tick (gated; call from a background loop)
# ---------------------------------------------------------------------------

def _unused_name_count() -> int:
    row = raw_query(
        "SELECT COUNT(*) c FROM adventurer_parties ap "
        "LEFT JOIN party_profiles pp ON pp.party_name = ap.party_name WHERE pp.id IS NULL")
    return int(row[0]["c"]) if row else 0


async def replenish_party_name_pool(min_free: int = 20, batch: int = 20) -> int:
    """Keep a reservoir of unused, LLM-generated (non-filler) crew names in
    adventurer_parties so formation/splitting always have a name to draw. Async;
    call from the background loop before party_lifecycle_tick(). Returns names added."""
    if _unused_name_count() >= min_free:
        return 0
    try:
        from src.mission_board import _generate_party_names
        new_names = await _generate_party_names(batch)
    except Exception as e:
        logger.debug(f"replenish_party_name_pool generation skipped: {e}")
        return 0
    added = 0
    for nm in (new_names or []):
        try:
            raw_execute("INSERT IGNORE INTO adventurer_parties (party_name) VALUES (%s)", (nm,))
            added += 1
        except Exception:
            pass
    if added:
        logger.info(f"\U0001f4db Replenished party name pool: +{added} crew names")
    return added


def _free_independent_count() -> int:
    row = raw_query(
        "SELECT COUNT(*) c FROM npcs WHERE (party_name IS NULL OR party_name='') "
        "AND (status IS NULL OR status IN ('alive','injured')) AND faction='Independent'")
    return int(row[0]["c"]) if row else 0


async def replenish_free_agents(min_free: int = 6, batch: int = 2) -> int:
    """Keep enough unaffiliated Independent NPCs in the city for crew formation
    and splits to recruit WITHOUT gutting faction rosters (_free_agent_npcs
    prefers Independents). Mints fully-generated NPCs via
    npc_lifecycle.generate_new_npc (LLM: real name, secret, quote -- no filler).
    Async; call from the background loop before party_lifecycle_tick().
    Returns NPCs added (capped at `batch` per tick so the city grows slowly)."""
    free = _free_independent_count()
    if free >= min_free:
        return 0
    added = 0
    try:
        from src.npc_lifecycle import generate_new_npc, _load_npcs, _save_npc
        npcs = _load_npcs()
        for _ in range(min(batch, min_free - free)):
            npc = await generate_new_npc(npcs, faction_override="Independent")
            if not npc:
                break
            _save_npc(npc)
            npcs.append(npc)
            _npc_hist(npc.get("name", ""),
                      f"[{_today()}] Arrived in the city as an independent -- looking for crew work.")
            added += 1
    except Exception as e:
        logger.warning(f"replenish_free_agents error: {e}")
    if added:
        logger.info(f"\U0001f9f3 Minted {added} Independent free-agent NPC(s) for crew recruitment")
    return added


def _active_party_count() -> int:
    row = raw_query("SELECT COUNT(*) c FROM party_profiles WHERE status='active'")
    return int(row[0]["c"]) if row else 0


def party_lifecycle_tick() -> dict:
    """One ambient pass: keep the floor, and occasionally split / merge / form.
    Everything is gated and guarded so the pool neither collapses nor floods.
    Mission-driven casualties are handled elsewhere. Returns a summary dict."""
    summary = {"formed": [], "split": [], "merged": []}
    try:
        active = _active_party_count()

        # 1) maintain the floor -- form up to 2 crews if we are short
        if active < MIN_ACTIVE_PARTIES:
            for _ in range(2):
                nm = form_party()
                if nm:
                    summary["formed"].append(nm)
                    active += 1

        # 2) occasionally a healthy crew splinters (Iron Fang crews favoured)
        if random.random() < 0.15:
            cand = raw_query(
                "SELECT party_name, faction FROM party_profiles WHERE status='active' "
                "ORDER BY RAND() LIMIT 25") or []
            for c in cand:
                nm = c["party_name"]
                if _is_protected(nm):
                    continue
                prof = pp.load_profile(nm) or {}
                if len(prof.get("members") or []) >= SPLIT_MIN_MEMBERS:
                    # Iron Fang crews split readily during the civil war
                    fav = (c.get("faction") or "").strip().lower() in _IRON_FANG
                    if fav or random.random() < 0.5:
                        new = split_party(nm)
                        if new:
                            summary["split"].append((nm, new))
                        break

        # 3) rarely, two small crews merge
        if random.random() < 0.10:
            smalls = []
            for c in (raw_query("SELECT party_name FROM party_profiles WHERE status='active' "
                                "ORDER BY RAND() LIMIT 30") or []):
                nm = c["party_name"]
                if _is_protected(nm):
                    continue
                prof = pp.load_profile(nm) or {}
                if 0 < len(prof.get("members") or []) <= 2:
                    smalls.append(nm)
                if len(smalls) >= 2:
                    break
            if len(smalls) >= 2 and merge_parties(smalls[0], smalls[1], "mutual survival"):
                summary["merged"].append((smalls[1], smalls[0]))
    except Exception as e:
        logger.warning(f"party_lifecycle_tick error: {e}")
    return summary
