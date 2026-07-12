"""
Small rendering utilities for specialized mission box sets.

This module intentionally does not decide mission content. Each pipeline owns
its own DM guide / players guide / chart pack text. These helpers only write
those pipeline-specific artifacts with the common HTML shell.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from src.mission_builder.html_renderer import render_component, _page
from src.mission_builder.vtt_renderer import PRETTY_TIMEOUT, stylize_pretty_battlemap

logger = logging.getLogger(__name__)


def write_component(out_dir: Path, slug: str, label: str, title: str, faction: str, body_md: str) -> str:
    path = out_dir / f"{slug}.html"
    path.write_text(render_component(label, title, body_md, faction), encoding="utf-8")
    return path.name


def write_maps_page(out_dir: Path, title: str, faction: str, image_paths: Iterable[Path]) -> str | None:
    paths = [p for p in image_paths if p and p.exists()]
    if not paths:
        return None
    figures = []
    tactical_paths = [p for p in paths if not p.stem.endswith("_pretty")]
    for p in tactical_paths:
        pretty = p.with_name(f"{p.stem}_pretty{p.suffix}")
        nice = p.with_name(f"{p.stem}_nice{p.suffix}")
        # Pretty map generation is NOT done here — it runs earlier in the map pipeline
        # and would block the async event loop for the full PRETTY_TIMEOUT if attempted
        # synchronously. Display whatever exists; missing pretty maps show a placeholder.
        preview = pretty if pretty.exists() else nice
        pretty_rel = preview.relative_to(out_dir).as_posix() if preview.exists() and preview.is_relative_to(out_dir) else ""
        rel = p.relative_to(out_dir).as_posix() if p.is_relative_to(out_dir) else p.name
        caption = p.stem.replace("_", " ").title()
        pretty_img = (
            f'<img src="{pretty_rel}" alt="{caption} Pretty" '
            'style="max-width:100%;border-radius:8px;border:1px solid rgba(0,0,0,.15);'
            'box-shadow:0 2px 12px rgba(0,0,0,.12);">'
            if pretty_rel else
            '<div style="min-height:180px;display:flex;align-items:center;justify-content:center;'
            'border:1px dashed rgba(0,0,0,.22);border-radius:8px;color:#777;font-style:italic;">'
            'Pretty preview not generated yet</div>'
        )
        figures.append(
            '<figure style="margin:0 0 2rem;">'
            '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;align-items:start;">'
            '<div>'
            '<div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#777;margin-bottom:6px;">VTT Tactical</div>'
            f'<img src="{rel}" alt="{caption} Tactical" '
            'style="max-width:100%;border-radius:8px;border:1px solid rgba(0,0,0,.15);box-shadow:0 2px 12px rgba(0,0,0,.12);">'
            '</div>'
            '<div>'
            '<div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#777;margin-bottom:6px;">Pretty Preview</div>'
            f'{pretty_img}'
            '</div>'
            '</div>'
            f'<figcaption style="font-size:12px;color:#888;margin-top:8px;font-style:italic;">{caption}</figcaption>'
            '</figure>'
        )
    body = (
        '<div class="chapter-header">'
        f'<div class="ch-label">{title}</div>'
        '<h2>Maps</h2>'
        '</div>'
        + "\n".join(figures)
    )
    path = out_dir / "maps.html"
    path.write_text(_page(f"Maps - {title}", body, faction), encoding="utf-8")
    return path.name


def component_links(has_maps: bool = False) -> list[tuple[str, str]]:
    links = [
        ("dm_guide", "dm_guide.html"),
        ("module", "module.html"),
        ("players_guide", "players_guide.html"),
        ("chart_pack", "chart_pack.html"),
    ]
    if has_maps:
        links.append(("maps", "maps.html"))
    links.append(("session", "session.html"))
    return links
