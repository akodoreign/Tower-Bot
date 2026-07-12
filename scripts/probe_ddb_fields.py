"""Check what's actually saved in the textarea fields after our edits."""
import asyncio, sys, re
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
import httpx
from src.ddb_homebrew import SESSION

async def probe():
    # Use EBP Thorny
    url = 'https://www.dndbeyond.com/homebrew/creations/monsters/6453242-ebp-thorny/edit'
    headers = {'Accept': 'text/html,application/xhtml+xml',
               'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124'}
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as c:
        r = await c.get(url, headers=headers, cookies={'CobaltSession': SESSION})

    # Find each textarea and print its content
    for m in re.finditer(r'<textarea[^>]+id="([^"]+)"[^>]*>(.*?)</textarea>', r.text, re.DOTALL | re.IGNORECASE):
        fid     = m.group(1)
        content = m.group(2).strip()[:200]
        if 'description' in fid or 'trait' in fid or 'action' in fid or 'reaction' in fid:
            print(f'\n--- {fid} ---')
            print(repr(content) if content else '(EMPTY)')

    # Also check description-type hidden field values
    print('\n--- description-type values ---')
    for m in re.finditer(r'id="(field-[^"]+description-type)"[^>]*value="([^"]*)"', r.text):
        print(f'  {m.group(1)}: {m.group(2)}')

asyncio.run(probe())
