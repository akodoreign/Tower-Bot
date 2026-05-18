"""
test_image_generator.py — Tests for battle map and encounter image generation.

Tests:
  - Tile generation parameter validation
  - Dungeon map stitching with various layouts
  - Image asset metadata creation
  - Image saving and directory management
  - Prompt engineering functions
  - Mock A1111 API interactions
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from PIL import Image
import io
import json

from src.mission_builder.image_generator import (
    TileGenerationParams,
    ImageAssetMetadata,
    generate_single_tile,
    generate_dungeon_tiles_for_rooms,
    stitch_dungeon_map,
    get_image_asset,
    generate_encounter_images,
    save_mission_images,
    craft_battle_map_prompt,
    craft_creature_prompt,
    craft_location_prompt,
    DEFAULT_TILE_WIDTH,
    DEFAULT_TILE_HEIGHT,
    MISSION_IMAGES_DIR,
)
from src.mission_builder.schemas import DungeonRoom


class TestTileGenerationParams:
    """Test parameter validation and construction."""

    def test_default_params(self):
        """Test TileGenerationParams with defaults."""
        params = TileGenerationParams(prompt="a dungeon")
        assert params.prompt == "a dungeon"
        assert params.width == DEFAULT_TILE_WIDTH
        assert params.height == DEFAULT_TILE_HEIGHT
        assert params.seed == -1
        assert params.cfg_scale == 7.0

    def test_custom_params(self):
        """Test TileGenerationParams with custom values."""
        params = TileGenerationParams(
            prompt="custom prompt",
            width=512,
            height=512,
            cfg_scale=12.0,
            steps=30,
        )
        assert params.width == 512
        assert params.height == 512
        assert params.cfg_scale == 12.0
        assert params.steps == 30


class TestImageAssetMetadata:
    """Test image asset metadata tracking."""

    def test_creation(self):
        """Test creating ImageAssetMetadata."""
        metadata = ImageAssetMetadata(
            filename="test.png",
            type="battle_map",
            size=(256, 256),
            seed=12345,
            prompt="test prompt",
        )
        assert metadata.filename == "test.png"
        assert metadata.type == "battle_map"
        assert metadata.size == (256, 256)
        assert metadata.seed == 12345


class TestGetImageAsset:
    """Test ImageAsset creation for mission JSON."""

    def test_basic_image_asset(self):
        """Test creating a basic image asset."""
        asset = get_image_asset(
            filename="map.png",
            type="battle_map",
        )
        assert asset["filename"] == "map.png"
        assert asset["type"] == "battle_map"
        assert asset["size"] == (DEFAULT_TILE_WIDTH, DEFAULT_TILE_HEIGHT)

    def test_image_asset_with_size(self):
        """Test creating image asset with custom size."""
        asset = get_image_asset(
            filename="large_map.png",
            type="battle_map",
            size=(512, 512),
            seed=999,
        )
        assert asset["size"] == (512, 512)
        assert asset["seed"] == 999

    def test_image_asset_prompt_truncation(self):
        """Test that long prompts are truncated."""
        long_prompt = "x" * 200
        asset = get_image_asset(
            filename="map.png",
            type="battle_map",
            prompt=long_prompt,
        )
        assert len(asset["prompt"]) <= 100


class TestGenerateSingleTile:
    """Test individual tile generation."""

    @pytest.mark.asyncio
    async def test_txt2img_generation(self):
        """Test txt2img tile generation (mock)."""
        params = TileGenerationParams(
            prompt="dungeon tile",
            use_reference=False,
        )

        # Create mock image
        mock_img = Image.new("RGB", (256, 256), color=(100, 100, 100))
        img_buffer = io.BytesIO()
        mock_img.save(img_buffer, format="PNG")
        img_base64 = __import__("base64").b64encode(img_buffer.getvalue()).decode()

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"images": [img_base64]})
            mock_response.raise_for_status = AsyncMock()
            
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await generate_single_tile(params)
            assert result is not None
            assert result.size == (256, 256)

    @pytest.mark.asyncio
    async def test_img2img_generation_with_reference(self):
        """Test img2img generation with reference image."""
        mock_img = Image.new("RGB", (256, 256), color=(100, 100, 100))
        img_buffer = io.BytesIO()
        mock_img.save(img_buffer, format="PNG")
        img_base64 = __import__("base64").b64encode(img_buffer.getvalue()).decode()

        params = TileGenerationParams(
            prompt="refined dungeon",
            use_reference=True,
            reference_base64=img_base64,
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"images": [img_base64]})
            mock_response.raise_for_status = AsyncMock()
            
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await generate_single_tile(params)
            assert result is not None

    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test handling of A1111 connection errors."""
        import httpx

        params = TileGenerationParams(prompt="test")

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection failed")
            )

            result = await generate_single_tile(params)
            assert result is None


class TestGenerateDungeonTiles:
    """Test generating tiles for multiple dungeon rooms."""

    @pytest.mark.asyncio
    async def test_generate_tiles_for_rooms(self):
        """Test generating tiles for multiple rooms in parallel."""
        rooms: list[DungeonRoom] = [
            {"name": "entrance", "description": "main entrance"},
            {"name": "corridor", "description": "long hallway"},
        ]

        mock_img = Image.new("RGB", (256, 256), color=(100, 100, 100))
        img_buffer = io.BytesIO()
        mock_img.save(img_buffer, format="PNG")
        img_base64 = __import__("base64").b64encode(img_buffer.getvalue()).decode()

        with patch("src.mission_builder.image_generator.generate_single_tile") as mock_gen:
            mock_gen.return_value = mock_img

            result = await generate_dungeon_tiles_for_rooms(rooms)
            assert "entrance" in result
            assert "corridor" in result
            assert result["entrance"] is not None
            assert result["corridor"] is not None


class TestStitchDungeonMap:
    """Test dungeon map stitching."""

    @pytest.mark.asyncio
    async def test_stitch_tiles_auto_layout(self):
        """Test stitching tiles with auto layout."""
        tiles = {
            "room1": Image.new("RGB", (256, 256), color=(100, 100, 100)),
            "room2": Image.new("RGB", (256, 256), color=(150, 150, 150)),
            "room3": Image.new("RGB", (256, 256), color=(200, 200, 200)),
        }

        result = await stitch_dungeon_map(tiles)
        assert result is not None
        # With 3 tiles and 4-per-row layout, we get 3 tiles in 1 row: 256*3 + 2 gaps
        assert result.size[0] >= 256 * 3
        assert result.size[1] >= 256

    @pytest.mark.asyncio
    async def test_stitch_tiles_custom_layout(self):
        """Test stitching with custom layout."""
        tiles = {
            "room1": Image.new("RGB", (256, 256), color=(100, 100, 100)),
            "room2": Image.new("RGB", (256, 256), color=(150, 150, 150)),
        }
        layout = [["room1", "room2"]]

        result = await stitch_dungeon_map(tiles, layout)
        assert result is not None
        # 2 tiles horizontally + 1 gap
        assert result.size[0] == 256 * 2 + 2

    @pytest.mark.asyncio
    async def test_stitch_empty_tiles(self):
        """Test stitching with no tiles."""
        result = await stitch_dungeon_map({})
        assert result is None


class TestPromptEngineering:
    """Test prompt crafting functions."""

    def test_battle_map_prompt(self):
        """Test battle map prompt generation."""
        room: DungeonRoom = {
            "name": "throne room",
            "description": "grand hall with raised throne",
            "hazards": ["acid pit", "spike trap"],
        }
        prompt = craft_battle_map_prompt(room, style="gothic dungeon")
        assert "throne room" in prompt
        assert "gothic dungeon" in prompt
        assert "grid lines" in prompt
        assert "top-down" in prompt

    def test_creature_prompt(self):
        """Test creature art prompt."""
        prompt = craft_creature_prompt("goblin", "goblin")
        assert "goblin" in prompt
        assert "D&D" in prompt
        assert "portrait" in prompt

    def test_location_prompt(self):
        """Test location/scene prompt."""
        prompt = craft_location_prompt("tavern", "bustling inn")
        assert "tavern" in prompt
        assert "bustling inn" in prompt
        assert "isometric" in prompt


class TestSaveMissionImages:
    """Test image saving and mission module updates."""

    @pytest.mark.asyncio
    async def test_save_single_image(self, tmp_path):
        """Test saving a single image."""
        # Create test image
        img = Image.new("RGB", (256, 256), color=(100, 100, 100))

        # Mock MISSION_IMAGES_DIR
        with patch("src.mission_builder.image_generator.MISSION_IMAGES_DIR", tmp_path):
            saved_paths, updated_module = await save_mission_images(
                mission_title="Test Mission",
                images={"test_map.png": img},
                mission_module=None,
            )

            assert "test_map.png" in saved_paths
            # Check that file was created
            mission_dir = tmp_path / "test_mission"
            assert mission_dir.exists()
            assert (mission_dir / "test_map.png").exists()

    @pytest.mark.asyncio
    async def test_save_images_with_mission_update(self, tmp_path):
        """Test saving images and updating mission module."""
        img = Image.new("RGB", (256, 256), color=(100, 100, 100))
        mission_module = {"title": "Test", "images": []}

        with patch("src.mission_builder.image_generator.MISSION_IMAGES_DIR", tmp_path):
            saved_paths, updated = await save_mission_images(
                mission_title="Test",
                images={"map.png": img},
                mission_module=mission_module,
            )

            assert len(updated["images"]) > 0
            assert updated["images"][0]["type"] in ["battle_map", "encounter_tile"]


class TestGenerateEncounterImages:
    """Test end-to-end encounter image generation."""

    @pytest.mark.asyncio
    async def test_generate_with_dungeon_rooms(self):
        """Test generating images for encounter with dungeon rooms."""
        rooms: list[DungeonRoom] = [
            {
                "name": "boss arena",
                "description": "cathedral-like chamber",
                "hazards": [],
            },
        ]

        mock_img = Image.new("RGB", (256, 256), color=(100, 100, 100))

        with patch(
            "src.mission_builder.image_generator.generate_dungeon_tiles_for_rooms"
        ) as mock_tiles:
            mock_tiles.return_value = {"boss arena": mock_img}

            with patch(
                "src.mission_builder.image_generator.stitch_dungeon_map"
            ) as mock_stitch:
                composite_img = Image.new("RGB", (512, 256))
                mock_stitch.return_value = composite_img

                result = await generate_encounter_images(
                    encounter_id="boss_fight",
                    encounter_data={},
                    dungeon_rooms=rooms,
                )

                assert "images_to_save" in result
                assert "encounter_update" in result


class TestIntegration:
    """Integration tests for image generation pipeline."""

    @pytest.mark.asyncio
    async def test_full_mission_image_pipeline(self, tmp_path):
        """Test complete mission image generation and saving."""
        # Create mock mission module
        mission_module = {
            "title": "Dungeon Descent",
            "acts": [
                {
                    "encounters": [
                        {
                            "name": "Goblin Ambush",
                            "rooms": [
                                {"name": "canyon", "description": "rocky terrain"}
                            ],
                        }
                    ]
                }
            ],
            "images": [],
        }

        # Create mock images
        images = {"battle_map_1.png": Image.new("RGB", (256, 256))}

        with patch("src.mission_builder.image_generator.MISSION_IMAGES_DIR", tmp_path):
            saved_paths, updated = await save_mission_images(
                "Dungeon Descent",
                images,
                mission_module,
            )

            assert len(saved_paths) > 0
            assert len(updated["images"]) > 0
            assert updated["title"] == "Dungeon Descent"
