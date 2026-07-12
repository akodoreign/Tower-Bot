"""
Database API for Tower Bot - MySQL Backend
Provides clean CRUD operations for all campaign data.
"""
import os
import json
import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling

logger = logging.getLogger(__name__)

# Configuration
MYSQL_CONFIG = {
    "host":     os.getenv("MYSQL_HOST", "localhost"),
    "user":     os.getenv("MYSQL_USER", "Claude"),
    "password": os.getenv("MYSQL_PASSWORD", "WXdCPJmeDfaQALaktzF6!"),
    "database": os.getenv("MYSQL_DB", "tower_bot"),
    "charset":  "utf8mb4",
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
    
    @staticmethod
    def _validate_identifier(name: str) -> str:
        """Reject SQL identifiers containing anything outside [a-zA-Z0-9_].

        All callers use hardcoded table/column names so this should never fire
        in normal operation, but guards against unexpected key injection.
        """
        import re as _re
        if not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Unsafe SQL identifier rejected: {name!r}")
        return name

    def insert(self, table: str, data: Dict) -> int:
        """Insert a row and return the new ID."""
        self._validate_identifier(table)
        for k in data:
            self._validate_identifier(k)
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
        self._validate_identifier(table)
        for k in list(data) + list(where):
            self._validate_identifier(k)
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
        self._validate_identifier(table)
        for k in where:
            self._validate_identifier(k)
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
# DISTRICT WEALTH — dynamic world simulation
# =============================================================================

def get_district_wealth(district: str) -> int:
    """
    Return the current wealth_level (1-10) for a district.
    1 = destitute survival zone. 10 = elite restricted access.
    Returns 5 (working class) if the district is unknown.
    """
    rows = raw_query(
        "SELECT AVG(wealth_level) as avg_w FROM gazetteer_places WHERE district = %s",
        (district,),
    ) or []
    if rows and rows[0].get("avg_w") is not None:
        return round(float(rows[0]["avg_w"]))
    return 5


def adjust_district_wealth(district: str, delta: int, reason: str) -> int:
    """
    Shift a district's wealth_level by delta (positive or negative).
    Clamps to 1-10. Logs the change to global_state event log.
    Returns the new wealth level.

    Called by:
      - rift events (damage → delta -1 to -2)
      - council rulings (infrastructure investment → delta +1)
      - mission completion in district (delta +1, optional)
      - faction power shifts (Iron Fang seizes district → delta -1)
      - disaster/collapse events (delta -2)
      - new venue/commerce opening (delta +1)
    """
    import json as _json
    from datetime import datetime as _dt

    current = get_district_wealth(district)
    new_level = max(1, min(10, current + delta))

    if new_level == current:
        return current  # already at cap, no-op

    raw_execute(
        "UPDATE gazetteer_places SET wealth_level = %s WHERE district = %s",
        (new_level, district),
    )

    # Log to global_state wealth_events so the world remembers what happened
    _log_key = "wealth_event_log"
    try:
        existing_rows = raw_query(
            "SELECT state_value FROM global_state WHERE state_key = %s", (_log_key,)
        ) or []
        log = _json.loads(existing_rows[0]["state_value"]) if existing_rows else []
        log.append({
            "ts":       _dt.now().isoformat(),
            "district": district,
            "old":      current,
            "new":      new_level,
            "delta":    delta,
            "reason":   reason,
        })
        log = log[-200:]  # keep last 200 events
        payload = _json.dumps(log)
        if existing_rows:
            raw_execute(
                "UPDATE global_state SET state_value = %s WHERE state_key = %s",
                (payload, _log_key),
            )
        else:
            raw_execute(
                "INSERT INTO global_state (state_key, state_value) VALUES (%s, %s)",
                (_log_key, payload),
            )
    except Exception:
        pass  # log failure is non-fatal

    from src.log import logger as _log
    direction = "↑" if delta > 0 else "↓"
    _log.info(
        f"💰 District wealth {direction}: {district} "
        f"{current} → {new_level} ({reason})"
    )
    return new_level


def get_charitable_gods(
    charity_style: str = None,
    max_risk: int = 100,
    suspicious: int = None,
    limit: int = 20,
) -> list:
    """
    Return gods from the pantheon that run charitable missions.
    charity_style: filter by type (healing_aid, community_craft, protection_justice,
                   education, grief_aid, suspicious_redistribution)
    max_risk:      cap recruitment_risk (lower = safer, higher = more dramatic)
    suspicious:    0 = only trustworthy, 1 = only suspicious, None = all
    """
    where = ["charitable = 1"]
    params = []
    if charity_style:
        where.append("charity_style = %s")
        params.append(charity_style)
    if max_risk < 100:
        where.append("recruit_risk <= %s")
        params.append(max_risk)
    if suspicious is not None:
        where.append("suspicious = %s")
        params.append(suspicious)
    query = (
        "SELECT name, origin, domain, alliance, alignment, recruit_risk, "
        "role_function, notes, charity_style, suspicious "
        "FROM gods WHERE " + " AND ".join(where) +
        " ORDER BY RAND() LIMIT %s"
    )
    params.append(limit)
    return raw_query(query, tuple(params)) or []


def get_wealth_event_log(limit: int = 20) -> list:
    """Return recent district wealth change events."""
    import json as _json
    rows = raw_query(
        "SELECT state_value FROM global_state WHERE state_key = 'wealth_event_log'"
    ) or []
    if not rows:
        return []
    try:
        log = _json.loads(rows[0]["state_value"])
        return log[-limit:]
    except Exception:
        return []


# =============================================================================
# LEGEND POINTS & CULINARY COUNCIL
# =============================================================================

def get_legend_points() -> int:
    """Return current party Legend Points."""
    val = get_global_state("legend_points")
    try:
        return int(val) if val is not None else 0
    except Exception:
        return 0


def update_legend_points(delta: int, reason: str = "") -> dict:
    """
    Adjust LP by delta, update Divine Attention accordingly, log the event.
    Returns {"old": int, "new": int, "da": int, "threshold_crossed": str|None}
    """
    import json as _json, datetime as _dt
    old_lp = get_legend_points()
    new_lp = max(0, old_lp + delta)
    set_global_state("legend_points", new_lp)

    # DA = 1 step per 10 LP
    old_da = int(get_global_state("divine_attention") or 0)
    new_da = new_lp // 10
    if new_da != old_da:
        set_global_state("divine_attention", new_da)

    # Detect threshold crossings
    threshold_crossed = None
    for thresh in [5, 7, 10, 13, 15, 20, 25]:
        if old_lp < thresh <= new_lp:
            threshold_crossed = str(thresh)
            break

    # Append to LP event log
    try:
        log_raw = get_global_state("lp_event_log") or "[]"
        log = _json.loads(log_raw) if isinstance(log_raw, str) else (log_raw if isinstance(log_raw, list) else [])
    except Exception:
        log = []
    log.append({
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
        "delta": delta,
        "old": old_lp,
        "new": new_lp,
        "reason": reason,
        "threshold": threshold_crossed,
    })
    set_global_state("lp_event_log", log[-50:])

    return {"old": old_lp, "new": new_lp, "da": new_da, "threshold_crossed": threshold_crossed}


def get_culinary_council(seat: int = None) -> list:
    """
    Return Culinary Council NPCs.  Pass seat=N for a specific member (1-7).
    """
    if seat is not None:
        rows = raw_query(
            "SELECT * FROM npcs WHERE faction='Culinary Council' "
            "AND JSON_EXTRACT(data_json,'$.council_seat')=%s",
            (seat,)
        ) or []
    else:
        rows = raw_query(
            "SELECT * FROM npcs WHERE faction='Culinary Council' "
            "ORDER BY JSON_EXTRACT(data_json,'$.council_seat')"
        ) or []
    return rows


def get_council_lp_behavior(member_name: str, lp: int = None) -> str:
    """
    Return the behavior description for a council member at the given LP level.
    If lp is None, uses current LP from global_state.
    """
    import json as _json
    if lp is None:
        lp = get_legend_points()
    rows = raw_query("SELECT data_json FROM npcs WHERE name=%s AND faction='Culinary Council'", (member_name,))
    if not rows:
        return ""
    try:
        data = _json.loads(rows[0]["data_json"]) if isinstance(rows[0]["data_json"], str) else rows[0]["data_json"]
        behaviors = data.get("lp_behaviors", {})
        best = ""
        for key, val in behaviors.items():
            # key format: "13-15" or "16+"
            parts = key.replace("+", "").split("-")
            lo = int(parts[0])
            hi = int(parts[1]) if len(parts) > 1 else 9999
            if lo <= lp <= hi:
                best = val
        return best
    except Exception:
        return ""


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
    try:
        from src.text_mojibake import repair_mojibake
    except Exception:
        repair_mojibake = lambda value: value

    data = {"created_at": datetime.now()}
    
    # New convention from news_feed.py
    if bulletin_text is not None or facts is not None:
        data["bulletin_text"] = repair_mojibake(bulletin_text or "")
        data["facts"] = repair_mojibake(facts or "")
        data["news_type"] = news_type or "bulletin"
        return db.insert("news_memory", data)
    
    # Legacy convention
    data["headline"] = repair_mojibake(headline or "")
    data["body"] = repair_mojibake(body or "")
    data["category"] = repair_mojibake(category or "")
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
        result = db.update("faction_reputation", data, {"faction_name": faction_name}) > 0
    else:
        result = db.insert("faction_reputation", {
            "faction_name": faction_name,
            "reputation_score": score,
            "tier": tier or "neutral"
        }) > 0
    if result:
        try:
            from src.mimir_sync import trigger_faction_sync
            trigger_faction_sync(faction_name)
        except Exception:
            pass
    return result


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

def save_image_ref(
    entity_type: str,
    entity_name: str,
    image_path: str,
    metadata: Optional[Dict] = None,
) -> bool:
    """Save image reference (insert or update). Increments ref_count on update."""
    import json as _json
    from datetime import datetime as _dt
    meta_str = _json.dumps(metadata, ensure_ascii=False) if metadata else None
    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = get_image_ref(entity_type, entity_name)
    if existing:
        update_data: Dict = {
            "image_path": image_path,
            "ref_count": existing["ref_count"] + 1,
            "updated_at": now,
        }
        if meta_str is not None:
            update_data["metadata_json"] = meta_str
        return db.update(
            "image_refs", update_data,
            {"entity_type": entity_type, "entity_name": entity_name}
        ) > 0
    else:
        insert_data: Dict = {
            "entity_type": entity_type,
            "entity_name": entity_name,
            "image_path": image_path,
            "ref_count": 1,
        }
        if meta_str is not None:
            insert_data["metadata_json"] = meta_str
        return db.insert("image_refs", insert_data) > 0


# =============================================================================
# NPC ACTION PROMPTS
# =============================================================================

_NPC_ACTION_PROMPT_DEFAULTS = [
    ("barbarian", "smash", "full body action shot, smashing downward with a heavy weapon, debris flying, ferocious motion, same face and outfit"),
    ("bard", "perform", "full body action shot, performing magic through music and gesture, glowing notes in the air, same face and outfit"),
    ("cleric", "channel_divinity", "full body action shot, channeling radiant divine magic with holy focus raised, same face and outfit"),
    ("druid", "wild_magic", "full body action shot, commanding vines and primal nature magic, wind and leaves swirling, same face and outfit"),
    ("fighter", "charge", "full body action shot, charging forward with weapon ready, dynamic combat stance, same face and outfit"),
    ("monk", "strike", "full body action shot, leaping into a precise martial arts strike, flowing motion, same face and outfit"),
    ("paladin", "smite", "full body action shot, raising a weapon with radiant smite energy, heroic stance, same face and outfit"),
    ("ranger", "aim", "full body action shot, aiming a bow or crossbow from cover, alert hunter posture, same face and outfit"),
    ("rogue", "ambush", "full body action shot, slipping from shadow with dagger ready, stealthy motion, same face and outfit"),
    ("sorcerer", "surge", "full body action shot, unleashing volatile arcane power from both hands, dramatic magical light, same face and outfit"),
    ("warlock", "eldritch_blast", "full body action shot, casting eldritch blast with occult energy spiraling from one hand, same face and outfit"),
    ("wizard", "cast_spell", "full body action shot, casting a spell from an open grimoire or raised hand, arcane sigils glowing, same face and outfit"),
    ("artificer", "activate_device", "full body action shot, activating a magical device or rune-powered tool, sparks and sigils, same face and outfit"),
    ("blood hunter", "brand", "full body action shot, brandishing a weapon charged with crimson rite energy, grim motion, same face and outfit"),
    ("gunslinger", "quick_draw", "full body action shot, quick-drawing a pistol or rifle with smoke and muzzle flash, same face and outfit"),
    ("monster hunter", "track_quarry", "full body action shot, stalking a monster with blade, crossbow, traps, and grim hunter tools, same face and outfit"),
    ("pugilist", "haymaker", "full body action shot, throwing a brutal bare-knuckle haymaker in close quarters, same face and outfit"),
    ("arcane archer", "arcane_shot", "full body action shot, drawing a bow with glowing arcane arrow energy, same face and outfit"),
    ("senior acquisitions agent", "field_deal", "full body action shot, closing a dangerous deal with one hand on a concealed weapon, same face and outfit"),
    ("inspector", "investigate", "full body action shot, examining evidence with a lantern and weapon close at hand, same face and outfit"),
    ("information broker", "trade_secret", "full body action shot, passing a sealed secret while watching every exit, same face and outfit"),
    ("archivist", "defend_archive", "full body action shot, defending scrolls and books with a staff and quick spell, same face and outfit"),
    ("memory architect", "shape_memory", "full body action shot, shaping floating memory shards into a psychic construct, same face and outfit"),
    ("contract mediator", "seal_contract", "full body action shot, invoking glowing contract sigils in the air, same face and outfit"),
    ("field captain", "lead_charge", "full body action shot, leading a charge with weapon raised and soldiers behind, same face and outfit"),
    ("speaker", "rally_crowd", "full body action shot, rallying a crowd with cult fervor and a raised staff, same face and outfit"),
    ("senior blade", "arena_flourish", "full body action shot, making a dramatic arena attack with weapon flashing, same face and outfit"),
    ("warden", "hold_line", "full body action shot, holding a defensive line with shield or spear braced, same face and outfit"),
    ("officer", "command", "full body action shot, commanding troops while drawing a weapon, same face and outfit"),
    ("compliance officer", "issue_order", "full body action shot, issuing an urgent FTA order while reaching for a sidearm, same face and outfit"),
    ("acolyte", "minor_miracle", "full body action shot, invoking a small divine miracle through a holy symbol, same face and outfit"),
    ("contract scribe", "write_binding", "full body action shot, writing glowing binding clauses in the air with a quill, same face and outfit"),
    ("mercenary", "advance", "full body action shot, advancing through danger with practical weapon and shield ready, same face and outfit"),
    ("street runner", "vault", "full body action shot, vaulting over an alley obstacle at speed, same face and outfit"),
    ("freelance", "improvise", "full body action shot, improvising under pressure with mixed adventuring gear, same face and outfit"),
    ("adventurer", "ready", "full body action shot, taking decisive action with class-appropriate gear, cinematic movement, same face and outfit"),
]


def _npc_action_class_key(class_name: str) -> str:
    text = (class_name or "").lower()
    matches = []
    for key, _label, _prompt in _NPC_ACTION_PROMPT_DEFAULTS:
        pos = text.find(key)
        if pos >= 0:
            matches.append((pos, -len(key), key))
    if matches:
        matches.sort()
        return matches[0][2]
    return "adventurer"


def ensure_npc_action_prompt_table() -> None:
    """Create and seed class-flavored NPC action prompts for ref_002+ images."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS npc_action_prompts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            class_name VARCHAR(80) NOT NULL,
            action_label VARCHAR(80) NOT NULL,
            action_prompt TEXT NOT NULL,
            weight INT NOT NULL DEFAULT 1,
            active TINYINT(1) NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_npc_action_prompt (class_name, action_label),
            INDEX idx_npc_action_class (class_name, active, weight)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    for class_name, action_label, action_prompt in _NPC_ACTION_PROMPT_DEFAULTS:
        db.execute(
            """
            INSERT IGNORE INTO npc_action_prompts
                (class_name, action_label, action_prompt, weight, active)
            VALUES (%s, %s, %s, 1, 1)
            """,
            (class_name, action_label, action_prompt),
        )


def pick_npc_action_prompt(class_name: str) -> Dict[str, Any]:
    """Pick one active action prompt for an NPC class, falling back to adventurer."""
    ensure_npc_action_prompt_table()
    key = _npc_action_class_key(class_name)
    rows = db.fetch_all(
        """
        SELECT class_name, action_label, action_prompt
        FROM npc_action_prompts
        WHERE class_name = %s AND active = 1
        ORDER BY (RAND() * GREATEST(weight, 1)) DESC
        LIMIT 1
        """,
        (key,),
    )
    if not rows and key != "adventurer":
        rows = db.fetch_all(
            """
            SELECT class_name, action_label, action_prompt
            FROM npc_action_prompts
            WHERE class_name = 'adventurer' AND active = 1
            ORDER BY (RAND() * GREATEST(weight, 1)) DESC
            LIMIT 1
            """
        )
    if not rows:
        return {
            "class_name": "adventurer",
            "action_label": "ready",
            "action_prompt": "full body action shot, taking decisive action with class-appropriate gear, same face and outfit",
        }
    return rows[0]


# =============================================================================
# D&D CLASS / SUBCLASS CATALOG
# =============================================================================

DND_CLASS_CATALOG: List[Dict[str, Any]] = [
    {"class_name": "Barbarian", "primary_ability": "Strength", "hit_die": 12, "save_proficiencies": ["STR", "CON"], "source": "2024 PHB / campaign"},
    {"class_name": "Bard", "primary_ability": "Charisma", "hit_die": 8, "save_proficiencies": ["DEX", "CHA"], "source": "2024 PHB / campaign"},
    {"class_name": "Cleric", "primary_ability": "Wisdom", "hit_die": 8, "save_proficiencies": ["WIS", "CHA"], "source": "2024 PHB / campaign"},
    {"class_name": "Druid", "primary_ability": "Wisdom", "hit_die": 8, "save_proficiencies": ["INT", "WIS"], "source": "2024 PHB / campaign"},
    {"class_name": "Fighter", "primary_ability": "Strength or Dexterity", "hit_die": 10, "save_proficiencies": ["STR", "CON"], "source": "2024 PHB / campaign"},
    {"class_name": "Monk", "primary_ability": "Dexterity and Wisdom", "hit_die": 8, "save_proficiencies": ["STR", "DEX"], "source": "2024 PHB / campaign"},
    {"class_name": "Paladin", "primary_ability": "Strength and Charisma", "hit_die": 10, "save_proficiencies": ["WIS", "CHA"], "source": "2024 PHB / campaign"},
    {"class_name": "Ranger", "primary_ability": "Dexterity and Wisdom", "hit_die": 10, "save_proficiencies": ["STR", "DEX"], "source": "2024 PHB / campaign"},
    {"class_name": "Rogue", "primary_ability": "Dexterity", "hit_die": 8, "save_proficiencies": ["DEX", "INT"], "source": "2024 PHB / campaign"},
    {"class_name": "Sorcerer", "primary_ability": "Charisma", "hit_die": 6, "save_proficiencies": ["CON", "CHA"], "source": "2024 PHB / campaign"},
    {"class_name": "Warlock", "primary_ability": "Charisma", "hit_die": 8, "save_proficiencies": ["WIS", "CHA"], "source": "2024 PHB / campaign"},
    {"class_name": "Wizard", "primary_ability": "Intelligence", "hit_die": 6, "save_proficiencies": ["INT", "WIS"], "source": "2024 PHB / campaign"},
    {"class_name": "Artificer", "primary_ability": "Intelligence", "hit_die": 8, "save_proficiencies": ["CON", "INT"], "source": "campaign"},
    {"class_name": "Blood Hunter", "primary_ability": "Strength or Dexterity and Intelligence", "hit_die": 10, "save_proficiencies": ["DEX", "INT"], "source": "campaign"},
    {"class_name": "Gunslinger", "primary_ability": "Dexterity", "hit_die": 8, "save_proficiencies": ["DEX", "CHA"], "source": "Valda's Spire of Secrets"},
    {"class_name": "Monster Hunter", "primary_ability": "Strength or Dexterity and Intelligence", "hit_die": 10, "save_proficiencies": ["DEX", "INT"], "source": "Grim Hollow Player's Guide"},
    {"class_name": "Pugilist", "primary_ability": "Strength", "hit_die": 10, "save_proficiencies": ["STR", "CON"], "source": "The Pugilist Class 2024"},
]

DND_SUBCLASS_CATALOG: Dict[str, List[Dict[str, str]]] = {
    "Barbarian": [
        {"name": "Path of the Berserker", "status": "2024"},
        {"name": "Path of the Wild Heart", "status": "2024"},
        {"name": "Path of the World Tree", "status": "2024"},
        {"name": "Path of the Zealot", "status": "2024"},
        {"name": "Path of the Ancestral Guardian", "status": "legacy"},
        {"name": "Path of the Beast", "status": "legacy"},
        {"name": "Path of the Storm Herald", "status": "legacy"},
        {"name": "Path of Wild Magic", "status": "legacy"},
    ],
    "Bard": [
        {"name": "College of Dance", "status": "2024"},
        {"name": "College of Glamour", "status": "2024"},
        {"name": "College of Lore", "status": "2024"},
        {"name": "College of Valor", "status": "2024"},
        {"name": "College of Creation", "status": "legacy"},
        {"name": "College of Eloquence", "status": "legacy"},
        {"name": "College of Swords", "status": "legacy"},
        {"name": "College of Whispers", "status": "legacy"},
    ],
    "Cleric": [
        {"name": "Life Domain", "status": "2024"},
        {"name": "Light Domain", "status": "2024"},
        {"name": "Trickery Domain", "status": "2024"},
        {"name": "War Domain", "status": "2024"},
        {"name": "Forge Domain", "status": "legacy"},
        {"name": "Order Domain", "status": "legacy"},
        {"name": "Peace Domain", "status": "legacy"},
        {"name": "Twilight Domain", "status": "legacy"},
    ],
    "Druid": [
        {"name": "Circle of the Land", "status": "2024"},
        {"name": "Circle of the Moon", "status": "2024"},
        {"name": "Circle of the Sea", "status": "2024"},
        {"name": "Circle of Stars", "status": "2024"},
        {"name": "Circle of Dreams", "status": "legacy"},
        {"name": "Circle of the Shepherd", "status": "legacy"},
        {"name": "Circle of Spores", "status": "legacy"},
        {"name": "Circle of Wildfire", "status": "legacy"},
    ],
    "Fighter": [
        {"name": "Battle Master", "status": "2024"},
        {"name": "Champion", "status": "2024"},
        {"name": "Eldritch Knight", "status": "2024"},
        {"name": "Psi Warrior", "status": "2024"},
        {"name": "Arcane Archer", "status": "legacy"},
        {"name": "Brawler", "status": "deprecated"},
        {"name": "Cavalier", "status": "legacy"},
        {"name": "Rune Knight", "status": "legacy"},
        {"name": "Samurai", "status": "legacy"},
    ],
    "Monk": [
        {"name": "Warrior of Mercy", "status": "2024"},
        {"name": "Warrior of Shadow", "status": "2024"},
        {"name": "Warrior of the Elements", "status": "2024"},
        {"name": "Warrior of the Hand", "status": "2024"},
        {"name": "Warrior of the Astral Self", "status": "legacy"},
        {"name": "Warrior of the Drunken Master", "status": "legacy"},
        {"name": "Warrior of Kensei", "status": "legacy"},
        {"name": "Warrior of Sun Soul", "status": "legacy"},
    ],
    "Paladin": [
        {"name": "Oath of Devotion", "status": "2024"},
        {"name": "Oath of Glory", "status": "2024"},
        {"name": "Oath of the Ancients", "status": "2024"},
        {"name": "Oath of Vengeance", "status": "2024"},
        {"name": "Oath of Conquest", "status": "legacy"},
        {"name": "Oath of Redemption", "status": "legacy"},
        {"name": "Oath of the Watchers", "status": "legacy"},
        {"name": "Oathbreaker", "status": "legacy"},
    ],
    "Ranger": [
        {"name": "Beast Master", "status": "2024"},
        {"name": "Fey Wanderer", "status": "2024"},
        {"name": "Gloom Stalker", "status": "2024"},
        {"name": "Hunter", "status": "2024"},
        {"name": "Horizon Walker", "status": "legacy"},
        {"name": "Monster Slayer", "status": "legacy"},
        {"name": "Swarmkeeper", "status": "legacy"},
        {"name": "Drakewarden", "status": "legacy"},
    ],
    "Rogue": [
        {"name": "Arcane Trickster", "status": "2024"},
        {"name": "Assassin", "status": "2024"},
        {"name": "Soulknife", "status": "2024"},
        {"name": "Thief", "status": "2024"},
        {"name": "Inquisitor", "status": "legacy"},
        {"name": "Mastermind", "status": "legacy"},
        {"name": "Phantom", "status": "legacy"},
        {"name": "Scout", "status": "legacy"},
        {"name": "Swashbuckler", "status": "deprecated"},
    ],
    "Sorcerer": [
        {"name": "Aberrant Sorcery", "status": "2024"},
        {"name": "Clockwork Sorcery", "status": "2024"},
        {"name": "Draconic Sorcery", "status": "2024"},
        {"name": "Wild Magic Sorcery", "status": "2024"},
        {"name": "Divine Soul Sorcery", "status": "legacy"},
        {"name": "Shadow Sorcery", "status": "legacy"},
        {"name": "Storm Sorcery", "status": "legacy"},
    ],
    "Warlock": [
        {"name": "Archfey Patron", "status": "2024"},
        {"name": "Celestial Patron", "status": "2024"},
        {"name": "Fiend Patron", "status": "2024"},
        {"name": "Great Old One Patron", "status": "2024"},
        {"name": "Fathomless", "status": "legacy"},
        {"name": "Genie", "status": "legacy"},
        {"name": "Hexblade", "status": "legacy"},
    ],
    "Wizard": [
        {"name": "Abjurer", "status": "2024"},
        {"name": "Diviner", "status": "2024"},
        {"name": "Evoker", "status": "2024"},
        {"name": "Illusionist", "status": "2024"},
        {"name": "Bladesinger", "status": "legacy"},
        {"name": "Order of Scribes", "status": "legacy"},
        {"name": "War Magic", "status": "legacy"},
        {"name": "Witch", "status": "campaign"},
    ],
    "Artificer": [
        {"name": "Alchemist", "status": "legacy"},
        {"name": "Armorer", "status": "legacy"},
        {"name": "Artillerist", "status": "legacy"},
        {"name": "Battle Smith", "status": "legacy"},
    ],
    "Blood Hunter": [
        {"name": "Order of the Ghostslayer", "status": "campaign"},
        {"name": "Order of the Lycan", "status": "campaign"},
        {"name": "Order of the Mutant", "status": "campaign"},
        {"name": "Order of the Profane Soul", "status": "campaign"},
    ],
    "Gunslinger": [
        {"name": "Deadeye", "status": "2024"},
        {"name": "High Roller", "status": "2024"},
        {"name": "Secret Agent", "status": "2024"},
        {"name": "Spellslinger", "status": "2024"},
        {"name": "Trick Shot", "status": "2024"},
        {"name": "White Hat", "status": "2024"},
    ],
    "Monster Hunter": [
        {"name": "Carver Guild", "status": "2024"},
        {"name": "Devourer Guild", "status": "2024"},
        {"name": "Occultist Guild", "status": "2024"},
        {"name": "Trapper Guild", "status": "2024"},
    ],
    "Pugilist": [
        {"name": "Dog and Hound", "status": "2024"},
        {"name": "Hand of Dread", "status": "2024"},
        {"name": "Piss and Vinegar", "status": "2024"},
        {"name": "Squared Circle", "status": "2024"},
        {"name": "Street Saint", "status": "2024"},
        {"name": "Sweet Science", "status": "2024"},
    ],
}

_SUBCLASS_ALIASES = {
    "eloquence": "College of Eloquence",
    "loremaster": "Order of Scribes",
    "psionic": "Diviner",
    "inquisitive": "Inquisitor",
    "kensai": "Warrior of Kensei",
    "kensei": "Warrior of Kensei",
    "shepard": "Circle of the Shepherd",
}


def _stable_index(seed_text: str, count: int) -> int:
    if count <= 0:
        return 0
    import hashlib
    digest = hashlib.sha256((seed_text or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % count


def canonical_class_name(class_name: str) -> str:
    text = (class_name or "").strip()
    if not text:
        return ""
    for row in DND_CLASS_CATALOG:
        name = row["class_name"]
        if name.lower() == text.lower():
            return name
    return text


def canonical_subclass_name(class_name: str, subclass_name: str) -> str:
    cls = canonical_class_name(class_name)
    raw = (subclass_name or "").strip()
    if not cls or not raw or raw.lower() in {"none", "null"}:
        return ""
    alias = _SUBCLASS_ALIASES.get(raw.lower())
    if alias:
        return alias
    for row in DND_SUBCLASS_CATALOG.get(cls, []):
        name = row["name"]
        if name.lower() == raw.lower():
            return name
    return ""


def pick_canonical_subclass(class_name: str, seed_text: str = "", prefer_legacy: bool = True) -> str:
    cls = canonical_class_name(class_name)
    rows = DND_SUBCLASS_CATALOG.get(cls, [])
    if not rows:
        return ""
    pool = rows if prefer_legacy else [r for r in rows if r.get("status") == "2024"] or rows
    return pool[_stable_index(f"{cls}:{seed_text}", len(pool))]["name"]


def ensure_dnd_class_catalog_tables() -> None:
    """Create and seed canonical class/subclass catalog tables."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS dnd_classes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            class_name VARCHAR(80) NOT NULL UNIQUE,
            primary_ability VARCHAR(120),
            hit_die INT,
            save_proficiencies_json JSON,
            source VARCHAR(160),
            active TINYINT(1) NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS dnd_subclasses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            class_name VARCHAR(80) NOT NULL,
            subclass_name VARCHAR(120) NOT NULL,
            source_status VARCHAR(40),
            source VARCHAR(160),
            active TINYINT(1) NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_dnd_subclass (class_name, subclass_name),
            INDEX idx_dnd_subclass_class (class_name, active)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    for row in DND_CLASS_CATALOG:
        db.execute(
            """
            INSERT INTO dnd_classes
                (class_name, primary_ability, hit_die, save_proficiencies_json, source, active)
            VALUES (%s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
                primary_ability = VALUES(primary_ability),
                hit_die = VALUES(hit_die),
                save_proficiencies_json = VALUES(save_proficiencies_json),
                source = VALUES(source),
                active = 1
            """,
            (
                row["class_name"],
                row.get("primary_ability"),
                row.get("hit_die"),
                json.dumps(row.get("save_proficiencies") or []),
                row.get("source"),
            ),
        )
    for class_name, subclasses in DND_SUBCLASS_CATALOG.items():
        source = next((r.get("source") for r in DND_CLASS_CATALOG if r["class_name"] == class_name), "campaign")
        for subclass in subclasses:
            db.execute(
                """
                INSERT INTO dnd_subclasses
                    (class_name, subclass_name, source_status, source, active)
                VALUES (%s, %s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE
                    source_status = VALUES(source_status),
                    source = VALUES(source),
                    active = 1
                """,
                (class_name, subclass["name"], subclass.get("status"), source),
            )


def get_dnd_class_catalog() -> Dict[str, List[str]]:
    """Return active class catalog as class_name -> subclass names."""
    ensure_dnd_class_catalog_tables()
    rows = db.fetch_all(
        """
        SELECT class_name, subclass_name
        FROM dnd_subclasses
        WHERE active = 1
        ORDER BY class_name, subclass_name
        """
    )
    catalog: Dict[str, List[str]] = {}
    for row in rows:
        catalog.setdefault(row["class_name"], []).append(row["subclass_name"])
    return catalog


# =============================================================================
# UTILITY / RAW QUERIES
# =============================================================================

def raw_query(query: str, params: tuple = None) -> List[Dict]:
    """Execute raw SELECT query."""
    return db.fetch_all(query, params)

def raw_execute(query: str, params: tuple = None) -> int:
    """Execute raw INSERT/UPDATE/DELETE query."""
    return db.execute(query, params)


# =============================================================================
# RECON DOSSIERS  (infiltration results -> building blocks for heist/assassination)
# =============================================================================

def ensure_recon_table() -> None:
    """Create the recon_dossiers table if it does not exist (idempotent)."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS recon_dossiers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            mission_id INT NULL,
            party_name VARCHAR(255) NULL,
            event_name VARCHAR(255) NULL,
            venue VARCHAR(255) NULL,
            district VARCHAR(255) NULL,
            host_faction VARCHAR(255) NULL,
            hiring_faction VARCHAR(255) NULL,
            target VARCHAR(512) NULL,
            target_kind VARCHAR(32) NULL,
            outcome VARCHAR(32) NOT NULL DEFAULT 'scouted',
            details TEXT NULL,
            dossier_json JSON NULL,
            consumed_by_mission_id INT NULL,
            consumed_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_host (host_faction),
            INDEX idx_district (district),
            INDEX idx_outcome (outcome),
            INDEX idx_consumed (consumed_by_mission_id),
            INDEX idx_kind (target_kind)
        )
        """
    )


def record_recon_dossier(
    *,
    mission_id: int = None,
    party_name: str = "",
    event_name: str = "",
    venue: str = "",
    district: str = "",
    host_faction: str = "",
    hiring_faction: str = "",
    target: str = "",
    target_kind: str = "",
    outcome: str = "scouted",
    details: str = "",
    dossier: dict = None,
) -> int:
    """Record an infiltration's recon result. Returns the new dossier id."""
    try:
        return db.insert("recon_dossiers", {
            "mission_id": mission_id,
            "party_name": party_name or None,
            "event_name": event_name or None,
            "venue": venue or None,
            "district": district or None,
            "host_faction": host_faction or None,
            "hiring_faction": hiring_faction or None,
            "target": (target or None) and str(target)[:512],
            "target_kind": target_kind or None,
            "outcome": outcome or "scouted",
            "details": details or None,
            "dossier_json": json.dumps(dossier or {}, ensure_ascii=False),
        })
    except Exception as e:
        logger.warning(f"record_recon_dossier failed: {e}")
        return 0


def set_recon_outcome(dossier_id: int, outcome: str, details: str = "") -> None:
    """Update a dossier with its mission result (success/partial/failure)."""
    data = {"outcome": outcome}
    if details:
        data["details"] = details
    try:
        db.update("recon_dossiers", data, {"id": dossier_id})
    except Exception as e:
        logger.warning(f"set_recon_outcome failed: {e}")


def find_recon_for_followup(host_faction: str = "", district: str = "", target_kind: str = "") -> Optional[Dict]:
    """Find the most recent USABLE, unconsumed recon dossier for a follow-up job.
    Prefers a host-faction match, then a district match. Only returns dossiers
    whose infiltration actually produced intel (success or partial)."""
    base = (
        "SELECT * FROM recon_dossiers "
        "WHERE consumed_by_mission_id IS NULL AND outcome IN ('success','partial') "
    )
    # Try host faction first (the strongest link), then district, then anything.
    for clause, val in (
        ("AND host_faction = %s ", host_faction),
        ("AND district = %s ", district),
        ("", None),
    ):
        if clause and not val:
            continue
        params = (val,) if clause else ()
        if target_kind:
            clause += "AND target_kind = %s "
            params = params + (target_kind,)
        rows = db.fetch_all(base + clause + "ORDER BY created_at DESC LIMIT 1", params)
        if rows:
            row = rows[0]
            dj = row.get("dossier_json")
            if isinstance(dj, str):
                try:
                    row["dossier"] = json.loads(dj)
                except Exception:
                    row["dossier"] = {}
            else:
                row["dossier"] = dj or {}
            return row
    return None


def record_recon_outcome_for_mission(
    mission_id: int,
    outcome: str,
    *,
    party_name: str = "",
    details: str = "",
    host_faction: str = "",
    hiring_faction: str = "",
    target: str = "",
    target_kind: str = "",
    venue: str = "",
    district: str = "",
    event_name: str = "",
) -> int:
    """Upsert an infiltration's result by mission_id: update the dossier recorded
    at module-build time, or insert a fresh row if none exists (NPC party that
    resolved without a generated module). Returns the dossier id."""
    try:
        if mission_id:
            rows = db.fetch_all(
                "SELECT id FROM recon_dossiers WHERE mission_id = %s ORDER BY id DESC LIMIT 1",
                (mission_id,),
            )
            if rows:
                data = {"outcome": outcome}
                if details:
                    data["details"] = details
                if party_name:
                    data["party_name"] = party_name
                db.update("recon_dossiers", data, {"id": rows[0]["id"]})
                return rows[0]["id"]
    except Exception as e:
        logger.warning(f"record_recon_outcome_for_mission update failed: {e}")
    return record_recon_dossier(
        mission_id=mission_id, party_name=party_name, outcome=outcome, details=details,
        host_faction=host_faction, hiring_faction=hiring_faction, target=target,
        target_kind=target_kind, venue=venue, district=district, event_name=event_name,
    )


def get_recon_by_id(dossier_id: int) -> Optional[Dict]:
    """Load a specific recon dossier by id (used by a spawned follow-up that
    carries parent_recon_id). Ignores the consumed flag -- the follow-up owns it."""
    if not dossier_id:
        return None
    rows = db.fetch_all("SELECT * FROM recon_dossiers WHERE id = %s LIMIT 1", (dossier_id,))
    if not rows:
        return None
    row = rows[0]
    dj = row.get("dossier_json")
    if isinstance(dj, str):
        try:
            row["dossier"] = json.loads(dj)
        except Exception:
            row["dossier"] = {}
    else:
        row["dossier"] = dj or {}
    return row


def mark_recon_consumed(dossier_id: int, mission_id: int = None) -> None:
    """Mark a dossier as used by a follow-up heist/assassination."""
    try:
        db.execute(
            "UPDATE recon_dossiers SET consumed_by_mission_id = %s, consumed_at = NOW() WHERE id = %s",
            (mission_id, dossier_id),
        )
    except Exception as e:
        logger.warning(f"mark_recon_consumed failed: {e}")


# =============================================================================
# DURABLE BOT JOBS
# =============================================================================

def ensure_bot_job_tables() -> None:
    """Create durable job tables used by dashboard/bot handoff paths."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_claim_jobs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            mission_id INT NOT NULL,
            claimer VARCHAR(255) NOT NULL DEFAULT 'DM Dashboard',
            title VARCHAR(255),
            status ENUM('queued','processing','done','failed') NOT NULL DEFAULT 'queued',
            attempts INT NOT NULL DEFAULT 0,
            locked_by VARCHAR(80),
            last_error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            UNIQUE KEY uq_dashboard_claim_mission (mission_id),
            INDEX idx_dashboard_claim_status (status, created_at)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS module_generation_jobs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            mission_id INT NOT NULL,
            claimer VARCHAR(255) NOT NULL DEFAULT 'DM Dashboard',
            status ENUM('queued','processing','done','failed') NOT NULL DEFAULT 'queued',
            attempts INT NOT NULL DEFAULT 0,
            locked_by VARCHAR(80),
            last_error TEXT,
            module_slug VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            UNIQUE KEY uq_module_generation_mission (mission_id),
            INDEX idx_module_generation_status (status, created_at)
        )
        """
    )


def enqueue_dashboard_claim_job(mission_id: int, claimer: str = "DM Dashboard", title: str = "") -> int:
    """Queue a dashboard claim job durably; returns the job id."""
    ensure_bot_job_tables()
    db.execute(
        """
        INSERT INTO dashboard_claim_jobs (mission_id, claimer, title, status, attempts, last_error)
        VALUES (%s, %s, %s, 'queued', 0, NULL)
        ON DUPLICATE KEY UPDATE
            claimer=VALUES(claimer),
            title=VALUES(title),
            status=IF(status IN ('done','processing','failed'), status, 'queued'),
            last_error=NULL,
            updated_at=NOW()
        """,
        (int(mission_id), claimer, title),
    )
    row = db.fetch_one("SELECT id FROM dashboard_claim_jobs WHERE mission_id=%s", (int(mission_id),))
    return int(row["id"]) if row else 0


def enqueue_module_generation_job(mission_id: int, claimer: str = "DM Dashboard") -> int:
    """Queue module generation durably; returns the job id."""
    ensure_bot_job_tables()
    db.execute(
        """
        INSERT INTO module_generation_jobs (mission_id, claimer, status, attempts, last_error)
        VALUES (%s, %s, 'queued', 0, NULL)
        ON DUPLICATE KEY UPDATE
            claimer=VALUES(claimer),
            status=IF(status IN ('done','processing','failed'), status, 'queued'),
            last_error=NULL,
            updated_at=NOW()
        """,
        (int(mission_id), claimer),
    )
    row = db.fetch_one("SELECT id FROM module_generation_jobs WHERE mission_id=%s", (int(mission_id),))
    return int(row["id"]) if row else 0


def _claim_next_job(table: str, stale_minutes: int = 180, max_attempts: int = 3) -> Optional[Dict]:
    ensure_bot_job_tables()
    token = uuid.uuid4().hex
    db.execute(
        f"""
        UPDATE {table}
        SET status='failed', locked_by=NULL, last_error='Max attempts exceeded', updated_at=NOW()
        WHERE status IN ('queued','processing')
          AND attempts >= %s
        """,
        (int(max_attempts),),
    )
    db.execute(
        f"""
        UPDATE {table}
        SET status='queued', locked_by=NULL
        WHERE status='processing'
          AND started_at IS NOT NULL
          AND started_at < (NOW() - INTERVAL %s MINUTE)
          AND attempts < %s
        """,
        (int(stale_minutes), int(max_attempts)),
    )
    affected = db.execute(
        f"""
        UPDATE {table}
        SET status='processing', locked_by=%s, attempts=attempts+1, started_at=NOW(), updated_at=NOW()
        WHERE status='queued'
          AND attempts < %s
        ORDER BY created_at ASC, id ASC
        LIMIT 1
        """,
        (token, int(max_attempts)),
    )
    if not affected:
        return None
    return db.fetch_one(f"SELECT * FROM {table} WHERE locked_by=%s LIMIT 1", (token,))


def claim_next_dashboard_claim_job(stale_minutes: int = 30) -> Optional[Dict]:
    return _claim_next_job("dashboard_claim_jobs", stale_minutes=stale_minutes, max_attempts=3)


def claim_next_module_generation_job(stale_minutes: int = 180) -> Optional[Dict]:
    return _claim_next_job("module_generation_jobs", stale_minutes=stale_minutes, max_attempts=2)


def finish_dashboard_claim_job(job_id: int, success: bool, message: str = "") -> None:
    ensure_bot_job_tables()
    status = "done" if success else "failed"
    db.execute(
        "UPDATE dashboard_claim_jobs SET status=%s, last_error=%s, finished_at=NOW(), updated_at=NOW(), locked_by=NULL WHERE id=%s",
        (status, None if success else message[:2000], int(job_id)),
    )


def finish_module_generation_job(job_id: int, success: bool, message: str = "", module_slug: str = "") -> None:
    ensure_bot_job_tables()
    status = "done" if success else "failed"
    db.execute(
        "UPDATE module_generation_jobs SET status=%s, last_error=%s, module_slug=%s, finished_at=NOW(), updated_at=NOW(), locked_by=NULL WHERE id=%s",
        (status, None if success else message[:2000], module_slug or None, int(job_id)),
    )


def get_latest_dashboard_claim_job(mission_id: int) -> Optional[Dict]:
    ensure_bot_job_tables()
    return db.fetch_one("SELECT * FROM dashboard_claim_jobs WHERE mission_id=%s LIMIT 1", (int(mission_id),))


def get_latest_module_generation_job(mission_id: int) -> Optional[Dict]:
    ensure_bot_job_tables()
    return db.fetch_one("SELECT * FROM module_generation_jobs WHERE mission_id=%s LIMIT 1", (int(mission_id),))


def get_character_memory_text() -> str:
    """Return all player characters as the legacy ---CHARACTER--- block format.

    Used by modules that still need the RAG text format. MySQL is the source
    of truth; stale campaign_docs fallbacks are intentionally not used.
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


# ---------------------------------------------------------------------------
# Treasure Items
# ---------------------------------------------------------------------------

def get_treasure_items(
    category: str = None,
    rarity: str = None,
    limit: int = 1,
) -> List[Dict]:
    """
    Pull random treasure items from treasure_items table.

    Args:
        category: 'gadget', 'utility', 'food', 'elemental_gem', 'magic_item', or None for any
        rarity:   'common', 'uncommon', 'rare', 'very_rare', or None for any
        limit:    number of items to return

    Returns:
        List of item dicts with name, category, item_type, effect, charges, ec_value, kharma_value, rarity
    """
    clauses = ["enabled = 1"]
    params: list = []
    if category:
        clauses.append("category = %s")
        params.append(category)
    if rarity:
        clauses.append("rarity = %s")
        params.append(rarity)
    params.append(limit)
    where = " AND ".join(clauses)
    return raw_query(
        f"SELECT name, category, item_type, effect, charges, ec_value, kharma_value, rarity "
        f"FROM treasure_items WHERE {where} ORDER BY RAND() LIMIT %s",
        tuple(params),
    ) or []


# ---------------------------------------------------------------------------
# NPC history helpers
# ---------------------------------------------------------------------------
import re as _re

_EVENT_TYPE_PATTERNS = [
    ("death",       _re.compile(r'\b(killed|died|succumbed|dead|deceased|absorbed)\b', _re.I)),
    ("resurrection",_re.compile(r'\b(resurrect|returned from death|raised|returned as undead|reanimat)\b', _re.I)),
    ("injury",      _re.compile(r'\binjured\b', _re.I)),
    ("recovery",    _re.compile(r'\brecovered\b', _re.I)),
    ("promotion",   _re.compile(r'\bpromoted\b', _re.I)),
    ("demotion",    _re.compile(r'\bdemoted\b', _re.I)),
    ("defection",   _re.compile(r'\bdefected\b', _re.I)),
    ("betrayal",    _re.compile(r'\bbetrayal\b', _re.I)),
    ("secret",      _re.compile(r'\bsecret\b', _re.I)),
    ("alliance",    _re.compile(r'\balliance\b', _re.I)),
    ("doppelganger",_re.compile(r'\bdoppelganger\b', _re.I)),
    ("incident",    _re.compile(r'\bpublic incident\b', _re.I)),
    ("introduced",  _re.compile(r'\bintroduced\b', _re.I)),
    ("hired",       _re.compile(r'\bhired\b', _re.I)),
    ("poached",     _re.compile(r'\bpoached\b', _re.I)),
    ("terminated",  _re.compile(r'\b(fired|left|resigned|terminated)\b', _re.I)),
]

def _infer_event_type(body: str) -> str:
    for etype, pat in _EVENT_TYPE_PATTERNS:
        if pat.search(body):
            return etype
    return "event"


_DATE_PAT = _re.compile(r'^\[(\d{4}-\d{2}-\d{2})\]')


def add_npc_history_event(npc_id: int, body: str, event_date=None) -> None:
    """Insert one history event for an NPC. Parses date from body if not given."""
    if not npc_id or not body:
        return
    if event_date is None:
        m = _DATE_PAT.match(body.strip())
        event_date = m.group(1) if m else None
    etype = _infer_event_type(body)
    raw_execute(
        "INSERT INTO npc_history (npc_id, event_date, event_type, body) VALUES (%s, %s, %s, %s)",
        (npc_id, event_date, etype, body),
    )


def get_npc_history(npc_id: int, limit: int = 50) -> list:
    """Return history events for an NPC ordered oldest-first."""
    return raw_query(
        "SELECT id, event_date, event_type, body, created_at "
        "FROM npc_history WHERE npc_id = %s ORDER BY event_date ASC, id ASC LIMIT %s",
        (npc_id, limit),
    ) or []


def get_npc_history_count(npc_id: int) -> int:
    """Return number of history events for an NPC."""
    rows = raw_query("SELECT COUNT(*) AS n FROM npc_history WHERE npc_id = %s", (npc_id,))
    return rows[0]["n"] if rows else 0


# ---------------------------------------------------------------------------
# Party history helpers
# ---------------------------------------------------------------------------

def add_party_history_event(party_id: int, body: str, event_date=None) -> None:
    """Insert one history event for a party."""
    if not party_id or not body:
        return
    if event_date is None:
        m = _DATE_PAT.match(body.strip())
        event_date = m.group(1) if m else None
    raw_execute(
        "INSERT INTO party_history (party_id, event_date, body) VALUES (%s, %s, %s)",
        (party_id, event_date, body),
    )


def get_party_history(party_id: int, limit: int = 30) -> list:
    """Return history events for a party ordered oldest-first."""
    return raw_query(
        "SELECT id, event_date, body, created_at FROM party_history "
        "WHERE party_id = %s ORDER BY event_date ASC, id ASC LIMIT %s",
        (party_id, limit),
    ) or []


# ---------------------------------------------------------------------------
# NPC revealed secrets helpers
# ---------------------------------------------------------------------------

def add_revealed_secret(npc_id: int, secret: str) -> None:
    """Record a newly revealed NPC secret."""
    if not npc_id or not secret:
        return
    existing = raw_query(
        "SELECT id FROM npc_revealed_secrets WHERE npc_id=%s AND secret=%s LIMIT 1",
        (npc_id, secret)
    )
    if not existing:
        raw_execute(
            "INSERT INTO npc_revealed_secrets (npc_id, secret) VALUES (%s, %s)",
            (npc_id, secret)
        )


def get_revealed_secrets(npc_id: int) -> list:
    """Return list of revealed secret strings for an NPC."""
    rows = raw_query(
        "SELECT secret FROM npc_revealed_secrets WHERE npc_id=%s ORDER BY revealed_at ASC",
        (npc_id,)
    ) or []
    return [r["secret"] for r in rows]


def has_revealed_secrets(npc_id: int) -> bool:
    rows = raw_query(
        "SELECT COUNT(*) AS n FROM npc_revealed_secrets WHERE npc_id=%s",
        (npc_id,)
    )
    return bool(rows and rows[0]["n"] > 0)
