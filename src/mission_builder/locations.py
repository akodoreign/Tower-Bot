"""
locations.py — Gazetteer integration for mission location selection.

Provides functions to:
- Load and query the city gazetteer
- Find appropriate locations by faction, danger level, district
- Get establishments for investigation leads
- Build location context blocks for AI prompts
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "campaign_docs"

# Cache the gazetteer after first load
_gazetteer_cache: Optional[dict] = None
_gazetteer_cache_ts: float = 0.0
_gazetteer_cache_revision: str = ""
GAZETTEER_CACHE_TTL = float(os.getenv("GAZETTEER_CACHE_TTL", "300"))
_places_migrated: bool = False


def invalidate_gazetteer_cache() -> None:
    """Force the next gazetteer load to read from the source again."""
    global _gazetteer_cache, _gazetteer_cache_ts, _gazetteer_cache_revision
    _gazetteer_cache = None
    _gazetteer_cache_ts = 0.0
    _gazetteer_cache_revision = ""


def load_gazetteer() -> dict:
    """Load the city gazetteer from MySQL with revision-aware caching."""
    global _gazetteer_cache, _gazetteer_cache_ts, _gazetteer_cache_revision
    now = time.monotonic()

    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT content_json, updated_at FROM gazetteer LIMIT 1") or []
        if rows and rows[0].get("content_json"):
            revision = str(rows[0].get("updated_at") or "")
            if _gazetteer_cache is not None and revision and revision == _gazetteer_cache_revision:
                _gazetteer_cache_ts = now
                return _gazetteer_cache
            if (
                _gazetteer_cache is not None
                and not revision
                and (now - _gazetteer_cache_ts) < GAZETTEER_CACHE_TTL
            ):
                return _gazetteer_cache
            cj = rows[0]["content_json"]
            _gazetteer_cache = json.loads(cj) if isinstance(cj, str) else cj
            _gazetteer_cache_ts = now
            _gazetteer_cache_revision = revision
            return _gazetteer_cache
    except Exception:
        if _gazetteer_cache is not None and (now - _gazetteer_cache_ts) < GAZETTEER_CACHE_TTL:
            return _gazetteer_cache

    return {"districts": {}, "warrens_distribution": [], "underground_network": {}}


def get_districts_by_faction(faction: str) -> List[str]:
    """Get all districts where a faction has presence."""
    gaz = load_gazetteer()
    faction_lower = faction.lower()
    
    matches = []
    for district_name, district_data in gaz.get("districts", {}).items():
        factions = district_data.get("faction_presence", [])
        if any(faction_lower in f.lower() for f in factions):
            matches.append(district_name)
    
    return matches


def get_districts_by_danger(danger_level: str) -> List[str]:
    """Get districts matching a danger level (low, moderate, high, extreme, restricted)."""
    gaz = load_gazetteer()
    
    matches = []
    for district_name, district_data in gaz.get("districts", {}).items():
        if district_data.get("danger_level", "").lower() == danger_level.lower():
            matches.append(district_name)
    
    return matches


def get_district_info(district_name: str) -> Optional[dict]:
    """Get full info for a specific district."""
    gaz = load_gazetteer()
    return gaz.get("districts", {}).get(district_name)


def get_establishments_in_district(district_name: str, establishment_type: Optional[str] = None) -> List[dict]:
    """Get notable establishments in a district, optionally filtered by type."""
    info = get_district_info(district_name)
    if not info:
        return []
    
    establishments = info.get("notable_establishments", [])
    
    if establishment_type:
        type_lower = establishment_type.lower()
        establishments = [e for e in establishments if e.get("type", "").lower() == type_lower]
    
    return establishments


def get_sub_areas(district_name: str) -> List[dict]:
    """Get sub-areas within a district."""
    info = get_district_info(district_name)
    if not info:
        return []
    
    return info.get("sub_areas", [])


def get_underground_locations(section: str = "all") -> List[dict]:
    """Get underground locations (sewers, lairs, dungeons, sanctums, etc.)"""
    gaz = load_gazetteer()
    underground = gaz.get("underground_network", {})
    
    if section == "all":
        locations = []
        for key in ["sewers", "lairs", "dungeons", "sanctums", "special_underground"]:
            data = underground.get(key, {})
            if isinstance(data, dict):
                if "locations" in data:
                    locations.extend(data["locations"])
                elif "major_sections" in data:
                    locations.extend(data["major_sections"])
        return locations
    
    data = underground.get(section, {})
    if isinstance(data, dict):
        return data.get("locations", data.get("major_sections", []))
    return []


def get_dungeons() -> List[dict]:
    """Get all dungeon locations."""
    return get_underground_locations("dungeons")


def get_lairs() -> List[dict]:
    """Get all creature lair locations."""
    return get_underground_locations("lairs")


def get_sanctums() -> List[dict]:
    """Get all secret sanctum locations."""
    return get_underground_locations("sanctums")


def get_warrens() -> List[dict]:
    """Get all warren distribution areas."""
    gaz = load_gazetteer()
    return gaz.get("warrens_distribution", [])


def find_location_for_mission(
    faction: Optional[str] = None,
    tier: Optional[str] = None,
    location_type: Optional[str] = None,
) -> Tuple[str, dict]:
    """
    Find an appropriate location for a mission based on parameters.
    
    Args:
        faction: Posting faction (prefers their territory)
        tier: Mission tier (higher tiers can access more dangerous areas)
        location_type: Specific type wanted (dungeon, lair, establishment, etc.)
    
    Returns:
        (location_name, location_details_dict)
    """
    gaz = load_gazetteer()
    
    # Determine appropriate danger levels based on tier
    tier_danger_map = {
        "local": ["low"],
        "patrol": ["low", "moderate"],
        "escort": ["low", "moderate"],
        "standard": ["low", "moderate"],
        "investigation": ["low", "moderate", "high"],
        "rift": ["high", "extreme"],
        "dungeon": ["high", "extreme"],
        "major": ["moderate", "high"],
        "inter-guild": ["moderate", "high"],
        "high-stakes": ["high", "extreme"],
        "epic": ["high", "extreme", "restricted"],
        "divine": ["high", "extreme", "restricted"],
        "tower": ["restricted"],
    }
    
    allowed_dangers = tier_danger_map.get(tier.lower() if tier else "standard", ["low", "moderate"])
    
    # If looking for a dungeon specifically
    if location_type == "dungeon":
        dungeons = get_dungeons()
        if dungeons:
            choice = random.choice(dungeons)
            return (choice.get("name", "Unknown Dungeon"), choice)
    
    # If looking for a lair
    if location_type == "lair":
        lairs = get_lairs()
        valid_lairs = [l for l in lairs if l.get("danger_level", "").lower() in allowed_dangers]
        if valid_lairs:
            choice = random.choice(valid_lairs)
            return (choice.get("name", "Unknown Lair"), choice)
    
    # If looking for underground
    if location_type == "underground":
        underground = get_underground_locations()
        if underground:
            choice = random.choice(underground)
            return (choice.get("name", "Unknown Underground"), choice)
    
    # Default: find a district
    candidate_districts = []
    
    # Prefer faction territory
    if faction:
        faction_districts = get_districts_by_faction(faction)
        candidate_districts.extend(faction_districts)
    
    # Add districts matching danger level
    for danger in allowed_dangers:
        candidate_districts.extend(get_districts_by_danger(danger))
    
    # Remove duplicates while preserving order
    seen = set()
    unique_districts = []
    for d in candidate_districts:
        if d not in seen:
            seen.add(d)
            unique_districts.append(d)
    
    if not unique_districts:
        # Fallback to any district
        unique_districts = list(gaz.get("districts", {}).keys())
    
    if unique_districts:
        district_name = random.choice(unique_districts)
        district_info = get_district_info(district_name)
        return (district_name, district_info or {})
    
    return ("Markets Infinite", {})


def build_location_context(district_name: str, include_underground: bool = False) -> str:
    """
    Build a context block describing a location for AI prompts.
    
    Returns a formatted string with district info, sub-areas, and establishments.
    """
    info = get_district_info(district_name)
    if not info:
        return f"Location: {district_name} (no detailed info available)"
    
    lines = [
        f"LOCATION: {district_name}",
        f"Ring: {info.get('ring', '?')} | Danger: {info.get('danger_level', 'unknown')}",
        f"Description: {info.get('description', 'No description')}",
        f"Factions Present: {', '.join(info.get('faction_presence', ['None']))}",
    ]
    
    # Add sub-areas
    sub_areas = info.get("sub_areas", [])
    if sub_areas:
        lines.append("\nSUB-AREAS:")
        for area in sub_areas[:5]:  # Limit to 5
            if isinstance(area, dict):
                name = area.get("name", "Unknown")
                desc = area.get("description", "")
                lines.append(f"  - {name}: {desc}")
    
    # Add establishments
    establishments = info.get("notable_establishments", [])
    if establishments:
        lines.append("\nNOTABLE ESTABLISHMENTS:")
        for est in establishments[:5]:  # Limit to 5
            name = est.get("name", "Unknown")
            est_type = est.get("type", "")
            desc = est.get("description", "")
            lines.append(f"  - {name} ({est_type}): {desc}")
    
    # Optionally add underground connections
    if include_underground:
        gaz = load_gazetteer()
        underground = gaz.get("underground_network", {})
        
        # Check sewers
        sewers = underground.get("sewers", {}).get("major_sections", [])
        for sewer in sewers:
            if district_name.lower() in sewer.get("name", "").lower():
                lines.append(f"\nUNDERGROUND ACCESS: {sewer.get('name')} — {sewer.get('description', '')}")
                break
    
    # Add new place types
    place_ctx = build_place_context(district_name)
    if place_ctx:
        lines.append("")
        lines.append(place_ctx)

    return "\n".join(lines)


def get_establishments_for_leads(
    faction: Optional[str] = None,
    district: Optional[str] = None,
    count: int = 3
) -> List[dict]:
    """
    Get establishments suitable for investigation leads.
    
    Returns establishments with contact potential: taverns, shops, offices, etc.
    """
    gaz = load_gazetteer()
    
    lead_types = ["tavern", "shop", "office", "info_broker", "inn", "market", "guild_hall"]
    all_establishments = []
    
    districts_to_search = []
    
    if district:
        districts_to_search = [district]
    elif faction:
        districts_to_search = get_districts_by_faction(faction)
    
    if not districts_to_search:
        districts_to_search = list(gaz.get("districts", {}).keys())
    
    for dist_name in districts_to_search:
        info = get_district_info(dist_name)
        if not info:
            continue
        
        for est in info.get("notable_establishments", []):
            if est.get("type", "").lower() in lead_types:
                est_copy = est.copy()
                est_copy["district"] = dist_name
                all_establishments.append(est_copy)
    
    # Shuffle and return requested count
    random.shuffle(all_establishments)
    return all_establishments[:count]


def format_lead_locations(establishments: List[dict]) -> str:
    """Format a list of establishments as a context block for prompts."""
    if not establishments:
        return "(No specific establishments found)"
    
    lines = ["INVESTIGATION LOCATIONS:"]
    for est in establishments:
        name = est.get("name", "Unknown")
        est_type = est.get("type", "")
        desc = est.get("description", "")
        district = est.get("district", "")
        lines.append(f"  - {name} ({est_type}) in {district}: {desc}")
    
    return "\n".join(lines)


def get_random_warren() -> dict:
    """Get a random warren area for Warrens-based missions."""
    warrens = get_warrens()
    if warrens:
        return random.choice(warrens)
    return {"name": "Eastern Warrens", "description": "Unknown warren area", "danger_level": "high"}


def get_transit_info() -> dict:
    """Get transportation network info."""
    gaz = load_gazetteer()
    return gaz.get("transportation", {})


# ---------------------------------------------------------------------------
# New place-type accessors (places_of_interest, small_shops, parks, malls)
# ---------------------------------------------------------------------------

def get_places_of_interest(district_name: Optional[str] = None) -> List[dict]:
    """Return places_of_interest, optionally filtered by district."""
    return _collect_place_type("places_of_interest", district_name)


def get_small_shops(district_name: Optional[str] = None, shop_type: Optional[str] = None) -> List[dict]:
    """Return small_shops, optionally filtered by district and/or type tag."""
    shops = _collect_place_type("small_shops", district_name)
    if shop_type:
        shops = [s for s in shops if shop_type.lower() in s.get("type", "").lower()]
    return shops


def get_parks(district_name: Optional[str] = None) -> List[dict]:
    """Return parks/green spaces, optionally filtered by district."""
    return _collect_place_type("parks", district_name)


def get_malls(district_name: Optional[str] = None) -> List[dict]:
    """Return market malls/covered bazaars, optionally filtered by district."""
    return _collect_place_type("malls", district_name)


def _collect_place_type(field: str, district_name: Optional[str] = None) -> List[dict]:
    """Collect entries from a named list field across all (or one) district(s)."""
    gaz = load_gazetteer()
    results: List[dict] = []
    districts = gaz.get("districts", {})
    targets = {district_name: districts[district_name]} if district_name and district_name in districts else districts
    for dist, info in targets.items():
        for item in info.get(field, []):
            entry = dict(item)
            entry.setdefault("district", dist)
            results.append(entry)
    return results


def get_all_places(district_name: Optional[str] = None) -> dict:
    """Return all place types for a district (or all districts) in one call."""
    return {
        "places_of_interest": get_places_of_interest(district_name),
        "small_shops": get_small_shops(district_name),
        "parks": get_parks(district_name),
        "malls": get_malls(district_name),
    }


def get_random_shop(district_name: Optional[str] = None) -> Optional[dict]:
    """Return a random small shop, optionally from a specific district."""
    shops = get_small_shops(district_name)
    return random.choice(shops) if shops else None


def get_random_place_of_interest(district_name: Optional[str] = None) -> Optional[dict]:
    """Return a random place of interest, optionally from a specific district."""
    pois = get_places_of_interest(district_name)
    return random.choice(pois) if pois else None


def build_place_context(district_name: str) -> str:
    """
    Build a prompt context block for shops, POIs, parks, and malls in a district.
    Extends build_location_context() with the new place types.
    """
    places = get_all_places(district_name)
    lines: List[str] = []

    pois = places["places_of_interest"]
    if pois:
        lines.append("PLACES OF INTEREST:")
        for p in pois[:4]:
            lines.append(f"  - {p.get('name', '?')} ({p.get('type', 'landmark')}): {p.get('description', '')}")

    shops = places["small_shops"]
    if shops:
        lines.append("SMALL SHOPS:")
        for s in shops[:4]:
            lines.append(f"  - {s.get('name', '?')} ({s.get('type', 'shop')}): {s.get('description', '')}")

    parks = places["parks"]
    if parks:
        lines.append("PARKS & OPEN SPACES:")
        for pk in parks[:3]:
            lines.append(f"  - {pk.get('name', '?')}: {pk.get('description', '')}")

    malls = places["malls"]
    if malls:
        lines.append("MARKET MALLS / COVERED BAZAARS:")
        for m in malls[:3]:
            lines.append(f"  - {m.get('name', '?')}: {m.get('description', '')}")

    return "\n".join(lines) if lines else ""


# ---------------------------------------------------------------------------
# DB persistence helpers for places
# ---------------------------------------------------------------------------

def migrate_places_to_db() -> int:
    """
    One-time migration: load all place types from city_gazetteer.json into gazetteer_places table.
    Returns count of rows inserted.
    Idempotent — safe to call multiple times (uses INSERT IGNORE).
    """
    try:
        from src.db_api import raw_execute
    except ImportError:
        return 0

    raw_execute("""
        CREATE TABLE IF NOT EXISTS gazetteer_places (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            district    VARCHAR(100) NOT NULL,
            place_type  ENUM('place_of_interest','small_shop','park','mall') NOT NULL,
            name        VARCHAR(200) NOT NULL,
            type_tag    VARCHAR(100),
            description TEXT,
            extra_json  JSON,
            UNIQUE KEY uq_place (district, place_type, name),
            INDEX idx_district (district),
            INDEX idx_type (place_type)
        )
    """)

    gaz = load_gazetteer()
    total = 0
    field_map = {
        "places_of_interest": "place_of_interest",
        "small_shops": "small_shop",
        "parks": "park",
        "malls": "mall",
    }

    for district, info in gaz.get("districts", {}).items():
        for json_field, db_type in field_map.items():
            for item in info.get(json_field, []):
                import json as _json
                name = item.get("name", "")
                if not name:
                    continue
                type_tag = item.get("type", "")
                description = item.get("description", "")
                # Stash everything else in extra_json
                extra = {k: v for k, v in item.items() if k not in ("name", "type", "description")}
                try:
                    raw_execute(
                        """INSERT IGNORE INTO gazetteer_places
                           (district, place_type, name, type_tag, description, extra_json)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (district, db_type, name, type_tag, description,
                         _json.dumps(extra, ensure_ascii=False) if extra else None),
                    )
                    total += 1
                except Exception:
                    pass

    return total


def query_places_from_db(
    district: Optional[str] = None,
    place_type: Optional[str] = None,
    limit: int = 20,
) -> List[dict]:
    """
    Query gazetteer_places from DB. Falls back to JSON on DB failure.
    place_type: 'place_of_interest' | 'small_shop' | 'park' | 'mall'
    """
    try:
        from src.db_api import raw_query
        clauses = []
        params: list = []
        if district:
            clauses.append("district = %s")
            params.append(district)
        if place_type:
            clauses.append("place_type = %s")
            params.append(place_type)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = raw_query(f"SELECT * FROM gazetteer_places {where} LIMIT %s", (*params, limit)) or []
        return list(rows)
    except Exception:
        # Fallback to in-memory JSON
        field_map = {
            "place_of_interest": "places_of_interest",
            "small_shop": "small_shops",
            "park": "parks",
            "mall": "malls",
        }
        json_field = field_map.get(place_type, "") if place_type else None
        if json_field:
            return _collect_place_type(json_field, district)[:limit]
        results = []
        for f in field_map.values():
            results.extend(_collect_place_type(f, district))
        return results[:limit]


# Auto-migrate on module import (best-effort — silently skipped if DB is unavailable)
try:
    migrate_places_to_db()
    _places_migrated = True
except Exception:
    pass
