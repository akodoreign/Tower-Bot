"""
assassination_pipeline.py — Pipeline for Assassination mission modules.

An assassination is a morally complex contract mission. The party must
surveil a target, plan their approach, execute (or abort), and exfiltrate.
The target is characterised — the module includes motive, security profile,
daily routine, and moral weight. Multiple approaches are always viable.

Flow:
  1. Briefing      — client contact, target, contract terms, moral hook
  2. Target        — characterisation, security profile, daily routine
  3. Surveillance  — 3 lead locations/times the party can observe the target
  4. Approaches    — 3 viable methods (social, stealth, direct)
  5. Execution     — the hit: position, window, guards, abort conditions
  6. Exfiltration  — escape route, heat level, tail possibility
  7. Map           — private interior map (dining room / meeting chamber)
  8. Module HTML + Session HTML + index.html + zip + DB slug

Exported:
    build_assassination_module(mission: dict, out_dir: Path) -> Path
    is_assassination_mission(mission_type: str) -> bool
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

_ASSASSINATION_KEYWORDS = {
    "assassination", "assassinate", "eliminate the target", "eliminate target",
    "kill the target", "kill target", "hit contract", "take out", "neutralize",
    "mark for death", "contract kill", "wet work", "remove target",
}

def is_assassination_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    return any(k in low for k in _ASSASSINATION_KEYWORDS)


# ---------------------------------------------------------------------------
# Target security profiles
# ---------------------------------------------------------------------------

SECURITY_PROFILES: Dict[str, Dict] = {
    "light": {
        "label":        "Light Security",
        "guards":       "1-2 personal attendants, not combat-trained",
        "guard_cr":     "1/4",
        "guard_count":  (1, 2),
        "patrol":       "No formal patrol — attendants stay close",
        "alarm":        "Shouting — brings 1d4 bystanders, not guards",
        "escape_heat":  "Low — target not publicly important enough for a manhunt",
    },
    "moderate": {
        "label":        "Moderate Security",
        "guards":       "2-4 hired bodyguards, competent fighters",
        "guard_cr":     "1",
        "guard_count":  (2, 4),
        "patrol":       "Two-person patrol, 10-minute rotation",
        "alarm":        "Whistle — brings all guards within 1 minute",
        "escape_heat":  "Moderate — faction will investigate, may issue bounty",
    },
    "heavy": {
        "label":        "Heavy Security",
        "guards":       "4-8 elite guards, ex-military or faction enforcers",
        "guard_cr":     "2",
        "guard_count":  (4, 8),
        "patrol":       "Three overlapping patrols, staggered timing",
        "alarm":        "Signal crystal — ward authority response in 3 minutes",
        "escape_heat":  "High — faction response within hours, description distributed",
    },
    "extreme": {
        "label":        "Extreme Security",
        "guards":       "8+ elite guards with caster support, permanent wards",
        "guard_cr":     "3",
        "guard_count":  (8, 12),
        "patrol":       "Constant coverage, overlapping line-of-sight, magic detection",
        "alarm":        "Arcane alarm — immediate response, area lockdown",
        "escape_heat":  "Extreme — Tower Authority involvement, full district alert",
    },
}

_DEFAULT_SECURITY = SECURITY_PROFILES["moderate"]

def _get_security_profile(tier: str) -> Dict:
    mapping = {
        "standard": "light",
        "seasoned": "moderate",
        "elite":    "heavy",
        "legend":   "extreme",
    }
    key = mapping.get((tier or "standard").lower(), "moderate")
    return SECURITY_PROFILES[key]


# ---------------------------------------------------------------------------
# Faction client profiles
# ---------------------------------------------------------------------------

FACTION_CLIENT_STYLES: Dict[str, str] = {
    "Obsidian Lotus":          "clinical, professional, no-names, payment in untraceable EC, cell structure",
    "Glass Sigil":             "information broker tone, payment in debt erasure or future favours, plausible deniability",
    "Iron Fang Consortium":    "business-like, contract terms in writing, breach clause if party is identified",
    "Argent Blades":           "mercenary bluntness, upfront partial payment, rest on delivery with a witnessed corpse",
    "Wardens of Ash":          "grim necessity, internal disciplinary action framed as a contract",
    "Tower Authority":         "never direct — always laundered through a third party, deniable",
    "Serpent Choir":           "ritual framing, target is a 'sacrifice', client expects a specific method",
    "Brother Thane's Cult":    "fervent, calls it justice, expects dramatic proof of death",
    "Patchwork Saints":        "community protection — target has wronged the neighbourhood, no ceremony",
    "Guild of Ashen Scrolls":  "scholarly precision, contract specifies method must leave evidence intact",
    "Wizards Tower":           "bureaucratic removal, framed as a security review, very indirect language",
}

_DEFAULT_CLIENT_STYLE = "professional, payment on delivery, no names exchanged"

def _get_client_style(faction: str) -> str:
    for k, v in FACTION_CLIENT_STYLES.items():
        if k.lower() in faction.lower():
            return v
    return _DEFAULT_CLIENT_STYLE


# ---------------------------------------------------------------------------
# Location vocabulary for the hit site
# ---------------------------------------------------------------------------

HIT_SITE_TYPES: Dict[str, str] = {
    "private dining":   "private dining room or meeting chamber with servant entrance",
    "residence":        "private residence — bedroom access, servant quarters, locked study",
    "office":           "faction office — front desk area, private back room, emergency exit",
    "transit":          "moving target on foot or in a carriage — fixed window of opportunity",
    "public event":     "public gathering — crowd cover but witnesses everywhere",
    "arena":            "arena box or private viewing terrace — security above and below",
    "warehouse":        "private warehouse meeting — empty building, single approach",
    "safehouse":        "target's personal safehouse — minimal security, high concealment",
}

def _pick_hit_site(faction: str, tier: str) -> str:
    # Faction tendencies
    faction_low = faction.lower()
    if any(x in faction_low for x in ("lotus", "glass", "shadow")):
        return random.choice(["private dining", "safehouse", "warehouse"])
    if any(x in faction_low for x in ("authority", "tower", "warden")):
        return random.choice(["office", "arena", "public event"])
    if any(x in faction_low for x in ("cult", "choir")):
        return random.choice(["warehouse", "residence", "private dining"])
    # Tier tendencies — higher tier = higher security location
    if tier in ("elite", "legend"):
        return random.choice(["arena", "public event", "office"])
    return random.choice(list(HIT_SITE_TYPES.keys()))


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
            data    = await call_ollama(payload, timeout=180.0, caller="assassination", force=True)
            content = (data.get("message") or {}).get("content", "").strip()
            if content:
                return content
            logger.warning(f"[ASSASSIN] Empty response (attempt {attempt}/{max_attempts})")
        except Exception as e:
            logger.warning(f"[ASSASSIN] Ollama error attempt {attempt}/{max_attempts}: {e}")

        if attempt < max_attempts:
            wait = min(30 * attempt, 120)
            logger.info(f"[ASSASSIN] Retrying in {wait}s…")
            await asyncio.sleep(wait)

    logger.error("[ASSASSIN] All 10 attempts exhausted — returning empty string")
    return ""


def _clean_json(raw: str) -> str:
    raw = raw.replace("\x5c\x27", "\x27")
    raw = re.sub(r"['']", "'", raw)
    raw = re.sub(r"[""]", '"', raw)
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

async def _generate_briefing(mission: dict, security: Dict, client_style: str) -> Dict:
    title    = mission.get("title", "Unknown Contract")
    faction  = mission.get("faction", "Independent")
    body     = mission.get("body") or mission.get("description") or ""
    tier     = mission.get("tier", "standard")

    prompt = f"""You are writing the opening briefing for a D&D assassination mission module.

Contract: {title}
Client faction: {faction} — {client_style}
Security tier: {security['label']}
Mission notes: {body[:300]}

Write a briefing as if the client contact is speaking to the party. Include:
- The target (described, not named yet — DM fills name later)
- Why the contract exists (political, personal, business, or ideological)
- The moral hook — is this justice, murder, or something in between?
- Payment terms matching the faction style
- One clear warning: what happens if the party is identified

Return JSON only:
{{
  "contact_speech": "2-3 paragraphs — the client briefing the party",
  "target_desc": "physical description of the target, no name",
  "contract_reason": "why this person is marked — 2 sentences",
  "moral_hook": "the ethical complication — 1 sentence",
  "payment": "payment terms",
  "identification_warning": "1 sentence on what happens if party is identified"
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    if not data:
        data = {
            "contact_speech":         f"The {faction} has a problem. A person of significance needs to be removed — quietly, cleanly, and without trace back to us. You're being offered this because you're capable and discreet.",
            "target_desc":            "A well-dressed figure of middle years, cautious in public, more relaxed in private.",
            "contract_reason":        "The target has accumulated dangerous leverage over the faction. Removing them removes the threat.",
            "moral_hook":             "The target may not be guilty of what the client claims — the party will have to decide how much they trust the contract.",
            "payment":                "Half upfront, half on confirmed elimination.",
            "identification_warning": "If the party is identified, the client will deny all knowledge and may issue a counter-bounty.",
        }
    return data


async def _generate_target(mission: dict, security: Dict, hit_site: str) -> Dict:
    faction  = mission.get("faction", "Independent")
    tier     = mission.get("tier", "standard")
    body     = mission.get("body") or ""

    prompt = f"""You are building the target profile for a D&D assassination mission.

Client faction: {faction}
Security level: {security['label']} — {security['guards']}
Hit location type: {hit_site}
Mission notes: {body[:200]}

Generate:
1. A target name and role (generic — not a canon NPC)
2. The target's actual guilt or innocence (the DM secret)
3. Their daily routine — 3 time windows the party could observe or strike
4. Security arrangement (use the profile provided)
5. One piece of information that might change the party's mind about the contract

Return JSON only:
{{
  "target_name": "Name (Role / Title)",
  "target_role": "what they do, who they are",
  "dm_secret": "what the DM knows about actual guilt/innocence",
  "routine": [
    {{"time": "morning", "location": "...", "activity": "...", "guards_present": 0}},
    {{"time": "afternoon", "location": "...", "activity": "...", "guards_present": 0}},
    {{"time": "evening", "location": "...", "activity": "...", "guards_present": 0}}
  ],
  "security_note": "specific guard arrangement at the hit site",
  "conscience_trigger": "the detail that might give the party pause"
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    if not data:
        data = {
            "target_name":       "Veran Solt (District Liaison)",
            "target_role":       "Mid-level faction functionary with access to sealed records",
            "dm_secret":         "Solt has been feeding information to a third party but does not know the extent of the damage caused",
            "routine": [
                {"time": "morning",   "location": "personal office, 3rd floor",    "activity": "reviews correspondence alone",   "guards_present": 1},
                {"time": "afternoon", "location": "private dining room, guild hall", "activity": "lunches with two known associates", "guards_present": 2},
                {"time": "evening",   "location": "residence, upper district",       "activity": "retires early, one guard at door",  "guards_present": 1},
            ],
            "security_note":     "Two personal bodyguards rotate in 6-hour shifts. No magic detection. Single patrol past the residence at midnight.",
            "conscience_trigger": "The target has a young apprentice who clearly adores them — and the target treats them with genuine care.",
        }
    return data


async def _generate_surveillance(mission: dict, target: Dict) -> List[Dict]:
    faction  = mission.get("faction", "Independent")
    routine  = target.get("routine", [])
    name     = target.get("target_name", "the target")

    prompt = f"""Generate 3 surveillance opportunities for a D&D assassination mission.

Target: {name}
Daily routine: {json.dumps(routine, indent=2)}

Each surveillance lead:
- A specific time and place the party can watch the target
- What they can learn (route, guard timing, weakness, social pattern)
- The skill check to gather that intel without being noticed

Return JSON only:
{{
  "leads": [
    {{
      "label": "short name",
      "time_window": "when",
      "location": "where",
      "what_is_learnable": "what the party can discover",
      "check": "Skill DC XX — what the check does"
    }}
  ]
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    leads = (data or {}).get("leads", [])
    if len(leads) < 3:
        leads = [
            {"label": "Morning observation",    "time_window": "07:00-09:00", "location": "café across from the office",        "what_is_learnable": "target arrives alone, guard stays outside the building", "check": "Stealth DC 12 — observe without being noted"},
            {"label": "Afternoon dining watch", "time_window": "12:00-14:00", "location": "gallery overlooking the guild hall", "what_is_learnable": "target has a predictable lunch table, guard relaxes after 15 minutes", "check": "Perception DC 13 — clock the guard rotation"},
            {"label": "Evening route",           "time_window": "20:00-21:30", "location": "narrow street between guild hall and residence", "what_is_learnable": "target uses the same route every evening, 8-minute window with no patrol", "check": "Investigation DC 12 — map the gap in coverage"},
        ]
    return leads[:3]


async def _generate_approaches(mission: dict, target: Dict, security: Dict, hit_site: str) -> List[Dict]:
    name     = target.get("target_name", "the target")
    tier     = mission.get("tier", "standard")
    site_desc = HIT_SITE_TYPES.get(hit_site, hit_site)

    prompt = f"""Generate 3 viable approach options for a D&D assassination mission.

Target: {name}
Hit site type: {site_desc}
Security: {security['label']} — {security['guards']}
Guard patrol: {security['patrol']}
Alarm system: {security['alarm']}

The three approaches must be meaningfully different:
1. Social / infiltration — get close through deception or legitimate access
2. Stealth — covert entry, silent elimination, clean exit
3. Direct / distraction — aggressive entry or create a scene that isolates the target

Each approach must specify:
- The entry method
- The skill checks required (2-3 specific DCs)
- The key risk or complication
- What a partial success looks like (failed one check but not all)

Return JSON only:
{{
  "approaches": [
    {{
      "label": "Social",
      "entry_method": "...",
      "checks": ["Skill DC XX — ...", "Skill DC XX — ..."],
      "key_risk": "...",
      "partial_success": "..."
    }},
    {{
      "label": "Stealth",
      "entry_method": "...",
      "checks": ["Skill DC XX — ...", "Skill DC XX — ..."],
      "key_risk": "...",
      "partial_success": "..."
    }},
    {{
      "label": "Direct",
      "entry_method": "...",
      "checks": ["Skill DC XX — ...", "Skill DC XX — ..."],
      "key_risk": "...",
      "partial_success": "..."
    }}
  ]
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    approaches = (data or {}).get("approaches", [])
    if len(approaches) < 3:
        approaches = [
            {
                "label": "Social",
                "entry_method": "Pose as delivery staff or invited guests to gain entry before the guard checks credentials",
                "checks": ["Deception DC 14 — bluff past the door check", "Persuasion DC 13 — keep the contact calm during the approach"],
                "key_risk": "The target may recognise any party member known to the faction",
                "partial_success": "Party gains entry but is watched — window is narrow and a guard stays closer than planned",
            },
            {
                "label": "Stealth",
                "entry_method": "Night entry through the servant entrance or window ledge while the target is alone",
                "checks": ["Stealth DC 15 — bypass the patrol", "Athletics DC 12 — reach the entry point cleanly"],
                "key_risk": "The alarm triggers if any guard sees the party for more than 6 seconds",
                "partial_success": "One guard is alerted but not the alarm — the party has 2 rounds to complete the job and move",
            },
            {
                "label": "Direct",
                "entry_method": "Create a distraction (fire, brawl, loud dispute) that draws guards away and isolates the target",
                "checks": ["Performance or Deception DC 13 — make the distraction convincing", "Initiative — the target may react if combat breaks out nearby"],
                "key_risk": "Distraction raises general heat even if the target is eliminated cleanly",
                "partial_success": "Distraction works but one guard stays — must be neutralised quietly or the alarm triggers",
            },
        ]
    return approaches[:3]


async def _generate_exfiltration(mission: dict, security: Dict) -> Dict:
    faction   = mission.get("faction", "Independent")
    heat      = security.get("escape_heat", "Moderate")

    prompt = f"""Write the exfiltration section for a D&D assassination mission.

Client faction: {faction}
Security level: {security['label']}
Escape heat: {heat}

Generate:
1. Two viable escape routes from the hit site
2. What pursuit looks like (timing, force, how it ends)
3. The anonymity window — how long before the party is described or connected
4. One safe house or extraction point the client provides

Return JSON only:
{{
  "escape_routes": [
    {{"name": "...", "method": "...", "check": "Skill DC XX if pursued"}},
    {{"name": "...", "method": "...", "check": "Skill DC XX if pursued"}}
  ],
  "pursuit": "what happens if alarm was raised — timing and force",
  "anonymity_window": "how long before the party can be connected to the hit",
  "extraction_point": "where the client wants the party to go after"
}}"""

    raw = await _ollama(prompt)
    data = _parse_json(raw)
    if not data:
        data = {
            "escape_routes": [
                {"name": "Street exit",    "method": "Blend into foot traffic heading toward the market district", "check": "Stealth DC 12 if pursuit within 2 minutes"},
                {"name": "Rooftop run",    "method": "Access rooftop via fire escape and cross two blocks before descending", "check": "Athletics DC 13 — avoid losing footing on the narrow run"},
            ],
            "pursuit":             "If alarm was raised: 1d4+1 guards arrive in 3 minutes. They have a general description. They do not have names.",
            "anonymity_window":    "Approximately 12-24 hours before the faction can connect the hit to a specific group.",
            "extraction_point":    "A dead-drop location two districts away. Leave the proof of contract fulfilment in the indicated container. Payment will be there within the hour.",
        }
    return data


async def _generate_debrief(mission: dict, success: bool = True) -> str:
    faction = mission.get("faction", "Independent")
    title   = mission.get("title", "the contract")

    prompt = f"""Write a short after-action debrief for a D&D assassination mission.

Faction: {faction}
Contract: {title}
Outcome: {"successful elimination" if success else "contract aborted or target survived"}

Write 2-3 sentences from the client contact after the fact. Tone should be clinical and deniable.
No JSON — just the speech text."""

    text = await _ollama(prompt)
    if not text:
        text = "Contract closed. The {faction} has noted your discretion. We will be in touch."
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
            logger.info(f"[ASSASSIN] A1111 not ready (attempt {attempt}/10) — waiting 30s…")
            await asyncio.sleep(30)
    logger.warning("[ASSASSIN] A1111 unavailable after 10 attempts")
    return False


async def _generate_assassination_map(
    hit_site: str,
    target: Dict,
    security: Dict,
    out_dir: Path,
) -> Optional[Path]:
    """One private-interior tactical map informed by the hit site and security profile."""
    out = out_dir / "assassination_map.png"

    # Build prompt components
    site_desc = HIT_SITE_TYPES.get(hit_site, "private interior meeting space")
    target_name = target.get("target_name", "the target")
    guard_count = random.randint(*security.get("guard_count", (1, 2)))

    lora_name   = os.getenv("A1111_MAP_LORA_TOWN",    "EnvyFluxFantasyTownMap01")
    lora_weight = float(os.getenv("A1111_MAP_LORA_WEIGHT", "0.8"))
    triggers    = os.getenv("A1111_MAP_TOWN_TRIGGERS", "detailed, map, village")

    positive = ", ".join(filter(None, [
        f"<lora:{lora_name}:{lora_weight}>",
        triggers,
        f"Interior Table Map, {site_desc}",
        "private room floor plan, top-down tactical view",
        "hidden alcove, servant entrance at back, window with external ledge",
        "central table obstacle, emergency exit panel, single main doorway",
        f"{guard_count} guard positions marked, patrol path visible",
        "shadowed corners, concealment positions, high fantasy cyberpunk fusion",
        "wealth-stratified materials, opulent but functional",
    ]))

    negative = "characters, people, isometric, perspective, watermark, text, exterior, outdoor"

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
            decision = await wait_for_a1111_turn("assassination_map", max_wait_seconds=60)
            if not decision.run_now:
                logger.info(f"[ASSASSIN] A1111 deferred by resource cop: {decision.reason}")
                from src.mission_builder.vtt_renderer import save_vtt_battlemap
                save_vtt_battlemap(out, None, context={"title": target_name, "location": site_desc, "prompt": positive, "kind": "assassination private interior"})
                return out
            async with a1111_lock:
                async with httpx.AsyncClient(timeout=600.0) as c:
                    r = await c.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
                    r.raise_for_status()
                    images = r.json().get("images", [])
            if not images:
                raise RuntimeError("A1111 returned no images")
            from src.mission_builder.vtt_renderer import save_vtt_battlemap
            save_vtt_battlemap(out, images[0], context={"title": target_name, "location": site_desc, "prompt": positive, "kind": "assassination private interior"})
            logger.info(f"[ASSASSIN] Map saved: {out.name}")
            return out
        except Exception as e:
            logger.warning(f"[ASSASSIN] Map attempt {map_attempt}/{max_map_attempts} failed: {e}")
            if map_attempt < max_map_attempts:
                wait = min(30 * map_attempt, 120)
                logger.info(f"[ASSASSIN] Retrying map in {wait}s…")
                await asyncio.sleep(wait)

    # All attempts exhausted — fall back to deterministic
    logger.error("[ASSASSIN] Map generation failed after 10 attempts — using deterministic fallback")
    from src.mission_builder.vtt_renderer import save_vtt_battlemap
    save_vtt_battlemap(out, None, context={"title": target_name, "location": site_desc, "prompt": positive, "kind": "assassination private interior"})
    logger.info(f"[ASSASSIN] Deterministic VTT map saved: {out.name}")
    return out


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _e(s: Any) -> str:
    import html
    return html.escape(str(s or ""))


def _approach_card(approach: Dict, idx: int, fc: str) -> str:
    checks_html = "".join(
        f'<li style="font-size:13px;">{_e(ch)}</li>' for ch in (approach.get("checks") or [])
    )
    return (
        f'<div style="border:1px solid {fc};border-radius:6px;padding:12px 16px;margin:8px 0;background:#fafafa;">'
        f'<h4 style="margin:0 0 6px;color:{fc};">{_e(approach.get("label","Approach"))}</h4>'
        f'<div style="font-size:14px;margin-bottom:6px;">{_e(approach.get("entry_method",""))}</div>'
        f'<ul style="margin:4px 0 6px 16px;">{checks_html}</ul>'
        f'<div style="font-size:13px;color:#7b1e1e;"><strong>Risk:</strong> {_e(approach.get("key_risk",""))}</div>'
        f'<div style="font-size:13px;color:#555;margin-top:4px;"><strong>Partial success:</strong> {_e(approach.get("partial_success",""))}</div>'
        f'</div>'
    )


def _surveillance_card(lead: Dict, idx: int) -> str:
    return (
        f'<div style="border:1px solid #3a6898;border-radius:6px;padding:10px 14px;margin:6px 0;background:#f0f5ff;">'
        f'<input type="checkbox" style="margin-right:8px;accent-color:#3a6898;">'
        f'<strong>{_e(lead.get("label","Surveillance lead"))}</strong>'
        f'<span style="font-size:12px;color:#666;margin-left:12px;">{_e(lead.get("time_window",""))}</span>'
        f'<div style="margin-top:4px;font-size:13px;">{_e(lead.get("location",""))}</div>'
        f'<div style="margin-top:4px;font-size:13px;color:#444;">{_e(lead.get("what_is_learnable",""))}</div>'
        f'<div style="margin-top:4px;font-size:12px;color:#888;">Check: {_e(lead.get("check",""))}</div>'
        f'</div>'
    )


def _routine_table(routine: List[Dict]) -> str:
    rows = ""
    for r in routine:
        rows += (
            f'<tr>'
            f'<td style="padding:6px;font-weight:bold;">{_e(r.get("time",""))}</td>'
            f'<td style="padding:6px;">{_e(r.get("location",""))}</td>'
            f'<td style="padding:6px;">{_e(r.get("activity",""))}</td>'
            f'<td style="padding:6px;text-align:center;">{_e(r.get("guards_present","?"))}</td>'
            f'</tr>'
        )
    return (
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        f'<thead><tr style="background:#e8e0d0;">'
        f'<th style="padding:6px;text-align:left;">Time</th>'
        f'<th style="padding:6px;text-align:left;">Location</th>'
        f'<th style="padding:6px;text-align:left;">Activity</th>'
        f'<th style="padding:6px;text-align:center;">Guards</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
    )


def render_assassination_module(
    mission: dict,
    briefing: Dict,
    target: Dict,
    security: Dict,
    surveillance: List[Dict],
    approaches: List[Dict],
    exfil: Dict,
    map_path: Optional[Path],
    out_dir: Path,
) -> str:
    title   = mission.get("title", "Assassination")
    faction = mission.get("faction", "Independent")
    fc      = _faction_color(faction)

    map_html = ""
    if map_path and map_path.exists():
        rel = map_path.relative_to(out_dir)
        map_html = (
            f'<div style="text-align:center;margin:20px 0;">'
            f'<img src="{rel}" style="max-width:100%;border:3px solid {fc};border-radius:8px;" alt="Hit Site Map">'
            f'<div style="font-size:12px;color:#888;margin-top:4px;">Tactical map — {_e(target.get("target_name",""))}</div>'
            f'</div>'
        )

    approaches_html = "".join(_approach_card(a, i, fc) for i, a in enumerate(approaches))
    surveillance_html = "".join(_surveillance_card(s, i) for i, s in enumerate(surveillance))
    routine_html = _routine_table(target.get("routine", []))

    escape_routes_html = "".join(
        f'<li style="font-size:13px;margin:4px 0;"><strong>{_e(r.get("name",""))}:</strong> {_e(r.get("method",""))} '
        f'<span style="color:#888;">({_e(r.get("check",""))})</span></li>'
        for r in (exfil.get("escape_routes") or [])
    )

    body = f"""
<div style="border-left:4px solid {fc};padding:12px 18px;margin:20px 0;background:#fafafa;border-radius:0 8px 8px 0;">
  <h2 style="margin:0 0 4px;">Contract Briefing</h2>
  <div style="font-style:italic;color:#444;white-space:pre-line;">{_e(briefing.get("contact_speech",""))}</div>
  <div style="margin-top:12px;font-size:13px;">
    <strong>Contract reason:</strong> {_e(briefing.get("contract_reason",""))}<br>
    <strong>Moral hook:</strong> {_e(briefing.get("moral_hook",""))}<br>
    <strong>Payment:</strong> {_e(briefing.get("payment",""))}<br>
    <strong>If identified:</strong> {_e(briefing.get("identification_warning",""))}
  </div>
</div>

<hr>

<h2>Target Profile — {_e(target.get("target_name","Unknown"))}</h2>
<div style="display:flex;gap:24px;flex-wrap:wrap;margin:12px 0;">
  <div style="flex:1;min-width:220px;">
    <strong>Role:</strong> {_e(target.get("target_role",""))}<br>
    <strong>Description:</strong> {_e(briefing.get("target_desc",""))}<br>
    <strong>Security:</strong> {_e(security.get("label",""))} — {_e(security.get("guards",""))}
  </div>
  <div style="flex:1;min-width:220px;background:#fff8e6;border:1px solid #b8923a;border-radius:6px;padding:10px;">
    <strong style="color:#7b1e1e;">DM Secret:</strong><br>
    <span style="font-size:13px;">{_e(target.get("dm_secret",""))}</span><br><br>
    <strong>Conscience trigger:</strong><br>
    <span style="font-size:13px;">{_e(target.get("conscience_trigger",""))}</span>
  </div>
</div>

<h3>Security Detail</h3>
<div style="font-size:13px;background:#fafafa;border:1px solid #ddd;border-radius:6px;padding:10px 14px;margin-bottom:12px;">
  <strong>Guards:</strong> {_e(security.get("guards",""))}<br>
  <strong>Patrol:</strong> {_e(security.get("patrol",""))}<br>
  <strong>Alarm:</strong> {_e(security.get("alarm",""))}<br>
  <strong>Escape heat:</strong> {_e(security.get("escape_heat",""))}<br>
  <strong>Site note:</strong> {_e(target.get("security_note",""))}
</div>

<h3>Daily Routine</h3>
{routine_html}

{map_html}

<hr>

<h2>Surveillance Leads</h2>
<div style="font-size:12px;color:#666;margin-bottom:8px;">Each completed lead gives the party actionable intel on the target.</div>
{surveillance_html}

<hr>

<h2>Approach Options</h2>
<div style="font-size:12px;color:#666;margin-bottom:8px;">Three viable methods — choose one or blend them.</div>
{approaches_html}

<hr>

<h2>Exfiltration</h2>
<ul style="list-style:none;padding:0;">{escape_routes_html}</ul>
<div style="font-size:13px;margin:8px 0;"><strong>If alarm was raised:</strong> {_e(exfil.get("pursuit",""))}</div>
<div style="font-size:13px;margin:4px 0;"><strong>Anonymity window:</strong> {_e(exfil.get("anonymity_window",""))}</div>
<div style="font-size:13px;margin:4px 0;"><strong>Extraction point:</strong> {_e(exfil.get("extraction_point",""))}</div>

<hr>

<h2>Debrief</h2>
<div style="background:#e8f5e8;border:1px solid #2a6a2a;border-radius:6px;padding:14px 18px;font-style:italic;">
  <em>(Generated after the session — record outcome below)</em><br><br>
  <strong>Approach used:</strong>
  {"".join(f'<input type="radio" name="approach"> {_e(a.get("label",""))} &nbsp;' for a in approaches)}<br>
  <strong>Target outcome:</strong>
  <input type="radio" name="outcome"> Eliminated &nbsp;
  <input type="radio" name="outcome"> Aborted &nbsp;
  <input type="radio" name="outcome"> Target survived<br>
  <strong>Party identified:</strong>
  <input type="radio" name="id"> Yes &nbsp;
  <input type="radio" name="id"> No<br><br>
  <textarea rows="4" style="width:100%;font-family:inherit;" placeholder="After-action notes..."></textarea>
</div>
"""

    return _page(title, body, faction)


def render_assassination_session(
    mission: dict,
    briefing: Dict,
    target: Dict,
    security: Dict,
    surveillance: List[Dict],
    approaches: List[Dict],
    exfil: Dict,
) -> str:
    title   = mission.get("title", "Assassination")
    faction = mission.get("faction", "Independent")
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

    # Scene 1 — Briefing
    cards += _card(
        "Scene 1 — Contract Briefing",
        f'<p style="font-style:italic;">{_e(briefing.get("contact_speech","")[:600])}</p>'
        f'<p><strong>Moral hook:</strong> {_e(briefing.get("moral_hook",""))}</p>'
        f'<p><strong>Payment:</strong> {_e(briefing.get("payment",""))}</p>',
        fc,
    )

    # Scene 2 — Surveillance
    surv_items = "".join(
        f'<li><input type="checkbox"> <strong>{_e(s.get("label",""))}</strong> — {_e(s.get("what_is_learnable",""))} <em>({_e(s.get("check",""))})</em></li>'
        for s in surveillance
    )
    cards += _card(
        "Scene 2 — Surveillance",
        f'<ul style="font-size:13px;">{surv_items}</ul>'
        f'<p style="font-size:12px;color:#666;">Each completed lead feeds intel into the approach selection.</p>',
        "#3a6898",
    )

    # Scene 3 — The Hit
    approach_items = "".join(
        f'<li><input type="radio" name="approach_sel"> <strong>{_e(a.get("label",""))}</strong> — {_e(a.get("entry_method",""))}</li>'
        for a in approaches
    )
    guard_boxes = "".join(
        f'<input type="checkbox" style="width:18px;height:18px;margin:2px;accent-color:#7b1e1e;">'
        for _ in range(random.randint(*security.get("guard_count", (1, 2))))
    )
    cards += _card(
        f"Scene 3 — The Hit ({_e(security.get('label',''))})",
        f'<p><strong>Choose approach:</strong></p>'
        f'<ul style="font-size:13px;">{approach_items}</ul>'
        f'<div style="margin-top:12px;"><strong>Guards ({security.get("label","")}):</strong><br>{guard_boxes}</div>'
        f'<p style="font-size:13px;margin-top:12px;"><strong>Alarm:</strong> {_e(security.get("alarm",""))}</p>'
        f'<div style="background:#fff8e6;border:1px solid #b8923a;border-radius:4px;padding:8px;margin-top:8px;font-size:13px;">'
        f'<strong>Conscience trigger:</strong> {_e(target.get("conscience_trigger",""))}</div>',
        "#7b1e1e",
    )

    # Scene 4 — Exfil
    escape_items = "".join(
        f'<li><input type="checkbox"> <strong>{_e(r.get("name",""))}</strong> — {_e(r.get("method",""))}</li>'
        for r in (exfil.get("escape_routes") or [])
    )
    cards += _card(
        "Scene 4 — Exfiltration",
        f'<ul style="font-size:13px;">{escape_items}</ul>'
        f'<p style="font-size:13px;"><strong>If alarm raised:</strong> {_e(exfil.get("pursuit",""))}</p>'
        f'<p style="font-size:13px;"><strong>Anonymity window:</strong> {_e(exfil.get("anonymity_window",""))}</p>'
        f'<p style="font-size:13px;"><strong>Extraction point:</strong> {_e(exfil.get("extraction_point",""))}</p>',
        "#2a6a2a",
    )

    # Debrief
    cards += _card(
        "Debrief",
        f'<p><strong>Outcome:</strong> '
        f'<input type="radio" name="out"> Eliminated &nbsp;'
        f'<input type="radio" name="out"> Aborted &nbsp;'
        f'<input type="radio" name="out"> Target survived</p>'
        f'<p><strong>Identified:</strong> <input type="radio" name="id2"> Yes &nbsp; <input type="radio" name="id2"> No</p>'
        f'<textarea rows="3" style="width:100%;font-family:inherit;" placeholder="After-action notes..."></textarea>',
        "#555",
    )

    body = (
        f'<div style="text-align:center;margin:0 0 24px;">'
        f'<h1 style="color:{fc};">{_e(title)}</h1>'
        f'<div style="font-size:14px;color:#666;">{_e(faction)} — Contract Module</div>'
        f'</div>'
        + cards
    )
    return _page(title, body, faction)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


async def build_assassination_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    """Full assassination pipeline. Returns path to index.html."""
    title   = mission.get("title", "Unknown Contract")
    faction = mission.get("faction", "Independent")
    tier    = mission.get("tier", "standard")

    if out_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[ASSASSIN] Building: {title!r} | faction={faction} | tier={tier}")

    security     = _get_security_profile(tier)
    client_style = _get_client_style(faction)
    hit_site     = _pick_hit_site(faction, tier)

    logger.info(f"[ASSASSIN] Security={security['label']} | site={hit_site}")

    # Generate content concurrently where safe
    briefing_task = asyncio.create_task(_generate_briefing(mission, security, client_style))
    target_task   = asyncio.create_task(_generate_target(mission, security, hit_site))

    briefing, target = await asyncio.gather(briefing_task, target_task)

    # Surveillance and approaches depend on target data
    surveillance, approaches, exfil = await asyncio.gather(
        _generate_surveillance(mission, target),
        _generate_approaches(mission, target, security, hit_site),
        _generate_exfiltration(mission, security),
    )

    # A1111 map
    map_path = None
    if str(os.getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        if await _check_a1111():
            map_path = await _generate_assassination_map(hit_site, target, security, out_dir)
        else:
            logger.warning("[ASSASSIN] A1111 not available — skipping map")

    # Mimir module
    from src.mission_builder.mimir_module import (
        create_module as _mc,
        upload_map as _mu,
        render_mimir_section as _ms,
        push_documents as _mpd,
    )
    _mimir_id = await _mc(mission, mission_type="assassination")
    if _mimir_id and map_path:
        await _mu(_mimir_id, map_path, "Hit Site Map")

    # Module HTML
    module_html = render_assassination_module(
        mission, briefing, target, security, surveillance, approaches, exfil, map_path, out_dir,
    )
    module_html += _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(module_html, encoding="utf-8")

    # Session HTML
    session_html = render_assassination_session(
        mission, briefing, target, security, surveillance, approaches, exfil,
    )
    (out_dir / "session.html").write_text(session_html, encoding="utf-8")

    # Box set components
    from src.mission_builder.boxset_utils import component_links, write_component, write_maps_page
    dm_md = (
        f"## Assassination DM Guide\n"
        f"### Contract\n{briefing.get('contact_speech','')}\n\n"
        f"### Target\n"
        f"- Name: {target.get('target_name','')}\n"
        f"- Role: {target.get('target_role','')}\n"
        f"- DM secret: {target.get('dm_secret','')}\n"
        f"- Conscience trigger: {target.get('conscience_trigger','')}\n\n"
        f"### Security\n"
        f"- Level: {security.get('label','')}\n"
        f"- Guards: {security.get('guards','')}\n"
        f"- Patrol: {security.get('patrol','')}\n"
        f"- Alarm: {security.get('alarm','')}\n\n"
        f"### Approaches\n"
        + "\n".join(f"- {a.get('label','')}: {a.get('entry_method','')}" for a in approaches)
        + "\n\n### Exfiltration\n"
        f"- Heat: {security.get('escape_heat','')}\n"
        f"- Anonymity window: {exfil.get('anonymity_window','')}\n"
        f"- Extraction: {exfil.get('extraction_point','')}"
    )
    players_md = (
        f"## Player Brief\n"
        f"### The Contract\n{briefing.get('contact_speech','')}\n\n"
        f"### What You Know\n"
        f"- Target description: {briefing.get('target_desc','')}\n"
        f"- Contract reason: {briefing.get('contract_reason','')}\n"
        f"- If identified: {briefing.get('identification_warning','')}\n\n"
        f"### Public Objective\nLocate the target, execute the contract via your chosen approach, and exfiltrate without leaving traces."
    )
    chart_md = (
        f"## Assassination Chart Pack\n"
        f"### Surveillance Leads\n"
        + "\n".join(f"- {s.get('label','')}: {s.get('what_is_learnable','')}" for s in surveillance)
        + "\n\n### Approach Options\n"
        + "\n".join(f"- {a.get('label','')}: {a.get('key_risk','')}" for a in approaches)
        + "\n\n### Exfiltration Routes\n"
        + "\n".join(f"- {r.get('name','')}: {r.get('method','')}" for r in (exfil.get("escape_routes") or []))
    )
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, dm_md)
    write_component(out_dir, "players_guide", "Players Guide", title, faction, players_md)
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, chart_md)
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief", "type": "description", "content": players_md},
            {"title": f"{title} — DM Notes",     "type": "dm_notes",    "content": dm_md},
            {"title": f"{title} — Chart Pack",   "type": "custom",      "content": chart_md},
        ])
    maps_name = write_maps_page(out_dir, title, faction, [map_path] if map_path else [])
    box_components = component_links(has_maps=bool(maps_name))

    # Index HTML
    try:
        from src.mission_builder.html_renderer import render_index
        from src.mission_builder.cr_scaling import mission_cr
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
    except Exception as _ie:
        logger.warning(f"[ASSASSIN] index.html failed: {_ie}")
        index_path = out_dir / "module.html"

    # DB slug
    try:
        from src.db_api import raw_execute as _rx
        _rx("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as _dbe:
        logger.warning(f"[ASSASSIN] Could not write module_slug: {_dbe}")

    # Zip
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[ASSASSIN] Complete: {title!r} → {out_dir.name}")
    return index_path
