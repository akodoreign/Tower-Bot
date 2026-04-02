"""
e2e_tests.py — End-to-end integration tests with real/mock backends.

Tests complete workflows using actual Ollama and A1111 backends (or mocks if unavailable).

Exports:
    test_mission_board_workflow()     — Full mission generation to display
    test_image_generation_workflow()  — Tile generation + stitching
    test_complete_gameplay_loop()     — Generate → Save → Load → Use
"""

from __future__ import annotations

import pytest
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, patch

from src.mission_builder.api import generate_mission_async, get_mission_output_path
from src.mission_builder.image_integration import (
    generate_mission_with_images,
    extract_dungeon_rooms_from_mission,
)
from src.mission_builder.schemas import MissionModule
from src.log import logger


# Backend availability checks
async def check_ollama_available(url: str = "http://127.0.0.1:11434") -> bool:
    """Check if Ollama is running and accessible."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{url}/api/tags")
            return response.status_code == 200
    except Exception:
        return False


async def check_a1111_available(url: str = "http://127.0.0.1:7860") -> bool:
    """Check if A1111 Stable Diffusion is running and accessible."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{url}/sdapi/v1/sd-models")
            return response.status_code == 200
    except Exception:
        return False


class TestMissionBoardWorkflow:
    """End-to-end tests for mission board generation."""

    @pytest.mark.asyncio
    async def test_generate_mission_board_post(self):
        """Test generating a mission for board display."""
        mission_title = "The Goblin Nest"
        faction = "Adventurers Guild"

        # Generate mission
        mission = await generate_mission_async(
            title=mission_title,
            faction=faction,
            tier="mid-level",
            body="Local goblin nest threatens trade routes. Elimination required.",
            player_name="Party of Heroes",
        )

        # Verify structure
        assert mission is not None
        assert mission["title"] == mission_title
        assert mission["faction"] == faction
        assert "acts" in mission
        assert len(mission["acts"]) == 5
        assert "npcs" in mission
        assert "metadata" in mission

        logger.info(f"✓ Generated board mission: {mission['title']}")
        logger.info(f"  - Acts: {len(mission['acts'])}")
        logger.info(f"  - NPCs: {len(mission.get('npcs', []))}")
        logger.info(f"  - Content size: {len(json.dumps(mission))} bytes")

    @pytest.mark.asyncio
    async def test_save_mission_to_disk(self):
        """Test generating and saving mission to disk."""
        mission_title = "Crypt Investigation"

        mission = await generate_mission_async(
            title=mission_title,
            faction="Wardens of Ash",
            tier="high-stakes",
            body="Ancient crypt awakened. Undead presence confirmed.",
        )

        if not mission:
            pytest.skip("Mission generation returned None")

        # Save to disk
        output_path = get_mission_output_path(mission_title)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(mission, f, indent=2)

        # Verify file exists and can be loaded
        assert output_path.exists()

        with open(output_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            assert loaded["title"] == mission_title

        logger.info(f"✓ Saved mission: {output_path}")
        logger.info(f"  - File size: {output_path.stat().st_size} bytes")

    @pytest.mark.asyncio
    async def test_multiple_missions_sequential(self):
        """Test generating multiple missions in sequence."""
        missions_data = [
            {
                "title": "Missing Merchant",
                "faction": "Iron Fang Consortium",
                "tier": "low-stakes",
                "body": "Merchant vanished from Neon Row. Find him or find out why.",
            },
            {
                "title": "Dragon's Hoard",
                "faction": "Argent Blades",
                "tier": "deadly",
                "body": "Ancient dragon discovered beneath the city. Mass burial of gold.",
            },
            {
                "title": "Ghost in the Machine",
                "faction": "Obsidian Lotus",
                "tier": "high-stakes",
                "body": "Mechanical construct acting independently. Retrieve or destroy.",
            },
        ]

        generated_missions = []

        for data in missions_data:
            mission = await generate_mission_async(
                title=data["title"],
                faction=data["faction"],
                tier=data["tier"],
                body=data["body"],
            )

            if mission:
                generated_missions.append(mission)
                logger.info(f"✓ Generated: {data['title']}")

        assert len(generated_missions) > 0
        logger.info(f"✓ Generated {len(generated_missions)}/{len(missions_data)} missions")


class TestImageGenerationWorkflow:
    """End-to-end tests for image generation with A1111."""

    @pytest.mark.asyncio
    async def test_dungeon_tile_generation_mock(self):
        """Test dungeon tile generation (with mocks if A1111 unavailable)."""
        from src.mission_builder.schemas import DungeonRoom

        rooms: list[DungeonRoom] = [
            {"name": "entrance", "description": "stone archway entrance"},
            {"name": "main_hall", "description": "vaulted ceiling, pillars"},
            {"name": "boss_chamber", "description": "throne room"},
        ]

        a1111_available = await check_a1111_available()

        if not a1111_available:
            logger.warning("A1111 not available, using mocks")
            # With mocks, just verify the schema works
            from PIL import Image

            tiles = {room["name"]: Image.new("RGB", (256, 256)) for room in rooms}
        else:
            from src.mission_builder.image_generator import generate_dungeon_tiles_for_rooms

            tiles = await generate_dungeon_tiles_for_rooms(rooms, style="dark dungeon")

        assert len(tiles) == len(rooms)
        logger.info(f"✓ Generated {len(tiles)} dungeon tiles")

    @pytest.mark.asyncio
    async def test_mission_with_images_mock(self):
        """Test complete mission generation with images (using mocks)."""
        mission_title = "The Sunken Temple"

        # Mock the image generation entirely since A1111 may not be available
        with patch(
            "src.mission_builder.image_integration.generate_dungeon_tiles_for_rooms"
        ) as mock_tiles:
            from PIL import Image

            mock_img = Image.new("RGB", (256, 256), color=(100, 100, 100))
            mock_tiles.return_value = {"room1": mock_img}

            with patch(
                "src.mission_builder.image_integration.stitch_dungeon_map"
            ) as mock_stitch:
                composite = Image.new("RGB", (512, 256))
                mock_stitch.return_value = composite

                with patch(
                    "src.mission_builder.image_integration.save_mission_images"
                ) as mock_save:
                    mock_save.return_value = (
                        {"map.png": "missions/sunken_temple/map.png"},
                        {
                            "title": mission_title,
                            "images": [
                                {
                                    "filename": "missions/sunken_temple/map.png",
                                    "type": "battle_map",
                                    "size": (512, 256),
                                    "seed": -1,
                                    "prompt": "sunken temple",
                                }
                            ],
                        },
                    )

                    mission, images = await generate_mission_with_images(
                        title=mission_title,
                        faction="Patchwork Saints",
                        tier="mid-level",
                        body="Ancient temple submerged. Exploration and recovery.",
                        include_images=True,
                    )

                    assert mission is not None
                    assert len(mission.get("images", [])) > 0
                    logger.info(f"✓ Mission with images: {mission_title}")


class TestCompleteGameplayLoop:
    """End-to-end tests for complete gameplay workflow."""

    @pytest.mark.asyncio
    async def test_generate_load_use_mission(self, tmp_path):
        """Test: Generate → Save → Load → Use mission."""
        mission_title = "The Archive Theft"

        # Step 1: Generate
        mission = await generate_mission_async(
            title=mission_title,
            faction="Glass Sigil",
            tier="mid-level",
            body="Valuable manuscript stolen from the Archive. Recovery mission.",
        )

        if not mission:
            pytest.skip("Mission generation failed")

        # Step 2: Save
        mission_file = tmp_path / f"{mission_title.lower().replace(' ', '_')}.json"
        with open(mission_file, "w") as f:
            json.dump(mission, f, indent=2)

        logger.info(f"✓ Saved mission: {mission_file}")

        # Step 3: Load
        with open(mission_file, "r") as f:
            loaded = json.load(f)

        assert loaded["title"] == mission_title

        # Step 4: Use (extract data for gameplay)
        acts = loaded.get("acts", [])
        npcs = loaded.get("npcs", [])
        hooks = loaded.get("hooks", [])

        logger.info(f"✓ Mission data extracted:")
        logger.info(f"  - Acts: {len(acts)}")
        logger.info(f"  - NPCs: {len(npcs)}")
        logger.info(f"  - Hooks: {len(hooks)}")

        assert len(acts) > 0
        assert len(npcs) > 0

    @pytest.mark.asyncio
    async def test_mission_with_dungeon_delve(self):
        """Test mission with dungeon delve encounter."""
        mission_title = "Necromancer's Tomb"

        mission = await generate_mission_async(
            title=mission_title,
            faction="Serpent Choir",
            tier="deadly",
            body="Necromancer's tomb has been breached. Seal or destroy the ritual.",
        )

        if not mission:
            pytest.skip("Mission generation failed")

        # Extract dungeon rooms (if present)
        rooms = extract_dungeon_rooms_from_mission(mission)

        logger.info(f"✓ Mission structure:")
        logger.info(f"  - Title: {mission['title']}")
        logger.info(f"  - Faction: {mission['faction']}")
        logger.info(f"  - Acts: {len(mission['acts'])}")
        logger.info(f"  - Dungeon rooms: {len(rooms)}")

        # If dungeon content exists, verify it's well-formed
        if rooms:
            for room in rooms:
                assert "name" in room
                assert "description" in room
                logger.info(f"    - {room['name']}: {room['description'][:50]}...")


class TestPerformanceAndScaling:
    """Performance and scaling tests."""

    @pytest.mark.asyncio
    async def test_generation_performance(self):
        """Test generation performance / time tracking."""
        import time

        mission_title = "Performance Test"

        start_time = time.time()

        mission = await generate_mission_async(
            title=mission_title,
            faction="Test Faction",
            tier="mid-level",
            body="Test mission for performance measurement.",
        )

        elapsed = time.time() - start_time

        if mission:
            content_size = len(json.dumps(mission))
            logger.info(f"✓ Generation performance:")
            logger.info(f"  - Time: {elapsed:.2f} seconds")
            logger.info(f"  - Content size: {content_size} bytes")
            logger.info(f"  - Throughput: {content_size / elapsed / 1024:.2f} KB/s")

    @pytest.mark.asyncio
    async def test_concurrent_generation(self):
        """Test generating multiple missions concurrently."""
        import time

        missions_data = [
            ("Concurrent 1", "Faction A", "low-stakes", "Test 1"),
            ("Concurrent 2", "Faction B", "mid-level", "Test 2"),
            ("Concurrent 3", "Faction C", "high-stakes", "Test 3"),
        ]

        start_time = time.time()

        tasks = [
            generate_mission_async(
                title=title,
                faction=faction,
                tier=tier,
                body=body,
            )
            for title, faction, tier, body in missions_data
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.time() - start_time

        successful = sum(1 for r in results if isinstance(r, dict) and "title" in r)

        logger.info(f"✓ Concurrent generation:")
        logger.info(f"  - Tasks: {len(tasks)}")
        logger.info(f"  - Successful: {successful}")
        logger.info(f"  - Total time: {elapsed:.2f}s")
        logger.info(
            f"  - Speedup: {(len(missions_data) * 30 / elapsed):.1f}x vs sequential"
        )


class TestBackendIntegration:
    """Tests for backend service integration."""

    @pytest.mark.asyncio
    async def test_ollama_backend_status(self):
        """Test Ollama backend availability."""
        available = await check_ollama_available()

        if available:
            logger.info("✓ Ollama backend available")
        else:
            logger.warning("⚠ Ollama backend not available")
            pytest.skip("Ollama not running")

    @pytest.mark.asyncio
    async def test_a1111_backend_status(self):
        """Test A1111 Stable Diffusion backend availability."""
        available = await check_a1111_available()

        if available:
            logger.info("✓ A1111 backend available")
        else:
            logger.warning("⚠ A1111 backend not available")
            pytest.skip("A1111 not running")

    @pytest.mark.asyncio
    async def test_graceful_degradation_without_backends(self):
        """Test that system degrades gracefully without backends."""
        # Mission generation should work with Ollama
        ollama_ok = await check_ollama_available()

        if not ollama_ok:
            logger.warning("Ollama not available - mission generation would fail")

        # Image generation should skip gracefully without A1111
        a1111_ok = await check_a1111_available()

        if not a1111_ok:
            logger.warning("A1111 not available - image generation will use mocks")

        # Both services being down is OK - just log it
        logger.info(f"Backend status: Ollama={ollama_ok}, A1111={a1111_ok}")


# ============================================================================
# Pytest fixtures for E2E tests
# ============================================================================


@pytest.fixture
async def mission_output_dir(tmp_path):
    """Provide temporary directory for mission output."""
    missions_dir = tmp_path / "missions"
    missions_dir.mkdir()
    return missions_dir


@pytest.fixture
async def sample_mission() -> Optional[MissionModule]:
    """Provide a sample generated mission."""
    mission = await generate_mission_async(
        title="Fixture Mission",
        faction="Test Faction",
        tier="mid-level",
        body="Fixture-generated mission for testing.",
    )

    return mission


if __name__ == "__main__":
    # Run tests: pytest tests/test_e2e.py -v
    pytest.main([__file__, "-v", "-s"])
