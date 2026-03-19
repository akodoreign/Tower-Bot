"""
tower_economy.py — TowerBay auction house and Tower Industrial Average (TIA) ticker.

TowerBay: 10 active auction listings at all times. Items sell after 7 real days,
replaced with fresh AI-generated listings. Prices start at 10,000+ EC with bids
that drift upward over the week.

TIA: A fictional stock-market-style index of 8 Undercity "industries". Values
shift each tick with small random drift plus occasional event-driven spikes.
Formatted as a scrolling ticker for Discord.

Both persist to JSON in campaign_docs/.
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from src.log import logger

DOCS_DIR         = Path(__file__).resolve().parent.parent / "campaign_docs"
TOWERBAY_FILE    = DOCS_DIR / "towerbay.json"
TIA_FILE         = DOCS_DIR / "tia.json"

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
_REACTION_COOLDOWN_FILE = DOCS_DIR / "tia_reaction_cooldown.json"


def _load_reaction_cooldown() -> Optional[datetime]:
    if not _REACTION_COOLDOWN_FILE.exists():
        return None
    try:
        data = json.loads(_REACTION_COOLDOWN_FILE.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data.get("last_reaction_at", ""))
    except Exception:
        return None


def _save_reaction_cooldown() -> None:
    try:
        _REACTION_COOLDOWN_FILE.write_text(
            json.dumps({"last_reaction_at": datetime.now().isoformat()}),
            encoding="utf-8"
        )
    except Exception:
        pass


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
    ts    = f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"

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
    return f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"


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
    if not TOWERBAY_FILE.exists():
        return []
    try:
        return json.loads(TOWERBAY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_towerbay(listings: List[Dict]) -> None:
    try:
        TOWERBAY_FILE.write_text(json.dumps(listings, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"TowerBay save error: {e}")


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


def _tick_bids(listings: List[Dict]) -> tuple:
    now = datetime.now()
    sold_this_tick = []
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
        if random.random() < 0.30:
            bump = random.uniform(0.03, 0.12)
            item["current_bid"] = int(item["current_bid"] * (1 + bump))
            item["bid_count"]  += 1
    return listings, sold_this_tick


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

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(ollama_url, json={
                "model":    ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream":   False,
            })
            resp.raise_for_status()
            data = resp.json()

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

        return {
            "id":           int(datetime.now().timestamp()),
            "name":         item.get("name", "Unknown Item"),
            "description":  item.get("description", ""),
            "category":     item.get("category", category),
            "condition":    item.get("condition", "Unknown"),
            "seller":       item.get("seller", "Anonymous"),
            "starting_bid": start,
            "current_bid":  start,
            "bid_count":    0,
            "listed_at":    now.isoformat(),
            "expires_at":   expires_at.isoformat(),
            "sold":         False,
        }

    except Exception as e:
        logger.error(f"TowerBay new listing error: {e}")
        return None


async def tick_towerbay() -> tuple[List[Dict], List[Dict]]:
    """
    Tick both the AI listing board and player listings.
    Returns (ai_sold, player_sold) — lists of items that sold this tick.
    """
    from src.player_listings import tick_player_listings

    # ── AI listings ────────────────────────────────────────────────────────
    listings = _load_towerbay()

    if not listings:
        listings = _seed_towerbay()
        _save_towerbay(listings)
        logger.info("🏪 TowerBay seeded with initial 10 listings.")
        ai_sold = []
    else:
        listings, ai_sold = _tick_bids(listings)

        active         = [l for l in listings if not l.get("sold")]
        existing_names = [l["name"] for l in listings]

        while len(active) < TOWERBAY_ITEM_COUNT:
            new_item = await _generate_new_listing(existing_names)
            if new_item:
                listings.append(new_item)
                active.append(new_item)
                existing_names.append(new_item["name"])
                logger.info(f"🏪 New TowerBay listing: {new_item['name']}")
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
    if not TIA_FILE.exists():
        return {}
    try:
        return json.loads(TIA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_tia(state: Dict) -> None:
    try:
        TIA_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
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

        desc = (
            f"{item['description'][:200]}\n\n"
            f"**Current bid:** {bid_str}  ({bids_str})\n"
            f"**Condition:** {item.get('condition', '?')}  \u00b7  **Seller:** {item.get('seller', '?')}"
        )

        embed = discord.Embed(
            title=f"{arrow} {item['name']}",
            description=desc,
            color=color,
        )
        embed.set_footer(text=f"{category}  \u2022  {time_str}")
        embeds.append(embed)

    # Footer embed
    footer_embed = discord.Embed(
        description=(
            "\U0001f4e6 **Want to sell something?** Use `/towerbay` to list an item \u2014 "
            "the DM reviews it before it goes live. Use `/myauctions` to check your listings."
        ),
        color=0x777777,
    )
    embeds.append(footer_embed)

    return embeds
