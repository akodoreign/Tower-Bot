import base64
import io

import pytest
from PIL import Image

import src.comfy_client as comfy


@pytest.mark.parametrize("checkpoint, recipe", [
    ("Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors", "scene"),
    ("sd_waiIllustriousSDXL_v160", "anime"),
    ("flux1-dev-fp8.safetensors", "map"),
    ("sd/epicrealismXL_pureFix.safetensors", "map"),
    ("map", "map"),
    ("anime", "anime"),
])
def test_recipe_for_old_checkpoint_names(checkpoint, recipe, monkeypatch):
    monkeypatch.delenv("A1111_ANIME_MODEL", raising=False)
    assert comfy.recipe_for(checkpoint) == recipe


def test_recipe_for_blank_follows_image_style(monkeypatch):
    monkeypatch.setenv("IMAGE_STYLE", "anime")
    assert comfy.recipe_for("") == "anime"
    monkeypatch.setenv("IMAGE_STYLE", "photorealistic")
    assert comfy.recipe_for("") == "scene"


def test_txt2img_graph_strips_loras_and_renders_near_one_megapixel():
    graph, info = comfy.build_graph(
        {"prompt": "<lora:EnvyFluxDungeonMap01:0.8> detailed, map, dungeon", "width": 896, "height": 512,
         "steps": 45, "cfg_scale": 5, "seed": 7},
        "scene",
    )
    assert graph["5"]["inputs"]["text"] == "detailed, map, dungeon"
    assert graph["8"]["inputs"]["steps"] == 8          # recipe steps, not the old SDXL 45
    assert graph["8"]["inputs"]["seed"] == 7
    assert graph["8"]["inputs"]["denoise"] == 1.0
    assert info["width"] == 896 and info["height"] == 512
    assert info["render_width"] * info["render_height"] >= 0.8 * 1024 * 1024
    assert graph[comfy.OUT_NODE]["class_type"] == "StudioImageOut"
    assert "20" not in graph


def test_img2img_graph_uses_inline_source_and_denoise():
    graph, info = comfy.build_graph(
        {"prompt": "x", "init_images": ["QUJD"], "denoising_strength": 0.4, "width": 1024, "height": 1024},
        "map",
    )
    assert graph["20"] == {"class_type": "StudioImageIn", "inputs": {"image_b64": "QUJD"}}
    assert graph["8"]["inputs"]["latent_image"] == ["22", 0]
    assert graph["8"]["inputs"]["denoise"] == 0.4


def test_sdxl_recipe_keeps_cfg_in_sane_range():
    graph, _ = comfy.build_graph({"prompt": "x", "cfg_scale": 12, "steps": 80}, "anime")
    assert graph["1"]["class_type"] == "CheckpointLoaderSimple"
    assert graph["8"]["inputs"]["cfg"] == 8.0
    assert graph["8"]["inputs"]["steps"] == 36


def test_image_from_frame_handles_both_preview_formats():
    png = b"\x89PNG-data"
    plain = (1).to_bytes(4, "big") + (2).to_bytes(4, "big") + png
    meta = b'{"node_id": "99"}'
    with_meta = (4).to_bytes(4, "big") + len(meta).to_bytes(4, "big") + meta + png
    assert comfy._image_from_frame(plain) == png
    assert comfy._image_from_frame(with_meta) == png


def test_fit_to_request_center_crops_to_requested_size():
    buf = io.BytesIO()
    Image.new("RGB", (1344, 768), (10, 20, 30)).save(buf, format="PNG")
    out = comfy._fit_to_request(buf.getvalue(), 896, 512)
    assert Image.open(io.BytesIO(out)).size == (896, 512)


@pytest.mark.asyncio
async def test_generate_returns_a1111_shape(monkeypatch):
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1024)).save(buf, format="PNG")

    async def fake_run(graph, timeout):
        return [buf.getvalue()]

    monkeypatch.setattr(comfy, "_run_graph", fake_run)
    data = await comfy.generate({"prompt": "x", "width": 768, "height": 768}, label="t", checkpoint="scene")
    img = Image.open(io.BytesIO(base64.b64decode(data["images"][0])))
    assert img.size == (768, 768)
    assert '"recipe": "scene"' in data["info"]
