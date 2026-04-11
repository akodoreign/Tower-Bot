"""
character_monitor.py — D&D Beyond character sheet change detector.

Polls the DDB character-service API for each campaign PC every 30 minutes.
When anything meaningful changes (level, HP, stats, inventory, feats, XP,
notes/Kharma) it posts a formatted diff embed to the DM channel.

No auth required — DDB's character-service endpoint is publicly accessible
for shared characters. Same endpoint Avrae uses.

Character IDs (from campaign roster):
  Frank           151018164   akodoreign
  Eleanor Reed    150944498   zoya7813
  S'kree          151107333   Skaree
  Boxxo           151180186   akodoreign
  Geralt          152890235   akodoreign
  Keta Fadeworth  153045941   XALIZAR11
  Ragard          150949635   akurarian
  Lammis          162140590   akodoreign
"""

from __future__ import annotations

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from src.log import logger
from src.db_api import (
    get_character_snapshot, save_character_snapshot,
    get_previous_snapshot, cleanup_old_snapshots
)

# ---------------------------------------------------------------------------
# Campaign characters — IDs hardcoded, names for display
# ---------------------------------------------------------------------------

CAMPAIGN_CHARACTERS = [
    {"name": "Frank",          "id": 151018164, "player": "akodoreign"},
    {"name": "Eleanor Reed",   "id": 150944498, "player": "zoya7813"},
    {"name": "S'kree",         "id": 151107333, "player": "Skaree"},
    {"name": "Boxxo",          "id": 151180186, "player": "akodoreign"},
    {"name": "Geralt",         "id": 152890235, "player": "akodoreign"},
    {"name": "Keta Fadeworth", "id": 153045941, "player": "XALIZAR11"},
    {"name": "Ragard",         "id": 150949635, "player": "akurarian"},
    {"name": "Lammis",         "id": 162140590, "player": "akodoreign"},
]

DDB_BASE      = "https://character-service.dndbeyond.com/character/v5/character"
POLL_INTERVAL = 30 * 60   # 30 minutes between full sweeps
REQUEST_GAP   = 8         # seconds between individual character fetches

# Keep file-based backup for character_memory.txt updates
DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"

# Stat IDs as DDB returns them
_STAT_NAMES = {1: "STR", 2: "DEX", 3: "CON", 4: "INT", 5: "WIS", 6: "CHA"}

# Notes fields we track, in display order. otherNotes is the Kharma tracker.
_NOTE_FIELDS = [
    ("otherNotes",        "Notes / Kharma"),   # primary Kharma tracking field
    ("personalityTraits", "Personality Traits"),
    ("ideals",            "Ideals"),
    ("bonds",             "Bonds"),
    ("flaws",             "Flaws"),
    ("appearance",        "Appearance"),
    ("organizations",     "Organizations"),
    ("allies",            "Allies"),
    ("enemies",           "Enemies"),
    ("backstory",         "Backstory"),
]


# ---------------------------------------------------------------------------
# Snapshot persistence (DATABASE-BACKED)
# ---------------------------------------------------------------------------

def _load_snapshot(char_id: int) -> Optional[dict]:
    """Load latest snapshot from database."""
    result = get_character_snapshot(char_id)
    if result and result.get("snapshot_json"):
        return result["snapshot_json"]
    return None


def _load_previous_snapshot(char_id: int) -> Optional[dict]:
    """Load previous snapshot from database."""
    result = get_previous_snapshot(char_id)
    if result and result.get("snapshot_json"):
        return result["snapshot_json"]
    return None


def _save_snapshot(char_id: int, char_name: str, player: str, snapshot: dict) -> None:
    """Save new snapshot to database. Keeps only last 5 snapshots per character."""
    try:
        save_character_snapshot(char_id, char_name, player, snapshot)
        # Cleanup old snapshots (keep last 5)
        cleanup_old_snapshots(char_id, keep_count=5)
    except Exception as e:
        logger.error(f"📊 Snapshot save error for {char_id}: {e}")


# ---------------------------------------------------------------------------
# Fetch & parse
# ---------------------------------------------------------------------------

# Headers that mimic a real browser hitting the DDB character API.
# DDB's character-service rejects bare/minimal requests with 403 for newer character IDs.
_DDB_HEADERS = {
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control":   "no-cache",
    "Origin":          "https://www.dndbeyond.com",
    "Referer":         "https://www.dndbeyond.com/",
    "User-Agent":      (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


async def _fetch_character(char_id: int) -> Optional[dict]:
    """Fetch raw JSON from DDB character-service. Returns the 'data' dict or None."""
    import os as _os
    url = f"{DDB_BASE}/{char_id}"

    headers = dict(_DDB_HEADERS)  # copy so we don't mutate the module-level dict

    # Optional: cobalt-token from .env lets us fetch private/auth-gated sheets.
    # Set DDB_COBALT_TOKEN in .env to enable. Safe to omit for public sheets.
    cobalt = _os.getenv("DDB_COBALT_TOKEN", "").strip()
    if cobalt:
        headers["Cookie"] = f"cobalt-token={cobalt}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            payload = r.json()
        return payload.get("data") or payload
    except httpx.HTTPStatusError as e:
        logger.warning(f"📊 DDB fetch {char_id}: HTTP {e.response.status_code}")
        return None
    except Exception as e:
        logger.warning(f"📊 DDB fetch {char_id}: {e}")
        return None


def _parse_snapshot(data: dict) -> dict:
    """
    Extract the fields we care about into a flat, comparable dict.
    Keeps only things that meaningfully change between sessions.
    """
    snap: dict = {}

    # --- Identity ---
    snap["name"] = data.get("name", "Unknown")

    # --- Class / Level ---
    classes = data.get("classes") or []
    snap["classes"] = {
        cls["definition"]["name"]: cls["level"]
        for cls in classes
        if cls.get("definition") and cls.get("level")
    }
    snap["total_level"] = sum(snap["classes"].values()) if snap["classes"] else 0

    # --- HP ---
    base_hp  = data.get("baseHitPoints") or 0
    bonus_hp = data.get("bonusHitPoints") or 0
    override = data.get("overrideHitPoints")
    snap["max_hp"] = override if override is not None else (base_hp + bonus_hp)

    # --- AC override (if set manually) ---
    snap["ac_override"] = data.get("overrideArmorClass")

    # --- Ability scores ---
    stats_raw = data.get("stats") or []
    snap["stats"] = {
        _STAT_NAMES[s["id"]]: s["value"]
        for s in stats_raw
        if s.get("id") in _STAT_NAMES and s.get("value") is not None
    }

    # --- XP ---
    snap["xp"] = data.get("currentXp") or 0

    # --- Currency ---
    currencies = data.get("currencies") or {}
    snap["currencies"] = {
        k: currencies.get(k, 0) for k in ("cp", "sp", "ep", "gp", "pp")
    }

    # --- Inventory: item names + quantities ---
    inventory = data.get("inventory") or []
    item_counts: dict = {}
    for slot in inventory:
        defn = slot.get("definition") or {}
        name = defn.get("name") or (slot.get("customItem") or {}).get("name")
        if name:
            qty = slot.get("quantity") or 1
            item_counts[name] = item_counts.get(name, 0) + qty
    snap["inventory"] = item_counts

    # --- Feats ---
    feats = data.get("feats") or []
    snap["feats"] = sorted(
        f["definition"]["name"]
        for f in feats
        if f.get("definition") and f["definition"].get("name")
    )

    # --- Spell slots (max per level) ---
    spell_slots_raw = data.get("spellSlots") or []
    snap["spell_slots"] = {
        str(sl["level"]): sl.get("max", 0)
        for sl in spell_slots_raw
        if sl.get("level") and sl.get("max", 0) > 0
    }

    # --- Notes (all free-text fields including otherNotes where Kharma lives) ---
    notes_raw = data.get("notes") or {}
    snap["notes"] = {
        key: (notes_raw.get(key) or "").strip()
        for key, _label in _NOTE_FIELDS
        if (notes_raw.get(key) or "").strip()   # only store non-empty fields
    }

    snap["fetched_at"] = datetime.now().isoformat()
    return snap


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------

def _diff_snapshots(old: dict, new: dict, char_name: str) -> list[str]:
    """
    Compare old and new snapshots. Returns a list of human-readable change strings.
    Empty list = no relevant changes.
    """
    changes = []

    # Level / class changes
    old_cls = old.get("classes", {})
    new_cls = new.get("classes", {})
    for cls, lvl in new_cls.items():
        old_lvl = old_cls.get(cls)
        if old_lvl is None:
            changes.append(f"\U0001f195 New class: **{cls}** (level {lvl})")
        elif lvl != old_lvl:
            direction = "\u2b06\ufe0f" if lvl > old_lvl else "\u2b07\ufe0f"
            changes.append(f"{direction} **{cls}** level {old_lvl} \u2192 {lvl}")
    for cls in old_cls:
        if cls not in new_cls:
            changes.append(f"\u274c Lost class: **{cls}**")

    # Total level
    if new.get("total_level") != old.get("total_level"):
        changes.append(
            f"\U0001f4c8 Total level: {old.get('total_level', '?')} \u2192 **{new.get('total_level', '?')}**"
        )

    # HP
    if new.get("max_hp") != old.get("max_hp"):
        changes.append(
            f"\u2764\ufe0f Max HP: {old.get('max_hp', '?')} \u2192 **{new.get('max_hp', '?')}**"
        )

    # AC override
    if new.get("ac_override") != old.get("ac_override"):
        if new.get("ac_override") is not None:
            changes.append(f"\U0001f6e1\ufe0f AC override set to **{new['ac_override']}**")
        else:
            changes.append("\U0001f6e1\ufe0f AC override removed")

    # Stats
    old_stats = old.get("stats", {})
    new_stats = new.get("stats", {})
    for stat, val in new_stats.items():
        if stat in old_stats and old_stats[stat] != val:
            changes.append(f"\U0001f3b2 **{stat}**: {old_stats[stat]} \u2192 {val}")

    # XP
    old_xp = old.get("xp", 0)
    new_xp = new.get("xp", 0)
    if new_xp != old_xp:
        diff = new_xp - old_xp
        sign = "+" if diff >= 0 else ""
        changes.append(f"\u2728 XP: {old_xp:,} \u2192 {new_xp:,} ({sign}{diff:,})")

    # Currency
    old_cur = old.get("currencies", {})
    new_cur = new.get("currencies", {})
    cur_changes = []
    for coin in ("pp", "gp", "ep", "sp", "cp"):
        o = old_cur.get(coin, 0)
        n = new_cur.get(coin, 0)
        if o != n:
            diff = n - o
            sign = "+" if diff >= 0 else ""
            cur_changes.append(f"{sign}{diff} {coin}")
    if cur_changes:
        changes.append(f"\U0001f4b0 Currency: {', '.join(cur_changes)}")

    # Inventory
    old_inv = old.get("inventory", {})
    new_inv = new.get("inventory", {})
    all_items = set(old_inv) | set(new_inv)
    gained, lost, qty_changed = [], [], []
    for item in sorted(all_items):
        o_qty = old_inv.get(item, 0)
        n_qty = new_inv.get(item, 0)
        if o_qty == 0 and n_qty > 0:
            gained.append(f"**{item}**" + (f" \u00d7{n_qty}" if n_qty > 1 else ""))
        elif n_qty == 0 and o_qty > 0:
            lost.append(f"**{item}**" + (f" \u00d7{o_qty}" if o_qty > 1 else ""))
        elif o_qty != n_qty:
            qty_changed.append(f"**{item}**: {o_qty} \u2192 {n_qty}")
    if gained:
        changes.append(f"\U0001f392 Gained: {', '.join(gained)}")
    if lost:
        changes.append(f"\U0001f5d1\ufe0f Lost: {', '.join(lost)}")
    if qty_changed:
        changes.append(f"\U0001f4e6 Quantity change: {', '.join(qty_changed)}")

    # Feats
    old_feats = set(old.get("feats", []))
    new_feats = set(new.get("feats", []))
    for feat in sorted(new_feats - old_feats):
        changes.append(f"\u2b50 New feat: **{feat}**")
    for feat in sorted(old_feats - new_feats):
        changes.append(f"\u274c Lost feat: **{feat}**")

    # Spell slots (max per level)
    old_slots = old.get("spell_slots", {})
    new_slots = new.get("spell_slots", {})
    all_levels = set(old_slots) | set(new_slots)
    slot_changes = []
    for lvl in sorted(all_levels, key=lambda x: int(x)):
        o = old_slots.get(lvl, 0)
        n = new_slots.get(lvl, 0)
        if o != n:
            slot_changes.append(f"L{lvl}: {o}\u2192{n}")
    if slot_changes:
        changes.append(f"\U0001f52e Spell slots (max): {', '.join(slot_changes)}")

    # Notes — diff each field. otherNotes gets a special 📓 emoji (Kharma tracker).
    old_notes = old.get("notes", {})
    new_notes = new.get("notes", {})
    for key, label in _NOTE_FIELDS:
        o_text = old_notes.get(key, "").strip()
        n_text = new_notes.get(key, "").strip()
        if o_text == n_text:
            continue
        emoji = "\U0001f4d3" if key == "otherNotes" else "\U0001f4dd"
        if not o_text:
            # Field newly populated
            preview = n_text[:200] + ("\u2026" if len(n_text) > 200 else "")
            changes.append(f"{emoji} **{label}** set:\n> {preview}")
        elif not n_text:
            # Field cleared
            changes.append(f"{emoji} **{label}** cleared")
        else:
            # Content changed — show before/after truncated
            o_preview = o_text[:150] + ("\u2026" if len(o_text) > 150 else "")
            n_preview = n_text[:150] + ("\u2026" if len(n_text) > 150 else "")
            changes.append(
                f"{emoji} **{label}** changed:\n"
                f"> *was:* {o_preview}\n"
                f"> *now:* {n_preview}"
            )

    return changes


# ---------------------------------------------------------------------------
# Auto-update character_memory.txt with fresh DDB data
# ---------------------------------------------------------------------------

def _find_character_block(text: str, char_name: str) -> tuple[int, int] | None:
    """
    Find the start and end indices of a character block in character_memory.txt.
    
    Returns:
        (start_idx, end_idx) tuple if found, None otherwise
    """
    sep = "---CHARACTER---"
    blocks = text.split(sep)
    
    current_pos = 0
    for i, block in enumerate(blocks):
        block_start = current_pos
        block_end = current_pos + len(block)
        
        # Check if this block contains the character
        # Look for "NAME: {name}" anywhere in block (case-insensitive comparison)
        for line in block.split("\n"):
            if line.strip().upper().startswith("NAME:"):
                # Extract name from "NAME: CharName" format
                parts = line.split(":", 1)
                if len(parts) == 2:
                    stored_name = parts[1].strip()
                    if stored_name.lower() == char_name.lower():
                        # Found it — return absolute positions
                        return (block_start, block_end)
        
        current_pos = block_end + len(sep)
    
    return None


def _update_character_memory(char_name: str, snap: dict) -> bool:
    """
    Update mechanical fields for a character in MySQL player_characters table.
    Also keeps character_memory.txt in sync as a fallback/RAG source.
    Only updates mechanical fields (class, HP, stats, XP, currency, inventory).
    Preserves manual fields (ORACLE NOTES, PERSONALITY, etc).

    Returns:
        True if updated successfully, False otherwise
    """
    import json as _json
    # --- MySQL update ---
    try:
        from src.db_api import raw_query as _rq, raw_execute as _rx
        rows = _rq("SELECT id, profile_json FROM player_characters WHERE name=%s", (char_name,))
        if rows:
            profile = rows[0].get("profile_json") or {}
            if isinstance(profile, str):
                try:
                    profile = _json.loads(profile)
                except Exception:
                    profile = {}
            # Overwrite mechanical keys
            if snap.get("classes"):
                profile["CLASS"] = " / ".join(f"{c} {l}" for c, l in snap["classes"].items())
            if snap.get("max_hp"):
                profile["HP"] = str(snap["max_hp"])
            if snap.get("stats"):
                profile["STATS"] = " | ".join(f"{k} {v}" for k, v in snap["stats"].items())
            if snap.get("currencies"):
                cur_parts = [f"{v}{k.upper()}" for k, v in snap["currencies"].items() if v > 0]
                profile["CURRENCY"] = ", ".join(cur_parts) if cur_parts else "0GP"
            if snap.get("xp") is not None:
                profile["XP"] = str(snap["xp"])
            cls_str = profile.get("CLASS", "")
            _rx(
                "UPDATE player_characters SET class_name=%s, profile_json=%s, updated_at=NOW() WHERE id=%s",
                (cls_str, _json.dumps(profile, ensure_ascii=False), rows[0]["id"])
            )
            logger.info(f"📊 {char_name}: player_characters DB updated")
    except Exception as e:
        logger.warning(f"📊 {char_name}: DB update failed ({e}), falling back to file only")

    # --- txt file update (keep in sync for RAG) ---
    mem_file = Path(__file__).resolve().parent.parent / "campaign_docs" / "character_memory.txt"
    if not mem_file.exists():
        logger.warning(f"📊 character_memory.txt not found")
        return False

    try:
        text = mem_file.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"📊 Could not read character_memory.txt: {e}")
        return False

    # Find the character block
    block_range = _find_character_block(text, char_name)
    if block_range is None:
        logger.warning(f"📊 {char_name}: not found in character_memory.txt")
        return False
    
    start_idx, end_idx = block_range
    char_block = text[start_idx:end_idx]
    lines = char_block.split("\n")
    
    new_lines = []
    field_updated = {
        "CLASS": False,
        "HP": False,
        "STATS": False,
        "CURRENCY": False,
        "XP": False,
        "INVENTORY": False,
    }
    
    for line in lines:
        # Extract field name (part before first colon only)
        if ":" not in line:
            new_lines.append(line)
            continue
        
        key = line.split(":")[0].strip().upper()
        
        # Replace mechanical fields with fresh DDB data
        if key == "CLASS" and snap.get("classes"):
            cls_str = " / ".join(f"{c} {l}" for c, l in snap.get("classes", {}).items())
            new_lines.append(f"CLASS: {cls_str}")
            field_updated["CLASS"] = True
        elif key == "HP" and snap.get("max_hp"):
            new_lines.append(f"HP: {snap.get('max_hp', '?')}")
            field_updated["HP"] = True
        elif key == "STATS" and snap.get("stats"):
            stats = snap.get("stats", {})
            stat_str = " | ".join(f"{k} {v}" for k, v in stats.items())
            new_lines.append(f"STATS: {stat_str}")
            field_updated["STATS"] = True
        elif key == "CURRENCY" and snap.get("currencies"):
            cur = snap.get("currencies", {})
            cur_parts = [f"{v}{k.upper()}" for k, v in cur.items() if v > 0]
            new_lines.append(f"CURRENCY: {', '.join(cur_parts) if cur_parts else '0GP'}")
            field_updated["CURRENCY"] = True
        elif key == "XP" and snap.get("xp") is not None:
            new_lines.append(f"XP: {snap.get('xp', 0):,}")
            field_updated["XP"] = True
        elif key == "INVENTORY" and snap.get("inventory"):
            # Format: item (qty), item (qty)
            inv = snap.get("inventory", {})
            inv_parts = [f"{name} ({qty})" for name, qty in inv.items()]
            new_lines.append(f"INVENTORY: {', '.join(inv_parts) if inv_parts else 'empty'}")
            field_updated["INVENTORY"] = True
        else:
            # Preserve all other fields (ORACLE NOTES, PERSONALITY, etc)
            new_lines.append(line)
    
    # Reconstruct the file
    new_block = "\n".join(new_lines)
    sep = "---CHARACTER---"
    new_text = text[:start_idx] + new_block + text[end_idx:]
    
    try:
        mem_file.write_text(new_text, encoding="utf-8")
        updates = [k for k, v in field_updated.items() if v]
        logger.info(f"✅ {char_name}: character_memory.txt updated ({', '.join(updates)})")
        return True
    except Exception as e:
        logger.error(f"❌ {char_name}: failed to write character_memory.txt: {e}")
        return False


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

async def run_character_monitor(channel) -> None:
    """
    Called once from aclient.py. Loops forever, polling each character every
    POLL_INTERVAL seconds and posting change embeds to `channel`.
    """
    logger.info("📊 Character monitor loop started")

    # On first run, seed snapshots silently so we have a baseline to diff against.
    first_run = not any(_load_snapshot(c["id"]) for c in CAMPAIGN_CHARACTERS)
    if first_run:
        logger.info("📊 First run — seeding character snapshots silently...")
        for char_info in CAMPAIGN_CHARACTERS:
            data = await _fetch_character(char_info["id"])
            if data:
                snap = _parse_snapshot(data)
                _save_snapshot(char_info["id"], char_info["name"], char_info["player"], snap)
                logger.info(f"📊 Seeded: {snap['name']} (level {snap['total_level']})")
            await asyncio.sleep(REQUEST_GAP)
        logger.info("📊 Snapshots seeded. Monitoring begins next cycle.")
        await asyncio.sleep(POLL_INTERVAL)

    while True:
        logger.info(f"📊 Character monitor: polling {len(CAMPAIGN_CHARACTERS)} characters...")
        success, failed, changed = 0, 0, 0
        for char_info in CAMPAIGN_CHARACTERS:
            try:
                result = await _check_character(char_info, channel)
                if result == "changed":
                    changed += 1
                    success += 1
                elif result == "ok":
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"📊 Error checking {char_info['name']}: {e}")
                failed += 1
            await asyncio.sleep(REQUEST_GAP)
        logger.info(
            f"📊 Poll complete: {success} ok, {changed} changed, {failed} failed. "
            f"Next in {POLL_INTERVAL // 60}m"
        )
        await asyncio.sleep(POLL_INTERVAL)


async def _check_character(char_info: dict, channel) -> str:
    """Fetch, compare, and post changes for a single character.
    Returns: 'ok', 'changed', 'failed', or 'seeded'."""
    import discord

    char_id   = char_info["id"]
    char_name = char_info["name"]
    player    = char_info["player"]

    data = await _fetch_character(char_id)
    if data is None:
        logger.warning(f"📊 {char_name}: fetch failed — skipping")
        return "failed"

    new_snap = _parse_snapshot(data)
    old_snap = _load_snapshot(char_id)

    # First time seeing this character — save silently
    if old_snap is None:
        _save_snapshot(char_id, char_name, player, new_snap)
        logger.info(f"📊 {char_name}: initial snapshot saved")
        return "seeded"

    changes = _diff_snapshots(old_snap, new_snap, char_name)

    if not changes:
        logger.info(f"📊 {char_name}: no changes (level {new_snap.get('total_level', '?')}, HP {new_snap.get('max_hp', '?')})")
        return "ok"

    # Something changed — save new snapshot and post embed
    _save_snapshot(char_id, char_name, player, new_snap)
    logger.info(f"📊 {char_name}: {len(changes)} change(s) detected")

    # Update character_memory.txt so the Oracle has fresh data
    # Use the DDB name (new_snap["name"]) which matches character_memory.txt format
    ddb_name = new_snap.get("name", char_name)
    try:
        success = _update_character_memory(ddb_name, new_snap)
        if not success:
            logger.warning(f"⚠️ {ddb_name}: character_memory.txt update failed — Oracle data may be stale")
    except Exception as e:
        logger.error(f"❌ {ddb_name}: character_memory.txt update exception: {e}")

    if channel is None:
        return "changed"  # changes detected but no channel to post to

    # Build embed — Discord has a 4096 char description limit, chunk if needed
    level_str = " / ".join(
        f"{cls} {lvl}" for cls, lvl in new_snap.get("classes", {}).items()
    ) or f"Level {new_snap.get('total_level', '?')}"

    description = "\n".join(changes)

    # Split into multiple embeds if the description is too long
    chunks = []
    current_lines: list[str] = []
    current_len = 0
    for line in changes:
        if current_len + len(line) + 1 > 3900 and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += len(line) + 1
    if current_lines:
        chunks.append("\n".join(current_lines))

    for i, chunk in enumerate(chunks):
        title = f"📋 Character Update — {new_snap['name']}"
        if len(chunks) > 1:
            title += f" ({i + 1}/{len(chunks)})"
        embed = discord.Embed(
            title=title,
            description=chunk,
            color=discord.Color.gold(),
        )
        if i == len(chunks) - 1:
            embed.set_footer(
                text=f"{level_str} · {player} · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            embed.add_field(
                name="Sheet",
                value=f"[D&D Beyond](https://www.dndbeyond.com/characters/{char_id})",
                inline=True,
            )
        try:
            await channel.send(embed=embed)
        except Exception as send_err:
            logger.error(f"📊 Failed to send embed for {new_snap['name']}: {send_err}")

    return "changed"
