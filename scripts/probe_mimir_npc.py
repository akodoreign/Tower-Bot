"""Check stat_block NPCs and correct data priority."""
import json, sys
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

# Full stat_block for Vexrath
print("=== Vexrath full stat_block ===")
row = raw_query("SELECT data_json FROM npcs WHERE name='Vexrath Sablegear'")
if row:
    dj = jload(row[0]["data_json"])
    sb = dj.get("stat_block")
    print(json.dumps(sb, indent=2) if sb else "None")

# Check correct data priority: data_json vs npc_appearances for a gear_tier NPC
print("\n=== Captain Havel Korin — data comparison ===")
row = raw_query("SELECT data_json FROM npcs WHERE name='Captain Havel Korin'")
dj = jload(row[0]["data_json"]) if row else {}
print(f"data_json.stats: {dj.get('stats')}")
print(f"data_json.level: {dj.get('level')}")
print(f"data_json.dnd_class: {dj.get('dnd_class')}")
items = dj.get("equipment", [])
if isinstance(items, list):
    print(f"data_json.equipment ({len(items)} items):")
    for it in items:
        print(f"  - {it.get('name')} (equipped={it.get('equipped')})")
elif isinstance(items, dict):
    print(f"data_json.equipment (dict): {items}")

# Check a sample regular NPC for data completeness
print("\n=== Regular NPC data_json stats check (Sera Voss) ===")
row = raw_query("SELECT data_json FROM npcs WHERE name='Sera Voss'")
dj = jload(row[0]["data_json"]) if row else {}
print(f"keys: {list(dj.keys())}")
print(f"stats: {dj.get('stats')}")
print(f"level: {dj.get('level')} | class: {dj.get('dnd_class')}")
items = dj.get("equipment", [])
print(f"equipment: {items}")

# Count how many NPCs have equipment as list vs dict
print("\n=== Equipment format distribution ===")
rows = raw_query("SELECT name, JSON_EXTRACT(data_json,'$.equipment') as eq FROM npcs WHERE JSON_EXTRACT(data_json,'$.equipment') IS NOT NULL")
list_count = 0; dict_count = 0; other = 0
for r in rows:
    eq = jload(r["eq"])
    if isinstance(eq, list): list_count += 1
    elif isinstance(eq, dict): dict_count += 1
    else: other += 1
print(f"List: {list_count}, Dict: {dict_count}, Other: {other}")
print(f"Total with equipment field: {len(rows)}")

# Sample magic items across gear_tier NPCs
print("\n=== All unique magic items across gear_tier NPCs ===")
epic_rows = raw_query("SELECT name, JSON_EXTRACT(data_json,'$.equipment') as eq FROM npcs WHERE JSON_EXTRACT(data_json,'$.gear_tier') IS NOT NULL")
all_items = {}
for r in epic_rows:
    eq = jload(r["eq"])
    if isinstance(eq, list):
        for it in eq:
            nm = it.get("name","")
            if nm and nm not in ("Explorer's Pack","Burglar's Pack","Potion of Healing","Potion of Greater Healing","Thieves' Tools","Dagger","Shield","Chain Mail","Backpack"):
                all_items[nm] = all_items.get(nm, 0) + 1
items_sorted = sorted(all_items.items(), key=lambda x: -x[1])
for nm, c in items_sorted:
    print(f"  {nm}: {c}")
