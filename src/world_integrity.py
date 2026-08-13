"""
world_integrity.py -- catch the world contradicting itself.

Written after the Adventurers Guild spent two months being run by a corpse.
`faction_reputation.leader` said "Aldric Vane (Guildmaster)" while `npcs.status`
said dead, and nothing anywhere compared the two. The same audit turned up
`resurrection_queue.status = 'lost_to_tower'` sitting next to `npcs.tower_absorbed
= 0` (the two death markers disagreeing), and JSON shadow copies of real columns
drifting out of sync.

None of these throw. They just quietly make the world wrong, and every downstream
prompt inherits the wrongness. So: check them on a schedule and say so out loud.

Every check is read-only and returns findings. `repair()` fixes only the ones that
are unambiguous -- a desynced shadow copy has an obvious correct answer (the
column wins), whereas a dead faction leader is a story decision and only ever gets
reported.
"""
from __future__ import annotations

import json
from typing import Any

from src.db_api import raw_query, raw_execute
from src.log import logger

# data_json / profile_json mirror these real columns. The column is authoritative;
# the blob copy is a denormalised cache that any direct UPDATE silently desyncs.
_NPC_MIRRORED = ("name", "faction", "status", "rank", "motivation", "secret",
                 "role", "location", "species")


def dead_faction_leaders() -> list[dict[str, Any]]:
    """Factions whose listed leader is dead, missing, or not on the roster."""
    findings: list[dict[str, Any]] = []
    rows = raw_query(
        "SELECT faction_name, leader FROM faction_reputation "
        "WHERE leader IS NOT NULL AND leader <> ''"
    ) or []

    for row in rows:
        raw_name = str(row["leader"]).strip()
        # Stored as "Aldric Vane (Guildmaster)" -- the title is not part of the name.
        name = raw_name.split("(")[0].strip()
        if not name:
            continue
        npc = raw_query(
            "SELECT id, name, status FROM npcs WHERE name = %s LIMIT 1", (name,)
        ) or []
        if not npc:
            # Leaders are stored with the title glued on ("Archivist Eir Velan"),
            # so fall back to the same resolver the dialog caster uses before
            # declaring anyone missing.
            try:
                from src.npc_dossier import resolve_npc
                match = resolve_npc(name, str(row["faction_name"]))
                if match:
                    npc = [match]
            except Exception:
                pass
        if not npc:
            findings.append({"check": "leader_missing", "faction": row["faction_name"],
                             "leader": name,
                             "detail": "listed leader is not on the NPC roster"})
        elif str(npc[0]["status"]).lower() != "alive":
            findings.append({"check": "leader_dead", "faction": row["faction_name"],
                             "leader": name, "npc_id": npc[0]["id"],
                             "detail": f"faction is led by someone marked "
                                       f"'{npc[0]['status']}'"})
    return findings


def resurrection_disagreements() -> list[dict[str, Any]]:
    """`resurrection_queue` and the NPC row telling different stories.

    The queue is append-only with no dedupe, so one NPC can carry several rows
    with contradictory verdicts (Tarn Veyne had three; Sera Veyne had both a
    'raised' and a 'lost_to_tower'). The LATEST row wins -- a later raising
    overturns an earlier absorption, which is also how the fiction works.
    """
    findings: list[dict[str, Any]] = []
    rows = raw_query(
        "SELECT q.npc_name, q.status AS queue_status, n.id, n.status AS npc_status, "
        "n.tower_absorbed FROM resurrection_queue q "
        "JOIN npcs n ON n.name = q.npc_name "
        "JOIN (SELECT npc_name, MAX(id) AS latest FROM resurrection_queue "
        "      GROUP BY npc_name) m "
        "  ON m.npc_name = q.npc_name AND m.latest = q.id"
    ) or []

    for row in rows:
        q, s = str(row["queue_status"]).lower(), str(row["npc_status"]).lower()
        absorbed = bool(row["tower_absorbed"])

        if q == "lost_to_tower" and not absorbed:
            findings.append({"check": "absorbed_flag_missing", "npc": row["npc_name"],
                             "npc_id": row["id"],
                             "detail": "queue says lost_to_tower but tower_absorbed=0"})
        if q == "lost_to_tower" and s == "alive":
            # REPORT ONLY, never repaired. A sweep must not kill anyone -- same
            # principle as the Unknown Party guard. If they are walking around,
            # the roster is the thing to believe and the queue row is stale.
            findings.append({"check": "walking_while_absorbed", "npc": row["npc_name"],
                             "npc_id": row["id"],
                             "detail": "queue says lost_to_tower but they are alive "
                                       "(report only -- never auto-killed)"})
        if q == "raised" and s == "dead":
            findings.append({"check": "raised_but_dead", "npc": row["npc_name"],
                             "npc_id": row["id"],
                             "detail": "queue says raised but the NPC is still dead"})
    return findings


def blob_divergence(limit: int = 500) -> list[dict[str, Any]]:
    """JSON shadow copies that no longer match their real column."""
    findings: list[dict[str, Any]] = []
    cols = ", ".join(f"`{c}`" for c in _NPC_MIRRORED)
    rows = raw_query(
        f"SELECT id, {cols}, data_json FROM npcs LIMIT %s", (int(limit),)
    ) or []

    for row in rows:
        blob = row.get("data_json")
        if isinstance(blob, str):
            try:
                blob = json.loads(blob)
            except Exception:
                continue
        if not isinstance(blob, dict):
            continue
        for field in _NPC_MIRRORED:
            if field not in blob:
                continue
            col_val = str(row.get(field) or "").strip()
            blob_val = str(blob.get(field) or "").strip()
            if col_val != blob_val:
                findings.append({
                    "check": "blob_divergence", "npc": row.get("name"),
                    "npc_id": row["id"], "field": field,
                    "detail": f"column={col_val!r} blob={blob_val!r}",
                })
    return findings


def orphaned_bonds() -> list[dict[str, Any]]:
    """Bonds pointing at NPCs that no longer exist."""
    rows = raw_query(
        "SELECT b.id, b.npc_a_id, b.npc_b_id FROM npc_bonds b "
        "LEFT JOIN npcs a ON a.id = b.npc_a_id "
        "LEFT JOIN npcs c ON c.id = b.npc_b_id "
        "WHERE a.id IS NULL OR c.id IS NULL"
    ) or []
    return [{"check": "orphan_bond", "bond_id": r["id"],
             "detail": f"{r['npc_a_id']} -> {r['npc_b_id']} has a missing endpoint"}
            for r in rows]


def run_all() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for check in (dead_faction_leaders, resurrection_disagreements,
                  blob_divergence, orphaned_bonds):
        try:
            findings.extend(check())
        except Exception as exc:
            logger.warning(f"[integrity] {check.__name__} failed: {exc}")
    return findings


def repair(findings: list[dict[str, Any]] | None = None) -> list[str]:
    """Fix only what has an unambiguous correct answer.

    A desynced shadow copy is safe to repair -- the real column is authoritative
    by definition. A dead faction leader is NOT: whether the Guild promotes a
    successor or raises the old one is a story decision, so it is only ever
    reported.
    """
    findings = findings if findings is not None else run_all()
    fixed: list[str] = []

    # 0. A living NPC with a 'lost_to_tower' row means the QUEUE is stale, not the
    #    person. Retire the row instead of touching the character -- the roster is
    #    the thing to believe when someone is demonstrably walking around.
    for f in findings:
        if f["check"] != "walking_while_absorbed":
            continue
        try:
            raw_execute(
                "UPDATE resurrection_queue SET status='superseded' "
                "WHERE npc_name=%s AND status='lost_to_tower'",
                (str(f["npc"]),),
            )
            fixed.append(f"retired stale lost_to_tower row for {f['npc']} (they are alive)")
        except Exception as exc:
            logger.warning(f"[integrity] queue retire failed: {exc}")

    # 1. Shadow copies: the column wins. Deliberately recomputed AFTER the status
    #    repairs below would have run -- see the re-scan at the end.
    stale = {f["npc_id"] for f in findings if f["check"] == "blob_divergence"}
    for npc_id in stale:
        rows = raw_query(
            "SELECT id, " + ", ".join(f"`{c}`" for c in _NPC_MIRRORED)
            + ", data_json FROM npcs WHERE id = %s", (int(npc_id),)
        ) or []
        if not rows:
            continue
        row = rows[0]
        blob = row.get("data_json")
        if isinstance(blob, str):
            try:
                blob = json.loads(blob)
            except Exception:
                continue
        if not isinstance(blob, dict):
            continue
        for field in _NPC_MIRRORED:
            if field in blob:
                blob[field] = row.get(field)
        try:
            raw_execute("UPDATE npcs SET data_json = %s WHERE id = %s",
                        (json.dumps(blob, default=str), int(npc_id)))
            fixed.append(f"resynced data_json for npc {npc_id}")
        except Exception as exc:
            logger.warning(f"[integrity] resync failed for {npc_id}: {exc}")

    # 2. The absorbed flag: the queue already made the call, the column just
    #    never heard about it. Only safe when the NPC is genuinely dead.
    for f in findings:
        if f["check"] != "absorbed_flag_missing":
            continue
        rows = raw_query("SELECT status FROM npcs WHERE id = %s",
                         (int(f["npc_id"]),)) or []
        if rows and str(rows[0]["status"]).lower() == "dead":
            try:
                raw_execute("UPDATE npcs SET tower_absorbed = 1 WHERE id = %s",
                            (int(f["npc_id"]),))
                fixed.append(f"marked {f['npc']} as absorbed by the Tower")
            except Exception as exc:
                logger.warning(f"[integrity] absorb flag failed: {exc}")

    # 3. The queue raised them and the roster never caught up. Bring them back
    #    properly -- status, bonds, and a history entry -- rather than leaving a
    #    character the world already decided to save sitting in the graveyard.
    for f in findings:
        if f["check"] != "raised_but_dead":
            continue
        npc_id = int(f["npc_id"])
        try:
            raw_execute(
                "UPDATE npcs SET status='alive', deceased_at=NULL, tower_absorbed=0 "
                "WHERE id=%s AND status='dead'",
                (npc_id,),
            )
            from src.db_api import add_npc_history_event
            from src.npc_bonds import restore_on_return
            from datetime import datetime
            add_npc_history_event(
                npc_id,
                "Returned. The raising had already gone through; the paperwork "
                "simply never reached the roster.",
                datetime.now().strftime("%Y-%m-%d"), "return",
            )
            restore_on_return(npc_id, str(f["npc"]), "resurrection")
            fixed.append(f"restored {f['npc']} (queue said raised, roster said dead)")
        except Exception as exc:
            logger.warning(f"[integrity] raise repair failed for {f['npc']}: {exc}")

    # 4. Orphaned bonds are simply garbage.
    orphans = [f["bond_id"] for f in findings if f["check"] == "orphan_bond"]
    for bond_id in orphans:
        try:
            raw_execute("DELETE FROM npc_bonds WHERE id = %s", (int(bond_id),))
            fixed.append(f"removed orphaned bond {bond_id}")
        except Exception as exc:
            logger.warning(f"[integrity] orphan delete failed: {exc}")

    # 5. The status repairs above wrote columns directly, which desyncs the very
    #    shadow copies step 1 just fixed. Re-scan and resync so a single pass
    #    leaves the world consistent instead of needing to be run twice.
    for f in blob_divergence():
        npc_id = int(f["npc_id"])
        rows = raw_query(
            "SELECT id, " + ", ".join(f"`{c}`" for c in _NPC_MIRRORED)
            + ", data_json FROM npcs WHERE id = %s", (npc_id,)
        ) or []
        if not rows:
            continue
        blob = rows[0].get("data_json")
        if isinstance(blob, str):
            try:
                blob = json.loads(blob)
            except Exception:
                continue
        if not isinstance(blob, dict):
            continue
        for field in _NPC_MIRRORED:
            if field in blob:
                blob[field] = rows[0].get(field)
        try:
            raw_execute("UPDATE npcs SET data_json = %s WHERE id = %s",
                        (json.dumps(blob, default=str), npc_id))
            fixed.append(f"resynced data_json for {f.get('npc')} (post-repair)")
        except Exception as exc:
            logger.warning(f"[integrity] post-repair resync failed: {exc}")

    return fixed


def summarise(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "world integrity: clean"
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["check"]] = counts.get(f["check"], 0) + 1
    return "world integrity: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
