"""Assign remaining unaffiliated parties via direct SQL UPDATE on faction column."""
from pathlib import Path, sys
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv; load_dotenv()
from src.db_api import raw_execute, raw_query

ASSIGNMENTS = [
    # The Grand Register — clause, verdict, legal/slow deliberation
    ("Cinder and Clause",    "The Grand Register (Guild)"),
    ("The Slow Verdict",     "The Grand Register (Guild)"),

    # Clearwater Authority — cold brook, water systems
    ("Coldbrook Syndicate",  "Clearwater Authority (Guild)"),

    # Mirrorgate Communications — cold line, unmarked messages, off-record hours
    ("Coldline Company",     "Mirrorgate Communications (Guild)"),
    ("The Unmarked",         "Mirrorgate Communications (Guild)"),
    ("The Unmarked Hours",   "Mirrorgate Communications (Guild)"),

    # Hearthwall Builders — crest/fall, construction and repair
    ("Crestfall Company",    "Hearthwall Builders (Guild)"),

    # Brightfire Entertainers — ember court, theatrical atmosphere
    ("Ember Court",          "Brightfire Entertainers (Guild)"),

    # Ironworks Combine — ember march, industrial advance
    ("Ember March",          "Ironworks Combine (Guild)"),

    # Arclight Engineers — flickering power, rust and radiance
    ("Flickering Standard",  "Arclight Engineers (Guild)"),
    ("Rust and Radiance",    "Arclight Engineers (Guild)"),

    # The Stonecrown Council — frost gate, property access control
    ("Frostgate Company",    "The Stonecrown Council (Guild)"),

    # Deepvein Extractors — iron mere expedition, ore/rock
    ("Ironmere Expedition",  "Deepvein Extractors (Guild)"),

    # The Polished Seal — shattered/waning compacts and pacts are their bread and butter
    ("Shattered Compact",    "The Polished Seal (Guild)"),
    ("The Waning Pact",      "The Polished Seal (Guild)"),

    # Crystal Lens Syndicate — tracking the quiet and pale majority
    ("The Pale Majority",    "Crystal Lens Syndicate (Guild)"),
    ("The Quiet Majority",   "Crystal Lens Syndicate (Guild)"),

    # Thornwall Security — patient knife, thorn crews
    ("The Patient Knife",    "Thornwall Security (Guild)"),
    ("Thorngate Crew",       "Thornwall Security (Guild)"),
    ("Thornveil Crew",       "Thornwall Security (Guild)"),

    # Wayfarer's Congress — severed roads are their problem to fix
    ("The Severed Road",     "Wayfarer's Congress (Guild)"),

    # Ashcraft Reclamation — waning collectives, things past their prime
    ("The Waning Collective","Ashcraft Reclamation (Guild)"),
]

# Staying independent (intentional):
# Unknown Party       — unknown by design
# Last Rites Collective — dark freelance crew
# The Unnamed Majority — anonymous, untracked
# Six Feet Forward    — freelance, their own path
# The Drifting Verdict — freelance arbiters
# Fracture Line Co.   — independent surveyors/breakers

def main():
    done = 0
    for party_name, guild in ASSIGNMENTS:
        n = raw_execute(
            "UPDATE party_profiles SET faction=%s WHERE party_name=%s AND (faction IS NULL OR faction='')",
            (guild, party_name)
        )
        status = "OK" if n else "SKIP"
        print(f"  {status}  {party_name!r:35} -> {guild}")
        if n: done += 1

    print(f"\n  {done} assigned.")

    # Final counts
    print("\n=== Guild party counts (DB) ===")
    rows = raw_query("""
        SELECT faction, COUNT(*) as n
        FROM party_profiles
        WHERE faction IS NOT NULL AND faction != ''
        GROUP BY faction ORDER BY faction
    """)
    for r in rows:
        print(f"  {r['n']:2d}  {r['faction']}")

    n_indep = raw_query("SELECT COUNT(*) as n FROM party_profiles WHERE faction IS NULL OR faction = ''")[0]['n']
    print(f"\n  {n_indep} parties remain independent")

if __name__ == "__main__":
    main()
