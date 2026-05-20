"""
enrich_creatures_ddb.py — Add portraits and fill out stat content for the 73
module creatures already imported to DDB.

Reads:
  logs/creature_ddb_import.log  — name -> edit URL mapping
  scripts/creature_ddb_staging.json — stat block data

For each creature:
  1. Generates a 256x256 portrait via A1111 (or skips if already cached)
  2. GETs the DDB edit page for fresh CSRF tokens
  3. POSTs full traits / actions / reactions / lair / legendary + portrait

Resumes cleanly: checks logs/creature_enrich.log for already-done names.

Run from project root AFTER the NPC import pipeline finishes:
    python scripts/enrich_creatures_ddb.py
"""
from __future__ import annotations

import argparse, asyncio, base64, html, io, json, os, re, sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

import httpx
from PIL import Image

from src.ddb_homebrew import SESSION, _CR_OPTIONS, _TYPE_OPTIONS, _SIZE_OPTIONS
from src.log import logger
from scripts.fix_ebp_types_and_art import A1111_URL, _NEG, generate_art

IMPORT_LOG   = ROOT / "logs" / "creature_ddb_import.log"
ENRICH_LOG   = ROOT / "logs" / "creature_enrich.log"
STAGING_FILE = ROOT / "scripts" / "creature_ddb_staging.json"
ART_DIR      = ROOT / "campaign_docs" / "npc_appearances" / "module_creatures_ddb"
ART_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL     = "https://www.dndbeyond.com"
DEFAULT_DB_MONSTER_SOURCES = ("undercity", "undercity_high_cr", "faction_generic")

log_lines: list[str] = []

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_lines.append(line)
    with open(ENRICH_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _ascii(s: str) -> str:
    return s.replace("—", "--").replace("–", "-").replace("’", "'").replace("‘", "'")

def _html(s: str) -> str:
    if not s: return ""
    return "".join(
        f"<p>{p.replace(chr(10), '<br>').strip()}</p>"
        for p in s.split("\n\n") if p.strip()
    )


def _json_list(path: Path) -> list[dict]:
    if not path.exists():
        log(f"[SKIP] Missing staging file: {path}")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _decode_json(value, fallback=None):
    if fallback is None:
        fallback = {}
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


async def _get_csrf(url: str) -> tuple[str, str, str, str, dict]:
    hdrs = {"Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124"}
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=30) as c:
            r = await c.get(url, headers=hdrs, cookies={"CobaltSession": SESSION})
            if r.status_code != 200:
                return "", "", "", "", {}
            alb     = r.cookies.get("AWSALB", "")
            albcors = r.cookies.get("AWSALBCORS", "")
            html    = r.text

        def _hid(field):
            m = re.search(r'name="' + re.escape(field) + r'"[^>]*value="([^"]*?)"', html)
            if not m:
                m = re.search(r'value="([^"]*?)"[^>]*name="' + re.escape(field) + r'"', html)
            return m.group(1) if m else ""

        obf: dict = {}
        for m in re.finditer(r"<input[^>]+>", html, re.IGNORECASE):
            inp = m.group()
            nm  = re.search(r'name="(f[a-f0-9]{30,})"', inp)
            idm = re.search(r'id="([^"]+)"', inp)
            if nm and idm:
                obf[idm.group(1)] = nm.group(1)
        for fid in ("field-avatar", "field-large-avatar"):
            m = re.search(r'id="' + re.escape(fid) + r'"[^>]*name="([^"]+)"', html, re.IGNORECASE)
            if not m:
                m = re.search(r'name="([^"]+)"[^>]*id="' + re.escape(fid) + r'"', html, re.IGNORECASE)
            if m:
                obf[fid] = m.group(1)
        return _hid("security-token"), _hid("authenticity-token"), alb, albcors, obf
    except Exception as exc:
        logger.warning("[ENRICH] GET error: %s", exc)
        return "", "", "", "", {}


async def _get_edit_html(url: str) -> str:
    hdrs = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=30) as c:
            r = await c.get(url, headers=hdrs, cookies={"CobaltSession": SESSION})
            if r.status_code != 200:
                log(f"  DDB GET returned {r.status_code} for {url}")
                return ""
            return r.text or ""
    except Exception as exc:
        logger.warning("[ENRICH] DDB edit-page GET error: %s", exc)
        return ""


def _form_textarea_value(page_html: str, field_name: str) -> str:
    if not page_html:
        return ""
    m = re.search(
        r"<textarea\b[^>]*\bname=[\"']" + re.escape(field_name) + r"[\"'][^>]*>(.*?)</textarea>",
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return ""
    text = html.unescape(m.group(1) or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _ddb_ability_fields(page_html: str) -> dict[str, str]:
    fields = (
        "special-traits-description",
        "actions-description",
        "bonus-actions-description",
        "reactions-description",
        "legendary-actions-description",
        "mythic-actions-description",
        "lair-description",
    )
    return {field: _form_textarea_value(page_html, field) for field in fields}


def _has_ddb_abilities(page_html: str) -> bool:
    values = _ddb_ability_fields(page_html)
    return any(bool(v.strip()) for v in values.values())


def _has_local_abilities(data: dict) -> bool:
    keys = (
        "traits",
        "actions",
        "bonus_actions",
        "reactions",
        "legendary_actions",
        "mythic_actions",
        "lair_actions",
    )
    return any(str(data.get(k) or "").strip() for k in keys)


async def _generate_portrait(prompt: str, cache_path: Path) -> Optional[bytes]:
    if cache_path.exists():
        return cache_path.read_bytes()
    try:
        payload = {
            "prompt":          prompt,
            "negative_prompt": _NEG,
            "width": 512, "height": 512,
            "steps": 25, "cfg_scale": 7.5,
            "sampler_name": "DPM++ 2M Karras",
            "n_iter": 1, "batch_size": 1,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
            r.raise_for_status()
            img_b64 = r.json()["images"][0]
        img = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGBA")
        img = img.resize((256, 256), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        cache_path.write_bytes(png)
        return png
    except Exception as exc:
        logger.warning("[ENRICH] Art gen failed for %r: %s", cache_path.stem, exc)
        return None


async def get_or_generate_portrait(name: str, creature_type: str, cr: str) -> Optional[bytes]:
    safe  = name.replace(" ", "_").replace("/", "_").replace("'", "").replace(",", "")
    cache = ART_DIR / f"{safe}.png"
    prompt = (
        f"{name}, {creature_type}, CR {cr}, "
        "D&D monster encounter, fantasy creature, detailed digital illustration, "
        "dark background, dramatic lighting, 8k uhd, cinematic, professional concept art"
    )
    return await _generate_portrait(prompt, cache)


NPC_ART_DIR = ROOT / "campaign_docs" / "npc_appearances" / "npc_portraits_ddb"

async def get_or_generate_npc_portrait(npc: dict) -> Optional[bytes]:
    name = npc["name"]
    safe = name.replace(" ", "_").replace("/", "_").replace("'", "").replace(",", "")
    cache = NPC_ART_DIR / f"{safe}.png"
    if cache.exists():
        return cache.read_bytes()

    # Try existing campaign portrait first
    portrait_path = npc.get("portrait_path")
    if portrait_path:
        p = Path(portrait_path)
        if p.exists():
            try:
                img = Image.open(p).convert("RGBA").resize((256, 256), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                png = buf.getvalue()
                cache.write_bytes(png)
                return png
            except Exception:
                pass

    sd = npc.get("sd_appearance", "")
    if not sd:
        return None
    prompt = (
        f"{sd[:300]}, D&D NPC portrait, fantasy RPG character art, "
        "dark background, detailed digital illustration, 8k uhd, cinematic lighting, professional concept art"
    )
    return await _generate_portrait(prompt, cache)


async def enrich_creature(edit_url: str, data: dict, portrait: Optional[bytes]) -> bool:
    """POST full content + portrait to DDB edit URL."""
    sec, auth, alb, albcors, obf = await _get_csrf(edit_url)
    if not sec:
        return False

    cr     = str(data.get("cr", "1"))
    ctype  = data.get("creature_type", "humanoid")
    size   = data.get("size", "M")
    ac     = data.get("ac", 10)
    hp     = data.get("hp", 10)
    hp_die = str(data.get("hp_die", "8"))
    hp_dc  = data.get("hp_die_count", 1)
    con    = data.get("con", 10)
    str_   = data.get("str_", 10)
    dex    = data.get("dex", 10)
    int_   = data.get("int_", 10)
    wis    = data.get("wis", 10)
    cha    = data.get("cha", 10)
    pp     = data.get("passive_perc", 10)
    lang   = data.get("languages", "Common")

    actions   = _ascii(data.get("actions",   ""))
    traits    = _ascii(data.get("traits",    ""))
    reactions = _ascii(data.get("reactions", ""))
    bonus     = _ascii(data.get("bonus_actions", ""))
    legendary = _ascii(data.get("legendary_actions", ""))
    lair      = _ascii(data.get("lair_actions", ""))

    type_id = _TYPE_OPTIONS.get(ctype.lower(), "11")
    size_id = _SIZE_OPTIONS.get(size, "4")
    cr_id   = _CR_OPTIONS.get(cr, "5")
    die_val = hp_die if hp_die in ("4","6","8","10","12","20") else "8"
    hp_mod  = ((con - 10) // 2) * hp_dc

    text_data: dict = {
        "security-token": sec, "authenticity-token": auth,
        "Name":             _ascii(data["name"]),
        "stat-block-type":  "1",
        "monster-type":     type_id,
        "size":             size_id,
        "challenge-rating": cr_id,
        "armor-class":      str(ac),
        "passive-perception": str(pp),
        "average-hit-points": str(hp),
        "hit-points-die-count": str(hp_dc),
        "hit-points-die-value": die_val,
        "hit-points-modifier":  str(hp_mod),
        "languages-note":   lang,
        "special-traits-description-type":    "1",
        "special-traits-description-wysiwyg": _html(traits),
        "special-traits-description":         traits,
        "actions-description-type":    "1",
        "actions-description-wysiwyg": _html(actions),
        "actions-description":         actions,
        "bonus-actions-description-type":    "1",
        "bonus-actions-description-wysiwyg": _html(bonus),
        "bonus-actions-description":         bonus,
        "reactions-description-type":    "1",
        "reactions-description-wysiwyg": _html(reactions),
        "reactions-description":         reactions,
        "monster-characteristics-description-type": "1",
        "monster-characteristics-description-wysiwyg": _html(data.get("notes", "")),
        "monster-characteristics-description": data.get("notes", ""),
        "legendary-actions-description-type": "1",
        "mythic-actions-description-type":    "1",
        "lair-description-type":              "1",
    }
    if legendary:
        text_data["is-legendary"] = "y"
        text_data["legendary-actions-description-wysiwyg"] = _html(legendary)
        text_data["legendary-actions-description"]          = legendary
    if lair:
        text_data["has-lair"] = "y"
        text_data["lair-description-wysiwyg"] = _html(lair)
        text_data["lair-description"]          = lair
        text_data["lair-challenge-rating"]     = cr_id

    score_map = {
        "field-strength": str(str_), "field-dexterity": str(dex),
        "field-constitution": str(con), "field-intelligence": str(int_),
        "field-wisdom": str(wis), "field-charisma": str(cha),
        "field-initiative-bonus": str((dex - 10) // 2),
    }
    for fid, val in score_map.items():
        if fid in obf:
            text_data[obf[fid]] = val

    saves = data.get("saves", {})
    save_fid = {
        "str": "field-strength-save-bonus", "dex": "field-dexterity-save-bonus",
        "con": "field-constitution-save-bonus", "int": "field-intelligence-save-bonus",
        "wis": "field-wisdom-save-bonus", "cha": "field-charisma-save-bonus",
    }
    for stat_key, fid_name in save_fid.items():
        if stat_key in saves and fid_name in obf:
            text_data[obf[fid_name]] = str(saves[stat_key])

    file_data: dict = {}
    if portrait:
        if "field-avatar" in obf:
            file_data[obf["field-avatar"]] = ("avatar.png", portrait, "image/png")
        if "field-large-avatar" in obf:
            file_data[obf["field-large-avatar"]] = ("large_avatar.png", portrait, "image/png")

    cookies = {"CobaltSession": SESSION}
    if alb:
        cookies["AWSALB"] = alb; cookies["AWSALBCORS"] = albcors
    hdrs = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124",
        "Origin": BASE_URL, "Referer": edit_url,
    }

    async with httpx.AsyncClient(follow_redirects=False, timeout=30) as c:
        resp = await c.post(
            edit_url, data=text_data,
            files=file_data if file_data else None,
            headers=hdrs, cookies=cookies,
        )

    ok = resp.status_code in (200, 301, 302, 303, 307, 308)
    if not ok:
        logger.warning("[ENRICH] POST %s for %r", resp.status_code, data["name"])
    return ok


def _parse_done_names(log_path: Path) -> set[str]:
    done: set[str] = set()
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            m = re.search(r"DONE: (.+?) \|", line)
            if m:
                done.add(m.group(1).strip())
    return done


def _parse_edit_urls(log_path: Path) -> dict[str, str]:
    urls: dict[str, str] = {}
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            m = re.search(r"DONE: (.+?) -> (https://[^\s]+)", line)
            if m:
                urls[m.group(1).strip()] = m.group(2).strip()
    return urls


async def run_pass(label: str, edit_urls: dict, by_name: dict,
                   done: set, portrait_fn, enrich_log: Path):
    log(f"\n{'='*60}")
    log(f"  {label}  ({len(edit_urls)} entries)")
    log(f"{'='*60}")

    ok = 0; fail = 0; no_art = 0
    total = len(edit_urls)

    for i, (name, edit_url) in enumerate(edit_urls.items(), 1):
        if name in done:
            continue
        data = by_name.get(name)
        if not data:
            log(f"[{i:03d}/{total}] SKIP {name!r} — not in staging")
            continue

        cr    = data.get("cr", "?")
        ctype = data.get("creature_type", "humanoid")
        log(f"[{i:03d}/{total}] {name}  CR{cr} {ctype}")

        portrait = await portrait_fn(data)
        if portrait:
            log(f"  Portrait OK ({len(portrait)//1024}KB)")
        else:
            log(f"  No portrait")
            no_art += 1

        success = await enrich_creature(edit_url, data, portrait)
        if success:
            log(f"  DONE: {name} | {edit_url}")
            ok += 1
        else:
            log(f"  FAIL: {name}")
            fail += 1

        await asyncio.sleep(1.5)

    log(f"\nPass done: {ok} OK, {fail} failed, {no_art} without art")
    return ok, fail, no_art


def _db_row_to_enrich_data(row: dict) -> dict:
    """Convert a monsters DB row to the data dict expected by enrich_creature()."""
    return {
        "name":             row["name"],
        "cr":               str(row.get("cr") or "1"),
        "creature_type":    row.get("creature_type") or "monstrosity",
        "size":             row.get("size") or "M",
        "ac":               int(row.get("ac") or 12),
        "hp":               int(row.get("hp") or 15),
        "hp_die":           str(row.get("hp_die") or "8"),
        "hp_die_count":     int(row.get("hp_die_count") or 2),
        "str_":             int(row.get("stat_str") or 10),
        "dex":              int(row.get("stat_dex") or 10),
        "con":              int(row.get("stat_con") or 10),
        "int_":             int(row.get("stat_int") or 10),
        "wis":              int(row.get("stat_wis") or 10),
        "cha":              int(row.get("stat_cha") or 10),
        "passive_perc":     int(row.get("passive_perc") or 10),
        "languages":        row.get("languages") or "Common",
        "actions":          row.get("actions") or "",
        "traits":           row.get("traits") or "",
        "reactions":        row.get("reactions") or "",
        "bonus_actions":    row.get("bonus_actions") or "",
        "legendary_actions": row.get("legendary_actions") or "",
        "mythic_actions":   row.get("mythic_actions") or "",
        "lair_actions":     row.get("lair_actions") or "",
        "notes":            row.get("notes") or "",
        "sd_appearance":    row.get("sd_appearance") or "",
        "saves":            _decode_json(row.get("saves_json"), {}),
        "portrait_path":    row.get("portrait_path"),
    }


def _db_edit_url(view_url: str) -> str:
    """Return the DDB edit URL.

    push_monster_http() already redirects directly to the /edit URL, so
    the returned URL IS the edit URL. No transformation needed.
    """
    return view_url or ""


def _parse_sources(raw: str) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_DB_MONSTER_SOURCES
    raw = raw.strip()
    if raw.lower() in {"all", "*"}:
        return ()
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def _db_monster_filters(
    sources: tuple[str, ...],
    *,
    cr_min: int | None = None,
    cr_max: int | None = None,
    void_mode: str = "all",
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if sources:
        clauses.append("source IN (" + ", ".join(["%s"] * len(sources)) + ")")
        params.extend(sources)
    if cr_min is not None:
        clauses.append("cr+0 >= %s")
        params.append(cr_min)
    if cr_max is not None:
        clauses.append("cr+0 <= %s")
        params.append(cr_max)
    if void_mode == "void":
        clauses.append("is_void=1")
    elif void_mode == "regular":
        clauses.append("is_void=0")
    return clauses, params


def _limit_clause(limit: int | None) -> str:
    if not limit:
        return ""
    return f" LIMIT {max(1, int(limit))}"


def _source_label(sources: tuple[str, ...]) -> str:
    return ", ".join(sources) if sources else "all sources"


async def run_db_import_pass(
    sources: tuple[str, ...] = DEFAULT_DB_MONSTER_SOURCES,
    *,
    limit: int | None = None,
    cr_min: int | None = None,
    cr_max: int | None = None,
    void_mode: str = "all",
    dry_run: bool = False,
):
    """PASS 3 — Create DDB homebrew entries for UC monsters not yet imported."""
    try:
        from src.db_api import raw_query, raw_execute
    except Exception as exc:
        log(f"[PASS 3] DB unavailable: {exc}")
        return

    clauses, params = _db_monster_filters(
        sources, cr_min=cr_min, cr_max=cr_max, void_mode=void_mode
    )
    clauses.append("ddb_url IS NULL")
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = raw_query(
        "SELECT * FROM monsters WHERE " + where
        + " ORDER BY cr+0, is_void, name"
        + _limit_clause(limit),
        tuple(params),
    ) or []

    if not rows:
        log(f"\n[PASS 3] No new DB monsters to import ({_source_label(sources)}).")
        return

    log(f"\n{'='*60}")
    mode = "DRY RUN - " if dry_run else ""
    log(f"  PASS 3 - {mode}Import DB Monsters ({_source_label(sources)})  ({len(rows)} pending)")
    log(f"{'='*60}")

    from src.ddb_homebrew import push_monster_http

    ok = fail = 0
    for i, row in enumerate(rows, 1):
        name = row["name"]
        cr   = str(row.get("cr") or "1")
        log(f"[{i:03d}/{len(rows)}] {name}  CR{cr}  source={row.get('source')}")
        if dry_run:
            log("  DRY RUN: would create DDB monster and update ddb_url/ddb_edit_url")
            ok += 1
            continue
        try:
            data = _db_row_to_enrich_data(row)
            url  = await push_monster_http(
                name          = data["name"],
                cr            = data["cr"],
                creature_type = data["creature_type"],
                size          = data["size"],
                ac            = data["ac"],
                hp            = data["hp"],
                hp_die        = data["hp_die"],
                hp_die_count  = data["hp_die_count"],
                str_          = data["str_"],
                dex           = data["dex"],
                con           = data["con"],
                int_          = data["int_"],
                wis           = data["wis"],
                cha           = data["cha"],
                passive_perc  = data["passive_perc"],
                languages     = data["languages"],
                actions       = _ascii(data["actions"]),
                notes         = _ascii(data["notes"]),
            )
            if url:
                edit_url = _db_edit_url(url)
                raw_execute(
                    "UPDATE monsters SET ddb_url=%s, ddb_edit_url=%s WHERE name=%s",
                    (url, edit_url, name),
                )
                log(f"  OK  -> {url}")
                ok += 1
            else:
                log(f"  FAIL  (no URL returned)")
                fail += 1
        except Exception as exc:
            log(f"  FAIL  {exc}")
            fail += 1
        await asyncio.sleep(3)

    log(f"\nPass 3 done: {ok} OK, {fail} failed.")


async def run_db_ability_repair_pass(
    sources: tuple[str, ...] = DEFAULT_DB_MONSTER_SOURCES,
    *,
    limit: int | None = None,
    cr_min: int | None = None,
    cr_max: int | None = None,
    void_mode: str = "all",
    dry_run: bool = False,
):
    """PASS 3.5 — Repair DDB monsters whose ability/action fields are empty."""
    try:
        from src.db_api import raw_query, raw_execute
    except Exception as exc:
        log(f"[PASS 3.5] DB unavailable: {exc}")
        return

    clauses, params = _db_monster_filters(
        sources, cr_min=cr_min, cr_max=cr_max, void_mode=void_mode
    )
    clauses.append("ddb_edit_url IS NOT NULL")
    clauses.append(
        "("
        "COALESCE(traits,'')<>'' OR COALESCE(actions,'')<>'' OR "
        "COALESCE(bonus_actions,'')<>'' OR COALESCE(reactions,'')<>'' OR "
        "COALESCE(legendary_actions,'')<>'' OR COALESCE(mythic_actions,'')<>'' OR "
        "COALESCE(lair_actions,'')<>''"
        ")"
    )
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = raw_query(
        "SELECT * FROM monsters WHERE " + where
        + " ORDER BY cr+0, is_void, name"
        + _limit_clause(limit),
        tuple(params),
    ) or []

    if not rows:
        log(f"\n[PASS 3.5] No imported DB monsters with local abilities ({_source_label(sources)}).")
        return

    log(f"\n{'='*60}")
    mode = "DRY RUN - " if dry_run else ""
    log(f"  PASS 3.5 - {mode}Repair Empty DDB Abilities ({_source_label(sources)})  ({len(rows)} candidates)")
    log(f"{'='*60}")

    ok = fail = skipped = 0
    for i, row in enumerate(rows, 1):
        name     = row["name"]
        edit_url = row["ddb_edit_url"]
        cr       = str(row.get("cr") or "1")
        ctype    = row.get("creature_type") or "monstrosity"
        log(f"[{i:03d}/{len(rows)}] {name}  CR{cr} {ctype}  source={row.get('source')}")

        data = _db_row_to_enrich_data(row)
        if not _has_local_abilities(data):
            log("  SKIP: DB row has no local traits/actions to push")
            skipped += 1
            continue

        page_html = await _get_edit_html(edit_url)
        if not page_html:
            log("  FAIL: could not read DDB edit page")
            fail += 1
            continue

        if _has_ddb_abilities(page_html):
            log("  SKIP: DDB already has ability/action text")
            skipped += 1
            continue

        if dry_run:
            log("  DRY RUN: DDB ability fields are empty; would POST DB traits/actions without portrait")
            ok += 1
            continue

        success = await enrich_creature(edit_url, data, portrait=None)
        if success:
            raw_execute(
                "UPDATE monsters SET enriched_at=COALESCE(enriched_at, NOW()) WHERE name=%s",
                (name,),
            )
            log(f"  REPAIRED: {name}")
            ok += 1
        else:
            log(f"  FAIL: {name}")
            fail += 1

        await asyncio.sleep(1.5)

    log(f"\nPass 3.5 done: {ok} repaired, {fail} failed, {skipped} skipped.")


async def run_db_portrait_pass(
    sources: tuple[str, ...] = DEFAULT_DB_MONSTER_SOURCES,
    *,
    limit: int | None = None,
    cr_min: int | None = None,
    cr_max: int | None = None,
    void_mode: str = "all",
    dry_run: bool = False,
):
    """PASS 5 — Generate missing portraits for already-enriched DB monsters."""
    try:
        from src.db_api import raw_query, raw_execute
    except Exception as exc:
        log(f"[PASS 5] DB unavailable: {exc}")
        return

    clauses, params = _db_monster_filters(
        sources, cr_min=cr_min, cr_max=cr_max, void_mode=void_mode
    )
    where = " AND ".join(clauses) if clauses else "1=1"
    all_rows = raw_query(
        "SELECT name, cr, creature_type, source, sd_appearance FROM monsters WHERE " + where
        + " ORDER BY cr+0, is_void, name"
        + _limit_clause(limit),
        tuple(params),
    ) or []

    # Filter to monsters whose portrait file is actually missing on disk
    def _portrait_path(name: str) -> Path:
        safe = name.replace(" ", "_").replace("/", "_").replace("'", "").replace(",", "")
        return ART_DIR / f"{safe}.png"

    rows = [r for r in all_rows if not _portrait_path(r["name"]).exists()]

    if not rows:
        log(f"\n[PASS 5] No DB monsters missing portraits ({_source_label(sources)}).")
        return

    log(f"\n{'='*60}")
    mode = "DRY RUN - " if dry_run else ""
    log(f"  PASS 5 - {mode}Portrait Backfill ({_source_label(sources)})  ({len(rows)} pending)")
    log(f"{'='*60}")

    ok = fail = 0
    for i, row in enumerate(rows, 1):
        name  = row["name"]
        cr    = str(row.get("cr") or "1")
        ctype = row.get("creature_type") or "monstrosity"
        log(f"[{i:03d}/{len(rows)}] {name}  CR{cr} {ctype}")
        if dry_run:
            log("  DRY RUN: would generate portrait and update portrait_path")
            ok += 1
            continue

        portrait = await get_or_generate_portrait(name, ctype, cr)
        if portrait:
            path = str(_portrait_path(name))
            raw_execute("UPDATE monsters SET portrait_path=%s WHERE name=%s", (path, name))
            log(f"  Portrait OK ({len(portrait)//1024}KB)")
            ok += 1
        else:
            log(f"  FAIL: no portrait generated")
            fail += 1

        await asyncio.sleep(0.5)

    log(f"\nPass 5 done: {ok} OK, {fail} failed.")


async def run_db_enrich_pass(
    sources: tuple[str, ...] = DEFAULT_DB_MONSTER_SOURCES,
    *,
    limit: int | None = None,
    cr_min: int | None = None,
    cr_max: int | None = None,
    void_mode: str = "all",
    dry_run: bool = False,
):
    """PASS 4 — Enrich UC monsters that are imported but not yet enriched."""
    try:
        from src.db_api import raw_query, raw_execute
    except Exception as exc:
        log(f"[PASS 4] DB unavailable: {exc}")
        return

    clauses, params = _db_monster_filters(
        sources, cr_min=cr_min, cr_max=cr_max, void_mode=void_mode
    )
    clauses.extend(["ddb_edit_url IS NOT NULL", "enriched_at IS NULL"])
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = raw_query(
        "SELECT * FROM monsters WHERE " + where
        + " ORDER BY cr+0, is_void, name"
        + _limit_clause(limit),
        tuple(params),
    ) or []

    if not rows:
        log(f"\n[PASS 4] No DB monsters pending enrichment ({_source_label(sources)}).")
        return

    log(f"\n{'='*60}")
    mode = "DRY RUN - " if dry_run else ""
    log(f"  PASS 4 - {mode}Enrich DB Monsters ({_source_label(sources)})  ({len(rows)} pending)")
    log(f"{'='*60}")

    ok = fail = no_art = 0
    for i, row in enumerate(rows, 1):
        name     = row["name"]
        edit_url = row["ddb_edit_url"]
        cr       = str(row.get("cr") or "1")
        ctype    = row.get("creature_type") or "monstrosity"
        log(f"[{i:03d}/{len(rows)}] {name}  CR{cr} {ctype}  source={row.get('source')}")

        data = _db_row_to_enrich_data(row)
        if dry_run:
            log("  DRY RUN: would generate portrait, POST enriched stat text, and set enriched_at")
            ok += 1
            continue

        portrait = await get_or_generate_portrait(name, ctype, cr)
        if portrait:
            log(f"  Portrait OK ({len(portrait)//1024}KB)")
        else:
            log(f"  No portrait")
            no_art += 1

        success = await enrich_creature(edit_url, data, portrait)
        if success:
            raw_execute(
                "UPDATE monsters SET enriched_at=NOW(), portrait_path=%s WHERE name=%s",
                (str(ART_DIR / f"{name.replace(' ','_').replace('/','_').replace(chr(39),'').replace(',','')}.png"),
                 name),
            )
            log(f"  DONE: {name}")
            ok += 1
        else:
            log(f"  FAIL: {name}")
            fail += 1

        await asyncio.sleep(1.5)

    log(f"\nPass 4 done: {ok} OK, {fail} failed, {no_art} without art.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Enrich/import DDB homebrew creatures from staging files and the monsters DB."
    )
    p.add_argument("--db-only", action="store_true", help="Only process monsters DB rows. This is now the default.")
    p.add_argument(
        "--include-legacy",
        action="store_true",
        help="Also run legacy module creature and NPC staging-log passes before DB monsters.",
    )
    p.add_argument("--skip-db", action="store_true", help="Skip the monsters DB import/enrich passes.")
    p.add_argument("--dry-run", action="store_true", help="List DB work without touching DDB or generating art.")
    p.add_argument(
        "--monster-sources",
        default=",".join(DEFAULT_DB_MONSTER_SOURCES),
        help="Comma-separated DB monster sources, or 'all'.",
    )
    p.add_argument("--monster-limit", type=int, default=0, help="Limit DB monsters per DB pass.")
    p.add_argument("--cr-min", type=int, default=None, help="Minimum CR for DB monster passes.")
    p.add_argument("--cr-max", type=int, default=None, help="Maximum CR for DB monster passes.")
    p.add_argument(
        "--repair-abilities-only",
        action="store_true",
        help="Only run PASS 3.5: inspect DDB edit pages and fill empty ability/action fields from the monsters DB.",
    )
    p.add_argument("--portraits-only", action="store_true", help="Only run PASS 5: generate missing portrait art files without re-enriching DDB.")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--void-only", action="store_true", help="Only process void monsters.")
    group.add_argument("--regular-only", action="store_true", help="Only process non-void monsters.")
    return p.parse_args(argv)


async def main(argv: list[str] | None = None):
    args = parse_args(argv)
    sources = _parse_sources(args.monster_sources)
    void_mode = "void" if args.void_only else "regular" if args.regular_only else "all"
    limit = args.monster_limit or None
    NPC_IMPORT_LOG  = ROOT / "logs" / "npc_ddb_import.log"
    NPC_STAGING     = ROOT / "scripts" / "npc_ddb_staging.json"
    NPC_ENRICH_LOG  = ROOT / "logs" / "npc_enrich.log"
    NPC_ART_DIR.mkdir(parents=True, exist_ok=True)

    # ── PASS 1: Creature enrichment (stats + portrait) ────────────────────────
    run_legacy = args.include_legacy and not args.db_only

    creature_urls  = {} if not run_legacy else _parse_edit_urls(IMPORT_LOG)
    creature_data  = {} if not run_legacy else {c["name"]: c for c in _json_list(STAGING_FILE)}
    creature_done  = set() if not run_legacy else _parse_done_names(ENRICH_LOG)

    async def creature_portrait(data):
        return await get_or_generate_portrait(data["name"], data.get("creature_type","humanoid"), data.get("cr","1"))

    if run_legacy:
        await run_pass("PASS 1 - Module Creatures (stats + portraits)",
                       creature_urls, creature_data, creature_done, creature_portrait, ENRICH_LOG)

    # ── PASS 2: NPC portrait fill (for NPCs that imported without art) ────────
    npc_urls  = {} if not run_legacy else _parse_edit_urls(NPC_IMPORT_LOG)
    npc_data  = {} if not run_legacy else {n["name"]: n for n in _json_list(NPC_STAGING)}
    npc_done  = set() if not run_legacy else _parse_done_names(NPC_ENRICH_LOG)

    # Only process NPCs whose portrait cache is still missing
    npc_missing = {
        name: url for name, url in npc_urls.items()
        if name not in npc_done
        and not (NPC_ART_DIR / f"{name.replace(' ','_').replace('/','_').replace(chr(39),'').replace(',','')}.png").exists()
    }
    if run_legacy:
        log(f"\nNPCs needing portraits: {len(npc_missing)} of {len(npc_urls)}")

        await run_pass("PASS 2 - NPC portrait fill",
                       npc_missing, npc_data, npc_done, get_or_generate_npc_portrait, NPC_ENRICH_LOG)

    # ── PASS 5: Portrait-only backfill (--portraits-only shortcut) ──────────
    if args.portraits_only:
        await run_db_portrait_pass(
            sources,
            limit=limit,
            cr_min=args.cr_min,
            cr_max=args.cr_max,
            void_mode=void_mode,
            dry_run=args.dry_run,
        )
        log("\nAll done.")
        return

    # ── PASS 3.5: Repair imported DDB monsters with empty ability fields ────
    if args.repair_abilities_only:
        await run_db_ability_repair_pass(
            sources,
            limit=limit,
            cr_min=args.cr_min,
            cr_max=args.cr_max,
            void_mode=void_mode,
            dry_run=args.dry_run,
        )
        log("\nAll done.")
        return

    # ── PASS 3: Import new DB monsters (monsters table, ddb_url IS NULL) ─────
    if not args.skip_db:
        await run_db_import_pass(
            sources,
            limit=limit,
            cr_min=args.cr_min,
            cr_max=args.cr_max,
            void_mode=void_mode,
            dry_run=args.dry_run,
        )

        # ── PASS 3.5: Repair imported DDB monsters with empty ability fields ────
        await run_db_ability_repair_pass(
            sources,
            limit=limit,
            cr_min=args.cr_min,
            cr_max=args.cr_max,
            void_mode=void_mode,
            dry_run=args.dry_run,
        )

        # ── PASS 4: Enrich DB monsters (ddb_edit_url set, enriched_at IS NULL) ───
        await run_db_enrich_pass(
            sources,
            limit=limit,
            cr_min=args.cr_min,
            cr_max=args.cr_max,
            void_mode=void_mode,
            dry_run=args.dry_run,
        )

        # ── PASS 5: Portrait backfill (portrait_path IS NULL) ────────────────
        await run_db_portrait_pass(
            sources,
            limit=limit,
            cr_min=args.cr_min,
            cr_max=args.cr_max,
            void_mode=void_mode,
            dry_run=args.dry_run,
        )

    log("\nAll done.")


if __name__ == "__main__":
    asyncio.run(main())
