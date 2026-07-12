"""Quick test: street and sewer at wider resolution with multi-room scope prompts."""
import asyncio, base64, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx

A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")
OUT_DIR   = ROOT / "logs" / "map_lora_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CKPT_REALVIS   = "RealVisXL_V4.0.safetensors"
CKPT_JUGGERNAUT = "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"
LORA = "<lora:mapcraft_sdxl_v1:0.85>"

NEG = (
    "characters, people, tokens, miniatures, isometric, side view, perspective distortion, "
    "3d render, sky background, blurry, low quality, watermark, single room, small area, "
    "cramped, one room only"
)

TESTS = [
    # (label, ckpt, prompt, w, h, cfg, steps)
    ("street_realvis_1024sq", CKPT_REALVIS,
     f"{LORA}, mapcraft. Illustrated top-down VTT battlemap, painted tabletop RPG map art style. "
     "Wide city street district, multiple city blocks visible, cobblestone road running through center, "
     "building facades on both sides with varied rooftops, market stalls and bollards as cover, "
     "branching side alleys, a plaza or courtyard off to one side, lamp posts, drainage gutters, "
     "manhole covers, crates and barrels scattered. Amber gas lanterns casting warm pools. "
     "Thick walls clearly define all structures. Empty of characters. Grid-compatible flat overhead view.",
     1024, 1024, 4.0, 35),

    ("street_realvis_wide", CKPT_REALVIS,
     f"{LORA}, mapcraft. Illustrated top-down VTT battlemap, painted tabletop RPG map art style. "
     "Wide city street district, multiple city blocks visible, cobblestone road running through center, "
     "building facades on both sides with varied rooftops, market stalls and bollards as cover, "
     "branching side alleys, a plaza or courtyard off to one side, lamp posts, drainage gutters, "
     "manhole covers, crates and barrels scattered. Amber gas lanterns casting warm pools. "
     "Thick walls clearly define all structures. Empty of characters. Grid-compatible flat overhead view.",
     1536, 1024, 4.0, 35),

    ("street_jugg_wide", CKPT_JUGGERNAUT,
     f"{LORA}, mapcraft. Illustrated top-down VTT battlemap, painted tabletop RPG map art style. "
     "Wide city street district, multiple city blocks visible, cobblestone road running through center, "
     "building facades on both sides with varied rooftops, market stalls and bollards as cover, "
     "branching side alleys, a plaza or courtyard off to one side, lamp posts, drainage gutters, "
     "manhole covers, crates and barrels scattered. Amber gas lanterns casting warm pools. "
     "Thick walls clearly define all structures. Empty of characters. Grid-compatible flat overhead view.",
     1536, 1024, 4.0, 35),

    ("sewer_realvis_1024sq", CKPT_REALVIS,
     f"{LORA}, mapcraft. Illustrated top-down VTT battlemap, painted tabletop RPG map art style. "
     "Underground sewer network, multiple branching tunnel corridors, brick-vaulted passages connecting "
     "several chambers of different sizes, central water channels with stone walkways flanking them, "
     "junction rooms where tunnels meet, iron grates and ladders, support pillars, maintenance alcoves, "
     "pipe clusters on walls. Dim wall-bracket lanterns casting orange pools on wet stone. "
     "Deep darkness beyond lit sections. Thick stone walls. Empty of characters. Grid-compatible.",
     1024, 1024, 4.0, 35),

    ("sewer_realvis_wide", CKPT_REALVIS,
     f"{LORA}, mapcraft. Illustrated top-down VTT battlemap, painted tabletop RPG map art style. "
     "Underground sewer network, multiple branching tunnel corridors, brick-vaulted passages connecting "
     "several chambers of different sizes, central water channels with stone walkways flanking them, "
     "junction rooms where tunnels meet, iron grates and ladders, support pillars, maintenance alcoves, "
     "pipe clusters on walls. Dim wall-bracket lanterns casting orange pools on wet stone. "
     "Deep darkness beyond lit sections. Thick stone walls. Empty of characters. Grid-compatible.",
     1536, 1024, 4.0, 35),

    ("sewer_jugg_wide", CKPT_JUGGERNAUT,
     f"{LORA}, mapcraft. Illustrated top-down VTT battlemap, painted tabletop RPG map art style. "
     "Underground sewer network, multiple branching tunnel corridors, brick-vaulted passages connecting "
     "several chambers of different sizes, central water channels with stone walkways flanking them, "
     "junction rooms where tunnels meet, iron grates and ladders, support pillars, maintenance alcoves, "
     "pipe clusters on walls. Dim wall-bracket lanterns casting orange pools on wet stone. "
     "Deep darkness beyond lit sections. Thick stone walls. Empty of characters. Grid-compatible.",
     1536, 1024, 4.0, 35),
]


async def set_checkpoint(ckpt: str, current: list) -> None:
    if current and current[0] == ckpt:
        return
    print(f"\n  Loading: {ckpt} ...")
    async with httpx.AsyncClient(timeout=300.0) as c:
        await c.post(f"{A1111_URL}/sdapi/v1/options", json={"sd_model_checkpoint": ckpt})
    base = ckpt.split(".")[0].lower()
    for _ in range(60):
        await asyncio.sleep(3)
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{A1111_URL}/sdapi/v1/options")
            loaded = r.json().get("sd_model_checkpoint", "")
            if base in loaded.lower():
                print(f"  Ready: {loaded}")
                current.clear(); current.append(ckpt)
                return
    print("  WARNING: swap may not have completed")
    current.clear(); current.append(ckpt)


async def gen(label, ckpt, prompt, w, h, cfg, steps, current_ckpt):
    await set_checkpoint(ckpt, current_ckpt)
    out = OUT_DIR / f"scope_{label}.png"
    print(f"  [{label}]  {w}x{h}  cfg={cfg}")
    t0 = time.time()
    payload = {
        "prompt": prompt, "negative_prompt": NEG,
        "width": w, "height": h,
        "steps": steps, "cfg_scale": cfg,
        "sampler_name": "DPM++ 2M Karras", "seed": 42,
    }
    async with httpx.AsyncClient(timeout=600.0) as c:
        r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
        r.raise_for_status()
        imgs = r.json().get("images", [])
        if imgs:
            out.write_bytes(base64.b64decode(imgs[0]))
            kb = out.stat().st_size // 1024
            print(f"  -> {out.name}  {kb}KB  {time.time()-t0:.0f}s")
        else:
            print("  -> NO IMAGE")


async def main():
    current_ckpt = []
    for args in TESTS:
        label, ckpt, prompt, w, h, cfg, steps = args
        await gen(label, ckpt, prompt, w, h, cfg, steps, current_ckpt)
    print(f"\nDone. Files in {OUT_DIR}")

asyncio.run(main())
