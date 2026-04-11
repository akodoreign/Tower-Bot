#!/usr/bin/env python3
"""
test_news_agents.py — Test the new editorial agent system

Usage:
    python scripts/test_news_agents.py [--type TYPE]
    
    TYPE: news, gossip, sports, or random (default: random)
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test_agent(editor_type: str):
    """Test a specific editor agent."""
    from src.news_integration import generate_editorial_bulletin, EditorType
    
    print(f"\n{'='*60}")
    print(f"Testing {editor_type.upper()} editor")
    print('='*60)
    
    # Map string to enum
    type_map = {
        "news": EditorType.NEWS,
        "gossip": EditorType.GOSSIP,
        "sports": EditorType.SPORTS,
        "random": EditorType.RANDOM,
    }
    
    et = type_map.get(editor_type.lower(), EditorType.RANDOM)
    
    print(f"Generating bulletin (this may take 30-60 seconds)...")
    result = await generate_editorial_bulletin(editor_type=et)
    
    print(f"\n--- Result ---")
    print(f"Success: {result.success}")
    print(f"Editor: {result.editor_type.value}")
    print(f"Save to memory: {result.save_to_memory}")
    
    if result.error:
        print(f"Error: {result.error}")
    
    if result.success:
        print(f"\nHeadline: {result.headline}")
        print(f"\nPreview (3 lines):")
        print("-" * 40)
        print(result.preview)
        print("-" * 40)
        
        print(f"\nFull Content:")
        print("-" * 40)
        print(result.raw_content)
        print("-" * 40)
        
        if result.embed:
            print(f"\nEmbed Title: {result.embed.title}")
            print(f"Embed Color: {result.embed.color}")
        
        if result.view:
            print(f"View has {len(result.view.children)} button(s)")
    
    return result.success


async def test_all():
    """Test all three agent types."""
    types = ["news", "gossip", "sports"]
    results = []
    
    for t in types:
        success = await test_agent(t)
        results.append((t, success))
        await asyncio.sleep(2)  # Brief pause between tests
    
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    for t, success in results:
        status = "✅" if success else "❌"
        print(f"{status} {t.upper()}")


def main():
    parser = argparse.ArgumentParser(description="Test news editorial agents")
    parser.add_argument(
        "--type", "-t",
        choices=["news", "gossip", "sports", "random", "all"],
        default="random",
        help="Which editor type to test (default: random)",
    )
    args = parser.parse_args()
    
    if args.type == "all":
        asyncio.run(test_all())
    else:
        asyncio.run(test_agent(args.type))


if __name__ == "__main__":
    main()
