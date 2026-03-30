"""Skill Loader — reads markdown skill files and matches them to queries.

Each skill file in campaign_docs/skills/ has a YAML-like header with:
  - **Keywords:** comma-separated relevance keywords
  - **Category:** lore | systems | rules | persona | style | learned
  - **Version:** integer version number
  - **Source:** seed | self-learned | dm-edited

The loader scores each skill against the user's message using keyword
overlap and returns the top-N most relevant skill bodies to inject into
the system prompt.
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from src.log import logger

# ── Paths ──────────────────────────────────────────────────────────────

SKILLS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs" / "skills"

# ── Data model ─────────────────────────────────────────────────────────

@dataclass
class Skill:
    """A single loaded skill with its metadata and body."""
    filename: str
    title: str          # first # heading
    keywords: List[str]
    category: str
    version: int
    source: str
    body: str           # full markdown content (including header for reference)

    # Computed at load time
    _keyword_set: set = field(default_factory=set, repr=False)

    def __post_init__(self):
        self._keyword_set = {k.strip().lower() for k in self.keywords if k.strip()}


# ── Cache ──────────────────────────────────────────────────────────────

_skills_cache: Optional[List[Skill]] = None
_cache_mtime: float = 0.0  # newest mtime when cache was built


def _needs_reload() -> bool:
    """Check if any skill file has been modified since last cache build."""
    global _cache_mtime
    if _skills_cache is None:
        return True
    if not SKILLS_DIR.exists():
        return False
    for p in SKILLS_DIR.glob("*.md"):
        if p.stat().st_mtime > _cache_mtime:
            return True
    return False


def _parse_skill(filepath: Path) -> Optional[Skill]:
    """Parse a single skill markdown file."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"skill_loader: cannot read {filepath.name}: {e}")
        return None

    # Extract header fields
    def _extract(pattern: str, default: str = "") -> str:
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    keywords_raw = _extract(r"\*\*Keywords?:\*\*\s*(.+)")
    category = _extract(r"\*\*Category:\*\*\s*(\S+)", "unknown")
    version_str = _extract(r"\*\*Version:\*\*\s*(\d+)", "1")
    source = _extract(r"\*\*Source:\*\*\s*(\S+)", "unknown")

    # Title from first heading
    title_match = re.search(r"^#\s+(?:Skill:\s*)?(.+)", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else filepath.stem

    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    return Skill(
        filename=filepath.name,
        title=title,
        keywords=keywords,
        category=category,
        version=int(version_str),
        source=source,
        body=text,
        _keyword_set=set(),
    )


def load_skills(force: bool = False) -> List[Skill]:
    """Load (or reload) all skill files from campaign_docs/skills/."""
    global _skills_cache, _cache_mtime

    if not force and not _needs_reload():
        return _skills_cache or []

    if not SKILLS_DIR.exists():
        logger.warning("skill_loader: skills directory does not exist")
        _skills_cache = []
        return []

    skills: List[Skill] = []
    newest_mtime = 0.0

    for filepath in sorted(SKILLS_DIR.glob("*.md")):
        skill = _parse_skill(filepath)
        if skill:
            skills.append(skill)
            mt = filepath.stat().st_mtime
            if mt > newest_mtime:
                newest_mtime = mt

    _skills_cache = skills
    _cache_mtime = newest_mtime
    logger.info(f"🧠 skill_loader: loaded {len(skills)} skills from {SKILLS_DIR}")
    return skills


# ── Matching ───────────────────────────────────────────────────────────

def _tokenize(text: str) -> set:
    """Simple tokenizer: lowercase alphanumeric words."""
    return set(re.findall(r"\w+", text.lower()))


def score_skill(skill: Skill, query_tokens: set) -> float:
    """
    Score a skill's relevance to a set of query tokens.

    Scoring:
    - Each keyword match = 2.0 points
    - Each keyword that partially matches (substring) = 0.5 points
    - Category bonus: if a query token matches the category name = 1.0
    """
    score = 0.0

    for kw in skill._keyword_set:
        if kw in query_tokens:
            score += 2.0
        else:
            # Check partial matches (e.g., "faction" in "factions")
            for qt in query_tokens:
                if kw in qt or qt in kw:
                    score += 0.5
                    break

    # Category bonus
    if skill.category.lower() in query_tokens:
        score += 1.0

    return score


def match_skills(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    top_n: int = 3,
    min_score: float = 1.0,
) -> List[Skill]:
    """
    Match the most relevant skills to the user's message + recent history.

    Args:
        user_message: The current user message.
        conversation_history: Optional recent conversation for broader context.
        top_n: Maximum number of skills to return.
        min_score: Minimum relevance score to include a skill.

    Returns:
        List of matched Skill objects, ordered by relevance (highest first).
    """
    skills = load_skills()
    if not skills:
        return []

    # Build token set from user message + last 3 conversation messages
    query_text = user_message
    if conversation_history:
        recent = conversation_history[-6:]  # last 3 exchanges (user+assistant)
        for msg in recent:
            if msg.get("role") == "user":
                query_text += " " + msg.get("content", "")

    query_tokens = _tokenize(query_text)

    # Score each skill
    scored: List[Tuple[float, Skill]] = []
    for skill in skills:
        s = score_skill(skill, query_tokens)
        if s >= min_score:
            scored.append((s, skill))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    return [skill for _, skill in scored[:top_n]]


def format_skills_for_prompt(skills: List[Skill], max_chars: int = 4000) -> str:
    """
    Format matched skills into a single block for injection into the system prompt.

    Truncates if the total exceeds max_chars to avoid blowing up context.
    """
    if not skills:
        return ""

    parts = ["[TOWER SKILLS — Relevant Knowledge]"]
    total = len(parts[0])

    for skill in skills:
        block = f"\n\n--- {skill.title} (v{skill.version}) ---\n{skill.body}"
        if total + len(block) > max_chars:
            # Truncate this skill's body to fit
            remaining = max_chars - total - 50
            if remaining > 200:
                parts.append(f"\n\n--- {skill.title} (v{skill.version}) [truncated] ---\n{skill.body[:remaining]}...")
            break
        parts.append(block)
        total += len(block)

    return "\n".join(parts)


# ── Inventory ──────────────────────────────────────────────────────────

def get_skill_inventory() -> List[Dict]:
    """Return a summary of all loaded skills for /skills command."""
    skills = load_skills()
    return [
        {
            "title": s.title,
            "filename": s.filename,
            "category": s.category,
            "version": s.version,
            "source": s.source,
            "keywords": s.keywords[:8],  # cap for display
        }
        for s in skills
    ]


def get_skill_body(filename: str) -> Optional[str]:
    """Return the full body of a skill by filename."""
    skills = load_skills()
    for s in skills:
        if s.filename == filename:
            return s.body
    return None
