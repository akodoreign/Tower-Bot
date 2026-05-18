"""
update_ebp_content.py

Full content pass for all 49 EBP creatures:
  - Traits, reactions, legendary, mythic, lair text in correct DDB fields
  - Speed entries added via /monster/movement/create/{id}
  - HP modifier corrected
  - Creates 3 new entries: Ninyoldah, Froddandan, Frummach
  - Re-generates missing art (Type One BE) and art for new creatures

Run from project root:
    python scripts/update_ebp_content.py
"""
from __future__ import annotations

import asyncio, base64, io, os, re, sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx
from PIL import Image

from src.ddb_homebrew import SESSION, _CR_OPTIONS, _TYPE_OPTIONS, _SIZE_OPTIONS
from src.log import logger
from scripts.ebp_enriched_data import ENRICHED, NEW_CREATURES
from scripts.fix_ebp_types_and_art import (
    EDIT_SLUGS, ART_DIR, A1111_URL, _NEG, ART_PROMPTS, generate_art,
)
from scripts.import_ebp_to_ddb import CREATURES as BASE_CREATURES

LOG_FILE = ROOT / "logs" / "ebp_update_content.log"
BASE_URL = "https://www.dndbeyond.com"

creature_by_name = {c["name"]: c for c in BASE_CREATURES}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _ascii(s: str) -> str:
    return s.replace("—", "--").replace("–", "-")

def _html(s: str) -> str:
    """Convert plain text with \\n\\n paragraph breaks to simple HTML for DDB wysiwyg fields."""
    if not s:
        return ""
    paragraphs = s.split("\n\n")
    parts = []
    for p in paragraphs:
        p = p.replace("\n", "<br>").strip()
        if p:
            parts.append(f"<p>{p}</p>")
    return "".join(parts)

def _hp_modifier(con: int, die_count: int) -> int:
    return ((con - 10) // 2) * die_count


async def _get_csrf(url: str) -> tuple[str, str, str, str, dict]:
    """GET url, return (security_token, authenticity_token, awsalb, awsalbcors, obf_map)."""
    hdrs = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124",
    }
    async with httpx.AsyncClient(follow_redirects=False, timeout=30) as c:
        r = await c.get(url, headers=hdrs, cookies={"CobaltSession": SESSION})
        if r.status_code not in (200,):
            return "", "", "", "", {}
        awsalb     = r.cookies.get("AWSALB", "")
        awsalbcors = r.cookies.get("AWSALBCORS", "")
        html       = r.text

    def _hidden(field):
        m = re.search(r'name="' + re.escape(field) + r'"[^>]*value="([^"]*?)"', html)
        if not m:
            m = re.search(r'value="([^"]*?)"[^>]*name="' + re.escape(field) + r'"', html)
        return m.group(1) if m else ""

    obf = {}
    for m in re.finditer(r"<input[^>]+>", html, re.IGNORECASE):
        inp = m.group()
        nm  = re.search(r'name="(f[a-f0-9]{30,})"', inp)
        idm = re.search(r'id="([^"]+)"', inp)
        if nm and idm:
            obf[idm.group(1)] = nm.group(1)
    # Avatar obf names use a different pattern on edit page
    for fid in ("field-avatar", "field-large-avatar"):
        m = re.search(r'id="' + re.escape(fid) + r'"[^>]*name="([^"]+)"', html, re.IGNORECASE)
        if not m:
            m = re.search(r'name="([^"]+)"[^>]*id="' + re.escape(fid) + r'"', html, re.IGNORECASE)
        if m:
            obf[fid] = m.group(1)

    return _hidden("security-token"), _hidden("authenticity-token"), awsalb, awsalbcors, obf


async def add_speed(monster_id: str, movement_type: int, speed_ft: int) -> bool:
    """POST one speed entry to /monster/movement/create/{id}."""
    if speed_ft == 0:
        return True  # nothing to submit for 0 ft speeds
    url = f"{BASE_URL}/monster/movement/create/{monster_id}"
    sec, auth, alb, albcors, _ = await _get_csrf(url)
    if not sec:
        return False
    data = {"security-token": sec, "authenticity-token": auth,
            "movement-type": str(movement_type), "speed": str(speed_ft)}
    cookies = {"CobaltSession": SESSION}
    if alb:
        cookies["AWSALB"] = alb; cookies["AWSALBCORS"] = albcors
    hdrs = {"Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124",
            "Origin": BASE_URL, "Referer": url}
    async with httpx.AsyncClient(follow_redirects=False, timeout=20) as c:
        r = await c.post(url, data=data, headers=hdrs, cookies=cookies)
    return r.status_code in (200, 301, 302, 303, 307, 308)


async def edit_full(edit_slug: str, base: dict, enriched: dict,
                    image_bytes: Optional[bytes]) -> bool:
    """Edit a DDB monster entry with full enriched content + optional image."""
    edit_url = f"{BASE_URL}/homebrew/creations/monsters/{edit_slug}/edit"
    hdrs = {"Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124",
            "Origin": BASE_URL, "Referer": edit_url}
    sec, auth, alb, albcors, obf = await _get_csrf(edit_url)
    if not sec:
        return False

    cr            = base.get("cr", "1")
    creature_type = base.get("creature_type", "humanoid")
    size          = base.get("size", "M")
    ac            = base.get("ac", 12)
    hp            = base.get("hp", 15)
    hp_die        = base.get("hp_die", "8")
    hp_die_count  = base.get("hp_die_count", 2)
    con           = base.get("con", 10)
    str_          = base.get("str_", 10)
    dex           = base.get("dex", 10)
    int_          = base.get("int_", 10)
    wis           = base.get("wis", 10)
    cha           = base.get("cha", 10)
    passive_perc  = base.get("passive_perc", 10)
    actions_text  = _ascii(base.get("actions", ""))
    name          = _ascii(base["name"])
    languages     = base.get("languages", "")
    if languages in ("--", "—", "–", "- -"):
        languages = "None"
    languages = _ascii(languages)

    traits     = _ascii(enriched.get("traits", ""))
    bonus_acts = _ascii(enriched.get("bonus_actions", ""))
    reactions  = _ascii(enriched.get("reactions", ""))
    legendary  = _ascii(enriched.get("legendary_actions", ""))
    mythic     = _ascii(enriched.get("mythic_actions", ""))
    lair       = _ascii(enriched.get("lair_actions", ""))
    notes      = _ascii(enriched.get("notes", ""))

    hp_mod = _hp_modifier(con, hp_die_count)
    die_opt = hp_die if hp_die in ("4","6","8","10","12","20") else "8"

    text_data: dict = {
        "security-token":     sec,
        "authenticity-token": auth,
        "Name":               name,
        "stat-block-type":    "1",
        "monster-type":       _TYPE_OPTIONS.get(creature_type.lower(), "11"),
        "size":               _SIZE_OPTIONS.get(size, "4"),
        "challenge-rating":   _CR_OPTIONS.get(str(cr), "5"),
        "armor-class":        str(ac),
        "passive-perception": str(passive_perc),
        "average-hit-points": str(hp),
        "hit-points-die-count": str(hp_die_count),
        "hit-points-die-value": die_opt,
        "hit-points-modifier": str(hp_mod),
        "languages-note":     languages,
        "special-traits-description-type":               "1",
        "special-traits-description-wysiwyg":            _html(traits),
        "special-traits-description":                    traits,
        "actions-description-type":                      "1",
        "actions-description-wysiwyg":                   _html(actions_text),
        "actions-description":                           actions_text,
        "bonus-actions-description-type":                "1",
        "bonus-actions-description-wysiwyg":             _html(bonus_acts),
        "bonus-actions-description":                     bonus_acts,
        "reactions-description-type":                    "1",
        "reactions-description-wysiwyg":                 _html(reactions),
        "reactions-description":                         reactions,
        "monster-characteristics-description-type":      "1",
        "monster-characteristics-description-wysiwyg":   _html(notes),
        "monster-characteristics-description":           notes,
        "legendary-actions-description-type":            "1",
        "mythic-actions-description-type":               "1",
        "lair-description-type":                         "1",
    }
    if legendary:
        text_data["is-legendary"] = "y"
        text_data["legendary-actions-description-wysiwyg"] = _html(legendary)
        text_data["legendary-actions-description"]          = legendary
    if mythic:
        text_data["is-mythic"] = "y"
        text_data["mythic-actions-description-wysiwyg"] = _html(mythic)
        text_data["mythic-actions-description"]          = mythic
    if lair:
        text_data["has-lair"] = "y"
        text_data["lair-description-wysiwyg"] = _html(lair)
        text_data["lair-description"]          = lair
        text_data["lair-challenge-rating"] = _CR_OPTIONS.get(str(cr), "5")

    # Ability scores via obfuscated names
    score_ids = {
        "field-strength": str(str_), "field-dexterity": str(dex),
        "field-constitution": str(con), "field-intelligence": str(int_),
        "field-wisdom": str(wis), "field-charisma": str(cha),
        "field-initiative-bonus": str(dex - 10),
    }
    for fid, val in score_ids.items():
        if fid in obf:
            text_data[obf[fid]] = val

    # Save bonuses from enriched
    saves = enriched.get("saves", {})
    save_map = {
        "strength": "field-strength-save-bonus", "dexterity": "field-dexterity-save-bonus",
        "constitution": "field-constitution-save-bonus", "intelligence": "field-intelligence-save-bonus",
        "wisdom": "field-wisdom-save-bonus", "charisma": "field-charisma-save-bonus",
    }
    for stat, fid in save_map.items():
        if stat in saves and fid in obf:
            text_data[obf[fid]] = str(saves[stat])

    file_data = {}
    if image_bytes:
        if "field-avatar" in obf:
            file_data[obf["field-avatar"]] = ("avatar.png", image_bytes, "image/png")
        if "field-large-avatar" in obf:
            file_data[obf["field-large-avatar"]] = ("large_avatar.png", image_bytes, "image/png")

    cookies = {"CobaltSession": SESSION}
    if alb:
        cookies["AWSALB"] = alb; cookies["AWSALBCORS"] = albcors

    async with httpx.AsyncClient(follow_redirects=False, timeout=30) as c:
        resp = await c.post(edit_url, data=text_data,
                            files=file_data if file_data else None,
                            headers=hdrs, cookies=cookies)
    if resp.status_code in (301,302,303,307,308):
        return True
    if resp.status_code == 200 and "ddb-homebrew-create-form" not in resp.text:
        return True
    return False


async def create_new(nc: dict, image_bytes: Optional[bytes]) -> Optional[str]:
    """Create a brand-new homebrew monster. Returns edit URL or None."""
    from src.ddb_homebrew import FORM_URL
    hdrs = {"Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124",
            "Origin": BASE_URL, "Referer": FORM_URL}
    sec, auth, alb, albcors, obf = await _get_csrf(FORM_URL)
    if not sec:
        return None

    cr            = nc.get("cr", "1")
    creature_type = nc.get("creature_type", "humanoid")
    size          = nc.get("size", "M")
    con           = nc.get("con", 10)
    dex           = nc.get("dex", 10)
    hp_die_count  = nc.get("hp_die_count", 2)
    hp_die        = nc.get("hp_die", "10")
    hp_mod        = _hp_modifier(con, hp_die_count)
    die_opt       = hp_die if hp_die in ("4","6","8","10","12","20") else "10"
    name          = _ascii(nc["name"])
    actions_text  = _ascii(nc.get("actions", ""))
    traits        = _ascii(nc.get("traits", ""))
    bonus_acts    = _ascii(nc.get("bonus_actions", ""))
    reactions     = _ascii(nc.get("reactions", ""))
    legendary     = _ascii(nc.get("legendary_actions", ""))
    mythic        = _ascii(nc.get("mythic_actions", ""))
    lair          = _ascii(nc.get("lair_actions", ""))
    notes         = _ascii(nc.get("notes", ""))
    languages     = _ascii(nc.get("languages", "Common"))

    text_data: dict = {
        "security-token":     sec,
        "authenticity-token": auth,
        "Name":               name,
        "stat-block-type":    "1",
        "monster-type":       _TYPE_OPTIONS.get(creature_type.lower(), "11"),
        "size":               _SIZE_OPTIONS.get(size, "5"),
        "challenge-rating":   _CR_OPTIONS.get(str(cr), "5"),
        "armor-class":        str(nc.get("ac", 17)),
        "passive-perception": str(nc.get("passive_perc", 14)),
        "average-hit-points": str(nc.get("hp", 100)),
        "hit-points-die-count": str(hp_die_count),
        "hit-points-die-value": die_opt,
        "hit-points-modifier": str(hp_mod),
        "languages-note":     languages,
        "special-traits-description-type":               "1",
        "special-traits-description-wysiwyg":            _html(traits),
        "special-traits-description":                    traits,
        "actions-description-type":                      "1",
        "actions-description-wysiwyg":                   _html(actions_text),
        "actions-description":                           actions_text,
        "bonus-actions-description-type":                "1",
        "bonus-actions-description-wysiwyg":             _html(bonus_acts),
        "bonus-actions-description":                     bonus_acts,
        "reactions-description-type":                    "1",
        "reactions-description-wysiwyg":                 _html(reactions),
        "reactions-description":                         reactions,
        "monster-characteristics-description-type":      "1",
        "monster-characteristics-description-wysiwyg":   _html(notes),
        "monster-characteristics-description":           notes,
        "legendary-actions-description-type":            "1",
        "mythic-actions-description-type":               "1",
        "lair-description-type":                         "1",
    }
    if legendary:
        text_data["is-legendary"] = "y"
        text_data["legendary-actions-description-wysiwyg"] = _html(legendary)
        text_data["legendary-actions-description"]          = legendary
    if mythic:
        text_data["is-mythic"] = "y"
        text_data["mythic-actions-description-wysiwyg"] = _html(mythic)
        text_data["mythic-actions-description"]          = mythic
    if lair:
        text_data["has-lair"] = "y"
        text_data["lair-description-wysiwyg"] = _html(lair)
        text_data["lair-description"]          = lair
        text_data["lair-challenge-rating"] = _CR_OPTIONS.get(str(cr), "5")

    score_ids = {
        "field-strength": str(nc.get("str_", 10)), "field-dexterity": str(dex),
        "field-constitution": str(con), "field-intelligence": str(nc.get("int_", 10)),
        "field-wisdom": str(nc.get("wis", 10)), "field-charisma": str(nc.get("cha", 10)),
        "field-initiative-bonus": str(dex - 10),
    }
    for fid, val in score_ids.items():
        if fid in obf:
            text_data[obf[fid]] = val

    saves = nc.get("saves", {})
    save_map = {
        "strength": "field-strength-save-bonus", "dexterity": "field-dexterity-save-bonus",
        "constitution": "field-constitution-save-bonus", "intelligence": "field-intelligence-save-bonus",
        "wisdom": "field-wisdom-save-bonus", "charisma": "field-charisma-save-bonus",
    }
    for stat, fid_name in save_map.items():
        if stat in saves and fid_name in obf:
            text_data[obf[fid_name]] = str(saves[stat])

    file_data = {}
    if image_bytes:
        if "field-avatar" in obf:
            file_data[obf["field-avatar"]] = ("avatar.png", image_bytes, "image/png")
        if "field-large-avatar" in obf:
            file_data[obf["field-large-avatar"]] = ("large_avatar.png", image_bytes, "image/png")

    cookies = {"CobaltSession": SESSION}
    if alb:
        cookies["AWSALB"] = alb; cookies["AWSALBCORS"] = albcors

    async with httpx.AsyncClient(follow_redirects=False, timeout=30) as c:
        resp = await c.post(FORM_URL, data=text_data,
                            files=file_data if file_data else None,
                            headers=hdrs, cookies=cookies)
    if resp.status_code in (301,302,303,307,308):
        loc = resp.headers.get("location", "")
        return f"{BASE_URL}{loc}" if loc.startswith("/") else loc
    return None


# ── Logging ───────────────────────────────────────────────────────────────────

log_entries: list[str] = []

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_entries.append(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log("EBP Content Update -- traits / reactions / legendary / lair / speeds")
    log(f"Creatures to update: {len(ENRICHED)}")
    log(f"New creatures to create: {len(NEW_CREATURES)}")

    ok_edit = 0; fail_edit = 0
    ok_speed = 0; fail_speed = 0

    # De-dup EDIT_SLUGS
    seen: set[str] = set()
    ordered = [n for n in EDIT_SLUGS if n not in seen and not seen.add(n)]  # type: ignore[func-returns-value]

    # ── Pass 1: Update existing 46 creatures ─────────────────────────────────
    for i, name in enumerate(ordered, 1):
        slug    = EDIT_SLUGS[name]
        base    = creature_by_name.get(name)
        enriched = ENRICHED.get(name)
        if not base or not enriched:
            log(f"[{i:02d}/{len(ordered)}] SKIP {name} -- missing data")
            continue

        monster_id = slug.split("-")[0]

        # Art: use cached file; re-generate if missing
        safe_name = name.replace(" ", "_").replace("/", "_").replace("'", "")
        art_path  = ART_DIR / f"{safe_name}.png"
        if art_path.exists():
            image_bytes = art_path.read_bytes()
        else:
            log(f"  Art missing for {name}, regenerating...")
            prompt = ART_PROMPTS.get(name, "")
            image_bytes = await generate_art(name, prompt) if prompt else None

        has_legendary = bool(enriched.get("legendary_actions", "").strip())
        has_mythic    = bool(enriched.get("mythic_actions", "").strip())
        has_lair      = bool(enriched.get("lair_actions", "").strip())
        flags = []
        if has_legendary: flags.append("legendary")
        if has_mythic:    flags.append("mythic")
        if has_lair:      flags.append("lair")
        flag_str = f" [{', '.join(flags)}]" if flags else ""

        log(f"[{i:02d}/{len(ordered)}] {name}{flag_str}")

        # Edit DDB entry
        ok = await edit_full(slug, base, enriched, image_bytes)
        if ok:
            log(f"  Edit OK")
            ok_edit += 1
        else:
            log(f"  Edit FAIL")
            fail_edit += 1

        # Add speeds
        speeds = enriched.get("speeds", [])
        for mv_type, speed_ft in speeds:
            s_ok = await add_speed(monster_id, mv_type, speed_ft)
            if s_ok:
                ok_speed += 1
            else:
                log(f"  Speed FAIL: type={mv_type} {speed_ft}ft")
                fail_speed += 1

        await asyncio.sleep(2)

    # ── Pass 2: Create 3 new creatures ───────────────────────────────────────
    log("")
    log("Creating new creatures...")
    new_art_prompts = {
        "EBP Ninyoldah": (
            "Majestic mature adult silver dragon with gleaming metallic scales, "
            "lightning crackling around it from embedded stone deposits, mountain cave lair, "
            "D&D monster token art, dramatic dark background, detailed digital illustration, "
            "cinematic lighting, 8k uhd, sharp focus, professional concept art"
        ),
        "EBP Stone Giant Chief Froddandan": (
            "Ancient stone giant chieftain with weathered granite skin, war-painted face, "
            "wielding a massive carved greatclub, mountain stronghold background, "
            "D&D monster token art, dramatic dark background, detailed digital illustration, "
            "8k uhd, sharp focus, professional concept art"
        ),
        "EBP Frummach": (
            "Stone giant scout, lean build compared to elder giants, cautious expression, "
            "holding a single throwing boulder, wilderness rocky terrain, "
            "D&D monster token art, dramatic dark background, detailed digital illustration, "
            "8k uhd, professional concept art"
        ),
    }

    for nc_name, nc in NEW_CREATURES.items():
        log(f"  Creating {nc_name}...")

        # Art
        safe = nc_name.replace(" ", "_").replace("/", "_").replace("'", "")
        art_path = ART_DIR / f"{safe}.png"
        if art_path.exists():
            img = art_path.read_bytes()
        else:
            prompt = new_art_prompts.get(nc_name, "")
            img = await generate_art(nc_name, prompt) if prompt else None
        if img:
            log(f"    Art OK ({len(img)//1024}KB)")
        else:
            log(f"    Art FAIL (skipping image)")

        # Create
        edit_url = await create_new(nc, img)
        if edit_url:
            log(f"    Created: {edit_url}")
            # Extract monster ID and add speeds
            m = re.search(r"/monsters/(\d+)-", edit_url)
            if m:
                monster_id = m.group(1)
                speeds = nc.get("speeds", [])
                for mv_type, speed_ft in speeds:
                    s_ok = await add_speed(monster_id, mv_type, speed_ft)
                    if not s_ok:
                        log(f"    Speed FAIL: type={mv_type} {speed_ft}ft")
        else:
            log(f"    Create FAIL")

        await asyncio.sleep(3)

    log("")
    log("=" * 60)
    log(f"Edits: {ok_edit} OK, {fail_edit} FAIL")
    log(f"Speeds: {ok_speed} OK, {fail_speed} FAIL")
    log(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
