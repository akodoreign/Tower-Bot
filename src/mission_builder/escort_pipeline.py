"""
escort_pipeline.py — Pipeline for Escort mission modules.

Party picks up a person or item at point A and delivers to point B.
Target vets the party before moving. An ambush is waiting somewhere on
the route — position randomised, marked on the DM reference map only.

Two maps:
  - Clean map  — shown to players, large constraining city route
  - DM map     — same prompt, different seed, HTML overlay marks ambush
                 point and trap locations

Target has a stat block — most are liabilities, some help.

Outcome states:
  intact         → full pay
  damaged/wounded → partial pay
  lost           → no pay, rep hit
  dead/destroyed → no pay, rep loss, party owes a debt

Exported:
    build_escort_module(mission: dict, out_dir: Path) -> Path
    is_escort_mission(mission_type: str) -> bool
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
from typing import Optional, Dict, List, Any, Tuple

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

_ESCORT_KEYWORDS = {
    "escort", "protect", "accompany", "guard", "convoy", "deliver",
    "transport", "bodyguard", "safe passage", "see them to",
}

def is_escort_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _ESCORT_KEYWORDS)


# ---------------------------------------------------------------------------
# Faction vetting — how each faction's target sizes up the party
# ---------------------------------------------------------------------------

FACTION_VET: Dict[str, Dict] = {
    "Wardens of Ash": {
        "style":       "visible and confident — Wardens want protectors who look the part",
        "check":       "Intimidation or Athletics DC 11",
        "fail_result": "The contact hesitates but proceeds — no better options",
        "pass_result": "Nods with approval. Leads you to the target immediately.",
    },
    "Tower Authority": {
        "style":       "papers and credentials — Authority wants documented, accountable crew",
        "check":       "Persuasion or Investigation DC 12",
        "fail_result": "Bureaucratic delay — 30 minutes lost while forms are checked",
        "pass_result": "Stamps something. Target is released to your custody.",
    },
    "Patchwork Saints": {
        "style":       "community trust — Saints want someone the neighbourhood vouches for",
        "check":       "Persuasion or History DC 11",
        "fail_result": "Cautious but no other choice. Target watches you nervously.",
        "pass_result": "Smiles. Introduces you to the target by name.",
    },
    "Wizards Tower": {
        "style":       "arcane verification — Tower wants someone who won't mishandle volatile cargo",
        "check":       "Arcana DC 13 or Investigation DC 14",
        "fail_result": "Reluctant handover with a very long list of handling warnings",
        "pass_result": "Impressed. Provides a protective cantrip scroll as a bonus.",
    },
    "Argent Blades": {
        "style":       "loud and visible — Blades want the world to know the target is protected",
        "check":       "Intimidation or Performance DC 12",
        "fail_result": "Target sighs. You'll do, apparently.",
        "pass_result": "Slaps you on the back. Buys the first round.",
    },
    "Iron Fang Consortium": {
        "style":       "professional credentials — Consortium wants receipts and references",
        "check":       "Persuasion DC 12 or Deception DC 14",
        "fail_result": "10% deducted from final pay as 'risk surcharge'",
        "pass_result": "Efficient handover. Paperwork signed in triplicate.",
    },
    "Obsidian Lotus": {
        "style":       "silence and discretion — Lotus assets disappear if the crew draws attention",
        "check":       "Stealth DC 13 or Deception DC 12",
        "fail_result": "Target watches the street for five minutes before approaching",
        "pass_result": "Appears from a shadow. Approves without a word.",
    },
    "Glass Sigil": {
        "style":       "wealth signals — Sigil targets trust presentation over capability",
        "check":       "Deception DC 12 or Persuasion DC 13",
        "fail_result": "Target is dismissive but out of options",
        "pass_result": "Visibly relieved. Comments on your attire positively.",
    },
    "Serpent Choir": {
        "style":       "ritual acceptance — Choir assets test if the party carries spiritual weight",
        "check":       "Religion DC 13 or Insight DC 14",
        "fail_result": "Tolerated. Not welcomed.",
        "pass_result": "Makes a blessing gesture. You passed something you didn't know was a test.",
    },
    "Brother Thane's Cult": {
        "style":       "faith recognition — Cult assets need to know you won't interfere",
        "check":       "Religion DC 12 or Persuasion DC 14",
        "fail_result": "Proceeds with visible distrust. Prays quietly the whole route.",
        "pass_result": "Clasps your hand. You are instruments of Thane's will now.",
    },
    "Guild of Ashen Scrolls": {
        "style":       "scholarly vetting — Guild assets ask unexpected questions",
        "check":       "History DC 13 or Arcana DC 12",
        "fail_result": "Sniffs. Decides competent muscle beats no muscle.",
        "pass_result": "Asks a follow-up question they clearly don't expect you to answer. You do.",
    },
}

_DEFAULT_VET = {
    "style":       "basic assessment",
    "check":       "Persuasion DC 12",
    "fail_result": "Proceeds with caution",
    "pass_result": "Satisfied. Ready to move.",
}

def _get_vet(faction: str) -> Dict:
    for k, v in FACTION_VET.items():
        if k.lower() in faction.lower():
            return v
    return _DEFAULT_VET


# ---------------------------------------------------------------------------
# Target types
# ---------------------------------------------------------------------------

PERSON_ARCHETYPES = [
    {"label": "Wounded Soldier",        "hp": 8,  "ac": 12, "useful": False, "note": "Can barely walk. Needs support on difficult terrain."},
    {"label": "Merchant",               "hp": 6,  "ac": 10, "useful": False, "note": "Complains. Stops to assess market prices. Slows the group."},
    {"label": "Soul Vial Farmer",       "hp": 4,  "ac": 9,  "useful": False, "note": "Knows nothing of combat. Extremely fragile."},
    {"label": "Retired Adventurer",     "hp": 20, "ac": 14, "useful": True,  "note": "Still sharp. Will join the fight if things go badly."},
    {"label": "Priestess of Valkyrie",  "hp": 14, "ac": 13, "useful": True,  "note": "Joins in for the fight if asked. Healing word and a blessed war hammer."},
    {"label": "Young Noble",            "hp": 6,  "ac": 10, "useful": False, "note": "Recognises someone mid-route and tries to stop and chat."},
    {"label": "Guild Scholar",          "hp": 6,  "ac": 10, "useful": False, "note": "Stops to document things. Fascinating observations. Terrible timing."},
    {"label": "Informant",              "hp": 8,  "ac": 11, "useful": True,  "note": "Knows the area well. Can identify cover if things go wrong."},
    {"label": "Child",                  "hp": 4,  "ac": 9,  "useful": False, "note": "Fast when scared. Cries loudly otherwise."},
    {"label": "Cult Defector",          "hp": 8,  "ac": 11, "useful": False, "note": "Paranoid. Sees pursuit everywhere. Sometimes right."},
    {"label": "Injured Mage",           "hp": 10, "ac": 11, "useful": True,  "note": "One spell left. Saves it for the worst moment."},
    {"label": "Diplomat",               "hp": 6,  "ac": 10, "useful": False, "note": "Insists on negotiating with the ambushers."},
    {"label": "Last of a Fallen Party", "hp": 12, "ac": 13, "useful": True,  "note": "Grieving but capable. Fights if cornered."},
    {"label": "Street Kid",             "hp": 6,  "ac": 11, "useful": True,  "note": "Knows every back alley. Can spot a tail on DC 10 Perception."},
]

ITEM_ARCHETYPES = [
    {"label": "Sealed Diplomatic Correspondence", "handling": "Keep dry, do not open, do not let it leave your sight", "fragility": "medium"},
    {"label": "Void Shard Containment Vessel",    "handling": "Do not strike, no direct magic, keep upright at all times", "fragility": "extreme"},
    {"label": "Soul Vial Collection",             "handling": "Individually wrapped — one breaks, the soul is gone", "fragility": "high"},
    {"label": "Rare Medical Reagents",            "handling": "Temperature sensitive — keep away from heat sources", "fragility": "medium"},
    {"label": "Evidence Package",                 "handling": "Chain of custody — do not let anyone else handle it", "fragility": "low"},
    {"label": "Arcane Relay Component",           "handling": "Hums near magic — keep away from spellcasters until delivered", "fragility": "high"},
    {"label": "Historical Artifact",              "handling": "Wrapped carefully — physical damage destroys its value", "fragility": "high"},
    {"label": "Blackmail Material",               "handling": "If intercepted the mission is already failed", "fragility": "low"},
    {"label": "Living Specimen",                  "handling": "Contained but aware — do not agitate, do not open the case", "fragility": "extreme"},
    {"label": "Faction Payment",                  "handling": "Heavy. Obvious. Everyone can tell what it is.", "fragility": "low"},
]


# ---------------------------------------------------------------------------
# Ambush goal by opposing faction
# ---------------------------------------------------------------------------

FACTION_AMBUSH_TENDENCY: Dict[str, List[str]] = {
    "Obsidian Lotus":       ["steal", "steal", "capture"],
    "Glass Sigil":          ["steal", "steal", "capture"],
    "Brother Thane's Cult": ["capture", "capture", "kill"],
    "Serpent Choir":        ["capture", "kill", "steal"],
    "Argent Blades":        ["kill", "kill", "capture"],
    "Iron Fang Consortium": ["steal", "steal", "kill"],
    "Tower Authority":      ["capture", "capture", "kill"],
    "Wardens of Ash":       ["capture", "kill"],
    "Patchwork Saints":     ["kill", "capture"],
}

def _ambush_goal(opposing_faction: str) -> str:
    for k, v in FACTION_AMBUSH_TENDENCY.items():
        if k.lower() in opposing_faction.lower():
            return random.choice(v)
    return random.choice(["kill", "capture", "steal"])


# ---------------------------------------------------------------------------
# Traps for DM reference overlay
# ---------------------------------------------------------------------------

TRAP_TYPES = [
    {"name": "Trip Wire",      "effect": "DC 13 Perception to spot. Triggered: DC 12 Dex save or prone, 1d4 damage"},
    {"name": "Pit Trap",       "effect": "DC 14 Perception. Triggered: DC 13 Dex save or 2d6 fall, restrained"},
    {"name": "Net Drop",       "effect": "DC 13 Perception. Triggered: DC 13 Str save or restrained"},
    {"name": "Smoke Canister", "effect": "DC 12 Perception. Triggered: 20ft smoke cloud, heavily obscured 3 rounds"},
    {"name": "Alarm Bell",     "effect": "DC 11 Perception. Triggered: ambush gains surprise round"},
    {"name": "Grease Patch",   "effect": "DC 12 Perception. Triggered: DC 12 Acrobatics or prone, difficult terrain"},
    {"name": "Blinding Flash", "effect": "DC 14 Perception. Triggered: DC 13 Con save or blinded 1 round"},
    {"name": "Dart Trap",      "effect": "DC 13 Perception. Triggered: +5 ranged attack, 1d6 + DC 12 Con or poisoned"},
    {"name": "False Floor",    "effect": "DC 15 Perception. Triggered: 1d6 fall, separated from group"},
    {"name": "Noise Maker",    "effect": "DC 10 Perception. Triggered: 1-in-4 chance draws 1d4 extra grunts"},
]


# ---------------------------------------------------------------------------
# Outcome states
# ---------------------------------------------------------------------------

OUTCOME_STATES = {
    "intact":   {"label": "Delivered intact",          "pay_mult": 1.0,  "rep": +1, "debt": False},
    "damaged":  {"label": "Delivered damaged/wounded", "pay_mult": 0.5,  "rep":  0, "debt": False},
    "lost":     {"label": "Lost — not delivered",      "pay_mult": 0.0,  "rep": -1, "debt": False},
    "dead":     {"label": "Dead or destroyed",         "pay_mult": 0.0,  "rep": -2, "debt": True},
}


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

async def _ollama(prompt: str, system: str = "", tokens: int = 1200) -> str:
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
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("escort_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[ESCORT] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[ESCORT] Ollama error: {e}")
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
    target: Dict,
    vet: Dict,
    ambush_goal: str,
    pickup_location: str,
    delivery_location: str,
) -> Dict:
    title    = mission.get("title", "Escort Contract")
    faction  = mission.get("faction", "Independent")
    opposing = mission.get("opposing_faction") or "Unknown Threat"
    body     = mission.get("body") or mission.get("description") or ""
    is_item  = target.get("is_item", False)

    prompt = f"""Write the briefing for a D&D escort mission module.

Mission: {title}
Hiring faction: {faction}
Target: {target['label']} ({'item' if is_item else 'person'})
Pickup: {pickup_location}
Delivery: {delivery_location}
Known threat: {opposing} — goal is to {ambush_goal} the target
Vetting style: {vet['style']}
Notes: {body[:300]}

Write a briefing from the contact. Include what needs escorting and why,
pickup and delivery locations, the known threat, and that an ambush is
likely but location is unknown.

Return JSON only:
{{
  "contact_speech": "2-3 paragraphs",
  "pickup_desc": "1 sentence",
  "delivery_desc": "1 sentence on delivery location and who receives",
  "threat_note": "1 sentence on the threat",
  "special_instructions": "handling or behaviour requirements"
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    if not data:
        data = {
            "contact_speech":       f"Get {target['label']} from {pickup_location} to {delivery_location}. {opposing} will try to {ambush_goal} them. Don't let that happen.",
            "pickup_desc":          f"Target is waiting at {pickup_location}.",
            "delivery_desc":        f"Deliver to the contact at {delivery_location}.",
            "threat_note":          f"{opposing} are moving on this. Expect an ambush.",
            "special_instructions": target.get("handling", "Keep them safe."),
        }
    return data


async def _generate_target_personality(target: Dict, faction: str) -> str:
    if target.get("is_item"):
        return f"An inanimate object. {target.get('handling', 'Handle with care.')} It will not cooperate or resist."

    prompt = f"""Write 2 sentences about how this escort target behaves during the journey.

Target: {target['label']}
Faction: {faction}
Useful in combat: {target.get('useful', False)}
Note: {target.get('note', '')}

Focus on behaviour — do they help, hinder, complain, stay quiet?
No JSON — just the text."""

    text = await _ollama(prompt, tokens=200)
    return text or target.get("note", "Stays close and says little.")


async def _generate_delivery_scene(mission: dict, target: Dict, delivery_location: str) -> str:
    prompt = f"""Write 2 sentences describing the delivery scene for a D&D escort mission.

Party arrives at {delivery_location} with {target['label']}.
The receiving contact is already waiting.
Faction: {mission.get('faction', 'Independent')}

Describe the receiving party's reaction and the handoff. No JSON."""

    text = await _ollama(prompt, tokens=200)
    return text or f"The contact is waiting at {delivery_location}. They take the target without ceremony and disappear inside."


# ---------------------------------------------------------------------------
# A1111 — two maps, same prompt, different seeds
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
            logger.info(f"[ESCORT] A1111 not ready (attempt {attempt}/10) — waiting 30s…")
            await asyncio.sleep(30)
    logger.warning("[ESCORT] A1111 unavailable after 10 attempts")
    return False


async def _generate_escort_maps(
    pickup: str,
    delivery: str,
    faction: str,
    out_dir: Path,
) -> Tuple[Optional[Path], Optional[Path]]:
    # Escort is always town/exterior
    lora_name   = os.getenv("A1111_MAP_LORA_TOWN", "EnvyFluxFantasyTownMap01")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    triggers    = os.getenv("A1111_MAP_TOWN_TRIGGERS", "detailed, map, village")

    faction_tint = {
        "Obsidian Lotus":   "shadow district, minimal signage, concealed routes, dark alleys",
        "Glass Sigil":      "wealth district, elegant facades, clean wide streets",
        "Patchwork Saints": "community district, mismatched signs, lived-in narrow streets",
        "Wizards Tower":    "arcane district, glowing markers, restricted zone signage",
        "Wardens of Ash":   "utilitarian district, grey stone, military checkpoint aesthetic",
        "Tower Authority":  "official district, enforcement colours, regulation signage",
        "Argent Blades":    "mercenary quarter, weapons visible, professional storefronts",
        "Serpent Choir":    "shadowed religious district, cult markings, dim lantern light",
    }.get(faction, "mixed city district, high fantasy cyberpunk fusion")

    positive = ", ".join(filter(None, [
        f"<lora:{lora_name}:{lora_weight}>",
        triggers,
        "top-down city map, large area overview, escort route",
        "narrow streets and chokepoints limiting movement, dense urban layout",
        "buildings packed close, few open spaces, natural channeling terrain",
        "market lanes, alleyways, bridges, canal paths visible",
        faction_tint,
        "high fantasy cyberpunk fusion, wealth-stratified technology",
    ]))
    route_name = f"{pickup} to {delivery}"
    negative = "characters, people, isometric, perspective, watermark, text"

    clean_path = out_dir / "escort_map_clean.png"
    dm_path = out_dir / "escort_map_dm.png"

    from src.news_feed import a1111_lock
    from src.resource_cop import wait_for_a1111_turn
    from src.mission_builder.vtt_renderer import save_vtt_battlemap

    seed_clean = random.randint(1, 999999)
    seed_dm    = random.randint(1, 999999)

    payload = {
        "prompt": positive, "negative_prompt": negative,
        "width": 1024, "height": 1024, "steps": 20,
        "cfg_scale": 1.0, "sampler_name": "Euler",
        "seed": seed_clean,
    }
    _map_ckpt = os.getenv("A1111_MAP_CHECKPOINT", "")
    if _map_ckpt:
        override: dict = {"sd_model_checkpoint": _map_ckpt}
        payload["override_settings"] = override
        payload["override_settings_restore_afterwards"] = True

    # --- Clean map (player-facing) ---
    max_map_attempts = 10
    decision = await wait_for_a1111_turn("escort_map", max_wait_seconds=60)
    if not decision.run_now:
        logger.info(f"[ESCORT] A1111 deferred by resource cop: {decision.reason}")
        save_vtt_battlemap(clean_path, None, context={"title": route_name, "location": route_name, "prompt": positive, "kind": "escort street"})
        save_vtt_battlemap(dm_path, None, context={"title": route_name, "location": route_name, "prompt": positive, "kind": "escort street dm"})
        return clean_path, dm_path

    for map_attempt in range(1, max_map_attempts + 1):
        try:
            async with a1111_lock:
                async with httpx.AsyncClient(timeout=600.0) as c:
                    r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                    r.raise_for_status()
                    images = r.json().get("images", [])
            if not images:
                raise RuntimeError("A1111 returned no images")
            from src.mission_builder.vtt_renderer import save_vtt_battlemap
            save_vtt_battlemap(clean_path, images[0], context={"title": route_name, "location": route_name, "prompt": positive, "kind": "escort street"})
            logger.info("[ESCORT] Clean map saved")
            break
        except Exception as e:
            logger.warning(f"[ESCORT] Clean map attempt {map_attempt}/{max_map_attempts} failed: {e}")
            if map_attempt < max_map_attempts:
                wait = min(30 * map_attempt, 120)
                logger.info(f"[ESCORT] Retrying clean map in {wait}s…")
                await asyncio.sleep(wait)
    else:
        logger.error("[ESCORT] Clean map generation failed after 10 attempts — using deterministic fallback")
        from src.mission_builder.vtt_renderer import save_vtt_battlemap
        save_vtt_battlemap(clean_path, None, context={"title": route_name, "location": route_name, "prompt": positive, "kind": "escort street"})
        logger.info(f"[ESCORT] Deterministic VTT map saved: {clean_path.name}")

    await asyncio.sleep(2)

    # --- DM map (ambush point & traps overlay reference) ---
    payload["seed"] = seed_dm
    for map_attempt in range(1, max_map_attempts + 1):
        try:
            async with a1111_lock:
                async with httpx.AsyncClient(timeout=600.0) as c:
                    r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                    r.raise_for_status()
                    images = r.json().get("images", [])
            if not images:
                raise RuntimeError("A1111 returned no images")
            from src.mission_builder.vtt_renderer import save_vtt_battlemap
            save_vtt_battlemap(dm_path, images[0], context={"title": route_name, "location": route_name, "prompt": positive, "kind": "escort street dm"})
            logger.info("[ESCORT] DM map saved")
            break
        except Exception as e:
            logger.warning(f"[ESCORT] DM map attempt {map_attempt}/{max_map_attempts} failed: {e}")
            if map_attempt < max_map_attempts:
                wait = min(30 * map_attempt, 120)
                logger.info(f"[ESCORT] Retrying DM map in {wait}s…")
                await asyncio.sleep(wait)
    else:
        logger.error("[ESCORT] DM map generation failed after 10 attempts — using deterministic fallback")
        from src.mission_builder.vtt_renderer import save_vtt_battlemap
        save_vtt_battlemap(dm_path, None, context={"title": route_name, "location": route_name, "prompt": positive, "kind": "escort street dm"})
        logger.info(f"[ESCORT] Deterministic VTT DM map saved: {dm_path.name}")

    return clean_path, dm_path


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _target_card(target: Dict, personality: str, fc: str) -> str:
    is_item = target.get("is_item", False)
    useful_badge = (
        '<span style="background:#2a6a2a;color:white;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:8px;">CAN HELP</span>'
        if target.get("useful") else ""
    )
    return (
        f'<div style="border:2px solid {fc};border-radius:8px;padding:14px 18px;margin:16px 0;background:#f5fff5;">'
        f'<h3 style="margin:0 0 6px;">{"📦 Item" if is_item else "👤 Escort Target"} — {_e(target["label"])}{useful_badge}</h3>'
        + (f'<div style="font-size:13px;margin:4px 0;"><strong>HP:</strong> {target.get("hp","—")} &nbsp;|&nbsp; <strong>AC:</strong> {target.get("ac","—")}</div>' if not is_item else "")
        + (f'<div style="font-size:13px;margin:4px 0;color:#7b1e1e;"><strong>Handling:</strong> {_e(target.get("handling",""))}</div>' if is_item else "")
        + f'<div style="font-size:13px;margin:8px 0;font-style:italic;">{_e(personality)}</div>'
        + f'</div>'
    )


def _dm_overlay(traps: List[Dict], ambush_goal: str, opposing: str) -> str:
    trap_rows = "".join(
        f'<tr style="background:{"#fff5f5" if i%2==0 else "white"};">'
        f'<td style="padding:6px 10px;font-weight:bold;">{_e(t["name"])}</td>'
        f'<td style="padding:6px 10px;font-size:13px;">{_e(t["effect"])}</td>'
        f'</tr>'
        for i, t in enumerate(traps)
    )
    return (
        f'<div style="background:#fff0e8;border:2px solid #c85320;border-radius:8px;padding:14px 18px;margin:16px 0;">'
        f'<h3 style="margin:0 0 8px;color:#c85320;">DM Reference — Ambush Setup</h3>'
        f'<div style="font-size:13px;margin-bottom:10px;">'
        f'<strong>Ambusher:</strong> {_e(opposing)} &nbsp;|&nbsp; '
        f'<strong>Goal:</strong> {_e(ambush_goal.upper())} the target &nbsp;|&nbsp; '
        f'<strong>Ambush point:</strong> randomised — marked on DM map'
        f'</div>'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="background:#e8d0c0;">'
        f'<th style="padding:6px 10px;text-align:left;">Trap</th>'
        f'<th style="padding:6px 10px;text-align:left;">Effect</th>'
        f'</tr></thead><tbody>{trap_rows}</tbody></table>'
        f'</div>'
    )


def _outcome_table() -> str:
    rows = "".join(
        f'<tr style="background:{"#f5f5f5" if i%2==0 else "white"};">'
        f'<td style="padding:6px 10px;">{_e(v["label"])}</td>'
        f'<td style="padding:6px 10px;text-align:center;">{int(v["pay_mult"]*100)}%</td>'
        f'<td style="padding:6px 10px;text-align:center;">{v["rep"]:+d}</td>'
        f'<td style="padding:6px 10px;text-align:center;">{"Yes" if v["debt"] else "—"}</td>'
        f'</tr>'
        for i, (k, v) in enumerate(OUTCOME_STATES.items())
    )
    return (
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        f'<thead><tr style="background:#e8e0d0;">'
        f'<th style="padding:6px 10px;text-align:left;">Outcome</th>'
        f'<th style="padding:6px 10px;">Pay</th>'
        f'<th style="padding:6px 10px;">Rep</th>'
        f'<th style="padding:6px 10px;">Debt</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
    )


def render_escort_module(
    mission: dict,
    target: Dict,
    vet: Dict,
    briefing: Dict,
    personality: str,
    traps: List[Dict],
    pickup_location: str,
    delivery_location: str,
    delivery_scene: str,
    ambush_goal: str,
    strength: Dict[str, Any],
    clean_map: Optional[Path],
    dm_map: Optional[Path],
    out_dir: Path,
) -> str:
    title    = mission.get("title", "Escort Contract")
    faction  = mission.get("faction", "Independent")
    opposing = mission.get("opposing_faction") or "Unknown Threat"
    fc       = _faction_color(faction)

    clean_map_html = ""
    if clean_map and clean_map.exists():
        rel = clean_map.relative_to(out_dir)
        clean_map_html = (
            f'<div style="text-align:center;margin:16px 0;">'
            f'<div style="font-weight:bold;margin-bottom:6px;">Player Map</div>'
            f'<img src="{rel}" style="max-width:100%;border:3px solid {fc};border-radius:8px;" alt="Route Map">'
            f'</div>'
        )

    dm_map_html = ""
    if dm_map and dm_map.exists():
        rel = dm_map.relative_to(out_dir)
        dm_map_html = (
            f'<div style="text-align:center;margin:16px 0;">'
            f'<div style="font-weight:bold;color:#c85320;margin-bottom:6px;">DM Reference Map — Ambush Point & Traps</div>'
            f'<img src="{rel}" style="max-width:100%;border:3px solid #c85320;border-radius:8px;" alt="DM Map">'
            f'</div>'
        )
    scaling_html = (
        f'<div style="background:#eef6ff;border:1px solid #3a6898;border-radius:6px;'
        f'padding:10px 14px;margin:14px 0;font-size:13px;">'
        f'<strong>Live Party Scaling:</strong> {_e(_party_scaling_note(strength))} '
        f'Ambush pressure and trap count are tuned from this read.</div>'
    )

    body = f"""
<div style="border-left:4px solid {fc};padding:12px 18px;margin:20px 0;background:#fafafa;border-radius:0 8px 8px 0;">
  <h2 style="margin:0 0 8px;">Briefing</h2>
  <div style="white-space:pre-line;font-style:italic;margin:10px 0;">{_e(briefing.get("contact_speech",""))}</div>
  <div style="margin-top:10px;font-size:13px;display:grid;grid-template-columns:1fr 1fr;gap:8px;">
    <div><strong>Pickup:</strong> {_e(briefing.get("pickup_desc",""))}</div>
    <div><strong>Delivery:</strong> {_e(briefing.get("delivery_desc",""))}</div>
    <div><strong>Threat:</strong> {_e(briefing.get("threat_note",""))}</div>
    <div><strong>Instructions:</strong> {_e(briefing.get("special_instructions",""))}</div>
  </div>
</div>

{_target_card(target, personality, fc)}

{scaling_html}

<div style="background:#e8f0f8;border:1px solid #3a6898;border-radius:6px;padding:12px 16px;margin:16px 0;">
  <h3 style="margin:0 0 6px;">Party Vetting — {_e(vet["style"])}</h3>
  <div style="font-size:13px;"><strong>Check:</strong> {_e(vet["check"])}</div>
  <div style="font-size:13px;margin-top:4px;"><strong>Pass:</strong> {_e(vet["pass_result"])}</div>
  <div style="font-size:13px;margin-top:2px;"><strong>Fail:</strong> {_e(vet["fail_result"])}</div>
</div>

<h2>Maps</h2>
{clean_map_html}
{dm_map_html}
{_dm_overlay(traps, ambush_goal, opposing)}

<h2>Delivery</h2>
<div style="font-style:italic;padding:12px 16px;background:#fafafa;border-radius:6px;margin:12px 0;">{_e(delivery_scene)}</div>

<h2>Outcomes</h2>
{_outcome_table()}

<hr>
<h2>Session Record</h2>
<div style="background:#e8f5e8;border:1px solid #2a6a2a;border-radius:6px;padding:14px 18px;">
  <p><strong>Outcome:</strong>
    <select style="font-family:inherit;margin-left:8px;">
      <option>Delivered intact</option>
      <option>Delivered damaged/wounded</option>
      <option>Lost</option>
      <option>Dead or destroyed</option>
    </select>
  </p>
  <p><strong>Ambush triggered:</strong> <input type="checkbox"></p>
  <p><strong>Vetting passed:</strong> <input type="checkbox"></p>
  <textarea rows="3" style="width:100%;font-family:inherit;" placeholder="Session notes..."></textarea>
</div>
"""
    return _page(title, body, faction)


def render_escort_session(
    mission: dict,
    target: Dict,
    vet: Dict,
    briefing: Dict,
    personality: str,
    clean_map: Optional[Path],
    delivery_scene: str,
    out_dir: Path,
) -> str:
    title  = mission.get("title", "Escort Contract")
    faction= mission.get("faction", "Independent")
    fc     = _faction_color(faction)

    def _card(heading: str, content: str, color: str = "#b8923a") -> str:
        return (
            f'<div style="border:2px solid {color};border-radius:10px;padding:18px 22px;margin:20px 0;background:white;">'
            f'<h2 style="margin:0 0 12px;color:{color};">{heading}</h2>{content}</div>'
        )

    map_html = ""
    if clean_map and clean_map.exists():
        rel = clean_map.relative_to(out_dir)
        map_html = f'<img src="{rel}" style="max-width:100%;border-radius:6px;margin:10px 0;" alt="Route Map">'

    cards = ""

    cards += _card(
        "Briefing",
        f'<p style="font-style:italic;">{_e(briefing.get("contact_speech","")[:400])}</p>'
        f'<p><strong>Pickup:</strong> {_e(briefing.get("pickup_desc",""))}</p>'
        f'<p><strong>Threat:</strong> {_e(briefing.get("threat_note",""))}</p>',
        fc,
    )

    useful_note = (
        f'<p style="color:#2a6a2a;font-weight:bold;">Can assist — {_e(target.get("note",""))}</p>'
        if target.get("useful") else ""
    )
    cards += _card(
        f"Target — {_e(target['label'])}",
        f'{map_html}'
        + (f'<p><strong>HP:</strong> {target.get("hp","—")} | <strong>AC:</strong> {target.get("ac","—")}</p>' if not target.get("is_item") else "")
        + (f'<p style="color:#7b1e1e;"><strong>Handling:</strong> {_e(target.get("handling",""))}</p>' if target.get("is_item") else "")
        + f'<p style="font-style:italic;">{_e(personality)}</p>'
        + useful_note
        + f'<div style="background:#e8f0f8;border-radius:6px;padding:10px;margin-top:8px;">'
        + f'<strong>Vetting:</strong> {_e(vet["check"])}</div>',
        fc,
    )

    cards += _card(
        "Delivery",
        f'<p style="font-style:italic;">{_e(delivery_scene)}</p>'
        f'<p><strong>Outcome:</strong> <select style="font-family:inherit;">'
        f'<option>Intact</option><option>Damaged</option>'
        f'<option>Lost</option><option>Dead/Destroyed</option>'
        f'</select></p>'
        f'<p><strong>Ambush triggered:</strong> <input type="checkbox"></p>'
        f'<textarea rows="2" style="width:100%;font-family:inherit;" placeholder="Notes..."></textarea>',
        "#2a6a2a",
    )

    body = (
        f'<div style="text-align:center;margin:0 0 24px;">'
        f'<h1 style="color:{fc};">{_e(title)}</h1>'
        f'<div style="font-size:14px;color:#666;">{_e(faction)} — Escorting: {_e(target["label"])}</div>'
        f'</div>' + cards
    )
    return _page(title, body, faction)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


def _party_strength() -> Dict[str, Any]:
    """Read live PC snapshots; copied here so escort stays standalone."""
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
        logger.warning(f"[ESCORT] Could not read live party snapshots: {e}")
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


async def build_escort_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title    = mission.get("title", "Escort Contract")
    faction  = mission.get("faction", "Independent")
    opposing = mission.get("opposing_faction") or "Unknown Threat"
    tier     = mission.get("tier", "standard")

    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[ESCORT] Building: {title!r} | faction={faction} | tier={tier}")

    strength    = _party_strength()
    vet         = _get_vet(faction)
    ambush_goal = _ambush_goal(opposing)
    is_item     = random.random() < 0.35

    if is_item:
        base = random.choice(ITEM_ARCHETYPES)
        target = {**base, "is_item": True, "hp": None, "ac": None, "useful": False}
    else:
        base = random.choice(PERSON_ARCHETYPES)
        target = {**base, "is_item": False}

    trap_count = min(6, max(2, (strength["party_size"] // 2) + max(0, strength["max_level"] - 4) // 2))
    traps      = random.sample(TRAP_TYPES, min(trap_count, len(TRAP_TYPES)))

    pickup_options   = [
        "Adventurers Guild side entrance", "a safehouse in Hearthstone District",
        "the Cobbleway Market food court",  "a private room at the Floating Bazaar",
        "a back alley off Neon Row",        "the Tower challenger staging area",
    ]
    delivery_options = [
        "a contact at the Grand Forum",       "a private residence in Diplomats Row",
        "the Artisan Quarter scriptorium",    "a Patchwork Saints community hall",
        "the Scrapworks loading bay",         "a vessel at the Ironworks shipping yards",
    ]
    pickup_location   = random.choice(pickup_options)
    delivery_location = random.choice(delivery_options)

    logger.info(f"[ESCORT] Target={target['label']} | ambush_goal={ambush_goal} | traps={len(traps)}")

    briefing_task    = asyncio.create_task(_generate_briefing(mission, target, vet, ambush_goal, pickup_location, delivery_location))
    personality_task = asyncio.create_task(_generate_target_personality(target, faction))
    briefing, personality = await asyncio.gather(briefing_task, personality_task)

    delivery_scene = await _generate_delivery_scene(mission, target, delivery_location)

    clean_map = dm_map = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            clean_map, dm_map = await _generate_escort_maps(pickup_location, delivery_location, faction, out_dir)
        else:
            logger.warning("[ESCORT] A1111 not available — skipping maps")

    from src.mission_builder.mimir_module import create_module as _mc, upload_map as _mu, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="escort")
    if _mimir_id and clean_map:
        await _mu(_mimir_id, clean_map, "Escort Route Map")
    module_html = render_escort_module(
        mission, target, vet, briefing, personality, traps,
        pickup_location, delivery_location, delivery_scene,
        ambush_goal, strength, clean_map, dm_map, out_dir,
    )
    module_html += _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")

    session_html = render_escort_session(
        mission, target, vet, briefing, personality,
        clean_map, delivery_scene, out_dir,
    )
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    dm_md = (
        f"## Escort DM Guide\n"
        f"### Target\n"
        f"- {target['label']} ({'item' if target.get('is_item') else 'person'})\n"
        f"- Personality/behavior: {personality}\n"
        f"- Handling: {target.get('handling', target.get('note', 'Keep the target alive and moving.'))}\n\n"
        f"### Ambush Truth\n"
        f"- Opposing faction: {opposing}\n"
        f"- Ambush goal: {ambush_goal}\n"
        f"- Trap count: {len(traps)}\n"
        f"- The DM reference map is the only place traps and ambush points should be visible.\n\n"
        f"### Delivery\n{delivery_scene}\n\n"
        f"### Live Scaling\n{_party_scaling_note(strength)}"
    )
    players_md = (
        f"## Player Brief\n{briefing.get('contact_speech', '')}\n\n"
        f"### Pickup And Delivery\n"
        f"- Pickup: {briefing.get('pickup_desc', pickup_location)}\n"
        f"- Delivery: {briefing.get('delivery_desc', delivery_location)}\n"
        f"- Known threat: {briefing.get('threat_note', opposing)}\n\n"
        f"### Target\n"
        f"- {target['label']}\n"
        f"- {personality}\n"
        f"- Special instructions: {briefing.get('special_instructions', target.get('handling', 'Keep them safe.'))}\n\n"
        f"### Vetting\n{vet['style']} Check: {vet['check']}."
    )
    chart_md = (
        f"## Escort Chart Pack\n"
        f"### Vetting\n"
        f"- Check: {vet['check']}\n"
        f"- Pass: {vet['pass_result']}\n"
        f"- Fail: {vet['fail_result']}\n\n"
        f"### Traps\n"
        + "\n".join(f"| {t['name']} | {t['effect']} |" for t in traps)
        + "\n\n### Outcomes\n"
        + "\n".join(f"| {v['label']} | Pay {int(v['pay_mult'] * 100)}% | Rep {v['rep']:+d} | Debt {'Yes' if v['debt'] else 'No'} |" for v in OUTCOME_STATES.values())
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, faction, players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",    "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",         "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Vetting & Outcomes","type": "custom",      "content": chart_md},
        ])
    map_paths = [p for p in (clean_map, dm_map) if p]
    maps_name = write_maps_page(out_dir, title, faction, map_paths)
    box_components = component_links(has_maps=bool(maps_name))

    try:
        from src.mission_builder.html_renderer import render_index
        index_html = render_index(
            novel_title=title, faction=faction, tier=tier,
            cr=mission_cr(mission),
            player_name=mission.get("player_name", "") or "Open",
            chapters=[],
            components=box_components,
            chart_pack=None,
            map_count=2 if (clean_map and dm_map) else (1 if clean_map else 0),
        )
        index_path = out_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
    except Exception as _e:
        logger.warning(f"[ESCORT] index.html failed: {_e}")
        index_path = out_dir / "module.html"

    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as _e:
        logger.warning(f"[ESCORT] Could not write module_slug: {_e}")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[ESCORT] Complete: {title!r} → {out_dir.name}")
    return index_path
