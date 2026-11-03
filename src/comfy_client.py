"""
comfy_client.py — ComfyUI image backend (replaces the A1111 /sdapi/v1 API).

Callers keep building the payloads they always have (prompt, negative_prompt,
width, height, seed, init_images, denoising_strength, override_settings) and
get back the same shape A1111 returned: {"images": [base64 PNG, ...], "info": ...}.

What changed underneath:
  * Checkpoint names are mapped to three ComfyUI recipes, each tuned for its
    model, so old SDXL sampler/step/CFG settings are ignored:
        scene — Z-Image Turbo (photoreal city scenes, portraits, item art)
        anime — WAI Illustrious v17 (IMAGE_STYLE=anime)
        map   — Qwen-Image / RedCraft (battle maps, area maps, tiles)
  * Every request runs inside a GPU turn (src.gpu_queue), so Ollama and
    ComfyUI never hold the card at the same time.
  * Images come back over ComfyUI's websocket (StudioImageOut node from the
    prompt-studio extension); img2img sources go in inline (StudioImageIn).
    Nothing is written to ComfyUI's output or input folders.

Usage:
    from src import comfy_client as comfy
    comfy.set_checkpoint(A1111_MODEL)             # was POST /sdapi/v1/options
    data = await comfy.generate(payload, label="npc_portrait")
    img_bytes = base64.b64decode(data["images"][0])
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import random
import re
import uuid
from typing import Any, Optional

import aiohttp
import httpx

from src import gpu_queue

logger = logging.getLogger(__name__)

OUT_NODE = "99"


class ComfyError(RuntimeError):
    """ComfyUI rejected or failed a generation."""


def comfy_url() -> str:
    return os.getenv("COMFY_URL", "http://127.0.0.1:8188").split()[0].rstrip("/")


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------

RECIPES: dict[str, dict[str, Any]] = {
    "scene": {
        "flow": True,
        "unet": os.getenv("COMFY_SCENE_UNET", "z_image_turbo_nvfp4.safetensors"),
        "clip": os.getenv("COMFY_SCENE_CLIP", "qwen_3_4b_fp8_mixed.safetensors"),
        "clip_type": "lumina2",
        "vae": os.getenv("COMFY_SCENE_VAE", "ae.safetensors"),
        "shift": 3.0,
        "latent": "EmptySD3LatentImage",
        "sampler": "res_multistep",
        "scheduler": "simple",
        "steps": 8,
        "cfg": 1.0,
    },
    "map": {
        "flow": True,
        "unet": os.getenv("COMFY_MAP_UNET", "redcraft_30Fixqw21t_fp8.safetensors"),
        "clip": os.getenv("COMFY_MAP_CLIP", "qwen3vl_8b_int8_convrot.safetensors"),
        "clip_type": "qwen_image",
        "vae": os.getenv("COMFY_MAP_VAE", "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"),
        "shift": 1.31,
        "latent": "EmptyLatentImage",
        "sampler": "er_sde",
        "scheduler": "simple",
        "steps": 8,
        "cfg": 1.0,
    },
    "anime": {
        "flow": False,
        "ckpt": os.getenv("COMFY_ANIME_CKPT", "waiIllustriousSDXL_v170.safetensors"),
        "latent": "EmptyLatentImage",
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "steps": 28,
        "cfg": 6.0,
    },
}

_MAP_HINTS = ("flux", "map", "mapcraft", "epicrealism", "qwen", "redcraft", "battle", "tile")
_ANIME_HINTS = ("illustrious", "wai", "anime", "animagine", "noob", "pony")

_checkpoint: str = os.getenv("A1111_MODEL", "")


def set_checkpoint(name: str) -> None:
    """Remember the active checkpoint, as A1111's sd_model_checkpoint option did."""
    global _checkpoint
    if name:
        _checkpoint = name


def get_checkpoint() -> str:
    return _checkpoint


def recipe_for(checkpoint: str | None) -> str:
    """Map an A1111 checkpoint name (or a recipe name) to a recipe."""
    name = (checkpoint or "").strip()
    low = name.lower()
    if low in RECIPES:
        return low
    if not name:
        return "anime" if os.getenv("IMAGE_STYLE", "").lower() == "anime" else "scene"
    anime_ckpt = os.getenv("A1111_ANIME_MODEL", "").strip().lower()
    if anime_ckpt and anime_ckpt in low:
        return "anime"
    if any(h in low for h in _MAP_HINTS):
        return "map"
    if any(h in low for h in _ANIME_HINTS):
        return "anime"
    return "scene"


def available_models() -> list[dict[str, str]]:
    """A1111 /sd-models-shaped list of what the recipes load."""
    names = [r.get("unet") or r.get("ckpt") for r in RECIPES.values()]
    return [{"title": n, "model_name": n} for n in names if n]


# ---------------------------------------------------------------------------
# Payload -> graph
# ---------------------------------------------------------------------------

_LORA_TAG = re.compile(r"<lora:[^>]+>", re.IGNORECASE)


def _clean_prompt(text: str) -> str:
    text = _LORA_TAG.sub("", text or "")
    text = re.sub(r"\s*,\s*(,\s*)+", ", ", text)
    return text.strip(" ,")


def _snap(v: int) -> int:
    return max(256, int(round(v / 16.0)) * 16)


def _render_size(width: int, height: int) -> tuple[int, int]:
    """All three recipes look best near one megapixel; small requests are rendered larger."""
    w, h = _snap(width), _snap(height)
    target = 1024 * 1024
    area = w * h
    if area < 0.8 * target:
        scale = (target / area) ** 0.5
        w, h = _snap(w * scale), _snap(h * scale)
    while max(w, h) > 1536:
        w, h = _snap(w * 0.9), _snap(h * 0.9)
    return w, h


def _seed(payload: dict) -> int:
    seed = payload.get("seed", -1)
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = -1
    return seed if seed >= 0 else random.randint(1, 2**31 - 1)


def build_graph(payload: dict, recipe_name: str) -> tuple[dict, dict]:
    """Translate an A1111-style payload into a ComfyUI API graph."""
    r = RECIPES[recipe_name]
    req_w = int(payload.get("width") or 1024)
    req_h = int(payload.get("height") or 1024)
    w, h = _render_size(req_w, req_h)
    batch = max(1, int(payload.get("batch_size") or 1)) * max(1, int(payload.get("n_iter") or 1))
    batch = min(batch, 4)
    seed = _seed(payload)
    init = (payload.get("init_images") or [None])[0]
    denoise = float(payload.get("denoising_strength", 0.75)) if init else 1.0

    g: dict[str, dict] = {}
    if r["flow"]:
        g["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": r["unet"], "weight_dtype": "default"}}
        g["2"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": r["clip"], "type": r["clip_type"], "device": "default"}}
        g["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": r["vae"]}}
        g["4"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": r["shift"]}}
        model, clip, vae = ["4", 0], ["2", 0], ["3", 0]
        cfg = r["cfg"]
        steps = r["steps"]
    else:
        g["1"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": r["ckpt"]}}
        model, clip, vae = ["1", 0], ["1", 1], ["1", 2]
        cfg = min(8.0, max(4.0, float(payload.get("cfg_scale") or r["cfg"])))
        steps = min(36, max(20, int(payload.get("steps") or r["steps"])))

    g["5"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": _clean_prompt(payload.get("prompt", ""))}}
    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": _clean_prompt(payload.get("negative_prompt", ""))}}

    if init:
        g["20"] = {"class_type": "StudioImageIn", "inputs": {"image_b64": init}}
        g["21"] = {"class_type": "ImageScale", "inputs": {"image": ["20", 0], "upscale_method": "lanczos",
                                                          "width": w, "height": h, "crop": "center"}}
        g["22"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["21", 0], "vae": vae}}
        latent = ["22", 0]
        if batch > 1:
            g["23"] = {"class_type": "RepeatLatentBatch", "inputs": {"samples": ["22", 0], "amount": batch}}
            latent = ["23", 0]
    else:
        g["7"] = {"class_type": r["latent"], "inputs": {"width": w, "height": h, "batch_size": batch}}
        latent = ["7", 0]

    g["8"] = {"class_type": "KSampler", "inputs": {
        "model": model, "positive": ["5", 0], "negative": ["6", 0], "latent_image": latent,
        "seed": seed, "steps": steps, "cfg": cfg,
        "sampler_name": r["sampler"], "scheduler": r["scheduler"], "denoise": denoise,
    }}
    g["9"] = {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": vae}}
    g[OUT_NODE] = {"class_type": "StudioImageOut", "inputs": {"images": ["9", 0]}}

    info = {"seed": seed, "recipe": recipe_name, "width": req_w, "height": req_h,
            "render_width": w, "render_height": h, "steps": steps, "cfg": cfg, "denoise": denoise}
    return g, info


# ---------------------------------------------------------------------------
# Running a graph
# ---------------------------------------------------------------------------

def _image_from_frame(frame: bytes) -> Optional[bytes]:
    if len(frame) < 8:
        return None
    event = int.from_bytes(frame[:4], "big")
    if event == 1:                      # [type][format][image]
        return frame[8:]
    if event == 4:                      # [type][meta len][meta json][image]
        meta_len = int.from_bytes(frame[4:8], "big")
        return frame[8 + meta_len:]
    return None


async def _run_graph(graph: dict, timeout: float) -> list[bytes]:
    base = comfy_url()
    ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
    client_id = uuid.uuid4().hex
    images: list[bytes] = []
    session_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=session_timeout) as session:
        async with session.ws_connect(f"{ws_base}/ws?clientId={client_id}", max_msg_size=0) as ws:
            async with session.post(f"{base}/prompt", json={"prompt": graph, "client_id": client_id}) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise ComfyError(f"ComfyUI rejected the prompt ({resp.status}): {body[:500]}")
                prompt_id = json.loads(body)["prompt_id"]

            executing: Optional[str] = None
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    kind, d = data.get("type"), data.get("data") or {}
                    if d.get("prompt_id") not in (None, prompt_id):
                        continue
                    if kind == "executing":
                        executing = d.get("node")
                        if executing is None and d.get("prompt_id") == prompt_id:
                            break
                    elif kind == "execution_success":
                        break
                    elif kind == "execution_error":
                        raise ComfyError(f"{d.get('node_type')}: {d.get('exception_message', '')[:500]}")
                    elif kind == "execution_interrupted":
                        raise ComfyError("generation was interrupted")
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    if executing == OUT_NODE:
                        img = _image_from_frame(msg.data)
                        if img:
                            images.append(img)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise ComfyError("ComfyUI websocket closed mid-generation")
    return images


def _fit_to_request(png: bytes, width: int, height: int) -> bytes:
    """Return the image at the size the caller asked for (recipes may render larger)."""
    from PIL import Image
    with Image.open(io.BytesIO(png)) as img:
        if img.size == (width, height):
            return png
        out = img.convert("RGB")
        src_ratio, dst_ratio = out.width / out.height, width / height
        if abs(src_ratio - dst_ratio) > 0.01:
            if src_ratio > dst_ratio:
                new_w = int(out.height * dst_ratio)
                left = (out.width - new_w) // 2
                out = out.crop((left, 0, left + new_w, out.height))
            else:
                new_h = int(out.width / dst_ratio)
                top = (out.height - new_h) // 2
                out = out.crop((0, top, out.width, top + new_h))
        out = out.resize((width, height), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()


async def generate(payload: dict, *, label: str = "", checkpoint: str | None = None,
                   timeout: float | None = None) -> dict:
    """Run an A1111-style txt2img/img2img payload on ComfyUI.

    The checkpoint is taken from (in order) the `checkpoint` argument,
    payload["override_settings"]["sd_model_checkpoint"], then the last
    set_checkpoint() value.
    """
    override = (payload.get("override_settings") or {}).get("sd_model_checkpoint")
    recipe_name = recipe_for(checkpoint or override or _checkpoint)
    graph, info = build_graph(payload, recipe_name)
    timeout = float(timeout or os.getenv("COMFY_TIMEOUT", "900"))

    async with gpu_queue.turn("image", label or recipe_name):
        logger.info("🖼️ ComfyUI %s [%s] %sx%s%s", recipe_name, label,
                    info["render_width"], info["render_height"],
                    f" img2img denoise={info['denoise']:.2f}" if "20" in graph else "")
        pngs = await _run_graph(graph, timeout)

    if not pngs:
        raise ComfyError("ComfyUI finished without returning an image")
    pngs = [_fit_to_request(p, info["width"], info["height"]) for p in pngs]
    return {
        "images": [base64.b64encode(p).decode("ascii") for p in pngs],
        "parameters": {k: v for k, v in payload.items() if k != "init_images"},
        "info": json.dumps(info),
    }


def generate_sync(payload: dict, *, label: str = "", checkpoint: str | None = None,
                  timeout: float | None = None) -> dict:
    """Blocking generate() for worker threads (e.g. the pretty-map pass).

    When the bot is running, the job is handed to its event loop so it waits
    in the same GPU queue as everything else.
    """
    loop = gpu_queue.main_loop()
    coro = generate(payload, label=label, checkpoint=checkpoint, timeout=timeout)
    if loop is not None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            coro.close()
            raise RuntimeError("generate_sync() called on the event loop; await generate() instead")
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Status and control
# ---------------------------------------------------------------------------

async def is_ready() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{comfy_url()}/object_info/StudioImageOut")
            return r.status_code == 200 and "StudioImageOut" in r.text
    except Exception:
        return False


def _queue_busy(data: dict) -> bool:
    return bool(data.get("queue_running")) or bool(data.get("queue_pending"))


async def is_busy() -> bool:
    if gpu_queue.locked():
        return True
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            return _queue_busy((await client.get(f"{comfy_url()}/queue")).json())
    except Exception:
        return False


def is_busy_sync() -> bool:
    if gpu_queue.locked():
        return True
    try:
        with httpx.Client(timeout=5.0) as client:
            return _queue_busy(client.get(f"{comfy_url()}/queue").json())
    except Exception:
        return False


async def interrupt() -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{comfy_url()}/interrupt")
        return r.status_code < 400
    except Exception as exc:
        logger.error("ComfyUI interrupt failed: %r", exc)
        return False


async def free_vram() -> None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(f"{comfy_url()}/free", json={"unload_models": True, "free_memory": True})
    except Exception as exc:
        logger.debug("ComfyUI free failed: %r", exc)
