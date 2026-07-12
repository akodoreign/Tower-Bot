"""
Smoke test + quality scorer for the infestation pipeline.
Runs one mission and scores the HTML output on a 0-10 scale.

Usage:
  python scripts/_smoke_infestation.py
  python scripts/_smoke_infestation.py --subtype sewer
  python scripts/_smoke_infestation.py --subtype dungeon --tier high-stakes
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

os.environ.setdefault("MODULE_GENERATE_MAPS", "true")

TEST_MISSION = {
    "id":               9999,
    "title":            "The Iron Scar Contract",
    "body":             (
        "Iron Fang Consortium enforcer Vex Kraugh has been embezzling artifact revenue. "
        "Senior blade Mira Osei hired the party to recover ledgers proving his guilt from "
        "Kraugh's safehouse in the Scrapworks, without alerting him."
    ),
    "faction":          "Iron Fang Consortium",
    "tier":             "high-stakes",
    "difficulty":       6,
    "primary_location": "Scrapworks sewer sub-level",
    "mission_type":     "infestation",
}


def score_module(html: str, out_dir: Path, has_map: bool) -> dict:
    """
    Score the rendered module HTML on 10 criteria (0 or 1 each).
    Returns {"score": int, "details": list[str]}.
    """
    checks = []

    def check(label: str, passed: bool) -> None:
        checks.append((label, passed))

    # 1. Overview map present
    check("Overview map image in HTML",
          'overview_labeled.png' in html or 'overview_raw' in html)

    # 2. Area legend rendered (table with A, B, C…)
    check("Area legend table present",
          bool(re.search(r'Area Legend', html, re.I)) and
          bool(re.search(r'<td[^>]*>[A-Z]</td>', html)))

    # 3. Room cards use letter labels (Area A, Area B…)
    check("Room cards use letter labels (Area A/B/C…)",
          len(re.findall(r'Area [A-Z]', html)) >= 3)

    # 4. Read-aloud text in every room card
    read_alouds = re.findall(r'read-aloud[^>]*>(.{30,}?)<', html, re.DOTALL)
    check("Read-aloud text present in rooms (≥3 rooms)",
          len(read_alouds) >= 3)

    # 5. Monster block present in rooms
    check("Monster blocks present (≥3 rooms)",
          html.count('inf-monster-block') >= 3)

    # 6. Boss room marked
    check("Boss room badge present",
          'inf-badge-boss' in html)

    # 7. Entry room marked
    check("Entry room badge present",
          'inf-badge-entry' in html)

    # 8. ASCII map in collapsed details element
    check("ASCII map in <details> (collapsible)",
          bool(re.search(r'<details[^>]*>.*?inf-ascii', html, re.DOTALL)))

    # 9. Hazard or features section in at least one room
    check("Hazard/features section in at least one room",
          'Hazard' in html or 'Room Features' in html)

    # 10. Treasure in at least one room
    check("Treasure present in at least one room",
          'Treasure' in html)

    passed = sum(1 for _, p in checks if p)
    details = [f"{'✅' if p else '❌'} {label}" for label, p in checks]
    return {"score": passed, "max": 10, "details": details}


async def run_test(subtype_override: str = "", tier: str = "") -> None:
    from src.mission_builder.infestation_pipeline import build_infestation_module

    mission = dict(TEST_MISSION)
    if tier:
        mission["tier"] = tier
    if subtype_override:
        mission["primary_location"] = subtype_override

    print(f"\n{'='*60}")
    print(f"  SMOKE TEST — infestation pipeline")
    print(f"  Mission: {mission['title']}")
    print(f"  Tier: {mission['tier']}  |  Difficulty: {mission['difficulty']}")
    print(f"{'='*60}\n")

    index_path = await build_infestation_module(mission)
    if not index_path or not index_path.exists():
        print("FAIL: build_infestation_module returned no path")
        return

    out_dir = index_path.parent
    module_html_path = out_dir / "module.html"
    if not module_html_path.exists():
        print("FAIL: module.html not found")
        return

    html = module_html_path.read_text(encoding="utf-8", errors="replace")
    has_map = (out_dir / "maps" / "overview_labeled.png").exists()

    result = score_module(html, out_dir, has_map)

    print(f"\n{'='*60}")
    print(f"  QUALITY SCORE: {result['score']}/{result['max']}")
    print(f"  Output: {out_dir}")
    print(f"  Map file: {'YES' if has_map else 'NO'}")
    print(f"{'='*60}")
    for line in result["details"]:
        print(f"  {line}")
    print()

    # Print sample room card text for manual inspection
    cards = re.findall(r'<div class="inf-room">(.*?)</div>\s*\)', html, re.DOTALL)
    if not cards:
        cards = re.findall(r'class="inf-room">(.*?)</div>\s*</div>', html, re.DOTALL)
    if cards:
        sample = re.sub(r'<[^>]+>', ' ', cards[0])
        sample = re.sub(r'\s+', ' ', sample).strip()[:400]
        print(f"  Sample room card text:\n  {sample}\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--subtype", default="", help="Force subtype via location override (sewer/basement/lair/dungeon)")
    p.add_argument("--tier",    default="", help="Override mission tier")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_test(args.subtype, args.tier))
