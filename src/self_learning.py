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
from pathlib import Path
from datetime import datetime, time
from typing import Optional, List, Dict

import httpx

from src.log import logger
from src.skill_loader import load_skills, SKILLS_DIR, _tokenize

# ── Config ─────────────────────────────────────────────────────────────

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

# Learning window (24h clock, local time)
LEARN_HOUR_START = int(os.getenv("LEARN_HOUR_START", "1"))   # 1 AM
LEARN_HOUR_END   = int(os.getenv("LEARN_HOUR_END", "2"))     # 2 AM

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
    """Read news_memory.txt and extract recurring themes, NPCs, and patterns."""
    news_path = CAMPAIGN_DOCS / "news_memory.txt"
    if not news_path.exists():
        return None

    try:
        text = news_path.read_text(encoding="utf-8")
        # Take the last ~30 entries (most recent)
        entries = text.split("---ENTRY---")
        recent = entries[-30:] if len(entries) > 30 else entries
        recent_text = "\n---\n".join(recent)
    except Exception as e:
        logger.warning(f"self_learning: cannot read news_memory: {e}")
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


async def _study_mission_patterns() -> Optional[str]:
    """Analyze mission_memory.json for patterns in mission types and outcomes."""
    mission_path = CAMPAIGN_DOCS / "mission_memory.json"
    if not mission_path.exists():
        return None

    try:
        with open(mission_path, "r", encoding="utf-8") as f:
            missions = json.load(f)
    except Exception:
        return None

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
    roster_path = CAMPAIGN_DOCS / "npc_roster.json"
    if not roster_path.exists():
        return None

    try:
        with open(roster_path, "r", encoding="utf-8") as f:
            roster = json.load(f)
    except Exception:
        return None

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
    rep_path = CAMPAIGN_DOCS / "faction_reputation.json"
    if not rep_path.exists():
        return None

    try:
        with open(rep_path, "r", encoding="utf-8") as f:
            rep_data = json.load(f)
    except Exception:
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


async def _study_world_state() -> Optional[str]:
    """
    Holistic world state assessment guided by LEARNING_PHILOSOPHY.
    Examines missions, NPCs, news, and PC data to evaluate campaign health
    and suggest adjustments that nurture player success.
    """
    # Gather data from multiple sources
    world_data = []
    
    # Mission data
    mission_path = CAMPAIGN_DOCS / "mission_memory.json"
    if mission_path.exists():
        try:
            missions = json.loads(mission_path.read_text(encoding="utf-8"))
            recent = missions[-15:] if len(missions) > 15 else missions
            completed = sum(1 for m in recent if m.get("resolved") and m.get("outcome") == "completed")
            failed = sum(1 for m in recent if m.get("resolved") and m.get("outcome") == "failed")
            expired = sum(1 for m in recent if m.get("resolved") and m.get("outcome") == "expired")
            world_data.append(f"MISSIONS (last 15): {completed} completed, {failed} failed, {expired} expired")
        except Exception:
            pass
    
    # PC data
    char_path = CAMPAIGN_DOCS / "character_memory.txt"
    if char_path.exists():
        try:
            char_text = char_path.read_text(encoding="utf-8")[:2000]
            world_data.append(f"PC DATA:\n{char_text}")
        except Exception:
            pass
    
    # Recent news tone
    news_path = CAMPAIGN_DOCS / "news_memory.txt"
    if news_path.exists():
        try:
            news_text = news_path.read_text(encoding="utf-8")
            entries = news_text.split("---ENTRY---")[-10:]
            world_data.append(f"RECENT NEWS THEMES:\n" + "\n".join(entries)[:1500])
        except Exception:
            pass
    
    # Faction reputation
    rep_path = CAMPAIGN_DOCS / "faction_reputation.json"
    if rep_path.exists():
        try:
            rep_data = json.loads(rep_path.read_text(encoding="utf-8"))
            world_data.append(f"FACTION STANDINGS: {json.dumps(rep_data, indent=2)[:800]}")
        except Exception:
            pass
    
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
    mission_path = CAMPAIGN_DOCS / "mission_memory.json"
    types_path = CAMPAIGN_DOCS / "generated_mission_types.json"
    
    if not mission_path.exists():
        return None
    
    try:
        missions = json.loads(mission_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    
    if len(missions) < 5:
        return None  # Need enough data to analyze
    
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
    if types_path.exists():
        try:
            types_data = json.loads(types_path.read_text(encoding="utf-8"))
            types_text = "\n".join(types_data.get("types", []))
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
    mission_path = CAMPAIGN_DOCS / "mission_memory.json"
    types_path = CAMPAIGN_DOCS / "generated_mission_types.json"
    
    # Gather current state
    current_types = []
    if types_path.exists():
        try:
            data = json.loads(types_path.read_text(encoding="utf-8"))
            current_types = data.get("types", [])
        except Exception:
            pass
    
    # Analyze recent mission titles for type patterns
    recent_titles = []
    faction_missions: Dict[str, int] = {}
    objective_words: Dict[str, int] = {}
    
    if mission_path.exists():
        try:
            missions = json.loads(mission_path.read_text(encoding="utf-8"))
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


# ── Skill File Writer ──────────────────────────────────────────────────

def _count_learned_skills() -> int:
    """Count how many self-learned skills currently exist."""
    if not SKILLS_DIR.exists():
        return 0
    count = 0
    for p in SKILLS_DIR.glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8")
            if "self-learned" in text.lower():
                count += 1
        except Exception:
            pass
    return count


def _save_learned_skill(content: str, name_hint: str) -> bool:
    """Save a self-learned skill to disk."""
    if not content or len(content) < 50:
        return False

    # Check limit
    if _count_learned_skills() >= MAX_LEARNED_SKILLS:
        logger.warning("self_learning: max learned skills reached, skipping save")
        _journal(f"SKIPPED: {name_hint} — max learned skills ({MAX_LEARNED_SKILLS}) reached")
        return False

    # Generate filename
    slug = re.sub(r"[^a-z0-9]+", "_", name_hint.lower()).strip("_")
    ts = datetime.now().strftime("%Y%m%d")
    filename = f"learned_{slug}_{ts}.md"
    filepath = SKILLS_DIR / filename

    # If a file with similar name already exists, overwrite it (updated version)
    existing = list(SKILLS_DIR.glob(f"learned_{slug}_*.md"))
    if existing:
        filepath = existing[0]  # overwrite the existing one

    try:
        # Bump the version number if overwriting
        if filepath.exists():
            old_text = filepath.read_text(encoding="utf-8")
            old_version = re.search(r"\*\*Version:\*\*\s*(\d+)", old_text)
            if old_version:
                new_version = int(old_version.group(1)) + 1
                content = re.sub(
                    r"(\*\*Version:\*\*\s*)\d+",
                    f"\\g<1>{new_version}",
                    content,
                )

        filepath.write_text(content, encoding="utf-8")
        logger.info(f"🧠 self_learning: saved skill → {filepath.name}")
        _journal(f"SAVED: {filepath.name} ({len(content)} chars)")
        return True
    except Exception as e:
        logger.error(f"self_learning: failed to save {filepath.name}: {e}")
        return False


# ── Main Learning Routine ──────────────────────────────────────────────

async def run_learning_session():
    """Execute one full learning session."""
    _journal("═══ LEARNING SESSION START ═══")
    logger.info("🧠 Self-learning session starting...")

    studies = [
        # World state assessment runs first — guided by LEARNING_PHILOSOPHY
        ("world_state",        _study_world_state,         "world_assessment"),
        ("news_memory",        _study_news_memory,        "current_events"),
        ("mission_patterns",   _study_mission_patterns,   "mission_patterns"),
        # Mission quality analysis — deep dive into mission health
        ("mission_quality",    _study_mission_quality,     "mission_quality"),
        # Mission type variety — generate fresh mission type seeds
        ("mission_types",      _study_mission_type_variety, "mission_type_ideas"),
        ("npc_roster",         _study_npc_roster,          "npc_landscape"),
        ("faction_reputation", _study_faction_reputation,  "faction_standing"),
        ("conversation_logs",  _study_conversation_logs,   "conversation_insights"),
    ]

    results = {"studied": 0, "saved": 0, "errors": 0}

    for label, study_func, skill_name in studies:
        try:
            logger.info(f"🧠 Studying: {label}")
            _journal(f"Studying: {label}")

            content = await study_func()
            results["studied"] += 1

            if content:
                saved = _save_learned_skill(content, skill_name)
                if saved:
                    results["saved"] += 1
            else:
                _journal(f"  → No content generated for {label}")

        except Exception as e:
            results["errors"] += 1
            logger.exception(f"🧠 self_learning error in {label}: {e}")
            _journal(f"  ERROR in {label}: {e}")

        # Pause between studies to not hammer Ollama
        await asyncio.sleep(10)

    # Force reload the skill cache so new skills are available
    load_skills(force=True)

    summary = f"Session complete: {results['studied']} studied, {results['saved']} saved, {results['errors']} errors"
    logger.info(f"🧠 {summary}")
    _journal(f"{summary}")
    _journal("═══ LEARNING SESSION END ═══\n")


# ── Background Loop ───────────────────────────────────────────────────

def _in_learning_window() -> bool:
    """Check if current time is within the learning window."""
    now = datetime.now()
    return LEARN_HOUR_START <= now.hour < LEARN_HOUR_END


async def self_learning_loop():
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
                await run_learning_session()
                last_session_date = today
            except Exception as e:
                logger.exception(f"🧠 Learning session failed: {e}")
                _journal(f"SESSION FAILED: {e}")
                last_session_date = today  # don't retry today
