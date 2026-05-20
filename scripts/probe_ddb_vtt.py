"""
probe_ddb_vtt.py — Discover the DDB VTT (media.dndbeyond.com/games) map upload API.

Uses Chrome CDP (the same headless Chrome we use for monster creation) to:
1. Navigate to your DDB VTT campaign
2. Click through the map upload UI
3. Capture all network requests made during the upload
4. Print the upload endpoint + form fields

Run this ONCE after maps are generated, then fill in _upload_to_ddb_vtt() in
scripts/seed_battle_maps.py with the discovered endpoint.

Prerequisites:
  - Chrome must be running (started by the bot or via enrich_creatures_ddb.py run)
  - Your DDB session must be active in the Chrome profile
  - Have at least one campaign in your DDB account with VTT access

Usage:
  python scripts/probe_ddb_vtt.py
  python scripts/probe_ddb_vtt.py --campaign-url https://media.dndbeyond.com/games/12345
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx

CDP_PORT = int(os.getenv("DDB_CDP_PORT", "9223"))
CHROME_PATH = os.getenv("CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
PROFILE_DIR = str(ROOT / ".chrome_ddb_profile")
REPORT_PATH = ROOT / "logs" / "ddb_vtt_probe.json"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _chrome_alive() -> bool:
    try:
        r = httpx.get(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _launch_chrome(target_url: str) -> bool:
    import subprocess, time
    log(f"Launching Chrome to {target_url}")
    try:
        subprocess.Popen(
            [CHROME_PATH,
             f"--remote-debugging-port={CDP_PORT}",
             f"--user-data-dir={PROFILE_DIR}",
             "--no-first-run", "--no-default-browser-check",
             target_url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(15):
            time.sleep(1)
            if _chrome_alive():
                return True
        return False
    except Exception as exc:
        log(f"Chrome launch failed: {exc}")
        return False


async def _get_ws_url() -> str | None:
    try:
        r = await asyncio.to_thread(httpx.get, f"http://localhost:{CDP_PORT}/json", timeout=5)
        for t in r.json():
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
    except Exception:
        pass
    return None


async def probe(campaign_url: str = "https://media.dndbeyond.com/games") -> dict:
    """
    Navigate Chrome to the DDB VTT and capture API calls.
    Returns a dict of discovered endpoints + upload form structure.
    """
    import websockets

    ws_url = await _get_ws_url()
    if not ws_url:
        log("No Chrome CDP page found")
        return {}

    log(f"Connecting to Chrome CDP: {ws_url[:60]}…")
    captured_requests: list[dict] = []
    captured_responses: list[dict] = []

    async with websockets.connect(ws_url, max_size=20_000_000, ping_interval=None) as ws:
        async def cdp(method: str, params: dict = None, id_: int = 1) -> dict:
            await ws.send(json.dumps({"id": id_, "method": method, "params": params or {}}))
            for _ in range(120):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get("id") == id_:
                    return msg.get("result", {})
            return {}

        # Enable network monitoring
        await cdp("Network.enable", id_=10)
        log(f"Navigating to {campaign_url}")
        await cdp("Page.navigate", {"url": campaign_url}, id_=1)

        # Collect network events for 15 seconds while page loads
        log("Listening for API calls (15 seconds)…")
        deadline = asyncio.get_event_loop().time() + 15
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
                method = msg.get("method", "")
                params = msg.get("params", {})

                if method == "Network.requestWillBeSent":
                    req = params.get("request", {})
                    url = req.get("url", "")
                    http_method = req.get("method", "GET")
                    post_data = req.get("postData", "")
                    headers = req.get("headers", {})
                    # Capture API/game/map related calls
                    if any(k in url.lower() for k in ("api", "game", "map", "asset", "media", "upload", "campaign")):
                        entry = {
                            "method": http_method,
                            "url": url,
                            "content_type": headers.get("Content-Type", ""),
                            "post_data_preview": post_data[:500] if post_data else "",
                        }
                        captured_requests.append(entry)
                        log(f"  REQ: {http_method} {url[:100]}")

                elif method == "Network.responseReceived":
                    resp = params.get("response", {})
                    url = resp.get("url", "")
                    status = resp.get("status", 0)
                    mime = resp.get("mimeType", "")
                    if any(k in url.lower() for k in ("api", "game", "map", "asset", "upload", "campaign")):
                        captured_responses.append({"url": url, "status": status, "mime": mime})

            except asyncio.TimeoutError:
                pass
            except Exception:
                pass

        # Get page text to find campaign IDs and upload buttons
        log("Extracting page structure…")
        result = await cdp("Runtime.evaluate", {
            "expression": """JSON.stringify({
                url: location.href,
                title: document.title,
                gameLinks: Array.from(document.querySelectorAll('a[href*=game]')).slice(0,5).map(a=>({href:a.href,text:a.innerText.trim().slice(0,40)})),
                uploadInputs: Array.from(document.querySelectorAll('input[type=file]')).map(i=>({accept:i.accept,name:i.name,id:i.id})),
                uploadForms: Array.from(document.querySelectorAll('form')).slice(0,5).map(f=>({action:f.action,method:f.method,enctype:f.enctype})),
                buttons: Array.from(document.querySelectorAll('button')).filter(b=>b.innerText.toLowerCase().includes('map')||b.innerText.toLowerCase().includes('upload')).slice(0,10).map(b=>b.innerText.trim().slice(0,40))
            })"""
        }, id_=20)
        page_info = {}
        try:
            page_info = json.loads(result.get("result", {}).get("value", "{}"))
        except Exception:
            pass

    report = {
        "probed_at": datetime.now().isoformat(),
        "target_url": campaign_url,
        "final_url": page_info.get("url", ""),
        "page_title": page_info.get("title", ""),
        "game_links": page_info.get("gameLinks", []),
        "upload_inputs": page_info.get("uploadInputs", []),
        "upload_forms": page_info.get("uploadForms", []),
        "map_buttons": page_info.get("buttons", []),
        "api_requests": captured_requests,
        "api_responses": captured_responses,
    }

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"\nReport saved: {REPORT_PATH}")

    log("\n=== SUMMARY ===")
    log(f"Final URL: {report['final_url']}")
    log(f"Title: {report['page_title']}")
    log(f"Upload inputs: {report['upload_inputs']}")
    log(f"Upload forms: {report['upload_forms']}")
    log(f"Map buttons: {report['map_buttons']}")
    log(f"API requests captured: {len(report['api_requests'])}")

    upload_hits = [r for r in captured_requests if any(k in r["url"].lower() for k in ("upload", "asset", "media"))]
    if upload_hits:
        log("\n=== UPLOAD ENDPOINTS FOUND ===")
        for h in upload_hits:
            log(f"  {h['method']} {h['url']}")
            if h["post_data_preview"]:
                log(f"    Body: {h['post_data_preview'][:200]}")
    else:
        log("\nNo upload endpoints captured yet.")
        log("To capture upload traffic: navigate Chrome manually to the DDB VTT,")
        log("upload a test map file, then re-run this probe.")

    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Probe DDB VTT to discover map upload API.")
    p.add_argument("--campaign-url", default="https://media.dndbeyond.com/games",
                   help="DDB VTT URL to navigate to (use your specific campaign URL for better results).")
    return p.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if not _chrome_alive():
        if not _launch_chrome(args.campaign_url):
            log("Could not start Chrome — ensure DDB_CDP_PORT and CHROME_PATH are set")
            return
    else:
        log("Chrome already running")

    await probe(args.campaign_url)


if __name__ == "__main__":
    asyncio.run(main())
