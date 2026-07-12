"""Backfill usable tactical maps for generated module directories.

This deliberately uses the deterministic VTT renderer instead of A1111. The
goal is to give the module browser playable map thumbnails and seed future
reference/reuse with clear tactical maps, not decorative scene art.
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

from src.mission_builder.boxset_utils import write_maps_page
from src.mission_builder.vtt_renderer import render_vtt_battlemap, write_grid_sidecar


MODULES_DIR = ROOT / "generated_modules"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _strip_tags(text: str) -> str:
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", " ", text)


def _title_from(module_dir: Path, text: str) -> str:
    match = re.search(r"<title>([^<]+)</title>", text, re.IGNORECASE)
    if match:
        title = _clean_text(match.group(1))
        title = re.sub(r"\s+[—-]\s+(?:Index|Maps|Module).*$", "", title, flags=re.IGNORECASE)
        if title:
            return title
    return module_dir.name.replace("_", " ")


def _faction_from(text: str) -> str:
    plain = _strip_tags(text)
    match = re.search(r"Faction:\s*([A-Za-z0-9 '&.-]{2,80})", plain, re.IGNORECASE)
    if match:
        return _clean_text(match.group(1))
    return "Independent"


def _mission_kind(module_dir: Path, text: str) -> str:
    haystack = f"{module_dir.name} {_strip_tags(text)}".lower()
    kinds = [
        "infestation",
        "defense",
        "battle",
        "assault",
        "ambush",
        "heist",
        "infiltration",
        "sabotage",
        "rescue",
        "escort",
        "exploration",
        "investigation",
        "negotiation",
        "recovery",
        "gather",
        "discovery",
        "first contact",
        "puzzle",
    ]
    for kind in kinds:
        if kind in haystack:
            return kind
    return "module"


def _context_for(module_dir: Path) -> dict:
    index_text = _read_text(module_dir / "index.html")
    module_text = _read_text(module_dir / "module.html")
    text = "\n".join(t for t in (index_text, module_text) if t) or module_dir.name
    title = _title_from(module_dir, text)
    faction = _faction_from(text)
    kind = _mission_kind(module_dir, text)
    plain = _clean_text(_strip_tags(module_text or text))
    description = plain[:900]
    return {
        "title": title,
        "faction": faction,
        "kind": kind,
        "location": title,
        "description": description,
        "prompt": f"{title} {kind} tactical VTT map for {faction}",
    }


def _target_modules(limit: int) -> list[Path]:
    if not MODULES_DIR.exists():
        return []
    dirs = [
        d
        for d in MODULES_DIR.iterdir()
        if d.is_dir()
        and not d.name.startswith("_")
        and ((d / "index.html").exists() or (d / "module.html").exists())
    ]
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[:limit]


def _write_map(module_dir: Path, *, force: bool) -> Path | None:
    maps_dir = module_dir / "maps"
    maps_dir.mkdir(exist_ok=True)
    out_path = maps_dir / "backfill_tactical_map.png"
    if out_path.exists() and not force:
        return None
    context = _context_for(module_dir)
    png = render_vtt_battlemap(context=context)
    out_path.write_bytes(png)
    write_grid_sidecar(out_path, context)
    write_maps_page(module_dir, context["title"], context["faction"], [out_path])
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50, help="Most-recent module directories to backfill.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing backfill_tactical_map.png files.")
    args = parser.parse_args()

    written = 0
    skipped = 0
    for module_dir in _target_modules(args.limit):
        path = _write_map(module_dir, force=args.force)
        if path:
            written += 1
            print(f"WROTE {module_dir.name}\\maps\\{path.name}")
        else:
            skipped += 1
            print(f"SKIP  {module_dir.name}")

    print(f"done: wrote={written} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
