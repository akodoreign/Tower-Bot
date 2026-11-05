"""
image_check.py — CLIP sanity check of a finished render, on the NPU.

Each image is compared with a few short captions in CLIP's shared space:
the style the recipe should produce, the styles it should not, and two
failure looks (blank/corrupt, text or watermark). It also scores how well
the image matches its own prompt.

IMAGE_CHECK=1 (default) logs one line per image with the scores; nothing
else changes. IMAGE_CHECK_REROLL=1 lets comfy_client.generate() render a
failing image once more with a new seed. Leave re-rolling off until a few
days of logged scores show where the thresholds belong for these models.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from src import npu

logger = logging.getLogger("src.log.image_check")

STYLES = {
    "anime": "an anime style illustration",
    "photo": "a realistic photograph",
    "painting": "a detailed digital fantasy painting",
    "map": "a top-down tabletop battle map",
}
FAILURES = {
    "blank": "a blank, corrupted or glitched image",
    "text": "an image covered in text and a watermark",
}
# Which styles count as on-target for each recipe.
EXPECTED = {"anime": {"anime"}, "scene": {"photo", "painting"}, "map": {"map"}}

_QUALITY_TAGS = re.compile(
    r"\b(masterpiece|best quality|high quality|very aesthetic|absurdres|highres|ultra[- ]detailed|8k|4k|uhd)\b",
    re.IGNORECASE)

_caption_vecs: Optional[np.ndarray] = None
_caption_keys: list[str] = []


def enabled() -> bool:
    return os.getenv("IMAGE_CHECK", "1") != "0"


def reroll_enabled() -> bool:
    return enabled() and os.getenv("IMAGE_CHECK_REROLL", "0") == "1"


@dataclass
class Verdict:
    recipe: str
    style: str                      # most likely style caption
    style_ok: float                 # probability mass on the expected styles
    prompt_sim: float               # cosine(image, prompt); ~0.2-0.35 is a normal match
    flags: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        # "text" is logged but not judged: on 2026-11-04 it scored 0.6-0.9 on
        # ordinary portraits. Wrong style and blank renders were clear-cut.
        min_style = float(os.getenv("IMAGE_CHECK_MIN_STYLE", "0.35"))
        max_blank = float(os.getenv("IMAGE_CHECK_MAX_BLANK", "0.5"))
        return self.style_ok >= min_style and self.flags.get("blank", 0.0) <= max_blank

    def summary(self) -> str:
        flags = " ".join(f"{k}={v:.2f}" for k, v in self.flags.items())
        return (f"recipe={self.recipe} style={self.style} on-target={self.style_ok:.2f} "
                f"prompt_sim={self.prompt_sim:.3f} {flags} -> {'ok' if self.ok else 'FAIL'}")


def _captions(clip: npu.Clip) -> tuple[list[str], np.ndarray]:
    global _caption_vecs, _caption_keys
    if _caption_vecs is None:
        _caption_keys = list(STYLES) + list(FAILURES)
        _caption_vecs = clip.texts([STYLES.get(k) or FAILURES[k] for k in _caption_keys])
    return _caption_keys, _caption_vecs


def _clean(prompt: str) -> str:
    text = _QUALITY_TAGS.sub("", prompt or "")
    return re.sub(r"\s*,\s*(,\s*)+", ", ", text).strip(" ,")


def warm_up() -> bool:
    """Compile CLIP and embed the captions (seconds on first run); call from a thread."""
    clip = npu.get_clip()
    if clip is None:
        return False
    _captions(clip)
    return True


def check(png: bytes, prompt: str, recipe: str) -> Optional[Verdict]:
    """Score one image. Blocking (~30 ms on the NPU); returns None without CLIP."""
    clip = npu.get_clip()
    if clip is None or recipe not in EXPECTED:
        return None
    keys, caps = _captions(clip)
    img = clip.image(png)
    logits = 100.0 * (caps @ img)                       # CLIP's learned logit scale
    style_keys = list(STYLES)
    s = np.exp(logits[: len(style_keys)] - logits[: len(style_keys)].max())
    style_p = dict(zip(style_keys, s / s.sum()))
    # Each failure look is judged against the image's own best style caption.
    best_style = max(logits[: len(style_keys)])
    flags = {}
    for i, k in enumerate(keys[len(style_keys):], start=len(style_keys)):
        flags[k] = float(1.0 / (1.0 + np.exp(best_style - logits[i])))
    cleaned = _clean(prompt)
    prompt_sim = float(clip.texts([cleaned])[0] @ img) if cleaned else 0.0
    return Verdict(recipe=recipe, style=max(style_p, key=style_p.get),
                   style_ok=float(sum(style_p[k] for k in EXPECTED[recipe])),
                   prompt_sim=prompt_sim, flags=flags)
