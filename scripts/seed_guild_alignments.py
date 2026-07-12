"""
seed_guild_alignments.py

1. Adds `alignment` column to faction_reputation
2. Creates faction_affiliations table (guild_name, faction_name, affiliation_type, strength)
3. Sets 5e alignment for all 24 guilds
4. Inserts guild→major-faction affiliations

affiliation_type: sponsor | partner | client | rival
strength:         primary | secondary | loose

Missions posted by a guild use their primary sponsor's faction tag
so reputation systems and mission filters stay consistent.

Safe to re-run (idempotent).
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from src.db_api import raw_execute, raw_query

# ---------------------------------------------------------------------------
# Step 1: Schema changes
# ---------------------------------------------------------------------------

def ensure_schema():
    cols = {r["Field"] for r in raw_query("DESCRIBE faction_reputation")}
    if "alignment" not in cols:
        raw_execute("ALTER TABLE faction_reputation ADD COLUMN alignment VARCHAR(30) NULL AFTER motto")
        print("  Added alignment column to faction_reputation")
    else:
        print("  alignment column already exists")

    raw_execute("""
        CREATE TABLE IF NOT EXISTS faction_affiliations (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            guild_name       VARCHAR(100) NOT NULL,
            faction_name     VARCHAR(100) NOT NULL,
            affiliation_type VARCHAR(30)  NOT NULL DEFAULT 'partner',
            strength         VARCHAR(20)  NOT NULL DEFAULT 'secondary',
            notes            TEXT,
            created_at       DATETIME DEFAULT NOW(),
            UNIQUE KEY uq_guild_faction (guild_name(80), faction_name(80))
        )
    """)
    print("  faction_affiliations table ready")


# ---------------------------------------------------------------------------
# Step 2: Alignments for the 24 guilds
# ---------------------------------------------------------------------------
# Format: guild_name -> alignment string (5e 5.5e standard)
ALIGNMENTS = {
    "Flying Fleet (Guild)":             "Lawful Neutral",
    "Ironworks Combine (Guild)":        "Lawful Neutral",
    "Crystal Lens Syndicate (Guild)":   "Lawful Evil",
    "Tidecrest Exchange (Guild)":       "Lawful Neutral",
    "Hearthwall Builders (Guild)":      "Lawful Good",
    "Aurelius Medicant (Guild)":        "Neutral Good",
    "The Long Plate (Guild)":           "Neutral Good",
    "Silkthread Market (Guild)":        "True Neutral",
    "Deepvein Extractors (Guild)":      "Lawful Neutral",
    "Arclight Engineers (Guild)":       "Lawful Neutral",
    "Wayfarer's Congress (Guild)":      "True Neutral",
    "Clearwater Authority (Guild)":     "Lawful Good",
    "The Grand Register (Guild)":       "Lawful Neutral",
    "Brightfire Entertainers (Guild)":  "Chaotic Neutral",
    "Thornwall Security (Guild)":       "Lawful Neutral",
    "Ashcraft Reclamation (Guild)":     "True Neutral",
    "Goldenleaf Hospitality (Guild)":   "Lawful Neutral",
    "Mirrorgate Communications (Guild)":"Lawful Neutral",
    "Spellwright Collective (Guild)":   "True Neutral",
    "The Stonecrown Council (Guild)":   "Lawful Evil",
    "Verdant Gardens (Guild)":          "Neutral Good",
    "Irondraft Logistics (Guild)":      "Lawful Neutral",
    "The Polished Seal (Guild)":        "Lawful Neutral",
    "Runemark Academy (Guild)":         "Lawful Good",
}


# ---------------------------------------------------------------------------
# Step 3: Guild → major faction affiliations
# affiliation_type: sponsor (they fund/direct missions), partner (mutual benefit),
#                   client (guild serves the faction), rival (opposed interests)
# strength: primary, secondary, loose
# ---------------------------------------------------------------------------
AFFILIATIONS: list[dict] = [
    # --- Flying Fleet ---
    {"guild": "Flying Fleet (Guild)", "faction": "Tower Authority / FTA",  "type": "client",  "strength": "primary",   "notes": "City mail and official passenger contracts"},
    {"guild": "Flying Fleet (Guild)", "faction": "Argent Blades",          "type": "client",  "strength": "secondary", "notes": "Military rapid-transport contracts"},
    {"guild": "Flying Fleet (Guild)", "faction": "Iron Fang Consortium",   "type": "client",  "strength": "loose",     "notes": "Freight smuggling routes, deniable"},

    # --- Ironworks Combine ---
    {"guild": "Ironworks Combine (Guild)", "faction": "Leaden Crown",          "type": "sponsor", "strength": "primary",   "notes": "Industrial backing and foundry investments"},
    {"guild": "Ironworks Combine (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "secondary", "notes": "City infrastructure build contracts"},
    {"guild": "Ironworks Combine (Guild)", "faction": "Iron Fang Consortium",  "type": "client",  "strength": "loose",     "notes": "Weapons-grade manufacturing, off-book"},

    # --- Crystal Lens Syndicate ---
    {"guild": "Crystal Lens Syndicate (Guild)", "faction": "Serpent Choir",         "type": "sponsor", "strength": "primary",   "notes": "Intelligence pipeline and data-market contracts"},
    {"guild": "Crystal Lens Syndicate (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "secondary", "notes": "Official surveillance grid maintenance"},
    {"guild": "Crystal Lens Syndicate (Guild)", "faction": "Obsidian Lotus",        "type": "partner", "strength": "loose",     "notes": "Discreet optics work, no questions asked"},

    # --- Tidecrest Exchange ---
    {"guild": "Tidecrest Exchange (Guild)", "faction": "Iron Fang Consortium",  "type": "sponsor", "strength": "primary",   "notes": "Trade financing and merchant banking arm"},
    {"guild": "Tidecrest Exchange (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "secondary", "notes": "Official treasury and city bond management"},
    {"guild": "Tidecrest Exchange (Guild)", "faction": "Leaden Crown",          "type": "partner", "strength": "loose",     "notes": "Industrial loan portfolios"},

    # --- Hearthwall Builders ---
    {"guild": "Hearthwall Builders (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "primary",   "notes": "City infrastructure and district maintenance contracts"},
    {"guild": "Hearthwall Builders (Guild)", "faction": "Patchwork Saints",      "type": "partner", "strength": "secondary", "notes": "Building clinics, shelters, and aid stations"},
    {"guild": "Hearthwall Builders (Guild)", "faction": "Wardens of Ash",        "type": "partner", "strength": "loose",     "notes": "Sustainable materials and green-build initiatives"},

    # --- Aurelius Medicant ---
    {"guild": "Aurelius Medicant (Guild)", "faction": "Patchwork Saints",      "type": "sponsor", "strength": "primary",   "notes": "Medical aid co-operation and staff secondments"},
    {"guild": "Aurelius Medicant (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "secondary", "notes": "Public health mandate contracts"},
    {"guild": "Aurelius Medicant (Guild)", "faction": "Glass Sigil",           "type": "partner", "strength": "loose",     "notes": "Magical medicine research sharing"},

    # --- The Long Plate ---
    {"guild": "The Long Plate (Guild)", "faction": "Patchwork Saints",      "type": "sponsor", "strength": "primary",   "notes": "Feeding the poor districts, ration distributions"},
    {"guild": "The Long Plate (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "secondary", "notes": "City ration contracts and emergency food reserves"},
    {"guild": "The Long Plate (Guild)", "faction": "Wardens of Ash",        "type": "partner", "strength": "loose",     "notes": "Sustainable light-farm and growing practices"},

    # --- Silkthread Market ---
    {"guild": "Silkthread Market (Guild)", "faction": "Iron Fang Consortium",   "type": "client",  "strength": "primary",   "notes": "Luxury goods import financing and trade route access"},
    {"guild": "Silkthread Market (Guild)", "faction": "Obsidian Lotus",         "type": "partner", "strength": "secondary", "notes": "Black market fashion and exclusive contraband textiles"},
    {"guild": "Silkthread Market (Guild)", "faction": "Tower Authority / FTA",  "type": "client",  "strength": "loose",     "notes": "Official textile standards and import licensing"},

    # --- Deepvein Extractors ---
    {"guild": "Deepvein Extractors (Guild)", "faction": "Leaden Crown",          "type": "sponsor", "strength": "primary",   "notes": "Primary mining operations investor and ore buyer"},
    {"guild": "Deepvein Extractors (Guild)", "faction": "Iron Fang Consortium",  "type": "client",  "strength": "secondary", "notes": "Ore and mineral trading through Consortium markets"},
    {"guild": "Deepvein Extractors (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "loose",     "notes": "Extraction permits and subsurface rights"},

    # --- Arclight Engineers ---
    {"guild": "Arclight Engineers (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "primary",   "notes": "City power grid and infrastructure maintenance mandate"},
    {"guild": "Arclight Engineers (Guild)", "faction": "Wizards Tower",         "type": "partner", "strength": "secondary", "notes": "Arcane power research and conduit enchantment"},
    {"guild": "Arclight Engineers (Guild)", "faction": "Glass Sigil",           "type": "partner", "strength": "loose",     "notes": "Magical systems integration"},

    # --- Wayfarer's Congress ---
    {"guild": "Wayfarer's Congress (Guild)", "faction": "Adventurers Guild",    "type": "sponsor", "strength": "primary",   "notes": "Mission logistics, supply runs, party resupply"},
    {"guild": "Wayfarer's Congress (Guild)", "faction": "Iron Fang Consortium", "type": "client",  "strength": "secondary", "notes": "Merchant freight and trade route contracts"},
    {"guild": "Wayfarer's Congress (Guild)", "faction": "Tower Authority / FTA","type": "client",  "strength": "loose",     "notes": "Official postal and government courier routes"},

    # --- Clearwater Authority ---
    {"guild": "Clearwater Authority (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "primary",   "notes": "City sanitation and water services mandate"},
    {"guild": "Clearwater Authority (Guild)", "faction": "Patchwork Saints",      "type": "partner", "strength": "secondary", "notes": "Clean water for clinics and aid stations"},
    {"guild": "Clearwater Authority (Guild)", "faction": "Wardens of Ash",        "type": "partner", "strength": "loose",     "notes": "Environmental water quality initiatives"},

    # --- The Grand Register ---
    {"guild": "The Grand Register (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "primary",   "notes": "Official record-keeping and notarization authority"},
    {"guild": "The Grand Register (Guild)", "faction": "Iron Fang Consortium",  "type": "client",  "strength": "secondary", "notes": "Commercial contract drafting and trade arbitration"},
    {"guild": "The Grand Register (Guild)", "faction": "Argent Blades",         "type": "client",  "strength": "loose",     "notes": "Military contracts and mercenary licensing"},

    # --- Brightfire Entertainers ---
    {"guild": "Brightfire Entertainers (Guild)", "faction": "Obsidian Lotus",        "type": "sponsor", "strength": "primary",   "notes": "Vice entertainment pipeline and venue protection"},
    {"guild": "Brightfire Entertainers (Guild)", "faction": "Iron Fang Consortium",  "type": "client",  "strength": "secondary", "notes": "Sponsored arena events and merchant festivals"},
    {"guild": "Brightfire Entertainers (Guild)", "faction": "Adventurers Guild",     "type": "partner", "strength": "loose",     "notes": "Arena management and competition hosting"},

    # --- Thornwall Security ---
    {"guild": "Thornwall Security (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "primary",   "notes": "Licensed security operations and district patrol contracts"},
    {"guild": "Thornwall Security (Guild)", "faction": "Argent Blades",         "type": "partner", "strength": "secondary", "notes": "Military overflow and high-threat response"},
    {"guild": "Thornwall Security (Guild)", "faction": "Iron Fang Consortium",  "type": "client",  "strength": "loose",     "notes": "Corporate facility security contracts"},

    # --- Ashcraft Reclamation ---
    {"guild": "Ashcraft Reclamation (Guild)", "faction": "Leaden Crown",         "type": "client",  "strength": "primary",   "notes": "Industrial waste processing and scrap contracts"},
    {"guild": "Ashcraft Reclamation (Guild)", "faction": "Iron Fang Consortium", "type": "client",  "strength": "secondary", "notes": "Salvageable goods resale through Consortium markets"},
    {"guild": "Ashcraft Reclamation (Guild)", "faction": "Wardens of Ash",       "type": "partner", "strength": "loose",     "notes": "Environmental reclamation and hazardous waste"},

    # --- Goldenleaf Hospitality ---
    {"guild": "Goldenleaf Hospitality (Guild)", "faction": "Iron Fang Consortium",  "type": "client",  "strength": "primary",   "notes": "Business travel accommodation and merchant event hosting"},
    {"guild": "Goldenleaf Hospitality (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "secondary", "notes": "Official state accommodations and diplomatic lodgings"},
    {"guild": "Goldenleaf Hospitality (Guild)", "faction": "Adventurers Guild",     "type": "partner", "strength": "loose",     "notes": "Adventurer lodgings, discount boards, mission briefing rooms"},

    # --- Mirrorgate Communications ---
    {"guild": "Mirrorgate Communications (Guild)", "faction": "Serpent Choir",         "type": "sponsor", "strength": "primary",   "notes": "Discreet message relay and information network contracts"},
    {"guild": "Mirrorgate Communications (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "secondary", "notes": "Official communications and government message relay"},
    {"guild": "Mirrorgate Communications (Guild)", "faction": "Adventurers Guild",     "type": "partner", "strength": "loose",     "notes": "Mission coordination and party contact relay"},

    # --- Spellwright Collective ---
    {"guild": "Spellwright Collective (Guild)", "faction": "Wizards Tower",         "type": "sponsor", "strength": "primary",   "notes": "Arcane R&D funding and research partnership"},
    {"guild": "Spellwright Collective (Guild)", "faction": "Glass Sigil",           "type": "partner", "strength": "secondary", "notes": "Enchantment trade and component supply"},
    {"guild": "Spellwright Collective (Guild)", "faction": "Guild of Ashen Scrolls","type": "partner", "strength": "loose",     "notes": "Magical scholarship and documentation"},

    # --- The Stonecrown Council ---
    {"guild": "The Stonecrown Council (Guild)", "faction": "Leaden Crown",          "type": "sponsor", "strength": "primary",   "notes": "Property empire backing and expansion capital"},
    {"guild": "The Stonecrown Council (Guild)", "faction": "Iron Fang Consortium",  "type": "client",  "strength": "secondary", "notes": "Commercial real estate and merchant district holdings"},
    {"guild": "The Stonecrown Council (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "loose",     "notes": "Official property registrar and land title authority"},

    # --- Verdant Gardens ---
    {"guild": "Verdant Gardens (Guild)", "faction": "Wardens of Ash",        "type": "sponsor", "strength": "primary",   "notes": "Environmental mission alignment and seed funding"},
    {"guild": "Verdant Gardens (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "secondary", "notes": "Public parks and fountain plaza contracts"},
    {"guild": "Verdant Gardens (Guild)", "faction": "Patchwork Saints",      "type": "partner", "strength": "loose",     "notes": "Healing gardens and botanical aid station supplies"},

    # --- Irondraft Logistics ---
    {"guild": "Irondraft Logistics (Guild)", "faction": "Leaden Crown",          "type": "client",  "strength": "primary",   "notes": "Industrial heavy-freight and ore-shipment contracts"},
    {"guild": "Irondraft Logistics (Guild)", "faction": "Iron Fang Consortium",  "type": "client",  "strength": "secondary", "notes": "Cargo port management and merchant freight"},
    {"guild": "Irondraft Logistics (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "loose",     "notes": "Military supply chain and official heavy cargo"},

    # --- The Polished Seal ---
    {"guild": "The Polished Seal (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "primary",   "notes": "Regulatory compliance body and official arbitration authority"},
    {"guild": "The Polished Seal (Guild)", "faction": "Iron Fang Consortium",  "type": "client",  "strength": "secondary", "notes": "Commercial risk management and merchant bond insurance"},
    {"guild": "The Polished Seal (Guild)", "faction": "Argent Blades",         "type": "client",  "strength": "loose",     "notes": "Mercenary contract insurance and liability bonds"},

    # --- Runemark Academy ---
    {"guild": "Runemark Academy (Guild)", "faction": "Adventurers Guild",     "type": "sponsor", "strength": "primary",   "notes": "Skills certification and adventurer licensing partnership"},
    {"guild": "Runemark Academy (Guild)", "faction": "Tower Authority / FTA", "type": "client",  "strength": "secondary", "notes": "Official professional licensing and certification authority"},
    {"guild": "Runemark Academy (Guild)", "faction": "Guild of Ashen Scrolls","type": "partner", "strength": "loose",     "notes": "Academic curriculum and scholarly exchange"},
    {"guild": "Runemark Academy (Guild)", "faction": "Wizards Tower",         "type": "partner", "strength": "loose",     "notes": "Arcane education programs"},
]


def main():
    print("=== Step 1: Schema ===")
    ensure_schema()

    print("\n=== Step 2: Set alignments ===")
    updated = 0
    for guild_name, alignment in ALIGNMENTS.items():
        n = raw_execute(
            "UPDATE faction_reputation SET alignment=%s WHERE faction_name=%s AND (alignment IS NULL OR alignment='')",
            (alignment, guild_name)
        )
        if n:
            print(f"  {guild_name!r:45} -> {alignment}")
            updated += 1
        else:
            print(f"  SKIP {guild_name!r} (already set or not found)")
    print(f"  => {updated} alignments set")

    print("\n=== Step 3: Insert affiliations ===")
    inserted = 0
    for a in AFFILIATIONS:
        try:
            raw_execute(
                "INSERT INTO faction_affiliations (guild_name, faction_name, affiliation_type, strength, notes) "
                "VALUES (%s,%s,%s,%s,%s)",
                (a["guild"], a["faction"], a["type"], a["strength"], a["notes"])
            )
            inserted += 1
        except Exception as e:
            if "Duplicate" in str(e):
                pass  # already exists
            else:
                print(f"  ERROR {a['guild']} -> {a['faction']}: {e}")
    print(f"  => {inserted} affiliations inserted")

    print("\n=== Summary: guild affiliations ===")
    rows = raw_query("""
        SELECT guild_name, faction_name, affiliation_type, strength
        FROM faction_affiliations
        ORDER BY guild_name, strength DESC, affiliation_type
    """)
    last = ""
    for r in rows:
        if r["guild_name"] != last:
            print(f"\n  {r['guild_name']}")
            last = r["guild_name"]
        print(f"    [{r['strength']:9}] {r['affiliation_type']:8} -> {r['faction_name']}")


if __name__ == "__main__":
    main()
    print("\nDone.")
