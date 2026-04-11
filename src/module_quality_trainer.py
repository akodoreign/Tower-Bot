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
TRAINING_PDFS_DIR = CAMPAIGN_DOCS / "TrainingPDFS" / "extracted"
SKILLS_DIR = PROJECT_ROOT / "skills"
PATCHES_FILE = SKILLS_DIR / "module-quality" / "PATCHES.md"

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
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
    Load excerpts from training docs in MySQL (falls back to extracted txt files).
    Returns concatenated excerpts from the best training modules.
    """
    good_names = {
        "Can_We_Keep_Him.txt",
        "2722702-Respect_your_elderly.txt",
        "Oni Mother .txt",
        "Original Adventures Reincarnated #5 - Castle Amber.txt",
    }

    # Primary: MySQL
    try:
        from src.db_api import raw_query as _rq
        rows = _rq(
            "SELECT filename, content FROM training_docs WHERE doc_type = 'training_pdf' ORDER BY filename"
        ) or []
        excerpts = []
        total_chars = 0
        for row in rows:
            name = row.get("filename", "")
            if name not in good_names:
                continue
            text = row.get("content") or ""
            if not text:
                continue
            lines = text.split("\n")
            content_start = max(0, len(lines) // 10)
            content_end   = min(len(lines), len(lines) // 2)
            chunk = "\n".join(lines[content_start:content_end])
            remaining = max_chars - total_chars
            if remaining <= 0:
                break
            chunk = chunk[:remaining]
            excerpts.append(f"### {name}\n{chunk}")
            total_chars += len(chunk)
        if excerpts:
            return "\n\n---\n\n".join(excerpts)
    except Exception as e:
        logger.warning(f"_load_training_excerpts DB error: {e}")

    # Fallback: files
    if not TRAINING_PDFS_DIR.exists():
        return ""

    excerpts = []
    total_chars = 0
    for filename in sorted(good_names):
        pdf_path = TRAINING_PDFS_DIR / filename
        if not pdf_path.exists():
            continue
        try:
            text = pdf_path.read_text(encoding="utf-8")
            lines = text.split("\n")
            content_start = max(0, len(lines) // 10)
            content_end   = min(len(lines), len(lines) // 2)
            chunk = "\n".join(lines[content_start:content_end])
            remaining = max_chars - total_chars
            if remaining <= 0:
                break
            chunk = chunk[:remaining]
            excerpts.append(f"### {filename}\n{chunk}")
            total_chars += len(chunk)
        except Exception as e:
            logger.warning(f"Could not read training PDF {filename}: {e}")

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


# ── Quality Comparison ─────────────────────────────────────────────────

async def _compare_to_reference(
    test_content: str,
    reference_excerpts: str,
) -> Dict[str, Any]:
    """
    Compare test mission content against reference material.
    
    Returns quality assessment with scores and gaps.
    """
    prompt = f"""You are a D&D module quality critic. Compare this GENERATED mission content
against these REFERENCE excerpts from published professional modules.

═══ GENERATED CONTENT (test mission) ═══
{test_content[:4000]}

═══ REFERENCE MATERIAL (professional modules) ═══
{reference_excerpts[:4000]}

═══ QUALITY CRITERIA ═══
1. SPECIFICITY: Does it use specific names, numbers, locations? (vs generic "a warehouse")
2. SENSORY DETAIL: Are scenes grounded in sight/sound/smell/texture?
3. NPC QUALITY: Do NPCs have appearance, voice, motivation, secrets?
4. ENCOUNTER DESIGN: Do encounters have setup, terrain, morale, loot?
5. READ-ALOUD TEXT: Is there evocative present-tense player-facing text?
6. ANTI-PATTERNS: Is it free of purple prose, hedging, echo chambers?
7. FORMAT: Does it follow professional module structure?
8. PLAYABILITY: Could a DM run this immediately at the table?

═══ OUTPUT FORMAT ═══
Score each criterion 1-10, then provide overall assessment:

SPECIFICITY: [X/10] - [brief explanation]
SENSORY_DETAIL: [X/10] - [brief explanation]
NPC_QUALITY: [X/10] - [brief explanation]
ENCOUNTER_DESIGN: [X/10] - [brief explanation]
READ_ALOUD: [X/10] - [brief explanation]
ANTI_PATTERNS: [X/10] - [brief explanation]
FORMAT: [X/10] - [brief explanation]
PLAYABILITY: [X/10] - [brief explanation]

OVERALL_SCORE: [X/10]

TOP 3 GAPS (most important improvements needed):
1. [specific gap with example from the content]
2. [specific gap with example from the content]
3. [specific gap with example from the content]

PROMPT PATCH SUGGESTIONS (specific wording to add to prompts):
1. [concrete prompt addition that would fix gap 1]
2. [concrete prompt addition that would fix gap 2]
3. [concrete prompt addition that would fix gap 3]"""

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
        # Step 1: Generate a test mission
        logger.info("🎓 Step 1: Generating test mission (sandbox mode)...")
        try:
            test_mission = await _generate_test_mission()
        except Exception as e:
            logger.error(f"Test mission generation failed: {e}")
            return None
        
        title = test_mission.get("metadata", {}).get("title", "Unknown")
        logger.info(f"🎓 Generated test mission: {title}")
        
        # Save the test module
        _save_test_module(test_mission)
        
        # Combine all sections for comparison
        sections = test_mission.get("sections", {})
        full_content = "\n\n".join(
            f"## {name.upper()}\n{content}"
            for name, content in sections.items()
        )
        
        if len(full_content) < 500:
            logger.warning("🎓 Test mission content too short, skipping comparison")
            return None
        
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
            "mission_title": title,
            "mission_metadata": test_mission.get("metadata", {}),
            "overall_score": overall_score,
            "scores": comparison.get("scores", {}),
            "gaps": gaps,
            "patches_generated": len(patches),
            "content_length": len(full_content),
        }
        _save_quality_journal(journal_entry)
        
        # Step 6: Generate skill summary
        skill_content = f"""# Skill: Module Quality Training Report
**Keywords:** module, quality, training, learning, improvement
**Category:** learned
**Version:** 1
**Source:** self-learned

## Latest Training Session: {datetime.now().strftime("%Y-%m-%d %H:%M")}

### Test Mission
**Title:** {title}
**Type:** {test_mission.get("metadata", {}).get("mission_type", "?")}
**Faction:** {test_mission.get("metadata", {}).get("faction", "?")}

### Quality Assessment
**Overall Score:** {overall_score}/10

**Criterion Scores:**
{chr(10).join(f"- {k}: {v}/10" for k, v in comparison.get("scores", {}).items())}

### Gaps Identified
{chr(10).join(f"- {g}" for g in gaps) if gaps else "- No major gaps identified"}

### Patches Generated
{len(patches)} prompt patches saved to `skills/module-quality/PATCHES.md` for DM review.

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
