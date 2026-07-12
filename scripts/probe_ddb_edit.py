"""Probe the DDB monster edit page for form action URL."""
import asyncio, sys, re
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
import httpx
from src.ddb_homebrew import SESSION

async def probe_edit():
    edit_url = 'https://www.dndbeyond.com/homebrew/creations/monsters/6453200-ebp-vegepygmy/edit'
    headers = {
        'Accept': 'text/html,application/xhtml+xml',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124',
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        r = await client.get(edit_url, headers=headers, cookies={'CobaltSession': SESSION})
        # Find ALL form tags
        forms = re.findall(r'<form[^>]+>', r.text, re.IGNORECASE)
        for i, f in enumerate(forms):
            print(f'Form {i}: {f[:300]}')
        print()
        # Find hidden _method override (DDB uses Rails-style POST with _method=patch)
        method_fields = re.findall(r'name="_method"[^>]*value="([^"]+)"', r.text, re.IGNORECASE)
        print('_method overrides:', method_fields)
        # Find form action attributes
        actions = re.findall(r'action="([^"]+)"', r.text, re.IGNORECASE)
        print('Form actions:', actions[:5])
        # Check avatar field names in this specific page (obfuscated per session)
        for fid in ('field-avatar', 'field-large-avatar'):
            m = re.search(r'id="' + fid + r'"[^>]*name="([^"]+)"', r.text)
            if not m:
                m = re.search(r'name="([^"]+)"[^>]*id="' + fid + r'"', r.text)
            print(f'  {fid} obf name: {m.group(1) if m else "NOT FOUND"}')

asyncio.run(probe_edit())
