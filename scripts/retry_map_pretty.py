"""
One-shot: run the pretty battlemap pass on an existing tactical map and post to Discord.
Usage: python scripts/retry_map_pretty.py [path/to/defense_map.png] [discord_channel_id]
"""
import os, sys, json
os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from pathlib import Path

MAP_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path(r"C:\Users\akodoreign\Desktop\chatGPT-discord-bot\generated_modules\Defense_of_the_Veiled_Path_20260509_165105\defense_map.png")

CHANNEL_ID = sys.argv[2] if len(sys.argv) > 2 else os.getenv("MODULE_OUTPUT_CHANNEL_ID", "1484147249637359769")
TOKEN      = os.getenv("DISCORD_BOT_TOKEN", "")

CONTEXT = {
    "title":    "Defense of the Veiled Path",
    "kind":     "interior",
    "location": "underground meeting hall",
    "faction":  "Serpent Choir",
}


def post_file_to_discord(channel_id, token, filepath: Path, caption: str = ""):
    import urllib.request, uuid, io as _io
    boundary = uuid.uuid4().hex
    buf = _io.BytesIO()
    # payload_json part
    payload = json.dumps({"content": caption})
    buf.write(f'--{boundary}\r\n'.encode())
    buf.write(b'Content-Disposition: form-data; name="payload_json"\r\n')
    buf.write(b'Content-Type: application/json\r\n\r\n')
    buf.write(payload.encode())
    buf.write(b'\r\n')
    # file part
    data = filepath.read_bytes()
    ctype = "image/png" if filepath.suffix == ".png" else "application/octet-stream"
    buf.write(f'--{boundary}\r\n'.encode())
    buf.write(f'Content-Disposition: form-data; name="files[0]"; filename="{filepath.name}"\r\n'.encode())
    buf.write(f'Content-Type: {ctype}\r\n\r\n'.encode())
    buf.write(data)
    buf.write(b'\r\n')
    buf.write(f'--{boundary}--\r\n'.encode())

    raw = buf.getvalue()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=raw,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "TowerBot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.request.HTTPError as e:
        print(f"  HTTP error: {e.code} — {e.read().decode()[:300]}")
        return e.code


if __name__ == "__main__":
    from src.mission_builder.vtt_renderer import stylize_pretty_battlemap
    from PIL import Image, ImageStat

    print(f"Source map : {MAP_PATH}")
    if not MAP_PATH.exists():
        print("ERROR: map file not found")
        sys.exit(1)

    with Image.open(MAP_PATH) as img:
        stat = ImageStat.Stat(img.convert("RGB").resize((64, 64)))
        print(f"Map stddev  : {[round(s, 2) for s in stat.stddev]}  (must be >4 to pass validation)")

    print("\nRunning pretty map pass (force=True)…")
    result = stylize_pretty_battlemap(MAP_PATH, context=CONTEXT, force=True)

    if result and result.exists():
        with Image.open(result) as img:
            stat = ImageStat.Stat(img.convert("RGB").resize((64, 64)))
            print(f"Pretty map  : {result}")
            print(f"Pretty stddev: {[round(s, 2) for s in stat.stddev]}")
        print(f"\nPosting to Discord channel {CHANNEL_ID}…")
        status = post_file_to_discord(
            CHANNEL_ID, TOKEN, result,
            "🗺️ **Defense of the Veiled Path** — tactical battle map"
        )
        print(f"Discord: HTTP {status}")
    else:
        print("❌ Pretty pass returned None — all strategies failed again")
        print("   Posting the raw tactical map as fallback…")
        status = post_file_to_discord(
            CHANNEL_ID, TOKEN, MAP_PATH,
            "🗺️ **Defense of the Veiled Path** — tactical map (programmatic render)"
        )
        print(f"Discord fallback: HTTP {status}")
