"""
image_ref.py — Reference image storage for iterative A1111 generation.

Stores recent images for NPCs and locations so future generations can use
img2img instead of txt2img, producing more consistent results over time.

Directory layout:
  campaign_docs/image_refs/npcs/{name_slug}/
    pinned.png        — DM-locked canonical reference (if set)
    ref_001.png       — most recent generation
    ref_002.png       — second most recent
    ref_003.png       — oldest kept

  campaign_docs/image_refs/locations/{location_slug}/
    (same structure)

When a reference exists, callers switch from txt2img to img2img and pass
the reference as init_images with a moderate denoising strength.

Exported:
    save_npc_ref(name, img_bytes)      — store a new NPC reference
    save_location_ref(location, img_bytes) — store a new location reference
    get_npc_ref(name)                  — get best NPC ref bytes (pinned > newest)
    get_location_ref(location)         — get best location ref bytes
    pin_npc_ref(name, img_bytes)       — set canonical NPC reference
    pin_location_ref(location, img_bytes) — set canonical location reference
    to_img2img_payload(payload, ref_bytes, denoise) — convert txt2img payload to img2img
    detect_and_save_refs(text, img_bytes) — auto-detect NPCs/locations and save refs
"""

from __future__ import annotations

import base64
import re
import threading
import uuid
from pathlib import Path
from typing import Optional

from src.log import logger

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
REFS_DIR = DOCS_DIR / "image_refs"
NPC_REFS = REFS_DIR / "npcs"
NPC_ALT_REFS = REFS_DIR / "npcs_alt"
LOC_REFS = REFS_DIR / "locations"

# Ensure dirs exist at import time
for _d in (REFS_DIR, NPC_REFS, NPC_ALT_REFS, LOC_REFS):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except PermissionError as _e:
        import logging as _log
        _log.getLogger(__name__).warning("image_ref: cannot create ref dir %s: %s", _d, _e)

MAX_REFS = 10  # keep up to 10 recent images per entity (plus optional pinned)
_REF_LOCKS_GUARD = threading.Lock()
_REF_LOCKS: dict[tuple[str, str], threading.RLock] = {}

# Default denoising strength for img2img — 0.0 = exact copy, 1.0 = ignore reference
# NPC refs need enough denoise to vary new portraits instead of cloning the last face.
NPC_DENOISE      = 0.68
LOCATION_DENOISE = 0.50
SCENE_DENOISE    = 0.55  # scenes need more freedom since composition varies


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Convert a name/location to a safe directory slug."""
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip()).strip("_")[:80]


# ---------------------------------------------------------------------------
# Core save / load
# ---------------------------------------------------------------------------

def _get_entity_dir(category_dir: Path, key: str) -> Path:
    """Return the directory for a specific entity, creating it if needed."""
    d = category_dir / _slug(key)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _entity_type(category_dir: Path) -> str:
    """Map a category directory to a DB entity_type string."""
    name = category_dir.name
    if name == "npcs":
        return "npc_portrait"
    if name == "npcs_alt":
        return "npc_portrait_alt"
    if name == "locations":
        return "location_map"
    return name  # fallback: use dir name directly


def _entity_lock(category_dir: Path, key: str) -> threading.RLock:
    lock_key = (str(category_dir.resolve()), _slug(key))
    with _REF_LOCKS_GUARD:
        lock = _REF_LOCKS.get(lock_key)
        if lock is None:
            lock = threading.RLock()
            _REF_LOCKS[lock_key] = lock
        return lock


def _save_ref(
    category_dir: Path,
    key: str,
    img_bytes: bytes,
    metadata: Optional[dict] = None,
) -> Path:
    """
    Save a new reference image (rotating older ones) and register it in the DB.
    ref_001.png = newest, ref_002.png = second newest.
    Returns the path of the saved file.
    """
    with _entity_lock(category_dir, key):
        d = _get_entity_dir(category_dir, key)

        oldest = d / f"ref_{MAX_REFS:03d}.png"
        if oldest.exists():
            oldest.unlink()

        for i in range(MAX_REFS - 1, 0, -1):
            src = d / f"ref_{i:03d}.png"
            dst = d / f"ref_{i + 1:03d}.png"
            if src.exists():
                src.replace(dst)

        newest = d / "ref_001.png"
        tmp = d / f".ref_001.{uuid.uuid4().hex}.tmp"
        tmp.write_bytes(img_bytes)
        tmp.replace(newest)
        logger.info(f"Saved ref image: {d.name}/ref_001.png ({len(img_bytes):,} bytes)")

        try:
            from src.db_api import save_image_ref as _db_save
            entity_type = _entity_type(category_dir)
            _db_save(entity_type, key, str(newest.resolve()), metadata=metadata)
            logger.debug(f"DB ref registered: {entity_type}/{key}")
        except Exception as e:
            logger.warning(f"DB ref save failed (file saved OK): {e}")

        return newest

def _get_ref(category_dir: Path, key: str) -> Optional[bytes]:
    """
    Get the best reference image bytes.
    Priority: DB record → pinned.png → ref_001.png (newest) → None.
    DB is checked first so references survive filesystem reorganisation.
    """
    # 1. Try DB first — it stores the canonical path for the newest ref
    try:
        from src.db_api import get_image_ref as _db_get
        entity_type = _entity_type(category_dir)
        row = _db_get(entity_type, key)
        if row and row.get("image_path"):
            p = Path(row["image_path"])
            if p.exists():
                logger.debug(f"🖼️ Loaded ref from DB: {entity_type}/{key}")
                return p.read_bytes()
            # DB points to a missing file — fall through to filesystem
            logger.debug(f"🖼️ DB ref path missing on disk, falling back: {p}")
    except Exception as e:
        logger.debug(f"🖼️ DB ref lookup failed, falling back to filesystem: {e}")

    # 2. Filesystem fallback — check pinned then newest
    d = category_dir / _slug(key)
    if not d.exists():
        return None

    pinned = d / "pinned.png"
    if pinned.exists():
        return pinned.read_bytes()

    newest = d / "ref_001.png"
    if newest.exists():
        return newest.read_bytes()

    return None


def _pin_ref(category_dir: Path, key: str, img_bytes: bytes) -> Path:
    """Set a pinned canonical reference image and register it in the DB."""
    d = _get_entity_dir(category_dir, key)
    pinned = d / "pinned.png"
    pinned.write_bytes(img_bytes)
    logger.info(f"📌 Pinned ref image: {d.name}/pinned.png ({len(img_bytes):,} bytes)")
    try:
        from src.db_api import save_image_ref as _db_save
        _db_save(_entity_type(category_dir), key, str(pinned.resolve()), metadata={"pinned": True})
    except Exception as e:
        logger.warning(f"📌 DB pin register failed: {e}")
    return pinned


def _has_ref(category_dir: Path, key: str) -> bool:
    """Check if any reference exists — checks DB first, then filesystem."""
    try:
        from src.db_api import get_image_ref as _db_get
        row = _db_get(_entity_type(category_dir), key)
        if row and row.get("image_path") and Path(row["image_path"]).exists():
            return True
    except Exception:
        pass
    d = category_dir / _slug(key)
    if not d.exists():
        return False
    return (d / "pinned.png").exists() or (d / "ref_001.png").exists()


def _count_refs(category_dir: Path, key: str) -> int:
    """Count how many reference images exist for an entity."""
    d = category_dir / _slug(key)
    if not d.exists():
        return 0
    count = 0
    if (d / "pinned.png").exists():
        count += 1
    for i in range(1, MAX_REFS + 1):
        if (d / f"ref_{i:03d}.png").exists():
            count += 1
    return count


# ---------------------------------------------------------------------------
# NPC-specific API
# ---------------------------------------------------------------------------

def save_npc_ref(name: str, img_bytes: bytes, metadata: Optional[dict] = None) -> Path:
    """Save a new NPC portrait reference and register it in the DB."""
    return _save_ref(NPC_REFS, name, img_bytes, metadata=metadata)


def save_npc_alt_ref(name: str, img_bytes: bytes, metadata: Optional[dict] = None) -> Path:
    """Save a new alt-universe NPC portrait reference and register it in the DB."""
    return _save_ref(NPC_ALT_REFS, name, img_bytes, metadata=metadata)


def get_npc_ref(name: str) -> Optional[bytes]:
    """Get best NPC reference image bytes (DB-primary, filesystem fallback)."""
    return _get_ref(NPC_REFS, name)


def get_npc_alt_ref(name: str) -> Optional[bytes]:
    """Get best alt-universe NPC reference image bytes."""
    return _get_ref(NPC_ALT_REFS, name)


def pin_npc_ref(name: str, img_bytes: bytes) -> Path:
    """Pin a canonical NPC reference."""
    return _pin_ref(NPC_REFS, name, img_bytes)


def has_npc_ref(name: str) -> bool:
    """Check if an NPC has any reference image (DB-primary check)."""
    return _has_ref(NPC_REFS, name)


def has_npc_alt_ref(name: str) -> bool:
    """Check if an NPC has any alt-universe reference image."""
    return _has_ref(NPC_ALT_REFS, name)


# ---------------------------------------------------------------------------
# Location-specific API
# ---------------------------------------------------------------------------

def save_location_ref(location: str, img_bytes: bytes, metadata: Optional[dict] = None) -> Path:
    """Save a new location/map reference and register it in the DB."""
    return _save_ref(LOC_REFS, location, img_bytes, metadata=metadata)


def get_location_ref(location: str) -> Optional[bytes]:
    """Get best location reference image bytes (DB-primary, filesystem fallback)."""
    return _get_ref(LOC_REFS, location)


def pin_location_ref(location: str, img_bytes: bytes) -> Path:
    """Pin a canonical location reference."""
    return _pin_ref(LOC_REFS, location, img_bytes)


def has_location_ref(location: str) -> bool:
    """Check if a location has any reference image (DB-primary check)."""
    return _has_ref(LOC_REFS, location)


# ---------------------------------------------------------------------------
# Payload conversion: txt2img → img2img
# ---------------------------------------------------------------------------

def to_img2img_payload(
    txt2img_payload: dict,
    ref_bytes: bytes,
    denoising_strength: float = 0.65,
) -> dict:
    """
    Convert a txt2img payload dict to an img2img payload by injecting
    the reference image as init_images and setting denoising_strength.

    The original payload's prompt, negative_prompt, steps, cfg_scale,
    width, height, sampler_name, and seed are all preserved.
    """
    payload = dict(txt2img_payload)  # shallow copy

    # Encode reference as base64
    ref_b64 = base64.b64encode(ref_bytes).decode("utf-8")
    payload["init_images"] = [ref_b64]
    payload["denoising_strength"] = denoising_strength

    # Remove txt2img-only keys that aren't valid for img2img
    payload.pop("enable_hr", None)
    payload.pop("hr_scale", None)
    payload.pop("hr_upscaler", None)

    return payload


# ---------------------------------------------------------------------------
# Auto-detect and save references from generated images
# ---------------------------------------------------------------------------

# Location keywords → canonical location key for storage
_LOCATION_KEYWORDS: list[tuple[list[str], str]] = [
    (["neon row"],                          "neon_row"),
    (["cobbleway", "cobbleway market"],     "cobbleway_market"),
    (["floating bazaar"],                   "floating_bazaar"),
    (["crimson alley"],                     "crimson_alley"),
    (["taste of worlds"],                   "taste_of_worlds"),
    (["markets infinite", "markets"],       "markets_infinite"),
    (["grand forum library"],               "grand_forum_library"),
    (["grand forum", "central plaza"],      "grand_forum"),
    (["fountain of echoes"],                "fountain_of_echoes"),
    (["adventurer's inn", "adventurers inn"], "adventurers_inn"),
    (["guild spires"],                      "guild_spires"),
    (["arena of ascendance"],               "arena_of_ascendance"),
    (["sanctum quarter", "pantheon walk"],  "sanctum_quarter"),
    (["hall of echoes"],                    "hall_of_echoes"),
    (["divine garden"],                     "divine_garden"),
    (["shantytown heights", "shantytown"],  "shantytown_heights"),
    (["scrapworks"],                        "scrapworks"),
    (["night pits"],                        "night_pits"),
    (["echo alley"],                        "echo_alley"),
    (["collapsed plaza"],                   "collapsed_plaza"),
    (["brother thane", "cult house"],       "brother_thane"),
    (["outer wall"],                        "outer_wall"),
    (["warrens"],                           "warrens"),
]


def _detect_location(text: str) -> Optional[str]:
    """Find the first matching location key in the text."""
    lower = text.lower()
    for keywords, loc_key in _LOCATION_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return loc_key
    return None


def detect_and_save_refs(text: str, img_bytes: bytes) -> dict:
    """
    Scan text (prompt or scene description) for NPC names and locations.
    Save the generated image as a reference for each detected entity.

    Returns dict: {"npcs": [names saved], "location": location_key or None}
    """
    saved_npcs = []
    saved_location = None

    # Detect NPCs
    try:
        from src.npc_appearance import find_npc_in_text
        found_npcs = find_npc_in_text(text, exact_only=True)
        for npc_name, _sd_prompt, _district in found_npcs[:3]:
            save_npc_ref(npc_name, img_bytes)
            saved_npcs.append(npc_name)
    except Exception as e:
        logger.debug(f"🖼️ NPC ref detection error: {e}")

    # Detect location
    loc_key = _detect_location(text)
    if loc_key:
        save_location_ref(loc_key, img_bytes)
        saved_location = loc_key

    if saved_npcs or saved_location:
        npc_str = ", ".join(saved_npcs) if saved_npcs else "none"
        loc_str = saved_location or "none"
        logger.info(f"🖼️ Auto-saved refs — NPCs: {npc_str} | Location: {loc_str}")

    return {"npcs": saved_npcs, "location": saved_location}


def get_best_ref_for_scene(text: str) -> tuple[Optional[bytes], float, str]:
    """
    For a scene description, find the best reference image to use.
    Priority: NPC portrait (if single NPC focus) > location ref > None

    Returns (ref_bytes, denoising_strength, source_label) or (None, 0, "")
    """
    # Check NPCs first — if there's exactly one NPC, use their portrait
    try:
        from src.npc_appearance import find_npc_in_text
        found_npcs = find_npc_in_text(text)
        if len(found_npcs) == 1:
            name = found_npcs[0][0]
            ref = get_npc_ref(name)
            if ref:
                return ref, NPC_DENOISE, f"NPC:{name}"
    except Exception:
        pass

    # Fall back to location
    loc_key = _detect_location(text)
    if loc_key:
        ref = get_location_ref(loc_key)
        if ref:
            return ref, LOCATION_DENOISE, f"LOC:{loc_key}"

    # If multiple NPCs, use location as base (scene composition > individual portrait)
    # or if still nothing, return None
    return None, 0.0, ""


# ---------------------------------------------------------------------------
# Stats / info for /pin command feedback
# ---------------------------------------------------------------------------

async def layered_generate(
    background_prompt: str,
    full_prompt: str,
    negative_prompt: str,
    payload_base: dict,
    a1111_url: str,
    char_denoise: float = 0.60,
) -> tuple[bytes, bytes]:
    """
    Two-pass layered scene generation.
    Pass 1 (txt2img): environment-only → clean background.
    Pass 2 (img2img): full prompt + chars, background as init → composited scene.
    Returns (final_bytes, background_bytes).
    """
    import httpx
    import base64 as _b64

    p1 = dict(payload_base)
    p1["prompt"] = background_prompt
    p1["negative_prompt"] = negative_prompt

    async with httpx.AsyncClient(timeout=900.0) as http:
        r = await http.post(f"{a1111_url}/sdapi/v1/txt2img", json=p1)
        r.raise_for_status()
        bg_bytes = _b64.b64decode(r.json()["images"][0])
    logger.info(f"Layered pass 1 done ({len(bg_bytes):,} bytes) — compositing characters")

    p2 = to_img2img_payload(dict(payload_base), bg_bytes, char_denoise)
    p2["prompt"] = full_prompt
    p2["negative_prompt"] = negative_prompt

    try:
        async with httpx.AsyncClient(timeout=900.0) as http:
            r = await http.post(f"{a1111_url}/sdapi/v1/img2img", json=p2)
            r.raise_for_status()
            final_bytes = _b64.b64decode(r.json()["images"][0])
        logger.info(f"Layered pass 2 done ({len(final_bytes):,} bytes)")
    except Exception as _e:
        logger.warning(f"Layered pass 2 failed ({_e!r}); returning pass-1 background as result")
        final_bytes = bg_bytes

    return final_bytes, bg_bytes


def get_ref_stats() -> dict:
    """Return counts of stored references for DM info."""
    npc_count = 0
    npc_pinned = 0
    for d in NPC_REFS.iterdir():
        if d.is_dir():
            npc_count += 1
            if (d / "pinned.png").exists():
                npc_pinned += 1

    loc_count = 0
    loc_pinned = 0
    for d in LOC_REFS.iterdir():
        if d.is_dir():
            loc_count += 1
            if (d / "pinned.png").exists():
                loc_pinned += 1

    return {
        "npc_refs": npc_count,
        "npc_pinned": npc_pinned,
        "location_refs": loc_count,
        "location_pinned": loc_pinned,
    }
