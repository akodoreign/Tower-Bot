"""Backfill one tactical map per room for infestation modules.

Infestation modules are room crawls. A single module-level map is not enough,
so this script parses generated infestation HTML, writes a VTT-safe tactical
map for every room, optionally asks A1111 for a pretty preview, and injects the
tactical map into each room card.

No VAE overrides are used.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backfill_module_tactical_maps import _clean_text, _faction_from, _read_text, _strip_tags, _title_from
from src.mission_builder.boxset_utils import write_maps_page
from src.mission_builder.vtt_renderer import render_vtt_battlemap, stylize_pretty_battlemap, write_grid_sidecar


MODULES_DIR = ROOT / "generated_modules"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", html.unescape(text).lower()).strip("_")[:48] or "room"


def _is_infestation_dir(module_dir: Path) -> bool:
    text = f"{module_dir.name}\n{_read_text(module_dir / 'module.html')[:20000]}".lower()
    return "infestation" in text or "inf-room" in text


def _target_modules(limit: int, slug: str = "") -> list[Path]:
    if slug:
        d = MODULES_DIR / slug
        return [d] if d.exists() and _is_infestation_dir(d) else []
    dirs = [
        d
        for d in MODULES_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_") and (d / "module.html").exists() and _is_infestation_dir(d)
    ]
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[:limit]


def _room_blocks(module_html: str) -> list[dict]:
    rooms: list[dict] = []
    pattern = re.compile(
        r'(<div class="inf-room" id="room-(\d+)">.*?)(?=<div class="inf-room" id="room-\d+">|</div>\s*</body>)',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(module_html):
        block = match.group(1)
        room_id = int(match.group(2))
        name_match = re.search(r'<span class="inf-room-name">([^<]+)</span>', block, re.IGNORECASE)
        density_match = re.search(r'<div class="inf-density-bar inf-den-([a-z]+)">', block, re.IGNORECASE)
        read_match = re.search(
            r'<div class="inf-section-label">Read Aloud</div>\s*<div[^>]*>\s*(.*?)\s*</div>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        rooms.append(
            {
                "id": room_id,
                "name": _clean_text(name_match.group(1) if name_match else f"Room {room_id}"),
                "density": _clean_text(density_match.group(1) if density_match else "normal"),
                "read_aloud": _clean_text(_strip_tags(read_match.group(1))) if read_match else "",
                "block": block,
            }
        )
    return rooms


def _room_context(module_dir: Path, room: dict, module_html: str) -> dict:
    title = _title_from(module_dir, module_html).replace("Infestation - ", "").replace("Infestation — ", "")
    faction = _faction_from(module_html)
    return {
        "title": f"R{room['id']:02d} {room['name']}",
        "module_title": title,
        "faction": faction,
        "kind": f"infestation dungeon room {room['density']}",
        "location": room["name"],
        "description": room["read_aloud"],
        "prompt": (
            f"top-down VTT battlemap for infestation room R{room['id']:02d}: {room['name']}. "
            f"Density: {room['density']}. {room['read_aloud']}"
        ),
    }


def _inject_room_images(module_html: str, room_to_path: dict[int, str]) -> str:
    def repl(match: re.Match) -> str:
        room_id = int(match.group(1))
        block = match.group(0)
        rel = room_to_path.get(room_id)
        if not rel:
            return block
        img = (
            f'  <img class="inf-room-map" src="{rel}" '
            f'alt="Room map R{room_id:02d}" loading="lazy">\n'
        )
        if 'class="inf-room-map"' in block:
            return re.sub(r'\s*<img class="inf-room-map"[^>]+>\s*', "\n" + img, block, count=1)
        return re.sub(
            r'(<div class="inf-density-bar [^"]+"></div>\s*)',
            r"\1" + img,
            block,
            count=1,
        )

    return re.sub(
        r'<div class="inf-room" id="room-(\d+)">.*?(?=<div class="inf-room" id="room-\d+">|</div>\s*</body>)',
        repl,
        module_html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _nice_preview(tactical_path: Path, context: dict, *, force: bool) -> Path | None:
    """Backward-compatible wrapper for the shared pretty-map finalizer."""
    try:
        return stylize_pretty_battlemap(tactical_path, context=context, force=force)
    except Exception as exc:
        print(f"PRETTY_FAIL {tactical_path.name}: {exc}")
        return None


def backfill_module(module_dir: Path, *, nice: bool, force: bool, max_rooms: int, start_room: int) -> tuple[int, int]:
    module_path = module_dir / "module.html"
    module_html = _read_text(module_path)
    rooms = _room_blocks(module_html)
    rooms.sort(key=lambda room: room["id"])
    if start_room > 1:
        rooms = [r for r in rooms if r["id"] >= start_room]
    if max_rooms > 0:
        rooms = rooms[:max_rooms]
    maps_dir = module_dir / "maps"
    maps_dir.mkdir(exist_ok=True)
    rel_by_room: dict[int, str] = {}
    written = 0
    nice_written = 0

    for room in rooms:
        filename = f"R{room['id']:02d}_{_slug(room['name'])}_tactical.png"
        path = maps_dir / filename
        context = _room_context(module_dir, room, module_html)
        if force or not path.exists():
            path.write_bytes(render_vtt_battlemap(context=context))
            write_grid_sidecar(path, context)
            written += 1
        rel_by_room[room["id"]] = f"maps/{filename}"
        if nice:
            result = _nice_preview(path, context=context, force=force)
            if result and result.exists():
                nice_written += 1

    if rel_by_room:
        module_path.write_text(_inject_room_images(module_html, rel_by_room), encoding="utf-8")
        write_maps_page(module_dir, _title_from(module_dir, module_html), _faction_from(module_html), [maps_dir / p.split("/", 1)[1] for p in rel_by_room.values()])
    return written, nice_written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--slug", default="")
    parser.add_argument("--nice", action="store_true", help="Compatibility alias for --pretty.")
    parser.add_argument("--pretty", action="store_true", help="Also run the shared A1111 pretty-preview pass.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-rooms", type=int, default=0, help="Debug throttle; 0 means every room.")
    parser.add_argument("--start-room", type=int, default=1, help="First room number to process.")
    args = parser.parse_args()

    total_maps = 0
    total_nice = 0
    for module_dir in _target_modules(args.limit, args.slug):
        maps, nice = backfill_module(module_dir, nice=args.nice or args.pretty, force=args.force, max_rooms=args.max_rooms, start_room=args.start_room)
        total_maps += maps
        total_nice += nice
        print(f"{module_dir.name}: tactical={maps} nice={nice}")
    print(f"done: tactical={total_maps} nice={total_nice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
