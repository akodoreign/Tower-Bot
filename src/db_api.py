"""
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
    """Get recent news entries from news_entries table."""
    return db.fetch_all(
        "SELECT * FROM news_entries ORDER BY posted_at DESC LIMIT %s",
        (limit,)
    )

def add_news_entry(bulletin_text: str = None, facts: str = None, news_type: str = None,
                   headline: str = None, body: str = None, category: str = None) -> int:
    """
    Add a news entry. Supports two calling conventions:
    - new: add_news_entry(bulletin_text=..., facts=..., news_type=...)
    - legacy: add_news_entry(headline=..., body=..., category=..., news_type=...)
    """
    data = {"created_at": datetime.now()}
    
    # New convention from news_feed.py
    if bulletin_text is not None or facts is not None:
        data["bulletin_text"] = bulletin_text or ""
        data["facts"] = facts or ""
        data["news_type"] = news_type or "bulletin"
        return db.insert("news_memory", data)
    
    # Legacy convention
    data["headline"] = headline or ""
    data["body"] = body or ""
    data["category"] = category or ""
    data["news_type"] = news_type
    data["posted_at"] = datetime.now()
    return db.insert("news_entries", data)

def get_news_memory(limit: int = 40) -> List[Dict]:
    """
    Get news memory entries from news_memory table.
    Returns List[Dict] with 'created_at' and 'facts' keys.
    """
    try:
        entries = db.fetch_all(
            "SELECT * FROM news_memory ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
        return entries or []
    except Exception as e:
        logger.error(f"get_news_memory error: {e}")
        return []


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
    # JSON-serialize any dict/list fields to prevent MySQL conversion errors
    for key, value in list(data.items()):
        if isinstance(value, (dict, list)):
            data[key] = json.dumps(value, ensure_ascii=False, default=str)
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


def get_character_memory_text() -> str:
    """Return all player characters as the legacy ---CHARACTER--- block format.

    Used by modules that still need the RAG text format but should prefer DB.
    Falls back to reading character_memory.txt if DB is empty.
    """
    try:
        rows = db.fetch_all(
            "SELECT name, raw_block, profile_json FROM player_characters ORDER BY name"
        )
        if rows:
            blocks = []
            for row in rows:
                rb = row.get("raw_block")
                if rb:
                    blocks.append("---CHARACTER---\n" + rb.strip())
                else:
                    # Reconstruct from profile_json if no raw_block
                    pj = row.get("profile_json") or {}
                    if isinstance(pj, str):
                        try:
                            import json as _j
                            pj = _j.loads(pj)
                        except Exception:
                            pj = {}
                    lines = [f"{k}: {v}" for k, v in pj.items()]
                    blocks.append("---CHARACTER---\n" + "\n".join(lines))
            return "\n\n".join(blocks)
    except Exception:
        pass
    # Fallback to file
    try:
        from pathlib import Path as _P
        f = _P(__file__).resolve().parent.parent / "campaign_docs" / "character_memory.txt"
        if f.exists():
            return f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def get_bot_command(name: str) -> Optional[Dict]:
    """Look up a slash command by name from bot_commands table."""
    return db.fetch_one("SELECT * FROM bot_commands WHERE command_name=%s", (name,))


def get_all_bot_commands(dm_only: bool = None) -> List[Dict]:
    """Return all registered bot commands, optionally filtered to DM-only."""
    if dm_only is True:
        return db.fetch_all("SELECT * FROM bot_commands WHERE dm_only=1 ORDER BY command_name")
    if dm_only is False:
        return db.fetch_all("SELECT * FROM bot_commands WHERE dm_only=0 ORDER BY command_name")
    return db.fetch_all("SELECT * FROM bot_commands ORDER BY command_name")


# =============================================================================
# CHARACTER SNAPSHOTS (for DDB character monitor)
# =============================================================================

def get_character_snapshot(char_id: int) -> Optional[Dict]:
    """Get the latest snapshot for a character by DDB ID."""
    result = db.fetch_one(
        "SELECT * FROM character_snapshots WHERE char_id = %s ORDER BY fetched_at DESC LIMIT 1",
        (char_id,)
    )
    if result and result.get("snapshot_json"):
        try:
            result["snapshot_json"] = json.loads(result["snapshot_json"])
        except:
            pass
    return result


def save_character_snapshot(char_id: int, char_name: str, player: str, snapshot: Dict) -> int:
    """Save a new character snapshot. Returns new ID."""
    return db.insert("character_snapshots", {
        "char_id": char_id,
        "char_name": char_name,
        "player": player,
        "snapshot_json": json.dumps(snapshot, ensure_ascii=False, default=str),
        "fetched_at": snapshot.get("fetched_at", datetime.now().isoformat())
    })


def get_previous_snapshot(char_id: int) -> Optional[Dict]:
    """Get the previous (second-most-recent) snapshot for a character."""
    results = db.fetch_all(
        "SELECT * FROM character_snapshots WHERE char_id = %s ORDER BY fetched_at DESC LIMIT 2",
        (char_id,)
    )
    if len(results) >= 2:
        result = results[1]  # Second one is previous
        if result.get("snapshot_json"):
            try:
                result["snapshot_json"] = json.loads(result["snapshot_json"])
            except:
                pass
        return result
    return None


def cleanup_old_snapshots(char_id: int, keep_count: int = 5) -> int:
    """Keep only the N most recent snapshots for a character."""
    # Get IDs to keep
    keep_rows = db.fetch_all(
        "SELECT id FROM character_snapshots WHERE char_id = %s ORDER BY fetched_at DESC LIMIT %s",
        (char_id, keep_count)
    )
    if not keep_rows:
        return 0
    keep_ids = [r["id"] for r in keep_rows]
    placeholders = ",".join(["%s"] * len(keep_ids))
    return db.execute(
        f"DELETE FROM character_snapshots WHERE char_id = %s AND id NOT IN ({placeholders})",
        (char_id, *keep_ids)
    )


# =============================================================================
# STORY CONTEXT (comprehensive context for image generation)
# =============================================================================

def get_story_context(limit_news: int = 5, limit_npcs: int = 10, limit_missions: int = 5) -> Dict:
    """
    Get comprehensive story context from multiple database sources.
    Used for story image generation to give the AI richer context.
    
    Returns dict with keys:
        - recent_news: List of recent news bulletins
        - active_npcs: List of active NPCs with recent activity
        - active_missions: List of active/recent missions
        - faction_reputations: Dict of faction standings
        - rift_state: Current rift situation
        - weather: Current dome weather
        - economy: Current exchange rate and market state
    """
    context = {}
    
    # Recent news bulletins
    try:
        news = get_news_memory(limit=limit_news)
        context["recent_news"] = [{
            "text": n.get("facts", ""),
            "timestamp": str(n.get("created_at", ""))
        } for n in news]
    except Exception:
        context["recent_news"] = []
    
    # Active NPCs (recently updated)
    try:
        npcs = db.fetch_all(
            "SELECT name, faction, role, location, status FROM npcs "
            "WHERE status != 'dead' ORDER BY updated_at DESC LIMIT %s",
            (limit_npcs,)
        )
        context["active_npcs"] = npcs if npcs else []
    except Exception:
        context["active_npcs"] = []
    
    # Active missions
    try:
        missions = db.fetch_all(
            "SELECT title, faction, tier, status FROM missions "
            "WHERE status IN ('active', 'claimed') ORDER BY posted_at DESC LIMIT %s",
            (limit_missions,)
        )
        context["active_missions"] = missions if missions else []
    except Exception:
        context["active_missions"] = []
    
    # Faction reputations
    try:
        reps = get_all_faction_reputations()
        context["faction_reputations"] = {
            r["faction_name"]: {"score": r["reputation_score"], "tier": r["tier"]}
            for r in reps
        }
    except Exception:
        context["faction_reputations"] = {}
    
    # Rift state
    try:
        rift = get_rift_state()
        active_rifts = [r for r in rift.get("rifts", []) if not r.get("resolved")] if rift else []
        context["rift_state"] = {
            "active_count": len(active_rifts),
            "rifts": [{
                "location": r.get("location"),
                "stage": r.get("stage")
            } for r in active_rifts[:3]]
        }
    except Exception:
        context["rift_state"] = {"active_count": 0, "rifts": []}
    
    # Weather
    try:
        weather = get_weather_state()
        context["weather"] = {
            "current": weather.get("current_weather") if weather else "unknown",
            "effects": weather.get("effects_json", {}) if weather else {}
        }
    except Exception:
        context["weather"] = {"current": "unknown", "effects": {}}
    
    # Economy
    try:
        economy = get_economy_state()
        context["economy"] = {
            "ec_rate": economy.get("ec_to_kharma_rate") if economy else 100,
            "trend": economy.get("trend") if economy else "stable"
        }
    except Exception:
        context["economy"] = {"ec_rate": 100, "trend": "stable"}
    
    return context


def format_story_context_for_prompt(context: Dict, max_chars: int = 2000) -> str:
    """
    Format story context dict into a string suitable for LLM prompts.
    Keeps it concise for model context window limits.
    """
    parts = []
    
    # Recent news (most important for story continuity)
    if context.get("recent_news"):
        news_lines = []
        for n in context["recent_news"][:3]:
            text = n.get("text", "")[:200]
            if text:
                news_lines.append(f"- {text}")
        if news_lines:
            parts.append("RECENT EVENTS:\n" + "\n".join(news_lines))
    
    # Active rifts (high priority if any)
    rift = context.get("rift_state", {})
    if rift.get("active_count", 0) > 0:
        rift_lines = [f"- {r['stage'].upper()} at {r['location']}" for r in rift.get("rifts", [])]
        parts.append("ACTIVE RIFTS:\n" + "\n".join(rift_lines))
    
    # Active missions
    if context.get("active_missions"):
        mission_lines = [f"- {m['title']} ({m['faction']})" for m in context["active_missions"][:3]]
        parts.append("ACTIVE MISSIONS:\n" + "\n".join(mission_lines))
    
    # Notable NPCs
    if context.get("active_npcs"):
        npc_lines = [f"- {n['name']} ({n['faction']}) at {n['location']}" for n in context["active_npcs"][:5]]
        parts.append("NOTABLE NPCS:\n" + "\n".join(npc_lines))
    
    # Weather (brief)
    weather = context.get("weather", {})
    if weather.get("current") and weather["current"] != "unknown":
        parts.append(f"WEATHER: {weather['current']}")
    
    result = "\n\n".join(parts)
    return result[:max_chars] if len(result) > max_chars else result


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


# ---------------------------------------------------------------------------
# global_state helpers
# ---------------------------------------------------------------------------

def get_global_state(key: str):
    """Return the parsed JSON value for a global_state key, or None if missing."""
    rows = db.fetch_all(
        "SELECT state_value FROM global_state WHERE state_key = %s", (key,)
    )
    if not rows:
        return None
    val = rows[0]["state_value"]
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


def set_global_state(key: str, value) -> None:
    """Upsert a global_state key with a JSON-serialisable value."""
    db.execute(
        "INSERT INTO global_state (state_key, state_value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE state_value = VALUES(state_value)",
        (key, json.dumps(value, ensure_ascii=False)),
    )


def get_active_tensions() -> List[str]:
    """Return the current list of active world tensions."""
    val = get_global_state("world_active_tensions")
    return val if isinstance(val, list) else []


def set_active_tensions(tensions: List[str]) -> None:
    """Replace the active tensions list."""
    set_global_state("world_active_tensions", tensions)


def add_tension(tension: str) -> None:
    """Append a tension if it isn't already present."""
    current = get_active_tensions()
    if tension not in current:
        current.append(tension)
        set_active_tensions(current)


def resolve_tension(keyword: str) -> bool:
    """Remove the first tension whose text contains *keyword* (case-insensitive).
    Returns True if something was removed."""
    current = get_active_tensions()
    kw = keyword.lower()
    updated = [t for t in current if kw not in t.lower()]
    if len(updated) < len(current):
        set_active_tensions(updated)
        return True
    return False
