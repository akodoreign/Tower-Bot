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
        "bias":        ["Pressure Fog", "Cinder Smog", "Rift Static", "Cold Sink", "Rift Weather",
                        "Sewer Backflow", "Fungal Bloom", "Pipe Burst", "Steam Veil", "Dead Air"],
    },
    "Markets Infinite": {
        "emoji":       "🏮",
        "description": "Dense crowd heat, vendor exhaust, poor ventilation.",
        "bias":        ["Thermal Surge", "Cinder Smog", "Stagnant Grey", "Acid Drizzle",
                        "Furnace Draft", "Heat Shimmer", "Sulphur Haze", "Pollen Drift"],
    },
    "Sanctum Quarter": {
        "emoji":       "🕍",
        "description": "Divine architecture moderates pressure. Unusually stable.",
        "bias":        ["Dim Clearance", "Pressure Calm", "False Dawn", "Stagnant Grey",
                        "Ghost Light", "Veil Thin", "Pollen Drift", "Clean Flush"],
    },
    "Grand Forum": {
        "emoji":       "🏛️",
        "description": "Central plaza. Open ceilings. Echo effects from Dome curvature.",
        "bias":        ["Echo Storms", "Dim Clearance", "Stagnant Grey", "False Dawn",
                        "Resonance Hum", "Dome Flicker", "Pressure Drop", "Whistling Vents"],
    },
    "Guild Spires": {
        "emoji":       "⚔️",
        "description": "Elevated. Dome vents nearby. Upper-level wind currents.",
        "bias":        ["Acid Drizzle", "Pressure Calm", "Thermal Surge", "Dim Clearance",
                        "UV Bleed", "Condensation Rain", "Pressure Spike", "Dust Storm"],
    },
    "Outer Wall": {
        "emoji":       "🧱",
        "description": "Dome seal closest here. Cold bleeds through. Structural stress.",
        "bias":        ["Cold Sink", "Pressure Fog", "Rift Static", "Acid Drizzle",
                        "Deep Freeze", "Black Ice", "Thermal Inversion", "Rust Rain", "Gravity Flux"],
    },
}

# ---------------------------------------------------------------------------
# Condition pool — (label, pressure_delta, base_description, emoji)
# Each district overrides the description with a district-specific flavour line.
# ---------------------------------------------------------------------------

_CONDITIONS: List[Tuple] = [
    # --- Original 12 ---
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
    # --- Moisture & precipitation ---
    ("Condensation Rain",    -1,  "Water condensing on the upper Dome surface is falling in sheets. Not acid — just cold.", "🌧️"),
    ("Fungal Bloom",          0,  "Warm damp air has triggered bioluminescent fungal spore release. Beautiful and mildly toxic.", "🍄"),
    ("Steam Veil",            0,  "Steam from the lower pipe network has risen through grates. Warm, wet, low visibility.", "♨️"),
    ("Black Ice",            -2,  "Condensation has frozen on metal surfaces. Walkways, ladders, and railings are treacherous.", "🧊"),
    ("Rust Rain",            -1,  "Oxidised particulate is falling with the condensation. Everything it touches stains brown.", "🟤"),
    # --- Temperature extremes ---
    ("Furnace Draft",        +1,  "A hot updraft from the industrial levels. Dry and choking. Feels like opening an oven.", "🌡️"),
    ("Deep Freeze",          -2,  "Dome thermal regulators offline in this sector. Breath is visible. Pipes are at risk.", "🥶"),
    ("Heat Shimmer",          0,  "The air itself is distorting. Mirage effects on long corridors. Depth perception is unreliable.", "🔆"),
    ("Thermal Inversion",    -1,  "Cold air trapped under warm. Ground-level is freezing while upper platforms are sweltering.", "↕️"),
    # --- Air quality ---
    ("Sulphur Haze",         -2,  "Yellow-tinged air with an unmistakable rotten-egg smell. Source unknown. FTA investigating.", "⚗️"),
    ("Dust Storm",           -2,  "Construction debris and dried sediment caught in a pressure differential. Abrasive and blinding.", "🌪️"),
    ("Pollen Drift",          0,  "The Divine Garden's seasonal release. Drifting golden particulate. Allergies citywide.", "🌼"),
    ("Clean Flush",          +2,  "The Dome's air recyclers ran a full purge cycle. The air is crisp and tastes of nothing. Unsettling.", "🫧"),
    ("Ozone Spike",          -1,  "Sharp metallic tang in the air. Arcane instruments misbehaving. Headaches reported.", "⚡"),
    # --- Light & visual ---
    ("Dome Flicker",         -1,  "The overhead lighting is stuttering. Strobe effect in open spaces. Seizure warnings posted.", "💡"),
    ("Blood Light",          -1,  "The Dome's light panels are stuck on deep red. Everything looks like a darkroom. Eerie.", "🔴"),
    ("Phosphor Glow",         0,  "A faint green-white glow from the Dome panels. Shadows are wrong. Faces look ill.", "🟢"),
    ("UV Bleed",             -1,  "Unfiltered UV light leaking through worn Dome panels. Exposed skin burns within minutes.", "☀️"),
    ("Total Dark",           -2,  "Section lighting has failed completely. Emergency strips only. Blue-white and barely enough.", "🌑"),
    # --- Pressure & sound ---
    ("Pressure Drop",        -2,  "Ears popping. Nosebleeds in the upper districts. Something vented that shouldn't have.", "📉"),
    ("Pressure Spike",       +1,  "Air feels heavy and thick. Doors are harder to open. Sealed containers are bulging.", "📈"),
    ("Dead Air",             -1,  "No air movement at all. Sound carries flat and close. The silence is suffocating.", "🤫"),
    ("Resonance Hum",        -1,  "A low-frequency hum reverberating through the infrastructure. Source: Dome structural flex.", "🎵"),
    ("Whistling Vents",       0,  "Pressure equalisation through narrow vents is producing an eerie whistle across the district.", "🎐"),
    # --- Arcane & supernatural ---
    ("Mana Fog",             -2,  "Dense, shimmering haze saturated with ambient magic. Spells behave unpredictably.", "🔮"),
    ("Ghost Light",           0,  "Pale orbs of light drifting at head height. Not dangerous. Not explained.", "👻"),
    ("Gravity Flux",         -3,  "Localised gravity anomalies. Objects falling at wrong angles. Stay off ladders.", "🪐"),
    ("Time Slip",            -3,  "Clocks are disagreeing. Some residents report lost minutes. Glass Sigil is concerned.", "⏳"),
    ("Veil Thin",            -2,  "The boundary between planes feels permeable. Faint sounds from elsewhere. Shadows move wrong.", "👁️"),
    # --- Infrastructure ---
    ("Pipe Burst",           -1,  "A major water main has ruptured. Streets are flooding at ground level. Wardens redirecting traffic.", "🚿"),
    ("Power Surge",          -1,  "Electrical grid fluctuations. Lights flaring. Appliances sparking. Stay away from junction boxes.", "🔌"),
    ("Sewer Backflow",       -2,  "Lower drainage systems are backing up. The smell is indescribable. Stay off ground level.", "🚽"),
    ("Construction Haze",     0,  "Ongoing structural work has filled the air with concrete dust and welding fumes. Masks advised.", "🏗️"),
]

_CONDITION_MAP = {c[0]: c for c in _CONDITIONS}

# District-specific flavour overrides — what each condition *feels like* in that district
_DISTRICT_FLAVOUR: Dict[str, Dict[str, str]] = {
    "The Warrens": {
        "Pressure Fog":     "Fog sits knee-deep in the alleys. Night Pits are quieter than usual.",
        "Cinder Smog":      "Scrapworks smoke has nowhere to go. Echo Alley is invisible past ten feet.",
        "Rift Static":      "The Collapsed Plaza is sparking. Brother Thane's people are keeping indoors.",
        "Cold Sink":        "The cold has come down through the Shantytown. Residents are burning scrap for heat.",
        "Rift Weather":     "Something is falling in the Warrens that is not water. Patchwork Saints have put out warnings.",
        "Stagnant Grey":    "The Warrens smell worse than usual. No wind to carry it away.",
        "Thermal Surge":    "The heat in the lower tunnels is unbearable. Mara's workers have stopped for the day.",
        "Sewer Backflow":   "Lower Warrens drainage has reversed. Echo Alley is ankle-deep. The Saints are handing out boots.",
        "Fungal Bloom":     "Bioluminescent spores drifting through Shantytown Heights. Beautiful until you start coughing.",
        "Pipe Burst":       "A main has burst near the Scrapworks. Mara's crew is waist-deep, swearing. Traffic rerouted.",
        "Steam Veil":       "Steam rising through every grate in the Warrens. Warm and wet. Visibility nil in the lower tunnels.",
        "Dead Air":         "Nothing is moving in the Warrens. Not a draft, not a breeze. The silence presses in.",
        "Mana Fog":         "A shimmering haze has settled over the Collapsed Plaza. Spells are misfiring. Brother Thane's people seem excited.",
        "Ghost Light":      "Pale orbs drifting through Echo Alley. The Saints say they've seen them before. Nobody else has.",
    },
    "Markets Infinite": {
        "Thermal Surge":    "Neon Row is stifling. Vendor stalls on Cobbleway are half-shuttered. Business is slow.",
        "Cinder Smog":      "The Floating Bazaar is barely visible. Traders are selling by smell and memory.",
        "Acid Drizzle":     "Crimson Alley awnings are up. The drizzle is light but it ruins dye.",
        "Stagnant Grey":    "The crowd heat and still air have produced an interesting smell in Taste of Worlds.",
        "Pressure Calm":    "Unusually pleasant morning in the Markets. Crowds are larger. Pickpockets are busier.",
        "Furnace Draft":    "A hot updraft from below has turned Neon Row into an oven. Vendors are selling water at triple price.",
        "Heat Shimmer":     "Mirage effects on Cobbleway. Customers can't tell real stalls from reflections. Serrik Dhal is not amused.",
        "Sulphur Haze":     "Yellow haze hanging over the Floating Bazaar. The fish stalls blame the alchemists. The alchemists blame the fish.",
        "Pollen Drift":     "Golden particulate from the Divine Garden has reached Taste of Worlds. Sneezing at every table.",
        "Dust Storm":       "Construction grit caught in a pressure differential. Crimson Alley vendors have shuttered completely.",
        "Power Surge":      "Neon Row is strobing. Every sign on the strip is flickering at different frequencies. Headaches everywhere.",
    },
    "Sanctum Quarter": {
        "Dim Clearance":    "The Pantheon Walk is bathed in soft Dome-light. Quiet. Almost peaceful.",
        "False Dawn":       "The orange glow catches the Hall of Echoes glass perfectly. Pilgrims have gathered.",
        "Pressure Calm":    "The Divine Garden is serene today. Even the Serpent Choir novices seem relaxed.",
        "Echo Storms":      "Prayers in the Hall of Echoes are carrying into the street. Everyone can hear them.",
        "Stagnant Grey":    "The Sanctum Quarter feels muted. The incense doesn't help.",
        "Ghost Light":      "Pale orbs drifting through the Divine Garden. The Choir says they're benign. Nobody asked them.",
        "Veil Thin":        "The boundary feels thin near the Hall of Echoes. Novices report hearing voices not their own.",
        "Pollen Drift":     "The Divine Garden is in bloom. Golden pollen coating every surface in the Sanctum Quarter.",
        "Clean Flush":      "The air recyclers purged the Sanctum Quarter. Crisp, clean air. Smells like nothing. The Choir finds it suspicious.",
        "Blood Light":      "The Dome's red lighting has turned the Pantheon Walk into something from a nightmare. Pilgrims are staying away.",
    },
    "Grand Forum": {
        "Echo Storms":      "The Central Plaza is carrying every conversation to every other corner. Brokers are whispering.",
        "False Dawn":       "The Fountain of Echoes is lit orange. The morning crowd stopped to look.",
        "Dim Clearance":    "Grand Forum is bright today. The Rift Bulletin Board is well-attended.",
        "Stagnant Grey":    "Flat light in the Forum. The Adventurer's Inn has not opened its shutters.",
        "Pressure Calm":    "A quiet morning at the Forum. Mira Kessan's usual corner table is occupied early.",
        "Resonance Hum":    "A deep vibration rattling the Forum's stone columns. Mira and Kessan have moved outdoors. Nobody can think.",
        "Dome Flicker":     "The Forum's ceiling lights are strobing. The Rift Bulletin Board is unreadable. Mari Fen is filing a complaint.",
        "Pressure Drop":    "Ears popping across the Central Plaza. The Adventurer's Inn has sealed its doors.",
        "Whistling Vents":  "An eerie whistle piercing through the Forum corridors. Source: pressure vents near the Fountain of Echoes.",
        "Time Slip":        "Clocks in the Grand Forum are disagreeing by minutes. Kessan and Mira noticed first. Glass Sigil dispatched.",
    },
    "Guild Spires": {
        "Acid Drizzle":     "The Arena's upper terraces are wet. Morning training has moved inside.",
        "Pressure Calm":    "Clear conditions at the Spires. Argent Blades are running outdoor drills.",
        "Thermal Surge":    "The Spires are hot today. Arena bouts scheduled for evening instead.",
        "Dim Clearance":    "Good visibility from the upper Guild Spires. Someone's doing something on the roof.",
        "UV Bleed":         "Unfiltered UV pouring through worn Dome panels above the Spires. The Arena is under shade cloth.",
        "Condensation Rain":"Cold rain sheeting off the Dome onto the Spires' upper levels. Training is miserable.",
        "Pressure Spike":   "The air at Spire elevation is dense and heavy. Arena fighters say it's like breathing soup.",
        "Dust Storm":       "Grit from the construction zone has reached the Arena. Lady Cerys has cancelled afternoon bouts.",
        "Construction Haze":"Spire renovation work filling the air with concrete dust. Masks mandatory above level three.",
    },
    "Outer Wall": {
        "Cold Sink":        "Gate District is freezing. Wall Quadrant C reports frost on the inner seal. FTA is aware.",
        "Rift Static":      "Wall Quadrant A instruments are reading. Wardens have increased patrols.",
        "Pressure Fog":     "The Outer Wall is invisible past twenty feet. Gate District has slowed to a crawl.",
        "Acid Drizzle":     "The Wall is weeping. Acid mist is pooling at the base of Gate District. Stay back.",
        "Stagnant Grey":    "Still day on the Wall. Wardens on long watch. Nothing moving outside the gate.",
        "Deep Freeze":      "Thermal regulators have failed in Wall Quadrant C. Ice forming on the inner seal. Captain Korin has doubled patrols.",
        "Black Ice":        "Every metal surface on the Outer Wall is glazed. Two Wardens slipped on the morning watch.",
        "Thermal Inversion":"Ground level at the Wall is freezing. Upper gantries are sweltering. Nobody can dress for both.",
        "Rust Rain":        "Brown-stained condensation dripping from the Dome seal. The Wall's infrastructure is corroding faster.",
        "Gravity Flux":     "Localised gravity anomalies near Wall Quadrant A. Tools drifting. Wardens have evacuated the section.",
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
