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

import asyncio, base64, io, json, os, re, sys
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


async def main():
    NPC_IMPORT_LOG  = ROOT / "logs" / "npc_ddb_import.log"
    NPC_STAGING     = ROOT / "scripts" / "npc_ddb_staging.json"
    NPC_ENRICH_LOG  = ROOT / "logs" / "npc_enrich.log"
    NPC_ART_DIR.mkdir(parents=True, exist_ok=True)

    # ── PASS 1: Creature enrichment (stats + portrait) ────────────────────────
    creature_urls  = _parse_edit_urls(IMPORT_LOG)
    creature_data  = {c["name"]: c for c in json.loads(STAGING_FILE.read_text(encoding="utf-8"))}
    creature_done  = _parse_done_names(ENRICH_LOG)

    async def creature_portrait(data):
        return await get_or_generate_portrait(data["name"], data.get("creature_type","humanoid"), data.get("cr","1"))

    await run_pass("PASS 1 — Module Creatures (stats + portraits)",
                   creature_urls, creature_data, creature_done, creature_portrait, ENRICH_LOG)

    # ── PASS 2: NPC portrait fill (for NPCs that imported without art) ────────
    npc_urls  = _parse_edit_urls(NPC_IMPORT_LOG)
    npc_data  = {n["name"]: n for n in json.loads(NPC_STAGING.read_text(encoding="utf-8"))}
    npc_done  = _parse_done_names(NPC_ENRICH_LOG)

    # Only process NPCs whose portrait cache is still missing
    npc_missing = {
        name: url for name, url in npc_urls.items()
        if name not in npc_done
        and not (NPC_ART_DIR / f"{name.replace(' ','_').replace('/','_').replace(chr(39),'').replace(',','')}.png").exists()
    }
    log(f"\nNPCs needing portraits: {len(npc_missing)} of {len(npc_urls)}")

    await run_pass("PASS 2 — NPC portrait fill",
                   npc_missing, npc_data, npc_done, get_or_generate_npc_portrait, NPC_ENRICH_LOG)

    log("\nAll done.")


if __name__ == "__main__":
    asyncio.run(main())
