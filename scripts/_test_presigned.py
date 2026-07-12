"""
One-shot test: pull all browser cookies via CDP, then call the presigned
S3 fields Server Action with the full cookie jar and print what comes back.
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

CDP_PORT   = 9223
GAME_ID    = "6923222"
USER_ID    = 123889713
ACTION_HASH = "70be8a5bf79ce7e9f33c3fca47aad1a3688b174bbe"
GAME_URL   = f"https://www.dndbeyond.com/games/{GAME_ID}"


async def get_browser_cookies() -> str:
    import websockets
    r = httpx.get(f"http://localhost:{CDP_PORT}/json", timeout=5)
    ws_url = next(
        (t["webSocketDebuggerUrl"] for t in r.json() if t.get("type") == "page"),
        None,
    )
    if not ws_url:
        return ""

    async with websockets.connect(ws_url, ping_interval=None) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies", "params": {}}))
        for _ in range(50):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("id") == 1:
                cookies = msg.get("result", {}).get("cookies", [])
                ddb = [c for c in cookies if "dndbeyond.com" in c.get("domain", "")]
                print(f"Found {len(ddb)} dndbeyond.com cookies")
                return "; ".join(f'{c["name"]}={c["value"]}' for c in ddb)
    return ""


async def main():
    cookie_str = await get_browser_cookies()
    if not cookie_str:
        print("ERROR: could not get cookies from Chrome")
        return

    payload = f'[true,"{GAME_ID}",{USER_ID}]'

    rstate_raw = (
        f'["",{{"children":[["campaignId","{GAME_ID}","d",null],'
        f'{{"children":["__PAGE__",{{}},null,null,0]}},'
        f'null,null,0]}},null,null,16]'
    )
    rstate = quote(rstate_raw, safe="")

    headers = {
        "User-Agent":              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Content-Type":            "text/plain;charset=UTF-8",
        "Accept":                  "text/x-component",
        "next-action":             ACTION_HASH,
        "next-router-state-tree":  rstate,
        "Referer":                 GAME_URL,
        "Origin":                  "https://www.dndbeyond.com",
        "Cookie":                  cookie_str,
    }

    print(f"\nPOST {GAME_URL}")
    print(f"Body: {payload}")
    print(f"next-action: {ACTION_HASH}")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
        resp = await c.post(GAME_URL, content=payload.encode(), headers=headers)

    print(f"\nStatus: {resp.status_code}")
    body = resp.text
    print(f"Response ({len(body)} bytes):")
    print(body[:800])

    match = re.search(r'\{[^{}]*"bucket"\s*:\s*"[^"]+"[^{}]*\}', body, re.DOTALL)
    if match:
        print("\n=== PRESIGNED FIELDS FOUND ===")
        print(match.group())
        try:
            fields = json.loads(match.group())
            print("\nParsed keys:", list(fields.keys()))
        except Exception:
            pass
    else:
        print("\nNo presigned fields in response.")
        print("This action hash does not return presigned S3 fields with this payload.")


if __name__ == "__main__":
    asyncio.run(main())
