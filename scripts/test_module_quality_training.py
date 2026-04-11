"""Test script for module quality training.

Run this manually to test the module quality self-learning system
without waiting for the 1-4 AM learning window.

Usage:
    cd C:\\Users\\akodoreign\\Desktop\\chatGPT-discord-bot
    python scripts\\test_module_quality_training.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.module_quality_trainer import study_module_quality
from src.log import logger


async def main():
    """Run one module quality training session."""
    print("=" * 60)
    print("MODULE QUALITY TRAINING TEST")
    print("=" * 60)
    print()
    print("This will:")
    print("  1. Generate a test mission (sandbox mode - no Discord)")
    print("  2. Compare it against professional module excerpts")
    print("  3. Identify quality gaps")
    print("  4. Generate prompt patches for improvement")
    print("  5. Save everything for DM review")
    print()
    print("Output locations:")
    print("  - Test modules: logs/learning/test_modules/")
    print("  - Quality journal: logs/learning/quality_journal.jsonl")
    print("  - Prompt patches: skills/module-quality/PATCHES.md")
    print()
    print("-" * 60)
    
    # Run the training
    result = await study_module_quality()
    
    print("-" * 60)
    
    if result:
        print()
        print("✅ Training complete! Skill summary:")
        print()
        print(result[:1500])  # First 1500 chars
        print()
        print("Check skills/module-quality/PATCHES.md for any generated patches.")
    else:
        print()
        print("❌ Training failed or no output generated.")
        print("Check the logs for errors.")
    
    print()
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
