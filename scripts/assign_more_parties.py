"""
assign_more_parties.py — Assign ~40 more unaffiliated parties to guilds.
Leaves ~30 independent. Safe to re-run (skips already-assigned).
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from src.db_api import raw_query, raw_execute

ASSIGNMENTS: dict[str, str] = {
    # Flying Fleet — scouts, advance teams, cold-weather routes
    "Coldwatch Advance":    "Flying Fleet (Guild)",
    "Crestmark Advance":    "Flying Fleet (Guild)",

    # Ironworks Combine — forge, iron, soot
    "Ironfall Company":     "Ironworks Combine (Guild)",
    "Ironshade Company":    "Ironworks Combine (Guild)",
    "Sootmark Brigade":     "Ironworks Combine (Guild)",

    # Crystal Lens Syndicate — mirrors, watching, optics
    "Mirrorbreak Company":  "Crystal Lens Syndicate (Guild)",
    "Siltwatch Company":    "Crystal Lens Syndicate (Guild)",

    # Tidecrest Exchange — open accounts, gilded wealth
    "The Open Account":     "Tidecrest Exchange (Guild)",
    "The Gilded Fracture":  "Tidecrest Exchange (Guild)",

    # Hearthwall Builders — stone, gravel, construction materials
    "Stoneletter Guild":    "Hearthwall Builders (Guild)",
    "Gravel Court":         "Hearthwall Builders (Guild)",

    # Aurelius Medicant — saints, patients, care
    "The Lapsed Saints":    "Aurelius Medicant (Guild)",
    "The Patient Majority": "Aurelius Medicant (Guild)",

    # The Long Plate — ember, salt, dust (food preservation, grain)
    "Ember and Salt":       "The Long Plate (Guild)",
    "Dustmere Brigade":     "The Long Plate (Guild)",

    # Deepvein Extractors — ash, dust, gate (extraction routes, mining ops)
    "Ashgate Runners":      "Deepvein Extractors (Guild)",
    "Dustgate Syndicate":   "Deepvein Extractors (Guild)",
    "Dustline Seven":       "Deepvein Extractors (Guild)",

    # Arclight Engineers — fault lines, leaden conductors
    "Faultline Seven":      "Arclight Engineers (Guild)",
    "The Leaden Wing":      "Arclight Engineers (Guild)",

    # Wayfarer's Congress — salt roads, expeditions, overland travel
    "Saltmarch Wanderers":  "Wayfarer's Congress (Guild)",
    "Saltveil Expedition":  "Wayfarer's Congress (Guild)",

    # The Grand Register — clauses, petitions, verdicts
    "Remnant Clause":       "The Grand Register (Guild)",
    "The Slow Petition":    "The Grand Register (Guild)",
    "The Weighted Verdict": "The Grand Register (Guild)",

    # Brightfire Entertainers — sunrise shows, borrowed time
    "The Second Sunrise":   "Brightfire Entertainers (Guild)",
    "The Borrowed Hours":   "Brightfire Entertainers (Guild)",

    # Thornwall Security — brass vigil, thorn crews
    "The Brass Vigil":      "Thornwall Security (Guild)",
    "Thornfield Crew":      "Thornwall Security (Guild)",

    # Ashcraft Reclamation — ash, cinder, hollow
    "Ashen Hollow":         "Ashcraft Reclamation (Guild)",
    "Cindermark Guild":     "Ashcraft Reclamation (Guild)",

    # Goldenleaf Hospitality — dawn service, chasing the early crowd
    "Dawnchaser Compact":   "Goldenleaf Hospitality (Guild)",

    # Mirrorgate Communications — marked hours, message timestamps
    "The Marked Hour":      "Mirrorgate Communications (Guild)",

    # Irondraft Logistics — dead reckoning navigation, heavy lifts
    "Dead Reckoning Co.":   "Irondraft Logistics (Guild)",
    "Nockfall Company":     "Irondraft Logistics (Guild)",

    # The Polished Seal — deliberate arbiters, weighty oaths
    "The Deliberate Few":   "The Polished Seal (Guild)",
    "The Weighted Oath":    "The Polished Seal (Guild)",

    # Runemark Academy — borrowed standards, deliberate study
    "The Borrowed Standard": "Runemark Academy (Guild)",
    "The Deliberate Hours":  "Runemark Academy (Guild)",

    # Spellwright Collective — thresholds, arcane boundaries
    "Threshold Nine":       "Spellwright Collective (Guild)",
}


def main():
    profiles = raw_query("SELECT id, party_name, profile_json FROM party_profiles")
    by_name = {r["party_name"]: r for r in profiles}

    assigned = 0
    skipped = 0
    not_found = []

    for pname, guild in sorted(ASSIGNMENTS.items()):
        if pname not in by_name:
            not_found.append(pname)
            continue
        row = by_name[pname]
        pj = row.get("profile_json") or {}
        if isinstance(pj, str):
            try: pj = json.loads(pj)
            except: pj = {}
        if pj.get("faction"):
            print(f"  SKIP  {pname!r:40} already -> {pj['faction']}")
            skipped += 1
            continue
        pj["faction"]  = guild
        pj["employer"] = guild
        raw_execute(
            "UPDATE party_profiles SET profile_json=%s WHERE id=%s",
            (json.dumps(pj, ensure_ascii=False), row["id"])
        )
        print(f"  ASSIGN {pname!r:40} -> {guild}")
        assigned += 1

    print(f"\n  Assigned: {assigned}  |  Skipped (already set): {skipped}  |  Not found: {len(not_found)}")
    if not_found:
        print(f"  Not found: {not_found}")

    # Tally
    print("\n=== Final guild party counts ===")
    counts: dict[str, int] = {}
    indep = 0
    for row in raw_query("SELECT profile_json FROM party_profiles"):
        pj = row.get("profile_json") or {}
        if isinstance(pj, str):
            try: pj = json.loads(pj)
            except: pj = {}
        f = (pj.get("faction") or "").strip()
        if f:
            counts[f] = counts.get(f, 0) + 1
        else:
            indep += 1
    for gname in sorted(counts):
        print(f"  {counts[gname]:2d}  {gname}")
    print(f"\n  {indep} parties remain unaffiliated")


if __name__ == "__main__":
    main()
