"""
Fix schema issues found during migration and re-migrate failed data.
"""
import os
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.db_api import db, raw_execute, raw_query

BASE_DIR = Path(__file__).parent
CAMPAIGN_DOCS = BASE_DIR / "campaign_docs"


def fix_schema():
    """Fix schema issues discovered during migration."""
    print("="*60)
    print("FIXING SCHEMA ISSUES")
    print("="*60)
    
    fixes = [
        # Fix role column - make it TEXT instead of VARCHAR(100)
        ("ALTER TABLE npcs MODIFY COLUMN role TEXT", "npcs.role → TEXT"),
        
        # Fix location column too while we're at it
        ("ALTER TABLE npcs MODIFY COLUMN location TEXT", "npcs.location → TEXT"),
        
        # Fix status ENUM to include more values
        ("ALTER TABLE npcs MODIFY COLUMN status VARCHAR(50) DEFAULT 'alive'", "npcs.status → VARCHAR(50)"),
        
        # Fix TIA value column to handle larger numbers
        ("ALTER TABLE tia_market MODIFY COLUMN value DECIMAL(15,2) DEFAULT 100.00", "tia_market.value → DECIMAL(15,2)"),
    ]
    
    for sql, description in fixes:
        try:
            raw_execute(sql)
            print(f"  ✓ {description}")
        except Exception as e:
            if "Duplicate" in str(e) or "already" in str(e).lower():
                print(f"  - {description} (already done)")
            else:
                print(f"  ✗ {description}: {e}")


def load_json(filepath):
    """Load JSON file safely."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ✗ Error loading {filepath}: {e}")
        return None


def remigrate_npcs():
    """Re-migrate all NPCs with fixed schema."""
    print("\n" + "="*60)
    print("Re-migrating: NPC Roster → npcs table")
    print("="*60)
    
    # Clear existing NPCs first
    raw_execute("DELETE FROM npcs")
    print("  Cleared existing NPC data")
    
    filepath = CAMPAIGN_DOCS / "npc_roster.json"
    data = load_json(filepath)
    if not data:
        return 0
    
    count = 0
    errors = 0
    for npc in data:
        try:
            appearance_data = {
                "appearance": npc.get("appearance", ""),
                "species": npc.get("species", ""),
                "age": npc.get("age", ""),
                "rank": npc.get("rank", ""),
                "motivation": npc.get("motivation", ""),
                "secret": npc.get("secret", ""),
                "relationships": npc.get("relationships", ""),
                "oracle_notes": npc.get("oracle_notes", ""),
                "revealed_secrets": npc.get("revealed_secrets", []),
                "history": npc.get("history", [])
            }
            
            arrival = None
            created_str = npc.get("created_at", "")
            if created_str:
                try:
                    arrival = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except:
                    pass
            
            # Normalize status
            status = npc.get("status", "alive")
            if status not in ["alive", "dead", "missing"]:
                status = "alive"  # Default unknown statuses to alive
            
            query = """
                INSERT INTO npcs (name, faction, role, location, description, arrival_date, status, appearance_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    faction = VALUES(faction),
                    role = VALUES(role),
                    location = VALUES(location),
                    description = VALUES(description),
                    status = VALUES(status),
                    appearance_json = VALUES(appearance_json)
            """
            
            raw_execute(query, (
                npc.get("name", "Unknown"),
                npc.get("faction", ""),
                npc.get("role", ""),
                npc.get("location", ""),
                npc.get("appearance", ""),
                arrival,
                status,
                json.dumps(appearance_data)
            ))
            count += 1
            
        except Exception as e:
            print(f"  ✗ Error: {npc.get('name', '?')}: {e}")
            errors += 1
    
    print(f"  ✓ Migrated {count} NPCs ({errors} errors)")
    return count


def remigrate_rift_state():
    """Re-migrate rift state handling list format."""
    print("\n" + "="*60)
    print("Re-migrating: Rift State")
    print("="*60)
    
    filepath = CAMPAIGN_DOCS / "rift_state.json"
    data = load_json(filepath)
    if not data:
        return 0
    
    try:
        # Handle if it's a list
        if isinstance(data, list):
            if len(data) > 0:
                # Use the first/most recent rift state
                rift_data = data[0] if isinstance(data[0], dict) else {"effects": data}
            else:
                rift_data = {"active": False, "intensity": 0}
        else:
            rift_data = data
        
        query = """
            UPDATE rift_state SET 
                active = %s,
                intensity = %s,
                location = %s,
                effects_json = %s
            WHERE id = 1
        """
        
        raw_execute(query, (
            rift_data.get("active", False),
            rift_data.get("intensity", 0),
            rift_data.get("location", ""),
            json.dumps(rift_data)
        ))
        
        print(f"  ✓ Migrated rift state")
        return 1
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return 0


def remigrate_tia():
    """Re-migrate TIA sectors with fixed value column."""
    print("\n" + "="*60)
    print("Re-migrating: TIA Market")
    print("="*60)
    
    # Clear existing TIA data
    raw_execute("DELETE FROM tia_market")
    
    filepath = CAMPAIGN_DOCS / "tia.json"
    data = load_json(filepath)
    if not data:
        return 0
    
    count = 0
    sectors = data.get("sectors", data)
    
    if isinstance(sectors, dict):
        for sector_name, sector_data in sectors.items():
            try:
                value = sector_data if isinstance(sector_data, (int, float)) else sector_data.get("value", 100)
                trend = "stable"
                if isinstance(sector_data, dict):
                    trend = sector_data.get("trend", "stable")
                
                # Cap extremely large values
                if value > 999999999999:
                    value = 999999999999
                
                query = """
                    INSERT INTO tia_market (sector, value, trend)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        value = VALUES(value),
                        trend = VALUES(trend)
                """
                
                raw_execute(query, (sector_name, value, trend))
                count += 1
                
            except Exception as e:
                print(f"  ✗ Error: sector {sector_name}: {e}")
    
    print(f"  ✓ Migrated {count} TIA sectors")
    return count


def verify_migration():
    """Verify final migration counts."""
    print("\n" + "="*60)
    print("VERIFICATION")
    print("="*60)
    
    tables = [
        ("npcs", "SELECT COUNT(*) as c FROM npcs"),
        ("missions", "SELECT COUNT(*) as c FROM missions"),
        ("bounties", "SELECT COUNT(*) as c FROM bounties"),
        ("news_entries", "SELECT COUNT(*) as c FROM news_entries"),
        ("faction_reputation", "SELECT COUNT(*) as c FROM faction_reputation"),
        ("npc_appearances", "SELECT COUNT(*) as c FROM npc_appearances"),
        ("party_profiles", "SELECT COUNT(*) as c FROM party_profiles"),
        ("tia_market", "SELECT COUNT(*) as c FROM tia_market"),
    ]
    
    total = 0
    for table, query in tables:
        try:
            result = raw_query(query)
            count = result[0]["c"] if result else 0
            print(f"  {table}: {count} records")
            total += count
        except Exception as e:
            print(f"  {table}: Error - {e}")
    
    print(f"\n  TOTAL: {total} records in database")
    return total


def main():
    print("="*60)
    print("MIGRATION FIX SCRIPT")
    print("="*60)
    
    fix_schema()
    remigrate_npcs()
    remigrate_rift_state()
    remigrate_tia()
    verify_migration()
    
    print("\n" + "="*60)
    print("FIX COMPLETE!")
    print("="*60)


if __name__ == "__main__":
    main()
