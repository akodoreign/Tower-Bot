"""
Retroactively edit Discord mission board messages to replace "" with —.
Scans channel for bot messages with embeds, patches any that contain "".
"""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()
import requests

TOKEN      = os.getenv("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = "1459652462045827113"
HEADERS    = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
EM         = "—"   # —
OLD        = '""'

def fetch_messages(channel_id, max_pages=50):
    messages, before = [], None
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    for _ in range(max_pages):
        params = {"limit": 100}
        if before:
            params["before"] = before
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code != 200 or not r.json():
            break
        batch = r.json()
        messages.extend(batch)
        before = batch[-1]["id"]
        print(f"  fetched {len(messages)} messages...")
        time.sleep(0.4)
    return messages

def fix_str(s):
    return s.replace(OLD, EM) if s else s

def needs_fix(s):
    return s and OLD in s

def patch_message(channel_id, msg_id, payload):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{msg_id}"
    r = requests.patch(url, headers=HEADERS, json=payload)
    if r.status_code == 429:
        time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
        r = requests.patch(url, headers=HEADERS, json=payload)
    return r.status_code

def main():
    dry = "--dry-run" in sys.argv
    print(f"Fetching messages from {CHANNEL_ID}...")
    messages = fetch_messages(CHANNEL_ID)
    print(f"Total: {len(messages)}\n")

    edited = skipped = 0
    for msg in messages:
        embeds = msg.get("embeds", [])
        content = msg.get("content", "")
        if not embeds and not needs_fix(content):
            continue

        new_embeds = []
        changed = False

        for emb in embeds:
            new_emb = dict(emb)
            if needs_fix(emb.get("title")):
                new_emb["title"] = fix_str(emb["title"])
                changed = True
            if needs_fix(emb.get("description")):
                new_emb["description"] = fix_str(emb["description"])
                changed = True
            # Fix fields
            if emb.get("fields"):
                new_fields = []
                for f in emb["fields"]:
                    nf = dict(f)
                    if needs_fix(f.get("name")):
                        nf["name"] = fix_str(f["name"])
                        changed = True
                    if needs_fix(f.get("value")):
                        nf["value"] = fix_str(f["value"])
                        changed = True
                    new_fields.append(nf)
                new_emb["fields"] = new_fields
            # Fix footer
            if emb.get("footer") and needs_fix(emb["footer"].get("text")):
                new_emb["footer"] = dict(emb["footer"])
                new_emb["footer"]["text"] = fix_str(emb["footer"]["text"])
                changed = True
            new_embeds.append(new_emb)

        new_content = fix_str(content) if needs_fix(content) else content
        if needs_fix(content):
            changed = True

        if not changed:
            continue

        title_preview = (new_embeds[0].get("title") if new_embeds else new_content)[:60]
        print(f"  msg {msg['id']}: {title_preview}")

        if dry:
            print(f"    -> DRY RUN")
            edited += 1
            continue

        payload = {}
        if new_embeds:
            payload["embeds"] = new_embeds
        if new_content != content:
            payload["content"] = new_content

        status = patch_message(CHANNEL_ID, msg["id"], payload)
        if status in (200, 204):
            print(f"    -> patched")
            edited += 1
        else:
            print(f"    -> FAILED (HTTP {status})")
            skipped += 1
        time.sleep(0.5)

    print(f"\nDone. Edited: {edited} | Failed: {skipped}")
    if dry:
        print("(dry run — nothing written)")

if __name__ == "__main__":
    main()
