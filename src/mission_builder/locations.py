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
import random
from pathlib import Path
from typing import List, Dict, Optional, Tuple

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "campaign_docs"
GAZETTEER_FILE = DOCS_DIR / "city_gazetteer.json"

# Cache the gazetteer after first load
_gazetteer_cache: Optional[dict] = None


def load_gazetteer() -> dict:
    """Load the city gazetteer from MySQL (cached after first call, falls back to file)."""
    global _gazetteer_cache
    if _gazetteer_cache is not None:
        return _gazetteer_cache

    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT content_json FROM gazetteer LIMIT 1") or []
        if rows and rows[0].get("content_json"):
            cj = rows[0]["content_json"]
            _gazetteer_cache = json.loads(cj) if isinstance(cj, str) else cj
            return _gazetteer_cache
    except Exception:
        pass

    if not GAZETTEER_FILE.exists():
        return {"districts": {}, "warrens_distribution": [], "underground_network": {}}

    try:
        _gazetteer_cache = json.loads(GAZETTEER_FILE.read_text(encoding="utf-8"))
        return _gazetteer_cache
    except Exception:
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
