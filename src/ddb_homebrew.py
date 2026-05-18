"""
ddb_homebrew.py — Push homebrew monsters to D&D Beyond via Chrome DevTools Protocol.

Uses a headless Chrome instance (opened during bot startup) with the user's
DDB session to automate the homebrew monster creation form.
Chrome's existing authenticated session handles all CSRF/obfuscation natively.

Config (.env):
  DDB_COBALT_SESSION   — CobaltSession cookie (from scripts/extract_ddb_session.py)
  DDB_HOMEBREW_ENABLED — set to false to disable (default: true if session set)

The module keeps a shared Chrome subprocess so monsters can be pushed
without relaunching Chrome for each one.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx

from src.log import logger

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SESSION  = os.getenv("DDB_COBALT_SESSION", "").strip()
ENABLED  = bool(SESSION) and os.getenv("DDB_HOMEBREW_ENABLED", "true").lower() not in ("0","false","no")
CDP_PORT = int(os.getenv("DDB_CDP_PORT", "9223"))   # separate port from extract_ddb_session.py
FORM_URL = "https://www.dndbeyond.com/homebrew/creations/create-monster/create"
CHROME_PATH = os.getenv("CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
PROFILE_DIR = str(Path(__file__).resolve().parent.parent / ".chrome_ddb_profile")

# ---------------------------------------------------------------------------
# Chrome lifecycle — one shared subprocess
# ---------------------------------------------------------------------------

_chrome_proc: Optional[subprocess.Popen] = None
_chrome_lock = asyncio.Lock()


def _chrome_alive() -> bool:
    try:
        r = httpx.get(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _launch_chrome() -> bool:
    global _chrome_proc
    if _chrome_alive():
        return True
    if not Path(CHROME_PATH).exists():
        logger.warning(f"[DDB_HB] Chrome not found at {CHROME_PATH}")
        return False
    try:
        _chrome_proc = subprocess.Popen(
            [CHROME_PATH,
             f"--remote-debugging-port={CDP_PORT}",
             f"--user-data-dir={PROFILE_DIR}",
             "--no-first-run",
             "--no-default-browser-check",
             "--headless=new",          # headless — no window
             FORM_URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(15):
            time.sleep(1)
            if _chrome_alive():
                logger.info("[DDB_HB] Chrome started (headless)")
                return True
        return False
    except Exception as exc:
        logger.warning(f"[DDB_HB] Chrome launch failed: {exc}")
        return False


async def ensure_chrome() -> bool:
    async with _chrome_lock:
        if await asyncio.to_thread(_chrome_alive):
            return True
        return await asyncio.to_thread(_launch_chrome)


# ---------------------------------------------------------------------------
# CDP helpers
# ---------------------------------------------------------------------------

async def _cdp(ws, method: str, params: dict = None, id_: int = 1) -> dict:
    import websockets as _ws
    await ws.send(json.dumps({"id": id_, "method": method, "params": params or {}}))
    for _ in range(60):
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if msg.get("id") == id_:
            return msg.get("result", {})
    return {}


async def _get_page_ws_url() -> Optional[str]:
    try:
        r = await asyncio.to_thread(httpx.get, f"http://localhost:{CDP_PORT}/json", timeout=5)
        targets = r.json()
        for t in targets:
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Fill + submit form via CDP
# ---------------------------------------------------------------------------

_FILL_JS_TEMPLATE = """
(function() {{
    try {{
        // Name
        var nameF = document.getElementById('field-name') ||
                    document.querySelector('input[name="Name"]') ||
                    document.querySelectorAll('input[type="text"]')[0];
        if (nameF) {{
            nameF.value = {name_json};
            nameF.dispatchEvent(new Event('input', {{bubbles:true}}));
        }}

        // Selects
        function setSelect(name, val) {{
            var s = document.querySelector('select[name="' + name + '"]');
            if (s) {{ s.value = val; s.dispatchEvent(new Event('change', {{bubbles:true}})); }}
        }}
        setSelect('stat-block-type', '1');   // D&D 2024 (5.5e)
        setSelect('monster-type',    {type_val_json});
        setSelect('size',            {size_val_json});
        setSelect('challenge-rating',{cr_val_json});
        setSelect('hit-points-die-value', {die_json});

        // Text inputs
        function setInput(name, val) {{
            var el = document.querySelector('input[name="' + name + '"]');
            if (el) {{ el.value = val; el.dispatchEvent(new Event('input', {{bubbles:true}})); }}
        }}
        setInput('armor-class',       '{ac}');
        setInput('average-hit-points','{hp}');
        setInput('hit-points-die-count','{hp_count}');
        setInput('passive-perception', '{pp}');
        setInput('languages-note',     {languages_json});

        // Ability scores by stable element ID
        var scores = {{
            'field-strength':    '{str_}',
            'field-dexterity':   '{dex}',
            'field-constitution':'{con}',
            'field-intelligence':'{int_}',
            'field-wisdom':      '{wis}',
            'field-charisma':    '{cha}'
        }};
        var filled = [];
        for (var id in scores) {{
            var el = document.getElementById(id);
            if (el) {{
                el.value = scores[id];
                el.dispatchEvent(new Event('input', {{bubbles:true}}));
                el.dispatchEvent(new Event('change', {{bubbles:true}}));
                filled.push(id.replace('field-',''));
            }}
        }}

        // Actions description
        var actEl = document.querySelector('textarea[name="actions-description"]');
        if (actEl) {{ actEl.value = {actions_json}; actEl.dispatchEvent(new Event('input',{{bubbles:true}})); }}

        // Monster characteristics (lore/notes)
        var loreEl = document.querySelector('textarea[name="monster-characteristics-description"]');
        if (loreEl) {{ loreEl.value = {notes_json}; loreEl.dispatchEvent(new Event('input',{{bubbles:true}})); }}

        return 'OK:' + filled.join(',');
    }} catch(e) {{ return 'ERR:' + e.message; }}
}})()
"""

_SUBMIT_JS = """
(function() {
    var form = document.querySelector('form[action*="create-monster"]');
    if (!form) {
        var forms = document.querySelectorAll('form');
        for (var f of forms) { if (f.action && f.action.includes('create')) { form = f; break; } }
    }
    if (form) { form.submit(); return 'submitted:' + form.action; }
    var btn = document.querySelector('input[type="submit"], button[type="submit"]');
    if (btn) { btn.click(); return 'clicked submit button'; }
    return 'no form found';
})()
"""

_CR_OPTIONS = {
    "0": "1", "1/8": "2", "1/4": "3", "1/2": "4",
    **{str(i): str(i + 4) for i in range(1, 31)},
}
_TYPE_OPTIONS = {
    "aberration":"1","beast":"2","celestial":"3","construct":"4",
    "dragon":"6","elemental":"7","fey":"8","fiend":"9",
    "giant":"10","humanoid":"11","monstrosity":"13","ooze":"14",
    "plant":"15","undead":"16",
}
_SIZE_OPTIONS = {
    "T":"2","Tiny":"2","S":"3","Small":"3","M":"4","Medium":"4",
    "L":"5","Large":"5","H":"6","Huge":"6","G":"7","Gargantuan":"7",
}
_HP_DIE_OPTIONS = {"4", "6", "8", "10", "12", "20"}


def _normalize_hp_die(hp_die: object) -> str:
    die = str(hp_die or "").strip().lower()
    if die.startswith("d"):
        die = die[1:]
    if die in _HP_DIE_OPTIONS:
        return die
    logger.warning(f"[DDB_HB] Invalid hp_die={hp_die!r}; defaulting to d8")
    return "8"


async def push_monster(
    name:          str,
    cr:            str  = "1",
    creature_type: str  = "humanoid",
    size:          str  = "M",
    ac:            int  = 12,
    hp:            int  = 15,
    hp_die:        str  = "8",
    hp_die_count:  int  = 2,
    str_:          int  = 10,
    dex:           int  = 10,
    con:           int  = 10,
    int_:          int  = 10,
    wis:           int  = 10,
    cha:           int  = 10,
    passive_perc:  int  = 10,
    languages:     str  = "Common",
    actions:       str  = "",
    notes:         str  = "",
) -> Optional[str]:
    """
    Create a DDB homebrew monster using Chrome CDP.
    Returns the monster's DDB URL or None on failure.
    """
    if not ENABLED:
        logger.debug("[DDB_HB] Disabled — set DDB_COBALT_SESSION to enable")
        return None

    if not await ensure_chrome():
        logger.warning("[DDB_HB] Chrome unavailable")
        return None

    ws_url = await _get_page_ws_url()
    if not ws_url:
        logger.warning("[DDB_HB] No CDP page target")
        return None

    try:
        import websockets
    except ImportError:
        logger.warning("[DDB_HB] websockets package missing — run: pip install websockets")
        return None

    cr_option   = _CR_OPTIONS.get(str(cr), "5")
    type_option = _TYPE_OPTIONS.get(creature_type.lower(), "11")
    size_option = _SIZE_OPTIONS.get(size, "4")
    die_option  = _normalize_hp_die(hp_die)

    fill_js = _FILL_JS_TEMPLATE.format(
        name_json      = json.dumps(name),
        type_val_json  = json.dumps(type_option),
        size_val_json  = json.dumps(size_option),
        cr_val_json    = json.dumps(cr_option),
        die_json       = json.dumps(die_option),
        ac             = ac, hp = hp, hp_count = hp_die_count, pp = passive_perc,
        languages_json = json.dumps(languages),
        str_           = str_, dex = dex, con = con, int_ = int_, wis = wis, cha = cha,
        actions_json   = json.dumps(actions),
        notes_json     = json.dumps(notes),
    )

    logger.info(f"[DDB_HB] Creating homebrew: {name!r} CR {cr}")

    try:
        async with websockets.connect(ws_url, max_size=10_000_000, ping_interval=None) as ws:
            # Inject session cookie before navigating so Chrome is authenticated
            if SESSION:
                await _cdp(ws, "Network.enable", id_=20)
                await _cdp(ws, "Network.setCookie", {
                    "name": "CobaltSession",
                    "value": SESSION,
                    "domain": ".dndbeyond.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                }, id_=21)

            # Navigate to a fresh form
            await _cdp(ws, "Page.navigate", {"url": FORM_URL}, id_=1)
            await asyncio.sleep(4)   # wait for page load

            # Fill the form
            fill_result = await _cdp(ws, "Runtime.evaluate", {"expression": fill_js}, id_=10)
            fill_val    = fill_result.get("result", {}).get("value", "")
            logger.debug(f"[DDB_HB] Fill: {fill_val}")

            if fill_val.startswith("ERR"):
                logger.warning(f"[DDB_HB] Fill error: {fill_val}")
                return None

            await asyncio.sleep(0.5)

            # Enable network monitoring before submit
            await _cdp(ws, "Network.enable", id_=11)

            # Submit
            sub_result  = await _cdp(ws, "Runtime.evaluate", {"expression": _SUBMIT_JS}, id_=12)
            logger.debug(f"[DDB_HB] Submit: {sub_result.get('result',{}).get('value','')}")

            # Wait for redirect to the created monster's page
            for _ in range(30):
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                    if msg.get("method") == "Network.responseReceived":
                        resp_url = msg.get("params", {}).get("response", {}).get("url", "")
                        status   = msg.get("params", {}).get("response", {}).get("status", 0)
                        if "dndbeyond.com/homebrew/creations/monsters/" in resp_url:
                            logger.info(f"[DDB_HB] Created: {resp_url}")
                            return resp_url
                except asyncio.TimeoutError:
                    pass

    except Exception as exc:
        logger.warning(f"[DDB_HB] CDP error: {exc}")

    return None


async def push_monster_http(
    name:          str,
    cr:            str  = "1",
    creature_type: str  = "humanoid",
    size:          str  = "M",
    ac:            int  = 12,
    hp:            int  = 15,
    hp_die:        str  = "8",
    hp_die_count:  int  = 2,
    str_:          int  = 10,
    dex:           int  = 10,
    con:           int  = 10,
    int_:          int  = 10,
    wis:           int  = 10,
    cha:           int  = 10,
    passive_perc:  int  = 10,
    languages:     str  = "Common",
    actions:       str  = "",
    notes:         str  = "",
) -> Optional[str]:
    """
    Create a DDB homebrew monster via direct HTTP POST (more reliable than CDP).
    Returns the monster's DDB edit URL or None on failure.

    Key technique: use separate httpx clients for GET and POST, manually
    carrying the AWSALB sticky-session cookie so both requests hit the same
    AWS backend server (which holds the obfuscated field name session state).
    """
    if not ENABLED:
        return None

    # DDB's form rejects em/en dashes — replace with ASCII equivalents
    def _ascii(s: str) -> str:
        return s.replace("—", "--").replace("–", "-")

    name      = _ascii(name)
    languages = _ascii(languages)
    actions   = _ascii(actions)
    notes     = _ascii(notes)

    cr_option   = _CR_OPTIONS.get(str(cr), "5")
    type_option = _TYPE_OPTIONS.get(creature_type.lower(), "11")
    size_option = _SIZE_OPTIONS.get(size, "4")
    die_option  = _normalize_hp_die(hp_die)

    _HDRS = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124",
        "Origin": "https://www.dndbeyond.com",
        "Referer": FORM_URL,
    }

    try:
        # ── Step 1: GET the form to collect CSRF tokens, obfuscated field names,
        #           and the AWSALB sticky-session cookie.
        async with httpx.AsyncClient(follow_redirects=False, timeout=20) as getter:
            r = await getter.get(FORM_URL, headers=_HDRS,
                                 cookies={"CobaltSession": SESSION})
            if r.status_code != 200:
                logger.warning(f"[DDB_HB_HTTP] GET {r.status_code} for {name!r}")
                return None
            awsalb     = r.cookies.get("AWSALB", "")
            awsalbcors = r.cookies.get("AWSALBCORS", "")
            html       = r.text

        def _hidden(field):
            m = re.search(r'name="' + re.escape(field) + r'"[^>]*value="([^"]*?)"', html)
            if not m:
                m = re.search(r'value="([^"]*?)"[^>]*name="' + re.escape(field) + r'"', html)
            return m.group(1) if m else ""

        # Build obfuscated field map: element-id → obfuscated name
        obf = {}
        for m in re.finditer(r"<input[^>]+>", html, re.IGNORECASE):
            inp = m.group()
            nm  = re.search(r'name="(f[a-f0-9]{30,})"', inp)
            idm = re.search(r'id="([^"]+)"', inp)
            if nm and idm:
                obf[idm.group(1)] = nm.group(1)

        # ── Step 2: Build form data
        form_data: dict = {
            "security-token":    _hidden("security-token"),
            "authenticity-token": _hidden("authenticity-token"),
            "Name":              name,
            "stat-block-type":   "1",          # D&D 2024
            "monster-type":      type_option,
            "size":              size_option,
            "challenge-rating":  cr_option,
            "armor-class":       str(ac),
            "passive-perception": str(passive_perc),
            "average-hit-points": str(hp),
            "hit-points-die-count": str(hp_die_count),
            "hit-points-die-value": die_option,
            "hit-points-modifier": "",
            "languages-note":    languages,
            "special-traits-description-type": "1",
            "actions-description-type":        "1",
            "bonus-actions-description-type":  "1",
            "reactions-description-type":      "1",
            "monster-characteristics-description-type": "1",
            "legendary-actions-description-type": "1",
            "mythic-actions-description-type": "1",
            "lair-description-type":           "1",
            "actions-description":             actions,
            "monster-characteristics-description": notes,
        }
        # Ability scores via obfuscated field names
        score_ids = {
            "field-strength": str(str_), "field-dexterity": str(dex),
            "field-constitution": str(con), "field-intelligence": str(int_),
            "field-wisdom": str(wis), "field-charisma": str(cha),
            "field-initiative-bonus": str(dex - 10),   # initiative = DEX mod
        }
        for fid, val in score_ids.items():
            if fid in obf:
                form_data[obf[fid]] = val

        # ── Step 3: POST with the sticky session cookie from the GET
        post_cookies = {"CobaltSession": SESSION}
        if awsalb:
            post_cookies["AWSALB"]     = awsalb
            post_cookies["AWSALBCORS"] = awsalbcors

        logger.info(f"[DDB_HB_HTTP] Creating homebrew: {name!r} CR {cr}")

        async with httpx.AsyncClient(follow_redirects=False, timeout=20) as poster:
            resp = await poster.post(
                FORM_URL, data=form_data,
                headers={**_HDRS, "Content-Type": "application/x-www-form-urlencoded"},
                cookies=post_cookies,
            )

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            url = f"https://www.dndbeyond.com{location}" if location.startswith("/") else location
            logger.info(f"[DDB_HB_HTTP] Created: {url}")
            return url

        # Extract DDB validation errors from the response HTML
        import re as _re
        err_hits = _re.findall(r'(?:class="[^"]*error[^"]*"|error[^<]{0,60})<[^>]*>([^<]{1,120})', resp.text, _re.IGNORECASE)
        if not err_hits:
            # Fallback: grab any visible error-class text
            err_hits = _re.findall(r'alert[^>]*>([^<]{1,120})', resp.text, _re.IGNORECASE)
        logger.warning(f"[DDB_HB_HTTP] POST {resp.status_code} for {name!r} — no redirect. Errors: {err_hits[:5]}")
        return None

    except Exception as exc:
        logger.warning(f"[DDB_HB_HTTP] Error for {name!r}: {exc}")
        return None


async def push_mission_enemy(enemy: dict, cr_val: str = "", statblock: dict = None) -> Optional[str]:
    """Push a mission enemy dict as a DDB homebrew monster. Returns URL or None.

    statblock — optional pre-generated stat block dict with keys:
        str_, dex, con, int_, wis, cha, ac, hp, hp_die, hp_die_count,
        passive_perc, languages, actions, notes, creature_type, size
    """
    name  = enemy.get("name", "Unknown")
    cr    = cr_val or enemy.get("cr", "1")
    try:
        cr_num = float(cr.replace("1/8","0.125").replace("1/4","0.25").replace("1/2","0.5"))
    except Exception:
        cr_num = 1.0

    avg_hp = max(5, int(cr_num * 13 + 7))
    avg_ac = max(10, min(18, int(cr_num + 12)))
    sb = statblock or {}

    return await push_monster(
        name          = name,
        cr            = str(cr),
        creature_type = sb.get("creature_type", "humanoid"),
        size          = sb.get("size", "M"),
        ac            = sb.get("ac", avg_ac),
        hp            = sb.get("hp", avg_hp),
        hp_die        = sb.get("hp_die", "8"),
        hp_die_count  = sb.get("hp_die_count", max(1, int(avg_hp / 5))),
        str_          = sb.get("str_", min(20, max(8, int(cr_num * 1.5 + 10)))),
        dex           = sb.get("dex", 12),
        con           = sb.get("con", min(20, max(8, int(cr_num + 10)))),
        int_          = sb.get("int_", 10),
        wis           = sb.get("wis", 10),
        cha           = sb.get("cha", 10),
        passive_perc  = sb.get("passive_perc", 10 + (int(cr_num) // 2)),
        languages     = sb.get("languages", "Common"),
        actions       = sb.get("actions", ""),
        notes         = sb.get("notes", enemy.get("notes", f"Campaign creature. CR {cr}.")),
    )


def shutdown_chrome() -> None:
    """Call on bot shutdown."""
    global _chrome_proc
    if _chrome_proc:
        try:
            _chrome_proc.terminate()
        except Exception:
            pass
        _chrome_proc = None
