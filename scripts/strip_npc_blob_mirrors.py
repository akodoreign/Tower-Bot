"""Remove mirrored real-column keys from npcs.data_json.

Step 3 of retiring the mirror. Steps 1 and 2 (widen every roster reader, stop
writing the mirror) must already be in place -- this only cleans what earlier
writes left behind.

Safety: a key is stripped ONLY when the blob value agrees with the column, or
the column is populated and the blob's copy is therefore redundant. If a blob
holds something the column does NOT have, the row is left alone and reported,
because that is data, not duplication.

Run with --apply.
"""

import argparse
import json
import re
import sys

sys.path.insert(0, r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot')
from dotenv import load_dotenv
load_dotenv(r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot\.env')

from src.db_api import raw_query, raw_execute  # noqa: E402
from src.npc_lifecycle import _BLOB_EXCLUDE  # noqa: E402


def norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
    return str(v).strip()


def generated_column_deps(table: str) -> set:
    """JSON keys that a GENERATED column reads. These can never be stripped.

    `npcs.species` is VIRTUAL GENERATED from
    coalesce(data_json->'$.species', data_json->'$.race') -- the column is
    DERIVED FROM the blob, not a copy of it. Treating those keys as mirrors and
    removing them emptied the column for all 250 NPCs. Detected from
    information_schema rather than remembered, so a new generated column is
    protected automatically.
    """
    deps = set()
    rows = raw_query(
        "SELECT COLUMN_NAME, GENERATION_EXPRESSION FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
        "AND GENERATION_EXPRESSION <> ''",
        (table,),
    ) or []
    for r in rows:
        for key in re.findall(r"\$\.([A-Za-z_][A-Za-z0-9_]*)", str(r.get("GENERATION_EXPRESSION") or "")):
            deps.add(key)
        # The generated column's own name is not a mirror either.
        if r.get("COLUMN_NAME"):
            deps.add(str(r["COLUMN_NAME"]))
    return deps


def main(apply: bool) -> None:
    columns = {r["Field"] for r in raw_query("SHOW COLUMNS FROM npcs") or []}
    protected = generated_column_deps("npcs")
    if protected:
        print(f"protected by generated columns (never stripped): {sorted(protected)}")
    rows = raw_query("SELECT * FROM npcs") or []

    stripped_keys = {}
    kept_conflicts = []
    changed = 0
    bytes_before = bytes_after = 0

    for r in rows:
        raw = r.get("data_json")
        if not raw:
            continue
        try:
            blob = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if not isinstance(blob, dict):
            continue

        bytes_before += len(raw if isinstance(raw, str) else json.dumps(raw))
        new_blob = {}
        for k, v in blob.items():
            if k in protected:
                new_blob[k] = v      # a generated column reads this
                continue
            if k not in _BLOB_EXCLUDE:
                new_blob[k] = v
                continue
            if k in columns:
                col = r.get(k)
                # Blob holds something the column lacks -> that is data. Keep it.
                if norm(col) == "" and norm(v) != "":
                    new_blob[k] = v
                    kept_conflicts.append((r.get("name"), k, norm(v)[:40]))
                    continue
            stripped_keys[k] = stripped_keys.get(k, 0) + 1

        if new_blob != blob:
            changed += 1
            payload = json.dumps(new_blob, ensure_ascii=False, default=str)
            bytes_after += len(payload)
            if apply:
                raw_execute("UPDATE npcs SET data_json=%s WHERE id=%s",
                            (payload, r["id"]))
        else:
            bytes_after += len(raw if isinstance(raw, str) else json.dumps(raw))

    print(f"rows scanned : {len(rows)}")
    print(f"rows changed : {changed}")
    print(f"blob bytes   : {bytes_before:,} -> {bytes_after:,} "
          f"({100 * (bytes_before - bytes_after) / max(1, bytes_before):.0f}% smaller)")
    print("\nkeys stripped (all are real columns on the same row):")
    for k, n in sorted(stripped_keys.items(), key=lambda x: -x[1]):
        print(f"  {k:20s} {n:5d}")
    if kept_conflicts:
        print(f"\nKEPT ({len(kept_conflicts)}) -- blob had a value the column did not:")
        for name, k, v in kept_conflicts[:15]:
            print(f"  {name}: {k} = {v!r}")
    if not apply:
        print("\nDRY RUN -- pass --apply")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    main(ap.parse_args().apply)
