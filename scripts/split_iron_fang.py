"""One-off: split the Iron Fang Consortium into two warring factions.

Iron Fang Consortium  -> Serrik Dhal's ORTHODOX old guard (relics + infrastructure;
                         morally grey but builds; amenable to PCs). PC rep: Liked +1.
Iron Fang Syndicate   -> Sera Voss's breakaway (rackets, loan-sharking, TowerBay
                         stock manipulation). PC rep: Disliked -2.

Idempotent: safe to re-run. Run from repo root:  python scripts/split_iron_fang.py
"""
import sys, os, json
sys.argv = ["split_iron_fang"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db_api import (
    raw_query, raw_execute, get_faction_reputation,
    get_global_state, set_global_state,
)

ORTHODOX = "Iron Fang Consortium"
SYNDICATE = "Iron Fang Syndicate"

# Thematic split (reviewed) -- ids that move to the Syndicate (Sera Voss).
SYNDICATE_IDS = [26, 208, 120, 229, 81, 45, 256, 112, 40]  # Sera + 8 enforcers/intel/rackets

ORTHODOX_DESC = ("The orthodox old guard of the Iron Fang under its dying founder Serrik Dhal: "
                 "relic recovery and Undercity infrastructure. Morally grey, but it builds rather "
                 "than bleeds, and Serrik still deals straight with adventurers who deal straight with him.")
ORTHODOX_MOTTO = "We build what others only loot."

SYNDICATE_DESC = ("Sera Voss's breakaway wing of the Iron Fang: protection rackets, loan-sharking, "
                  "extortion, and TowerBay stock and auction manipulation. Ruthless expansion with "
                  "the Voss name stamped on everything Serrik built.")
SYNDICATE_MOTTO = "Everything has a price, and an owner."


def main():
    print("== Iron Fang split ==")

    # 1) faction_reputation: Orthodox row (update existing Iron Fang Consortium)
    raw_execute(
        "UPDATE faction_reputation SET reputation_score=%s, tier=%s, leader=%s, "
        "location_name=%s, description=%s, motto=%s, alignment=%s WHERE faction_name=%s",
        (1, "Liked", "Serrik Dhal", "Consortium Underhalls, Markets Infinite",
         ORTHODOX_DESC, ORTHODOX_MOTTO, "Lawful Neutral", ORTHODOX),
    )
    print(f"  [rep] {ORTHODOX}: Liked (+1), leader Serrik Dhal")

    # 2) faction_reputation: Syndicate row (insert or update)
    if get_faction_reputation(SYNDICATE):
        raw_execute(
            "UPDATE faction_reputation SET reputation_score=%s, tier=%s, leader=%s, "
            "location_name=%s, description=%s, motto=%s, alignment=%s WHERE faction_name=%s",
            (-2, "Disliked", "Sera Voss", "Crimson Alley, Markets Infinite",
             SYNDICATE_DESC, SYNDICATE_MOTTO, "Neutral Evil", SYNDICATE),
        )
        print(f"  [rep] {SYNDICATE}: updated (Disliked -2)")
    else:
        raw_execute(
            "INSERT INTO faction_reputation (faction_name, reputation_score, tier, leader, "
            "location_name, description, motto, alignment) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (SYNDICATE, -2, "Disliked", "Sera Voss", "Crimson Alley, Markets Infinite",
             SYNDICATE_DESC, SYNDICATE_MOTTO, "Neutral Evil"),
        )
        print(f"  [rep] {SYNDICATE}: created (Disliked -2), leader Sera Voss")

    # 3) reassign living members to the Syndicate
    raw_execute(
        f"UPDATE npcs SET faction=%s WHERE id IN ({','.join(['%s']*len(SYNDICATE_IDS))})",
        tuple([SYNDICATE] + SYNDICATE_IDS),
    )
    moved = raw_query(
        f"SELECT name FROM npcs WHERE id IN ({','.join(['%s']*len(SYNDICATE_IDS))}) ORDER BY name",
        tuple(SYNDICATE_IDS),
    ) or []
    print(f"  [npcs] -> {SYNDICATE}: " + ", ".join(n["name"] for n in moved))

    # everyone else still tagged Iron Fang stays Orthodox (no-op), confirm count
    orth = raw_query("SELECT COUNT(*) c FROM npcs WHERE faction=%s AND status!='dead'", (ORTHODOX,))
    synd = raw_query("SELECT COUNT(*) c FROM npcs WHERE faction=%s AND status!='dead'", (SYNDICATE,))
    print(f"  [npcs] living: {ORTHODOX}={orth[0]['c']}  {SYNDICATE}={synd[0]['c']}")

    # 4) leaders: Serrik heads the Orthodox last stand; Sera heads the Syndicate
    raw_execute(
        "UPDATE npcs SET `rank`=%s, role=%s WHERE id=%s",
        ("Guildmaster",
         "Guildmaster of the orthodox Iron Fang Consortium -- the old guard. Dying, Serrik rallies "
         "the relic-and-infrastructure loyalists to keep the Consortium true to what he built before "
         "Sera Voss turns the Iron Fang name into a protection racket.",
         101),
    )
    raw_execute(
        "UPDATE npcs SET faction=%s, `rank`=%s, role=%s WHERE id=%s",
        (SYNDICATE, "Guildmaster",
         "Guildmaster of the Iron Fang Syndicate -- her breakaway wing built on protection rackets, "
         "loan-sharking, and TowerBay stock and auction manipulation. She means to make the Voss name "
         "outshine everything Serrik built.",
         26),
    )
    print("  [npcs] leaders set: Serrik Dhal (Consortium), Sera Voss (Syndicate)")

    # 5) ongoing civil-war arc in global_state (read by the mission-prompt injector)
    set_global_state("iron_fang_civil_war", {
        "active": True,
        "since": "2026-05-31",
        "sides": [ORTHODOX, SYNDICATE],
        "orthodox": {"faction": ORTHODOX, "leader": "Serrik Dhal",
                     "wants": "keep the Iron Fang to relics + infrastructure; morally grey but builds"},
        "syndicate": {"faction": SYNDICATE, "leader": "Sera Voss",
                      "wants": "expand into rackets, loan-sharking, and TowerBay stock manipulation"},
        "summary": ("The Iron Fang has split. Sera Voss seized the guild and is turning it into a "
                    "racket; the dying founder Serrik Dhal rallies the orthodox old guard to keep it "
                    "true to relics and infrastructure. The war escalates for the foreseeable future."),
    })
    print("  [arc] global_state.iron_fang_civil_war = active")

    # 6) faction_events: a schism bulletin for each side (idempotent on event_type)
    for fac, etype, emoji, desc in [
        (ORTHODOX, "The Orthodox Hold", "\U0001f6e1️",
         "Serrik Dhal's loyalists refuse Sera Voss's writ. Relic crews and infrastructure hands stay "
         "with the founder. The old Iron Fang is digging in."),
        (SYNDICATE, "The Voss Ascendancy", "\U0001f4b0",
         "Sera Voss declares the Iron Fang Syndicate open for business: protection, paper, and "
         "TowerBay positions. Tribute is no longer optional in the lower Markets."),
    ]:
        exists = raw_query(
            "SELECT id FROM faction_events WHERE faction=%s AND event_type=%s", (fac, etype))
        if not exists:
            meta = json.dumps({"emoji": emoji, "announced": False, "resolved": False,
                               "mission_spawned": False, "original_desc": desc})
            raw_execute(
                "INSERT INTO faction_events (faction, event_type, event_date, description) "
                "VALUES (%s,%s, NOW() + INTERVAL 2 DAY, %s)",
                (fac, etype, f"{desc}\n<!--META:{meta}-->"),
            )
            print(f"  [event] {fac}: {etype}")
        else:
            print(f"  [event] {fac}: {etype} (exists, skipped)")

    print("== done ==")


if __name__ == "__main__":
    main()
