#!/usr/bin/env python3
"""
Quick test script for dungeon delve generation.

Run: python test_dungeon_delve.py

Options:
  --no-tiles    Skip A1111 tile generation (faster, placeholder map)
  --no-llm      Skip LLM room descriptions (faster, fallback text)
  --save        Save outputs to generated_modules/
"""

import os
import sys
import asyncio
import argparse
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s -> %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

async def main():
    parser = argparse.ArgumentParser(description="Test dungeon delve generation")
    parser.add_argument("--no-tiles", action="store_true", help="Skip A1111 tile generation")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM room descriptions")
    parser.add_argument("--save", action="store_true", help="Save outputs to disk")
    parser.add_argument("--location", type=str, default=None, help="Specific location name")
    parser.add_argument("--level", type=int, default=None, help="Override party level (auto-detects if not set)")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("🏰 DUNGEON DELVE TEST")
    print("="*60)

    # Import after path setup
    from src.mission_builder.dungeon_delve import (
        generate_dungeon_delve,
        save_dungeon_delve,
        get_max_pc_level,
        get_cr,
    )

    # Show what we're testing
    detected_level = get_max_pc_level()
    test_level = args.level if args.level else (detected_level if detected_level > 0 else 5)
    test_cr = get_cr("dungeon-delve")
    
    print(f"\n📊 Party Level Detection:")
    print(f"   • Detected from character_memory.txt: {detected_level if detected_level > 0 else 'None found'}")
    print(f"   • Using level: {test_level}")
    print(f"   • Calculated CR: {test_cr}")
    
    print(f"\n⚙️  Generation Options:")
    print(f"   • Generate A1111 tiles: {not args.no_tiles}")
    print(f"   • Use LLM descriptions: {not args.no_llm}")
    print(f"   • Location: {args.location or 'Auto-select'}")
    print(f"   • Save outputs: {args.save}")
    
    print("\n" + "-"*60)
    print("🚀 Starting generation...\n")

    try:
        result = await generate_dungeon_delve(
            location_name=args.location,
            party_level=args.level,  # None = auto-detect
            use_llm=not args.no_llm,
            generate_tiles=not args.no_tiles,
            faction="Adventurers Guild",
        )
        
        print("\n" + "-"*60)
        print("✅ GENERATION COMPLETE!")
        print("-"*60)
        
        # Summary
        module = result["module_data"]
        layout = result["layout"]
        
        print(f"\n📜 Module: {module['title']}")
        print(f"   • Rooms: {module['room_count']}")
        print(f"   • Encounters: {module['encounter_count']}")
        print(f"   • CR: {module['cr']}")
        print(f"   • Party Level: {module['player_level']}")
        print(f"   • Layout: {layout.name}")
        print(f"   • Aesthetic: {layout.aesthetic}")
        
        print(f"\n🗺️  Map:")
        print(f"   • Composite map: {len(result['composite_map']):,} bytes")
        print(f"   • Room tiles: {len(result['room_tiles'])} generated")
        
        print(f"\n🏠 Rooms:")
        for room_id, info in result["room_info"].items():
            enc = "⚔️" if info.get("encounter") else "  "
            trp = "⚠️" if info.get("traps") else "  "
            trs = "💰" if info.get("treasure") else "  "
            print(f"   {room_id}: {info.get('name', '?'):30s} {enc}{trp}{trs}")
        
        if args.save:
            print("\n💾 Saving to disk...")
            saved = await save_dungeon_delve(result)
            print(f"   • Saved to: {saved['composite_map'].parent}")
            for key, path in saved.items():
                print(f"   • {key}: {path.name}")
        else:
            print("\n💡 Tip: Run with --save to write outputs to disk")
        
        print("\n" + "="*60)
        print("🏰 TEST COMPLETE")
        print("="*60 + "\n")
        
        return result
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    asyncio.run(main())
