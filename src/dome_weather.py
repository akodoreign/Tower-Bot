"""
dome_weather.py — Undercity Dome Weather & Environmental System

The city is sealed under a Dome. There is no real sky.
Each district generates its own conditions based on its location,
infrastructure, and proximity to the Dome wall or Rift activity.

Updated daily, posted as a per-district bulletin.
Persists to campaign_docs/dome_weather.json.
"""

from __future__ import annotations
import json, os, random, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List, Tuple

logger   = logging.getLogger(__name__)
DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
WEATHER_FILE      = DOCS_DIR / "dome_weather.json"
TOWER_YEAR_OFFSET = 10


def _dual_ts() -> str:
    now   = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    return f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"


# ---------------------------------------------------------------------------
# Districts — each has a character that biases its weather pool
# ---------------------------------------------------------------------------

DISTRICTS = {
    "The Warrens": {
        "emoji":       "🕯️",
        "description": "Low-lying. Bad drainage. Rift-adjacent.",
        "bias":        ["Pressure Fog", "Cinder Smog", "Rift Static", "Cold Sink", "Rift Weather"],
    },
    "Markets Infinite": {
        "emoji":       "🏮",
        "description": "Dense crowd heat, vendor exhaust, poor ventilation.",
        "bias":        ["Thermal Surge", "Cinder Smog", "Stagnant Grey", "Acid Drizzle"],
    },
    "Sanctum Quarter": {
        "emoji":       "🕍",
        "description": "Divine architecture moderates pressure. Unusually stable.",
        "bias":        ["Dim Clearance", "Pressure Calm", "False Dawn", "Stagnant Grey"],
    },
    "Grand Forum": {
        "emoji":       "🏛️",
        "description": "Central plaza. Open ceilings. Echo effects from Dome curvature.",
        "bias":        ["Echo Storms", "Dim Clearance", "Stagnant Grey", "False Dawn"],
    },
    "Guild Spires": {
        "emoji":       "⚔️",
        "description": "Elevated. Dome vents nearby. Upper-level wind currents.",
        "bias":        ["Acid Drizzle", "Pressure Calm", "Thermal Surge", "Dim Clearance"],
    },
    "Outer Wall": {
        "emoji":       "🧱",
        "description": "Dome seal closest here. Cold bleeds through. Structural stress.",
        "bias":        ["Cold Sink", "Pressure Fog", "Rift Static", "Acid Drizzle"],
    },
}

# ---------------------------------------------------------------------------
# Condition pool — (label, pressure_delta, base_description, emoji)
# Each district overrides the description with a district-specific flavour line.
# ---------------------------------------------------------------------------

_CONDITIONS: List[Tuple] = [
    ("Stagnant Grey",   0,  "The false sky is flat and colourless. The air sits heavy.", "🌫️"),
    ("Dim Clearance",   0,  "The Dome glows faintly — something approximating clear. Rare enough to notice.", "🌤️"),
    ("Pressure Fog",   -1,  "Dense fog has settled. Visibility is poor.", "🌁"),
    ("Rift Static",    -2,  "Arcane static crackles. Hair stands on end. Small objects drift.", "⚡"),
    ("Acid Drizzle",   -1,  "Fine acidic mist seeps from the Dome's upper vents.", "🌧️"),
    ("Thermal Surge",  +1,  "Heat exchangers are struggling. Temperature is rising.", "🔥"),
    ("Cinder Smog",    -2,  "Furnace output has overwhelmed the filters. Visibility poor. Breathing unpleasant.", "💨"),
    ("Pressure Calm",  +2,  "A rare stabilisation. The air is clean and still. Nobody trusts it.", "✨"),
    ("Rift Weather",   -3,  "Reality distortions causing precipitation of unknown substance. Smells of copper.", "🌀"),
    ("False Dawn",     +1,  "The Dome's lighting cycle has glitched. A pale orange glow.", "🌅"),
    ("Echo Storms",    -1,  "Sound propagates strangely. Conversations carry further than intended.", "🔊"),
    ("Cold Sink",      -1,  "Cold air has escaped. The temperature has dropped sharply.", "❄️"),
]

_CONDITION_MAP = {c[0]: c for c in _CONDITIONS}

# District-specific flavour overrides — what each condition *feels like* in that district
_DISTRICT_FLAVOUR: Dict[str, Dict[str, str]] = {
    "The Warrens": {
        "Pressure Fog":   "Fog sits knee-deep in the alleys. Night Pits are quieter than usual.",
        "Cinder Smog":    "Scrapworks smoke has nowhere to go. Echo Alley is invisible past ten feet.",
        "Rift Static":    "The Collapsed Plaza is sparking. Brother Thane's people are keeping indoors.",
        "Cold Sink":      "The cold has come down through the Shantytown. Residents are burning scrap for heat.",
        "Rift Weather":   "Something is falling in the Warrens that is not water. Patchwork Saints have put out warnings.",
        "Stagnant Grey":  "The Warrens smell worse than usual. No wind to carry it away.",
        "Thermal Surge":  "The heat in the lower tunnels is unbearable. Mara's workers have stopped for the day.",
    },
    "Markets Infinite": {
        "Thermal Surge":  "Neon Row is stifling. Vendor stalls on Cobbleway are half-shuttered. Business is slow.",
        "Cinder Smog":    "The Floating Bazaar is barely visible. Traders are selling by smell and memory.",
        "Acid Drizzle":   "Crimson Alley awnings are up. The drizzle is light but it ruins dye.",
        "Stagnant Grey":  "The crowd heat and still air have produced an interesting smell in Taste of Worlds.",
        "Pressure Calm":  "Unusually pleasant morning in the Markets. Crowds are larger. Pickpockets are busier.",
    },
    "Sanctum Quarter": {
        "Dim Clearance":  "The Pantheon Walk is bathed in soft Dome-light. Quiet. Almost peaceful.",
        "False Dawn":     "The orange glow catches the Hall of Echoes glass perfectly. Pilgrims have gathered.",
        "Pressure Calm":  "The Divine Garden is serene today. Even the Serpent Choir novices seem relaxed.",
        "Echo Storms":    "Prayers in the Hall of Echoes are carrying into the street. Everyone can hear them.",
        "Stagnant Grey":  "The Sanctum Quarter feels muted. The incense doesn't help.",
    },
    "Grand Forum": {
        "Echo Storms":    "The Central Plaza is carrying every conversation to every other corner. Brokers are whispering.",
        "False Dawn":     "The Fountain of Echoes is lit orange. The morning crowd stopped to look.",
        "Dim Clearance":  "Grand Forum is bright today. The Rift Bulletin Board is well-attended.",
        "Stagnant Grey":  "Flat light in the Forum. The Adventurer's Inn has not opened its shutters.",
        "Pressure Calm":  "A quiet morning at the Forum. Mira Kessan's usual corner table is occupied early.",
    },
    "Guild Spires": {
        "Acid Drizzle":   "The Arena's upper terraces are wet. Morning training has moved inside.",
        "Pressure Calm":  "Clear conditions at the Spires. Argent Blades are running outdoor drills.",
        "Thermal Surge":  "The Spires are hot today. Arena bouts scheduled for evening instead.",
        "Dim Clearance":  "Good visibility from the upper Guild Spires. Someone's doing something on the roof.",
    },
    "Outer Wall": {
        "Cold Sink":      "Gate District is freezing. Wall Quadrant C reports frost on the inner seal. FTA is aware.",
        "Rift Static":    "Wall Quadrant A instruments are reading. Wardens have increased patrols.",
        "Pressure Fog":   "The Outer Wall is invisible past twenty feet. Gate District has slowed to a crawl.",
        "Acid Drizzle":   "The Wall is weeping. Acid mist is pooling at the base of Gate District. Stay back.",
        "Stagnant Grey":  "Still day on the Wall. Wardens on long watch. Nothing moving outside the gate.",
    },
}

# ---------------------------------------------------------------------------
# Special events — rare, city-wide, override normal conditions
# ---------------------------------------------------------------------------

_SPECIAL_EVENTS = [
    ("ARCANE OVERLOAD",        -4, "Dome arcane regulators at 94% capacity. FTA has suspended all non-essential magical operations until further notice.", "⚠️"),
    ("PRESSURE INVERSION",     -3, "A full pressure inversion is underway. Weather is running backwards across all districts. This is not normal.", "🔄"),
    ("CLARITY EVENT",          +5, "The Dome is displaying a perfect open sky simulation. Crowds gathering in Grand Forum. First time in years.", "🌟"),
    ("RIFT PRECIPITATION",     -4, "Solid Rift residue falling like snow in the Warrens. Do not touch. Do not taste. Evacuate affected blocks.", "☣️"),
    ("THERMAL COLLAPSE",       -3, "The Dome's heat exchange network has partially failed. Temperature dropping fast in outer districts, rising in the centre.", "🌡️"),
    # Static storm is district-localized — see _roll_static_storm()
    # Entry kept as a sentinel so the 8% event roll can trigger it
    ("STATIC STORM",           -2, "LOCALIZED", "⚡"),
    ("FALSE NIGHT",            -1, "The Dome's lighting cycle has locked into night mode. FTA is working on it. Estimated resolution: unknown.", "🌑"),
    ("VENTILATION FAILURE",    -2, "Upper vent network is offline. Air is stale and warming across all districts. Warrens residents advised to stay low.", "💨"),
]


# ---------------------------------------------------------------------------
# Localized static storm
# ---------------------------------------------------------------------------

_STATIC_STORM_FLAVOUR = {
    "The Warrens":      "Arcane static is discharging through the Scrapworks metal. Sparks at every junction. Glass Sigil has lost three instruments.",
    "Markets Infinite": "Static is jumping between stalls on Neon Row. Iron Fang kiosks are offline. Traders are doing it by hand.",
    "Sanctum Quarter":  "The Hall of Echoes is resonating with static discharge. Divine instruments are unreliable. Serpent Choir has closed the Pantheon Walk.",
    "Grand Forum":      "Static is arcing off the Fountain of Echoes. The Rift Bulletin Board is sparking. Mira Kessan has moved her operation indoors.",
    "Guild Spires":     "The Arena's upper metalwork is conducting. Morning training cancelled. Argent Blades are not happy about it.",
    "Outer Wall":       "Wall Quadrant A and C instrumentation is down. Wardens are running manual patrols. Captain Korin has not commented.",
}


def _roll_static_storm() -> Dict:
    """
    Pick 1-2 adjacent or random districts to hit with a static storm.
    Returns a special_event dict with localized desc and affected districts.
    """
    district_names = list(DISTRICTS.keys())
    count    = random.randint(1, 2)
    affected = random.sample(district_names, count)
    descs    = [_STATIC_STORM_FLAVOUR.get(d, "Arcane static is causing problems.") for d in affected]
    affected_str = " and ".join(affected)
    combined_desc = f"Localized arcane static storm affecting **{affected_str}**. " + " ".join(descs)
    return {
        "label":            "STATIC STORM",
        "pressure_delta":   -2,
        "desc":             combined_desc,
        "emoji":            "⚡",
        "affected_districts": affected,
    }


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _load_weather() -> Dict:
    if not WEATHER_FILE.exists():
        return {}
    try:
        return json.loads(WEATHER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_weather(state: Dict) -> None:
    try:
        WEATHER_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"Weather save error: {e}")


def _roll_condition_for_district(district: str) -> Tuple[str, str, str]:
    """
    Roll a weather condition for a district.
    Biased conditions are twice as likely to appear.
    Returns (label, description, emoji).
    """
    bias = DISTRICTS[district].get("bias", [])
    pool = list(_CONDITIONS)  # base pool
    # Add biased conditions a second time so they appear ~2x as often
    for c in pool[:]:
        if c[0] in bias:
            pool.append(c)

    chosen = random.choice(pool)
    label, _, base_desc, emoji = chosen

    # Use district-specific flavour if available, otherwise base description
    flavour = _DISTRICT_FLAVOUR.get(district, {}).get(label, base_desc)
    return label, flavour, emoji


def _init_weather() -> Dict:
    districts = {}
    for name in DISTRICTS:
        label, desc, emoji = _roll_condition_for_district(name)
        districts[name] = {"condition": label, "description": desc, "emoji": emoji}
    return {
        "districts":      districts,
        "pressure":       50,
        "special_event":  None,
        "forecast":       [random.choice(_CONDITIONS)[0] for _ in range(3)],
        "updated_at":     datetime.now().isoformat(),
        "last_posted_at": None,
    }


def tick_weather() -> tuple:
    """Advance weather state. Returns (state, special_event_or_None)."""
    state = _load_weather()
    if not state or "districts" not in state:
        state = _init_weather()

    special = None

    if random.random() < 0.04:
        ev = random.choice(_SPECIAL_EVENTS)

        if ev[0] == "STATIC STORM":
            # Localized — only affects 1-2 districts
            storm = _roll_static_storm()
            state["special_event"] = storm
            state["pressure"] = max(0, min(100, state["pressure"] + storm["pressure_delta"]))
            special = (storm["label"], storm["pressure_delta"], storm["desc"], storm["emoji"])
            # Apply Rift Static condition only to affected districts
            for name in DISTRICTS:
                if name in storm["affected_districts"]:
                    state["districts"][name] = {
                        "condition":   "Rift Static",
                        "description": _STATIC_STORM_FLAVOUR.get(name, "Arcane static is causing problems."),
                        "emoji":       "⚡",
                        "storm":       True,
                    }
                # Other districts keep their normal rolled condition (rolled below)
        else:
            state["special_event"] = {"label": ev[0], "pressure_delta": ev[1], "desc": ev[2], "emoji": ev[3]}
            state["pressure"] = max(0, min(100, state["pressure"] + ev[1]))
            special = ev
            # City-wide events blanket all districts
            for name in DISTRICTS:
                state["districts"][name] = {
                    "condition":   ev[0],
                    "description": ev[2],
                    "emoji":       ev[3],
                }
    else:
        state["special_event"] = None
        # Roll each district independently
        for name in DISTRICTS:
            label, desc, emoji = _roll_condition_for_district(name)
            state["districts"][name] = {"condition": label, "description": desc, "emoji": emoji}

        # Pressure drifts based on a random base condition
        sample_cond = random.choice(_CONDITIONS)
        state["pressure"] = max(0, min(100,
            state["pressure"] + sample_cond[1] + random.randint(-3, 3)
        ))

    # Drift pressure back toward 50
    if state["pressure"] > 50:
        state["pressure"] -= random.randint(0, 3)
    elif state["pressure"] < 50:
        state["pressure"] += random.randint(0, 3)

    state["forecast"]   = [random.choice(_CONDITIONS)[0] for _ in range(3)]
    state["updated_at"] = datetime.now().isoformat()
    _save_weather(state)
    return state, special


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_weather_bulletin() -> str:
    state = _load_weather()
    if not state or "districts" not in state:
        state, _ = tick_weather()

    pressure = state.get("pressure", 50)
    if pressure >= 70:
        p_label, p_emoji = "HIGH", "🟢"
    elif pressure >= 40:
        p_label, p_emoji = "STABLE", "🟡"
    else:
        p_label, p_emoji = "LOW", "🔴"

    forecast     = state.get("forecast", [])
    forecast_str = " → ".join(forecast) if forecast else "Unknown"
    special      = state.get("special_event")

    lines = [
        "🌐 **DOME ENVIRONMENTAL REPORT — BY DISTRICT** 🌐",
        f"-# {_dual_ts()}",
        "",
        "*Here is the weather in your part of the Undercity:*",
        "",
    ]

    for district, info in DISTRICTS.items():
        d_data    = state.get("districts", {}).get(district, {})
        condition = d_data.get("condition", "Unknown")
        desc      = d_data.get("description", "No data.")
        d_emoji   = d_data.get("emoji", info["emoji"])
        d_icon    = info["emoji"]

        lines.append(f"{d_icon} **{district}** — {d_emoji} {condition}")
        lines.append(f"   *{desc}*")

    lines += [
        "",
        f"**Dome Pressure Index:** {p_emoji} {p_label} ({pressure}/100)",
        f"**3-Day Forecast (city-wide trend):** {forecast_str}",
    ]

    if special:
        s_label = special.get("label") if isinstance(special, dict) else special[0]
        s_desc  = special.get("desc")  if isinstance(special, dict) else special[2]
        affected = special.get("affected_districts") if isinstance(special, dict) else None
        scope   = f"LOCALIZED — {', '.join(affected)}" if affected else "CITY-WIDE ALERT"
        lines += [
            "",
            f"⚡ **{scope} — {s_label}**",
            f"*{s_desc}*",
        ]

    lines += [
        "",
        "-# Dome Environmental Report issued by FTA Atmospheric Division.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cadence guards
# ---------------------------------------------------------------------------

def should_post_weather() -> bool:
    state = _load_weather()
    if not state:
        return True
    last = state.get("last_posted_at")
    if not last:
        return True
    try:
        elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
        return elapsed >= 23 * 3600
    except Exception:
        return True


def mark_weather_posted() -> None:
    state = _load_weather()
    if not state:
        state = _init_weather()
    state["last_posted_at"] = datetime.now().isoformat()
    _save_weather(state)
