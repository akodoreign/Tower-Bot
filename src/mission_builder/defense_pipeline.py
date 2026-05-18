"""
defense_pipeline.py — Pipeline for Defense mission modules.

A defense is an open-ended, multi-day mission where the party holds a location
against an attacking force. It does not use 5-scene structure — instead it
generates a living siege document with waves, downtime, morale, and a debrief.

Flow:
  1. Briefing      — contact, location, threat, timeline (soft/unknown)
  2. Location      — faction-appropriate defensible site + A1111 map
  3. Attacker      — army type + base force + faction morale pool
  4. Downtime      — watch event table, resource list, intel leads (feed force modifiers)
  5. Waves         — 2-4 waves with modified force composition
  6. Module HTML   — briefing, defense card, wave cards, morale track, debrief
  7. Session HTML  — linear card flow: briefing → waves → between-wave → debrief
  8. index.html + zip + DB slug

Exported:
    build_defense_module(mission: dict, out_dir: Path) -> Path
    is_defense_mission(mission_type: str) -> bool
"""

from __future__ import annotations

import os
import re
import json
import base64
import random
import asyncio
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

import httpx

from src.log import logger
from src.mission_builder.html_renderer import _faction_color, _CSS, _page
from src.mission_builder.cr_scaling import mission_cr, party_strength as _party_strength

OUTPUT_BASE  = Path(__file__).resolve().parent.parent.parent / "generated_modules"
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
A1111_URL    = os.getenv("A1111_URL", "http://127.0.0.1:7860")

# ---------------------------------------------------------------------------
# Mission type detection
# ---------------------------------------------------------------------------

_DEFENSE_KEYWORDS = {"defense", "defend", "hold", "siege", "fortify", "guard the", "protect the"}

def is_defense_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _DEFENSE_KEYWORDS)


# ---------------------------------------------------------------------------
# Faction profiles
# ---------------------------------------------------------------------------

# base_morale is before tier scaling
# style: how the faction fights (used in prompts and module flavour)
FACTION_PROFILES: Dict[str, Dict] = {
    "Wardens of Ash": {
        "base_morale": 28,
        "army_style":  "warband",
        "tactics":     "highly regimented, squad-based, fall back to regroup then recommit, never truly break",
        "commander":   "a Wall Commander — tactical, calm under fire, inspires by example",
    },
    "Tower Authority": {
        "base_morale": 26,
        "army_style":  "warband",
        "tactics":     "institutional discipline, escalating force, will call in reinforcements rather than rout",
        "commander":   "a Senior Enforcer — by-the-book, escalates to lethal force methodically",
    },
    "Patchwork Saints": {
        "base_morale": 25,
        "army_style":  "mob",
        "tactics":     "chaotic but stubborn, fight for each other, morale sustained by community bonds not command",
        "commander":   "a neighbourhood boss — rallies by personal loyalty, loses authority if wounded",
    },
    "Wizards Tower": {
        "base_morale": 18,
        "army_style":  "warband",
        "tactics":     "overconfident, relies on magic advantage, loses confidence fast if their tricks stop working or their leader hesitates",
        "commander":   "an Arcane Supervisor — brilliant but brittle, morale crumbles if they publicly doubt the mission",
    },
    "Argent Blades": {
        "base_morale": 20,
        "army_style":  "warband",
        "tactics":     "professional mercenaries, holds until losses exceed contract value, withdraws cleanly",
        "commander":   "a Contract Captain — calculating, will negotiate withdrawal if offered face-saving terms",
    },
    "Iron Fang Consortium": {
        "base_morale": 20,
        "army_style":  "warband",
        "tactics":     "profit-driven discipline, efficient, cuts losses when ROI is negative",
        "commander":   "a Consortium Handler — manages the attack like a business operation",
    },
    "Brother Thane's Cult": {
        "base_morale": 35,
        "army_style":  "cultist_surge",
        "tactics":     "fanatical, self-sacrifice triggers effects, morale near-immune — only breaks on commander death",
        "commander":   "a Returned Apostle — death causes a morale surge in remaining grunts before collapse",
    },
    "Serpent Choir": {
        "base_morale": 24,
        "army_style":  "cultist_surge",
        "tactics":     "zealot discipline, holds long then shatters suddenly when the ritual logic breaks",
        "commander":   "a Choir Director — morale collapses if their ritual objective is denied twice",
    },
    "Obsidian Lotus": {
        "base_morale": 16,
        "army_style":  "shadow_cell",
        "tactics":     "small elite force, not trying to win — trying to get one thing through. Withdraws clean when the math says so",
        "commander":   "a Cell Coordinator — never seen on the field, withdraws the cell if objective becomes impossible",
    },
    "Glass Sigil": {
        "base_morale": 10,
        "army_style":  "shadow_cell",
        "tactics":     "avoids direct combat entirely, uses proxies and distractions, folds fast under real pressure",
        "commander":   "a Sigil Broker — not a fighter, flees or negotiates the moment casualties mount",
    },
    "Guild of Ashen Scrolls": {
        "base_morale": 17,
        "army_style":  "warband",
        "tactics":     "scholarly pride holds them together, but internal disagreement can collapse cohesion mid-assault",
        "commander":   "a Senior Archivist — competent planner, but loses authority if junior members start second-guessing",
    },
}

_DEFAULT_PROFILE = {
    "base_morale": 18,
    "army_style":  "warband",
    "tactics":     "determined but disorganised",
    "commander":   "a field leader of unknown capability",
}

def _get_profile(faction: str) -> Dict:
    for k, v in FACTION_PROFILES.items():
        if k.lower() in faction.lower():
            return v
    return _DEFAULT_PROFILE


# ---------------------------------------------------------------------------
# Army types
# ---------------------------------------------------------------------------

ARMY_TYPES = {
    "mob": {
        "label":       "Mob",
        "description": "Disorganised surge — high numbers, low tactics. No real command; killing the 'leader' causes confusion, not a rout.",
        "grunt_label": "rioters / street fighters",
        "lt_label":    "mob enforcers",
        "grunt_cr":    "1/4",
        "lt_cr":       "1",
        "wave_size":   (8, 14),
        "lt_count":    (1, 2),
    },
    "warband": {
        "label":       "Warband",
        "description": "Professional fighters in squads of 4-6 with a sergeant per squad. Flanking tactics, falls back to regroup.",
        "grunt_label": "soldiers / fighters",
        "lt_label":    "squad sergeants",
        "grunt_cr":    "1/2",
        "lt_cr":       "2",
        "wave_size":   (5, 9),
        "lt_count":    (1, 3),
    },
    "cultist_surge": {
        "label":       "Cultist Surge",
        "description": "Fanatical, ignores morale checks. Some grunts self-sacrifice to trigger effects. Thin numbers, unpredictable.",
        "grunt_label": "true believers / acolytes",
        "lt_label":    "zealot champions",
        "grunt_cr":    "1/2",
        "lt_cr":       "2",
        "wave_size":   (4, 8),
        "lt_count":    (1, 2),
    },
    "shadow_cell": {
        "label":       "Shadow Cell",
        "description": "Small, elite. Not trying to win — trying to get one thing through the defense. Withdraws clean on failure.",
        "grunt_label": "operatives / agents",
        "lt_label":    "cell lieutenants",
        "grunt_cr":    "1",
        "lt_cr":       "3",
        "wave_size":   (3, 6),
        "lt_count":    (1, 2),
    },
}


# ---------------------------------------------------------------------------
# Location tables per faction
# ---------------------------------------------------------------------------

FACTION_LOCATIONS: Dict[str, List[str]] = {
    "Wardens of Ash":          ["a wall gate outpost", "a memorial hall", "a civilian shelter checkpoint"],
    "Tower Authority":         ["a transit node", "a ward anchor point", "an enforcement checkpoint"],
    "Patchwork Saints":        ["a community safehouse", "a food kitchen", "a bolt-hole network entrance"],
    "Wizards Tower":           ["a restricted research annex", "an arcane relay tower", "a containment facility"],
    "Argent Blades":           ["a contract staging depot", "an armoury house", "a mercenary billet"],
    "Iron Fang Consortium":    ["a consortium vault", "a secure warehouse", "a distribution hub"],
    "Brother Thane's Cult":    ["a hidden recruitment hall", "a ritual preparation site", "a converted cellar shrine"],
    "Serpent Choir":           ["a hidden shrine", "an initiation chamber", "an underground meeting hall"],
    "Obsidian Lotus":          ["a dead-drop location", "a private meeting house", "a smuggler dock"],
    "Glass Sigil":             ["a secure office", "a private gallery", "an information broker front"],
    "Guild of Ashen Scrolls":  ["an archive annex", "a scholar's sanctum", "a vault of restricted texts"],
}

_DEFAULT_LOCATIONS = ["a fortified building", "a defended plaza", "a secure compound"]

def _pick_location(faction: str) -> str:
    for k, v in FACTION_LOCATIONS.items():
        if k.lower() in faction.lower():
            return random.choice(v)
    return random.choice(_DEFAULT_LOCATIONS)


# ---------------------------------------------------------------------------
# Tier scaling
# ---------------------------------------------------------------------------

TIER_SCALES = {
    "standard": {"morale_mult": 1.0, "grunt_bonus": 0,  "wave_count": 2},
    "seasoned": {"morale_mult": 1.3, "grunt_bonus": 2,  "wave_count": 3},
    "elite":    {"morale_mult": 1.6, "grunt_bonus": 4,  "wave_count": 3},
    "legend":   {"morale_mult": 2.0, "grunt_bonus": 6,  "wave_count": 4},
}

def _tier_scale(tier: str) -> Dict:
    return TIER_SCALES.get((tier or "standard").lower(), TIER_SCALES["standard"])


# ---------------------------------------------------------------------------
# Force modifier table
# ---------------------------------------------------------------------------

FORCE_MODIFIERS = [
    # (trigger_source, description, grunt_delta, lt_delta, morale_delta, commander_effect)
    ("intel — captured scout",        "Captured enemy scout revealed patrol routes",   -3,  0,  -2, None),
    ("intel — vantage point",         "Scouted enemy staging area, knew wave timing",  -2,  0,  -3, None),
    ("intel — local contact",         "Local contact identified commander's position",  0,  0,  -4, "commander arrives cautious, -2 to attack rolls round 1"),
    ("watch — spy slipped through",   "Enemy spy reported defensive layout",            +3,  0,  +2, None),
    ("watch — missed patrol",         "Patrol missed — enemy probed defenses unseen",   +2, +1,  0, None),
    ("watch — intercepted messenger", "Intercepted enemy messenger, disrupted orders",  -2, -1, -3, None),
    ("resource — food spoiled",       "Food supply compromised, defender fatigue",       0,  0,  0, None),
    ("resource — weapons cached",     "Found cached weapons, defenders better equipped", 0,  0,  0, "party gains 1 upgrade slot for free"),
    ("rally — inspiring speech",      "Party rallied defenders, morale boosted",         0,  0, -3, None),
    ("intimidation — display",        "Visible show of force unnerved approaching units",-2,  0, -4, None),
]


def _normalize_force_modifier_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("â€”", "-").replace("—", "-").replace("–", "-")
    text = re.sub(r"\s*-\s*", " - ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _force_modifier_entry(key: str) -> Optional[tuple]:
    wanted = _normalize_force_modifier_key(key)
    for mod in FORCE_MODIFIERS:
        if _normalize_force_modifier_key(mod[0]) == wanted:
            return mod
    return None


def _mission_force_modifiers(mission: dict, intel_leads: Optional[List[Dict]] = None) -> List[str]:
    """Return force modifier keys explicitly marked as applied for this build."""
    raw_values: List[Any] = []
    for field in (
        "force_modifiers",
        "modifiers_applied",
        "completed_intel_modifiers",
        "defense_modifiers",
    ):
        value = mission.get(field)
        if isinstance(value, str):
            raw_values.extend(part.strip() for part in re.split(r"[,;\n]", value) if part.strip())
        elif isinstance(value, (list, tuple, set)):
            raw_values.extend(value)

    for lead in intel_leads or []:
        if lead.get("applied") or lead.get("completed") or lead.get("success") or lead.get("default_applied"):
            raw_values.append(lead.get("modifier"))

    seen: set[str] = set()
    applied: List[str] = []
    for value in raw_values:
        entry = _force_modifier_entry(str(value))
        if not entry:
            continue
        norm = _normalize_force_modifier_key(entry[0])
        if norm in seen:
            continue
        seen.add(norm)
        applied.append(entry[0])
    return applied


def _force_modifier_totals(modifiers_applied: List[str]) -> Dict[str, Any]:
    grunt_delta = 0
    lt_delta = 0
    morale_delta = 0
    commander_notes: List[str] = []
    applied: List[str] = []
    seen: set[str] = set()

    for mod_key in modifiers_applied:
        mod = _force_modifier_entry(mod_key)
        if not mod:
            logger.warning(f"[DEFENSE] Unknown force modifier ignored: {mod_key!r}")
            continue
        norm = _normalize_force_modifier_key(mod[0])
        if norm in seen:
            continue
        seen.add(norm)
        applied.append(mod[0])
        grunt_delta += int(mod[2] or 0)
        lt_delta += int(mod[3] or 0)
        morale_delta += int(mod[4] or 0)
        if mod[5]:
            commander_notes.append(str(mod[5]))

    return {
        "applied": applied,
        "grunt_delta": grunt_delta,
        "lt_delta": lt_delta,
        "morale_delta": morale_delta,
        "commander_notes": commander_notes,
    }


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

async def _ollama(prompt: str, system: str = "") -> str:
    """Call Ollama via the shared queue with up to 10 retries and backoff."""
    from src.ollama_queue import call_ollama

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model":    OLLAMA_MODEL,
        "messages": messages,
        "stream":   False,
        "think":    False,
        "options":  {"temperature": 0.8, "num_predict": 1200},
    }

    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            data    = await call_ollama(payload, timeout=180.0, caller="defense", force=True)
            content = (data.get("message") or {}).get("content", "").strip()
            if content:
                return content
            logger.warning(f"[DEFENSE] Empty response (attempt {attempt}/{max_attempts})")
        except Exception as e:
            logger.warning(f"[DEFENSE] Ollama error attempt {attempt}/{max_attempts}: {e}")

        if attempt < max_attempts:
            wait = min(30 * attempt, 120)
            logger.info(f"[DEFENSE] Retrying in {wait}s…")
            await asyncio.sleep(wait)

    logger.error("[DEFENSE] All 10 attempts exhausted — returning empty string")
    return ""


def _clean_json(raw: str) -> str:
    raw = raw.replace("\x5c\x27", "\x27")
    raw = re.sub(r"[‘’]", "'", raw)
    raw = re.sub(r"[“”]", '"', raw)
    raw = re.sub(r"[–—]", "-", raw)
    cleaned, in_string, i = [], False, 0
    while i < len(raw):
        ch = raw[i]
        if ch == '"' and (i == 0 or raw[i-1] != "\\"):
            in_string = not in_string
            cleaned.append(ch)
        elif in_string and ord(ch) in (10, 13):
            cleaned.append(" ")
        else:
            cleaned.append(ch)
        i += 1
    return "".join(cleaned)


def _parse_json(raw: str) -> Optional[dict]:
    for attempt in (raw, _clean_json(raw)):
        m = re.search(r"\{[\s\S]*\}", attempt)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Generation steps
# ---------------------------------------------------------------------------

async def _generate_briefing(mission: dict, location: str, profile: Dict) -> Dict:
    title   = mission.get("title", "Unknown Defense")
    faction = mission.get("faction", "Independent")
    opposing = mission.get("opposing_faction") or "Unknown Threat"
    body    = mission.get("body") or mission.get("description") or ""

    prompt = f"""You are writing the opening briefing for a D&D defense mission module.

Mission: {title}
Defending faction: {faction}
Attacking faction/threat: {opposing}
Location to defend: {location}
Attacker profile: {profile['tactics']}
Mission notes: {body[:300]}

Write a briefing as if the faction contact is speaking to the party. Include:
- What is at stake (why this location matters)
- What is known about the threat
- That the attack could come at any time — could be days, could be tonight
- 1-2 specific things the party can do to prepare

Return JSON only:
{{
  "contact_speech": "2-3 paragraphs of the contact briefing the party",
  "location_desc": "1 sentence describing the defensive position",
  "threat_summary": "1 sentence on the expected attackers",
  "prep_window": "how long they likely have (vague — hours to days)"
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    if not data:
        data = {
            "contact_speech": f"We need you to hold {location}. The {opposing} are moving on us — could be tonight, could be three days from now. Use the time.",
            "location_desc":  f"A defensible position at {location}.",
            "threat_summary": f"The {opposing} are coming in force.",
            "prep_window":    "Hours to days — unknown.",
        }
    return data


async def _generate_defenses(mission: dict, location: str, faction: str) -> Dict:
    prompt = f"""You are designing the defensive features of a location for a D&D siege module.

Location: {location}
Defending faction: {faction}

Generate:
1. Three features already present at the location (gates, walls, chokepoints, guard posts, etc.)
2. Five available upgrades the party can build or set up during prep time. Each upgrade should:
   - Have a short name
   - Say what it does mechanically (flat, specific — e.g. "attackers using this route arrive in groups of 2 not 4")
   - Cost (time in minutes of prep, or a skill check DC)

Return JSON only:
{{
  "existing_features": ["feature 1", "feature 2", "feature 3"],
  "upgrades": [
    {{"name": "...", "effect": "...", "cost": "..."}},
    {{"name": "...", "effect": "...", "cost": "..."}},
    {{"name": "...", "effect": "...", "cost": "..."}},
    {{"name": "...", "effect": "...", "cost": "..."}},
    {{"name": "...", "effect": "...", "cost": "..."}}
  ]
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    if not data:
        data = {
            "existing_features": ["Main gate with heavy doors", "Guard post with sightlines", "Narrow approach alley"],
            "upgrades": [
                {"name": "Barricade side alley",    "effect": "Attackers via side route arrive in groups of 2 not 4", "cost": "20 min prep"},
                {"name": "Oil channel",             "effect": "Once per wave — area becomes difficult terrain, 2d6 fire damage", "cost": "DC 14 Athletics"},
                {"name": "Arrow slits reinforced",  "effect": "+2 AC to defenders firing from the guard post", "cost": "30 min prep"},
                {"name": "Razor wire approach",     "effect": "Grunts crossing the front lose 5 ft speed and take 1d4 on entry", "cost": "15 min prep"},
                {"name": "Signal horn cached",      "effect": "Once — rally action grants +2 to all defender saves for 1 round", "cost": "10 min prep"},
            ],
        }
    return data


async def _generate_watch_events(location: str, opposing: str) -> List[Dict]:
    prompt = f"""Generate 8 watch events for a D&D defense mission.
Location being defended: {location}
Enemy force: {opposing}

Each event is something that happens during a watch rotation between attacks.
Mix of: enemy probing, civilian complications, internal defender issues, environmental.

Return JSON only:
{{
  "events": [
    {{"title": "...", "description": "1-2 sentences of what happens", "outcome": "mechanical effect or choice for the party"}},
    ...8 total...
  ]
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    events = (data or {}).get("events", [])
    if len(events) < 4:
        events = [
            {"title": "Scout spotted",         "description": "A lone figure watches from the roofline opposite, then vanishes.", "outcome": "DC 14 Perception to spot. If missed, attacker gains +2 grunts next wave."},
            {"title": "Civilian at the gate",  "description": "A family arrives begging to be let inside the perimeter.", "outcome": "Party decision — letting them in costs 1 food resource but may boost defender morale."},
            {"title": "Strange noise",         "description": "Scraping from below the floor — something moving under the building.", "outcome": "DC 13 Investigation to identify. May be nothing, may be tunnel advance."},
            {"title": "Messenger intercepted", "description": "A runner from the enemy is caught slipping through a side alley.", "outcome": "Successful capture: apply 'intercepted messenger' force modifier."},
        ]
    return events[:8]


async def _generate_intel_leads(location: str, opposing: str, profile: Dict) -> List[Dict]:
    prompt = f"""Generate 3 intel leads for a D&D defense mission.
Defenders are at: {location}
Enemy: {opposing} — {profile['tactics']}

Each lead is an action the party can take during downtime to gather information.
Intel gathered applies force modifiers to incoming waves.

Return JSON only:
{{
  "leads": [
    {{"name": "...", "action": "what the party does", "check": "skill and DC", "modifier": "which force modifier this unlocks if successful"}},
    ...3 total...
  ]
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    leads = (data or {}).get("leads", [])
    if len(leads) < 3:
        leads = [
            {"name": "Capture a scout",        "action": "Ambush an enemy scout outside the perimeter", "check": "DC 14 Stealth then DC 13 Athletics", "modifier": "intel — captured scout"},
            {"name": "Vantage point survey",   "action": "Reach a high point to observe enemy staging", "check": "DC 12 Stealth, DC 14 Perception",       "modifier": "intel — vantage point"},
            {"name": "Local contact",          "action": "Track down someone who knows the attacking group", "check": "DC 13 Investigation, DC 12 Persuasion", "modifier": "intel — local contact"},
        ]
    return leads[:3]


async def _generate_waves(
    mission: dict,
    profile: Dict,
    army: Dict,
    tier_data: Dict,
    modifiers_applied: List[str],
) -> List[Dict]:
    faction   = mission.get("faction", "Independent")
    opposing  = mission.get("opposing_faction") or "Unknown Threat"
    wave_count = tier_data["wave_count"]
    grunt_bonus = tier_data["grunt_bonus"]

    raw_base_grunts = random.randint(*army["wave_size"]) + grunt_bonus
    raw_base_lts    = random.randint(*army["lt_count"])
    modifier_totals = _force_modifier_totals(modifiers_applied)
    base_grunts = max(1, raw_base_grunts + modifier_totals["grunt_delta"])
    base_lts    = max(0, raw_base_lts + modifier_totals["lt_delta"])
    commander_notes = modifier_totals["commander_notes"]
    applied_modifiers = modifier_totals["applied"]
    modifier_summary = "None"
    if applied_modifiers:
        modifier_summary = (
            f"{', '.join(applied_modifiers)} "
            f"(grunts {modifier_totals['grunt_delta']:+d}, "
            f"lieutenants {modifier_totals['lt_delta']:+d}, "
            f"attacker morale {modifier_totals['morale_delta']:+d})"
        )

    prompt = f"""Write {wave_count} attack waves for a D&D defense mission module.

Attacker: {opposing} — {profile['tactics']}
Army type: {army['label']} — {army['description']}
Grunt type: {army['grunt_label']} (CR {army['grunt_cr']})
Lieutenant type: {army['lt_label']} (CR {army['lt_cr']})
Commander: {profile['commander']}
Base wave size: {base_grunts} grunts, {base_lts} lieutenants (after force modifiers)
Applied force modifiers: {modifier_summary}
Wave count: {wave_count}

Wave structure:
- Wave 1: Probe — smaller, testing defenses. Maybe {max(2,base_grunts//2)} grunts, 0-1 lieutenants. No commander.
- Wave 2: Main push — full force. All grunts and lieutenants.
{"- Wave 3: Commander's charge — remaining force + commander leads personally." if wave_count >= 3 else ""}
{"- Wave 4: Desperate final assault — everything left, commander exposed." if wave_count >= 4 else ""}

For each wave write:
- Composition (exact numbers)
- Tactics used this wave (2 sentences)
- What happens if the wave is repelled (do they retreat, regroup, change approach)
- Between-wave window: 5-15 minutes, what the enemy is visibly doing

Return JSON only:
{{
  "waves": [
    {{
      "number": 1,
      "label": "The Probe",
      "grunts": 0,
      "lieutenants": 0,
      "commander_present": false,
      "tactics": "...",
      "repelled_result": "...",
      "between_wave": "..."
    }}
  ]
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    waves = (data or {}).get("waves", [])
    if not waves:
        waves = [
            {"number": 1, "label": "The Probe",       "grunts": max(2, base_grunts//2), "lieutenants": 0, "commander_present": False, "tactics": "Testing the perimeter, probing for weak points.", "repelled_result": "Pull back 200 yards, regroup for 10 minutes.", "between_wave": "The enemy can be seen binding wounds and conferring at the treeline."},
            {"number": 2, "label": "The Main Push",   "grunts": base_grunts,             "lieutenants": base_lts, "commander_present": False, "tactics": "Full assault, lieutenants directing grunt squads at chokepoints.", "repelled_result": "Withdraw, shift approach for next wave.", "between_wave": "Shouted orders. They are reorganising. 8-10 minutes."},
            {"number": 3, "label": "Commander's Charge", "grunts": max(2, base_grunts//2), "lieutenants": base_lts, "commander_present": True, "tactics": "Commander leads personally. No more probing — this is the final push.", "repelled_result": "Commander withdraws. Enemy morale collapses. Siege over.", "between_wave": ""},
        ][:wave_count]

    # Stamp modifier metadata for renderers, Mimir notes, and future smoke checks.
    for wave in waves:
        wave["applied_force_modifiers"] = applied_modifiers
        wave["force_modifier_grunt_delta"] = modifier_totals["grunt_delta"]
        wave["force_modifier_lieutenant_delta"] = modifier_totals["lt_delta"]
        wave["force_modifier_morale_delta"] = modifier_totals["morale_delta"]
    if commander_notes and waves:
        waves[0]["commander_notes"] = " / ".join(commander_notes)

    return waves


def _defense_enemy_type(army: Dict, profile: Dict) -> str:
    """Infer a Mimir/DDB creature type for this defense army profile."""
    text = f"{army.get('label', '')} {army.get('description', '')} {profile.get('tactics', '')}".lower()
    if any(word in text for word in ("cult", "acolyte", "fanatic")):
        return "humanoid"
    if any(word in text for word in ("construct", "machine", "arcane")):
        return "construct"
    if any(word in text for word in ("undead", "dead", "returned")):
        return "undead"
    return "humanoid"


def _defense_mimir_enemies(waves: List[Dict], army: Dict, profile: Dict) -> List[Dict]:
    """Build defense-specific Mimir enemy entries from generated wave data."""
    creature_type = _defense_enemy_type(army, profile)
    enemies: dict[tuple[str, str], Dict] = {}

    def add_enemy(name: str, cr: str, count: int, note: str) -> None:
        if count <= 0:
            return
        key = (name.lower(), str(cr))
        if key not in enemies:
            enemies[key] = {
                "name": name,
                "cr": str(cr),
                "count": 0,
                "notes": "",
                "creature_type": creature_type,
            }
        enemies[key]["count"] += count
        enemies[key]["notes"] = f"{enemies[key]['notes']}\n{note}".strip()

    for wave in waves:
        wave_label = wave.get("label") or f"Wave {wave.get('number', '?')}"
        note = (
            f"Wave {wave.get('number', '?')}: {wave_label}. "
            f"{wave.get('tactics', '')} {wave.get('repelled_result', '')}"
        ).strip()
        add_enemy(str(army.get("grunt_label") or "attack grunts"), str(army.get("grunt_cr") or "1/4"), int(wave.get("grunts") or 0), note)
        add_enemy(str(army.get("lt_label") or "attack lieutenants"), str(army.get("lt_cr") or "1"), int(wave.get("lieutenants") or 0), note)
        if wave.get("commander_present"):
            add_enemy(
                str(profile.get("commander") or "enemy commander"),
                str(army.get("commander_cr") or army.get("lt_cr") or "2"),
                1,
                f"Commander present in {wave_label}. {profile.get('tactics', '')}",
            )

    return list(enemies.values())


async def _generate_debrief(
    mission: dict,
    waves_survived: int,
    total_waves: int,
    morale_remaining: int,
    location: str,
) -> str:
    faction  = mission.get("faction", "Independent")
    title    = mission.get("title", "the defense")
    quality  = "excellent" if morale_remaining > 10 else ("adequate" if morale_remaining > 0 else "costly")

    prompt = f"""Write a short after-action debrief for a D&D defense mission.

Mission: {title}
Defending faction: {faction}
Location defended: {location}
Waves survived: {waves_survived} of {total_waves}
Attacker morale remaining when they withdrew: {morale_remaining}
Result quality: {quality}

Write 2-3 sentences from the faction contact after the battle. Tone should match {quality} performance.
No JSON — just the speech text."""

    text = await _ollama(prompt)
    if not text:
        text = f"You held {location}. That's what matters. The {faction} won't forget it."
    return text


# ---------------------------------------------------------------------------
# A1111 map
# ---------------------------------------------------------------------------

async def _check_a1111() -> bool:
    for attempt in range(1, 11):
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{A1111_URL}/sdapi/v1/progress")
                if r.status_code == 200:
                    return True
        except Exception:
            pass
        if attempt < 10:
            logger.info(f"[DEFENSE] A1111 not ready (attempt {attempt}/10) — waiting 30s…")
            await asyncio.sleep(30)
    logger.warning("[DEFENSE] A1111 unavailable after 10 attempts")
    return False


_LOCATION_MAP_STYLE: Dict[str, str] = {
    # Outdoor / street
    "gate":          "Town Exterior Table Map, fortified gatehouse, portcullis visible, flanking guard towers, cobblestone approach road",
    "outpost":       "Town Exterior Table Map, fortified outpost building, guard post at corners, open approach with chokepoint alley",
    "checkpoint":    "Town Exterior Table Map, enforcement checkpoint across road, bollards, inspection lanes, guard posts flanking",
    "street":        "Town Exterior Table Map, wide road with buildings flanking, alley side routes, market stall cover, lamp posts",
    "plaza":         "Town Exterior Table Map, open central space, radiating approach paths, monument at center, perimeter buildings",
    "dock":          "Town Exterior Table Map, canal edge, moored boats, warehouse loading bays, narrow gangway chokepoints, water on one side",
    "alley":         "Town Exterior Table Map, narrow winding passage, dumpster cover, fire escapes, dead-end alcoves, single entry",
    "market":        "Town Exterior Table Map, dense stall rows, narrow lanes between vendors, open central square, supply crates as cover",
    # Interior
    "vault":         "Interior Table Map, heavy vault door at entry, narrow access corridor, security alcoves, reinforced walls",
    "safehouse":     "Interior Table Map, cramped rooms, multiple entry points, hidden trapdoor, barricaded windows",
    "kitchen":       "Interior Table Map, open cooking area, multiple exits, supply storage, counter cover positions",
    "hall":          "Interior Table Map, large open hall, support columns for cover, multiple doorways to control",
    "sanctum":       "Interior Table Map, ritual chamber layout, tiered floor sections, arcane apparatus, single narrow entry",
    "archive":       "Interior Table Map, tall shelving rows, narrow reading aisles, single main entrance, archive alcoves",
    "annex":         "Interior Table Map, connected rooms, corridor chokepoints, locked side rooms, reinforced entry",
    "relay":         "Interior Table Map, central arcane apparatus, control stations, tight corridors, one main access point",
    "depot":         "Interior Table Map, large storage crates as cover, loading dock entry, support columns, staging area",
    "billet":        "Interior Table Map, bunk room layout, weapon racks, single corridor entry, mess area",
}

def _location_map_style(location: str) -> str:
    loc_low = location.lower()
    for key, style in _LOCATION_MAP_STYLE.items():
        if key in loc_low:
            return style
    # Default — outdoor street scene
    return "Town Exterior Table Map, urban approach road, buildings flanking, alley side routes, clear chokepoint at center"


async def _generate_defense_map(
    location: str,
    faction: str,
    defenses: Dict,
    out_dir: Path,
) -> Optional[Path]:
    """One highly-defensible tactical map informed by the actual location and generated defenses."""
    out = out_dir / "defense_map.png"
    import re
    # Location-specific map base
    map_style = _location_map_style(location)
    # Strip SD1.5 LoRA prefix tokens (meaningless to Flux)
    map_style = re.sub(r'(?:Big |Small )?(?:[\w]+ )*?Table Map[, ]+', '', map_style, count=1, flags=re.IGNORECASE).strip(', ')
    is_dungeon = "dungeon" in map_style.lower()
    lora_name = os.getenv("A1111_MAP_LORA_DUNGEON" if is_dungeon else "A1111_MAP_LORA_TOWN",
                           "EnvyFluxDungeonMap01" if is_dungeon else "EnvyFluxFantasyTownMap01")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    triggers = os.getenv("A1111_MAP_DUNGEON_TRIGGERS" if is_dungeon else "A1111_MAP_TOWN_TRIGGERS",
                          "detailed, map, dungeon" if is_dungeon else "detailed, map, village")

    # Faction visual tint
    faction_tint = {
        "Wardens of Ash":   "grey stone walls, ash sigil markings on posts, utilitarian military fortification",
        "Tower Authority":  "official enforcement colours, regulation signage, structured checkpoint aesthetic",
        "Patchwork Saints": "improvised mismatched barricades, community painted symbols, salvaged materials",
        "Wizards Tower":    "arcane ward glyphs on walls, magical barrier nodes, glowing runic reinforcements",
        "Argent Blades":    "mercenary banner colours, professional barricade lines, weapon rack visible",
        "Iron Fang Consortium": "industrial reinforcement, iron-braced doors, consortium markings",
        "Obsidian Lotus":   "subtle concealed entry points, shadow-friendly recesses, minimal signage",
        "Glass Sigil":      "elegant facade, wealth-district materials, hidden reinforcements behind decor",
        "Serpent Choir":    "cult symbols etched into barriers, ritual markings at entry points",
        "Patchwork Saints": "community-built defenses, mismatched but sturdy, people's fortress aesthetic",
    }.get(faction, "neutral stone and timber fortification")

    # Pull existing features from the generated defenses
    features = defenses.get("existing_features", [])
    feature_tokens = ", ".join(f[:50] for f in features[:3])

    # Pull upgrade names as visual elements that may be visible on the map
    upgrades = defenses.get("upgrades", [])
    upgrade_tokens = ", ".join(
        u.get("name", "")[:40] for u in upgrades[:4] if u.get("name")
    )

    positive = ", ".join(filter(None, [
        f"<lora:{lora_name}:{lora_weight}>",
        triggers,
        map_style,
        "highly defensible tactical position",
        feature_tokens,
        upgrade_tokens,
        "barricade positions, channeling chokepoints, arrow slit positions, flanking guard posts",
        faction_tint,
        "high fantasy cyberpunk fusion, wealth-stratified technology",
    ]))

    negative = "characters, people, isometric, perspective, watermark, text"

    payload = {
        "prompt":          positive,
        "negative_prompt": negative,
        "width":           1024,
        "height":          1024,
        "steps":           20,
        "cfg_scale":       1.0,
        "sampler_name":    "Euler",
        "seed":            -1,
    }

    _map_ckpt = os.getenv("A1111_MAP_CHECKPOINT", "")
    if _map_ckpt:
        override: dict = {"sd_model_checkpoint": _map_ckpt}
        payload["override_settings"] = override
        payload["override_settings_restore_afterwards"] = True
    max_map_attempts = 10
    for map_attempt in range(1, max_map_attempts + 1):
        try:
            from src.news_feed import a1111_lock
            from src.resource_cop import wait_for_a1111_turn
            decision = await wait_for_a1111_turn("defense_map", max_wait_seconds=60)
            if not decision.run_now:
                logger.info(f"[DEFENSE] A1111 deferred by resource cop: {decision.reason}")
                from src.mission_builder.vtt_renderer import save_vtt_battlemap
                save_vtt_battlemap(out, None, context={"title": location, "location": location, "prompt": positive, "kind": "defense fort checkpoint"})
                return out
            async with a1111_lock:
                async with httpx.AsyncClient(timeout=600.0) as c:
                    r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                    r.raise_for_status()
                    images = r.json().get("images", [])
            if not images:
                raise RuntimeError("A1111 returned no images")
            from src.mission_builder.vtt_renderer import save_vtt_battlemap
            save_vtt_battlemap(out, images[0], context={"title": location, "location": location, "prompt": positive, "kind": "defense fort checkpoint"})
            logger.info(f"[DEFENSE] Map saved: {out.name}")
            return out
        except Exception as e:
            logger.warning(f"[DEFENSE] Map attempt {map_attempt}/{max_map_attempts} failed: {e}")
            if map_attempt < max_map_attempts:
                wait = min(30 * map_attempt, 120)
                logger.info(f"[DEFENSE] Retrying map in {wait}s…")
                await asyncio.sleep(wait)

    # All attempts exhausted — fall back to deterministic
    logger.error("[DEFENSE] Map generation failed after 10 attempts — using deterministic fallback")
    from src.mission_builder.vtt_renderer import save_vtt_battlemap
    save_vtt_battlemap(out, None, context={"title": location, "location": location, "prompt": positive, "kind": "defense fort checkpoint"})
    logger.info(f"[DEFENSE] Deterministic VTT map saved: {out.name}")
    return out


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

def _morale_checkboxes(pool: int, label: str, color: str = "#c85320") -> str:
    boxes = "".join(
        f'<input type="checkbox" style="width:18px;height:18px;margin:2px;accent-color:{color};">'
        for _ in range(pool)
    )
    return (
        f'<div style="margin:12px 0;">'
        f'<div style="font-weight:bold;font-size:13px;margin-bottom:4px;">{label} — {pool} points</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:2px;">{boxes}</div>'
        f'</div>'
    )


def _upgrade_card(u: Dict, idx: int) -> str:
    return (
        f'<div style="border:1px solid #b8923a;border-radius:6px;padding:10px 14px;margin:6px 0;background:#fffdf5;">'
        f'<input type="checkbox" id="upg{idx}" style="margin-right:8px;accent-color:#b8923a;">'
        f'<label for="upg{idx}" style="font-weight:bold;">{_e(u.get("name",""))}</label>'
        f'<div style="margin-top:4px;color:#444;font-size:13px;">{_e(u.get("effect",""))}</div>'
        f'<div style="margin-top:2px;color:#888;font-size:12px;">Cost: {_e(u.get("cost",""))}</div>'
        f'</div>'
    )


def _wave_card(w: Dict, army: Dict, faction_color: str) -> str:
    commander_badge = (
        f'<span style="background:#7b1e1e;color:white;padding:2px 8px;border-radius:4px;font-size:12px;margin-left:8px;">COMMANDER PRESENT</span>'
        if w.get("commander_present") else ""
    )
    grunt_boxes = "".join(
        f'<input type="checkbox" style="width:16px;height:16px;margin:2px;accent-color:#555;">'
        for _ in range(int(w.get("grunts", 0)))
    )
    lt_boxes = "".join(
        f'<input type="checkbox" style="width:16px;height:16px;margin:2px;accent-color:#3a6898;">'
        for _ in range(int(w.get("lieutenants", 0)))
    )
    between = w.get("between_wave", "")
    notes   = w.get("commander_notes", "")
    return (
        f'<div style="border-left:4px solid {faction_color};padding:14px 18px;margin:16px 0;background:#fafafa;border-radius:0 8px 8px 0;">'
        f'<h3 style="margin:0 0 8px;font-size:16px;">Wave {w.get("number","?")} — {_e(w.get("label",""))}{commander_badge}</h3>'
        f'<div style="display:flex;gap:32px;flex-wrap:wrap;margin:8px 0;">'
        f'<div><div style="font-size:12px;color:#666;margin-bottom:4px;">GRUNTS ({w.get("grunts",0)})</div><div style="display:flex;flex-wrap:wrap;">{grunt_boxes}</div></div>'
        f'<div><div style="font-size:12px;color:#666;margin-bottom:4px;">LIEUTENANTS ({w.get("lieutenants",0)})</div><div style="display:flex;flex-wrap:wrap;">{lt_boxes}</div></div>'
        f'</div>'
        f'<div style="margin:8px 0;font-size:14px;"><strong>Tactics:</strong> {_e(w.get("tactics",""))}</div>'
        f'<div style="margin:4px 0;font-size:13px;color:#555;"><strong>If repelled:</strong> {_e(w.get("repelled_result",""))}</div>'
        + (f'<div style="margin:8px 0;padding:8px;background:#fff8e6;border-radius:4px;font-size:13px;"><strong>Between-wave ({between}):</strong> {_e(between)}</div>' if between else "")
        + (f'<div style="margin:8px 0;font-size:13px;color:#7b1e1e;"><strong>Intel note:</strong> {_e(notes)}</div>' if notes else "")
        + f'</div>'
    )


def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _watch_event_table(events: List[Dict]) -> str:
    rows = ""
    for i, ev in enumerate(events, 1):
        rows += (
            f'<tr><td style="width:30px;text-align:center;font-weight:bold;">{i}</td>'
            f'<td style="font-weight:bold;">{_e(ev.get("title",""))}</td>'
            f'<td>{_e(ev.get("description",""))}</td>'
            f'<td style="color:#555;font-size:12px;">{_e(ev.get("outcome",""))}</td></tr>'
        )
    return (
        f'<h2>Watch Event Table (d8)</h2>'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        f'<thead><tr style="background:#e8e0d0;">'
        f'<th style="padding:6px;">d8</th><th style="padding:6px;">Event</th>'
        f'<th style="padding:6px;">Description</th><th style="padding:6px;">Outcome</th>'
        f'</tr></thead><tbody>'
        + rows +
        f'</tbody></table>'
    )


def _intel_lead_cards(leads: List[Dict]) -> str:
    cards = ""
    for lead in leads:
        mod = lead.get("modifier", "")
        mod_entry = _force_modifier_entry(mod)
        effect_str = ""
        if mod_entry:
            parts = []
            if mod_entry[2]: parts.append(f"{mod_entry[2]:+d} grunts")
            if mod_entry[3]: parts.append(f"{mod_entry[3]:+d} lieutenants")
            if mod_entry[4]: parts.append(f"{mod_entry[4]:+d} attacker morale")
            if mod_entry[5]: parts.append(mod_entry[5])
            effect_str = ", ".join(parts)

        cards += (
            f'<div style="border:1px solid #3a6898;border-radius:6px;padding:10px 14px;margin:6px 0;background:#f0f5ff;">'
            f'<input type="checkbox" style="margin-right:8px;accent-color:#3a6898;">'
            f'<strong>{_e(lead.get("name",""))}</strong>'
            f'<div style="margin-top:4px;font-size:13px;">{_e(lead.get("action",""))}</div>'
            f'<div style="margin-top:2px;font-size:12px;color:#555;">Check: {_e(lead.get("check",""))}</div>'
            + (f'<div style="margin-top:4px;font-size:12px;color:#3a6898;font-weight:bold;">If successful: {_e(effect_str)}</div>' if effect_str else "")
            + f'</div>'
        )
    return cards


def render_defense_module(
    mission: dict,
    location: str,
    profile: Dict,
    army: Dict,
    briefing: Dict,
    defenses: Dict,
    watch_events: List[Dict],
    intel_leads: List[Dict],
    waves: List[Dict],
    morale_pool: int,
    strength: Dict[str, Any],
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title   = mission.get("title", "Defense")
    faction = mission.get("faction", "Independent")
    opposing = mission.get("opposing_faction") or "Unknown Threat"
    fc      = _faction_color(faction)

    map_html = ""
    if map_path and map_path.exists():
        rel = map_path.relative_to(out_dir)
        map_html = (
            f'<div style="text-align:center;margin:20px 0;">'
            f'<img src="{rel}" style="max-width:100%;border:3px solid {fc};border-radius:8px;" alt="Defense Map">'
            f'<div style="font-size:12px;color:#888;margin-top:4px;">Tactical map — {_e(location)}</div>'
            f'</div>'
        )

    # Upgrade cards
    upgrade_html = "".join(_upgrade_card(u, i) for i, u in enumerate(defenses.get("upgrades", [])))

    # Existing features
    features_html = "".join(
        f'<li>{_e(f)}</li>' for f in defenses.get("existing_features", [])
    )

    # Wave cards
    wave_html = "".join(_wave_card(w, army, fc) for w in waves)

    # Intel leads
    intel_html = _intel_lead_cards(intel_leads)

    # Watch event table
    watch_html = _watch_event_table(watch_events)

    # Morale track
    morale_html = _morale_checkboxes(morale_pool, f"{opposing} Morale", "#c85320")
    scaling_html = (
        f'<div style="background:#eef6ff;border:1px solid #3a6898;border-radius:6px;'
        f'padding:10px 14px;margin:14px 0;font-size:13px;">'
        f'<strong>Live Party Scaling:</strong> {_e(_party_scaling_note(strength))} '
        f'Attacker morale and wave pressure are tuned from this read.</div>'
    )

    body = f"""
<div style="border-left:4px solid {fc};padding:12px 18px;margin:20px 0;background:#fafafa;border-radius:0 8px 8px 0;">
  <h2 style="margin:0 0 4px;">Mission Briefing</h2>
  <div style="font-style:italic;color:#444;white-space:pre-line;">{_e(briefing.get("contact_speech",""))}</div>
  <div style="margin-top:12px;font-size:13px;">
    <strong>Location:</strong> {_e(briefing.get("location_desc",""))}<br>
    <strong>Threat:</strong> {_e(briefing.get("threat_summary",""))}<br>
    <strong>Prep window:</strong> {_e(briefing.get("prep_window",""))}
  </div>
</div>

{scaling_html}

{map_html}

<h2>Defensive Position — {_e(location)}</h2>
<h3>Existing Features</h3>
<ul style="font-size:14px;">{features_html}</ul>

<h3>Available Upgrades</h3>
<div style="font-size:12px;color:#666;margin-bottom:8px;">Check off each upgrade as the party completes it during prep time.</div>
{upgrade_html}

<hr>

<h2>Attacker Profile — {_e(opposing)}</h2>
<div style="display:flex;gap:24px;flex-wrap:wrap;margin:12px 0;">
  <div style="flex:1;min-width:200px;">
    <strong>Army type:</strong> {_e(army.get("label",""))}<br>
    <strong>Tactics:</strong> {_e(profile.get("tactics",""))}<br>
    <strong>Commander:</strong> {_e(profile.get("commander",""))}
  </div>
  <div style="flex:1;min-width:200px;">
    {morale_html}
  </div>
</div>

<hr>

<h2>Intel Leads</h2>
<div style="font-size:12px;color:#666;margin-bottom:8px;">Each completed lead applies a force modifier to the wave composition.</div>
{intel_html}

<hr>

<h2>The Assault — Wave Breakdown</h2>
{wave_html}

<hr>

{watch_html}

<hr>

<h2>Debrief</h2>
<div style="background:#e8f5e8;border:1px solid #2a6a2a;border-radius:6px;padding:14px 18px;font-style:italic;">
  <em>(Generated after the session — record outcome below)</em><br><br>
  <strong>Waves survived:</strong> <input type="number" style="width:50px;"> / {len(waves)}<br>
  <strong>Attacker morale when withdrawn:</strong> <input type="number" style="width:50px;"><br>
  <strong>Upgrades completed:</strong> <input type="number" style="width:50px;"> / {len(defenses.get("upgrades",[]))}<br>
  <strong>Intel gathered:</strong> <input type="number" style="width:50px;"> / {len(intel_leads)}<br><br>
  <textarea rows="4" style="width:100%;font-family:inherit;" placeholder="After-action notes..."></textarea>
</div>
"""

    return _page(title, body, faction)


def render_defense_session(
    mission: dict,
    location: str,
    profile: Dict,
    army: Dict,
    briefing: Dict,
    defenses: Dict,
    waves: List[Dict],
    morale_pool: int,
    intel_leads: List[Dict],
    watch_events: List[Dict],
) -> str:
    """Simple linear session runner — briefing card → wave cards → debrief."""
    title   = mission.get("title", "Defense")
    faction = mission.get("faction", "Independent")
    opposing = mission.get("opposing_faction") or "Unknown Threat"
    fc      = _faction_color(faction)

    def _card(heading: str, content: str, color: str = "#b8923a") -> str:
        return (
            f'<div style="border:2px solid {color};border-radius:10px;padding:18px 22px;'
            f'margin:20px 0;background:white;page-break-inside:avoid;">'
            f'<h2 style="margin:0 0 12px;color:{color};">{heading}</h2>'
            f'{content}'
            f'</div>'
        )

    cards = ""

    # Briefing card
    cards += _card(
        f"Scene 1 — Briefing at {_e(location)}",
        f'<p style="font-style:italic;">{_e(briefing.get("contact_speech","")[:500])}</p>'
        f'<p><strong>Prep window:</strong> {_e(briefing.get("prep_window",""))}</p>'
        f'<p><strong>Available upgrades:</strong> {", ".join(_e(u.get("name","")) for u in defenses.get("upgrades",[]))}</p>',
        fc,
    )

    # Wave cards
    for w in waves:
        grunt_boxes = "".join(
            f'<input type="checkbox" style="width:18px;height:18px;margin:2px;accent-color:#555;">'
            for _ in range(int(w.get("grunts", 0)))
        )
        lt_boxes = "".join(
            f'<input type="checkbox" style="width:18px;height:18px;margin:2px;accent-color:#3a6898;">'
            for _ in range(int(w.get("lieutenants", 0)))
        )
        between = w.get("between_wave", "")
        content = (
            f'<div style="margin:8px 0;"><strong>Grunts ({w.get("grunts",0)}):</strong><br>{grunt_boxes}</div>'
            f'<div style="margin:8px 0;"><strong>Lieutenants ({w.get("lieutenants",0)}):</strong><br>{lt_boxes}</div>'
            + (f'<div style="margin:8px 0;font-size:13px;color:#7b1e1e;font-weight:bold;">⚔ COMMANDER PRESENT</div>' if w.get("commander_present") else "")
            + f'<div style="margin:8px 0;"><strong>Tactics:</strong> {_e(w.get("tactics",""))}</div>'
            + _morale_checkboxes(morale_pool, f"{opposing} Morale", "#c85320")
            + (f'<div style="margin-top:12px;padding:8px;background:#fff8e6;border-radius:4px;font-size:13px;"><strong>Between waves (~{between}):</strong> {_e(between)}</div>' if between else "")
        )
        cards += _card(f"Wave {w.get('number','?')} — {_e(w.get('label',''))}", content, "#7b1e1e")

        # Between-wave action card
        if between and w.get("number", 0) < len(waves):
            between_content = (
                f'<p style="font-size:13px;">The enemy regroups. You have approximately {_e(between)} before the next wave.</p>'
                f'<p><strong>Available actions:</strong></p>'
                f'<ul style="font-size:13px;">'
                f'<li><input type="checkbox"> Complete a remaining upgrade</li>'
                f'<li><input type="checkbox"> Administer first aid (expend a hit die)</li>'
                f'<li><input type="checkbox"> Rally defenders (Performance DC 12 — attacker morale -2)</li>'
                f'<li><input type="checkbox"> Roll a watch event (d8)</li>'
                f'</ul>'
            )
            cards += _card("Between Waves — Regroup Window", between_content, "#3a6898")

    # Debrief card
    cards += _card(
        "Debrief",
        f'<p><strong>Waves survived:</strong> <input type="number" style="width:50px;"> / {len(waves)}</p>'
        f'<p><strong>Morale remaining:</strong> <input type="number" style="width:50px;"></p>'
        f'<textarea rows="3" style="width:100%;font-family:inherit;" placeholder="After-action notes..."></textarea>',
        "#2a6a2a",
    )

    body = (
        f'<div style="text-align:center;margin:0 0 24px;">'
        f'<h1 style="color:{fc};">{_e(title)}</h1>'
        f'<div style="font-size:14px;color:#666;">{_e(faction)} — Defense of {_e(location)}</div>'
        f'</div>'
        + cards
    )
    return _page(title, body, faction)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


def _party_strength() -> Dict[str, Any]:
    """Read live PC snapshots; copied here so defense stays standalone."""
    pcs = []
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC"
        ) or []
        for row in rows:
            snap = row.get("snapshot_json") or {}
            if isinstance(snap, str):
                try:
                    snap = json.loads(snap)
                except Exception:
                    snap = {}
            if not isinstance(snap, dict):
                continue
            level = int(snap.get("total_level") or 0)
            if level <= 0:
                continue
            pcs.append({"name": snap.get("name") or row.get("char_name"), "level": level, "max_hp": int(snap.get("max_hp") or 0)})
    except Exception as e:
        logger.warning(f"[DEFENSE] Could not read live party snapshots: {e}")
    levels = [p["level"] for p in pcs] or [5]
    return {"party_size": len(pcs) or 4, "avg_level": round(sum(levels) / len(levels), 1), "max_level": max(levels), "pcs": pcs}


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    return f"Live party read: {strength['party_size']} PCs, average level {strength['avg_level']}, max level {strength['max_level']}."


async def build_defense_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    """Full defense pipeline. Returns path to index.html."""
    title    = mission.get("title", "Unknown Defense")
    faction  = mission.get("faction", "Independent")
    opposing = mission.get("opposing_faction") or "Unknown Threat"
    tier     = mission.get("tier", "standard")

    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[DEFENSE] Building: {title!r} | faction={faction} | opposing={opposing} | tier={tier}")

    profile    = _get_profile(opposing)
    army       = ARMY_TYPES[profile["army_style"]]
    tier_data  = _tier_scale(tier)
    location   = _pick_location(faction)
    strength   = _party_strength()

    # Morale pool = base * tier multiplier, rounded to int
    morale_pool = max(5, int(
        (profile["base_morale"] + max(0, strength["party_size"] - 4) * 2 + max(0, strength["max_level"] - 5) * 2)
        * tier_data["morale_mult"]
    ))

    logger.info(f"[DEFENSE] Army={army['label']} | morale={morale_pool} | waves={tier_data['wave_count']} | location={location}")

    # Generate content concurrently where possible
    briefing_task      = asyncio.create_task(_generate_briefing(mission, location, profile))
    defenses_task      = asyncio.create_task(_generate_defenses(mission, location, faction))
    watch_task         = asyncio.create_task(_generate_watch_events(location, opposing))
    intel_task         = asyncio.create_task(_generate_intel_leads(location, opposing, profile))

    briefing, defenses, watch_events, intel_leads = await asyncio.gather(
        briefing_task, defenses_task, watch_task, intel_task
    )

    # Waves need to know army/profile — run after
    applied_modifiers = _mission_force_modifiers(mission, intel_leads)
    modifier_totals = _force_modifier_totals(applied_modifiers)
    if applied_modifiers:
        morale_pool = max(1, morale_pool + modifier_totals["morale_delta"])
        logger.info(
            "[DEFENSE] Applied force modifiers: %s | grunts %+d | lieutenants %+d | morale %+d",
            ", ".join(applied_modifiers),
            modifier_totals["grunt_delta"],
            modifier_totals["lt_delta"],
            modifier_totals["morale_delta"],
        )
    waves = await _generate_waves(mission, profile, army, tier_data, applied_modifiers)

    # A1111 map — runs after defenses so the prompt includes actual features/upgrades
    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            map_path = await _generate_defense_map(location, faction, defenses, out_dir)
        else:
            logger.warning("[DEFENSE] A1111 not available — skipping map")

    # Mimir: create module + upload map + catalog-enriched wave enemies
    from src.mission_builder.mimir_module import create_module as _mc, enrich_monsters as _me, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="defense")
    _d_enemies = _defense_mimir_enemies(waves, army, profile)
    _enriched = await _me(_mimir_id or "", _d_enemies)
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Defense Map")

    # Direct DDB homebrew push — fires when Mimir is unavailable but DDB session is set.
    # enrich_monsters() exits early without pushing anything if Mimir is down, so we
    # push each enemy directly here as a fallback.
    if not _mimir_id:
        try:
            from src.ddb_homebrew import push_mission_enemy as _ddb_push, ENABLED as _ddb_en
            if _ddb_en:
                async def _push_all_direct():
                    for _e in _d_enemies:
                        if not _e.get("name"):
                            continue
                        _cr = str(_e.get("cr", "1"))
                        try:
                            _cr_num = float(_cr.replace("1/8", "0.125").replace("1/4", "0.25").replace("1/2", "0.5"))
                        except Exception:
                            _cr_num = 1.0
                        _prebuilt = {
                            "hp":            _e.get("hp") or max(1, int(_cr_num * 13 + 7)),
                            "ac":            _e.get("ac") or max(10, min(18, int(_cr_num + 12))),
                            "creature_type": _e.get("creature_type", "humanoid"),
                            "speed":         _e.get("speed", "30 ft."),
                        }
                        _atks = _e.get("attacks", [])
                        if _atks:
                            _prebuilt["actions"] = "\n\n".join(
                                f"**{a.split('.')[0]}.** {'.'.join(a.split('.')[1:]).strip()}"
                                if '.' in a else f"**Attack.** {a}"
                                for a in _atks[:4]
                            )
                        try:
                            await _ddb_push(_e, cr_val=_cr, statblock=_prebuilt)
                            logger.info(f"[DDB_HB] Direct push: {_e['name']!r} CR {_cr}")
                        except Exception as _de:
                            logger.warning(f"[DDB_HB] Direct push failed for {_e.get('name')!r}: {_de}")
                asyncio.create_task(_push_all_direct())
        except Exception as _dex:
            logger.warning(f"[DDB_HB] Could not start direct push task: {_dex}")

    # Module HTML
    module_html = render_defense_module(
        mission, location, profile, army, briefing, defenses,
        watch_events, intel_leads, waves, morale_pool, strength, map_path, out_dir,
    )
    module_html += _ms(_enriched, [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")

    # Session HTML
    session_html = render_defense_session(
        mission, location, profile, army, briefing, defenses,
        waves, morale_pool, intel_leads, watch_events,
    )
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    existing_features = [
        str(feature) for feature in defenses.get("existing_features", [])
    ]
    recommended_upgrades = [
        item.get("name", str(item)) if isinstance(item, dict) else str(item)
        for item in defenses.get("upgrades", [])
    ]
    dm_md = (
        f"## Defense DM Guide\n"
        f"### Situation\n{briefing.get('contact_speech', '')}\n\n"
        f"### Enemy Army\n"
        f"- Opposing faction: {opposing}\n"
        f"- Army profile: {army['label']} ({profile['army_style']})\n"
        f"- Morale pool: {morale_pool}\n"
        f"- Live scaling: {_party_scaling_note(strength)}\n\n"
        f"### Defender Position\n"
        f"- Location: {location}\n"
        f"- Existing features: {', '.join(existing_features)}\n"
        f"- Recommended upgrades: {', '.join(recommended_upgrades)}\n\n"
        f"### Wave Plan\n"
        + "\n".join(f"- Wave {i+1}: {w.get('label', 'Attack wave')} - {w.get('tactics', 'pressure the defense')}" for i, w in enumerate(waves))
        + "\n\n### DM Pacing\nRun prep, watch events, then waves. Let morale checks decide when the enemy breaks or redoubles."
    )
    players_md = (
        f"## Player Brief\n"
        f"### What You Know\n{briefing.get('contact_speech', '')}\n\n"
        f"### Defensive Site\n"
        f"- {location}\n"
        f"- Known useful features: {', '.join(existing_features)}\n"
        f"- You can prepare upgrades before the attack begins.\n\n"
        f"### Public Objective\nHold the location until the attacking force breaks, withdraws, or can no longer continue the assault."
    )
    chart_md = (
        f"## Defense Chart Pack\n"
        f"### Morale Track\nMorale pool: {morale_pool}. Mark morale as waves fail, leaders fall, defenders rally, or attackers suffer visible losses.\n\n"
        f"### Watch Events\n"
        + "\n".join(f"- {e.get('title', '')}: {e.get('description', '')}" for e in watch_events)
        + "\n\n### Intel Leads\n"
        + "\n".join(f"- {lead.get('label', lead.get('name', 'Lead'))}: {lead.get('action', lead.get('check', ''))}" for lead in intel_leads)
        + "\n\n### Waves\n"
        + "\n".join(f"| {i+1} | {w.get('label', '')} | {w.get('tactics', '')} |" for i, w in enumerate(waves))
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, faction, players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",       "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",            "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Morale & Wave Chart", "type": "custom",      "content": chart_md},
        ])
    maps_name = write_maps_page(out_dir, title, faction, [map_path] if map_path else [])
    box_components = component_links(has_maps=bool(maps_name))

    # Index HTML
    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title,
            faction=faction,
            tier=tier,
            cr=mission_cr(mission),
            player_name=mission.get("player_name", "") or "Open",
            chapters=[],
            components=box_components,
            chart_pack=None,
            map_count=1 if map_path else 0,
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as _e:
        logger.warning(f"[DEFENSE] index.html failed: {_e}")
        index_path = out_dir / "module.html"

    # DB slug
    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as _e:
        logger.warning(f"[DEFENSE] Could not write module_slug: {_e}")

    # Zip
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[DEFENSE] Complete: {title!r} → {out_dir.name}")
    return index_path
