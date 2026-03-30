#!/usr/bin/env python3
"""
merge_faction_leaders.py — Adds missing faction leaders to npc_roster.json

Run this script from the project root:
    python scripts/merge_faction_leaders.py

This will:
1. Read campaign_docs/faction_leaders_to_add.json
2. Read campaign_docs/npc_roster.json
3. Check for duplicates by name
4. Append new leaders to the roster
5. Write the updated roster back
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "campaign_docs"

LEADERS_FILE = DOCS_DIR / "faction_leaders_to_add.json"
ROSTER_FILE = DOCS_DIR / "npc_roster.json"
BACKUP_FILE = DOCS_DIR / "npc_roster_backup_before_leaders.json"


def main():
    print("=" * 60)
    print("Faction Leaders Merge Script")
    print("=" * 60)
    
    # Check files exist
    if not LEADERS_FILE.exists():
        print(f"ERROR: Leaders file not found: {LEADERS_FILE}")
        return False
    
    if not ROSTER_FILE.exists():
        print(f"ERROR: Roster file not found: {ROSTER_FILE}")
        return False
    
    # Load files
    print(f"\nLoading leaders from: {LEADERS_FILE}")
    with open(LEADERS_FILE, "r", encoding="utf-8") as f:
        leaders = json.load(f)
    print(f"  Found {len(leaders)} faction leaders to add")
    
    print(f"\nLoading roster from: {ROSTER_FILE}")
    with open(ROSTER_FILE, "r", encoding="utf-8") as f:
        roster = json.load(f)
    print(f"  Found {len(roster)} existing NPCs")
    
    # Get existing names (lowercase for comparison)
    existing_names = {npc.get("name", "").lower() for npc in roster}
    
    # Check for duplicates and add new leaders
    added = []
    skipped = []
    
    for leader in leaders:
        name = leader.get("name", "Unknown")
        name_lower = name.lower()
        
        if name_lower in existing_names:
            skipped.append(name)
            print(f"  SKIP: {name} (already exists)")
        else:
            roster.append(leader)
            added.append(name)
            print(f"  ADD:  {name} ({leader.get('faction', 'Unknown')})")
    
    if not added:
        print("\nNo new leaders to add. All already exist in roster.")
        return True
    
    # Create backup
    print(f"\nCreating backup: {BACKUP_FILE}")
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        # Read original file to preserve exact formatting
        with open(ROSTER_FILE, "r", encoding="utf-8") as orig:
            f.write(orig.read())
    
    # Write updated roster
    print(f"Writing updated roster: {ROSTER_FILE}")
    with open(ROSTER_FILE, "w", encoding="utf-8") as f:
        json.dump(roster, f, indent=2, ensure_ascii=False)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Added:   {len(added)} faction leaders")
    for name in added:
        print(f"           - {name}")
    print(f"  Skipped: {len(skipped)} (already existed)")
    for name in skipped:
        print(f"           - {name}")
    print(f"  Total:   {len(roster)} NPCs in roster")
    print(f"\nBackup saved to: {BACKUP_FILE}")
    print("Done!")
    
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
