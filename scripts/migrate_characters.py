"""
Migrate campaign_docs/character_memory.txt into player_characters table.
Each ---CHARACTER--- block becomes one row.
Run with system Python: C:/Program Files/Python311/python.exe
"""
import re, json, pathlib
import mysql.connector

DOCS = pathlib.Path("campaign_docs")
MEM_FILE = DOCS / "character_memory.txt"

conn = mysql.connector.connect(
    host="localhost", user="Claude",
    password="WXdCPJmeDfaQALaktzF6!", database="tower_bot",
    charset="utf8mb4", collation="utf8mb4_unicode_ci"
)
cur = conn.cursor(dictionary=True)

# Make sure player_characters has an oracle_notes + raw_block column
try:
    cur.execute("ALTER TABLE player_characters ADD COLUMN oracle_notes TEXT")
    print("Added oracle_notes column")
except Exception as e:
    print(f"oracle_notes column: {e}")

try:
    cur.execute("ALTER TABLE player_characters ADD COLUMN raw_block TEXT")
    print("Added raw_block column")
except Exception as e:
    print(f"raw_block column: {e}")

conn.commit()

# Parse character_memory.txt
text = MEM_FILE.read_text(encoding="utf-8", errors="replace")
blocks = [b.strip() for b in text.split("---CHARACTER---") if b.strip() and "NAME:" in b]
print(f"Found {len(blocks)} character blocks")

def extract(block, field):
    m = re.search(rf"^{field}:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else ""

inserted = updated = 0
for block in blocks:
    name = extract(block, "NAME")
    if not name:
        continue
    player = extract(block, "PLAYER")
    species = extract(block, "SPECIES")
    cls = extract(block, "CLASS")
    oracle = extract(block, "ORACLE NOTES")

    # Build a profile_json with all parsed fields
    profile = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith("#"):
            k, _, v = line.partition(":")
            k = k.strip().upper().replace(" ", "_")
            if k and v.strip():
                profile[k] = v.strip()

    # Check if already in DB
    cur.execute("SELECT id FROM player_characters WHERE name=%s", (name,))
    row = cur.fetchone()
    if row:
        cur.execute(
            """UPDATE player_characters
               SET class_name=%s, species=%s, player_name=%s,
                   oracle_notes=%s, raw_block=%s,
                   profile_json=%s, updated_at=NOW()
               WHERE id=%s""",
            (cls, species, player, oracle, block,
             json.dumps(profile, ensure_ascii=False), row["id"])
        )
        updated += 1
        print(f"  Updated: {name}")
    else:
        cur.execute(
            """INSERT INTO player_characters
               (name, class_name, species, player_name, oracle_notes,
                raw_block, profile_json, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())""",
            (name, cls, species, player, oracle, block,
             json.dumps(profile, ensure_ascii=False))
        )
        inserted += 1
        print(f"  Inserted: {name}")

conn.commit()
cur.execute("SELECT COUNT(*) as cnt FROM player_characters")
print(f"\nDone. Inserted={inserted} Updated={updated} Total={cur.fetchone()['cnt']}")
cur.close()
conn.close()
