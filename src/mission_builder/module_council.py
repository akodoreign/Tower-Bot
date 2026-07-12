"""
module_council.py — 3-agent quality council for mission plan generation.

Council:
  1. Architect     — structural draft: scenes, survey points, setup, win conditions (JSON)
  2. Rules Expert  — mechanic validation + real campaign data from DB (enriched JSON)
  3. Bob           — adversarial critic in R.A. Salvatore's voice; returns numbered gaps
  4. Synthesis     — applies Bob's critique, outputs the final corrected plan (JSON)

Each pass is logged to logs/module_council.log.
Set MODULE_USE_COUNCIL=true to enable. Falls back to single-pass on any failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from src.log import logger

OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")

_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "module_council.log"
_LOG_PATH.parent.mkdir(exist_ok=True)

ENABLED = os.getenv("MODULE_USE_COUNCIL", "false").lower() in ("1", "true", "yes", "on")

import time as _time


# ---------------------------------------------------------------------------
# Logging helpers — write to both src.log AND module_council.log
# ---------------------------------------------------------------------------

def _log(label: str, content: str) -> None:
    """Write full content to the council log file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n{'='*70}\n[{ts}] {label}\n{'='*70}\n{content}\n")


def _info(msg: str) -> None:
    """Write to both src.log (dashboard-visible) and module_council.log."""
    logger.info(f"[COUNCIL] {msg}")
    ts = datetime.now().strftime("%H:%M:%S")
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


# ---------------------------------------------------------------------------
# Internal Ollama helper with timing
# ---------------------------------------------------------------------------

def _fit_ctx(prompt: str, reply_tokens: int) -> int:
    """Size the Ollama context window to the prompt + planned reply. With no
    num_ctx set, Ollama uses a small default and silently truncates either the
    oversized prompt or the long reply (yielding empty/unparseable output).
    Only raises; capped at 32k. Local to this module by the no-shared-helpers
    rule."""
    needed = len(prompt) // 4 + reply_tokens + 768
    for cand in (8192, 12288, 16384, 24576, 32768):
        if cand >= needed:
            return cand
    return 32768


async def _call(system: str, user: str, tokens: int = 3200, temp: float = 0.82, label: str = "") -> str:
    t0 = _time.monotonic()
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn(f"module_council:{label or 'llm'}", track="primary")
        if not decision.run_now:
            _info(f"  Ollama deferred {label or 'LLM'} after resource-cop wait: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=300.0) as c:
            r = await c.post(OLLAMA_URL, json={
                "model":    OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "stream":  False,
                "options": {"temperature": temp, "num_predict": tokens, "num_ctx": _fit_ctx(system + user, tokens)},
            })
            r.raise_for_status()
            result = (r.json().get("message") or {}).get("content", "").strip()
            elapsed = _time.monotonic() - t0
            if label:
                _info(f"  ⏱  {label} → {len(result)} chars in {elapsed:.0f}s")
            return result
    except Exception as exc:
        elapsed = _time.monotonic() - t0
        _info(f"  ❌ {label or 'LLM'} failed after {elapsed:.0f}s: {exc}")
        return ""


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pass 1 — Architect
# ---------------------------------------------------------------------------

_ARCHITECT_SYSTEM = """\
You are a seasoned D&D module designer with 20 years of professional tabletop publishing.
You write for DMs who are opening your module 30 minutes before the session starts.

YOUR RULE: No atmosphere without actionability. Every "vivid description" must also tell
the DM what to DO with it. Every scene has a concrete DM instruction — not "something
interesting happens" but "the DM places [specific NPC] at [specific position] and says...".

You write for the Undercity — a vast domed city beneath an artificial sky, billions of
people, faction politics, rifts that bleed monsters into reality. Dark urban fantasy.
Names. Smells. Iron, ozone, chalk dust, machine oil. Every location is specific and real.

Output ONLY a JSON object. No markdown fences, no explanation."""

async def _architect_pass(
    mission_title: str,
    subtype:       str,
    area:          Dict[str, Any],
    strength:      Dict[str, Any],
    dcs:           Dict[str, int],
    rifts:         List[Dict[str, Any]],
    faction:       str,
    briefing:      str,
) -> Dict[str, Any]:
    _info(f"📐 Pass 1/4 — Architect drafting '{mission_title}' ({subtype}) …")
    user = f"""Generate a COMPLETE D&D 5e 2024 Exploration mission plan as JSON.

MISSION: {mission_title}
SUBTYPE: {subtype}
LOCATION: {area.get('name')} in {area.get('district')} — {area.get('description','')}
FACTION: {faction}
PARTY: {strength['party_size']} PCs, avg Lv {strength['avg_level']}, max Lv {strength['max_level']}
DCs: navigation {dcs['navigation']}, hazard {dcs['hazard']}, stability {dcs['stability']}, lore {dcs['lore']}
ACTIVE RIFTS: {json.dumps(rifts[:2])}
PLAYER BRIEFING: {briefing}

Return JSON with these EXACT keys:

"setup": DM pre-session paragraph — name the contact NPC, where they stand, what gear they
  hand out, what the first visible hazard is, what the DM should prep before players arrive.

"win_conditions": plain-language SUCCESS / PARTIAL / FAILURE criteria.

"opening_scene": 3-sentence read-aloud for the moment players arrive at the survey area entrance.
  Specific. Name one NPC, one sensory detail, one wrongness in the environment.

"scenes": array of exactly 3 scene objects — Survey Phase, Complication, Extraction. Each has:
  "name": scene title
  "trigger": concrete entry condition (e.g. "after 2nd survey point" or "if any hazard is triggered")
  "read_aloud": 2-3 sentence read-aloud. Specific. Names, smells, textures.
  "dm_notes": 2-3 sentences of DM-only context — what is REALLY happening, where NPCs are,
    what the DM does. No vague suggestions.
  "mechanics": skill checks, DCs, timing pressure
  "outcome": one sentence where this leads

"route_log": array of exactly 6 survey point objects. Each has:
  "point": a specific named location within the survey area (e.g. "The Chalk Gate", "The Sunken Arch")
  "change": 1 sentence: what is specifically different or wrong at this location
  "read_aloud": 2-sentence read-aloud. Concrete. One physical detail, one wrongness.
  "dm_notes": 1-2 sentences DM-only — hidden info, tactical note, what a good DC reveals
  "check": skill name
  "dc": DC integer ({dcs['navigation']})
  "failure": 1 sentence concrete consequence

"hazards": array of 5 hazard strings, each starting with a name: e.g. "Floor Repeat: ..."
"deliverables": array of 6-8 specific survey deliverables
"discoveries": array of 5 specific findings with location hook
"dialogue": array of 8 lines with speaker prefix and context (e.g. "Warden [at the gate]: ...")
"news_seed": 1-sentence TNN bulletin after mission completion
"follow_up": one specific follow-up mission type"""

    raw  = await _call(_ARCHITECT_SYSTEM, user, tokens=3600, temp=0.84, label="Architect")
    data = _parse_json(raw)
    _log("PASS 1 — ARCHITECT", raw[:4000])
    if data:
        keys = list(data.keys())
        pts  = len(data.get("route_log") or [])
        sc   = len(data.get("scenes") or [])
        _info(f"  ✅ Architect done — {len(keys)} keys, {sc} scenes, {pts} survey points")
    else:
        _info("  ⚠️  Architect returned no valid JSON — will use fallback")
    return data or {}


# ---------------------------------------------------------------------------
# Pass 2 — Rules Expert
# ---------------------------------------------------------------------------

_RULES_SYSTEM = """\
You are a D&D 5e 2024 rules expert and Undercity campaign historian.
You review drafted mission plans for mechanical correctness and campaign authenticity.

YOUR JOB:
1. Validate DC scaling — party avg level {avg_level}: all DCs should be roughly
   10 + (avg_level / 2) ± 3. Flag and correct outliers in the JSON.
2. Replace generic "contact NPC" / "warden" / "faction representative" references
   with REAL named NPCs from the campaign DB when provided.
3. Replace generic "guards" / "monsters" with specific named creature types that fit
   the faction and location.
4. Ensure every scene has at least one concrete DM instruction that is NOT vague.
5. Add stat lines for any named combat NPCs that are missing them (HP, AC, CR).

Return the CORRECTED JSON plan. Same structure. Only fix what is wrong.
Output ONLY JSON. No explanation."""

async def _rules_expert_pass(
    draft:        Dict[str, Any],
    faction_npcs: List[Dict[str, Any]],
    strength:     Dict[str, Any],
    dcs:          Dict[str, int],
    faction:      str,
    area:         Dict[str, Any],
) -> Dict[str, Any]:
    npc_block = ""
    if faction_npcs:
        npc_lines = [
            f"  - {r.get('name','?')} ({r.get('role','?')}, {r.get('status','alive')})"
            for r in faction_npcs[:8]
        ]
        npc_block = "REAL NPCs in this faction:\n" + "\n".join(npc_lines)

    _info(f"⚖️  Pass 2/4 — Rules Expert validating (party avg Lv {strength.get('avg_level',5)}, {len(faction_npcs)} faction NPCs) …")
    system = _RULES_SYSTEM.replace("{avg_level}", str(strength.get("avg_level", 5)))
    user   = f"""Review and correct this mission plan for mechanical accuracy and campaign grounding.

{npc_block}
FACTION: {faction}
AREA: {area.get('name')}, {area.get('district')}
PARTY AVG LEVEL: {strength.get('avg_level', 5)}
DC PROFILE: nav {dcs['navigation']}, hazard {dcs['hazard']}, stability {dcs['stability']}

DRAFT PLAN:
{json.dumps(draft, indent=2)[:4000]}

Return the corrected JSON plan. If the draft is already correct, return it unchanged."""

    raw  = await _call(system, user, tokens=3600, temp=0.60, label="Rules Expert")
    data = _parse_json(raw)
    _log("PASS 2 — RULES EXPERT", raw[:4000])
    if data:
        _info(f"  ✅ Rules Expert done — mechanics validated, {len(faction_npcs)} NPCs available for grounding")
    else:
        _info("  ⚠️  Rules Expert returned no JSON — keeping Architect draft")
    return data if data else draft


# ---------------------------------------------------------------------------
# Pass 3 — Bob (adversarial critic, R.A. Salvatore sensibility)
# ---------------------------------------------------------------------------

_BOB_SYSTEM = """\
You are Bob — you write in the style of R.A. Salvatore.
You've been handed a D&D module and told you're running it TONIGHT.

You know what a real DM needs: atmosphere that can be FELT, NPCs with a soul,
combat that has a tactical shape, and read-aloud text that makes the room go quiet.
You have no patience for the generic. A blank stare, a shrug, an improvised awkward
pause — those are what happens when a module fails its DM.

YOUR JOB: Read this plan and list every place you'd have to improvise because the
module doesn't tell you what to do. Problems fall into two categories:
  - MECHANICS GAP: a skill check, trigger, or resolution that is missing or vague
  - ATMOSPHERE GAP: a read-aloud, NPC moment, or sensory detail that doesn't land

Format each problem as:
PROBLEM [N]: [category — MECHANICS GAP or ATMOSPHERE GAP]
ISSUE: [one sentence describing exactly what is wrong]
FIX NEEDED: [one sentence describing exactly what is missing]

Maximum 7 problems. Minimum 3. Be specific. Name the scene or survey point."""

async def _bob_critique(draft: Dict[str, Any]) -> str:
    _info("✍️  Pass 3/4 — Bob reviewing (R.A. Salvatore mode — running it tonight) …")
    user = f"""Read this mission plan. You're running it tonight. What would make you stop and improvise?

{json.dumps(draft, indent=2)[:5000]}

List your problems."""

    raw = await _call(_BOB_SYSTEM, user, tokens=1200, temp=0.80, label="Bob")
    _log("PASS 3 — BOB (R.A. Salvatore critique)", raw)

    # Log Bob's individual problems to the main feed
    problem_lines = [l.strip() for l in raw.splitlines()
                     if l.strip().startswith("PROBLEM") or l.strip().startswith("ISSUE:") or l.strip().startswith("FIX")]
    if problem_lines:
        _info(f"  📋 Bob found {len([l for l in problem_lines if l.startswith('PROBLEM')])} problem(s):")
        for line in problem_lines[:14]:  # cap to avoid log spam
            _info(f"      {line}")
    else:
        _info("  📋 Bob's critique written (see module_council.log for full text)")

    return raw


# ---------------------------------------------------------------------------
# Pass 4 — Synthesis (apply Bob's fixes)
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = """\
You are a technical editor. You are given a mission plan (JSON) and a list of
specific problems identified by a critic. Your job is to apply EXACTLY the fixes
described — no more, no less. Do not change structure, plot, or outcomes that are
not mentioned. Fill the gaps. Sharpen the vague. Make it runnable.
Output ONLY the corrected JSON plan."""

async def _synthesis_pass(draft: Dict[str, Any], critique: str) -> Dict[str, Any]:
    n_problems = len([l for l in critique.splitlines() if l.strip().startswith("PROBLEM")])
    _info(f"🔧 Pass 4/4 — Synthesis applying {n_problems} fix(es) from Bob …")
    user = f"""Apply these fixes to the mission plan.

CRITIC'S PROBLEMS:
{critique}

CURRENT PLAN:
{json.dumps(draft, indent=2)[:4500]}

Return the corrected JSON plan with all identified gaps filled."""

    raw  = await _call(_SYNTHESIS_SYSTEM, user, tokens=3600, temp=0.70, label="Synthesis")
    data = _parse_json(raw)
    _log("PASS 4 — SYNTHESIS", raw[:4000])
    if data:
        _info(f"  ✅ Synthesis done — final plan: {len(data.keys())} keys, {len(data.get('route_log') or [])} survey points")
    else:
        _info("  ⚠️  Synthesis returned no JSON — keeping Rules Expert draft")
    return data if data else draft


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _get_faction_npcs(faction: str) -> List[Dict[str, Any]]:
    try:
        from src.db_api import raw_query
        return raw_query(
            "SELECT name, role, status, location, data_json "
            "FROM npcs WHERE faction=%s AND status NOT IN ('dead') LIMIT 12",
            (faction,),
        ) or []
    except Exception:
        return []


async def generate_with_council(
    mission_title: str,
    subtype:       str,
    area:          Dict[str, Any],
    strength:      Dict[str, Any],
    dcs:           Dict[str, int],
    rifts:         List[Dict[str, Any]],
    faction:       str,
    briefing:      str,
) -> Optional[Dict[str, Any]]:
    """
    Run the 4-pass council: Architect → Rules Expert → Bob → Synthesis.
    Returns the enriched plan dict, or None on complete failure.
    """
    if not ENABLED:
        return None

    t_start = _time.monotonic()
    _log("COUNCIL START", f"Mission: {mission_title} | Faction: {faction} | Area: {area.get('name')}")
    _info(f"🏛️  ══ MODULE COUNCIL CONVENED ══  '{mission_title}'")
    _info(f"     Faction: {faction}  |  Area: {area.get('name')}, {area.get('district')}")
    _info(f"     Party: {strength.get('party_size',4)} PCs · avg Lv {strength.get('avg_level',5)} · max Lv {strength.get('max_level',5)}")
    _info(f"     Model: {OLLAMA_MODEL}  |  Log: logs/module_council.log")

    # Pull real faction NPCs for the Rules Expert
    faction_npcs = _get_faction_npcs(faction)
    _info(f"     DB faction NPCs loaded: {len(faction_npcs)}")

    try:
        # Pass 1: Architect draft
        draft = await _architect_pass(
            mission_title, subtype, area, strength, dcs, rifts, faction, briefing
        )
        if not draft:
            _info("  ❌ Architect returned empty — aborting council, falling back to single-pass")
            return None

        # Pass 2: Rules Expert enrichment
        draft = await _rules_expert_pass(draft, faction_npcs, strength, dcs, faction, area)

        # Pass 3: Bob's critique
        critique = await _bob_critique(draft)
        if not critique.strip():
            t_total = _time.monotonic() - t_start
            _info(f"  ✅ Bob found nothing wrong — skipping synthesis")
            _info(f"🏛️  ══ COUNCIL COMPLETE ══  {t_total:.0f}s total  (no synthesis needed)")
            _log("COUNCIL COMPLETE", "Bob passed — no synthesis needed")
            return draft

        # Pass 4: Synthesis — apply Bob's fixes
        final = await _synthesis_pass(draft, critique)

        t_total = _time.monotonic() - t_start
        _info(f"🏛️  ══ COUNCIL COMPLETE ══  {t_total:.0f}s total")
        _info(f"     Final plan: {len(final.keys())} sections · {len(final.get('route_log') or [])} survey points · {len(final.get('scenes') or [])} scenes")
        _log("COUNCIL COMPLETE", f"Final plan keys: {list(final.keys())}  |  Total time: {t_total:.0f}s")
        return final

    except Exception as exc:
        t_total = _time.monotonic() - t_start
        _info(f"❌ Council failed after {t_total:.0f}s: {exc}")
        _log("COUNCIL ERROR", str(exc))
        return None
