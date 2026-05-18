"""
mimir_module.py — Mimir DM integration for mission pipelines.

Called after LLM content generation to:
  1. Mirror the mission as a Mimir module (campaign-tracked, VTT-ready)
  2. Populate it with real D&D 5e catalog data (monsters, items)
  3. Push read-aloud text and DM notes as structured documents
  4. Upload A1111 map PNGs via create_map
  5. Return enriched data for HTML rendering (real stat blocks, item cards)

All functions are no-ops when Mimir is unavailable.
"""

from __future__ import annotations

import os
import re
import html as html_lib
from pathlib import Path
from typing import Optional

import httpx

from src.log import logger
from src.mimir_client import get_mimir

_OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434/api/chat")
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")


# ---------------------------------------------------------------------------
# Mission type → Mimir module template mapping
# ---------------------------------------------------------------------------

_MIMIR_MODULE_TYPE: dict[str, str] = {
    # Combat / action
    "battle":             "Standard Adventure",
    "assault":            "Standard Adventure",
    "defense":            "Standard Adventure",
    "ambush":             "Standard Adventure",
    "escort":             "Standard Adventure",
    "gather":             "Standard Adventure",
    "recovery":           "Standard Adventure",
    "rescue":             "Standard Adventure",
    "first_contact":      "Standard Adventure",
    "strange_occurrence": "Standard Adventure",
    "discovery":          "Standard Adventure",
    # Dungeon / exploration
    "infestation":        "Dungeon Crawl",
    "exploration":        "Dungeon Crawl",
    # Heist / infiltration / sabotage
    "heist":              "Heist",
    "infiltration":       "Heist",
    "sabotage":           "Heist",
    # Mystery / investigation / puzzle
    "investigation":      "Mystery",
    "puzzle":             "Mystery",
    # Social / political
    "negotiation":        "Political Intrigue",
    "political":          "Political Intrigue",
    # Dark / horror
    "assassination":      "Horror",
}


def _mimir_type(mission_type: str) -> str:
    """Return the Mimir module template type for a given pipeline mission type."""
    return _MIMIR_MODULE_TYPE.get(mission_type.lower(), "Standard Adventure")


# ---------------------------------------------------------------------------
# CR parsing helper
# ---------------------------------------------------------------------------

_CR_MAP = {"1/8": 0.125, "1/4": 0.25, "1/2": 0.5}


def _parse_cr(cr_str: str) -> Optional[float]:
    if not cr_str:
        return None
    if cr_str in _CR_MAP:
        return _CR_MAP[cr_str]
    try:
        return float(cr_str)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 5.5e stat block generation for catalog-miss homebrew enemies
# ---------------------------------------------------------------------------

_CR_XP = {
    0: 10, 0.125: 25, 0.25: 50, 0.5: 100,
    1: 200, 2: 450, 3: 700, 4: 1100, 5: 1800,
    6: 2300, 7: 2900, 8: 3900, 9: 5000, 10: 5900,
    11: 7200, 12: 8400, 13: 10000, 14: 11500, 15: 13000,
    16: 15000, 17: 18000, 18: 20000, 19: 22000, 20: 25000,
}
_SIZE_CODE = {"tiny": "T", "small": "S", "medium": "M", "large": "L", "huge": "H", "gargantuan": "G"}


def _parse_5e_statblock(text: str) -> dict:
    """Parse a 5.5e stat block string into a push_monster()-compatible dict."""
    result: dict = {}

    m = re.search(r'\*\*Armor Class\*\*\s+(\d+)', text)
    if m:
        result["ac"] = int(m.group(1))

    m = re.search(r'\*\*Hit Points\*\*\s+(\d+)\s+\((\d+)d(\d+)', text)
    if m:
        result["hp"]           = int(m.group(1))
        result["hp_die_count"] = int(m.group(2))
        result["hp_die"]       = m.group(3)

    # Ability score table row: | 16 (+3) | 14 (+2) | ...
    m = re.search(
        r'\|\s*(\d+)[^|]+\|\s*(\d+)[^|]+\|\s*(\d+)[^|]+\|\s*(\d+)[^|]+\|\s*(\d+)[^|]+\|\s*(\d+)',
        text,
    )
    if m:
        result["str_"] = int(m.group(1))
        result["dex"]  = int(m.group(2))
        result["con"]  = int(m.group(3))
        result["int_"] = int(m.group(4))
        result["wis"]  = int(m.group(5))
        result["cha"]  = int(m.group(6))

    m = re.search(r'Passive Perception\s+(\d+)', text, re.IGNORECASE)
    if m:
        result["passive_perc"] = int(m.group(1))

    m = re.search(r'\*\*Languages\*\*\s+(.+)', text)
    if m:
        result["languages"] = m.group(1).strip()

    # Actions (main + bonus + reactions combined into the actions textarea)
    actions_parts = []
    m = re.search(r'##\s*Actions?\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL | re.IGNORECASE)
    if m:
        actions_parts.append(m.group(1).strip())
    m = re.search(r'##\s*Bonus Actions?\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL | re.IGNORECASE)
    if m:
        actions_parts.append("## Bonus Actions\n" + m.group(1).strip())
    m = re.search(r'##\s*Reactions?\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL | re.IGNORECASE)
    if m:
        actions_parts.append("## Reactions\n" + m.group(1).strip())
    if actions_parts:
        result["actions"] = "\n\n".join(actions_parts)

    # Traits → notes field
    m = re.search(r'##\s*Traits?\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL | re.IGNORECASE)
    if m:
        result["notes"] = m.group(1).strip()

    # Size
    m = re.search(r'\*(tiny|small|medium|large|huge|gargantuan)', text, re.IGNORECASE)
    if m:
        result["size"] = _SIZE_CODE.get(m.group(1).lower(), "M")

    # Creature type
    m = re.search(
        r'\*\w+\s+(humanoid|beast|undead|fiend|construct|elemental|fey|dragon|monstrosity|aberration|celestial|giant|ooze|plant)',
        text, re.IGNORECASE,
    )
    if m:
        result["creature_type"] = m.group(1).lower()

    return result


async def _generate_statblock_llm(name: str, cr: str, creature_type: str, notes: str) -> dict:
    """Ask Ollama for a full D&D 2024 (5.5e) stat block; return parsed field dict."""
    try:
        cr_num = float(cr.replace("1/8", "0.125").replace("1/4", "0.25").replace("1/2", "0.5"))
    except Exception:
        cr_num = 1.0
    prof = 2 + max(0, int((cr_num - 1) // 4))
    xp   = _CR_XP.get(cr_num, int(cr_num * 1000))
    ac   = max(10, min(18, int(cr_num + 12)))
    hp   = max(5, int(cr_num * 13 + 7))
    atk  = 4 + int(cr_num // 2)
    dc   = 8 + 4 + int(cr_num // 2)

    prompt = (
        f"Generate a D&D 2024 (5.5e) stat block for a CR {cr} {creature_type} named {name!r}.\n"
        f"Context: {notes or 'Campaign creature for an urban dark fantasy setting.'}\n\n"
        f"Use EXACTLY this format — do not deviate:\n\n"
        f"**{name.upper()}**\n"
        f"*Medium {creature_type}, [alignment]*\n\n"
        f"**Armor Class** {ac} ([armor type])\n"
        f"**Hit Points** {hp} ([Xd8 + Y])\n"
        f"**Speed** 30 ft.\n"
        f"**Initiative** +[mod]\n\n"
        f"| STR | DEX | CON | INT | WIS | CHA |\n"
        f"|-----|-----|-----|-----|-----|-----|\n"
        f"| [val] ([mod]) | [val] ([mod]) | [val] ([mod]) | [val] ([mod]) | [val] ([mod]) | [val] ([mod]) |\n\n"
        f"**Saving Throws** [only proficient saves, e.g. CON +{prof+2}]\n"
        f"**Skills** [only notable skills]\n"
        f"**Senses** [senses], Passive Perception [val]\n"
        f"**Languages** Common[, others]\n"
        f"**Challenge** {cr} ({xp:,} XP)  **Proficiency Bonus** +{prof}\n\n"
        f"## Traits\n\n"
        f"[1-2 relevant traits, or write 'None.' if the creature has no special traits]\n\n"
        f"## Actions\n\n"
        f"**Multiattack.** [description]\n\n"
        f"**[Primary Attack].** *Melee Attack Roll:* +{atk}, Reach 5 ft., one target. "
        f"*Hit:* [avg] ([dice]) [Damage Type] damage.\n\n"
        f"## Bonus Actions\n\n"
        f"[If applicable, else write 'None.']\n\n"
        f"## Reactions\n\n"
        f"[If applicable, else write 'None.']\n\n"
        f"Output ONLY the stat block. No explanation, no commentary."
    )

    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("mimir_statblock", track="primary")
        if not decision.run_now:
            logger.warning(f"[MIMIR] LLM statblock deferred for {name!r}: {decision.reason}")
            return {}

        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(_OLLAMA_URL, json={
                "model":    _OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream":   False,
            })
            text = r.json().get("message", {}).get("content", "")
    except Exception as exc:
        logger.warning(f"[MIMIR] LLM statblock failed for {name!r}: {exc}")
        return {}

    if not text:
        return {}

    parsed = _parse_5e_statblock(text)
    logger.debug(f"[MIMIR] Parsed statblock for {name!r}: {list(parsed.keys())}")
    return parsed


# ---------------------------------------------------------------------------
# Module creation
# ---------------------------------------------------------------------------

async def create_module(mission: dict, mission_type: str = "") -> Optional[str]:
    """
    Create a Mimir module that mirrors this mission.
    Returns the Mimir module_id, or None if unavailable.
    """
    mimir = get_mimir()
    if not mimir.available:
        await mimir.ensure_connected()
    if not mimir.available:
        return None

    title = mission.get("title", "Untitled Mission")
    tier  = mission.get("tier", 1)
    fac   = mission.get("faction") or mission.get("client_faction", "")
    mtype = mission_type or mission.get("mission_type", "")

    desc_parts = [f"Tier {tier}"]
    if mtype:
        desc_parts.append(mtype.replace("_", " ").title())
    if fac:
        desc_parts.append(f"— {fac}")
    desc_parts.append("| Tower of Last Chance")

    mimir_type = _mimir_type(mtype)
    mod = await mimir.create_module(
        name=title,
        description=" ".join(desc_parts),
        module_type=mimir_type,
    )
    if not mod:
        return None

    module_id = mod.get("id") or mod.get("module_id")
    logger.debug(f"[MIMIR] Module created: {module_id} — {title}")
    return module_id


# ---------------------------------------------------------------------------
# Monster enrichment
# ---------------------------------------------------------------------------

async def enrich_monsters(
    module_id: str,
    enemies: list[dict],
) -> list[dict]:
    """
    For each enemy entry, search Mimir catalog for the closest real 5e monster.
    Adds to Mimir module. Returns list with 'catalog_data' field added.

    Enemy dict format (flexible):
        name       : str   — monster name or description
        cr         : str   — challenge rating ("3", "1/2", etc.)
        count      : int   — number appearing
        notes      : str   — optional context
    """
    mimir = get_mimir()
    if not mimir.available:
        await mimir.ensure_connected()
    if not mimir.available or not module_id:
        return enemies

    enriched = []
    for enemy in enemies:
        name  = enemy.get("name", "")
        cr    = enemy.get("cr", "")
        count = int(enemy.get("count", 1))
        notes = enemy.get("notes", "")

        cr_val = _parse_cr(cr)

        # Search by name first; widen if no results
        results = await mimir.search_monsters(
            name=name,
            cr_min=max(0.0, (cr_val or 0) - 1) if cr_val else None,
            cr_max=((cr_val or 0) + 2)           if cr_val else None,
        )

        if not results and name:
            # Try just a keyword from the name
            keyword = name.split()[0]
            results = await mimir.search_monsters(name=keyword)

        if results:
            best      = results[0]
            cat_name  = best.get("name", name)
            await mimir.add_monster(module_id, cat_name, count=count, notes=notes)
            enriched.append({**enemy, "catalog_name": cat_name, "catalog_data": best})
            logger.debug(f"[MIMIR] Monster matched: {name!r} → {cat_name!r}")
        else:
            # No catalog match — create as campaign homebrew so the DM has a stat block
            cr_val = cr_val or 1.0
            # Use creature_type from the enemy dict if provided (e.g. infestation pipeline
            # passes beast/construct/ooze etc.) — fall back to humanoid only as last resort
            ctype  = enemy.get("creature_type", "humanoid")
            avg_hp = enemy.get("hp") or max(1, int(cr_val * 13 + 7))
            avg_ac = enemy.get("ac") or max(10, min(18, int(cr_val + 12)))
            import json as _json
            hw_data = _json.dumps({
                "hp":      {"average": avg_hp, "formula": f"{max(1, int(cr_val*3))}d8"},
                "ac":      [{"ac": avg_ac}],
                "cr":      cr,
                "type":    ctype,
                "size":    ["M"],
                "entries": [notes or f"Campaign creature. CR {cr}."],
            })
            hw = await mimir.create_homebrew_monster(
                name          = name,
                data_json     = hw_data,
                cr            = str(cr) if cr else "1",
                creature_type = ctype,
            )
            if hw:
                await mimir.add_monster(module_id, name, count=count, notes=notes)
                logger.debug(f"[MIMIR] Homebrew monster created: {name!r} CR {cr} ({ctype})")
                try:
                    from src.ddb_homebrew import push_mission_enemy as _ddb_push, ENABLED as _ddb_en
                    if _ddb_en:
                        import asyncio as _aio
                        _enemy_snap = {**enemy, "cr": cr or "1"}
                        _ctype_snap = ctype
                        _cr_snap    = cr or "1"
                        _notes_snap = notes
                        # Pre-built stat data from the pipeline (hp, ac, attacks, speed)
                        _prebuilt   = {
                            "hp":            avg_hp,
                            "ac":            avg_ac,
                            "creature_type": ctype,
                            "speed":         enemy.get("speed", "30 ft."),
                        }
                        _attacks = enemy.get("attacks", [])
                        if _attacks:
                            _prebuilt["actions"] = "\n\n".join(
                                f"**{a.split('.')[0]}.** {'.'.join(a.split('.')[1:]).strip()}"
                                if '.' in a else f"**Attack.** {a}"
                                for a in _attacks[:4]
                            )

                        async def _push_with_statblock(
                            _e=_enemy_snap, _c=_ctype_snap, _cr=_cr_snap,
                            _n=_notes_snap, _pb=_prebuilt
                        ):
                            # Generate full 5.5e stat block for ability scores / traits
                            sb = await _generate_statblock_llm(_e["name"], _cr, _c, _n)
                            # Overlay pre-built hp/ac/actions from the pipeline (more accurate)
                            if sb:
                                sb.update({k: v for k, v in _pb.items() if v})
                            else:
                                sb = _pb
                            await _ddb_push(_e, statblock=sb)
                            logger.debug(f"[DDB_HB] Pushed infestation monster: {_e['name']!r} ({_c})")

                        _aio.create_task(_push_with_statblock())
                except Exception as _ex:
                    logger.warning(f"[MIMIR] DDB push task failed to start for {name!r}: {_ex}")
            enriched.append({**enemy, "catalog_name": name, "catalog_data": hw})

    return enriched


# ---------------------------------------------------------------------------
# Item enrichment
# ---------------------------------------------------------------------------

async def enrich_items(module_id: str, rewards: list[dict]) -> list[dict]:
    """
    For each reward entry, search Mimir catalog.
    Returns list with 'catalog_data' field added.

    Reward dict format:
        name    : str  — item name
        rarity  : str  — common / uncommon / rare / very rare / legendary
        type    : str  — weapon / armor / wondrous item / etc.
        notes   : str
    """
    mimir = get_mimir()
    if not mimir.available or not module_id:
        return rewards

    enriched = []
    for reward in rewards:
        name   = reward.get("name", "")
        rarity = reward.get("rarity", "")
        itype  = reward.get("type", "")

        results = await mimir.search_items(name=name, rarity=rarity, item_type=itype)

        if not results and name:
            results = await mimir.search_items(name=name.split()[0])

        if results:
            best      = results[0]
            cat_name  = best.get("name", name)
            await mimir.add_item(module_id, cat_name)
            enriched.append({**reward, "catalog_name": cat_name, "catalog_data": best})
        else:
            enriched.append({**reward, "catalog_name": name, "catalog_data": None})

    return enriched


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

async def push_documents(module_id: str, documents: list[dict]) -> None:
    """
    Push read-aloud text, DM notes, and descriptions to the Mimir module.

    Document dict:
        title    : str
        type     : "read_aloud" | "dm_notes" | "description" | "backstory" | "custom"
        content  : str  — markdown OK
    """
    mimir = get_mimir()
    if not mimir.available:
        await mimir.ensure_connected()
    if not mimir.available or not module_id:
        return

    for doc in documents:
        await mimir.add_document(
            module_id=module_id,
            title=doc.get("title", "Untitled"),
            doc_type=doc.get("type", "description"),
            content=doc.get("content", ""),
        )


# ---------------------------------------------------------------------------
# Map upload
# ---------------------------------------------------------------------------

async def upload_map(module_id: str, map_path: Path | str, map_name: str = "Battle Map") -> bool:
    """Upload an A1111-generated PNG to the Mimir module."""
    mimir = get_mimir()
    if not mimir.available:
        await mimir.ensure_connected()
    if not mimir.available or not module_id:
        return False

    path = Path(map_path)
    if not path.exists():
        return False

    result = await mimir.upload_map(module_id=module_id, name=map_name, file_path=str(path))
    if result:
        logger.debug(f"[MIMIR] Map uploaded to {module_id}: {map_name}")
    return bool(result)


# ---------------------------------------------------------------------------
# HTML rendering helpers
# ---------------------------------------------------------------------------

def _e(s) -> str:
    return html_lib.escape(str(s or ""))


def _cr_color(cr_str: str) -> str:
    v = _parse_cr(cr_str) or 0
    if v <= 1:   return "#2a6a2a"
    if v <= 5:   return "#b8923a"
    if v <= 10:  return "#a04020"
    return "#7b1e1e"


def render_mimir_section(
    enemies: list[dict],
    rewards: list[dict],
    module_id: str = "",
) -> str:
    """
    Build an HTML section with real 5e stat summaries pulled from Mimir catalog.
    Injected at the bottom of any pipeline's module.html.
    Returns empty string if no Mimir data is present.
    """
    has_enemies = any(e.get("catalog_data") for e in enemies)
    has_rewards = any(r.get("catalog_data") for r in rewards)

    if not has_enemies and not has_rewards:
        return ""

    parts = [
        '<div style="margin:24px 0;border-top:3px solid #1a1a2e;padding-top:16px;">',
        '<h2 style="color:#1a1a2e;margin:0 0 12px;">📖 D&amp;D 5e Reference <span style="font-size:12px;font-weight:normal;color:#666;">(via Mimir)</span></h2>',
    ]

    if has_enemies:
        parts.append('<h3 style="color:#7b1e1e;margin:0 0 8px;">Encounter Monsters</h3>')
        parts.append('<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px;">')
        for enemy in enemies:
            cd = enemy.get("catalog_data")
            if not cd:
                continue
            name = _e(cd.get("name", enemy.get("name", "?")))
            cr   = _e(cd.get("cr", enemy.get("cr", "?")))
            _hp_raw = cd.get("hp", {}).get("average") if isinstance(cd.get("hp"), dict) else cd.get("hp")
            _ac_raw = cd.get("ac", [{}])[0].get("ac") if isinstance(cd.get("ac"), list) else cd.get("ac")
            # Fall back to CR-based estimates when catalog doesn't supply values.
            def _cr_estimate(cr_str, hp_formula, ac_formula):
                try:
                    n = float(str(cr_str).replace("1/8","0.125").replace("1/4","0.25").replace("1/2","0.5"))
                    return str(hp_formula(n)), str(ac_formula(n))
                except Exception:
                    return "?", "?"
            if not _hp_raw or not _ac_raw:
                _hp_est, _ac_est = _cr_estimate(
                    cr,
                    lambda n: max(1, int(n * 13 + 7)),
                    lambda n: max(10, min(18, int(n + 12))),
                )
            hp = _e(_hp_raw if _hp_raw else _hp_est)
            ac = _e(_ac_raw if _ac_raw else _ac_est)
            size = _e(cd.get("size", ["M"])[0] if isinstance(cd.get("size"), list) else cd.get("size", "M"))
            ctype = _e(cd.get("type", ""))
            color = _cr_color(str(cr))
            count = enemy.get("count", 1)

            parts.append(
                f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;'
                f'padding:10px 14px;background:#fff;min-width:160px;max-width:220px;">'
                f'<div style="font-weight:bold;color:{color};margin-bottom:4px;">{name}'
                + (f' ×{count}' if count > 1 else "") +
                f'</div>'
                f'<div style="font-size:12px;color:#444;">{size} {ctype}</div>'
                f'<div style="font-size:12px;margin-top:4px;">'
                f'<b>CR</b> {cr} &nbsp; <b>HP</b> {hp} &nbsp; <b>AC</b> {ac}'
                f'</div></div>'
            )
        parts.append("</div>")

    if has_rewards:
        parts.append('<h3 style="color:#2a4a7a;margin:0 0 8px;">Loot &amp; Rewards</h3>')
        parts.append('<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px;">')
        _rarity_colors = {
            "common": "#666", "uncommon": "#2a6a2a", "rare": "#1a4090",
            "very rare": "#6a1a8a", "legendary": "#b8923a", "artifact": "#7b1e1e",
        }
        for reward in rewards:
            cd = reward.get("catalog_data")
            if not cd:
                continue
            name   = _e(cd.get("name", reward.get("name", "?")))
            rarity = str(cd.get("rarity", reward.get("rarity", "common"))).lower()
            itype  = _e(cd.get("type", reward.get("type", "")))
            color  = _rarity_colors.get(rarity, "#444")

            parts.append(
                f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;'
                f'padding:10px 14px;background:#fff;min-width:160px;max-width:220px;">'
                f'<div style="font-weight:bold;color:{color};margin-bottom:4px;">{name}</div>'
                f'<div style="font-size:12px;color:#444;text-transform:capitalize;">{rarity} {itype}</div>'
                f'</div>'
            )
        parts.append("</div>")

    if module_id:
        parts.append(
            f'<div style="font-size:11px;color:#888;margin-top:4px;">'
            f'Mimir module ID: <code>{_e(module_id)}</code></div>'
        )

    parts.append("</div>")
    return "\n".join(parts)
