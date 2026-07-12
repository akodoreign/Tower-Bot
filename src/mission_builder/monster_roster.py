"""
DB-backed monster roster helpers for mission pipelines.

Use this module when a pipeline needs campaign monsters by CR, creature type,
or void status. This keeps monster selection out of LLM prompts and pointed at
the authoritative MySQL `monsters` table.
"""
from __future__ import annotations

import json
import random
from typing import Any, Optional

from src.db_api import raw_query
from src.mission_builder.cr_scaling import mission_cr


DEFAULT_SOURCES = ("undercity", "undercity_high_cr", "faction_generic")
MONSTER_SOURCES = ("undercity", "undercity_high_cr")
FACTION_SOURCE = "faction_generic"

ROLE_KEYWORDS = {
    "thug": ("thug", "goon", "street", "mob", "gang"),
    "scout": ("scout", "lookout", "watch", "tail", "spy"),
    "archer": ("archer", "bow", "ranged", "shooter", "crossbow"),
    "bruiser": ("bruiser", "heavy", "brawler", "muscle"),
    "enforcer": ("enforcer", "guard", "soldier", "officer", "contractor"),
    "priest": ("priest", "preist", "acolyte", "cleric", "cult", "choir", "devotee"),
    "shieldbearer": ("shield", "wall", "riot", "protector"),
    "handler": ("handler", "beast", "asset", "prisoner", "escort"),
    "alchemist": ("alchemist", "poison", "acid", "fire", "chemist"),
    "saboteur": ("saboteur", "bomber", "trap", "explosive", "arson"),
    "zealot": ("zealot", "fanatic", "faithful", "returned"),
    "mage": ("mage", "wizard", "arcane", "spell", "analyst"),
    "duelist": ("duelist", "blade", "operative", "lotus"),
    "lieutenant": ("lieutenant", "lt", "sergeant", "prior", "supervisor"),
    "assassin": ("assassin", "killer", "knife", "shadow"),
    "quartermaster": ("quartermaster", "supply", "logistics", "paymaster"),
    "captain": ("captain", "commander", "leader", "officer"),
    "champion": ("champion", "elite", "hero", "executioner"),
}


def _decode_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _row_to_monster(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["is_void"] = bool(out.get("is_void"))
    out["saves"] = _decode_json(out.pop("saves_json", None), {})
    try:
        out["cr_float"] = float(out.get("cr") or 0)
    except (TypeError, ValueError):
        out["cr_float"] = 0.0
    return out


def get_monsters_by_cr(
    cr_min: float,
    cr_max: Optional[float] = None,
    *,
    count: int = 5,
    creature_type: str = "",
    include_void: bool = True,
    only_void: bool = False,
    source: str = "",
) -> list[dict[str, Any]]:
    """Return monsters from MySQL matching a CR range.

    Args:
        cr_min: Minimum challenge rating, inclusive.
        cr_max: Maximum challenge rating, inclusive. Defaults to cr_min.
        count: Maximum rows to return.
        creature_type: Optional exact creature type filter.
        include_void: If false, exclude void variants.
        only_void: If true, return only void variants.
        source: Optional source filter such as "undercity_high_cr".
    """
    cr_max = cr_min if cr_max is None else cr_max
    clauses = ["CAST(cr AS DECIMAL(6,2)) BETWEEN %s AND %s"]
    params: list[Any] = [cr_min, cr_max]

    if creature_type:
        clauses.append("creature_type = %s")
        params.append(creature_type)
    if only_void:
        clauses.append("is_void = 1")
    elif not include_void:
        clauses.append("is_void = 0")
    if source:
        clauses.append("source = %s")
        params.append(source)

    params.append(max(1, int(count)))
    rows = raw_query(
        "SELECT * FROM monsters WHERE "
        + " AND ".join(clauses)
        + " ORDER BY RAND() LIMIT %s",
        tuple(params),
    ) or []
    return [_row_to_monster(row) for row in rows]


def get_monsters_by_cr_sources(
    cr_min: float,
    cr_max: Optional[float] = None,
    *,
    count: int = 5,
    creature_type: str = "",
    include_void: bool = True,
    only_void: bool = False,
    sources: tuple[str, ...] = DEFAULT_SOURCES,
) -> list[dict[str, Any]]:
    """Return monsters from one or more DB sources."""
    cr_max = cr_min if cr_max is None else cr_max
    clauses = ["CAST(cr AS DECIMAL(6,2)) BETWEEN %s AND %s"]
    params: list[Any] = [cr_min, cr_max]

    if creature_type:
        clauses.append("creature_type = %s")
        params.append(creature_type)
    if only_void:
        clauses.append("is_void = 1")
    elif not include_void:
        clauses.append("is_void = 0")
    if sources:
        clauses.append("source IN (" + ", ".join(["%s"] * len(sources)) + ")")
        params.extend(sources)

    params.append(max(1, int(count)))
    rows = raw_query(
        "SELECT * FROM monsters WHERE "
        + " AND ".join(clauses)
        + " ORDER BY RAND() LIMIT %s",
        tuple(params),
    ) or []
    return [_row_to_monster(row) for row in rows]


def pick_monster_by_cr(
    cr: float,
    *,
    spread: float = 2,
    creature_type: str = "",
    include_void: bool = True,
    only_void: bool = False,
    sources: tuple[str, ...] = MONSTER_SOURCES,
) -> Optional[dict[str, Any]]:
    rows = get_monsters_by_cr_sources(
        max(0, cr - spread),
        cr + spread,
        count=1,
        creature_type=creature_type,
        include_void=include_void,
        only_void=only_void,
        sources=sources,
    )
    return rows[0] if rows else None


def faction_role_monsters(
    roles: list[str] | tuple[str, ...],
    *,
    count: int = 5,
    cr_min: float | None = None,
    cr_max: float | None = None,
    target_cr: float | None = None,
) -> list[dict[str, Any]]:
    """Return reusable source=faction_generic stat blocks by role names."""
    wanted = [r.lower().strip() for r in roles if r]
    clauses = ["source = %s"]
    params: list[Any] = [FACTION_SOURCE]
    if wanted:
        clauses.append("(" + " OR ".join(["LOWER(name) LIKE %s"] * len(wanted)) + ")")
        params.extend([f"%{r}%" for r in wanted])
    if cr_min is not None:
        clauses.append("CAST(cr AS DECIMAL(6,2)) >= %s")
        params.append(cr_min)
    if cr_max is not None:
        clauses.append("CAST(cr AS DECIMAL(6,2)) <= %s")
        params.append(cr_max)
    order_sql = "CAST(cr AS DECIMAL(6,2)) DESC, RAND()"
    if target_cr is not None:
        order_sql = "ABS(CAST(cr AS DECIMAL(6,2)) - %s), CAST(cr AS DECIMAL(6,2)) DESC, RAND()"
        params.append(target_cr)
    params.append(max(1, int(count)))
    rows = raw_query(
        "SELECT * FROM monsters WHERE "
        + " AND ".join(clauses)
        + f" ORDER BY {order_sql} LIMIT %s",
        tuple(params),
    ) or []
    return [_row_to_monster(row) for row in rows]


def infer_faction_roles(text: str, *, max_roles: int = 4) -> list[str]:
    low = (text or "").lower()
    found: list[str] = []
    for role, keywords in ROLE_KEYWORDS.items():
        if any(k in low for k in keywords):
            found.append(role)
    if not found:
        found = ["enforcer", "lieutenant", "priest", "scout"]
    random.shuffle(found)
    return found[:max_roles]


def logical_enemy_roster(
    *,
    mission_type: str = "",
    faction: str = "",
    opposing_faction: str = "",
    cr: float = 5,
    count: int = 3,
    prefer_void: bool = False,
    prefer_monsters: bool = False,
    prefer_faction_roles: bool = False,
    creature_type: str = "",
) -> list[dict[str, Any]]:
    """Pick table-ready enemies from DB using mission context.

    This favors faction_generic humanoids for guards, security, and faction-vs-faction
    work, and campaign monsters for infestation, rift/void, breakout, and beastier
    conflicts.
    """
    text = f"{mission_type} {faction} {opposing_faction} {creature_type}".lower()
    wants_void = prefer_void or any(w in text for w in ("void", "rift", "corrupt"))
    wants_monsters = prefer_monsters or wants_void or any(
        w in text for w in ("infestation", "monster", "beast", "creature", "breakout", "lair")
    )
    wants_roles = prefer_faction_roles or not wants_monsters or any(
        w in text for w in ("guard", "security", "faction", "assault", "defense", "battle", "ambush", "rescue")
    )

    roster: list[dict[str, Any]] = []
    if wants_roles:
        roles = infer_faction_roles(text, max_roles=count)
        roster.extend(
            faction_role_monsters(
                roles,
                count=count,
                cr_min=max(1, cr - 3),
                cr_max=max(1, cr + 2),
                target_cr=cr,
            )
        )

    if len(roster) < count and wants_monsters:
        roster.extend(
            get_monsters_by_cr_sources(
                max(0, cr - 2),
                cr + 2,
                count=count - len(roster),
                creature_type=creature_type,
                include_void=not wants_void,
                only_void=wants_void,
                sources=MONSTER_SOURCES,
            )
        )

    if len(roster) < count:
        if prefer_faction_roles:
            roster.extend(
                faction_role_monsters(
                    [],
                    count=count - len(roster),
                    cr_min=max(1, cr - 3),
                    cr_max=max(1, cr + 2),
                    target_cr=cr,
                )
            )
            return roster[:count]
        roster.extend(
            get_monsters_by_cr_sources(
                max(0, cr - 2),
                cr + 2,
                count=count - len(roster),
                include_void=True,
                sources=DEFAULT_SOURCES,
            )
        )
    return roster[:count]


def logical_enemy_roster_for_mission(
    mission: dict[str, Any],
    *,
    count: int = 3,
    prefer_void: bool = False,
    prefer_monsters: bool = False,
    prefer_faction_roles: bool = False,
    creature_type: str = "",
) -> list[dict[str, Any]]:
    return logical_enemy_roster(
        mission_type=str(mission.get("type") or mission.get("mission_type") or mission.get("tier") or ""),
        faction=str(mission.get("faction") or ""),
        opposing_faction=str(mission.get("opposing_faction") or mission.get("guarding_faction") or ""),
        cr=mission_cr(mission),
        count=count,
        prefer_void=prefer_void,
        prefer_monsters=prefer_monsters,
        prefer_faction_roles=prefer_faction_roles,
        creature_type=creature_type,
    )


def get_void_variants(base_name: str, *, count: int = 5) -> list[dict[str, Any]]:
    rows = raw_query(
        "SELECT * FROM monsters WHERE base_name = %s AND is_void = 1 ORDER BY CAST(cr AS DECIMAL(6,2)), name LIMIT %s",
        (base_name, max(1, int(count))),
    ) or []
    return [_row_to_monster(row) for row in rows]


def monster_summary(monster: dict[str, Any]) -> str:
    """Compact monster text suitable for a prompt, room note, or encounter card."""
    parts = [
        f"{monster.get('name')} (CR {monster.get('cr')}, {monster.get('size')} {monster.get('creature_type')})",
        f"AC {monster.get('ac')}, HP {monster.get('hp')}, speed {monster.get('speed')}",
    ]
    if monster.get("traits"):
        parts.append(f"Traits: {str(monster.get('traits')).splitlines()[0]}")
    if monster.get("actions"):
        parts.append(f"Actions: {str(monster.get('actions')).splitlines()[0]}")
    return " | ".join(parts)


def mission_enemy_entry(
    monster: dict[str, Any],
    *,
    count: int = 1,
    notes: str = "",
) -> dict[str, Any]:
    """Shape a DB monster row for Mimir/DDB mission enemy enrichment."""
    attacks = []
    if monster.get("actions"):
        attacks = [p.strip() for p in str(monster["actions"]).split("\n\n") if p.strip()][:4]
    return {
        "name": monster.get("name"),
        "cr": str(monster.get("cr") or "1"),
        "count": count,
        "notes": notes or monster.get("notes") or monster_summary(monster),
        "creature_type": monster.get("creature_type") or "humanoid",
        "hp": monster.get("hp"),
        "ac": monster.get("ac"),
        "speed": monster.get("speed") or "30 ft.",
        "attacks": attacks,
        "traits": monster.get("traits") or "",
        "source": monster.get("source") or "",
    }
