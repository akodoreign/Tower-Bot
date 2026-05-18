"""Check mimir_sync table and Mimir connectivity."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
from src.db_api import raw_query

def jload(v):
    if isinstance(v, str):
        try: return json.loads(v)
        except: return {}
    return v or {}

# Mimir env vars
print("MIMIR_MCP_PATH:", os.getenv("MIMIR_MCP_PATH", "(not set)"))
print("MIMIR_CAMPAIGN_ID:", os.getenv("MIMIR_CAMPAIGN_ID", "(not set)"))

# mimir_sync table
print("\n=== mimir_sync table ===")
cols = raw_query("DESCRIBE mimir_sync")
print("Columns:", [r["Field"] for r in cols])
count = raw_query("SELECT COUNT(*) as c FROM mimir_sync")[0]["c"]
print(f"Total rows: {count}")
sample = raw_query("SELECT * FROM mimir_sync LIMIT 3")
for r in sample:
    print(f"  {r}")

# Check if any NPCs have mimir_id in their data_json
print("\n=== NPCs with mimir_id ===")
rows = raw_query("SELECT name, JSON_EXTRACT(data_json, '$.mimir_id') as mid FROM npcs WHERE JSON_EXTRACT(data_json, '$.mimir_id') IS NOT NULL LIMIT 5")
for r in rows:
    print(f"  {r['name']}: mimir_id={r['mid']}")

count_with_mid = raw_query("SELECT COUNT(*) as c FROM npcs WHERE JSON_EXTRACT(data_json, '$.mimir_id') IS NOT NULL")[0]["c"]
print(f"Total NPCs with mimir_id: {count_with_mid}")

# Check the skills table more carefully (kharma-purchasable abilities)
print("\n=== skills table (kharma abilities) ===")
sk_count = raw_query("SELECT COUNT(*) as c FROM skills")[0]["c"]
print(f"Total skills rows: {sk_count}")
sk_cats = raw_query("SELECT category, COUNT(*) as c FROM skills GROUP BY category ORDER BY c DESC LIMIT 10")
for r in sk_cats:
    print(f"  {r['category']}: {r['c']}")
sk_sample = raw_query("SELECT title, category, keywords FROM skills LIMIT 5")
for r in sk_sample:
    print(f"  [{r['category']}] {r['title']} | {str(r['keywords'])[:80]}")
