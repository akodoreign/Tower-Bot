"""Small DB helpers shared by mission module pipelines."""

from __future__ import annotations

from typing import Any, Mapping

from src.log import logger


def _coerce_mission_id(value: Any) -> int | None:
    try:
        mission_id = int(value)
    except (TypeError, ValueError):
        return None
    return mission_id if mission_id > 0 else None


def write_module_slug_for_mission(
    mission: Mapping[str, Any],
    module_slug: str,
    *,
    log_prefix: str = "MISSION",
) -> int:
    """Write module_slug by mission id when possible, with title fallback.

    Title fallback is intentionally retained for older callers that do not pass
    mission ids yet, but it can touch duplicate titles. Prefer id/mission_id.
    """
    from src.db_api import raw_execute

    title = str(mission.get("title") or "").strip()
    mission_id = next(
        (
            coerced
            for candidate in (mission.get("id"), mission.get("mission_id"))
            for coerced in (_coerce_mission_id(candidate),)
            if coerced is not None
        ),
        None,
    )

    if mission_id is not None:
        affected = raw_execute(
            "UPDATE missions SET module_slug=%s WHERE id=%s",
            (module_slug, mission_id),
        )
        if affected:
            return affected
        logger.warning(
            "[%s] module_slug id update affected 0 rows for mission id %s; falling back to title %r",
            log_prefix,
            mission_id,
            title,
        )
    else:
        logger.warning(
            "[%s] module_slug title fallback for %r; pass mission id to avoid duplicate-title writes",
            log_prefix,
            title,
        )

    if not title:
        logger.warning("[%s] module_slug update skipped: no mission id or title", log_prefix)
        return 0

    # Title fallback: check for duplicates first — refuse ambiguous writes
    from src.db_api import raw_query
    matches = raw_query("SELECT id FROM missions WHERE title=%s", (title,)) or []
    if len(matches) > 1:
        logger.error(
            "[%s] module_slug title fallback ABORTED — %d rows match title %r. "
            "Pass mission id to avoid wrong-row writes.",
            log_prefix, len(matches), title,
        )
        return 0
    if not matches:
        logger.warning("[%s] module_slug title fallback: no row found for %r", log_prefix, title)
        return 0

    return raw_execute(
        "UPDATE missions SET module_slug=%s WHERE id=%s",
        (module_slug, matches[0]["id"]),
    )
