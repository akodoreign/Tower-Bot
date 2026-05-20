"""
recovery_pipeline.py - standalone Recovery mission modules.

Recovery is not Rescue. The target is a thing, record, relic, memory,
identity packet, lost gear, misplaced cargo, evidence, or missing pet.
If a living person is the main target, route that mission to Rescue instead.

Core identity:
  - find the target
  - learn what happened to it
  - retrieve it cleanly
  - return it to the hiring faction for pay

Exported:
    build_recovery_module(mission: dict, out_dir: Path) -> Path
    is_recovery_mission(mission_type: str) -> bool
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from src.log import logger
from src.mission_builder.html_renderer import _faction_color, _page
from src.mission_builder.cr_scaling import mission_cr, party_strength as _party_strength

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "generated_modules"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")


RECOVERY_KEYWORDS = {
    "recovery", "recover", "retrieve", "retrieval", "relic recovery",
    "artifact recovery", "evidence recovery", "lost gear", "misdelivered",
    "misplaced", "black box", "data recovery", "record recovery",
    "memory recovery", "identity recovery", "missing pet", "lost pet",
}

RESCUE_OVERLAP = {
    "rescue", "hostage", "captive", "survivor", "extract person",
    "recover survivor", "save them", "evacuate civilians",
}


def is_recovery_mission(mission_type: str) -> bool:
    low = (mission_type or "").lower()
    if any(k in low for k in RESCUE_OVERLAP):
        return False
    return any(k in low for k in RECOVERY_KEYWORDS)


TARGET_TYPES: Dict[str, Dict[str, Any]] = {
    "evidence": {
        "label": "Evidence Recovery",
        "examples": ["sealed testimony crystal", "blood-marked weapon", "trial ledger", "security recording", "signed confession"],
        "pay": "standard EC, little or no Kharma",
        "success_bias": "chain of custody and intact readability matter most",
        "map_bias": "archives, evidence lockers, crime scenes, offices",
    },
    "relic": {
        "label": "Relic / Artifact Recovery",
        "examples": ["pre-Dome relic", "saint icon", "rift-touched tool", "family heirloom", "Tower-grown mechanism"],
        "pay": "good EC, Kharma only if sacred/community value is clear",
        "success_bias": "return intact and contained",
        "map_bias": "vaults, galleries, ruins, hidden shrines",
    },
    "lost_gear": {
        "label": "Lost Expedition Gear",
        "examples": ["failed party satchel", "field journals", "sample kit", "lucky rope", "charter badge"],
        "pay": "low to standard EC, some Kharma if it helps families or the guild",
        "success_bias": "recover the useful pieces and reconstruct what happened",
        "map_bias": "collapsed rooms, rift-scored alleys, abandoned camps",
    },
    "memory_identity": {
        "label": "Memory / Identity Recovery",
        "examples": ["Obsidian Lotus memory packet", "stolen name contract", "identity papers", "soul record", "copied childhood"],
        "pay": "good EC, messy reputation consequences",
        "success_bias": "return sealed and unexamined unless ordered otherwise",
        "map_bias": "private salons, black archives, hidden clinics",
    },
    "data_record": {
        "label": "Data / Record Recovery",
        "examples": ["Tower log", "rift telemetry", "coroner record", "guild registry fragment", "missing delivery manifest"],
        "pay": "standard EC, Kharma only when public safety is involved",
        "success_bias": "readable, complete, and verified",
        "map_bias": "records offices, relay rooms, scriptoriums, machine rooms",
    },
    "misplaced_cargo": {
        "label": "Misdelivered / Misplaced Cargo",
        "examples": ["wrong-warehouse crate", "reality-pocket package", "mis-signed shipment", "auction lot", "unclaimed courier tube"],
        "pay": "standard EC, usually no Kharma",
        "success_bias": "bring the right cargo back without opening or substituting it",
        "map_bias": "warehouses, loading bays, train depots, counting houses",
    },
    "missing_pet": {
        "label": "Missing Pet Recovery",
        "examples": ["tower-cat with a collar charm", "familiar that refuses summons", "glasssong hound", "clockwork ferret", "kid's lizard-drake"],
        "pay": "low EC, some Kharma",
        "success_bias": "bring the pet home alive, calm, and recognisable",
        "map_bias": "markets, alleys, rooftops, sewers, garden walls",
    },
}

COMPLICATIONS = [
    "Someone else found it first and thinks possession means ownership.",
    "The place changed after a rift collapse, sewer shift, fire, or Tower recycling event.",
    "The target is dangerous to touch, read, open, or remember.",
    "Ownership is technically simple but emotionally ugly.",
    "The target is incomplete and the missing piece changes the payout.",
    "A rival adventuring party is following the same trail.",
    "A clerk, fence, or witness signed for it under a name that should not exist.",
    "The hiring faction is correct legally and unpleasant morally.",
    "The item wants to be found by someone else.",
    "The target is ordinary, but what happened around it is not.",
]

RETRIEVAL_SHAPES = [
    "careful extraction",
    "race against another crew",
    "scene reconstruction",
    "negotiated handoff",
    "bureaucratic unravelling",
    "hazard handling",
    "quiet search through a changed place",
]

FACTION_STYLE = {
    "Obsidian Lotus": "quiet custody, memory discipline, anonymous recovery, no public paper trail",
    "Iron Fang Consortium": "strict contract, receipts, insurance language, no excuses",
    "Glass Sigil": "archive rights, secrecy, elegant pressure, high pay for difficult scholarship",
    "Guild of Ashen Scrolls": "scholarly chain of custody, provenance, careful notes, peer review",
    "Wardens of Ash": "public safety, duty, proof, protecting the weak over profit",
    "Patchwork Saints": "community stakes, sentimental value, people first, warm but cash-poor",
    "Wizards Tower": "arcane handling protocols, failed scholars, dangerous objects, expensive embarrassment",
    "Tower Authority": "forms, warrants, evidence tags, official procedure",
    "Argent Blades": "lost gear, trophy proof, rival crews, pride and reputation",
    "Serpent Choir": "sacred custody, omen logic, ritual ownership, unsettling sincerity",
    "Brother Thane's Cult": "returned records, burial claims, faith debt, reverent pressure",
    "Adventurers Guild": "failed expedition gear, lost party proof, rival party records, job-board accountability",
}


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text or "mission").strip().replace(" ", "_")[:maxlen] or "mission"


def _db_rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        from src.db_api import raw_query
        return raw_query(sql, params) or []
    except Exception as e:
        logger.debug(f"[RECOVERY] DB read skipped: {e}")
        return []


def _json_col(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return fallback
    return fallback


GENERIC_PLAN_MARKERS = {
    "recovery target",
    "lost item",
    "missing object",
    "generic recovery",
    "the sponsor needs the item",
}


def _mission_text(mission: dict) -> str:
    parts: List[str] = []
    for key in ("title", "type", "mission_type", "tier", "faction", "npc_giver", "body", "description", "private_notes"):
        value = mission.get(key)
        if value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def _mission_context(mission: dict) -> Dict[str, Any]:
    text = _mission_text(mission)
    terms = []
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9'’.-]*(?:\s+[A-Z][A-Za-z0-9'’.-]*){0,4}\b", text):
        term = match.group(0).strip()
        if term.lower() not in {"mission", "recovery", "standard", "posted"} and term not in terms:
            terms.append(term)
    objects = re.findall(r"\b(?:relic|artifact|ledger|record|cargo|shipment|pet|familiar|gear|journal|evidence|manifest|memory|identity|contract|shard|icon)\b", text, flags=re.I)
    stakes = re.findall(r"[^.!?\n]*(?:recover|retrieve|missing|lost|stolen|custody|return|proof|owner|rival|pay|contract|evidence)[^.!?\n]*", text, flags=re.I)
    return {
        "full_text": text[:1800],
        "canon_terms": terms[:14],
        "objects": sorted({o.lower() for o in objects})[:8],
        "stakes": [s.strip() for s in stakes[:6] if s.strip()],
    }


def _specificity_score(plan: Dict[str, Any], context: Dict[str, Any]) -> int:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    score = 0
    for term in context.get("canon_terms", []):
        if term.lower() in blob:
            score += 2
    for obj in context.get("objects", []):
        if obj.lower() in blob:
            score += 1
    for stake in context.get("stakes", []):
        words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", stake)[:4]]
        if words and any(w in blob for w in words):
            score += 1
    return score


def _is_generic_plan(plan: Dict[str, Any], context: Dict[str, Any]) -> bool:
    blob = json.dumps(plan, ensure_ascii=False).lower()
    has_context = bool(context.get("canon_terms") or context.get("objects") or context.get("stakes"))
    return (has_context and _specificity_score(plan, context) < 3) or any(marker in blob for marker in GENERIC_PLAN_MARKERS)


def _party_strength() -> Dict[str, Any]:
    rows = _db_rows("SELECT char_name, snapshot_json, fetched_at FROM latest_character_snapshots ORDER BY fetched_at DESC")
    pcs = []
    for row in rows:
        snap = _json_col(row.get("snapshot_json"), {})
        if not isinstance(snap, dict):
            continue
        level = int(snap.get("total_level") or 0)
        if level <= 0:
            continue
        pcs.append({
            "name": snap.get("name") or row.get("char_name"),
            "level": level,
            "classes": snap.get("classes") or snap.get("class") or {},
            "skills": snap.get("skills") or {},
            "max_hp": int(snap.get("max_hp") or 0),
        })
    levels = [p["level"] for p in pcs] or [5]
    return {
        "party_size": len(pcs) or 4,
        "avg_level": round(sum(levels) / len(levels), 1),
        "max_level": max(levels),
        "pcs": pcs,
    }


def _party_note(strength: Dict[str, Any]) -> str:
    names = ", ".join(p["name"] for p in strength.get("pcs", [])[:6]) or "current party"
    return f"Live party read: {strength['party_size']} PCs, average level {strength['avg_level']}, max level {strength['max_level']} ({names})."


def _dc_profile(tier: str, strength: Dict[str, Any]) -> Dict[str, int]:
    tier_bump = {
        "local": -1, "patrol": 0, "standard": 1, "escort": 1,
        "investigation": 1, "rift": 2, "dungeon": 2, "major": 2,
        "inter-guild": 3, "high-stakes": 4, "epic": 5, "divine": 5, "tower": 5,
    }.get((tier or "standard").lower(), 1)
    level_bump = max(0, int(strength["avg_level"]) - 5) // 3
    base = 12 + tier_bump + level_bump
    return {
        "locate": base + 1,
        "verify": base + 2,
        "handle": base + 3,
        "extract": base + 3,
        "negotiate": base + 1,
        "chase": base + 2,
    }


def _pick_target_type(mission: dict) -> str:
    text = " ".join(str(mission.get(k, "")) for k in ("title", "type", "mission_type", "body", "description")).lower()
    if any(k in text for k in ("pet", "familiar", "hound", "cat", "ferret")):
        return "missing_pet"
    if any(k in text for k in ("evidence", "ledger", "confession", "trial", "weapon")):
        return "evidence"
    if any(k in text for k in ("relic", "artifact", "heirloom", "icon")):
        return "relic"
    if any(k in text for k in ("gear", "expedition", "lucky rope", "satchel", "journal")):
        return "lost_gear"
    if any(k in text for k in ("memory", "identity", "name", "soul record")):
        return "memory_identity"
    if any(k in text for k in ("data", "record", "log", "telemetry", "registry", "manifest")):
        return "data_record"
    if any(k in text for k in ("cargo", "misdelivered", "misplaced", "warehouse", "shipment")):
        return "misplaced_cargo"
    return random.choice(list(TARGET_TYPES))


def _pick_context(target_type: str) -> Dict[str, Any]:
    if target_type == "missing_pet":
        clause = "place_type IN ('market','garden','residence','street','sewer','tavern')"
    elif target_type in ("data_record", "evidence"):
        clause = "place_type IN ('archive','office','guildhall','civic','library','court','morgue')"
    elif target_type == "misplaced_cargo":
        clause = "place_type IN ('warehouse','market','dock','station','shop','factory')"
    elif target_type == "relic":
        clause = "place_type IN ('shrine','museum','vault','archive','ruin','gallery')"
    else:
        clause = "1=1"
    rows = _db_rows(
        f"SELECT district, place_type, name, type_tag, description, extra_json FROM gazetteer_places WHERE {clause} ORDER BY RAND() LIMIT 1"
    )
    if rows:
        return rows[0]
    rows = _db_rows("SELECT district, place_type, name, type_tag, description, extra_json FROM gazetteer_places ORDER BY RAND() LIMIT 1")
    return rows[0] if rows else {
        "district": "Cobbleway",
        "place_type": "street",
        "name": "a cramped side street with too many witnesses",
        "description": "A lived-in place where every answer is technically true and not quite useful.",
    }


def _pick_rival_party() -> Dict[str, Any]:
    rows = _db_rows("SELECT party_name, members_json, reputation, status FROM party_profiles WHERE status = 'active' ORDER BY RAND() LIMIT 1")
    if rows:
        row = rows[0]
        return {
            "name": row.get("party_name") or "a rival adventuring party",
            "members": _json_col(row.get("members_json"), []),
            "reputation": row.get("reputation"),
            "status": row.get("status"),
        }
    return {"name": "a rival adventuring party", "members": [], "reputation": None, "status": "unknown"}


def _recent_news() -> str:
    rows = _db_rows("SELECT facts FROM news_memory ORDER BY id DESC LIMIT 6")
    return " | ".join(r.get("facts") or "" for r in rows if r.get("facts"))[:900]


def _faction_style(faction: str) -> str:
    low = (faction or "").lower()
    for key, style in FACTION_STYLE.items():
        if key.lower() in low:
            return style
    return "straight contract, practical concerns, payment on return"


def _reward_profile(target_type: str, mission: dict) -> Dict[str, Any]:
    if target_type == "missing_pet":
        return {"ec": 60, "kharma": 25, "note": "Low pay, some Kharma. This matters because someone loves the animal."}
    tier = (mission.get("tier") or "standard").lower()
    mult = {"local": 0.6, "patrol": 0.8, "standard": 1.0, "investigation": 1.1, "major": 1.4, "inter-guild": 1.8, "high-stakes": 2.2, "epic": 3.0}.get(tier, 1.0)
    base = {
        "evidence": 220,
        "relic": 360,
        "lost_gear": 140,
        "memory_identity": 420,
        "data_record": 260,
        "misplaced_cargo": 240,
    }.get(target_type, 220)
    kharma = 0
    if target_type in ("lost_gear", "relic") and random.random() < 0.35:
        kharma = random.choice([15, 20, 25, 30])
    return {"ec": int(base * mult), "kharma": kharma, "note": TARGET_TYPES[target_type]["pay"]}


async def _ollama(prompt: str, tokens: int = 2400) -> str:
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("recovery_plan", track="primary")
        if not decision.run_now:
            logger.warning(f"[RECOVERY] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=240.0) as c:
            r = await c.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.82, "num_predict": tokens},
                },
            )
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"[RECOVERY] Ollama unavailable: {e}")
        return ""


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


async def _generate_plan(
    mission: dict,
    target_type: str,
    context: Dict[str, Any],
    dcs: Dict[str, int],
    strength: Dict[str, Any],
    rival_party: Dict[str, Any],
    reward: Dict[str, Any],
) -> Dict[str, Any]:
    spec = TARGET_TYPES[target_type]
    faction = mission.get("faction", "Adventurers Guild")
    examples = ", ".join(spec["examples"])
    mission_context = _mission_context(mission)
    prompt = f"""Create a D&D Recovery mission module plan as JSON only.

Recovery is not Rescue. Do not make a living person the main target.

Mission: {mission.get('title', 'Recovery')}
Mission seed: {(mission.get('body') or mission.get('description') or '')[:600]}
Mission canon that must be preserved: {mission_context}
Sponsor faction: {faction}
Faction style: {_faction_style(faction)}
Target type: {target_type} - {spec['label']}
Target examples: {examples}
Context from DB: {context}
Rival party from DB: {rival_party}
Recent news: {_recent_news()}
Party: {_party_note(strength)}
DCs: {dcs}
Reward profile: {reward}

User rules:
- Recovery types include evidence, relic/artifact, lost expedition gear, memory/identity, data/record, misplaced cargo, and missing pets.
- No Rescue overlap. No survivor extraction as the main target.
- Complications depend on target type and faction.
- Success is contextual, but the contract is strict: return to sponsor for full pay.
- Missing pets are low EC with some Kharma.
- Maps are optional; text area descriptions are fine unless a retrieval location really benefits from a map.

Return JSON object only with:
- target_name
- target_description
- chain_of_custody: 5 ordered custody beats from last rightful owner to current holder
- proof_of_recovery: what proves this is the exact mission target, not a substitute
- rival_clock: 4-stage clock showing how a rival, holder, or faction pressure escalates
- briefing
- location_readaloud
- trail: 6 investigation/retrieval trail beats, each with clue, skill, dc, success, fail_forward
- complications: 6 target/faction-specific complications
- retrieval_scene: location, read_aloud (2 sentences DM reads when party reaches the retrieval site), current_holder, approach_options, hazards, handling_rules
- rival_pressure: how rival faction/party may interfere without stealing the whole mission
- moral_note: only if target type deserves one; otherwise say "none"
- map_plan: none/one_map/two_maps plus why
- dialogue_bank: at least 16 lines from sponsor, witness, holder, rival, clerk, local, or pet owner
- outcome_table: intact, usable, truth_only, wrong_holder, lost_destroyed outcomes with pay and consequence
- debrief: strict sponsor response for each outcome
- news_seed
- follow_up_hooks: 5 hooks"""
    data = _parse_json(await _ollama(prompt))
    return _normalize_plan(data, mission, target_type, context, dcs, rival_party)


def _fallback_plan(
    mission: dict,
    target_type: str,
    context: Dict[str, Any],
    dcs: Dict[str, int],
    rival_party: Dict[str, Any],
) -> Dict[str, Any]:
    spec = TARGET_TYPES[target_type]
    mission_context = _mission_context(mission)
    canon = mission_context.get("canon_terms", [])
    object_hint = mission_context.get("objects", [])
    target_name = (canon[0] if canon else random.choice(spec["examples"]).title())
    object_text = ", ".join(object_hint[:3]) or spec["label"].lower()
    _stakes = mission_context.get("stakes") or [f"{target_name} must be returned to the sponsor intact"]
    stake = _stakes[0]
    return {
        "target_name": target_name,
        "target_description": f"A mission-specific {spec['label'].lower()} target tied to {object_text}: {target_name}.",
        "chain_of_custody": ["rightful claimant last had it", "first witness confirms disappearance", "intermediate holder moved or signed for it", "current holder or place has it", "sponsor receives verified return"],
        "proof_of_recovery": f"Verify {target_name} with physical marks, testimony, and one mission-specific detail from the original brief.",
        "rival_clock": ["rival hears the trail", "rival reaches witness first", "holder demands a second price", f"stake escalates: {stake}"],
        "briefing": f"The sponsor needs {target_name} recovered and returned. Payment is on return, not on good intentions.",
        "location_readaloud": f"{context.get('name')} in {context.get('district')} looks ordinary until the trail starts pointing at the wrong doors.",
        "trail": [
            {"clue": "Last confirmed sighting", "skill": "Investigation or Survival", "dc": dcs["locate"], "success": "confirms direction of travel", "fail_forward": "finds the trail late and alerts a rival"},
            {"clue": "Custody mark or signature", "skill": "Insight or History", "dc": dcs["verify"], "success": "identifies who handled it", "fail_forward": "misreads the first holder but finds a new witness"},
            {"clue": "Changed-place evidence", "skill": "Arcana or Perception", "dc": dcs["locate"], "success": "spots where reality shifted", "fail_forward": "takes damage, delay, or attention but reaches the changed area"},
            {"clue": "Current holder", "skill": "Persuasion, Intimidation, or Deception", "dc": dcs["negotiate"], "success": "opens a handoff path", "fail_forward": "handoff becomes expensive or public"},
            {"clue": "Authenticity check", "skill": "Investigation, Arcana, or relevant tool", "dc": dcs["verify"], "success": "proves this is the right target", "fail_forward": "returns with a question mark and reduced pay risk"},
            {"clue": "Extraction moment", "skill": "Sleight of Hand, Athletics, Arcana, or Animal Handling", "dc": dcs["extract"], "success": "gets it out clean", "fail_forward": "gets it out damaged, delayed, or chased"},
        ],
        "complications": random.sample(COMPLICATIONS, 6),
        "retrieval_scene": {
            "location": context.get("name"),
            "read_aloud": f"{context.get('name', 'The place')} in {context.get('district', 'the district')} is quieter than it should be for somewhere that has what you need. You count the exits before you start looking for {object_text}.",
            "current_holder": "someone who can be negotiated with, bypassed, or exposed",
            "approach_options": RETRIEVAL_SHAPES[:4],
            "hazards": ["fragility", "bad paperwork", "watching rivals", "limited time"],
            "handling_rules": ["do not open it", "verify it before leaving", "record who touches it"],
        },
        "rival_pressure": f"{rival_party.get('name')} may arrive late, offer a buyout, or try to claim the credit.",
        "moral_note": "none" if target_type in ("lost_gear", "misplaced_cargo", "missing_pet") else "There may be a better moral claimant, but the sponsor pays only for return.",
        "map_plan": {"mode": "none", "why": "Text areas are enough unless the DM wants a retrieval map."},
        "dialogue_bank": [
            "Sponsor: Payment is on return. Philosophy is unpaid.",
            "Witness: I saw the mark. I did not say I saw who carried it.",
            "Holder: Possession is not theft if nobody came looking.",
            "Clerk: The signature exists. The signer does not.",
            "Rival: We can both walk away paid if you stop being heroic.",
            "Local: That thing made the room colder when you named it.",
            "Sponsor: Damaged is not intact. Do not make me define those words.",
            "Owner: Please, just bring them home.",
        ],
        "outcome_table": {
            "intact": "Full pay.",
            "usable": "Reduced pay.",
            "truth_only": "Partial only if unrecoverable is proven.",
            "wrong_holder": "Usually breach of contract.",
            "lost_destroyed": "No pay and possible debt.",
        },
        "debrief": "Strict sponsor response: paid for return, reduced for partial, no pay for wrong-holder morality plays.",
        "news_seed": "A recovery contract ended with questions about custody, loss, and who gets to call something theirs.",
        "follow_up_hooks": ["rival wants revenge", "record reveals a new name", "owner disputes sponsor", "target was a copy", "pet found something else"],
    }


def _normalize_plan(
    data: Optional[Dict[str, Any]],
    mission: dict,
    target_type: str,
    context: Dict[str, Any],
    dcs: Dict[str, int],
    rival_party: Dict[str, Any],
) -> Dict[str, Any]:
    fallback = _fallback_plan(mission, target_type, context, dcs, rival_party)
    if not isinstance(data, dict):
        return fallback

    plan = {**fallback, **{k: v for k, v in data.items() if v not in (None, "")}}
    for key in ("trail", "complications", "dialogue_bank", "follow_up_hooks"):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    for key in ("chain_of_custody", "rival_clock"):
        value = plan.get(key)
        if isinstance(value, str):
            items = [part.strip(" -") for part in re.split(r"[\n;]", value) if part.strip(" -")]
            plan[key] = items or fallback[key]
        elif not isinstance(value, list) or not value:
            plan[key] = fallback[key]
    if not isinstance(plan.get("retrieval_scene"), dict):
        plan["retrieval_scene"] = fallback["retrieval_scene"]
    if not isinstance(plan.get("outcome_table"), dict):
        plan["outcome_table"] = fallback["outcome_table"]
    if not isinstance(plan.get("map_plan"), (dict, str)):
        plan["map_plan"] = fallback["map_plan"]
    if _is_generic_plan(plan, _mission_context(mission)):
        logger.warning("[RECOVERY] Rejected generic plan; using mission-specific fallback")
        return fallback
    return plan


def _e(v: Any) -> str:
    import html
    return html.escape(str(v or ""))


def _card(title: str, body: str, color: str = "#3a6898") -> str:
    return (
        f'<div style="border-left:4px solid {color};padding:12px 16px;margin:14px 0;'
        f'background:#fafafa;border-radius:0 6px 6px 0;">'
        f'<h2 style="margin:0 0 8px;color:{color};">{_e(title)}</h2>{body}</div>'
    )


def _ul(items: List[Any]) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items or []) + "</ul>"


def _trail_table(trail: List[Dict[str, Any]]) -> str:
    rows = ""
    for beat in trail or []:
        rows += (
            f"<tr><td>{_e(beat.get('clue'))}</td>"
            f"<td>{_e(beat.get('skill'))} DC {_e(beat.get('dc'))}</td>"
            f"<td>{_e(beat.get('success'))}</td>"
            f"<td>{_e(beat.get('fail_forward'))}</td></tr>"
        )
    return "<table><tr><th>Beat</th><th>Check</th><th>Success</th><th>Fail Forward</th></tr>" + rows + "</table>"


def _outcome_table(plan: Dict[str, Any]) -> str:
    outcomes = plan.get("outcome_table") or {}
    if isinstance(outcomes, dict):
        rows = "".join(f"<tr><td>{_e(k.replace('_', ' ').title())}</td><td>{_e(v)}</td></tr>" for k, v in outcomes.items())
    else:
        rows = "".join(f"<tr><td>{_e(i)}</td><td></td></tr>" for i in outcomes)
    return "<table><tr><th>Outcome</th><th>Contract Result</th></tr>" + rows + "</table>"


def _retrieval_html(scene: Dict[str, Any]) -> str:
    if not isinstance(scene, dict):
        return f"<p>{_e(scene)}</p>"
    read_aloud = scene.get("read_aloud", "")
    read_aloud_html = (
        f'<div style="font-style:italic;color:#333;border-left:3px solid #8a5a1f;padding:6px 12px;margin-bottom:10px;">'
        f'{_e(read_aloud)}</div>'
    ) if read_aloud else ""
    return (
        read_aloud_html
        + f"<p><strong>Location:</strong> {_e(scene.get('location'))}</p>"
        f"<p><strong>Current Holder:</strong> {_e(scene.get('current_holder'))}</p>"
        f"<h3>Approach Options</h3>{_ul(scene.get('approach_options', []))}"
        f"<h3>Hazards</h3>{_ul(scene.get('hazards', []))}"
        f"<h3>Handling Rules</h3>{_ul(scene.get('handling_rules', []))}"
    )


def render_module(
    mission: dict,
    target_type: str,
    context: Dict[str, Any],
    plan: Dict[str, Any],
    dcs: Dict[str, int],
    strength: Dict[str, Any],
    reward: Dict[str, Any],
) -> str:
    title = mission.get("title", "Recovery")
    faction = mission.get("faction", "Adventurers Guild")
    fc = _faction_color(faction)
    spec = TARGET_TYPES[target_type]
    reward_text = f"{reward['ec']} EC" + (f" + {reward['kharma']} Kharma" if reward.get("kharma") else "")

    body = ""
    body += _card("Briefing", f"<p>{_e(plan.get('briefing'))}</p><p><strong>Reward:</strong> {_e(reward_text)}. {_e(reward.get('note'))}</p><p>{_e(_party_note(strength))}</p>", fc)
    body += _card("Recovery Target", f"<p><strong>{_e(plan.get('target_name'))}</strong> - {_e(spec['label'])}</p><p>{_e(plan.get('target_description'))}</p><p><strong>Success bias:</strong> {_e(spec['success_bias'])}</p>", "#8a5a1f")
    body += _card("Custody & Proof", f"<h3>Chain of Custody</h3>{_ul(plan.get('chain_of_custody', []))}<p><strong>Proof:</strong> {_e(plan.get('proof_of_recovery'))}</p><h3>Rival Clock</h3>{_ul(plan.get('rival_clock', []))}", "#2a6a2a")
    body += _card("Location Read-Aloud", f"<p><em>{_e(plan.get('location_readaloud'))}</em></p><p><strong>DB Context:</strong> {_e(context.get('name'))} - {_e(context.get('district'))}</p>", "#555")
    body += _card("Trail", _trail_table(plan.get("trail", [])), "#3a6898")
    body += _card("Complications", _ul(plan.get("complications", [])), "#7b1e1e")
    body += _card("Retrieval Scene", _retrieval_html(plan.get("retrieval_scene", {})), "#2a6a2a")
    body += _card("Rival Pressure", f"<p>{_e(plan.get('rival_pressure'))}</p>", "#8a5a1f")
    body += _card("Moral Note", f"<p>{_e(plan.get('moral_note'))}</p>", "#555")
    body += _card("Dialogue Bank", _ul(plan.get("dialogue_bank", [])), "#3a6898")
    body += _card("Outcomes", _outcome_table(plan) + f"<p><strong>Debrief:</strong> {_e(plan.get('debrief'))}</p>", "#2a6a2a")
    body += _card("Map Plan", f"<p>{_e(plan.get('map_plan'))}</p>", "#8a5a1f")
    return _page(title, body, faction)


def render_session(mission: dict, plan: Dict[str, Any], dcs: Dict[str, int], reward: Dict[str, Any]) -> str:
    title = mission.get("title", "Recovery")
    faction = mission.get("faction", "Adventurers Guild")
    reward_text = f"{reward['ec']} EC" + (f" + {reward['kharma']} Kharma" if reward.get("kharma") else "")
    body = f"<h1>{_e(title)}</h1>"
    body += _card("Target", f"<p><strong>{_e(plan.get('target_name'))}</strong></p><p>{_e(plan.get('target_description'))}</p>", "#8a5a1f")
    body += _card("Trail Checklist", "".join(f"<p><input type='checkbox'> {_e(b.get('clue'))} - {_e(b.get('skill'))} DC {_e(b.get('dc'))}</p>" for b in plan.get("trail", [])), "#3a6898")
    body += _card("Retrieval", "<p><input type='checkbox'> Target verified</p><p><input type='checkbox'> Target recovered</p><p><input type='checkbox'> Returned to sponsor</p><textarea rows='5' style='width:100%;font-family:inherit;' placeholder='Handling, damage, custody, witnesses...'></textarea>", "#2a6a2a")
    body += _card("Debrief", f"<p><strong>Reward:</strong> {_e(reward_text)}</p><select><option>Returned intact</option><option>Returned usable/damaged</option><option>Truth only</option><option>Returned to wrong holder</option><option>Lost or destroyed</option></select>", "#7b1e1e")
    return _page(title, body, faction)


def _guides(
    target_type: str,
    context: Dict[str, Any],
    plan: Dict[str, Any],
    dcs: Dict[str, int],
    strength: Dict[str, Any],
    reward: Dict[str, Any],
) -> Dict[str, str]:
    spec = TARGET_TYPES[target_type]
    return {
        "dm": (
            "## Recovery DM Guide\n"
            f"### Target\n{plan.get('target_name')} - {spec['label']}\n\n"
            f"### Contract Truth\nRecovery is strict: full pay requires return to sponsor. Wrong-holder moral wins usually breach the deal.\n\n"
            f"### Complications\n" + "\n".join(f"- {x}" for x in plan.get("complications", [])) + "\n\n"
            f"### Retrieval Scene\n{json.dumps(plan.get('retrieval_scene', {}), ensure_ascii=False, indent=2)}\n\n"
            f"### Rival Pressure\n{plan.get('rival_pressure')}\n\n"
            f"### Dialogue\n" + "\n".join(f"- {x}" for x in plan.get("dialogue_bank", [])) + "\n\n"
            f"### News Seed\n{plan.get('news_seed')}"
        ),
        "players": (
            "## Recovery Players Guide\n"
            f"### Public Job\n{plan.get('briefing')}\n\n"
            f"### What You Know\n- Target: {plan.get('target_name')}\n- Type: {spec['label']}\n- Last area: {context.get('name')} in {context.get('district')}\n\n"
            "### Contract\nPayment is for getting the target back to the hiring party."
        ),
        "chart": (
            "## Recovery Chart Pack\n"
            f"### Party Scaling\n{_party_note(strength)}\n\n"
            "### DCs\n" + "\n".join(f"- {k}: {v}" for k, v in dcs.items()) + "\n\n"
            "### Trail Beats\n" + "\n".join(f"- {b.get('clue')}: {b.get('skill')} DC {b.get('dc')}" for b in plan.get("trail", [])) + "\n\n"
            "### Outcomes\n" + "\n".join(f"- {k}: {v}" for k, v in (plan.get("outcome_table") or {}).items()) + "\n\n"
            f"### Reward\n- {reward['ec']} EC\n- {reward.get('kharma', 0)} Kharma"
        ),
    }


async def build_recovery_module(mission: dict, out_dir: Optional[Path] = None) -> Path:
    title = mission.get("title", "Recovery")
    faction = mission.get("faction", "Adventurers Guild")
    tier = mission.get("tier", "standard")
    if out_dir is None:
        out_dir = OUTPUT_BASE / f"{_safe_filename(title)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    strength = _party_strength()
    dcs = _dc_profile(tier, strength)
    target_type = _pick_target_type(mission)
    context = _pick_context(target_type)
    rival_party = _pick_rival_party()
    reward = _reward_profile(target_type, mission)

    logger.info(
        f"[RECOVERY] Building {title!r} | type={target_type} | faction={faction} | "
        f"party={strength['party_size']} avg={strength['avg_level']}"
    )

    plan = await _generate_plan(mission, target_type, context, dcs, strength, rival_party, reward)

    from src.mission_builder.mimir_module import create_module as _mc, render_mimir_section as _ms, push_documents as _mpd
    _mimir_id = await _mc(mission, mission_type="recovery")
    _html = render_module(mission, target_type, context, plan, dcs, strength, reward) + _ms([], [], _mimir_id or "")
    (out_dir / "module.html").write_text(_html, encoding="utf-8")
    (out_dir / "session.html").write_text(render_session(mission, plan, dcs, reward), encoding="utf-8")

    from src.mission_builder.boxset_utils import component_links, write_component
    guide = _guides(target_type, context, plan, dcs, strength, reward)
    write_component(out_dir, "dm_guide", "DM Guide", title, faction, guide["dm"])
    write_component(out_dir, "players_guide", "Players Guide", title, faction, guide["players"])
    write_component(out_dir, "chart_pack", "Chart Pack", title, faction, guide["chart"])
    if _mimir_id:
        await _mpd(_mimir_id, [
            {"title": f"{title} — Player Brief",  "type": "description", "content": guide["players"]},
            {"title": f"{title} — DM Notes",       "type": "dm_notes",    "content": guide["dm"]},
            {"title": f"{title} — Trail & Outcomes","type": "custom",      "content": guide["chart"]},
        ])

    from src.mission_builder.html_renderer import render_index
    cr = mission_cr(mission)
    index_html = render_index(title, faction, tier, cr, mission.get("player_name", "") or "Open", [], component_links(False), None, 0)
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    try:
        from src.db_api import raw_execute
        raw_execute("UPDATE missions SET module_slug=%s WHERE title=%s", (out_dir.name, title))
    except Exception as e:
        logger.warning(f"[RECOVERY] Could not write module_slug: {e}")

    with zipfile.ZipFile(out_dir.parent / f"{out_dir.name}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(out_dir.parent))

    logger.info(f"[RECOVERY] Complete: {title!r} -> {out_dir.name}")
    return index_path
