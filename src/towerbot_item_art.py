"""Daily A1111 fallback art for TowerBot item cards."""

from __future__ import annotations

import asyncio
import base64
import os
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

from src.db_api import raw_query, save_image_ref, set_global_state, get_global_state
from src.log import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ART_DIR = PROJECT_ROOT / "campaign_docs" / "image_refs" / "towerbot_items"
ENTITY_TYPE = "towerbot_item"

GENERIC_TYPES = [
    ("sword", ("sword", "rapier", "scimitar", "blade")),
    ("axe", ("axe", "battleaxe", "greataxe", "handaxe")),
    ("bow", ("bow", "longbow", "shortbow")),
    ("crossbow", ("crossbow",)),
    ("firearm", ("pistol", "rifle", "musket", "firearm", "gun")),
    ("polearm", ("spear", "javelin", "trident", "pike", "halberd", "glaive", "lance")),
    ("dagger", ("dagger", "knife", "needle", "dart")),
    ("hammer", ("hammer", "maul", "mace", "club", "warhammer")),
    ("armor", ("armor", "mail", "plate", "breastplate", "shield", "hide", "leather", "padded")),
    ("boots", ("boots", "slippers", "shoes")),
    ("amulet", ("amulet", "necklace", "periapt")),
    ("ring", ("ring",)),
    ("wand", ("wand",)),
    ("staff", ("staff",)),
    ("rod", ("rod",)),
    ("instrument", ("instrument", "lute", "lyre", "horn", "flute", "drum")),
    ("book", ("book", "grimoire", "manual", "tome")),
    ("tool", ("tool", "tools", "kit")),
    ("bag", ("bag", "sack", "pouch", "haversack")),
    ("cloak", ("cloak", "cape", "robe", "mantle")),
    ("gloves", ("gloves", "gauntlets")),
    ("gem", ("gem", "stone", "crystal", "orb", "pearl")),
    ("bottle", ("bottle", "flask", "jug", "vial")),
]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80] or "item"


def generic_item_key(name: str, item_type: str = "") -> str:
    text = re.sub(r"^\+\d+\s+", "", str(name or "").lower())
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("adamantine", " ").replace("silvered", " ")
    for key, words in GENERIC_TYPES:
        if any(word in text for word in words):
            return key
    if item_type in {"M", "R", "A"}:
        return "weapon"
    if item_type in {"LA", "MA", "HA", "S"}:
        return "armor"
    return _slug(text)


def _display_name(key: str) -> str:
    return key.replace("_", " ").title()


def _project_media_url(path: Path) -> str:
    rel = path.resolve().relative_to(PROJECT_ROOT).as_posix()
    return "/media/project/" + rel


def image_url_for_item_art_key(key: str) -> str:
    row = raw_query(
        "SELECT image_path FROM image_refs WHERE entity_type=%s AND entity_name=%s LIMIT 1",
        (ENTITY_TYPE, key),
    )
    if not row or not row[0].get("image_path"):
        return ""
    path = (PROJECT_ROOT / str(row[0]["image_path"])).resolve()
    if not path.exists():
        return ""
    return _project_media_url(path)


def missing_art_keys(limit: int = 6) -> list[dict]:
    rows = raw_query(
        """
        SELECT item_name, item_type
        FROM towerbot_world_items
        WHERE status='active' AND COALESCE(image_url, '') = ''
        ORDER BY listed_at DESC, id DESC
        """
    ) or []
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        key = generic_item_key(row.get("item_name") or "", row.get("item_type") or "")
        if key in seen or image_url_for_item_art_key(key):
            continue
        seen.add(key)
        out.append({
            "key": key,
            "display": _display_name(key),
            "example": row.get("item_name") or key,
        })
        if len(out) >= limit:
            break
    return out


async def _call_a1111(prompt: str, negative: str) -> Optional[bytes]:
    from src.a1111_runtime import cool_down_a1111_after_generation, ensure_a1111_model
    from src.news_feed import a1111_lock
    from src.resource_cop import wait_for_a1111_turn

    url = os.getenv("A1111_URL", "http://127.0.0.1:7860").split()[0].rstrip("/")
    model = os.getenv("A1111_ITEM_MODEL", os.getenv("A1111_MODEL", ""))
    decision = await wait_for_a1111_turn("towerbot_item_art", model_hint=model, max_wait_seconds=90)
    if not decision.run_now:
        logger.info("TowerBot item art skipped: A1111 busy (%s)", decision.reason)
        return None

    async with a1111_lock:
        await ensure_a1111_model(model, label="ITEM_ART", url=url)
        payload = {
            "prompt": prompt,
            "negative_prompt": negative,
            "steps": int(os.getenv("A1111_ITEM_STEPS", "24")),
            "cfg_scale": float(os.getenv("A1111_ITEM_CFG", "6.0")),
            "width": int(os.getenv("A1111_ITEM_WIDTH", "768")),
            "height": int(os.getenv("A1111_ITEM_HEIGHT", "768")),
            "sampler_name": os.getenv("A1111_ITEM_SAMPLER", "DPM++ 2M SDE Karras"),
            "seed": random.randint(1, 999_999_999),
            "batch_size": 1,
            "n_iter": 1,
        }
        timeout = float(os.getenv("A1111_ITEM_TIMEOUT", "600"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{url}/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
            images = resp.json().get("images") or []
        await cool_down_a1111_after_generation(cooldown=float(os.getenv("A1111_ITEM_COOLDOWN", "20")))
    if not images:
        return None
    return base64.b64decode(images[0])


async def generate_item_art_batch(batch_size: int | None = None) -> int:
    batch_size = batch_size or int(os.getenv("TOWERBOT_ITEM_ART_BATCH", "4"))
    candidates = missing_art_keys(batch_size)
    if not candidates:
        logger.info("TowerBot item art: no missing generic item art keys")
        return 0

    ART_DIR.mkdir(parents=True, exist_ok=True)
    negative = (
        "person, hands, character, text, watermark, label, logo, blurry, low quality, "
        "cropped, cluttered background, multiple objects"
    )
    made = 0
    for item in candidates:
        key = item["key"]
        display = item["display"]
        prompt = (
            f"single fantasy RPG magic item, {display}, isolated object, centered, "
            "plain warm parchment background, studio product illustration, detailed material, "
            "soft shadow, readable silhouette, no text, no person, game inventory icon"
        )
        try:
            img = await _call_a1111(prompt, negative)
        except Exception as exc:
            logger.warning("TowerBot item art generation failed for %s: %r", key, exc)
            img = None
        if not img:
            continue
        path = ART_DIR / f"{_slug(key)}.png"
        path.write_bytes(img)
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        save_image_ref(ENTITY_TYPE, key, rel, {
            "prompt": prompt,
            "example_item": item["example"],
            "generated_by": "towerbot_item_art",
        })
        logger.info("TowerBot item art saved: %s", rel)
        made += 1
        await asyncio.sleep(float(os.getenv("TOWERBOT_ITEM_ART_PAUSE", "2")))
    return made


async def run_daily_item_art_if_due() -> int:
    hour = int(os.getenv("TOWERBOT_ITEM_ART_HOUR", "4"))
    now = datetime.now()
    last = get_global_state("towerbot_item_art_last_run")
    if last:
        try:
            last_dt = datetime.fromisoformat(str(last))
            if last_dt.date() == now.date():
                return 0
        except Exception:
            pass
    if now.hour != hour:
        return 0
    had_candidates = bool(missing_art_keys(1))
    if not had_candidates:
        set_global_state("towerbot_item_art_last_run", now.isoformat())
        return 0
    made = await generate_item_art_batch()
    if made:
        set_global_state("towerbot_item_art_last_run", now.isoformat())
    return made
