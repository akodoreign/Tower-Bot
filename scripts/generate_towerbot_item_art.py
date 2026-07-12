"""Generate fallback TowerBot item art for web shop cards with no Mimir image."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from src.towerbot_item_art import generate_item_art_batch, missing_art_keys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=None, help="Number of generic item images to generate.")
    parser.add_argument("--dry-run", action="store_true", help="List missing generic art keys without calling A1111.")
    args = parser.parse_args()

    if args.dry_run:
        for row in missing_art_keys(args.batch or 10):
            print(f"{row['key']}: example={row['example']}")
        return 0

    made = asyncio.run(generate_item_art_batch(args.batch))
    print(f"generated={made}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
