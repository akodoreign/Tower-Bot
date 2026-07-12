"""Quarantined A1111 map-lane experiments.

Runs a small set of checkpoint/LoRA/prompt combinations against one module room
context and writes outputs under generated_modules/_map_experiments. Nothing is
cached, injected into HTML, or promoted automatically.

No VAE overrides are used.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backfill_infestation_room_maps import _read_text, _room_blocks, _room_context
from src.mission_builder.vtt_renderer import A1111_URL, wait_for_a1111_idle

MODULES_DIR = ROOT / "generated_modules"
OUT_BASE = MODULES_DIR / "_map_experiments"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:80] or "map"


def _score_image(raw: bytes) -> dict:
    try:
        with Image.open(io.BytesIO(raw)) as img:
            rgb = img.convert("RGB")
            small = rgb.resize((64, 64), Image.Resampling.BILINEAR)
            stat = ImageStat.Stat(small)
            return {
                "bytes": len(raw),
                "stddev_max": round(max(stat.stddev), 2),
                "stddev": [round(v, 2) for v in stat.stddev],
                "size": list(rgb.size),
                "passes_signal_gate": len(raw) >= 90_000 and max(stat.stddev) >= 8.0,
            }
    except Exception as exc:
        return {"bytes": len(raw), "error": str(exc), "passes_signal_gate": False}


def _prompt(context: dict, lane: dict) -> tuple[str, str]:
    lora = lane.get("lora", "").strip()
    lora_tag = f"<lora:{lora}:{lane.get('weight', '0.8')}>" if lora else ""
    trigger = lane.get("trigger", "").strip()
    positive = ", ".join(
        p
        for p in [
            lora_tag,
            trigger,
            "roofless overhead floor plan, camera straight down, no vertical wall cutaway",
            "top-down orthographic D&D VTT battlemap",
            "single complete dungeon room layout with readable entrances and exits",
            "clear walls, doors, stairs, cover objects, hazards, stone floor, tactical boundaries",
            "dark fantasy cellar infestation room, professional virtual tabletop battlemap asset",
            "no characters, no monsters, no tokens",
            context.get("prompt", ""),
        ]
        if p
    )
    negative = (
        "side view, first person, perspective, isometric, horizon, sky, landscape, portrait, "
        "cutaway, dollhouse, elevation view, vertical wall facade, characters, monsters, tokens, "
        "text, watermark, blurry, abstract, empty flat wall"
    )
    return positive, negative


def _lanes() -> list[dict]:
    return [
        {
            "name": "baseline_sdxl",
            "checkpoint": os.getenv("A1111_NICE_MAP_CHECKPOINT", os.getenv("A1111_MODEL", "")).strip(),
            "sampler": os.getenv("A1111_NICE_MAP_SAMPLER", "DPM++ 2M Karras"),
            "steps": int(os.getenv("A1111_EXPERIMENT_BASE_STEPS", "18")),
            "cfg": float(os.getenv("A1111_EXPERIMENT_BASE_CFG", "6.0")),
        },
        {
            "name": "flux_mapcraft",
            "checkpoint": os.getenv("A1111_MAPCRAFT_FLUX_CHECKPOINT", os.getenv("A1111_MAP_CHECKPOINT", "")).strip(),
            "lora": os.getenv("A1111_MAPCRAFT_FLUX_LORA", "mapcraft_flux_v2").strip(),
            "trigger": os.getenv("A1111_MAPCRAFT_TRIGGER", "mapcraft.").strip(),
            "weight": os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"),
            "sampler": "Euler",
            "steps": int(os.getenv("A1111_EXPERIMENT_FLUX_STEPS", "20")),
            "cfg": float(os.getenv("A1111_EXPERIMENT_FLUX_CFG", "1.0")),
        },
        {
            "name": "sdxl_mapcraft",
            "checkpoint": os.getenv("A1111_MAPCRAFT_SDXL_CHECKPOINT", "").strip(),
            "lora": os.getenv("A1111_MAPCRAFT_SDXL_LORA", "mapcraft_sdxl_v1").strip(),
            "trigger": os.getenv("A1111_MAPCRAFT_TRIGGER", "mapcraft.").strip(),
            "weight": os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"),
            "sampler": os.getenv("A1111_NICE_MAP_SAMPLER", "DPM++ 2M Karras"),
            "steps": int(os.getenv("A1111_EXPERIMENT_SDXL_STEPS", "18")),
            "cfg": float(os.getenv("A1111_EXPERIMENT_SDXL_CFG", "5.0")),
        },
    ]


def _context(slug: str, room_id: int) -> dict:
    module_dir = MODULES_DIR / slug
    module_html = _read_text(module_dir / "module.html")
    rooms = sorted(_room_blocks(module_html), key=lambda room: room["id"])
    room = next((room for room in rooms if room["id"] == room_id), rooms[0])
    return _room_context(module_dir, room, module_html)


def _generate(lane: dict, context: dict, out_dir: Path) -> dict:
    positive, negative = _prompt(context, lane)
    payload = {
        "prompt": positive,
        "negative_prompt": negative,
        "width": 1024,
        "height": 1024,
        "steps": lane["steps"],
        "cfg_scale": lane["cfg"],
        "sampler_name": lane["sampler"],
        "seed": -1,
    }
    if lane.get("checkpoint"):
        payload["override_settings"] = {"sd_model_checkpoint": lane["checkpoint"]}
        payload["override_settings_restore_afterwards"] = True

    result = {"lane": lane, "prompt": positive, "negative_prompt": negative}
    try:
        wait_for_a1111_idle(cooldown=10)
        with httpx.Client(timeout=float(os.getenv("A1111_EXPERIMENT_TIMEOUT", "360"))) as client:
            resp = client.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
            images = resp.json().get("images") or []
        wait_for_a1111_idle(cooldown=20)
        if not images:
            result["error"] = "A1111 returned no images"
            return result
        raw = base64.b64decode(images[0])
        score = _score_image(raw)
        result["score"] = score
        out_png = out_dir / f"{lane['name']}.png"
        out_png.write_bytes(raw)
        result["output"] = str(out_png)
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", default="The_Leaden_Crowns_Corruption_20260511_091657")
    parser.add_argument("--room", type=int, default=2)
    args = parser.parse_args()

    context = _context(args.slug, args.room)
    out_dir = OUT_BASE / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slug(args.slug)}_R{args.room:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "context.json").write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")

    results = []
    for lane in _lanes():
        print(f"RUN {lane['name']} checkpoint={lane.get('checkpoint')}")
        result = _generate(lane, context, out_dir)
        results.append(result)
        if result.get("error"):
            print(f"FAIL {lane['name']}: {result['error']}")
        else:
            print(f"DONE {lane['name']}: {result.get('score')}")

    (out_dir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
