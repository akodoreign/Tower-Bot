"""
Fix NPC stats that are blank or all-10s glitches.
Assigns class-appropriate stat arrays. Run: python scripts/_fix_npc_stats.py
"""
import hashlib, json, mysql.connector, sys
sys.path.insert(0, ".")

db = mysql.connector.connect(
    host="localhost", user="Claude",
    password="WXdCPJmeDfaQALaktzF6!", database="tower_bot"
)
cur = db.cursor(dictionary=True)
cur2 = db.cursor()

STAT_KEYS = ("STR", "DEX", "CON", "INT", "WIS", "CHA")

# Class -> (primary, secondary, tertiary) stat priorities
# Each entry is a base array [STR, DEX, CON, INT, WIS, CHA] then we seed variation
CLASS_ARRAYS = {
    # Martial / STR-primary
    "Fighter":       [17, 12, 16, 11, 13, 10],
    "Barbarian":     [18, 13, 17, 8,  12, 10],
    "Paladin":       [16, 10, 15, 10, 14, 16],
    "Blood Hunter":  [16, 14, 15, 13, 12, 10],
    "Monster Hunter":[16, 14, 15, 14, 13, 10],
    "Pugilist":      [18, 13, 16, 10, 12, 10],
    # DEX-primary martial
    "Ranger":        [13, 17, 14, 12, 16, 10],
    "Rogue":         [10, 18, 13, 15, 13, 12],
    "Monk":          [13, 17, 14, 11, 16, 10],
    "Gunslinger":    [10, 18, 13, 13, 12, 14],
    # INT/WIS casters
    "Wizard":        [8,  12, 13, 18, 15, 12],
    "Artificer":     [10, 14, 13, 17, 14, 10],
    # WIS casters
    "Cleric":        [13, 10, 14, 11, 18, 14],
    "Druid":         [10, 13, 14, 12, 18, 12],
    # CHA casters
    "Bard":          [10, 14, 13, 13, 14, 17],
    "Sorcerer":      [8,  13, 14, 13, 13, 18],
    "Warlock":       [10, 13, 14, 13, 13, 17],
}
DEFAULT_ARRAY = [13, 13, 13, 13, 13, 13]


def _seeded_vary(base: list[int], seed: str) -> dict:
    """Apply small seeded variation (+/-2) to a base stat array."""
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    result = {}
    for i, (key, val) in enumerate(zip(STAT_KEYS, base)):
        nudge = ((h >> (i * 4)) & 0xF) % 5 - 2   # -2 to +2
        result[key] = max(8, min(20, val + nudge))
    return result


def _primary_class(dnd_class: str) -> str:
    if not dnd_class:
        return "Fighter"
    primary = dnd_class.split("/")[0].strip()
    return primary if primary in CLASS_ARRAYS else "Fighter"


def _needs_fix(stats: dict) -> bool:
    vals = [stats.get(k) for k in STAT_KEYS]
    has_any = any(v is not None for v in vals)
    if not has_any:
        return True
    all_ten = all((v or 0) == 10 for v in vals if v is not None)
    return all_ten


cur.execute("SELECT id, name, data_json FROM npcs WHERE status != 'dead' ORDER BY name")
rows = cur.fetchall()
fixed = 0

for r in rows:
    dj = json.loads(r["data_json"]) if isinstance(r["data_json"], str) else (r["data_json"] or {})
    stats = dj.get("stats", {})
    if not isinstance(stats, dict):
        stats = {}

    if not _needs_fix(stats):
        continue

    cls = _primary_class(dj.get("dnd_class") or "Fighter")
    base = CLASS_ARRAYS.get(cls, DEFAULT_ARRAY)
    new_stats = _seeded_vary(base, f"{r['name']}:{cls}")

    # Preserve any fields already in stats (class, subclass, level, multiclass)
    stats.update(new_stats)
    dj["stats"] = stats

    cur2.execute(
        "UPDATE npcs SET data_json=%s WHERE id=%s",
        (json.dumps(dj, ensure_ascii=False), r["id"])
    )
    print(f"  Fixed [{cls:15}] {r['name']}: {new_stats}")
    fixed += 1

db.commit()
print(f"\nDone — {fixed} NPCs updated")
