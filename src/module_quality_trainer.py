"""Module Quality Trainer — Self-learning system for improving mission module quality.

This module runs during the nightly self-learning window (1-4 AM) and:
1. Generates a test mission in sandbox mode (no Discord posting)
2. Compares the output against extracted professional D&D module PDFs
3. Identifies quality gaps using AICriticAgent
4. Generates prompt improvement patches
5. Logs all learning for DM review

The test mission is isolated — it does NOT:
- Post to Discord
- Update mission_memory.json
- Change faction reputation
- Affect any production systems
"""

import os
import json
import asyncio
import random
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple

import httpx

from src.log import logger
from src.ollama_busy import is_available, mark_busy, mark_available, get_busy_reason
from src.agents.learning_agents import (
    ProAuthorAgent,
    DNDExpertAgent,
    DNDVeteranAgent,
    AICriticAgent,
)

# ── Config ─────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN_DOCS = PROJECT_ROOT / "campaign_docs"
LOGS_DIR = PROJECT_ROOT / "logs"
LEARNING_DIR = LOGS_DIR / "learning"
TEST_MODULES_DIR = LEARNING_DIR / "test_modules"
QUALITY_JOURNAL = LEARNING_DIR / "quality_journal.jsonl"
# Training material lives in campaign_docs/skills/training_modules/ after PDF extraction
TRAINING_MODULES_DIR = CAMPAIGN_DOCS / "skills" / "training_modules"
MODULE_FORMAT_GUIDE = TRAINING_MODULES_DIR / "MODULE_FORMAT_GUIDE.md"
SKILLS_DIR = CAMPAIGN_DOCS / "skills"
PATCHES_FILE = LOGS_DIR / "learning" / "module_quality_patches.md"
GENERATED_MODULES_DIR = PROJECT_ROOT / "generated_modules"

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

# Test mission parameters
TEST_FACTIONS = [
    "Iron Fang Consortium", "Argent Blades", "Wardens of Ash",
    "Serpent Choir", "Obsidian Lotus", "Patchwork Saints",
]
TEST_TIERS = ["local", "standard", "major"]
TEST_TYPES = ["investigation", "combat", "social", "dungeon-delve"]


# ── Directory Setup ────────────────────────────────────────────────────

def _ensure_directories():
    """Create learning output directories if they don't exist."""
    LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    TEST_MODULES_DIR.mkdir(parents=True, exist_ok=True)


# ── Reference Material Loading ─────────────────────────────────────────

def _load_training_excerpts(max_chars: int = 8000) -> str:
    """
    Load the curated MODULE_FORMAT_GUIDE.md, then supplement with raw training text.
    This is the authoritative format reference used for quality comparison.
    """
    excerpts = []
    total_chars = 0

    # Primary: curated format guide (most authoritative — contains real examples)
    if MODULE_FORMAT_GUIDE.exists():
        try:
            guide_text = MODULE_FORMAT_GUIDE.read_text(encoding="utf-8")
            excerpts.append(f"### MODULE FORMAT GUIDE (authoritative reference)\n{guide_text[:max_chars // 2]}")
            total_chars += len(excerpts[-1])
        except Exception as e:
            logger.warning(f"Could not read MODULE_FORMAT_GUIDE: {e}")

    # Supplement with raw training files (Oni Mother and Respect Your Elderly are best)
    priority_files = [
        "Oni_Mother_.txt",
        "2722702-Respect_your_elderly.txt",
        "Can_We_Keep_Him.txt",
    ]
    if TRAINING_MODULES_DIR.exists():
        for fname in priority_files:
            if total_chars >= max_chars:
                break
            fpath = TRAINING_MODULES_DIR / fname
            if not fpath.exists():
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
                # Take the content-rich middle section
                lines = text.splitlines()
                start = max(0, len(lines) // 10)
                end   = min(len(lines), start + 80)
                chunk = "\n".join(lines[start:end])
                remaining = max_chars - total_chars
                chunk = chunk[:remaining]
                excerpts.append(f"### {fname}\n{chunk}")
                total_chars += len(chunk)
            except Exception as e:
                logger.warning(f"Could not read training file {fname}: {e}")

    return "\n\n---\n\n".join(excerpts)


def _load_quality_skill() -> str:
    """Load the module-quality skill content from MySQL, falling back to file."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT body FROM skills WHERE filename = 'module-quality-SKILL.md' LIMIT 1") or []
        if rows and rows[0].get("body"):
            return rows[0]["body"]
    except Exception as e:
        logger.warning(f"module_quality_trainer: DB load of quality skill failed: {e}")
    skill_path = SKILLS_DIR / "module-quality" / "SKILL.md"
    if skill_path.exists():
        try:
            return skill_path.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""


# ── Ollama Helper ──────────────────────────────────────────────────────

async def _ask_ollama(
    prompt: str,
    system: str = "",
    timeout: int = 300,
    retries: int = 2,
) -> str:
    """
    Send a prompt to Ollama and return the response text.
    
    Args:
        prompt: User prompt
        system: System prompt (optional)
        timeout: Timeout in seconds (default 5 minutes)
        retries: Number of retry attempts on failure
    
    Returns:
        Response text or empty string on failure
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    last_error = None
    
    for attempt in range(retries + 1):
        try:
            from src.resource_cop import wait_for_ollama_turn
            decision = await wait_for_ollama_turn("module_quality_trainer", track="primary", max_wait_seconds=60)
            if not decision.run_now:
                logger.info(f"module_quality_trainer: Ollama deferred by resource cop: {decision.reason}")
                return ""
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(OLLAMA_URL, json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                })
                data = resp.json()
                return data.get("message", {}).get("content", "").strip()
                
        except httpx.TimeoutException as e:
            last_error = f"Timeout after {timeout}s (attempt {attempt + 1}/{retries + 1})"
            logger.warning(f"module_quality_trainer: {last_error}")
            if attempt < retries:
                # Wait before retry, increasing each time
                wait_time = 30 * (attempt + 1)
                logger.info(f"module_quality_trainer: Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                continue
                
        except httpx.ConnectError as e:
            last_error = f"Connection error: {e}"
            logger.error(f"module_quality_trainer: {last_error}")
            break  # Don't retry connection errors
            
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            logger.error(f"module_quality_trainer: Ollama call failed: {last_error}")
            if attempt < retries:
                await asyncio.sleep(10)
                continue
    
    if last_error:
        logger.error(f"module_quality_trainer: All attempts failed. Last error: {last_error}")
    return ""


# ── Test Mission Generation (Sandbox Mode) ─────────────────────────────

async def _generate_test_mission() -> Dict[str, Any]:
    """
    Generate a random test mission without affecting production systems.
    
    Returns a mission dict with generated content for quality testing.
    """
    # Random parameters
    faction = random.choice(TEST_FACTIONS)
    tier = random.choice(TEST_TIERS)
    mission_type = random.choice(TEST_TYPES)
    cr = {"local": 4, "standard": 6, "major": 8}.get(tier, 6)
    
    # Generate a test title
    title_prompt = f"""Generate a single creative mission title for a D&D mission.
Faction: {faction}
Type: {mission_type}
Tier: {tier}

Output ONLY the title, nothing else. Make it specific and evocative."""

    title = await _ask_ollama(title_prompt)
    if not title:
        title = f"Test Mission: {faction} {mission_type.title()}"
    
    # Build mission metadata
    mission = {
        "metadata": {
            "title": title.strip('"').strip(),
            "faction": faction,
            "tier": tier,
            "mission_type": mission_type,
            "cr": cr,
            "is_learning_test": True,
            "generated_at": datetime.now().isoformat(),
        },
        "sections": {},
    }
    
    # Load skill context
    quality_skill = _load_quality_skill()
    skill_context = quality_skill[:4000] if quality_skill else ""
    
    # Generate each section
    sections = ["overview", "act_1", "act_2", "act_3", "rewards"]
    accumulated = ""
    
    for section in sections:
        section_prompt = _build_section_prompt(section, mission, accumulated, skill_context)
        
        system = f"""You are a master D&D 5e 2024 module writer.

═══ ANTI-PATTERNS (NEVER USE) ═══
❌ Purple prose ("ethereal glow", "otherworldly pallor")
❌ Echo chamber (saying the same thing multiple ways)
❌ Hedging ("seemed to", "appeared to", "might be")
❌ Adjective avalanche (more than one adjective per noun)
❌ Generic locations ("a warehouse" → name it specifically)

═══ REQUIRED PATTERNS ═══
✓ Specific names, numbers, times, locations
✓ Sensory grounding (sight, sound, smell, texture)
✓ Read-aloud text in present tense, second person
✓ NPCs have: Appearance, Voice, Knows, Wants
✓ Encounters have: Setup, Terrain, Morale, Loot

{skill_context[:2000]}"""

        content = await _ask_ollama(section_prompt, system=system, timeout=300)
        
        if content:
            # Strip AI preamble
            lines = content.splitlines()
            skip_prefixes = ("sure", "here's", "here is", "certainly", "of course")
            while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip_prefixes):
                lines.pop(0)
            content = "\n".join(lines).strip()
        
        mission["sections"][section] = content or f"[{section} generation failed]"
        accumulated += f"\n\n### {section.upper()}\n{content}"
    
    return mission


def _build_section_prompt(
    section: str,
    mission: Dict,
    previous: str,
    skill_context: str,
) -> str:
    """Build the prompt for generating a specific section."""
    meta = mission.get("metadata", {})
    title = meta.get("title", "Test Mission")
    faction = meta.get("faction", "Unknown")
    tier = meta.get("tier", "standard")
    cr = meta.get("cr", 6)
    mission_type = meta.get("mission_type", "standard")
    
    prompts = {
        "overview": f"""Write the OVERVIEW section for a D&D mission module.

MISSION: {title}
FACTION: {faction}
TIER: {tier} (CR {cr})
TYPE: {mission_type}

Include:
- Mission hook (why the party is hired)
- Primary objective
- Key locations (2-3, named specifically)
- Major NPCs (named with roles)
- Expected challenges
- Reward summary

Write 400-600 words. Be specific — no generic "a warehouse" or "some guards".""",

        "act_1": f"""Write ACT 1 (Setup & Hook) for the mission module.

MISSION: {title}
FACTION: {faction}
CR: {cr}

PREVIOUS CONTEXT:
{previous[:1500]}

Include:
- Opening scene with read-aloud text (present tense, second person)
- Quest-giver NPC with: name, appearance (2-3 details), voice, motivation
- Initial information and clues
- First minor challenge (social or exploration)

Write 500-800 words. Include at least one read-aloud box marked with >>>.""",

        "act_2": f"""Write ACT 2 (Rising Action) for the mission module.

MISSION: {title}
FACTION: {faction}
CR: {cr}

PREVIOUS CONTEXT:
{previous[:1500]}

Include:
- Travel or exploration scene with location descriptions
- Major encounter with: Setup, Terrain features, Morale/retreat conditions
- Environmental hazards or puzzles with DCs
- Discovery that raises stakes
- NPC interaction with useful information

Write 600-900 words. Include specific DCs and tactical details.""",

        "act_3": f"""Write ACT 3 (Climax) for the mission module.

MISSION: {title}
FACTION: {faction}
CR: {cr}

PREVIOUS CONTEXT:
{previous[:1500]}

Include:
- Final location with vivid read-aloud description
- Boss encounter or major challenge with full tactical breakdown
- Terrain features that affect combat
- Victory and failure conditions
- Immediate aftermath

Write 600-900 words. Be tactically specific.""",

        "rewards": f"""Write the REWARDS & CONCLUSION section.

MISSION: {title}
FACTION: {faction}
TIER: {tier}

PREVIOUS CONTEXT:
{previous[:1000]}

Include:
- XP awards (specific numbers)
- Gold/treasure rewards (specific amounts)
- Faction reputation changes
- Magic items or special rewards (if any)
- Consequences of success vs failure
- Hooks for future missions

Write 300-500 words.""",
    }
    
    return prompts.get(section, f"Write the {section} section.")


def _load_latest_real_module() -> Optional[tuple[str, str]]:
    """
    Find the most recently generated real module (from generated_modules/).
    Returns (title, full_module_html_text) or None.
    Prefers module.html (the play-ready scene document).
    """
    if not GENERATED_MODULES_DIR.exists():
        return None
    try:
        # Find most recent dir with a module.html
        candidates = sorted(
            [d for d in GENERATED_MODULES_DIR.iterdir()
             if d.is_dir() and (d / "module.html").exists()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return None
        latest = candidates[0]
        html_text = (latest / "module.html").read_text(encoding="utf-8", errors="ignore")
        # Strip style/script blocks first (their content is not HTML tags, so
        # the tag stripper below leaves raw CSS/JS in the text otherwise).
        import re as _re
        text = _re.sub(r"<style[^>]*>.*?</style>", " ", html_text, flags=_re.DOTALL | _re.IGNORECASE)
        text = _re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=_re.DOTALL | _re.IGNORECASE)
        text = _re.sub(r"<[^>]+>", " ", text)
        text = _re.sub(r"\s+", " ", text).strip()
        return latest.name, text
    except Exception as e:
        logger.warning(f"Could not load latest module: {e}")
        return None


def _structural_check(module_text: str) -> Dict[str, Any]:
    """
    Fast structural checks against WotC format markers.
    Returns a dict of counts and a list of specific failures.
    """
    import re
    checks = {}
    failures = []

    def count(pattern, label, flags=re.IGNORECASE):
        n = len(re.findall(pattern, module_text, flags))
        checks[label] = n
        return n

    # READ ALOUD blocks — check all known label variants including HTML class
    ra = count(
        r"Read Aloud to Players|Read this:|READ ALOUD|class=['\"]read-aloud",
        "read_aloud_blocks"
    )
    if ra == 0:
        failures.append("CRITICAL: No READ ALOUD blocks — players have no atmospheric immersion text")
    elif ra < 4:
        failures.append(f"LOW: Only {ra} READ ALOUD block(s) — need ≥4 for a 3-scene module")

    # Numbered area headers — accept "N - Name", "N – Name", or area-header HTML class.
    # Defense modules use "Wave N —" and "Defensive Position" headers instead of numbered areas.
    areas = count(
        r"(?:^|\n)\s*\d+\s*[-–]\s+[A-Z]|class=['\"]area-header|Wave \d+\s*[-–]|Defensive Position",
        "numbered_areas",
        re.IGNORECASE | re.MULTILINE,
    )
    scene_headers = count(r"(?:^|\n)\s*Scene\s+\d+\s*[:\-]", "scene_header_format", re.MULTILINE)
    if areas == 0:
        if scene_headers > 0:
            failures.append(
                f"CRITICAL: Module used 'Scene N:' format ({scene_headers} instances) instead of "
                f"'N - Location Name' — DMs cannot scan locations at the table. "
                f"Fix: BookToModuleAgent must output '1 - THE RUINED MARKET', not 'Scene 1: The Ruined Market'"
            )
        else:
            failures.append("CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable")

    # GM/DM NOTE boxes
    notes = count(r"GM\s*/?\s*DM\s+Only|GM NOTE|DM NOTE|class=['\"]gm-note", "gm_notes")
    if notes == 0:
        failures.append("MISSING: No GM NOTE boxes — DMs have no private guidance during scenes")
    elif notes < 3:
        failures.append(f"LOW: Only {notes} GM NOTE(s) — need ≥3 for a 3-scene module")

    # Conversation branches — require BOTH "If players" AND follow-up depth
    branches_broad = count(r"If players ask|If the party|On a success|DC \d+", "skill_checks_and_branches")
    branches_npc   = count(r"If players ask|If they ask|If the party ask", "conversation_branches_strict")
    if branches_broad < 5:
        failures.append(f"LOW: Only {branches_broad} skill check/conversation branch(es) — need ≥5 (min 2 per NPC)")
    if branches_npc < 3:
        failures.append(
            f"LOW: Only {branches_npc} 'If players ask' conversation branch(es) — "
            f"NPCs need ≥2 branches each. DMs cannot improvise social encounters without them."
        )

    # Stat blocks (AC / HP markers) — also check for appendix placement (violation)
    stat_blocks = count(r"Armor Class|Hit Points|AC \d+|HP \d+", "stat_blocks")
    if stat_blocks == 0:
        failures.append("CRITICAL: No stat blocks — enemies cannot be run in combat")
    # Check if stat blocks are buried in appendix (WotC violation — must be inline)
    appendix_stats = len(re.findall(
        r"(?:Appendix|Stat Block Appendix|Reference).*?(?:AC \d+|HP \d+|Armor Class)",
        module_text, re.IGNORECASE | re.DOTALL
    ))
    if appendix_stats > 0:
        failures.append(
            f"CRITICAL: {appendix_stats} stat block(s) placed in appendix — "
            f"must be INLINE immediately after NPC/monster introduction in the scene"
        )

    # Failure consequences — every DC needs a "On a failure" / "if they fail" clause
    dc_count    = len(re.findall(r"DC \d+", module_text, re.IGNORECASE))
    fail_clause = len(re.findall(r"On a failure|On failure|If they fail|failed check|miss the DC", module_text, re.IGNORECASE))
    checks["skill_dc_count"]      = dc_count
    checks["failure_consequences"] = fail_clause
    if dc_count > 0 and fail_clause == 0:
        failures.append(
            f"LOW: {dc_count} skill check DC(s) but NO failure consequences specified — "
            f"every DC must say what happens when players fail"
        )
    elif dc_count > 0 and fail_clause < dc_count // 2:
        failures.append(
            f"LOW: {dc_count} DC(s) but only {fail_clause} failure consequence(s) — "
            f"most skill checks leave DMs guessing what failure means"
        )

    # Transitions — also check for weak "party proceeds" transitions
    transitions = count(r"TRANSITION|class=['\"]transition|Proceed to|➡", "transitions")
    weak_trans  = len(re.findall(r"the party (?:proceeds|moves|heads|continues) to", module_text, re.IGNORECASE))
    if transitions < 2:
        failures.append(f"LOW: Only {transitions} transition(s) — scenes don't lead into each other")
    if weak_trans > 0:
        failures.append(
            f"LOW: {weak_trans} weak transition(s) using 'the party proceeds/moves' — "
            f"transitions must PULL players with a mystery or threat, not just move them"
        )

    # Three-clue rule — verify independent paths
    clues = count(r"[Cc]lue [ABC\d]|[Rr]eveals|[Dd]iscovers|DC \d+ (?:Investigation|Perception|Insight)", "clue_indicators")
    labeled_clues = count(r"Clue [ABC123]:", "labeled_clues")
    if clues < 3:
        failures.append(f"LOW: Only {clues} clue indicator(s) — three-clue rule requires 3 independent paths to each revelation")
    if labeled_clues == 0 and clues > 0:
        failures.append(
            "LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — "
            "DMs cannot track which paths players have used"
        )

    # NPC truth sheets — Wants/Knows/Hides per NPC
    npc_truth  = count(r"Wants:|Knows:|Hides:|Information:|motivation|secret", "npc_truth_elements")
    wants_cnt  = count(r"\bWants:", "npc_wants")
    knows_cnt  = count(r"\bKnows:", "npc_knows")
    hides_cnt  = count(r"\bHides:", "npc_hides")
    if npc_truth < 3:
        failures.append(f"LOW: Only {npc_truth} NPC truth element(s) — NPCs need explicit Wants/Knows/Hides")
    if wants_cnt == 0 or knows_cnt == 0 or hides_cnt == 0:
        failures.append(
            f"LOW: Missing NPC truth sheet structure — found Wants:{wants_cnt} Knows:{knows_cnt} Hides:{hides_cnt}. "
            f"Every NPC with dialogue must have all three."
        )

    # Battlefield descriptions for combat scenes
    battlefield = count(r"[Bb]attlefield|[Cc]over|[Hh]azard|[Ee]levation|[Ll]ighting condition", "battlefield_elements")
    if stat_blocks > 0 and battlefield == 0:
        failures.append(
            "LOW: Has combat encounters (stat blocks found) but no battlefield description — "
            "DMs need terrain, cover, hazards, and lighting for each combat scene"
        )

    # Read-aloud action hooks — good read-aloud ends with something demanding player response
    ra_texts = re.findall(
        r"(?:Read Aloud|Read this|READ ALOUD)[^\n]*\n(.*?)(?=\n\n|\Z)",
        module_text, re.IGNORECASE | re.DOTALL
    )
    passive_ra = sum(
        1 for t in ra_texts
        if not any(w in t.lower() for w in [
            "looks at you", "reaches", "draws", "steps forward", "notices you",
            "raises", "shouts", "moves", "attacks", "blocks your path",
            "speak to", "asks", "demands", "says"
        ])
    )
    checks["read_aloud_with_action_hook"] = len(ra_texts) - passive_ra
    if ra_texts and passive_ra == len(ra_texts):
        failures.append(
            "LOW: All read-aloud blocks are purely atmospheric — "
            "good read-aloud ends with an action or NPC demand that players must respond to"
        )

    checks["failures"]  = failures
    checks["fail_count"] = len(failures)
    checks["critical_count"] = sum(1 for f in failures if f.startswith("CRITICAL"))
    return checks


# ── Quality Comparison ─────────────────────────────────────────────────

async def _compare_to_reference(
    test_content: str,
    reference_excerpts: str,
) -> Dict[str, Any]:
    """
    Compare test mission content against reference material.
    
    Returns quality assessment with scores and gaps.
    """
    prompt = f"""You are a professional D&D module editor. Evaluate this GENERATED module against published professional standards.

═══ GENERATED MODULE (evaluate this) ═══
{test_content[:4000]}

═══ PROFESSIONAL REFERENCE (match this quality) ═══
{reference_excerpts[:3000]}

═══ QUALITY CRITERIA — score each 1-10 ═══

1. READ_ALOUD_FORMAT: Does each scene open with a marked read-aloud block (2-4 sensory sentences, second person, ends with an action or NPC demand players must respond to)? Purely atmospheric blocks that don't demand player response score 5 max.
2. NUMBERED_AREAS: Are locations numbered "N - Area Name" format? "Scene N:" or "Area N:" are failures — only "N - Name" is correct.
3. CONVERSATION_BRANCHES: Does each NPC have ≥2 "If players ask about X" branches? Is there explicit handling for what happens if players ATTACK or DO NOTHING? Partial branches score 5 max.
4. INLINE_STAT_BLOCKS: Are stat blocks placed INLINE immediately after the NPC/monster appears? Any stat block in an appendix is an automatic 0.
5. GM_NOTES: DM-only callout boxes present? Do they include hidden motivations, timing triggers, and "what if players do X" contingencies?
6. THREE_CLUE_RULE: Every key revelation has three independent paths (different scenes OR different skills)? Clues stacked in the same scene fail.
7. FAILURE_CONSEQUENCES: Every skill check DC specifies what happens on failure? "DC 14 Persuasion" with no failure clause scores 3 max.
8. NPC_TRUTH_SHEETS: Every NPC with dialogue has explicit Wants/Knows/Hides? Missing any of the three scores 4 max.
9. TRANSITIONS: Each scene ends with a mystery or threat pulling players forward? "The party proceeds" is automatic 2.
10. PLAYABILITY: Could a DM pick this up cold and run it in 2-3 hours without extra prep?

═══ OUTPUT FORMAT — output EXACTLY this ═══

READ_ALOUD_FORMAT: [X/10] - [one sentence on what's missing or working]
NUMBERED_AREAS: [X/10] - [one sentence — if wrong format, say which format was used]
CONVERSATION_BRANCHES: [X/10] - [one sentence]
INLINE_STAT_BLOCKS: [X/10] - [one sentence]
GM_NOTES: [X/10] - [one sentence]
THREE_CLUE_RULE: [X/10] - [one sentence]
FAILURE_CONSEQUENCES: [X/10] - [one sentence]
NPC_TRUTH_SHEETS: [X/10] - [one sentence]
TRANSITIONS: [X/10] - [one sentence]
PLAYABILITY: [X/10] - [one sentence]

OVERALL_SCORE: [X/10]

TOP 3 GAPS (most important fixes — cite the EXACT text that fails):
1. [gap description + the exact line that fails]
2. [gap description + the exact line that fails]
3. [gap description + the exact line that fails]

PROMPT PATCH SUGGESTIONS (add these exact sentences to the module generation prompt):
1. [the exact sentence to add to the prompt — in quotes]
2. [the exact sentence to add to the prompt — in quotes]
3. [the exact sentence to add to the prompt — in quotes]"""

    system = """You are an expert D&D module critic. Be specific and constructive.
Point to exact problems in the generated content. Suggest concrete fixes.
Your goal is to help the generation system improve iteratively."""

    response = await _ask_ollama(prompt, system=system, timeout=300)
    
    # Parse the response
    result = {
        "raw_response": response,
        "scores": {},
        "overall_score": 5,
        "gaps": [],
        "patches": [],
        "timestamp": datetime.now().isoformat(),
    }
    
    if response:
        # Extract scores
        import re
        score_pattern = r"(\w+):\s*\[?(\d+)/10\]?"
        for match in re.finditer(score_pattern, response):
            criterion = match.group(1).lower()
            score = int(match.group(2))
            result["scores"][criterion] = score
        
        # Extract overall score
        overall_match = re.search(r"OVERALL_SCORE:\s*\[?(\d+)/10\]?", response)
        if overall_match:
            result["overall_score"] = int(overall_match.group(1))
        
        # Extract gaps
        gaps_section = re.search(r"TOP 3 GAPS.*?(?=PROMPT PATCH|$)", response, re.DOTALL)
        if gaps_section:
            gap_matches = re.findall(r"\d+\.\s*(.+?)(?=\d+\.|PROMPT|$)", gaps_section.group(0), re.DOTALL)
            result["gaps"] = [g.strip() for g in gap_matches[:3] if g.strip()]
        
        # Extract patches
        patches_section = re.search(r"PROMPT PATCH SUGGESTIONS.*", response, re.DOTALL)
        if patches_section:
            patch_matches = re.findall(r"\d+\.\s*(.+?)(?=\d+\.|$)", patches_section.group(0), re.DOTALL)
            result["patches"] = [p.strip() for p in patch_matches[:3] if p.strip()]
    
    return result


# ── Patch Generation and Storage ───────────────────────────────────────

def _save_patches(patches: List[str], comparison: Dict[str, Any], mission_title: str):
    """
    Save prompt patches to PATCHES.md for DM review.
    
    Patches are NOT auto-applied — they require DM approval.
    """
    if not patches:
        return
    
    _ensure_directories()
    
    # Ensure patches file exists
    PATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Read existing content
    existing = ""
    if PATCHES_FILE.exists():
        try:
            existing = PATCHES_FILE.read_text(encoding="utf-8")
        except Exception:
            pass
    
    # Format new patches
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    overall_score = comparison.get("overall_score", "?")
    gaps = comparison.get("gaps", [])
    
    new_section = f"""
---

## Patches from {timestamp}

**Test Mission:** {mission_title}
**Quality Score:** {overall_score}/10

**Gaps Identified:**
{chr(10).join(f'- {g}' for g in gaps)}

**Proposed Prompt Patches (PENDING DM APPROVAL):**

"""
    
    for i, patch in enumerate(patches, 1):
        new_section += f"""### Patch {i}

```
{patch}
```

**Status:** ⏳ PENDING

"""
    
    # Append to file
    try:
        with open(PATCHES_FILE, "a", encoding="utf-8") as f:
            if not existing:
                f.write("""# Module Quality Prompt Patches

This file contains proposed prompt improvements generated by the self-learning system.

**DM ACTION REQUIRED:** Review each patch and mark as:
- ✅ APPROVED — Apply to production prompts
- ❌ REJECTED — Do not apply (explain why)
- 🔄 MODIFIED — Apply with changes (show modified version)

Patches are generated by comparing test missions against professional module excerpts.
""")
            f.write(new_section)
        
        logger.info(f"📝 Saved {len(patches)} prompt patches to {PATCHES_FILE.name}")
        
    except Exception as e:
        logger.error(f"Failed to save patches: {e}")


def _save_quality_journal(entry: Dict[str, Any]):
    """Append an entry to the quality learning journal."""
    _ensure_directories()
    
    try:
        with open(QUALITY_JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Failed to write quality journal: {e}")


def _save_test_module(mission: Dict[str, Any]):
    """Save the test module to the learning directory for inspection."""
    _ensure_directories()
    
    title = mission.get("metadata", {}).get("title", "test_mission")
    slug = "".join(c if c.isalnum() else "_" for c in title.lower())[:30]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"{slug}_{timestamp}.json"
    
    try:
        filepath = TEST_MODULES_DIR / filename
        filepath.write_text(json.dumps(mission, indent=2), encoding="utf-8")
        logger.info(f"📄 Saved test module: {filename}")
        return filepath
    except Exception as e:
        logger.error(f"Failed to save test module: {e}")
        return None


def _update_quality_skill_file(
    title: str,
    score: int,
    struct: Dict[str, Any],
    gaps: List[str],
) -> None:
    """
    Append a self-evaluation summary to campaign_docs/skills/module_quality.md.
    This gives the bot a running record of what format elements it keeps missing,
    which it can read during the next session's module generation.
    """
    skill_file = SKILLS_DIR / "module_quality.md"
    if not skill_file.exists():
        return  # Don't create — only append to existing

    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        failures = struct.get("failures", [])
        block = f"""

---

## Self-Evaluation — {ts}

**Module evaluated:** {title}
**LLM quality score:** {score}/10

**Structural counts (from real output):**
- READ ALOUD blocks: {struct.get('read_aloud_blocks', 0)} (need ≥4 per 5-scene module)
- Numbered areas (N - Name): {struct.get('numbered_areas', 0)} (need ≥4)
- Inline stat blocks: {struct.get('stat_blocks', 0)} (need ≥1 per combat scene)
- Skill checks / branches: {struct.get('skill_checks_and_branches', 0)} (need ≥5)
- GM NOTE boxes: {struct.get('gm_notes', 0)} (need ≥3)
- Transitions: {struct.get('transitions', 0)} (need ≥4)

**Format failures this run:**
{chr(10).join(f'- {f}' for f in failures) if failures else '- None detected'}

**Content gaps (LLM critique):**
{chr(10).join(f'- {g}' for g in gaps) if gaps else '- None identified'}
"""
        with open(skill_file, "a", encoding="utf-8") as f:
            f.write(block)
        logger.info(f"🎓 Updated module_quality.md with self-evaluation for: {title}")
    except Exception as e:
        logger.warning(f"🎓 Could not update quality skill file: {e}")


# ── Main Training Function ─────────────────────────────────────────────

async def study_module_quality() -> Optional[str]:
    """
    Main entry point for module quality self-learning.
    
    This function:
    1. Generates a test mission in sandbox mode
    2. Loads reference material from extracted PDFs
    3. Compares the test output to professional quality
    4. Identifies gaps and generates prompt patches
    5. Saves everything for DM review
    
    Returns a skill summary or None if learning failed.
    """
    logger.info("🎓 Starting module quality training session...")
    _ensure_directories()
    
    # Wait for Ollama to be available (max 5 minutes)
    wait_attempts = 0
    while not is_available() and wait_attempts < 10:
        reason = get_busy_reason()
        logger.info(f"🎓 Ollama busy ({reason}), waiting 30s...")
        await asyncio.sleep(30)
        wait_attempts += 1
    
    if not is_available():
        logger.warning("🎓 Ollama still busy after 5 minutes, skipping module quality training")
        return None
    
    # Mark Ollama as busy for this long-running task
    mark_busy("module quality training", "qwen3")
    
    try:
        # Step 1: Load the most recent real module (evaluate what was actually produced)
        logger.info("🎓 Step 1: Loading most recent real module for evaluation...")
        real_module = _load_latest_real_module()

        if real_module:
            title, full_content = real_module
            mission_meta = {"title": title, "mission_type": "real_module", "faction": "unknown"}
            logger.info(f"🎓 Evaluating real module: {title} ({len(full_content)} chars)")
        else:
            # Fallback: generate a test mission if no real module exists yet
            logger.info("🎓 No real module found — generating test mission (sandbox mode)...")
            try:
                test_mission = await _generate_test_mission()
            except Exception as e:
                logger.error(f"Test mission generation failed: {e}")
                return None
            title = test_mission.get("metadata", {}).get("title", "Unknown")
            mission_meta = test_mission.get("metadata", {})
            logger.info(f"🎓 Generated test mission: {title}")
            _save_test_module(test_mission)
            sections = test_mission.get("sections", {})
            full_content = "\n\n".join(
                f"## {name.upper()}\n{content}"
                for name, content in sections.items()
            )

        if len(full_content) < 500:
            logger.warning("🎓 Module content too short, skipping comparison")
            return None

        # Step 1b: Run structural check FIRST (fast, no LLM needed)
        logger.info("🎓 Step 1b: Running structural format check...")
        struct = _structural_check(full_content)

        # Summary line
        logger.info(
            f"🎓 Structural check: read_aloud={struct.get('read_aloud_blocks',0)} "
            f"areas={struct.get('numbered_areas',0)} "
            f"stat_blocks={struct.get('stat_blocks',0)} "
            f"branches={struct.get('skill_checks_and_branches',0)} "
            f"gm_notes={struct.get('gm_notes',0)} "
            f"transitions={struct.get('transitions',0)} "
            f"wants/knows/hides={struct.get('npc_wants',0)}/{struct.get('npc_knows',0)}/{struct.get('npc_hides',0)} "
            f"failure_consequences={struct.get('failure_consequences',0)}/{struct.get('skill_dc_count',0)} DCs "
            f"| CRITICAL={struct.get('critical_count',0)} TOTAL_FAILS={struct.get('fail_count',0)}"
        )

        # Surface critical failures prominently
        criticals = [f for f in struct.get("failures", []) if f.startswith("CRITICAL")]
        lows      = [f for f in struct.get("failures", []) if not f.startswith("CRITICAL")]
        if criticals:
            logger.error(f"🎓 CRITICAL FORMAT FAILURES ({len(criticals)}):")
            for f in criticals:
                logger.error(f"🎓   [CRITICAL] {f}")
        for f in lows:
            logger.warning(f"🎓   [CHECK] {f}")
        
        # Step 2: Load reference material
        logger.info("🎓 Step 2: Loading reference material from training PDFs...")
        reference_excerpts = _load_training_excerpts(max_chars=8000)
        
        if len(reference_excerpts) < 500:
            logger.warning("🎓 Not enough reference material, skipping comparison")
            return None
        
        logger.info(f"🎓 Loaded {len(reference_excerpts)} chars of reference material")
        
        # Step 3: Compare to reference
        logger.info("🎓 Step 3: Comparing test output to reference quality...")
        try:
            comparison = await _compare_to_reference(full_content, reference_excerpts)
        except Exception as e:
            logger.error(f"Quality comparison failed: {e}")
            return None
        
        overall_score = comparison.get("overall_score", 5)
        gaps = comparison.get("gaps", [])
        patches = comparison.get("patches", [])
        
        logger.info(f"🎓 Quality score: {overall_score}/10, Gaps: {len(gaps)}, Patches: {len(patches)}")
        
        # Step 4: Save patches for DM review
        if patches:
            logger.info("🎓 Step 4: Saving prompt patches for DM review...")
            _save_patches(patches, comparison, title)
        
        # Step 5: Log to quality journal
        journal_entry = {
            "timestamp": datetime.now().isoformat(),
            "module_title": title,
            "overall_score": overall_score,
            "scores": comparison.get("scores", {}),
            "gaps": gaps,
            "structural_check": {k: v for k, v in struct.items() if k != "failures"},
            "structural_failures": struct.get("failures", []),
            "patches_generated": len(patches),
            "content_length": len(full_content),
        }
        _save_quality_journal(journal_entry)

        # Auto-update module_quality.md with structural failure counts
        # so the bot knows which format elements it's still missing
        _update_quality_skill_file(title, overall_score, struct, gaps)
        
        # Step 6: Generate skill summary
        skill_content = f"""# Skill: Module Quality Training Report
**Keywords:** module, quality, training, learning, improvement
**Category:** learned
**Version:** 1
**Source:** self-learned

## Latest Training Session: {datetime.now().strftime("%Y-%m-%d %H:%M")}

### Test Mission
**Title:** {title}
**Type:** {mission_meta.get("mission_type", "?")}
**Faction:** {mission_meta.get("faction", "?")}

### Quality Assessment
**Overall Score:** {overall_score}/10

**Criterion Scores:**
{chr(10).join(f"- {k}: {v}/10" for k, v in comparison.get("scores", {}).items())}

### Gaps Identified
{chr(10).join(f"- {g}" for g in gaps) if gaps else "- No major gaps identified"}

### Patches Generated
{len(patches)} prompt patches saved to `logs/learning/module_quality_patches.md` for DM review.

### Trend
This session contributes to the ongoing quality improvement of mission module generation.
Review the quality_journal.jsonl for historical trends.
"""
        
        logger.info(f"🎓 Module quality training complete. Score: {overall_score}/10")
        
        return skill_content
    
    finally:
        # Always mark Ollama as available when done
        mark_available()


# ── Integration with Self-Learning Loop ────────────────────────────────

# This function should be called from self_learning.py's run_learning_session()
# Add to the studies list:
#   ("module_quality_training", study_module_quality, "module_quality_report"),
