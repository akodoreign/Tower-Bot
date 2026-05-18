"""
mimir_sync.py — Bidirectional sync between Tower bot MySQL and Mimir DM.

Architecture
------------
Translation layer: _*_to_bridge() and _bridge_to_*() are the ONLY places where
format conversion happens. MySQL data never touches Mimir directly; Mimir data
never touches MySQL directly. The bridge dataclasses are the contract between
the two systems.

Sync directions
---------------
  Bot → Mimir : NPCs, party characters, faction lore, world overview
  Mimir → Bot : NPC stat changes (HP/AC/location DM edits), character updates

Background task : full sync every MIMIR_SYNC_INTERVAL seconds (default 15 min)
Trigger hooks   : on_npc_changed(), on_faction_changed() — fire-and-forget

DB table : mimir_sync — entity_type + entity_id → mimir_id + change hash
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.log import logger
from src.db_api import raw_query, raw_execute
from src.mimir_client import get_mimir

SYNC_INTERVAL = int(os.getenv("MIMIR_SYNC_INTERVAL", "900"))   # seconds, default 15 min
MIMIR_PULL_NPC_SLEEP = float(os.getenv("MIMIR_PULL_NPC_SLEEP", "0.10"))
MIMIR_PULL_PROGRESS_EVERY = int(os.getenv("MIMIR_PULL_PROGRESS_EVERY", "100"))


# ---------------------------------------------------------------------------
# DB table — sync state tracking
# ---------------------------------------------------------------------------

_CREATE_SYNC_TABLE = """
CREATE TABLE IF NOT EXISTS mimir_sync (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    entity_type      VARCHAR(32)   NOT NULL,
    entity_id        VARCHAR(128)  NOT NULL,
    mimir_id         VARCHAR(128)  DEFAULT NULL,
    sync_hash        VARCHAR(32)   DEFAULT NULL,
    synced_at        TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_entity (entity_type, entity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_sync_table() -> None:
    try:
        raw_execute(_CREATE_SYNC_TABLE)
        # Only run the ALTER if the generated column doesn't already exist
        cols = raw_query(
            "SELECT GENERATION_EXPRESSION FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='player_characters' AND COLUMN_NAME='race'"
        )
        needs_alter = not cols or not cols[0].get("GENERATION_EXPRESSION")
        if needs_alter:
            raw_execute(
                "ALTER TABLE player_characters "
                "MODIFY COLUMN race varchar(500) COLLATE utf8mb4_unicode_ci "
                "GENERATED ALWAYS AS (`species`) VIRTUAL"
            )
    except Exception as exc:
        logger.warning(f"[MIMIR_SYNC] Table init failed: {exc}")


def _get_sync_row(entity_type: str, entity_id: str) -> Optional[dict]:
    rows = raw_query(
        "SELECT mimir_id, sync_hash FROM mimir_sync WHERE entity_type=%s AND entity_id=%s",
        (entity_type, str(entity_id)),
    )
    return rows[0] if rows else None


def _upsert_sync(entity_type: str, entity_id: str, mimir_id: str, sync_hash: str) -> None:
    raw_execute(
        """INSERT INTO mimir_sync (entity_type, entity_id, mimir_id, sync_hash)
           VALUES (%s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE mimir_id=%s, sync_hash=%s, synced_at=NOW()""",
        (entity_type, str(entity_id), mimir_id, sync_hash, mimir_id, sync_hash),
    )


def _make_hash(data: dict) -> str:
    return hashlib.md5(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Translation layer — NPC bridge
# ---------------------------------------------------------------------------

@dataclass
class _NPCBridge:
    """
    Internal bridge format for NPC data.
    Bot side uses npcs table columns + data_json.stats; Mimir side uses character fields.
    Never persisted — only lives during a sync operation.
    """
    # --- from bot (npcs table) ---
    bot_id:   int
    name:     str
    species:  str
    faction:  str
    status:   str
    role:     str
    location: str
    notes:    str = ""
    # --- from data_json.stats ---
    ability_scores: list = field(default_factory=list)  # [STR,DEX,CON,INT,WIS,CHA]
    hp:     int = 0
    ac:     int = 0
    level:  int = 1
    dnd_class: str = ""
    # --- from data_json.equipment ---
    gear: list = field(default_factory=list)  # [(name, qty), ...]
    # --- from Mimir (pulled back) ---
    mimir_id:      str = ""
    mimir_hp:      Optional[int] = None
    mimir_ac:      Optional[int] = None
    mimir_location: str = ""


# Species names that Mimir won't recognise as D&D races — normalise before sending.
# Patterns like "Specter (formerly Human)" → extract the base race in parentheses.
# Anything else unusual → map to closest standard race or keep as-is.
_SPECIES_OVERRIDES: dict[str, str] = {
    "Specter":          "Human",
    "Vampire Spawn":    "Human",
    "Vampire":          "Human",
    "Revenant":         "Human",
    "Lich":             "Human",
    "Zombie":           "Human",
    "Skeleton":         "Human",
    "Wight":            "Human",
    "Ghoul":            "Human",
    "Ghost":            "Human",
}


def _normalise_species(raw: str) -> str:
    """
    Translation: bot species string → Mimir-compatible race_name.

    Rules (in order):
    1. Strip all parentheticals to get the base race ("Lich (nascent) (formerly Goblin)" → "Lich")
    2. If base race is in the override list (undead/transformed types Mimir won't recognise):
       a. Prefer the "(formerly X)" original race if present → use X
       b. Otherwise use the override value (usually "Human")
    3. If base race is valid (e.g. "Tiefling", "Gnome"), return it as-is.
       "(formerly Human)" on a Tiefling is lore, not a race change.
    """
    if not raw:
        return "Human"
    clean = re.sub(r'\s*\([^)]*\)', '', raw).strip()
    if clean in _SPECIES_OVERRIDES:
        m = re.search(r'\(formerly\s+([^)]+)\)', raw, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return _SPECIES_OVERRIDES[clean]
    return clean or "Human"


def _npc_row_to_bridge(row: dict) -> _NPCBridge:
    """MySQL npcs row → _NPCBridge. Reads columns AND data_json.stats."""
    dj: dict = {}
    if row.get("data_json"):
        try:
            dj = row["data_json"] if isinstance(row["data_json"], dict) else json.loads(row["data_json"])
        except Exception:
            pass

    stats: dict = dj.get("stats", {}) or {}

    # Build [STR,DEX,CON,INT,WIS,CHA] — keys stored uppercase
    ability_scores: list = []
    if any(k in stats for k in ("STR", "DEX", "CON", "INT", "WIS", "CHA")):
        ability_scores = [
            int(stats.get("STR", 10) or 10),
            int(stats.get("DEX", 10) or 10),
            int(stats.get("CON", 10) or 10),
            int(stats.get("INT", 10) or 10),
            int(stats.get("WIS", 10) or 10),
            int(stats.get("CHA", 10) or 10),
        ]

    raw_species = row.get("species") or dj.get("species") or "Human"

    # Equipment — list of strings or list of dicts in data_json.equipment
    gear: list = []
    for item in (dj.get("equipment") or []):
        if isinstance(item, str) and item:
            gear.append((item, 1))
        elif isinstance(item, dict):
            iname = item.get("name", "")
            iqty  = int(item.get("quantity", item.get("qty", 1)) or 1)
            if iname:
                gear.append((iname, iqty))

    return _NPCBridge(
        bot_id         = row.get("id", 0),
        name           = row.get("name", ""),
        species        = _normalise_species(raw_species),
        faction        = row.get("faction", ""),
        status         = row.get("status", "alive"),
        role           = row.get("role") or dj.get("role") or "",
        location       = row.get("location") or dj.get("location") or "",
        notes          = row.get("description") or dj.get("notes") or "",
        ability_scores = ability_scores,
        hp             = int(stats.get("HP", 0) or 0),
        ac             = int(stats.get("AC", 0) or 0),
        level          = int(stats.get("level", 1) or dj.get("level", 1) or 1),
        dnd_class      = stats.get("class", "") or dj.get("dnd_class", ""),
        gear           = gear,
        mimir_id       = dj.get("mimir_id", ""),
    )


def _bridge_to_mimir_create(b: _NPCBridge) -> dict:
    """Translation: _NPCBridge → mimir create_character params."""
    params: dict = {
        "name":           b.name,
        "character_type": "npc",
        "race_name":      b.species,
    }
    if b.dnd_class:
        params["class_name"] = b.dnd_class
        params["level"]      = max(1, b.level)
    return params


def _bridge_to_mimir_edit(b: _NPCBridge) -> dict:
    """
    Translation: _NPCBridge → mimir edit_character params.
    Mimir edit_character accepts individual ability score fields, not an array.
    race_name IS editable. HP/AC go to the dm_notes document instead.
    """
    params: dict = {}
    if b.dnd_class:
        params["class_name"] = b.dnd_class
        params["level"] = max(1, b.level)
    if b.role:     params["npc_role"]     = b.role
    if b.location: params["npc_location"] = b.location
    if b.faction:  params["faction"]      = b.faction
    if b.species:  params["race_name"]    = b.species
    if b.ability_scores and len(b.ability_scores) == 6:
        params["strength"]     = b.ability_scores[0]
        params["dexterity"]    = b.ability_scores[1]
        params["constitution"] = b.ability_scores[2]
        params["intelligence"] = b.ability_scores[3]
        params["wisdom"]       = b.ability_scores[4]
        params["charisma"]     = b.ability_scores[5]
    return params


def _build_npc_notes(b: _NPCBridge, dj: dict) -> str:
    """
    Translation: everything that doesn't fit a direct Mimir field → markdown notes doc.
    Goes to Mimir as a dm_notes document on the character.
    """
    stats: dict = dj.get("stats", {}) or {}
    lines: list[str] = [f"# {b.name}"]

    # Combat block (doesn't map to Mimir character fields directly)
    if b.dnd_class or b.level or b.hp or b.ac:
        combat = []
        if b.dnd_class:
            sub = stats.get("subclass", "")
            combat.append(f"{b.dnd_class}{' (' + sub + ')' if sub else ''} Lv{b.level}")
        if b.hp:  combat.append(f"HP {b.hp}")
        if b.ac:  combat.append(f"AC {b.ac}")
        pb = stats.get("proficiency_bonus", "")
        if pb:    combat.append(f"PB +{pb}")
        lines.append("**" + " | ".join(combat) + "**")

    saves = stats.get("save_proficiencies", [])
    if saves:
        lines.append(f"*Saving throws:* {', '.join(saves)}")

    lines.append("")

    # Identity
    if dj.get("faction"):    lines.append(f"**Faction:** {dj['faction']}")
    if dj.get("rank"):       lines.append(f"**Rank:** {dj['rank']}")
    if dj.get("age"):        lines.append(f"**Age:** {dj['age']}")
    if dj.get("pronouns"):   lines.append(f"**Pronouns:** {dj['pronouns']}")
    if dj.get("species") and dj["species"] != b.species:
        lines.append(f"**True form:** {dj['species']}")  # e.g. "Specter (formerly Human)"

    # Narrative fields
    for label, key in [
        ("Motivation", "motivation"),
        ("History",    "history"),
        ("Notes",      "notes"),
        ("Oracle notes", "oracle_notes"),
    ]:
        val = dj.get(key, "")
        if val:
            lines.append(f"\n## {label}\n{val}")

    # Relationships
    rels = dj.get("relationships", {})
    if rels:
        lines.append("\n## Relationships")
        if isinstance(rels, dict):
            for k, v in list(rels.items())[:10]:
                lines.append(f"- **{k}:** {v}")
        elif isinstance(rels, list):
            for r in rels[:10]:
                lines.append(f"- {r}")

    # Secrets
    secret = dj.get("secret", "") or ""
    revealed = dj.get("revealed_secrets", []) or []
    if secret or revealed:
        lines.append("\n## Secrets")
        if secret:
            lines.append(f"*Hidden:* {secret}")
        for s in (revealed if isinstance(revealed, list) else []):
            lines.append(f"- {s}")

    return "\n".join(lines)


_MIMIR_STAT_MAP = [
    ("strength", "STR"), ("dexterity", "DEX"), ("constitution", "CON"),
    ("intelligence", "INT"), ("wisdom", "WIS"), ("charisma", "CHA"),
]


def _mimir_char_to_bot_patch(char: dict) -> dict:
    """
    Mimir character dict → structured patch for MySQL.
    Returns {"columns": {column: value}, "json": {json_path: value}}
    Only includes fields that actually changed (non-null, non-default from Mimir).
    """
    columns: dict = {}
    json_paths: dict = {}

    # Ability scores → data_json.stats.*
    for mimir_key, stat_key in _MIMIR_STAT_MAP:
        v = char.get(mimir_key)
        if v is not None and int(v) != 10:   # skip unchanged default-10s
            json_paths[f"stats.{stat_key}"] = int(v)

    # Location → npcs.location column
    loc = char.get("npc_location", "")
    if loc:
        columns["location"] = loc

    # Faction → npcs.faction column
    fac = char.get("faction", "")
    if fac:
        columns["faction"] = fac

    # Species/race -> data_json.species; npcs.species is generated from JSON.
    race = char.get("race_name", "")
    if race and race != "Human":
        json_paths["species"] = race

    return {"columns": columns, "json": json_paths}


def _mimir_char_to_npc_insert(char: dict) -> dict:
    """
    Translation: Mimir character → MySQL npcs INSERT dict.
    Used when the DM creates a new NPC in Mimir that doesn't exist in MySQL yet.
    """
    stats: dict = {}
    for mimir_key, stat_key in _MIMIR_STAT_MAP:
        v = char.get(mimir_key)
        if v is not None:
            stats[stat_key] = int(v)

    return {
        "name":      char.get("name", "Unknown"),
        "faction":   char.get("faction", "") or "",
        "status":    "alive",
        "role":      char.get("npc_role", "") or "",
        "location":  char.get("npc_location", "") or "",
        "data_json": json.dumps({
            "mimir_id":  char.get("id", ""),
            "species":   char.get("race_name", "") or "Human",
            "stats":     stats,
            "notes":     "Added via Mimir DM interface",
            "traits":    char.get("traits", ""),
            "ideals":    char.get("ideals", ""),
            "bonds":     char.get("bonds", ""),
            "flaws":     char.get("flaws", ""),
            "source":    "mimir",
        }),
    }


def _npc_sync_hash(b: _NPCBridge) -> str:
    return _make_hash({
        "name":     b.name,
        "species":  b.species,
        "faction":  b.faction,
        "role":     b.role,
        "location": b.location,
        "scores":   b.ability_scores,
        "hp":       b.hp,
        "ac":       b.ac,
        "level":    b.level,
        "gear":     b.gear,
    })


# ---------------------------------------------------------------------------
# Translation layer — Party character bridge
# ---------------------------------------------------------------------------

_PC_STAT_RE = re.compile(r'(STR|DEX|CON|INT|WIS|CHA)\s+(\d+)', re.IGNORECASE)


def _parse_pc_stats(stats_str: str) -> list:
    """Parse 'STR 10 | DEX 14 | CON 14 | INT 18 | WIS 14 | CHA 16' → [10,14,14,18,14,16]."""
    mapping = {m.group(1).upper(): int(m.group(2)) for m in _PC_STAT_RE.finditer(stats_str or "")}
    if not mapping:
        return []
    return [mapping.get(k, 10) for k in ("STR", "DEX", "CON", "INT", "WIS", "CHA")]


def _parse_pc_class_level(class_str: str) -> tuple:
    """'Wizard 4' → ('Wizard', 4), 'Fighter 1 / Rogue 4' → ('Fighter', 5)."""
    if not class_str:
        return ("Fighter", 1)
    base = re.sub(r'\s*\([^)]*\)', '', class_str).strip()
    segments = re.split(r'\s*/\s*', base)
    total_level = 0
    primary_class = ""
    for seg in segments:
        m = re.search(r'(\d+)\s*$', seg.strip())
        if m:
            total_level += int(m.group(1))
            if not primary_class:
                primary_class = re.sub(r'\s*\d+\s*$', '', seg.strip()).strip()
        elif not primary_class:
            primary_class = seg.strip()
    return (primary_class or "Fighter", max(1, total_level))


def _parse_pc_gear(gear_str: str) -> list:
    """'Quarterstaff, Potions of Healing (x2)' → [('Quarterstaff',1), ('Potion of Healing',2)]."""
    items = []
    for part in (gear_str or "").split(","):
        part = part.strip()
        if not part or part.lower() == "empty":
            continue
        qty_match = re.search(r'\((?:x)?(\d+)\)', part, re.IGNORECASE)
        qty = int(qty_match.group(1)) if qty_match else 1
        name = re.sub(r'\s*\((?:x)?\d+\)\s*', '', part).strip()
        # Normalise pluralised consumables: "Potions of Healing" → "Potion of Healing"
        name = re.sub(r'^Potions\b', 'Potion', name)
        name = re.sub(r'^Scrolls\b', 'Scroll', name)
        name = re.sub(r'^Arrows\b', 'Arrow', name)
        if name:
            items.append((name, qty))
    return items


def _normalise_pc_race(race_str: str) -> str:
    """Strip meta-notes like '(Pipeline — only known of his kind...)' from species."""
    if not race_str:
        return "Human"
    clean = re.sub(r'\s*\([^)]{20,}\)', '', race_str).strip()
    clean = re.sub(r'\s*(—|–|-)\s*(only|created|Pipeline|homebrew).*$', '', clean, flags=re.IGNORECASE).strip()
    return clean or "Human"


@dataclass
class _PCBridge:
    """Bridge from player_characters (MySQL) + DDB snapshot → Mimir PC character."""
    bot_id:     int
    name:       str
    race:       str
    class_name: str
    player:     str = ""
    level:      int = 1
    hp_max:     int = 0
    ac:         int = 10
    ability_scores: list  = field(default_factory=list)
    gear:       list      = field(default_factory=list)   # [(name, qty), ...]
    currencies: dict      = field(default_factory=dict)   # {gp, sp, cp, ep, pp}
    spells:     list      = field(default_factory=list)   # [{name, level, class, prepared}]


def _player_char_to_bridge(row: dict) -> Optional[_PCBridge]:
    """
    player_characters row → _PCBridge.
    DDB snapshot (character_snapshots) is the authoritative source for all
    mechanical data. profile_json text parsing is the fallback when no snapshot exists.
    """
    name = row.get("name", "")
    if not name:
        return None
    profile: dict = {}
    if row.get("profile_json"):
        try:
            profile = row["profile_json"] if isinstance(row["profile_json"], dict) else json.loads(row["profile_json"])
        except Exception:
            profile = {}

    # --- DDB snapshot (updated every 30 min by character_monitor) ---
    snap_rows = raw_query(
        "SELECT snapshot_json FROM character_snapshots WHERE char_name=%s ORDER BY fetched_at DESC LIMIT 1",
        (name,),
    )
    snap: dict = {}
    if snap_rows:
        sj = snap_rows[0]["snapshot_json"]
        snap = sj if isinstance(sj, dict) else json.loads(sj or "{}")

    # Ability scores — DDB wins, fall back to raw text parse
    ddb_stats = snap.get("stats", {})
    if ddb_stats:
        ability_scores = [
            ddb_stats.get("STR", 10), ddb_stats.get("DEX", 10),
            ddb_stats.get("CON", 10), ddb_stats.get("INT", 10),
            ddb_stats.get("WIS", 10), ddb_stats.get("CHA", 10),
        ]
    else:
        ability_scores = _parse_pc_stats(profile.get("STATS", ""))

    # Class + level — DDB wins
    ddb_classes = snap.get("classes", {})   # {"Wizard": 4} or {"Fighter": 1, "Rogue": 4}
    if ddb_classes:
        class_name = list(ddb_classes.keys())[0]
        level      = sum(ddb_classes.values())
    else:
        class_name, level = _parse_pc_class_level(row.get("class_name", "") or "")

    # HP — DDB
    hp_max = int(snap.get("max_hp") or 0)

    # Currencies — DDB
    currencies = snap.get("currencies", {})

    # Inventory: DDB items plus any Mimir-only extras stored in profile_json.
    ddb_inventory = snap.get("inventory", {})   # {item_name: qty}
    profile_gear = _parse_pc_gear(
        profile.get("INVENTORY", "")
        or profile.get("NOTABLE_GEAR", "")
        or profile.get("NOTABLE GEAR", "")
    )
    if ddb_inventory:
        gear = [(item, qty) for item, qty in ddb_inventory.items() if item]
        seen = {item.lower() for item, _ in gear}
        for item, qty in profile_gear:
            if item.lower() not in seen:
                gear.append((item, qty))
                seen.add(item.lower())
    else:
        gear = profile_gear

    # Spells — from DDB snapshot (parsed by character_monitor)
    spells = snap.get("spells", [])

    return _PCBridge(
        bot_id         = row.get("id", 0),
        name           = name,
        race           = _normalise_pc_race(row.get("race") or row.get("species") or "Human"),
        class_name     = class_name,
        player         = row.get("player_name", ""),
        level          = max(1, level),
        hp_max         = hp_max,
        ac             = 10,
        ability_scores = ability_scores,
        gear           = gear,
        currencies     = currencies,
        spells         = spells,
    )


def _bridge_to_mimir_pc_create(b: _PCBridge) -> dict:
    params: dict = {
        "name":           b.name,
        "character_type": "pc",
        "race_name":      b.race,
        "level":          b.level,
    }
    if b.class_name:
        params["class_name"] = b.class_name
    return params


def _bridge_to_mimir_pc_edit(b: _PCBridge) -> dict:
    params: dict = {"level": max(1, b.level)}
    if b.class_name:
        params["class_name"] = b.class_name
    if b.ability_scores and len(b.ability_scores) == 6:
        params["strength"]     = b.ability_scores[0]
        params["dexterity"]    = b.ability_scores[1]
        params["constitution"] = b.ability_scores[2]
        params["intelligence"] = b.ability_scores[3]
        params["wisdom"]       = b.ability_scores[4]
        params["charisma"]     = b.ability_scores[5]
    if b.player:
        params["player_name"] = b.player
    # Currencies from DDB
    for coin in ("gp", "sp", "cp", "ep", "pp"):
        v = b.currencies.get(coin)
        if v is not None:
            params[coin] = int(v)
    return params


async def _push_gear_to_mimir(character_id: str, gear: list) -> None:
    """
    Push (name, qty) gear pairs to a Mimir character.
    Mimir's add_item_to_character accepts any item name — catalog or custom.
    If it returns false (hard miss), register as homebrew then retry once.
    """
    mimir = get_mimir()
    for item_name, qty in gear:
        try:
            ok = await mimir.add_item_to_character(
                character_id, item_name, equipped=_is_equippable_item(item_name), quantity=qty
            )
            if not ok:
                # Hard miss — create homebrew entry so it's trackable in Mimir's UI
                await mimir.create_homebrew_item(item_name)
                await mimir.add_item_to_character(
                    character_id, item_name, equipped=_is_equippable_item(item_name), quantity=qty
                )
            logger.debug(f"[MIMIR_SYNC] gear → {item_name} ×{qty}")
        except Exception as exc:
            logger.debug(f"[MIMIR_SYNC] gear push failed for {item_name!r}: {exc}")


def _is_equippable_item(item_name: str) -> bool:
    name = (item_name or "").lower()
    if any(word in name for word in ("pack", "kit", "tools", "supplies", "clothes", "book", "rope", "rations")):
        return False
    return True


def _pc_sync_hash(b: _PCBridge) -> str:
    return _make_hash({
        "name":       b.name,
        "race":       b.race,
        "class":      b.class_name,
        "level":      b.level,
        "hp":         b.hp_max,
        "scores":     b.ability_scores,
        "currencies": b.currencies,
        "gear":       b.gear,
        "spells":     sorted(s.get("name", "") for s in b.spells if isinstance(s, dict)),
    })


def _infer_pc_gear(bridge: _PCBridge) -> list:
    """Infer a level-friendly starter kit for a PC when DDB/MySQL has no inventory."""
    seen: set = set()
    gear: list = []

    def _add(name: str, qty: int = 1) -> None:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            gear.append((name, qty))

    cls = (bridge.class_name or "").strip()
    base = _CLASS_GEAR.get(cls)
    if base is None:
        for known_cls, items in _CLASS_GEAR.items():
            if known_cls.lower() in cls.lower() or cls.lower() in known_cls.lower():
                base = items
                break
    for name, qty in (base or _DEFAULT_GEAR):
        _add(name, qty)

    race = (bridge.race or "").lower()
    if "dwarf" in race:
        _add("Handaxe", 1)
    elif "elf" in race:
        _add("Longbow", 1)
        _add("Arrows", 20)
    elif "halfling" in race or "gnome" in race:
        _add("Sling", 1)
        _add("Bullets", 20)
    elif "warforged" in race or "construct" in race:
        _add("Smith's Tools", 1)
    elif "tiefling" in race or "aasimar" in race:
        _add("Arcane Focus", 1)

    if bridge.level >= 3:
        _add("Potion of Healing", 1)
    if bridge.level >= 7:
        _add("Potion of Greater Healing", 1)
    if bridge.level >= 11:
        _add("Potion of Superior Healing", 1)

    return gear


async def _catalog_item_name(item_name: str) -> str:
    """Use Mimir catalog as the source of truth for item display names when available."""
    mimir = get_mimir()
    if not mimir.available:
        return item_name
    try:
        items = await mimir.search_items(name=item_name)
        if not items:
            return item_name
        exact = next((i for i in items if (i.get("name") or "").lower() == item_name.lower()), None)
        chosen = exact or items[0]
        return chosen.get("name") or item_name
    except Exception:
        return item_name


async def _catalog_normalise_gear(gear: list) -> list:
    normalised = []
    seen = set()
    for item_name, qty in gear:
        catalog_name = await _catalog_item_name(item_name)
        key = catalog_name.lower()
        if key in seen:
            continue
        seen.add(key)
        normalised.append((catalog_name, qty))
    return normalised


_MAGIC_ITEM_HINTS = (
    "+1 ", "+2 ", "+3 ", "amulet of", "bag of holding", "belt of", "boots of",
    "cloak of protection", "ring of protection", "wand of the war mage",
    "rod of the pact keeper", "moon sickle", "all-purpose tool", "dragonhide belt",
    "rhythm-maker", "instrument of the bards", "staff of", "bracers of",
)


_MAGIC_POWER_HINTS = (
    "+1 ", "+2 ", "+3 ", "amulet of the devout", "wand of the war mage",
    "rod of the pact keeper", "moon sickle", "all-purpose tool", "dragonhide belt",
    "rhythm-maker", "instrument of the bards",
)


_WONDROUS_BY_LEVEL = (
    (3, (
        "Cloak of Billowing",
        "Cloak of Many Fashions",
        "Boots of False Tracks",
        "Dread Helm",
        "Ear Horn of Hearing",
        "Hat of Vermin",
        "Hat of Wizardry",
        "Heward's Handy Spice Pouch",
        "Horn of Silent Alarm",
        "Rope of Mending",
    )),
    (5, (
        "Alchemy Jug",
        "Bag of Holding",
        "Boots of Elvenkind",
        "Boots of Striding and Springing",
        "Boots of the Winterlands",
        "Cloak of Elvenkind",
        "Cloak of Protection",
        "Elemental Gem, Blue Sapphire",
        "Elemental Gem, Emerald",
        "Elemental Gem, Red Corundum",
        "Elemental Gem, Yellow Diamond",
        "Eversmoking Bottle",
        "Gem of Brightness",
        "Gloves of Missile Snaring",
        "Gloves of Swimming and Climbing",
        "Gloves of Thievery",
        "Goggles of Night",
        "Hat of Disguise",
        "Helm of Comprehending Languages",
        "Lantern of Revealing",
        "Pearl of Power",
        "Periapt of Health",
        "Periapt of Wound Closure",
        "Ring of Warmth",
        "Rope of Climbing",
        "Sending Stones",
        "Winged Boots",
    )),
    (9, (
        "Amulet of Health",
        "Bag of Beans",
        "Bag of Tricks, Gray",
        "Bag of Tricks, Rust",
        "Bag of Tricks, Tan",
        "Boots of Levitation",
        "Boots of Speed",
        "Chime of Opening",
        "Cloak of Displacement",
        "Cloak of the Bat",
        "Gem of Seeing",
        "Helm of Telepathy",
        "Helm of Teleportation",
        "Heward's Handy Haversack",
        "Ioun Stone, Awareness",
        "Ioun Stone, Protection",
        "Ioun Stone, Sustenance",
        "Periapt of Proof against Poison",
        "Quaal's Feather Token, Bird",
        "Quaal's Feather Token, Tree",
        "Rope of Entanglement",
    )),
    (13, (
        "Amethyst Lodestone",
        "Cloak of Arachnida",
        "Helm of Brilliance",
        "Ioun Stone, Absorption",
        "Ioun Stone, Agility",
        "Ioun Stone, Fortitude",
        "Manual of Bodily Health",
        "Obsidian Steed Figurine of Wondrous Power",
        "Prehistoric Figurine of Wondrous Power, Carnelian Triceratops",
        "Robe of Eyes",
    )),
    (17, (
        "Cloak of Invisibility",
        "Gold Canary Figurine of Wondrous Power",
        "Horn of Valhalla, Iron",
        "Scarab of Protection",
    )),
)


_WONDROUS_ALIASES = {
    "Obsidian Steed Figurine of Wondrous Power": "Figurine of Wondrous Power, Obsidian Steed",
}


def _has_magic_gear(gear: list) -> bool:
    names = " | ".join(str(item_name).lower() for item_name, _ in (gear or []))
    return any(hint in names for hint in _MAGIC_ITEM_HINTS)


def _has_magic_power_gear(gear: list) -> bool:
    names = " | ".join(str(item_name).lower() for item_name, _ in (gear or []))
    return any(hint in names for hint in _MAGIC_POWER_HINTS)


def _stable_item_pick(options: tuple[str, ...], seed: str, count: int) -> list[str]:
    if not options or count <= 0:
        return []
    start = sum(ord(ch) for ch in seed) % len(options)
    return [options[(start + i) % len(options)] for i in range(min(count, len(options)))]


def _infer_wondrous_gear(class_name: str, level: int, race: str, existing_gear: list) -> list:
    """Sprinkle in Mimir-catalog wondrous items without turning every sheet into a vault."""
    if level < 3:
        return []

    existing = {str(name).lower() for name, _ in (existing_gear or [])}
    seed = f"{class_name}|{race}|{level}"
    gear: list = []

    # Low levels get one flavor/common item. Higher levels add utility at each tier.
    for minimum_level, options in _WONDROUS_BY_LEVEL:
        if level < minimum_level:
            continue
        tier_names = {_WONDROUS_ALIASES.get(name, name).lower() for name in options}
        if existing.intersection(tier_names):
            continue
        picks = _stable_item_pick(options, seed + str(minimum_level), 1)
        for name in picks:
            catalog_name = _WONDROUS_ALIASES.get(name, name)
            if catalog_name.lower() not in existing:
                gear.append((catalog_name, 1))
                existing.add(catalog_name.lower())

    race_lower = (race or "").lower()
    if level >= 5 and "elf" in race_lower and "boots of elvenkind" not in existing:
        gear.append(("Boots of Elvenkind", 1))

    cls = (class_name or "").lower()
    if level >= 5 and ("wizard" in cls or "sorcerer" in cls or "warlock" in cls) and "pearl of power" not in existing:
        gear.append(("Pearl of Power", 1))
    if level >= 5 and ("rogue" in cls or "bard" in cls) and "gloves of thievery" not in existing:
        gear.append(("Gloves of Thievery", 1))
    if level >= 5 and ("ranger" in cls or "druid" in cls) and "boots of the winterlands" not in existing:
        gear.append(("Boots of the Winterlands", 1))

    return gear


def _primary_weapon_for_magic(gear: list, class_name: str) -> str:
    names = [str(item_name) for item_name, _ in (gear or [])]
    lower = [n.lower() for n in names]
    for preferred in (
        "longsword", "rapier", "greataxe", "quarterstaff", "longbow",
        "shortbow", "light crossbow", "dagger", "mace",
    ):
        if preferred in lower:
            return preferred.title()

    cls = (class_name or "").lower()
    if "rogue" in cls:
        return "Rapier"
    if "ranger" in cls:
        return "Longbow"
    if "wizard" in cls or "sorcerer" in cls or "druid" in cls or "monk" in cls:
        return "Quarterstaff"
    if "cleric" in cls:
        return "Mace"
    return "Longsword"


def _spellcasting_focus_for_class(class_name: str) -> str:
    cls = (class_name or "").lower()
    if "artificer" in cls:
        return "+1 All-Purpose Tool"
    if "warlock" in cls:
        return "+1 Rod of the Pact Keeper"
    if "cleric" in cls or "paladin" in cls:
        return "+1 Amulet of the Devout"
    if "druid" in cls or "ranger" in cls:
        return "+1 Moon Sickle"
    if "monk" in cls:
        return "+1 Dragonhide Belt"
    if "wizard" in cls or "sorcerer" in cls:
        return "+1 Wand of the War Mage"
    if "bard" in cls:
        return "Cloak of Protection"
    return ""


def _infer_magic_gear(class_name: str, level: int, race: str, existing_gear: list) -> list:
    """Pick conservative, level-friendly magic items that exist in Mimir's catalog."""
    if level < 3:
        return []

    gear: list = []
    cls = class_name or ""
    focus = _spellcasting_focus_for_class(cls)
    primary_weapon = _primary_weapon_for_magic(existing_gear, cls)

    if not _has_magic_power_gear(existing_gear):
        if focus:
            gear.append((focus, 1))
        else:
            gear.append((f"+1 {primary_weapon}", 1))

    if level >= 5:
        if "shield" in {str(n).lower() for n, _ in existing_gear}:
            gear.append(("+1 Shield", 1))
        else:
            gear.append(("Cloak of Protection", 1))

    if level >= 9:
        gear.append(("Bag of Holding", 1))
        if not focus:
            gear.append(("Cloak of Protection", 1))

    if level >= 13:
        upgraded = []
        for name, qty in gear:
            if name.startswith("+1 "):
                upgraded.append((name.replace("+1 ", "+2 ", 1), qty))
            else:
                upgraded.append((name, qty))
        gear = upgraded
        gear.append(("Ring of Protection", 1))

    return _merge_gear(gear, _infer_wondrous_gear(cls, level, race, existing_gear + gear))


def _merge_gear(base_gear: list, extra_gear: list) -> list:
    merged = list(base_gear or [])
    seen = {str(name).lower() for name, _ in merged}
    for name, qty in extra_gear or []:
        key = str(name).lower()
        if key not in seen:
            merged.append((name, qty))
            seen.add(key)
    return merged


def _gear_keys(gear: list) -> set[tuple[str, int]]:
    return {(str(name).strip().lower(), int(qty or 1)) for name, qty in (gear or [])}


def _item_norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


async def _catalog_resolve_real_item(candidates: list[str]) -> Optional[str]:
    """
    Resolve one candidate to a real Mimir catalog item name.
    Unlike _catalog_item_name, this returns None on a catalog miss so epic gear
    never silently becomes homebrew.
    """
    mimir = get_mimir()
    if not mimir.available:
        return None

    for candidate in candidates:
        try:
            items = await mimir.search_items(name=candidate)
        except Exception:
            items = []
        if not items:
            continue

        wanted = _item_norm(candidate)
        exact = next((i for i in items if _item_norm(i.get("name") or "") == wanted), None)
        if exact and exact.get("name"):
            return exact["name"]

        wanted_parts = set(wanted.split())
        contained = next(
            (
                i for i in items
                if wanted_parts and wanted_parts.issubset(set(_item_norm(i.get("name") or "").split()))
            ),
            None,
        )
        chosen = contained or items[0]
        if chosen.get("name"):
            return chosen["name"]

    return None


def _is_martial_class(class_name: str) -> bool:
    cls = (class_name or "").lower()
    return any(word in cls for word in ("fighter", "paladin", "ranger", "barbarian", "blood hunter"))


def _is_weapon_or_armor_replaced(name: str) -> bool:
    n = str(name or "").lower()
    if n in {"shield", "+1 shield", "+2 shield", "+3 shield"}:
        return True
    if n in {"chain mail", "scale mail", "leather armor", "hide armor", "plate", "plate armor", "+1 plate", "+2 plate", "+3 plate"}:
        return True
    if n in {"+1 longsword", "+2 longsword", "+3 longsword", "longsword"}:
        return True
    if "sword of sharpness" in n or "vorpal" in n or n.startswith("defender "):
        return True
    return False


async def _infer_epic_npc_gear(bridge: _NPCBridge, base_gear: list) -> tuple[list, int, list[str]]:
    """
    Add catalog-backed epic equipment and derive a display AC modifier.
    Returns (gear_to_add, target_ac, missing_catalog_names).
    """
    level = int(bridge.level or 1)
    if level < 13:
        return [], int(bridge.ac or 0), []

    cls = bridge.dnd_class or ""
    martial = _is_martial_class(cls)
    existing = {_item_norm(name) for name, _ in (base_gear or [])}
    missing: list[str] = []
    resolved: list = []

    async def add_slot(candidates: list[str]) -> None:
        item = await _catalog_resolve_real_item(candidates)
        if not item:
            missing.append(candidates[0])
            return
        key = _item_norm(item)
        if key not in existing:
            existing.add(key)
            resolved.append((item, 1))

    if martial:
        await add_slot(["Vorpal Longsword", "Longsword of Sharpness", "+3 Longsword"])
        await add_slot(["Defender Longsword", "Defender", "+3 Longsword"])
        await add_slot(["Armor, +3", "+3 Plate Armor", "Plate Armor +3"])
        await add_slot(["Shield, +3", "+3 Shield", "Shield +3"])
        await add_slot(["Ring of Protection"])
        await add_slot(["Cloak of Protection"])
        await add_slot(["Ioun Stone, Protection", "Ioun Stone of Protection"])
        target_ac = 29 if level >= 17 else 25
    else:
        focus = _spellcasting_focus_for_class(cls)
        if focus:
            await add_slot([
                focus.replace("+1 ", "+3 ", 1),
                focus.replace("+1 ", "+2 ", 1),
                focus,
            ])
        else:
            await add_slot(["Staff of Power", "Staff of the Magi", "Rod of Absorption"])
        await add_slot(["Robe of the Archmagi", "Bracers of Defense", "Cloak of Protection"])
        await add_slot(["Ring of Protection"])
        await add_slot(["Ioun Stone, Protection", "Ioun Stone of Protection"])
        target_ac = 24 if level >= 17 else 21

    # Epic-but-flavorful wondrous kit. Resolve through Mimir before adding.
    if level >= 17:
        await add_slot(["Cloak of Invisibility", "Scarab of Protection"])
        await add_slot(["Horn of Valhalla, Iron", "Horn of Valhalla"])
    else:
        await add_slot(["Helm of Brilliance", "Gem of Seeing"])

    return resolved, max(int(bridge.ac or 0), target_ac), missing


def _serialise_gear(gear: list) -> str:
    return json.dumps([{"name": n, "quantity": q, "equipped": True} for n, q in gear], ensure_ascii=False)


async def run_pc_gear_run(force: bool = False) -> dict:
    """
    Fill missing player-character equipment in MySQL and clear Mimir gear hashes.
    DDB/MySQL inventory wins unless force=True.
    """
    rows = raw_query("SELECT * FROM player_characters ORDER BY name LIMIT 100")
    if not rows:
        return {"total": 0, "done": 0, "skipped": 0, "failed": 0}

    total = skipped = done = failed = 0
    for row in rows:
        total += 1
        try:
            bridge = _player_char_to_bridge(row)
            if not bridge:
                skipped += 1
                continue

            profile = row.get("profile_json") or {}
            if isinstance(profile, str):
                try:
                    profile = json.loads(profile)
                except Exception:
                    profile = {}

            base_gear = bridge.gear if bridge.gear and not force else _infer_pc_gear(bridge)
            magic_gear = _infer_magic_gear(bridge.class_name, bridge.level, bridge.race, base_gear)
            normalised_base = await _catalog_normalise_gear(base_gear) if bridge.gear and not force else base_gear
            gear = await _catalog_normalise_gear(_merge_gear(base_gear, magic_gear))
            if not gear:
                skipped += 1
                continue
            if bridge.gear and not force and _gear_keys(gear) == _gear_keys(normalised_base):
                skipped += 1
                continue

            profile["INVENTORY"] = ", ".join(f"{name} ({qty})" for name, qty in gear)
            raw_execute(
                "UPDATE player_characters SET profile_json=%s, updated_at=NOW() WHERE id=%s",
                (json.dumps(profile, ensure_ascii=False), row["id"]),
            )
            raw_execute(
                "UPDATE mimir_sync SET sync_hash=NULL WHERE entity_type IN ('pc','pc_gear') AND entity_id=%s",
                (str(row["id"]),),
            )
            done += 1
            logger.debug(f"[MIMIR_SYNC] PC gear inferred: {bridge.name!r} - {len(gear)} items")
        except Exception as exc:
            failed += 1
            logger.warning(f"[MIMIR_SYNC] PC gear infer failed for {row.get('name', row.get('id'))!r}: {exc}")

    logger.debug(f"[MIMIR_SYNC] PC gear run: {done} done, {skipped} skipped, {failed} failed / {total} total")
    return {"total": total, "done": done, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# Translation layer — Faction doc bridge
# ---------------------------------------------------------------------------

def _faction_row_to_doc(row: dict) -> str:
    """faction_reputation row → Mimir document content (markdown)."""
    name   = row.get("faction_name", "Unknown")
    score  = row.get("reputation_score", 0)
    tier   = row.get("tier", "neutral")
    leader = row.get("leader", "")
    loc    = row.get("location_name", "")
    desc   = row.get("description", "")
    motto  = row.get("motto", "")

    lines = [f"# {name}", "", f"**Reputation:** {score} ({tier})"]
    if leader:  lines.append(f"**Leader:** {leader}")
    if loc:     lines.append(f"**Base:** {loc}")
    if motto:   lines.append(f"*\"{motto}\"*")
    if desc:    lines += ["", desc]
    return "\n".join(lines)


def _mimir_doc_to_faction_patch(doc: dict) -> dict:
    """
    Read back a faction doc from Mimir → extract any DM edits.
    Currently just pulls description changes; extend as needed.
    """
    content = doc.get("content", "")
    if not content:
        return {}
    # If DM added a new description paragraph, capture it
    lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#") and not l.startswith("**") and not l.startswith("*")]
    if lines:
        return {"description": " ".join(lines[:3])}
    return {}


# ---------------------------------------------------------------------------
# Translation layer — World lore
# ---------------------------------------------------------------------------

def _build_world_overview() -> str:
    """World overview from city_gazetteer.json (read-only file source, still valid)."""
    try:
        from pathlib import Path
        gz_path = Path(__file__).resolve().parents[1] / "campaign_docs/city_gazetteer.json"
        if gz_path.exists():
            gz = json.loads(gz_path.read_text(encoding="utf-8"))
            city = gz.get("city", {})
            districts = list(gz.get("districts", {}).items())
        else:
            city, districts = {}, []
    except Exception:
        city, districts = {}, []

    lines = [
        "# The Undercity — World Overview",
        "",
        city.get("description", (
            "A vast domed city of billions built under an artificial sky. "
            "The Tower of Last Chance pierces the dome's center. "
            "A city of wealth disparity, arcane technology, and constant political friction."
        )),
        "",
        "## Districts",
    ]
    for name, data in districts[:10]:
        desc = (data.get("description", "") if isinstance(data, dict) else "")[:180]
        lines.append(f"**{name}**: {desc}" if desc else f"**{name}**")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# NPC gear inference
# ---------------------------------------------------------------------------

_CLASS_GEAR: dict[str, list] = {
    "Wizard":       [("Spellbook", 1), ("Quarterstaff", 1), ("Arcane Focus", 1), ("Scholar's Pack", 1)],
    "Sorcerer":     [("Arcane Focus", 1), ("Dagger", 1), ("Dungeoneer's Pack", 1)],
    "Warlock":      [("Arcane Focus", 1), ("Dagger", 1), ("Scholar's Pack", 1)],
    "Artificer":    [("Tinker's Tools", 1), ("Light Crossbow", 1), ("Scale Mail", 1), ("Thieves' Tools", 1)],
    "Cleric":       [("Mace", 1), ("Shield", 1), ("Holy Symbol", 1), ("Chain Shirt", 1), ("Priest's Pack", 1)],
    "Paladin":      [("Longsword", 1), ("Shield", 1), ("Chain Mail", 1), ("Holy Symbol", 1)],
    "Fighter":      [("Longsword", 1), ("Shield", 1), ("Chain Mail", 1), ("Explorer's Pack", 1)],
    "Ranger":       [("Longbow", 1), ("Quiver of Arrows", 1), ("Shortsword", 1), ("Leather Armor", 1), ("Explorer's Pack", 1)],
    "Rogue":        [("Rapier", 1), ("Dagger", 2), ("Thieves' Tools", 1), ("Leather Armor", 1), ("Burglar's Pack", 1)],
    "Barbarian":    [("Greataxe", 1), ("Handaxe", 2), ("Hide Armor", 1), ("Explorer's Pack", 1)],
    "Druid":        [("Quarterstaff", 1), ("Druidic Focus", 1), ("Leather Armor", 1), ("Explorer's Pack", 1)],
    "Bard":         [("Rapier", 1), ("Lute", 1), ("Leather Armor", 1), ("Entertainer's Pack", 1)],
    "Monk":         [("Quarterstaff", 1), ("Dagger", 2)],
    "Blood Hunter": [("Longsword", 1), ("Leather Armor", 1), ("Explorer's Pack", 1)],
}
_DEFAULT_GEAR = [("Dagger", 1), ("Common Clothes", 1)]

# Role keyword → bonus items
_ROLE_EXTRAS: list[tuple[str, list]] = [
    ("guard",      [("Chain Mail", 1), ("Shield", 1)]),
    ("merchant",   [("Merchant's Scale", 1), ("Coin Purse", 1)]),
    ("scholar",    [("Book", 1), ("Ink and Quill", 1)]),
    ("librarian",  [("Book", 1), ("Ink and Quill", 1)]),
    ("researcher", [("Book", 1), ("Ink and Quill", 1)]),
    ("assassin",   [("Poison Vial", 1), ("Dark Cloak", 1)]),
    ("spy",        [("Disguise Kit", 1)]),
    ("healer",     [("Healer's Kit", 1), ("Herbalism Kit", 1)]),
    ("alchemist",  [("Alchemist's Supplies", 1)]),
    ("smith",      [("Smith's Tools", 1)]),
    ("thief",      [("Thieves' Tools", 1)]),
    ("cult",       [("Dark Robes", 1), ("Holy Symbol", 1)]),
    ("priest",     [("Holy Symbol", 1), ("Priest's Pack", 1)]),
]

# Appearance keyword → bonus item
_APPEARANCE_EXTRAS: list[tuple[str, str]] = [
    ("staff",         "Quarterstaff"),
    ("book",          "Spellbook"),
    ("tome",          "Ancient Tome"),
    ("scroll",        "Scroll of Identify"),
    ("crossbow",      "Light Crossbow"),
    ("bow",           "Shortbow"),
    ("sword",         "Longsword"),
    ("dagger",        "Dagger"),
    ("shield",        "Shield"),
    ("robes",         "Scholar's Robes"),
    ("armor",         "Leather Armor"),
    ("cloak",         "Dark Cloak"),
    ("mask",          "Masquerade Mask"),
    ("poison",        "Poison Vial"),
    ("flask",         "Flask of Oil"),
    ("crystal",       "Crystal Orb"),
    ("amulet",        "Amulet"),
    ("ring",          "Ring of Protection"),
    ("potion",        "Potion of Healing"),
]


def _infer_npc_gear(bridge: _NPCBridge) -> list:
    """
    Infer appropriate gear for an NPC from class, role, and appearance.
    Returns (name, qty) pairs.
    """
    seen: set  = set()
    gear: list = []

    def _add(name: str, qty: int = 1) -> None:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            gear.append((name, qty))

    # Class-based base kit
    cls = (bridge.dnd_class or "").strip()
    base = _CLASS_GEAR.get(cls, None)
    if base is None:
        # Try partial match (e.g. "Arcane Trickster" → Rogue)
        for known_cls, items in _CLASS_GEAR.items():
            if known_cls.lower() in cls.lower() or cls.lower() in known_cls.lower():
                base = items
                break
    for name, qty in (base or _DEFAULT_GEAR):
        _add(name, qty)

    # Role keyword extras
    role_lower = (bridge.role or "").lower()
    for keyword, extras in _ROLE_EXTRAS:
        if keyword in role_lower:
            for name, qty in extras:
                _add(name, qty)

    # Appearance keyword extras (from notes field which maps to description/appearance)
    appear_lower = (bridge.notes or "").lower()
    for keyword, item_name in _APPEARANCE_EXTRAS:
        if keyword in appear_lower and item_name.lower() not in seen:
            _add(item_name, 1)

    # High-level NPCs get a Potion of Healing
    if bridge.level >= 5:
        _add("Potion of Healing", 1)
    if bridge.level >= 10:
        _add("Potion of Greater Healing", 1)

    return gear


async def run_npc_gear_run(force: bool = False) -> dict:
    """
    Infer and write equipment for all living NPCs that lack it.
    Writes to MySQL data_json.equipment, then clears npc_gear hash so
    the next sync_npc() call pushes the gear to Mimir.

    Returns {"total": N, "done": N, "skipped": N, "failed": N}.
    """
    rows = raw_query(
        "SELECT id, name, data_json FROM npcs WHERE status NOT IN ('dead') LIMIT 500"
    )
    if not rows:
        return {"total": 0, "done": 0, "skipped": 0, "failed": 0}

    total = skipped = done = failed = 0

    for row in rows:
        total += 1
        npc_id = row["id"]
        dj: dict = {}
        try:
            dj = row["data_json"] if isinstance(row["data_json"], dict) else json.loads(row["data_json"] or "{}")
        except Exception:
            pass

        try:
            bridge = _npc_row_to_bridge(row)
            base_gear = bridge.gear if bridge.gear and not force else _infer_npc_gear(bridge)
            magic_gear = _infer_magic_gear(bridge.dnd_class, bridge.level, bridge.species, base_gear)
            normalised_base = await _catalog_normalise_gear(base_gear) if bridge.gear and not force else base_gear
            gear = await _catalog_normalise_gear(_merge_gear(base_gear, magic_gear))
            if not gear:
                skipped += 1
                continue
            if bridge.gear and not force and _gear_keys(gear) == _gear_keys(normalised_base):
                skipped += 1
                continue

            # Serialise as list of dicts for storage
            eq_json = _serialise_gear(gear)
            raw_execute(
                "UPDATE npcs SET data_json = JSON_SET(IFNULL(data_json,'{}'), '$.equipment', CAST(%s AS JSON)) WHERE id=%s",
                (eq_json, npc_id),
            )
            # Clear npc_gear hash so sync picks it up
            raw_execute(
                "UPDATE mimir_sync SET sync_hash=NULL WHERE entity_type='npc_gear' AND entity_id=%s",
                (str(npc_id),),
            )
            done += 1
            logger.debug(f"[MIMIR_SYNC] ⚙ NPC gear inferred: {bridge.name!r} — {len(gear)} items")
        except Exception as exc:
            logger.warning(f"[MIMIR_SYNC] Gear infer failed for NPC {npc_id}: {exc}")
            failed += 1

    logger.debug(f"[MIMIR_SYNC] NPC gear run: {done} done, {skipped} skipped, {failed} failed / {total} total")
    return {"total": total, "done": done, "skipped": skipped, "failed": failed}


async def run_epic_npc_gear_run(min_level: int = 13, force: bool = False, npc_name: str = "") -> dict:
    """
    Upgrade high-level NPCs with Mimir-catalog epic gear and derived AC.

    Only real Mimir catalog items are applied. Misses are reported and skipped;
    this path deliberately does not create homebrew placeholders.
    """
    mimir = get_mimir()
    if not mimir.available:
        return {
            "total": 0, "done": 0, "skipped": 0, "failed": 0,
            "catalog_misses": 0, "updated": [],
            "error": "Mimir MCP is not connected; epic gear requires catalog validation.",
        }

    where = "WHERE status NOT IN ('dead')"
    params: list[Any] = []
    if npc_name:
        where += " AND name=%s"
        params.append(npc_name)
    rows = raw_query(f"SELECT * FROM npcs {where} LIMIT 500", tuple(params))
    if not rows:
        return {"total": 0, "done": 0, "skipped": 0, "failed": 0, "catalog_misses": 0, "updated": []}

    total = skipped = done = failed = catalog_misses = 0
    updated: list[str] = []

    for row in rows:
        npc_id = row["id"]
        try:
            bridge = _npc_row_to_bridge(row)
            if int(bridge.level or 1) < int(min_level or 13):
                skipped += 1
                continue
            total += 1

            base_gear = bridge.gear or _infer_npc_gear(bridge)
            if force:
                base_gear = _infer_npc_gear(bridge)

            epic_gear, target_ac, missing = await _infer_epic_npc_gear(bridge, base_gear)
            catalog_misses += len(missing)

            if not epic_gear and target_ac <= int(bridge.ac or 0):
                skipped += 1
                continue

            if epic_gear:
                if force:
                    filtered_base = [
                        (name, qty) for name, qty in base_gear
                        if not _is_weapon_or_armor_replaced(name)
                    ]
                else:
                    filtered_base = base_gear
                gear = _merge_gear(filtered_base, epic_gear)
            else:
                gear = base_gear

            patch = {
                "equipment": [
                    {"name": n, "quantity": q, "equipped": True}
                    for n, q in gear
                ],
                "gear_tier": "epic",
                "epic_gear_applied_at": datetime.utcnow().isoformat() + "Z",
            }
            if target_ac > int(bridge.ac or 0):
                patch["stats"] = {"AC": target_ac}

            raw_execute(
                """
                UPDATE npcs
                   SET data_json = JSON_MERGE_PATCH(IFNULL(data_json, '{}'), CAST(%s AS JSON)),
                       updated_at = NOW()
                 WHERE id=%s
                """,
                (json.dumps(patch, ensure_ascii=False), npc_id),
            )
            raw_execute(
                "UPDATE mimir_sync SET sync_hash=NULL WHERE entity_type IN ('npc','npc_gear','npc_notes') AND entity_id=%s",
                (str(npc_id),),
            )
            done += 1
            updated.append(f"{bridge.name} (Lv {bridge.level}, AC {bridge.ac}->{target_ac}, +{len(epic_gear)} items)")
            logger.debug(f"[MIMIR_SYNC] Epic NPC gear applied: {bridge.name!r} +{len(epic_gear)} items AC {bridge.ac}->{target_ac}")
        except Exception as exc:
            failed += 1
            logger.warning(f"[MIMIR_SYNC] Epic gear failed for NPC {npc_id}: {exc}")

    logger.debug(
        f"[MIMIR_SYNC] Epic NPC gear run: {done} done, {skipped} skipped, "
        f"{failed} failed / {total} eligible; catalog_misses={catalog_misses}"
    )
    return {
        "total": total,
        "done": done,
        "skipped": skipped,
        "failed": failed,
        "catalog_misses": catalog_misses,
        "updated": updated,
    }


# ---------------------------------------------------------------------------
# Sync engine
# ---------------------------------------------------------------------------

class MimirSyncEngine:
    """
    Bidirectional sync between Tower MySQL and Mimir DM campaign.

    Translation layer enforces: bot data never touches Mimir format directly,
    Mimir data never touches MySQL format directly. All conversion goes through
    the _*Bridge dataclasses above.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Bot → Mimir: individual NPC
    # ------------------------------------------------------------------

    async def sync_npc(self, npc_id: int) -> bool:
        """Sync one NPC. Returns True if pushed. No-op if unavailable/unchanged."""
        mimir = get_mimir()
        if not mimir.available:
            return False

        rows = raw_query("SELECT * FROM npcs WHERE id=%s", (npc_id,))
        if not rows:
            return False

        row = rows[0]
        bridge = _npc_row_to_bridge(row)
        if bridge.status in ("dead",):
            return False

        # Extract data_json for notes doc — needed before bridge (bridge already parsed it,
        # but we need the raw dict to pass to _build_npc_notes)
        dj: dict = {}
        if row.get("data_json"):
            try:
                dj = row["data_json"] if isinstance(row["data_json"], dict) else json.loads(row["data_json"])
            except Exception:
                pass

        sync_row = _get_sync_row("npc", str(npc_id))
        hash_now = _npc_sync_hash(bridge)

        if sync_row and sync_row["sync_hash"] == hash_now and sync_row["mimir_id"]:
            return True  # nothing changed

        mimir_id = (sync_row or {}).get("mimir_id") or ""

        if not mimir_id:
            char = await mimir.create_character(**_bridge_to_mimir_create(bridge))
            if not char:
                return False
            mimir_id = char.get("id", "")
            if not mimir_id:
                return False
            raw_execute(
                "UPDATE npcs SET data_json = JSON_SET(IFNULL(data_json, '{}'), '$.mimir_id', %s) WHERE id=%s",
                (mimir_id, npc_id),
            )

        # Apply all editable fields: stats, race, role, location, faction
        edit_params = _bridge_to_mimir_edit(bridge)
        if edit_params:
            await mimir.edit_character(mimir_id, **edit_params)

        # Push gear — hash-gated, same pattern as PC gear
        if bridge.gear:
            gear_hash = _make_hash({"gear": bridge.gear})
            gear_row  = _get_sync_row("npc_gear", str(npc_id))
            if not (gear_row and gear_row["sync_hash"] == gear_hash):
                await _push_gear_to_mimir(mimir_id, bridge.gear)
                _upsert_sync("npc_gear", str(npc_id), mimir_id, gear_hash)

        # Push notes document — HP, AC, class, level, narrative fields that don't map to Mimir
        notes_content = _build_npc_notes(bridge, dj)
        if notes_content:
            notes_sync_row = _get_sync_row("npc_notes", str(npc_id))
            notes_hash = _make_hash({"notes": notes_content})
            if not (notes_sync_row and notes_sync_row["sync_hash"] == notes_hash):
                if notes_sync_row and notes_sync_row["mimir_id"]:
                    await mimir.delete_document(notes_sync_row["mimir_id"])
                doc_id = await mimir.add_document(
                    title    = f"{bridge.name} — DM Notes",
                    doc_type = "dm_notes",
                    content  = notes_content,
                )
                if doc_id:
                    _upsert_sync("npc_notes", str(npc_id), doc_id, notes_hash)

        _upsert_sync("npc", str(npc_id), mimir_id, hash_now)
        logger.debug(f"[MIMIR_SYNC] → NPC {bridge.name!r} synced ({mimir_id})")
        return True

    async def sync_all_npcs(self) -> int:
        rows = raw_query(
            "SELECT id FROM npcs WHERE status NOT IN ('dead') LIMIT 300"
        )
        if not rows:
            return 0
        count = 0
        for row in rows:
            try:
                if await self.sync_npc(row["id"]):
                    count += 1
                await asyncio.sleep(0.05)   # light throttle — don't hammer mimir-mcp
            except Exception as exc:
                logger.debug(f"[MIMIR_SYNC] NPC {row['id']} error: {exc}")
        logger.debug(f"[MIMIR_SYNC] NPCs pushed: {count}/{len(rows)}")
        return count

    # ------------------------------------------------------------------
    # Mimir → Bot: NPC stat changes
    # ------------------------------------------------------------------

    async def pull_npc_changes(self) -> int:
        """
        Pull Mimir → MySQL in two passes:
        1. Update known NPCs: ability scores, location, faction edited by DM in Mimir.
        2. New NPCs: characters created in Mimir that don't exist in MySQL yet → INSERT them.
        """
        mimir = get_mimir()
        if not mimir.available:
            return 0

        count = 0

        # --- Pass 1: patch edits to known NPCs ---
        synced = raw_query(
            "SELECT entity_id, mimir_id FROM mimir_sync "
            "WHERE entity_type='npc' AND mimir_id IS NOT NULL LIMIT 250"
        )
        total_synced = len(synced or [])
        if total_synced:
            logger.debug(f"[MIMIR_SYNC] Pulling known NPC changes from Mimir: {total_synced} rows")
        for idx, row in enumerate(synced or [], start=1):
            try:
                char = await mimir.get_character(row["mimir_id"])
                if not char:
                    continue

                patch = _mimir_char_to_bot_patch(char)
                col_patch  = patch.get("columns", {})
                json_patch = patch.get("json", {})
                if not col_patch and not json_patch:
                    continue

                pull_hash = _make_hash(patch)
                pull_row  = _get_sync_row("npc_pull", row["entity_id"])
                if pull_row and pull_row["sync_hash"] == pull_hash:
                    continue

                npc_id = int(row["entity_id"])
                if col_patch:
                    set_parts = [f"{k}=%s" for k in col_patch]
                    raw_execute(
                        f"UPDATE npcs SET {', '.join(set_parts)} WHERE id=%s",
                        list(col_patch.values()) + [npc_id],
                    )
                if json_patch:
                    json_set_parts = []
                    if any(k.startswith("stats.") for k in json_patch):
                        json_set_parts.append(
                            "'$.stats', COALESCE(JSON_EXTRACT(data_json, '$.stats'), JSON_OBJECT())"
                        )
                    json_set_parts.extend([f"'$.{k}', %s" for k in json_patch])
                    json_args = ", ".join(json_set_parts)
                    raw_execute(
                        f"UPDATE npcs SET data_json = JSON_SET(IFNULL(data_json,'{{}}'), {json_args}) WHERE id=%s",
                        list(json_patch.values()) + [npc_id],
                    )
                _upsert_sync("npc_pull", row["entity_id"], row["mimir_id"], pull_hash)
                count += 1
                logger.debug(
                    f"[MIMIR_SYNC] ← NPC {row['entity_id']} patched "
                    f"cols={list(col_patch)} json={list(json_patch)}"
                )

            except Exception as exc:
                logger.debug(f"[MIMIR_SYNC] Pull NPC {row['entity_id']} error: {exc}")
            finally:
                if total_synced and idx % max(MIMIR_PULL_PROGRESS_EVERY, 1) == 0:
                    logger.debug(f"[MIMIR_SYNC] NPC pull progress: {idx}/{total_synced} checked, {count} changed")
                await asyncio.sleep(MIMIR_PULL_NPC_SLEEP)

        if total_synced:
            logger.debug(f"[MIMIR_SYNC] NPC pull known-pass complete: {total_synced} checked, {count} changed")

        # --- Pass 2: detect new NPCs created in Mimir ---
        try:
            all_mimir_npcs = await mimir.list_characters(character_type="npc")
            known_ids = {
                r["mimir_id"]
                for r in raw_query(
                    "SELECT mimir_id FROM mimir_sync WHERE entity_type='npc' AND mimir_id IS NOT NULL"
                )
            }
            for char in all_mimir_npcs:
                char_id = char.get("id", "")
                if not char_id or char_id in known_ids:
                    continue
                # New NPC — exists in Mimir but not in MySQL
                ins = _mimir_char_to_npc_insert(char)
                try:
                    raw_execute(
                        "INSERT INTO npcs (name, faction, status, role, location, data_json) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (ins["name"], ins["faction"], ins["status"],
                         ins["role"], ins["location"], ins["data_json"]),
                    )
                    new_row = raw_query(
                        "SELECT id FROM npcs WHERE name=%s ORDER BY id DESC LIMIT 1",
                        (ins["name"],),
                    )
                    if new_row:
                        npc_id = new_row[0]["id"]
                        _upsert_sync("npc", str(npc_id), char_id, "")  # empty hash → pushes notes on next cycle
                        count += 1
                        logger.info(f"[MIMIR_SYNC] ← New NPC from Mimir: {ins['name']!r} (id={npc_id})")
                except Exception as exc:
                    logger.warning(f"[MIMIR_SYNC] New NPC insert failed ({ins['name']!r}): {exc}")

        except Exception as exc:
            logger.warning(f"[MIMIR_SYNC] New-NPC detection failed: {exc}")

        if count:
            logger.info(f"[MIMIR_SYNC] Mimir → MySQL: {count} NPCs updated/created")
        return count

    # ------------------------------------------------------------------
    # Bot → Mimir: Party characters
    # ------------------------------------------------------------------

    async def sync_party(self) -> int:
        """Sync player_characters (MySQL) as PCs in Mimir. Returns count synced."""
        mimir = get_mimir()
        if not mimir.available:
            return 0

        # player_characters is the MySQL source of truth for PCs
        rows = raw_query(
            "SELECT * FROM player_characters ORDER BY name LIMIT 30"
        )
        if not rows:
            return 0

        count = 0
        for row in rows:
            try:
                bridge = _player_char_to_bridge(row)
                if not bridge:
                    continue

                hash_now = _pc_sync_hash(bridge)
                sync_row = _get_sync_row("pc", str(bridge.bot_id))

                if sync_row and sync_row["sync_hash"] == hash_now and sync_row["mimir_id"]:
                    count += 1
                    continue

                is_new = not (sync_row and sync_row["mimir_id"])

                if not is_new:
                    mimir_id = sync_row["mimir_id"]
                    edit_p = _bridge_to_mimir_pc_edit(bridge)
                    if edit_p:
                        await mimir.edit_character(mimir_id, **edit_p)
                else:
                    char = await mimir.create_character(**_bridge_to_mimir_pc_create(bridge))
                    if not char:
                        continue
                    mimir_id = char.get("id", "")
                    if not mimir_id:
                        continue
                    edit_p = _bridge_to_mimir_pc_edit(bridge)
                    if edit_p:
                        await mimir.edit_character(mimir_id, **edit_p)

                # Push gear
                if bridge.gear:
                    gear_hash = _make_hash({"gear": bridge.gear})
                    gear_row  = _get_sync_row("pc_gear", str(bridge.bot_id))
                    if not (gear_row and gear_row["sync_hash"] == gear_hash):
                        await _push_gear_to_mimir(mimir_id, bridge.gear)
                        _upsert_sync("pc_gear", str(bridge.bot_id), mimir_id, gear_hash)

                # Push spells (hash-gated — only re-syncs when spell list changes)
                if bridge.spells:
                    spell_names = sorted(s["name"] for s in bridge.spells)
                    spell_hash  = _make_hash({"spells": spell_names})
                    spell_row   = _get_sync_row("pc_spells", str(bridge.bot_id))
                    if not (spell_row and spell_row["sync_hash"] == spell_hash):
                        primary_class = bridge.class_name or "Wizard"
                        for sp in bridge.spells:
                            try:
                                await mimir.add_character_spell(
                                    mimir_id,
                                    spell_name   = sp["name"],
                                    source_class = sp.get("class") or primary_class,
                                    prepared     = sp.get("prepared", False),
                                )
                                await asyncio.sleep(0.02)
                            except Exception:
                                pass
                        _upsert_sync("pc_spells", str(bridge.bot_id), mimir_id, spell_hash)
                        logger.debug(f"[MIMIR_SYNC] → PC {bridge.name!r} spells: {len(bridge.spells)}")

                _upsert_sync("pc", str(bridge.bot_id), mimir_id, hash_now)
                count += 1
                logger.debug(
                    f"[MIMIR_SYNC] → PC {bridge.name!r} synced "
                    f"(gear={len(bridge.gear)}, spells={len(bridge.spells)}, gp={bridge.currencies.get('gp',0)})"
                )
                await asyncio.sleep(0.05)

            except Exception as exc:
                logger.debug(f"[MIMIR_SYNC] PC sync error: {exc}")

        logger.debug(f"[MIMIR_SYNC] Party synced: {count}/{len(rows)}")
        return count

    # ------------------------------------------------------------------
    # Bot → Mimir: Faction documents
    # ------------------------------------------------------------------

    async def sync_faction(self, faction_name: str) -> bool:
        """Sync one faction as a campaign document. Returns True on success."""
        mimir = get_mimir()
        if not mimir.available:
            return False

        rows = raw_query(
            "SELECT * FROM faction_reputation WHERE faction_name=%s", (faction_name,)
        )
        if not rows:
            return False

        content  = _faction_row_to_doc(rows[0])
        hash_now = _make_hash({"content": content})
        sync_row = _get_sync_row("faction", faction_name)

        if sync_row and sync_row["sync_hash"] == hash_now and sync_row["mimir_id"]:
            return True

        if sync_row and sync_row["mimir_id"]:
            # Delete + recreate (Mimir may not have update_document)
            await mimir.delete_document(sync_row["mimir_id"])

        doc_id = await mimir.add_document(
            title    = faction_name,
            doc_type = "description",
            content  = content,
        )
        if not doc_id:
            return False

        _upsert_sync("faction", faction_name, doc_id, hash_now)
        logger.debug(f"[MIMIR_SYNC] → Faction {faction_name!r} synced")
        return True

    async def sync_all_factions(self) -> int:
        rows = raw_query("SELECT faction_name FROM faction_reputation")
        if not rows:
            return 0
        count = 0
        for row in rows:
            try:
                if await self.sync_faction(row["faction_name"]):
                    count += 1
                await asyncio.sleep(0.05)
            except Exception as exc:
                logger.debug(f"[MIMIR_SYNC] Faction error: {exc}")
        logger.debug(f"[MIMIR_SYNC] Factions synced: {count}/{len(rows)}")
        return count

    # ------------------------------------------------------------------
    # Mimir → Bot: Faction doc changes
    # ------------------------------------------------------------------

    async def pull_faction_changes(self) -> int:
        """Pull DM edits to faction docs back into MySQL."""
        mimir = get_mimir()
        if not mimir.available:
            return 0

        synced = raw_query(
            "SELECT entity_id, mimir_id FROM mimir_sync "
            "WHERE entity_type='faction' AND mimir_id IS NOT NULL"
        )
        if not synced:
            return 0

        count = 0
        for row in synced:
            try:
                doc = await mimir.read_document(row["mimir_id"])
                if not doc:
                    continue

                patch = _mimir_doc_to_faction_patch(doc)
                if not patch:
                    continue

                pull_hash = _make_hash(patch)
                pull_row = _get_sync_row("faction_pull", row["entity_id"])
                if pull_row and pull_row["sync_hash"] == pull_hash:
                    continue

                set_parts = [f"{k}=%s" for k in patch]
                vals = list(patch.values()) + [row["entity_id"]]
                raw_execute(
                    f"UPDATE faction_reputation SET {', '.join(set_parts)} WHERE faction_name=%s",
                    vals,
                )
                _upsert_sync("faction_pull", row["entity_id"], row["mimir_id"], pull_hash)
                count += 1

            except Exception as exc:
                logger.debug(f"[MIMIR_SYNC] Faction pull error: {exc}")

        if count:
            logger.info(f"[MIMIR_SYNC] Faction updates pulled: {count}")
        return count

    # ------------------------------------------------------------------
    # Bot → Mimir: World lore
    # ------------------------------------------------------------------

    async def sync_world_lore(self) -> bool:
        mimir = get_mimir()
        if not mimir.available:
            return False

        content  = _build_world_overview()
        hash_now = _make_hash({"content": content})
        sync_row = _get_sync_row("world", "undercity_overview")

        if sync_row and sync_row["sync_hash"] == hash_now and sync_row["mimir_id"]:
            return True

        if sync_row and sync_row["mimir_id"]:
            await mimir.delete_document(sync_row["mimir_id"])

        doc_id = await mimir.add_document(
            title    = "Undercity — World Overview",
            doc_type = "backstory",
            content  = content,
        )
        if not doc_id:
            return False

        _upsert_sync("world", "undercity_overview", doc_id, hash_now)
        logger.debug("[MIMIR_SYNC] → World lore synced")
        return True

    # ------------------------------------------------------------------
    # Full sync
    # ------------------------------------------------------------------

    async def full_sync(self) -> None:
        if not get_mimir().available:
            return

        logger.debug("[MIMIR_SYNC] Full sync starting…")
        # Push world + factions first (cheap, no per-row throttle needed)
        await asyncio.gather(
            self.sync_world_lore(),
            self.sync_all_factions(),
            return_exceptions=True,
        )
        # NPCs — largest set, throttled internally
        await self.sync_all_npcs()
        # Party chars
        await self.sync_party()
        # Pull back DM edits
        await self.pull_npc_changes()
        await self.pull_faction_changes()
        logger.debug("[MIMIR_SYNC] Full sync complete")

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        self._running = True
        logger.info(f"[MIMIR_SYNC] Background loop started (interval={SYNC_INTERVAL}s)")
        while self._running:
            await asyncio.sleep(SYNC_INTERVAL)
            try:
                await self.full_sync()
            except Exception as exc:
                logger.warning(f"[MIMIR_SYNC] Loop error: {exc}")

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()


# ---------------------------------------------------------------------------
# Singleton + public trigger hooks
# ---------------------------------------------------------------------------

_engine = MimirSyncEngine()


def get_sync_engine() -> MimirSyncEngine:
    return _engine


async def startup_sync() -> None:
    """
    Called from bot on_ready after Mimir connects.
    Creates DB table, runs full sync, then starts background loop.
    """
    ensure_sync_table()
    await _engine.full_sync()
    _engine.start()


def trigger_npc_sync(npc_id: int) -> None:
    """
    Fire-and-forget hook — call after any NPC create/update/status change.
    Safe to call from sync code; creates an asyncio task if a loop is running.
    """
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            loop.create_task(_engine.sync_npc(npc_id))
    except Exception:
        pass


def trigger_faction_sync(faction_name: str) -> None:
    """Fire-and-forget hook — call after faction_reputation changes."""
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            loop.create_task(_engine.sync_faction(faction_name))
    except Exception:
        pass


def trigger_pc_mimir_sync(char_name: str) -> None:
    """
    Fire-and-forget hook — called by character_monitor when DDB detects a change.
    Clears that PC's sync hash so the next sync_party cycle pushes fresh data.
    """
    try:
        rows = raw_query(
            "SELECT id FROM player_characters WHERE name=%s LIMIT 1", (char_name,)
        )
        if rows:
            pc_id = str(rows[0]["id"])
            raw_execute(
                "UPDATE mimir_sync SET sync_hash=NULL WHERE entity_type='pc' AND entity_id=%s",
                (pc_id,),
            )
            # Also clear gear/spell hashes so full re-push happens
            raw_execute(
                "UPDATE mimir_sync SET sync_hash=NULL "
                "WHERE entity_type IN ('pc_gear','pc_spells') AND entity_id=%s",
                (pc_id,),
            )
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(_engine.sync_party())
    except Exception:
        pass
