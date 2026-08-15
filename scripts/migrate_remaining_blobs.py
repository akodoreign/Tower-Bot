"""Move the last of the row-shaped global_state blobs into real tables.

  wealth_event_log          -> district_wealth_events
  used_parties              -> used_parties
  towerbay_npc_acquisitions -> towerbay_npc_acquisitions

Each archives its payload under <key>_archived_json and empties the live key,
the convention the council/ads/tensions migrations established.

NOT migrated, deliberately:
  arena_venues       -- nested reference config (meta / venues /
                        notable_personalities / event_type_descriptions), read
                        whole by news_agents. Genuinely schemaless.
  public_health_arcs -- nested plot state (arcs / false_cures / updated_at)
                        read whole by mission_board and news_feed.
  rift_history       -- 7 entries and NO readers anywhere in the codebase.
                        Left alone rather than built a table nothing consumes.
"""

import argparse
import json
import sys
from datetime import datetime

sys.path.insert(0, r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot')
from dotenv import load_dotenv
load_dotenv(r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot\.env')

from src.db_api import (  # noqa: E402
    get_global_state, set_global_state, raw_query, raw_execute, db,
    _ensure_wealth_log_table,
)


def _archive(key: str, blob) -> None:
    payload = blob if isinstance(blob, str) else json.dumps(blob, ensure_ascii=False)
    set_global_state(f"{key}_archived_json", payload)
    set_global_state(key, "[]")
    print(f"   archived {len(payload)} bytes -> {key}_archived_json; live key emptied")


def _blob(key):
    d = get_global_state(key) or []
    return json.loads(d) if isinstance(d, str) else d


def wealth(apply: bool) -> None:
    _ensure_wealth_log_table()
    events = [e for e in _blob("wealth_event_log") if isinstance(e, dict)]
    have = raw_query("SELECT COUNT(*) c FROM district_wealth_events")[0]["c"]
    print(f"wealth_event_log: blob={len(events)} table={have}")
    if have >= len(events) and have > 0:
        print("   already migrated")
    elif apply:
        for e in events:
            ts = e.get("ts") or ""
            try:
                when = datetime.fromisoformat(ts) if ts else datetime.now()
            except ValueError:
                when = datetime.now()
            db.insert("district_wealth_events", {
                "district":   str(e.get("district") or "")[:120],
                "old_level":  e.get("old"),
                "new_level":  e.get("new"),
                "delta":      e.get("delta"),
                "reason":     str(e.get("reason") or "")[:400],
                "created_at": when,
            })
        print(f"   migrated {len(events)}")
    if apply and raw_query("SELECT COUNT(*) c FROM district_wealth_events")[0]["c"]:
        _archive("wealth_event_log", _blob("wealth_event_log"))


def parties(apply: bool) -> None:
    from src.mission_board import _ensure_used_parties_table
    _ensure_used_parties_table()
    names = [str(n).strip() for n in _blob("used_parties") if str(n).strip()]
    have = raw_query("SELECT COUNT(*) c FROM used_parties")[0]["c"]
    print(f"used_parties: blob={len(names)} ({len(set(names))} unique) table={have}")
    if have >= len(set(names)) and have > 0:
        print("   already migrated")
    elif apply:
        now = datetime.now()
        for n in names:
            raw_execute(
                "INSERT INTO used_parties (party_name, used_at) VALUES (%s,%s) "
                "ON DUPLICATE KEY UPDATE used_at = used_at", (n[:200], now))
        print(f"   migrated {len(names)}")
    if apply and raw_query("SELECT COUNT(*) c FROM used_parties")[0]["c"]:
        _archive("used_parties", _blob("used_parties"))


def acquisitions(apply: bool) -> None:
    raw_execute(
        """
        CREATE TABLE IF NOT EXISTS towerbay_npc_acquisitions (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            item       VARCHAR(200) NOT NULL,
            rarity     VARCHAR(40)  NULL,
            winner     VARCHAR(200) NULL,
            faction    VARCHAR(120) NULL,
            final_bid  INT          NULL,
            sold_at    DATETIME     NULL,
            created_at DATETIME     NOT NULL,
            KEY idx_faction (faction),
            KEY idx_winner (winner),
            KEY idx_sold (sold_at)
        )
        """, ())
    rows = [a for a in _blob("towerbay_npc_acquisitions") if isinstance(a, dict)]
    have = raw_query("SELECT COUNT(*) c FROM towerbay_npc_acquisitions")[0]["c"]
    print(f"towerbay_npc_acquisitions: blob={len(rows)} table={have}")
    if have >= len(rows) and have > 0:
        print("   already migrated")
    elif apply:
        for a in rows:
            sold = a.get("sold_at") or ""
            try:
                when = datetime.fromisoformat(sold) if sold else None
            except ValueError:
                when = None
            db.insert("towerbay_npc_acquisitions", {
                "item":       str(a.get("item") or "")[:200],
                "rarity":     (a.get("rarity") or None),
                "winner":     (a.get("winner") or None),
                "faction":    (a.get("faction") or None),
                "final_bid":  a.get("final_bid"),
                "sold_at":    when,
                "created_at": datetime.now(),
            })
        print(f"   migrated {len(rows)}")
    if apply and raw_query("SELECT COUNT(*) c FROM towerbay_npc_acquisitions")[0]["c"]:
        _archive("towerbay_npc_acquisitions", _blob("towerbay_npc_acquisitions"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    wealth(a.apply)
    parties(a.apply)
    acquisitions(a.apply)
    if not a.apply:
        print("\nDRY RUN -- pass --apply")
