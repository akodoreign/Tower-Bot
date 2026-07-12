"""
src/treasure.py — Campaign treasure generation.

Generates loot packages appropriate to mission CR and tier.
All items pulled from DB (treasure_items table) or Mimir MCP.

Treasure tiers by weight:
  Always   : EC reward (CR-scaled)
  60%      : 1-2 store items (gadget / utility / food)
  25%      : Elemental Gem (+1d6 element to weapon)
  15%      : Common/Uncommon magic item (weapon, armor, wondrous)
  5%       : Mimir pull (real D&D 5.5e item, CR-appropriate, uncommon+)

Exported:
  roll_treasure(cr, tier)          -> TreasurePackage dict
  format_treasure_for_discord(pkg) -> str
  format_treasure_for_html(pkg)    -> str
"""

from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)

# EC reward table keyed by CR bracket
_EC_BY_CR: list[tuple[int, int, int]] = [
    # (min_cr, max_cr, base_ec)
    (0,  2,   50),
    (3,  4,  150),
    (5,  7,  300),
    (8, 10,  600),
    (11,14, 1000),
    (15,18, 2000),
    (19,24, 4000),
    (25,99, 8000),
]

_TIER_MULT: dict[str, float] = {
    "local": 0.5, "patrol": 0.75, "standard": 1.0,
    "dungeon": 1.25, "investigation": 1.0, "major": 1.5,
    "high-stakes": 2.0, "epic": 3.0, "divine": 4.0, "tower": 5.0,
}


def _base_ec(cr: int) -> int:
    for mn, mx, base in _EC_BY_CR:
        if mn <= cr <= mx:
            return base
    return 50


def _roll_ec(cr: int, tier: str) -> int:
    base = _base_ec(cr)
    mult = _TIER_MULT.get(tier.lower(), 1.0)
    variance = random.uniform(0.8, 1.2)
    return round(base * mult * variance / 10) * 10


def _get_store_items(count: int = 1) -> list[dict]:
    try:
        from src.db_api import get_treasure_items, raw_query
        rows = raw_query(
            "SELECT name, category, effect, charges, ec_value, kharma_value "
            "FROM treasure_items WHERE category IN ('gadget','utility','food') AND enabled=1 "
            "ORDER BY RAND() LIMIT %s",
            (count,)
        ) or []
        return list(rows)
    except Exception as e:
        logger.warning(f"treasure: store item fetch failed: {e}")
        return []


def _get_elemental_gem() -> Optional[dict]:
    try:
        from src.db_api import get_treasure_items
        rows = get_treasure_items(category="elemental_gem", limit=1)
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"treasure: gem fetch failed: {e}")
        return None


def _get_magic_item(rarity: str = "common") -> Optional[dict]:
    try:
        from src.db_api import get_treasure_items
        rows = get_treasure_items(category="magic_item", rarity=rarity, limit=1)
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"treasure: magic item fetch failed: {e}")
        return None


async def _mimir_pull(cr: int) -> Optional[dict]:
    try:
        from src.mimir_client import get_mimir
        mimir = get_mimir()
        if not mimir.available():
            return None
        rarity = "rare" if cr >= 11 else "uncommon"
        item_type = random.choice(["weapon", "armor", "wondrous item"])
        results = await mimir.search_items(query=rarity, item_type=item_type)
        if results:
            picked = random.choice(results[:10])
            return {
                "name": picked.get("name", "Unknown Item"),
                "item_type": item_type,
                "effect": picked.get("description", picked.get("notes", "")),
                "rarity": rarity,
                "source": "mimir",
            }
    except Exception as e:
        logger.debug(f"treasure: mimir pull failed: {e}")
    return None


def roll_treasure(cr: int = 5, tier: str = "standard") -> dict:
    """
    Roll a treasure package for a mission.

    Returns:
        {
          "ec": int,
          "items": [{"name": ..., "category": ..., "effect": ..., "charges": ...}, ...],
          "gems": [{"name": ..., "effect": ...}],
          "magic": {"name": ..., "item_type": ..., "effect": ..., "rarity": ...} | None,
          "mimir": {"name": ..., "effect": ..., "rarity": ..., "source": "mimir"} | None,
        }
    """
    ec = _roll_ec(cr, tier)
    items = []
    gems = []
    magic = None
    mimir_item = None

    roll = random.random()

    if roll < 0.60:
        count = random.choices([1, 2], weights=[70, 30])[0]
        items = _get_store_items(count)
    elif roll < 0.85:
        gem = _get_elemental_gem()
        if gem:
            gems.append(gem)
    elif roll < 0.97:
        rarity = random.choices(["common", "uncommon"], weights=[60, 40])[0]
        magic = _get_magic_item(rarity)
    # else: ec-only

    return {
        "ec": ec,
        "items": items,
        "gems": gems,
        "magic": magic,
        "mimir": mimir_item,
    }


async def roll_treasure_async(cr: int = 5, tier: str = "standard") -> dict:
    """
    Async version — includes potential Mimir pull (5% chance if CR >= 5).
    """
    pkg = roll_treasure(cr, tier)

    if cr >= 5 and random.random() < 0.05 and not pkg["magic"]:
        pkg["mimir"] = await _mimir_pull(cr)

    return pkg


def format_treasure_for_discord(pkg: dict) -> str:
    parts = [f"**{pkg['ec']:,} EC**"]
    for item in pkg.get("items", []):
        charges = f" *({item.get('charges', '')})*" if item.get("charges") and item["charges"] != "Permanent" else ""
        parts.append(f"{item['name']}{charges}")
    for gem in pkg.get("gems", []):
        parts.append(f"{gem['name']}")
    if pkg.get("magic"):
        m = pkg["magic"]
        parts.append(f"{m['name']} *({m.get('rarity','').title()} {m.get('item_type','')})*")
    if pkg.get("mimir"):
        m = pkg["mimir"]
        parts.append(f"{m['name']} *({m.get('rarity','').title()} — from Mimir)*")
    return " + ".join(parts)


def format_treasure_for_html(pkg: dict) -> str:
    rows = [f"<tr><td><strong>{pkg['ec']:,} EC</strong></td><td>Currency</td><td>Primary reward</td></tr>"]
    for item in pkg.get("items", []):
        charges = item.get("charges", "Permanent")
        effect = item.get("effect", "")
        rows.append(f"<tr><td>{item['name']}</td><td>{item.get('category','').title()}</td>"
                    f"<td>{effect} <em>({charges})</em></td></tr>")
    for gem in pkg.get("gems", []):
        rows.append(f"<tr><td>{gem['name']}</td><td>Elemental Gem</td>"
                    f"<td>{gem.get('effect','')}</td></tr>")
    if pkg.get("magic"):
        m = pkg["magic"]
        rows.append(f"<tr><td>{m['name']}</td>"
                    f"<td>{m.get('rarity','').title()} {m.get('item_type','')}</td>"
                    f"<td>{m.get('effect','')}</td></tr>")
    if pkg.get("mimir"):
        m = pkg["mimir"]
        rows.append(f"<tr><td>{m['name']} <em>(Mimir)</em></td>"
                    f"<td>{m.get('rarity','').title()}</td>"
                    f"<td>{m.get('effect','')}</td></tr>")
    return (
        "<table class='loot-table'>"
        "<thead><tr><th>Item</th><th>Type</th><th>Effect</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def loot_card(mission: dict, color: str = "#2a6a2a") -> str:
    """
    Generate a styled loot card HTML for injection into any pipeline's module body.

    CR is derived from mission_cr(mission) (party avg level + difficulty offset).
    Tier is read from mission['tier'].

    Args:
        mission: mission dict (needs 'tier', 'difficulty' or CR fields)
        color:   card accent color (defaults to green)

    Returns:
        HTML string — a self-contained card matching pipeline _card() style.
    """
    try:
        from src.mission_builder.cr_scaling import mission_cr
        cr = mission_cr(mission)
    except Exception:
        cr = 5

    tier = str(mission.get("tier") or "standard").lower()
    # Roll once per mission and cache on the dict: repeated loot_card calls stay
    # consistent, and mimir_module.enrich_mission_loot can attach the SAME items
    # to the Mimir module afterwards.
    pkg = mission.get("_loot_pkg")
    if not isinstance(pkg, dict) or "ec" not in pkg:
        pkg = roll_treasure(cr=cr, tier=tier)
        try:
            mission["_loot_pkg"] = pkg
        except Exception:
            pass

    rows = [
        f"<tr><td><strong>{pkg['ec']:,} EC</strong></td>"
        f"<td>Currency</td><td>Contract payment</td></tr>"
    ]
    for item in pkg.get("items", []):
        charges = item.get("charges") or "Permanent"
        ch_label = f" <em>({charges})</em>" if charges != "Permanent" else ""
        effect = item.get("effect") or ""
        rows.append(
            f"<tr><td>{item['name']}{ch_label}</td>"
            f"<td>{item.get('category','').title()}</td>"
            f"<td>{effect}</td></tr>"
        )
    for gem in pkg.get("gems", []):
        rows.append(
            f"<tr><td><strong>{gem['name']}</strong></td>"
            f"<td>Elemental Gem</td>"
            f"<td>{gem.get('effect','')}</td></tr>"
        )
    if pkg.get("magic"):
        m = pkg["magic"]
        rows.append(
            f"<tr><td><strong>{m['name']}</strong></td>"
            f"<td>{m.get('rarity','').title()} {m.get('item_type','')}</td>"
            f"<td>{m.get('effect','')}</td></tr>"
        )
    if pkg.get("mimir"):
        m = pkg["mimir"]
        rows.append(
            f"<tr><td><strong>{m['name']}</strong> <em>(Mimir)</em></td>"
            f"<td>{m.get('rarity','').title()}</td>"
            f"<td>{m.get('effect','')}</td></tr>"
        )

    table = (
        "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
        "<thead><tr style='background:#f5f5f5;'>"
        "<th style='text-align:left;padding:6px 8px;border-bottom:1px solid #ddd;'>Item</th>"
        "<th style='text-align:left;padding:6px 8px;border-bottom:1px solid #ddd;'>Type</th>"
        "<th style='text-align:left;padding:6px 8px;border-bottom:1px solid #ddd;'>Effect</th>"
        "</tr></thead><tbody>"
        + "".join(
            f"<tr style='border-bottom:1px solid #eee;'>"
            + r.replace("<tr>", "").replace("</tr>", "")
            + "</tr>"
            for r in rows
        )
        + "</tbody></table>"
    )

    return (
        f'<div style="border:1px solid {color};border-left:4px solid {color};'
        f'border-radius:6px;padding:14px 18px;margin:14px 0;background:#fff;">'
        f'<h2 style="margin:0 0 8px;color:{color};">Treasure</h2>'
        f'{table}</div>'
    )


__all__ = [
    "roll_treasure",
    "roll_treasure_async",
    "format_treasure_for_discord",
    "format_treasure_for_html",
    "loot_card",
]
