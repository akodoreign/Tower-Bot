"""
assign_npc_guilds.py — Assign unaffiliated NPCs to guilds.
Some get managerial/executive titles prepended to their role.
Updates the faction column directly on the npcs table.
Safe to re-run (skips already-affiliated).
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
# Assignments
# (name, guild, new_role_prefix)
# new_role_prefix = None → leave role as-is (operational/specialist)
# new_role_prefix = str  → prepend "[Title] — " to existing role (managerial)
# ---------------------------------------------------------------------------
ASSIGNMENTS: list[tuple[str, str, str | None]] = [

    # ── MANAGERIAL (guild title prepended to role) ──────────────────────────

    # The Ward is already a Lead Contractor — natural senior position
    ("The Ward",
     "The Grand Register (Guild)",
     "Senior Contract Director"),

    # Locket: Intelligence/Logistics — classic covert-ops manager
    ("Locket",
     "Mirrorgate Communications (Guild)",
     "Head of Covert Operations"),

    # Kael Drakon: sells salvaged gear to highest bidder — acquisition chief
    ("Kael Drakon",
     "Ashcraft Reclamation (Guild)",
     "Chief Acquisitions Manager"),

    # Carrion: Combat Specialist in the Warrens — field command
    ("Carrion",
     "Thornwall Security (Guild)",
     "Field Commander, Warrens Division"),

    # Gruggar: runs a black-market stall AND is a Tower Authority informant
    # — dual-use asset, managerial information officer for The Grand Register
    ("Gruggar Grimshackle",
     "The Grand Register (Guild)",
     "Deputy Information Officer"),

    # ── SPECIALIST / OPERATIONAL (faction only, role unchanged) ─────────────

    # Gurthok: mercenary/bodyguard → Thornwall Security operational
    ("Gurthok Ironhide",
     "Thornwall Security (Guild)",
     None),

    # Elira Duskspire: rift fragment smuggler at Ironworks → Ashcraft handles
    # hazardous/unstable salvage
    ("Elira Duskspire",
     "Ashcraft Reclamation (Guild)",
     None),

    # Elira Veyth: hides cursed heritage from Tower Authority, works black markets
    # → Crystal Lens Syndicate (surveillance, information, shadow work)
    ("Elira Veyth",
     "Crystal Lens Syndicate (Guild)",
     None),

    # Kaelen Searith: rare artifacts and forbidden tech → Crystal Lens field analyst
    ("Kaelen Searith",
     "Crystal Lens Syndicate (Guild)",
     None),

    # Nyxara 'Shadowclaw' Mourn: info broker navigating black markets
    # → Crystal Lens, Docks sector operative
    ("Nyxara 'Shadowclaw' Mourn",
     "Crystal Lens Syndicate (Guild)",
     None),

    # Thokk Skullsplitter: brokers deals between factions while moving contraband
    # → Wayfarer's Congress (he knows every route, legal and otherwise)
    ("Thokk Skullsplitter",
     "Wayfarer's Congress (Guild)",
     None),

    # Tobias Mossroot: runner, moves contraband through back alleys
    # → Wayfarer's Congress courier ops
    ("Tobias Mossroot",
     "Wayfarer's Congress (Guild)",
     None),

    # Vex Ironspine: moves black-market tech through the Docks
    # → Irondraft Logistics (Docks ops)
    ("Vex Ironspine",
     "Irondraft Logistics (Guild)",
     None),

    # Veyra Duskhollow: broker at the Docks, black-market deals
    # → Tidecrest Exchange (unofficial acquisitions channel)
    ("Veyra Duskhollow",
     "Tidecrest Exchange (Guild)",
     None),
]

# Staying truly independent:
# Vexrath Sablegear  — warlord/villain, his own agenda
# Iggy               — Vexrath's inner circle
# Pop                — Vexrath's inner circle
# The Mute           — freelance closer, deliberately unaffiliated
# Elaris Moonshadow  — too deep underground for any guild affiliation
# (Unknown 20th if present)


def main():
    rows = raw_query("SELECT id, name, faction, role FROM npcs")
    by_name = {r["name"]: r for r in rows}

    done = 0
    for (npc_name, guild, title) in ASSIGNMENTS:
        row = by_name.get(npc_name)
        if not row:
            print(f"  NOT FOUND: {npc_name!r}")
            continue

        existing_faction = (row.get("faction") or "").strip()
        if existing_faction and existing_faction not in ("Unknown", "Independent", ""):
            print(f"  SKIP  {npc_name!r} (already: {existing_faction})")
            continue

        if title:
            # Managerial: prepend guild title to existing role text
            current_role = (row.get("role") or "").strip()
            new_role = f"{title} — {current_role}" if current_role else title
            raw_execute(
                "UPDATE npcs SET faction=%s, role=%s WHERE id=%s",
                (guild, new_role, row["id"])
            )
            print(f"  MGR   {npc_name!r:35} -> {guild}")
            print(f"        role: {title}")
        else:
            raw_execute(
                "UPDATE npcs SET faction=%s WHERE id=%s",
                (guild, row["id"])
            )
            print(f"  OPS   {npc_name!r:35} -> {guild}")

        done += 1

    print(f"\n  {done} NPCs assigned.")

    print("\n=== Remaining unaffiliated NPCs ===")
    unaffiliated = raw_query("""
        SELECT name, role FROM npcs
        WHERE (faction IS NULL OR faction = '' OR faction IN ('Unknown','Independent'))
        AND (status IS NULL OR status NOT IN ('dead','retired'))
        ORDER BY name
    """)
    for r in unaffiliated:
        print(f"  {r['name']!r:30} {(r.get('role') or '')[:60]!r}")
    print(f"\n  {len(unaffiliated)} remain independent")

    print("\n=== Guild NPC counts ===")
    counts = raw_query("""
        SELECT faction, COUNT(*) as n FROM npcs
        WHERE faction LIKE '%(Guild)%'
        GROUP BY faction ORDER BY n DESC, faction
    """)
    for r in counts:
        print(f"  {r['n']:2d}  {r['faction']}")


if __name__ == "__main__":
    main()
