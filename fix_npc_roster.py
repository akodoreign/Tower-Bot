#!/usr/bin/env python3
"""
Fix npc_roster.json:
1. Remove duplicate keys in Gruum Boneshaper
2. Update 26 NPC locations to canonical gazetteer locations
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

# Location updates
LOCATION_UPDATES = {
    "Gurthok Ironhide": "Underbelly Warrens, The Midden settlement — mercenary, protects hidden family",
    "Zephyrus Sylphim, the Smokestorm Serpent": "Outer Wall, North Gate patrol command — leads perimeter security",
    "Arin Obsidianwhisper": "Outer Wall, The Fringe observation post — patrols the boundary wastes",
    "Nimue Silverpaw": "Guild Spires, Prospect's Rest inn — takes low-level jobs, secretly Thane's Cult",
    "Kip Stonefang": "Shantytown Heights, Saints' Refuge tunnels — messenger, spy (secretly Thane's Cult)",
    "Lysandra Stardust": "Neon Row, The Vice Quarter shadow office — spy, information broker",
    "Elysia Thornshadow": "Outer Wall, West Gate barracks — leads patrol teams from the Dusk Gate",
    "Grimbush Gizzlethorn": "Scrapworks, Saints' outpost near Patchwork Saints territory — scout, secretly Serpent Choir",
    "Sebastian Azrael": "Night Pits, Fighter's Row adjacent housing — F-Rank, dangerous jobs (secretly Thane's Cult)",
    "Voris Ironhammer": "Artisan Quarter, Scriptorium Quarter — transferred to Guild of Ashen Scrolls, studies ancient texts",
    "Cassius Argent-Heart": "Guild Spires, Gilded Halls command room — leads combat teams, seeks redemption",
    "Thoren Azurescale": "Guild Spires, Adventurers Guild Hall lower level — F-Rank, seeks recognition (secretly Thane's Cult)",
    "Seraphina Nightwatch": "Ember Ward, cramped apartment above The Laughing Skull tavern — E-Rank scout, escaped Thane's Cult",
    "Kyrus Ironscale": "Markets Infinite, Consortium Underhalls — negotiates deals, secret Saints member",
    "Nalus Thundertide": "Archive Row, Grand Archive Dome senior offices — leads research, hidden royal heritage",
    "Thalia Elenshade": "Shantytown Heights, hidden safe house — leads operations against Iron Fang",
    "Thyra Scalescar": "Night Pits, Fighter's Row adjacent — enforcer for Choir in gambling district",
    "Elias Whisperstep": "Guild Spires, Gilded Halls intelligence wing — covert operations, relic hunting",
    "Eolande Starfall": "Outer Wall, Captain Korin's Command annex — leads patrol squads",
    "Gruggar Grimshackle": "Underbelly Warrens, The Bone Market — smuggler stall, secretly Tower Authority informant",
    "Gurrek Ironheart": "Outer Wall, burnt patrol post near Southern Warrens access — watches the edge",
    "Lysander Elveshadow": "Scrapworks, Saints' patrol route lodging — night patrol, secretly former Argent Blade",
    "Zephyria Flamefingers": "Artisan Quarter, Scriptorium Quarter research wing — catalogues artifacts, studies Rifts",
    "Seraph Zephyrion": "Archive Row, Archive of Forgotten Histories wing — catalogues, seeks artifacts",
    "Rianna Elenshade-Ironhammer": "Grand Forum, FTA satellite office observation post — security systems, suspects Consortium",
    "Zara Ironspark": "Artisan Quarter, Scriptorium Quarter (Inkwell Alley lodging nearby) — researches forbidden texts"
}

def fix_gruum_boneshaper_raw(content: str) -> str:
    """Fix the duplicate keys in Gruum Boneshaper by removing the corrupted middle section."""
    # Pattern: Find the corrupted status field and the duplicate fields after it
    # The corruption looks like:
    #   "status": "alive — maintains Warden weapons and armor — the heart of the Warden's district",
    #   "motivation": "Despite...",  (DUPLICATE)
    #   "role": "As the head...",    (DUPLICATE)  
    #   "secret": "Unknown...",      (DUPLICATE)
    #   "relationships": "Gruum...", (DUPLICATE)
    #   "oracle_notes": "The Oracle...",(DUPLICATE)
    #   "status": "alive",           (CORRECT)
    
    # Find the Gruum Boneshaper entry
    gruum_pattern = r'("name":\s*"Gruum Boneshaper".*?"status":\s*)"alive\s*—[^"]+"\s*,\s*"motivation":\s*"[^"]*"\s*,\s*"role":\s*"[^"]*"\s*,\s*"secret":\s*"[^"]*"\s*,\s*"relationships":\s*"[^"]*"\s*,\s*"oracle_notes":\s*"[^"]*"\s*,\s*"status":\s*"alive"'
    
    # Replace with just the clean status
    replacement = r'\1"alive"'
    
    fixed = re.sub(gruum_pattern, replacement, content, flags=re.DOTALL)
    
    if fixed == content:
        print("WARNING: Could not find Gruum Boneshaper corruption pattern - may already be fixed or pattern changed")
    else:
        print("FIXED: Gruum Boneshaper duplicate fields removed")
    
    return fixed

def main():
    roster_path = Path(__file__).parent / "campaign_docs" / "npc_roster.json"
    
    if not roster_path.exists():
        print(f"ERROR: File not found: {roster_path}")
        return 1
    
    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = roster_path.parent / f"npc_roster_backup_{timestamp}.json"
    shutil.copy2(roster_path, backup_path)
    print(f"Backup created: {backup_path}")
    
    # Read raw content first to fix the corruption
    raw_content = roster_path.read_text(encoding='utf-8')
    
    # Fix the Gruum Boneshaper corruption in raw text
    fixed_content = fix_gruum_boneshaper_raw(raw_content)
    
    # Now parse the fixed JSON
    try:
        npcs = json.loads(fixed_content)
    except json.JSONDecodeError as e:
        print(f"ERROR: JSON parse failed after fix attempt: {e}")
        print("Trying to parse original file...")
        npcs = json.loads(raw_content)
    
    # Apply location updates
    updated_count = 0
    for npc in npcs:
        name = npc.get("name", "")
        if name in LOCATION_UPDATES:
            old_loc = npc.get("location", "")
            new_loc = LOCATION_UPDATES[name]
            if old_loc != new_loc:
                npc["location"] = new_loc
                updated_count += 1
                print(f"UPDATED: {name}")
                print(f"  FROM: {old_loc[:60]}...")
                print(f"  TO:   {new_loc[:60]}...")
        
        # Ensure Gruum Boneshaper has clean status
        if name == "Gruum Boneshaper":
            npc["status"] = "alive"
    
    # Write clean JSON
    roster_path.write_text(json.dumps(npcs, indent=2, ensure_ascii=False), encoding='utf-8')
    
    print(f"\n=== SUMMARY ===")
    print(f"Locations updated: {updated_count}")
    print(f"Total NPCs: {len(npcs)}")
    print(f"File written: {roster_path}")
    print(f"\nDon't forget to restart the bot!")
    
    return 0

if __name__ == "__main__":
    exit(main())
