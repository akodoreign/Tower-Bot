"""
published_pipeline.py - fast, table-first mission module generator.

This pipeline intentionally does not write a novel first. It turns a claimed
mission into a playable one-shot that follows the shape of published 5e
adventures: background, summary, numbered areas, read-aloud text, DM notes,
checks, NPC handling, tactics, rewards, player handout, chart pack, and map
manifest.
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.log import logger
from src.mission_builder.encounters import get_cr, get_encounter_budget, get_party_size
from src.mission_builder.html_renderer import render_component, render_index, render_maps_page

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "generated_modules"
TRAINING_DIR = Path(__file__).resolve().parent.parent.parent / "campaign_docs" / "skills" / "training_modules"
FORMAT_GUIDE = TRAINING_DIR / "MODULE_FORMAT_GUIDE.md"


def _safe_filename(text: str, maxlen: int = 50) -> str:
    safe = re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")
    return (safe or "mission")[:maxlen]


def _make_output_dir(title: str) -> Path:
    out = OUTPUT_BASE / f"{_safe_filename(title)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _sentences(text: str, limit: int = 3) -> list[str]:
    found = re.findall(r"[^.!?]+[.!?]", _clean(text))
    if not found and text:
        found = [_clean(text).rstrip(".") + "."]
    return [s.strip() for s in found[:limit]]


def _contact_parts(mission: dict) -> tuple[str, str, str]:
    contact = _clean(mission.get("contact") or "")
    if not contact:
        return "The posting contact", "the mission board", ""
    name, rest = contact, ""
    if "," in contact:
        name, rest = contact.split(",", 1)
    elif " - " in contact:
        name, rest = contact.split(" - ", 1)
    elif "—" in contact:
        name, rest = contact.split("—", 1)
    detail = ""
    if "—" in rest:
        rest, detail = rest.split("—", 1)
    elif " - " in rest:
        rest, detail = rest.split(" - ", 1)
    return _clean(name), _clean(rest) or "the mission board", _clean(detail)


def _mission_seed(mission: dict) -> dict:
    title = _clean(mission.get("title") or "Untitled Contract")
    faction = _clean(mission.get("faction") or "Independent")
    tier = _clean(mission.get("tier") or "standard").lower()
    mission_type = _clean(mission.get("type") or mission.get("mission_type") or tier).title()
    public_text = _clean(mission.get("public_text") or mission.get("story_text") or mission.get("description"))
    private_notes = _clean(mission.get("private_notes") or "")
    body = _clean(mission.get("body") or "")
    contact_name, contact_location, contact_detail = _contact_parts(mission)
    return {
        "title": title,
        "faction": faction,
        "tier": tier,
        "mission_type": mission_type,
        "public_text": public_text or f"{faction} needs a crew for {title}.",
        "private_notes": private_notes,
        "body": body,
        "contact_name": contact_name,
        "contact_location": contact_location,
        "contact_detail": contact_detail,
        "reward": _clean(mission.get("reward") or "See contract"),
        "opposing_faction": _clean(mission.get("opposing_faction") or "None"),
    }


def _infer_primary_location(seed: dict, fallback: str = "") -> str:
    """Prefer the mission's own contact/location over a random gazetteer pick."""
    contact_location = _clean(seed.get("contact_location") or "")
    if contact_location:
        parts = [p.strip() for p in contact_location.split(",") if p.strip()]
        if parts:
            return parts[-1]
        return contact_location
    body = f"{seed.get('title', '')} {seed.get('public_text', '')} {seed.get('private_notes', '')}"
    for marker in ("Bone Market", "Warrens", "Tower", "Underbelly", "Sanctum", "Forge", "Docks"):
        if marker.lower() in body.lower():
            return marker
    return fallback or "the Undercity"


def _specific_sites(ctx: dict) -> dict:
    """Create concrete WotC-style area names from mission facts."""
    primary = ctx["primary_location"]
    contact = ctx["contact_name"]
    title = ctx["title"]
    title_low = title.lower()
    contact_site = ctx["contact_location"] if ctx.get("contact_location") else f"{contact}'s table in {primary}"

    if "bone market" in primary.lower() or "bone market" in title_low:
        return {
            "contract": contact_site,
            "leads": "Bone Market vendor row",
            "route": "Marrow-Cut service lane",
            "hidden": "Gruggar's shuttered sub-stall",
            "final": "the ossuary counting room below the Bone Market",
        }
    if "rift" in title_low:
        return {
            "contract": contact_site,
            "leads": f"rift-scarred alleys of {primary}",
            "route": "glass-dusted maintenance stair",
            "hidden": "collapsed warding chamber",
            "final": f"the unstable rift focus beneath {primary}",
        }
    if "ledger" in title_low or "codex" in title_low or "relic" in title_low:
        return {
            "contract": contact_site,
            "leads": f"record stalls of {primary}",
            "route": "sealed archive passage",
            "hidden": "false-bottom evidence room",
            "final": f"the locked counting room in {primary}",
        }
    return {
        "contract": contact_site,
        "leads": primary,
        "route": f"back route through {primary}",
        "hidden": f"hidden room beneath {primary}",
        "final": f"confrontation site at {primary}",
    }


def _goal_from_title(title: str, mission_type: str) -> str:
    low = f"{title} {mission_type}".lower()
    if any(w in low for w in ("codex", "ledger", "relic", "key", "sigil", "retrieve", "recovery")):
        return "recover the missing object and learn who moved it"
    if any(w in low for w in ("strangler", "killer", "assassin", "bounty", "hunt", "manhunt")):
        return "identify the culprit, corner them, and decide their fate"
    if any(w in low for w in ("rift", "ritual", "seal", "arcane")):
        return "stabilize the magical threat before it spreads"
    if any(w in low for w in ("escort", "caravan", "delivery")):
        return "move the protected person or cargo through danger intact"
    if any(w in low for w in ("ambush", "trap")):
        return "survive the setup and trace who arranged it"
    return "find the truth behind the contract and resolve the immediate threat"


def _dc(cr: int, offset: int = 0) -> int:
    return max(10, min(23, 10 + cr // 2 + offset))


def _lead_lines(ctx: dict) -> list[str]:
    leads = ctx.get("leads") or []
    lines = []
    for lead in leads[:3]:
        loc = _clean(lead.get("location") or "a local contact point")
        why = _clean(lead.get("why_go_there") or "It connects to the contract.")
        checks = lead.get("skill_checks") or []
        skill = checks[0].get("skill", "Investigation") if checks else "Investigation"
        lines.append(f"- {loc}: {why} A DC {ctx['dc']} {skill} check confirms the useful detail.")
    if not lines:
        lines = [
            f"- {ctx['primary_location']}: records, witnesses, or traces point toward the hidden site.",
            f"- {ctx['contact_location']}: the contact can confirm what is public and what they fear saying aloud.",
            f"- A nearby market stall: a witness saw the last suspicious movement before the job went bad.",
        ]
    return lines


def _load_format_guide(max_chars: int = 5500) -> str:
    """Load the local published-module format guide without copying whole PDFs."""
    try:
        text = FORMAT_GUIDE.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        logger.warning("[PUBLISHED] FORMAT_GUIDE not found: %s", FORMAT_GUIDE)
        return ""
    # Prefer the distilled rules and brief labels over long excerpts.
    rules_at = text.find("## FORMAT RULES")
    if rules_at >= 0:
        return text[rules_at:rules_at + max_chars]
    return text[:max_chars]


def _extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except Exception as e:
        logger.warning(f"[PUBLISHED] Blueprint JSON parse failed: {e}")
        return None
    return data if isinstance(data, dict) else None


async def _generate_blueprint(ctx: dict) -> Optional[dict]:
    """
    Ask the local model for a bounded adventure blueprint.

    The renderer still enforces structure, but this pass gives the module
    specificity: named rooms, clue logic, suspects, complications, and maps.
    """
    if os.getenv("MODULE_USE_LLM_BLUEPRINT", "false").lower() not in ("1", "true", "yes", "on"):
        return None

    _mtype_guidance = {
        "sabotage":      "Scene structure: infiltration → locate target → disable/destroy under pressure → escape or cover tracks.",
        "investigation": "Scene structure: briefing with incomplete info → gather clues → twist/ambush → uncover truth → confront responsible party.",
        "escort":        "Scene structure: meet the package/person → move through hostile route → ambush/complication → deliver safely.",
        "courier":       "Scene structure: receive sealed package → navigate surveillance → exchange goes wrong → recover the handoff.",
        "retrieval":     "Scene structure: locate the target object → overcome security → seize it under opposition → exfiltrate.",
        "heist":         "Scene structure: case the location → penetrate security → grab the objective → survive the alarm.",
        "bounty":        "Scene structure: track the mark → identify/confirm → close in → capture or neutralise in a crowded space.",
        "assassination": "Scene structure: surveil the target → get into position → execute or abort → exfiltrate cleanly.",
        "rift":          "Scene structure: report of anomaly → reach the rift site → fight what came through → close or contain it.",
        "recovery":      "Scene structure: learn what was taken and by whom → trace it → intercept → secure.",
        "battle":        (
            "Scene structure: enemies spotted and engaged → Wave 1 (scouts/light troops, softening blow) → "
            "brief lull (PCs can reposition, heal, assess) → Wave 2 (main force, heavier and organised) → "
            "brief lull (morale check, terrain shift) → Wave 3 / Final (elite unit or commander arrives). "
            "Each wave must be described separately with its own tactics, entry point, and how it ends. "
            "The lulls between waves are NOT free time — give the party a hard choice or environmental event each time."
        ),
        "defense":       (
            "Scene structure: arrive and assess what must be held → prepare defenses (fortify choke points, "
            "position NPC allies, set traps) → Wave 1 attack (probing, light opposition tests the defenses) → "
            "Wave 2 attack (main assault, focused on the weakest point the party chose) → "
            "Wave 3 / Final assault (elite shock troops or a named commander leading a breach attempt). "
            "Between waves the party must make decisions: shore up the breach or press an advantage. "
            "Success condition is survival or holding until a trigger event (dawn, reinforcements, ritual complete). "
            "Every scene must reference what is being defended and what is at stake if it falls."
        ),
        "ambush":        (
            "Scene structure: surprise round (enemies have advantage, party is flat-footed) → "
            "adaptation (party finds cover, identifies threat positions) → "
            "counter-pressure (second group of ambushers arrives or terrain hazard activates) → "
            "resolution (break out, turn the trap, or extract). "
            "Include one dramatic 'turn the tables' opportunity the party can seize with a good check."
        ),
    }
    _mtype_key = next((k for k in _mtype_guidance if k in ctx['mission_type'].lower()), None)
    _mtype_hint = f"\nMISSION TYPE STRUCTURE HINT: {_mtype_guidance[_mtype_key]}" if _mtype_key else ""

    prompt = f"""Build a professional D&D 5e one-shot adventure blueprint as JSON.

MISSION
Title: {ctx['title']}
Faction: {ctx['faction']}
Type: {ctx['mission_type']}{_mtype_hint}
Tier: {ctx['tier']}
Reward: {ctx['reward']}
Public contract: {ctx['public_text']}
Private GM notes: {ctx['private_notes']}
Contact: {ctx['contact_name']} at {ctx['contact_location']} ({ctx['contact_detail']})
Primary location: {ctx['primary_location']}

PUBLISHED MODULE STYLE RULES
Use: numbered areas, Read this/read-aloud text, GM NOTE, exact DC checks, NPC wants/knows/hides, failure-forward consequences, immediate stat blocks.
The 5 scenes MUST reflect the mission Type — read-alouds, checks, and transitions must feel like THIS specific type of job, not a generic contract briefing.

Return ONLY valid JSON with this schema:
{{
  "secret_truth": "one DM-only truth",
  "villain": {{"name": "specific name", "role": "specific role", "motive": "specific motive"}},
  "objective": "specific playable objective",
  "failure_clock": ["what worsens first", "what worsens second", "what happens if ignored"],
  "scenes": [
    {{
      "name": "short scene name",
      "location": "specific area name",
      "read": "3-4 sentence read-aloud text",
      "gm_notes": ["specific hidden fact", "specific clue", "specific consequence"],
      "npcs": ["Name - role - wants / knows / hides"],
      "checks": ["Skill DC NN: exact success result and failure cost"],
      "what_happens": ["trigger and result", "if players do nothing"],
      "transition": "sensory clue or concrete reason leading onward",
      "treasure": "specific reward or clue object, or None",
      "map_features": ["feature", "feature", "feature"]
    }}
  ],
  "rumors": ["d8 rumor 1", "d8 rumor 2", "d8 rumor 3", "d8 rumor 4", "d8 rumor 5", "d8 rumor 6", "d8 rumor 7", "d8 rumor 8"],
  "maps": [
    {{"name": "map name", "type": "interior|urban|dungeon|market|rooftop", "features": ["feature", "feature", "feature"]}}
  ]
}}

Requirements:
- Exactly 5 scenes.
- Use numbered-area style internally: every scene must be a place the players can enter.
- Do not invent a different city. Stay in the Undercity/Tower setting.
- Do not reveal GM-only details in player-facing read text.
- Every check must name DC, skill, success result, and failure cost.
- Every NPC line must include wants / knows / hides.
"""
    try:
        from src.ollama_queue import call_ollama

        data = await call_ollama(
            {
                "model": os.getenv("OLLAMA_FAST_MODEL", os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")),
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "num_predict": int(os.getenv("MODULE_BLUEPRINT_TOKENS", "1600")),
                    "num_ctx": 8192,
                    "temperature": 0.75,
                    "think": False,
                },
            },
            timeout=float(os.getenv("MODULE_BLUEPRINT_TIMEOUT", "90")),
            caller="module_blueprint",
        )
        content = ((data.get("message") or {}).get("content") or "").strip()
        blueprint = _extract_json_object(content)
        if blueprint and len(blueprint.get("scenes") or []) >= 4:
            logger.info(f"[PUBLISHED] LLM blueprint accepted ({len(blueprint.get('scenes', []))} scenes)")
            return blueprint
        logger.warning("[PUBLISHED] LLM blueprint missing/short; using deterministic scaffold")
    except Exception as e:
        logger.warning(f"[PUBLISHED] LLM blueprint failed; using deterministic scaffold: {e}")
    return None


def _scene_data(ctx: dict) -> list[dict]:
    blueprint = ctx.get("blueprint") or {}
    bp_scenes = blueprint.get("scenes") if isinstance(blueprint, dict) else None
    if isinstance(bp_scenes, list) and bp_scenes:
        scenes: list[dict] = []
        for raw_scene in bp_scenes[:5]:
            if not isinstance(raw_scene, dict):
                continue
            scenes.append({
                "name": _clean(raw_scene.get("name") or "Scene"),
                "location": _clean(raw_scene.get("location") or ctx["primary_location"]),
                "read": _clean(raw_scene.get("read") or "The room waits in tense silence."),
                "notes": [_clean(x) for x in (raw_scene.get("gm_notes") or []) if _clean(x)][:4],
                "npcs": [_clean(x) for x in (raw_scene.get("npcs") or []) if _clean(x)][:4],
                "checks": [_clean(x) for x in (raw_scene.get("checks") or []) if _clean(x)][:5],
                "what_happens": [_clean(x) for x in (raw_scene.get("what_happens") or []) if _clean(x)][:4],
                "transition": _clean(raw_scene.get("transition") or "The next clue points onward."),
                "treasure": _clean(raw_scene.get("treasure") or ""),
                "map_features": [_clean(x) for x in (raw_scene.get("map_features") or []) if _clean(x)][:5],
            })
        if len(scenes) >= 4:
            while len(scenes) < 5:
                scenes.append({"name": "Escalation", "location": scenes[-1].get("location", ""), "read": "The situation escalates toward the final confrontation.", "notes": [], "npcs": [], "checks": [], "what_happens": [], "transition": "", "treasure": "", "map_features": []})
            return scenes

    title = ctx["title"]
    contact = ctx["contact_name"]
    primary = ctx["primary_location"]
    sites = _specific_sites(ctx)
    goal = ctx["goal"]
    clue = ctx["private_notes"] or "Something about the scene contradicts the public version of events."
    enemy = ctx["enemy"]
    mtype = ctx.get("mission_type", "").lower()

    # ── Scene 1 read-aloud: varies by mission type ──────────────────
    def _s1_read() -> str:
        if any(w in mtype for w in ("sabotage", "destroy", "disable")):
            return (
                f"{contact} spreads a rough diagram across the table without greeting you. "
                f"Three points are circled in red. One of them is already crossed out. "
                f"'The window is closing,' they say, without looking up."
            )
        if any(w in mtype for w in ("escort", "protect", "guard")):
            return (
                f"{contact} is already watching the door when you arrive. The person they want moved "
                f"sits in the corner with their back to the wall, not eating. "
                f"The contract on the table has no destination written on it — only a time."
            )
        if any(w in mtype for w in ("recover", "retrieve", "heist", "theft", "steal")):
            return (
                f"{contact} slides a folded floor plan across the table before you've sat down. "
                f"Two rooms are marked: one where the thing is, one where the guards change shift. "
                f"'You have until the second bell,' they say. 'After that it moves.'"
            )
        if any(w in mtype for w in ("courier", "delivery", "transport")):
            return (
                f"{contact} sets a sealed package on the table between you. It has no address — "
                f"only a symbol pressed into the wax that you're not meant to recognise. "
                f"'Don't open it. Don't lose it. Don't be seen with it.' That's the whole brief."
            )
        if any(w in mtype for w in ("investigation", "interrogat", "find", "locate", "missing")):
            return (
                f"{contact} doesn't offer you a seat. They push a page of notes across the table "
                f"and let you read it while they watch your face for a reaction. "
                f"Most of the names have been crossed out. One is circled twice."
            )
        if any(w in mtype for w in ("bounty", "hunt", "assassin", "kill", "eliminate")):
            return (
                f"{contact} shows you one thing: a face. No name, no dossier, no reason. "
                f"The coin on the table is real enough. So is the warning at the bottom of the contract: "
                f"'This person is already running.'"
            )
        if any(w in mtype for w in ("rift", "arcane", "magical", "containment")):
            return (
                f"{contact} has burn marks on their left hand they're pretending not to favour. "
                f"The diagram they show you is half equations, half apology. "
                f"'It opened three nights ago,' they say. 'We don't know what came through.'"
            )
        if any(w in mtype for w in ("battle", "assault", "attack", "raid")):
            return (
                f"{contact} is calm in the way people get when they've already accepted the outcome. "
                f"They lay out a battle sketch — three approach vectors, two of them already compromised. "
                f"'They'll come in waves,' they say. 'The first one is just to count your swords.'"
            )
        if any(w in mtype for w in ("defense", "defend", "hold", "siege", "protect")):
            return (
                f"{contact} has a map of the location pinned to the wall with a blade through the centre. "
                f"Red marks ring three entry points. 'They'll probe first,' they say. "
                f"'Hit the soft spot in the second push. The third wave is the one that kills you if you let it.'"
            )
        # Default — contract handoff, generic but not identical every time
        return (
            f"{contact} waits at the far end of a table no one else is sitting at. "
            f"The contract is already signed on their side. They slide it across without preamble. "
            f"One clause near the bottom has been rewritten — the ink is still damp."
        )

    # ── Scene 3 read-aloud: varies by mission type ──────────────────
    def _s3_read() -> str:
        if any(w in mtype for w in ("escort", "protect", "guard")):
            return (
                f"The route was supposed to be clear. It isn't. "
                f"Something has been moved to block the natural path through, and whoever moved it "
                f"is still close enough that you can hear them breathing."
            )
        if any(w in mtype for w in ("courier", "delivery", "transport")):
            return (
                f"The handoff point has company that wasn't invited. "
                f"Someone got here first — not to receive the package, but to intercept it. "
                f"The city goes quiet the way it does when it knows something is about to break."
            )
        if any(w in mtype for w in ("investigation", "find", "locate", "missing")):
            return (
                f"The lead that seemed solid has a shadow behind it. "
                f"Someone has been following the same trail, and they're not interested in answers — "
                f"they're interested in making sure you stop asking questions."
            )
        if any(w in mtype for w in ("battle", "assault", "attack", "raid")):
            return (
                f"The first contact is light — too light. "
                f"A handful of fighters, hitting hard and pulling back before the party can press. "
                f"Somewhere behind them, something larger is still getting into position."
            )
        if any(w in mtype for w in ("defense", "defend", "hold", "siege")):
            return (
                f"They come without warning — not a charge but a probe. "
                f"Scattered fighters testing the edges, counting how many swords swing back. "
                f"They're not trying to win yet. They're learning where it hurts."
            )
        # Default — ambush on a route
        return (
            f"The route narrows until conversation becomes a liability. "
            f"A lantern has been left burning where no one should need light, "
            f"and boot marks overlap in deliberate confusion. "
            f"Then the city goes quiet in the way it does before violence."
        )

    return [
        {
            "name": "The Contract Table",
            "location": sites["contract"],
            "read": _s1_read(),
            "notes": [
                f"The surface objective is to {goal}.",
                f"{contact} knows more than the public post says: {clue}",
                "The scene should end with a concrete destination, not a vague instruction to investigate.",
            ],
            "npcs": [f"{contact} - contact - wants the party moving quickly; hides the part that would make them refuse."],
            "checks": [
                f"Insight DC {ctx['dc']}: {contact} is afraid of a specific person, not the job itself.",
                f"Persuasion DC {ctx['dc'] + 1}: they reveal the first private lead before the party leaves.",
            ],
            "transition": f"The scraped line on the contract matches a stall mark used in {sites['leads']}.",
        },
        {
            "name": "The Market Remembers",
            "location": sites["leads"],
            "read": (
                f"{sites['leads']} is busy enough to hide a crime and narrow enough to remember one. The air carries "
                f"old smoke, wet stone, and the metallic tang of recent work. People glance away when the party "
                f"mentions {title}, but nobody looks surprised."
            ),
            "notes": [
                "This area gives the players three directions. They only need two successes to reach the next scene.",
                "Failure should cost time, attention, or resources, never stop the adventure.",
                "Let creative plans bypass one check if they use a contact, spell, tool, or faction standing.",
            ],
            "npcs": ["Local witness - frightened resident - saw the wrong person carrying the right evidence."],
            "checks": _lead_lines(ctx),
            "transition": f"Two clues agree on one thing: someone carried the answer through {sites['route']}.",
        },
        {
            "name": "The Bad Turn",
            "location": sites["route"],
            "read": _s3_read(),
            "notes": [
                "This is the pressure scene: ambush, chase, collapsing route, or social trap depending on player choices.",
                "The attackers are trying to delay the party, not necessarily kill them.",
                "One captured opponent can name the final location or identify the patron behind the trouble.",
            ],
            "npcs": [f"{enemy} scout - hostile agent - has orders to slow the party and destroy evidence."],
            "checks": [
                f"Perception DC {ctx['dc']}: notice the ambush position before initiative.",
                f"Athletics or Acrobatics DC {ctx['dc']}: cross the unstable route without losing position.",
                f"Intimidation DC {ctx['dc'] + 2}: make a captured scout talk before reinforcements arrive.",
            ],
            "transition": f"The ambushers carry a route mark, key, or coded phrase that opens {sites['hidden']}.",
        },
        {
            "name": "The Room That Was Cleaned",
            "location": sites["hidden"],
            "read": (
                f"The hidden {'space' if any(w in mtype for w in ('rift','arcane')) else 'room'} "
                f"is smaller than the problem it contains. "
                f"{'The air tastes wrong — not dangerous yet, but wrong.' if any(w in mtype for w in ('rift','arcane','magical')) else 'Dust has been cleared from only the surfaces someone needed, leaving clean shapes in the grime.'} "
                f"Whatever happened here was planned, interrupted, and hidden in a hurry."
            ),
            "notes": [
                "This is the evidence scene. Give the party the truth if they interact with the room.",
                "Put the core clue in three forms: physical trace, witness/object, and magical or faction signature.",
                "The final antagonist should become understandable here, even if not sympathetic.",
            ],
            "npcs": ["Bound witness, damaged construct, or surviving clerk - knows one fact but fears the consequence."],
            "checks": [
                f"Investigation DC {ctx['dc']}: reconstruct the sequence of events.",
                f"Arcana, Religion, or History DC {ctx['dc'] + 1}: identify the ritual, relic, or faction method involved.",
                f"Medicine or Survival DC {ctx['dc']}: read the physical aftermath correctly.",
            ],
            "transition": f"The evidence points to {sites['final']} and tells the party what failure will cost.",
        },
        {
            "name": "Final Demand",
            "location": sites["final"],
            "read": (
                f"The final site has been prepared for exactly this moment. "
                f"Exits are watched, useful cover has been moved into place, "
                f"and {'the rift pulses at the center of the room like a wound that will not close' if any(w in mtype for w in ('rift','arcane','magical')) else f'the thing at the center of {title} waits where everyone can see it but no one can safely touch it'}. "
                f"The opposition offers one last bargain before blades, spells, or accusations decide the room."
            ),
            "notes": [
                "Run this as a confrontation with a combat spine: negotiation can change targets, terrain, or stakes.",
                "The antagonist wants to leave with leverage. If cornered, they threaten the mission objective first.",
                "A clever party can win by exposing, binding, banishing, bargaining, or defeating the threat.",
            ],
            "npcs": [f"{enemy} leader - antagonist - wants the objective, the secret, or the witness silenced."],
            "checks": [
                f"Persuasion or Deception DC {ctx['dc'] + 2}: force a concession before combat.",
                f"Arcana or Thieves' Tools DC {ctx['dc'] + 1}: secure the objective during the fight.",
                f"Intimidation DC {ctx['dc'] + 2}: make lesser enemies break when the leader is bloodied.",
            ],
            "transition": "When the dust settles, the faction must decide what truth becomes public.",
        },
    ]


def _enemy_name(mission_type: str, faction: str) -> str:
    low = mission_type.lower()
    if any(w in low for w in ("battle", "assault", "raid")):
        return f"{faction} Warband" if faction and faction.lower() != "independent" else "Undercity Warband"
    if any(w in low for w in ("defense", "defend", "siege")):
        return f"{faction} Assault Force" if faction and faction.lower() != "independent" else "Siege Breakers"
    if "ambush" in low:
        return "Contract Knives"
    if "investigation" in low:
        return "Evidence Broker"
    if "rift" in low:
        return "Rift-Touched Enforcer"
    if "escort" in low:
        return "Route Breaker"
    if faction and faction.lower() != "independent":
        return f"{faction} Renegade"
    return "Undercity Fixer"


def _module_markdown(ctx: dict, scenes: list[dict]) -> str:
    scene_md = []
    enemy = ctx.get("enemy") or _enemy_name(ctx.get("mission_type", ""), ctx.get("faction", ""))
    for i, scene in enumerate(scenes, 1):
        notes = "\n".join(f"- {n}" for n in scene["notes"])
        npcs = "\n".join(f"- {n}" for n in scene["npcs"])
        checks = "\n".join(f"- {c}" for c in scene["checks"])
        battlefield = ""
        is_combat_type = any(
            w in ctx.get("mission_type", "").lower()
            for w in ("battle", "defense", "defend", "siege", "assault", "ambush", "raid")
        )
        if i in (3, 5):
            features = scene.get("map_features") or [
                "stacked crates", "stone buttresses", "market awnings", "overturned carts"
            ]
            if is_combat_type:
                # Multi-wave battlefield block for battle/defense missions
                wave_label = "Wave" if "battle" in ctx.get("mission_type", "").lower() or "assault" in ctx.get("mission_type", "").lower() else "Push"
                if i == 3:
                    battlefield = (
                        "\n### Battlefield\n"
                        f"- Cover: {', '.join(features[:4])}.\n"
                        "- Lighting: dim unless the party acts; bright light reveals the enemy entry point.\n"
                        f"\n**{wave_label} 1 — Probe** *(opening engagement)*\n"
                        f"- Light opposition: 2–3 scouts or skirmishers test the party's response.\n"
                        "- Tactics: hit-and-run, draw fire, identify the biggest threat. They are not trying to win yet.\n"
                        "- Ends when: opposition retreats or is reduced below half.\n"
                        f"\n**Between {wave_label}s — The Lull**\n"
                        "- The party has 1 round (6 seconds) to reposition, use a potion, or take cover before the next push.\n"
                        "- DM: describe sounds of regrouping — barked orders, the clatter of heavier armour moving into place.\n"
                        f"\n**{wave_label} 2 — Main Force** *(this scene's primary encounter)*\n"
                        f"- Heavier troops arrive from a second entry point the party may not be watching.\n"
                        "- Tactics: split the party's attention; the leader hangs back until the party is committed.\n"
                        f"- {enemy} commander visible but not yet engaged — watching, choosing the moment.\n"
                        "- Ends when: party neutralises the commander or main force breaks morale.\n"
                    )
                elif i == 5:
                    battlefield = (
                        "\n### Battlefield\n"
                        f"- Cover: {', '.join(features[:4])}.\n"
                        "- Lighting: dim unless the party acts; bright light reveals the enemy entry point.\n"
                        f"\n**{wave_label} 1 — Shock** *(immediate pressure)*\n"
                        "- Veteran fighters, not scouts. They know where the party will be.\n"
                        "- Tactics: deny the chokepoint, separate spellcasters from melee, suppress healing.\n"
                        "- Ends when: reduced to one fighter standing or leader enters.\n"
                        f"\n**Between {wave_label}s — Hard Choice**\n"
                        "- The party can chase the retreating wave OR prepare a position for what's coming.\n"
                        "- Chasing costs action economy. Preparing costs time the clock may not have.\n"
                        f"\n**{wave_label} 2 — The Named Threat** *(boss entry)*\n"
                        f"- {enemy} leader arrives personally with 1–2 elite bodyguards.\n"
                        "- Tactics: the leader targets whoever hurt the most fighters in the previous wave.\n"
                        "- At half HP: offers terms, reveals hidden leverage, or triggers an environmental effect.\n"
                        f"\n**{wave_label} 3 — If They Stall** *(escalation clock)*\n"
                        "- If the party does not press the advantage after Wave 2, a third group arrives to encircle.\n"
                        "- This is the kill box. No more reinforcements for the party. Finishing it fast matters.\n"
                    )
            else:
                battlefield = (
                    "\n### Battlefield\n"
                    f"- Cover: {', '.join(features[:4])}.\n"
                    "- Hazards: difficult terrain, unstable shelves, loose braziers, exposed conduits, or panicked bystanders.\n"
                    "- Lighting: dim unless the party brings their own; bright light reveals one hidden route.\n"
                    "- Tactics: lesser foes delay and flank; the leader targets whoever protects the objective.\n"
                )
        stat = ""
        if i == 3:
            stat = _stat_block(ctx, "Scout")
        elif i == 5:
            stat = _stat_block(ctx, "Leader")
        scene_md.append(
            f"### Scene {i}: {scene['name']}\n\n"
            f"{i} - {scene['location']}\n\n"
            f"READ ALOUD:\n{scene['read']}\n\n"
            f"DM NOTE:\n{notes}\n\n"
            f"### NPCs Present\n{npcs}\n\n"
            f"### Checks and Branches\n{checks}\n\n"
            f"### What Happens\n"
            f"- If the party succeeds quickly, they keep surprise or gain advantage on the next scene's first check.\n"
            f"- If the party fails forward, add a complication from the chart pack and keep the trail moving.\n"
            f"- If the party stalls, an NPC acts first and changes the situation visibly.\n"
            + "".join(f"- {w}\n" for w in scene.get("what_happens", [])[:3])
            + f"{battlefield}\n"
            + (f"### Treasure\n{scene['treasure']}\n\n" if scene.get("treasure") and scene.get("treasure") != "None" else "")
            + f"### Transition\n{scene['transition']}\n\n"
            + f"{stat}"
        )

    return (
        f"# {ctx['title']}\n\n"
        f"An adventure for {get_party_size()} characters. Recommended challenge: CR {ctx['cr']}.\n\n"
        f"## Adventure Background\n"
        f"{ctx['public_text']}\n\n"
        f"Behind the post, {ctx.get('secret_truth') or ctx['private_notes'] or 'the contract is messier than the board admits.'} "
        f"The important truth should surface through play, not through a boxed exposition speech.\n\n"
        f"## Adventure Summary\n"
        f"The characters accept the contract from {ctx['contact_name']}, follow leads through {ctx['primary_location']}, "
        f"survive a deliberate bad turn, discover what was hidden, and confront the force trying to control the outcome.\n\n"
        f"## Running the Adventure\n"
        f"Keep the session moving by giving every scene an automatic clue, a check-gated clue, and a consequence. "
        f"Use the DCs below as defaults; raise or lower them by 2 for especially strong plans or bad circumstances.\n\n"
        + "\n\n---\n\n".join(scene_md)
        + f"\n\n## Resolution\n"
        f"If the party completes the objective, {ctx['faction']} pays {ctx['reward']} and the truth becomes leverage. "
        f"If they fail, the opposition keeps the initiative and one unresolved thread becomes tomorrow's bulletin.\n"
    )


def _stat_block(ctx: dict, role: str) -> str:
    cr = ctx["cr"]
    prof = max(2, min(6, 2 + cr // 5))
    hp = 18 + cr * (6 if role == "Scout" else 10)
    ac = 13 + min(5, cr // 4) + (1 if role == "Leader" else 0)
    dmg = 5 + cr * (2 if role == "Scout" else 3)
    name = f"{ctx['enemy']} {role}"
    return (
        f">> {name}\n"
        f">> Medium humanoid, typically neutral evil\n"
        f">> Armor Class {ac}; Hit Points {hp} ({max(3, cr)}d8 + {cr * 3}); Speed 30 ft.\n"
        f">> STR {12 + cr // 3} (+{max(1, cr // 3)}) DEX {14 + cr // 4} (+{max(2, cr // 4)}) CON {12 + cr // 3} (+{max(1, cr // 3)}) INT 11 (+0) WIS 12 (+1) CHA 13 (+1)\n"
        f">> Saving Throws Dex +{prof + 2}, Wis +{prof + 1}; Skills Deception +{prof + 1}, Perception +{prof + 1}, Stealth +{prof + 2}\n"
        f">> Senses passive Perception {11 + prof}; Languages Common plus one faction code; Challenge {max(1, cr // (2 if role == 'Scout' else 1))}\n"
        f">> Multiattack. The {role.lower()} makes two attacks.\n"
        f">> Hooked Blade. Melee Weapon Attack: +{prof + 3} to hit, reach 5 ft., one target. Hit: {dmg} slashing damage, and the target cannot take reactions until the start of its next turn.\n"
        f">> Smoke Step (Recharge 5-6). The {role.lower()} moves up to half its speed without provoking opportunity attacks and can Hide if lightly obscured.\n"
        f">> Tactics. Round 1: isolate the objective holder. Bloodied: bargain, threaten evidence, or retreat toward prepared cover.\n\n"
    )


def _dm_guide_markdown(ctx: dict, scenes: list[dict]) -> str:
    beats = "\n".join(f"- Scene {i}: {s['name']} at {s['location']}." for i, s in enumerate(scenes, 1))
    clock = ctx.get("failure_clock") or [
        "The opposition realizes the party is involved.",
        "The key witness or object is moved.",
        "The faction loses control of the story publicly.",
    ]
    clock_md = "\n".join(f"- {step}" for step in clock[:3])
    return (
        f"## Adventure Background\n{ctx['public_text']}\n\n"
        f"## Secret Truths\n"
        f"- {ctx.get('secret_truth') or ctx['private_notes'] or 'The contact is omitting the detail that makes the contract dangerous.'}\n"
        f"- The opposition wants leverage more than slaughter.\n"
        f"- The final scene should reveal a choice, not only a fight.\n\n"
        f"## Failure Clock\n{clock_md}\n\n"
        f"## Adventure Summary\n{beats}\n\n"
        f"## Faction Stakes\n"
        f"- {ctx['faction']}: wants the objective recovered without public embarrassment.\n"
        f"- {ctx['opposing_faction']}: benefits if the truth stays buried.\n"
        f"- Independent witnesses: want to survive being useful.\n\n"
        f"## Pacing Notes\n"
        f"- Briefing: 15 minutes.\n- Leads: 45 minutes.\n- Complication: 35 minutes.\n"
        f"- Evidence room: 35 minutes.\n- Finale and resolution: 60-90 minutes.\n\n"
        f"## Adjusting Difficulty\n"
        f"- Smaller party: remove one scout and lower all DCs by 2.\n"
        f"- Larger party: add terrain hazards and one additional scout in scenes 3 and 5.\n"
        f"- Strong party: give the leader a hostage, unstable objective, or timed ritual.\n"
    )


def _players_guide_markdown(ctx: dict) -> str:
    return (
        f"## The Contract\n{ctx['public_text']}\n\n"
        f"## Known Contact\n"
        f"- {ctx['contact_name']} at {ctx['contact_location']}.\n\n"
        f"## Known Dangers\n"
        f"- The job is listed as {ctx['tier'].upper()} tier and typed as {ctx['mission_type']}.\n"
        f"- The posting faction is {ctx['faction']}.\n"
        f"- The reward is {ctx['reward']}.\n\n"
        f"## Player Hooks\n"
        f"- You owe {ctx['faction']} a small favor and this is a clean way to settle it.\n"
        f"- Someone you know works near {ctx['primary_location']} and has gone quiet.\n"
        f"- The object, person, or secret at stake sounds too dangerous to leave on the board.\n"
    )


def _chart_pack_markdown(ctx: dict) -> str:
    budget = get_encounter_budget(ctx["cr"])
    rumors = (ctx.get("rumors") or [])[:8] or [
        "The contact has been asking about the wrong name on purpose.",
        "A courier changed routes after seeing a familiar faction sign.",
        "The last witness refuses payment but accepts protection.",
        "Someone cleaned the obvious evidence and missed the small evidence.",
        "The opposition has orders to delay, not kill.",
        "The public reward is not the real reason the job matters.",
        "A local official knows more and is pretending this is routine.",
        "The final site has already been prepared for visitors.",
    ]
    rumor_rows = "\n".join(f"| {i} | {r} | {'True' if i % 3 else 'Half true'} |" for i, r in enumerate(rumors, 1))
    return (
        f"## Encounter Budget\n"
        f"| Difficulty | XP Budget per Character |\n|---|---|\n"
        + "\n".join(f"| {k.title()} | {v} |" for k, v in budget.items())
        + "\n\n## Rumor Chart\n| d8 | Rumor | Truth |\n|---|---|---|\n"
        + rumor_rows
        + f"\n\n## Complication Table\n| d6 | Complication | Effect |\n|---|---|---|\n"
        f"| 1 | Patrol interruption | A scene becomes public unless the party acts quietly. |\n"
        f"| 2 | Evidence moved | The clue is still present, but now costs a DC {ctx['dc'] + 1} check. |\n"
        f"| 3 | Contact panics | The contact flees toward danger with useful information. |\n"
        f"| 4 | Rival crew arrives | They want the same objective for a different employer. |\n"
        f"| 5 | Structural hazard | Each round, one area becomes difficult terrain. |\n"
        f"| 6 | The truth is worse | Add one moral cost to the cleanest solution. |\n\n"
        f"## Rewards\n"
        f"- Contract reward: {ctx['reward']}.\n"
        f"- Bonus: advantage on the next social check with {ctx['faction']} if the truth is handled discreetly.\n"
        f"- Unique find: a coded token, damaged key, ritual splinter, or signed ledger page tied to {ctx['title']}.\n"
    )


_MTYPE_TO_MAP_TYPE: Dict[str, str] = {
    # infiltration / sabotage — multi-level building with crawlspaces
    "infiltration": "multi_level_building",
    "sabotage":     "multi_level_building",
    # street movement
    "escort":       "city_street",
    "courier":      "city_street",
    # open combat / siege
    "battle":       "urban_combat",
    "assault":      "urban_combat",
    "defense":      "fortified_interior",
    "siege":        "fortified_interior",
    # stealth / targeted
    "heist":        "vault_interior",
    "retrieval":    "vault_interior",
    "bounty":       "rooftop",
    "assassination":"private_interior",
    # search / discovery
    "investigation":"interior",
    # supernatural
    "rift":         "arcane_chamber",
    "ambush":       "alley",
}


def _mission_map_type(ctx: dict, scene: dict) -> str:
    """Pick the right A1111 map type based on mission type and scene name."""
    mtype = ctx.get("mission_type", "").lower()
    for key, map_type in _MTYPE_TO_MAP_TYPE.items():
        if key in mtype:
            return map_type
    # Fallback: guess from scene name keywords
    sname = (scene.get("name", "") + " " + scene.get("location", "")).lower()
    if any(w in sname for w in ("room", "chamber", "vault", "hidden", "office")):
        return "interior"
    if any(w in sname for w in ("street", "alley", "market", "road", "plaza")):
        return "city_street"
    if any(w in sname for w in ("roof", "rooftop", "tower top")):
        return "rooftop"
    if any(w in sname for w in ("sewer", "tunnel", "drain")):
        return "sewer"
    return "interior"


def _map_manifest(ctx: dict, scenes: list[dict]) -> list[dict]:
    entries = []
    bp_maps = (ctx.get("blueprint") or {}).get("maps") if isinstance(ctx.get("blueprint"), dict) else None
    by_name = {m.get("name"): m for m in bp_maps or [] if isinstance(m, dict)}
    for scene in scenes[1:5]:
        override = by_name.get(scene["location"], {})
        features = override.get("features") or scene.get("map_features") or ["cover", "multiple entrances", "visible clue", "dangerous terrain"]
        map_type = override.get("type") or _mission_map_type(ctx, scene)
        entries.append({
            "name":         override.get("name") or scene["location"],
            "type":         map_type,
            "mission_type": ctx.get("mission_type", ""),
            "description":  scene["read"],
            "size":         "30x30",
            "features":     features,
            "ascii": "....................\n..####......####....\n..#..D......D..#....\n..#..T..##..T..#....\n..####......####....\n....................",
        })
    return entries


def _quality_report(module_md: str, ctx: dict, scenes: list[dict], used_blueprint: bool) -> tuple[int, str]:
    checks = [
        ("Published-format guide loaded", bool(ctx.get("format_guide"))),
        ("Has adventure background", "## Adventure Background" in module_md),
        ("Has adventure summary", "## Adventure Summary" in module_md),
        ("Has at least five scenes", len(scenes) >= 5),
        ("Uses numbered areas", len(re.findall(r"\n\d+\s+-\s+", module_md)) >= 5),
        ("Has read-aloud blocks", module_md.count("READ ALOUD:") >= 5),
        ("Has DM-only notes", module_md.count("DM NOTE:") >= 5),
        ("Has concrete DC checks", len(re.findall(r"\bDC\s+\d+", module_md)) >= 8),
        ("NPC lines include secrets", "hides" in module_md.lower() or "hide" in module_md.lower()),
        ("Has failure-forward procedure", "fails forward" in module_md.lower() or "failure" in module_md.lower()),
        ("Has immediate stat blocks", module_md.count(">> ") >= 16),
        ("Has battlefield/tactics", "### Battlefield" in module_md and "Tactics" in module_md),
        ("Has resolution/rewards", "## Resolution" in module_md and ctx["reward"] in module_md),
    ]
    earned = sum(1 for _, ok in checks if ok)
    score = round(100 * earned / len(checks))
    lines = [
        f"# Module Quality Report - {ctx['title']}",
        "",
        f"Score: {score}/100 ({earned}/{len(checks)} checks)",
        "",
        "This is an automated structural comparison against the local TrainingPDFS format guide.",
        f"Optional LLM blueprint used: {'yes' if used_blueprint else 'no'}",
        "",
    ]
    for label, ok in checks:
        lines.append(f"- [{'x' if ok else ' '}] {label}")
    lines.extend([
        "",
        "Notes:",
        "- The report checks published-module structure, table usability, and failure-forward design.",
        "- It does not certify prose as official quality; it flags whether the generated module has the bones of one.",
    ])
    return score, "\n".join(lines) + "\n"


async def generate_published_module(mission: dict, player_name: str = "") -> Optional[Path]:
    """Generate a table-ready module and return index.html."""
    from src.mission_builder import gather_context
    seed = _mission_seed(mission)
    ctx = gather_context(mission)
    ctx.update(seed)
    ctx["primary_location"] = _infer_primary_location(seed, ctx.get("primary_location", ""))
    ctx["cr"] = get_cr(seed["tier"])
    ctx["dc"] = _dc(ctx["cr"])
    ctx["goal"] = _goal_from_title(seed["title"], seed["mission_type"])
    ctx["enemy"] = _enemy_name(seed["mission_type"], seed["opposing_faction"] if seed["opposing_faction"] != "None" else seed["faction"])
    ctx["format_guide"] = _load_format_guide()

    out_dir = _make_output_dir(ctx["title"])
    logger.info(f"[PUBLISHED] Building table-first module: {ctx['title']!r} -> {out_dir}")

    blueprint = await _generate_blueprint(ctx)
    if blueprint:
        ctx["blueprint"] = blueprint
        ctx["secret_truth"] = _clean(blueprint.get("secret_truth") or "")
        ctx["failure_clock"] = blueprint.get("failure_clock") or []
        ctx["rumors"] = blueprint.get("rumors") or []
        villain = blueprint.get("villain") or {}
        if isinstance(villain, dict) and villain.get("name"):
            ctx["enemy"] = _clean(villain.get("name"))

    scenes = _scene_data(ctx)
    module_md = _module_markdown(ctx, scenes)
    components = {
        "dm_guide": ("DM Guide", _dm_guide_markdown(ctx, scenes)),
        "module": ("Module", module_md),
        "players_guide": ("Players Guide", _players_guide_markdown(ctx)),
        "chart_pack": ("Chart Pack", _chart_pack_markdown(ctx)),
    }

    component_links: list[tuple[str, str]] = []
    for slug, (label, md) in components.items():
        path = out_dir / f"{slug}.html"
        path.write_text(render_component(label, ctx["title"], md, ctx["faction"]), encoding="utf-8")
        component_links.append((slug, path.name))

    # Inject scene dialogs + visual clues into module.html
    try:
        from src.mission_builder.scene_dialogs import patch_module_file
        module_html_path = out_dir / "module.html"
        await patch_module_file(module_html_path, ctx)
        logger.info(f"[PUBLISHED] Scene dialogs injected into module.html")
    except Exception as _e:
        logger.warning(f"[PUBLISHED] Scene dialog injection failed: {_e}")

    manifest = _map_manifest(ctx, scenes)
    manifest_path = out_dir / "maps_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Write placeholder maps.html — will be overwritten after PNG generation below
    (out_dir / "maps.html").write_text(
        render_maps_page(ctx["title"], ctx["faction"], [], json.dumps(manifest, indent=2)),
        encoding="utf-8",
    )
    component_links.append(("maps", "maps.html"))

    score, report = _quality_report(module_md, ctx, scenes, used_blueprint=bool(blueprint))
    report_path = out_dir / "quality_report.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info(f"[PUBLISHED] Quality score: {score}/100 -> {report_path.name}")

    map_paths: list[Path] = []
    if str(__import__("os").getenv("MODULE_GENERATE_MAPS", "false")).lower() in ("1", "true", "yes", "on"):
        try:
            from src.mission_builder.novel_pipeline import _pass5_generate_maps
            map_paths = await _pass5_generate_maps({"maps": manifest_path}, ctx["title"], out_dir)
        except Exception as e:
            logger.warning(f"[PUBLISHED] Optional map generation failed: {e}")

    # Rewrite maps.html now that we know which PNGs were actually generated
    (out_dir / "maps.html").write_text(
        render_maps_page(ctx["title"], ctx["faction"], map_paths, json.dumps(manifest, indent=2)),
        encoding="utf-8",
    )

    # Generate tablet session runner from module scenes
    try:
        from src.mission_builder.session_runner import extract_scenes, generate_session_html
        session_scenes = extract_scenes(out_dir / "module.html")
        _mid = None
        try:
            from src.db_api import raw_query as _rq
            _rows = _rq("SELECT id FROM missions WHERE title=%s LIMIT 1", (ctx["title"],))
            if _rows:
                _mid = _rows[0]["id"]
        except Exception:
            pass
        session_path = generate_session_html(
            out_dir=out_dir,
            mission_title=ctx["title"],
            faction=ctx["faction"],
            tier=ctx["tier"],
            player_name=player_name or "Party",
            mission_id=_mid,
            scenes=session_scenes,
        )
        component_links.append(("session", "session.html"))
        logger.info(f"[PUBLISHED] Session runner: {session_path.name} ({len(session_scenes)} scenes)")
    except Exception as e:
        logger.warning(f"[PUBLISHED] Session runner generation failed: {e}")

    index_html = render_index(
        novel_title=ctx["title"],
        faction=ctx["faction"],
        tier=ctx["tier"],
        cr=ctx["cr"],
        player_name=player_name or "Open",
        chapters=[],
        components=component_links,
        chart_pack=None,
        map_count=len(map_paths) or len(manifest),
    )
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(out_dir.rglob("*")):
            if file.is_file():
                zf.write(file, arcname=file.relative_to(out_dir.parent))

    # Write module_slug back to missions table so the dashboard can link directly
    try:
        from src.db_api import raw_execute as _rx
        _rx(
            "UPDATE missions SET module_slug=%s WHERE title=%s",
            (out_dir.name, ctx["title"]),
        )
        logger.info(f"[PUBLISHED] module_slug '{out_dir.name}' written to missions DB")
    except Exception as _e:
        logger.warning(f"[PUBLISHED] Could not write module_slug to DB: {_e}")

    logger.info(f"[PUBLISHED] Complete: {ctx['title']!r} -> {zip_path.name} ({zip_path.stat().st_size // 1024}KB)")
    return index_path
