#!/usr/bin/env python3
"""
Merge faction leaders into npc_roster.json
Run from project root: python merge_faction_leaders.py
"""

import json
from pathlib import Path

ROSTER_PATH = Path("campaign_docs/npc_roster.json")
LEADERS_PATH = Path("campaign_docs/faction_leaders_new.json")

def main():
    # Load existing roster
    print(f"Reading {ROSTER_PATH}...")
    with open(ROSTER_PATH, "r", encoding="utf-8") as f:
        roster = json.load(f)
    print(f"  Found {len(roster)} existing NPCs")
    
    # Load new faction leaders
    print(f"Reading {LEADERS_PATH}...")
    with open(LEADERS_PATH, "r", encoding="utf-8") as f:
        leaders = json.load(f)
    print(f"  Found {len(leaders)} faction leaders to add")
    
    # Check for duplicates
    existing_names = {npc["name"] for npc in roster}
    new_leaders = []
    for leader in leaders:
        if leader["name"] in existing_names:
            print(f"  SKIP: {leader['name']} already exists in roster")
        else:
            new_leaders.append(leader)
            print(f"  ADD: {leader['name']} ({leader['faction']})")
    
    if not new_leaders:
        print("\nNo new leaders to add!")
        return
    
    # Merge
    roster.extend(new_leaders)
    
    # Backup original
    backup_path = ROSTER_PATH.with_suffix(".json.bak")
    print(f"\nCreating backup at {backup_path}...")
    with open(ROSTER_PATH, "r", encoding="utf-8") as f:
        original = f.read()
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(original)
    
    # Write merged roster
    print(f"Writing merged roster to {ROSTER_PATH}...")
    with open(ROSTER_PATH, "w", encoding="utf-8") as f:
        json.dump(roster, f, indent=2, ensure_ascii=False)
    
    print(f"\nDone! Roster now has {len(roster)} NPCs (+{len(new_leaders)} faction leaders)")
    print(f"Backup saved to {backup_path}")

if __name__ == "__main__":
    main()
