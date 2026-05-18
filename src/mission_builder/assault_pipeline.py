"""
assault_pipeline.py — Pipeline for Assault mission modules.

The exact opposite of defense. The party leads a faction force against a fixed
position held by an enemy. One assault wave — the force either breaks the
defenders or breaks itself. The party manages their own troop morale while
fighting through chokepoints to reach the objective.

Win conditions (any one):
  - Reach and hold the objective
  - Break defender morale through losses
  - Kill or capture the commander

Flow:
  1. Briefing       — contact, target position, objective, friendly force
  2. Forces         — faction-appropriate attacker force + defender force with home advantage
  3. Commander      — archetype-driven (priest/warlord/fighter), abilities + surrender threshold
  4. Map            — single map: exterior approach + interior layout, defender positions visible to DM
  5. Assault        — one push: chokepoints, trickle defender reinforcements, troop morale track
  6. Debrief        — contact arrives at site, reacts by outcome + faction disposition, may offer stay bonus
  7. index.html + session.html + zip + DB slug

Exported:
    build_assault_module(mission: dict, out_dir: Path) -> Path
    is_assault_mission(mission_type: str) -> bool
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

_ASSAULT_KEYWORDS = {
    "assault", "attack", "storm", "breach", "raid", "take the", "seize",
    "capture", "offensive", "strike on", "hit the",
}

def is_assault_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _ASSAULT_KEYWORDS)


# ---------------------------------------------------------------------------
# Faction attacker force profiles
# ---------------------------------------------------------------------------

FACTION_FORCES: Dict[str, Dict] = {
    "Wardens of Ash": {
        "force_label":   "Wall Squad",
        "force_style":   "warband",
        "force_size":    (6, 10),
        "morale_pool":   28,
        "grunt_label":   "Wall Wardens",
        "grunt_cr":      "1",
        "lt_label":      "Squad Captains",
        "lt_count":      (1, 2),
        "lt_cr":         "3",
        "tactics":       "disciplined advance, squad cohesion, hold the line — self-sufficient unless things go badly",
        "morale_note":   "Steady unless taking catastrophic losses. Rally actions from the party are rarely needed.",
        "disposition":   "honourable — always debrief in person, always offer stay bonus if objective was reached",
    },
    "Tower Authority": {
        "force_label":   "Enforcement Unit",
        "force_style":   "warband",
        "force_size":    (5, 8),
        "morale_pool":   24,
        "grunt_label":   "Authority Enforcers",
        "grunt_cr":      "1",
        "lt_label":      "Senior Enforcers",
        "lt_count":      (1, 2),
        "lt_cr":         "3",
        "tactics":       "methodical, escalating force, by the book — will pull back if the operation becomes politically inconvenient",
        "morale_note":   "Solid morale unless leadership is questioned or losses mount beyond protocol.",
        "disposition":   "bureaucratic — pay on delivery, stay offer only if the objective was politically sensitive",
    },
    "Patchwork Saints": {
        "force_label":   "Neighbourhood Volunteers",
        "force_style":   "mob",
        "force_size":    (8, 14),
        "morale_pool":   18,
        "grunt_label":   "Saints Volunteers",
        "grunt_cr":      "1/4",
        "lt_label":      "Neighbourhood Bosses",
        "lt_count":      (1, 3),
        "lt_cr":         "1",
        "tactics":       "chaotic bravery — fight hard for each other, easily spooked by organised opposition, need constant rallying",
        "morale_note":   "Fragile early. Party rally actions matter a lot. Once committed they are stubborn.",
        "disposition":   "warm — debrief with food and thanks, always ask party to stay if they can",
    },
    "Wizards Tower": {
        "force_label":   "Arcane Response Team",
        "force_style":   "warband",
        "force_size":    (4, 7),
        "morale_pool":   20,
        "grunt_label":   "Tower Adepts",
        "grunt_cr":      "2",
        "lt_label":      "Arcane Supervisors",
        "lt_count":      (1, 2),
        "lt_cr":         "4",
        "tactics":       "magic-heavy, overconfident, powerful but brittle — loses confidence fast if their spells stop working",
        "morale_note":   "High output, low resilience. If a lieutenant falls early, morale can spiral.",
        "disposition":   "transactional — pay precisely, rarely offer stay, will if the target had something they want",
    },
    "Argent Blades": {
        "force_label":   "Contract Squad",
        "force_style":   "warband",
        "force_size":    (5, 9),
        "morale_pool":   22,
        "grunt_label":   "Blades Mercs",
        "grunt_cr":      "1",
        "lt_label":      "Contract Lieutenants",
        "lt_count":      (1, 2),
        "lt_cr":         "3",
        "tactics":       "professional, efficient, flanking focus — holds until losses aren't worth the contract",
        "morale_note":   "Steady until 50% losses then starts calculating. Rally with pay promises.",
        "disposition":   "professional — clean handover, stay offer only if extra pay is in the contract",
    },
    "Iron Fang Consortium": {
        "force_label":   "Consortium Security",
        "force_style":   "warband",
        "force_size":    (5, 8),
        "morale_pool":   20,
        "grunt_label":   "Consortium Guards",
        "grunt_cr":      "1",
        "lt_label":      "Operations Handlers",
        "lt_count":      (1, 2),
        "lt_cr":         "3",
        "tactics":       "profit-focused, efficient — cuts losses when ROI is negative",
        "morale_note":   "Reliable until the math goes wrong. Not loyal, just contracted.",
        "disposition":   "cold — pay and go, never offer stay",
    },
    "Obsidian Lotus": {
        "force_label":   "Lotus Cell",
        "force_style":   "shadow_cell",
        "force_size":    (3, 5),
        "morale_pool":   20,
        "grunt_label":   "Lotus Operatives",
        "grunt_cr":      "2",
        "lt_label":      "Cell Lieutenants",
        "lt_count":      (1, 2),
        "lt_cr":         "4",
        "tactics":       "precise, quiet — get in, hit the objective, get out. Not interested in a prolonged fight",
        "morale_note":   "Small force, high quality. Morale holds until the mission becomes impossible.",
        "disposition":   "private — debrief quietly, stay offer if the party proved discreet",
    },
    "Serpent Choir": {
        "force_label":   "Choir Vanguard",
        "force_style":   "cultist_surge",
        "force_size":    (5, 9),
        "morale_pool":   26,
        "grunt_label":   "Choir Faithful",
        "grunt_cr":      "1",
        "lt_label":      "Choir Champions",
        "lt_count":      (1, 2),
        "lt_cr":         "3",
        "tactics":       "fanatical advance, self-sacrifice tactics — will not retreat unless the ritual logic fails",
        "morale_note":   "Near-immune to morale loss until commander falls, then sudden collapse.",
        "disposition":   "cryptic — debrief in ritual language, stay offer if the party served the Choir's deeper purpose",
    },
    "Brother Thane's Cult": {
        "force_label":   "The Returned",
        "force_style":   "cultist_surge",
        "force_size":    (6, 10),
        "morale_pool":   30,
        "grunt_label":   "Cult Zealots",
        "grunt_cr":      "1",
        "lt_label":      "Returned Apostles",
        "lt_count":      (1, 2),
        "lt_cr":         "3",
        "tactics":       "fanatical, death-embracing — some will sacrifice themselves to trigger effects",
        "morale_note":   "Does not break. Individual units may fall but the force keeps advancing.",
        "disposition":   "reverent — treats the party as instruments of Thane's will, stay offer always extended",
    },
    "Glass Sigil": {
        "force_label":   "Sigil Proxy Force",
        "force_style":   "shadow_cell",
        "force_size":    (3, 5),
        "morale_pool":   14,
        "grunt_label":   "Hired Proxies",
        "grunt_cr":      "1",
        "lt_label":      "Sigil Coordinators",
        "lt_count":      (1, 1),
        "lt_cr":         "3",
        "tactics":       "uses proxies to avoid direct exposure — will abandon the assault if it becomes public",
        "morale_note":   "Very fragile. Any setback may trigger withdrawal.",
        "disposition":   "distant — debrief via messenger if possible, never stay offer",
    },
    "Guild of Ashen Scrolls": {
        "force_label":   "Archive Reclamation Team",
        "force_style":   "warband",
        "force_size":    (4, 7),
        "morale_pool":   18,
        "grunt_label":   "Guild Retrievers",
        "grunt_cr":      "1",
        "lt_label":      "Senior Archivists",
        "lt_count":      (1, 2),
        "lt_cr":         "2",
        "tactics":       "cautious advance, object-focused — more interested in retrieving the target than fighting",
        "morale_note":   "Holds under pressure if the objective is in sight. Falters if the target seems out of reach.",
        "disposition":   "scholarly — precise debrief, stay offer if materials remain unsecured",
    },
}

_DEFAULT_FORCE = {
    "force_label":   "Hired Squad",
    "force_style":   "warband",
    "force_size":    (5, 8),
    "morale_pool":   18,
    "grunt_label":   "fighters",
    "grunt_cr":      "1",
    "lt_label":      "squad leaders",
    "lt_count":      (1, 2),
    "lt_cr":         "3",
    "tactics":       "determined advance",
    "morale_note":   "Standard morale.",
    "disposition":   "neutral — pay and go",
}

def _get_force(faction: str) -> Dict:
    for k, v in FACTION_FORCES.items():
        if k.lower() in faction.lower():
            return v
    return _DEFAULT_FORCE


# ---------------------------------------------------------------------------
# Defender force profiles (mirrors defense pipeline army types)
# ---------------------------------------------------------------------------

DEFENDER_TYPES: Dict[str, Dict] = {
    "mob": {
        "label":         "Mob Defense",
        "grunt_label":   "rioters / street fighters",
        "lt_label":      "mob enforcers",
        "grunt_cr":      "1/4",
        "lt_cr":         "1",
        "base_size":     (6, 12),
        "lt_count":      (1, 2),
        "home_bonus":    "knows every exit and hiding spot — can reposition freely",
        "trickle":       "1d3 grunts appear from side entrances each round after round 2",
        "morale_pool":   16,
    },
    "warband": {
        "label":         "Warband Defense",
        "grunt_label":   "soldiers",
        "lt_label":      "squad sergeants",
        "grunt_cr":      "1/2",
        "lt_cr":         "2",
        "base_size":     (5, 9),
        "lt_count":      (1, 3),
        "home_bonus":    "pre-positioned at chokepoints, +2 AC when behind cover they placed",
        "trickle":       "1 lieutenant reinforcement after round 3 if the commander still stands",
        "morale_pool":   22,
    },
    "cultist_surge": {
        "label":         "Cult Defense",
        "grunt_label":   "true believers",
        "lt_label":      "zealot champions",
        "grunt_cr":      "1/2",
        "lt_cr":         "2",
        "base_size":     (5, 9),
        "lt_count":      (1, 2),
        "home_bonus":    "ritual wards in place — advantage on saving throws vs fear and charm",
        "trickle":       "1d2 zealots emerge from hidden chambers each round",
        "morale_pool":   28,
    },
    "shadow_cell": {
        "label":         "Shadow Cell Defense",
        "grunt_label":   "operatives",
        "lt_label":      "cell lieutenants",
        "grunt_cr":      "1",
        "lt_cr":         "3",
        "base_size":     (3, 6),
        "lt_count":      (1, 2),
        "home_bonus":    "trap network pre-set, hidden exits — Perception DC 16 to spot traps",
        "trickle":       "no trickle — but 1 operative may reappear from a hidden passage once",
        "morale_pool":   18,
    },
}

DEFENDER_FACTION_PROFILES: Dict[str, Dict] = {
    "Wardens of Ash": {
        "base_morale": 28,
        "army_style":  "warband",
        "tactics":     "highly regimented, squad-based, fall back to regroup then recommit, never truly break",
        "commander":   "a Wall Commander - tactical, calm under fire, inspires by example",
    },
    "Tower Authority": {
        "base_morale": 26,
        "army_style":  "warband",
        "tactics":     "institutional discipline, escalating force, will call in reinforcements rather than rout",
        "commander":   "a Senior Enforcer - by-the-book, escalates to lethal force methodically",
    },
    "Patchwork Saints": {
        "base_morale": 25,
        "army_style":  "mob",
        "tactics":     "chaotic but stubborn, fight for each other, morale sustained by community bonds not command",
        "commander":   "a neighbourhood boss - rallies by personal loyalty, loses authority if wounded",
    },
    "Wizards Tower": {
        "base_morale": 18,
        "army_style":  "warband",
        "tactics":     "overconfident, relies on magic advantage, loses confidence fast if their tricks stop working or their leader hesitates",
        "commander":   "an Arcane Supervisor - brilliant but brittle, morale crumbles if they publicly doubt the mission",
    },
    "Argent Blades": {
        "base_morale": 20,
        "army_style":  "warband",
        "tactics":     "professional mercenaries, holds until losses exceed contract value, withdraws cleanly",
        "commander":   "a Contract Captain - calculating, will negotiate withdrawal if offered face-saving terms",
    },
    "Iron Fang Consortium": {
        "base_morale": 20,
        "army_style":  "warband",
        "tactics":     "profit-driven discipline, efficient, cuts losses when ROI is negative",
        "commander":   "a Consortium Handler - manages the attack like a business operation",
    },
    "Brother Thane's Cult": {
        "base_morale": 35,
        "army_style":  "cultist_surge",
        "tactics":     "fanatical, self-sacrifice triggers effects, morale near-immune - only breaks on commander death",
        "commander":   "a Returned Apostle - death causes a morale surge in remaining grunts before collapse",
    },
    "Serpent Choir": {
        "base_morale": 24,
        "army_style":  "cultist_surge",
        "tactics":     "zealot discipline, holds long then shatters suddenly when the ritual logic breaks",
        "commander":   "a Choir Director - morale collapses if their ritual objective is denied twice",
    },
    "Obsidian Lotus": {
        "base_morale": 16,
        "army_style":  "shadow_cell",
        "tactics":     "small elite force, not trying to win - trying to get one thing through. Withdraws clean when the math says so",
        "commander":   "a Cell Coordinator - never seen on the field, withdraws the cell if objective becomes impossible",
    },
    "Glass Sigil": {
        "base_morale": 10,
        "army_style":  "shadow_cell",
        "tactics":     "avoids direct combat entirely, uses proxies and distractions, folds fast under real pressure",
        "commander":   "a Sigil Broker - not a fighter, flees or negotiates the moment casualties mount",
    },
    "Guild of Ashen Scrolls": {
        "base_morale": 17,
        "army_style":  "warband",
        "tactics":     "scholarly pride holds them together, but internal disagreement can collapse cohesion mid-assault",
        "commander":   "a Senior Archivist - competent planner, but loses authority if junior members start second-guessing",
    },
}

_DEFAULT_DEFENDER_PROFILE = {
    "base_morale": 18,
    "army_style":  "warband",
    "tactics":     "determined but disorganised",
    "commander":   "a field leader of unknown capability",
}

def _get_defender_profile(faction: str) -> Dict:
    for k, v in DEFENDER_FACTION_PROFILES.items():
        if k.lower() in faction.lower():
            return v
    return _DEFAULT_DEFENDER_PROFILE


# ---------------------------------------------------------------------------
# Commander archetypes
# ---------------------------------------------------------------------------

COMMANDER_ARCHETYPES = {
    "priest": {
        "label":      "Priest / Cleric",
        "cr":         "5",
        "abilities":  [
            "Healing Word (bonus action) — restores 1d8+3 HP to one visible defender per round",
            "Bless (concentration) — up to 3 defenders gain +1d4 to attack rolls and saving throws",
            "Sanctuary (reaction) — any attacker targeting the priest must succeed DC 14 Wisdom save or choose a new target",
            "Divine Intervention (1/combat) — calls a trickle reinforcement immediately out of turn",
        ],
        "surrender_threshold": "Yields at 25% HP — drops to knees, demands terms",
        "avoid_instakill":     "Sanctuary reaction fires automatically when first targeted — party must pass the save to engage directly",
        "lead_style":          "stays back, keeps defenders alive, makes the fight last longer than it should",
    },
    "warlord": {
        "label":      "Warlord / Tactician",
        "cr":         "6",
        "abilities":  [
            "Command (bonus action) — one defender makes an immediate free attack or moves up to their speed",
            "Rally Cry (1/round) — all defenders within 30ft gain advantage on their next attack roll",
            "Reposition (reaction) — when a defender is hit, the warlord moves them 10ft to adjacent cover",
            "Strategic Reserve (1/combat) — calls the trickle reinforcement early, before the normal trigger",
        ],
        "surrender_threshold": "Does not surrender — fights to 0 HP, then is incapacitated not dead",
        "avoid_instakill":     "Always within 10ft of 2+ defenders — area attacks must account for ally positioning",
        "lead_style":          "moves constantly, directs defenders into chokepoints, turns the position into a puzzle",
    },
    "fighter": {
        "label":      "Fighter / Champion",
        "cr":         "7",
        "abilities":  [
            "Wall of Steel — occupies a chokepoint, defenders behind them have +2 AC",
            "Second Wind (1/combat) — regains 1d10+5 HP as a bonus action",
            "Intercept (reaction) — when an adjacent ally is attacked, the commander takes the hit instead",
            "Intimidating Presence — party must succeed DC 13 Wisdom save or have disadvantage on first attack against the commander",
        ],
        "surrender_threshold": "Fights to 10% HP, then makes a contested Athletics check — if the party wins they yield",
        "avoid_instakill":     "Intercept reaction means eliminating supporting defenders first is tactically required",
        "lead_style":          "leads from the front, becomes the wall the party must break through personally",
    },
}

# Faction → most likely commander archetype
FACTION_COMMANDER: Dict[str, str] = {
    "Wardens of Ash":          "fighter",
    "Tower Authority":         "warlord",
    "Patchwork Saints":        "warlord",
    "Wizards Tower":           "priest",
    "Argent Blades":           "fighter",
    "Iron Fang Consortium":    "warlord",
    "Obsidian Lotus":          "warlord",
    "Glass Sigil":             "priest",
    "Serpent Choir":           "priest",
    "Brother Thane's Cult":    "priest",
    "Guild of Ashen Scrolls":  "warlord",
}


# ---------------------------------------------------------------------------
# Position / target tables
# ---------------------------------------------------------------------------

FACTION_POSITIONS: Dict[str, List[str]] = {
    "Wardens of Ash":          ["a wall gate outpost", "a bastion checkpoint", "a warden staging post"],
    "Tower Authority":         ["an enforcement office", "a transit checkpoint", "a regulated holding facility"],
    "Patchwork Saints":        ["a community safehouse", "a bolt-hole", "a Saints-held block"],
    "Wizards Tower":           ["a restricted research annex", "an arcane relay station", "a containment facility"],
    "Argent Blades":           ["a contract house", "a mercenary billet", "an armoury depot"],
    "Iron Fang Consortium":    ["a consortium vault", "a secure warehouse", "a distribution hub"],
    "Obsidian Lotus":          ["a private meeting house", "a smuggler dock", "a dead-drop facility"],
    "Glass Sigil":             ["a private gallery", "a Glass Sigil office", "a wealth-district club"],
    "Serpent Choir":           ["a hidden shrine", "a ritual preparation site", "a choir recruitment hall"],
    "Brother Thane's Cult":    ["a cult meeting hall", "a converted cellar complex", "a vigil house"],
    "Guild of Ashen Scrolls":  ["an archive annex", "a restricted vault", "a scholar sanctum"],
}

_DEFAULT_POSITIONS = ["a fortified position", "a defended building", "an enemy-held compound"]

def _pick_position(defending_faction: str) -> str:
    for k, v in FACTION_POSITIONS.items():
        if k.lower() in defending_faction.lower():
            return random.choice(v)
    return random.choice(_DEFAULT_POSITIONS)


# ---------------------------------------------------------------------------
# Tier scaling
# ---------------------------------------------------------------------------

TIER_SCALES = {
    "standard": {"defender_mult": 1.0, "grunt_bonus": 0,  "morale_mult": 1.0},
    "seasoned": {"defender_mult": 1.2, "grunt_bonus": 2,  "morale_mult": 1.2},
    "elite":    {"defender_mult": 1.5, "grunt_bonus": 4,  "morale_mult": 1.5},
    "legend":   {"defender_mult": 2.0, "grunt_bonus": 6,  "morale_mult": 2.0},
}

def _tier_scale(tier: str) -> Dict:
    return TIER_SCALES.get((tier or "standard").lower(), TIER_SCALES["standard"])


# ---------------------------------------------------------------------------
# Morale state thresholds
# ---------------------------------------------------------------------------

MORALE_STATES = [
    (0.00, 0.25, "Steady",   "#2a6a2a", "No penalty"),
    (0.25, 0.50, "Shaken",   "#b8923a", "−1 to all rolls"),
    (0.50, 0.75, "Breaking", "#c85320", "−2 to all rolls"),
    (0.75, 1.00, "Routed",   "#7b1e1e", "Troops flee — party fights alone"),
]


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

async def _ollama(prompt: str, system: str = "", tokens: int = 1400) -> str:
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
        "options":  {"temperature": 0.85, "num_predict": tokens},
    }

    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            data    = await call_ollama(payload, timeout=180.0, caller="assault", force=True)
            content = (data.get("message") or {}).get("content", "").strip()
            if content:
                return content
            # Ollama returned 200 but empty body — treat as transient failure
            logger.warning(f"[ASSAULT] Empty response (attempt {attempt}/{max_attempts})")
        except Exception as e:
            logger.warning(f"[ASSAULT] Ollama error attempt {attempt}/{max_attempts}: {e}")

        if attempt < max_attempts:
            wait = min(30 * attempt, 120)   # 30s, 60s, 90s, 120s … capped at 2 min
            logger.info(f"[ASSAULT] Retrying in {wait}s…")
            await asyncio.sleep(wait)

    logger.error("[ASSAULT] All 10 attempts exhausted — returning empty string")
    return ""


def _clean_json(raw: str) -> str:
    raw = raw.replace("\x5c\x27", "\x27")
    raw = raw.replace("\u2018", "'").replace("\u2019", "'")
    raw = raw.replace("\u201c", '"').replace("\u201d", '"')
    raw = raw.replace("\u2013", "-").replace("\u2014", "-")
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

async def _generate_briefing(
    mission: dict,
    position: str,
    attacker_force: Dict,
    commander: Dict,
    defending_faction: str,
) -> Dict:
    title    = mission.get("title", "Unknown Assault")
    faction  = mission.get("faction", "Independent")
    body     = mission.get("body") or mission.get("description") or ""

    prompt = f"""You are writing the briefing for a D&D assault mission module.

Mission: {title}
Hiring faction: {faction}
Target position: {position}
Defenders: {defending_faction}
Friendly force provided: {attacker_force['force_label']} — {attacker_force['grunt_label']}
Force tactics: {attacker_force['tactics']}
Defender commander: {commander['label']} — {commander['lead_style']}
Mission notes: {body[:300]}

Write a briefing as if the faction contact is speaking to the party. Include:
- What the target position is and why it needs to be taken
- What force the party is being given to lead
- The three win conditions: reach the objective, break defender morale, or take down the commander
- One specific warning about the defender commander and how they operate
- The party's role — they lead, the troops follow

Return JSON only:
{{
  "contact_speech": "2-3 paragraphs of the contact briefing the party",
  "objective_desc": "1 sentence on what the specific objective is inside the position",
  "commander_warning": "1 sentence warning about the defender commander",
  "win_conditions": ["reach and hold the objective", "break defender morale", "neutralise the commander"],
  "position_desc": "2 sentences describing the target position from the outside"
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    if not data:
        data = {
            "contact_speech":    f"We need that position taken. Lead the {attacker_force['force_label']} in — they'll follow if you show them it can be done.",
            "objective_desc":    f"Reach and hold the inner chamber of {position}.",
            "commander_warning": f"Their {commander['label']} is the linchpin — take them out and the defense collapses.",
            "win_conditions":    ["Reach and hold the objective", "Break defender morale through losses", "Neutralise the commander"],
            "position_desc":     f"A fortified {position}. Defenders have had time to prepare.",
        }
    return data


async def _generate_chokepoints(position: str, defender_type: Dict, defending_faction: str) -> List[Dict]:
    prompt = f"""Generate 3 chokepoints inside a defended position for a D&D assault module.

Position: {position}
Defenders: {defending_faction} — {defender_type['label']}
Home field advantage: {defender_type['home_bonus']}

Each chokepoint is a location the party must fight through to reach the objective.
Make them specific and varied — a gate, a corridor, a room, a stairwell.

For each chokepoint:
- Name and brief description
- What makes it defensible (cover, narrow approach, elevated position, etc.)
- Tactic the defenders use here
- How the party can overcome it (skill check, flanking route, destroying cover, etc.)

Return JSON only:
{{
  "chokepoints": [
    {{
      "name": "...",
      "desc": "...",
      "defensive_advantage": "...",
      "defender_tactic": "...",
      "party_solution": "..."
    }}
  ]
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    points = (data or {}).get("chokepoints", [])
    if len(points) < 3:
        points = [
            {"name": "The Gate",      "desc": "Main entrance, heavy doors, defenders behind.",           "defensive_advantage": "Narrow approach, only 2 abreast",    "defender_tactic": "Concentrated fire through arrow slits",   "party_solution": "DC 14 Athletics to force gate or DC 13 Stealth for side alley"},
            {"name": "The Courtyard", "desc": "Open kill zone between gate and the main building.",       "defensive_advantage": "Elevated firing positions on walls",   "defender_tactic": "Ranged attacks while party crosses open ground", "party_solution": "Smoke cover, DC 12 Acrobatics to dash between scattered cover"},
            {"name": "The Inner Door","desc": "Final entry to the objective room, barricaded.",           "defensive_advantage": "Barricaded, commander directs here",    "defender_tactic": "Commander rallies final defenders for last stand", "party_solution": "DC 15 Strength to breach or DC 13 Arcana to disrupt the barricade wards"},
        ]
    return points[:3]


async def _generate_debrief(
    mission: dict,
    position: str,
    attacker_force: Dict,
    outcome: str,
    troop_losses_pct: float,
) -> Dict:
    faction     = mission.get("faction", "Independent")
    title       = mission.get("title", "the assault")
    disposition = attacker_force.get("disposition", "neutral")

    prompt = f"""Write the debrief scene for a D&D assault mission.

Hiring faction: {faction}
Target: {position}
Mission: {title}
Outcome: {outcome}
Friendly troop losses: {int(troop_losses_pct * 100)}%
Faction disposition: {disposition}

The contact arrives at the assault site — not a neutral location. Write:
1. Their reaction to what they see (2 sentences of scene-setting)
2. Their words to the party (2-3 sentences, tone matching outcome and disposition)
3. Whether they offer a stay bonus and why (based purely on disposition, not just outcome)

Return JSON only:
{{
  "arrival_desc": "what the contact sees when they arrive",
  "contact_words": "what they say to the party",
  "stay_offer": true or false,
  "stay_reason": "why they do or don't offer extra pay to stay"
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    if not data:
        stay = "always" in disposition or "warm" in disposition
        data = {
            "arrival_desc":   f"The contact picks their way through the aftermath of the assault on {position}.",
            "contact_words":  "You did what was asked. Payment as agreed.",
            "stay_offer":     stay,
            "stay_reason":    "The position still needs securing." if stay else "The contract is complete.",
        }
    return data


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
            logger.info(f"[ASSAULT] A1111 not ready (attempt {attempt}/10) — waiting 30s…")
            await asyncio.sleep(30)
    logger.warning("[ASSAULT] A1111 unavailable after 10 attempts")
    return False


_POSITION_MAP_STYLES: List[tuple] = [
    ("gate",       "Town Exterior Table Map, gatehouse entry, portcullis, flanking guard towers, courtyard beyond, approach road"),
    ("outpost",    "Town Exterior Table Map, outer wall, entry checkpoint, interior yard, guard post at corners"),
    ("checkpoint", "Town Exterior Table Map, road crossing, inspection lanes, guard posts, barrier structures"),
    ("warehouse",  "Interior Table Map, loading dock entry, storage floor, office section, loading bay exits"),
    ("vault",      "Interior Table Map, reinforced entry corridor, security alcoves, inner vault chamber, single approach"),
    ("safehouse",  "Interior Table Map, cramped rooms, multiple entry points, hidden passages, barricaded interior doors"),
    ("annex",      "Interior Table Map, main entry, connecting corridors, locked rooms, objective chamber at rear"),
    ("facility",   "Interior Table Map, reception entry, operational floor, secure inner section, utility passages"),
    ("shrine",     "Interior Table Map, ceremonial entry, prayer chamber, inner sanctum, altar room at centre"),
    ("hall",       "Interior Table Map, grand entry, open main chamber, flanking galleries, dais or stage at far end"),
    ("dock",       "Interior Table Map, pier entry, warehouse flanking, loading cranes, water edge on one side"),
    ("billet",     "Interior Table Map, bunkroom entry, common area, armoury alcove, command room at rear"),
    ("office",     "Interior Table Map, reception entry, open floor plan, private offices, secure back room"),
    ("club",       "Interior Table Map, main entrance, open social floor, private rooms, back office"),
]

def _position_map_style(position: str) -> str:
    pos_low = position.lower()
    for key, style in _POSITION_MAP_STYLES:
        if key in pos_low:
            return style
    return "Interior Table Map, exterior approach, fortified entry, interior rooms, objective chamber at rear"


async def _generate_assault_map(
    position: str,
    defending_faction: str,
    chokepoints: List[Dict],
    out_dir: Path,
) -> Optional[Path]:
    out = out_dir / "assault_map.png"
    import re
    map_style = _position_map_style(position)
    # Strip SD1.5 LoRA prefix tokens (meaningless to Flux)
    map_style = re.sub(r'(?:Big |Small )?(?:[\w]+ )*?Table Map[, ]+', '', map_style, count=1, flags=re.IGNORECASE).strip(', ')
    is_dungeon = "dungeon" in map_style.lower()
    lora_name = os.getenv("A1111_MAP_LORA_DUNGEON" if is_dungeon else "A1111_MAP_LORA_TOWN",
                           "EnvyFluxDungeonMap01" if is_dungeon else "EnvyFluxFantasyTownMap01")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    triggers = os.getenv("A1111_MAP_DUNGEON_TRIGGERS" if is_dungeon else "A1111_MAP_TOWN_TRIGGERS",
                          "detailed, map, dungeon" if is_dungeon else "detailed, map, village")

    # Chokepoint features as visual elements
    chokepoint_tokens = ", ".join(
        cp.get("name", "")[:30] for cp in chokepoints if cp.get("name")
    )

    faction_tint = {
        "Wardens of Ash":   "grey stone military aesthetic, ash sigil markers, utilitarian fortification",
        "Tower Authority":  "official enforcement colours, regulation signage, structured layout",
        "Patchwork Saints": "improvised community defenses, mismatched barricades, lived-in",
        "Wizards Tower":    "arcane wards on walls, glowing rune reinforcements, magical barrier nodes",
        "Argent Blades":    "mercenary colours, weapon racks, professional barricade lines",
        "Obsidian Lotus":   "minimal signage, concealed entries, shadow-friendly recesses",
        "Glass Sigil":      "wealth-district materials, elegant facade, hidden reinforcements",
        "Serpent Choir":    "cult symbols at entry points, ritual markings, dim sacred lighting",
        "Brother Thane's Cult": "vigil candles, Returned symbols, converted civilian space",
        "Iron Fang Consortium": "industrial materials, iron-braced doors, consortium markings",
    }.get(defending_faction, "neutral stone and timber fortification")

    positive = ", ".join(filter(None, [
        f"<lora:{lora_name}:{lora_weight}>",
        triggers,
        map_style,
        chokepoint_tokens,
        "defender positions marked, cover objects placed, chokepoint at entry",
        "assault approach visible, exterior and interior both shown",
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
            decision = await wait_for_a1111_turn("assault_map", max_wait_seconds=60)
            if not decision.run_now:
                logger.info(f"[ASSAULT] A1111 deferred by resource cop: {decision.reason}")
                from src.mission_builder.vtt_renderer import save_vtt_battlemap
                save_vtt_battlemap(out, None, context={"title": position, "location": position, "prompt": positive, "kind": "assault fort"})
                return out
            async with a1111_lock:
                async with httpx.AsyncClient(timeout=600.0) as c:
                    r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                    r.raise_for_status()
                    images = r.json().get("images", [])
            if not images:
                raise RuntimeError("A1111 returned no images")
            from src.mission_builder.vtt_renderer import save_vtt_battlemap
            save_vtt_battlemap(out, images[0], context={"title": position, "location": position, "prompt": positive, "kind": "assault fort"})
            logger.info(f"[ASSAULT] Map saved: {out.name}")
            return out
        except Exception as e:
            logger.warning(f"[ASSAULT] Map attempt {map_attempt}/{max_map_attempts} failed: {e}")
            if map_attempt < max_map_attempts:
                wait = min(30 * map_attempt, 120)
                logger.info(f"[ASSAULT] Retrying map in {wait}s…")
                await asyncio.sleep(wait)

    # All attempts exhausted — fall back to deterministic
    logger.error("[ASSAULT] Map generation failed after 10 attempts — using deterministic fallback")
    from src.mission_builder.vtt_renderer import save_vtt_battlemap
    save_vtt_battlemap(out, None, context={"title": position, "location": position, "prompt": positive, "kind": "assault fort"})
    logger.info(f"[ASSAULT] Deterministic VTT map saved: {out.name}")
    return out


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _morale_track(pool: int, label: str) -> str:
    """Color-coded checkbox track with state thresholds marked."""
    boxes = ""
    for i in range(pool):
        pct = i / pool
        if pct < 0.25:
            color, title = "#2a6a2a", "Steady"
        elif pct < 0.50:
            color, title = "#b8923a", "Shaken (−1)"
        elif pct < 0.75:
            color, title = "#c85320", "Breaking (−2)"
        else:
            color, title = "#7b1e1e", "Routed"
        boxes += (
            f'<input type="checkbox" title="{title}" '
            f'style="width:18px;height:18px;margin:2px;accent-color:{color};">'
        )

    threshold_labels = "".join(
        f'<span style="display:inline-block;width:{int(pct_end*100)-int(pct_start*100)}%;'
        f'text-align:center;font-size:10px;color:{color};font-weight:bold;">{state}</span>'
        for pct_start, pct_end, state, color, _ in MORALE_STATES
    )

    return (
        f'<div style="margin:12px 0;">'
        f'<div style="font-weight:bold;font-size:13px;margin-bottom:4px;">{_e(label)} — {pool} troops</div>'
        f'<div style="width:100%;display:flex;margin-bottom:2px;">{threshold_labels}</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:2px;">{boxes}</div>'
        f'<div style="font-size:11px;color:#666;margin-top:4px;">'
        f'<span style="color:#2a6a2a">■</span> Steady &nbsp;'
        f'<span style="color:#b8923a">■</span> Shaken −1 &nbsp;'
        f'<span style="color:#c85320">■</span> Breaking −2 &nbsp;'
        f'<span style="color:#7b1e1e">■</span> Routed — flee'
        f'</div>'
        f'</div>'
    )


def _commander_card(commander: Dict, defending_faction: str, fc: str) -> str:
    abilities_html = "".join(
        f'<li style="margin:4px 0;font-size:13px;">{_e(a)}</li>'
        for a in commander.get("abilities", [])
    )
    return (
        f'<div style="border:2px solid #7b1e1e;border-radius:8px;padding:14px 18px;margin:16px 0;background:#fff5f5;">'
        f'<h3 style="margin:0 0 8px;color:#7b1e1e;">Defender Commander — {_e(commander["label"])}</h3>'
        f'<div style="font-size:13px;margin:4px 0;"><strong>Faction:</strong> {_e(defending_faction)}</div>'
        f'<div style="font-size:13px;margin:4px 0;"><strong>CR:</strong> {_e(commander["cr"])} &nbsp;|&nbsp; <strong>Lead style:</strong> {_e(commander["lead_style"])}</div>'
        f'<h4 style="margin:10px 0 4px;">Command Abilities</h4>'
        f'<ul style="margin:0;padding-left:20px;">{abilities_html}</ul>'
        f'<div style="margin-top:10px;padding:8px 12px;background:#ffe8e8;border-radius:4px;font-size:13px;">'
        f'<strong>Avoid instakill:</strong> {_e(commander["avoid_instakill"])}'
        f'</div>'
        f'<div style="margin-top:6px;padding:8px 12px;background:#fff0e8;border-radius:4px;font-size:13px;">'
        f'<strong>Surrender threshold:</strong> {_e(commander["surrender_threshold"])}'
        f'</div>'
        f'</div>'
    )


def _chokepoint_card(cp: Dict, idx: int, fc: str) -> str:
    return (
        f'<div style="border-left:4px solid {fc};padding:12px 16px;margin:10px 0;background:#fafafa;border-radius:0 6px 6px 0;">'
        f'<div style="font-weight:bold;font-size:15px;margin-bottom:6px;">Chokepoint {idx} — {_e(cp.get("name",""))}</div>'
        f'<div style="font-size:13px;margin:4px 0;font-style:italic;">{_e(cp.get("desc",""))}</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;font-size:13px;">'
        f'<div><strong>Defensive advantage:</strong><br>{_e(cp.get("defensive_advantage",""))}</div>'
        f'<div><strong>Defender tactic:</strong><br>{_e(cp.get("defender_tactic",""))}</div>'
        f'</div>'
        f'<div style="margin-top:8px;padding:6px 10px;background:#e8f0f8;border-radius:4px;font-size:13px;">'
        f'<strong>Party solution:</strong> {_e(cp.get("party_solution",""))}'
        f'</div>'
        f'<div style="margin-top:6px;">'
        f'<input type="checkbox" id="cp{idx}c" style="accent-color:#2a6a2a;"> <label for="cp{idx}c" style="font-size:13px;">Chokepoint cleared</label>'
        f'</div>'
        f'</div>'
    )


def render_assault_module(
    mission: dict,
    position: str,
    defending_faction: str,
    attacker_force: Dict,
    defender_type: Dict,
    commander: Dict,
    briefing: Dict,
    chokepoints: List[Dict],
    attacker_morale: int,
    defender_morale: int,
    strength: Dict[str, Any],
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title    = mission.get("title", "Assault")
    faction  = mission.get("faction", "Independent")
    fc       = _faction_color(faction)

    map_html = ""
    if map_path and map_path.exists():
        rel = map_path.relative_to(out_dir)
        map_html = (
            f'<div style="text-align:center;margin:20px 0;">'
            f'<img src="{rel}" style="max-width:100%;border:3px solid {fc};border-radius:8px;" alt="Assault Map">'
            f'<div style="font-size:12px;color:#888;margin-top:4px;">Target: {_e(position)}</div>'
            f'</div>'
        )

    win_conditions_html = "".join(
        f'<li style="margin:4px 0;">{_e(w)}</li>'
        for w in briefing.get("win_conditions", [])
    )

    chokepoint_html = "".join(
        _chokepoint_card(cp, i+1, fc) for i, cp in enumerate(chokepoints)
    )
    scaling_html = (
        f'<div style="background:#eef6ff;border:1px solid #3a6898;border-radius:6px;'
        f'padding:10px 14px;margin:14px 0;font-size:13px;">'
        f'<strong>Live Party Scaling:</strong> {_e(_party_scaling_note(strength))} '
        f'Defender morale and commander CR are tuned from this read.</div>'
    )

    body = f"""
<div style="border-left:4px solid {fc};padding:12px 18px;margin:20px 0;background:#fafafa;border-radius:0 8px 8px 0;">
  <h2 style="margin:0 0 8px;">Briefing</h2>
  <div style="white-space:pre-line;font-style:italic;margin:10px 0;">{_e(briefing.get("contact_speech",""))}</div>
  <div style="margin-top:10px;font-size:13px;">
    <strong>Objective:</strong> {_e(briefing.get("objective_desc",""))}<br>
    <strong>Position:</strong> {_e(briefing.get("position_desc",""))}<br>
    <strong>Commander warning:</strong> {_e(briefing.get("commander_warning",""))}
  </div>
  <h3 style="margin:12px 0 4px;">Win Conditions — any one</h3>
  <ul style="margin:0;padding-left:20px;">{win_conditions_html}</ul>
</div>

{scaling_html}

{map_html}

<h2>Forces</h2>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:16px 0;flex-wrap:wrap;">

  <div style="border:1px solid {fc};border-radius:8px;padding:14px 18px;background:#f5fff5;">
    <h3 style="margin:0 0 8px;color:{fc};">Attacker Force — {_e(attacker_force['force_label'])}</h3>
    <div style="font-size:13px;margin:4px 0;"><strong>Grunts:</strong> {_e(attacker_force['grunt_label'])} (CR {_e(attacker_force['grunt_cr'])})</div>
    <div style="font-size:13px;margin:4px 0;"><strong>Lieutenants:</strong> {_e(attacker_force['lt_label'])} (CR {_e(attacker_force['lt_cr'])})</div>
    <div style="font-size:13px;margin:4px 0;"><strong>Tactics:</strong> {_e(attacker_force['tactics'])}</div>
    <div style="font-size:13px;margin:4px 0;color:#555;"><strong>Morale note:</strong> {_e(attacker_force['morale_note'])}</div>
    {_morale_track(attacker_morale, "Friendly Troop Morale")}
  </div>

  <div style="border:1px solid #7b1e1e;border-radius:8px;padding:14px 18px;background:#fff5f5;">
    <h3 style="margin:0 0 8px;color:#7b1e1e;">Defender Force — {_e(defender_type['label'])}</h3>
    <div style="font-size:13px;margin:4px 0;"><strong>Grunts:</strong> {_e(defender_type['grunt_label'])} (CR {_e(defender_type['grunt_cr'])})</div>
    <div style="font-size:13px;margin:4px 0;"><strong>Lieutenants:</strong> {_e(defender_type['lt_label'])} (CR {_e(defender_type['lt_cr'])})</div>
    <div style="font-size:13px;margin:4px 0;"><strong>Home advantage:</strong> {_e(defender_type['home_bonus'])}</div>
    <div style="font-size:13px;margin:4px 0;color:#7b1e1e;"><strong>Trickle:</strong> {_e(defender_type['trickle'])}</div>
    {_morale_track(defender_morale, "Defender Morale")}
  </div>

</div>

{_commander_card(commander, defending_faction, fc)}

<h2>The Assault — Chokepoints</h2>
<div style="font-size:13px;color:#555;margin-bottom:12px;">
  One assault wave. The party leads the force through each chokepoint to reach the objective.
  Friendly troop morale drops as casualties mount — rally actions can push the state back one tier.
</div>
{chokepoint_html}

<hr>

<h2>Debrief</h2>
<div style="background:#e8f5e8;border:1px solid #2a6a2a;border-radius:6px;padding:14px 18px;">
  <p><strong>Outcome:</strong>
    <select style="font-family:inherit;margin-left:8px;">
      <option>Objective reached</option>
      <option>Defender morale broken</option>
      <option>Commander neutralised</option>
      <option>Troops routed — party pushed through alone</option>
      <option>Full failure</option>
    </select>
  </p>
  <p><strong>Friendly losses:</strong> <input type="number" style="width:50px;"> / {attacker_morale}</p>
  <p><strong>Stay offer accepted:</strong> <input type="checkbox"></p>
  <textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Session notes..."></textarea>
</div>
"""

    return _page(title, body, faction)


def render_assault_session(
    mission: dict,
    position: str,
    defending_faction: str,
    attacker_force: Dict,
    defender_type: Dict,
    commander: Dict,
    briefing: Dict,
    chokepoints: List[Dict],
    attacker_morale: int,
    defender_morale: int,
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title  = mission.get("title", "Assault")
    faction= mission.get("faction", "Independent")
    fc     = _faction_color(faction)

    def _card(heading: str, content: str, color: str = "#b8923a") -> str:
        return (
            f'<div style="border:2px solid {color};border-radius:10px;padding:18px 22px;margin:20px 0;background:white;">'
            f'<h2 style="margin:0 0 12px;color:{color};">{heading}</h2>{content}</div>'
        )

    map_html = ""
    if map_path and map_path.exists():
        rel = map_path.relative_to(out_dir)
        map_html = f'<img src="{rel}" style="max-width:100%;border-radius:6px;margin:10px 0;" alt="Map">'

    cards = ""

    # Briefing
    cards += _card(
        f"Briefing — {_e(position)}",
        f'<p style="font-style:italic;">{_e(briefing.get("contact_speech","")[:500])}</p>'
        f'<p><strong>Objective:</strong> {_e(briefing.get("objective_desc",""))}</p>'
        f'<p><strong>Commander warning:</strong> {_e(briefing.get("commander_warning",""))}</p>',
        fc,
    )

    # Forces card
    cards += _card(
        "Forces",
        f'{map_html}'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">'
        f'<div><h3 style="color:{fc};margin:0 0 6px;">Attackers</h3>'
        f'{_morale_track(attacker_morale, attacker_force["force_label"])}</div>'
        f'<div><h3 style="color:#7b1e1e;margin:0 0 6px;">Defenders</h3>'
        f'{_morale_track(defender_morale, defending_faction)}</div>'
        f'</div>'
        f'<div style="margin-top:10px;font-size:12px;color:#555;">'
        f'Trickle: {_e(attacker_force.get("morale_note",""))} | Defender trickle: {_e(defender_type.get("trickle", "see module"))}</div>',
        "#555",
    )

    # Chokepoint cards
    for i, cp in enumerate(chokepoints, 1):
        cards += _card(
            f"Chokepoint {i} — {_e(cp.get('name',''))}",
            f'<p style="font-style:italic;">{_e(cp.get("desc",""))}</p>'
            f'<p><strong>Defender tactic:</strong> {_e(cp.get("defender_tactic",""))}</p>'
            f'<p><strong>Party solution:</strong> {_e(cp.get("party_solution",""))}</p>'
            f'<input type="checkbox"> <strong>Cleared</strong>',
            "#c85320",
        )

    # Commander card
    abilities_html = "".join(f'<li style="font-size:13px;">{_e(a)}</li>' for a in commander.get("abilities", []))
    cards += _card(
        f"Commander — {_e(commander['label'])}",
        f'<ul style="padding-left:20px;margin:0 0 8px;">{abilities_html}</ul>'
        f'<div style="background:#ffe8e8;padding:8px;border-radius:4px;font-size:13px;margin-top:6px;">'
        f'{_e(commander["avoid_instakill"])}</div>'
        f'<div style="margin-top:6px;"><input type="checkbox"> <strong>Neutralised</strong></div>',
        "#7b1e1e",
    )

    # Debrief
    cards += _card(
        "Debrief",
        f'<p><strong>Outcome:</strong> <select style="font-family:inherit;">'
        f'<option>Objective reached</option><option>Defender morale broken</option>'
        f'<option>Commander neutralised</option><option>Troops routed — party solo</option>'
        f'<option>Full failure</option></select></p>'
        f'<p><strong>Friendly losses:</strong> <input type="number" style="width:50px;"> / {attacker_morale}</p>'
        f'<textarea rows="2" style="width:100%;font-family:inherit;" placeholder="Notes..."></textarea>',
        "#2a6a2a",
    )

    body = (
        f'<div style="text-align:center;margin:0 0 24px;">'
        f'<h1 style="color:{fc};">{_e(title)}</h1>'
        f'<div style="font-size:14px;color:#666;">{_e(faction)} — Assault on {_e(position)}</div>'
        f'</div>' + cards
    )
    return _page(title, body, faction)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


def _party_strength() -> Dict[str, Any]:
    """Read live PC snapshots; copied here so assault stays standalone."""
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
            pcs.append({
                "name": snap.get("name") or row.get("char_name"),
                "level": level,
                "max_hp": int(snap.get("max_hp") or 0),
            })
    except Exception as e:
        logger.warning(f"[ASSAULT] Could not read live party snapshots: {e}")
    levels = [p["level"] for p in pcs] or [5]
    return {
        "party_size": len(pcs) or 4,
        "avg_level": round(sum(levels) / len(levels), 1),
        "max_level": max(levels),
        "pcs": pcs,
    }


def _party_scaling_note(strength: Dict[str, Any]) -> str:
    return (
        f"Live party read: {strength['party_size']} PCs, average level "
        f"{strength['avg_level']}, max level {strength['max_level']}."
    )


async def build_assault_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    """Full assault pipeline. Returns path to index.html."""
    title            = mission.get("title", "Unknown Assault")
    faction          = mission.get("faction", "Independent")
    defending_faction= mission.get("opposing_faction") or "Unknown Faction"
    tier             = mission.get("tier", "standard")

    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[ASSAULT] Building: {title!r} | faction={faction} | defending={defending_faction} | tier={tier}")

    attacker_force   = _get_force(faction)
    tier_data        = _tier_scale(tier)
    position         = _pick_position(defending_faction)
    strength         = _party_strength()

    # Defender army type is owned here so assault stays independent from defense.
    def_profile      = _get_defender_profile(defending_faction)
    defender_type    = DEFENDER_TYPES[def_profile["army_style"]]

    # Commander archetype
    cmd_key = FACTION_COMMANDER.get(
        next((k for k in FACTION_COMMANDER if k.lower() in defending_faction.lower()), ""),
        random.choice(list(COMMANDER_ARCHETYPES.keys()))
    )
    commander = dict(COMMANDER_ARCHETYPES[cmd_key])
    commander["cr"] = str(max(int(commander["cr"]), int(strength["avg_level"]) + 2))

    # Morale pools
    f_size = random.randint(*attacker_force["force_size"])
    attacker_morale = f_size
    defender_morale = max(5, int(
        (def_profile["base_morale"] + max(0, strength["party_size"] - 4) * 2 + max(0, strength["max_level"] - 5) * 2)
        * tier_data["morale_mult"]
    ))

    logger.info(f"[ASSAULT] Position={position} | cmd={commander['label']} | atk_troops={attacker_morale} | def_morale={defender_morale}")

    # Generate concurrently
    briefing_task    = asyncio.create_task(_generate_briefing(mission, position, attacker_force, commander, defending_faction))
    chokepoint_task  = asyncio.create_task(_generate_chokepoints(position, defender_type, defending_faction))
    briefing, chokepoints = await asyncio.gather(briefing_task, chokepoint_task)

    # Map
    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            map_path = await _generate_assault_map(position, defending_faction, chokepoints, out_dir)
        else:
            logger.warning("[ASSAULT] A1111 not available — skipping map")

    # Mimir: commander + defender catalog lookup
    from src.mission_builder.mimir_module import create_module as _mc, enrich_monsters as _me, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="assault")
    _a_enemies = [
        {"name": f"{defending_faction} Guard", "cr": str(max(1, int(strength.get("avg_level", 3)) - 1)), "count": 4, "notes": "Defenders"},
        {"name": commander["label"], "cr": str(commander["cr"]), "count": 1, "notes": "Commander"},
    ]
    _enriched = await _me(_mimir_id or "", _a_enemies)

    # Direct DDB homebrew push — fires when Mimir is unavailable but DDB session is set.
    # enrich_monsters() exits early without pushing anything if Mimir is down, so we
    # push each enemy directly here as a fallback.
    if not _mimir_id:
        try:
            from src.ddb_homebrew import push_mission_enemy as _ddb_push, ENABLED as _ddb_en
            if _ddb_en:
                async def _push_all_direct():
                    for _e in _a_enemies:
                        if not _e.get("name"):
                            continue
                        _cr = str(_e.get("cr", "1"))
                        try:
                            _cr_num = float(_cr.replace("1/8","0.125").replace("1/4","0.25").replace("1/2","0.5"))
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

    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Assault Map")

    # Render
    module_html = render_assault_module(
        mission, position, defending_faction, attacker_force, defender_type,
        commander, briefing, chokepoints, attacker_morale, defender_morale, strength, map_path, out_dir,
    )
    module_html += _ms(_enriched, [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")

    session_html = render_assault_session(
        mission, position, defending_faction, attacker_force, defender_type, commander,
        briefing, chokepoints, attacker_morale, defender_morale, map_path, out_dir,
    )
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    dm_md = (
        f"## Assault DM Guide\n"
        f"### Target Position\n{position}: {briefing.get('position_desc', '')}\n\n"
        f"### Defender Side\n"
        f"- Defending faction: {defending_faction}\n"
        f"- Defender force: {defender_type['label']}\n"
        f"- Home advantage: {defender_type['home_bonus']}\n"
        f"- Trickle resources: {defender_type['trickle']}\n"
        f"- Defender morale: {defender_morale}\n\n"
        f"### Commander\n"
        f"- {commander['label']} CR {commander['cr']}\n"
        f"- Lead style: {commander['lead_style']}\n"
        f"- Avoid instant kill: {commander['avoid_instakill']}\n"
        f"- Surrender threshold: {commander['surrender_threshold']}\n"
        + "\n".join(f"- {a}" for a in commander.get("abilities", []))
        + "\n\n### Chokepoints\n"
        + "\n".join(f"- {cp.get('name')}: {cp.get('defender_tactic')} / Solution: {cp.get('party_solution')}" for cp in chokepoints)
        + f"\n\n### Live Scaling\n{_party_scaling_note(strength)}"
    )
    players_md = (
        f"## Player Brief\n{briefing.get('contact_speech', '')}\n\n"
        f"### Friendly Force\n"
        f"- {attacker_force['force_label']}: {attacker_force['grunt_label']}\n"
        f"- Tactics: {attacker_force['tactics']}\n"
        f"- Morale note: {attacker_force['morale_note']}\n\n"
        f"### Win Conditions\n"
        + "\n".join(f"- {w}" for w in briefing.get("win_conditions", []))
        + "\n\nThe party leads the push. Troops follow the party's momentum and can break if morale collapses."
    )
    chart_md = (
        f"## Assault Chart Pack\n"
        f"### Morale\n"
        f"- Friendly morale boxes: {attacker_morale}\n"
        f"- Defender morale boxes: {defender_morale}\n"
        f"- Steady 0-25%, Shaken 26-50% (-1), Breaking 51-75% (-2), Routed 76%+.\n\n"
        f"### Chokepoint Tracker\n"
        + "\n".join(f"| {i+1} | {cp.get('name')} | {cp.get('defensive_advantage')} |" for i, cp in enumerate(chokepoints))
        + "\n\n### Commander Abilities\n"
        + "\n".join(f"- {a}" for a in commander.get("abilities", []))
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, faction, players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",      "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",           "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Morale & Chokepoints","type": "custom",     "content": chart_md},
        ])
    maps_name = write_maps_page(out_dir, title, faction, [map_path] if map_path else [])
    box_components = component_links(has_maps=bool(maps_name))

    # Index
    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title, faction=faction, tier=tier,
            cr=mission_cr(mission),
            player_name=mission.get("player_name", "") or "Open",
            chapters=[],
            components=box_components,
            chart_pack=None, map_count=1 if map_path else 0,
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as _e:
        logger.warning(f"[ASSAULT] index.html failed: {_e}")
        index_path = out_dir / "module.html"

    # DB slug
    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as _e:
        logger.warning(f"[ASSAULT] Could not write module_slug: {_e}")

    # Zip
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[ASSAULT] Complete: {title!r} → {out_dir.name}")
    return index_path
