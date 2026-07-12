"""
probe_ddb_vtt.py — Capture the DDB VTT map-upload API calls.

HOW IT WORKS — THE FULL PICTURE
=================================

Chrome DevTools Protocol (CDP)
--------------------------------
When Chrome starts with --remote-debugging-port=9223, it opens a WebSocket
server on that port.  This is the exact same channel the Chrome DevTools panel
uses internally — every network tab, every console call, every DOM inspection
you've ever done in DevTools goes through CDP.

We connect to that WebSocket as a "debugger client" and send JSON messages like:

    {"id": 1, "method": "Network.enable", "params": {}}

Chrome responds with:

    {"id": 1, "result": {}}

…and then starts pushing unsolicited "event" messages whenever something
network-related happens:

    {"method": "Network.requestWillBeSent", "params": { "requestId": "...", "request": {...} }}

So the whole thing is a bidirectional JSON-over-WebSocket conversation.

TWO CAPTURE LAYERS
-------------------
The DDB VTT is a Next.js app.  Next.js can make fetch() calls from inside
React Server Components (which run on the server) or Client Components (which
run in the browser).  The map-upload "Server Action" is triggered from a Client
Component, so the actual HTTP request leaves the user's browser — which means
we CAN capture it.

But "can" depends on timing.  CDP's Network domain is reliable for most requests,
but there's a small race: if a request fires in the first few milliseconds before
our "Network.enable" command reaches Chrome, we miss it.  To be safe we add a
second capture layer: we inject JavaScript into the page that wraps window.fetch
and XMLHttpRequest before navigation begins, so any request the page makes is
recorded in a JS-side array we can read back later.

LAYER 1 — CDP Network Events
  "Network.enable" arms Chrome to emit requestWillBeSent for every outgoing
  request.  We read those events off the WebSocket in a background task.

LAYER 2 — JS fetch/XHR monkey-patch
  We inject code via Runtime.evaluate that replaces window.fetch and
  XMLHttpRequest.open with wrappers that log URL + method + POST body into
  window.__capturedRequests before forwarding to the real implementation.
  At the end of the wait window we call Runtime.evaluate again to read that
  array back out.

THE UPLOAD FLOW WE'RE HUNTING
-------------------------------
DDB's map upload is a Next.js Server Action.  That means:

  Request 1 — POST to https://www.dndbeyond.com/games/<campaignId>
    Headers include:
      next-action: <40-char hex hash>   ← identifies which server function to call
      next-router-state-tree: <encoded JSON>
      Content-Type: text/plain;charset=UTF-8
    Body is a JSON array:  [true, "<campaignId>", <userId>]
    Response is RSC (React Server Component) wire format — looks like binary
    garbage but hidden inside is a JSON object with presigned S3 fields:
      { bucket, key, Policy, X-Amz-Credential, X-Amz-Signature, ... }

  Request 2 — POST to https://<bucket>.s3.amazonaws.com/
    multipart/form-data containing those presigned fields + the image file.
    S3 returns 204 No Content on success.

Once we have those two requests we have everything we need to replicate the
upload from Python without touching Chrome at all.

USAGE
------
  python scripts/probe_ddb_vtt.py
  python scripts/probe_ddb_vtt.py --campaign-id 6923222
  python scripts/probe_ddb_vtt.py --campaign-id 6923222 --wait 120

Prerequisites:
  - Chrome must already be running with remote debugging enabled, OR this
    script will launch it for you.
  - Your DDB session must be active in the Chrome profile (you should be
    logged in to dndbeyond.com).
  - pip install websockets httpx
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

CDP_PORT    = int(os.getenv("DDB_CDP_PORT", "9223"))
CHROME_PATH = os.getenv("CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
PROFILE_DIR = str(ROOT / ".chrome_ddb_profile")
REPORT_PATH = ROOT / "logs" / "ddb_vtt_probe.json"

DEFAULT_CAMPAIGN_ID = os.getenv("DDB_GAME_ID", "6923222")
DDB_GAMES_URL = "https://www.dndbeyond.com/games"


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Chrome helpers
# ---------------------------------------------------------------------------

def chrome_is_alive() -> bool:
    """Return True if Chrome is already running on CDP_PORT."""
    try:
        r = httpx.get(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def launch_chrome(target_url: str) -> bool:
    """
    Start Chrome with remote debugging enabled.

    --remote-debugging-port tells Chrome to open a CDP WebSocket server.
    --user-data-dir points at our dedicated DDB profile so session cookies
    carry over from previous runs (you stay logged in).
    --no-first-run / --no-default-browser-check suppress startup dialogs.
    """
    log(f"Launching Chrome → {target_url}")
    try:
        subprocess.Popen(
            [
                CHROME_PATH,
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={PROFILE_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
                target_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Poll until the CDP server responds (up to 15 s)
        for _ in range(15):
            time.sleep(1)
            if chrome_is_alive():
                log("Chrome is up.")
                return True
        log("Chrome did not start in time.")
        return False
    except Exception as exc:
        log(f"Chrome launch failed: {exc}")
        return False


def get_all_ws_urls(campaign_id: str) -> tuple[list[str], list[str]]:
    """
    Return (all_ws_urls, navigate_urls).

    all_ws_urls  — WebSocket debugger URL for every open page tab.
    navigate_urls — parallel list: the URL to navigate to, or "" to skip.

    If a tab is already on the games page for this campaign we skip
    navigation — navigating a live authenticated session can reset auth state.
    If a tab is on a different page we navigate it to the campaign URL.
    Only the FIRST tab gets a navigation target; the rest just listen.
    """
    campaign_url  = f"{DDB_GAMES_URL}/{campaign_id}"
    games_pattern = f"/games/{campaign_id}"

    try:
        r = httpx.get(f"http://localhost:{CDP_PORT}/json", timeout=5)
        ws_urls   = []
        nav_urls  = []
        navigated = False
        for target in r.json():
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                tab_url = target.get("url", "")
                ws_urls.append(target["webSocketDebuggerUrl"])
                already_there = games_pattern in tab_url
                if already_there and not navigated:
                    # Already on games page — pass the URL so the watcher knows
                    # to do Page.reload() instead of Page.navigate()
                    nav_urls.append(campaign_url)
                    navigated = True
                    log(f"  Tab (already on games page — will reload): {tab_url[:80]}")
                elif not navigated:
                    nav_urls.append(campaign_url)
                    navigated = True
                    log(f"  Tab (will navigate): {tab_url[:80]}")
                else:
                    nav_urls.append("")
                    log(f"  Tab (listening): {tab_url[:80]}")
        return ws_urls, nav_urls
    except Exception:
        pass
    return [], []


# ---------------------------------------------------------------------------
# JS injected into the page — fetch/XHR monkey-patch
# ---------------------------------------------------------------------------

# This JavaScript replaces window.fetch and XMLHttpRequest.prototype.open
# with thin wrappers.  Every outgoing request is logged into
# window.__capturedRequests before the real call happens.
#
# We read window.__capturedRequests back via Runtime.evaluate at the end of
# the wait window.  This is our safety net against any requests that fire
# before CDP's Network.enable acknowledgement arrives.

INTERCEPT_JS = """
(function() {
    if (window.__capturedRequests) return;  // already injected
    window.__capturedRequests = [];

    // --- wrap fetch() ---
    const _realFetch = window.fetch.bind(window);
    window.fetch = function(input, init) {
        const url    = (typeof input === 'string') ? input : (input.url || String(input));
        const method = (init && init.method) ? init.method.toUpperCase() : 'GET';
        let body = '';
        try { body = (init && init.body) ? String(init.body).slice(0, 2000) : ''; } catch(e) {}
        let headers = {};
        try {
            if (init && init.headers) {
                if (init.headers instanceof Headers) {
                    init.headers.forEach((v, k) => { headers[k] = v; });
                } else {
                    headers = Object.assign({}, init.headers);
                }
            }
        } catch(e) {}
        window.__capturedRequests.push({
            source:  'fetch',
            method:  method,
            url:     url,
            headers: headers,
            body:    body,
            ts:      new Date().toISOString(),
        });
        return _realFetch(input, init);
    };

    // --- wrap XMLHttpRequest ---
    const _realOpen = XMLHttpRequest.prototype.open;
    const _realSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
        this.__xhrMethod = method ? method.toUpperCase() : 'GET';
        this.__xhrUrl    = url || '';
        return _realOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
        let bodyStr = '';
        try { bodyStr = body ? String(body).slice(0, 2000) : ''; } catch(e) {}
        window.__capturedRequests.push({
            source: 'xhr',
            method: this.__xhrMethod || 'GET',
            url:    this.__xhrUrl    || '',
            body:   bodyStr,
            ts:     new Date().toISOString(),
        });
        return _realSend.apply(this, arguments);
    };

    console.log('[probe] fetch/XHR intercept armed');
})();
"""


# ---------------------------------------------------------------------------
# CDP session helpers
# ---------------------------------------------------------------------------

async def cdp_send(ws, method: str, params: dict | None = None, id_: int = 1) -> dict:
    """
    Send one CDP command and wait for its reply.

    CDP messages look like:
      {"id": 1, "method": "Network.enable", "params": {}}

    The response echoes the same id:
      {"id": 1, "result": {}}

    Any messages that arrive in between (with no id, or a different id) are
    events — we ignore them here and let the background event reader handle them.
    """
    await ws.send(json.dumps({"id": id_, "method": method, "params": params or {}}))
    # Spin reading messages until we see our reply
    for _ in range(200):
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        msg = json.loads(raw)
        if msg.get("id") == id_:
            return msg.get("result", {})
    return {}


# ---------------------------------------------------------------------------
# Main probe coroutine
# ---------------------------------------------------------------------------

async def _watch_one_tab(
    ws_url: str,
    cdp_requests: list[dict],
    cdp_responses: list[dict],
    stop_event: asyncio.Event,
    navigate_url: str | None = None,
) -> None:
    """
    Connect to one Chrome tab via CDP, enable network capture on the tab AND
    any Web Workers it spawns, then read events until stop_event is set or the
    WebSocket closes.

    WHY WE NEED WORKER CAPTURE
    ---------------------------
    DDB's VTT likely handles the S3 file upload inside a Dedicated Worker
    (a separate JS thread) to avoid blocking the UI.  CDP's Network.enable on
    the *page* target only sees requests made by the main thread.  To see
    Worker requests we must:

      1. Call Target.setAutoAttach with flatten=true on the page session.
         This tells Chrome to automatically create a "session" for every child
         target (workers, iframes) and route their events through the same
         WebSocket using a "sessionId" field.

      2. When we receive a Target.attachedToTarget event we get a new sessionId.
         We send Network.enable using that sessionId (via the "sessionId" field
         on the CDP message) to arm network capture on the worker too.

      3. Network events from workers arrive on the same WebSocket but carry the
         worker's sessionId — we log them prefixed with [tab/worker].

    RESPONSE BODY CAPTURE
    ----------------------
    CDP's Network.requestWillBeSent gives us the request but not the response
    body.  To read the body we must:

      1. Note the requestId from each interesting request.
      2. When Network.loadingFinished fires for that requestId, call
         Network.getResponseBody with the requestId to retrieve the body.

    We do this for all POST requests to dndbeyond.com/games so we can see
    which one actually returns presigned S3 fields.
    """
    import websockets

    tab_label = ws_url.split("/")[-1][:12]

    # Map requestId → url so we know which response bodies to fetch
    pending_response_bodies: dict[str, str] = {}

    try:
        async with websockets.connect(
            ws_url,
            max_size=50_000_000,
            ping_interval=None,
        ) as ws:

            async def cdp_tab(method: str, params: dict | None = None,
                               id_: int = 1, session_id: str | None = None) -> dict:
                """Send a CDP command, optionally on a child session (worker)."""
                msg: dict = {"id": id_, "method": method, "params": params or {}}
                if session_id:
                    msg["sessionId"] = session_id
                await ws.send(json.dumps(msg))
                # We don't wait for the reply here — fire-and-forget is fine for
                # enable/setAutoAttach because we process replies in the event loop.
                return {}

            # Arm network monitoring on the page
            await cdp_tab("Network.enable", id_=10)

            # Tell Chrome to auto-attach to child targets (workers, iframes)
            # flatten=True routes their CDP messages through this same WebSocket
            # with a "sessionId" field distinguishing them from the page.
            await cdp_tab("Target.setAutoAttach", {
                "autoAttach":            True,
                "waitForDebuggerOnStart": False,
                "flatten":               True,
            }, id_=11)

            # Inject JS interceptor on the page
            await cdp_tab("Runtime.evaluate", {"expression": INTERCEPT_JS}, id_=12)

            if navigate_url:
                # Check if we're already on the right page — if so, reload instead
                # of navigating.  Page.reload() keeps cookies/session intact and
                # re-establishes all WebSocket connections from scratch while our
                # Network monitor is already armed.  Page.navigate() to a new URL
                # can reset auth state in headless Chrome.
                current_url_result = await cdp_tab(
                    "Runtime.evaluate",
                    {"expression": "location.href", "returnByValue": True},
                    id_=12,
                )
                current_url = current_url_result.get("result", {}).get("value", "")
                campaign_id_str = navigate_url.rstrip("/").split("/")[-1]

                if campaign_id_str in current_url:
                    log(f"  [{tab_label}] Already on games page — reloading to re-arm WebSocket capture")
                    await cdp_tab("Page.reload", {"ignoreCache": False}, id_=13)
                else:
                    log(f"  [{tab_label}] Navigating to {navigate_url}")
                    await cdp_tab("Page.navigate", {"url": navigate_url}, id_=13)

            # Give the page a moment to start loading before we begin reading events
            await asyncio.sleep(2)

            # Track worker sessions so we can arm Network.enable on them
            worker_sessions: set[str] = set()

            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    msg = json.loads(raw)
                    method  = msg.get("method", "")
                    params  = msg.get("params", {})
                    session = msg.get("sessionId", "")  # non-empty = from a child target

                    # ── New worker/iframe attached ────────────────────────
                    if method == "Target.attachedToTarget":
                        new_session = params.get("sessionId", "")
                        ti = params.get("targetInfo", {})
                        ttype = ti.get("type", "")
                        turl  = ti.get("url", "")
                        if new_session and new_session not in worker_sessions:
                            worker_sessions.add(new_session)
                            log(f"  [{tab_label}] Attached to {ttype}: {turl[:60]}")
                            # Arm network capture on the worker
                            await cdp_tab("Network.enable", id_=10, session_id=new_session)

                    # ── WebSocket created — note the requestId so we can
                    #    match frames to the right connection ───────────────
                    elif method == "Network.webSocketCreated":
                        ws_req_id = params.get("requestId", "")
                        ws_url2   = params.get("url", "")
                        src       = f"{tab_label}/{session[:6]}" if session else tab_label
                        log(f"  [WS] [{src}] CREATED {ws_url2[:100]}")

                    # ── WebSocket frame SENT (client → server) ────────────
                    # This fires whenever JavaScript calls ws.send(data).
                    # payloadData is a string; for binary frames it may be
                    # base64 or show as raw bytes depending on Chrome version.
                    # opcode 1 = text, 2 = binary.
                    elif method == "Network.webSocketFrameSent":
                        ws_req_id = params.get("requestId", "")
                        frame     = params.get("response", {})   # CDP calls it "response" even for sent frames
                        opcode    = frame.get("opcode", 1)
                        payload   = frame.get("payloadData", "")
                        src       = f"{tab_label}/{session[:6]}" if session else tab_label
                        # Only print if non-empty and not a ping (opcode 9)
                        if payload and opcode not in (9, 10):
                            log(f"  [WS SEND] [{src}] op={opcode} len={len(payload)}")
                            log(f"    {payload[:600]}")
                            cdp_requests.append({
                                "tab":       src,
                                "method":    "WS_SEND",
                                "url":       f"ws_req:{ws_req_id}",
                                "headers":   {},
                                "post_data": payload[:3000],
                            })

                    # ── WebSocket frame RECEIVED (server → client) ────────
                    elif method == "Network.webSocketFrameReceived":
                        ws_req_id = params.get("requestId", "")
                        frame     = params.get("response", {})
                        opcode    = frame.get("opcode", 1)
                        payload   = frame.get("payloadData", "")
                        src       = f"{tab_label}/{session[:6]}" if session else tab_label
                        if payload and opcode not in (9, 10):
                            log(f"  [WS RECV] [{src}] op={opcode} len={len(payload)}")
                            log(f"    {payload[:600]}")
                            cdp_responses.append({
                                "tab":    src,
                                "url":    f"ws_recv:{ws_req_id}",
                                "status": 0,
                                "mime":   "websocket",
                                "body":   payload[:3000],
                            })

                    # ── Network request (page OR worker) ──────────────────
                    elif method == "Network.requestWillBeSent":
                        req         = params.get("request", {})
                        req_id      = params.get("requestId", "")
                        url         = req.get("url", "")
                        http_method = req.get("method", "GET")
                        post_data   = req.get("postData", "")
                        headers     = req.get("headers", {})
                        src         = f"{tab_label}/{session[:6]}" if session else tab_label

                        entry = {
                            "tab":       src,
                            "method":    http_method,
                            "url":       url,
                            "headers":   headers,
                            "post_data": post_data[:3000] if post_data else "",
                        }
                        cdp_requests.append(entry)

                        flag = ">>>" if http_method == "POST" else "   "
                        log(f"  {flag} [{src}] {http_method:7s} {url[:100]}")
                        if post_data:
                            log(f"           body: {post_data[:300]}")
                        if http_method == "POST" and headers:
                            for k, v in headers.items():
                                v_short = str(v)[:120]
                                if "cookie" in k.lower():
                                    v_short = v_short[:60] + "…"
                                log(f"           {k}: {v_short}")

                        # Queue response body fetch for POSTs to DDB games endpoint
                        # and for any S3 POST
                        if http_method == "POST" and (
                            "dndbeyond.com/games" in url or "s3.amazonaws.com" in url
                        ):
                            pending_response_bodies[req_id] = (url, session)

                    # ── Loading finished — fetch response body ────────────
                    elif method == "Network.loadingFinished":
                        req_id = params.get("requestId", "")
                        if req_id in pending_response_bodies:
                            (req_url, req_session) = pending_response_bodies.pop(req_id)
                            try:
                                # getResponseBody must be sent on the same session
                                # as the request (page or worker)
                                resp_msg: dict = {
                                    "id":     99,
                                    "method": "Network.getResponseBody",
                                    "params": {"requestId": req_id},
                                }
                                if req_session:
                                    resp_msg["sessionId"] = req_session
                                await ws.send(json.dumps(resp_msg))
                                # Read until we get id=99
                                for _ in range(30):
                                    rm = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                                    if rm.get("id") == 99:
                                        body_data = rm.get("result", {}).get("body", "")
                                        if body_data:
                                            log(f"  RESPONSE BODY for {req_url[:60]}:")
                                            log(f"    {body_data[:500]}")
                                            # Check for presigned fields
                                            import re as _re
                                            if _re.search(r'"bucket"\s*:', body_data):
                                                log("  *** PRESIGNED FIELDS IN THIS RESPONSE ***")
                                        break
                            except Exception as exc:
                                pass

                    elif method == "Network.responseReceived":
                        resp = params.get("response", {})
                        cdp_responses.append({
                            "tab":    tab_label,
                            "url":    resp.get("url", ""),
                            "status": resp.get("status", 0),
                            "mime":   resp.get("mimeType", ""),
                        })

                except asyncio.TimeoutError:
                    pass
                except Exception:
                    log(f"  [{tab_label}] WebSocket closed.")
                    break

    except Exception as exc:
        log(f"  [{tab_label}] Could not connect: {exc}")


async def probe(campaign_id: str, wait_seconds: int) -> dict:
    """
    Connect to ALL open Chrome tabs, arm network capture on each, navigate
    the main tab to the campaign page, then wait for the user to trigger
    an upload.  Collect and return all captured requests.

    Running one watcher per tab is necessary because DDB's map upload spans
    two origins:
      www.dndbeyond.com   → Server Action POST (presigned S3 fields)
      media.dndbeyond.com → VTT SPA (S3 multipart upload POST)
    A single-tab watcher only catches half the story.
    """
    campaign_url = f"{DDB_GAMES_URL}/{campaign_id}"
    log(f"Campaign URL: {campaign_url}")
    log("Listing open Chrome tabs…")

    ws_urls, nav_urls = get_all_ws_urls(campaign_id)
    if not ws_urls:
        log("ERROR: No Chrome CDP page found.  Is Chrome running?")
        return {}

    log(f"Found {len(ws_urls)} tab(s) — will watch all of them.")

    # Warn if none of the tabs is already on the games page — navigation
    # can drop the authenticated session in headless Chrome.
    if all(nav != "" for nav in nav_urls):
        log("")
        log("WARNING: No tab is already on the games page.")
        log("For best results, manually open Chrome to:")
        log(f"  {campaign_url}")
        log("and then re-run this script so it attaches to your live session.")
        log("")

    # Shared lists written by all watcher tasks
    cdp_requests:  list[dict] = []
    cdp_responses: list[dict] = []
    stop_event = asyncio.Event()

    log("")
    log("=" * 60)
    log(f"WAITING {wait_seconds} SECONDS — DO YOUR UPLOAD NOW")
    log("In the Chrome window:")
    log("  1. Open the VTT map panel (the map upload icon)")
    log("  2. Click the upload / add map button")
    log("  3. Choose an image file and confirm")
    log("All tabs are monitored. POST requests are flagged with >>>")
    log("Full headers printed for every POST (action hash will appear there)")
    log("=" * 60)
    log("")

    # Launch one watcher task per tab.
    # nav_urls[i] is either the campaign URL (navigate) or "" (skip navigation).
    tasks = []
    for ws_url, nav in zip(ws_urls, nav_urls):
        task = asyncio.create_task(
            _watch_one_tab(ws_url, cdp_requests, cdp_responses, stop_event, nav or None)
        )
        tasks.append(task)

    # Wait for the user's upload window, then signal all watchers to stop
    await asyncio.sleep(wait_seconds)
    stop_event.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    js_requests: list[dict] = []   # JS-layer capture not used in multi-tab mode
    page_info:   dict       = {}

    # ── Step 9: Build and save the report ─────────────────────────────────
    report = {
        "probed_at":     datetime.now().isoformat(),
        "campaign_url":  campaign_url,
        "final_url":     page_info.get("url", ""),
        "page_title":    page_info.get("title", ""),
        "file_inputs":   page_info.get("inputs", []),
        "map_buttons":   page_info.get("buttons", []),
        "cdp_requests":  cdp_requests,
        "cdp_responses": cdp_responses,
        "js_requests":   js_requests,
    }

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"\nFull report saved → {REPORT_PATH}")

    # ── Step 10: Print a focused summary ──────────────────────────────────
    log("\n" + "=" * 60)
    log("SUMMARY")
    log("=" * 60)
    log(f"Final URL   : {report['final_url']}")
    log(f"Page title  : {report['page_title']}")
    log(f"File inputs : {report['file_inputs']}")
    log(f"Map buttons : {report['map_buttons']}")
    log(f"CDP requests captured   : {len(cdp_requests)}")
    log(f"JS  requests captured   : {len(js_requests)}")

    # The two requests we care about most:
    all_reqs = cdp_requests + [
        {"method": r.get("method"), "url": r.get("url"), "post_data": r.get("body", ""), "source": "js"}
        for r in js_requests
    ]

    post_reqs = [r for r in all_reqs if r.get("method") == "POST"]
    s3_reqs   = [r for r in all_reqs if "s3.amazonaws.com" in r.get("url", "")]
    action_reqs = [r for r in post_reqs if "dndbeyond.com" in r.get("url", "")]

    log(f"\nPOST requests total     : {len(post_reqs)}")

    if action_reqs:
        log("\n>>> FOUND: DDB Server Action call(s) <<<")
        for r in action_reqs:
            log(f"  URL  : {r['url']}")
            log(f"  Body : {str(r.get('post_data', ''))[:300]}")
            hdrs = r.get("headers", {})
            if hdrs:
                for k, v in hdrs.items():
                    if "next-action" in k.lower() or "cookie" in k.lower() or "content-type" in k.lower():
                        if "cookie" in k.lower():
                            log(f"  {k}: {str(v)[:80]}…")
                        else:
                            log(f"  {k}: {v}")
    else:
        log("\n  No DDB Server Action POST found.")
        log("  Did you trigger an upload in Chrome during the wait window?")

    if s3_reqs:
        log("\n>>> FOUND: S3 upload call(s) <<<")
        for r in s3_reqs:
            log(f"  URL  : {r['url']}")
            log(f"  Body : {str(r.get('post_data', ''))[:200]}")
    else:
        log("\n  No S3 upload call found.")

    # If we found the action hash, call it out clearly
    for r in action_reqs:
        hdrs = r.get("headers", {})
        for k, v in hdrs.items():
            if "next-action" in k.lower():
                log(f"\n>>> ACTION HASH FOUND: {v}")
                log("    Update _DDB_ACTION_HASH in seed_battle_maps.py with this value.")

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Capture DDB VTT map-upload API calls via Chrome CDP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/probe_ddb_vtt.py
  python scripts/probe_ddb_vtt.py --campaign-id 6923222 --wait 120
        """,
    )
    p.add_argument(
        "--campaign-id",
        default=DEFAULT_CAMPAIGN_ID,
        help=f"DDB campaign (game) ID — appears in the URL, e.g. 6923222 (default: {DEFAULT_CAMPAIGN_ID})",
    )
    p.add_argument(
        "--wait",
        type=int,
        default=90,
        help="Seconds to wait for you to trigger an upload in the browser (default: 90)",
    )
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    campaign_url = f"{DDB_GAMES_URL}/{args.campaign_id}"

    if not chrome_is_alive():
        log("Chrome not detected on CDP port — launching it…")
        if not launch_chrome(campaign_url):
            log("ERROR: Could not start Chrome.  Set CHROME_PATH in .env if needed.")
            return
    else:
        log("Chrome already running — will connect to all open tabs.")

    await probe(campaign_id=args.campaign_id, wait_seconds=args.wait)


if __name__ == "__main__":
    asyncio.run(main())
