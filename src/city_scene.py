"""
city_scene.py — City scene image generator for the Undercity.

Modeled after the NPC portrait loop (generate_npc_portrait in news_feed.py).
Instead of character portraits, generates wide environmental scenes:
  - Specific named districts and locations from the gazetteer DB
  - Real weather from the dome_weather DB state
  - Time of day (dawn / day / dusk / night / deep night)
  - The Tower always looms in the far background — sci-fi spire to the heavens
  - Rotates between multiple A1111 models for visual variety
  - Full prompt and scene metadata logged in src.log

Returns: (image_bytes, prompt_str, caption_str) — same signature as generate_story_image.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import random
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model roster — rotated per scene for visual variety
# ---------------------------------------------------------------------------

_image_style = os.getenv("IMAGE_STYLE", "photorealistic").lower()
_SCENE_MODELS = [
    os.getenv("A1111_MODEL",         ""),   # primary photorealistic model
    os.getenv("A1111_SCENE_MODEL_2", ""),   # optional second model
    os.getenv("A1111_SCENE_MODEL_3", ""),   # optional third model
]
if _image_style == "anime":
    _SCENE_MODELS.append(os.getenv("A1111_ANIME_MODEL", ""))
# Filter out empty/duplicate entries
_SCENE_MODELS = list(dict.fromkeys(m for m in _SCENE_MODELS if m))


# ---------------------------------------------------------------------------
# Time of day
# ---------------------------------------------------------------------------

def _time_of_day() -> tuple[str, str]:
    """
    Return (label, prompt_fragment) based on current real-world time.
    The Undercity's artificial sky mimics a 24-hour cycle.
    """
    hour = datetime.now().hour
    if 5 <= hour < 7:
        return "dawn", "dawn light through the dome, amber and violet sky, long shadows, city waking up"
    elif 7 <= hour < 11:
        return "morning", "bright dome sky, morning crowds, vendors setting up stalls, sharp shadows"
    elif 11 <= hour < 14:
        return "midday", "high dome light, harsh overhead illumination, no shadows, heat haze rising from streets"
    elif 14 <= hour < 17:
        return "afternoon", "warm afternoon dome glow, golden light, busy streets, faction patrols"
    elif 17 <= hour < 20:
        return "dusk", "dusk, dome cycling to amber-red, long evening shadows, tavern lights coming on"
    elif 20 <= hour < 23:
        return "night", "night, dome sky dark, neon signs and torch light, shadows deep, faction enforcers visible"
    else:
        return "deep night", "deep night, dome black overhead, only torch-light and alchemical lanterns, near-empty streets, watchmen"


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

# Maps wttr.in weather codes → Undercity SD prompt fragments.
# Groups chosen to cover all ~50 wttr codes without a case per line.
def _wttr_to_undercity(code: int, temp_c: int) -> str:
    if code == 113:   # Clear / Sunny
        if temp_c >= 32:
            return "thermal surge from dome heat exchangers, heat shimmer rising off cobblestones, vendors retreating into shade"
        return "dome lighting at full intensity, hard crisp shadows on the cobblestones, the clearest the artificial sky gets"
    if code in (116, 119):   # Partly / Mostly cloudy
        return "dome light cycling between bright patches and muted grey, intermittent shadows, clouds painted on the inner panels"
    if code == 122:          # Overcast
        return "overcast dome, flat diffuse grey light, no shadows, gloomy streets, everyone moving with their heads down"
    if code in (143, 248, 260):  # Mist / Fog / Freezing fog
        return "dome fog rolling in from the lower vents, thick mist at street level, figures emerging from grey"
    if code in range(200, 232) or code in (386, 389, 392, 395):  # Thunderstorm variants
        return "dome electrical storm, arcing discharges flickering in the artificial sky, emergency lighting pulsing, people running"
    if code in (227, 230, 338, 371, 377):  # Blowing snow / blizzard / heavy snow
        return "dome cold front at full intensity, heavy frost coating every surface, pipes bursting, people wrapped in everything they own"
    if code in (323, 326, 329, 332, 335, 368):  # Light–moderate snow
        return "dome snow, rare white dusting on ledges and awnings, citizens stopping to look up in surprise"
    if code in (317, 320, 362, 365):  # Sleet
        return "dome sleet, icy pellets rattling off ironwork and rooftops, treacherous footing on the cobblestones"
    if code in (305, 308, 356, 359):  # Heavy rain / torrential
        return "heavy dome rain pouring from the upper vents, streets flooding at ground level, people sheltering in every doorway"
    if code in (263, 266, 281, 284, 293, 296, 299, 302, 311, 314, 353):  # Light–moderate rain
        return "artificial rain falling from dome vents, wet cobblestones gleaming, puddle reflections of neon and torch-light"
    if code in (350, 374, 377):  # Ice pellets
        return "dome ice pellets clattering off every surface, pedestrians flinching and covering their heads"
    if temp_c <= 2:
        return "deep cold sink from the dome regulators, breath misting, ice forming on metal railings, almost no foot traffic"
    return ""  # unknown code — fall through to DB


def _fetch_real_weather() -> str:
    """
    Fetch current real-world weather via wttr.in and return an Undercity SD
    prompt fragment.  Returns "" on any failure so callers can fall back.
    REAL_WEATHER_LOCATION env var must be set (city name, zip, or lat,lon).
    """
    location = os.getenv("REAL_WEATHER_LOCATION", "").strip()
    if not location:
        return ""
    try:
        import urllib.request
        url = f"https://wttr.in/{location}?format=j1"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        cc   = data["current_condition"][0]
        code = int(cc["weatherCode"])
        temp = int(cc["temp_C"])
        frag = _wttr_to_undercity(code, temp)
        logger.info(f"🖼️ [SCENE] Real weather @ {location}: code={code} temp={temp}°C → {frag or '(no mapping, falling back)'}")
        return frag
    except Exception as e:
        logger.debug(f"🖼️ [SCENE] wttr.in fetch failed ({e!r}); using dome_weather DB")
        return ""


def _current_weather() -> str:
    """
    Return an Undercity weather SD fragment.
    Priority: real-world wttr.in → dome_weather DB → default.
    """
    real = _fetch_real_weather()
    if real:
        return real

    # Fall back to dome_weather DB
    try:
        from src.db_api import get_global_state
        weather_json = get_global_state("dome_weather")
        if weather_json:
            if isinstance(weather_json, str):
                weather_json = json.loads(weather_json)
            condition = weather_json.get("condition") or weather_json.get("type", "")
            if condition:
                _weather_map = {
                    "clear":         "dome lighting at full intensity, hard crisp shadows on the cobblestones",
                    "rain":          "artificial rain falling from dome vents, wet cobblestones, puddle reflections",
                    "heavy rain":    "heavy dome rain pouring from the upper vents, streets flooding, people sheltering",
                    "fog":           "dome fog, thick mist at street level, shapes emerging from grey",
                    "storm":         "dome electrical storm, arcing discharges in the artificial sky, emergency lighting pulsing",
                    "snow":          "dome snow, rare white dusting on buildings, people bundled up, staring skyward",
                    "haze":          "industrial haze from the factories, amber murk in the dome light, visibility reduced",
                    "rift weather":  "rift contamination in the air, purple-green aurora flickering above, ozone distortion visible",
                    "acid drizzle":  "acid drizzle seeping from corroded dome vents, umbrellas up, everyone covering skin",
                    "overcast":      "overcast dome, flat grey light, no shadows, gloomy streets",
                    "thermal":       "thermal surge from dome heat exchangers, heat shimmer rising off cobblestones",
                    "cold":          "cold sink, breath misting in the air, people bundled, ice forming on railings",
                    "frost":         "frost coating every surface, pipes at risk, citizens walking carefully",
                    "pressure":      "pressure differential in the dome corridors, whistling vents, papers blowing",
                }
                for key, frag in _weather_map.items():
                    if key.lower() in condition.lower():
                        return frag
                return condition.lower()
    except Exception:
        pass
    return "dome lighting at full intensity, hard crisp shadows on the cobblestones"


# ---------------------------------------------------------------------------
# Holiday / seasonal themes
# ---------------------------------------------------------------------------

_HOLIDAYS = [
    # (start_month, start_day, end_month, end_day, name, SD fragment)
    # Each window: 7 days before the anchor date → 1 day after.

    # Halloween Oct 31  → Oct 24 – Nov 1
    (10, 24, 11,  1,
     "Veil Festival",
     "faction skull masks on every face, bone-lanterns hanging from market stalls, ghost-light orbs drifting at head height, incense smoke, "
     "children in death-themed costumes demanding offerings at doorways"),

    # Christmas Dec 25  → Dec 18 – Dec 26
    (12, 18, 12, 26,
     "Solstice Market",
     "festival market stalls draped in coloured faction banners, warm light-strings strung between buildings, gift boxes stacked high, "
     "carollers in faction colours, mulled wine braziers, snow-white decorations despite there being no snow"),

    # New Year Jan 1  → Dec 25 – Jan 2  (wraps year)
    (12, 25,  1,  2,
     "New Year",
     "spent firework-flare casings scattered on the wet streets, countdown boards still glowing, revellers sleeping on benches, "
     "confetti trampled into every puddle, faction banners fresh and newly hung"),

    # Lunar New Year ~Jan 29  → Jan 22 – Jan 30
    ( 1, 22,  1, 30,
     "Lunar Concourse",
     "red and gold paper lanterns strung across every alley, drum processions visible at intersections, lucky coin tokens on strings, "
     "faction stalls offering year-of-the-rift fortunes, firecrackers echoing off the dome walls"),

    # Valentine's Day Feb 14  → Feb 7 – Feb 15
    ( 2,  7,  2, 15,
     "Heartbond Week",
     "flower stall vendors overflowing onto every corner, rose-coloured bunting on faction signage, couples arm in arm, "
     "faction-coloured heart tokens pinned to lapels, chocolatiers doing record business"),

    # Spring Equinox Mar 20  → Mar 13 – Mar 21
    ( 3, 13,  3, 21,
     "Renewal Bloom",
     "golden pollen drifting from the Divine Garden district, flower garlands looped over faction signage, "
     "street sweepers overwhelmed, everyone sneezing, children with pollen-stained faces"),

    # Summer Solstice Jun 21  → Jun 14 – Jun 22
    ( 6, 14,  6, 22,
     "Midsummer Circuit",
     "open-air music stages on every plaza, festival fabrics and bright colours, alchemical cooling units at street corners, "
     "street food vendors shoulder to shoulder, dome lighting turned warm amber for the season"),

    # Fallen Adventurers Day Jul 15  → Jul 8 – Jul 16
    # The Sorrow Wall (Grand Forum) — marble wall etched with names of every citizen lost to Rift events.
    # The Adventurers Guild memorial wall at Guild Spires — maintained by the Guild Master.
    ( 7,  8,  7, 16,
     "Day of the Fallen",
     "citizens moving slowly and quietly toward the Grand Forum, fresh flowers and candles laid at the base of the Sorrow Wall, "
     "Guild members in mourning-grey sashes, faction representatives standing silently in their colours, "
     "the Champion's Plinth dark and covered — no rankings displayed today, "
     "chalk names of newly fallen adventurers scrawled on the cobblestones outside Guild Spires, "
     "street vendors absent, no music, a city holding its breath"),

    # Fall Equinox Sep 22  → Sep 15 – Sep 23
    ( 9, 15,  9, 23,
     "Harvest Concourse",
     "market stalls piled with preserved food and dried goods, harvest-colour faction banners — orange amber gold — "
     "prices temporarily fair, children running unsupervised, faction goodwill gestures posted on bulletin boards"),
]


def _holiday_theme() -> tuple[str, str]:
    """
    Check whether today falls within a seasonal event window.
    Returns (holiday_name, sd_fragment) or ("", "").
    """
    today = datetime.now()
    m, d  = today.month, today.day

    for s_mo, s_day, e_mo, e_day, name, frag in _HOLIDAYS:
        # Build comparable int tuples — works across year boundaries (e.g. Dec→Jan)
        start = (s_mo, s_day)
        end   = (e_mo, e_day)
        now   = (m, d)
        if start <= end:
            in_range = start <= now <= end
        else:
            # Wraps year (e.g. Dec 18 → Jan 3)
            in_range = now >= start or now <= end
        if in_range:
            return name, frag
    return "", ""


# ---------------------------------------------------------------------------
# Location selection
# ---------------------------------------------------------------------------

def _get_district_sd_fragment(district: str) -> str:
    """Pull the pre-built SD fragment for a district from area_profiles."""
    try:
        from src.db_api import raw_query
        import json as _json
        rows = raw_query(
            "SELECT profile_json FROM area_profiles WHERE district=%s", (district,)
        ) or []
        if rows and rows[0].get("profile_json"):
            profile = rows[0]["profile_json"]
            if isinstance(profile, str):
                profile = _json.loads(profile)
            return (profile.get("sd_fragment") or "").strip()
    except Exception:
        pass
    return ""


def _pick_location() -> tuple[str, str, str, int, str, str]:
    """
    Pick a random location from the gazetteer DB.
    Returns (district, place_name, type_tag, wealth_level, place_description, district_sd_fragment).
    Falls back to hardcoded list if DB is empty.
    """
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT district, name, type_tag, wealth_level, description "
            "FROM gazetteer_places "
            "WHERE district IS NOT NULL AND name IS NOT NULL "
            "ORDER BY RAND() LIMIT 1"
        ) or []
        if rows:
            r        = rows[0]
            district = r["district"]
            place    = r["name"]
            ptype    = (r.get("type_tag") or "").strip()
            wealth   = int(r.get("wealth_level") or 5)
            desc     = (r.get("description") or "").strip()
            dist_frag = _get_district_sd_fragment(district)

            # Empty type_tag — infer from district character
            if not ptype:
                district_lower = district.lower()
                if any(w in district_lower for w in ("shantytown", "shanty", "fringe")):
                    ptype = "shanty"
                elif any(w in district_lower for w in ("collapsed", "scrapwork", "ashfall", "night pit", "cult corner", "duskhollow")):
                    ptype = "warrens"
                elif any(w in district_lower for w in ("ironwork", "ember", "outer wall")):
                    ptype = "industrial"
                elif any(w in district_lower for w in ("market", "bazaar", "cobbleway")):
                    ptype = "market"
                elif any(w in district_lower for w in ("tower", "spire")):
                    ptype = "tower"
                elif any(w in district_lower for w in ("temple", "reliquary", "sanctum")):
                    ptype = "temple"
                elif any(w in district_lower for w in ("archive", "academy", "guild spire")):
                    ptype = "landmark"
                elif any(w in district_lower for w in ("forum", "diplomat", "hearthstone")):
                    ptype = "political"
                else:
                    ptype = "street"

            # Dangerous-district override for generic types only — a specific named
            # tavern in the Night Pits is still a tavern, but a generic street is warrens
            district_lower = district.lower()
            if ptype in ("street", "alley", "residential"):
                if any(w in district_lower for w in (
                    "collapsed", "scrapwork", "ashfall", "night pit",
                    "cult corner", "duskhollow", "coppergate"
                )):
                    ptype = "warrens"
                elif any(w in district_lower for w in ("shantytown", "fringe")):
                    ptype = "shanty"

            return district, place, ptype, wealth, desc, dist_frag
    except Exception as e:
        logger.warning(f"🖼️ [SCENE] gazetteer DB query failed: {e!r}")

    # Fallback — no district fragment available at this point
    fallbacks = [
        ("Grand Forum",          "the Forum Clock plaza",                       "plaza",        9, ""),
        ("Floating Bazaar",      "the hanging market stalls",                   "market",       6, ""),
        ("Artisan Quarter",      "The Hollow Forge smithy",                     "smithy",       6, ""),
        ("Archive Row",          "The Frosted Quill scholar's bar",             "tavern",       7, "A dimly lit bar where scholars swap theories."),
        ("Cobbleway Market",     "a general goods market street",               "market",       5, ""),
        ("Coppergate",           "a working-class tenement block",              "warrens",      3, ""),
        ("Ironworks",            "a factory district street",                   "industrial",   3, ""),
        ("Ashfall Terraces",     "The Burned Healer clinic",                    "clinic",       2, "A clinic with charred walls and antiseptic stench."),
        ("Collapsed Plaza",      "The Wound's Edge fighting pit",               "arena",        1, "A ring of broken concrete where fighters duel."),
        ("Shantytown Heights",   "shanty walkways above the waste level",       "shanty",       1, ""),
        ("Sanctum Quarter",      "a Serpent Choir temple annex",                "temple",       8, ""),
        ("Night Pits",           "a narrow warren alley near the faction wall", "warrens",      2, ""),
    ]
    district, place, ptype, wealth, desc = random.choice(fallbacks)
    dist_frag = _get_district_sd_fragment(district)
    return district, place, ptype, wealth, desc, dist_frag


# ---------------------------------------------------------------------------
# Scene prompt builder
# ---------------------------------------------------------------------------

def _wealth_fragment(wealth: int) -> str:
    """
    Convert a district's wealth_level (1-10) into an SD prompt fragment
    describing the visible signs of that wealth level.
    Wealth changes dynamically — rift damage, council investment, disasters.
    """
    if wealth >= 9:
        return (
            "grand architecture of polished stone and gilded ironwork, "
            "citizens in expensive faction-coloured robes and tailored coats, "
            "FTA inspectors and private guards visible, "
            "spotless streets, arcane lighting fixtures, "
            "exclusive shopfronts with etched glass windows"
        )
    elif wealth >= 7:
        return (
            "solid prosperous architecture, well-maintained facades, "
            "guild signage on upper floors, well-dressed professionals and merchants, "
            "faction officials present but not overwhelming, "
            "gas-lamp lighting in good repair, clean swept cobblestones"
        )
    elif wealth >= 5:
        return (
            "serviceable buildings with mixed upkeep, "
            "working-class crowds in practical clothing, "
            "a mix of faction colours and neutral citizens, "
            "some worn stonework and patched walls, "
            "functional street lighting, vendors at doorsteps"
        )
    elif wealth >= 3:
        return (
            "cracked and patched facades, people in worn clothing moving quickly, "
            "Iron Fang or Consortium enforcers on patrol rather than officials, "
            "refuse in the gutters, a few boarded windows, "
            "flickering or broken lights, makeshift stalls"
        )
    else:
        return (
            "crumbling structures barely held together with rope and salvage, "
            "desperate faces that look away from strangers, "
            "gang territorial markers and warning signs on every surface, "
            "almost no official presence, "
            "darkness broken only by barrel fires and single lanterns, "
            "evidence of recent damage: scorch marks, collapsed sections"
        )


def _build_scene_prompt(
    district: str,
    place: str,
    place_type: str,
    time_label: str,
    time_frag: str,
    weather: str,
    model: str,
    wealth: int = 5,
    description: str = "",
    district_sd_fragment: str = "",
    holiday: str = "",
    holiday_name: str = "",
) -> tuple[str, str, str]:
    """
    Build the full SD prompt, negative prompt, and caption for a city scene.
    Returns (positive_prompt, negative_prompt, caption).
    """
    _image_style = os.getenv("IMAGE_STYLE", "photorealistic").lower().strip()
    is_anime     = _image_style == "anime" or "nova" in model.lower() or "anime" in model.lower()

    # Tower fragment — always sci-fi, always in the far background
    tower_frag = (
        "in the far background the Tower of Last Chance rises impossibly high, "
        "a gleaming sci-fi spire of chrome and dark glass stretching beyond the dome, "
        "disappearing into the artificial sky, dwarfing every building around it"
    )

    # Location type modifiers — these drive the SD prompt detail.
    # IMPORTANT: types map to the danger/character of the district, NOT just the architecture.
    # Warrens ≠ nice residential. Shanty ≠ charming poverty. Get the tone right.
    type_frags = {
        # ── Eating / Drinking ──────────────────────────────────────────────
        "tavern":        "tavern interior visible through open doors, warm firelight, patrons at rough-hewn tables, bottles and flagons on shelves, smoke and the smell of ale",
        "inn":           "inn courtyard and entrance, hanging lantern sign, travelers and merchants unloading bags, stable hands, worn but welcoming facade",
        "bakery":        "bakery storefront, warm light from brick ovens within, trays of goods in the window, queue of customers, flour-dusted workers",

        # ── Commerce / Markets ─────────────────────────────────────────────
        "market":        "crowded market stalls packed tight, goods piled high, merchants calling out, faction buyers haggling, guards watching the edges",
        "shop":          "merchant shopfront, goods on open display, a sign overhead, clerk dealing with a queue of customers, faction buyers examining wares",
        "specialty":     "specialty goods shop with unusual wares in the window, discrete signage, serious-looking customers, a guard on the door",
        "general":       "general goods shop with barrels and crates outside, diverse stock on shelves, steady foot traffic from all walks of life",
        "weapon":        "weapon shop, blades and polearms displayed in the window and on wall racks, armored clientele, a whetstone grinding in back",
        "armor":         "armor shop, suits and plate pieces on stands, guild smiths inspecting fit, faction insignia on display pieces",
        "tool":          "tool and equipment merchant, practical goods stacked to the ceiling, dock workers and factory hands shopping",
        "potion":        "potions and reagents shop, glowing vials in the window, the smell of alchemical reagents, careful-looking clientele",
        "magic":         "arcane goods shop, contained magical auras visible, sigil-engraved goods behind glass, cautious wealthy buyers",
        "scroll":        "scroll and document shop, shelves of rolled parchment, scholars examining texts at reading tables, protective wards visible",
        "apothecary":    "apothecary shop front, dried herbs in jars, a mortar and pestle on the counter, steady stream of residents buying remedies",

        # ── Services / Professional ────────────────────────────────────────
        "clinic":        "medical clinic, a red lamp or healing symbol at the door, patients waiting on benches, healers moving urgently, the smell of antiseptic",
        "office":        "professional office on an upper floor, shuttered windows, a queue of petitioners, faction officials going in and out",
        "service":       "service establishment, neutral signage, mixed clientele, workers in practical uniforms, the interior glimpsed through a half-open door",
        "guild":         "guild hall entrance, faction insignia above the arch, uniformed members coming and going, a notice board crowded with contracts",

        # ── Civic / Institutions ───────────────────────────────────────────
        "landmark":      "impressive civic structure of worked stone and iron, wide steps leading to an entrance, citizens gathered and pointing, arcane light detailing",
        "monument":      "formal public monument or memorial, carved stone figures, citizens pausing to observe, faction wreaths and offerings at the base",
        "attraction":    "public attraction drawing a mixed crowd, onlookers of every species, a street performer or display nearby, energy of spectacle",
        "curiosity":     "an unusual or out-of-place structure, bystanders peering curiously, something that shouldn't be there but is, an atmosphere of low unease",
        "plaza":         "open civic plaza, monument at the center with competing faction marks, ring of watchers at the edges, nobody standing in the middle",
        "political":     "faction banners hanging from tall buildings, uniformed officials, guarded entrances, petitioners queuing in the rain",
        "tower":         "vast plaza at the base of the Tower, arcane light bleeding from the spire, supplicants and merchants, the Tower impossibly close and overwhelming",

        # ── Entertainment ──────────────────────────────────────────────────
        "theater":       "playhouse or theater facade, playbill posters on the walls, a queue forming at the box window, stagehands moving equipment, gas footlights visible",
        "arena":         "fighting arena exterior or interior, tiered seating, roaring crowd or blood-stained dirt floor, weapon racks at the edges, faction banners overhead",

        # ── Religious ──────────────────────────────────────────────────────
        "temple":        "stone-arched temple facade, faction iconography carved above the door, worshippers in robes, incense smoke rising into the dome-sky",
        "shrine":        "small public shrine set into an alcove, offerings of coins and food at the base, a kneeling figure, faction iconography worked into the stonework",

        # ── Faction / Criminal ─────────────────────────────────────────────
        "hideout":       "nondescript building with no signage, boarded lower windows, a single watcher at the door, narrow approach alley, coded marks on the doorframe",

        # ── Outdoor / Natural ──────────────────────────────────────────────
        "garden":        "a rare cultivated garden under the dome, stone paths between raised planting beds, strange dome-adapted plants, citizens walking slowly and quietly",

        # ── Docks / Ports ──────────────────────────────────────────────────
        "docks":         "heavy loading cranes, rope-lashed crates, saltwater smell, dock workers in worn gear, faction shipping flags on masts",
        "docks_lower":   "fog-choked lower docks, rotting wood piers, smuggler vessels tied to cleats, dim lanterns, figures watching from doorways, no official presence",

        # ── Industrial ─────────────────────────────────────────────────────
        "industrial":    "factory smokestacks pouring black smoke, conveyor belts visible through grimy windows, workers in protective gear, Iron Fang enforcers on patrol",
        "warehouse":     "warehouse district, shuttered iron loading bays, a few hard-looking workers, no foot traffic, faction sigils spray-painted on shutters",
        "smithy":        "forge workshop, orange glow of the furnace through the open front, a smith at work on an anvil, finished weapons and tools hanging on the wall",

        # ── Residential — tiered by social class ──────────────────────────
        "residential":      "mid-ring residential block, tenement buildings five stories, laundry lines strung between windows, vendors at street level, wary but not hostile",
        "residential_poor": "outer-ring tenements in disrepair, cracked facades, broken windows covered with boards, children in patched clothes watching strangers, Patchwork Saints chalk marks",

        # ── Warrens — DANGEROUS, NOT charming poverty ─────────────────────
        "warrens":       (
            "cramped warren alleyways so narrow shoulders brush both walls, "
            "buildings stacked and leaning overhead cutting off dome-light, "
            "Iron Fang and Serpent Choir territorial graffiti on every surface, "
            "residents moving fast and not making eye contact, "
            "a rusted iron barrier at the far end of the passage, "
            "damp stone, old fire pits, the smell of rot"
        ),
        "shanty":        (
            "shanty walkways of salvaged wood and rope stretched between structures, "
            "patchwork dwellings nailed together from scrap metal and broken crates, "
            "smoke from barrel cooking fires, figures in rags watching from doorways, "
            "no faction presence, Patchwork Saints aid markers scratched into the walls"
        ),
        "underground":   "low-ceilinged underground tunnels, phosphorescent moss the only light, dripping water, narrow passages between crumbling support columns, a figure wrapped in shadows",

        # ── Ruins ──────────────────────────────────────────────────────────
        "ruins":         "crumbled walls exposing rusted rebar, overgrown with pale fungus, squatter camps in the wreckage, faction warning signs, the air thick with ash",

        # ── Streets ────────────────────────────────────────────────────────
        "street":        "cobblestone street slicked with condensation, people moving with purpose, faction signage on every corner, a patrol visible at the far end",
        "alley":         "narrow alley between windowless walls, stacked crates blocking one end, a single guttering lantern, shadows that move on their own schedule",
    }
    loc_frag = type_frags.get(place_type.lower(), "busy Undercity street, faction signage and watchful eyes")

    # Description flavor — first 100 chars of the DB description, cleaned up for SD injection
    desc_frag = ""
    if description:
        # Strip DnD mechanical text (DC checks etc.) and trim
        import re
        cleaned = re.sub(r"DC\s*\d+[^,\.]*[,\.]?", "", description)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        if cleaned:
            desc_frag = cleaned[:120].rstrip(",. ") + ", "

    if is_anime:
        quality = (
            "masterpiece, best quality, very aesthetic, absurdres, "
            "detailed background, cinematic composition, dynamic angle, "
            "environmental storytelling, anime key visual style"
        )
        neg = (
            "nsfw, worst quality, jpeg artifacts, lowres, simple background, "
            "white background, text, watermark, signature, cropped, "
            "portrait close-up, solo character, no background"
        )
    else:
        quality = (
            "cinematic photography, wide angle lens, sharp focus, "
            "detailed architecture, film grain, dramatic lighting, 8k uhd, "
            "environmental storytelling, photorealistic, no text"
        )
        neg = (
            "cartoon, anime, painting, illustration, sketch, cgi, 3d render, "
            "oversaturated, plastic, blurry, watermark, text, signature, "
            "portrait close-up, simple background, white background"
        )

    # Undercity is a dome city — NOT underground caves/sewers
    neg += (
        ", sewer, cave, medieval castle, open countryside, "
        "fantasy forest, village, sunny outdoor meadow, "
        "empty room, corridor only, bare stone tunnel"
    )

    wealth_frag  = _wealth_fragment(wealth)
    # District ambient fragment — architecture style, faction presence, atmosphere
    dist_frag_str = f"{district_sd_fragment}, " if district_sd_fragment else ""

    # Show the dome explicitly ~30% of the time — it's always there in-world but
    # doesn't need to dominate every frame. Strip "dome " from time/weather phrases
    # and the base tag on the other 70% so A1111 focuses on street-level detail instead.
    _show_dome = random.random() < 0.30
    _time_frag  = time_frag if _show_dome else time_frag.replace("dome ", "").replace(" dome", "")
    _weather    = weather   if _show_dome else weather.replace("dome ", "").replace(" dome", "")
    _city_tag   = "Undercity dome city" if _show_dome else "Undercity city"

    holiday_frag_str = f"{holiday}, " if holiday else ""

    prompt = (
        f"{quality}, "
        f"wide establishing shot of {place} in the {district} district of the Undercity, "
        f"{desc_frag}"
        f"{loc_frag}, "
        f"{dist_frag_str}"
        f"{wealth_frag}, "
        f"{_time_frag}, {_weather}, "
        f"{holiday_frag_str}"
        f"dark urban fantasy noir, dense city architecture, {_city_tag}, "
        f"citizens of many species and cultures, "
        f"{tower_frag}"
    )

    wealth_label = (
        "elite" if wealth >= 9 else "prosperous" if wealth >= 7
        else "working class" if wealth >= 5 else "poor" if wealth >= 3
        else "destitute"
    )
    caption = (
        f"**{place}** — {district} | {time_label.title()}, {weather}"
        + (f" | {holiday_name}" if holiday_name else "")
        + f" | wealth {wealth}/10 ({wealth_label})"
    )

    return prompt, neg, caption


# ---------------------------------------------------------------------------
# A1111 helper
# ---------------------------------------------------------------------------

async def _call_a1111(
    prompt: str,
    neg: str,
    model: str,
    *,
    steps: int = 28,
    cfg: float = 6.5,
    width: int = 1216,
    height: int = 768,
) -> Optional[bytes]:
    """Call A1111 txt2img and return PNG bytes."""
    A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")

    from src.a1111_runtime import cool_down_a1111_after_generation, ensure_a1111_model
    await ensure_a1111_model(model, label="SCENE", url=A1111_URL)

    payload = {
        "prompt":          prompt,
        "negative_prompt": neg,
        "steps":           steps,
        "cfg_scale":       cfg,
        "width":           width,
        "height":          height,
        "sampler_name":    "DPM++ 2M SDE Karras",
        "seed":            random.randint(1, 999_999),
        "batch_size":      1,
        "n_iter":          1,
    }

    try:
        timeout = float(os.getenv("A1111_SCENE_TIMEOUT", "900"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
            data = resp.json()
            images = data.get("images")
            if images:
                logger.info(f"🖼️ [SCENE] Got {len(images)} image(s) from A1111")
                from src.a1111_health import record_a1111_success
                await record_a1111_success("city_scene")
                await cool_down_a1111_after_generation()
                return base64.b64decode(images[0])
            else:
                logger.warning(f"🖼️ [SCENE] A1111 returned empty images list — response keys: {list(data.keys())}")
                from src.a1111_health import record_a1111_failure
                await record_a1111_failure("city_scene", "empty images list", url=A1111_URL)
    except httpx.ConnectError as e:
        logger.warning(f"🖼️ [SCENE] A1111 not reachable at {A1111_URL} — is it running? ({e!r})")
        from src.a1111_health import record_a1111_failure
        await record_a1111_failure("city_scene", f"connect error: {e!r}", url=A1111_URL)
    except httpx.TimeoutException as e:
        logger.warning(f"🖼️ [SCENE] A1111 timed out after {timeout:.0f}s — generation took too long")
        from src.a1111_health import record_a1111_failure
        await record_a1111_failure("city_scene", f"timeout after {timeout:.0f}s", url=A1111_URL)
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        logger.warning(f"🖼️ [SCENE] A1111 HTTP {e.response.status_code}: {body}")
        from src.a1111_health import record_a1111_failure
        await record_a1111_failure("city_scene", f"HTTP {e.response.status_code}: {body[:120]}", url=A1111_URL)
        if "AutoencoderKLInferenceWrapper" in body or "quant_conv" in body:
            logger.warning(
                f"🖼️ [SCENE] VAE mismatch detected for model '{model}'. "
                f"Restart A1111 to clear the bad VAE state; the bot no longer sends VAE overrides."
            )
    except Exception as e:
        logger.warning(f"🖼️ [SCENE] A1111 call failed: {e!r}")
        from src.a1111_health import record_a1111_failure
        await record_a1111_failure("city_scene", f"call failed: {e!r}", url=A1111_URL)

    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_city_scene() -> tuple:
    """
    Generate a wide city scene image of the Undercity.

    Modeled after generate_npc_portrait() — same retry/wait logic.
    The Tower always appears in the far background as a sci-fi spire.

    Returns (image_bytes, prompt_str, caption_str).
    Returns (None, None, None) on failure.
    """
    from src.news_feed import a1111_lock
    from src.resource_cop import wait_for_a1111_turn

    # A1111 runs in its own GPU context — completely separate from Ollama.
    # With 8GB dedicated + 16GB shared VRAM, A1111 (SDXL ~6-8GB) and Ollama
    # (8B slim ~5.2GB) fit simultaneously. No Ollama busy check needed here.

    district, place, place_type, wealth, description, dist_frag = _pick_location()
    time_label, time_frag                                       = _time_of_day()
    weather                                                     = _current_weather()
    holiday_name, holiday_frag                                  = _holiday_theme()
    model                                                       = random.choice(_SCENE_MODELS) if _SCENE_MODELS else ""

    logger.info("🖼️ [SCENE] ─────────────────────────────────────────")
    logger.info(f"🖼️ [SCENE] Location:   {place} ({district})")
    logger.info(f"🖼️ [SCENE] Type tag:   {place_type}")
    logger.info(f"🖼️ [SCENE] Wealth:     {wealth}/10")
    logger.info(f"🖼️ [SCENE] Time:       {time_label}")
    logger.info(f"🖼️ [SCENE] Weather:    {weather}")
    if holiday_name:
        logger.info(f"🖼️ [SCENE] Holiday:    {holiday_name}")
    logger.info(f"🖼️ [SCENE] Model:      {model or '(default)'}")
    logger.info(f"🖼️ [SCENE] Dist frag:  {'yes' if dist_frag else 'none'} ({district})")
    if description:
        logger.info(f"🖼️ [SCENE] Place desc: {description[:80]}...")

    prompt, neg, caption = _build_scene_prompt(
        district, place, place_type, time_label, time_frag, weather, model,
        wealth, description, dist_frag,
        holiday=holiday_frag, holiday_name=holiday_name,
    )

    logger.info(f"🖼️ [SCENE] Prompt:    {prompt[:200]}...")

    img_bytes = None
    try:
        decision = await wait_for_a1111_turn("city_scene", model_hint=model)
        if not decision.run_now:
            logger.warning(
                "🖼️ [SCENE] A1111 still busy after traffic-cop wait; skipping this scene cycle: %s",
                decision.reason,
            )
            from src.a1111_health import record_a1111_failure
            await record_a1111_failure("city_scene", f"busy after traffic-cop wait: {decision.reason}")
            return None, None, None
        async with a1111_lock:
            img_bytes = await _call_a1111(prompt, neg, model)
    except Exception as e:
        logger.warning(f"🖼️ [SCENE] Generation failed: {e}")

    if img_bytes:
        try:
            from src.image_ref import save_location_ref
            save_location_ref(
                place,
                img_bytes,
                metadata={
                    "district": district,
                    "place": place,
                    "place_type": place_type,
                    "wealth_level": wealth,
                    "caption": caption,
                    "source": "city_scene",
                },
            )
        except Exception as e:
            logger.warning(f"🖼️ [SCENE] Failed to save place image ref for {place}: {e}")
        logger.info(f"🖼️ [SCENE] Done — {len(img_bytes)//1024}KB | {caption}")
    else:
        logger.warning("🖼️ [SCENE] No image produced")

    return img_bytes, prompt, caption

