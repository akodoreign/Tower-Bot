"""
seed_mega_guilds.py — Insert 24 Mega-Guilds into faction_reputation,
create new NPC parties for guilds with no existing ones, and assign
all parties to their management guilds.

Run once: python scripts/seed_mega_guilds.py
Safe to re-run (skips existing entries).
"""
from __future__ import annotations
import json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.db_api import raw_execute, raw_query

# ---------------------------------------------------------------------------
# 24 Mega-Guilds
# ---------------------------------------------------------------------------
GUILDS = [
    {
        "faction_name":    "Flying Fleet (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Guildmistress Zara Windveil",
        "location_name":   "Upper Tier Spires",
        "description":     "The city's dominant air freight and passenger transport network. Skycraft, tethered airships, and magitech drones connect every district above street level.",
        "motto":           "Distance is a tax. We collect it.",
    },
    {
        "faction_name":    "Ironworks Combine (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Forge-Master Denn Ashkeel",
        "location_name":   "Ironworks District",
        "description":     "The largest heavy manufacturing collective in the Undercity. Smelting, fabrication, and weapons-grade production run day and night in vast forge-halls.",
        "motto":           "We build what holds the city up.",
    },
    {
        "faction_name":    "Crystal Lens Syndicate (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Director Pale Morren",
        "location_name":   "Archive Row",
        "description":     "Intelligence brokers and optic-tech specialists. Scrying arrays, data-markets, camera networks, and information arbitrage on a city-wide scale.",
        "motto":           "See everything. Sell selectively.",
    },
    {
        "faction_name":    "Tidecrest Exchange (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Chief Comptroller Vasen Auric",
        "location_name":   "Grand Forum",
        "description":     "The dominant financial institution. EC exchange, trade financing, insurance bonds, and the city's largest private treasury behind marble columns.",
        "motto":           "Your coin, our keep.",
    },
    {
        "faction_name":    "Hearthwall Builders (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Chief Architect Mara Stonecroft",
        "location_name":   "Guild Spires",
        "description":     "City-builders from luxury towers to sewer maintenance. Structural contracts span every district and outlast every administration.",
        "motto":           "We raise it, we maintain it, we outlast it.",
    },
    {
        "faction_name":    "Aurelius Medicant (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "High Medicant Cael Voss",
        "location_name":   "Sanctum Quarter",
        "description":     "The largest private medical network. Gleaming clinics in wealthy districts, triage posts in the warrens, potion supply chains, and cutting-edge trauma research.",
        "motto":           "Pain is a problem. We are the solution.",
    },
    {
        "faction_name":    "The Long Plate (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Supply Master Brinna Loam",
        "location_name":   "Hearthstone District",
        "description":     "Light-farms, fungal vats, imported produce, and city-wide provisioning contracts. If the Undercity eats today, The Long Plate likely had a hand in it.",
        "motto":           "Full bellies make quiet streets.",
    },
    {
        "faction_name":    "Silkthread Market (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Tailor-Royal Sienna Drape",
        "location_name":   "Floating Bazaar",
        "description":     "Designer wardrobes for the elite, serviceable cloth for the masses. Silkthread controls most textile imports and runs the city's most-visited fashion arcades.",
        "motto":           "Dress the city. Know its worth.",
    },
    {
        "faction_name":    "Deepvein Extractors (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Bore-Captain Grael Dusthammer",
        "location_name":   "Outer Wall",
        "description":     "Rock drilling, ore extraction, and subsurface surveying. The city sits atop their excavation work. Loud, dirty, indispensable.",
        "motto":           "The wealth runs deeper.",
    },
    {
        "faction_name":    "Arclight Engineers (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Prime Engineer Tessla Voltmane",
        "location_name":   "Arclight Quarter",
        "description":     "The power grid, magitech infrastructure, and enchanted systems that keep the Undercity lit and running. Polished offices above; glowing conduit-tunnels below.",
        "motto":           "Charge everything. Lose nothing.",
    },
    {
        "faction_name":    "Wayfarer's Congress (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Road-Marshal Birch Callan",
        "location_name":   "Markets Infinite",
        "description":     "Ground-level freight, cart networks, and overland caravan management. The backbone of street-level commerce, with a fleet of runners, wagons, and portal-linked depots.",
        "motto":           "If it moves, we moved it first.",
    },
    {
        "faction_name":    "Clearwater Authority (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Director Ysen Pureflow",
        "location_name":   "Sanctum Quarter",
        "description":     "Manages the city's water filtration, sewage processing, and dome air-cycling systems. Quietly essential; their offices smell of clean rainfall and fresh paper.",
        "motto":           "Clean water. Clean air. Clean city.",
    },
    {
        "faction_name":    "The Grand Register (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "First Registrar Aldous Penn",
        "location_name":   "Archive Row",
        "description":     "Contract drafting, legal arbitration, official notarization, and the city's most complete civil records vault. Their word is legally binding.",
        "motto":           "Nothing real is unwritten.",
    },
    {
        "faction_name":    "Brightfire Entertainers (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Impresario Lira Velour",
        "location_name":   "Night Pits",
        "description":     "From high opera in marble halls to arena spectacle and street festivals, Brightfire owns the major venues and produces the city's entertainment calendar.",
        "motto":           "We sell the dream. Keep buying.",
    },
    {
        "faction_name":    "Thornwall Security (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Commander-General Sten Holt",
        "location_name":   "Guild Spires",
        "description":     "The Undercity's largest licensed security contractor. Corporate guards, bounty hunters, and district patrol contracts. Disciplined, expensive, effective.",
        "motto":           "We stand between order and the alternative.",
    },
    {
        "faction_name":    "Ashcraft Reclamation (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Salvage-Prime Rovi Cinder",
        "location_name":   "Scrapworks",
        "description":     "Nothing is wasted in the Undercity. Ashcraft recovers, repurposes, and resells everything from scrap iron to expired spell matrices. Their yards sprawl.",
        "motto":           "Your waste is our commodity.",
    },
    {
        "faction_name":    "Goldenleaf Hospitality (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Proprietor-General Maise Tanvale",
        "location_name":   "Neon Row",
        "description":     "Luxury hotels, chain taverns, and catering for every occasion from guild dinners to street festivals. Warmly lit, competitively priced, everywhere.",
        "motto":           "Every guest is a contract.",
    },
    {
        "faction_name":    "Mirrorgate Communications (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Signal-Chief Keris Farwhisper",
        "location_name":   "Coppergate",
        "description":     "Courier networks, magical message relays, and the city's largest signal-post infrastructure. Discretion available at a premium.",
        "motto":           "Your words, delivered intact.",
    },
    {
        "faction_name":    "Spellwright Collective (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Archmage-Regent Selar Vanthorn",
        "location_name":   "Guild Spires",
        "description":     "A coalition of independent mages pooling resources for arcane R&D, spell component supply, and enchantment-for-hire. Their tower floors glow at odd hours.",
        "motto":           "Magic is craft. We are its craftsmen.",
    },
    {
        "faction_name":    "The Stonecrown Council (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Property-Lord Davan Coldmarble",
        "location_name":   "Diplomats Row",
        "description":     "Owns or manages vast commercial and residential property across all districts. Their ledgers determine who lives where and at what price.",
        "motto":           "Every floor belongs to someone.",
    },
    {
        "faction_name":    "Verdant Gardens (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Chief Botanist Alys Greenveil",
        "location_name":   "Hearthstone District",
        "description":     "Manages the city's parks, rooftop gardens, and fountain plazas. Sunshine and fresh air where you least expect it. Also sells rare botanicals to the wealthy.",
        "motto":           "Life grows where we plant it.",
    },
    {
        "faction_name":    "Irondraft Logistics (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Dock-Master Gorath Swale",
        "location_name":   "Ember Ward",
        "description":     "Specialized in moving impossible loads — crane operations, heavy-freight hauling, and major cargo port management. Loud, oily, irreplaceable.",
        "motto":           "We lift what others cannot.",
    },
    {
        "faction_name":    "The Polished Seal (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Grand Arbiter Nora Fairclause",
        "location_name":   "Grand Forum",
        "description":     "Risk assessment, insurance bonds, and contract dispute arbitration. Their offices are spotless. Their terms are iron.",
        "motto":           "Every risk has a price. Ours is worth it.",
    },
    {
        "faction_name":    "Runemark Academy (Guild)",
        "reputation_score": 0,
        "tier":            "Neutral",
        "leader":          "Grandmaster Scholar Elias Wordkeep",
        "location_name":   "Academy Heights",
        "description":     "The city's foremost training and certification institution. Guild-recognized licenses, academic programs, and skills assessment for every profession.",
        "motto":           "Knowledge is the only credential that matters.",
    },
]

# ---------------------------------------------------------------------------
# New NPC parties to create (guilds that had none or too few)
# ---------------------------------------------------------------------------
NEW_PARTIES = [
    # Spellwright Collective
    {"party_name": "The Arcane Chapter",       "faction": "Spellwright Collective (Guild)", "tier": "Recognized",  "visual": "Three robed researchers who speak in overlapping sentences, each finishing the others' thoughts. They carry enchanted reference tablets everywhere."},
    {"party_name": "Glimmerveil Research",     "faction": "Spellwright Collective (Guild)", "tier": "Unknown",     "visual": "A quiet quartet of junior mages in matching slate-grey coats, always slightly singed at the cuffs."},
    {"party_name": "The Resonant Few",         "faction": "Spellwright Collective (Guild)", "tier": "Unknown",     "visual": "Specialists in sympathetic magic. They hum under their breath constantly, which their contractor finds unsettling."},

    # The Stonecrown Council
    {"party_name": "Coldmarble Assessors",     "faction": "The Stonecrown Council (Guild)", "tier": "Recognized",  "visual": "Sharp-dressed property valuers with measuring rods and ledgers. Polite, impersonal, and always looking at your walls more than you."},
    {"party_name": "The Property Clause",      "faction": "The Stonecrown Council (Guild)", "tier": "Unknown",     "visual": "Enforcement specialists in well-ironed shirts. They carry eviction notices and are very sorry about it, professionally speaking."},
    {"party_name": "The Marble Standard",      "faction": "The Stonecrown Council (Guild)", "tier": "Unknown",     "visual": "A mixed party of architects and negotiators who specialize in rezoning disputes and site acquisitions."},

    # Verdant Gardens
    {"party_name": "Greenwatch Company",       "faction": "Verdant Gardens (Guild)",        "tier": "Recognized",  "visual": "Park wardens in leaf-green coats. More capable than their pleasant uniforms suggest — they handle everything from vandalism to rogue fauna."},
    {"party_name": "The Rooftop Accord",       "faction": "Verdant Gardens (Guild)",        "tier": "Unknown",     "visual": "Specialists in vertical garden installation. Arrive with rope kits, soil packs, and an oddly cheerful attitude about heights."},
    {"party_name": "The Fountain Guild",       "faction": "Verdant Gardens (Guild)",        "tier": "Unknown",     "visual": "Water-feature engineers and landscape architects who insist that a well-placed fountain improves any neighborhood. They're probably right."},

    # Irondraft Logistics
    {"party_name": "The Ironlift Crew",        "faction": "Irondraft Logistics (Guild)",    "tier": "Recognized",  "visual": "Six broad-shouldered workers with enchanted harnesses and crane-operating licenses. They have moved things that shouldn't be moveable."},
    {"party_name": "Heavymark & Sons",         "faction": "Irondraft Logistics (Guild)",    "tier": "Unknown",     "visual": "A family operation. Father, two daughters, and an adopted nephew who operates the levitation rig. Very professional. Very loud."},
    {"party_name": "The Deep Haul",            "faction": "Irondraft Logistics (Guild)",    "tier": "Unknown",     "visual": "Specialists in cargo extraction from collapsed or flooded sites. Equipment is battered but reliable. So are they."},

    # Runemark Academy
    {"party_name": "The Scholar's March",      "faction": "Runemark Academy (Guild)",       "tier": "Recognized",  "visual": "Academic assessors who travel in pairs, conducting skills evaluations for guild certification. Carry clipboards. Judge quietly."},
    {"party_name": "Wordkeep Advance",         "faction": "Runemark Academy (Guild)",       "tier": "Unknown",     "visual": "Field trainers who embed with inexperienced teams to assess real-world performance. They observe, advise, and occasionally save lives."},
    {"party_name": "The Ink Standard",         "faction": "Runemark Academy (Guild)",       "tier": "Unknown",     "visual": "Document and records specialists. They travel between guilds preserving institutional knowledge and running short professional courses."},

    # Mirrorgate Communications (boost to 3)
    {"party_name": "The Signal Compact",       "faction": "Mirrorgate Communications (Guild)", "tier": "Unknown",  "visual": "Courier specialists who can deliver a message anywhere in the city within two hours. They know every shortcut and take none for granted."},
    {"party_name": "Whisperline Co.",          "faction": "Mirrorgate Communications (Guild)", "tier": "Unknown",  "visual": "Operators of Mirrorgate's discreet relay network. They pride themselves on never reading what they carry — probably."},

    # Goldenleaf Hospitality (boost to 3)
    {"party_name": "The Warm Standard",        "faction": "Goldenleaf Hospitality (Guild)", "tier": "Unknown",     "visual": "Event planning and catering team. They arrive with tablecloths and a box of emergencies. They've never missed a deadline."},

    # Ashcraft Reclamation (boost to 3)
    {"party_name": "The Cinder Brief",         "faction": "Ashcraft Reclamation (Guild)",   "tier": "Unknown",     "visual": "Hazardous salvage specialists. Fire-resistant gear, chemical knowledge, and a fatalistic sense of humour about what they find."},

    # Silkthread Market (boost to 3)
    {"party_name": "The Thread Count",         "faction": "Silkthread Market (Guild)",      "tier": "Unknown",     "visual": "Inventory auditors and quality inspectors for luxury textile shipments. Exacting, fashionable, and offended by poor stitching."},

    # Clearwater Authority (boost to 3)
    {"party_name": "The Flow Compact",         "faction": "Clearwater Authority (Guild)",   "tier": "Unknown",     "visual": "Emergency water-systems repair team. They're on-call at all hours and somehow always arrive smelling faintly of river water."},
]

# ---------------------------------------------------------------------------
# Definitive party assignments (existing parties → guilds)
# ---------------------------------------------------------------------------
ASSIGNMENTS: dict[str, str] = {
    "Nullpoint Advance":       "Flying Fleet (Guild)",
    "Stormline Company":       "Flying Fleet (Guild)",
    "Saltborn Advance":        "Flying Fleet (Guild)",

    "Ironveil Syndicate":      "Ironworks Combine (Guild)",
    "Fracture Compact":        "Ironworks Combine (Guild)",

    "Hollow March":            "Crystal Lens Syndicate (Guild)",
    "Duskwatch Company":       "Crystal Lens Syndicate (Guild)",

    "Rattlebone & Associates": "Tidecrest Exchange (Guild)",
    "Vaultbreakers":           "Tidecrest Exchange (Guild)",
    "Chains of Fortune":       "Tidecrest Exchange (Guild)",

    "Fallmark Collective":     "Hearthwall Builders (Guild)",
    "Gravelight Company":      "Hearthwall Builders (Guild)",

    "The Patient Accord":      "Aurelius Medicant (Guild)",
    "The Grieving Oath":       "Aurelius Medicant (Guild)",

    "The Long Exhale":         "The Long Plate (Guild)",
    "The Long Standard":       "The Long Plate (Guild)",

    "Ember Writ":              "Silkthread Market (Guild)",
    "The Crumbling Accord":    "Silkthread Market (Guild)",

    "Hollow Crown Expedition": "Deepvein Extractors (Guild)",
    "Ashveil Collective":      "Deepvein Extractors (Guild)",
    "Bonedust Collective":     "Deepvein Extractors (Guild)",
    "Ashmark Brigade":         "Deepvein Extractors (Guild)",

    "The Dim Accord":          "Arclight Engineers (Guild)",
    "The Pale Advance":        "Arclight Engineers (Guild)",

    "The Scoured Path":        "Wayfarer's Congress (Guild)",
    "The Scoured Majority":    "Wayfarer's Congress (Guild)",

    "The Cracked Seal":        "Clearwater Authority (Guild)",
    "The Long Wager":          "Clearwater Authority (Guild)",

    "The Last Petition":       "The Grand Register (Guild)",
    "The Dim Petition":        "The Grand Register (Guild)",
    "Grim Clause Co.":         "The Grand Register (Guild)",

    "The Slow Burn":           "Brightfire Entertainers (Guild)",
    "The Fortunate Doomed":    "Brightfire Entertainers (Guild)",

    "The Fallen Standard":     "Thornwall Security (Guild)",
    "The Unfinished War":      "Thornwall Security (Guild)",
    "Warden's Folly":          "Thornwall Security (Guild)",

    "Ashborn Seven":           "Ashcraft Reclamation (Guild)",

    "The Echoing Pact":        "Goldenleaf Hospitality (Guild)",

    "Irongate Collective":     "Mirrorgate Communications (Guild)",

    "The Pale Contract":       "The Polished Seal (Guild)",
}


def main(dry_run: bool = False):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # -- Guilds ---------------------------------------------------------------
    print("=== Inserting 24 Mega-Guilds ===")
    existing_factions = {r["faction_name"] for r in (raw_query("SELECT faction_name FROM faction_reputation") or [])}
    inserted_guilds = 0
    for g in GUILDS:
        if g["faction_name"] in existing_factions:
            print(f"  SKIP  {g['faction_name']}")
            continue
        if not dry_run:
            raw_execute(
                "INSERT INTO faction_reputation "
                "(faction_name, reputation_score, tier, leader, location_name, description, motto, last_updated) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())",
                (g["faction_name"], g["reputation_score"], g["tier"],
                 g["leader"], g["location_name"], g["description"], g["motto"])
            )
        print(f"  INSERT {g['faction_name']}")
        inserted_guilds += 1
    print(f"  => {inserted_guilds} guilds inserted\n")

    # -- New parties ----------------------------------------------------------
    print("=== Creating new NPC parties ===")
    existing_parties = {r["party_name"] for r in (raw_query("SELECT party_name FROM party_profiles") or [])}
    created = 0
    for p in NEW_PARTIES:
        if p["party_name"] in existing_parties:
            print(f"  SKIP  {p['party_name']}")
            continue
        pj = {
            "name":    p["party_name"],
            "faction": p["faction"],
            "employer": p["faction"],
            "tier":    p["tier"],
            "visual":  p["visual"],
            "points":  1,
        }
        mj = {"name": p["party_name"], "tier": p["tier"], "points": 1, "visual": p["visual"]}
        if not dry_run:
            raw_execute(
                "INSERT INTO party_profiles (party_name, members_json, reputation, formed_at, status, profile_json) "
                "VALUES (%s,%s,%s,%s,'active',%s)",
                (p["party_name"],
                 json.dumps(mj, ensure_ascii=False),
                 1,
                 now,
                 json.dumps(pj, ensure_ascii=False))
            )
        print(f"  CREATE {p['party_name']!r:40} -> {p['faction']}")
        created += 1
    print(f"  => {created} new parties created\n")

    # -- Assign existing parties ----------------------------------------------
    print("=== Assigning existing parties to guilds ===")
    profiles = raw_query("SELECT id, party_name, profile_json FROM party_profiles")
    updated = 0
    for row in profiles:
        pname = row["party_name"]
        guild = ASSIGNMENTS.get(pname)
        if not guild:
            continue
        pj = row.get("profile_json") or {}
        if isinstance(pj, str):
            try: pj = json.loads(pj)
            except: pj = {}
        if pj.get("faction") == guild:
            continue
        pj["faction"] = guild
        pj["employer"] = guild
        if not dry_run:
            raw_execute(
                "UPDATE party_profiles SET profile_json=%s WHERE id=%s",
                (json.dumps(pj, ensure_ascii=False), row["id"])
            )
        print(f"  ASSIGN {pname!r:40} -> {guild}")
        updated += 1
    print(f"  => {updated} existing parties assigned\n")

    # -- Summary --------------------------------------------------------------
    print("=== Parties still unassigned (available for manual guild assignment) ===")
    all_profiles = raw_query("SELECT party_name, profile_json FROM party_profiles")
    for row in all_profiles:
        pj = row.get("profile_json") or {}
        if isinstance(pj, str):
            try: pj = json.loads(pj)
            except: pj = {}
        if not pj.get("faction"):
            print(f"  - {row['party_name']}")

    print("\n=== Guild party counts ===")
    guild_counts: dict[str, int] = {}
    all_profiles2 = raw_query("SELECT profile_json FROM party_profiles")
    for row in all_profiles2:
        pj = row.get("profile_json") or {}
        if isinstance(pj, str):
            try: pj = json.loads(pj)
            except: pj = {}
        f = pj.get("faction") or ""
        if f:
            guild_counts[f] = guild_counts.get(f, 0) + 1
    for gname in sorted(guild_counts):
        print(f"  {guild_counts[gname]:2d}  {gname}")


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    if dry:
        print("=== DRY RUN — no writes ===\n")
    main(dry_run=dry)
    print("\nDone.")
