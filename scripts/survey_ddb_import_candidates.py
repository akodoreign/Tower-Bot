"""Check image_refs and npc_appearances for existing NPC portrait data."""
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

def main():
    # image_refs table
    print("=== image_refs table ===")
    try:
        cols = raw_query("DESCRIBE image_refs")
        print("Columns:", [r["Field"] for r in cols])
        sample = raw_query("SELECT * FROM image_refs LIMIT 3")
        for r in sample:
            print(f"  {r}")
        count = raw_query("SELECT COUNT(*) as c FROM image_refs")[0]["c"]
        npc_imgs = raw_query("SELECT COUNT(*) as c FROM image_refs WHERE entity_type='npc' OR entity_type LIKE '%npc%'")
        print(f"  Total rows: {count}")
        print(f"  NPC-type rows: {npc_imgs[0]['c']}")
        entity_types = raw_query("SELECT entity_type, COUNT(*) as c FROM image_refs GROUP BY entity_type ORDER BY c DESC")
        print(f"  By entity_type: {[(r['entity_type'], r['c']) for r in entity_types]}")
    except Exception as e:
        print(f"  Error: {e}")

    # npc_appearances deep sample - get dnd_stats structure
    print("\n=== npc_appearances dnd_stats sample (5 NPCs) ===")
    na_rows = raw_query("SELECT npc_name, appearance_json FROM npc_appearances LIMIT 5")
    for r in na_rows:
        aj = jload(r["appearance_json"])
        ds = aj.get("dnd_stats", {})
        print(f"\n  [{r['npc_name']}]")
        print(f"    class={ds.get('class')} level={ds.get('level')} subclass={ds.get('subclass')}")
        print(f"    AC={ds.get('AC')} HP={ds.get('HP')} hit_die={ds.get('hit_die')} PB={ds.get('proficiency_bonus')}")
        print(f"    STR={ds.get('STR')} DEX={ds.get('DEX')} CON={ds.get('CON')} INT={ds.get('INT')} WIS={ds.get('WIS')} CHA={ds.get('CHA')}")
        print(f"    saves={ds.get('save_proficiencies')} speed={ds.get('speed')}")
        # species
        print(f"    species={aj.get('species')} sd_prompt exists: {bool(aj.get('sd_appearance'))}")

    # Count how many npc_appearances rows have sd_appearance (portrait prompt)
    print("\n=== npc_appearances coverage ===")
    na_count = raw_query("SELECT COUNT(*) as c FROM npc_appearances")[0]["c"]
    print(f"Total npc_appearances rows: {na_count}")
    na_with_sd = raw_query("""
        SELECT COUNT(*) as c FROM npc_appearances
        WHERE JSON_EXTRACT(appearance_json, '$.sd_appearance') IS NOT NULL
        AND JSON_EXTRACT(appearance_json, '$.sd_appearance') != 'null'
        AND JSON_EXTRACT(appearance_json, '$.sd_appearance') != ''
    """)[0]["c"]
    print(f"  With sd_appearance prompt: {na_with_sd}")
    na_with_dnd = raw_query("""
        SELECT COUNT(*) as c FROM npc_appearances
        WHERE JSON_EXTRACT(appearance_json, '$.dnd_stats') IS NOT NULL
        AND JSON_EXTRACT(appearance_json, '$.dnd_stats') != 'null'
    """)[0]["c"]
    print(f"  With dnd_stats block: {na_with_dnd}")

    # NPC status breakdown
    print("\n=== NPC status breakdown ===")
    status_rows = raw_query("SELECT status, COUNT(*) as c FROM npcs GROUP BY status ORDER BY c DESC")
    for r in status_rows:
        print(f"  {r['status']}: {r['c']}")

    # Sample stat block from a well-populated NPC
    print("\n=== Sample full dnd_stats from npc_appearances (1 detailed) ===")
    detailed = raw_query("""
        SELECT npc_name, appearance_json FROM npc_appearances
        WHERE JSON_EXTRACT(appearance_json, '$.dnd_stats.level') > 5
        LIMIT 1
    """)
    if detailed:
        r = detailed[0]
        aj = jload(r["appearance_json"])
        print(f"NPC: {r['npc_name']}")
        print(json.dumps(aj.get("dnd_stats", {}), indent=2))
        print(f"sd_appearance[:200]: {str(aj.get('sd_appearance',''))[:200]}")

main()
