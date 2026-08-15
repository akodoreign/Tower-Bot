"""Move global_state['generated_ads'] into the generated_ads tables.

Idempotent: skips when the table already holds at least as many ads as the blob.
Archives the payload under generated_ads_archived_json and empties the live key,
the same convention the council rulings migration used.
"""

import argparse
import json
import sys

sys.path.insert(0, r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot')
from dotenv import load_dotenv
load_dotenv(r'c:\Users\akodoreign\Desktop\chatGPT-discord-bot\.env')

from src.db_api import get_global_state, set_global_state  # noqa: E402
from src import ad_registry as ar  # noqa: E402

ARCHIVE_KEY = "generated_ads_archived_json"


def main(apply: bool) -> None:
    ar.ensure_schema()
    blob = get_global_state("generated_ads") or []
    if isinstance(blob, str):
        blob = json.loads(blob)
    ads = [a for a in blob if isinstance(a, dict) and a.get("ad_text")]
    existing = ar.ad_count()

    print(f"blob ads : {len(ads)}")
    print(f"in table : {existing}")

    if existing >= len(ads) and existing > 0:
        print("already migrated -- skipping insert")
    else:
        n = 0
        for ad in ads:
            if apply and ar.add_ad(ad):
                n += 1
            elif not apply:
                n += 1
        print(f"{'migrated' if apply else 'would migrate'}: {n}")

    if apply:
        rows = ar.ad_count()
        if rows == 0:
            print("!! refusing to archive with an empty table")
            return
        payload = blob if isinstance(blob, str) else json.dumps(blob, ensure_ascii=False)
        set_global_state(ARCHIVE_KEY, payload)
        set_global_state("generated_ads", "[]")
        print(f"\narchived {len(payload)} bytes -> global_state['{ARCHIVE_KEY}']; live key emptied")

        print(f"ads in table: {rows}")
        shop = ar.pick_ad(ad_types=("shop", "tourism"))
        print("sample pick (shop/tourism):",
              (shop or {}).get("shop_name"), "|", (shop or {}).get("district"),
              "| tags:", (shop or {}).get("dnd_tags"))
    else:
        print("\nDRY RUN -- pass --apply")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    main(ap.parse_args().apply)
