"""Move global_state['world_active_tensions'] into the world_tensions table.

Idempotent. Archives the payload under world_active_tensions_archived_json and
empties the live key, matching the council/ads convention.
"""

import argparse
import json
import sys

sys.path.insert(0, r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot')
from dotenv import load_dotenv
load_dotenv(r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot\.env')

from src.db_api import (  # noqa: E402
    get_global_state, set_global_state, raw_query,
    add_tension, get_active_tensions, _ensure_tension_table,
)

ARCHIVE_KEY = "world_active_tensions_archived_json"


def main(apply: bool) -> None:
    _ensure_tension_table()
    blob = get_global_state("world_active_tensions") or []
    if isinstance(blob, str):
        blob = json.loads(blob)
    items = [str(t).strip() for t in blob if str(t).strip()]
    existing = len(get_active_tensions())

    print(f"blob tensions : {len(items)} ({len(set(items))} unique)")
    print(f"in table      : {existing}")

    if existing >= len(set(items)) and existing > 0:
        print("already migrated -- skipping insert")
    elif apply:
        for t in items:
            add_tension(t)
        print(f"migrated: {len(items)}")
    else:
        print(f"would migrate: {len(items)}")

    if apply:
        now = len(get_active_tensions())
        if now == 0:
            print("!! refusing to archive with an empty table")
            return
        payload = blob if isinstance(blob, str) else json.dumps(blob, ensure_ascii=False)
        set_global_state(ARCHIVE_KEY, payload)
        set_global_state("world_active_tensions", "[]")
        print(f"\narchived {len(payload)} bytes -> global_state['{ARCHIVE_KEY}']; live key emptied")
        print(f"active tensions in table: {now}")
        rows = raw_query("SELECT tension FROM world_tensions WHERE active=1 ORDER BY id LIMIT 3") or []
        for r in rows:
            print("   -", r["tension"][:90])
    else:
        print("\nDRY RUN -- pass --apply")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    main(ap.parse_args().apply)
