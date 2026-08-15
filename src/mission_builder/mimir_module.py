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


# RETIRED 2026-08-15. Stat blocks come from the curated `monsters` table, never
# from a model. This fabricated ability scores and traits for any creature that
# was neither db_backed nor in the Mimir catalog -- which is how homebrew filled
# with generic "soldiers / fighters". enrich_monsters() now substitutes a
# CR-appropriate curated creature instead, and the last-resort branch ships the
# pipeline's own computed numbers. Kept unreferenced rather than deleted so the
# next person sees WHY there is no LLM in this path.
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
# Curated monsters -- our `monsters` table is the authority, never the model
# ---------------------------------------------------------------------------

def _blocks_to_entries(text: str) -> list[dict]:
    """Split a curated 'Name. Body text' block into 5etools {name, entries} dicts."""
    out: list[dict] = []
    for para in [p.strip() for p in str(text or "").split("\n\n") if p.strip()]:
        head, sep, body = para.partition(". ")
        if sep and len(head) <= 60:
            out.append({"name": head.strip(), "entries": [body.strip()]})
        else:
            out.append({"name": "", "entries": [para]})
    return out


def _speed_value(speed: str) -> dict | str:
    """'30 ft.' -> {'walk': 30}; anything more exotic stays as written."""
    m = re.match(r"^\s*(\d+)\s*ft\.?\s*$", str(speed or ""))
    return {"walk": int(m.group(1))} if m else str(speed or "30 ft.")


def _curated_monster_data(sb: dict) -> str:
    """5etools-shaped payload built entirely from a curated `monsters` row.

    Every field here comes from MySQL. Nothing is estimated from CR and nothing
    is generated -- that is the whole point of this path.
    """
    import json as _json

    hp     = sb.get("hp")
    die    = sb.get("hp_die") or "8"
    die_n  = sb.get("hp_die_count")
    data: dict = {
        "name": sb.get("name"),
        "size": [str(sb.get("size") or "M")[:1].upper()],
        "type": sb.get("creature_type") or "humanoid",
        "cr":   str(sb.get("cr") or "1"),
        "ac":   [{"ac": sb["ac"]}] if sb.get("ac") else [],
        "hp":   {"average": hp, "formula": f"{die_n}d{die}" if die_n else ""} if hp else {},
        "speed": _speed_value(sb.get("speed")),
    }

    for out_key, in_key in (("str", "str_"), ("dex", "dex"), ("con", "con"),
                            ("int", "int_"), ("wis", "wis"), ("cha", "cha")):
        if sb.get(in_key) is not None:
            data[out_key] = sb[in_key]

    if sb.get("saves"):
        data["save"] = {k: (f"+{v}" if isinstance(v, int) and v >= 0 else str(v))
                        for k, v in dict(sb["saves"]).items()}
    if sb.get("passive_perc") is not None:
        data["passive"] = sb["passive_perc"]
    if sb.get("languages"):
        data["languages"] = [s.strip() for s in str(sb["languages"]).split(",") if s.strip()]

    for out_key, in_key in (("trait", "traits"), ("action", "actions"),
                            ("reaction", "reactions"), ("bonus", "bonus_actions"),
                            ("legendary", "legendary_actions"), ("mythic", "mythic_actions"),
                            ("legendaryGroup", "lair_actions")):
        entries = _blocks_to_entries(sb.get(in_key))
        if entries:
            data[out_key] = entries

    if sb.get("notes"):
        data["entries"] = [str(sb["notes"])]

    return _json.dumps(data)


async def _sync_curated_homebrew(mimir, enemy: dict) -> None:
    """Mirror a curated monster into Mimir homebrew once, with its real stats.

    Guarded by the `mimir_sync` table (entity_type='monster') so repeated module
    builds stop stacking duplicate copies of the same creature -- the old path
    re-created a fresh stub on every single build, which is why the homebrew
    table filled up with things like 'soldiers / fighters'.
    """
    sb   = enemy.get("statblock") or {}
    name = str(sb.get("name") or enemy.get("name") or "").strip()
    if not name:
        return

    try:
        from src.mimir_sync import _get_sync_row, _upsert_sync, _make_hash
    except Exception as exc:
        logger.debug(f"[MIMIR] Curated sync bookkeeping unavailable: {exc}")
        return

    payload = _curated_monster_data(sb)
    try:
        stat_hash = _make_hash({"data": payload})
        row = _get_sync_row("monster", name)
        if row and row.get("sync_hash") == stat_hash:
            return
    except Exception as exc:
        logger.debug(f"[MIMIR] Curated sync lookup failed for {name!r}: {exc}")
        return

    try:
        hw = await mimir.create_homebrew_monster(
            name          = name,
            data_json     = payload,
            cr            = str(sb.get("cr") or "1"),
            creature_type = sb.get("creature_type") or "humanoid",
        )
        if hw:
            _upsert_sync("monster", name, str(hw.get("id") or ""), stat_hash)
            logger.debug(f"[MIMIR] Curated homebrew synced: {name!r} CR {sb.get('cr')}")
    except Exception as exc:
        logger.warning(f"[MIMIR] Curated homebrew sync failed for {name!r}: {exc}")


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

        # Creatures from our curated `monsters` table are already authoritative:
        # real 5e stat block, already pushed to DDB, already portrait-enriched.
        # Register them on the module and stop -- no catalog fuzzy-match (which
        # used to resolve "Faction Enforcer" to nothing and fall through), no
        # fabricated homebrew stub, and no LLM-generated stat block.
        if enemy.get("db_backed") and enemy.get("statblock"):
            await mimir.add_monster(module_id, name, count=count, notes=notes)
            await _sync_curated_homebrew(mimir, enemy)
            enriched.append({**enemy, "catalog_name": name, "catalog_data": None})
            logger.debug(f"[MIMIR] Curated monster used as-is: {name!r} CR {cr}")
            continue

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
                            # A one-off creature still gets its own homebrew
                            # entry -- but its ability scores come from a
                            # CR-matched creature in the curated `monsters`
                            # table, never from a model. The LLM used to invent
                            # them here, which is how homebrew filled with
                            # generic "soldiers / fighters" that looked
                            # authoritative and were not.
                            sb = dict(_pb)
                            try:
                                from src.mission_builder.monster_roster import pick_monster_by_cr
                                _ref = pick_monster_by_cr(
                                    float(_parse_cr(str(_cr)) or 1.0),
                                    creature_type=_c or "",
                                )
                                if _ref:
                                    for _k_sb, _k_row in (
                                        ("str_", "stat_str"), ("dex", "stat_dex"),
                                        ("con", "stat_con"), ("int_", "stat_int"),
                                        ("wis", "stat_wis"), ("cha", "stat_cha"),
                                        ("passive_perc", "passive_perc"),
                                        ("languages", "languages"),
                                    ):
                                        if _ref.get(_k_row):
                                            sb.setdefault(_k_sb, _ref[_k_row])
                                    logger.debug(
                                        f"[MIMIR] {_e['name']!r} ability scores taken from "
                                        f"curated {_ref.get('name')!r} (CR {_ref.get('cr')})"
                                    )
                            except Exception as _ref_err:
                                logger.debug(f"[MIMIR] curated score lookup failed: {_ref_err}")
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


async def enrich_mission_loot(module_id: str, mission: dict) -> list[dict]:
    """
    Attach the mission's rolled loot to the Mimir module and return enriched
    reward dicts for render_mimir_section.

    Reads the treasure package that src.treasure.loot_card cached on the
    mission dict (mission["_loot_pkg"]). Only the slots holding real item
    names go to the catalog: "magic" (treasure_items magic_item rows) and
    "mimir" (already a catalog item). Store gadgets, food, and elemental gems
    are campaign-custom and stay out of the 5e catalog lookup.

    No-op (returns []) when there is no package, no lootable item, no module,
    or Mimir is down.
    """
    pkg = (mission or {}).get("_loot_pkg") or {}
    rewards: list[dict] = []
    for slot in ("magic", "mimir"):
        entry = pkg.get(slot)
        if isinstance(entry, dict) and entry.get("name"):
            rewards.append({
                "name":   entry["name"],
                "rarity": entry.get("rarity", ""),
                "type":   entry.get("item_type", ""),
                "notes":  entry.get("effect", ""),
            })
    if not rewards or not module_id:
        return []
    try:
        return await enrich_items(module_id, rewards)
    except Exception as e:
        logger.warning(f"[MIMIR] Loot enrichment failed: {e}")
        return []


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


_ABILITY_LABELS = (("STR", "str_"), ("DEX", "dex"), ("CON", "con"),
                   ("INT", "int_"), ("WIS", "wis"), ("CHA", "cha"))


def _ability_mod(score) -> str:
    try:
        mod = (int(score) - 10) // 2
    except (TypeError, ValueError):
        return ""
    return f"+{mod}" if mod >= 0 else str(mod)


def _render_curated_statblock(enemy: dict) -> str:
    """Full runnable stat block for a creature from our `monsters` table.

    The DM has to fight this thing at the table, so print what it actually does
    -- ability scores, saves, traits, actions, reactions -- not a CR/HP/AC chip.
    """
    sb    = enemy.get("statblock") or {}
    color = _cr_color(str(sb.get("cr") or 1))
    count = enemy.get("count", 1)
    name  = _e(sb.get("name") or enemy.get("name") or "?")
    if count and int(count) > 1:
        name += f' <span style="font-weight:normal;font-size:13px;">x{count}</span>'

    size_word = {"T": "Tiny", "S": "Small", "M": "Medium",
                 "L": "Large", "H": "Huge", "G": "Gargantuan"}.get(
        str(sb.get("size") or "M")[:1].upper(), "Medium")

    rows = [
        f'<div style="font-size:18px;font-weight:bold;color:{color};">{name}</div>',
        f'<div style="font-style:italic;color:#555;font-size:13px;margin-bottom:6px;">'
        f'{_e(size_word)} {_e(sb.get("creature_type") or "humanoid")}</div>',
        f'<div style="border-top:2px solid {color};margin:6px 0;"></div>',
    ]

    stat_line = " &nbsp; ".join(
        f"<b>{lab}</b> {_e(sb.get(key))} ({_e(_ability_mod(sb.get(key)))})"
        for lab, key in _ABILITY_LABELS if sb.get(key) is not None
    )
    meta = [
        f'<b>AC</b> {_e(sb.get("ac"))}' if sb.get("ac") else "",
        f'<b>HP</b> {_e(sb.get("hp"))}' + (
            f' ({_e(sb.get("hp_die_count"))}d{_e(sb.get("hp_die"))})'
            if sb.get("hp_die_count") else ""
        ) if sb.get("hp") else "",
        f'<b>Speed</b> {_e(sb.get("speed"))}' if sb.get("speed") else "",
        f'<b>CR</b> {_e(sb.get("cr"))}' if sb.get("cr") else "",
    ]
    rows.append('<div style="font-size:13px;">' + " &nbsp; ".join(p for p in meta if p) + "</div>")
    if stat_line:
        rows.append(f'<div style="font-size:13px;margin-top:4px;">{stat_line}</div>')

    extras = []
    if sb.get("saves"):
        extras.append("<b>Saves</b> " + _e(", ".join(
            f"{k.upper()} {'+' if isinstance(v, int) and v >= 0 else ''}{v}"
            for k, v in dict(sb["saves"]).items()
        )))
    if sb.get("passive_perc") is not None:
        extras.append(f'<b>Passive Perception</b> {_e(sb.get("passive_perc"))}')
    if sb.get("languages"):
        extras.append(f'<b>Languages</b> {_e(sb.get("languages"))}')
    if extras:
        rows.append(f'<div style="font-size:13px;margin-top:4px;">{" &nbsp; ".join(extras)}</div>')

    for heading, key in (("Traits", "traits"), ("Actions", "actions"),
                         ("Bonus Actions", "bonus_actions"), ("Reactions", "reactions"),
                         ("Legendary Actions", "legendary_actions"),
                         ("Mythic Actions", "mythic_actions"),
                         ("Lair Actions", "lair_actions")):
        body = str(sb.get(key) or "").strip()
        if not body:
            continue
        rows.append(f'<div style="border-top:1px solid {color};margin:8px 0 4px;"></div>')
        rows.append(
            f'<div style="font-variant:small-caps;font-weight:bold;letter-spacing:1px;'
            f'color:{color};font-size:14px;">{heading}</div>'
        )
        for para in [p.strip() for p in body.split("\n\n") if p.strip()]:
            head, sep, rest = para.partition(". ")
            if sep and len(head) <= 60:
                rows.append(f'<div style="font-size:13px;margin:3px 0;">'
                            f'<b><i>{_e(head)}.</i></b> {_e(rest)}</div>')
            else:
                rows.append(f'<div style="font-size:13px;margin:3px 0;">{_e(para)}</div>')

    if enemy.get("ddb_url"):
        rows.append(
            f'<div style="font-size:11px;margin-top:8px;">'
            f'<a href="{_e(enemy["ddb_url"])}" style="color:#666;">D&amp;D Beyond stat block</a></div>'
        )

    return (
        f'<div style="border:1px solid {color};border-left:5px solid {color};border-radius:6px;'
        f'padding:12px 16px;background:#fffdf8;flex:1 1 320px;max-width:460px;">'
        + "\n".join(rows) +
        "</div>"
    )


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
    has_enemies = any(e.get("catalog_data") or e.get("hp") or e.get("cr") for e in enemies)
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
            # Curated `monsters` row -> print the whole stat block. These are the
            # creatures we built and already pushed to DDB; the DM should not have
            # to go look anything up mid-fight.
            if enemy.get("db_backed") and enemy.get("statblock"):
                parts.append(_render_curated_statblock(enemy))
                continue

            cd = enemy.get("catalog_data") or {}
            # Prefer our own DB-backed stats (authoritative) over the fuzzy Mimir
            # catalog match, which often resolves grunts/bosses to a generic
            # creature ("Construct Spirit") with no CR/HP/AC. Use cd to fill gaps only.
            _cd_hp = cd.get("hp", {}).get("average") if isinstance(cd.get("hp"), dict) else cd.get("hp")
            _cd_ac = cd.get("ac", [{}])[0].get("ac") if isinstance(cd.get("ac"), list) else cd.get("ac")
            name_raw = enemy.get("name") or cd.get("name") or "?"
            cr_raw   = enemy.get("cr") or cd.get("cr") or ""
            hp_raw   = enemy.get("hp") or _cd_hp
            ac_raw   = enemy.get("ac") or _cd_ac
            if not (cr_raw or hp_raw or ac_raw or cd):
                continue
            # CR-based estimate fills any remaining gap.
            def _cr_estimate(cr_str):
                try:
                    n = float(str(cr_str).replace("1/8","0.125").replace("1/4","0.25").replace("1/2","0.5"))
                    return str(max(1, int(n * 13 + 7))), str(max(10, min(18, int(n + 12))))
                except Exception:
                    return "?", "?"
            _hp_est, _ac_est = _cr_estimate(cr_raw)
            name = _e(name_raw)
            cr   = _e(str(cr_raw) if cr_raw else "?")
            hp = _e(hp_raw if hp_raw else _hp_est)
            ac = _e(ac_raw if ac_raw else _ac_est)
            size = _e((cd.get("size", ["M"])[0] if isinstance(cd.get("size"), list) else cd.get("size")) or "M")
            ctype = _e(enemy.get("creature_type") or cd.get("type") or "")
            color = _cr_color(str(cr_raw or 1))
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
