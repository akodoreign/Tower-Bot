"""Update Aldric and Sera Vane with the 99th floor backstory."""
import mysql.connector, json, sys
sys.path.insert(0, ".")

db = mysql.connector.connect(
    host="localhost", user="Claude",
    password="WXdCPJmeDfaQALaktzF6!", database="tower_bot"
)
cur = db.cursor(dictionary=True)
cur2 = db.cursor()

# ── Sera Vane ──────────────────────────────────────────────────────────────────
sera_oracle = (
    "Sera Vane is an Elf, approximately 200 years old, and has been with Aldric Vane since before the wipe. "
    "What she knows is that Aldric sacrificed every one of his memories and stories to attempt the 99th floor "
    "of the Tower. He gave everything he had ever been to make that attempt. "
    "Sera refused to let go of her stories of him. She had run lean the entire journey — saving Kharma instead "
    "of spending it — and used every last point to hold onto their connection when he let his go. "
    "It worked. She remembers. But reading the journal makes her unbearably sad — it is easier, day to day, "
    "to let it stay half-forgotten and just feel the love that has no story attached to it anymore. "
    "She does not resent him. She understands exactly why he did it. "
    "She is level 18 across Sorcerer (Wild Magic 8) / Bard (College of Whispers 6) / Rogue (Mastermind 4). "
    "She appears to be a quiet, slightly distracted woman who loves her husband. That is true. It is just not all of it."
)

sera_secret = (
    "Aldric sacrificed all his memories to attempt the 99th floor of the Tower. "
    "Sera spent every point of Kharma she had ever saved to hold onto her stories of him and keep their connection. "
    "She keeps a journal of what she managed to preserve. She does not open it often — it makes her grieve a version "
    "of him that still exists physically in front of her but cannot remember being that person. "
    "She has made peace with loving what remains. She has not fully made peace with what the Tower floor cost them."
)

# history goes in data_json since there is no history column
cur.execute("SELECT data_json FROM npcs WHERE id=260")
row = cur.fetchone()
dj = json.loads(row["data_json"]) if isinstance(row["data_json"], str) else (row["data_json"] or {})
dj["history"] = [
    "Has been with Aldric Vane for approximately 200 years.",
    "Aldric sacrificed all his memories and stories to attempt the 99th floor of the Tower.",
    "Sera ran lean the entire journey — saving Kharma rather than spending it — and used every point to hold onto her stories of him and their connection.",
    "The Kharma held. She remembers. But the memories are blurry and reading the journal grieves her deeply.",
    "Day to day it is easier to let it stay half-forgotten and just feel the love that no longer has a story attached to it.",
    "She does not resent him. She understands exactly why he did it.",
]

cur2.execute(
    "UPDATE npcs SET oracle_notes=%s, secret=%s, data_json=%s WHERE id=260",
    (sera_oracle, sera_secret, json.dumps(dj, ensure_ascii=False))
)
db.commit()
print("Sera updated:", cur2.rowcount)

# ── Aldric Vane ────────────────────────────────────────────────────────────────
aldric_oracle = (
    "Aldric is approximately 200 years old. He sacrificed every memory and story he had ever lived to attempt "
    "the 99th floor of the Tower. He does not remember making that choice. He does not remember what he gave up, "
    "who he was before, or that his wife spent everything she had saved to hold onto him when he let go. "
    "He functions with total authority and calm competence but carries a hollowness he cannot name. "
    "He does not know what was taken — only that something should be there and is not. "
    "Level 18 Battle Master Fighter. Has been running the Guild on instinct for 150 years without knowing why "
    "it matters to him. It matters because it mattered to who he was. He has no access to that person anymore."
)

aldric_secret = (
    "He voluntarily sacrificed every memory he had ever made to attempt the 99th floor of the Tower. "
    "He did not tell Sera beforehand. She found out when he came back empty. "
    "He does not know he made this choice. He does not know the Tower took it as payment."
)

cur2.execute(
    "UPDATE npcs SET oracle_notes=%s, secret=%s WHERE id=259",
    (aldric_oracle, aldric_secret)
)
db.commit()
print("Aldric updated:", cur2.rowcount)

# Verify
cur.execute("SELECT name, oracle_notes, secret FROM npcs WHERE id IN (259,260)")
for r in cur.fetchall():
    print(f"\n{r['name']}")
    print(f"  oracle: {(r['oracle_notes'] or '')[:100]}...")
    print(f"  secret: {(r['secret'] or '')[:100]}...")
