import mysql.connector, json, sys
sys.path.insert(0, ".")

db = mysql.connector.connect(
    host="localhost", user="Claude",
    password="WXdCPJmeDfaQALaktzF6!", database="tower_bot"
)
cur = db.cursor(dictionary=True)

# ── Aldric Vane ───────────────────────────────────────────────────────────────
cur.execute("SELECT id FROM npcs WHERE name='Aldric Vane'")
if cur.fetchone():
    print("Aldric already exists — skipping")
else:
    leader_data = {
        "age": "200", "level": 18, "dnd_class": "Fighter", "subclass": "Battle Master",
        "species": "Human", "gender": "Male",
        "appearance": (
            "Enormous even by adventurer standards. Broad shoulders that fill a doorframe, "
            "arms like bridge cables, a jaw like a stone shelf. Wears worn guild leathers "
            "that have been let out three times. A faded scar runs from left ear to chin — "
            "he does not remember how he got it."
        ),
        "motivation": "Keep the Guild running. Keep adventurers alive. Do not ask questions he cannot answer.",
        "stats": {"class": "Fighter", "subclass": "Battle Master", "level": 18, "multiclass": []},
        "rank": "Guildmaster",
        "history": [
            "Founded or inherited leadership of the Adventurers Guild approximately 200 years ago.",
            "Memory completely wiped 150 years ago — no recollection of the first 50 years, his origins, or why he stayed.",
            "Has led the Guild with consistent calm authority for 150 years without knowing what he is building toward.",
        ],
        "relationships": {
            "Mari Fen": "trusted front desk manager",
            "Sera Vane": "Elven wife who still holds blurry fragments of his past",
        },
    }
    aldric_oracle = (
        "Aldric is approximately 200 years old. For 150 of those years his memory has been completely wiped — "
        "he has no recollection of who he was before, how he came to lead the Guild, or what happened to him. "
        "He does not know what was taken. He functions with total authority and calm competence, but carries a "
        "hollowness he does not discuss. His Elven wife Sera Vane spent an enormous amount of Kharma to hold "
        "onto fragments of what she remembers of him — those memories are blurry and incomplete. "
        "Players who dig into very old Guild records or pre-Dome history may find references to an Aldric that "
        "predate his current self by decades. He is physically enormous — level 18 Battle Master Fighter — "
        "and has been running the Guild on muscle memory and instinct for 150 years without knowing why he cares."
    )
    cur2 = db.cursor()
    cur2.execute(
        "INSERT INTO npcs (name, faction, role, location, status, `rank`, motivation, oracle_notes, data_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            "Aldric Vane",
            "Adventurers Guild",
            "Guildmaster of the Adventurers Guild. Sets policy, arbitrates rank disputes, signs off on "
            "high-tier contracts, and personally reviews every death report. Rarely seen outside the Guild "
            "hall. Speaks little but carries enormous presence.",
            "Adventurers Guild Hall, Grand Forum",
            "alive", "Guildmaster",
            "Keep the Guild running. Keep adventurers alive. Do not ask questions he cannot answer.",
            aldric_oracle,
            json.dumps(leader_data, ensure_ascii=False),
        )
    )
    db.commit()
    print("Aldric Vane created, id:", cur2.lastrowid)

# ── Sera Vane ─────────────────────────────────────────────────────────────────
cur.execute("SELECT id FROM npcs WHERE name='Sera Vane'")
if cur.fetchone():
    print("Sera already exists — skipping")
else:
    sera_data = {
        "age": "200+", "level": 18, "dnd_class": "Sorcerer / Bard / Rogue",
        "subclass": "Wild Magic / College of Whispers / Mastermind",
        "species": "Elf", "gender": "Female",
        "appearance": (
            "Willowy even for an elf, with silver hair she keeps loosely braided and pale amber eyes "
            "that occasionally lose focus mid-conversation — she is often half-listening to something "
            "else. Dresses simply. Carries a small journal she never lets anyone else read."
        ),
        "motivation": "Hold on to what is left. Keep Aldric safe. Find out what happened to both of them.",
        "stats": {
            "class": "Sorcerer / Bard / Rogue",
            "subclass": "Wild Magic / College of Whispers / Mastermind",
            "level": 18,
            "multiclass": [
                {"class": "Sorcerer", "subclass": "Wild Magic", "level": 8},
                {"class": "Bard", "subclass": "College of Whispers", "level": 6},
                {"class": "Rogue", "subclass": "Mastermind", "level": 4},
            ]
        },
        "rank": "Guildmaster's Wife",
        "history": [
            "Has been with Aldric for approximately 200 years.",
            "When his memory was wiped 150 years ago she spent an enormous amount of Kharma to resist the same wipe.",
            "The Kharma held — but the memories are blurry, incomplete, and sometimes contradict each other.",
            "She keeps a private journal of every fragment she can still reach.",
            "She does not know who did this to them or why.",
        ],
        "relationships": {
            "Aldric Vane": "husband — she remembers more of him than he does of himself",
            "Mari Fen": "cordial, occasional visitor to the Guild hall",
        },
        "secret": (
            "Her journal contains fragments that, assembled correctly, would point to who wiped their memories "
            "and why. She has not assembled them correctly yet. She is afraid of what the answer is."
        ),
    }
    sera_oracle = (
        "Sera Vane is an Elf, approximately 200 years old, and has been with Aldric Vane since before his memory wipe. "
        "When the wipe happened 150 years ago she spent a massive amount of Kharma to hold onto her own memories of him. "
        "It worked — but the memories are fragmentary, blurry, and sometimes internally inconsistent. "
        "She keeps a private journal of every fragment she can still access. "
        "She is level 18 across Sorcerer (Wild Magic 8) / Bard (College of Whispers 6) / Rogue (Mastermind 4) — "
        "a combination built over two centuries for surviving situations where raw power is not enough. "
        "She does not advertise what she knows or what she is. She appears to be a quiet, slightly distracted woman "
        "who visits the Guild hall occasionally. She is not. "
        "Her journal, if the party ever gains access to it, is a significant plot hook — assembled correctly, "
        "its fragments point toward who wiped their memories and why. She has not assembled them correctly. "
        "She is afraid of what the answer is."
    )
    cur2 = db.cursor()
    cur2.execute(
        "INSERT INTO npcs (name, faction, role, location, status, `rank`, motivation, oracle_notes, secret, data_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            "Sera Vane",
            "Adventurers Guild",
            "Wife of Aldric Vane, Guildmaster of the Adventurers Guild. No official role. Occasional presence "
            "at the Guild hall. Older than most buildings in this district.",
            "Varies — seen near the Guild hall, Archive Row, and occasionally the Sanctum Quarter",
            "alive", "Guildmaster's Wife",
            "Hold on to what is left. Keep Aldric safe. Find out what happened to both of them.",
            sera_oracle,
            "Her private journal contains fragments that point to who wiped their memories. She has not "
            "assembled them correctly yet and is afraid of what the answer is.",
            json.dumps(sera_data, ensure_ascii=False),
        )
    )
    db.commit()
    print("Sera Vane created, id:", cur2.lastrowid)

# ── Update faction_reputation leader field ─────────────────────────────────────
cur3 = db.cursor()
cur3.execute(
    "UPDATE faction_reputation SET leader='Aldric Vane (Guildmaster)' WHERE faction_name='Adventurers Guild'"
)
db.commit()
print("faction_reputation leader updated:", cur3.rowcount, "row")
