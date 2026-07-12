"""Scan all generated_modules for creature stat blocks."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODULES_DIR = ROOT / "generated_modules"

def jload(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}

# 1. Check completed/ MODULE_*.json files
print("=== completed/ MODULE files ===")
completed_dir = MODULES_DIR / "completed"
for f in sorted(completed_dir.glob("MODULE_*.json")):
    data = jload(f)
    if isinstance(data, dict):
        print(f"\n{f.name}: keys={list(data.keys())[:10]}")
        encs = data.get("encounters", [])
        print(f"  encounters: {len(encs)}")
        for enc in encs[:1]:
            creatures = enc.get("creatures", [])
            print(f"  creatures: {len(creatures)}")
            for c in creatures[:1]:
                print(f"    sample: {c.get('name')} CR{c.get('cr')} | ac={c.get('ac')} hp={c.get('hp')}")
                print(f"    traits: {len(c.get('traits',[]))} actions: {len(c.get('actions',[]))}")
    elif isinstance(data, list):
        print(f"\n{f.name}: list of {len(data)}")
        # might be array of missions
        if data and isinstance(data[0], dict):
            print(f"  first item keys: {list(data[0].keys())[:10]}")

# 2. Check module_data.json files in subdirectories
print("\n=== module_data.json files ===")
for f in sorted(MODULES_DIR.rglob("module_data.json"))[:5]:
    data = jload(f)
    print(f"\n{f.parent.name}/module_data.json: keys={list(data.keys())[:10]}")
    encs = data.get("encounters", [])
    if encs:
        print(f"  encounters: {len(encs)}, first has creatures: {len(encs[0].get('creatures',[]))}")
        for c in encs[0].get("creatures", [])[:1]:
            print(f"    {c.get('name')} CR{c.get('cr')}")

# 3. Scan ALL json files in generated_modules for creature data
print("\n=== Full scan for creature data ===")
all_creatures: dict[str, dict] = {}
source_files: list[str] = []

for f in sorted(MODULES_DIR.rglob("*.json")):
    if any(x in str(f) for x in ("vtt.json", "mapdata", "_vtt_test", "maps_manifest", "backfill")):
        continue
    data = jload(f)
    # Try as dict with encounters
    if isinstance(data, dict):
        for enc in data.get("encounters", []):
            for c in enc.get("creatures", []):
                nm = (c.get("name") or "").strip()
                if nm and c.get("actions") and nm not in all_creatures:
                    all_creatures[nm] = c
                    source_files.append(str(f.relative_to(ROOT)))
    # Try as list of missions
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for enc in item.get("encounters", []):
                    for c in enc.get("creatures", []):
                        nm = (c.get("name") or "").strip()
                        if nm and c.get("actions") and nm not in all_creatures:
                            all_creatures[nm] = c
                            source_files.append(str(f.relative_to(ROOT)))

print(f"\nTotal unique creatures with actions: {len(all_creatures)}")
if all_creatures:
    print("Sample names:", list(all_creatures.keys())[:20])
    # Show one fully populated sample
    for nm, c in list(all_creatures.items())[:1]:
        print(f"\n=== Sample: {nm} ===")
        print(json.dumps(c, indent=2, default=str)[:1200])
