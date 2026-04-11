"""
ec_exchange.py — EC/Kharma exchange rate tracker for Tower of Last Chance.
*** REFACTORED TO USE MySQL via db_api ***

CANON:
  Essence Coins (EC) are common currency, formed from Kharma for everyday trade.
  Kharma is the premium faith-crystallised currency — rarer and more powerful.
  Base rate: 10 EC = 1 Kharma.

INFLATION:
  Slow natural drift of ~1–2% per real month.
  Per bulletin tick (~1 hour): ~0.002% drift (adds up to ~1.5%/month).
  Major news events can shock the rate by up to ±10%.
"""

from __future__ import annotations

import json
import random
import logging
from datetime import datetime
from typing import Optional

from src.db_api import get_economy_state, update_economy_state

logger = logging.getLogger(__name__)

# Base rate: how many EC per 1 Kharma
EC_BASE_RATE   = 10.0
EC_TICK_DRIFT  = 0.00002
EC_TICK_NOISE  = 0.0001
EC_RATE_FLOOR  = 5.0
EC_RATE_CEIL   = 50.0
EC_HISTORY_MAX = 30
TOWER_YEAR_OFFSET = 10


def _dual_ts() -> str:
    now = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    return f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"


def _load() -> dict:
    """Load economy state from database."""
    try:
        state = get_economy_state()
        if not state:
            return {}
        # Rate is stored in ec_to_kharma_rate, full data might be in a JSON field
        return {
            "rate": float(state.get("ec_to_kharma_rate", EC_BASE_RATE)),
            "trend": state.get("trend", "stable"),
            "last_updated": str(state.get("updated_at", "")),
            "history": [],  # History tracking simplified for DB
            "last_event": state.get("trend", "normal drift"),
        }
    except Exception as e:
        logger.error(f"ec_exchange load error: {e}")
        return {}


def _save(data: dict) -> None:
    """Save economy state to database."""
    try:
        trend = data.get("last_event", "stable")
        if len(trend) > 50:
            trend = trend[:47] + "..."
        update_economy_state({
            "ec_to_kharma_rate": data.get("rate", EC_BASE_RATE),
            "trend": trend,
        })
    except Exception as e:
        logger.error(f"ec_exchange save error: {e}")


def _init() -> dict:
    return {
        "rate":         EC_BASE_RATE,
        "last_updated": datetime.now().isoformat(),
        "history":      [],
        "last_event":   None,
    }


def get_rate() -> float:
    """Return the current EC-per-Kharma rate."""
    data = _load()
    return float(data.get("rate", EC_BASE_RATE))


def tick_exchange() -> float:
    """Apply one bulletin-tick of inflation drift. Returns the new rate."""
    data = _load()
    if not data:
        data = _init()

    old_rate = float(data.get("rate", EC_BASE_RATE))
    noise    = random.uniform(-EC_TICK_NOISE, EC_TICK_NOISE)
    new_rate = old_rate * (1 + EC_TICK_DRIFT + noise)
    new_rate = round(max(EC_RATE_FLOOR, min(EC_RATE_CEIL, new_rate)), 4)

    data["rate"] = new_rate
    data["last_event"] = "tick"
    data["last_updated"] = datetime.now().isoformat()
    _save(data)
    return new_rate


def apply_event_shock(delta_pct: float, reason: str = "") -> tuple[float, float]:
    """Apply an event-driven shock to the exchange rate."""
    data = _load()
    if not data:
        data = _init()

    old_rate = float(data.get("rate", EC_BASE_RATE))
    delta_pct = max(-0.10, min(0.10, delta_pct))
    new_rate  = round(max(EC_RATE_FLOOR, min(EC_RATE_CEIL, old_rate * (1 + delta_pct))), 4)

    data["rate"] = new_rate
    data["last_event"] = reason or f"Market shock {delta_pct:+.1%}"
    data["last_updated"] = datetime.now().isoformat()
    _save(data)

    logger.info(f"💱 EC exchange shock: {old_rate:.4f} → {new_rate:.4f} EC/Kharma ({delta_pct:+.1%}) — {reason}")
    return old_rate, new_rate


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def format_exchange_line() -> str:
    """One-liner for embedding in bulletins or /finances."""
    rate = get_rate()
    return (
        f"💱 **EC/Kharma Rate:** `1 Kharma = {rate:.2f} EC`  "
        f"│  `10 Kharma = {rate*10:.1f} EC`  "
        f"│  `100 Kharma = {rate*100:.0f} EC`"
    )


_EXAMPLE_GOODS = [
    ("Healing Potion (basic)",  50,    "2d4+2 HP"),
    ("Hot meal (Grand Forum)",   3,    "standard inn fare"),
    ("Torch bundle (10)",        2,    "standard"),
    ("Rope, 50 ft",              5,    "hemp"),
    ("Night's lodging",         15,    "Markets Infinite inn"),
    ("Rift-ward (1 hour)",      50,    "temporary residue shield"),
    ("God-tongue ink vial",    500,    "Obsidian Lotus grade"),
    ("Adventurer license",     100,    "FTA annual fee"),
]


def format_exchange_bulletin() -> str:
    """Full bulletin-style block for the daily midday EC/Kharma rate post."""
    data  = _load()
    if not data:
        data = _init()

    rate    = float(data.get("rate", EC_BASE_RATE))
    last_ev = data.get("last_event", "normal market drift")

    change_str = ""  # Simplified without history tracking

    import random as _random
    sampled = _random.sample(_EXAMPLE_GOODS, min(3, len(_EXAMPLE_GOODS)))

    lines = [
        "💱 **UNDERCITY DISPATCH — DAILY EXCHANGE RATES** 💱",
        f"-# {_dual_ts()}",
        "",
        "**Current Essence Coin / Kharma Rate:**",
        f"`1 Kharma  = {rate:.2f} EC`{change_str}",
        f"`10 Kharma = {rate*10:.1f} EC`",
        f"`100 Kharma = {rate*100:.0f} EC`",
        "",
        "**Sample Prices (EC) at today\'s rate:**",
    ]
    for name, base, desc in sampled:
        inflated = round(base * (rate / EC_BASE_RATE), 2)
        lines.append(f"└ **{name}** — _{desc}_ · `{inflated:.2f} EC`")

    lines += [
        "",
        f"-# Rate note: {last_ev}",
        "-# Exchange kiosks at Cobbleway Market, Grand Forum, and Guild Spires.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Price reference tables (static — from campaign docs)
# ---------------------------------------------------------------------------

PRICE_TABLES = {
    "quest_rewards": {
        "title": "Quest Reward Tiers",
        "entries": [
            ("Local (Lvl 1-2)",    "Escort, delivery, patrol",              "+10 Kharma,  +1 LP"),
            ("Standard (Lvl 2-4)", "Guild dispute, Rift closure",           "+50 Kharma,  +2 LP"),
            ("Major (Lvl 5-8)",    "Political mission, divine interference", "+100 Kharma, +3 LP"),
            ("Epic (Lvl 9+)",      "Council upheaval, godslaying",           "+500 Kharma, +5 LP"),
        ],
    },
    "hireables": {
        "title": "Hireable Adventurers (EC/day)",
        "entries": [
            ("Rank 1 Hireable",  "Basic fighter/scout",                   "50–100 EC/day"),
            ("Rank 2 Hireable",  "Experienced, discerning",               "100–200 EC/day"),
            ("Rank 3+ Hireable", "Confident, may refuse unsafe work",     "200–500 EC/day"),
            ("Long-term (7+ days)", "Loyalty discount",                   "-10% per week"),
            ("Specialised",      "Traps, stealth, divine rituals, craft", "+10–30 EC/day"),
            ("Dual-role",        "e.g. Fighter/Mage, Cleric/Rogue",       "+15–40 EC/day"),
            ("Famous Adventurer","High Rank or fame premium",             "+20–50 EC/day"),
        ],
    },
    "services": {
        "title": "Common Services (EC)",
        "entries": [
            ("Serpent Choir blessing",    "Minor divine contract",              "50–500 EC"),
            ("Obsidian Lotus memory job", "Memory erasure or retrieval",        "500–5,000 EC"),
            ("Iron Fang relic appraisal", "Item valuation",                     "25–200 EC"),
            ("Glass Sigil Rift analysis", "Anomaly survey",                     "100–1,000 EC"),
            ("Adventurers Guild contract","Quest posting fee",                  "10–50 EC"),
            ("FTA license renewal",       "Adventurer license",                 "100 EC/year"),
            ("Warden escort (1 day)",     "Personal security",                  "75–300 EC"),
            ("Patchwork Saints aid",      "Warrens medical/shelter",            "5–20 EC (sliding scale)"),
        ],
    },
    "goods": {
        "title": "Common Goods (EC)",
        "entries": [
            ("Hot meal, Grand Forum",    "Basic inn meal",             "2–5 EC"),
            ("Bed for the night",        "Warrens hostel",             "3–10 EC"),
            ("Bed for the night",        "Markets Infinite inn",       "10–30 EC"),
            ("Torch bundle (10)",        "Standard",                   "2 EC"),
            ("Rope (50 ft)",             "Hemp",                       "5 EC"),
            ("Healing potion",           "Basic (2d4+2 HP)",           "50 EC"),
            ("Healing potion",           "Greater (4d4+4 HP)",         "150 EC"),
            ("Rift-residue shielding",   "Temporary ward, 1 hour",     "30–80 EC"),
            ("God-tongue ink vial",      "Obsidian Lotus",             "200–2,000 EC"),
            ("Blank divine contract",    "Serpent Choir grade",        "500–5,000 EC"),
        ],
    },
    "kharma_uses": {
        "title": "Kharma Uses",
        "entries": [
            ("Minor miracle",            "Serpent Choir contract",      "5–20 Kharma"),
            ("Major divine boon",        "God-tier contract",           "50–500 Kharma"),
            ("Adventurer tithe",         "FTA-mandated levy",           "Varies by LP tier"),
            ("Kharma trade (EC)",        f"Current market rate",        f"See exchange rate above"),
            ("Divine Attention trigger", "Threshold (LP-scaled)",       "Automatic above threshold"),
        ],
    },
}


def format_price_table(table_key: str) -> str:
    """Format one price table as a Discord embed block."""
    table = PRICE_TABLES.get(table_key)
    if not table:
        return f"Unknown price table: `{table_key}`"

    lines = [f"**{table['title']}**", ""]
    for name, desc, price in table["entries"]:
        lines.append(f"┣ **{name}** — _{desc}_")
        lines.append(f"┗ `{price}`")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_all_prices() -> str:
    """Full price reference for /finances prices."""
    rate = get_rate()
    sections = []
    for key in PRICE_TABLES:
        sections.append(format_price_table(key))
    header = (
        "📋 **UNDERCITY PRICE REFERENCE**\n"
        f"-# {_dual_ts()}\n"
        f"-# Exchange rate: **{rate:.2f} EC = 1 Kharma** (live)\n"
    )
    return header + "\n\n---\n\n".join(sections)
