"""
battle_map_library.py — Query interface for the battle_maps_library DB table.

Mission pipelines call get_battle_map() to fetch a contextually appropriate
map without generating one from scratch.

All reads go through DB — no file scanning.
"""
from __future__ import annotations

import json
import random
import re
import shutil
from pathlib import Path
from typing import Optional

from src.db_api import raw_execute, raw_query
from src.log import logger


def get_battle_map(
    district_slug: str = "",
    mission_type: str = "",
    map_type: str = "",
    wealth_tier: str = "",
    size_class: str = "",
    min_score: int = 0,
    exclude_paths: list[str] | None = None,
) -> Optional[dict]:
    """
    Return a random suitable map row from battle_maps_library.

    Matching priority:
      1. district_slug + mission_type (most specific)
      2. mission_type only
      3. map_type only
      4. Any analyzed map

    Returns the full DB row dict, or None if no match found.
    """
    exclude_paths = exclude_paths or []

    base_clauses, base_params = _battle_map_base_filters(
        wealth_tier=wealth_tier,
        size_class=size_class,
        min_score=min_score,
        exclude_paths=exclude_paths,
    )
    stages: list[tuple[str, list[str], list]] = []

    # When map_type is provided, include it in the more-specific stages first
    # so an explicit office/dungeon/street request isn't beaten by a broad mission-type tag.
    if district_slug and mission_type and map_type:
        stages.append((
            "district+mission_type+map_type",
            [
                "JSON_CONTAINS(suitable_districts, %s)",
                "JSON_CONTAINS(suitable_mission_types, %s)",
                "map_type = %s",
            ],
            [json.dumps(district_slug), json.dumps(mission_type), map_type],
        ))
    if district_slug and mission_type:
        stages.append((
            "district+mission_type",
            [
                "JSON_CONTAINS(suitable_districts, %s)",
                "JSON_CONTAINS(suitable_mission_types, %s)",
            ],
            [json.dumps(district_slug), json.dumps(mission_type)],
        ))
    if mission_type and map_type:
        stages.append((
            "mission_type+map_type",
            ["JSON_CONTAINS(suitable_mission_types, %s)", "map_type = %s"],
            [json.dumps(mission_type), map_type],
        ))
    if map_type:
        stages.append(("map_type", ["map_type = %s"], [map_type]))
    if mission_type:
        stages.append((
            "mission_type",
            ["JSON_CONTAINS(suitable_mission_types, %s)"],
            [json.dumps(mission_type)],
        ))

    stages.append(("any analyzed", ["analyzed_at IS NOT NULL"], []))

    for label, stage_clauses, stage_params in stages:
        clauses = [*base_clauses, *stage_clauses]
        params = [*base_params, *stage_params]
        where = "WHERE " + " AND ".join(clauses)
        # Deprioritise recently-used maps: push maps used in the last 24h to the back,
        # then randomise within each bucket so variety improves across a session.
        sql = (
            f"SELECT * FROM battle_maps_library {where} "
            "ORDER BY (analyzed_at IS NOT NULL) DESC, "
            "(last_used_at IS NOT NULL AND last_used_at > NOW() - INTERVAL 2 HOUR) ASC, "
            "RAND() LIMIT 1"
        )
        try:
            rows = raw_query(sql, tuple(params))
            if rows:
                row = rows[0]
                # Stamp use immediately so the next call within the same session avoids it
                try:
                    raw_execute(
                        "UPDATE battle_maps_library SET last_used_at=NOW(), use_count=use_count+1 WHERE id=%s",
                        (row["id"],),
                    )
                except Exception:
                    pass
                return row
        except Exception as e:
            logger.warning(f"battle_map_library: {label} query failed: {e}")

    return None

    # Fallback: loosen constraints — drop district, keep mission type
def get_maps_for_mission(mission: dict, count: int = 1) -> list[dict]:
    """
    Pull N maps for a mission dict.
    Returns list of map rows — each has .id, .file_path, and format_map_ref().
    """
    mission_type  = _normalise_mission_type(mission.get("mission_type") or mission.get("type", ""))
    district_slug = _district_from_mission(mission) or _faction_to_district(mission.get("faction", ""))
    tier          = _tier_to_wealth(mission.get("difficulty") or mission.get("tier", ""))
    memory_key    = _memory_key_for_mission(mission, district_slug)
    map_type      = _map_type_from_mission(mission, mission_type)

    results = []
    seen: list[str] = []
    for _ in range(count):
        if memory_key:
            remembered = get_remembered_battle_map(memory_key, mission_type=mission_type, map_type=map_type)
            if remembered and remembered.get("file_path") not in seen:
                results.append(remembered)
                seen.append(remembered["file_path"])
                continue

        row = get_battle_map(
            district_slug=district_slug,
            mission_type=mission_type,
            map_type=map_type,
            wealth_tier=tier,
            exclude_paths=seen,
        )
        if row:
            if memory_key:
                remember_battle_map(
                    memory_key,
                    row,
                    mission=mission,
                    mission_type=mission_type,
                    district_slug=district_slug,
                    map_type=map_type,
                )
            results.append(row)
            seen.append(row["file_path"])
    return results


def get_remembered_battle_map(
    memory_key: str,
    mission_type: str = "",
    map_type: str = "",
) -> Optional[dict]:
    """Return the remembered map for a canonical area key, if it still exists.

    Maps used within the last 4 hours are excluded — this breaks bakeoff/rapid-
    generation sticky loops while preserving long-term area consistency.
    """
    if not memory_key:
        return None
    try:
        _ensure_map_memory_table()
        map_clause = " AND m.map_type=%s" if map_type else ""
        params = [memory_key, mission_type, mission_type]
        if map_type:
            params.append(map_type)
        params.append(mission_type)
        rows = raw_query(
            "SELECT m.battle_map_id FROM battle_map_area_memory m "
            "JOIN battle_maps_library b ON b.id=m.battle_map_id "
            "WHERE m.area_key=%s AND (m.mission_type=%s OR m.mission_type='' OR %s='') "
            "AND b.file_path IS NOT NULL AND b.file_path<>'' "
            "AND (b.last_used_at IS NULL OR b.last_used_at < NOW() - INTERVAL 4 HOUR) "
            f"{map_clause} "
            "ORDER BY m.mission_type=%s DESC, m.use_count DESC, m.last_used_at DESC LIMIT 1",
            tuple(params),
        ) or []
        if not rows:
            return None
        map_rows = raw_query("SELECT * FROM battle_maps_library WHERE id=%s LIMIT 1", (rows[0]["battle_map_id"],)) or []
        if map_rows:
            raw_execute(
                "UPDATE battle_map_area_memory SET use_count=use_count+1, last_used_at=NOW() "
                "WHERE area_key=%s AND battle_map_id=%s",
                (memory_key, rows[0]["battle_map_id"]),
            )
            return map_rows[0]
    except Exception as e:
        logger.warning(f"battle_map_library: remembered map lookup failed: {e}")
    return None


def remember_battle_map(
    memory_key: str,
    row: dict,
    mission: dict | None = None,
    mission_type: str = "",
    district_slug: str = "",
    map_type: str = "",
) -> None:
    """Persist the selected map for a named area so future missions stay consistent."""
    if not memory_key or not row or not row.get("id"):
        return
    mission = mission or {}
    map_type = map_type or str(row.get("map_type") or "")
    try:
        _ensure_map_memory_table()
        raw_execute(
            "INSERT INTO battle_map_area_memory "
            "(area_key, area_name, district_slug, mission_type, map_type, battle_map_id, map_file_path, source_mission_title, use_count, last_used_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,NOW()) "
            "ON DUPLICATE KEY UPDATE use_count=use_count+1, last_used_at=NOW(), "
            "area_name=VALUES(area_name), district_slug=VALUES(district_slug), "
            "battle_map_id=VALUES(battle_map_id), map_file_path=VALUES(map_file_path), "
            "source_mission_title=VALUES(source_mission_title)",
            (
                memory_key,
                _area_name_for_mission(mission) or memory_key,
                district_slug,
                mission_type,
                map_type,
                row["id"],
                row.get("file_path", ""),
                mission.get("title", ""),
            ),
        )
    except Exception as e:
        logger.warning(f"battle_map_library: remember map failed: {e}")


def _map_too_small(path: Path, min_short_side: int = 700, min_pixels: int = 600_000) -> bool:
    """True if an image is too small to serve as a battle map (likely a thumbnail
    or preview, e.g. 442x665). Header-only read; fails open so a missing PIL or an
    unreadable file never blocks map selection."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
    except Exception as e:
        logger.debug(f"battle_map_library: could not read map size for {path} ({e}); allowing")
        return False
    return min(w, h) < min_short_side or (w * h) < min_pixels


def copy_library_map_for_mission(
    mission: dict,
    out_path: Path | str,
    *,
    mission_type: str = "",
    location_name: str = "",
    district: str = "",
    description: str = "",
    map_type: str = "",
) -> Optional[Path]:
    """
    Select a remembered/library map for a mission/location and copy it to out_path.

    This is the low-friction adapter for mission pipelines that historically
    generated one bespoke map file. It preserves their expected output filename
    while moving selection to battle_maps_library and battle_map_area_memory.
    """
    if not _library_enabled():
        return None

    out = Path(out_path)
    hint = dict(mission or {})
    if mission_type:
        hint["mission_type"] = mission_type
        hint["type"] = mission_type
    if location_name:
        hint["location_name"] = location_name
        hint["location"] = location_name
        hint.setdefault("area", location_name)
    if district:
        hint["district"] = district
    if description:
        hint["description"] = description
    if map_type:
        hint["map_type"] = map_type
    if location_name or district:
        hint["map_memory_key"] = f"{district}:{location_name}" if district else location_name

    for _ in range(5):
        rows = get_maps_for_mission(hint, count=1)
        if not rows:
            return None

        row = rows[0]
        src = Path(row.get("file_path") or "")
        if src.exists():
            if _map_too_small(src):
                logger.warning(
                    f"battle_map_library: rejecting undersized map #{row.get('id')} "
                    f"({src.name}) - too small to be a battle map"
                )
                _mark_stale_library_map(row, reason="undersized map (thumbnail/preview)")
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
            try:
                from src.mission_builder.vtt_renderer import write_grid_sidecar
                hint["library_map_id"] = row.get("id")
                hint["library_map_type"] = row.get("map_type") or ""
                write_grid_sidecar(out, hint)
            except Exception as _sidecar_err:
                logger.debug(f"battle_map_library: sidecar write failed (non-fatal): {_sidecar_err}")
            logger.info(f"battle_map_library: copied map #{row.get('id')} -> {out.name}")
            return out

        logger.warning(f"battle_map_library: selected map file missing: {src}")
        _mark_stale_library_map(row, reason="copy source missing")

    return None


def format_map_ref(row: dict) -> str:
    """
    Return the DM-facing map reference string for a module.
    Pipeline output should include this wherever a map is relevant.

    Example:
      Map #42 — sewer | score 2381
      File: campaign_docs/battle_maps/_downloaded/sewer/002381_steps_out_of_the_underdark.png
      Tags: dark, flooded, multi-room, underground
      Notes: Central flooded chamber with narrow raised walkways forces single-file movement.
    """
    map_id    = row.get("id", "?")
    map_type  = row.get("map_type", "")
    score     = row.get("reddit_score", 0)
    file_path = row.get("file_path", "")
    tags      = row.get("tags") or []
    notes     = row.get("analysis_notes", "")
    title     = row.get("reddit_title", "")

    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []

    # Make path relative to project root for readability
    try:
        rel = Path(file_path).relative_to(Path(file_path).parts[0])
        display_path = str(rel)
    except Exception:
        display_path = file_path

    lines = [f"Map #{map_id} — {map_type} | score {score}"]
    if title:
        lines.append(f'"{title}"')
    lines.append(f"File: {display_path}")
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")
    if notes:
        lines.append(f"Notes: {notes}")
    return "\n".join(lines)


def library_stats() -> dict:
    """Return {total, analyzed, by_type} summary dict."""
    try:
        rows = raw_query(
            "SELECT map_type, COUNT(*) AS n, SUM(analyzed_at IS NOT NULL) AS done "
            "FROM battle_maps_library GROUP BY map_type"
        ) or []
        total    = sum(r["n"] for r in rows)
        analyzed = sum(r["done"] or 0 for r in rows)
        by_type  = {r["map_type"]: {"total": r["n"], "analyzed": r["done"] or 0} for r in rows}
        return {"total": total, "analyzed": analyzed, "by_type": by_type}
    except Exception as e:
        logger.warning(f"battle_map_library: stats failed: {e}")
        return {"total": 0, "analyzed": 0, "by_type": {}}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FACTION_DISTRICT: dict[str, str] = {
    "Iron Fang Consortium":   "scrapworks",
    "Obsidian Lotus":         "night_pits",
    "The Syndicate":          "grand_forum",
    "Wardens of the Dome":    "outer_wall",
    "Tower Authority":        "tower_of_last_chance",
    "Merchant League":        "cobbleway_market",
    "Cult of the Void":       "collapsed_plaza",
    "Patchwork Saints":       "shantytown_heights",
    "Arcane Registry":        "archive_row",
    "Church of Ashara":       "ashfall_terraces",
}

_MISSION_TYPE_ALIASES: dict[str, str] = {
    "strange occurrence": "strange_occurrences",
    "strange occurrences": "strange_occurrences",
    "strange_occurrence": "strange_occurrences",
    "strange_occurrences": "strange_occurrences",
    "first contact": "first_contact",
    "first-contact": "first_contact",
    "gathering": "gather",
    "gather": "gather",
    "retrieval": "recovery",
    "recovery": "recovery",
    "theft": "heist",
    "courier": "escort",
    "delivery": "escort",
    "political": "negotiation",
}

_DISTRICT_CACHE: dict[str, str] | None = None
_MAP_MEMORY_TABLE_READY = False

def _faction_to_district(faction: str) -> str:
    for key, slug in _FACTION_DISTRICT.items():
        if key.lower() in faction.lower():
            return slug
    return ""


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def _normalise_mission_type(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    key = re.sub(r"\s+", " ", raw.replace("_", " ").replace("-", " ")).strip()
    return _MISSION_TYPE_ALIASES.get(key) or _MISSION_TYPE_ALIASES.get(raw) or _slugify(raw)


def _known_districts() -> dict[str, str]:
    global _DISTRICT_CACHE
    if _DISTRICT_CACHE is not None:
        return _DISTRICT_CACHE

    out: dict[str, str] = {}
    try:
        rows = raw_query("SELECT DISTINCT district FROM gazetteer_places") or []
        for row in rows:
            name = str(row.get("district") or "")
            slug = _slugify(name)
            if name and slug:
                out[slug] = name
                out[name.lower()] = name
    except Exception as e:
        logger.warning(f"battle_map_library: district cache failed: {e}")

    _DISTRICT_CACHE = out
    return out


def _area_name_for_mission(mission: dict) -> str:
    for key in ("location_name", "location", "primary_location", "area", "district"):
        value = mission.get(key)
        if isinstance(value, dict):
            for sub_key in ("name", "district"):
                if value.get(sub_key):
                    return str(value[sub_key])
        elif value:
            return str(value)
    return ""


def _district_from_mission(mission: dict) -> str:
    candidates: list[str] = []
    for key in (
        "district_slug", "district", "area_slug", "area",
        "location_district", "primary_district", "primary_location",
        "location", "location_name",
    ):
        value = mission.get(key)
        if isinstance(value, dict):
            candidates.extend(str(value.get(k) or "") for k in ("district_slug", "district", "name"))
        elif value:
            candidates.append(str(value))

    known = _known_districts()
    for value in candidates:
        slug = _slugify(value)
        if slug in known:
            return slug

    text = " ".join(
        str(mission.get(k, ""))
        for k in ("title", "body", "description", "private_notes")
    ).lower()
    for slug, name in known.items():
        if "_" not in slug:
            continue
        if slug.replace("_", " ") in text or str(name).lower() in text:
            return slug

    return ""


def _memory_key_for_mission(mission: dict, district_slug: str = "") -> str:
    explicit = mission.get("map_memory_key") or mission.get("area_key")
    if explicit:
        return _slugify(str(explicit))
    area_name = _area_name_for_mission(mission)
    if area_name:
        return _slugify(area_name)
    return district_slug


def _map_type_from_mission(mission: dict, mission_type: str = "") -> str:
    explicit = str(mission.get("map_type") or mission.get("battle_map_type") or "").strip().lower()
    if explicit in {
        "street", "sewer", "cave", "dungeon", "tavern", "office", "temple",
        "warehouse", "arena", "rooftop", "prison", "cistern", "forge",
    }:
        return explicit

    text = " ".join(
        str(mission.get(k, ""))
        for k in (
            "location_name", "location", "area", "district",
            "title", "description", "body", "private_notes",
        )
    ).lower()

    keyword_map: list[tuple[tuple[str, ...], str]] = [
        (("sewer", "drain", "cistern", "canal", "runoff"), "sewer"),
        (("cave", "cavern", "mine", "tunnel", "underground"), "cave"),
        (("dungeon", "crypt", "catacomb", "reliquary", "lair"), "dungeon"),
        (("tavern", "inn", "pub", "bar", "taproom"), "tavern"),
        (("archive", "library", "office", "study", "guild", "embassy", "records"), "office"),
        (("temple", "shrine", "church", "cathedral", "sanctum", "ritual"), "temple"),
        (("warehouse", "storage", "dock", "loading", "depot"), "warehouse"),
        (("arena", "pit", "colosseum", "coliseum", "ring"), "arena"),
        (("roof", "rooftop", "spire", "tower top", "skyscraper"), "rooftop"),
        (("prison", "jail", "cell", "guardhouse"), "prison"),
        (("forge", "foundry", "factory", "machine", "ironworks"), "forge"),
        (("street", "alley", "market", "bazaar", "plaza", "road"), "street"),
    ]
    for keywords, map_type in keyword_map:
        if any(keyword in text for keyword in keywords):
            return map_type

    if mission_type in {"heist", "infiltration", "sabotage", "investigation", "negotiation"}:
        return "office"
    if mission_type in {"battle", "ambush", "escort", "defense", "assassination"}:
        return "street"
    if mission_type in {"infestation", "discovery", "exploration", "strange_occurrences"}:
        return "dungeon"
    return ""


def _library_enabled() -> bool:
    import os
    return str(os.getenv("MODULE_USE_BATTLE_MAP_LIBRARY", "true")).lower() in {"1", "true", "yes", "on"}


def _battle_map_base_filters(
    *,
    wealth_tier: str = "",
    size_class: str = "",
    min_score: int = 0,
    exclude_paths: list[str] | None = None,
) -> tuple[list[str], list]:
    clauses: list[str] = ["file_path IS NOT NULL", "file_path<>''"]
    params: list = []

    if wealth_tier:
        clauses.append("wealth_tier = %s")
        params.append(wealth_tier)

    if size_class:
        clauses.append("size_class = %s")
        params.append(size_class)

    if min_score:
        clauses.append("reddit_score >= %s")
        params.append(min_score)

    if exclude_paths:
        placeholders = ",".join(["%s"] * len(exclude_paths))
        clauses.append(f"file_path NOT IN ({placeholders})")
        params.extend(exclude_paths)

    return clauses, params


def _mark_stale_library_map(row: dict, reason: str = "") -> None:
    map_id = row.get("id")
    file_path = row.get("file_path") or ""
    if not map_id:
        return
    try:
        note = f"\nstale file_path cleared: {reason or 'missing file'}: {file_path}"
        raw_execute(
            "UPDATE battle_maps_library SET file_path='', "
            "analysis_notes=TRIM(CONCAT(COALESCE(analysis_notes,''), %s)) "
            "WHERE id=%s",
            (note, map_id),
        )
        raw_execute("DELETE FROM battle_map_area_memory WHERE battle_map_id=%s", (map_id,))
    except Exception as e:
        logger.warning(f"battle_map_library: stale map mark failed for #{map_id}: {e}")


def _ensure_map_memory_table() -> None:
    global _MAP_MEMORY_TABLE_READY
    if _MAP_MEMORY_TABLE_READY:
        return
    raw_execute(
        """
        CREATE TABLE IF NOT EXISTS battle_map_area_memory (
            id INT AUTO_INCREMENT PRIMARY KEY,
            area_key VARCHAR(160) NOT NULL,
            area_name VARCHAR(200),
            district_slug VARCHAR(100),
            mission_type VARCHAR(80) NOT NULL DEFAULT '',
            map_type VARCHAR(40) NOT NULL DEFAULT '',
            battle_map_id INT NOT NULL,
            map_file_path VARCHAR(600),
            source_mission_title VARCHAR(300),
            use_count INT NOT NULL DEFAULT 0,
            first_used_at DATETIME NOT NULL DEFAULT NOW(),
            last_used_at DATETIME NOT NULL DEFAULT NOW(),
            UNIQUE KEY uq_area_type (area_key, mission_type, map_type),
            INDEX idx_area_key (area_key),
            INDEX idx_battle_map (battle_map_id)
        )
        """
    )
    _ensure_map_memory_map_type_column()
    _ensure_map_memory_unique_key()
    _MAP_MEMORY_TABLE_READY = True


def _ensure_map_memory_map_type_column() -> None:
    try:
        rows = raw_query("SHOW COLUMNS FROM battle_map_area_memory LIKE 'map_type'") or []
        if not rows:
            raw_execute(
                "ALTER TABLE battle_map_area_memory "
                "ADD COLUMN map_type VARCHAR(40) NOT NULL DEFAULT '' AFTER mission_type"
            )
    except Exception as e:
        logger.warning(f"battle_map_library: map memory map_type migration failed: {e}")


def _ensure_map_memory_unique_key() -> None:
    try:
        rows = raw_query(
            """
            SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS cols
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA=DATABASE()
              AND TABLE_NAME='battle_map_area_memory'
              AND INDEX_NAME='uq_area_type'
            GROUP BY INDEX_NAME
            """
        ) or []
        current_cols = (rows[0].get("cols") if rows else "") or ""
        if current_cols == "area_key,mission_type,map_type":
            return
        if rows:
            raw_execute("ALTER TABLE battle_map_area_memory DROP INDEX uq_area_type")
        raw_execute(
            "ALTER TABLE battle_map_area_memory "
            "ADD UNIQUE KEY uq_area_type (area_key, mission_type, map_type)"
        )
    except Exception as e:
        logger.warning(f"battle_map_library: map memory unique key migration failed: {e}")


def _tier_to_wealth(tier_or_difficulty) -> str:
    """Map numeric difficulty (1-10) or legacy tier string to wealth tier for map selection.

    Logic: low difficulty = safe area = wealthy district visuals (gardens, market halls).
           High difficulty = dangerous area = poor/underground visuals (warrens, back alleys).
    """
    try:
        d = int(tier_or_difficulty)
        if d <= 2:   return "wealthy"      # Trivial/Easy — safe, well-lit, nice part of town
        if d <= 4:   return "middle"       # Moderate/Standard — working district
        if d <= 7:   return "poor"         # Challenging→Severe — rough neighborhoods
        return "underground"               # Deadly→Legendary — the deep warrens, void zones
    except (TypeError, ValueError):
        tier = str(tier_or_difficulty).lower()
        if "local" in tier or "patrol" in tier:
            return "wealthy"
        if "underground" in tier or "void" in tier or "tower" in tier or "divine" in tier or "epic" in tier:
            return "underground"
        if "high" in tier or "inter-guild" in tier or "rift" in tier:
            return "poor"
        # "standard", empty string, or any other unrecognised tier → no wealth filter
        return ""


# ---------------------------------------------------------------------------
# Schema management — canonical DDL so scripts don't each define their own
# ---------------------------------------------------------------------------

_LIBRARY_DDL = """
CREATE TABLE IF NOT EXISTS battle_maps_library (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    file_path               VARCHAR(600) NOT NULL,
    source                  VARCHAR(30)  NOT NULL DEFAULT 'downloaded',
    map_type                VARCHAR(40)  NOT NULL,
    reddit_score            INT          DEFAULT 0,
    reddit_title            VARCHAR(300),
    suitable_districts      JSON,
    suitable_mission_types  JSON,
    tags                    JSON,
    wealth_tier             VARCHAR(20),
    size_class              VARCHAR(20),
    width                   INT,
    height                  INT,
    file_size_kb            INT,
    analysis_notes          TEXT,
    analyzed_at             DATETIME,
    vtt_asset_name          VARCHAR(100),
    vtt_asset_id            VARCHAR(120),
    vtt_asset_url           VARCHAR(500),
    vtt_uploaded_at         DATETIME,
    created_at              DATETIME DEFAULT NOW(),
    UNIQUE KEY uq_path (file_path(400)),
    INDEX idx_map_type   (map_type),
    INDEX idx_source     (source),
    INDEX idx_wealth     (wealth_tier),
    INDEX idx_analyzed   (analyzed_at),
    INDEX idx_vtt        (vtt_uploaded_at)
)
"""

_AREA_MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS battle_map_area_memory (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    area_key     VARCHAR(200) NOT NULL,
    mission_type VARCHAR(60)  NOT NULL DEFAULT '',
    map_type     VARCHAR(40)  NOT NULL DEFAULT '',
    map_id       INT NOT NULL,
    used_at      DATETIME DEFAULT NOW(),
    UNIQUE KEY uq_area_mission_type (area_key(100), mission_type(40), map_type(30))
)
"""


def ensure_battle_maps_library_schema() -> None:
    """Create/verify battle_maps_library and battle_map_area_memory tables.

    Call this at the top of any script that reads or writes these tables.
    Scripts should NOT define their own DDL — this is the single source of truth.
    """
    try:
        raw_execute(_LIBRARY_DDL)
        raw_execute(_AREA_MEMORY_DDL)
        # Idempotent column additions for schema drift
        cols = {r["Field"] for r in (raw_query("DESCRIBE battle_maps_library") or [])}
        if "file_size_kb" not in cols:
            raw_execute("ALTER TABLE battle_maps_library ADD COLUMN file_size_kb INT NULL AFTER height")
        if "analysis_notes" not in cols:
            raw_execute("ALTER TABLE battle_maps_library ADD COLUMN analysis_notes TEXT NULL AFTER file_size_kb")
    except Exception as e:
        logger.warning(f"ensure_battle_maps_library_schema: {e}")
