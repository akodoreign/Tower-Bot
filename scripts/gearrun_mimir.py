"""Run Mimir gear population without the Discord bot.

Usage:
    python scripts/gearrun_mimir.py
    python scripts/gearrun_mimir.py --force
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.mimir_client import get_mimir
from src.mimir_sync import (
    ensure_sync_table,
    get_sync_engine,
    run_epic_npc_gear_run,
    run_npc_gear_run,
    run_pc_gear_run,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Populate Mimir character gear from MySQL.")
    parser.add_argument("--force", action="store_true", help="Regenerate gear even when inventory exists.")
    parser.add_argument("--epic", action="store_true", help="Apply Mimir-backed epic gear to NPCs over level 12.")
    parser.add_argument("--min-level", type=int, default=13, help="Minimum NPC level for --epic.")
    parser.add_argument("--npc", default="", help="Optional single NPC name for --epic.")
    args = parser.parse_args()

    mimir = get_mimir()
    connected = await mimir.connect()
    if not connected:
        print("Mimir MCP unavailable. Gear will be inferred in MySQL but not synced to Mimir.")

    ensure_sync_table()
    engine = get_sync_engine()

    if args.epic:
        npc_stats = await run_epic_npc_gear_run(min_level=args.min_level, force=args.force, npc_name=args.npc)
        pc_stats = {"total": 0, "done": 0, "skipped": 0, "failed": 0}
    else:
        npc_stats = await run_npc_gear_run(force=args.force)
        pc_stats = await run_pc_gear_run(force=args.force)

    npc_synced = await engine.sync_all_npcs() if connected else 0
    pc_synced = await engine.sync_party() if connected else 0

    if connected:
        await mimir.disconnect()

    print("NPC gear:", npc_stats, "synced:", npc_synced)
    print("PC gear:", pc_stats, "synced:", pc_synced)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
