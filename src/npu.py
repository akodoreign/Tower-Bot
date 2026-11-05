"""
npu.py — small models on the Intel NPU (OpenVINO), off the shared GPU.

The RTX 5070 is time-shared between Ollama and ComfyUI (src/gpu_queue.py) and
the CPU carries Ollama's MoE expert layers, so these jobs run on the NPU:

    TextEmbedder  bge-small-en-v1.5 — semantic search for tower_rag
    Clip          CLIP ViT-B/32     — checks generated images against intent

Models are ONNX files under NPU_MODELS_DIR (C:\\AI\\models\\npu). The NPU needs
fixed input shapes, so inputs are padded to one size. NPU_DEVICE picks the
device (default NPU, falling back to CPU). Everything here is optional:
`get_embedder()` / `get_clip()` return None when OpenVINO or the model files
are missing, and callers carry on without them.

Compiling for the NPU takes a few seconds, so never call the getters for the
first time on the event loop; warm them up from a worker thread.
"""

from __future__ import annotations

import io
import logging
import os
import threading
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

# A child of src.log so these lines reach the bot's log handler.
logger = logging.getLogger("src.log.npu")

_lock = threading.Lock()          # guards model loading
_embedder: Optional["TextEmbedder"] = None
_clip: Optional["Clip"] = None
_failed: set[str] = set()


def models_dir() -> Path:
    return Path(os.getenv("NPU_MODELS_DIR", r"C:\AI\models\npu"))


def _compile(path: Path, shapes: dict[str, list[int]]):
    import openvino as ov
    core = ov.Core()
    model = core.read_model(str(path))
    names = {i.get_any_name() for i in model.inputs}
    model.reshape({k: v for k, v in shapes.items() if k in names})
    wanted = os.getenv("NPU_DEVICE", "NPU")
    for device in dict.fromkeys([wanted, "CPU"]):
        if device not in core.available_devices:
            continue
        try:
            compiled = core.compile_model(model, device)
            logger.info("🧠 NPU: %s compiled on %s", path.parent.parent.name if path.parent.name == "onnx" else path.name, device)
            return compiled
        except Exception as exc:
            logger.warning("🧠 NPU: compiling %s on %s failed: %r", path.name, device, exc)
    raise RuntimeError(f"could not compile {path}")


class _Runner:
    """One compiled model with one infer request; calls are serialized."""

    def __init__(self, path: Path, shapes: dict[str, list[int]]):
        self._compiled = _compile(path, shapes)
        self._request = self._compiled.create_infer_request()
        self._inputs = {i.get_any_name() for i in self._compiled.inputs}
        self._call = threading.Lock()

    def __call__(self, feed: dict[str, np.ndarray]) -> np.ndarray:
        with self._call:
            self._request.infer({k: v for k, v in feed.items() if k in self._inputs})
            return self._request.get_output_tensor(0).data.copy()


def _normalize(v: np.ndarray) -> np.ndarray:
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


class TextEmbedder:
    """bge-small-en-v1.5: 384-dim normalized embeddings, 512 tokens max."""

    SEQ = 512
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, root: Path):
        from tokenizers import Tokenizer
        self._tok = Tokenizer.from_file(str(root / "tokenizer.json"))
        self._tok.enable_truncation(self.SEQ)
        self._tok.enable_padding(length=self.SEQ)
        shape = [1, self.SEQ]
        self._run = _Runner(root / "onnx" / "model.onnx",
                            {"input_ids": shape, "attention_mask": shape, "token_type_ids": shape})

    def embed(self, text: str, *, query: bool = False) -> np.ndarray:
        enc = self._tok.encode((self.QUERY_PREFIX + text) if query else text)
        ids = np.asarray([enc.ids], dtype=np.int64)
        mask = np.asarray([enc.attention_mask], dtype=np.int64)
        hidden = self._run({"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)})
        return _normalize(hidden[0, 0]).astype(np.float32)        # CLS token


class Clip:
    """CLIP ViT-B/32: image and caption embeddings in one 512-dim space."""

    SEQ = 77
    MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
    STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

    def __init__(self, root: Path):
        from tokenizers import Tokenizer
        self._tok = Tokenizer.from_file(str(root / "tokenizer.json"))
        self._tok.enable_truncation(self.SEQ)
        self._tok.enable_padding(length=self.SEQ, pad_id=49407, pad_token="<|endoftext|>")
        self._vision = _Runner(root / "onnx" / "vision_model.onnx", {"pixel_values": [1, 3, 224, 224]})
        self._text = _Runner(root / "onnx" / "text_model.onnx",
                             {"input_ids": [1, self.SEQ], "attention_mask": [1, self.SEQ]})

    def _pixels(self, png: bytes) -> np.ndarray:
        from PIL import Image
        with Image.open(io.BytesIO(png)) as img:
            img = img.convert("RGB")
            scale = 224 / min(img.size)
            img = img.resize((max(224, round(img.width * scale)), max(224, round(img.height * scale))),
                             Image.Resampling.BICUBIC)
            left, top = (img.width - 224) // 2, (img.height - 224) // 2
            arr = np.asarray(img.crop((left, top, left + 224, top + 224)), dtype=np.float32) / 255.0
        return ((arr - self.MEAN) / self.STD).transpose(2, 0, 1)[None]

    def image(self, png: bytes) -> np.ndarray:
        return _normalize(self._vision({"pixel_values": self._pixels(png)})[0])

    def texts(self, captions: Sequence[str]) -> np.ndarray:
        out = []
        for caption in captions:
            enc = self._tok.encode(caption)
            out.append(self._text({"input_ids": np.asarray([enc.ids], dtype=np.int64),
                                   "attention_mask": np.asarray([enc.attention_mask], dtype=np.int64)})[0])
        return _normalize(np.stack(out))


def _load(name: str, factory):
    if name in _failed:
        return None
    root = models_dir() / name
    if not root.exists():
        _failed.add(name)
        logger.info("🧠 NPU: %s not installed at %s; skipping", name, root)
        return None
    try:
        return factory(root)
    except Exception as exc:
        _failed.add(name)
        logger.warning("🧠 NPU: could not load %s: %r", name, exc)
        return None


def get_embedder() -> Optional[TextEmbedder]:
    global _embedder
    with _lock:
        if _embedder is None:
            _embedder = _load("bge-small-en-v1.5", TextEmbedder)
        return _embedder


def get_clip() -> Optional[Clip]:
    global _clip
    with _lock:
        if _clip is None:
            _clip = _load("clip-vit-base-patch32", Clip)
        return _clip
