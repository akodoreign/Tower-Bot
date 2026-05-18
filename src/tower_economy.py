"""
tower_economy.py — TowerBay auction house and Tower Industrial Average (TIA) ticker.

TowerBay: 10 active auction listings at all times. Items sell after 7 real days,
replaced with fresh AI-generated listings. Prices start at 10,000+ EC with bids
that drift upward over the week.

TIA: A fictional stock-market-style index of 8 Undercity "industries". Values
shift each tick with small random drift plus occasional event-driven spikes.
Formatted as a scrolling ticker for Discord.

Both persist to MySQL via db_api.
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from src.log import logger
from src.db_api import get_global_state, raw_query, raw_execute, set_global_state, db

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"

# ---------------------------------------------------------------------------
# TIA News Reaction System
# ---------------------------------------------------------------------------
#
# After each bulletin is generated, scan its text for keywords.
# Each rule: (keyword_list, sector_key, delta, severity, market_note)
#
# Severity: "minor" = single sector nudge
#           "major" = sector crash/spike + composite drag
#           "shock" = multi-sector panic, big numbers
#
# Only one rule fires per bulletin (highest severity wins).
# Cooldown: 30 minutes between reaction events so a string of bad news
# doesn't crater the index to zero.
# ---------------------------------------------------------------------------

_NEWS_REACTIONS = [

    # =========================================================
    # NEGATIVE — crashes, disruptions, disasters
    # =========================================================

    # Rift events — shock tier: adventurer demand craters, security scrambles, rift tech spikes
    (["rift", "disaster", "collapse", "evacuation", "containment failing", "rift is open", "rift has opened"],
     ["adventurer", "security", "rift_tech"], [-0.14, -0.10, +0.18],
     "shock", "Active Rift event: contract board freezes, security costs spike, containment stocks surge"),

    (["rift precipitation", "rift residue falling", "evacuate"],
     ["rift_tech", "adventurer", "smuggling"], [+0.20, -0.12, -0.08],
     "shock", "Rift precipitation forces district shutdown: containment stocks spike, logistics collapse"),

    # Warden failures
    (["warden deserter", "warden failed", "wardens overwhelmed", "warden casualt", "warden missing"],
     ["security", "adventurer"], [-0.12, +0.08],
     "major", "Warden credibility hit: private security demand rises, adventurer contracts up"),

    # Warden crackdowns — good for security, bad for grey market
    (["wardens raid", "warden raid", "warden crackdown", "new checkpoint"],
     ["security", "smuggling"], [+0.09, -0.13],
     "major", "Warden enforcement surge: security sector strengthens, grey market logistics disrupted"),

    # Iron Fang disruption
    (["iron fang seizure", "fta seizure", "smuggling ring", "contraband bust", "relic confiscated"],
     ["relic", "smuggling", "essence"], [-0.10, -0.09, -0.04],
     "major", "Enforcement action against Iron Fang supply chain rattles relic and grey market"),

    # Divine / Kharma scandal
    (["contract default", "breach of contract", "divine scandal", "choir corrupt", "sevas", "false miracle"],
     ["divine", "essence"], [-0.14, -0.07],
     "major", "Divine contract scandal: Kharma trading suppressed, EC confidence dips"),

    # FTA crackdown
    (["fta investigation", "fta scrutiny", "fta crackdown", "fta raid", "compliance review"],
     ["memory", "smuggling", "relic"], [-0.09, -0.07, -0.05],
     "major", "FTA enforcement action chills memory market, grey logistics, and relic trade"),

    # Counterfeit / fraud
    (["counterfeit", "forged", "fraudulent", "fake ec", "false license", "falsified"],
     ["essence", "relic"], [-0.12, -0.06],
     "major", "Fraud report dents EC confidence and relic authentication trust"),

    # Violence / death
    (["body found", "found dead", "assassination", "massacre", "murdered", "casualt"],
     ["security", "adventurer"], [-0.09, +0.06],
     "major", "Public violence: security sector rattled, adventurer demand rises as factions hire muscle"),

    # Cult activity
    (["brother thane", "thane's cult", "collapsed plaza", "gorgon gizzick", "cult recruiting"],
     ["security", "memory"], [-0.07, +0.06],
     "minor", "Cult activity spooks security investors; information brokers see uptick in intel demand"),

    # Warrens unrest
    (["warrens unrest", "warrens protest", "residents evacuating", "shantytown", "echo alley incident"],
     ["security", "smuggling"], [-0.07, -0.05],
     "minor", "Warrens instability disrupts logistics routes and rattles security sector"),

    # Party failure / adventurer death
    (["party disbanded", "adventurer dead", "contract failed", "mission failed", "did not return"],
     ["adventurer"], [-0.10],
     "minor", "High-profile contract failure drags adventurer sector confidence"),

    # Missing persons surge
    (["missing persons", "disappeared", "has not returned", "has not been seen"],
     ["security", "memory"], [-0.05, +0.04],
     "minor", "Missing persons spike raises security concerns and information sector demand"),

    # =========================================================
    # POSITIVE — rallies, windfalls, stability events
    # =========================================================

    # Rift sealed — broad relief rally
    (["rift sealed", "rift closed", "rift contained", "containment successful", "rift cleared"],
     ["adventurer", "security", "essence", "rift_tech"], [+0.12, +0.08, +0.06, -0.09],
     "shock", "Rift successfully sealed: broad market relief rally, adventurer demand surges, containment stocks normalise"),

    # Iron Fang auction / surplus — trade boom
    (["iron fang auction", "relic auction", "surplus clearance", "clearance sale", "iron fang open"],
     ["relic", "essence", "smuggling"], [+0.10, +0.05, +0.06],
     "minor", "Iron Fang market activity: relic demand up, EC exchange active, grey logistics ticking"),

    # Serpent Choir positive event
    (["new miracle tier", "divine contract signed", "kharma tithe", "open contract day", "yzura speaks"],
     ["divine", "essence"], [+0.12, +0.05],
     "minor", "Serpent Choir expansion drives Kharma premium and EC exchange activity"),

    # Glass Sigil breakthrough
    (["glass sigil patent", "new stabilisation", "residue method", "anomaly resolved", "instruments recalibrated"],
     ["rift_tech", "memory"], [+0.14, +0.06],
     "major", "Glass Sigil breakthrough lifts rift technology confidence and information sector"),

    # Adventurer win / mission complete
    (["contract complete", "mission complete", "returned successful", "rift cleared", "dungeon cleared"],
     ["adventurer", "essence"], [+0.08, +0.04],
     "minor", "Successful contract completion boosts adventurer sector confidence"),

    # Arena / Argent Blades positive
    (["arena champion", "season champion", "title bout", "championship", "open challenge night", "record crowd"],
     ["adventurer", "essence", "security"], [+0.07, +0.04, +0.03],
     "minor", "Arena season energy lifts adventurer enthusiasm and city-wide spending"),

    # Rank advancement / guild expansion
    (["rank advancement", "new a-rank", "new s-rank", "guild recruitment", "guild expansion"],
     ["adventurer", "security"], [+0.09, +0.05],
     "minor", "Adventurer Guild growth signals contract pipeline strength"),

    # Diplomatic / faction stability
    (["peace accord", "alliance formed", "treaty signed", "faction agreement", "truce"],
     ["essence", "adventurer", "smuggling"], [+0.08, +0.05, +0.04],
     "major", "Faction stability agreement lifts cross-sector confidence and trade flows"),

    # Obsidian Lotus expanding — memory market boom
    (["memory market", "lotus expanding", "memory vial", "new lotus contract", "waitlist"],
     ["memory", "essence"], [+0.10, +0.04],
     "minor", "Obsidian Lotus demand surge lifts information sector and EC exchange"),

    # Warden ceremony / expansion — security confidence
    (["warden oath", "warden recruit", "warden expansion", "new warden", "warden commiss"],
     ["security", "essence"], [+0.08, +0.03],
     "minor", "Warden expansion boosts public security confidence"),

    # Community / Patchwork Saints positive
    (["community mend", "warrens stable", "saints distribut", "warrens quiet", "patchwork saints"],
     ["security", "smuggling"], [+0.05, +0.04],
     "minor", "Warrens stability lifts logistics confidence and reduces security risk premium"),

    # FTA positive — compliance clears, licence renewal
    (["compliance cleared", "licence renewed", "fta approved", "director kess approved", "fta certified"],
     ["adventurer", "essence"], [+0.06, +0.04],
     "minor", "FTA compliance clearance restores market confidence and adventurer contract flow"),

    # Clarity Event — rare morale event, everything up slightly
    (["clarity event", "open sky", "dome displaying", "crowds gathering in grand forum"],
     ["essence", "adventurer", "divine", "memory"], [+0.07, +0.06, +0.05, +0.04],
     "major", "Clarity Event lifts city-wide morale: broad-based market rally across all consumer sectors"),

    # Ashen Scrolls / lore discovery
    (["tessaly", "narrative resonance", "fate archive", "ashen scrolls", "thesaurus"],
     ["memory", "relic"], [+0.08, +0.05],
     "minor", "Ashen Scrolls discovery drives information sector and relic authentication demand"),
]

# Sector keys that get a sympathy drag when a shock fires
_SHOCK_SYMPATHY_DRAG = 0.04   # all non-affected sectors drop this much on a shock

# Cooldown between reaction events (seconds)
_REACTION_COOLDOWN = 30 * 60  # 30 minutes


def _load_reaction_cooldown() -> Optional[datetime]:
    """Load reaction cooldown from global_state table."""
    try:
        data = get_global_state("tia_reaction_cooldown")
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict) and data.get("last_reaction_at"):
            return datetime.fromisoformat(str(data["last_reaction_at"]))
        return None
    except Exception as e:
        logger.warning(f"Reaction cooldown load error: {e}")
        return None


def _save_reaction_cooldown() -> None:
    """Save reaction cooldown to global_state table."""
    try:
        set_global_state("tia_reaction_cooldown", {"last_reaction_at": datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"Reaction cooldown save error: {e}")


def _on_cooldown() -> bool:
    last = _load_reaction_cooldown()
    if not last:
        return False
    return (datetime.now() - last).total_seconds() < _REACTION_COOLDOWN


def react_to_bulletin(bulletin_text: str) -> Optional[str]:
    """
    Scan a bulletin for keywords and apply TIA market shocks if matched.
    Returns a formatted TIA flash bulletin string if a reaction fired, else None.

    Call this immediately after generate_bulletin() returns text.
    """
    if not bulletin_text or _on_cooldown():
        return None

    text_lower = bulletin_text.lower()

    # Find the highest-severity matching rule
    best_rule  = None
    best_rank  = 0
    rank_map   = {"minor": 1, "major": 2, "shock": 3}

    for rule in _NEWS_REACTIONS:
        keywords, sectors, deltas, severity, note = rule
        if any(kw in text_lower for kw in keywords):
            rank = rank_map.get(severity, 0)
            if rank > best_rank:
                best_rank = rank
                best_rule = rule

    if not best_rule:
        return None

    keywords, sectors, deltas, severity, note = best_rule

    # Apply the shock
    state = _load_tia()
    if not state or "sectors" not in state:
        state = _init_tia()

    moved = []
    for key, delta in zip(sectors, deltas):
        if key in state["sectors"]:
            sec = state["sectors"][key]
            sec["prev_value"] = sec["value"]
            sec["value"]      = round(max(100, sec["value"] * (1 + delta)), 2)
            sec["change_pct"] = round(delta * 100, 2)
            moved.append((key, delta))

    # On shock: sympathy move for all other sectors
    # Positive shock = sympathy lift. Negative shock = sympathy drag.
    if severity == "shock":
        net = sum(deltas)
        sympathy = _SHOCK_SYMPATHY_DRAG if net > 0 else -_SHOCK_SYMPATHY_DRAG
        for key, sec in state["sectors"].items():
            if key not in sectors:
                sec["prev_value"] = sec["value"]
                sec["value"]      = round(max(100, sec["value"] * (1 + sympathy)), 2)
                sec["change_pct"] = round(sympathy * 100, 2)

    state["last_event"]   = note
    state["last_updated"] = datetime.now().isoformat()
    _save_tia(state)
    _save_reaction_cooldown()

    logger.info(f"📊 TIA reaction fired ({severity}): {note}")

    # Build flash bulletin
    now   = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    ts    = f"{now.strftime('%Y-%m-%d %H:%M')} | Tower: {tower.strftime('%d %b %Y, %H:%M')}"

    # Determine overall direction from the moved sectors
    net_delta = sum(d for _, d in moved)
    bullish   = net_delta > 0

    severity_header = {
        ("minor", True):  "📈 TIA MARKET NOTE — POSITIVE",
        ("minor", False): "📌 TIA MARKET NOTE",
        ("major", True):  "📈 TIA MARKET RALLY",
        ("major", False): "📉 TIA MARKET ALERT",
        ("shock", True):  "🚀 TIA SURGE — MARKET IN MOTION",
        ("shock", False): "🚨 TIA FLASH CRASH — MARKET IN MOTION",
    }.get((severity, bullish), "📊 TIA UPDATE")

    lines = [
        f"📊 **{severity_header}** 📊",
        f"-# {ts}",
        "",
        f"*{note}*",
        "",
    ]

    for key, delta in moved:
        sec_name = state["sectors"][key]["name"]
        sign     = "+" if delta >= 0 else ""
        arrow    = "🟢 ▲" if delta > 0 else "🔴 ▼"
        lines.append(f"{arrow}  **{sec_name}**  _{sign}{delta*100:.1f}%_")

    if severity == "shock":
        if bullish:
            lines.append(f"🟢 ▲  *All other sectors*  _+{_SHOCK_SYMPATHY_DRAG*100:.1f}% sympathy lift_")
        else:
            lines.append(f"🔴 ▼  *All other sectors*  _{-_SHOCK_SYMPATHY_DRAG*100:.1f}% sympathy drag_")

    lines += [
        "",
        "-# TIA reaction to breaking news. Glass Sigil Economic Monitoring. Not financial advice."
    ]
    return "-# 🕰️ " + ts + "\n" + "\n".join(lines)

TOWER_YEAR_OFFSET = 10  # mirrors news_feed

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dual_ts() -> str:
    now = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    return f"{now.strftime('%Y-%m-%d %H:%M')} | Tower: {tower.strftime('%d %b %Y, %H:%M')}"


def _ec(n: int) -> str:
    return f"{n:,} EC"


# ---------------------------------------------------------------------------
# TowerBay — auction house
# ---------------------------------------------------------------------------

TOWERBAY_ITEM_COUNT  = 10
TOWERBAY_LISTING_DAYS = 7

_SEED_ITEMS = [
    {
        "name": "Void-Tempered Zweihänder",
        "description": "A two-handed blade forged in collapsed Rift residue. Hums at the frequency of open wounds. Previous owner: unknown. Condition of previous owner: also unknown.",
        "category": "Weapons",
        "condition": "Well-used",
        "seller": "Anonymous (verified Iron Fang-adjacent)",
        "starting_bid": 42_000,
    },
    {
        "name": "Glass Sigil Resonance Compass",
        "description": "Decommissioned anomaly-tracking device. Still accurate. Still logging. Nobody's checked what it's been logging.",
        "category": "Arcane Instruments",
        "condition": "Functional — provenance unclear",
        "seller": "Dova (Glass Sigil, selling personally)",
        "starting_bid": 18_500,
    },
    {
        "name": "Obsidian Lotus Memory Vial — Lot of 3",
        "description": "Three sealed crystal vials containing erased memories. Identities of original owners redacted per contract. Contents unknown. Non-refundable.",
        "category": "Occult Curiosities",
        "condition": "Sealed",
        "seller": "Obsidian Lotus (verified)",
        "starting_bid": 55_000,
    },
    {
        "name": "Argent Blades Arena Championship Belt — Season 7",
        "description": "The actual belt. Engraved. Blood on the back clasp has not been cleaned. Aric Veyne's name is on the inside. He sold it himself.",
        "category": "Memorabilia",
        "condition": "Excellent (exterior)",
        "seller": "Aric Veyne (verified)",
        "starting_bid": 28_000,
    },
    {
        "name": "Rift-Stable Pocket Dimension Flask",
        "description": "Holds up to 4 litres in a space the size of a thumb. Opens perpendicular to local reality. Do not shake.",
        "category": "Utility Gear",
        "condition": "New — Iron Fang overstock",
        "seller": "Iron Fang Consortium (surplus clearance)",
        "starting_bid": 33_000,
    },
    {
        "name": "Pre-Dome City Map — Hand-Drawn, Authenticated",
        "description": "Shows streets that no longer exist and gates that were sealed before the current generation was born. Ashen Scrolls authentication stamp. Three annotations in an unknown script.",
        "category": "Documents & Lore",
        "condition": "Fragile — handle with care",
        "seller": "Private collector (anonymous)",
        "starting_bid": 61_000,
    },
    {
        "name": "Serpent Choir Blank Contract — Divine Grade",
        "description": "A pre-notarised divine contract with all terms left blank. Legally binding the moment a name is signed. High Apostle Yzura's seal on the cover. Not officially for sale.",
        "category": "Documents & Lore",
        "condition": "Mint",
        "seller": "Vesper (selling on behalf of undisclosed party)",
        "starting_bid": 120_000,
    },
    {
        "name": "Kharma-Infused Whetstone",
        "description": "Sharpens any blade. Edges hold faith as well as steel. Secondary effect: weapons sharpened on this stone attract divine attention proportional to LP of wielder. Read the fine print.",
        "category": "Consumables",
        "condition": "Partially used — significant charges remain",
        "seller": "Patchwork Saints (fundraiser item)",
        "starting_bid": 14_000,
    },
    {
        "name": "FTA-Certified Adventurer License — Blank",
        "description": "Blank, signed, stamped. Fill in any name. Officially valid. Definitely not stolen. Calix Drenn has been looking for this.",
        "category": "Documents & Lore",
        "condition": "New",
        "seller": "Unknown",
        "starting_bid": 22_000,
    },
    {
        "name": "Brother Thane's Cult Recruitment Pamphlet — Annotated Edition",
        "description": "Someone has written corrections in red ink throughout. The handwriting is Corvin Thale's. He doesn't know it's for sale.",
        "category": "Occult Curiosities",
        "condition": "Well-annotated",
        "seller": "Street vendor, Echo Alley (no name given)",
        "starting_bid": 10_500,
    },
]


def _load_towerbay() -> List[Dict]:
    """Load TowerBay listings from database."""
    try:
        rows = raw_query("SELECT * FROM towerbay_auctions ORDER BY id")
        listings = []
        for row in rows:
            # Start with auction_json for rich fields (description, category, condition, bid_count, etc.)
            aj = row.get("auction_json") or {}
            if isinstance(aj, str):
                try:
                    aj = json.loads(aj)
                except Exception:
                    aj = {}

            # Base dict from auction_json, then override with live DB columns
            listing = {
                "description": "",
                "category": "Utility Gear",
                "condition": "Unknown",
                "bid_count": 0,
                "listed_at": None,
                **{k: v for k, v in aj.items() if k != "id" and v not in (None, "", [])},
                # DB columns always win for live state
                "id": row.get("id"),
                "name": row.get("item_name") or aj.get("name", "Unknown"),
                "seller": row.get("seller_name") or aj.get("seller", "Anonymous"),
                "seller_id": row.get("seller_id"),
                "current_bid": row.get("current_bid", aj.get("current_bid", 10000)),
                "starting_bid": aj.get("starting_bid", row.get("current_bid", 10000)),
                "buy_now_price": row.get("buy_now_price"),
                "expires_at": row.get("expires_at").isoformat() if row.get("expires_at") else aj.get("expires_at"),
                "sold": row.get("status") == "sold",
                "winner_id": row.get("winner_id"),
            }
            listings.append(listing)
        return listings
    except Exception as e:
        logger.error(f"TowerBay load error: {e}")
        return []


def _save_towerbay(listings: List[Dict]) -> None:
    """Save all TowerBay listings to database."""
    try:
        for item in listings:
            _save_towerbay_item(item)
    except Exception as e:
        logger.error(f"TowerBay save error: {e}")


def _save_towerbay_item(item: Dict) -> None:
    """Save a single TowerBay item to database."""
    try:
        item_id = item.get("id")
        name = item.get("name", "Unknown Item")
        status = "sold" if item.get("sold") else "active"
        
        # Parse dates for DB columns
        expires_at = None
        if item.get("expires_at"):
            try:
                expires_at = datetime.fromisoformat(item["expires_at"]).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                expires_at = None
        
        current_bid = item.get("current_bid", item.get("starting_bid", 10000))
        buy_now_price = item.get("buy_now_price")
        seller_name = item.get("seller", "Anonymous")
        
        # Serialize full item dict as auction_json for rich field preservation
        auction_json_str = json.dumps({k: v for k, v in item.items() if k != "id"}, ensure_ascii=False, default=str)

        if item_id:
            # Check if exists
            existing = raw_query("SELECT id FROM towerbay_auctions WHERE id = %s", (item_id,))
            if existing:
                raw_execute(
                    "UPDATE towerbay_auctions SET item_name = %s, current_bid = %s, status = %s, "
                    "expires_at = %s, seller_name = %s, auction_json = %s WHERE id = %s",
                    (name, current_bid, status, expires_at, seller_name, auction_json_str, item_id)
                )
                return

        # Insert new
        new_id = db.insert("towerbay_auctions", {
            "item_name": name,
            "current_bid": current_bid,
            "buy_now_price": buy_now_price,
            "seller_name": seller_name,
            "status": status,
            "expires_at": expires_at,
            "auction_json": auction_json_str,
        })
        item["id"] = new_id
    except Exception as e:
        logger.error(f"TowerBay item save error for {item.get('name', '?')}: {e}")


def _seed_towerbay() -> List[Dict]:
    now = datetime.now()
    listings = []
    for i, item in enumerate(_SEED_ITEMS):
        start      = item["starting_bid"]
        listed_at  = now - timedelta(days=random.randint(0, 3))
        expires_at = listed_at + timedelta(days=TOWERBAY_LISTING_DAYS)
        listings.append({
            "id":           i + 1,
            "name":         item["name"],
            "description":  item["description"],
            "category":     item["category"],
            "condition":    item["condition"],
            "seller":       item["seller"],
            "starting_bid": start,
            "current_bid":  start + random.randint(0, int(start * 0.15)),
            "bid_count":    random.randint(0, 4),
            "listed_at":    listed_at.isoformat(),
            "expires_at":   expires_at.isoformat(),
            "sold":         False,
        })
    return listings


def _load_npc_bidder_pool() -> List[Dict]:
    """Load a small pool of named NPCs and adventurer parties for Tower Bay bidding."""
    pool = []
    try:
        npcs = raw_query(
            "SELECT name, faction FROM npcs "
            "WHERE status IN ('alive','injured','undead','doppelganger') ORDER BY RAND() LIMIT 20"
        ) or []
        for n in npcs:
            pool.append({"name": n["name"], "faction": n.get("faction",""), "kind": "npc"})
    except Exception:
        pass
    try:
        parties = raw_query(
            "SELECT party_name FROM party_profiles WHERE status='active' ORDER BY RAND() LIMIT 8"
        ) or []
        for p in parties:
            pool.append({"name": p["party_name"], "faction": "Adventurers Guild", "kind": "party"})
    except Exception:
        pass
    return pool


def _tick_bids(listings: List[Dict], bidder_pool: Optional[List[Dict]] = None) -> tuple:
    """
    Advance NPC/party bids. Named bidders from the pool replace anonymous phantom bids.
    Backs off when a real player is winning.
    """
    now = datetime.now()
    sold_this_tick = []
    pool = bidder_pool or []

    for item in listings:
        if item.get("sold"):
            continue
        try:
            expires = datetime.fromisoformat(item["expires_at"])
        except Exception:
            expires = now
        if now >= expires:
            item["sold"] = True
            sold_this_tick.append(item)
            continue

        has_real_bidder = bool(item.get("highest_bidder_id"))
        chance  = 0.12 if has_real_bidder else 0.30
        max_bump = 0.05 if has_real_bidder else 0.12

        if random.random() < chance:
            bump    = random.uniform(0.02, max_bump)
            new_bid = int(item["current_bid"] * (1 + bump))
            proxy   = item.get("proxy_max")
            if has_real_bidder and proxy and new_bid <= proxy:
                item["bid_count"] += 1
            else:
                item["current_bid"] = new_bid
                item["bid_count"]  += 1
                if has_real_bidder:
                    item["highest_bidder_id"]   = None
                    item["highest_bidder_name"] = None
                    item["proxy_max"]           = None

                # Assign a named NPC/party as current bid holder
                if pool:
                    bidder = random.choice(pool)
                    # Use a stable "npc" pseudo-ID so it shows as NPC not player
                    item["npc_bidder_name"]    = bidder["name"]
                    item["npc_bidder_faction"] = bidder.get("faction", "")
                    item["npc_bidder_kind"]    = bidder.get("kind", "npc")
                    # Store in auction_json for history later
                    aj = item.get("auction_json_obj") or {}
                    bids = aj.get("npc_bid_history", [])
                    bids.append({
                        "bidder": bidder["name"],
                        "amount": new_bid,
                        "at":     now.isoformat(),
                    })
                    aj["npc_bid_history"] = bids[-20:]  # keep last 20
                    item["auction_json_obj"] = aj

    return listings, sold_this_tick


def _award_sold_items(sold_items: List[Dict]) -> None:
    """
    Record Tower Bay wins to the NPC/party acquisition log in global_state.
    Called after _tick_bids resolves expired listings.
    """
    if not sold_items:
        return
    try:
        acquisitions = get_global_state("towerbay_npc_acquisitions") or []
        if not isinstance(acquisitions, list):
            acquisitions = []
        for item in sold_items:
            winner_name = (
                item.get("npc_bidder_name")
                or item.get("highest_bidder_name")
            )
            if not winner_name:
                continue
            record = {
                "item":         item.get("name", "Unknown"),
                "winner":       winner_name,
                "winner_kind":  item.get("npc_bidder_kind", "npc"),
                "faction":      item.get("npc_bidder_faction", ""),
                "final_bid":    item.get("current_bid", 0),
                "rarity":       item.get("rarity", ""),
                "mimir_source": item.get("mimir_source", False),
                "sold_at":      datetime.now().isoformat(),
            }
            acquisitions.append(record)
            logger.info(
                f"🏆 TowerBay: {item.get('name','?')} sold to "
                f"{winner_name} for {item.get('current_bid',0):,} EC"
            )
        # Keep last 100 acquisition records
        set_global_state("towerbay_npc_acquisitions", acquisitions[-100:])

        # Push won items to Mimir as NPC documents (best-effort)
        _push_acquisitions_to_mimir(acquisitions[-len(sold_items):])
    except Exception as e:
        logger.warning(f"TowerBay award tracking error: {e}")


def _push_acquisitions_to_mimir(records: List[Dict]) -> None:
    """Best-effort: write acquisition notes to Mimir so NPCs/parties have item history."""
    try:
        from src.mimir_client import get_mimir
        import asyncio as _aio
        mimir = get_mimir()
        if not mimir or not mimir._available:
            return

        async def _write():
            for rec in records:
                item_name   = rec.get("item", "Unknown Item")
                winner      = rec.get("winner", "Unknown")
                faction     = rec.get("faction", "")
                final_bid   = rec.get("final_bid", 0)
                rarity      = rec.get("rarity", "")
                title = f"TowerBay Acquisition: {item_name} — {winner}"
                content = (
                    f"**{winner}** ({faction}) won **{item_name}** "
                    f"at TowerBay auction.\n"
                    f"Final bid: {final_bid:,} EC"
                    + (f"\nRarity: {rarity}" if rarity else "")
                    + f"\nDate: {rec.get('sold_at','')}"
                )
                try:
                    await mimir.add_document(title=title, doc_type="note", content=content)
                except Exception:
                    pass

        try:
            loop = _aio.get_event_loop()
            if loop.is_running():
                loop.create_task(_write())
            else:
                loop.run_until_complete(_write())
        except Exception:
            pass
    except Exception:
        pass


async def _generate_new_listing(existing_names: List[str]) -> Optional[Dict]:
    import httpx, re

    names_str  = ", ".join(existing_names[-20:]) if existing_names else "none"
    categories = [
        "Weapons", "Armour", "Arcane Instruments", "Utility Gear",
        "Documents & Lore", "Occult Curiosities", "Consumables",
        "Memorabilia", "Contraband", "Vehicles & Mounts",
    ]
    category  = random.choice(categories)
    min_price = random.randint(10_000, 80_000)

    prompt = f"""You are writing a listing for TowerBay — an Undercity auction house for rare, dangerous, and unusual items.
The setting is a dark fantasy underground city sealed under a Dome. Currency is Essence Coins (EC).

Do NOT reuse these item names: {names_str}
Category for this listing: {category}
Minimum starting bid: {min_price:,} EC

Generate ONE auction listing. Output ONLY a JSON object with these exact keys:
{{
  "name": "short evocative item name",
  "description": "2-3 sentences — specific, flavourful, slightly ominous or darkly funny. Mention provenance or a hook.",
  "category": "{category}",
  "condition": "one of: Mint / Excellent / Good / Well-used / Damaged / Unknown",
  "seller": "a specific seller name or faction — can be anonymous but with a hint",
  "starting_bid": {min_price}
}}

RULES:
- Be specific and creative. No generic fantasy filler.
- The item should feel like it has a history.
- Output ONLY the JSON. No markdown fences, no preamble."""

    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")

    try:
        from src.ollama_queue import call_ollama, OllamaBusyError
        data = await call_ollama(
            payload={
                "model":    ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream":   False,
            },
            timeout=90.0,
            caller="tower_economy",
        )

        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()

        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        try:
            item = json.loads(text)
        except Exception:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if not match:
                return None
            item = json.loads(match.group())

        now        = datetime.now()
        start      = int(item.get("starting_bid", min_price))
        expires_at = now + timedelta(days=TOWERBAY_LISTING_DAYS)
        # Buy Now at 2.5–3.5× starting bid — tempting but premium
        buy_now    = int(start * random.uniform(2.5, 3.5))

        return {
            "id":             int(datetime.now().timestamp()),
            "name":           item.get("name", "Unknown Item"),
            "description":    item.get("description", ""),
            "category":       item.get("category", category),
            "condition":      item.get("condition", "Unknown"),
            "seller":         item.get("seller", "Anonymous"),
            "starting_bid":   start,
            "current_bid":    start,
            "buy_now_price":  buy_now,
            "bid_count":      0,
            "listed_at":      now.isoformat(),
            "expires_at":     expires_at.isoformat(),
            "sold":           False,
        }

    except Exception as e:
        logger.error(f"TowerBay new listing error: {e}")
        return None


# ---------------------------------------------------------------------------
# Mimir item listings — real D&D magic items pulled from the catalog
# ---------------------------------------------------------------------------

# Starting bid ≈ 50% of standard D&D 5e value for each rarity tier (in EC)
# Buy Now = starting_bid × 2  (still below "full" value, encourages bidding)
_MIMIR_RARITY_EC: Dict[str, tuple] = {
    "uncommon":  (1_000,   8_000),
    "rare":      (8_000,   40_000),
    "very rare": (40_000, 150_000),
    "very_rare": (40_000, 150_000),
    "legendary": (150_000, 500_000),
    "artifact":  (400_000, 1_200_000),
}

_MIMIR_TYPE_CATEGORY: Dict[str, str] = {
    "weapon": "Weapons",
    "sword":  "Weapons",
    "axe":    "Weapons",
    "bow":    "Weapons",
    "armor":  "Armour",
    "armour": "Armour",
    "shield": "Armour",
    "wand":   "Arcane Instruments",
    "staff":  "Arcane Instruments",
    "rod":    "Arcane Instruments",
    "orb":    "Arcane Instruments",
    "potion": "Consumables",
    "elixir": "Consumables",
    "scroll": "Documents & Lore",
    "ring":   "Utility Gear",
    "cloak":  "Utility Gear",
    "boots":  "Utility Gear",
    "gloves": "Utility Gear",
    "amulet": "Utility Gear",
    "necklace": "Utility Gear",
}


def _mimir_item_to_listing(item: dict) -> Optional[Dict]:
    """Convert a Mimir catalog item dict into a Tower Bay listing dict."""
    name = (item.get("name") or "").strip()
    if not name:
        return None

    rarity_raw = (item.get("rarity") or "rare").lower().strip()
    lo, hi = _MIMIR_RARITY_EC.get(rarity_raw, (8_000, 40_000))
    start = random.randint(lo, hi)
    # Buy Now = 2× starting bid so it's tempting but not a fire sale
    buy_now = int(start * random.uniform(1.8, 2.4))

    # Category from item type
    raw_type = (item.get("item_type") or item.get("type") or "").lower()
    category = "Occult Curiosities"
    for keyword, cat in _MIMIR_TYPE_CATEGORY.items():
        if keyword in raw_type or keyword in name.lower():
            category = cat
            break
    if "wondrous" in raw_type:
        category = "Utility Gear"

    # Description — use Mimir's text or build a short flavor line
    desc_parts = []
    mimir_desc = (item.get("description") or item.get("text") or item.get("content") or "").strip()
    if mimir_desc and len(mimir_desc) > 20:
        # Trim to 2 sentences max for embed cleanliness
        sentences = mimir_desc.replace("\n", " ").split(". ")
        desc_parts.append(". ".join(sentences[:2]).strip().rstrip(".") + ".")
    attune = item.get("requires_attunement") or item.get("attunement") or False
    if attune:
        desc_parts.append("Requires attunement.")
    desc_parts.append("Source authenticated via Mimir catalog. Provenance verified.")
    description = " ".join(desc_parts)

    # Seller — flavour based on rarity
    sellers = [
        "Obsidian Lotus (undisclosed acquisition)",
        "Glass Sigil (decommissioned archive stock)",
        "Iron Fang Consortium (recovered goods)",
        "Private Collector (anonymous)",
        "Adventurers Guild (estate liquidation)",
        "Tower Authority (evidence locker clearance)",
        "Wardens of Ash (field surplus)",
        "Serpent Choir (fulfilled contract collateral)",
    ]
    seller = random.choice(sellers)

    condition_by_rarity = {
        "uncommon": "Good",
        "rare": "Excellent",
        "very rare": "Mint",
        "very_rare": "Mint",
        "legendary": "Mint",
        "artifact": "Unknown",
    }
    condition = condition_by_rarity.get(rarity_raw, "Good")

    now = datetime.now()
    expires_at = now + timedelta(days=TOWERBAY_LISTING_DAYS)

    return {
        "id":            int(now.timestamp() * 1000) % 2_000_000_000,
        "name":          name,
        "description":   description,
        "category":      category,
        "condition":     condition,
        "seller":        seller,
        "rarity":        rarity_raw,
        "mimir_source":  True,
        "starting_bid":  start,
        "current_bid":   start,
        "buy_now_price": buy_now,
        "bid_count":     0,
        "listed_at":     now.isoformat(),
        "expires_at":    expires_at.isoformat(),
        "sold":          False,
    }


async def _fetch_random_mimir_item(existing_names: List[str]) -> Optional[Dict]:
    """Pull one random rare+ item from Mimir catalog and build a listing."""
    try:
        from src.mimir_client import get_mimir
        mimir = get_mimir()
        if not mimir or not mimir._available:
            return None

        existing_lower = {n.lower() for n in existing_names}

        # Cycle through rarities with weighted probability
        rarities = random.choices(
            ["rare", "very rare", "legendary"],
            weights=[60, 30, 10],
            k=3,  # try up to 3 rarities to find something not already listed
        )

        for rarity in rarities:
            items = await mimir.search_items(rarity=rarity)
            if not items:
                continue

            random.shuffle(items)
            for item in items[:20]:
                item_name = (item.get("name") or "").strip()
                if not item_name:
                    continue
                if item_name.lower() in existing_lower:
                    continue
                listing = _mimir_item_to_listing(item)
                if listing:
                    return listing

    except Exception as e:
        logger.debug(f"🏪 Mimir item fetch failed: {e}")
    return None


async def seed_towerbay_from_mimir(count: int = 5) -> int:
    """
    Immediately add `count` real Mimir magic items to Tower Bay.
    Items are injected as active listings without displacing existing ones.
    Returns the number of items successfully added.
    """
    listings = _load_towerbay()
    existing_names = [l["name"] for l in listings]
    added = 0

    for _ in range(count):
        item = await _fetch_random_mimir_item(existing_names)
        if not item:
            logger.warning("🏪 seed_towerbay_from_mimir: no Mimir items returned — stopping early")
            break
        _save_towerbay_item(item)
        existing_names.append(item["name"])
        added += 1
        logger.info(f"🏪 Mimir listing added: {item['name']} ({item.get('rarity','?')}) — start {item['starting_bid']:,} EC")

    return added


async def tick_towerbay() -> tuple[List[Dict], List[Dict]]:
    """
    Tick both the listing board and player listings.
    New slots are filled 100% from the Mimir catalog (real magic items).
    NPC/party bidders are drawn from the live DB roster.
    Returns (ai_sold, player_sold) — lists of items that sold this tick.
    """
    from src.player_listings import tick_player_listings

    # Load named NPC/party bidder pool once per tick
    bidder_pool = _load_npc_bidder_pool()

    # ── Main listings ──────────────────────────────────────────────────────
    listings = _load_towerbay()

    if not listings:
        # First boot — seed with Mimir items; fall back to narrative seed if Mimir unavailable
        mimir_seeded = []
        try:
            existing: List[str] = []
            for _ in range(TOWERBAY_ITEM_COUNT):
                item = await _fetch_random_mimir_item(existing)
                if item:
                    mimir_seeded.append(item)
                    existing.append(item["name"])
        except Exception:
            pass
        listings = mimir_seeded if mimir_seeded else _seed_towerbay()
        _save_towerbay(listings)
        logger.info(f"🏪 TowerBay seeded: {len(listings)} listings ({'Mimir' if mimir_seeded else 'narrative seed'})")
        ai_sold = []
    else:
        listings, ai_sold = _tick_bids(listings, bidder_pool=bidder_pool)
        _award_sold_items(ai_sold)

        active         = [l for l in listings if not l.get("sold")]
        existing_names = [l["name"] for l in listings]

        while len(active) < TOWERBAY_ITEM_COUNT:
            # New slots always come from Mimir — real rare items from the catalog
            new_item = await _fetch_random_mimir_item(existing_names)
            if not new_item:
                # Mimir unavailable — fall back to narrative generation
                new_item = await _generate_new_listing(existing_names)
            if new_item:
                listings.append(new_item)
                active.append(new_item)
                existing_names.append(new_item["name"])
                src = "Mimir" if new_item.get("mimir_source") else "generated"
                logger.info(f"🏪 New listing [{src}]: {new_item['name']} — start {new_item.get('starting_bid',0):,} EC")
            else:
                break

        _save_towerbay(listings)

    # ── Player listings ────────────────────────────────────────────────────
    player_sold = tick_player_listings()

    return ai_sold, player_sold


def format_towerbay_bulletin() -> str:
    listings = _load_towerbay()
    active   = [l for l in listings if not l.get("sold")]
    active.sort(key=lambda x: x["current_bid"], reverse=True)

    now   = datetime.now()
    lines = [
        "🏪 **TOWERBAY — TOP LISTINGS** 🏪",
        f"-# {_dual_ts()}",
        "",
    ]

    for i, item in enumerate(active[:10], 1):
        try:
            expires   = datetime.fromisoformat(item["expires_at"])
            days_left = max(0, (expires - now).days)
            time_str  = f"{days_left}d left" if days_left > 0 else "ending soon"
        except Exception:
            time_str = "?"

        bid_str  = _ec(item["current_bid"])
        bids_str = f"{item['bid_count']} bid{'s' if item['bid_count'] != 1 else ''}"
        arrow    = "🔥" if item["bid_count"] >= 5 else ("📈" if item["bid_count"] >= 2 else "🆕")

        lines.append(
            f"{arrow} **{i}. {item['name']}**  ·  `{item['category']}`  ·  _{item['condition']}_\n"
            f"   ┣ {item['description'][:120]}{'…' if len(item['description']) > 120 else ''}\n"
            f"   ┣ **Current bid:** {bid_str}  ({bids_str})  ·  ⏳ {time_str}\n"
            f"   ┗ *Seller: {item['seller']}*"
        )

    lines.append("")
    lines.append("-# Bids accepted at any registered Exchange kiosk. All sales final. TowerBay accepts no liability.")
    lines.append("-# 📦 **Want to sell something?** Use `/towerbay` to list an item from your character sheet — the DM reviews it before it goes live. Use `/myauctions` to check the status of your active listings.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tower Industrial Average (TIA)
# ---------------------------------------------------------------------------

TIA_SECTORS = [
    {"key": "relic",       "name": "Relic & Antiquities",      "base": 4_820},
    {"key": "essence",     "name": "Essence Coin Exchange",     "base": 8_150},
    {"key": "adventurer",  "name": "Adventurer Contracts",      "base": 3_340},
    {"key": "divine",      "name": "Divine Services & Kharma",  "base": 2_910},
    {"key": "smuggling",   "name": "Grey Market Logistics",     "base": 5_670},
    {"key": "memory",      "name": "Memory & Information",      "base": 1_880},
    {"key": "security",    "name": "Security & Enforcement",    "base": 2_240},
    {"key": "rift_tech",   "name": "Rift Technology",           "base": 1_120},
]

_TIA_EVENTS = [
    ("relic",       +0.08, "Iron Fang auction clearance drives relic demand"),
    ("relic",       -0.06, "FTA seizure of unlicensed relics floods market"),
    ("essence",     +0.05, "EC/Kharma exchange rate stabilises after volatility"),
    ("essence",     -0.07, "Counterfeit EC batch detected in Cobbleway Market"),
    ("adventurer",  +0.10, "High-tier Rift mission board surge drives contract demand"),
    ("adventurer",  -0.08, "Two A-Rank parties disbanded; contracts unassigned"),
    ("divine",      +0.12, "Serpent Choir announces new miracle tier; Kharma demand spikes"),
    ("divine",      -0.09, "God-contract default scandal suppresses Kharma trading"),
    ("smuggling",   +0.07, "New access tunnel opens through Outer Wall undercroft"),
    ("smuggling",   -0.10, "Wardens raid Neon Row warehouse; grey market logistics disrupted"),
    ("memory",      +0.06, "Obsidian Lotus memory-erasure waitlist drives information premium"),
    ("memory",      -0.05, "FTA investigation chills memory market transactions"),
    ("security",    +0.09, "Warden contract expansion approved by FTA"),
    ("security",    -0.06, "Night Pits gang activity spooks private security clients"),
    ("rift_tech",   +0.15, "Glass Sigil patents new residue stabilisation method"),
    ("rift_tech",   -0.12, "Experimental containment device failure shakes investor confidence"),
]


def _load_tia() -> Dict:
    """Load TIA state from database."""
    try:
        rows = raw_query("SELECT * FROM tia_market")
        if not rows:
            return {}
        
        state = {
            "sectors": {},
            "last_updated": None,
            "last_event": None,
        }
        
        for row in rows:
            sector_key = row.get("sector")
            if not sector_key:
                continue

            value = float(row.get("value", 100.0))
            # Use stored prev_value if available; fall back to current value
            prev_value = row.get("prev_value")
            prev_value = float(prev_value) if prev_value is not None else value
            trend = row.get("trend", "") or ""

            sector_info = next((s for s in TIA_SECTORS if s["key"] == sector_key), None)
            sector_name = sector_info["name"] if sector_info else sector_key

            change_pct = round(((value - prev_value) / prev_value) * 100, 2) if prev_value else 0.0

            state["sectors"][sector_key] = {
                "name": sector_name,
                "value": value,
                "prev_value": prev_value,
                "change_pct": change_pct,
            }

            if trend and state["last_event"] is None:
                state["last_event"] = trend if not trend.startswith("{") else None

            if row.get("updated_at") and state["last_updated"] is None:
                state["last_updated"] = row["updated_at"].isoformat() if hasattr(row["updated_at"], 'isoformat') else str(row["updated_at"])
        
        return state
    except Exception as e:
        logger.error(f"TIA load error: {e}")
        return {}


def _save_tia(state: Dict) -> None:
    """Save TIA state to database."""
    try:
        sectors = state.get("sectors", {})
        last_event = state.get("last_event", "") or "stable"

        for sector_key, sector_data in sectors.items():
            value = sector_data.get("value", 100.0)
            prev_value = sector_data.get("prev_value", value)

            existing = raw_query(
                "SELECT id FROM tia_market WHERE sector = %s",
                (sector_key,)
            )

            if existing:
                raw_execute(
                    "UPDATE tia_market SET value = %s, prev_value = %s, trend = %s, updated_at = NOW() WHERE sector = %s",
                    (value, prev_value, last_event, sector_key)
                )
            else:
                db.insert("tia_market", {
                    "sector": sector_key,
                    "value": value,
                    "prev_value": prev_value,
                    "trend": last_event,
                })
    except Exception as e:
        logger.error(f"TIA save error: {e}")


def _init_tia() -> Dict:
    state = {
        "sectors":      {},
        "last_updated": datetime.now().isoformat(),
        "last_event":   None,
    }
    for s in TIA_SECTORS:
        base = s["base"]
        val  = base * random.uniform(0.90, 1.10)
        state["sectors"][s["key"]] = {
            "name":       s["name"],
            "value":      round(val, 2),
            "prev_value": round(val, 2),
            "change_pct": 0.0,
        }
    return state


def tick_tia() -> tuple:
    state = _load_tia()
    if not state or "sectors" not in state:
        state = _init_tia()

    event_desc = None

    if random.random() < 0.08:
        ev = random.choice(_TIA_EVENTS)
        key, delta, desc = ev
        if key in state["sectors"]:
            sec = state["sectors"][key]
            sec["prev_value"] = sec["value"]
            sec["value"]      = round(sec["value"] * (1 + delta), 2)
            sec["change_pct"] = round(delta * 100, 2)
            event_desc        = desc
            state["last_event"] = desc

    for key, sec in state["sectors"].items():
        drift = random.uniform(-0.02, 0.02)
        prev  = sec["value"]
        sec["prev_value"] = prev
        sec["value"]      = round(max(100, prev * (1 + drift)), 2)
        sec["change_pct"] = round(((sec["value"] - prev) / prev) * 100, 2)

    state["last_updated"] = datetime.now().isoformat()
    _save_tia(state)
    return state, event_desc


def format_tia_bulletin(event_desc: Optional[str] = None) -> str:
    state = _load_tia()
    if not state or "sectors" not in state:
        state = _init_tia()
        _save_tia(state)

    lines = [
        "📊 **TOWER INDUSTRIAL AVERAGE — MARKET CLOSE** 📊",
        f"-# {_dual_ts()}",
        "",
    ]

    sectors = sorted(state["sectors"].items(), key=lambda x: x[1]["value"], reverse=True)

    for key, sec in sectors:
        val = sec["value"]
        chg = sec["change_pct"]

        if chg > 0.5:
            arrow = "🟢 ▲"
        elif chg < -0.5:
            arrow = "🔴 ▼"
        else:
            arrow = "⬜ ─"

        sign    = "+" if chg >= 0 else ""
        chg_str = f"{sign}{chg:.2f}%"
        val_str = f"{val:,.0f}"

        lines.append(f"{arrow}  **{sec['name']}**  `{val_str}`  _{chg_str}_")

    lines.append("")

    all_vals   = [s["value"] for s in state["sectors"].values()]
    all_prevs  = [s["prev_value"] for s in state["sectors"].values()]
    
    # Guard against empty sectors (ZeroDivisionError fix)
    if not all_vals:
        state = _init_tia()
        _save_tia(state)
        all_vals  = [s["value"] for s in state["sectors"].values()]
        all_prevs = [s["prev_value"] for s in state["sectors"].values()]
    
    index_now  = sum(all_vals)  / len(all_vals)
    index_prev = sum(all_prevs) / len(all_prevs)
    index_chg  = ((index_now - index_prev) / index_prev) * 100 if index_prev else 0
    idx_arrow  = "🟢 ▲" if index_chg > 0.1 else ("🔴 ▼" if index_chg < -0.1 else "⬜ ─")
    lines.append(f"**TIA COMPOSITE** {idx_arrow}  `{index_now:,.0f}`  _{'+' if index_chg >= 0 else ''}{index_chg:.2f}%_")

    if event_desc:
        lines.append("")
        lines.append(f"📌 *Market note: {event_desc}*")
    elif state.get("last_event"):
        lines.append("")
        lines.append(f"-# Last major event: {state['last_event']}")

    lines.append("")
    lines.append("-# TIA data provided by Glass Sigil Economic Monitoring Division. Not financial advice.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Embed-formatted TowerBay board (color-coded by category)
# ---------------------------------------------------------------------------

_CATEGORY_COLORS = {
    "Weapons":              0xCC3333,  # red
    "Armour":               0x5588CC,  # steel blue
    "Arcane Instruments":   0x9933CC,  # purple
    "Utility Gear":         0x777777,  # grey
    "Documents & Lore":     0xCC9933,  # amber
    "Occult Curiosities":   0x336633,  # dark green
    "Consumables":          0x33AA77,  # teal
    "Memorabilia":          0xAA7733,  # bronze
    "Contraband":           0x993333,  # dark red
    "Vehicles & Mounts":    0x5577AA,  # blue-grey
}


def format_towerbay_embeds():
    """Return a list of discord.Embed objects for the TowerBay board.
    Each item gets its own embed, color-coded by category."""
    import discord

    listings = _load_towerbay()
    active   = [l for l in listings if not l.get("sold")]
    active.sort(key=lambda x: x["current_bid"], reverse=True)

    now    = datetime.now()
    embeds = []

    # Header embed
    header = discord.Embed(
        title="\U0001f3ea TOWERBAY \u2014 TOP LISTINGS",
        description=f"-# {_dual_ts()}\nBids accepted at any registered Exchange kiosk. All sales final.",
        color=0xCC9933,
    )
    embeds.append(header)

    for i, item in enumerate(active[:10], 1):
        try:
            expires   = datetime.fromisoformat(item["expires_at"])
            days_left = max(0, (expires - now).days)
            time_str  = f"{days_left}d left" if days_left > 0 else "\u23f3 ending soon"
        except Exception:
            time_str = "?"

        bid_str  = _ec(item["current_bid"])
        bids_str = f"{item['bid_count']} bid{'s' if item['bid_count'] != 1 else ''}"
        arrow    = "\U0001f525" if item["bid_count"] >= 5 else ("\U0001f4c8" if item["bid_count"] >= 2 else "\U0001f195")

        category = item.get("category", "Utility Gear")
        color    = _CATEGORY_COLORS.get(category, 0x777777)

        buy_now_price = item.get("buy_now_price")
        buy_now_str   = f"**Buy Now:** {_ec(buy_now_price)}" if buy_now_price else ""

        # Named NPC/party bidder — named trumps anonymous
        npc_bidder  = item.get("npc_bidder_name")
        high_bidder = npc_bidder or item.get("highest_bidder_name")
        bidder_line = (chr(10) + "🏆 *Current high bid: " + high_bidder + "*") if high_bidder else ""

        # Rarity badge for Mimir items
        _rarity     = (item.get("rarity") or "").lower()
        _RBADGES    = {
            "uncommon":  "🟢 Uncommon",
            "rare":      "🔵 Rare",
            "very rare": "🟣 Very Rare",
            "very_rare": "🟣 Very Rare",
            "legendary": "🟠 Legendary",
            "artifact":  "🔴 Artifact",
        }
        rarity_prefix = ("**" + _RBADGES[_rarity] + "**  ·  ") if _rarity in _RBADGES else ""

        desc = (
            f"{item['description'][:180]}" + chr(10) + chr(10)
            + rarity_prefix
            + f"**Current bid:** {bid_str}  ({bids_str})" + bidder_line + chr(10)
            + (f"{buy_now_str}" + chr(10) if buy_now_str else "")
            + f"**Condition:** {item.get('condition', '?')}  ·  **Seller:** {item.get('seller', '?')}"
        )

        item_id   = item.get("id", "?")
        mimir_tag = " ❖" if item.get("mimir_source") else ""
        embed = discord.Embed(
            title=f"{arrow} Lot #{item_id} — {item['name']}{mimir_tag}",
            description=desc,
            color=color,
        )
        embed.set_footer(text=f"{category}  •  {time_str}  •  /bid {item_id} <amount>")
        embeds.append(embed)

    # Footer embed
    footer_embed = discord.Embed(
        description=(
            "**To bid:** `/bid <lot#> <amount>` — or `/buynow <lot#>` to buy instantly.\n"
            "**To sell:** `/towerbay` — DM reviews before it goes live.\n"
            "Use `/mybids` to track your active bids. Use `/myauctions` for your listings."
        ),
        color=0x777777,
    )
    embeds.append(footer_embed)

    return embeds


# ---------------------------------------------------------------------------
# Real-player bid engine
# ---------------------------------------------------------------------------

def _ensure_bid_columns() -> None:
    """Idempotent: ensure towerbay_auctions has real-bidder columns."""
    try:
        cols = raw_query(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'towerbay_auctions'"
        )
        existing = {r["COLUMN_NAME"] for r in (cols or [])}
        if "highest_bidder_id" not in existing:
            raw_execute("ALTER TABLE towerbay_auctions ADD COLUMN highest_bidder_id BIGINT DEFAULT NULL")
        if "highest_bidder_name" not in existing:
            raw_execute("ALTER TABLE towerbay_auctions ADD COLUMN highest_bidder_name VARCHAR(100) DEFAULT NULL")
        if "proxy_max" not in existing:
            raw_execute("ALTER TABLE towerbay_auctions ADD COLUMN proxy_max BIGINT DEFAULT NULL")
        raw_execute("""
            CREATE TABLE IF NOT EXISTS towerbay_bids (
                id           INT AUTO_INCREMENT PRIMARY KEY,
                listing_id   VARCHAR(50)            NOT NULL,
                listing_type ENUM('ai','player')     NOT NULL DEFAULT 'ai',
                bidder_id    BIGINT                 NOT NULL,
                bidder_name  VARCHAR(100)           NOT NULL,
                amount       BIGINT                 NOT NULL,
                proxy_max    BIGINT                 DEFAULT NULL,
                successful   TINYINT(1)             NOT NULL DEFAULT 1,
                bid_at       DATETIME               NOT NULL DEFAULT NOW(),
                INDEX idx_listing (listing_id, listing_type),
                INDEX idx_bidder  (bidder_id)
            )
        """)
    except Exception as e:
        logger.warning(f"TowerBay bid column check: {e}")


# Run on import so the columns are always present
try:
    _ensure_bid_columns()
except Exception as _e:
    logger.warning("TowerBay bid column startup failed: %s", _e)


def _log_bid(
    listing_id: str,
    listing_type: str,
    bidder_id: int,
    bidder_name: str,
    amount: int,
    successful: bool,
    proxy_max: Optional[int] = None,
) -> None:
    try:
        db.insert("towerbay_bids", {
            "listing_id":   str(listing_id),
            "listing_type": listing_type,
            "bidder_id":    bidder_id,
            "bidder_name":  bidder_name,
            "amount":       amount,
            "proxy_max":    proxy_max,
            "successful":   1 if successful else 0,
        })
    except Exception as e:
        logger.warning(f"towerbay_bids log error: {e}")


def place_bid(
    listing_id: int,
    bidder_id: int,
    bidder_name: str,
    amount: int,
    proxy_max: Optional[int] = None,
) -> Dict:
    """
    Place a real player bid on an AI-generated TowerBay listing.
    Returns:
        success       bool
        message       str   — shown to the bidder
        outbid_user   dict  — {id, name} of the player just knocked off top spot, or None
        new_price     int   — current bid after this action
        item_name     str
    """
    rows = raw_query(
        "SELECT * FROM towerbay_auctions WHERE id = %s AND status = 'active'", (listing_id,)
    )
    if not rows:
        return {"success": False, "message": "That lot doesn't exist or has already closed.", "outbid_user": None}

    row           = rows[0]
    current_bid   = int(row.get("current_bid") or 0)
    buy_now_price = row.get("buy_now_price")
    seller_id     = row.get("seller_id")
    curr_holder   = row.get("highest_bidder_id")
    curr_proxy    = row.get("proxy_max")
    item_name     = row.get("item_name", "Unknown")

    if seller_id and int(seller_id) == bidder_id:
        return {"success": False, "message": "You can't bid on your own listing.", "outbid_user": None}

    if curr_holder and int(curr_holder) == bidder_id:
        if proxy_max and proxy_max > (curr_proxy or 0):
            # Updating proxy max only
            raw_execute(
                "UPDATE towerbay_auctions SET proxy_max = %s WHERE id = %s",
                (proxy_max, listing_id)
            )
            return {
                "success": True,
                "message": f"Your max auto-bid updated to **{proxy_max:,} EC**.",
                "outbid_user": None,
                "new_price": current_bid,
                "item_name": item_name,
            }
        return {"success": False, "message": "You're already the highest bidder!", "outbid_user": None}

    # Minimum increment: 5% above current bid, at least 500 EC
    min_bid = max(current_bid + 500, int(current_bid * 1.05))
    if amount < min_bid:
        return {
            "success": False,
            "message": f"Minimum bid is **{min_bid:,} EC** (5% above current {current_bid:,} EC).",
            "outbid_user": None,
        }

    # Existing proxy can counter this bid
    if curr_holder and curr_proxy and curr_proxy >= amount:
        counter = min(int(amount * 1.05), curr_proxy)
        raw_execute(
            "UPDATE towerbay_auctions SET current_bid = %s WHERE id = %s",
            (counter, listing_id)
        )
        _log_bid(str(listing_id), "ai", bidder_id, bidder_name, amount, False)
        return {
            "success": False,
            "message": (
                f"A proxy bid held by another buyer countered yours. "
                f"Current bid is now **{counter:,} EC**."
            ),
            "outbid_user": None,
            "new_price": counter,
        }

    # Bid succeeds — record who got knocked off
    outbid_user = None
    if curr_holder:
        outbid_user = {
            "id":   int(curr_holder),
            "name": row.get("highest_bidder_name") or "Unknown",
        }

    raw_execute(
        "UPDATE towerbay_auctions "
        "SET current_bid = %s, highest_bidder_id = %s, highest_bidder_name = %s, proxy_max = %s "
        "WHERE id = %s",
        (amount, bidder_id, bidder_name, proxy_max, listing_id),
    )

    # Keep bid_count in sync inside auction_json blob
    try:
        aj_row = raw_query("SELECT auction_json FROM towerbay_auctions WHERE id = %s", (listing_id,))
        if aj_row and aj_row[0].get("auction_json"):
            aj = aj_row[0]["auction_json"]
            if isinstance(aj, str):
                aj = json.loads(aj)
            aj["bid_count"]          = aj.get("bid_count", 0) + 1
            aj["current_bid"]        = amount
            aj["highest_bidder_id"]  = bidder_id
            aj["highest_bidder_name"] = bidder_name
            raw_execute(
                "UPDATE towerbay_auctions SET auction_json = %s WHERE id = %s",
                (json.dumps(aj), listing_id),
            )
    except Exception:
        pass

    _log_bid(str(listing_id), "ai", bidder_id, bidder_name, amount, True, proxy_max)
    logger.info(f"🏪 Real bid: {bidder_name} → Lot #{listing_id} at {amount:,} EC")

    return {
        "success":     True,
        "message":     f"Bid placed: **{amount:,} EC** on *{item_name}*.",
        "outbid_user": outbid_user,
        "new_price":   amount,
        "item_name":   item_name,
    }


def buy_now(listing_id: int, buyer_id: int, buyer_name: str) -> Dict:
    """
    Immediately purchase a listing at its buy_now_price.
    Returns: {success, message, price, item_name}
    """
    rows = raw_query(
        "SELECT * FROM towerbay_auctions WHERE id = %s AND status = 'active'", (listing_id,)
    )
    if not rows:
        return {"success": False, "message": "That lot doesn't exist or has already closed."}

    row           = rows[0]
    buy_now_price = row.get("buy_now_price")
    seller_id     = row.get("seller_id")
    item_name     = row.get("item_name", "Unknown")

    if not buy_now_price:
        return {"success": False, "message": "This listing doesn't have a Buy Now price."}

    if seller_id and int(seller_id) == buyer_id:
        return {"success": False, "message": "You can't buy your own listing."}

    # Mark sold immediately
    raw_execute(
        "UPDATE towerbay_auctions "
        "SET status = 'sold', current_bid = %s, winner_id = %s, "
        "    highest_bidder_id = %s, highest_bidder_name = %s "
        "WHERE id = %s",
        (buy_now_price, buyer_id, buyer_id, buyer_name, listing_id),
    )
    _log_bid(str(listing_id), "ai", buyer_id, buyer_name, buy_now_price, True)
    logger.info(f"🏪 Buy Now: {buyer_name} → Lot #{listing_id} *{item_name}* at {buy_now_price:,} EC")

    return {
        "success":   True,
        "message":   f"You bought *{item_name}* for **{buy_now_price:,} EC**. Congratulations!",
        "price":     buy_now_price,
        "item_name": item_name,
        # Previous highest bidder needs a refund notification — caller handles it
        "outbid_user": {
            "id":   int(row["highest_bidder_id"]),
            "name": row.get("highest_bidder_name") or "Unknown",
        } if row.get("highest_bidder_id") else None,
    }


def get_active_listings() -> List[Dict]:
    """Return active AI listings — used for autocomplete and /mybids."""
    try:
        rows = raw_query(
            "SELECT id, item_name, current_bid, buy_now_price, "
            "highest_bidder_id, highest_bidder_name, expires_at "
            "FROM towerbay_auctions WHERE status = 'active' ORDER BY current_bid DESC"
        )
        return rows or []
    except Exception as e:
        logger.error(f"get_active_listings error: {e}")
        return []


def get_player_bids(player_id: int) -> List[Dict]:
    """Return all recent bids by a player across AI and player listings."""
    try:
        rows = raw_query(
            "SELECT tb.*, "
            "  CASE tb.listing_type "
            "    WHEN 'ai' THEN ta.item_name "
            "    ELSE pl.item_name END AS item_name, "
            "  CASE tb.listing_type "
            "    WHEN 'ai' THEN ta.status "
            "    ELSE pl.status END AS listing_status, "
            "  CASE tb.listing_type "
            "    WHEN 'ai' THEN ta.highest_bidder_id "
            "    ELSE pl.highest_bidder_id END AS current_winner_id "
            "FROM towerbay_bids tb "
            "LEFT JOIN towerbay_auctions ta ON tb.listing_type = 'ai' "
            "  AND CAST(tb.listing_id AS UNSIGNED) = ta.id "
            "LEFT JOIN player_listings pl ON tb.listing_type = 'player' "
            "  AND tb.listing_id = CONCAT('pl_', pl.id) "
            "WHERE tb.bidder_id = %s AND tb.successful = 1 "
            "ORDER BY tb.bid_at DESC LIMIT 20",
            (player_id,)
        )
        return rows or []
    except Exception as e:
        logger.error(f"get_player_bids error: {e}")
        return []
