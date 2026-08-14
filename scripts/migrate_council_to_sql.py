"""Move the Grand Council out of Python literals and a JSON blob into MySQL.

Run with --apply. Idempotent: seats upsert by name, rulings are skipped if the
table already holds them.

What changes in the world, not just the schema:
  - The council presidency passes from "Guildmaster Mari Fen" -- a title she has
    never held; she is rank Member and runs the Adventurers Guild front desk --
    to the Tower Authority / FTA.
  - Mari Fen keeps her actual job. She was only ever mislabelled here.
"""

import argparse
import json
import sys
from datetime import datetime

sys.path.insert(0, r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot')
from dotenv import load_dotenv
load_dotenv(r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot\.env')

from src.db_api import get_global_state, set_global_state, raw_query  # noqa: E402
from src import council_registry as cr  # noqa: E402

ARCHIVE_KEY = "council_rulings_archived_json"

# The FTA takes the chair. Kaelen Voss over Gideon Steelforge (whose role line
# is the better fit on paper) because the seat prompt feeds motivation, secret
# and oracle_notes into every vote and dissent -- Kaelen has all three, Gideon
# has none, and an empty dossier is exactly how a council seat ends up sounding
# like a form letter.
NEW_PRESIDENT = {
    "name":    "Kaelen Voss",
    "faction": "Tower Authority / FTA",
    "title":   "Senior Officer, FTA — President of the Grand Council",
    "agenda":  "Containment of rift breaches, protocol integrity, Tower continuity above any guild's quarter",
    "bias":    "Tiebreaker only. Breaks ties toward whatever keeps the Dome intact and the protocols enforceable, even when it costs a guild dearly. Will not be seen to favour the FTA, and overcorrects against it in public.",
    "voice":   "Measured, procedural, tired in a way that predates this council. Speaks in contingencies. Never raises their voice; the room quiets anyway.",
}


def migrate_seats(apply: bool) -> None:
    from src.agents.guild_council import COUNCIL_MEMBERS, COUNCIL_PRESIDENT

    print("=== SEATS ===")
    print(f"  old president: {COUNCIL_PRESIDENT['name']} ({COUNCIL_PRESIDENT['faction']})")
    print(f"  new president: {NEW_PRESIDENT['name']} ({NEW_PRESIDENT['faction']})")
    npc_id = cr.resolve_seat_npc_id(NEW_PRESIDENT["name"])
    print(f"  resolved to npcs.id = {npc_id}")
    if npc_id is None:
        print("  !! could not resolve the new president to a real NPC -- aborting")
        return

    for i, m in enumerate(COUNCIL_MEMBERS):
        rid = cr.resolve_seat_npc_id(m["name"])
        print(f"  member {i}: {m['name']:28s} -> npcs.id {rid}")
        if apply:
            cr.upsert_seat(m, cr.SEAT_MEMBER, sort_order=i, npc_id=rid)

    if apply:
        cr.upsert_seat(NEW_PRESIDENT, cr.SEAT_PRESIDENT, sort_order=0, npc_id=npc_id)
        # Mari Fen never held the chair in the world -- only in this table.
        cr.retire_seat(COUNCIL_PRESIDENT["name"])
        cr.retire_seat("Mari Fen")


def migrate_rulings(apply: bool) -> None:
    print("\n=== RULINGS ===")
    existing = cr.ruling_count() if apply else cr.ruling_count()
    blob = get_global_state("council_rulings") or []
    if isinstance(blob, str):
        blob = json.loads(blob)
    print(f"  JSON blob entries : {len(blob)}")
    print(f"  rows already in DB: {existing}")

    if existing >= len(blob) and existing > 0:
        print("  already migrated -- skipping")
        return

    migrated = 0
    for entry in blob:
        if not isinstance(entry, dict):
            continue
        raw_date = entry.get("date") or ""
        try:
            when = datetime.fromisoformat(raw_date) if raw_date else datetime.now()
        except ValueError:
            when = datetime.now()
        if apply:
            cr.record_ruling(
                topic=entry.get("topic") or "",
                proposal=entry.get("proposal") or "",
                passed=bool(entry.get("passed")),
                tiebreak=bool(entry.get("tiebreak")),
                votes_yes=entry.get("votes_yes") or [],
                votes_no=entry.get("votes_no") or [],
                ruled_at=when,
            )
        migrated += 1
    print(f"  migrated: {migrated}")


def archive_blob(apply: bool) -> None:
    print("\n=== ARCHIVE ===")
    blob = get_global_state("council_rulings")
    if blob is None:
        print("  council_rulings already archived")
        return
    rows = cr.ruling_count()
    payload = blob if isinstance(blob, str) else json.dumps(blob)
    print(f"  rows in council_rulings table: {rows}")
    print(f"  blob size: {len(payload)} bytes -> global_state['{ARCHIVE_KEY}']")
    if rows == 0:
        print("  !! refusing to archive with an empty table")
        return
    if apply:
        # Keep the original payload under a new key rather than deleting it.
        set_global_state(ARCHIVE_KEY, payload)
        set_global_state("council_rulings", "[]")
        print("  archived; live key emptied")


def verify() -> None:
    print("\n=== VERIFY ===")
    pres = cr.get_president()
    members = cr.get_members()
    print(f"  president: {pres['name'] if pres else 'NONE'} ({pres['faction'] if pres else '-'})")
    print(f"  members  : {len(members)} -> {[m['name'] for m in members]}")
    print(f"  rulings  : {cr.ruling_count()}")
    recent = cr.recent_rulings(3)
    for r in recent:
        print(f"    [{r['date'][:10]}] {r['topic']} passed={r['passed']}")
    seated = raw_query(
        "SELECT name, seat_role, npc_id, active FROM council_seats ORDER BY seat_role, sort_order"
    ) or []
    unlinked = [s["name"] for s in seated if s["active"] and not s["npc_id"]]
    print(f"  seats with no npcs row: {unlinked or 'none'}")
    mari = raw_query("SELECT active FROM council_seats WHERE name='Mari Fen'") or []
    if mari:
        print(f"  Mari Fen seat active: {bool(mari[0]['active'])} (should be False)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cr.ensure_schema()
    migrate_seats(args.apply)
    migrate_rulings(args.apply)
    archive_blob(args.apply)
    if args.apply:
        verify()
    else:
        print("\nDRY RUN -- pass --apply")
