"""
One-shot: re-run the module pipeline for a mission that failed mid-generation.
Posts result to the module output channel via Discord REST API (no bot client needed).

Usage: python scripts/retry_module_gen.py [mission_id]
Default mission_id = 855 (Defense of the Veiled Path for Akodo Reign)
"""

import asyncio
import json
import os
import sys
import zipfile
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MISSION_ID   = int(sys.argv[1]) if len(sys.argv) > 1 else 855
PLAYER_NAME  = "Akodo Reign"


# ---------------------------------------------------------------------------
# Discord REST helpers (no discord.py bot client needed)
# ---------------------------------------------------------------------------

def _discord_post(channel_id: str, token: str, **kwargs):
    """POST a message to a Discord channel via REST. kwargs forwarded to requests."""
    import urllib.request, urllib.error
    import json as _json

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "TowerBot/1.0",
    }

    body    = kwargs.get("json_body")
    files   = kwargs.get("files")     # list of (field_name, filename, bytes, content_type)
    payload = kwargs.get("payload_json")  # str for multipart

    if files:
        import email.mime.multipart
        import mimetypes, io, uuid
        boundary = uuid.uuid4().hex
        parts = []
        if payload:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
                f'Content-Type: application/json\r\n\r\n{payload}\r\n'
            )
        for i, (field, fname, data, ctype) in enumerate(files):
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="files[{i}]"; filename="{fname}"\r\n'
                f'Content-Type: {ctype}\r\n\r\n'
            )
        body_parts = b"".join(
            p.encode() if isinstance(p, str) else p
            for pair in zip(
                parts,
                [f[2] for f in files],
                [b"\r\n"] * len(files),
            )
            for p in pair
        )
        body_parts += f"--{boundary}--\r\n".encode()

        # Simpler: use urllib multipart the manual way
        import io as _io
        buf = _io.BytesIO()
        if payload:
            buf.write(f'--{boundary}\r\n'.encode())
            buf.write(b'Content-Disposition: form-data; name="payload_json"\r\n')
            buf.write(b'Content-Type: application/json\r\n\r\n')
            buf.write(payload.encode())
            buf.write(b'\r\n')
        for i, (field, fname, data, ctype) in enumerate(files):
            buf.write(f'--{boundary}\r\n'.encode())
            buf.write(f'Content-Disposition: form-data; name="files[{i}]"; filename="{fname}"\r\n'.encode())
            buf.write(f'Content-Type: {ctype}\r\n\r\n'.encode())
            buf.write(data if isinstance(data, bytes) else data.encode())
            buf.write(b'\r\n')
        buf.write(f'--{boundary}--\r\n'.encode())

        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        raw = buf.getvalue()
        req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
    else:
        raw = _json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=raw, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, _json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def post_module_rest(out_dir: Path, mission: dict, player_name: str, token: str, channel_id: str):
    """Post generated module files to Discord using raw REST API."""
    title   = mission.get("title", "Unknown")
    tier    = mission.get("tier", "standard").upper()
    faction = mission.get("faction", "Unknown")

    BOX_SET_SLUGS = ["dm_guide", "module", "players_guide", "chart_pack"]
    box_files = [out_dir / f"{s}.html" for s in BOX_SET_SLUGS if (out_dir / f"{s}.html").exists()]
    map_files = sorted((out_dir / "maps").glob("*.png")) if (out_dir / "maps").is_dir() else []
    zip_path  = out_dir.parent / f"{out_dir.name}.zip"

    print(f"  Box set files: {[f.name for f in box_files]}")
    print(f"  Maps: {len(map_files)}")
    print(f"  ZIP: {zip_path.exists()}")

    # 1. Embed summary
    embed = {
        "title": f"📖 Module Ready: {title}",
        "description": (
            f"**Claimed by:** {player_name}\n"
            f"**Faction:** {faction} | **Tier:** {tier}\n"
            f"Box set: {len(box_files)} components · {len(map_files)} maps"
        ),
        "color": 0xB8860B,
        "footer": {"text": "Tower of Last Chance — D&D 5e 2024"}
    }
    status, resp = _discord_post(channel_id, token, json_body={"embeds": [embed]})
    print(f"  Embed: HTTP {status}")

    # 2. HTML box set files (chunked, 10 MB Discord file limit)
    MAX_BYTES = 9 * 1024 * 1024  # 9 MB per message
    batch, batch_size = [], 0
    for fpath in box_files:
        data = fpath.read_bytes()
        if batch_size + len(data) > MAX_BYTES and batch:
            payload = json.dumps({"content": ""})
            status, _ = _discord_post(channel_id, token,
                files=[(f"file{i}", f.name, d, "text/html") for i, (f, d) in enumerate(batch)],
                payload_json=payload)
            print(f"  Batch HTML: HTTP {status}")
            batch, batch_size = [], 0
        batch.append((fpath, data))
        batch_size += len(data)
    if batch:
        payload = json.dumps({"content": ""})
        status, _ = _discord_post(channel_id, token,
            files=[(f"file{i}", f.name, d, "text/html") for i, (f, d) in enumerate(batch)],
            payload_json=payload)
        print(f"  HTML files: HTTP {status}")

    # 3. ZIP (if ≤ 25 MB)
    if zip_path.exists() and zip_path.stat().st_size < 25 * 1024 * 1024:
        data = zip_path.read_bytes()
        payload = json.dumps({"content": f"📦 Full module ZIP ({zip_path.stat().st_size // 1024} KB)"})
        status, _ = _discord_post(channel_id, token,
            files=[("file0", zip_path.name, data, "application/zip")],
            payload_json=payload)
        print(f"  ZIP: HTTP {status}")

    # 4. Maps (up to 4 per message)
    for i in range(0, len(map_files), 4):
        chunk = map_files[i:i+4]
        payload = json.dumps({"content": f"🗺️ Maps ({i+1}–{i+len(chunk)})" if i == 0 else ""})
        files = [(f"file{j}", p.name, p.read_bytes(), "image/png") for j, p in enumerate(chunk)]
        status, _ = _discord_post(channel_id, token, files=files, payload_json=payload)
        print(f"  Maps chunk {i//4+1}: HTTP {status}")

    print("✅ All files posted to Discord.")


async def main():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

    from src.db_api import raw_query
    from src.mission_builder import generate_module

    token      = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = os.getenv("MODULE_OUTPUT_CHANNEL_ID", "1484147249637359769")

    # Load mission from DB
    rows = raw_query("SELECT * FROM missions WHERE id = %s", (MISSION_ID,))
    if not rows:
        print(f"❌ Mission {MISSION_ID} not found in DB")
        return

    row = rows[0]
    mj  = row.get("mission_json") or {}
    if isinstance(mj, str):
        mj = json.loads(mj) if mj else {}

    mission = {
        **mj,
        "id":           row["id"],
        "title":        row.get("title") or mj.get("title", "Unknown"),
        "faction":      row.get("faction") or mj.get("faction", ""),
        "tier":         row.get("tier") or mj.get("tier", "standard"),
        "status":       row.get("status", "claimed"),
        "player_claimer": mj.get("player_claimer", PLAYER_NAME),
    }
    player_name = mission.get("player_claimer") or PLAYER_NAME

    print("=" * 70)
    print(f"MODULE PIPELINE RETRY: '{mission['title']}' for {player_name}")
    print(f"Faction: {mission['faction']} | Tier: {mission['tier']}")
    print("=" * 70)

    # Mark busy so news/lifecycle don't pile up
    try:
        from src.ollama_busy import mark_priority_busy, unmark_priority_busy
        mark_priority_busy(f"module retry: {mission['title']}")
    except Exception:
        unmark_priority_busy = lambda: None

    try:
        out_path = await generate_module(mission, player_name)
        if not out_path:
            print("❌ generate_module returned None — check logs")
            return

        out_dir = out_path.parent if out_path.is_file() else out_path
        print(f"\n✅ MODULE FILES: {out_dir}")

        # Create ZIP if it doesn't exist
        zip_path = out_dir.parent / f"{out_dir.name}.zip"
        if not zip_path.exists():
            print("  Creating ZIP archive...")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in out_dir.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(out_dir.parent))
            print(f"  ZIP: {zip_path.name} ({zip_path.stat().st_size // 1024} KB)")

        # Post to Discord
        if token and channel_id:
            print(f"\nPosting to Discord channel {channel_id}...")
            post_module_rest(out_dir, mission, player_name, token, channel_id)
        else:
            print("⚠️  DISCORD_BOT_TOKEN or MODULE_OUTPUT_CHANNEL_ID not set — skipping Discord post")
            print(f"   Open: {out_dir / 'module.html'}")

    except Exception as e:
        import traceback
        print(f"\n❌ Pipeline error: {e}")
        traceback.print_exc()
    finally:
        try:
            unmark_priority_busy()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
