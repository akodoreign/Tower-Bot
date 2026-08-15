"""Generated ads in MySQL instead of a 34KB JSON list in global_state.

The nightly ad study produced 109 ads and appended each one to
`global_state['generated_ads']`. Every consumer then loaded the whole blob to
pick ONE ad, and filtered it in Python:

    ad_feed         -> ads that have a shop_name and ad_text, then random.choice
    party_interview -> ad_type in ('shop','tourism'), then random.choice

That is `WHERE ... ORDER BY RAND() LIMIT 1` written the long way, over a field
(`ad_type`, `district`) that is exactly what the JSON reflex check says belongs
in a real column. 6 ad types, 30 districts, all 109 with a shop name.

`dnd_tags` gets its own child table. It is only passed through today rather than
queried, but it is a small list of short strings and a join is cheaper than the
next person needing "every ad tagged healing" and finding it locked in a blob.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from src.db_api import raw_execute, raw_query
from src.log import logger

_SCHEMA_READY = False


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    try:
        raw_execute(
            """
            CREATE TABLE IF NOT EXISTS generated_ads (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                ad_text       TEXT         NOT NULL,
                ad_type       VARCHAR(32)  NOT NULL DEFAULT 'shop',
                district      VARCHAR(120) NULL,
                shop_name     VARCHAR(200) NULL,
                bulletin_type VARCHAR(32)  NULL,
                active        TINYINT(1)   NOT NULL DEFAULT 1,
                created_at    DATETIME     NOT NULL,
                KEY idx_type_active (ad_type, active),
                KEY idx_district (district),
                KEY idx_shop (shop_name)
            )
            """,
            (),
        )
        raw_execute(
            """
            CREATE TABLE IF NOT EXISTS generated_ad_tags (
                id     INT AUTO_INCREMENT PRIMARY KEY,
                ad_id  INT         NOT NULL,
                tag    VARCHAR(64) NOT NULL,
                UNIQUE KEY uniq_ad_tag (ad_id, tag),
                KEY idx_tag (tag)
            )
            """,
            (),
        )
        _SCHEMA_READY = True
    except Exception as exc:
        logger.error(f"[ads] schema init failed: {exc}")


def add_ad(ad: dict) -> Optional[int]:
    """Persist one generated ad. Returns its id."""
    ensure_schema()
    text = str(ad.get("ad_text") or "").strip()
    if not text:
        return None
    now = datetime.now()
    try:
        # db.insert() returns cursor.lastrowid from the SAME connection.
        #
        # NOT "INSERT ...; SELECT LAST_INSERT_ID()". The pool hands the second
        # statement a different connection, where LAST_INSERT_ID() is 0 or
        # someone else's -- so the parent row lands and the child rows are
        # silently dropped. That is exactly how the first ad migration wrote
        # 109 ads but only 178 of ~316 tags, and how the council migration
        # wrote 110 rulings and ZERO votes.
        from src.db_api import db
        ad_id = db.insert("generated_ads", {
            "ad_text":       text,
            "ad_type":       str(ad.get("ad_type") or "shop")[:32],
            "district":      ad.get("district") or None,
            "shop_name":     ad.get("shop_name") or None,
            "bulletin_type": ad.get("bulletin_type") or None,
            "active":        1,
            "created_at":    now,
        })
    except Exception as exc:
        logger.error(f"[ads] insert failed: {exc}")
        return None
    if not ad_id:
        logger.error("[ads] insert returned no id -- tags would be orphaned")
        return None

    for tag in (ad.get("dnd_tags") or []):
        tag = str(tag).strip()[:64]
        if not tag:
            continue
        try:
            raw_execute(
                "INSERT IGNORE INTO generated_ad_tags (ad_id, tag) VALUES (%s,%s)",
                (ad_id, tag),
            )
        except Exception as exc:
            logger.debug(f"[ads] tag insert failed ({tag}): {exc}")
    return ad_id


def _with_tags(rows: list[dict]) -> list[dict]:
    """Attach dnd_tags so callers keep the shape they already expect."""
    if not rows:
        return []
    ids = [int(r["id"]) for r in rows]
    tags: dict[int, list[str]] = {i: [] for i in ids}
    try:
        placeholders = ",".join(["%s"] * len(ids))
        for t in raw_query(
            f"SELECT ad_id, tag FROM generated_ad_tags WHERE ad_id IN ({placeholders})",
            tuple(ids),
        ) or []:
            tags.setdefault(int(t["ad_id"]), []).append(t["tag"])
    except Exception as exc:
        logger.debug(f"[ads] tag fetch failed: {exc}")
    for r in rows:
        r["dnd_tags"] = tags.get(int(r["id"]), [])
    return rows


def pick_ad(ad_types: Optional[Iterable[str]] = None,
            require_shop: bool = True) -> Optional[dict]:
    """One random ad matching the filter -- chosen by the database.

    Replaces "load 34KB, filter in Python, random.choice".
    """
    ensure_schema()
    where = ["active = 1", "ad_text <> ''"]
    params: list = []
    if require_shop:
        where.append("shop_name IS NOT NULL AND shop_name <> ''")
    types = [t for t in (ad_types or []) if t]
    if types:
        where.append("ad_type IN (" + ",".join(["%s"] * len(types)) + ")")
        params.extend(types)
    try:
        rows = raw_query(
            "SELECT * FROM generated_ads WHERE " + " AND ".join(where)
            + " ORDER BY RAND() LIMIT 1", tuple(params)
        ) or []
    except Exception as exc:
        logger.warning(f"[ads] pick failed: {exc}")
        return None
    return _with_tags(rows)[0] if rows else None


def all_ads(limit: int = 500) -> list[dict]:
    ensure_schema()
    rows = raw_query(
        "SELECT * FROM generated_ads WHERE active = 1 ORDER BY id DESC LIMIT %s",
        (int(limit),),
    ) or []
    return _with_tags(rows)


def ad_count() -> int:
    ensure_schema()
    rows = raw_query("SELECT COUNT(*) c FROM generated_ads WHERE active = 1") or [{"c": 0}]
    return int(rows[0]["c"])
