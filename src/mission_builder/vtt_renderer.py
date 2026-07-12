"""
VTT battlemap renderer/finalizer.

The image models are useful for mood, but they are not a reliable contract for
playable maps. This module makes that contract explicit: module maps are
orthographic, square, grid-aligned, and carry a tiny sidecar describing the
5-foot grid. The default is 32x32 squares so fast characters still have room
to matter.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageStat

MAP_SIZE = int(os.getenv("VTT_MAP_SIZE", "2048"))
GRID_CELLS = int(os.getenv("VTT_MAP_GRID_CELLS", "32"))
GRID_SIZE_PX = MAP_SIZE // GRID_CELLS
STRICT_VTT = os.getenv("VTT_MAP_STRICT", "true").lower() not in {"0", "false", "no", "off"}
ALLOW_AI_TEXTURE = os.getenv("VTT_MAP_ALLOW_AI_TEXTURE", "false").lower() in {"1", "true", "yes", "on"}
PRETTY_MAPS = os.getenv("VTT_MAP_PRETTY", "true").lower() in {"1", "true", "yes", "on"}
PRETTY_SIZE = int(os.getenv("VTT_MAP_PRETTY_SIZE", "1024"))
PRETTY_DENOISE = float(os.getenv("VTT_MAP_PRETTY_DENOISE", "0.32"))
PRETTY_TIMEOUT = float(os.getenv("VTT_MAP_PRETTY_TIMEOUT", "600"))
PRETTY_MAPCRAFT_TEXT2IMG = os.getenv("VTT_MAP_PRETTY_MAPCRAFT_TEXT2IMG", "false").lower() in {"1", "true", "yes", "on"}
PRETTY_INCLUDE_FLUX = os.getenv("VTT_MAP_PRETTY_INCLUDE_FLUX", "false").lower() in {"1", "true", "yes", "on"}
A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860").split()[0]
A1111_IDLE_TIMEOUT = float(os.getenv("A1111_MAP_IDLE_TIMEOUT", "180"))
A1111_POLL_SECONDS = float(os.getenv("A1111_MAP_POLL_SECONDS", "3"))
A1111_COOLDOWN_SECONDS = float(os.getenv("A1111_MAP_COOLDOWN_SECONDS", "20"))
A1111_MODEL_SWAP_COOLDOWN = float(os.getenv("A1111_MAP_MODEL_SWAP_COOLDOWN", "180"))
MAPCRAFT_ENABLED = os.getenv("A1111_MAPCRAFT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
MAPCRAFT_TRIGGER = os.getenv("A1111_MAPCRAFT_TRIGGER", "mapcraft.").strip()
MAPCRAFT_FLUX_LORA = os.getenv("A1111_MAPCRAFT_FLUX_LORA", "mapcraft_flux_v2").strip()
MAPCRAFT_SDXL_LORA = os.getenv("A1111_MAPCRAFT_SDXL_LORA", "mapcraft_sdxl_v1").strip()
MAPCRAFT_FLUX_CHECKPOINT = os.getenv("A1111_MAPCRAFT_FLUX_CHECKPOINT", os.getenv("A1111_FLUX_CHECKPOINT", "flux1-dev-fp8.safetensors")).strip()
MAPCRAFT_SDXL_CHECKPOINT = os.getenv("A1111_MAPCRAFT_SDXL_CHECKPOINT", os.getenv("A1111_MAP_CHECKPOINT", "")).strip()

logger = logging.getLogger(__name__)
_PRETTY_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pretty-map")


def wait_for_a1111_idle(timeout: float | None = None, cooldown: float | None = None) -> bool:
    """
    Wait for A1111 to finish the previous image job before requesting another.

    A1111 often reports the HTTP request complete before the model/checkpoint
    memory is ready for a reliable next run, so this combines progress polling
    with a small cooldown.
    """
    import time

    timeout = A1111_IDLE_TIMEOUT if timeout is None else timeout
    cooldown = A1111_COOLDOWN_SECONDS if cooldown is None else cooldown
    deadline = time.monotonic() + timeout
    saw_busy = False
    consecutive_errors = 0

    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{A1111_URL}/sdapi/v1/progress?skip_current_image=true")
                resp.raise_for_status()
                data = resp.json()
            consecutive_errors = 0
            progress = float(data.get("progress") or 0.0)
            state = data.get("state") or {}
            job_count = int(state.get("job_count") or 0)
            job_no = int(state.get("job_no") or 0)
            sampling_step = int(state.get("sampling_step") or 0)
            sampling_steps = int(state.get("sampling_steps") or 0)
            busy = progress > 0.0 or (job_count and job_no < job_count) or (sampling_steps and sampling_step < sampling_steps)
            if not busy:
                if saw_busy and cooldown > 0:
                    time.sleep(cooldown)
                return True
            saw_busy = True
        except Exception as exc:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                logger.warning("wait_for_a1111_idle: giving up after %d consecutive errors: %s", consecutive_errors, exc)
                return False
            logger.debug("wait_for_a1111_idle: transient error (%d/3), retrying: %s", consecutive_errors, exc)
        time.sleep(A1111_POLL_SECONDS)

    return False


def _seed(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    return int(digest[:16], 16)


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _detect_kind(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("sewer", "drain", "pipe", "water channel")):
        return "sewer"
    if any(w in t for w in ("cave", "cavern", "natural", "fungal", "lair", "nest", "egg chamber")):
        return "cave"
    if any(w in t for w in ("heist", "vault", "treasury", "infiltration", "sabotage", "facility", "factory", "office", "interior", "rescue", "cell", "hostage")):
        return "interior"
    if any(w in t for w in ("fort", "gate", "checkpoint", "wall", "outpost", "bastion", "defense", "assault")):
        return "fort"
    if any(w in t for w in ("market", "bazaar", "stall", "street", "alley", "plaza", "escort", "ambush")):
        return "street"
    return "dungeon"


def _current_a1111_checkpoint() -> str:
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{A1111_URL}/sdapi/v1/options")
            resp.raise_for_status()
            return _norm(resp.json().get("sd_model_checkpoint"))
    except Exception:
        return ""


def _is_flux_checkpoint(name: str) -> bool:
    return "flux" in (name or "").lower()


def _mapcraft_kind_phrase(kind: str) -> str:
    if kind in {"dungeon", "cave", "sewer"}:
        return "an underground dungeon or sewer battlemap with connected rooms, corridors, walls, water channels, cover, hazards, and clear exits"
    if kind == "interior":
        return "a fantasy building floor plan with rooms, corridors, doors, furnishings, cover, stairs, and clear entrances"
    if kind == "fort":
        return "a fortified compound battlemap with walls, gates, guard posts, courtyards, barricades, cover, and breach points"
    return "an exterior urban fantasy battlemap with streets, alleys, plazas, buildings, terrain cover, chokepoints, and encounter zones"


def _palette(kind: str) -> dict[str, tuple[int, int, int]]:
    palettes = {
        "sewer": {
            "floor": (72, 70, 58), "wall": (44, 47, 42), "line": (112, 116, 96),
            "water": (40, 82, 82), "cover": (94, 79, 55), "hazard": (91, 118, 65),
        },
        "cave": {
            "floor": (76, 64, 53), "wall": (42, 35, 31), "line": (112, 98, 82),
            "water": (42, 72, 85), "cover": (95, 86, 69), "hazard": (93, 66, 54),
        },
        "fort": {
            "floor": (91, 88, 76), "wall": (50, 50, 47), "line": (130, 126, 108),
            "water": (49, 72, 84), "cover": (88, 70, 49), "hazard": (115, 84, 55),
        },
        "street": {
            "floor": (93, 83, 64), "wall": (55, 48, 42), "line": (133, 119, 91),
            "water": (43, 72, 88), "cover": (112, 83, 45), "hazard": (96, 76, 58),
        },
        "interior": {
            "floor": (83, 78, 66), "wall": (39, 39, 37), "line": (124, 116, 96),
            "water": (43, 67, 81), "cover": (76, 65, 52), "hazard": (98, 74, 49),
        },
        "dungeon": {
            "floor": (75, 70, 61), "wall": (39, 38, 36), "line": (112, 106, 91),
            "water": (40, 67, 83), "cover": (80, 64, 47), "hazard": (97, 64, 49),
        },
    }
    return palettes.get(kind, palettes["dungeon"])


def _rect(cell_x: int, cell_y: int, w: int, h: int) -> tuple[int, int, int, int]:
    return (
        cell_x * GRID_SIZE_PX,
        cell_y * GRID_SIZE_PX,
        (cell_x + w) * GRID_SIZE_PX,
        (cell_y + h) * GRID_SIZE_PX,
    )


def _jitter_poly(rng: random.Random, cells: list[tuple[int, int]], jitter: int = 10) -> list[tuple[int, int]]:
    return [
        (x * GRID_SIZE_PX + rng.randint(-jitter, jitter), y * GRID_SIZE_PX + rng.randint(-jitter, jitter))
        for x, y in cells
    ]


def _draw_texture(draw: ImageDraw.ImageDraw, rng: random.Random, pal: dict[str, tuple[int, int, int]]) -> None:
    for _ in range(1800):
        x = rng.randrange(MAP_SIZE)
        y = rng.randrange(MAP_SIZE)
        r = rng.choice((1, 1, 2, 3))
        base = pal["line"] if rng.random() < 0.65 else pal["wall"]
        alpha = rng.randrange(22, 58)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*base, alpha))


def _draw_grid(draw: ImageDraw.ImageDraw) -> None:
    for i in range(GRID_CELLS + 1):
        p = i * GRID_SIZE_PX
        width = 2 if i in (0, GRID_CELLS) else 1
        color = (235, 226, 190, 82 if i not in (0, GRID_CELLS) else 145)
        draw.line((p, 0, p, MAP_SIZE), fill=color, width=width)
        draw.line((0, p, MAP_SIZE, p), fill=color, width=width)


def _draw_dungeon(draw: ImageDraw.ImageDraw, rng: random.Random, pal: dict[str, tuple[int, int, int]], kind: str, text: str) -> None:
    wall = (*pal["wall"], 255)
    floor = (*pal["floor"], 255)
    cover = (*pal["cover"], 255)
    water = (*pal["water"], 235)
    hazard = (*pal["hazard"], 220)

    c = GRID_CELLS
    half = c // 2
    q = c // 4

    # Heavy outside walls, then several connected rooms.
    draw.rectangle(_rect(0, 0, c, c), fill=wall)
    rooms = [
        (2, 2, q + 4, q + 1),
        (half + 1, 2, q + 5, q),
        (3, half - 1, q + 2, q + 6),
        (half + 1, half - 2, q + 5, q + 8),
        (q + 2, q + 2, q + 4, q + 2),
    ]
    for x, y, w, h in rooms:
        draw.rectangle(_rect(x, y, w, h), fill=floor, outline=(*pal["line"], 255), width=3)
    corridors = [(q + 4, 4, q - 1, 1), (q - 1, q + 1, 2, q), (half - 1, half, 3, 1), (half + 4, q + 1, 1, q)]
    for x, y, w, h in corridors:
        draw.rectangle(_rect(x, y, w, h), fill=floor)

    if kind == "sewer":
        draw.rectangle(_rect(half - 2, 0, 4, c), fill=water)
        draw.rectangle(_rect(half - 2, 0, 4, c), outline=(155, 170, 145, 130), width=2)
    elif kind == "cave":
        pts = _jitter_poly(rng, [(3, 3), (c - 4, 2), (c - 2, q + 2), (c - 5, c - 3), (q, c - 2), (2, half + 4)], 20)
        draw.polygon(pts, fill=floor, outline=(*pal["line"], 255))
        for _ in range(32):
            x, y = rng.randrange(3, c - 3), rng.randrange(3, c - 3)
            draw.ellipse(_rect(x, y, 1, 1), fill=cover)

    # Pillars, cover, hazards.
    for x, y in [(4, 4), (half + 5, 4), (5, half + 7), (half + 6, half + 6), (c - 5, c - 6)]:
        draw.rectangle(_rect(x, y, 1, 1), fill=cover, outline=(*pal["line"], 255), width=2)
    draw.ellipse(_rect(half - 1, half - 1, 3, 3), fill=hazard, outline=(170, 125, 80, 180), width=2)
    draw.rectangle(_rect(c - 7, half - 1, 3, 1), fill=cover)
    if any(w in text for w in ("nest", "egg", "infestation", "breeding")):
        for x, y in [(half + 2, half), (half + 3, half + 2), (half + 6, half + 2), (half + 3, half + 6), (c - 6, c - 7), (q, half)]:
            draw.ellipse(_rect(x, y, 1, 1), fill=(145, 142, 103, 230), outline=(95, 108, 70, 220), width=2)
        draw.arc(_rect(half, half - 1, 8, 8), 20, 315, fill=(95, 108, 70, 190), width=4)


def _draw_interior(draw: ImageDraw.ImageDraw, rng: random.Random, pal: dict[str, tuple[int, int, int]], text: str) -> None:
    wall = (*pal["wall"], 255)
    floor = (*pal["floor"], 255)
    cover = (*pal["cover"], 255)
    c = GRID_CELLS
    half = c // 2
    q = c // 4
    draw.rectangle(_rect(2, 2, c - 4, c - 4), fill=wall)
    rooms = [
        (3, 3, q + 3, q + 2),
        (half, 3, q + 8, q + 2),
        (3, half, q + 5, q + 7),
        (half + 1, half, q + 6, q + 7),
        (q + 5, q + 5, q + 4, q),
    ]
    for x, y, w, h in rooms:
        draw.rectangle(_rect(x, y, w, h), fill=floor, outline=(*pal["line"], 255), width=3)
    for x, y, w, h in [(q + 6, 5, 2, 4), (q + 4, q + 5, q + 8, 2), (half - 1, half + 1, 2, q + 3)]:
        draw.rectangle(_rect(x, y, w, h), fill=floor)
    for x, y, w, h in [(4, 4, 3, 1), (half + 3, 4, 5, 1), (4, half + 5, 3, 1), (half + 4, half + 3, 3, 3), (c - 7, c - 7, 2, 2)]:
        draw.rectangle(_rect(x, y, w, h), fill=cover, outline=(40, 35, 30, 180), width=1)
    if any(w in text for w in ("vault", "heist", "treasury", "relic")):
        draw.rectangle(_rect(half + 5, half + 2, 6, 6), fill=(35, 38, 38, 255), outline=(165, 150, 100, 255), width=4)
        draw.ellipse(_rect(half + 7, half + 4, 2, 2), outline=(190, 170, 110, 255), width=3)
    if any(w in text for w in ("rescue", "cell", "prisoner", "hostage")):
        for x in range(4, 10):
            draw.line((x * GRID_SIZE_PX, half * GRID_SIZE_PX, x * GRID_SIZE_PX, (half + 6) * GRID_SIZE_PX), fill=(150, 145, 130, 255), width=3)
        draw.rectangle(_rect(3, half, 8, 6), outline=(150, 145, 130, 255), width=3)
    if any(w in text for w in ("sabotage", "machine", "factory", "engine", "pump")):
        for x, y in [(half + 2, 4), (half + 6, 5), (half + 1, half + 6), (c - 8, half + 6)]:
            draw.ellipse(_rect(x, y, 1, 1), fill=(72, 72, 68, 255), outline=(160, 130, 80, 255), width=2)
        draw.line(((half + 1) * GRID_SIZE_PX, 5 * GRID_SIZE_PX, (c - 6) * GRID_SIZE_PX, (half + 8) * GRID_SIZE_PX), fill=(160, 130, 80, 190), width=4)


def _draw_street(draw: ImageDraw.ImageDraw, rng: random.Random, pal: dict[str, tuple[int, int, int]], text: str, fort: bool = False) -> None:
    wall = (*pal["wall"], 255)
    floor = (*pal["floor"], 255)
    cover = (*pal["cover"], 255)
    hazard = (*pal["hazard"], 230)
    draw.rectangle((0, 0, MAP_SIZE, MAP_SIZE), fill=wall)
    c = GRID_CELLS
    half = c // 2
    q = c // 4
    if fort:
        draw.rectangle(_rect(4, 4, c - 8, c - 8), fill=floor, outline=(*pal["line"], 255), width=4)
        draw.rectangle(_rect(0, half - 2, q, 4), fill=floor)
        draw.rectangle(_rect(c - q, half - 2, q, 4), fill=floor)
        for x, y in [(4, 4), (c - 5, 4), (4, c - 5), (c - 5, c - 5)]:
            draw.rectangle(_rect(x, y, 2, 2), fill=cover)
        draw.rectangle(_rect(half - 4, half - 4, 8, 8), outline=hazard, width=3)
    else:
        horizontal = (half - 5, 10) if "alley" not in text else (half - 3, 6)
        vertical = (half - 5, 10) if "alley" not in text else (half - 1, 3)
        draw.rectangle(_rect(0, horizontal[0], c, horizontal[1]), fill=floor)
        draw.rectangle(_rect(vertical[0], 0, vertical[1], c), fill=floor)
        for x, y, w, h in [(2, 2, q - 1, q - 1), (c - q - 2, 2, q, q - 1), (2, c - q - 2, q, q), (c - q - 2, c - q - 2, q, q)]:
            draw.rectangle(_rect(x, y, w, h), fill=wall, outline=(*pal["line"], 255), width=2)
        stalls = [(q - 1, half - 4), (half - 4, q - 1), (half + 4, half - 4), (half - 2, half + 5), (c - 7, half + 1), (4, half + 1)]
        if any(w in text for w in ("market", "bazaar", "stall", "ledger")):
            stalls += [(q, half), (q + 2, half + 1), (half + 1, q), (half + 4, half), (half + 5, half - 1), (half - 2, q + 1), (half + 8, half + 4), (half - 7, half + 4)]
        for i, (x, y) in enumerate(stalls):
            fill = cover if i % 3 else (126, 52, 42, 255) if i % 2 else (54, 86, 111, 255)
            draw.rectangle(_rect(x, y, 1, 1), fill=fill, outline=(225, 210, 160, 170), width=1)
        if any(w in text for w in ("canal", "bridge", "water")):
            draw.rectangle(_rect(0, half + 3, c, 3), fill=(*pal["water"], 235))
            draw.rectangle(_rect(half - 3, half + 2, 6, 5), fill=floor, outline=(*pal["line"], 230), width=2)
        draw.ellipse(_rect(half - 2, half - 2, 4, 4), outline=hazard, width=4)


def render_vtt_battlemap(context: Optional[dict] = None, ai_png: Optional[bytes] = None) -> bytes:
    context = context or {}
    text = " ".join(_norm(context.get(k)) for k in ("title", "kind", "location", "description", "prompt"))
    kind = _detect_kind(text)
    rng = random.Random(_seed(text or kind))
    pal = _palette(kind)

    if ai_png and ALLOW_AI_TEXTURE and not STRICT_VTT:
        try:
            base = Image.open(io.BytesIO(ai_png)).convert("RGBA").resize((MAP_SIZE, MAP_SIZE))
            base = base.filter(ImageFilter.GaussianBlur(radius=0.2))
            overlay = Image.new("RGBA", (MAP_SIZE, MAP_SIZE), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay, "RGBA")
            _draw_grid(draw)
            out = Image.alpha_composite(base, overlay)
            buf = io.BytesIO()
            out.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            pass

    img = Image.new("RGBA", (MAP_SIZE, MAP_SIZE), (*pal["floor"], 255))
    texture = Image.new("RGBA", (MAP_SIZE, MAP_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(texture, "RGBA")
    _draw_texture(draw, rng, pal)
    img = Image.alpha_composite(img, texture)
    draw = ImageDraw.Draw(img, "RGBA")

    if kind in {"street"}:
        _draw_street(draw, rng, pal, text.lower(), fort=False)
    elif kind == "fort":
        _draw_street(draw, rng, pal, text.lower(), fort=True)
    elif kind == "interior":
        _draw_interior(draw, rng, pal, text.lower())
    else:
        _draw_dungeon(draw, rng, pal, kind, text.lower())

    _draw_grid(draw)
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_grid_sidecar(path: Path, context: Optional[dict] = None) -> None:
    meta = {
        "format": "vtt-battlemap",
        "width_px": MAP_SIZE,
        "height_px": MAP_SIZE,
        "grid_size_px": GRID_SIZE_PX,
        "grid_cells": GRID_CELLS,
        "scale": "1 square = 5 ft",
        "context": context or {},
    }
    path.with_suffix(".vtt.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def pretty_map_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}_pretty{path.suffix}")


def tactical_map_path(path: Path) -> Path:
    if path.stem.endswith("_pretty"):
        return path.with_name(f"{path.stem[:-7]}{path.suffix}")
    return path


def _pretty_lora_prompt(context: Optional[dict], strategy: str = "legacy") -> tuple[str, str]:
    context = context or {}
    text = " ".join(_norm(context.get(k)) for k in ("title", "kind", "location", "description", "prompt"))
    kind = _detect_kind(text)
    if MAPCRAFT_ENABLED and strategy in {"flux", "sdxl"}:
        weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
        lora_name = MAPCRAFT_FLUX_LORA if strategy == "flux" else MAPCRAFT_SDXL_LORA
        lora_tag = f"<lora:{lora_name}:{weight}>" if lora_name else ""
        positive = ", ".join(
            p for p in [
                lora_tag,
                MAPCRAFT_TRIGGER,
                f"A top-down view of {_mapcraft_kind_phrase(kind)}.",
                "Contextually correct fantasy battlemap, detailed terrain, visible rooms, roads, walls, water, cover, hazards, entrances, exits, and tactical landmarks.",
                "Readable VTT battlemap, orthographic camera, clear top-down composition, no perspective, no people, no tokens.",
                text[:600],
            ]
            if p
        )
        negative = (
            "characters, people, creatures, monsters, tokens, portraits, face, body, isometric, perspective, "
            "side view, horizon, sky, text, watermark, labels, blurry, abstract illustration"
        )
        return positive, negative

    weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    town = os.getenv("A1111_MAP_LORA_TOWN", "EnvyFluxVillageMap01")
    dungeon = os.getenv("A1111_MAP_LORA_DUNGEON", "EnvyFluxDungeonMap01")
    interior = os.getenv("A1111_MAP_LORA_INTERIOR", "").strip()
    town_triggers = os.getenv("A1111_MAP_TOWN_TRIGGERS", "detailed, map, village")
    dungeon_triggers = os.getenv("A1111_MAP_DUNGEON_TRIGGERS", "detailed, map, dungeon")
    interior_triggers = os.getenv("A1111_MAP_INTERIOR_TRIGGERS", "detailed, map, interior, floor plan")

    if kind in {"dungeon", "cave", "sewer"}:
        lora = dungeon
        triggers = dungeon_triggers
    elif kind == "interior" and interior:
        lora = interior
        triggers = interior_triggers
    else:
        lora = town
        triggers = town_triggers

    lora_tag = f"<lora:{lora}:{weight}>" if lora else ""
    positive = ", ".join(
        p for p in [
            lora_tag,
            triggers,
            "top-down orthographic fantasy VTT battlemap",
            "preserve the exact room shapes, roads, walls, water, cover, and grid alignment from the input map",
            "painted terrain detail, readable tactical surfaces, no perspective, no people, no tokens",
            text[:500],
        ]
        if p
    )
    negative = (
        "characters, people, creatures, monsters, tokens, portraits, face, body, isometric, perspective, "
        "side view, horizon, sky, text, watermark, labels, blurry, abstract illustration"
    )
    return positive, negative


def _pretty_override_settings(strategy: str) -> dict[str, str]:
    override: dict[str, str] = {}
    if strategy == "flux":
        ckpt = MAPCRAFT_FLUX_CHECKPOINT
        if ckpt:
            override["sd_model_checkpoint"] = ckpt
    elif strategy == "sdxl":
        ckpt = os.getenv("A1111_MAPCRAFT_SDXL_CHECKPOINT", "").strip()
        if ckpt:
            override["sd_model_checkpoint"] = ckpt
    elif strategy == "legacy":
        ckpt = os.getenv("A1111_MAP_CHECKPOINT", "").strip()
        if ckpt:
            override["sd_model_checkpoint"] = ckpt
    return override


def _pretty_attempts(base_payload: dict[str, Any], context: Optional[dict]) -> list[tuple[str, dict[str, Any]]]:
    strategies = ["legacy"]
    if MAPCRAFT_ENABLED:
        strategies = ["sdxl", "legacy"]
        if PRETTY_INCLUDE_FLUX:
            strategies.insert(0, "flux")
    attempts: list[tuple[str, dict[str, Any]]] = []
    for strategy in strategies:
        positive, negative = _pretty_lora_prompt(context, strategy)
        payload = {**base_payload, "prompt": positive, "negative_prompt": negative}
        override = _pretty_override_settings(strategy)
        if override:
            payload["override_settings"] = override
            payload["override_settings_restore_afterwards"] = True
        attempts.append((strategy, payload))
    return attempts


def decode_useful_a1111_image(image_b64: str) -> bytes | None:
    """Decode an A1111 image only if it has enough visual signal to be useful."""
    try:
        raw = base64.b64decode(image_b64)
        with Image.open(io.BytesIO(raw)) as img:
            rgb = img.convert("RGB")
            stat = ImageStat.Stat(rgb.resize((64, 64), Image.Resampling.BILINEAR))
            # Flat gray/black/white outputs can happen when a checkpoint switch
            # half-fails. Treat those as failed attempts and try the next lane.
            if max(stat.stddev) < 4.0:
                return None
            if len(raw) < 50_000:
                return None
        return raw
    except Exception:
        return None


def _decode_useful_pretty_image(image_b64: str) -> bytes | None:
    return decode_useful_a1111_image(image_b64)


def stylize_pretty_battlemap(path: Path, context: Optional[dict] = None, force: bool = False) -> Optional[Path]:
    """
    Run a tactical map back through A1111 as img2img and save a sibling *_pretty.png.

    This is intentionally a presentation pass. The tactical map remains the
    authoritative VTT-safe file.
    """
    if not PRETTY_MAPS and not force:
        return None
    if not path.exists() or path.stem.endswith("_pretty"):
        return None

    out = pretty_map_path(path)
    if out.exists() and not force:
        return out

    try:
        from src.resource_cop import ask_a1111_sync

        decision = ask_a1111_sync("pretty_map", model_hint=str((context or {}).get("kind") or ""))
        if not decision.run_now:
            logger.info("Pretty map pass deferred for %s: %s", path, decision.reason)
            return None
    except Exception as exc:
        logger.debug("Pretty map traffic-cop check failed for %s: %s", path, exc)

    try:
        with Image.open(path) as img:
            img = img.convert("RGB").resize((PRETTY_SIZE, PRETTY_SIZE), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            init_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        logger.warning("Could not prepare tactical map for pretty pass %s: %s", path, exc)
        return None

    payload = {
        "init_images": [init_b64],
        "width": PRETTY_SIZE,
        "height": PRETTY_SIZE,
        "steps": int(os.getenv("VTT_MAP_PRETTY_STEPS", "24")),
        "cfg_scale": float(os.getenv("VTT_MAP_PRETTY_CFG", "3.5")),
        "sampler_name": os.getenv("VTT_MAP_PRETTY_SAMPLER", "Euler"),
        "denoising_strength": PRETTY_DENOISE,
        "seed": -1,
        "resize_mode": 1,
    }

    try:
        with httpx.Client(timeout=PRETTY_TIMEOUT) as client:
            try:
                client.post(f"{A1111_URL}/sdapi/v1/refresh-loras", timeout=15.0)
            except Exception:
                pass

            images = []
            attempts = _pretty_attempts(payload, context)
            for idx, (strategy, attempt) in enumerate(attempts, start=1):
                wait_for_a1111_idle(cooldown=max(A1111_COOLDOWN_SECONDS, A1111_MODEL_SWAP_COOLDOWN if idx > 1 else 0))
                try:
                    logger.info("Pretty map pass trying %s strategy for %s", strategy, path)
                    endpoint = "img2img"
                    if PRETTY_MAPCRAFT_TEXT2IMG and strategy in {"flux", "sdxl"}:
                        endpoint = "txt2img"
                        attempt = {
                            k: v for k, v in attempt.items()
                            if k not in {"init_images", "resize_mode", "denoising_strength"}
                        }
                    resp = client.post(f"{A1111_URL}/sdapi/v1/{endpoint}", json=attempt)
                    resp.raise_for_status()
                    images = resp.json().get("images", [])
                    wait_for_a1111_idle(cooldown=max(A1111_COOLDOWN_SECONDS, 45))
                    if images and not _decode_useful_pretty_image(images[0]):
                        logger.warning("Pretty map pass %s strategy returned a blank/invalid image for %s", strategy, path)
                        images = []
                    if images:
                        break
                except Exception as exc:
                    logger.warning("Pretty map pass %s strategy failed for %s: %s", strategy, path, exc)
                    wait_for_a1111_idle(cooldown=max(A1111_COOLDOWN_SECONDS, A1111_MODEL_SWAP_COOLDOWN))
            if not images:
                fallback = {
                    **payload,
                    "prompt": _pretty_lora_prompt(context, "legacy")[0],
                    "negative_prompt": _pretty_lora_prompt(context, "legacy")[1],
                    "width": min(PRETTY_SIZE, 768),
                    "height": min(PRETTY_SIZE, 768),
                    "steps": min(int(payload["steps"]), 18),
                    "denoising_strength": min(PRETTY_DENOISE, 0.24),
                }
                override = _pretty_override_settings("legacy")
                if override:
                    fallback["override_settings"] = override
                    fallback["override_settings_restore_afterwards"] = True
                try:
                    logger.info("Pretty map pass trying reduced legacy strategy for %s", path)
                    wait_for_a1111_idle(cooldown=max(A1111_COOLDOWN_SECONDS, A1111_MODEL_SWAP_COOLDOWN))
                    resp = client.post(f"{A1111_URL}/sdapi/v1/img2img", json=fallback)
                    resp.raise_for_status()
                    images = resp.json().get("images", [])
                    wait_for_a1111_idle(cooldown=max(A1111_COOLDOWN_SECONDS, 45))
                    if images and not _decode_useful_pretty_image(images[0]):
                        logger.warning("Pretty map pass reduced legacy strategy returned a blank/invalid image for %s", path)
                        images = []
                except Exception as exc:
                    logger.warning("Pretty map pass reduced legacy strategy failed for %s: %s", path, exc)
                    wait_for_a1111_idle(cooldown=max(A1111_COOLDOWN_SECONDS, A1111_MODEL_SWAP_COOLDOWN))
    except Exception as exc:
        logger.warning("Pretty map pass failed for %s: %s", path, exc)
        return None

    if not images:
        logger.warning("Pretty map pass returned no images for %s", path)
        return None

    try:
        pretty_bytes = _decode_useful_pretty_image(images[0])
        if not pretty_bytes:
            logger.warning("Pretty map pass refused to save blank/invalid image for %s", path)
            return None
        out.write_bytes(pretty_bytes)
        out.with_suffix(".vtt.json").write_text(
            json.dumps(
                {
                    "format": "pretty-battlemap-preview",
                    "source_tactical_map": path.name,
                    "scale": "presentation copy; use tactical map for exact VTT grid",
                    "context": context or {},
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return out
    except Exception as exc:
        logger.warning("Could not save pretty map %s: %s", out, exc)
        return None


def stylize_pretty_battlemap_safe(path: Path, context: Optional[dict] = None, force: bool = False) -> Optional[Path]:
    """
    Run the pretty pass without blocking a live asyncio event loop.

    Mission pipelines are async Discord tasks. The pretty pass polls A1111 and
    sleeps between attempts, so calling it directly from the event loop can
    starve Discord heartbeats. In async contexts we queue it on a single worker;
    in normal sync contexts we keep the old blocking behavior.
    """
    try:
        import asyncio

        asyncio.get_running_loop()
        in_event_loop = True
    except RuntimeError:
        in_event_loop = False

    if not in_event_loop:
        return stylize_pretty_battlemap(path, context, force)

    path = Path(path)
    context_copy = dict(context or {})

    def _done(future) -> None:
        try:
            future.result()
        except Exception as exc:
            logger.warning("Background pretty map pass failed for %s: %s", path, exc)

    future = _PRETTY_EXECUTOR.submit(stylize_pretty_battlemap, path, context_copy, force)
    future.add_done_callback(_done)
    logger.info("Pretty map pass queued in background for %s", path)
    return pretty_map_path(path) if pretty_map_path(path).exists() else None


def save_vtt_battlemap(path: Path, ai_b64: str | None = None, context: Optional[dict] = None) -> Path:
    ai_bytes = None
    if ai_b64:
        ai_bytes = decode_useful_a1111_image(ai_b64)
        if not ai_bytes:
            logger.warning("Refusing blank/invalid AI map texture for %s", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_vtt_battlemap(context=context, ai_png=ai_bytes))
    write_grid_sidecar(path, context)
    stylize_pretty_battlemap_safe(path, context)
    return path


def save_vtt_battlemap_bytes(path: Path, ai_bytes: bytes | None = None, context: Optional[dict] = None) -> Path:
    """Save a VTT-safe tactical map from raw PNG bytes, then run the pretty pass."""
    if ai_bytes:
        try:
            with Image.open(io.BytesIO(ai_bytes)) as img:
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                ai_bytes = buf.getvalue()
        except Exception:
            logger.warning("Refusing unreadable AI map texture for %s", path)
            ai_bytes = None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_vtt_battlemap(context=context, ai_png=ai_bytes))
    write_grid_sidecar(path, context)
    stylize_pretty_battlemap_safe(path, context)
    return path
