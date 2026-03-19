"""
ec_exchange.py — EC/Kharma exchange rate tracker for Tower of Last Chance.

CANON:
  Essence Coins (EC) are common currency, formed from Kharma for everyday trade.
  Kharma is the premium faith-crystallised currency — rarer and more powerful.
  Base rate: 10 EC = 1 Kharma.

INFLATION:
  Slow natural drift of ~1–2% per real month.
  Per bulletin tick (~1 hour): ~0.002% drift (adds up to ~1.5%/month).
  Major news events can shock the rate by up to ±10%.

PERSISTENCE:
  Stored in campaign_docs/ec_exchange.json.
  Rate history kept for last 30 entries.
"""

from __future__ import annotations

import json
import random
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DOCS_DIR       = Path(__file__).resolve().parent.parent / "campaign_docs"
EC_FILE        = DOCS_DIR / "ec_exchange.json"

# Base rate: how many EC per 1 Kharma
EC_BASE_RATE   = 10.0

# Inflation per bulletin tick (~hourly). Targets ~1.5%/month.
# 1.5% / (30 days * 24 ticks) = ~0.002% per tick
EC_TICK_DRIFT  = 0.00002   # fractional drift per tick (tiny, compounding)

# Max random noise per tick (so rate isn't perfectly smooth)
EC_TICK_NOISE  = 0.0001    # ± this per tick

# Hard floor/ceiling on the rate (prevents runaway)
EC_RATE_FLOOR  = 5.0       # EC per Kharma min
EC_RATE_CEIL   = 50.0      # EC per Kharma max

# History entries to keep
EC_HISTORY_MAX = 30

TOWER_YEAR_OFFSET = 10


def _dual_ts() -> str:
    now = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    return f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"


def _load() -> dict:
    if not EC_FILE.exists():
        return {}
    try:
        return json.loads(EC_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        EC_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
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
    """
    Apply one bulletin-tick of inflation drift.
    Call this each bulletin cycle (alongside TIA tick, etc.).
    Returns the new rate.
    """
    data = _load()
    if not data:
        data = _init()

    old_rate = float(data.get("rate", EC_BASE_RATE))

    # Inflation drift: very slight upward nudge each tick
    noise    = random.uniform(-EC_TICK_NOISE, EC_TICK_NOISE)
    new_rate = old_rate * (1 + EC_TICK_DRIFT + noise)
    new_rate = round(max(EC_RATE_FLOOR, min(EC_RATE_CEIL, new_rate)), 4)

    _record(data, old_rate, new_rate, "tick")
    _save(data)
    return new_rate


def apply_event_shock(delta_pct: float, reason: str = "") -> tuple[float, float]:
    """
    Apply an event-driven shock to the exchange rate.
    delta_pct: fractional change, e.g. +0.05 = +5%, -0.10 = -10%.
    Returns (old_rate, new_rate).
    """
    data = _load()
    if not data:
        data = _init()

    old_rate = float(data.get("rate", EC_BASE_RATE))
    # Clamp shock to ±10%
    delta_pct = max(-0.10, min(0.10, delta_pct))
    new_rate  = round(max(EC_RATE_FLOOR, min(EC_RATE_CEIL, old_rate * (1 + delta_pct))), 4)

    data["last_event"] = reason or f"Market shock {delta_pct:+.1%}"
    _record(data, old_rate, new_rate, data["last_event"])
    _save(data)

    logger.info(f"💱 EC exchange shock: {old_rate:.4f} → {new_rate:.4f} EC/Kharma ({delta_pct:+.1%}) — {reason}")
    return old_rate, new_rate


def _record(data: dict, old: float, new: float, event: str) -> None:
    history = data.get("history", [])
    history.append({
        "ts":    datetime.now().isoformat(),
        "old":   old,
        "new":   new,
        "event": event,
    })
    data["history"]      = history[-EC_HISTORY_MAX:]
    data["rate"]         = new
    data["last_updated"] = datetime.now().isoformat()


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


# Example goods whose EC prices scale with inflation for the daily bulletin
# Format: (name, base_ec_price, description)
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
    history = data.get("history", [])
    last_ev = data.get("last_event", "normal market drift")

    # Calculate recent change if we have history
    change_str = ""
    if len(history) >= 2:
        day_ago_entries = [h for h in history if h.get("old")]
        if day_ago_entries:
            oldest = day_ago_entries[0]["old"]
            pct    = ((rate - oldest) / oldest) * 100 if oldest else 0
            sign   = "+" if pct >= 0 else ""
            arrow  = "🟢 ▲" if pct > 0.05 else ("🔴 ▼" if pct < -0.05 else "⬜ ─")
            change_str = f" {arrow} _{sign}{pct:.2f}%_"

    # Pick 3 varied example goods to show live-inflated prices
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
        # Apply inflation ratio relative to base rate of 10.0
        inflated = round(base * (rate / EC_BASE_RATE), 2)
        lines.append(f"└ **{name}** — _{desc}_ · `{inflated:.2f} EC`")

    lines += [
        "",
        f"-# Rate note: {last_ev}",
        "-# Exchange kiosks at Cobbleway Market, Grand Forum, and Guild Spires. Rates subject to change without notice.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Price reference tables (static — from campaign docs)
# ---------------------------------------------------------------------------

# These are the canonical Undercity EC prices from the sourcebook.
# Used by /finances prices command.

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
    # Insert live rate into kharma_uses section naturally
    header = (
        "📋 **UNDERCITY PRICE REFERENCE**\n"
        f"-# {_dual_ts()}\n"
        f"-# Exchange rate: **{rate:.2f} EC = 1 Kharma** (live)\n"
    )
    return header + "\n\n---\n\n".join(sections)
