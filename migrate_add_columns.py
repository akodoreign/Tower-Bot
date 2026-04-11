"""
Database Migration: Add Missing Columns (2026-04-09)

Run this script to add missing columns to the database tables.
Fixes errors:
- NPC save error: Unknown column 'data_json'
- TowerBay item save error: Unknown column 'auction_json'
- Arena save error: Unknown column 'champion_name'
- Calendar save event error: Unknown column 'emoji'

Usage:
    python migrate_add_columns.py
"""

import os
import mysql.connector
from mysql.connector import Error

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "Claude"),
    "password": os.getenv("MYSQL_PASSWORD", "WXdCPJmeDfaQALaktzF6!"),
    "database": os.getenv("MYSQL_DB", "tower_bot"),
}


MIGRATIONS = [
    # Add data_json to npcs table
    {
        "name": "Add data_json to npcs",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'tower_bot' AND TABLE_NAME = 'npcs' AND COLUMN_NAME = 'data_json'",
        "sql": "ALTER TABLE npcs ADD COLUMN data_json JSON AFTER appearance_json"
    },
    
    # Add auction_json to towerbay_auctions table
    {
        "name": "Add auction_json to towerbay_auctions",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'tower_bot' AND TABLE_NAME = 'towerbay_auctions' AND COLUMN_NAME = 'auction_json'",
        "sql": "ALTER TABLE towerbay_auctions ADD COLUMN auction_json JSON AFTER status"
    },
    
    # Modify tia_market table to have expected columns
    {
        "name": "Add sector_name to tia_market",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'tower_bot' AND TABLE_NAME = 'tia_market' AND COLUMN_NAME = 'sector_name'",
        "sql": "ALTER TABLE tia_market ADD COLUMN sector_name VARCHAR(100) AFTER id"
    },
    {
        "name": "Add value_json to tia_market",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'tower_bot' AND TABLE_NAME = 'tia_market' AND COLUMN_NAME = 'value_json'",
        "sql": "ALTER TABLE tia_market ADD COLUMN value_json JSON AFTER sector_name"
    },
    {
        "name": "Add state_json to tia_market",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'tower_bot' AND TABLE_NAME = 'tia_market' AND COLUMN_NAME = 'state_json'",
        "sql": "ALTER TABLE tia_market ADD COLUMN state_json JSON AFTER value_json"
    },
    {
        "name": "Add last_updated to tia_market",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'tower_bot' AND TABLE_NAME = 'tia_market' AND COLUMN_NAME = 'last_updated'",
        "sql": "ALTER TABLE tia_market ADD COLUMN last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
    },
    
    # Add champion_name to arena_seasons
    {
        "name": "Add champion_name to arena_seasons",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'tower_bot' AND TABLE_NAME = 'arena_seasons' AND COLUMN_NAME = 'champion_name'",
        "sql": "ALTER TABLE arena_seasons ADD COLUMN champion_name VARCHAR(255) AFTER season_number"
    },
    
    # Add emoji to faction_events
    {
        "name": "Add emoji to faction_events",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'tower_bot' AND TABLE_NAME = 'faction_events' AND COLUMN_NAME = 'emoji'",
        "sql": "ALTER TABLE faction_events ADD COLUMN emoji VARCHAR(50) AFTER event_type"
    },
    
    # Create global_state table if it doesn't exist (for TIA cooldown tracking)
    {
        "name": "Create global_state table",
        "check": "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'tower_bot' AND TABLE_NAME = 'global_state'",
        "sql": """
            CREATE TABLE global_state (
                id INT AUTO_INCREMENT PRIMARY KEY,
                state_key VARCHAR(100) UNIQUE NOT NULL,
                state_value JSON,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_key(state_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    },
]


def run_migrations():
    """Run all pending migrations."""
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        
        print("=" * 60)
        print("Database Migration: Add Missing Columns")
        print("=" * 60)
        print()
        
        applied = 0
        skipped = 0
        
        for migration in MIGRATIONS:
            name = migration["name"]
            check_sql = migration["check"]
            alter_sql = migration["sql"]
            
            # Check if already exists
            cursor.execute(check_sql)
            result = cursor.fetchone()
            
            if result:
                print(f"⏭️  SKIP: {name} (already exists)")
                skipped += 1
            else:
                print(f"🔧 APPLY: {name}")
                try:
                    cursor.execute(alter_sql)
                    conn.commit()
                    print(f"   ✅ Success")
                    applied += 1
                except Error as e:
                    print(f"   ❌ Error: {e}")
        
        print()
        print("=" * 60)
        print(f"Migration complete: {applied} applied, {skipped} skipped")
        print("=" * 60)
        
        cursor.close()
        conn.close()
        
    except Error as e:
        print(f"❌ Database connection error: {e}")
        return False
    
    return True


if __name__ == "__main__":
    run_migrations()
