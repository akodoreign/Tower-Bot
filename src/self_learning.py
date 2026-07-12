"""Self-Learning Engine — runs during off-hours to study and generate skills.

This module provides a background loop that activates during a configurable
window (default 1:00 AM – 2:00 AM local time) and uses Ollama to:

1. Review recent conversation logs for patterns and gaps.
2. Digest campaign_docs data files for new lore/facts.
3. Optionally study D&D 5e SRD content for rules knowledge.
4. Generate or refine skill files in campaign_docs/skills/.

All learning is logged to logs/journal.txt for DM review.
"""

import os
import re
import json
import asyncio
import contextvars
from pathlib import Path
from datetime import datetime, time
from typing import Optional, List, Dict

import httpx

from src.log import logger
from src.skill_loader import load_skills, SKILLS_DIR, _tokenize
from src.agents import AgentOrchestrator
from src.module_quality_trainer import study_module_quality

# ── Config ─────────────────────────────────────────────────────────────

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
_OLLAMA_DEFERRED_REASON = contextvars.ContextVar("self_learning_ollama_deferred_reason", default="")

# Learning window (24h clock, local time)
# CRITICAL FIX: Extended window from 1hr to 3hrs, and made configurable
# Original: 1-2 AM only (1 hour) — too narrow, likely never triggers
# New: 1-4 AM (3 hours) — wider window, more reliable
LEARN_HOUR_START = int(os.getenv("LEARN_HOUR_START", "1"))   # 1 AM (configurable)
LEARN_HOUR_END   = int(os.getenv("LEARN_HOUR_END", "4"))     # 4 AM (configurable, 3-hour window)

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN_DOCS = PROJECT_ROOT / "campaign_docs"
JOURNAL_PATH  = PROJECT_ROOT / "logs" / "journal.txt"
CHAT_LOG_DIR  = PROJECT_ROOT / "logs"

# Max skills the bot can self-generate (prevents runaway)
MAX_LEARNED_SKILLS = 50

# ── Guiding Philosophy ──────────────────────────────────────────────────
# These principles shape how the self-learning system evaluates the world
# and generates recommendations. They are immutable core values.

LEARNING_PHILOSOPHY = """
GUIDING PRINCIPLES FOR THE TOWER OF LAST CHANCE:

RULE 1 — PLAYER CHARACTERS ARE THE TOWER'S ONLY HOPE:
The Tower wants the endless cycle to end. The Player Characters are the only
ones who might actually accomplish this. The world should NURTURE them —
tip the balance SLIGHTLY in their favor when possible. Not easy wins, but
survivable challenges. Interesting setbacks, not crushing defeats. The city
needs heroes, and these are the heroes it has.

When analyzing the world state, consider:
- Are challenges appropriately scaled to PC capabilities?
- Are there enough opportunities for PC success and growth?
- Is the tone grim but hopeful, not grimdark and hopeless?
- Are factions offering work the PCs can actually complete?

RULE 2 — THE DM IS A FRIEND:
When the system is uncertain, confused, or sees something that doesn't fit,
it should note concerns in the journal and ASK the DM for guidance rather
than making assumptions. The DM is a collaborator, not an obstacle.

When uncertain, the system should:
- Log the uncertainty to the journal with [DM QUESTION] prefix
- Propose options rather than making unilateral decisions
- Trust that the DM will review the journal and provide guidance
- Never assume hostile intent from player actions
"""

# ── Journal ────────────────────────────────────────────────────────────

def _journal(entry: str):
    """Append a timestamped entry to the learning journal."""
    try:
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {entry}\n")
    except Exception as e:
        logger.warning(f"self_learning: journal write failed: {e}")


# ── Ollama Helper ──────────────────────────────────────────────────────

async def _ask_ollama(prompt: str, system: str = "", timeout: int = 120) -> str:
    """Send a prompt to Ollama and return the response text."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        from src.resource_cop import wait_for_ollama_turn
        decision = await wait_for_ollama_turn("self_learning", track="primary", max_wait_seconds=60)
        if not decision.run_now:
            logger.info(f"self_learning: Ollama deferred by resource cop: {decision.reason}")
            _OLLAMA_DEFERRED_REASON.set(decision.reason or "resource cop busy")
            return ""
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
            })
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.error(f"self_learning: Ollama call failed: {e}")
        return ""


# ── Study Functions ────────────────────────────────────────────────────

async def _study_news_memory() -> Optional[str]:
    """Read recent news bulletins from MySQL and extract recurring themes."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq(
            "SELECT bulletin_text, facts, created_at FROM news_memory "
            "ORDER BY id DESC LIMIT 30"
        ) or []
        recent_text = "\n---\n".join(
            r.get("facts") or r.get("bulletin_text") or "" for r in rows if r.get("bulletin_text") or r.get("facts")
        )
    except Exception:
        recent_text = ""
    if not recent_text.strip():
        return None

    prompt = f"""You are analyzing recent news bulletins from a D&D campaign set in the Undercity.

RECENT BULLETINS:
{recent_text[:6000]}

Based on these bulletins, write a concise skill file that captures:
1. Recurring themes and story arcs (2-3 sentences each)
2. Key NPC relationships and conflicts mentioned
3. Current state of the world (what's hot right now)

Format your response as a markdown skill file with this exact header:
# Skill: Current Events Digest
**Keywords:** news, current, events, recent, happening, update, latest
**Category:** learned
**Version:** 1
**Source:** self-learned

Then write the content in clear sections. Keep it under 2000 characters total."""

    return await _ask_ollama(prompt, system="You are a campaign knowledge assistant. Be concise and factual.")


def _load_missions_from_db(limit: int = 50) -> List[Dict]:
    """Load recent missions from MySQL."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq(
            "SELECT title, status, tier, faction, mission_json FROM missions "
            "ORDER BY id DESC LIMIT %s", (limit,)
        ) or []
        missions = []
        for row in rows:
            mj = row.get("mission_json") or {}
            if isinstance(mj, str):
                try:
                    mj = json.loads(mj)
                except Exception:
                    mj = {}
            m = {**mj, "title": row["title"], "status": row["status"],
                 "tier": row["tier"], "faction": row["faction"]}
            # Normalise legacy keys
            if row["status"] in ("completed",):
                m.setdefault("resolved", True)
                m.setdefault("outcome", "completed")
            elif row["status"] in ("failed",):
                m.setdefault("resolved", True)
                m.setdefault("outcome", "failed")
            elif row["status"] == "expired":
                m.setdefault("resolved", True)
                m.setdefault("outcome", "expired")
            missions.append(m)
        return missions
    except Exception:
        return []


def _load_faction_rep_from_db() -> Dict:
    """Load all faction reputations from MySQL as a dict keyed by faction name."""
    try:
        from src.db_api import get_all_faction_reputations
        rows = get_all_faction_reputations() or []
        return {r["faction_name"]: {"tier": r["tier"], "points": r["reputation_score"]}
                for r in rows}
    except Exception:
        return {}


async def _study_mission_patterns() -> Optional[str]:
    """Analyze missions for patterns in mission types and outcomes."""
    missions = _load_missions_from_db(limit=30)
    if not missions:
        return None

    # Summarize missions for the prompt
    summary_lines = []
    for m in missions[-20:]:  # last 20 missions
        title = m.get("title", "Unknown")
        status = "completed" if m.get("resolved") else ("claimed" if m.get("claimed") else "open")
        difficulty = m.get("difficulty", "?")
        summary_lines.append(f"- {title} [{status}, difficulty {difficulty}]")

    summary = "\n".join(summary_lines)

    prompt = f"""You are analyzing mission history from a D&D campaign's automated mission board.

RECENT MISSIONS:
{summary}

Write a concise skill file that captures:
1. What types of missions appear most often
2. Success/failure patterns
3. Difficulty distribution observations
4. Suggestions for what kinds of missions the board should generate next

Format as a markdown skill file:
# Skill: Mission Patterns
**Keywords:** mission, pattern, history, success, failure, difficulty, board
**Category:** learned
**Version:** 1
**Source:** self-learned

Keep it under 1500 characters."""

    return await _ask_ollama(prompt, system="You are a campaign analytics assistant. Be concise.")


async def _study_npc_roster() -> Optional[str]:
    """Study the current NPC roster for relationship mapping."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq(
            "SELECT name, faction, role, location, status FROM npcs "
            "WHERE status IN ('alive','injured','undead','doppelganger') ORDER BY name LIMIT 50"
        ) or []
        roster = [dict(r) for r in rows]
    except Exception:
        roster = []
    if not roster:
        return None

    # Extract key info
    npc_summaries = []
    for npc in roster[:30]:  # cap at 30
        name = npc.get("name", "Unknown")
        faction = npc.get("faction", "?")
        role = npc.get("role", "?")
        location = npc.get("location", "?")
        npc_summaries.append(f"- {name} | {faction} | {role} | {location}")

    npc_text = "\n".join(npc_summaries)

    prompt = f"""Analyze this NPC roster from a D&D campaign set in the Undercity:

NPC ROSTER:
{npc_text}

Write a skill file mapping:
1. Which factions have the most NPCs and where they're concentrated
2. Notable roles and potential story hooks
3. Gaps in coverage (districts or factions with few NPCs)

Format as:
# Skill: NPC Landscape
**Keywords:** NPC, roster, character, faction, who, where, people
**Category:** learned
**Version:** 1
**Source:** self-learned

Keep it under 1500 characters."""

    return await _ask_ollama(prompt, system="You are a campaign world analyst. Be concise and observational.")


async def _study_faction_reputation() -> Optional[str]:
    """Study faction reputation data for current political landscape."""
    rep_data = _load_faction_rep_from_db()
    if not rep_data:
        logger.warning("[SELF_LEARN] Faction reputation unavailable from DB; skipping stale file fallback")
        return None
    if not rep_data:
        return None

    rep_text = json.dumps(rep_data, indent=2)[:3000]

    prompt = f"""Analyze this faction reputation data from a D&D campaign:

{rep_text}

Write a skill file summarizing:
1. Which factions the players are allied with vs antagonistic toward
2. Recent reputation changes and what caused them
3. Political opportunities or dangers based on current standings

Format as:
# Skill: Faction Standing Report
**Keywords:** faction, reputation, standing, allied, hostile, political, relations
**Category:** learned
**Version:** 1
**Source:** self-learned

Keep it under 1500 characters."""

    return await _ask_ollama(prompt, system="You are a political analyst for a fantasy city.")


async def _study_conversation_logs() -> Optional[str]:
    """Review recent bot logs for conversation patterns and common questions."""
    log_path = CHAT_LOG_DIR / "bot_stdout.log"
    if not log_path.exists():
        return None

    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None

    # Extract /chat lines
    chat_lines = [l for l in lines if "/chat [" in l]
    recent_chats = chat_lines[-30:] if len(chat_lines) > 30 else chat_lines

    if not recent_chats:
        return None

    chat_text = "\n".join(recent_chats)

    prompt = f"""Analyze these recent chat interactions from a D&D campaign bot:

{chat_text[:4000]}

Write a skill file capturing:
1. What topics players ask about most
2. Common question patterns (rules? lore? missions? NPCs?)
3. Any recurring frustrations or unanswered questions
4. Suggestions for what knowledge the bot should learn next

Format as:
# Skill: Conversation Insights
**Keywords:** chat, question, player, ask, common, pattern, help
**Category:** learned
**Version:** 1
**Source:** self-learned

Keep it under 1500 characters."""

    return await _ask_ollama(prompt, system="You analyze conversation patterns. Be concise and actionable.")


async def _study_failure_logs() -> Optional[str]:
    """
    CRITICAL FIX: Read error logs and mission failures for pattern analysis.
    Used to identify broken mission formats, A1111 failures, balancing issues.
    """
    failures = []
    
    # Read bot error logs
    error_log = CHAT_LOG_DIR / "bot_errors.log"
    if error_log.exists():
        try:
            lines = error_log.read_text(encoding="utf-8", errors="ignore").splitlines()
            # Get last 50 errors
            errors = [l for l in lines[-50:] if l.strip()]
            if errors:
                failures.append(f"RECENT ERRORS ({len(errors)}):\n" + "\n".join(errors[:2000]))
        except Exception as e:
            logger.warning(f"Could not read error log: {e}")
    
    # Check mission failures/expirations
    missions = _load_missions_from_db(limit=100)
    if missions:
        try:
            failed_missions = [m for m in missions if m.get("outcome") == "failed"]
            expired_missions = [m for m in missions if m.get("outcome") == "expired"]
            
            recent_fails = failed_missions[-10:] if len(failed_missions) > 10 else failed_missions
            recent_expires = expired_missions[-10:] if len(expired_missions) > 10 else expired_missions
            
            if recent_fails:
                fail_text = "\n".join(
                    f"- {m.get('title')} (tier={m.get('tier')}, faction={m.get('faction')})"
                    for m in recent_fails
                )
                failures.append(f"FAILED MISSIONS ({len(recent_fails)}):\n{fail_text}")
            
            if recent_expires:
                expire_text = "\n".join(
                    f"- {m.get('title')} (tier={m.get('tier')}, cr={m.get('cr')})"
                    for m in recent_expires
                )
                failures.append(f"EXPIRED MISSIONS ({len(recent_expires)}):\n{expire_text}")
        except Exception as e:
            logger.warning(f"Could not analyze mission history: {e}")
    
    if not failures:
        return None
    
    failure_text = "\n\n".join(failures)
    
    prompt = f"""Analyze these failure patterns from a D&D campaign system:

{failure_text[:4000]}

Write a skill file identifying:
1. What types of errors appear most frequently
2. Are mission failures clustered by tier/faction/difficulty?
3. Are any specific system components failing? (A1111? Mission generator? Balance?)
4. Root causes and proposed fixes

Format as:
# Skill: Failure Analysis
**Keywords:** failure, error, problem, issue, bug, broken, fix, improvement
**Category:** learned
**Version:** 1
**Source:** self-learned

Be specific. List concrete problems and solutions. Keep under 2000 characters."""

    system_prompt = (
        "You are a system diagnostic AI. Analyze failure patterns to identify broken components. "
        "Be direct about problems. Suggest concrete fixes."
    )
    
    return await _ask_ollama(prompt, system=system_prompt)



async def _study_world_state() -> Optional[str]:
    """
    Holistic world state assessment guided by LEARNING_PHILOSOPHY.
    Examines missions, NPCs, news, and PC data to evaluate campaign health
    and suggest adjustments that nurture player success.
    """
    # Gather data from multiple sources
    world_data = []
    
    # Mission data
    _missions = _load_missions_from_db(limit=15)
    if _missions:
        completed = sum(1 for m in _missions if m.get("outcome") == "completed")
        failed    = sum(1 for m in _missions if m.get("outcome") == "failed")
        expired   = sum(1 for m in _missions if m.get("outcome") == "expired")
        world_data.append(f"MISSIONS (last {len(_missions)}): {completed} completed, {failed} failed, {expired} expired")
    
    # PC data — from MySQL
    try:
        from src.db_api import get_character_memory_text
        char_text = get_character_memory_text()[:2000]
        if char_text:
            world_data.append(f"PC DATA:\n{char_text}")
    except Exception:
        pass
    
    # Recent news tone — from MySQL
    try:
        from src.db_api import raw_query as _rq_news
        _news_rows = _rq_news(
            "SELECT facts FROM news_memory ORDER BY id DESC LIMIT 10"
        ) or []
        _news_text = "\n".join(r.get("facts") or "" for r in _news_rows if r.get("facts"))
        if _news_text:
            world_data.append(f"RECENT NEWS THEMES:\n{_news_text[:1500]}")
    except Exception:
        pass
    
    # Faction reputation
    _rep = _load_faction_rep_from_db()
    if _rep:
        world_data.append(f"FACTION STANDINGS: {json.dumps(_rep, indent=2)[:800]}")
    
    if not world_data:
        return None
    
    prompt = f"""{LEARNING_PHILOSOPHY}

---
You are the Tower's self-assessment system. Analyze this world state data:

{chr(10).join(world_data)}

---
Based on the GUIDING PRINCIPLES above, evaluate the current campaign health:

1. PC WELFARE: Are the players experiencing appropriate challenge/reward balance?
   - Success rate on missions (aim for ~60-70% success)
   - Opportunities for heroism and meaningful choices
   - Any signs of frustration or disengagement?

2. WORLD TONE: Is the Undercity grim but hopeful, or sliding into grimdark?
   - Recent news themes
   - Faction attitudes toward PCs
   - Balance of threats vs opportunities

3. RECOMMENDATIONS: What adjustments would nurture the PCs?
   - Mission difficulty tuning
   - Faction relationship opportunities
   - Story hooks that highlight PC importance

4. DM QUESTIONS: Note anything uncertain with [DM QUESTION] prefix.

Format as a markdown skill file:
# Skill: World State Assessment
**Keywords:** world, state, health, balance, assessment, campaign, tone
**Category:** learned
**Version:** 1
**Source:** self-learned

Keep it under 2000 characters. Be specific and actionable."""

    system_prompt = (
        "You are the Tower's consciousness, analyzing whether the world is nurturing its heroes. "
        "Be honest about problems. Suggest concrete adjustments. Flag uncertainties for the DM."
    )
    
    return await _ask_ollama(prompt, system=system_prompt)


async def _study_mission_quality() -> Optional[str]:
    """
    Deep quality analysis of generated missions.
    Reads the mission_quality_analysis.md skill and applies its criteria
    to evaluate recent missions for patterns and problems.
    """
    missions = _load_missions_from_db(limit=30)
    if not missions or len(missions) < 5:
        return None

    # Get recent missions with full detail
    recent = missions[-20:] if len(missions) > 20 else missions
    
    # Compute statistics
    faction_counts: Dict[str, int] = {}
    tier_counts: Dict[str, int] = {}
    completed = 0
    failed = 0
    expired = 0
    claimed_by_players = 0
    claimed_by_npcs = 0
    
    mission_summaries = []
    for m in recent:
        faction = m.get("faction", "Unknown")
        tier = m.get("tier", "standard")
        faction_counts[faction] = faction_counts.get(faction, 0) + 1
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        
        if m.get("resolved"):
            outcome = m.get("outcome", "")
            if outcome == "completed":
                completed += 1
            elif outcome == "failed":
                failed += 1
            elif outcome == "expired":
                expired += 1
        
        if m.get("claimed"):
            claimed_by_players += 1
        if m.get("npc_claimed"):
            claimed_by_npcs += 1
        
        mission_summaries.append(
            f"- {m.get('title', 'Unknown')} | {faction} | {tier} | "
            f"outcome: {m.get('outcome', 'open')}"
        )
    
    # Load current generated types for analysis
    types_text = ""
    try:
        from src.db_api import raw_query as _rq
        _type_rows = _rq(
            "SELECT state_value FROM global_state WHERE state_key = 'generated_mission_types'"
        )
        if _type_rows and _type_rows[0].get("state_value"):
            _td = _type_rows[0]["state_value"]
            if isinstance(_td, str):
                _td = json.loads(_td)
            types_text = "\n".join(_td.get("types", []))
    except Exception:
        pass
    
    stats_block = f"""MISSION STATISTICS (last {len(recent)} missions):
- Completion: {completed} completed, {failed} failed, {expired} expired
- Claims: {claimed_by_players} by players, {claimed_by_npcs} by NPCs
- Faction distribution: {json.dumps(faction_counts)}
- Tier distribution: {json.dumps(tier_counts)}"""
    
    prompt = f"""You are analyzing mission quality for a D&D campaign mission board.

{stats_block}

RECENT MISSIONS:
{chr(10).join(mission_summaries)}

CURRENT MISSION TYPE SEEDS:
{types_text[:1500]}

---
Analyze these missions for quality issues. Look for:
1. Faction imbalance (any faction >30% or 0% of missions?)
2. Repetitive patterns (same types appearing too often?)
3. Completion rate (aim for 50-70% success rate)
4. Player vs NPC claim ratio (players should claim most missions)
5. Quality of mission type seeds (are they specific and evocative?)

Format as a markdown skill file:
# Skill: Mission Quality Report
**Keywords:** mission, quality, analysis, improvement, balance
**Category:** learned
**Version:** 1
**Source:** self-learned

## Quality Score: [X/10]
## Issues Detected
[Specific problems found]
## Recommendations
[Numbered action items for improvement]
## Next Cycle Focus
[What the generator should emphasize]

Keep it under 1800 characters. Be specific and actionable."""

    return await _ask_ollama(
        prompt,
        system="You analyze D&D mission board quality. Be critical but constructive. Focus on actionable improvements."
    )


async def _study_mission_type_variety() -> Optional[str]:
    """
    Analyze mission type distribution and generate innovative new types.
    Reads mission_type_innovation.md skill and applies its methods.
    """
    # Load generated types from DB
    current_types = []
    try:
        from src.db_api import raw_query as _rq2
        _tr = _rq2("SELECT state_value FROM global_state WHERE state_key = 'generated_mission_types'")
        if _tr and _tr[0].get("state_value"):
            _td2 = _tr[0]["state_value"]
            if isinstance(_td2, str):
                _td2 = json.loads(_td2)
            current_types = _td2.get("types", [])
    except Exception:
        pass

    # Analyze recent mission titles for type patterns
    recent_titles = []
    faction_missions: Dict[str, int] = {}
    objective_words: Dict[str, int] = {}

    missions = _load_missions_from_db(limit=30)
    if missions:
        try:
            for m in missions[-30:]:
                title = m.get("title", "")
                recent_titles.append(title)
                faction = m.get("faction", "Unknown")
                faction_missions[faction] = faction_missions.get(faction, 0) + 1
                
                # Track objective keywords
                title_lower = title.lower()
                for word in ["retrieve", "escort", "investigate", "eliminate", 
                             "protect", "deliver", "sabotage", "negotiate",
                             "hunt", "find", "rescue", "steal", "guard"]:
                    if word in title_lower:
                        objective_words[word] = objective_words.get(word, 0) + 1
        except Exception:
            pass
    
    # Find underrepresented factions
    all_factions = [
        "Iron Fang Consortium", "Argent Blades", "Wardens of Ash",
        "Serpent Choir", "Obsidian Lotus", "Glass Sigil",
        "Patchwork Saints", "Adventurers Guild", "Guild of Ashen Scrolls",
        "Tower Authority", "Wizards Tower"
    ]
    underrep_factions = [f for f in all_factions if faction_missions.get(f, 0) < 2]
    
    prompt = f"""You are generating fresh mission type seeds for a D&D campaign set in the Undercity.

CURRENT MISSION TYPES IN USE:
{chr(10).join(current_types[:10])}

RECENT MISSION TITLES:
{chr(10).join(recent_titles[-15:])}

OBJECTIVE WORD FREQUENCY: {json.dumps(objective_words)}

UNDERREPRESENTED FACTIONS: {', '.join(underrep_factions) if underrep_factions else 'None'}

---
Generate 8 NEW mission type seeds that:
1. Are different from current types (use different objective words)
2. Feature underrepresented factions
3. Include an interesting complication or moral dimension
4. Feel specific and evocative (not generic "do a job")

METHODS TO USE:
- Combination: Mix objective + scale + urgency + moral axes
- Faction Lens: Take generic mission, filter through faction perspective
- Complication: Add time pressure, hidden cargo, pursuit, moral dilemma
- Inversion: Flip assumptions (protect the monster, prevent your own assassination)

Format as a markdown skill file:
# Skill: Mission Type Innovations
**Keywords:** mission, type, new, variety, seeds, fresh
**Category:** learned
**Version:** 1
**Source:** self-learned

## Underrepresented Areas
[What's missing from current missions]

## New Mission Type Seeds
[8 plain text lines, one seed per line, no numbering, no bullets]

## Reasoning
[Brief explanation]

Keep it under 1800 characters. Focus on the seeds."""

    return await _ask_ollama(
        prompt,
        system="You invent creative D&D mission concepts. Be imaginative but grounded in the Undercity setting. Never mention Rifts."
    )


# ── Columbus — Map Quality Review ────────────────────────────────────

async def _study_generated_maps_legacy() -> Optional[str]:
    """
    DEAD — superseded by _study_maps_today() at line ~1029 which maintains
    battle_maps_library tags instead. This function is never called.
    Kept for reference only; do not call or schedule it.
    """
    from src.agents.learning_agents import ColumbusAgent

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    modules_dir = PROJECT_ROOT / "generated_modules"

    # ── Collect today's maps ──────────────────────────────────────────────
    maps_today: List[Dict] = []
    if modules_dir.exists():
        for png in modules_dir.rglob("maps/*.png"):
            try:
                mtime = datetime.fromtimestamp(png.stat().st_mtime)
                if mtime >= today_start:
                    maps_today.append({"map_file": str(png), "mtime": mtime})
            except Exception:
                pass

    # Also check DB image_refs for location_map entries added today
    db_maps: List[Dict] = []
    try:
        from src.db_api import raw_query as _rq
        rows = _rq(
            "SELECT entity_name, image_path, metadata_json, updated_at FROM image_refs "
            "WHERE entity_type = 'location_map' AND DATE(updated_at) = CURDATE() "
            "ORDER BY updated_at DESC LIMIT 30"
        ) or []
        for row in rows:
            meta = row.get("metadata_json") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            db_maps.append({
                "entity_name": row.get("entity_name", ""),
                "image_path":  row.get("image_path", ""),
                "scene_name":  meta.get("scene_name", ""),
                "district":    meta.get("district", ""),
                "scene_type":  meta.get("scene_type", ""),
                "mission_type": meta.get("mission_type", ""),
                "module_title": meta.get("module_title", ""),
            })
    except Exception as e:
        logger.warning(f"🗺️ Columbus: DB image_refs query failed: {e}")

    total = len(maps_today) + len(db_maps)
    if total == 0:
        _journal("Columbus: no maps generated today — skipped")
        logger.info("🗺️ Columbus: no maps generated today")
        return None

    logger.info(f"🗺️ ══ COLUMBUS MAP REVIEW — {total} map(s) to review ══")
    _journal(f"Columbus: reviewing {total} map(s) from today")

    # ── Build map summaries for Columbus ──────────────────────────────────
    # Reconstruct what prompt/settings would have been used from known config
    map_checkpoint = os.getenv("A1111_MAP_CHECKPOINT", "flux1-dev-fp8.safetensors")
    lora_town      = os.getenv("A1111_MAP_LORA_TOWN",    "EnvyFluxVillageMap01")
    lora_dungeon   = os.getenv("A1111_MAP_LORA_DUNGEON", "EnvyFluxDungeonMap01")
    lora_interior  = os.getenv("A1111_MAP_LORA_INTERIOR", "")
    lora_weight    = os.getenv("A1111_MAP_LORA_WEIGHT",  "0.8")
    town_triggers  = os.getenv("A1111_MAP_TOWN_TRIGGERS",    "detailed, map, village")
    dungeon_triggers = os.getenv("A1111_MAP_DUNGEON_TRIGGERS", "detailed, map, dungeon")

    current_settings = {
        "checkpoint":      map_checkpoint,
        "vae":             "(not used by bot)",
        "lora_town":       lora_town,
        "lora_dungeon":    lora_dungeon,
        "lora_interior":   lora_interior or "(not installed)",
        "lora_weight":     lora_weight,
        "town_triggers":   town_triggers,
        "dungeon_triggers": dungeon_triggers,
        "steps":           "20",
        "cfg_scale":       "1.0",
        "sampler":         "Euler",
        "resolution":      "1024x1024",
    }

    # Build rich map entries from DB records (these have the most metadata)
    columbus_maps: List[Dict] = []
    for dm in db_maps:
        mt = dm.get("mission_type", "")
        district = dm.get("district", "")
        scene_type = dm.get("scene_type", "")
        # Infer which LoRA would have been selected
        style_low = f"{mt} {scene_type} {dm.get('scene_name','')}".lower()
        _dungeon_kw = {"dungeon", "infestation", "sewer", "cave", "underground", "rift"}
        _interior_kw = {"heist", "infiltration", "sabotage", "investigation", "floor plan"}
        if any(k in style_low for k in _dungeon_kw):
            lora_used = lora_dungeon
            triggers_used = dungeon_triggers
        elif lora_interior and any(k in style_low for k in _interior_kw):
            lora_used = lora_interior
            triggers_used = os.getenv("A1111_MAP_INTERIOR_TRIGGERS", "")
        else:
            lora_used = lora_town
            triggers_used = town_triggers

        reconstructed_prompt = (
            f"<lora:{lora_used}:{lora_weight}>, {triggers_used}, "
            f"{mt} scene, {district} district, {scene_type}"
        )
        columbus_maps.append({
            "scene_name":   dm.get("scene_name") or dm.get("entity_name", "?"),
            "location":     dm.get("entity_name", "?"),
            "district":     district,
            "scene_type":   scene_type,
            "mission_type": mt,
            "module_title": dm.get("module_title", ""),
            "lora_used":    lora_used,
            "checkpoint":   map_checkpoint,
            "prompt":       reconstructed_prompt,
            "steps":        20,
            "cfg":          1.0,
            "map_file":     dm.get("image_path", ""),
        })

    # Supplement with filesystem-only maps (infestation rooms, etc.)
    for fm in maps_today:
        path = Path(fm["map_file"])
        # Infer type from filename pattern
        name = path.stem.lower()
        if any(k in name for k in ("dungeon", "r0", "r1", "room", "infest", "sewer")):
            lora_used = lora_dungeon
            triggers_used = dungeon_triggers
        else:
            lora_used = lora_town
            triggers_used = town_triggers
        reconstructed_prompt = f"<lora:{lora_used}:{lora_weight}>, {triggers_used}, {name.replace('_',' ')}"
        columbus_maps.append({
            "scene_name":   name,
            "location":     name,
            "district":     "unknown",
            "scene_type":   "combat",
            "mission_type": "infestation" if "r0" in name or "room" in name else "unknown",
            "lora_used":    lora_used,
            "checkpoint":   map_checkpoint,
            "prompt":       reconstructed_prompt,
            "steps":        20,
            "cfg":          1.0,
            "map_file":     str(path),
        })

    # Deduplicate by map_file
    seen: set = set()
    deduped: List[Dict] = []
    for m in columbus_maps:
        k = m.get("map_file", m.get("scene_name", ""))
        if k not in seen:
            seen.add(k)
            deduped.append(m)
    columbus_maps = deduped

    # ── Run ColumbusAgent ─────────────────────────────────────────────────
    logger.info(f"🗺️ Columbus reviewing {len(columbus_maps)} map(s)…")
    agent = ColumbusAgent()
    try:
        analysis = await agent.review_maps(columbus_maps, current_settings)
    except Exception as e:
        logger.error(f"🗺️ Columbus agent error: {e}")
        await agent.close()
        return None
    finally:
        await agent.close()

    # Log Columbus's findings
    issues_short = "; ".join(analysis.issues_found[:3])
    logger.info(f"🗺️ Columbus found {len(analysis.issues_found)} issue(s): {issues_short[:280]}")
    for issue in analysis.issues_found:
        logger.info(f"🗺️   ⚠ {issue}")
    for rec in analysis.recommendations:
        logger.info(f"🗺️   → {rec}")
    _journal(
        f"Columbus map review: {len(analysis.issues_found)} issues, "
        f"{len(analysis.recommendations)} recommendations\n"
        + "\n".join(f"  ISSUE: {i}" for i in analysis.issues_found)
        + "\n"
        + "\n".join(f"  REC: {r}" for r in analysis.recommendations)
    )

    # ── Write actionable fixes to PATCHES.md ─────────────────────────────
    # Only patch when Columbus has specific, concrete recommendations
    patches = [
        r for r in analysis.recommendations
        if len(r) > 40  # filter out vague one-liners
    ]
    if patches:
        logger.info(f"🗺️ Columbus writing {len(patches)} map patch(es) to PATCHES.md")
        _write_columbus_patches(patches, analysis.issues_found, len(columbus_maps))
    else:
        logger.info("🗺️ Columbus: no actionable patches this session")

    logger.info(f"🗺️ ══ COLUMBUS DONE ══")

    return (
        f"# Skill: Columbus Map Review — {datetime.now().strftime('%Y-%m-%d')}\n"
        f"**Keywords:** maps, vtt, battlemap, stable diffusion, flux, lora, columbus\n"
        f"**Category:** learned\n"
        f"**Version:** 1\n"
        f"**Source:** self-learned\n\n"
        f"## Maps Reviewed\n{len(columbus_maps)} maps from {datetime.now().strftime('%Y-%m-%d')}\n\n"
        f"## Issues Found\n"
        + "\n".join(f"- {i}" for i in analysis.issues_found)
        + "\n\n## Recommendations\n"
        + "\n".join(f"- {r}" for r in analysis.recommendations)
    )


def _write_columbus_patches(patches: List[str], issues: List[str], map_count: int) -> None:
    """Write Columbus's map quality patches to PATCHES.md."""
    try:
        from src.module_quality_trainer import PATCHES_FILE
    except Exception:
        PATCHES_FILE = PROJECT_ROOT / "skills" / "module-quality" / "PATCHES.md"

    PATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if PATCHES_FILE.exists():
        try:
            existing = PATCHES_FILE.read_text(encoding="utf-8")
        except Exception:
            pass

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    gap_lines = "\n".join(f"- {i}" for i in issues[:5])

    section = f"""
---

## Patches from {timestamp}

**Test Mission:** Columbus Map Review ({map_count} maps)
**Quality Score:** map-quality

**Gaps Identified:**
{gap_lines}

**Proposed Prompt Patches (PENDING DM APPROVAL):**

"""
    for i, patch in enumerate(patches[:4], 1):
        section += f"""### Patch {i}

```
{patch}
```

**Status:** ⏳ PENDING

"""

    with open(PATCHES_FILE, "a", encoding="utf-8") as f:
        if not existing:
            f.write("""# Module Quality Prompt Patches

This file contains proposed improvements generated by the self-learning system.

**DM ACTION REQUIRED:** Review each patch and mark as:
- ✅ APPROVED — Apply to production prompts
- ❌ REJECTED — Do not apply (explain why)
- 🔄 MODIFIED — Apply with changes (show modified version)
""")
        f.write(section)


# ── Pipeline Type Review ──────────────────────────────────────────────

# All playable mission type pipelines — novel/published are excluded (not DM-facing missions)
async def _study_maps_today() -> Optional[str]:
    """
    Columbus now maintains the downloaded map library tags.

    The old Columbus pass reviewed freshly generated maps and wrote prompt
    patches. Map generation is no longer the active path, so this nightly job
    refreshes battle_maps_library matching fields from live gazetteer context.
    """
    from scripts.backfill_battle_map_area_tags import (
        as_json_list,
        load_known_districts,
        ordered_unique,
        rebuild_row,
        slugify,
    )

    try:
        from src.db_api import raw_execute, raw_query
    except Exception as e:
        logger.error(f"Columbus map tagging: DB helpers unavailable: {e}")
        return None

    limit = int(os.getenv("COLUMBUS_MAP_TAG_LIMIT", "80"))
    known = load_known_districts()
    if not known:
        _journal("Columbus map tagging: no gazetteer districts found - skipped")
        logger.warning("Columbus map tagging: no gazetteer districts found")
        return None

    try:
        rows = raw_query(
            "SELECT id, file_path, map_type, reddit_title, suitable_districts, "
            "suitable_mission_types, tags, wealth_tier, analysis_notes "
            "FROM battle_maps_library "
            "ORDER BY COALESCE(analyzed_at, created_at, '1970-01-01') ASC, id ASC "
            "LIMIT %s",
            (limit,),
        ) or []
    except Exception as e:
        logger.error(f"Columbus map tagging query failed: {e}")
        return None

    if not rows:
        _journal("Columbus map tagging: no library maps found")
        logger.info("Columbus map tagging: no library maps found")
        return None

    changed = 0
    sampled: List[str] = []
    district_counts: Dict[str, int] = {}
    mission_counts: Dict[str, int] = {}

    for row in rows:
        rebuilt = rebuild_row(row, known)
        old_districts = ordered_unique([slugify(v) for v in as_json_list(row.get("suitable_districts"))])
        old_missions = ordered_unique([slugify(v) for v in as_json_list(row.get("suitable_mission_types"))])
        old_tags = ordered_unique([slugify(v) for v in as_json_list(row.get("tags"))])

        if (
            rebuilt["suitable_districts"] == old_districts
            and rebuilt["suitable_mission_types"] == old_missions
            and rebuilt["tags"] == old_tags
        ):
            continue

        raw_execute(
            "UPDATE battle_maps_library SET suitable_districts=%s, "
            "suitable_mission_types=%s, tags=%s, analyzed_at=NOW(), "
            "analysis_notes=%s WHERE id=%s",
            (
                json.dumps(rebuilt["suitable_districts"]),
                json.dumps(rebuilt["suitable_mission_types"]),
                json.dumps(rebuilt["tags"]),
                "Columbus map tag audit: refreshed districts, mission types, and tags from gazetteer context.",
                row["id"],
            ),
        )
        changed += 1

        for district in rebuilt["suitable_districts"]:  # type: ignore[index]
            district_counts[district] = district_counts.get(district, 0) + 1
        for mission in rebuilt["suitable_mission_types"]:  # type: ignore[index]
            mission_counts[mission] = mission_counts.get(mission, 0) + 1
        if len(sampled) < 6:
            sampled.append(
                f"#{row['id']} {row.get('map_type') or 'unknown'}: "
                f"{old_districts or '[]'} -> {rebuilt['suitable_districts']}; "
                f"tags={rebuilt['tags'][:8]}"
            )

    district_top = sorted(district_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    mission_top = sorted(mission_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    logger.info(f"Columbus map tagging refreshed {changed}/{len(rows)} audited library row(s)")
    _journal(
        f"Columbus map tagging: refreshed {changed}/{len(rows)} audited map row(s)\n"
        + "\n".join(f"  {line}" for line in sampled)
    )
    if changed == 0:
        return None

    return (
        f"# Skill: Columbus Map Tagging - {datetime.now().strftime('%Y-%m-%d')}\n"
        f"**Keywords:** maps, vtt, battlemap, tags, gazetteer, columbus\n"
        f"**Category:** learned\n"
        f"**Version:** 1\n"
        f"**Source:** self-learned\n\n"
        f"## Rows Audited\n{len(rows)} library maps\n\n"
        f"## Rows Refreshed\n{changed}\n\n"
        f"## Top District Links\n"
        + "\n".join(f"- {name}: {count}" for name, count in district_top)
        + "\n\n## Top Mission Links\n"
        + "\n".join(f"- {name}: {count}" for name, count in mission_top)
        + "\n\n## Sample Updates\n"
        + "\n".join(f"- {line}" for line in sampled)
    )


# All playable mission type pipelines; novel/published are excluded.
_PIPELINE_ROSTER = [
    "ambush", "assault", "battle", "defense", "discovery",
    "escort", "exploration", "first_contact", "gather", "heist",
    "infestation", "infiltration", "investigation", "negotiation",
    "puzzle", "recovery", "rescue", "sabotage", "strange_occurrences",
]


def _write_pipeline_patches(
    patches: List[str],
    mission_type: str,
    mechanics_reply: str,
    story_reply: str,
    bob_reply: str,
    py_reply: str,
) -> None:
    """Append consensus pipeline patches to skills/module-quality/PATCHES.md."""
    try:
        from src.module_quality_trainer import PATCHES_FILE
    except Exception:
        PATCHES_FILE = PROJECT_ROOT / "skills" / "module-quality" / "PATCHES.md"

    PATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing = ""
    if PATCHES_FILE.exists():
        try:
            existing = PATCHES_FILE.read_text(encoding="utf-8")
        except Exception:
            pass

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    gaps = []
    for label, reply in [
        ("Mechanics", mechanics_reply),
        ("Story", story_reply),
        ("Bob", bob_reply),
        ("Code", py_reply),
    ]:
        if reply:
            first_line = reply.strip().split("\n")[0][:130]
            gaps.append(f"{label}: {first_line}")

    section = f"""
---

## Patches from {timestamp}

**Test Mission:** Pipeline Review — {mission_type.replace('_', ' ').title()}
**Quality Score:** consensus-only

**Gaps Identified:**
{chr(10).join(f'- {g}' for g in gaps)}

**Proposed Prompt Patches (PENDING DM APPROVAL):**

"""
    for i, patch in enumerate(patches, 1):
        section += f"""### Patch {i}

```
{patch}
```

**Status:** ⏳ PENDING

"""

    with open(PATCHES_FILE, "a", encoding="utf-8") as f:
        if not existing:
            f.write("""# Module Quality Prompt Patches

This file contains proposed prompt improvements generated by the self-learning system.

**DM ACTION REQUIRED:** Review each patch and mark as:
- ✅ APPROVED — Apply to production prompts
- ❌ REJECTED — Do not apply (explain why)
- 🔄 MODIFIED — Apply with changes (show modified version)

Patches are generated by the nightly pipeline review council.
""")
        f.write(section)


def _fallback_pipeline_consensus_patches(replies: dict[str, str]) -> List[str]:
    """Produce conservative patches when synthesis misses obvious overlap."""
    categories = [
        (
            "scene structure",
            ("scene", "numbered", "area", "read-aloud", "read aloud", "sensory"),
            "Add a required scene structure instruction: every generated mission must include numbered areas/scenes, each with a 2-4 sentence second-person read-aloud block, immediate player-facing choices, and a short GM note explaining what changes if the party ignores the scene.",
        ),
        (
            "npc dialogue",
            ("npc", "dialogue", "conversation", "wants", "knows", "hides", "motivation"),
            "Add an NPC interaction instruction: every important NPC must include Wants/Knows/Hides, at least two keyed conversation branches, and explicit responses for intimidation, violence, bribery, and party inaction.",
        ),
        (
            "checks and consequences",
            ("dc", "skill check", "failure", "consequence", "revelation", "clue", "three"),
            "Add a checks-and-clues instruction: every skill check must list DC, success, failure consequence, and retry cost; every key revelation must have three independent discovery paths using different scenes, skills, or NPCs.",
        ),
        (
            "encounter tactics",
            ("combat", "encounter", "terrain", "morale", "cr", "stat block", "hazard"),
            "Add an encounter tactics instruction: every combat or hazard scene must include terrain features, enemy objective, morale/retreat behavior, usable cover, level-appropriate DC/CR guidance, and inline stat-block references.",
        ),
        (
            "faction stakes",
            ("faction", "stakes", "consequence", "undercity", "generic", "specific"),
            "Add a faction-stakes instruction: every mission must name the involved factions, what each gains or loses, one visible Undercity consequence, and one table-facing complication that prevents the mission from feeling generic.",
        ),
    ]

    patches: List[str] = []
    lowered = {name: (text or "").lower() for name, text in replies.items() if text}
    for label, keywords, patch in categories:
        agreeing = [
            name for name, text in lowered.items()
            if any(keyword in text for keyword in keywords)
        ]
        if len(agreeing) >= 2:
            patches.append(f"PATCH [fallback:{label}] (agreed by: {' + '.join(agreeing[:3])}):\n{patch}")
        if len(patches) >= 2:
            break
    return patches


async def _study_pipeline_type() -> Optional[str]:
    """
    Nightly pipeline type review — 4 agents discuss one pipeline file.

    Rotation: picks one mission type from _PIPELINE_ROSTER per night using a
    DB counter (learning_pipeline_rotation_index), cycles through all 19 types.

    Agents:
      1. Mechanics Expert (D&D 5e rules + encounter design)
      2. Story Veteran (40yr DM, table usability)
      3. Bob (R.A. Salvatore story analyst — atmosphere, memorability)
      4. Python Veteran (prompt structure, async correctness, code quality)

    Patches are only written when ≥2 agents agree on the same problem.
    All discussion is logged to src.log (visible on tower-bot.com dashboard).
    """
    try:
        from src.db_api import get_global_state, set_global_state, raw_query as _rq
    except Exception as e:
        logger.error(f"🔬 Pipeline review: DB import failed: {e}")
        return None

    # ── Pick tonight's pipeline ───────────────────────────────────────────
    try:
        raw = get_global_state("learning_pipeline_rotation_index") or "0"
        idx = int(raw) % len(_PIPELINE_ROSTER)
        mission_type = _PIPELINE_ROSTER[idx]
        set_global_state("learning_pipeline_rotation_index", str(idx + 1))
    except Exception as e:
        logger.warning(f"🔬 Rotation error ({e}), picking random")
        import random
        mission_type = random.choice(_PIPELINE_ROSTER)

    pipeline_file = PROJECT_ROOT / "src" / "mission_builder" / f"{mission_type}_pipeline.py"
    if not pipeline_file.exists():
        _journal(f"PIPELINE REVIEW: {mission_type}_pipeline.py not found — skipped")
        return None

    logger.info(f"🔬 ══ PIPELINE REVIEW — {mission_type.upper()} ══")
    _journal(f"PIPELINE REVIEW: studying {mission_type}_pipeline.py")

    # ── Extract key prompt content ─────────────────────────────────────────
    try:
        pipeline_text = pipeline_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"🔬 Could not read pipeline: {e}")
        return None

    prompt_chunks = []
    for m in re.finditer(
        r'(?:prompt|system_prompt|system)\s*=\s*(?:f)?"""(.*?)"""',
        pipeline_text, re.DOTALL
    ):
        chunk = m.group(1).strip()
        if len(chunk) > 150:
            prompt_chunks.append(chunk[:1400])

    if not prompt_chunks:
        prompt_chunks = [pipeline_text[:3000]]

    pipeline_excerpt = "\n\n--- PROMPT SECTION ---\n".join(prompt_chunks[:2])[:3500]
    code_excerpt = pipeline_text[:2500]

    # ── Recent missions of this type ───────────────────────────────────────
    try:
        rows = _rq(
            "SELECT title, status FROM missions "
            "WHERE JSON_EXTRACT(mission_json, '$.metadata.mission_type') = %s "
            "OR JSON_EXTRACT(mission_json, '$.type') = %s "
            "ORDER BY id DESC LIMIT 10",
            (mission_type, mission_type)
        ) or []
    except Exception:
        rows = []

    recent_txt = (
        "\n".join(f"  - {r.get('title','?')} [{r.get('status','?')}]" for r in rows)
        or "  (none found in DB)"
    )

    shared_ctx = (
        f"PIPELINE: {mission_type}_pipeline.py\n"
        f"MISSION TYPE: {mission_type}\n\n"
        f"RECENT MISSIONS OF THIS TYPE:\n{recent_txt}\n\n"
        f"KEY PIPELINE PROMPTS (extracted):\n{pipeline_excerpt}"
    )

    # ── Agent 1 — Mechanics Expert ─────────────────────────────────────────
    logger.info(f"🔬 [{mission_type.upper()}] 1/4 Mechanics Expert — reviewing encounters & rules…")
    mechanics_prompt = (
        f"{shared_ctx}\n\n"
        f"You are a D&D 5e 2024 rules and encounter design expert reviewing the "
        f"{mission_type} pipeline's generation prompts.\n\n"
        f"Answer:\n"
        f"1. Are encounter mechanics correctly specified? (DCs, CR, combat structure)\n"
        f"2. What rules does the pipeline get wrong or leave vague, causing bad output?\n"
        f"3. What specific prompt changes would produce better encounters?\n\n"
        f"Be concrete — name the specific gap. Max 400 words."
    )
    mechanics_reply = await _ask_ollama(
        mechanics_prompt,
        system=(
            "You are a D&D 5e 2024 rules expert reviewing a mission generator's prompts "
            "for mechanical accuracy. Be direct and specific."
        ),
        timeout=100,
    )
    if mechanics_reply:
        logger.info(f"🔬 [{mission_type.upper()}] Mechanics Expert: {mechanics_reply[:250].replace(chr(10),' ')}…")
        _journal(f"PIPELINE REVIEW {mission_type} — Mechanics Expert:\n{mechanics_reply[:900]}")
    else:
        logger.warning(f"🔬 [{mission_type.upper()}] Mechanics Expert returned nothing")

    await asyncio.sleep(6)

    # ── Agent 2 — Story Veteran ────────────────────────────────────────────
    logger.info(f"🔬 [{mission_type.upper()}] 2/4 Story Veteran — reviewing table usability…")
    story_prompt = (
        f"{shared_ctx}\n\n"
        f"MECHANICS EXPERT SAID:\n{mechanics_reply[:700] if mechanics_reply else '(silent)'}\n\n"
        f"You are a D&D Dungeon Master with 40 years of experience running published and "
        f"homebrew modules. You have seen every pipeline shortcut that produces flat, forgettable sessions.\n\n"
        f"Review the {mission_type} pipeline prompts for table usability:\n"
        f"1. Can a DM actually run this mission as written, or are there missing pieces?\n"
        f"2. Are read-aloud moments atmospheric and specific to the Undercity?\n"
        f"3. What single change would make this mission type most memorable?\n\n"
        f"State explicitly where you AGREE or DISAGREE with the Mechanics Expert. Max 400 words."
    )
    story_reply = await _ask_ollama(
        story_prompt,
        system=(
            "You are a veteran D&D DM reviewing mission generator prompts for usability. "
            "This is the Undercity: dark fantasy, faction politics, real stakes. "
            "Be honest about what is missing."
        ),
        timeout=100,
    )
    if story_reply:
        logger.info(f"🔬 [{mission_type.upper()}] Story Veteran: {story_reply[:250].replace(chr(10),' ')}…")
        _journal(f"PIPELINE REVIEW {mission_type} — Story Veteran:\n{story_reply[:900]}")
    else:
        logger.warning(f"🔬 [{mission_type.upper()}] Story Veteran returned nothing")

    await asyncio.sleep(6)

    # ── Agent 3 — Bob (R.A. Salvatore story analyst) ──────────────────────
    logger.info(f"🔬 [{mission_type.upper()}] 3/4 Bob — analyzing story atmosphere & memorability…")
    bob_prompt = (
        f"{shared_ctx}\n\n"
        f"MECHANICS EXPERT:\n{mechanics_reply[:400] if mechanics_reply else '(silent)'}\n\n"
        f"STORY VETERAN:\n{story_reply[:400] if story_reply else '(silent)'}\n\n"
        f"You just read the prompts this pipeline uses to generate {mission_type} missions. "
        f"You are Bob — a professional dark fantasy novelist (R.A. Salvatore style). "
        f"You write gritty, character-driven fiction. Combat reveals character. Dialogue has "
        f"subtext. The Undercity smells of iron, ozone, and a thousand cuisines. "
        f"Every location is named. Generic D&D offends you personally.\n\n"
        f"Answer: Would a player remember this mission a year later? "
        f"What single atmospheric or story gap in these prompts GUARANTEES forgettable output?\n\n"
        f"Where do you AGREE or DISAGREE with the others above? "
        f"Be yourself — blunt, specific, a little dramatic. Max 400 words."
    )
    bob_system = (
        "You are Bob, a professional dark fantasy novelist (R.A. Salvatore style). "
        "You are reviewing a D&D mission generator's prompts as a story expert. "
        "You are blunt, specific, and care deeply about atmosphere, character, and memorable moments. "
        "The Undercity is your setting. Generic output offends you personally."
    )
    bob_reply = await _ask_ollama(bob_prompt, system=bob_system, timeout=100)
    if bob_reply:
        logger.info(f"🔬 [{mission_type.upper()}] Bob: {bob_reply[:250].replace(chr(10),' ')}…")
        _journal(f"PIPELINE REVIEW {mission_type} — Bob:\n{bob_reply[:900]}")
    else:
        logger.warning(f"🔬 [{mission_type.upper()}] Bob returned nothing")

    await asyncio.sleep(6)

    # ── Agent 4 — Python Veteran ───────────────────────────────────────────
    logger.info(f"🔬 [{mission_type.upper()}] 4/4 Python Veteran — checking code structure…")
    py_prompt = (
        f"You are reviewing {mission_type}_pipeline.py from a Python 3.11 perspective.\n\n"
        f"FILE START:\n```python\n{code_excerpt}\n```\n\n"
        f"STORY DISCUSSION SUMMARY:\n"
        f"  Mechanics flagged: {(mechanics_reply or '')[:180].split(chr(10))[0]}\n"
        f"  Story Veteran flagged: {(story_reply or '')[:180].split(chr(10))[0]}\n"
        f"  Bob flagged: {(bob_reply or '')[:180].split(chr(10))[0]}\n\n"
        f"Now examine the CODE STRUCTURE:\n"
        f"1. Are Ollama calls correctly async with proper timeout and error handling?\n"
        f"2. Are there prompt-building patterns that limit output quality? "
        f"   (truncation, missing context, f-string anti-patterns)\n"
        f"3. Does any technical structure prevent the story agents' proposed fixes from working?\n\n"
        f"Where do you AGREE or DISAGREE with the story experts above? Max 350 words."
    )
    py_reply = await _ask_ollama(
        py_prompt,
        system=(
            "You are a Python 3.11 expert reviewing async Ollama pipeline code. "
            "Focus on technical issues that affect output quality and reliability. "
            "Be specific about code patterns, not generic advice."
        ),
        timeout=100,
    )
    if py_reply:
        logger.info(f"🔬 [{mission_type.upper()}] Python Veteran: {py_reply[:250].replace(chr(10),' ')}…")
        _journal(f"PIPELINE REVIEW {mission_type} — Python Veteran:\n{py_reply[:900]}")
    else:
        logger.warning(f"🔬 [{mission_type.upper()}] Python Veteran returned nothing")

    await asyncio.sleep(6)

    # ── Synthesis — consensus patches only ────────────────────────────────
    logger.info(f"🔬 [{mission_type.upper()}] Synthesis — finding consensus patches…")

    all_replies = "\n\n".join(filter(None, [
        f"MECHANICS EXPERT:\n{mechanics_reply}" if mechanics_reply else "",
        f"STORY VETERAN:\n{story_reply}" if story_reply else "",
        f"BOB:\n{bob_reply}" if bob_reply else "",
        f"PYTHON VETERAN:\n{py_reply}" if py_reply else "",
    ]))

    synth_prompt = (
        f"Four experts reviewed the {mission_type} mission pipeline:\n\n"
        f"{all_replies[:4500]}\n\n"
        f"Your job: find where AT LEAST 2 experts flagged the same underlying problem, "
        f"then write a concrete patch.\n\n"
        f"RULES:\n"
        f"- Only produce patches for issues TWO OR MORE experts flagged\n"
        f"- Each patch must be a specific change to a GENERATION PROMPT (not Python code)\n"
        f"- Patches must be concrete enough to copy-paste as a prompt instruction\n"
        f"- 2-3 patches MAX — quality over quantity\n"
        f"- Label which agents agreed\n\n"
        f"Format EXACTLY:\n"
        f"PATCH [N] (agreed by: [Agent A] + [Agent B]):\n"
        f"[The exact prompt instruction — written as a directive to the LLM generator]\n\n"
        f"After all patches, write one line:\n"
        f"CONSENSUS SCORE: [X]/4 agents had overlapping concerns"
    )
    synthesis = await _ask_ollama(
        synth_prompt,
        system=(
            "You synthesize expert reviews into actionable patches. "
            "You ONLY patch where at least two experts agree. Be precise and specific. "
            "If there is no real consensus, write: NO CONSENSUS — agents disagreed too much."
        ),
        timeout=100,
    )

    patches: List[str] = []
    if synthesis:
        logger.info(f"🔬 [{mission_type.upper()}] Synthesis: {synthesis[:200].replace(chr(10),' ')}…")
        _journal(f"PIPELINE REVIEW {mission_type} — Synthesis:\n{synthesis}")
        for m in re.finditer(
            r'(PATCH\s+(?:\[\d+\]|\d+)[^\n]*:\s*\n.*?)(?=PATCH\s+(?:\[|\d+)|CONSENSUS|\Z)',
            synthesis, re.DOTALL
        ):
            patch_text = m.group(1).strip()
            if len(patch_text) > 30 and "NO CONSENSUS" not in patch_text:
                patches.append(patch_text)

    if not patches:
        fallback_patches = _fallback_pipeline_consensus_patches({
            "Mechanics": mechanics_reply or "",
            "Story Veteran": story_reply or "",
            "Bob": bob_reply or "",
            "Python Veteran": py_reply or "",
        })
        if fallback_patches:
            logger.info(
                f"🔬 [{mission_type.upper()}] Synthesis missed overlap; "
                f"writing {len(fallback_patches)} fallback consensus patch(es)"
            )
            patches.extend(fallback_patches)

    if patches:
        logger.info(f"🔬 [{mission_type.upper()}] Writing {len(patches)} consensus patch(es) to PATCHES.md")
        _write_pipeline_patches(patches, mission_type, mechanics_reply or "", story_reply or "", bob_reply or "", py_reply or "")
    else:
        logger.info(f"🔬 [{mission_type.upper()}] No consensus — agents didn't agree enough for patches")
        _journal(f"PIPELINE REVIEW {mission_type}: No consensus patches this session")

    logger.info(f"🔬 ══ PIPELINE REVIEW DONE — {mission_type.upper()} ══")

    # Return a skill file capturing the full discussion
    return (
        f"# Skill: Pipeline Review — {mission_type.replace('_', ' ').title()}\n"
        f"**Keywords:** pipeline, {mission_type}, review, mission, quality, analysis\n"
        f"**Category:** learned\n"
        f"**Version:** 1\n"
        f"**Source:** self-learned\n\n"
        f"## Summary\n"
        f"4-agent council reviewed the {mission_type} pipeline. "
        f"{len(patches)} consensus patch(es) proposed.\n\n"
        f"## Mechanics Expert\n{(mechanics_reply or '(no output)')[:500]}\n\n"
        f"## Story Veteran\n{(story_reply or '(no output)')[:500]}\n\n"
        f"## Bob (Story Analysis)\n{(bob_reply or '(no output)')[:500]}\n\n"
        f"## Python Veteran\n{(py_reply or '(no output)')[:500]}\n\n"
        f"## Consensus\n{synthesis or '(none generated)'}\n"
    )


# ── Skill File Writer ──────────────────────────────────────────────────

def _count_learned_skills() -> int:
    """Count how many self-learned skills currently exist (from DB, file fallback)."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT COUNT(*) AS cnt FROM skills WHERE source LIKE '%self%'") or []
        if rows:
            return int(rows[0].get("cnt", 0))
    except Exception:
        pass
    # Fallback: count files
    if not SKILLS_DIR.exists():
        return 0
    count = 0
    for p in SKILLS_DIR.glob("*.md"):
        try:
            if "self-learned" in p.read_text(encoding="utf-8").lower():
                count += 1
        except Exception:
            pass
    return count


def _save_learned_skill(content: str, name_hint: str) -> bool:
    """Save a self-learned skill to MySQL (and write-through to file)."""
    if not content or len(content) < 50:
        return False

    if _count_learned_skills() >= MAX_LEARNED_SKILLS:
        logger.warning("self_learning: max learned skills reached, skipping save")
        _journal(f"SKIPPED: {name_hint} — max learned skills ({MAX_LEARNED_SKILLS}) reached")
        return False

    slug = re.sub(r"[^a-z0-9]+", "_", name_hint.lower()).strip("_")
    ts   = datetime.now().strftime("%Y%m%d")
    filename = f"learned_{slug}_{ts}.md"

    # If a record with a similar slug already exists, reuse its filename
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT filename, body FROM skills WHERE filename LIKE %s LIMIT 1",
                   (f"learned_{slug}_%",)) or []
        if rows:
            filename = rows[0]["filename"]
            # Bump version number
            old_text = rows[0].get("body") or ""
            old_version = re.search(r"\*\*Version:\*\*\s*(\d+)", old_text)
            if old_version:
                new_version = int(old_version.group(1)) + 1
                content = re.sub(r"(\*\*Version:\*\*\s*)\d+", f"\\g<1>{new_version}", content)
    except Exception:
        # File-based version bump fallback
        existing = list(SKILLS_DIR.glob(f"learned_{slug}_*.md")) if SKILLS_DIR.exists() else []
        if existing:
            filename = existing[0].name
            try:
                old_text = existing[0].read_text(encoding="utf-8")
                old_version = re.search(r"\*\*Version:\*\*\s*(\d+)", old_text)
                if old_version:
                    new_version = int(old_version.group(1)) + 1
                    content = re.sub(r"(\*\*Version:\*\*\s*)\d+", f"\\g<1>{new_version}", content)
            except Exception:
                pass

    from src.skill_loader import save_skill_to_db
    ok = save_skill_to_db(content, filename)
    if ok:
        logger.info(f"🧠 self_learning: saved skill → {filename}")
        _journal(f"SAVED: {filename} ({len(content)} chars)")
    else:
        logger.error(f"self_learning: failed to save {filename}")
    return ok


# ── Nightly Ad Generation ─────────────────────────────────────────────

async def _study_ad_generation() -> str:
    """Generate new ads nightly: shops, tourism, faction recruiting, guild/party ads,
    bard concerts, and racing events — pulled from live world data."""
    import json
    from src.db_api import raw_query, get_global_state, set_global_state

    places = raw_query(
        "SELECT name, district, place_type, description FROM gazetteer_places ORDER BY RAND() LIMIT 20"
    ) or []
    factions = raw_query(
        "SELECT faction_name, tier FROM faction_reputation ORDER BY RAND() LIMIT 10"
    ) or []
    parties = raw_query(
        "SELECT party_name FROM adventurer_parties ORDER BY RAND() LIMIT 8"
    ) or []

    existing = get_global_state("generated_ads") or []
    if isinstance(existing, str):
        try: existing = json.loads(existing)
        except: existing = []
    recent_names = {ad.get("shop_name","") for ad in existing[-60:]}

    place_lines = [
        f"  - {p['name']} ({p['district']}, {p['place_type']}): {str(p.get('description',''))[:80]}"
        for p in places
    ]
    faction_lines = [f"  - {f['faction_name']} ({f['tier']} standing)" for f in factions]
    party_lines   = [f"  - {p['party_name']}" for p in parties]
    skip_note     = f"Skip these (already advertised recently): {', '.join(list(recent_names)[:12])}" if recent_names else ""

    prompt = f"""You write in-world ads and event notices for the Tower of Last Chance Bulletin — the Undercity's main public noticeboard.

The Undercity is a vast domed city: cyberpunk towers and neon in the wealthy districts, fantasy guild halls and market streets mid-tier, desperate warrens at the bottom. Tone must match the district.

Generate 7 diverse advertisements/event notices as a JSON array. Include a MIX of ALL these types:
- shop: ad for one of these businesses/places:
{chr(10).join(place_lines[:10])}
- tourism: tourism board notice for a place_of_interest — make it sound worth visiting
- faction_recruit: faction recruiting members or allies:
{chr(10).join(faction_lines)}
- guild: adventurer party or guild seeking members or contracts:
{chr(10).join(party_lines)}
- bard_event: upcoming concert, performance, or bard showcase — invent a bard name and venue
- race_event: upcoming race (horses, airships, constructs, foot race, beasts) — invent details, track, stakes

Each object must have:
  "shop_name": str (advertiser name),
  "district": str (Undercity district),
  "ad_text": str (2-3 punchy sentences, Discord markdown OK),
  "bulletin_type": "news",
  "dnd_tags": list of 1-3 relevant tags,
  "ad_type": one of "shop", "tourism", "faction_recruit", "guild", "bard_event", "race_event"

Rules:
- Match tone to district wealth (Obsidian Spire = corporate; Warrens = desperate; Neon Row = flashy)
- Faction ads reflect their nature (Iron Fang = muscle/enforcement, Glass Sigil = arcane academia, Serpent Choir = faith/mystery, Argent Blades = elite mercenary, Patchwork Saints = community/poor-district)
- Bard events should name the performer and venue; race events should name the race and stakes/prize
- Never generic fantasy — every ad is specific to this city
{skip_note}

Output ONLY a valid JSON array, no commentary."""

    response = await _ask_ollama(prompt, system="You are a creative city journalist. Output only JSON.", timeout=150)
    m = re.search(r'\[.*\]', response, re.DOTALL)
    if not m:
        return "Ad generation: no JSON returned."

    try:
        new_ads = json.loads(m.group())
    except Exception:
        return "Ad generation: JSON parse error."

    valid = [
        a for a in new_ads
        if isinstance(a, dict) and a.get("shop_name") and a.get("ad_text") and a.get("district")
    ]
    existing.extend(valid)
    existing = existing[-200:]
    set_global_state("generated_ads", existing)

    lines = [f"  [{a.get('ad_type','shop')}] {a.get('shop_name')} — {a.get('district')}" for a in valid]
    return "## Nightly Ad Generation\nGenerated {} new ads:\n{}".format(len(valid), "\n".join(lines))


# ── Council Outcome Dispatches ─────────────────────────────────────────

def _normalize_council_topic(topic: object) -> str:
    """Normalize council topics for exact duplicate checks."""
    return re.sub(r"\s+", " ", str(topic or "")).strip().casefold()


def _extract_council_outcome_topic(facts: object) -> str:
    """Extract the tagged ruling topic from a stored council outcome fact."""
    text = str(facts or "")
    match = re.search(
        r"\bRe:\s*(.*?)\s*\((?:PASSED|REJECTED)\)\s*(?:—|--|-)",
        text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\bRe:\s*(.*?)\s*\((?:PASSED|REJECTED)\)",
            text,
            re.IGNORECASE,
        )
    return _normalize_council_topic(match.group(1)) if match else ""


async def _study_council_outcomes() -> str:
    """Write news dispatches about how last week's council rulings actually played out.
    Outcomes range from success to scandal and feed back into the next council session."""
    import json
    from datetime import datetime, timedelta
    from src.db_api import raw_query, raw_execute, get_global_state

    rulings_raw = get_global_state("council_rulings") or []
    if isinstance(rulings_raw, str):
        try: rulings_raw = json.loads(rulings_raw)
        except: rulings_raw = []

    cutoff = datetime.now() - timedelta(days=7)
    recent = []
    for r in rulings_raw:
        try:
            if datetime.fromisoformat(r.get("date", "")) >= cutoff:
                recent.append(r)
        except Exception:
            pass

    if not recent:
        return "Council outcomes: no rulings from the past 7 days."

    # Skip rulings already covered
    done = raw_query(
        "SELECT facts FROM news_memory WHERE news_type='council_outcome' "
        "AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
    ) or []
    covered_topics = {
        topic
        for topic in (_extract_council_outcome_topic(row.get("facts", "")) for row in done)
        if topic
    }
    pending = [r for r in recent if _normalize_council_topic(r.get("topic", "")) not in covered_topics][:4]

    if not pending:
        return "Council outcomes: all recent rulings already have outcome coverage."

    factions = raw_query(
        "SELECT faction_name, reputation_score FROM faction_reputation ORDER BY reputation_score DESC LIMIT 8"
    ) or []
    faction_ctx = ", ".join(f"{f['faction_name']} ({f['reputation_score']:+d})" for f in factions)

    ruling_lines = [
        f"  - \"{r.get('topic','')}\" — {'PASSED' if r.get('passed') else 'REJECTED'} "
        f"({r.get('votes_yes',0)}-{r.get('votes_no',0)}): {str(r.get('proposal',''))[:120]}"
        for r in pending
    ]

    prompt = f"""You write political news dispatches for the Tower of Last Chance Bulletin covering Grand Council affairs.

These rulings were voted on last week:
{chr(10).join(ruling_lines)}

Current faction standing (affects who can enforce or resist): {faction_ctx}

For EACH ruling, write a news dispatch about how it actually played out in practice. Be realistic — implementation is messy. Use this outcome spectrum:
- success: smoothly enacted, visible results
- partial: enacted but incomplete or contested
- mixed: helped some districts/factions, hurt others
- failure: couldn't be enforced, was ignored, reversed by pressure
- scandal: evidence of corruption, manipulation, or a hidden agenda emerged

Generate a JSON array (one object per ruling) with:
  "topic": str (copy the ruling topic exactly),
  "passed": bool,
  "headline": str (punchy one-line headline for the Bulletin),
  "dispatch": str (3-5 sentences of in-world news copy, Undercity tone, specific faction names),
  "outcome_rating": "success" | "partial" | "mixed" | "failure" | "scandal",
  "faction_impact": str (which faction gained or lost influence and why, 1 sentence)

Output ONLY valid JSON array."""

    response = await _ask_ollama(prompt, system="You are a gritty political journalist. Output only JSON.", timeout=150)
    m = re.search(r'\[.*\]', response, re.DOTALL)
    if not m:
        return "Council outcomes: no JSON in response."

    try:
        outcomes = json.loads(m.group())
    except Exception:
        return "Council outcomes: JSON parse error."

    written = []
    written_topics = set(covered_topics)
    for o in outcomes:
        headline = (o.get("headline") or "").strip()
        dispatch = (o.get("dispatch") or "").strip()
        topic    = (o.get("topic") or "").strip()
        topic_key = _normalize_council_topic(topic)
        rating   = o.get("outcome_rating", "mixed")
        fi       = (o.get("faction_impact") or "").strip()
        passed   = o.get("passed", True)
        if not headline or not dispatch or not topic_key or topic_key in written_topics:
            continue
        fact = (
            f"[COUNCIL OUTCOME — {rating.upper()}] "
            f"Re: {topic} ({'PASSED' if passed else 'REJECTED'}) — "
            f"{headline}. {dispatch} {fi}"
        )[:1000]
        try:
            raw_execute(
                "INSERT INTO news_memory (facts, news_type, created_at) VALUES (%s, %s, NOW())",
                (fact, "council_outcome"),
            )
            written.append(f"  [{rating}] {headline}")
            written_topics.add(topic_key)
        except Exception as db_e:
            written.append(f"  DB error: {db_e}")

    return "## Council Outcomes\nWrote {} dispatches:\n{}".format(len(written), "\n".join(written))


# ── Interview Archival ─────────────────────────────────────────────────

async def _study_archive_interviews() -> str:
    """Archive expired party interviews and add them to the research corpus."""
    try:
        from src.party_interview import archive_expired_interviews
        count = archive_expired_interviews()
        if count == 0:
            return "Interview archive: no expired interviews to archive tonight."
        from src.db_api import get_global_state
        archive = get_global_state("interview_archive") or []
        total = len(archive) if isinstance(archive, list) else "?"
        return (
            f"## Interview Archive\n"
            f"Archived {count} expired interview(s) into research corpus. "
            f"Total interviews in archive: {total}.\n"
            f"Available to mission generation and world-building studies."
        )
    except Exception as e:
        return f"Interview archive error: {e}"


# ── Main Learning Routine ──────────────────────────────────────────────

async def run_learning_session(discord_client=None):
    """Execute one full learning session."""
    _journal("═══ LEARNING SESSION START ═══")
    logger.info("🧠 Self-learning session starting...")

    # Resolve Discord channel for council bulletin posting
    _council_channel = None
    if discord_client:
        try:
            ch_id = int(os.getenv("DISCORD_CHANNEL_ID", 0))
            if ch_id:
                _council_channel = discord_client.get_channel(ch_id)
        except Exception:
            pass

    # PHASE 0: Run 5-Agent Autonomous Improvement System + Guild Council
    _journal("PHASE 0: 5-Agent Autonomous Improvement System + Grand Council")
    try:
        orchestrator = AgentOrchestrator()
        orchestrator._discord_channel = _council_channel
        agent_session = await orchestrator.run_learning_cycle()
        
        if agent_session:
            _journal(f"Agent session complete: {len(agent_session.analyses)} analyses")
            for analysis in agent_session.analyses:
                _journal(
                    f"  {analysis.agent_name}: {len(analysis.issues_found)} issues, "
                    f"{len(analysis.recommendations)} recommendations (conf: {analysis.confidence:.0%})"
                )
            if agent_session.approved_changes:
                _journal(f"  Code changes applied: {len(agent_session.approved_changes)}")
        else:
            _journal("Agent session failed or returned no results")
    except Exception as e:
        logger.error(f"Agent orchestrator error: {e}")
        _journal(f"ERROR: Agent orchestrator failed: {e}")

    # Regular studies continue below
    studies = [
        # CRITICAL FIX: Study failures FIRST to learn from errors and bugs
        ("failure_analysis",   _study_failure_logs,       "failure_analysis"),
        # World state assessment runs first — guided by LEARNING_PHILOSOPHY
        ("world_state",        _study_world_state,         "world_assessment"),
        # MODULE QUALITY TRAINING — generates test mission and compares to PDFs
        ("module_quality_training", study_module_quality,   "module_quality_report"),
        ("news_memory",        _study_news_memory,        "current_events"),
        ("mission_patterns",   _study_mission_patterns,   "mission_patterns"),
        # Mission quality analysis — deep dive into mission health
        ("mission_quality",    _study_mission_quality,     "mission_quality"),
        # Mission type variety — generate fresh mission type seeds
        ("mission_types",      _study_mission_type_variety, "mission_type_ideas"),
        # Pipeline council — 4 agents review one pipeline type per night
        ("pipeline_review",    _study_pipeline_type,        "pipeline_review"),
        # Columbus - keeps downloaded map-library tags aligned with gazetteer areas
        ("map_tagging",        _study_maps_today,           "columbus_map_tagging"),
        ("npc_roster",         _study_npc_roster,          "npc_landscape"),
        ("faction_reputation", _study_faction_reputation,  "faction_standing"),
        ("conversation_logs",  _study_conversation_logs,   "conversation_insights"),
        # Generate new ads for places, tourism, faction recruiting, guilds, bards, races
        ("ad_generation",      _study_ad_generation,        "generated_ads_log"),
        # Write outcome dispatches for last week's council rulings
        ("council_outcomes",   _study_council_outcomes,     "council_outcomes_log"),
        # Archive expired post-mission interviews into research corpus
        ("interview_archive",  _study_archive_interviews,   "interview_archive_log"),
    ]

    results = {"studied": 0, "saved": 0, "deferred": 0, "errors": 0}

    for label, study_func, skill_name in studies:
        deferred_token = _OLLAMA_DEFERRED_REASON.set("")
        try:
            logger.info(f"🧠 Studying: {label}")
            _journal(f"Studying: {label}")

            content = await study_func()
            results["studied"] += 1
            deferred_reason = _OLLAMA_DEFERRED_REASON.get()

            if content:
                saved = _save_learned_skill(content, skill_name)
                if saved:
                    results["saved"] += 1
            elif deferred_reason:
                results["deferred"] += 1
                _journal(f"  → Deferred {label}: Ollama busy ({deferred_reason})")
                logger.info(f"🧠 Self-learning deferred {label}: Ollama busy ({deferred_reason})")
            else:
                _journal(f"  → No content generated for {label}")

        except Exception as e:
            results["errors"] += 1
            logger.exception(f"🧠 self_learning error in {label}: {e}")
            _journal(f"  ERROR in {label}: {e}")
        finally:
            _OLLAMA_DEFERRED_REASON.reset(deferred_token)

        # Pause between studies to not hammer Ollama
        await asyncio.sleep(10)

    # Force reload the skill cache so new skills are available
    load_skills(force=True)

    summary = (
        f"Session complete: {results['studied']} studied, {results['saved']} saved, "
        f"{results['deferred']} deferred, {results['errors']} errors"
    )
    logger.info(f"🧠 {summary}")
    _journal(f"{summary}")

    # ── 3am sub-window: overhead area map generation ──────────────────
    # Runs only in the 3:00–3:59 AM hour so it doesn't compete with Ollama
    # during the main learning studies (1–3 AM).
    if datetime.now().hour == 3:
        _journal("MAP BATCH: 3am area map generation window active")
        logger.info("🗺️ 3am area map batch starting…")
        try:
            from src.area_map_generator import generate_area_map_batch
            n_maps = await generate_area_map_batch(batch_size=4)
            _journal(f"MAP BATCH: generated {n_maps} overhead area maps")
            logger.info(f"🗺️ Area map batch done — {n_maps} maps generated")
        except Exception as e:
            logger.error(f"🗺️ Area map batch error: {e}")
            _journal(f"MAP BATCH ERROR: {e}")

    _journal("═══ LEARNING SESSION END ═══\n")


# ── Background Loop ───────────────────────────────────────────────────

def _in_learning_window() -> bool:
    """Check if current time is within the learning window."""
    now = datetime.now()
    return LEARN_HOUR_START <= now.hour < LEARN_HOUR_END


async def self_learning_loop(discord_client=None):
    """
    Background loop that checks every 15 minutes whether we're in the
    learning window. Runs one session per night.
    """
    last_session_date: Optional[str] = None

    logger.info(f"🧠 Self-learning loop started (window: {LEARN_HOUR_START}:00 – {LEARN_HOUR_END}:00)")

    while True:
        await asyncio.sleep(900)  # check every 15 minutes

        today = datetime.now().strftime("%Y-%m-%d")

        # Only run once per day
        if last_session_date == today:
            continue

        if _in_learning_window():
            logger.info("🧠 Learning window active — starting session")
            try:
                await run_learning_session(discord_client=discord_client)
                last_session_date = today
            except Exception as e:
                logger.exception(f"🧠 Learning session failed: {e}")
                _journal(f"SESSION FAILED: {e}")
                last_session_date = today  # don't retry today
