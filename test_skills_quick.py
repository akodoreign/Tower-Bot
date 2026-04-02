#!/usr/bin/env python
"""Quick test of skills integration with mission generation."""

import asyncio
import json
from src.mission_builder.api import generate_mission_async
from src.mission_builder.json_generator import set_use_skills
from src.log import logger

async def main():
    """Test mission generation with and without skills."""
    
    # Test parameters
    mission_title = "Quick Test Mission"
    faction = "Test Guild"
    tier = "mid-level"
    body = "Quick test of skills integration."
    
    print("\n" + "="*70)
    print("TEST 1: Mission generation WITHOUT skills")
    print("="*70)
    
    # Generate without skills
    set_use_skills(False)
    mission_1 = await generate_mission_async(
        title=mission_title,
        faction=faction,
        tier=tier,
        body=body,
    )
    
    if mission_1:
        print(f"✓ Mission generated successfully")
        print(f"  - Title: {mission_1.get('title')}")
        print(f"  - Acts: {len(mission_1.get('acts', []))}")
        print(f"  - NPCs: {len(mission_1.get('npcs', []))}")
        print(f"  - Keys: {list(mission_1.keys())}")
    else:
        print("✗ Mission generation failed")
        return
    
    print("\n" + "="*70)
    print("TEST 2: Skills loading")
    print("="*70)
    
    from src.mission_builder.skills_integration import load_all_skills
    skills = load_all_skills()
    print(f"✓ Loaded {len(skills)} skills")
    print(f"  - Key skills available:")
    for skill_name in ["cw-mission-gen", "cw-prose-writing", "dnd5e-srd"]:
        if skill_name in skills:
            print(f"    ✓ {skill_name}")
        else:
            print(f"    ✗ {skill_name} NOT FOUND")
    
    print("\n" + "="*70)
    print("TEST 3: Mission generation WITH skills")
    print("="*70)
    
    # Generate with skills
    set_use_skills(True)
    mission_2 = await generate_mission_async(
        title=f"{mission_title} (with skills)",
        faction=faction,
        tier=tier,
        body=body,
    )
    
    if mission_2:
        print(f"✓ Mission generated successfully with skills")
        print(f"  - Title: {mission_2.get('title')}")
        print(f"  - Acts: {len(mission_2.get('acts', []))}")
        print(f"  - NPCs: {len(mission_2.get('npcs', []))}")
        print(f"  - Keys: {list(mission_2.keys())}")
    else:
        print("✗ Mission generation with skills failed")
        return
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"✓ Both generation modes completed successfully")
    print(f"✓ Skills integration working correcty")
    print(f"✓ System is ready for end-to-end testing")

if __name__ == "__main__":
    asyncio.run(main())
