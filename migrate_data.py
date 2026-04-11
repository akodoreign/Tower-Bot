"""
Phase 2: Data Migration Script
Migrates existing JSON/TXT files to MySQL database.
"""
import os
import json
import re
from datetime import datetime
from pathlib import Path

# Add src to path for db_api
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.db_api import db, raw_execute

BASE_DIR = Path(__file__).parent
CAMPAIGN_DOCS = BASE_DIR / "campaign_docs"

# Track migration progress
migration_log = []

def log(msg):
    print(msg)
    migration_log.append(msg)


def load_json(filepath):
    """Load JSON file safely."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"  ✗ Error loading {filepath}: {e}")
        return None


def migrate_npcs():
    """Migrate npc_roster.json to npcs table."""
    log("\n" + "="*50)
    log("Migrating: NPC Roster → npcs table")
    log("="*50)
    
    filepath = CAMPAIGN_DOCS / "npc_roster.json"
    if not filepath.exists():
        log("  ✗ npc_roster.json not found")
        return 0
    
    data = load_json(filepath)
    if not data:
        return 0
    
    count = 0
    for npc in data:
        try:
            # Map JSON fields to table columns
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
            
            # Parse dates
            arrival = None
            created_str = npc.get("created_at", "")
            if created_str:
                try:
                    arrival = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except:
                    pass
            
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
                npc.get("appearance", ""),  # Use appearance as description
                arrival,
                npc.get("status", "alive"),
                json.dumps(appearance_data)
            ))
            count += 1
            
        except Exception as e:
            log(f"  ✗ Error migrating NPC {npc.get('name', '?')}: {e}")
    
    log(f"  ✓ Migrated {count} NPCs")
    return count


def migrate_missions():
    """Migrate mission_memory.json to missions table."""
    log("\n" + "="*50)
    log("Migrating: Mission Memory → missions table")
    log("="*50)
    
    filepath = CAMPAIGN_DOCS / "mission_memory.json"
    if not filepath.exists():
        log("  ✗ mission_memory.json not found")
        return 0
    
    data = load_json(filepath)
    if not data:
        return 0
    
    count = 0
    for mission in data:
        try:
            # Parse dates
            posted_at = None
            expires_at = None
            
            if mission.get("posted_at"):
                try:
                    posted_at = datetime.fromisoformat(mission["posted_at"].replace("Z", "+00:00"))
                except:
                    pass
            
            if mission.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(mission["expires_at"].replace("Z", "+00:00"))
                except:
                    pass
            
            # Determine status
            status = "active"
            if mission.get("resolved"):
                status = "completed"
            elif expires_at and expires_at < datetime.now():
                status = "expired"
            
            # Extract reward EC from reward string
            reward_str = mission.get("reward", "0")
            reward_ec = 0
            ec_match = re.search(r"(\d+)\s*EC", reward_str)
            if ec_match:
                reward_ec = int(ec_match.group(1))
            
            query = """
                INSERT INTO missions (title, description, difficulty, faction, status, reward_ec, created_at, expires_at, message_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            raw_execute(query, (
                mission.get("title", "Untitled"),
                mission.get("body", ""),
                mission.get("tier", "local"),
                mission.get("faction", ""),
                status,
                reward_ec,
                posted_at,
                expires_at,
                str(mission.get("message_id", ""))
            ))
            count += 1
            
        except Exception as e:
            log(f"  ✗ Error migrating mission {mission.get('title', '?')}: {e}")
    
    log(f"  ✓ Migrated {count} missions")
    return count


def migrate_faction_reputation():
    """Migrate faction_reputation.json to faction_reputation table."""
    log("\n" + "="*50)
    log("Migrating: Faction Reputation → faction_reputation table")
    log("="*50)
    
    filepath = CAMPAIGN_DOCS / "faction_reputation.json"
    if not filepath.exists():
        log("  ✗ faction_reputation.json not found")
        return 0
    
    data = load_json(filepath)
    if not data:
        return 0
    
    count = 0
    for faction_name, rep_data in data.items():
        try:
            query = """
                INSERT INTO faction_reputation (faction_name, reputation_score, tier)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    reputation_score = VALUES(reputation_score),
                    tier = VALUES(tier)
            """
            
            raw_execute(query, (
                faction_name,
                rep_data.get("points", 0),
                rep_data.get("tier", "Neutral")
            ))
            count += 1
            
        except Exception as e:
            log(f"  ✗ Error migrating faction {faction_name}: {e}")
    
    log(f"  ✓ Migrated {count} faction reputations")
    return count


def migrate_news_memory():
    """Migrate news_memory.txt to news_entries table."""
    log("\n" + "="*50)
    log("Migrating: News Memory → news_entries table")
    log("="*50)
    
    filepath = CAMPAIGN_DOCS / "news_memory.txt"
    if not filepath.exists():
        log("  ✗ news_memory.txt not found")
        return 0
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        log(f"  ✗ Error reading file: {e}")
        return 0
    
    # Split by entry separator
    entries = content.split("---ENTRY---")
    
    count = 0
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        
        try:
            lines = entry.split("\n")
            if len(lines) < 2:
                continue
            
            # Parse timestamp from first line [2026-04-06 12:57 │ Tower: ...]
            timestamp_line = lines[0]
            timestamp = None
            ts_match = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", timestamp_line)
            if ts_match:
                try:
                    timestamp = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M")
                except:
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()
            
            # Get the content (rest of the lines)
            content_lines = lines[1:]
            body = "\n".join(content_lines).strip()
            
            # Extract headline (first significant line or marker)
            headline = body[:200] if body else "News Entry"
            
            # Determine category from content
            category = "general"
            if "TIA market" in body.lower():
                category = "market"
            elif "weather" in body.lower():
                category = "weather"
            elif "missing persons" in body.lower():
                category = "missing_persons"
            elif "TowerBay" in body:
                category = "towerbay"
            elif any(district in body for district in ["Docks", "Warrens", "Sanctum", "Markets", "Iron Maw", "Ash Ring"]):
                category = "district_news"
            
            query = """
                INSERT INTO news_entries (headline, body, category, posted_at)
                VALUES (%s, %s, %s, %s)
            """
            
            raw_execute(query, (headline, body, category, timestamp))
            count += 1
            
        except Exception as e:
            log(f"  ✗ Error migrating news entry: {e}")
    
    log(f"  ✓ Migrated {count} news entries")
    return count


def migrate_bounties():
    """Migrate bounty_board.json to bounties table."""
    log("\n" + "="*50)
    log("Migrating: Bounty Board → bounties table")
    log("="*50)
    
    filepath = CAMPAIGN_DOCS / "bounty_board.json"
    if not filepath.exists():
        log("  ✗ bounty_board.json not found (may be empty)")
        return 0
    
    data = load_json(filepath)
    if not data:
        return 0
    
    count = 0
    for bounty in data:
        try:
            query = """
                INSERT INTO bounties (title, target_type, target_name, reward_ec, status)
                VALUES (%s, %s, %s, %s, %s)
            """
            
            raw_execute(query, (
                bounty.get("title", "Untitled"),
                bounty.get("target_type", ""),
                bounty.get("target_name", ""),
                bounty.get("reward_ec", 0),
                bounty.get("status", "active")
            ))
            count += 1
            
        except Exception as e:
            log(f"  ✗ Error migrating bounty: {e}")
    
    log(f"  ✓ Migrated {count} bounties")
    return count


def migrate_weather():
    """Migrate dome_weather.json to weather_state table."""
    log("\n" + "="*50)
    log("Migrating: Dome Weather → weather_state table")
    log("="*50)
    
    filepath = CAMPAIGN_DOCS / "dome_weather.json"
    if not filepath.exists():
        log("  ✗ dome_weather.json not found")
        return 0
    
    data = load_json(filepath)
    if not data:
        return 0
    
    try:
        query = """
            UPDATE weather_state SET 
                current_weather = %s,
                temperature = %s,
                effects_json = %s
            WHERE id = 1
        """
        
        raw_execute(query, (
            data.get("current_weather", data.get("weather", "clear")),
            data.get("temperature", "moderate"),
            json.dumps(data)
        ))
        
        log(f"  ✓ Migrated weather state")
        return 1
        
    except Exception as e:
        log(f"  ✗ Error migrating weather: {e}")
        return 0


def migrate_economy():
    """Migrate ec_exchange.json to economy_state table."""
    log("\n" + "="*50)
    log("Migrating: EC Exchange → economy_state table")
    log("="*50)
    
    filepath = CAMPAIGN_DOCS / "ec_exchange.json"
    if not filepath.exists():
        log("  ✗ ec_exchange.json not found")
        return 0
    
    data = load_json(filepath)
    if not data:
        return 0
    
    try:
        query = """
            UPDATE economy_state SET 
                ec_to_kharma_rate = %s,
                trend = %s
            WHERE id = 1
        """
        
        raw_execute(query, (
            data.get("rate", data.get("ec_to_kharma_rate", 1.0)),
            data.get("trend", "stable")
        ))
        
        log(f"  ✓ Migrated economy state")
        return 1
        
    except Exception as e:
        log(f"  ✗ Error migrating economy: {e}")
        return 0


def migrate_rift_state():
    """Migrate rift_state.json to rift_state table."""
    log("\n" + "="*50)
    log("Migrating: Rift State → rift_state table")
    log("="*50)
    
    filepath = CAMPAIGN_DOCS / "rift_state.json"
    if not filepath.exists():
        log("  ✗ rift_state.json not found")
        return 0
    
    data = load_json(filepath)
    if not data:
        return 0
    
    try:
        query = """
            UPDATE rift_state SET 
                active = %s,
                intensity = %s,
                location = %s,
                effects_json = %s
            WHERE id = 1
        """
        
        raw_execute(query, (
            data.get("active", False),
            data.get("intensity", 0),
            data.get("location", ""),
            json.dumps(data)
        ))
        
        log(f"  ✓ Migrated rift state")
        return 1
        
    except Exception as e:
        log(f"  ✗ Error migrating rift state: {e}")
        return 0


def migrate_tia_market():
    """Migrate tia.json to tia_market table."""
    log("\n" + "="*50)
    log("Migrating: TIA Market → tia_market table")
    log("="*50)
    
    filepath = CAMPAIGN_DOCS / "tia.json"
    if not filepath.exists():
        log("  ✗ tia.json not found")
        return 0
    
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
                log(f"  ✗ Error migrating sector {sector_name}: {e}")
    
    log(f"  ✓ Migrated {count} TIA sectors")
    return count


def migrate_npc_appearances():
    """Migrate npc_appearances/*.json to npc_appearances table."""
    log("\n" + "="*50)
    log("Migrating: NPC Appearances → npc_appearances table")
    log("="*50)
    
    appearances_dir = CAMPAIGN_DOCS / "npc_appearances"
    if not appearances_dir.exists():
        log("  ✗ npc_appearances directory not found")
        return 0
    
    count = 0
    for filepath in appearances_dir.glob("*.json"):
        data = load_json(filepath)
        if not data:
            continue
        
        try:
            npc_name = filepath.stem  # filename without extension
            
            query = """
                INSERT INTO npc_appearances (npc_name, appearance_prompt, style)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    appearance_prompt = VALUES(appearance_prompt),
                    style = VALUES(style)
            """
            
            raw_execute(query, (
                data.get("name", npc_name),
                data.get("prompt", data.get("appearance_prompt", "")),
                data.get("style", "photorealistic")
            ))
            count += 1
            
        except Exception as e:
            log(f"  ✗ Error migrating appearance {filepath.name}: {e}")
    
    log(f"  ✓ Migrated {count} NPC appearances")
    return count


def migrate_party_profiles():
    """Migrate party_profiles/*.json to party_profiles table."""
    log("\n" + "="*50)
    log("Migrating: Party Profiles → party_profiles table")
    log("="*50)
    
    profiles_dir = CAMPAIGN_DOCS / "party_profiles"
    if not profiles_dir.exists():
        log("  ✗ party_profiles directory not found")
        return 0
    
    count = 0
    for filepath in profiles_dir.glob("*.json"):
        data = load_json(filepath)
        if not data:
            continue
        
        try:
            party_name = data.get("name", filepath.stem)
            
            query = """
                INSERT INTO party_profiles (party_name, members_json, reputation)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    members_json = VALUES(members_json),
                    reputation = VALUES(reputation)
            """
            
            raw_execute(query, (
                party_name,
                json.dumps(data.get("members", data)),
                data.get("reputation", 0)
            ))
            count += 1
            
        except Exception as e:
            log(f"  ✗ Error migrating party {filepath.name}: {e}")
    
    log(f"  ✓ Migrated {count} party profiles")
    return count


def run_migration():
    """Run all migrations."""
    print("="*60)
    print("PHASE 2: DATA MIGRATION")
    print("="*60)
    print(f"Source: {CAMPAIGN_DOCS}")
    print(f"Target: MySQL tower_bot database")
    
    total = 0
    
    # Run all migrations
    total += migrate_npcs()
    total += migrate_missions()
    total += migrate_faction_reputation()
    total += migrate_news_memory()
    total += migrate_bounties()
    total += migrate_weather()
    total += migrate_economy()
    total += migrate_rift_state()
    total += migrate_tia_market()
    total += migrate_npc_appearances()
    total += migrate_party_profiles()
    
    print("\n" + "="*60)
    print(f"MIGRATION COMPLETE: {total} records migrated")
    print("="*60)
    
    # Save migration log
    log_path = BASE_DIR / "logs" / "migration_log.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(migration_log))
    print(f"Log saved to: {log_path}")
    
    return total


if __name__ == "__main__":
    run_migration()
