"""
SQL Refactor Setup Script
Run this to test connectivity and set up the foundation.
"""
import asyncio
import httpx
import json
import os
import sys
import re

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OLLAMA_CHAT_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_GEN_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3-8b-slim:latest"

MYSQL_USER = "Claude"
MYSQL_PASSWORD = "WXdCPJmeDfaQALaktzF6!"
MYSQL_HOST = "localhost"
MYSQL_DB = "tower_bot"


def strip_thinking(text: str) -> str:
    """Strip <think>...</think> tags from Qwen3 output."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return text.strip()


async def test_ollama():
    """Test Ollama connectivity using generate endpoint."""
    print("\n" + "="*60)
    print("PHASE 0.1: Testing Ollama Connectivity")
    print("="*60)
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # First, check if Ollama is running at all
            try:
                check = await client.get("http://localhost:11434/api/tags")
                models = check.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                print(f"Available models: {model_names}")
                
                if not any("qwen3" in m.lower() for m in model_names):
                    print("⚠ qwen3-8b-slim not found. Available models:", model_names)
                    if model_names:
                        print(f"  Will try with: {model_names[0]}")
            except Exception as e:
                print(f"Could not list models: {e}")
            
            # Use generate endpoint with /no_think in prompt
            print("Testing with generate endpoint...")
            resp = await client.post(OLLAMA_GEN_URL, json={
                "model": OLLAMA_MODEL,
                "prompt": "Respond with only the word READY. /no_think",
                "stream": False,
                "options": {"num_predict": 50}
            })
            data = resp.json()
            raw_response = data.get("response", "").strip()
            response = strip_thinking(raw_response)
            
            print(f"Raw response: '{raw_response[:100]}'")
            print(f"Cleaned response: '{response}'")
            
            if response or raw_response:
                print("✓ Ollama is responding!")
                return True
            else:
                # Try chat endpoint as fallback
                print("Trying chat endpoint...")
                resp2 = await client.post(OLLAMA_CHAT_URL, json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": "Say READY /no_think"}],
                    "stream": False,
                    "options": {"num_predict": 50}
                })
                data2 = resp2.json()
                raw2 = data2.get("message", {}).get("content", "").strip()
                print(f"Chat endpoint raw: '{raw2[:100] if raw2 else 'empty'}'")
                if raw2:
                    print("✓ Ollama chat endpoint working!")
                    return True
                    
            print("✗ Both endpoints returned empty")
            return False
            
    except Exception as e:
        print(f"✗ Ollama connection failed: {e}")
        return False


def test_mysql():
    """Test MySQL connectivity."""
    print("\n" + "="*60)
    print("PHASE 0.2: Testing MySQL Connectivity")
    print("="*60)
    
    try:
        import mysql.connector
        print("✓ mysql-connector-python is installed")
    except ImportError:
        print("✗ mysql-connector-python not installed")
        print("  Run: pip install mysql-connector-python")
        return False
    
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        print(f"✓ MySQL connected to '{MYSQL_DB}' as '{MYSQL_USER}'!")
        return True
        
    except mysql.connector.Error as e:
        print(f"✗ MySQL connection failed: {e}")
        if "Access denied" in str(e) or "1044" in str(e):
            print("\n  Run first: python mysql_setup.py")
            print("  (This will set up database and permissions using root)")
        return False


async def prompt_ollama(prompt: str, max_tokens: int = 2000) -> str:
    """Send a prompt to Ollama using generate endpoint."""
    full_prompt = prompt + "\n\n/no_think"
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(OLLAMA_GEN_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": full_prompt,
            "stream": False,
            "options": {"num_predict": max_tokens}
        })
        data = resp.json()
        raw = data.get("response", "").strip()
        return strip_thinking(raw)


async def generate_database_schema():
    """Have Ollama generate the database schema."""
    print("\n" + "="*60)
    print("PHASE 1.1: Generating Database Schema (via Ollama)")
    print("="*60)
    
    prompt = """You are a database architect. Generate MySQL CREATE TABLE statements.

Output SQL only, no explanations. Start with: USE tower_bot;

Create these 23 tables:

1. npcs (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) UNIQUE, faction VARCHAR(100), role VARCHAR(100), location VARCHAR(255), description TEXT, arrival_date DATETIME, status ENUM('alive','dead','missing') DEFAULT 'alive', appearance_json JSON, INDEX idx_faction(faction), INDEX idx_status(status))

2. missions (id INT AUTO_INCREMENT PRIMARY KEY, title VARCHAR(255), description TEXT, difficulty VARCHAR(50), faction VARCHAR(100), npc_giver VARCHAR(255), status ENUM('active','claimed','completed','expired','failed') DEFAULT 'active', reward_ec INT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, expires_at DATETIME, claimed_by VARCHAR(255), completed_at DATETIME, INDEX idx_status(status))

3. bounties (id INT AUTO_INCREMENT PRIMARY KEY, title VARCHAR(255), target_type VARCHAR(50), target_name VARCHAR(255), reward_ec INT, status VARCHAR(50) DEFAULT 'active', created_at DATETIME DEFAULT CURRENT_TIMESTAMP, claimed_by VARCHAR(255))

4. news_entries (id INT AUTO_INCREMENT PRIMARY KEY, headline VARCHAR(500), body TEXT, category VARCHAR(100), posted_at DATETIME DEFAULT CURRENT_TIMESTAMP, news_type VARCHAR(100), INDEX idx_posted(posted_at))

5. player_characters (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255), class_name VARCHAR(100), species VARCHAR(100), player_name VARCHAR(255), player_discord_id VARCHAR(50), profile_json JSON, UNIQUE KEY unique_name(name))

6. faction_reputation (id INT AUTO_INCREMENT PRIMARY KEY, faction_name VARCHAR(100) UNIQUE, reputation_score INT DEFAULT 0, tier VARCHAR(50), last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

7. weather_state (id INT AUTO_INCREMENT PRIMARY KEY, current_weather VARCHAR(100), temperature VARCHAR(50), effects_json JSON, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

8. economy_state (id INT AUTO_INCREMENT PRIMARY KEY, ec_to_kharma_rate DECIMAL(10,4), trend VARCHAR(50), updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

9. arena_seasons (id INT AUTO_INCREMENT PRIMARY KEY, season_number INT, champions_json JSON, standings_json JSON, started_at DATETIME)

10. faction_events (id INT AUTO_INCREMENT PRIMARY KEY, faction VARCHAR(100), event_type VARCHAR(100), event_date DATETIME, description TEXT, INDEX idx_date(event_date))

11. missing_persons (id INT AUTO_INCREMENT PRIMARY KEY, person_name VARCHAR(255), last_seen_location VARCHAR(255), reported_at DATETIME DEFAULT CURRENT_TIMESTAMP, status VARCHAR(50) DEFAULT 'missing', found_at DATETIME)

12. rift_state (id INT AUTO_INCREMENT PRIMARY KEY, active BOOLEAN DEFAULT FALSE, intensity INT, location VARCHAR(255), effects_json JSON, started_at DATETIME)

13. tia_market (id INT AUTO_INCREMENT PRIMARY KEY, sector VARCHAR(100) UNIQUE, value DECIMAL(10,2), trend VARCHAR(50), updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)

14. towerbay_auctions (id INT AUTO_INCREMENT PRIMARY KEY, item_name VARCHAR(255), seller_id VARCHAR(100), current_bid INT, buy_now_price INT, expires_at DATETIME, status VARCHAR(50) DEFAULT 'active')

15. player_listings (id INT AUTO_INCREMENT PRIMARY KEY, player_id VARCHAR(100), item_name VARCHAR(255), asking_price INT, status VARCHAR(50) DEFAULT 'active', created_at DATETIME DEFAULT CURRENT_TIMESTAMP)

16. npc_appearances (id INT AUTO_INCREMENT PRIMARY KEY, npc_name VARCHAR(255) UNIQUE, appearance_prompt TEXT, style VARCHAR(50), generated_at DATETIME DEFAULT CURRENT_TIMESTAMP)

17. party_profiles (id INT AUTO_INCREMENT PRIMARY KEY, party_name VARCHAR(255) UNIQUE, members_json JSON, reputation INT DEFAULT 0, formed_at DATETIME)

18. image_refs (id INT AUTO_INCREMENT PRIMARY KEY, entity_type VARCHAR(50), entity_name VARCHAR(255), image_path VARCHAR(500), ref_count INT DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, INDEX idx_entity(entity_type, entity_name))

19. personal_missions (id INT AUTO_INCREMENT PRIMARY KEY, character_name VARCHAR(255), mission_data_json JSON, status VARCHAR(50) DEFAULT 'active', assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP)

20. resurrection_queue (id INT AUTO_INCREMENT PRIMARY KEY, npc_name VARCHAR(255), died_at DATETIME, resurrect_at DATETIME)

21. news_types (id INT AUTO_INCREMENT PRIMARY KEY, type_name VARCHAR(100) UNIQUE, template TEXT, weight DECIMAL(5,2) DEFAULT 1.0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)

22. mission_types (id INT AUTO_INCREMENT PRIMARY KEY, type_name VARCHAR(100) UNIQUE, template TEXT, difficulty_range VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)

23. lifecycle_events (id INT AUTO_INCREMENT PRIMARY KEY, event_type VARCHAR(100), npc_name VARCHAR(255), event_data_json JSON, occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP, INDEX idx_occurred(occurred_at))

Use ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci for all tables."""

    print("Prompting Ollama for schema generation... (this may take 1-2 minutes)")
    schema_sql = await prompt_ollama(prompt, max_tokens=8000)
    
    # If Ollama gives us nothing or garbage, use the fallback schema
    if not schema_sql or len(schema_sql) < 500 or "CREATE TABLE" not in schema_sql.upper():
        print("⚠ Ollama output insufficient, using pre-built schema...")
        schema_sql = generate_fallback_schema()
    
    # Clean up
    if "```sql" in schema_sql:
        schema_sql = schema_sql.split("```sql")[1].split("```")[0]
    elif "```" in schema_sql:
        parts = schema_sql.split("```")
        if len(parts) > 1:
            schema_sql = parts[1]
    
    if not schema_sql.strip().upper().startswith("USE"):
        schema_sql = "USE tower_bot;\n\n" + schema_sql
    
    schema_path = os.path.join(os.path.dirname(__file__), "database_schema.sql")
    with open(schema_path, "w", encoding="utf-8") as f:
        f.write(schema_sql)
    
    print(f"✓ Schema saved to: {schema_path}")
    print(f"  Length: {len(schema_sql)} characters")
    print("\nPreview (first 2000 chars):")
    print("-" * 40)
    print(schema_sql[:2000])
    print("-" * 40)
    
    return schema_sql


def generate_fallback_schema() -> str:
    """Fallback schema if Ollama fails."""
    return """USE tower_bot;

-- NPCs table
CREATE TABLE IF NOT EXISTS npcs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    faction VARCHAR(100),
    role VARCHAR(100),
    location VARCHAR(255),
    description TEXT,
    arrival_date DATETIME,
    status ENUM('alive','dead','missing') DEFAULT 'alive',
    appearance_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_faction(faction),
    INDEX idx_status(status),
    INDEX idx_location(location)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Missions table
CREATE TABLE IF NOT EXISTS missions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    difficulty VARCHAR(50),
    faction VARCHAR(100),
    npc_giver VARCHAR(255),
    status ENUM('active','claimed','completed','expired','failed') DEFAULT 'active',
    reward_ec INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,
    claimed_by VARCHAR(255),
    completed_at DATETIME,
    message_id VARCHAR(50),
    INDEX idx_status(status),
    INDEX idx_faction(faction)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bounties table
CREATE TABLE IF NOT EXISTS bounties (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    target_type VARCHAR(50),
    target_name VARCHAR(255),
    reward_ec INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    claimed_by VARCHAR(255),
    INDEX idx_status(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- News entries table
CREATE TABLE IF NOT EXISTS news_entries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    headline VARCHAR(500) NOT NULL,
    body TEXT,
    category VARCHAR(100),
    posted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    news_type VARCHAR(100),
    message_id VARCHAR(50),
    INDEX idx_posted(posted_at DESC),
    INDEX idx_category(category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Player characters table
CREATE TABLE IF NOT EXISTS player_characters (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    class_name VARCHAR(100),
    species VARCHAR(100),
    player_name VARCHAR(255),
    player_discord_id VARCHAR(50),
    profile_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_player(player_discord_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Faction reputation table
CREATE TABLE IF NOT EXISTS faction_reputation (
    id INT AUTO_INCREMENT PRIMARY KEY,
    faction_name VARCHAR(100) UNIQUE NOT NULL,
    reputation_score INT DEFAULT 0,
    tier VARCHAR(50),
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Weather state table
CREATE TABLE IF NOT EXISTS weather_state (
    id INT AUTO_INCREMENT PRIMARY KEY,
    current_weather VARCHAR(100),
    temperature VARCHAR(50),
    effects_json JSON,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Economy state table
CREATE TABLE IF NOT EXISTS economy_state (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ec_to_kharma_rate DECIMAL(10,4) DEFAULT 1.0,
    trend VARCHAR(50),
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Arena seasons table
CREATE TABLE IF NOT EXISTS arena_seasons (
    id INT AUTO_INCREMENT PRIMARY KEY,
    season_number INT,
    champions_json JSON,
    standings_json JSON,
    started_at DATETIME,
    ended_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Faction events table
CREATE TABLE IF NOT EXISTS faction_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    faction VARCHAR(100),
    event_type VARCHAR(100),
    event_date DATETIME,
    description TEXT,
    INDEX idx_date(event_date),
    INDEX idx_faction(faction)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Missing persons table
CREATE TABLE IF NOT EXISTS missing_persons (
    id INT AUTO_INCREMENT PRIMARY KEY,
    person_name VARCHAR(255) NOT NULL,
    last_seen_location VARCHAR(255),
    reported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'missing',
    found_at DATETIME,
    INDEX idx_status(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Rift state table
CREATE TABLE IF NOT EXISTS rift_state (
    id INT AUTO_INCREMENT PRIMARY KEY,
    active BOOLEAN DEFAULT FALSE,
    intensity INT DEFAULT 0,
    location VARCHAR(255),
    effects_json JSON,
    started_at DATETIME,
    ended_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TIA market table
CREATE TABLE IF NOT EXISTS tia_market (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sector VARCHAR(100) UNIQUE NOT NULL,
    value DECIMAL(10,2) DEFAULT 100.00,
    trend VARCHAR(50),
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TowerBay auctions table
CREATE TABLE IF NOT EXISTS towerbay_auctions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    item_name VARCHAR(255) NOT NULL,
    seller_id VARCHAR(100),
    seller_name VARCHAR(255),
    current_bid INT DEFAULT 0,
    buy_now_price INT,
    expires_at DATETIME,
    status VARCHAR(50) DEFAULT 'active',
    winner_id VARCHAR(100),
    INDEX idx_status(status),
    INDEX idx_expires(expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Player listings table
CREATE TABLE IF NOT EXISTS player_listings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    player_id VARCHAR(100),
    player_name VARCHAR(255),
    item_name VARCHAR(255) NOT NULL,
    asking_price INT,
    status VARCHAR(50) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_status(status),
    INDEX idx_player(player_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- NPC appearances table
CREATE TABLE IF NOT EXISTS npc_appearances (
    id INT AUTO_INCREMENT PRIMARY KEY,
    npc_name VARCHAR(255) UNIQUE NOT NULL,
    appearance_prompt TEXT,
    style VARCHAR(50),
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Party profiles table
CREATE TABLE IF NOT EXISTS party_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    party_name VARCHAR(255) UNIQUE NOT NULL,
    members_json JSON,
    reputation INT DEFAULT 0,
    formed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'active'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Image refs table
CREATE TABLE IF NOT EXISTS image_refs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,
    entity_name VARCHAR(255) NOT NULL,
    image_path VARCHAR(500),
    ref_count INT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_entity(entity_type, entity_name),
    INDEX idx_entity(entity_type, entity_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Personal missions table
CREATE TABLE IF NOT EXISTS personal_missions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    character_name VARCHAR(255) NOT NULL,
    mission_data_json JSON,
    status VARCHAR(50) DEFAULT 'active',
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    INDEX idx_character(character_name),
    INDEX idx_status(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Resurrection queue table
CREATE TABLE IF NOT EXISTS resurrection_queue (
    id INT AUTO_INCREMENT PRIMARY KEY,
    npc_name VARCHAR(255) NOT NULL,
    died_at DATETIME,
    resurrect_at DATETIME,
    status VARCHAR(50) DEFAULT 'pending',
    INDEX idx_resurrect(resurrect_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- News types table (self-learning)
CREATE TABLE IF NOT EXISTS news_types (
    id INT AUTO_INCREMENT PRIMARY KEY,
    type_name VARCHAR(100) UNIQUE NOT NULL,
    template TEXT,
    weight DECIMAL(5,2) DEFAULT 1.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    usage_count INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mission types table (self-learning)
CREATE TABLE IF NOT EXISTS mission_types (
    id INT AUTO_INCREMENT PRIMARY KEY,
    type_name VARCHAR(100) UNIQUE NOT NULL,
    template TEXT,
    difficulty_range VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    usage_count INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Lifecycle events table
CREATE TABLE IF NOT EXISTS lifecycle_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    npc_name VARCHAR(255),
    event_data_json JSON,
    occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_occurred(occurred_at DESC),
    INDEX idx_type(event_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default weather state
INSERT INTO weather_state (current_weather, temperature, effects_json) 
VALUES ('clear', 'moderate', '{}')
ON DUPLICATE KEY UPDATE id=id;

-- Insert default economy state
INSERT INTO economy_state (ec_to_kharma_rate, trend)
VALUES (1.0, 'stable')
ON DUPLICATE KEY UPDATE id=id;

-- Insert default rift state
INSERT INTO rift_state (active, intensity, location, effects_json)
VALUES (FALSE, 0, NULL, '{}')
ON DUPLICATE KEY UPDATE id=id;
"""


async def generate_db_api():
    """Generate the database API module."""
    print("\n" + "="*60)
    print("PHASE 1.2: Generating Database API")
    print("="*60)
    
    # Use pre-built API since Ollama is unreliable for large code generation
    print("Generating db_api.py with production-ready code...")
    api_code = generate_db_api_code()
    
    api_path = os.path.join(os.path.dirname(__file__), "src", "db_api.py")
    with open(api_path, "w", encoding="utf-8") as f:
        f.write(api_code)
    
    print(f"✓ API saved to: {api_path}")
    print(f"  Length: {len(api_code)} characters")
    print("\nPreview (first 1500 chars):")
    print("-" * 40)
    print(api_code[:1500])
    print("-" * 40)
    
    return api_code


def generate_db_api_code() -> str:
    """Generate production-ready database API code."""
    return '''"""
Database API for Tower Bot - MySQL Backend
Provides clean CRUD operations for all campaign data.
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling

logger = logging.getLogger(__name__)

# Configuration
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "Claude"),
    "password": os.getenv("MYSQL_PASSWORD", "WXdCPJmeDfaQALaktzF6!"),
    "database": os.getenv("MYSQL_DB", "tower_bot"),
    "charset": "utf8mb4",
    "collation": "utf8mb4_unicode_ci",
    "autocommit": True,
}

POOL_CONFIG = {
    "pool_name": "tower_pool",
    "pool_size": 5,
    **MYSQL_CONFIG
}


class DatabaseManager:
    """Manages MySQL connections and provides CRUD operations."""
    
    _instance = None
    _pool = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._init_pool()
    
    def _init_pool(self):
        """Initialize connection pool."""
        try:
            self._pool = pooling.MySQLConnectionPool(**POOL_CONFIG)
            logger.info("Database connection pool initialized")
        except mysql.connector.Error as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = None
        try:
            conn = self._pool.get_connection()
            yield conn
        except mysql.connector.Error as e:
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn and conn.is_connected():
                conn.close()
    
    def execute(self, query: str, params: tuple = None) -> int:
        """Execute a query and return affected rows."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            conn.commit()
            affected = cursor.rowcount
            cursor.close()
            return affected
    
    def fetch_one(self, query: str, params: tuple = None) -> Optional[Dict]:
        """Fetch single row as dictionary."""
        with self.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, params or ())
            result = cursor.fetchone()
            cursor.close()
            return result
    
    def fetch_all(self, query: str, params: tuple = None) -> List[Dict]:
        """Fetch all rows as list of dictionaries."""
        with self.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, params or ())
            results = cursor.fetchall()
            cursor.close()
            return results
    
    def insert(self, table: str, data: Dict) -> int:
        """Insert a row and return the new ID."""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(data.values()))
            conn.commit()
            new_id = cursor.lastrowid
            cursor.close()
            return new_id
    
    def update(self, table: str, data: Dict, where: Dict) -> int:
        """Update rows matching where conditions."""
        set_clause = ", ".join([f"{k} = %s" for k in data.keys()])
        where_clause = " AND ".join([f"{k} = %s" for k in where.keys()])
        query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(data.values()) + tuple(where.values()))
            conn.commit()
            affected = cursor.rowcount
            cursor.close()
            return affected
    
    def delete(self, table: str, where: Dict) -> int:
        """Delete rows matching where conditions."""
        where_clause = " AND ".join([f"{k} = %s" for k in where.keys()])
        query = f"DELETE FROM {table} WHERE {where_clause}"
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(where.values()))
            conn.commit()
            affected = cursor.rowcount
            cursor.close()
            return affected


# Singleton instance
db = DatabaseManager()


# =============================================================================
# NPC FUNCTIONS
# =============================================================================

def get_npc(name: str) -> Optional[Dict]:
    """Get NPC by name."""
    return db.fetch_one("SELECT * FROM npcs WHERE name = %s", (name,))

def get_all_npcs() -> List[Dict]:
    """Get all NPCs."""
    return db.fetch_all("SELECT * FROM npcs ORDER BY name")

def get_npcs_by_faction(faction: str) -> List[Dict]:
    """Get NPCs by faction."""
    return db.fetch_all("SELECT * FROM npcs WHERE faction = %s ORDER BY name", (faction,))

def get_npcs_by_status(status: str) -> List[Dict]:
    """Get NPCs by status (alive/dead/missing)."""
    return db.fetch_all("SELECT * FROM npcs WHERE status = %s ORDER BY name", (status,))

def get_living_npcs() -> List[Dict]:
    """Get all living NPCs."""
    return get_npcs_by_status("alive")

def add_npc(data: Dict) -> int:
    """Add a new NPC."""
    if "appearance_json" in data and isinstance(data["appearance_json"], dict):
        data["appearance_json"] = json.dumps(data["appearance_json"])
    return db.insert("npcs", data)

def update_npc(name: str, data: Dict) -> bool:
    """Update an NPC by name."""
    if "appearance_json" in data and isinstance(data["appearance_json"], dict):
        data["appearance_json"] = json.dumps(data["appearance_json"])
    return db.update("npcs", data, {"name": name}) > 0

def kill_npc(name: str) -> bool:
    """Mark NPC as dead."""
    return db.update("npcs", {"status": "dead"}, {"name": name}) > 0

def delete_npc(name: str) -> bool:
    """Delete an NPC (use sparingly - prefer kill_npc)."""
    return db.delete("npcs", {"name": name}) > 0


# =============================================================================
# MISSION FUNCTIONS
# =============================================================================

def get_mission(mission_id: int) -> Optional[Dict]:
    """Get mission by ID."""
    return db.fetch_one("SELECT * FROM missions WHERE id = %s", (mission_id,))

def get_active_missions() -> List[Dict]:
    """Get all active missions."""
    return db.fetch_all("SELECT * FROM missions WHERE status = 'active' ORDER BY created_at DESC")

def get_missions_by_status(status: str) -> List[Dict]:
    """Get missions by status."""
    return db.fetch_all("SELECT * FROM missions WHERE status = %s ORDER BY created_at DESC", (status,))

def create_mission(data: Dict) -> int:
    """Create a new mission."""
    if "created_at" not in data:
        data["created_at"] = datetime.now()
    return db.insert("missions", data)

def claim_mission(mission_id: int, player: str) -> bool:
    """Claim a mission for a player."""
    return db.update("missions", {"status": "claimed", "claimed_by": player}, {"id": mission_id}) > 0

def complete_mission(mission_id: int) -> bool:
    """Mark mission as completed."""
    return db.update("missions", {"status": "completed", "completed_at": datetime.now()}, {"id": mission_id}) > 0

def expire_mission(mission_id: int) -> bool:
    """Mark mission as expired."""
    return db.update("missions", {"status": "expired"}, {"id": mission_id}) > 0

def fail_mission(mission_id: int) -> bool:
    """Mark mission as failed."""
    return db.update("missions", {"status": "failed"}, {"id": mission_id}) > 0


# =============================================================================
# NEWS FUNCTIONS
# =============================================================================

def get_recent_news(limit: int = 20) -> List[Dict]:
    """Get recent news entries."""
    return db.fetch_all(
        "SELECT * FROM news_entries ORDER BY posted_at DESC LIMIT %s",
        (limit,)
    )

def add_news_entry(headline: str, body: str, category: str, news_type: str = None) -> int:
    """Add a news entry."""
    return db.insert("news_entries", {
        "headline": headline,
        "body": body,
        "category": category,
        "news_type": news_type,
        "posted_at": datetime.now()
    })

def get_news_memory(limit: int = 40) -> str:
    """Get news memory as formatted string (for LLM context)."""
    entries = get_recent_news(limit)
    lines = []
    for entry in entries:
        lines.append(f"[{entry['posted_at']}] {entry['headline']}")
        if entry.get('body'):
            lines.append(f"  {entry['body'][:200]}...")
    return "\\n".join(lines)


# =============================================================================
# WEATHER / ECONOMY STATE
# =============================================================================

def get_weather_state() -> Optional[Dict]:
    """Get current weather state."""
    result = db.fetch_one("SELECT * FROM weather_state ORDER BY id DESC LIMIT 1")
    if result and result.get("effects_json"):
        try:
            result["effects_json"] = json.loads(result["effects_json"])
        except:
            pass
    return result

def update_weather_state(data: Dict) -> bool:
    """Update weather state."""
    if "effects_json" in data and isinstance(data["effects_json"], dict):
        data["effects_json"] = json.dumps(data["effects_json"])
    data["updated_at"] = datetime.now()
    # Update the single row or insert if none exists
    existing = db.fetch_one("SELECT id FROM weather_state LIMIT 1")
    if existing:
        return db.update("weather_state", data, {"id": existing["id"]}) > 0
    else:
        return db.insert("weather_state", data) > 0

def get_economy_state() -> Optional[Dict]:
    """Get current economy state."""
    return db.fetch_one("SELECT * FROM economy_state ORDER BY id DESC LIMIT 1")

def update_economy_state(data: Dict) -> bool:
    """Update economy state."""
    data["updated_at"] = datetime.now()
    existing = db.fetch_one("SELECT id FROM economy_state LIMIT 1")
    if existing:
        return db.update("economy_state", data, {"id": existing["id"]}) > 0
    else:
        return db.insert("economy_state", data) > 0


# =============================================================================
# FACTION REPUTATION
# =============================================================================

def get_faction_reputation(faction_name: str) -> Optional[Dict]:
    """Get reputation for a faction."""
    return db.fetch_one("SELECT * FROM faction_reputation WHERE faction_name = %s", (faction_name,))

def get_all_faction_reputations() -> List[Dict]:
    """Get all faction reputations."""
    return db.fetch_all("SELECT * FROM faction_reputation ORDER BY faction_name")

def set_faction_reputation(faction_name: str, score: int, tier: str = None) -> bool:
    """Set faction reputation (insert or update)."""
    existing = get_faction_reputation(faction_name)
    if existing:
        data = {"reputation_score": score}
        if tier:
            data["tier"] = tier
        return db.update("faction_reputation", data, {"faction_name": faction_name}) > 0
    else:
        return db.insert("faction_reputation", {
            "faction_name": faction_name,
            "reputation_score": score,
            "tier": tier or "neutral"
        }) > 0


# =============================================================================
# BOUNTIES
# =============================================================================

def get_active_bounties() -> List[Dict]:
    """Get all active bounties."""
    return db.fetch_all("SELECT * FROM bounties WHERE status = 'active' ORDER BY created_at DESC")

def add_bounty(title: str, target_type: str, target_name: str, reward_ec: int) -> int:
    """Add a new bounty."""
    return db.insert("bounties", {
        "title": title,
        "target_type": target_type,
        "target_name": target_name,
        "reward_ec": reward_ec,
        "status": "active"
    })

def claim_bounty(bounty_id: int, claimed_by: str) -> bool:
    """Claim a bounty."""
    return db.update("bounties", {"status": "claimed", "claimed_by": claimed_by}, {"id": bounty_id}) > 0

def complete_bounty(bounty_id: int) -> bool:
    """Complete a bounty."""
    return db.update("bounties", {"status": "completed"}, {"id": bounty_id}) > 0


# =============================================================================
# RIFT STATE
# =============================================================================

def get_rift_state() -> Optional[Dict]:
    """Get current rift state."""
    result = db.fetch_one("SELECT * FROM rift_state ORDER BY id DESC LIMIT 1")
    if result and result.get("effects_json"):
        try:
            result["effects_json"] = json.loads(result["effects_json"])
        except:
            pass
    return result

def update_rift_state(data: Dict) -> bool:
    """Update rift state."""
    if "effects_json" in data and isinstance(data["effects_json"], dict):
        data["effects_json"] = json.dumps(data["effects_json"])
    existing = db.fetch_one("SELECT id FROM rift_state LIMIT 1")
    if existing:
        return db.update("rift_state", data, {"id": existing["id"]}) > 0
    else:
        return db.insert("rift_state", data) > 0


# =============================================================================
# PLAYER CHARACTERS
# =============================================================================

def get_player_character(name: str) -> Optional[Dict]:
    """Get player character by name."""
    result = db.fetch_one("SELECT * FROM player_characters WHERE name = %s", (name,))
    if result and result.get("profile_json"):
        try:
            result["profile_json"] = json.loads(result["profile_json"])
        except:
            pass
    return result

def get_all_player_characters() -> List[Dict]:
    """Get all player characters."""
    return db.fetch_all("SELECT * FROM player_characters ORDER BY name")

def save_player_character(name: str, data: Dict) -> bool:
    """Save player character (insert or update)."""
    if "profile_json" in data and isinstance(data["profile_json"], dict):
        data["profile_json"] = json.dumps(data["profile_json"])
    data["name"] = name
    existing = get_player_character(name)
    if existing:
        return db.update("player_characters", data, {"name": name}) > 0
    else:
        return db.insert("player_characters", data) > 0


# =============================================================================
# IMAGE REFS
# =============================================================================

def get_image_ref(entity_type: str, entity_name: str) -> Optional[Dict]:
    """Get image reference for an entity."""
    return db.fetch_one(
        "SELECT * FROM image_refs WHERE entity_type = %s AND entity_name = %s",
        (entity_type, entity_name)
    )

def save_image_ref(entity_type: str, entity_name: str, image_path: str) -> bool:
    """Save image reference (insert or update)."""
    existing = get_image_ref(entity_type, entity_name)
    if existing:
        return db.update("image_refs", 
            {"image_path": image_path, "ref_count": existing["ref_count"] + 1},
            {"entity_type": entity_type, "entity_name": entity_name}
        ) > 0
    else:
        return db.insert("image_refs", {
            "entity_type": entity_type,
            "entity_name": entity_name,
            "image_path": image_path,
            "ref_count": 1
        }) > 0


# =============================================================================
# UTILITY / RAW QUERIES
# =============================================================================

def raw_query(query: str, params: tuple = None) -> List[Dict]:
    """Execute raw SELECT query."""
    return db.fetch_all(query, params)

def raw_execute(query: str, params: tuple = None) -> int:
    """Execute raw INSERT/UPDATE/DELETE query."""
    return db.execute(query, params)


# Test connection on import
if __name__ == "__main__":
    try:
        with db.get_connection() as conn:
            print("✓ Database connection successful!")
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            print(f"  Tables: {[t[0] for t in tables]}")
            cursor.close()
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
'''


async def main():
    print("="*60)
    print("TOWER BOT SQL REFACTOR - SETUP SCRIPT")
    print("="*60)
    
    # Test connectivity
    ollama_ok = await test_ollama()
    mysql_ok = test_mysql()
    
    if not mysql_ok:
        print("\n⚠ MySQL not available.")
        print("  First run: python mysql_setup.py")
        print("  Then run this script again.")
        return
    
    if not ollama_ok:
        print("\n⚠ Ollama not responding properly.")
        print("  Will use pre-built templates instead.")
    
    print("\n" + "="*60)
    print("Ready to proceed (will use fallback templates if Ollama fails)")
    print("="*60)
    
    proceed = input("\nGenerate database schema and API? (y/n): ").strip().lower()
    if proceed == 'y':
        await generate_database_schema()
        await generate_db_api()
        print("\n" + "="*60)
        print("PHASE 1 COMPLETE!")
        print("="*60)
        print("\nNext steps:")
        print("1. Review database_schema.sql")
        print("2. Apply schema: mysql -u Claude -p tower_bot < database_schema.sql")
        print("   OR run: python apply_schema.py")
        print("3. Review src/db_api.py")
        print("4. Tell Claude to continue with Phase 2 (data migration)")
    else:
        print("Skipped. Run again when ready.")


if __name__ == "__main__":
    asyncio.run(main())
