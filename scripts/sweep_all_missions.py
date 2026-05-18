"""
sweep_all_missions.py — One-time mission board reset.

Sets ALL currently active/claimed missions to 'expired' so the board can
start fresh. NPC-only missions get npc_claimed status then expired.
Personal missions (personal_for set) get rescinded.

Run from project root:
    python scripts/sweep_all_missions.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db_api import raw_query, raw_execute

def run():
    rows = raw_query(
        "SELECT id, title, status, faction, tier, "
        "IFNULL(JSON_UNQUOTE(JSON_EXTRACT(mission_json, '$.personal_for')), '') AS personal_for "
        "FROM missions WHERE status IN ('active', 'claimed', 'npc_claimed') "
        "ORDER BY id"
    ) or []

    if not rows:
        print("No active missions found — board is already clean.")
        return

    print(f"Found {len(rows)} missions to sweep.\n")

    personal, board = [], []
    for r in rows:
        if r.get("personal_for") and r["personal_for"] not in (None, "null", ""):
            personal.append(r)
        else:
            board.append(r)

    # Expire normal board missions (including npc_claimed)
    if board:
        ids = tuple(r["id"] for r in board)
        placeholders = ",".join(["%s"] * len(ids))
        raw_execute(
            f"UPDATE missions SET status = 'expired' WHERE id IN ({placeholders})",
            ids,
        )
        print(f"Expired {len(board)} board missions:")
        for r in board:
            print(f"  [{r['id']}] {r['title']} ({r['status']} -> expired)")

    # Rescind personal missions
    if personal:
        ids = tuple(r["id"] for r in personal)
        placeholders = ",".join(["%s"] * len(ids))
        raw_execute(
            f"UPDATE missions SET status = 'expired' WHERE id IN ({placeholders})",
            ids,
        )
        print(f"\nRescinded {len(personal)} personal missions:")
        for r in personal:
            print(f"  [{r['id']}] {r['title']} (personal for: {r['personal_for']})")

    # Reset used_parties so NPC claims start fresh
    raw_execute(
        "UPDATE global_state SET state_value = '[]' WHERE state_key = 'used_parties'"
    )
    print("\nReset used_parties list.")

    remaining = raw_query(
        "SELECT COUNT(*) as cnt FROM missions WHERE status IN ('active','claimed','npc_claimed')"
    )
    cnt = remaining[0]["cnt"] if remaining else "?"
    print(f"\nDone. Active missions remaining: {cnt}")
    print("Restart the bot — it will post fresh missions on the next trickle cycle.")

if __name__ == "__main__":
    run()
