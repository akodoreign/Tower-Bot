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
from pathlib import Path
from typing import Optional

from src.log import logger

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
REFS_DIR = DOCS_DIR / "image_refs"
NPC_REFS = REFS_DIR / "npcs"
LOC_REFS = REFS_DIR / "locations"

# Ensure dirs exist at import time
for _d in (REFS_DIR, NPC_REFS, LOC_REFS):
    _d.mkdir(parents=True, exist_ok=True)

MAX_REFS = 3  # keep last 3 images per entity (plus optional pinned)

# Default denoising strength for img2img — 0.0 = exact copy, 1.0 = ignore reference
# 0.45 preserves core composition/colors while allowing prompt to steer details
NPC_DENOISE      = 0.45
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


def _save_ref(category_dir: Path, key: str, img_bytes: bytes) -> Path:
    """
    Save a new reference image, rotating older ones.
    ref_001.png = newest, ref_002.png = second newest, etc.
    Returns the path of the saved file.
    """
    d = _get_entity_dir(category_dir, key)

    # Rotate: delete oldest, shift others up
    oldest = d / f"ref_{MAX_REFS:03d}.png"
    if oldest.exists():
        oldest.unlink()

    for i in range(MAX_REFS - 1, 0, -1):
        src = d / f"ref_{i:03d}.png"
        dst = d / f"ref_{i + 1:03d}.png"
        if src.exists():
            src.rename(dst)

    # Save new as ref_001
    newest = d / "ref_001.png"
    newest.write_bytes(img_bytes)
    logger.info(f"🖼️ Saved ref image: {d.name}/ref_001.png ({len(img_bytes):,} bytes)")
    return newest


def _get_ref(category_dir: Path, key: str) -> Optional[bytes]:
    """
    Get the best reference image bytes.
    Priority: pinned.png > ref_001.png (newest) > None
    """
    d = category_dir / _slug(key)
    if not d.exists():
        return None

    # Check pinned first
    pinned = d / "pinned.png"
    if pinned.exists():
        return pinned.read_bytes()

    # Fall back to newest ref
    newest = d / "ref_001.png"
    if newest.exists():
        return newest.read_bytes()

    return None


def _pin_ref(category_dir: Path, key: str, img_bytes: bytes) -> Path:
    """Set a pinned canonical reference image."""
    d = _get_entity_dir(category_dir, key)
    pinned = d / "pinned.png"
    pinned.write_bytes(img_bytes)
    logger.info(f"📌 Pinned ref image: {d.name}/pinned.png ({len(img_bytes):,} bytes)")
    return pinned


def _has_ref(category_dir: Path, key: str) -> bool:
    """Check if any reference exists without loading the bytes."""
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

def save_npc_ref(name: str, img_bytes: bytes) -> Path:
    """Save a new NPC portrait reference."""
    return _save_ref(NPC_REFS, name, img_bytes)


def get_npc_ref(name: str) -> Optional[bytes]:
    """Get best NPC reference image bytes, or None."""
    return _get_ref(NPC_REFS, name)


def pin_npc_ref(name: str, img_bytes: bytes) -> Path:
    """Pin a canonical NPC reference."""
    return _pin_ref(NPC_REFS, name, img_bytes)


def has_npc_ref(name: str) -> bool:
    """Check if an NPC has any reference image."""
    return _has_ref(NPC_REFS, name)


# ---------------------------------------------------------------------------
# Location-specific API
# ---------------------------------------------------------------------------

def save_location_ref(location: str, img_bytes: bytes) -> Path:
    """Save a new location reference."""
    return _save_ref(LOC_REFS, location, img_bytes)


def get_location_ref(location: str) -> Optional[bytes]:
    """Get best location reference image bytes, or None."""
    return _get_ref(LOC_REFS, location)


def pin_location_ref(location: str, img_bytes: bytes) -> Path:
    """Pin a canonical location reference."""
    return _pin_ref(LOC_REFS, location, img_bytes)


def has_location_ref(location: str) -> bool:
    """Check if a location has any reference image."""
    return _has_ref(LOC_REFS, location)


# ---------------------------------------------------------------------------
# Payload conversion: txt2img → img2img
# ---------------------------------------------------------------------------

def to_img2img_payload(
    txt2img_payload: dict,
    ref_bytes: bytes,
    denoising_strength: float = 0.45,
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
        found_npcs = find_npc_in_text(text)
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
