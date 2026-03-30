#!/usr/bin/env python3
"""
Test script for mission_builder package.
Run from project root: python test_mission_builder.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

print("=" * 60)
print("Testing mission_builder package imports")
print("=" * 60)

def test_imports():
    """Test all module imports."""
    errors = []
    
    # Test individual modules
    modules = [
        ("locations", "src.mission_builder.locations"),
        ("leads", "src.mission_builder.leads"),
        ("encounters", "src.mission_builder.encounters"),
        ("npcs", "src.mission_builder.npcs"),
        ("rewards", "src.mission_builder.rewards"),
        ("docx_builder", "src.mission_builder.docx_builder"),
        ("__init__ (orchestrator)", "src.mission_builder"),
    ]
    
    for name, module_path in modules:
        try:
            __import__(module_path)
            print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            errors.append((name, e))
    
    return errors


def test_compatibility_wrapper():
    """Test the backward-compatibility wrapper."""
    print("\nTesting compatibility wrapper (mission_module_gen.py)...")
    
    try:
        from src.mission_module_gen import (
            generate_module,
            post_module_to_channel,
            gather_context,
            get_cr,
            get_max_pc_level,
        )
        print("  ✓ All exports available from mission_module_gen")
        return []
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        return [("compatibility_wrapper", e)]


def test_key_functions():
    """Test key functions work."""
    print("\nTesting key functions...")
    errors = []
    
    # Test locations
    try:
        from src.mission_builder.locations import (
            load_gazetteer,
            find_location_for_mission,
        )
        gaz = load_gazetteer()
        loc, info = find_location_for_mission(faction="Mercantile Collective", tier="standard")
        print(f"  ✓ find_location_for_mission() → {loc}")
    except Exception as e:
        print(f"  ✗ locations functions: {e}")
        errors.append(("locations", e))
    
    # Test encounters
    try:
        from src.mission_builder.encounters import get_cr, get_max_pc_level
        max_lvl = get_max_pc_level()
        cr = get_cr("standard")
        print(f"  ✓ get_cr('standard') → CR {cr} (max PC level: {max_lvl})")
    except Exception as e:
        print(f"  ✗ encounters functions: {e}")
        errors.append(("encounters", e))
    
    # Test leads
    try:
        from src.mission_builder.leads import generate_investigation_leads
        leads = generate_investigation_leads(
            faction="Ironclad Guild",
            tier="investigation",
            mission_type="investigation",
            count=2,
        )
        print(f"  ✓ generate_investigation_leads() → {len(leads)} leads")
    except Exception as e:
        print(f"  ✗ leads functions: {e}")
        errors.append(("leads", e))
    
    # Test NPCs
    try:
        from src.mission_builder.npcs import get_relevant_npcs, format_npc_block
        npcs = get_relevant_npcs("Circle of the Eclipse")
        block = format_npc_block(npcs)
        print(f"  ✓ get_relevant_npcs() → {len(npcs)} NPCs")
    except Exception as e:
        print(f"  ✗ npcs functions: {e}")
        errors.append(("npcs", e))
    
    # Test rewards
    try:
        from src.mission_builder.rewards import calculate_gold_reward, build_loot_table
        gold = calculate_gold_reward("major")
        loot = build_loot_table(cr=8, tier="major")
        print(f"  ✓ calculate_gold_reward('major') → {gold[0]}-{gold[1]} gp")
    except Exception as e:
        print(f"  ✗ rewards functions: {e}")
        errors.append(("rewards", e))
    
    return errors


def main():
    all_errors = []
    
    all_errors.extend(test_imports())
    all_errors.extend(test_compatibility_wrapper())
    all_errors.extend(test_key_functions())
    
    print("\n" + "=" * 60)
    if all_errors:
        print(f"❌ FAILED: {len(all_errors)} error(s)")
        for name, err in all_errors:
            print(f"   - {name}: {err}")
        sys.exit(1)
    else:
        print("✅ ALL TESTS PASSED")
        print("\nThe mission_builder package is ready to use.")
        print("Next steps:")
        print("  1. Start the bot: python main.py")
        print("  2. Test a mission claim in Discord")
        print("  3. Verify the .docx output in generated_modules/")
        sys.exit(0)


if __name__ == "__main__":
    main()
