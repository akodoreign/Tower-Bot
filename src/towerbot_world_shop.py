"""DB-backed TowerBot world shop fed from the Mimir item catalog."""

from __future__ import annotations

import json
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from src.log import logger
from src.db_api import raw_query, raw_execute, db

TARGET_STOCK = {"uncommon": 20, "rare": 10}
SHOP_RARITIES = tuple(TARGET_STOCK.keys())

# Item names containing any of these substrings (case-insensitive) are banned from the shop.
_BANNED_ITEM_SUBSTRINGS = ["adamantine", "adamantite"]

def _is_banned_item(name: str) -> bool:
    low = name.lower()
    return any(s in low for s in _BANNED_ITEM_SUBSTRINGS)
RESTOCK_HOURS = 6

# EC equivalents used by the Tower economy. buy_now is 1.5x this value.
REAL_COST_EC = {
    "uncommon": (2_000, 16_000),
    "rare": (16_000, 80_000),
}

IMAGE_KEYS = (
    "image_url",
    "imageUrl",
    "image",
    "img",
    "avatar_url",
    "thumbnail",
    "thumbnail_url",
    "large_avatar",
)

MIMIR_ITEM_IMAGE_BASE_URL = os.getenv(
    "MIMIR_ITEM_IMAGE_BASE_URL",
    "https://5etools.jinocenc.io/img/",
)
_TAG_RE = re.compile(r"\{@(?:[a-zA-Z]+)\s+([^}|]+)(?:\|[^}]*)?\}")

_WORLD_SHOP_TABLES_READY = False


def ensure_world_shop_tables() -> None:
    global _WORLD_SHOP_TABLES_READY
    if _WORLD_SHOP_TABLES_READY:
        return
    raw_execute(
        """
        CREATE TABLE IF NOT EXISTS towerbot_world_items (
            id INT AUTO_INCREMENT PRIMARY KEY,
            item_name VARCHAR(255) NOT NULL,
            rarity VARCHAR(40) NOT NULL,
            item_type VARCHAR(120),
            source VARCHAR(80),
            mimir_item_id VARCHAR(128),
            image_url VARCHAR(800),
            description TEXT,
            real_cost_ec INT NOT NULL,
            buy_now_ec INT NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'active',
            item_json JSON,
            listed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            removed_at DATETIME NULL,
            purchased_at DATETIME NULL,
            INDEX idx_towerbot_world_status (status, rarity, listed_at),
            INDEX idx_towerbot_world_name (item_name)
        )
        """
    )
    raw_execute(
        """
        CREATE TABLE IF NOT EXISTS towerbot_purchase_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            item_id INT NOT NULL,
            character_id INT NULL,
            character_name VARCHAR(255),
            player_name VARCHAR(255),
            buyer_note TEXT,
            status VARCHAR(40) NOT NULL DEFAULT 'queued',
            dm_message_id VARCHAR(80),
            requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            decided_at DATETIME NULL,
            decided_by VARCHAR(120),
            error TEXT,
            request_json JSON,
            INDEX idx_towerbot_purchase_status (status, requested_at),
            INDEX idx_towerbot_purchase_item (item_id)
        )
        """
    )
    try:
        col_exists = raw_query(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'towerbot_purchase_requests' "
            "AND COLUMN_NAME = 'player_name'"
        )
        if not col_exists:
            raw_execute("ALTER TABLE towerbot_purchase_requests ADD COLUMN player_name VARCHAR(255)")
    except Exception:
        pass
    _WORLD_SHOP_TABLES_READY = True


def _json_col(value: Any, default: Any = None) -> Any:
    if default is None:
        default = {}
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def _clean_rarity(value: object) -> str:
    rarity = str(value or "").lower().replace("_", " ").strip()
    return "rare" if rarity == "rare" else "uncommon"


def _mimir_db_path() -> str:
    configured = os.getenv("MIMIR_DATABASE_PATH", "").strip()
    if configured:
        return configured
    return str(Path.home() / "AppData" / "Roaming" / "com.mimir.app" / "data" / "mimir.db")


def _internal_asset_url(path: str) -> str:
    path = str(path or "").replace("\\", "/").lstrip("/")
    if not path:
        return ""
    return MIMIR_ITEM_IMAGE_BASE_URL.rstrip("/") + "/" + quote(path, safe="/")


def _clean_entry_text(value: object) -> str:
    text = str(value or "")
    text = _TAG_RE.sub(lambda m: m.group(1), text)
    return (
        text.replace("{@h}", "")
        .replace("{@hit}", "hit")
        .replace("{@miss}", "miss")
        .replace("{@atk mw}", "Melee Weapon Attack:")
        .replace("{@atk rw}", "Ranged Weapon Attack:")
        .strip()
    )


def _flatten_entries(value: object, limit: int = 900) -> str:
    parts: list[str] = []

    def walk(node: object) -> None:
        if len(" ".join(parts)) >= limit:
            return
        if isinstance(node, str):
            cleaned = _clean_entry_text(node)
            if cleaned:
                parts.append(cleaned)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            if node.get("type") in {"table", "image"}:
                return
            name = node.get("name")
            entry = node.get("entry")
            entries = node.get("entries")
            items = node.get("items")
            if name and entry:
                parts.append(f"{_clean_entry_text(name)} {_clean_entry_text(entry)}")
            elif entry:
                walk(entry)
            elif entries:
                walk(entries)
            elif items:
                walk(items)

    walk(value)
    return " ".join(parts)[:limit].strip()


def _item_image_url(item: dict) -> str:
    for key in IMAGE_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
        if isinstance(value, dict):
            for nested in IMAGE_KEYS:
                nested_value = value.get(nested)
                if isinstance(nested_value, str) and nested_value.startswith(("http://", "https://")):
                    return nested_value
    images = item.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.startswith(("http://", "https://")):
                return image
            if isinstance(image, dict):
                href = image.get("href")
                if isinstance(href, dict):
                    href_path = href.get("url") or href.get("path")
                    if isinstance(href_path, str):
                        if href_path.startswith(("http://", "https://")):
                            return href_path
                        if href.get("type") == "internal" or "/" in href_path:
                            return _internal_asset_url(href_path)
                url = _item_image_url(image)
                if url:
                    return url
    fluff = item.get("fluff")
    if isinstance(fluff, dict):
        url = _item_image_url(fluff)
        if url:
            return url
    return ""


def _item_description(item: dict) -> str:
    for key in ("description", "text", "content", "entries", "desc"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            text = _flatten_entries(value)
            if text:
                return text
    return "Authenticated Mimir catalog item. Details available in the compendium."


def _enrich_mimir_item_from_db(item: dict) -> dict:
    """Search_catalog is intentionally small; load full item data/fluff from Mimir's DB."""
    name = str(item.get("name") or "").strip()
    source = str(item.get("source") or "").strip()
    if not name:
        return item
    db_path = _mimir_db_path()
    if not db_path or not Path(db_path).exists():
        return item
    con = None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        if source:
            rows = cur.execute(
                "SELECT * FROM items WHERE name=? AND source=? LIMIT 1",
                (name, source),
            ).fetchall()
        else:
            rows = []
        if not rows:
            rows = cur.execute(
                "SELECT * FROM items WHERE name=? ORDER BY source LIMIT 1",
                (name,),
            ).fetchall()
        if not rows:
            return item
        row = rows[0]
        data = _json_col(row["data"], {})
        fluff = _json_col(row["fluff"], {}) if row["fluff"] else {}
        enriched = dict(data)
        enriched.update({
            "id": row["id"],
            "name": row["name"],
            "source": row["source"],
            "item_type": row["item_type"],
            "rarity": row["rarity"],
        })
        if fluff:
            enriched["fluff"] = fluff
            if isinstance(fluff.get("images"), list):
                enriched["images"] = fluff["images"]
        return enriched
    except Exception as exc:
        logger.debug("TowerBot shop Mimir DB enrichment skipped for %s: %s", name, exc)
        return item
    finally:
        try:
            if con:
                con.close()
        except Exception:
            pass


def _shop_row(row: dict) -> dict:
    item_json = _json_col(row.get("item_json"), {})
    image_url = row.get("image_url") or ""
    if not image_url:
        try:
            from src.towerbot_item_art import generic_item_key, image_url_for_item_art_key
            key = generic_item_key(row.get("item_name") or "", row.get("item_type") or "")
            image_url = image_url_for_item_art_key(key)
        except Exception:
            image_url = ""
    return {
        "id": row.get("id"),
        "item_name": row.get("item_name"),
        "name": row.get("item_name"),
        "rarity": row.get("rarity"),
        "item_type": row.get("item_type") or item_json.get("item_type") or item_json.get("type") or "",
        "source": row.get("source") or item_json.get("source") or "Mimir",
        "mimir_item_id": row.get("mimir_item_id") or item_json.get("id") or "",
        "image_url": image_url,
        "description": row.get("description") or _item_description(item_json),
        "real_cost_ec": int(row.get("real_cost_ec") or 0),
        "buy_now_ec": int(row.get("buy_now_ec") or 0),
        "listed_at": str(row.get("listed_at") or ""),
        "status": row.get("status"),
    }


def list_active_world_items() -> list[dict]:
    ensure_world_shop_tables()
    rows = raw_query(
        """
        SELECT * FROM towerbot_world_items
        WHERE status='active'
        ORDER BY FIELD(rarity, 'uncommon', 'rare'), listed_at DESC, id DESC
        """
    ) or []
    return [_shop_row(r) for r in rows if not _is_banned_item(r.get("item_name") or "")]


def list_player_characters_for_shop() -> list[dict]:
    rows = raw_query(
        "SELECT id, name, player_name, class_name FROM player_characters ORDER BY name"
    ) or []
    return [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "player_name": r.get("player_name") or "",
            "class_name": r.get("class_name") or "",
        }
        for r in rows
    ]


def _existing_names() -> set[str]:
    rows = raw_query(
        "SELECT item_name FROM towerbot_world_items WHERE status IN ('active','pending_dm','sold')"
    ) or []
    return {str(r.get("item_name") or "").lower() for r in rows if r.get("item_name")}


def _active_counts() -> dict[str, int]:
    rows = raw_query(
        """
        SELECT rarity, COUNT(*) AS n
        FROM towerbot_world_items
        WHERE status='active'
        GROUP BY rarity
        """
    ) or []
    counts = {k: 0 for k in TARGET_STOCK}
    for row in rows:
        rarity = _clean_rarity(row.get("rarity"))
        counts[rarity] = int(row.get("n") or 0)
    return counts


def _clone_existing_stock_to_target() -> int:
    """Keep the shelf full when Mimir has fewer unique rows or is temporarily locked."""
    added = 0
    counts = _active_counts()
    for rarity, target in TARGET_STOCK.items():
        if counts.get(rarity, 0) >= target:
            continue
        pool = raw_query(
            """
            SELECT item_name, rarity, item_type, source, mimir_item_id, image_url,
                   description, real_cost_ec, buy_now_ec, item_json
            FROM towerbot_world_items
            WHERE status='active' AND rarity=%s
            """,
            (rarity,),
        ) or []
        if not pool:
            continue
        while counts.get(rarity, 0) < target:
            src = dict(random.choice(pool))
            src["status"] = "active"
            db.insert("towerbot_world_items", src)
            counts[rarity] = counts.get(rarity, 0) + 1
            added += 1
    return added


def _mimir_item_to_shop_row(item: dict, rarity: str) -> dict:
    item = _enrich_mimir_item_from_db(item)
    name = str(item.get("name") or "").strip()
    real_lo, real_hi = REAL_COST_EC[rarity]
    catalog_value = int(item.get("cost_ec") or item.get("value") or 0)
    real_cost = catalog_value if real_lo <= catalog_value <= real_hi else random.randint(real_lo, real_hi)
    buy_now = int(round(real_cost * 1.5))
    description = _item_description(item)
    item_type = str(item.get("item_type") or item.get("type") or "").strip()
    source = str(item.get("source") or "Mimir").strip() or "Mimir"
    return {
        "item_name": name,
        "rarity": rarity,
        "item_type": item_type,
        "source": source,
        "mimir_item_id": str(item.get("id") or item.get("uuid") or ""),
        "image_url": _item_image_url(item),
        "description": description,
        "real_cost_ec": real_cost,
        "buy_now_ec": buy_now,
        "status": "active",
        "item_json": json.dumps(item, ensure_ascii=False, default=str),
    }


async def _fetch_mimir_shop_item(
    mimir,
    rarity: str,
    seen_names: set[str],
    allow_duplicate: bool = False,
) -> Optional[dict]:
    try:
        raw = await mimir._call("search_catalog", category="item", rarity=rarity, limit=250)
        if isinstance(raw, dict):
            items = raw.get("items") or raw.get("results") or raw.get("item") or []
        elif isinstance(raw, list):
            items = raw
        else:
            items = []
    except Exception as exc:
        logger.debug("TowerBot shop Mimir fetch failed for %s: %s", rarity, exc)
        return None
    random.shuffle(items)
    fallback = None
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name or _is_banned_item(name):
            continue
        if not allow_duplicate and name.lower() in seen_names:
            continue
        row = _mimir_item_to_shop_row(item, rarity)
        if row.get("image_url"):
            return row
        if fallback is None:
            fallback = row
    return fallback


async def restock_world_shop(force: bool = False) -> int:
    """Rotate old stock occasionally and refill to 20 uncommon / 10 rare."""
    ensure_world_shop_tables()

    try:
        from src.db_api import get_global_state, set_global_state
        last = get_global_state("towerbot_world_shop_last_rotation")
        if not force and last:
            try:
                if (datetime.now() - datetime.fromisoformat(str(last))).total_seconds() < RESTOCK_HOURS * 3600:
                    counts = _active_counts()
                    if all(counts[r] >= TARGET_STOCK[r] for r in TARGET_STOCK):
                        return 0
            except Exception:
                pass
    except Exception:
        last = None

    try:
        from src.mimir_client import get_mimir
        mimir = get_mimir()
        if not mimir.available:
            await mimir.ensure_connected()
        if not mimir.available:
            return _clone_existing_stock_to_target()
    except Exception:
        return _clone_existing_stock_to_target()

    if not force:
        active = raw_query("SELECT id FROM towerbot_world_items WHERE status='active' ORDER BY RAND() LIMIT 4") or []
        if active and random.random() < 0.45:
            retire_count = random.randint(1, min(4, len(active)))
            for row in active[:retire_count]:
                raw_execute(
                    "UPDATE towerbot_world_items SET status='retired', removed_at=NOW() WHERE id=%s",
                    (row["id"],),
                )

    seen_names = _existing_names()
    added = 0
    counts = _active_counts()
    for rarity, target in TARGET_STOCK.items():
        attempts = 0
        while counts.get(rarity, 0) < target and attempts < target * 4:
            attempts += 1
            item = await _fetch_mimir_shop_item(mimir, rarity, seen_names)
            if not item and counts.get(rarity, 0) < target:
                item = await _fetch_mimir_shop_item(mimir, rarity, seen_names, allow_duplicate=True)
            if not item:
                break
            db.insert("towerbot_world_items", item)
            seen_names.add(item["item_name"].lower())
            counts[rarity] = counts.get(rarity, 0) + 1
            added += 1

    try:
        from src.db_api import set_global_state
        set_global_state("towerbot_world_shop_last_rotation", datetime.now().isoformat())
    except Exception:
        pass
    added += _clone_existing_stock_to_target()
    if added:
        logger.info("TowerBot world shop restocked: %s item(s)", added)
    return added


def queue_world_item_purchase(item_id: int, character_id: int, buyer_note: str = "", *, player_name: str = "") -> dict:
    ensure_world_shop_tables()
    item_rows = raw_query(
        "SELECT * FROM towerbot_world_items WHERE id=%s AND status='active' LIMIT 1",
        (int(item_id),),
    ) or []
    if not item_rows:
        return {"ok": False, "error": "Item is no longer available."}
    char_rows = raw_query(
        "SELECT id, name FROM player_characters WHERE id=%s LIMIT 1",
        (int(character_id),),
    ) or []
    if not char_rows:
        return {"ok": False, "error": "Choose a character before buying."}

    affected = raw_execute(
        "UPDATE towerbot_world_items SET status='pending_dm', purchased_at=NOW() WHERE id=%s AND status='active'",
        (int(item_id),),
    )
    if not affected:
        return {"ok": False, "error": "Item was already claimed."}

    item = item_rows[0]
    char = char_rows[0]
    req_json = {
        "item": _shop_row(item),
        "character": {"id": char["id"], "name": char["name"]},
        "player_name": player_name,
        "buyer_note": buyer_note,
    }
    request_id = db.insert(
        "towerbot_purchase_requests",
        {
            "item_id": int(item_id),
            "character_id": int(character_id),
            "character_name": char["name"],
            "player_name": player_name or None,
            "buyer_note": buyer_note,
            "status": "queued",
            "request_json": json.dumps(req_json, ensure_ascii=False, default=str),
        },
    )
    return {
        "ok": True,
        "request_id": request_id,
        "message": f"Purchase request queued for DM approval: {item.get('item_name')} -> {char.get('name')}.",
    }


def _append_item_to_character_profile(character_id: int, item_name: str, request_id: int) -> None:
    rows = raw_query("SELECT profile_json FROM player_characters WHERE id=%s LIMIT 1", (character_id,)) or []
    if not rows:
        return
    profile = _json_col(rows[0].get("profile_json"), {})
    purchases = profile.get("TOWERBOT_PURCHASES")
    if not isinstance(purchases, list):
        purchases = []
    purchases.append({"item": item_name, "request_id": request_id, "at": datetime.now().isoformat()})
    profile["TOWERBOT_PURCHASES"] = purchases[-50:]
    notable = str(profile.get("NOTABLE_GEAR") or profile.get("NOTABLE GEAR") or "").strip()
    if item_name.lower() not in notable.lower():
        profile["NOTABLE_GEAR"] = (notable + (", " if notable else "") + item_name).strip()
    raw_execute(
        "UPDATE player_characters SET profile_json=%s, updated_at=NOW() WHERE id=%s",
        (json.dumps(profile, ensure_ascii=False), character_id),
    )
    raw_execute(
        "UPDATE mimir_sync SET sync_hash=NULL WHERE entity_type IN ('pc','pc_gear') AND entity_id=%s",
        (str(character_id),),
    )


async def _mimir_character_id_for_pc(character_id: int, character_name: str) -> str:
    rows = raw_query(
        "SELECT mimir_id FROM mimir_sync WHERE entity_type='pc' AND entity_id=%s LIMIT 1",
        (str(character_id),),
    ) or []
    if rows and rows[0].get("mimir_id"):
        return str(rows[0]["mimir_id"])

    from src.mimir_client import get_mimir
    mimir = get_mimir()
    chars = await mimir.list_characters(character_type="pc")
    wanted = character_name.lower()
    for char in chars:
        if str(char.get("name") or "").lower() == wanted and char.get("id"):
            return str(char["id"])
    for char in chars:
        if wanted in str(char.get("name") or "").lower() and char.get("id"):
            return str(char["id"])
    return ""


async def approve_purchase_request(request_id: int, decided_by: str = "DM") -> dict:
    ensure_world_shop_tables()
    rows = raw_query(
        """
        SELECT pr.*, wi.item_name, wi.buy_now_ec, wi.rarity
        FROM towerbot_purchase_requests pr
        JOIN towerbot_world_items wi ON wi.id=pr.item_id
        WHERE pr.id=%s LIMIT 1
        """,
        (int(request_id),),
    ) or []
    if not rows:
        return {"ok": False, "error": "Request not found."}
    req = rows[0]
    if req.get("status") not in ("queued", "dm_sent", "apply_failed"):
        return {"ok": False, "error": f"Request is already {req.get('status')}."}

    from src.mimir_client import get_mimir
    mimir = get_mimir()
    if not mimir.available:
        await mimir.ensure_connected()
    if not mimir.available:
        raw_execute(
            "UPDATE towerbot_purchase_requests SET status='apply_failed', error=%s WHERE id=%s",
            ("Mimir unavailable", int(request_id)),
        )
        return {"ok": False, "error": "Mimir is unavailable; item was not applied."}

    mimir_character_id = await _mimir_character_id_for_pc(
        int(req["character_id"]), str(req.get("character_name") or "")
    )
    if not mimir_character_id:
        raw_execute(
            "UPDATE towerbot_purchase_requests SET status='apply_failed', error=%s WHERE id=%s",
            ("Mimir character not found", int(request_id)),
        )
        return {"ok": False, "error": "Could not find the character in Mimir."}

    ok = await mimir.add_item_to_character(
        mimir_character_id,
        item_name=str(req["item_name"]),
        quantity=1,
        equipped=False,
    )
    if not ok:
        raw_execute(
            "UPDATE towerbot_purchase_requests SET status='apply_failed', error=%s WHERE id=%s",
            ("Mimir add_item_to_character failed", int(request_id)),
        )
        return {"ok": False, "error": "Mimir did not accept the item add."}

    _append_item_to_character_profile(int(req["character_id"]), str(req["item_name"]), int(request_id))
    raw_execute(
        "UPDATE towerbot_world_items SET status='sold', removed_at=NOW() WHERE id=%s",
        (int(req["item_id"]),),
    )
    raw_execute(
        "UPDATE towerbot_purchase_requests SET status='approved', decided_at=NOW(), decided_by=%s, error=NULL WHERE id=%s",
        (decided_by, int(request_id)),
    )
    return {"ok": True, "message": f"{req['item_name']} applied to {req.get('character_name')}."}


def reject_purchase_request(request_id: int, decided_by: str = "DM") -> dict:
    ensure_world_shop_tables()
    rows = raw_query("SELECT * FROM towerbot_purchase_requests WHERE id=%s LIMIT 1", (int(request_id),)) or []
    if not rows:
        return {"ok": False, "error": "Request not found."}
    req = rows[0]
    if req.get("status") not in ("queued", "dm_sent", "apply_failed"):
        return {"ok": False, "error": f"Request is already {req.get('status')}."}
    raw_execute(
        "UPDATE towerbot_world_items SET status='rejected', removed_at=NOW() WHERE id=%s",
        (int(req["item_id"]),),
    )
    raw_execute(
        "UPDATE towerbot_purchase_requests SET status='rejected', decided_at=NOW(), decided_by=%s WHERE id=%s",
        (decided_by, int(request_id)),
    )
    return {"ok": True, "message": "Purchase rejected and item removed from the web stock."}


async def process_purchase_dm_queue(discord_client) -> int:
    ensure_world_shop_tables()
    dm_id = int(os.getenv("DM_USER_ID", "0") or 0)
    if not dm_id:
        return 0
    rows = raw_query(
        """
        SELECT pr.*, wi.item_name, wi.rarity, wi.item_type, wi.source, wi.mimir_item_id,
               wi.description, wi.real_cost_ec, wi.buy_now_ec, wi.item_json
        FROM towerbot_purchase_requests pr
        JOIN towerbot_world_items wi ON wi.id=pr.item_id
        WHERE pr.status='queued'
        ORDER BY pr.requested_at ASC
        LIMIT 5
        """
    ) or []
    if not rows:
        return 0

    import discord

    class PurchaseApprovalView(discord.ui.View):
        def __init__(self, req_id: int):
            super().__init__(timeout=None)
            self.req_id = req_id

        @discord.ui.button(label="Approve and Apply", style=discord.ButtonStyle.success)
        async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.defer(ephemeral=True)
            result = await approve_purchase_request(self.req_id, str(interaction.user))
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
            await interaction.followup.send(result.get("message") or result.get("error", "Done."), ephemeral=True)

        @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
        async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
            result = reject_purchase_request(self.req_id, str(interaction.user))
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(result.get("message") or result.get("error", "Done."), ephemeral=True)

    sent = 0
    dm_user = await discord_client.fetch_user(dm_id)
    for req in rows:
        item_json = _json_col(req.get("item_json"), {})
        details = [
            f"Request ID: {req['id']}",
            f"Player: {req.get('player_name') or 'Unknown'}",
            f"Character: {req.get('character_name') or 'Unknown'}",
            f"Item: {req.get('item_name')}",
            f"Rarity: {req.get('rarity')}",
            f"Type: {req.get('item_type') or item_json.get('item_type') or item_json.get('type') or 'Unknown'}",
            f"Source: {req.get('source') or item_json.get('source') or 'Mimir'}",
            f"Mimir item id: {req.get('mimir_item_id') or item_json.get('id') or 'n/a'}",
            f"Real cost estimate: {int(req.get('real_cost_ec') or 0):,} EC",
            f"Buy Now charge: {int(req.get('buy_now_ec') or 0):,} EC",
        ]
        note = str(req.get("buyer_note") or "").strip()
        if note:
            details.append(f"Buyer note: {note}")
        desc = str(req.get("description") or "").strip()
        if desc:
            details.append("")
            details.append("Description:")
            details.append(desc[:1200])
        embed = discord.Embed(
            title="TowerBot Web Purchase Request",
            description="\n".join(details)[:3900],
            color=discord.Color.gold(),
        )
        embed.set_footer(text="No item image included by request. Approve applies the item in Mimir.")
        msg = await dm_user.send(embed=embed, view=PurchaseApprovalView(int(req["id"])))
        raw_execute(
            "UPDATE towerbot_purchase_requests SET status='dm_sent', dm_message_id=%s WHERE id=%s",
            (str(msg.id), int(req["id"])),
        )
        sent += 1
    return sent
